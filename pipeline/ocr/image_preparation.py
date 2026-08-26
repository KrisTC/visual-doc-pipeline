"""Prepare source images for OCR providers that require opaque RGB pixels."""

from __future__ import annotations

from typing import TypeAlias

from PIL import Image


RgbColour: TypeAlias = tuple[int, int, int]
DEFAULT_OCR_BACKGROUND: RgbColour = (255, 255, 255)


def opaque_rgb_for_ocr(
    image: Image.Image, background: RgbColour = DEFAULT_OCR_BACKGROUND
) -> Image.Image:
    """Return an opaque RGB OCR copy without changing ``image``.

    Palette transparency can be represented as a byte sequence. Pillow correctly
    expands that representation when converting to RGBA, but warns if it is
    converted directly to RGB because the alpha values would be discarded.
    """
    if not _has_transparency(image):
        return image.convert("RGB")

    rgba = image.convert("RGBA")
    if rgba.getchannel("A").getextrema() == (255, 255):
        return rgba.convert("RGB")
    flattened = Image.new("RGBA", image.size, (*background, 255))
    flattened.alpha_composite(rgba)
    return flattened.convert("RGB")


def _has_transparency(image: Image.Image) -> bool:
    return "transparency" in image.info or "A" in image.getbands()
