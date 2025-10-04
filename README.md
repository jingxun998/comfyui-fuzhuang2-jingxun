comfyui-fuzhuang2-jingxun
==========================

Custom ComfyUI nodes powered by Google Gemini for virtual try-on workflows.

Features
--------
- Gemini Model Generator: clean, studio-style e-commerce model image from a user photo
- Gemini Virtual Try-On: wear a garment image onto the model (supports layering)
- Gemini Pose Variation: change camera/pose with instruction while preserving identity, clothes, and background
- Gemini Garment Processor: convert arbitrary garment photo into clean product flat lay on white background
  - New: selectable categories (top/bottom/shoes)
  - New: seed mode and caching

Installation
------------
1. Place this folder under your ComfyUI custom nodes directory, for example:
   - Windows: `ComfyUI\\custom_nodes\\comfyui-fuzhuang2-jingxun`
2. Install dependencies (one-time):
   ```bash
   pip install -r comfyui-fuzhuang2-jingxun/requirements.txt
   ```

API Key, Base URL & Proxies
---------------------------
Recommended: create `gemini_config.json` in the plugin folder with:
```json
{
  "api_key": "YOUR_GOOGLE_GEMINI_API_KEY",
  "base_url": "https://generativelanguage.googleapis.com",
  "endpoint_template": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
  "auth_header_name": null,
  "auth_header_value_template": null,
  "query_param_name": "key",
  "extra_headers": {
    
  }
}
```

You can also use environment variables (override config) before launching ComfyUI:
- `GOOGLE_API_KEY` or `GEMINI_API_KEY` (API key)
- `GOOGLE_API_URL` or `GEMINI_API_URL` (full endpoint template, must include `{model}`)
- `GOOGLE_API_BASE_URL` or `GEMINI_API_BASE_URL` (base URL; default `https://generativelanguage.googleapis.com`)
- `GEMINI_AUTH_HEADER_NAME` and `GEMINI_AUTH_HEADER_VALUE` (header-based auth; value can include `{api_key}`)
- `GEMINI_QUERY_PARAM_NAME` (query param name for key; default `key`)

Windows PowerShell example:
```powershell
$env:GOOGLE_API_KEY="YOUR_KEY_HERE"
$env:GOOGLE_API_BASE_URL="https://generativelanguage.googleapis.com"
# header auth example (proxy):
$env:GEMINI_AUTH_HEADER_NAME="Authorization"
$env:GEMINI_AUTH_HEADER_VALUE="Bearer {api_key}"
```

Alternatively, you may create a file `gemini_api_key.txt` inside this plugin folder with the key as the only content.

Nodes and Prompts
-----------------
All nodes use model `gemini-2.5-flash-image-preview` and request `responseModalities: [IMAGE, TEXT]`. Nodes now support `seed_mode` (random/fixed) and `seed`.

1) Gemini 模特生成器 (Gemini Model Generator)
---------------------------------------------
Input: `source_image (IMAGE)`
Output: `model_image (IMAGE)`
Extra controls:
- `seed_mode`: `random` or `fixed` (fixed enables caching to avoid re-generation when inputs unchanged)
- `seed`: integer used when `seed_mode=fixed`
Prompt (exact):
```
You are an expert fashion photographer AI. Transform the person in this image into a full-body fashion model photo suitable for an e-commerce website. The background must be a clean, neutral studio backdrop (light gray, #f0f0f0). The person should have a neutral, professional model expression. Preserve the person's identity, unique features, and body type, but place them in a standard, relaxed standing model pose. The final image must be photorealistic. Return ONLY the final image.
```

