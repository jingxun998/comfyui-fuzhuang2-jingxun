from __future__ import annotations

import importlib
import io

import pytest
from PIL import Image


PNG_BUFFER = io.BytesIO()
Image.new("RGB", (12, 10), (10, 20, 30)).save(PNG_BUFFER, format="PNG")
PNG = PNG_BUFFER.getvalue()
SENTINEL = object()


CASES = [
    ("node_gemini_model_generator", "GeminiModelGenerator", "generate", (object(), 0, 5, 0), 1),
    ("node_gemini_virtual_tryon", "GeminiVirtualTryOn", "tryon", (object(), object(), 0, 5, 0), 2),
    (
        "node_gemini_pose_variation",
        "GeminiPoseVariation",
        "repose",
        (object(), "front_straight", "", 0, 5, 0),
        1,
    ),
    (
        "node_gemini_garment_processor",
        "GeminiGarmentProcessor",
        "process",
        (object(), True, False, False, 0, 5, 0),
        1,
    ),
    (
        "node_gemini_advanced_recolor",
        "GeminiAdvancedRecolor",
        "process",
        (object(), "red", "", False, True, False, False, False, False, False, 0, 5, 0),
        1,
    ),
    (
        "node_gemini_styling_assistant",
        "GeminiStylingAssistant",
        "style",
        (object(), "add a belt", False, False, False, False, False, False, False, 0, 5, 0, "fixed"),
        1,
    ),
    (
        "node_gemini_occasion_stylist",
        "GeminiOccasionStylist",
        "style",
        (object(), "gallery opening", False, False, False, False, False, False, 0, 5, 0, "fixed"),
        1,
    ),
]


@pytest.mark.parametrize("module_name,class_name,method_name,args,image_count", CASES)
def test_each_node_executes_with_original_interface(
    plugin,
    monkeypatch,
    module_name,
    class_name,
    method_name,
    args,
    image_count,
):
    module = importlib.import_module(plugin.__name__ + ".nodes." + module_name)
    calls = []
    pil = Image.new("RGB", (12, 10))

    monkeypatch.setattr(module, "tensor_to_pil_list", lambda value: [pil])
    monkeypatch.setattr(module, "hash_pil_images", lambda images: "input-hash")
    monkeypatch.setattr(module, "get_default_image_model", lambda: "gemini-test-image")
    monkeypatch.setattr(module, "bytes_to_pil_image", lambda data: pil)
    monkeypatch.setattr(module, "pil_list_to_tensor", lambda images: SENTINEL)

    def fake_call(**kwargs):
        calls.append(kwargs)
        return PNG

    monkeypatch.setattr(module, "call_gemini_generate_image", fake_call)
    instance = getattr(module, class_name)()
    result = getattr(instance, method_name)(*args)

    assert result == (SENTINEL,)
    assert len(calls) == 1
    assert calls[0]["model"] == "gemini-test-image"
    assert len(calls[0]["images"]) == image_count
