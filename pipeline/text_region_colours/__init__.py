"""OCR text-region colour estimation."""

from pipeline.text_region_colours.estimator import estimate_text_region_colours
from pipeline.text_region_colours.models import (
    BackgroundKind,
    RgbaColour,
    TextRegionColourEstimate,
)
from pipeline.text_region_colours.replacement import estimate_replacement_colours

__all__ = [
    "BackgroundKind",
    "RgbaColour",
    "TextRegionColourEstimate",
    "estimate_replacement_colours",
    "estimate_text_region_colours",
]
