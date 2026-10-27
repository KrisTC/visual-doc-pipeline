"""Skia-backed visible-text rendering into OCR text regions."""

from pipeline.text_region_rendering.renderer import (
    SkippedTextRegion,
    TextRegionReplacement,
    render_replacement_text,
    replace_text_region,
    replace_text_regions,
    wipe_text_region_background,
)

__all__ = [
    "SkippedTextRegion",
    "TextRegionReplacement",
    "render_replacement_text",
    "replace_text_region",
    "replace_text_regions",
    "wipe_text_region_background",
]
