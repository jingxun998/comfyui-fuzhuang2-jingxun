from __future__ import annotations

import importlib
import io

import pytest
from PIL import Image


torch = pytest.importorskip("torch")

BUFFER = io.BytesIO()
Image.new("RGB", (16, 12), (90, 80, 70)).save(BUFFER, format="PNG")
PNG = BUFFER.getvalue()
INPUT = torch.zeros((1, 12, 16, 3), dtype=torch.float32)

CASES = [
    ("node_gemini_model_generator", "GeminiModelGenerator", "generate", (INPUT, 0, 5, 0), 1),
    ("node_gemini_virtual_tryon", "GeminiVirtualTryOn", "tryon", (INPUT, INPUT, 0, 5, 0), 2),
    ("node_gemini_pose_variation", "GeminiPoseVariation", "repose", (INPUT, "front_straight", "", 0, 5, 0), 1),
    ("node_gemini_garment_processor", "GeminiGarmentProcessor", "process", (INPUT, True, False, False, 0, 5, 0), 1),
    (
        "node_gemini_advanced_recolor",
        "GeminiAdvancedRecolor",
        "process",
        (INPUT, "blue", "", False, True, False, False, False, False, False, 0, 5, 0),
        1,
    ),
    (
        "node_gemini_styling_assistant",
        "GeminiStylingAssistant",
        "style",
        (INPUT, "add a belt", False, False, False, False, False, False, False, 0, 5, 0, "fixed"),
        1,
    ),
    (
        "node_gemini_occasion_stylist",
        "GeminiOccasionStylist",
        "style",
        (INPUT, "gallery opening", False, False, False, False, False, False, 0, 5, 0, "fixed"),
        1,
    ),
]


@pytest.mark.parametrize("module_name,class_name,method_name,args,image_count", CASES)
def test_real_tensor_conversion_with_mocked_remote_api(
    plugin, monkeypatch, module_name, class_name, method_name, args, image_count
):
    module = importlib.import_module(plugin.__name__ + ".nodes." + module_name)
    calls = []

    def fake_call(**kwargs):
        calls.append(kwargs)
        return PNG

    monkeypatch.setattr(module, "call_gemini_generate_image", fake_call)
    monkeypatch.setattr(module, "get_default_image_model", lambda: "gemini-test-image")
    output = getattr(getattr(module, class_name)(), method_name)(*args)[0]

    assert tuple(output.shape) == (1, 12, 16, 3)
    assert output.dtype == torch.float32
    assert len(calls) == 1
    assert len(calls[0]["images"]) == image_count
