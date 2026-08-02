"""OCR text-region colour estimation."""

from pipeline.text_region_colours.estimator import estimate_text_region_colours
from pipeline.text_region_colours.models import (
    BackgroundKind,
    RgbaColour,
    TextRegionColourEstimate,
)

__all__ = [
    "BackgroundKind",
    "RgbaColour",
    "TextRegionColourEstimate",
    "estimate_text_region_colours",
]