2) Gemini 虚拟试衣 (Gemini Virtual Try-On)
-----------------------------------------
Inputs: `model_image (IMAGE)`, `garment_image (IMAGE)`
Output: `try_on_image (IMAGE)`
Extra controls:
- `seed_mode`: `random` or `fixed`
- `seed`: integer used when `seed_mode=fixed`
Prompt (exact):
```
You are an expert virtual try-on AI. You will be given a 'model image' and a 'garment image'. Your task is to create a new photorealistic image where the person from the 'model image' is wearing the clothing from the 'garment image'.

**Crucial Rules:**
1.  **Complete Garment Replacement:** You MUST completely REMOVE and REPLACE the clothing item worn by the person in the 'model image' with the new garment. No part of the original clothing (e.g., collars, sleeves, patterns) should be visible in the final image.
2.  **Preserve the Model:** The person's face, hair, body shape, and pose from the 'model image' MUST remain unchanged.
3.  **Preserve the Background:** The entire background from the 'model image' MUST be preserved perfectly.
4.  **Apply the Garment:** Realistically fit the new garment onto the person. It should adapt to their pose with natural folds, shadows, and lighting consistent with the original scene.
5.  **Output:** Return ONLY the final, edited image. Do not include any text.
```

3) Gemini 姿势变换器 (Gemini Pose Variation)
------------------------------------------
Inputs: `source_image (IMAGE)`, `use_preset (BOOLEAN)`, `pose_preset (STRING)`, `pose_instruction (STRING)`
Output: `posed_image (IMAGE)`
Extra controls:
- Presets: `front_straight`, `three_quarter_right`, `three_quarter_left`, `profile_right`, `profile_left`, `hands_on_hips`, `crossed_arms`, `walking_forward`, `seated_relaxed`
- `seed_mode`: `random` or `fixed`
- `seed`: integer used when `seed_mode=fixed`
Prompt (f-string):
```python
prompt = f"""You are an expert fashion photographer AI. Take this image and regenerate it from a different perspective. The person, clothing, and background style must remain identical. The new perspective should be: "{pose_instruction}". Return ONLY the final image."""
```

4) Gemini 服装处理器 (Gemini Garment Processor)
---------------------------------------------
Input: `source_garment_image (IMAGE)`
Output: `clean_garment_image (IMAGE)`
Extra controls:
- Category toggles: `select_top`, `select_bottom`, `select_shoes`
- `seed_mode`: `random` or `fixed`
- `seed`: integer used when `seed_mode=fixed`
Prompt (exact):
```
You are an expert e-commerce product photographer AI. Your task is to take the clothing item from the provided image and create a professional 'product flat lay' photo of it.

**Crucial Rules:**
1.  **Isolate the Garment:** Identify and isolate the primary clothing item in the image.
2.  **Remove Background & Person:** Completely remove the original background, any person wearing the garment, and any other distracting elements.
3.  **Create a Clean Backdrop:** Place the isolated garment on a clean, neutral, perfectly white background (#ffffff).
4.  **Standardize Presentation:** Present the garment as if it were neatly laid out flat for a product catalog. Remove any wrinkles and smooth out the fabric.
5.  **Reconstruct Missing Parts:** If parts of the garment are obscured (e.g., by arms, hair, or complex folds in the original photo), you must realistically reconstruct the full, complete garment.
6.  **Professional Lighting:** Ensure the lighting on the garment is even and professional, as if in a photography studio, eliminating harsh shadows.
7.  **Output:** Return ONLY the final, edited image of the garment on the white background. Do not include any text.
```

Example Workflows
-----------------
- Basic: Load Image (user photo) -> Gemini Model Generator -> Load Image (garment) -> Gemini Virtual Try-On -> Preview Image
- Layering: (previous try_on_image) -> Load Image (jacket) -> Gemini Virtual Try-On -> Preview Image
- Pose Change: (any try_on result) -> Primitive (pose text) -> Gemini Pose Variation -> Preview Image
- With Garment Processor: Load Image (user photo) -> Gemini Model Generator | Load Image (any garment photo) -> Gemini Garment Processor | Gemini Virtual Try-On -> Preview Image

Errors
------
If the API returns an error or safety block, the node will raise an informative error in ComfyUI. Check your API key, quota, and prompt content.

License
-------
MIT


