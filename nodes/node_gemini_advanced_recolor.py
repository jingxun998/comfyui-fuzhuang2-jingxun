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




class GeminiAdvancedRecolor:
    """Gemini 高级调色盘（功能完备）

    功能完备的图像精准重上色节点。通过单行文本接收颜色描述（颜色名/HEX/自然语言），
    支持多目标（外套、上衣、下装、连衣裙、鞋子、配饰、头发）选择；也可自定义目标，
    自定义目标填写后，其它勾选自动失效（逻辑上忽略）。
    """

    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        return {
            "required": {
                "图片": ("IMAGE", {"tooltip": "需要进行颜色修改的原始图片"}),
                "颜色描述": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "tooltip": "颜色描述（单行）：'Red' / '#FF0000' / 'sky blue' / '天蓝色' 等",
                    },
                ),
                "自定义目标": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "tooltip": "可填写自定义目标描述；填写后将忽略下方所有勾选",
                    },
                ),
                "选择外套": ("BOOLEAN", {"default": False, "tooltip": "将外套/夹克作为换色目标"}),
                "选择上衣": ("BOOLEAN", {"default": True, "tooltip": "将上衣/衬衫/T恤作为换色目标"}),
                "选择下装": ("BOOLEAN", {"default": False, "tooltip": "将下装/裤装作为换色目标"}),
                "选择连衣裙": ("BOOLEAN", {"default": False, "tooltip": "将连衣裙作为换色目标"}),
                "选择鞋子": ("BOOLEAN", {"default": False, "tooltip": "将鞋子作为换色目标"}),
                "选择配饰": ("BOOLEAN", {"default": False, "tooltip": "将配饰（包/腰带/帽子等）作为换色目标"}),
                "选择头发": ("BOOLEAN", {"default": False, "tooltip": "将头发作为换色目标"}),
                "种子": ("INT", {"default": 0, "min": 0, "max": 2**31 - 1, "tooltip": "种子>0固定并缓存；0表示每次随机"}),
                "超时秒数": ("INT", {"default": 60, "min": 5, "max": 600, "tooltip": "请求超时自动终止（秒）"}),
                "刷新间隔秒数": ("INT", {"default": 5, "min": 0, "max": 60, "tooltip": "控制台刷新/心跳频率；0 表示关闭"}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("重新着色图",)
    FUNCTION = "process"
    CATEGORY = "Gemini/Image"

    def process(
        self,
        图片,
        颜色描述: str,
        自定义目标: str,
        选择外套: bool,
        选择上衣: bool,
        选择下装: bool,
        选择连衣裙: bool,
        选择鞋子: bool,
        选择配饰: bool,
        选择头发: bool,
        种子: int,
        超时秒数: int,
        刷新间隔秒数: int,
    ):
        images: List[Image.Image] = tensor_to_pil_list(图片)
        if not images:
            raise RuntimeError("No input image provided.")
        img = images[0]

        # Build selected targets
        selected_targets: List[str] = []
        custom_target = (自定义目标 or "").strip()
        if len(custom_target) > 0:
            selected_targets.append(custom_target)
        else:
            if 选择外套:
                selected_targets.append("the coat/jacket")
            if 选择上衣:
                selected_targets.append("the top/shirt")
            if 选择下装:
                selected_targets.append("the bottom/pants")
            if 选择连衣裙:
                selected_targets.append("the dress")
            if 选择鞋子:
                selected_targets.append("the shoes")
            if 选择配饰:
                selected_targets.append("the accessories")
            if 选择头发:
                selected_targets.append("the hair")

        color_text = (颜色描述 or "").strip()

        # Input validation: if no targets or no color, return the original image without API calls
        if len(selected_targets) == 0 or len(color_text) == 0:
            return (图片,)

        target_string = " and ".join(selected_targets)
        prompt = (
            f"You are a hyper-precise, professional-grade photo editing AI assistant. Your ONLY task is to perform a highly accurate color change operation on the provided image based on the user's request.\n\n"
            f"**CRUCIAL INSTRUCTIONS - FOLLOW THESE EXACTLY:**\n"
            f"1.  **IDENTIFY TARGET:** Your primary task is to precisely identify ONLY the following object(s) in the image: '{target_string}'.\n"
            f"2.  **APPLY NEW COLOR:** Change the color of the identified target(s) to be exactly this: '{color_text}'. Interpret this color description accurately, whether it's a simple color name, a HEX code, or a descriptive phrase.\n"
            f"3.  **PRESERVE EVERYTHING ELSE:** This is the most important rule. The texture, material, fabric folds, shadows, highlights, and all other elements of the image (including the person's skin tone, the background, and any other clothing items not listed in the target) MUST remain absolutely identical and unchanged.\n"
            f"4.  **NO OTHER ALTERATIONS:** Do not add, remove, or alter anything else in the image. Do not change the composition or style.\n"
            f"5.  **OUTPUT:** Return ONLY the final, edited image. Do not include any text, dialogue, or explanations in your response."
        )

        # Cache when seed > 0
        input_hash = hash_pil_images([img])
        model_name = get_default_image_model()
        cache_key = f"advanced_recolor:{input_hash}:{target_string}:{color_text}:{model_name}:{种子}"
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
                c = 0
                while not stop_flag["stop"]:
                    time.sleep(刷新间隔秒数)
                    c += 1
                    elapsed = int(time.perf_counter() - start)
                    print(f"[GeminiAdvancedRecolor] waiting... elapsed={elapsed}s (tick {c})")

        th = threading.Thread(target=_hb, daemon=True)
        th.start()

        try:
            png_bytes = call_gemini_generate_image(
                prompt=prompt,
                images=[img],
                model=model_name,
                seed=(种子 if 种子 > 0 else None),
                timeout=max(5, int(超时秒数) if isinstance(超时秒数, int) else 60),
            )
        except GeminiAPIError as ex:
            raise RuntimeError(f"Gemini Advanced Recolor error: {ex}")
        finally:
            stop_flag["stop"] = True

        if 种子 > 0:
            GLOBAL_RESULT_CACHE.set(cache_key, png_bytes)
        out_img = bytes_to_pil_image(png_bytes)
        out_tensor = pil_list_to_tensor([out_img])
        return (out_tensor,)
