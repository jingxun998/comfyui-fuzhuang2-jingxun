from __future__ import annotations

import base64
import io
import json

import pytest
from PIL import Image


def png_bytes(size=(8, 6), color=(20, 40, 60)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, status_code=200, payload=None, raw=None, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._raw = raw if raw is not None else json.dumps(payload or {}).encode("utf-8")

    def iter_content(self, chunk_size=65536):
        for index in range(0, len(self._raw), chunk_size):
            yield self._raw[index : index + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.trust_env = None
        self.calls = []
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response

    def close(self):
        self.closed = True


def client_module(plugin):
    import sys

    return sys.modules[plugin.__name__ + ".gemini_client"]


def test_official_request_and_image_response(plugin, monkeypatch):
    client = client_module(plugin)
    encoded = base64.b64encode(png_bytes()).decode("ascii")
    response = FakeResponse(
        payload={"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": encoded}}]}}]}
    )
    session = FakeSession(response)
    monkeypatch.setattr(client.requests, "Session", lambda: session)
    monkeypatch.setattr(client, "_load_config", lambda: {})

    result = client.call_gemini_generate_image(
        "edit this image",
        [Image.new("RGB", (8, 6))],
        api_key="unit-test-key",
        seed=7,
    )

    assert result == png_bytes()
    assert session.closed is True
    assert session.trust_env is False
    url, kwargs = session.calls[0]
    assert url == (
        "https://generativelanguage.googleapis.com/"
        "v1/models/gemini-3.1-flash-image:generateContent"
    )
    assert kwargs["allow_redirects"] is False
    assert kwargs["stream"] is True
    assert kwargs["headers"]["x-goog-api-key"] == "unit-test-key"
    payload = json.loads(kwargs["data"].decode("utf-8"))
    assert payload["generationConfig"] == {"responseModalities": ["IMAGE"], "seed": 7}
    assert "store" not in payload
    assert "responseModalities" not in {key for key in payload if key != "generationConfig"}


def test_custom_endpoint_requires_both_opt_in_and_allowlist(plugin, monkeypatch):
    client = client_module(plugin)
    config = {"base_url": "https://trusted.example.com"}
    monkeypatch.setattr(client, "_load_config", lambda: config)
    with pytest.raises(client.GeminiAPIError, match="Custom endpoint"):
        client.call_gemini_generate_image(
            "x" * 1000,
            [Image.new("RGB", (4, 4))],
            api_key="unit-test-key",
        )

    monkeypatch.setenv("GEMINI_ALLOW_CUSTOM_ENDPOINT", "1")
    with pytest.raises(client.GeminiAPIError, match="not in GEMINI_ALLOWED_HOSTS"):
        client.call_gemini_generate_image(
            "x" * 1000,
            [Image.new("RGB", (4, 4))],
            api_key="unit-test-key",
        )


def test_trusted_custom_endpoint_can_use_bearer_auth(plugin, monkeypatch):
    client = client_module(plugin)
    encoded = base64.b64encode(png_bytes()).decode("ascii")
    response = FakeResponse(payload={"x": {"type": "image", "mime_type": "image/png", "data": encoded}})
    session = FakeSession(response)
    config = {
        "base_url": "https://trusted.example.com",
        "auth_header_name": "Authorization",
        "auth_header_value_template": "Bearer {api_key}",
    }
    monkeypatch.setattr(client, "_load_config", lambda: config)
    monkeypatch.setattr(client.requests, "Session", lambda: session)
    monkeypatch.setenv("GEMINI_ALLOW_CUSTOM_ENDPOINT", "1")
    monkeypatch.setenv("GEMINI_ALLOWED_HOSTS", "trusted.example.com")

    result = client.call_gemini_generate_image(
        "x" * 1000,
        [Image.new("RGB", (4, 4))],
        api_key="unit-test-key",
    )
    assert result == png_bytes()
    assert session.calls[0][1]["headers"]["Authorization"] == "Bearer unit-test-key"
    assert "x-goog-api-key" not in session.calls[0][1]["headers"]


def test_redirect_is_blocked(plugin, monkeypatch):
    client = client_module(plugin)
    session = FakeSession(FakeResponse(status_code=302, headers={"Location": "https://evil.example"}))
    monkeypatch.setattr(client.requests, "Session", lambda: session)
    monkeypatch.setattr(client, "_load_config", lambda: {})
    with pytest.raises(client.GeminiAPIError, match="redirect"):
        client.call_gemini_generate_image(
            "x" * 1000,
            [Image.new("RGB", (4, 4))],
            api_key="unit-test-key",
        )


def test_remote_error_is_redacted(plugin, monkeypatch):
    client = client_module(plugin)
    key = "unit-test-secret-value"
    response = FakeResponse(status_code=401, payload={"error": {"message": f"invalid key={key}"}})
    session = FakeSession(response)
    monkeypatch.setattr(client.requests, "Session", lambda: session)
    monkeypatch.setattr(client, "_load_config", lambda: {})
    with pytest.raises(client.GeminiAPIError) as caught:
        client.call_gemini_generate_image(
            "x" * 1000,
            [Image.new("RGB", (4, 4))],
            api_key=key,
        )
    assert key not in str(caught.value)
    assert "[REDACTED]" in str(caught.value)


