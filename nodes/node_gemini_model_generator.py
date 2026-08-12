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
    "You are an expert fashion photographer AI. Transform the person in this image into a full-body fashion model photo suitable for an e-commerce website. "
    "The background must be a clean, neutral studio backdrop (light gray, #f0f0f0). The person should have a neutral, professional model expression. "
    "Preserve the person's identity, unique features, and body type, but place them in a standard, relaxed standing model pose. The final image must be photorealistic. Return ONLY the final image."
)


class GeminiModelGenerator:
    """ComfyUI node: Gemini 模特生成器

    Inputs:
      - source_image (IMAGE)
    Outputs:
      - model_image (IMAGE)
    """

    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        return {
            "required": {
                "输入图片": ("IMAGE", {"tooltip": "输入用户照片（全身/半身均可）"}),
                "种子": ("INT", {"default": 0, "min": 0, "max": 2**31 - 1, "tooltip": "用于复现结果；更改或随机化可抽新图"}),
                "超时秒数": ("INT", {"default": 60, "min": 5, "max": 600, "tooltip": "请求超时自动终止（秒）"}),
                "刷新间隔秒数": ("INT", {"default": 5, "min": 0, "max": 60, "tooltip": "控制台刷新/心跳频率；0 表示关闭"}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("模特图",)
    FUNCTION = "generate"
    CATEGORY = "Gemini / Fuzhuang"

    def generate(self, 输入图片, 种子: int, 超时秒数: int, 刷新间隔秒数: int):
        # Convert input tensor to PIL
        images: List[Image.Image] = tensor_to_pil_list(输入图片)
        if not images:
            raise RuntimeError("No input image provided.")
        img = images[0]

        # Cache key: node + input hash + seed
        input_hash = hash_pil_images([img])
        model_name = get_default_image_model()
        cache_key = f"model_generator:{input_hash}:{model_name}:{种子}"
        cached = GLOBAL_RESULT_CACHE.get(cache_key)
        if cached is not None:
            out_img = bytes_to_pil_image(cached)
            out_tensor = pil_list_to_tensor([out_img])
            return (out_tensor,)

        # Heartbeat
        stop_flag = {"stop": False}

        def _hb():
            if 刷新间隔秒数 and 刷新间隔秒数 > 0:
                start = time.perf_counter()
                tick = 0
                while not stop_flag["stop"]:
                    time.sleep(刷新间隔秒数)
                    tick += 1
                    elapsed = int(time.perf_counter() - start)
                    print(f"[GeminiModelGenerator] waiting... elapsed={elapsed}s (tick {tick})")

        t = threading.Thread(target=_hb, daemon=True)
        t.start()

        result = {"data": None, "err": None}

        def _worker():
            try:
                result["data"] = call_gemini_generate_image(
                    prompt=PROMPT,
                    images=[img],
                    model=model_name,
                    seed=种子,
                    timeout=max(5, int(超时秒数) if isinstance(超时秒数, int) else 60),
                )
            except Exception as e:
                result["err"] = e

        w = threading.Thread(target=_worker, daemon=True)
        w.start()

        w.join(timeout=max(5, int(超时秒数) if isinstance(超时秒数, int) else 60))
        stop_flag["stop"] = True
        if w.is_alive():
            raise RuntimeError(f"Gemini Model Generator timed out after {超时秒数}s")
        if result["err"] is not None:
            raise RuntimeError(f"Gemini Model Generator error: {result['err']}")
        png_bytes = result["data"]

        GLOBAL_RESULT_CACHE.set(cache_key, png_bytes)
        out_img = bytes_to_pil_image(png_bytes)
        out_tensor = pil_list_to_tensor([out_img])
        return (out_tensor,)
