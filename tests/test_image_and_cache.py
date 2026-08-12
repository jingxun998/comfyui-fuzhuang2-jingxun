import io

import pytest
from PIL import Image


def modules(plugin):
    import sys

    return (
        sys.modules[plugin.__name__ + ".utils.image_io"],
        sys.modules[plugin.__name__ + ".utils.result_cache"],
    )


def test_image_round_trip_and_invalid_data(plugin):
    image_io, _ = modules(plugin)
    source = Image.new("RGB", (9, 7), (1, 2, 3))
    data = image_io.pil_to_png_bytes(source)
    restored = image_io.bytes_to_pil_image(data)
    assert restored.size == (9, 7)
    assert restored.mode == "RGB"
    with pytest.raises(ValueError, match="safe, decodable image"):
        image_io.bytes_to_pil_image(b"not an image")


def test_cache_enforces_total_size(plugin):
    _, cache_module = modules(plugin)
    cache = cache_module.ResultCache(max_items=3, max_bytes=5, max_item_bytes=4)
    cache.set("a", b"12")
    cache.set("b", b"34")
    cache.set("c", b"56")
    assert cache.get("a") is None
    assert cache.stats()["bytes"] <= 5
    cache.set("too-big", b"12345")
    assert cache.get("too-big") is None
