"""Security-conscious Gemini image client used by the ComfyUI nodes.

The public node interfaces remain compatible with the original plugin. By
default, requests go only to Google's official Gemini API over HTTPS. Using a
third-party endpoint is still supported, but requires explicit process-level
opt-in and a hostname allowlist so an untrusted config file cannot silently
redirect user images or credentials.
"""

from __future__ import annotations

import base64
import binascii
import io
import ipaddress
import json
import os
import re
import string
import time
import warnings
from pathlib import Path
from typing import Any, Iterable, List, Mapping, MutableMapping, Optional
from urllib.parse import quote, urlparse

import requests
from PIL import Image, UnidentifiedImageError


DEFAULT_API_BASE_URL = "https://generativelanguage.googleapis.com"
DEFAULT_MODEL = "gemini-3.1-flash-image"
DEFAULT_API_VERSION = "v1"
OFFICIAL_HOSTS = frozenset({"generativelanguage.googleapis.com"})

_CONFIG_FILENAME = "gemini_config.json"
_LEGACY_KEY_FILENAME = "gemini_api_key.txt"
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_QUERY_NAME_RE = re.compile(r"^[A-Za-z0-9._~-]{1,128}$")
_DENIED_HEADERS = frozenset(
    {
        "accept",
        "connection",
        "content-length",
        "content-type",
        "cookie",
        "host",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "user-agent",
    }
)
_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})


class GeminiAPIError(RuntimeError):
    """Safe, user-facing error raised for Gemini request failures."""


def _plugin_dir() -> Path:
    return Path(__file__).resolve().parent


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUTHY:
        return True
    if normalized in _FALSY:
        return False
    raise GeminiAPIError(
        f"Environment variable {name} must be one of: 1/0, true/false, yes/no, on/off."
    )


def _bounded_int(value: Any, *, name: str, default: int, minimum: int, maximum: int) -> int:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise GeminiAPIError(f"{name} must be an integer.") from exc
    if not minimum <= number <= maximum:
        raise GeminiAPIError(f"{name} must be between {minimum} and {maximum}.")
    return number


