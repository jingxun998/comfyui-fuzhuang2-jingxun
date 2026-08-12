from pathlib import Path


EXPECTED = {
    "GeminiModelGenerator": ("generate", ("模特图",), "Gemini / Fuzhuang"),
    "GeminiVirtualTryOn": ("tryon", ("试穿图",), "Gemini / 服装"),
    "GeminiPoseVariation": ("repose", ("变换姿势图",), "Gemini / 姿势"),
    "GeminiGarmentProcessor": ("process", ("清洗后服装图",), "Gemini / 服装"),
    "GeminiAdvancedRecolor": ("process", ("重新着色图",), "Gemini/Image"),
    "GeminiStylingAssistant": ("style", ("造型增强图",), "Gemini / 造型"),
    "GeminiOccasionStylist": ("style", ("场合造型图",), "Gemini / 场合"),
}


def test_all_original_node_identifiers_are_preserved(plugin):
    assert set(plugin.NODE_CLASS_MAPPINGS) == set(EXPECTED)
    for identifier, (function, return_names, category) in EXPECTED.items():
        cls = plugin.NODE_CLASS_MAPPINGS[identifier]
        assert cls.FUNCTION == function
        assert cls.RETURN_NAMES == return_names
        assert cls.RETURN_TYPES == ("IMAGE",)
        assert cls.CATEGORY == category


def test_source_is_public_not_hidden_in_zip():
    root = Path(__file__).resolve().parents[1]
    assert len(list((root / "nodes").glob("node_*.py"))) == 7
    assert (root / "utils" / "image_io.py").is_file()
    assert (root / "utils" / "result_cache.py").is_file()
    assert not (root / "comfyui-fuzhuang2-jingxun.zip").exists()
    assert not (root / "gemini_config.json").exists()