def test_invalid_image_response_is_rejected(plugin):
    client = client_module(plugin)
    limits = client._limits({})
    payload = {
        "candidates": [
            {"content": {"parts": [{"inline_data": {"mime_type": "image/png", "data": base64.b64encode(b"not-image").decode("ascii")}}]}}
        ]
    }
    with pytest.raises(client.GeminiAPIError, match="safe, decodable image"):
        client._extract_image_bytes_from_response(payload, limits)


def test_legacy_proxy_payload_remains_available(plugin):
    client = client_module(plugin)
    limits = client._limits({})
    payload = client._build_payload(
        "x" * 1000,
        [Image.new("RGB", (4, 4))],
        seed=5,
        api_mode="legacy_proxy",
        limits=limits,
    )
    assert payload["responseModalities"] == ["IMAGE", "TEXT"]
    assert payload["generationConfig"]["random_seed"] == 5


def test_thought_images_are_skipped_and_last_final_image_is_returned(plugin):
    client = client_module(plugin)
    thought = base64.b64encode(png_bytes(color=(255, 0, 0))).decode("ascii")
    first_final = base64.b64encode(png_bytes(color=(0, 255, 0))).decode("ascii")
    last_final = base64.b64encode(png_bytes(color=(0, 0, 255))).decode("ascii")
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"thought": True, "inlineData": {"mimeType": "image/png", "data": thought}},
                        {"inlineData": {"mimeType": "image/png", "data": first_final}},
                        {"inlineData": {"mimeType": "image/png", "data": last_final}},
                    ]
                }
            }
        ]
    }
    assert client._extract_image_bytes_from_response(payload, client._limits({})) == png_bytes(
        color=(0, 0, 255)
    )


def test_response_with_only_thought_images_has_no_final_output(plugin):
    client = client_module(plugin)
    thought = base64.b64encode(png_bytes(color=(255, 0, 0))).decode("ascii")
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"thought": True, "inlineData": {"mimeType": "image/png", "data": thought}}
                    ]
                }
            }
        ]
    }
    with pytest.raises(client.GeminiAPIError, match="no final image"):
        client._extract_image_bytes_from_response(payload, client._limits({}))


@pytest.mark.parametrize(
    "url,match",
    [
        ("https://generativelanguage.googleapis.com/v1/models/x:generateContent?key=bad", "query"),
        ("https://generativelanguage.googleapis.com/v1/models/x:otherMethod", "generateContent"),
        ("https://generativelanguage.googleapis.com:444/v1/models/x:generateContent", "port 443"),
        ("https://generativelanguage.googleapis.com:99999/v1/models/x:generateContent", "invalid port"),
    ],
)
def test_official_endpoint_shape_is_strict(plugin, url, match):
    client = client_module(plugin)
    with pytest.raises(client.GeminiAPIError, match=match):
        client._validate_endpoint(url)


def test_endpoint_template_rejects_attribute_traversal(plugin):
    client = client_module(plugin)
    with pytest.raises(client.GeminiAPIError, match="literal \\{model\\}"):
        client._format_endpoint("https://example.com/{model.__class__}", "safe-model")


def test_auth_template_rejects_attribute_traversal(plugin):
    client = client_module(plugin)
    with pytest.raises(client.GeminiAPIError, match="literal \\{api_key\\}"):
        client._format_auth_header_value("Bearer {api_key.__class__}", "unit-test-key")


def test_custom_endpoint_cannot_override_transport_headers(plugin, monkeypatch):
    client = client_module(plugin)
    monkeypatch.setenv("GEMINI_ALLOW_CUSTOM_ENDPOINT", "1")
    monkeypatch.setenv("GEMINI_ALLOWED_HOSTS", "trusted.example.com")
    client._validate_endpoint("https://trusted.example.com/v1/models/x:generateContent")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    with pytest.raises(client.GeminiAPIError, match="cannot be overridden"):
        client._apply_auth(
            headers,
            {},
            "unit-test-key",
            {"extra_headers": {"Content-Type": "text/plain"}},
            official_endpoint=False,
        )


def test_private_literal_endpoint_is_blocked_even_if_allowlisted(plugin, monkeypatch):
    client = client_module(plugin)
    monkeypatch.setenv("GEMINI_ALLOW_CUSTOM_ENDPOINT", "1")
    monkeypatch.setenv("GEMINI_ALLOWED_HOSTS", "127.0.0.1")
    with pytest.raises(client.GeminiAPIError, match="Private|Local"):
        client._validate_endpoint("https://127.0.0.1/v1/models/x:generateContent")


def test_deep_fallback_json_is_rejected_without_recursion(plugin):
    client = client_module(plugin)
    value = {}
    cursor = value
    for _ in range(70):
        child = {}
        cursor["next"] = child
        cursor = child
    with pytest.raises(client.GeminiAPIError, match="nesting is too deep"):
        list(client._walk_json(value))


def test_response_content_length_limit_is_enforced(plugin):
    client = client_module(plugin)
    response = FakeResponse(headers={"Content-Length": "999"}, raw=b"{}")
    with pytest.raises(client.GeminiAPIError, match="too large"):
        client._read_limited_response(response, 10, float("inf"))
