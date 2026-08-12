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




PROMPT_TEMPLATE = (
    "You are a top-tier fashion stylist AI. Take the person from this 'model image' and dress them in a complete, stylish, and cohesive outfit suitable for a '{occasion}'.\n\n"
    "**Crucial Rules:**\n"
    "1.  **Preserve the Model's Identity:** The person's face, hair, body shape, and unique features from the original image MUST remain perfectly unchanged.\n"
    "2.  **Preserve Pose and Background:** The person's pose and the entire background from the original image MUST be preserved perfectly.\n"
    "3.  **Complete Outfit Generation:** Your task is to generate a new, full outfit from head to toe (as appropriate for the frame). You must completely replace any existing clothing on the model.\n"
    "4.  **Photorealism:** The final image must be photorealistic, with natural lighting, shadows, and textures consistent with the original scene.\n"
    "5.  **Output:** Return ONLY the final, edited image. Do not include any text, explanations, or dialogue."
)


class GeminiOccasionStylist:
    """Gemini 场合造型师

    根据“场合”描述为模特生成全新的完整穿搭。支持多开关预设（商务休闲、晚宴、周末早午餐、
    海滩度假、健身房、鸡尾酒会），以及自定义场合描述。若填写自定义，则忽略所有开关。
    保留人物身份、姿势和背景，仅替换服装，要求照片级真实感。
    """

    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        return {
            "required": {
                "模特图": ("IMAGE", {"tooltip": "输入基础模特图（人物+背景）"}),
                "自定义场合": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "tooltip": "自定义场合描述（填写后忽略下方所有开关）",
                    },
                ),
                "选择商务休闲": ("BOOLEAN", {"default": False, "tooltip": "商务休闲 Business Casual"}),
                "选择晚宴": ("BOOLEAN", {"default": False, "tooltip": "晚宴 Gala Dinner"}),
                "选择周末早午餐": ("BOOLEAN", {"default": False, "tooltip": "周末早午餐 Weekend Brunch"}),
                "选择海滩度假": ("BOOLEAN", {"default": False, "tooltip": "海滩度假 Beach Vacation"}),
                "选择健身房": ("BOOLEAN", {"default": False, "tooltip": "健身房 Gym/Fitness"}),
                "选择鸡尾酒会": ("BOOLEAN", {"default": False, "tooltip": "鸡尾酒会 Cocktail Party"}),
                "种子": ("INT", {"default": 0, "min": 0, "max": 2**31 - 1, "tooltip": "种子>0固定并缓存；0表示每次随机"}),
                "超时秒数": ("INT", {"default": 60, "min": 5, "max": 600, "tooltip": "请求超时自动终止（秒）"}),
                "刷新间隔秒数": ("INT", {"default": 5, "min": 0, "max": 60, "tooltip": "控制台刷新/心跳频率；0 表示关闭"}),
                "生成后控制": (
                    "STRING",
                    {
                        "default": "fixed",
                        "choices": ["fixed", "increment", "randomize"],
                        "ui": {"type": "combo"},
                        "tooltip": "生成后控制（ComfyUI 标准流程控制）",
                    },
                ),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("场合造型图",)
    FUNCTION = "style"
    CATEGORY = "Gemini / 场合"

    def style(
        self,
        模特图,
        自定义场合: str,
        选择商务休闲: bool,
        选择晚宴: bool,
        选择周末早午餐: bool,
        选择海滩度假: bool,
        选择健身房: bool,
        选择鸡尾酒会: bool,
        种子: int,
        超时秒数: int,
        刷新间隔秒数: int,
        生成后控制: str,
    ):
        images: List[Image.Image] = tensor_to_pil_list(模特图)
        if not images:
            raise RuntimeError("No model image provided.")
        img = images[0]

        # 优先级：自定义场合 > 开关组合 > 透传
        custom = (自定义场合 or "").strip()
        if len(custom) > 0:
            final_occasion = custom
        else:
            selected: List[str] = []
            if 选择商务休闲:
                selected.append("business casual")
            if 选择晚宴:
                selected.append("gala dinner")
            if 选择周末早午餐:
                selected.append("casual weekend brunch")
            if 选择海滩度假:
                selected.append("relaxing beach vacation")
            if 选择健身房:
                selected.append("gym/fitness session")
            if 选择鸡尾酒会:
                selected.append("cocktail party")

            if len(selected) == 0:
                return (模特图,)  # no-op for stability
            elif len(selected) == 1:
                final_occasion = selected[0]
            else:
                list_text = ", ".join(selected)
                final_occasion = f"one of the following occasions: {list_text}"

        prompt = PROMPT_TEMPLATE.format(occasion=final_occasion)

        # Cache when seed > 0
        input_hash = hash_pil_images([img])
        model_name = get_default_image_model()
        cache_key = f"occasion_stylist:{input_hash}:{final_occasion}:{model_name}:{种子}"
        if 种子 > 0:
            cached = GLOBAL_RESULT_CACHE.get(cache_key)
            if cached is not None:
                out_img = bytes_to_pil_image(cached)
                out_tensor = pil_list_to_tensor([out_img])
                return (out_tensor,)

        # Heartbeat thread for console refresh
        stop_flag = {"stop": False}

        def _heartbeat():
            if 刷新间隔秒数 and 刷新间隔秒数 > 0:
                start = time.perf_counter()
                counter = 0
                while not stop_flag["stop"]:
                    time.sleep(刷新间隔秒数)
                    counter += 1
                    elapsed = int(time.perf_counter() - start)
                    print(f"[GeminiOccasionStylist] waiting for Gemini... elapsed={elapsed}s (tick {counter})")

        thread = threading.Thread(target=_heartbeat, daemon=True)
        thread.start()

        try:
            png_bytes = call_gemini_generate_image(
                prompt=prompt,
                images=[img],
                model=model_name,
                seed=(种子 if 种子 > 0 else None),
                timeout=max(5, int(超时秒数) if isinstance(超时秒数, int) else 60),
            )
        except GeminiAPIError as ex:
            raise RuntimeError(f"Gemini Occasion Stylist error: {ex}")
        finally:
            stop_flag["stop"] = True

        if 种子 > 0:
            GLOBAL_RESULT_CACHE.set(cache_key, png_bytes)
        out_img = bytes_to_pil_image(png_bytes)
        out_tensor = pil_list_to_tensor([out_img])
        return (out_tensor,)