def _setting_int(
    env_name: str,
    config: Mapping[str, Any],
    config_name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.environ.get(env_name)
    if raw is None:
        raw = config.get(config_name)
    return _bounded_int(
        raw,
        name=env_name,
        default=default,
        minimum=minimum,
        maximum=maximum,
    )


def _load_config() -> dict[str, Any]:
    """Load the local, Git-ignored config and fail closed if it is malformed."""

    path = _plugin_dir() / _CONFIG_FILENAME
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise GeminiAPIError(f"{_CONFIG_FILENAME} must be a regular, non-symlink file.")
    if path.stat().st_size > 64 * 1024:
        raise GeminiAPIError(f"{_CONFIG_FILENAME} exceeds the 64 KiB limit.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GeminiAPIError(f"Failed to read {_CONFIG_FILENAME}: {exc}") from exc
    if not isinstance(data, dict):
        raise GeminiAPIError(f"{_CONFIG_FILENAME} must contain a JSON object.")
    return data


def _clean_secret(value: Any) -> str:
    if value is None:
        return ""
    secret = str(value).strip()
    if "\r" in secret or "\n" in secret:
        raise GeminiAPIError("API key must not contain newline characters.")
    if len(secret) > 4096:
        raise GeminiAPIError("API key is unexpectedly long.")
    return secret


def _get_api_key(config: Optional[Mapping[str, Any]] = None) -> str:
    key = _clean_secret(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))
    if key:
        return key

    cfg = dict(config or _load_config())
    key = _clean_secret(cfg.get("api_key"))
    if key:
        return key

    # Backward-compatible local file. It is excluded from Git by .gitignore.
    key_file = _plugin_dir() / _LEGACY_KEY_FILENAME
    if key_file.exists():
        if key_file.is_symlink() or not key_file.is_file() or key_file.stat().st_size > 16 * 1024:
            raise GeminiAPIError(f"{_LEGACY_KEY_FILENAME} is not a valid key file.")
        try:
            key = _clean_secret(key_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            raise GeminiAPIError(f"Failed to read {_LEGACY_KEY_FILENAME}: {exc}") from exc
        if key:
            return key

    raise GeminiAPIError(
        "Gemini API key not found. Set GOOGLE_API_KEY (recommended), GEMINI_API_KEY, "
        f"or create an untracked {_CONFIG_FILENAME} from gemini_config.example.json."
    )


def _resolve_model(requested_model: Optional[str], config: Mapping[str, Any]) -> str:
    model = (
        os.environ.get("GEMINI_IMAGE_MODEL")
        or os.environ.get("GEMINI_MODEL")
        or config.get("model")
        or requested_model
        or DEFAULT_MODEL
    )
    model = str(model).strip()
    if not _MODEL_RE.fullmatch(model):
        raise GeminiAPIError(
            "Invalid Gemini model name. Use only letters, numbers, dots, underscores, and hyphens."
        )
    return model


def get_default_image_model() -> str:
    """Return the configured image model without making a network request."""

    return _resolve_model(None, _load_config())


def _resolve_api_mode(config: Mapping[str, Any]) -> str:
    mode = str(os.environ.get("GEMINI_API_MODE") or config.get("api_mode") or "generate_content")
    mode = mode.strip().lower().replace("-", "_")
    if mode not in {"generate_content", "legacy_proxy"}:
        raise GeminiAPIError("GEMINI_API_MODE must be 'generate_content' or 'legacy_proxy'.")
    return mode


def _format_endpoint(template: str, model: str) -> str:
    safe_model = quote(model, safe="._-")
    try:
        fields = list(string.Formatter().parse(str(template)))
    except ValueError as exc:
        raise GeminiAPIError("Endpoint template is invalid.") from exc
    for _, field_name, format_spec, conversion in fields:
        if field_name is None:
            continue
        if field_name != "model" or format_spec or conversion:
            raise GeminiAPIError(
                "Endpoint template may contain only the literal {model} replacement field."
            )
    try:
        rendered = str(template).format(model=safe_model)
    except (KeyError, IndexError, ValueError) as exc:
        raise GeminiAPIError("Endpoint template is invalid.") from exc
    return rendered.strip()


def _configured_endpoint(model: str, config: Mapping[str, Any]) -> str:
    full_override = os.environ.get("GOOGLE_API_URL") or os.environ.get("GEMINI_API_URL")
    if full_override:
        return _format_endpoint(full_override, model)

    endpoint_template = config.get("endpoint_template") or config.get("endpoint") or config.get("full_url")
    if endpoint_template:
        return _format_endpoint(str(endpoint_template), model)

    base = (
        os.environ.get("GOOGLE_API_BASE_URL")
        or os.environ.get("GEMINI_API_BASE_URL")
        or config.get("base_url")
        or DEFAULT_API_BASE_URL
    )
    base = str(base).strip().rstrip("/")
    api_version = str(
        os.environ.get("GEMINI_API_VERSION") or config.get("api_version") or DEFAULT_API_VERSION
    ).strip()
    if api_version not in {"v1", "v1beta"}:
        raise GeminiAPIError("GEMINI_API_VERSION must be 'v1' or 'v1beta'.")
    return f"{base}/{api_version}/models/{quote(model, safe='._-')}:generateContent"


def _allowed_custom_hosts() -> set[str]:
    raw = os.environ.get("GEMINI_ALLOWED_HOSTS", "")
    return {item.strip().lower().rstrip(".") for item in raw.split(",") if item.strip()}


def _validate_endpoint(url: str) -> tuple[str, bool]:
    if any(ord(char) < 32 or ord(char) == 127 for char in url):
        raise GeminiAPIError("Gemini endpoint contains control characters.")
    if "\\" in url:
        raise GeminiAPIError("Gemini endpoint must not contain backslashes.")
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise GeminiAPIError("Gemini endpoint must use HTTPS.")
    if not parsed.hostname:
        raise GeminiAPIError("Gemini endpoint is missing a hostname.")
    if parsed.username or parsed.password:
        raise GeminiAPIError("Credentials must not be embedded in the endpoint URL.")
    if parsed.fragment:
        raise GeminiAPIError("Gemini endpoint must not contain a URL fragment.")

    host = parsed.hostname.lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError as exc:
        raise GeminiAPIError("Gemini endpoint contains an invalid port.") from exc
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise GeminiAPIError("Local Gemini endpoints are blocked.")
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None and not literal_ip.is_global:
        raise GeminiAPIError("Private, loopback, link-local, and reserved endpoint IPs are blocked.")

    official = host in OFFICIAL_HOSTS
    if official:
        if port not in {None, 443}:
            raise GeminiAPIError("The official Gemini endpoint may use only HTTPS port 443.")
        if parsed.query:
            raise GeminiAPIError("The official Gemini endpoint must not include URL query parameters.")
        if not re.fullmatch(r"/(?:v1|v1beta)/models/[A-Za-z0-9._-]+:generateContent", parsed.path):
            raise GeminiAPIError("The official Gemini endpoint path is not a generateContent path.")
    if not official:
        if not _env_bool("GEMINI_ALLOW_CUSTOM_ENDPOINT", default=False):
            raise GeminiAPIError(
                f"Custom endpoint '{host}' is blocked. Set GEMINI_ALLOW_CUSTOM_ENDPOINT=1 "
                "only after reviewing the provider, and add its hostname to GEMINI_ALLOWED_HOSTS."
            )
        if host not in _allowed_custom_hosts():
            raise GeminiAPIError(f"Custom endpoint '{host}' is not in GEMINI_ALLOWED_HOSTS.")
    return host, official


def _validate_header(name: Any, value: Any) -> tuple[str, str]:
    header_name = str(name).strip()
    header_value = str(value)
    if not _HEADER_NAME_RE.fullmatch(header_name):
        raise GeminiAPIError(f"Invalid HTTP header name: {header_name!r}.")
    if header_name.lower() in _DENIED_HEADERS:
        raise GeminiAPIError(f"HTTP header '{header_name}' cannot be overridden.")
    if "\r" in header_value or "\n" in header_value:
        raise GeminiAPIError(f"HTTP header '{header_name}' contains a newline.")
    if len(header_value) > 8192:
        raise GeminiAPIError(f"HTTP header '{header_name}' is unexpectedly long.")
    return header_name, header_value


def _format_auth_header_value(template: Any, api_key: str) -> str:
    """Render only the literal ``{api_key}`` field; reject traversal/specifiers."""

    raw = str(template)
    try:
        fields = list(string.Formatter().parse(raw))
    except ValueError as exc:
        raise GeminiAPIError("Authentication header template is invalid.") from exc
    for _, field_name, format_spec, conversion in fields:
        if field_name is None:
            continue
        if field_name != "api_key" or format_spec or conversion:
            raise GeminiAPIError(
                "Authentication header template may contain only the literal {api_key} field."
            )
    try:
        return raw.format(api_key=api_key)
    except (KeyError, IndexError, ValueError) as exc:
        raise GeminiAPIError("Authentication header template is invalid.") from exc


def _apply_auth(
    headers: MutableMapping[str, str],
    params: MutableMapping[str, str],
    api_key: str,
    config: Mapping[str, Any],
    *,
    official_endpoint: bool,
) -> None:
    # The official API has one unambiguous authentication path. Custom auth
    # configuration is accepted only after a custom hostname was explicitly trusted.
    if official_endpoint:
        headers["x-goog-api-key"] = api_key
        return

    extra_headers = config.get("extra_headers") or {}
    if not isinstance(extra_headers, dict):
        raise GeminiAPIError("extra_headers must be a JSON object.")
    if len(extra_headers) > 20:
        raise GeminiAPIError("extra_headers contains too many entries (limit: 20).")
    for name, value in extra_headers.items():
        clean_name, clean_value = _validate_header(name, value)
        if clean_name.lower() in {"authorization", "x-goog-api-key"}:
            raise GeminiAPIError(
                f"Put authentication in auth_header_name/value_template, not extra_headers ({clean_name})."
            )
        headers[clean_name] = clean_value

    header_name = os.environ.get("GEMINI_AUTH_HEADER_NAME") or config.get("auth_header_name")
    header_template = os.environ.get("GEMINI_AUTH_HEADER_VALUE") or config.get("auth_header_value_template")
    if header_name or header_template:
        if not (header_name and header_template):
            raise GeminiAPIError(
                "Both auth header name and auth header value template must be provided."
            )
        rendered = _format_auth_header_value(header_template, api_key)
        clean_name, clean_value = _validate_header(header_name, rendered)
        headers[clean_name] = clean_value
        return

    query_param = os.environ.get("GEMINI_QUERY_PARAM_NAME") or config.get("query_param_name")
    if query_param:
        query_name = str(query_param).strip()
        if not _QUERY_NAME_RE.fullmatch(query_name):
            raise GeminiAPIError("Invalid API-key query parameter name.")
        params[query_name] = api_key
        return

    headers["x-goog-api-key"] = api_key


def _limits(config: Mapping[str, Any]) -> dict[str, int]:
    return {
        "max_prompt_chars": _setting_int(
            "GEMINI_MAX_PROMPT_CHARS", config, "max_prompt_chars", 32_000, 1_000, 200_000
        ),
        "max_input_images": _setting_int(
            "GEMINI_MAX_INPUT_IMAGES", config, "max_input_images", 3, 1, 14
        ),
        "max_input_pixels": _setting_int(
            "GEMINI_MAX_INPUT_PIXELS", config, "max_input_pixels", 40_000_000, 1_000_000, 200_000_000
        ),
        "max_input_image_bytes": _setting_int(
            "GEMINI_MAX_INPUT_IMAGE_BYTES",
            config,
            "max_input_image_bytes",
            24 * 1024 * 1024,
            1 * 1024 * 1024,
            100 * 1024 * 1024,
        ),
        "max_request_bytes": _setting_int(
            "GEMINI_MAX_REQUEST_BYTES",
            config,
            "max_request_bytes",
            96 * 1024 * 1024,
            1 * 1024 * 1024,
            256 * 1024 * 1024,
        ),
        "max_response_bytes": _setting_int(
            "GEMINI_MAX_RESPONSE_BYTES",
            config,
            "max_response_bytes",
            80 * 1024 * 1024,
            1 * 1024 * 1024,
            256 * 1024 * 1024,
        ),
        "max_output_image_bytes": _setting_int(
            "GEMINI_MAX_OUTPUT_IMAGE_BYTES",
            config,
            "max_output_image_bytes",
            48 * 1024 * 1024,
            1 * 1024 * 1024,
            200 * 1024 * 1024,
        ),
        "max_output_pixels": _setting_int(
            "GEMINI_MAX_OUTPUT_PIXELS", config, "max_output_pixels", 40_000_000, 1_000_000, 200_000_000
        ),
    }


def _encode_image_to_base64(img: Image.Image, limits: Mapping[str, int]) -> dict[str, str]:
    from .utils.image_io import pil_to_png_bytes

    if not isinstance(img, Image.Image):
        raise GeminiAPIError("Every input image must be a PIL.Image.Image instance.")
    width, height = img.size
    if width <= 0 or height <= 0 or width * height > limits["max_input_pixels"]:
        raise GeminiAPIError(
            f"Input image is too large: {width}x{height}; pixel limit is {limits['max_input_pixels']:,}."
        )
    png_bytes = pil_to_png_bytes(img)
    if len(png_bytes) > limits["max_input_image_bytes"]:
        raise GeminiAPIError(
            f"Encoded input image is too large ({len(png_bytes):,} bytes; "
            f"limit {limits['max_input_image_bytes']:,})."
        )
    return {"mime_type": "image/png", "data": base64.b64encode(png_bytes).decode("ascii")}


def _validate_prompt_and_seed(prompt: str, seed: Optional[int], limits: Mapping[str, int]) -> tuple[str, Optional[int]]:
    clean_prompt = str(prompt)
    if not clean_prompt.strip():
        raise GeminiAPIError("Prompt must not be empty.")
    if len(clean_prompt) > limits["max_prompt_chars"]:
        raise GeminiAPIError(
            f"Prompt is too long ({len(clean_prompt):,} characters; "
            f"limit {limits['max_prompt_chars']:,})."
        )
    if seed is None:
        return clean_prompt, None
    try:
        seed_value = int(seed)
    except (TypeError, ValueError) as exc:
        raise GeminiAPIError("Seed must be an integer.") from exc
    if not 0 <= seed_value <= 2**31 - 1:
        raise GeminiAPIError("Seed must be between 0 and 2147483647.")
    return clean_prompt, seed_value


def _build_payload(
    prompt: str,
    images: List[Image.Image],
    *,
    seed: Optional[int],
    api_mode: str,
    limits: Mapping[str, int],
) -> dict[str, Any]:
    prompt, seed_value = _validate_prompt_and_seed(prompt, seed, limits)
    if not images:
        raise GeminiAPIError("At least one input image is required.")
    if len(images) > limits["max_input_images"]:
        raise GeminiAPIError(
            f"Too many input images ({len(images)}; limit {limits['max_input_images']})."
        )

    parts: list[dict[str, Any]] = [{"text": prompt}]
    parts.extend({"inline_data": _encode_image_to_base64(img, limits)} for img in images)

    if api_mode == "legacy_proxy":
        generation_config: dict[str, Any] = {"response_mime_type": "image/png"}
        if seed_value is not None:
            generation_config["seed"] = seed_value
            generation_config["random_seed"] = seed_value
        return {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation_config,
            "responseModalities": ["IMAGE", "TEXT"],
        }

    generation_config = {"responseModalities": ["IMAGE"]}
    if seed_value is not None:
        generation_config["seed"] = seed_value
    return {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": generation_config,
    }


def _decode_base64_image(value: Any, *, max_bytes: int) -> bytes:
    if not isinstance(value, str) or not value:
        raise GeminiAPIError("Gemini returned empty image data.")
    if len(value) > ((max_bytes + 2) // 3) * 4 + 16:
        raise GeminiAPIError("Gemini returned image data larger than the configured limit.")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GeminiAPIError("Gemini returned invalid base64 image data.") from exc
    if not decoded or len(decoded) > max_bytes:
        raise GeminiAPIError("Gemini returned an empty or oversized image.")
    return decoded


def _validate_output_image(data: bytes, *, max_pixels: int) -> bytes:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                image_format = image.format
                if width <= 0 or height <= 0 or width * height > max_pixels:
                    raise GeminiAPIError(
                        f"Gemini output image is too large: {width}x{height}; pixel limit is {max_pixels:,}."
                    )
                image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise GeminiAPIError("Gemini returned data that is not a safe, decodable image.") from exc
    if image_format not in {"PNG", "JPEG", "WEBP"}:
        raise GeminiAPIError(f"Gemini returned unsupported image format: {image_format or 'unknown'}.")
    return data


def _walk_json(
    value: Any, *, max_depth: int = 64, max_nodes: int = 100_000
) -> Iterable[Mapping[str, Any]]:
    """Iteratively walk bounded JSON so hostile nesting cannot exhaust recursion."""

    stack: list[tuple[Any, int]] = [(value, 0)]
    visited = 0
    while stack:
        current, depth = stack.pop()
        visited += 1
        if visited > max_nodes:
            raise GeminiAPIError("Gemini response contains too many JSON elements.")
        if depth > max_depth:
            raise GeminiAPIError("Gemini response JSON nesting is too deep.")
        if isinstance(current, Mapping):
            yield current
            # A thought part can contain inline image data. Do not descend into
            # it during legacy-shape fallback, or its nested blob would lose the
            # parent thought marker and be mistaken for a final image.
            if current.get("thought") is True:
                continue
            children = list(current.values())
            stack.extend((child, depth + 1) for child in reversed(children))
        elif isinstance(current, list):
            stack.extend((child, depth + 1) for child in reversed(current))


def _image_payload_from_object(obj: Mapping[str, Any]) -> Optional[Any]:
    """Return encoded image data from a non-thought response object."""

    if obj.get("thought") is True:
        return None
    inline = obj.get("inline_data") or obj.get("inlineData")
    if isinstance(inline, Mapping):
        mime = str(inline.get("mime_type") or inline.get("mimeType") or "")
        if mime.lower().startswith("image/") and inline.get("data"):
            return inline.get("data")

    obj_type = str(obj.get("type") or "").lower()
    mime = str(obj.get("mime_type") or obj.get("mimeType") or "")
    if (obj_type in {"image", "output_image"} or mime.lower().startswith("image/")) and obj.get("data"):
        return obj.get("data")
    return None


def _decode_selected_image(value: Any, limits: Mapping[str, int]) -> bytes:
    decoded = _decode_base64_image(value, max_bytes=limits["max_output_image_bytes"])
    return _validate_output_image(decoded, max_pixels=limits["max_output_pixels"])


def _extract_image_bytes_from_response(resp_json: Mapping[str, Any], limits: Mapping[str, int]) -> bytes:
    # Prefer the documented generateContent response path. Gemini 3 image
    # models can expose interim thought images; those must never be returned as
    # the final ComfyUI output. When more than one final image exists, use the
    # last one, matching the model's documented final-render ordering.
    official_payloads: list[Any] = []
    candidates = resp_json.get("candidates") or []
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            content = candidate.get("content")
            if not isinstance(content, Mapping):
                continue
            parts = content.get("parts") or []
            if not isinstance(parts, list):
                continue
            for part in parts:
                if isinstance(part, Mapping):
                    payload = _image_payload_from_object(part)
                    if payload is not None:
                        official_payloads.append(payload)
    if official_payloads:
        return _decode_selected_image(official_payloads[-1], limits)

    # Backward-compatible fallback for explicitly trusted proxy response shapes.
    fallback_payloads: list[Any] = []
    for obj in _walk_json(resp_json):
        payload = _image_payload_from_object(obj)
        if payload is not None:
            fallback_payloads.append(payload)
    if fallback_payloads:
        return _decode_selected_image(fallback_payloads[-1], limits)

    feedback = resp_json.get("promptFeedback") or resp_json.get("prompt_feedback") or {}
    if isinstance(feedback, Mapping):
        block_reason = feedback.get("blockReason") or feedback.get("block_reason")
        if block_reason:
            raise GeminiAPIError(f"Gemini blocked the request: {block_reason}")

    finish_reason = None
    if isinstance(candidates, list) and candidates and isinstance(candidates[0], Mapping):
        finish_reason = candidates[0].get("finishReason") or candidates[0].get("finish_reason")
    detail = f" finishReason={finish_reason}" if finish_reason else ""
    raise GeminiAPIError(f"Gemini response contained no final image.{detail}")


def _redact(text: Any, secrets: Iterable[str]) -> str:
    result = str(text)
    for secret in secrets:
        if secret:
            result = result.replace(secret, "[REDACTED]")
    result = re.sub(
        r"(?i)(x-goog-api-key|authorization|api[_-]?key|access[_-]?token|token|secret|cookie|key)"
        r"(\s*[:=]\s*)(?:Bearer\s+)?[^\s,;\]\}\"]+",
        r"\1\2[REDACTED]",
        result,
    )
    return " ".join(result.split())[:1000]


def _read_limited_response(response: requests.Response, limit: int, deadline: float) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > limit:
                raise GeminiAPIError(
                    f"Gemini response is too large ({content_length} bytes; limit {limit})."
                )
        except ValueError:
            pass

    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if time.monotonic() > deadline:
            raise GeminiAPIError("Gemini request exceeded the configured total timeout.")
        if not chunk:
            continue
        total += len(chunk)
        if total > limit:
            raise GeminiAPIError(f"Gemini response exceeded the {limit}-byte limit.")
        chunks.append(chunk)
    return b"".join(chunks)


def call_gemini_generate_image(
    prompt: str,
    images: List[Image.Image],
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: float = 60.0,
    seed: Optional[int] = None,
) -> bytes:
    """Generate/edit an image and return encoded PNG/JPEG/WebP bytes.

    The function intentionally performs no automatic retry because a retry may
    create duplicate paid generations. Existing node call signatures remain
    compatible with the original implementation.
    """

    config = _load_config()
    key = _clean_secret(api_key) or _get_api_key(config)
    resolved_model = _resolve_model(model, config)
    api_mode = _resolve_api_mode(config)
    url = _configured_endpoint(resolved_model, config)
    _, official_endpoint = _validate_endpoint(url)

    try:
        timeout_value = float(timeout)
    except (TypeError, ValueError) as exc:
        raise GeminiAPIError("Timeout must be a number.") from exc
    if not 1 <= timeout_value <= 600:
        raise GeminiAPIError("Timeout must be between 1 and 600 seconds.")

    limits = _limits(config)
    payload = _build_payload(
        prompt,
        images,
        seed=seed,
        api_mode=api_mode,
        limits=limits,
    )
    payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload_bytes) > limits["max_request_bytes"]:
        raise GeminiAPIError(
            f"Gemini request is too large ({len(payload_bytes):,} bytes; "
            f"limit {limits['max_request_bytes']:,})."
        )

    headers: dict[str, str] = {
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "fuzhuang2-jingxun/0.1.0",
    }
    params: dict[str, str] = {}
    _apply_auth(headers, params, key, config, official_endpoint=official_endpoint)
    sensitive_header_names = ("auth", "key", "token", "secret", "cookie")
    redaction_secrets = [key, *params.values()]
    redaction_secrets.extend(
        value
        for name, value in headers.items()
        if any(marker in name.lower() for marker in sensitive_header_names)
    )

    session = requests.Session()
    # Secure default: ignore inherited HTTP(S)_PROXY. Users who intentionally
    # need a system proxy can explicitly set GEMINI_TRUST_ENV_PROXY=1.
    session.trust_env = _env_bool("GEMINI_TRUST_ENV_PROXY", default=False)
    deadline = time.monotonic() + timeout_value
    try:
        try:
            response = session.post(
                url,
                headers=headers,
                params=params,
                data=payload_bytes,
                timeout=(min(10.0, timeout_value), timeout_value),
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as exc:
            raise GeminiAPIError(f"Network error calling Gemini API: {_redact(exc, redaction_secrets)}") from exc

        with response:
            if 300 <= response.status_code < 400:
                raise GeminiAPIError(
                    "Gemini endpoint returned a redirect; redirects are blocked to protect images and credentials."
                )
            body = _read_limited_response(response, limits["max_response_bytes"], deadline)
            try:
                parsed = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
                if response.status_code != 200:
                    snippet = _redact(body[:1000].decode("utf-8", errors="replace"), redaction_secrets)
                    raise GeminiAPIError(
                        f"Gemini API error {response.status_code}: {snippet or 'non-JSON response'}"
                    ) from exc
                raise GeminiAPIError("Gemini returned an invalid JSON response.") from exc

            if response.status_code != 200:
                error_obj = parsed.get("error") if isinstance(parsed, Mapping) else None
                if isinstance(error_obj, Mapping):
                    message = error_obj.get("message") or error_obj.get("status") or "request failed"
                else:
                    message = "request failed"
                raise GeminiAPIError(
                    f"Gemini API error {response.status_code}: {_redact(message, redaction_secrets)}"
                )
            if not isinstance(parsed, Mapping):
                raise GeminiAPIError("Gemini returned an unexpected JSON response type.")
            return _extract_image_bytes_from_response(parsed, limits)
    finally:
        session.close()
