"""
ComfyUI Plugin: comfyui-fuzhuang2-jingxun

Provides custom nodes powered by Google Gemini for virtual try-on workflows:
- Gemini Model Generator
- Gemini Virtual Try-On
- Gemini Pose Variation
- Gemini Garment Processor

Environment variable for API key:
- GOOGLE_API_KEY (preferred) or GEMINI_API_KEY
"""

from .nodes.node_gemini_model_generator import GeminiModelGenerator
from .nodes.node_gemini_virtual_tryon import GeminiVirtualTryOn
from .nodes.node_gemini_pose_variation import GeminiPoseVariation
from .nodes.node_gemini_garment_processor import GeminiGarmentProcessor
from .nodes.node_gemini_advanced_recolor import GeminiAdvancedRecolor
from .nodes.node_gemini_styling_assistant import GeminiStylingAssistant
from .nodes.node_gemini_occasion_stylist import GeminiOccasionStylist


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


