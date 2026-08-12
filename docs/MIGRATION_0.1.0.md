# Migration to 0.1.0

## Compatibility promise

The seven node class identifiers, display names, Chinese input field names,
function names, return types, and categories are preserved. Existing ComfyUI
workflow JSON should reconnect to the same nodes without manual rewiring.

## Required changes

1. Delete any old root-level `comfyui-fuzhuang2-jingxun.zip` after installing the
   public source tree. The ZIP is no longer a second source of truth.
2. Do not commit `gemini_config.json` or `gemini_api_key.txt`. Copy
   `gemini_config.example.json` to `gemini_config.json` locally, or set
   `GOOGLE_API_KEY` before starting ComfyUI.
3. The default model is now `gemini-3.1-flash-image`. Override it with
   `GEMINI_IMAGE_MODEL` or the local config only when your provider requires a
   different identifier.
4. The default request format is the official `v1` `generateContent` structure.
   It contains only fields documented for that endpoint. A provider that accepts
   only the former proxy-specific body can use `api_mode: "legacy_proxy"` locally.
   Remote retention and logging remain governed by the selected provider.

## Custom endpoints

A non-Google endpoint is denied until the launching process contains both:

```bash
GEMINI_ALLOW_CUSTOM_ENDPOINT=1
GEMINI_ALLOWED_HOSTS=trusted-provider.example.com
```

The local config may then set `base_url`, `endpoint_template`, authentication
header fields, or a query parameter. This double opt-in prevents a repository or
workflow file from silently selecting an untrusted destination.
