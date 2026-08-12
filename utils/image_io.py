import hashlib
import io
import warnings
from typing import List

import numpy as np
from PIL import Image, UnidentifiedImageError

try:
    import torch
except Exception:  # pragma: no cover - ComfyUI provides torch
    torch = None


MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_BYTES = 48 * 1024 * 1024


def _ensure_torch_available():
    if torch is None:
        raise RuntimeError("PyTorch is required in the ComfyUI runtime but was not found.")


def _check_dimensions(width: int, height: int) -> None:
    if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
        raise ValueError(
            f"Image dimensions {width}x{height} exceed the {MAX_IMAGE_PIXELS:,}-pixel limit."
        )


def tensor_to_pil_list(image_tensor) -> List[Image.Image]:
    """Convert ComfyUI IMAGE tensor [B,H,W,C] float 0..1 to RGB PIL images."""

    _ensure_torch_available()
    if image_tensor is None:
        raise ValueError("image_tensor is None")
    if not isinstance(image_tensor, torch.Tensor):
        raise TypeError("Expected image_tensor to be a torch.Tensor")
    if image_tensor.ndim != 4 or image_tensor.shape[-1] != 3:
        raise ValueError(
            f"Expected image tensor shape [B,H,W,3], got {tuple(image_tensor.shape)}"
        )

    batch, height, width, _ = image_tensor.shape
    if batch <= 0:
        raise ValueError("Image batch is empty.")
    _check_dimensions(int(width), int(height))

    safe_tensor = image_tensor.detach().cpu().clamp(0.0, 1.0)
    np_images = (safe_tensor.numpy() * 255.0).round().astype(np.uint8)
    return [Image.fromarray(np_images[index], mode="RGB") for index in range(batch)]


def pil_list_to_tensor(images: List[Image.Image]):
    """Convert same-sized RGB PIL images to ComfyUI IMAGE tensor [B,H,W,C]."""

    _ensure_torch_available()
    if not images:
        raise ValueError("images list is empty")

    expected_size = images[0].size
    _check_dimensions(*expected_size)
    tensors = []
    for image in images:
        if not isinstance(image, Image.Image):
            raise TypeError("Every item must be a PIL.Image.Image.")
        if image.size != expected_size:
            raise ValueError("All images in a batch must have the same dimensions.")
        rgb = image.convert("RGB") if image.mode != "RGB" else image
        array = np.asarray(rgb, dtype=np.float32) / 255.0
        tensors.append(torch.from_numpy(array))
    return torch.stack(tensors, dim=0)


def pil_to_png_bytes(image: Image.Image) -> bytes:
    if not isinstance(image, Image.Image):
        raise TypeError("Expected a PIL.Image.Image.")
    _check_dimensions(*image.size)
    rgb = image.convert("RGB") if image.mode != "RGB" else image
    buffer = io.BytesIO()
    rgb.save(buffer, format="PNG")
    data = buffer.getvalue()
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"Encoded PNG exceeds the {MAX_IMAGE_BYTES:,}-byte limit.")
    return data


def bytes_to_pil_image(data: bytes) -> Image.Image:
    if not isinstance(data, bytes) or not data:
        raise ValueError("Image data must be non-empty bytes.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"Image data exceeds the {MAX_IMAGE_BYTES:,}-byte limit.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                _check_dimensions(*image.size)
                image.load()
                return image.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Image data is not a safe, decodable image.") from exc


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_pil_image(image: Image.Image) -> str:
    return sha256_bytes(pil_to_png_bytes(image))


def hash_pil_images(images: List[Image.Image]) -> str:
    hasher = hashlib.sha256()
    for image in images:
        payload = pil_to_png_bytes(image)
        hasher.update(len(payload).to_bytes(8, "big"))
        hasher.update(payload)
    return hasher.hexdigest()
