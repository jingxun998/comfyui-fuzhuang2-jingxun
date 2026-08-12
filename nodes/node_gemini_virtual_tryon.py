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




PROMPT = (
    "You are an expert virtual try-on AI. You will be given a 'model image' and a 'garment image'. Your task is to create a new photorealistic image where the person from the 'model image' is wearing the clothing from the 'garment image'.\n\n"
    "**Crucial Rules:**\n"
    "1.  **Complete Garment Replacement:** You MUST completely REMOVE and REPLACE the clothing item worn by the person in the 'model image' with the new garment. No part of the original clothing (e.g., collars, sleeves, patterns) should be visible in the final image.\n"
    "2.  **Preserve the Model:** The person's face, hair, body shape, and pose from the 'model image' MUST remain unchanged.\n"
    "3.  **Preserve the Background:** The entire background from the 'model image' MUST be preserved perfectly.\n"
    "4.  **Apply the Garment:** Realistically fit the new garment onto the person. It should adapt to their pose with natural folds, shadows, and lighting consistent with the original scene.\n"
    "5.  **Output:** Return ONLY the final, edited image. Do not include any text."
)


class GeminiVirtualTryOn:
    """ComfyUI node: Gemini 虚拟试衣

    Inputs:
      - model_image (IMAGE)
      - garment_image (IMAGE)
    Outputs:
      - try_on_image (IMAGE)
    """

    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        return {
            "required": {
                "模特图": ("IMAGE", {"tooltip": "输入模特图，通常来自上一步生成/试衣结果"}),
                "服装图": ("IMAGE", {"tooltip": "输入服装商品图，或由服装处理器输出"}),
                "种子": ("INT", {"default": 0, "min": 0, "max": 2**31 - 1, "tooltip": "种子>0固定并缓存；0表示每次随机"}),
                "超时秒数": ("INT", {"default": 60, "min": 5, "max": 600, "tooltip": "请求超时自动终止（秒）"}),
                "刷新间隔秒数": ("INT", {"default": 5, "min": 0, "max": 60, "tooltip": "控制台刷新/心跳频率；0 表示关闭"}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("试穿图",)
    FUNCTION = "tryon"
    CATEGORY = "Gemini / 服装"

    def tryon(self, 模特图, 服装图, 种子: int, 超时秒数: int, 刷新间隔秒数: int):
        model_list: List[Image.Image] = tensor_to_pil_list(模特图)
        garment_list: List[Image.Image] = tensor_to_pil_list(服装图)

        if not model_list:
            raise RuntimeError("No model image provided.")
        if not garment_list:
            raise RuntimeError("No garment image provided.")

        img_model = model_list[0]
        img_garment = garment_list[0]

        # Cache key（仅当种子>0时启用缓存）
        input_hash = hash_pil_images([img_model, img_garment])
        model_name = get_default_image_model()
        cache_key = f"virtual_tryon:{input_hash}:{model_name}:{种子}"
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
                k = 0
                while not stop_flag["stop"]:
                    time.sleep(刷新间隔秒数)
                    k += 1
                    elapsed = int(time.perf_counter() - start)
                    print(f"[GeminiVirtualTryOn] waiting... elapsed={elapsed}s (tick {k})")

        th = threading.Thread(target=_hb, daemon=True)
        th.start()

        result = {"data": None, "err": None}

        def _worker():
            try:
                result["data"] = call_gemini_generate_image(
                    prompt=PROMPT,
                    images=[img_model, img_garment],
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
            raise RuntimeError(f"Gemini Virtual Try-On timed out after {超时秒数}s")
        if result["err"] is not None:
            raise RuntimeError(f"Gemini Virtual Try-On error: {result['err']}")
        png_bytes = result["data"]

        if 种子 > 0:
            GLOBAL_RESULT_CACHE.set(cache_key, png_bytes)
        out_img = bytes_to_pil_image(png_bytes)
        out_tensor = pil_list_to_tensor([out_img])
        return (out_tensor,)
