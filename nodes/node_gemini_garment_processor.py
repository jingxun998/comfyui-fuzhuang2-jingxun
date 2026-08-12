from typing import Any, Dict, List
import threading
import time

from PIL import Image

from ..gemini_client import (
    GeminiAPIError,
    call_gemini_generate_image,
    get_default_image_model,
)
from ..utils.image_io import tensor_to_pil_list, bytes_to_pil_image, pil_list_to_tensor, hash_pil_images
from ..utils.result_cache import GLOBAL_RESULT_CACHE




BASE_PROMPT = (
    "You are an expert e-commerce product photographer AI. Your task is to take the clothing item(s) from the provided image and create a professional 'product flat lay' photo.\n\n"
    "**Crucial Rules:**\n"
    "1.  **Isolate the Garment:** Identify and isolate the specified clothing categories in the image.\n"
    "2.  **Remove Background & Person:** Completely remove the original background, any person wearing the garment, and any other distracting elements.\n"
    "3.  **Create a Clean Backdrop:** Place the isolated garment(s) on a clean, neutral, perfectly white background (#ffffff).\n"
    "4.  **Standardize Presentation:** Present each garment as if it were neatly laid out flat for a product catalog. Remove any wrinkles and smooth out the fabric.\n"
    "5.  **Reconstruct Missing Parts:** If parts of any garment are obscured (e.g., by arms, hair, or complex folds), realistically reconstruct the full, complete garment.\n"
    "6.  **Professional Lighting:** Ensure even, studio lighting with no harsh shadows.\n"
    "7.  **Output:** Return ONLY the final, edited image on the white background. Do not include any text.\n\n"
)


class GeminiGarmentProcessor:
    """ComfyUI node: Gemini 服装处理器

    Inputs:
      - source_garment_image (IMAGE)
    Outputs:
      - clean_garment_image (IMAGE)
    """

    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        return {
            "required": {
                "输入图片": ("IMAGE", {"tooltip": "输入包含服装的原始图片（可为街拍/复杂背景）"}),
                "选择上装": ("BOOLEAN", {"default": True, "tooltip": "提取上装（衬衫/外套等）"}),
                "选择下装": ("BOOLEAN", {"default": False, "tooltip": "提取下装（裙装/裤装等）"}),
                "选择鞋子": ("BOOLEAN", {"default": False, "tooltip": "提取鞋子"}),
                "种子": ("INT", {"default": 0, "min": 0, "max": 2**31 - 1, "tooltip": "种子>0固定并缓存；0表示每次随机"}),
                "超时秒数": ("INT", {"default": 60, "min": 5, "max": 600, "tooltip": "请求超时自动终止（秒）"}),
                "刷新间隔秒数": ("INT", {"default": 5, "min": 0, "max": 60, "tooltip": "控制台刷新/心跳频率；0 表示关闭"}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("清洗后服装图",)
    FUNCTION = "process"
    CATEGORY = "Gemini / 服装"

    def process(self, 输入图片, 选择上装: bool, 选择下装: bool, 选择鞋子: bool, 种子: int, 超时秒数: int, 刷新间隔秒数: int):
        images: List[Image.Image] = tensor_to_pil_list(输入图片)
        if not images:
            raise RuntimeError("No garment image provided.")
        img = images[0]

        selected = []
        if 选择上装:
            selected.append("tops")
        if 选择下装:
            selected.append("bottoms")
        if 选择鞋子:
            selected.append("shoes")
        if not selected:
            raise RuntimeError("Please select at least one category (top/bottom/shoes).")

        categories_text = ", ".join(selected)
        prompt = (
            BASE_PROMPT
            + f"Extract and present ONLY these categories: {categories_text}. If a category is not present, leave it out."
        )

        input_hash = hash_pil_images([img])
        model_name = get_default_image_model()
        cache_key = f"garment_processor:{input_hash}:{categories_text}:{model_name}:{种子}"
        if 种子 > 0:
            cached = GLOBAL_RESULT_CACHE.get(cache_key)
            if cached is not None:
                out_img = bytes_to_pil_image(cached)
                out_tensor = pil_list_to_tensor([out_img])
                return (out_tensor,)

        stop_flag = {"stop": False}

        def _hb():
            if 刷新间隔秒数 and 刷新间隔秒数 > 0:
                start = time.perf_counter()
                i = 0
                while not stop_flag["stop"]:
                    time.sleep(刷新间隔秒数)
                    i += 1
                    elapsed = int(time.perf_counter() - start)
                    print(f"[GeminiGarmentProcessor] waiting... elapsed={elapsed}s (tick {i})")

        thread = threading.Thread(target=_hb, daemon=True)
        thread.start()

        result = {"data": None, "err": None}

        def _worker():
            try:
                result["data"] = call_gemini_generate_image(
                    prompt=prompt,
                    images=[img],
                    model=model_name,
                    seed=(种子 if 种子 > 0 else None),
                    timeout=max(5, int(超时秒数) if isinstance(超时秒数, int) else 60),
                )
            except Exception as e:
                result["err"] = e

        w = threading.Thread(target=_worker, daemon=True)
        w.start()

        w.join(timeout=max(5, int(超时秒数) if isinstance(超时秒数, int) else 60))
        stop_flag["stop"] = True
        if w.is_alive():
            raise RuntimeError(f"Gemini Garment Processor timed out after {超时秒数}s")
        if result["err"] is not None:
            raise RuntimeError(f"Gemini Garment Processor error: {result['err']}")
        png_bytes = result["data"]

        if 种子 > 0:
            GLOBAL_RESULT_CACHE.set(cache_key, png_bytes)
        out_img = bytes_to_pil_image(png_bytes)
        out_tensor = pil_list_to_tensor([out_img])
        return (out_tensor,)
