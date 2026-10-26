"""Replacement-text colours for images that may be transparent."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from PIL import Image

from pipeline.ocr.image_preparation import DEFAULT_OCR_BACKGROUND, RgbColour, opaque_rgb_for_ocr
from pipeline.ocr.models import OcrText
from pipeline.text_region_colours.estimator import estimate_text_region_colours
from pipeline.text_region_colours.models import RgbaColour, TextRegionColourEstimate

LOW_TEXT_COLOUR_CONFIDENCE = 0.60


def relative_luminance(colour: RgbaColour) -> float:
    """Return WCAG relative luminance of the colour's RGB channels."""
    channels = (colour.red / 255.0, colour.green / 255.0, colour.blue / 255.0)
    linear_channels = tuple(
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    )
    return (
        (0.2126 * linear_channels[0])
        + (0.7152 * linear_channels[1])
        + (0.0722 * linear_channels[2])
    )


def estimate_replacement_colours(
    image: Image.Image,
    text_regions: Sequence[OcrText],
    page_colour: RgbColour = DEFAULT_OCR_BACKGROUND,
) -> list[TextRegionColourEstimate]:
    """Estimate wipe and text colours for replacing ``text_regions`` in ``image``.

    The wipe colour is the background observed in ``image``, so a transparent cell
    stays transparent. The text colour is estimated from a copy composited onto
    ``page_colour``, which is what a viewer sees, and is always opaque. When that
    estimate is unreliable and the background shows the page colour, the text colour
    is black or white, whichever contrasts more with the page colour.
    """
    visible = _visible_image(image, page_colour)
    return [
        _estimate_region(image, visible, region, page_colour) for region in text_regions
    ]


def _estimate_region(
    image: Image.Image,
    visible: Image.Image | None,
    region: OcrText,
    page_colour: RgbColour,
) -> TextRegionColourEstimate:
    observed = estimate_text_region_colours(image, region)
    text_estimate = observed if visible is None else estimate_text_region_colours(visible, region)
    return _replacement_estimate(observed, text_estimate, page_colour)


def _visible_image(image: Image.Image, page_colour: RgbColour) -> Image.Image | None:
    """Return ``image`` composited onto the page colour, or None if it is fully opaque."""
    if "A" not in image.getbands() and "transparency" not in image.info:
        return None
    if image.convert("RGBA").getchannel("A").getextrema()[0] == 255:
        return None
    return opaque_rgb_for_ocr(image, page_colour)


def _replacement_estimate(
    observed: TextRegionColourEstimate,
    text_estimate: TextRegionColourEstimate,
    page_colour: RgbColour,
) -> TextRegionColourEstimate:
    text_colour = replace(text_estimate.text_colour, alpha=255)
    background = observed.background_colour
    if text_estimate.text_colour_confidence < LOW_TEXT_COLOUR_CONFIDENCE and _shows_page_colour(
        background, page_colour
    ):
        text_colour = _high_contrast_colour(page_colour)
    return TextRegionColourEstimate(
        text_colour=text_colour,
        background_colour=background,
        text_colour_confidence=text_estimate.text_colour_confidence,
        background_colour_confidence=observed.background_colour_confidence,
        background_kind=observed.background_kind,
    )


def _shows_page_colour(background: RgbaColour, page_colour: RgbColour) -> bool:
    if background.alpha == 0:
        return True
    return background.alpha == 255 and (
        background.red,
        background.green,
        background.blue,
    ) == page_colour


def _high_contrast_colour(page_colour: RgbColour) -> RgbaColour:
    """Return opaque black or white, whichever has the higher WCAG contrast with the page."""
    page_luminance = relative_luminance(RgbaColour(*page_colour))
    black_contrast = (page_luminance + 0.05) / 0.05
    white_contrast = 1.05 / (page_luminance + 0.05)
    return RgbaColour(0, 0, 0) if black_contrast >= white_contrast else RgbaColour(255, 255, 255)
