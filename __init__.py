"""Fuzhuang2 Jingxun: Gemini-powered fashion image nodes for ComfyUI.

The package exposes seven nodes while keeping the original class names and
Chinese input fields stable for existing workflows.
"""

# Some test runners import a custom-node root as the top-level module
# ``__init__``. A repository folder may contain hyphens, so establish a stable
# synthetic package name before resolving the relative imports. ComfyUI's normal
# package loader already provides ``__package__`` and does not use this branch.
if not __package__:
    import sys as _sys
    from importlib.machinery import ModuleSpec as _ModuleSpec
    from pathlib import Path as _Path

    __package__ = "fuzhuang2_jingxun_runtime"
    __path__ = [str(_Path(__file__).resolve().parent)]
    __spec__ = _ModuleSpec(__package__, loader=None, is_package=True)
    __spec__.submodule_search_locations = __path__
    _sys.modules.setdefault(__package__, _sys.modules[__name__])

from .nodes.node_gemini_advanced_recolor import GeminiAdvancedRecolor
from .nodes.node_gemini_garment_processor import GeminiGarmentProcessor
from .nodes.node_gemini_model_generator import GeminiModelGenerator
from .nodes.node_gemini_occasion_stylist import GeminiOccasionStylist
from .nodes.node_gemini_pose_variation import GeminiPoseVariation
from .nodes.node_gemini_styling_assistant import GeminiStylingAssistant
from .nodes.node_gemini_virtual_tryon import GeminiVirtualTryOn

__version__ = "0.1.0"

NODE_CLASS_MAPPINGS = {
    "GeminiModelGenerator": GeminiModelGenerator,
    "GeminiVirtualTryOn": GeminiVirtualTryOn,
    "GeminiPoseVariation": GeminiPoseVariation,
    "GeminiGarmentProcessor": GeminiGarmentProcessor,
    "GeminiAdvancedRecolor": GeminiAdvancedRecolor,
    "GeminiStylingAssistant": GeminiStylingAssistant,
    "GeminiOccasionStylist": GeminiOccasionStylist,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "GeminiModelGenerator": "Gemini 模特生成器",
    "GeminiVirtualTryOn": "Gemini 虚拟试衣",
    "GeminiPoseVariation": "Gemini 姿势变换器",
    "GeminiGarmentProcessor": "Gemini 服装处理器",
    "GeminiAdvancedRecolor": "Gemini 高级调色盘",
    "GeminiStylingAssistant": "Gemini 造型助手",
    "GeminiOccasionStylist": "Gemini 场合造型师",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
