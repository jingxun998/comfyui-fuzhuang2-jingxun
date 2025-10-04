import base64
import json
import os
from typing import List, Optional

import requests
from PIL import Image


DEFAULT_API_BASE_URL = "https://generativelanguage.googleapis.com"


class GeminiAPIError(RuntimeError):
    pass


def _plugin_dir() -> str:
    return os.path.dirname(__file__)


def _load_config() -> Optional[dict]:
    cfg_path = os.path.join(_plugin_dir(), "gemini_config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            # Ignore malformed config, fall back to other methods
            return None
    return None


def _get_api_key() -> str:
    # 1) Environment variables override
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if key:
        return key

    # 2) Config file
    cfg = _load_config() or {}
    key = cfg.get("api_key")
    if key:
        return key

    # 3) Legacy local text file
    local_key_file = os.path.join(_plugin_dir(), "gemini_api_key.txt")
    if os.path.exists(local_key_file):
        with open(local_key_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return content

    raise GeminiAPIError(
        "Google Gemini API key not found. Provide it via environment variable 'GOOGLE_API_KEY' (or 'GEMINI_API_KEY'),"
        " config file 'gemini_config.json' (field 'api_key'), or a 'gemini_api_key.txt' file in the plugin directory."
    )


def _get_base_url() -> str:
    # 2) Base URL via env
    base = os.environ.get("GOOGLE_API_BASE_URL") or os.environ.get("GEMINI_API_BASE_URL")
    if base:
        return base

    # 3) Config file base URL
    cfg = _load_config() or {}
    base = cfg.get("base_url")
    if base:
        return base

    # 4) Default
    return DEFAULT_API_BASE_URL


def _build_full_endpoint(model: str) -> str:
    # 1) Full URL override via env (highest precedence)
    env_url = os.environ.get("GOOGLE_API_URL") or os.environ.get("GEMINI_API_URL")
    if env_url:
        return env_url.format(model=model)

    # 2) Config explicit endpoint template
    cfg = _load_config() or {}
    endpoint_template = (
        cfg.get("endpoint_template")
        or cfg.get("endpoint")
        or cfg.get("full_url")
    )
    if endpoint_template:
        return str(endpoint_template).format(model=model)

    # 3) Build from base URL
    base = _get_base_url().rstrip("/")
    return f"{base}/v1beta/models/{model}:generateContent"


def _apply_auth(headers: dict, params: dict, api_key: str) -> None:
    """Apply authentication to headers or query according to env/config.

    Priority:
    - Env vars (header)
    - Config (auth_header_name/auth_header_value_template)
    - Query param (env GEMINI_QUERY_PARAM_NAME) or config (query_param_name)
    - Default query param 'key'
    """
    cfg = _load_config() or {}

    # Extra headers from config
    extra_headers = cfg.get("extra_headers") or {}
    if isinstance(extra_headers, dict):
        headers.update({str(k): str(v) for k, v in extra_headers.items()})

    # Auth via header (env)
    env_hdr_name = os.environ.get("GEMINI_AUTH_HEADER_NAME")
    env_hdr_value = os.environ.get("GEMINI_AUTH_HEADER_VALUE")
    if env_hdr_name and env_hdr_value:
        headers[str(env_hdr_name)] = env_hdr_value.format(api_key=api_key)
        return

    # Auth via header (config)
    hdr_name = cfg.get("auth_header_name")
    hdr_value_tmpl = cfg.get("auth_header_value_template")
    if hdr_name and hdr_value_tmpl:
        headers[str(hdr_name)] = str(hdr_value_tmpl).format(api_key=api_key)
        return

    # Auth via query param (env or config)
    query_param = os.environ.get("GEMINI_QUERY_PARAM_NAME") or cfg.get("query_param_name") or "key"
    params[str(query_param)] = api_key


def _encode_image_to_base64(img: Image.Image) -> dict:
    from .utils.image_io import pil_to_png_bytes

    png_bytes = pil_to_png_bytes(img)
    return {
        "mime_type": "image/png",
        "data": base64.b64encode(png_bytes).decode("utf-8"),
    }


def _build_payload(prompt: str, images: List[Image.Image], seed: Optional[int] = None) -> dict:
    parts: List[dict] = [{"text": prompt}]
    for img in images:
        parts.append({"inline_data": _encode_image_to_base64(img)})
    generation_config = {
        "response_mime_type": "image/png",
    }
    if seed is not None:
        # Include commonly seen keys for better proxy compatibility
        try:
            generation_config["seed"] = int(seed)
            generation_config["random_seed"] = int(seed)
        except Exception:
            pass

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": parts,
            }
        ],
        # Match requirement: request both IMAGE and TEXT modalities, but we expect image primary
        "generationConfig": generation_config,
        "responseModalities": ["IMAGE", "TEXT"],
    }
    return payload


