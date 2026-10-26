"""Synthetic tests for page-colour aware replacement colours."""

from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pipeline.ocr.models import BoundingPolygon, OcrText, PixelPoint
from pipeline.text_region_colours import RgbaColour, estimate_replacement_colours
from pipeline.text_region_rendering.renderer import _render_text_colour

_FONT_PATH = Path(__file__).parent / "assets" / "fonts" / "NotoSansJP[wght].ttf"
_REGION = OcrText(
    "Test",
    1.0,
    BoundingPolygon(
        (PixelPoint(50, 20), PixelPoint(190, 20), PixelPoint(190, 80), PixelPoint(50, 80))
    ),
)


class ReplacementColourTests(unittest.TestCase):
    # Verifies FR-2026-10-26-01.
    def test_transparent_background_keeps_alpha_zero_and_text_is_the_opaque_glyph_colour(
        self,
    ) -> None:
        image = _transparent_image((44, 44, 44, 255))
        alpha = np.asarray(image)[:, :, 3]
        fringe = (alpha > 0) & (alpha < 255)
        pixels = np.array(image)
        pixels[fringe, :3] = (0, 0, 56)
        pixels[alpha == 0, :3] = (0, 0, 0)

        estimate = estimate_replacement_colours(Image.fromarray(pixels, "RGBA"), [_REGION])[0]

        self.assertEqual(0, estimate.background_colour.alpha)
        self.assertEqual(255, estimate.text_colour.alpha)
        _assert_near(self, estimate.text_colour, (44, 44, 44))

    # Verifies FR-2026-10-26-01.
    def test_opaque_background_is_wiped_with_its_observed_colour(self) -> None:
        image = _transparent_image((20, 20, 20, 255))
        ImageDraw.Draw(image).rectangle((40, 10, 200, 90), fill=(200, 230, 255, 255))
        ImageDraw.Draw(image).text(
            (70, 24), "Test", font=ImageFont.truetype(_FONT_PATH, size=38), fill=(20, 20, 20, 255)
        )

        estimate = estimate_replacement_colours(image, [_REGION])[0]

        self.assertEqual(RgbaColour(200, 230, 255, 255), estimate.background_colour)
        self.assertEqual(255, estimate.text_colour.alpha)

    # Verifies FR-2026-10-26-01.
    def test_estimates_text_against_a_non_white_page_colour(self) -> None:
        image = _transparent_image((240, 240, 240, 255))

        on_white = estimate_replacement_colours(image, [_REGION])[0]
        on_dark = estimate_replacement_colours(image, [_REGION], (20, 20, 20))[0]

        self.assertEqual(0, on_dark.background_colour.alpha)
        _assert_near(self, on_dark.text_colour, (240, 240, 240))
        # Light glyphs on a white page are not distinguishable, so the fallback applies.
        self.assertEqual(RgbaColour(0, 0, 0), on_white.text_colour)

    # Verifies FR-2026-10-26-01.
    def test_low_confidence_text_on_the_page_colour_uses_high_contrast(self) -> None:
        empty = Image.new("RGBA", (240, 100), (0, 0, 0, 0))

        on_light = estimate_replacement_colours(empty, [_REGION], (250, 250, 250))[0]
        on_dark = estimate_replacement_colours(empty, [_REGION], (20, 20, 20))[0]

        self.assertLess(on_light.text_colour_confidence, 0.6)
        self.assertEqual(RgbaColour(0, 0, 0), on_light.text_colour)
        self.assertEqual(RgbaColour(255, 255, 255), on_dark.text_colour)

    # Verifies FR-2026-10-26-01.
    def test_low_confidence_text_on_another_background_is_unchanged(self) -> None:
        panel = Image.new("RGBA", (240, 100), (120, 160, 90, 255))

        estimate = estimate_replacement_colours(panel, [_REGION])[0]

        self.assertLess(estimate.text_colour_confidence, 0.6)
        self.assertEqual(RgbaColour(120, 160, 90, 255), estimate.text_colour)

    # Verifies FR-2026-10-26-01.
    def test_lightness_boost_judges_a_transparent_background_against_the_page(self) -> None:
        text = RgbaColour(207, 215, 235)
        transparent = RgbaColour(0, 0, 0, 0)

        self.assertGreater(
            _render_text_colour(text, transparent, (20, 20, 20)).red, text.red
        )
        self.assertEqual(text, _render_text_colour(text, transparent, (255, 255, 255)))
        self.assertEqual(text, _render_text_colour(text, transparent))


def _transparent_image(text_colour: tuple[int, int, int, int]) -> Image.Image:
    image = Image.new("RGBA", (240, 100), (0, 0, 0, 0))
    ImageDraw.Draw(image).text(
        (70, 24), "Test", font=ImageFont.truetype(_FONT_PATH, size=38), fill=text_colour
    )
    return image


def _assert_near(
    test_case: unittest.TestCase,
    actual: RgbaColour,
    expected: tuple[int, int, int],
    *,
    tolerance: int = 16,
) -> None:
    for actual_value, expected_value in zip(
        (actual.red, actual.green, actual.blue), expected, strict=True
    ):
        test_case.assertLessEqual(abs(actual_value - expected_value), tolerance)
