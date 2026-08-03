"""Shared path and in-memory processing for every supported raster bitmap."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import skia  # type: ignore[import-not-found]
from PIL import Image

from pipeline.folder_replacement.common import TEXT_REPLACEMENT_MINIMUM_CONFIDENCE
from pipeline.ocr import OcrProvider, OcrRequest
from pipeline.text_region_colours import estimate_text_region_colours
from pipeline.text_region_rendering import TextRegionReplacement, replace_text_regions
from pipeline.text_replacement import TextReplacementProvider, TextReplacementRequest


def replace_bitmap_file(source: Path, destination: Path, ocr: OcrProvider, replacement: TextReplacementProvider, source_language: str, target_language: str, typeface: skia.Typeface) -> int:
    with Image.open(source) as opened:
        image, format_name = opened.copy(), opened.format
    if format_name is None: raise ValueError(f"Could not determine bitmap format: {source}")
    count = replace_image(image, ocr, replacement, source_language, target_language, typeface)
    image.save(destination, format=format_name)
    return count

def replace_bitmap_bytes(data: bytes, ocr: OcrProvider, replacement: TextReplacementProvider, source_language: str, target_language: str, typeface: skia.Typeface) -> tuple[bytes, int]:
    with Image.open(BytesIO(data)) as opened:
        image, format_name = opened.copy(), opened.format
    if format_name is None: raise ValueError("Could not determine embedded bitmap format.")
    count = replace_image(image, ocr, replacement, source_language, target_language, typeface)
    output = BytesIO(); image.save(output, format=format_name)
    return output.getvalue(), count

def replace_image(image: Image.Image, ocr: OcrProvider, replacement: TextReplacementProvider, source_language: str, target_language: str, typeface: skia.Typeface) -> int:
    prepared: list[TextRegionReplacement] = []
    for item in ocr.recognize(OcrRequest(image, source_language)).text_items:
        if item.confidence < TEXT_REPLACEMENT_MINIMUM_CONFIDENCE: continue
        text = replacement.replace(TextReplacementRequest(item.text, False, source_language, target_language)).text
        prepared.append(TextRegionReplacement(item, estimate_text_region_colours(image, item), text))
    replace_text_regions(image, prepared, typeface, target_language)
    return len(prepared)
