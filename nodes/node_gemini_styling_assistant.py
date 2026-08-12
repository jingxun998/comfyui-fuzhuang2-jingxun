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
    "You are a top-tier fashion stylist AI. Based on the person and the clothing they are wearing in this image, add a complementary {item_description} to create a complete, stylish, and cohesive outfit.\n\n"
    "**Crucial Rules:**\n"
    "1.  **Preserve the Model:** The person's face, hair, body shape, and pose from the original image MUST remain perfectly unchanged.\n"
    "2.  **Preserve Existing Garments:** All clothing and accessories already present in the image MUST be preserved perfectly.\n"
    "3.  **Preserve the Background:** The entire background from the original image MUST be preserved perfectly.\n"
    "4.  **Additive Only:** Your only task is to ADD the new item. Do not remove, replace, or alter any existing element.\n"
    "5.  **Photorealism:** The final image must be photorealistic, with natural lighting, shadows, and textures consistent with the original scene.\n"
    "6.  **Output:** Return ONLY the final, edited image. Do not include any text, explanations, or dialogue."
)


class GeminiStylingAssistant:
    """Gemini 造型助手

    接收一张人物图和描述，为人物添加互补的衣物或配饰，完成造型。
    支持“自定义添加”优先，其次基于多项开关（外套/上衣/下装/连衣裙/鞋子/配饰）与“智能推荐”。
    """

    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        return {
            "required": {
                "图片": ("IMAGE", {"tooltip": "输入包含人物的原始图片"}),
                "自定义添加": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "tooltip": "自定义要添加的物品（填写后忽略下方所有开关）",
                    },
                ),
                "选择外套": ("BOOLEAN", {"default": False, "tooltip": "添加外套/夹克"}),
                "选择上衣": ("BOOLEAN", {"default": False, "tooltip": "添加上衣/衬衫/T恤"}),
                "选择下装": ("BOOLEAN", {"default": False, "tooltip": "添加下装/裤装"}),
                "选择连衣裙": ("BOOLEAN", {"default": False, "tooltip": "添加连衣裙"}),
                "选择鞋子": ("BOOLEAN", {"default": False, "tooltip": "添加鞋子"}),
                "选择配饰": ("BOOLEAN", {"default": False, "tooltip": "添加配饰（包/腰带/帽子等）"}),
                "智能推荐": ("BOOLEAN", {"default": True, "tooltip": "AI 智能推荐合适的单品/配饰"}),
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
    RETURN_NAMES = ("造型增强图",)
    FUNCTION = "style"
    CATEGORY = "Gemini / 造型"

    def style(self, 图片, 自定义添加: str, 选择外套: bool, 选择上衣: bool, 选择下装: bool, 选择连衣裙: bool, 选择鞋子: bool, 选择配饰: bool, 智能推荐: bool, 种子: int, 超时秒数: int, 刷新间隔秒数: int, 生成后控制: str):
        images: List[Image.Image] = tensor_to_pil_list(图片)
        if not images:
            raise RuntimeError("No input image provided.")
        img = images[0]

        # Build item description with priority: 自定义添加 > 开关项 > 智能推荐 > 透传
        custom = (自定义添加 or "").strip()
        if len(custom) > 0:
            final_desc = custom
        else:
            selected: List[str] = []
            if 选择外套:
                selected.append("a coat or jacket")
            if 选择上衣:
                selected.append("a top or shirt")
            if 选择下装:
                selected.append("bottoms such as pants or a skirt")
            if 选择连衣裙:
                selected.append("a dress")
            if 选择鞋子:
                selected.append("a pair of shoes")
            if 选择配饰:
                selected.append("an accessory such as a handbag, belt, or hat")

            if len(selected) == 0:
                if 智能推荐:
                    final_desc = "a suitable accessory or piece of clothing"
                else:
                    # No-op for stability
                    return (图片,)
            else:
                if len(selected) == 1:
                    final_desc = f"a complementary {selected[0]}"
                else:
                    list_text = ", ".join(selected[:-1]) + " and " + selected[-1]
                    final_desc = f"a complementary set consisting of {list_text}"

        prompt = PROMPT_TEMPLATE.format(item_description=final_desc)

        # Cache when seed > 0
        input_hash = hash_pil_images([img])
        model_name = get_default_image_model()
        cache_key = f"styling_assistant:{input_hash}:{final_desc}:{model_name}:{种子}"
        if 种子 > 0:
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
                j = 0
                while not stop_flag["stop"]:
                    time.sleep(刷新间隔秒数)
                    j += 1
                    elapsed = int(time.perf_counter() - start)
                    print(f"[GeminiStylingAssistant] waiting... elapsed={elapsed}s (tick {j})")

        t = threading.Thread(target=_hb, daemon=True)
        t.start()

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
            raise RuntimeError(f"Gemini Styling Assistant timed out after {超时秒数}s")
        if result["err"] is not None:
            raise RuntimeError(f"Gemini Styling Assistant error: {result['err']}")
        png_bytes = result["data"]

        if 种子 > 0:
            GLOBAL_RESULT_CACHE.set(cache_key, png_bytes)
        out_img = bytes_to_pil_image(png_bytes)
        out_tensor = pil_list_to_tensor([out_img])
        return (out_tensor,)
