from typing import Any, Dict, List

from PIL import Image

from ..gemini_client import (
    GeminiAPIError,
    call_gemini_generate_image,
    get_default_image_model,
)
from ..utils.image_io import tensor_to_pil_list, bytes_to_pil_image, pil_list_to_tensor, hash_pil_images
import threading
import time
from ..utils.result_cache import GLOBAL_RESULT_CACHE




class GeminiPoseVariation:
    """ComfyUI node: Gemini 姿势变换器（高级版，中文 UI）

    Inputs:
      - 输入图片 (IMAGE)
      - 姿势预设 (STRING dropdown, 中文标签)
      - 自定义姿势 (STRING)
      - 种子 (INT)
    Outputs:
      - 变换姿势图 (IMAGE)
    """

    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        return {
            "required": {
                "输入图片": ("IMAGE", {"tooltip": "输入一张包含人物与服装的图片"}),
                "姿势预设": (
                    "STRING",
                    {
                        "default": "微微转身，3/4 视角",
                        "choices": [
                            "正面视角，双手叉腰",
                            "微微转身，3/4 视角",
                            "侧面轮廓视角",
                            "腾空跳跃，动作定格",
                            "朝向相机行走",
                            "倚靠墙面",
                        ],
                        "tooltip": "从下拉列表中快速选择一个常用姿势",
                        "ui": {"type": "combo"}
                    },
                ),
                "自定义姿势": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "tooltip": "自定义姿势描述（优先级高于预设；留空则使用预设）",
                    },
                ),
                "种子": ("INT", {"default": 0, "min": 0, "max": 2**31 - 1, "tooltip": "种子>0固定并缓存；0表示每次随机"}),
                "超时秒数": ("INT", {"default": 60, "min": 5, "max": 600, "tooltip": "请求超时自动终止（秒）"}),
                "刷新间隔秒数": ("INT", {"default": 5, "min": 0, "max": 60, "tooltip": "控制台刷新/心跳频率；0 表示关闭"}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("变换姿势图",)
    FUNCTION = "repose"
    CATEGORY = "Gemini / 姿势"

    def repose(self, 输入图片, 姿势预设: str, 自定义姿势: str, 种子: int, 超时秒数: int, 刷新间隔秒数: int):
        images: List[Image.Image] = tensor_to_pil_list(输入图片)
        if not images:
            raise RuntimeError("No source image provided.")
        img = images[0]

        # Map Chinese labels to concise English instructions for the API
        zh_to_en = {
            "正面视角，双手叉腰": "Full frontal view, hands on hips",
            "微微转身，3/4 视角": "Slightly turned, 3/4 view",
            "侧面轮廓视角": "Side profile view",
            "腾空跳跃，动作定格": "Jumping in the air, mid-action shot",
            "朝向相机行走": "Walking towards camera",
            "倚靠墙面": "Leaning against a wall",
        }

        # Priority: 自定义姿势 > 预设（映射到英文）
        custom = (自定义姿势 or "").strip()
        pose_text = custom if len(custom) > 0 else zh_to_en.get(姿势预设, 姿势预设)

        prompt = (
            f"You are an expert fashion photographer AI. Take this image and regenerate it from a different perspective. "
            f"The person, clothing, and background style must remain identical. The new perspective should be: \"{pose_text}\". "
            f"Return ONLY the final image."
        )

        input_hash = hash_pil_images([img])
        model_name = get_default_image_model()
        cache_key = f"pose_variation:{input_hash}:{pose_text}:{model_name}:{种子}"
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
                n = 0
                while not stop_flag["stop"]:
                    time.sleep(刷新间隔秒数)
                    n += 1
                    elapsed = int(time.perf_counter() - start)
                    print(f"[GeminiPoseVariation] waiting... elapsed={elapsed}s (tick {n})")

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
            raise RuntimeError(f"Gemini Pose Variation timed out after {超时秒数}s")
        if result["err"] is not None:
            raise RuntimeError(f"Gemini Pose Variation error: {result['err']}")
        png_bytes = result["data"]

        if 种子 > 0:
            GLOBAL_RESULT_CACHE.set(cache_key, png_bytes)
        out_img = bytes_to_pil_image(png_bytes)
        out_tensor = pil_list_to_tensor([out_img])
        return (out_tensor,)