def _extract_image_bytes_from_response(resp_json: dict) -> bytes:
    # Typical success path: candidates[0].content.parts[*].inline_data.data (base64)
    candidates = resp_json.get("candidates") or []
    if not candidates:
        # Check for promptFeedback block
        feedback = resp_json.get("promptFeedback") or {}
        block_reason = feedback.get("blockReason") or feedback.get("block_reason")
        if block_reason:
            raise GeminiAPIError(f"Gemini blocked the request: {block_reason}")
        raise GeminiAPIError("Gemini API returned no candidates.")

    # inspect first candidate with inline image data
    for cand in candidates:
        content = cand.get("content") or {}
        parts = content.get("parts") or []
        for part in parts:
            inline = part.get("inline_data") or part.get("inlineData")
            if inline and isinstance(inline, dict):
                mime = inline.get("mime_type") or inline.get("mimeType") or ""
                data_b64 = inline.get("data")
                if data_b64 and mime.startswith("image/"):
                    return base64.b64decode(data_b64)

    # Fallback: check ground-level parts
    contents = resp_json.get("contents") or []
    for content in contents:
        for part in content.get("parts", []):
            inline = part.get("inline_data") or part.get("inlineData")
            if inline and isinstance(inline, dict):
                mime = inline.get("mime_type") or inline.get("mimeType") or ""
                data_b64 = inline.get("data")
                if data_b64 and mime.startswith("image/"):
                    return base64.b64decode(data_b64)

    # If we reach here, extract helpful diagnostics
    finish_reason = candidates[0].get("finishReason") if candidates else None
    raise GeminiAPIError(
        f"No image found in response. finishReason={finish_reason}, raw={json.dumps(resp_json)[:800]}"
    )


def call_gemini_generate_image(
    prompt: str,
    images: List[Image.Image],
    model: str = "gemini-2.5-flash-image-preview",
    api_key: Optional[str] = None,
    timeout: float = 60.0,
    seed: Optional[int] = None,
) -> bytes:
    """Call Gemini API to generate an image response from prompt + images.

    Returns PNG bytes on success, raises GeminiAPIError on failure.
    """
    key = api_key or _get_api_key()
    url = _build_full_endpoint(model)
    headers = {
        "Content-Type": "application/json",
    }
    params = {}
    _apply_auth(headers, params, key)
    payload = _build_payload(prompt, images, seed=seed)

    try:
        resp = requests.post(url, headers=headers, params=params, json=payload, timeout=timeout)
    except requests.RequestException as ex:
        raise GeminiAPIError(f"Network error calling Gemini API: {ex}")

    if resp.status_code != 200:
        # Try to parse error payload
        try:
            err_json = resp.json()
        except Exception:
            err_json = None
        if err_json:
            # Common format: {"error": {"code":..., "message":..., "status":...}}
            err = err_json.get("error") or {}
            message = err.get("message") or json.dumps(err_json)
            raise GeminiAPIError(f"Gemini API error {resp.status_code}: {message}")
        raise GeminiAPIError(f"Gemini API error {resp.status_code}: {resp.text}")

    try:
        resp_json = resp.json()
    except ValueError as ex:
        raise GeminiAPIError(f"Failed to parse Gemini response JSON: {ex}")

    return _extract_image_bytes_from_response(resp_json)


