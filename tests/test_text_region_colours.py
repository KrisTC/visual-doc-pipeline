"""Synthetic tests for OCR text-region colour estimation."""

from __future__ import annotations

from math import cos, radians, sin
from pathlib import Path
import unittest

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pipeline.ocr.models import BoundingPolygon, OcrText, PixelPoint
from pipeline.text_region_colours import (
    BackgroundKind,
    RgbaColour,
    TextRegionColourEstimate,
    estimate_text_region_colours,
)

_FONT_PATH = Path(__file__).parent / "assets" / "fonts" / "NotoSansJP[wght].ttf"


class TextRegionColourModelTests(unittest.TestCase):
    # Verifies FR-2026-08-02-09.
    def test_models_reject_invalid_channel_and_confidence_values(self) -> None:
        with self.assertRaises(ValueError):
            RgbaColour(256, 0, 0)
        with self.assertRaises(ValueError):
            TextRegionColourEstimate(
                RgbaColour(0, 0, 0), RgbaColour(255, 255, 255), -0.1, 1.0, BackgroundKind.FLAT
            )

    # Verifies FR-2026-08-02-09.
    def test_public_models_document_colour_encoding_and_confidence_meaning(self) -> None:
        self.assertIn("non-premultiplied", RgbaColour.__doc__ or "")
        self.assertIn("0 through 255", RgbaColour.__doc__ or "")
        self.assertIn("probability nor OCR confidence", TextRegionColourEstimate.__doc__ or "")
        self.assertNotIn("outline_colour", TextRegionColourEstimate.__dataclass_fields__)
        self.assertNotIn("shadow_colour", TextRegionColourEstimate.__dataclass_fields__)


class TextRegionColourEstimatorTests(unittest.TestCase):
    # Verifies FR-2026-08-02-09.
    def test_estimates_antialiased_light_text_on_a_flat_dark_background(self) -> None:
        image, region = _text_image(
            background=(31, 78, 121, 255), text=(255, 255, 255, 255)
        )

        estimate = estimate_text_region_colours(image, region)

        _assert_colour_near(self, estimate.text_colour, (255, 255, 255, 255))
        _assert_colour_near(self, estimate.background_colour, (31, 78, 121, 255))
        self.assertEqual(BackgroundKind.FLAT, estimate.background_kind)
        self.assertGreater(estimate.text_colour_confidence, 0.6)
        self.assertGreater(estimate.background_colour_confidence, 0.8)

    # Verifies FR-2026-08-02-09.
    def test_estimates_dark_text_with_a_rotated_ocr_polygon(self) -> None:
        image, region = _text_image(
            background=(255, 242, 204, 255), text=(31, 31, 31, 255), angle=18.0
        )

        estimate = estimate_text_region_colours(image, region)

        _assert_colour_near(self, estimate.text_colour, (31, 31, 31, 255))
        _assert_colour_near(self, estimate.background_colour, (255, 242, 204, 255))

    # Verifies FR-2026-08-02-09.
    def test_classifies_a_smooth_local_gradient(self) -> None:
        width, height = 240, 100
        pixels = np.zeros((height, width, 4), dtype=np.uint8)
        for column in range(width):
            pixels[:, column] = (80 + column // 4, 150, 210 - column // 5, 255)
        image = Image.fromarray(pixels, "RGBA")
        image, region = _draw_text(image, (255, 255, 255, 255))

        estimate = estimate_text_region_colours(image, region)

        _assert_colour_near(self, estimate.text_colour, (255, 255, 255, 255))
        self.assertEqual(BackgroundKind.GRADIENT, estimate.background_kind)

    # Verifies FR-2026-08-02-09.
    def test_classifies_a_patterned_background_as_complex(self) -> None:
        width, height = 240, 100
        pixels = np.zeros((height, width, 4), dtype=np.uint8)
        for row in range(height):
            for column in range(width):
                pixels[row, column] = (
                    60 if (row // 8 + column // 8) % 2 else 180,
                    120,
                    80 if (row // 8 + column // 8) % 2 else 180,
                    255,
                )
        image = Image.fromarray(pixels, "RGBA")
        image, region = _draw_text(image, (10, 10, 10, 255))

        estimate = estimate_text_region_colours(image, region)

        _assert_colour_near(self, estimate.text_colour, (10, 10, 10, 255))
        self.assertEqual(BackgroundKind.COMPLEX, estimate.background_kind)

    # Verifies FR-2026-08-02-09.
    def test_estimates_dark_thin_text_on_a_high_variation_background(self) -> None:
        width, height = 240, 100
        pixels = np.zeros((height, width, 4), dtype=np.uint8)
        for row in range(height):
            for column in range(width):
                # Independent deterministic channel variation models a complex map
                # surface without relying on a real image fixture.
                red_variation = ((column * 17 + row * 31) % 101) - 50
                green_variation = ((column * 43 + row * 7) % 101) - 50
                blue_variation = ((column * 11 + row * 29) % 101) - 50
                pixels[row, column] = (
                    max(0, min(255, 135 + red_variation * 40 // 50)),
                    max(0, min(255, 205 + green_variation * 40 // 50)),
                    max(0, min(255, 220 + blue_variation * 40 // 50)),
                    255,
                )
        image = Image.fromarray(pixels, "RGBA")
        font = ImageFont.truetype(_FONT_PATH, size=20)
        ImageDraw.Draw(image).text((85, 36), "IIII", font=font, fill=(45, 48, 52, 255))
        region = OcrText(
            "IIII",
            1.0,
            BoundingPolygon(
                (
                    PixelPoint(70, 30),
                    PixelPoint(180, 30),
                    PixelPoint(180, 65),
                    PixelPoint(70, 65),
                )
            ),
        )

        estimate = estimate_text_region_colours(image, region)

        self.assertLess(estimate.text_colour.red, estimate.background_colour.red)
        self.assertLess(estimate.text_colour.green, estimate.background_colour.green)
        self.assertLess(estimate.text_colour.blue, estimate.background_colour.blue)
        self.assertGreater(estimate.text_colour_confidence, 0.4)

    # Verifies FR-2026-08-02-09.
    def test_prefers_thin_dark_text_over_a_lower_contrast_fill_component(self) -> None:
        image = Image.new("RGBA", (240, 100), (133, 206, 224, 255))
        draw = ImageDraw.Draw(image)
        # This compact, pale component has a thicker interior than the glyphs but
        # insufficient contrast to be the text colour.
        draw.rectangle((95, 35, 145, 38), fill=(201, 243, 220, 255))
        font = ImageFont.truetype(_FONT_PATH, size=20)
        draw.text((85, 36), "IIII", font=font, fill=(43, 44, 48, 255))
        region = OcrText(
            "IIII",
            1.0,
            BoundingPolygon(
                (
                    PixelPoint(70, 30),
                    PixelPoint(180, 30),
                    PixelPoint(180, 65),
                    PixelPoint(70, 65),
                )
            ),
        )

        estimate = estimate_text_region_colours(image, region)

        self.assertLess(estimate.text_colour.red, 100)
        self.assertLess(estimate.text_colour.green, 100)
        self.assertLess(estimate.text_colour.blue, 100)
        self.assertGreater(estimate.text_colour_confidence, 0.4)

    # Verifies FR-2026-08-02-09.
    def test_handles_text_and_background_alpha_values(self) -> None:
        image = Image.new("RGBA", (240, 100), (220, 230, 240, 96))
        image, region = _draw_text(image, (20, 40, 60, 220))

        estimate = estimate_text_region_colours(image, region)

        # Alpha compositing makes the observed text pixel differ from the source
        # layer's raw RGBA colour; this estimator intentionally reports the image's
        # visible stored colour rather than attempting background reconstruction.
        _assert_colour_near(self, estimate.text_colour, (31, 51, 70, 233))
        _assert_colour_near(self, estimate.background_colour, (220, 230, 240, 96))

    # Verifies FR-2026-08-02-09.
    def test_estimates_text_fill_when_an_outline_is_present(self) -> None:
        image, region = _text_image(
            background=(86, 145, 111, 255),
            text=(255, 255, 255, 255),
            outline=(0, 0, 0, 255),
        )

        estimate = estimate_text_region_colours(image, region)

        _assert_colour_near(self, estimate.text_colour, (255, 255, 255, 255))

    # Verifies FR-2026-08-02-09.
    def test_estimates_text_fill_when_a_shadow_is_present(self) -> None:
        image, region = _text_image(
            background=(235, 225, 190, 255),
            text=(30, 30, 30, 255),
            shadow=(130, 130, 130, 255),
        )

        estimate = estimate_text_region_colours(image, region)

        _assert_colour_near(self, estimate.text_colour, (30, 30, 30, 255))

    # Verifies FR-2026-08-02-09.
    def test_uses_a_strong_label_panel_as_the_immediate_background(self) -> None:
        image = Image.new("RGBA", (240, 100), (180, 225, 190, 255))
        ImageDraw.Draw(image).rectangle((55, 20, 185, 75), fill=(56, 119, 198, 255))
        image, region = _draw_text(image, (255, 255, 255, 255))

        estimate = estimate_text_region_colours(image, region)

        _assert_colour_near(self, estimate.background_colour, (56, 119, 198, 255))
        _assert_colour_near(self, estimate.text_colour, (255, 255, 255, 255))
        self.assertGreater(estimate.background_colour_confidence, 0.7)


def _text_image(
    *,
    background: tuple[int, int, int, int],
    text: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] | None = None,
    shadow: tuple[int, int, int, int] | None = None,
    angle: float = 0.0,
) -> tuple[Image.Image, OcrText]:
    return _draw_text(Image.new("RGBA", (240, 100), background), text, outline, shadow, angle)


def _draw_text(
    image: Image.Image,
    colour: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] | None = None,
    shadow: tuple[int, int, int, int] | None = None,
    angle: float = 0.0,
) -> tuple[Image.Image, OcrText]:
    font = ImageFont.truetype(_FONT_PATH, size=38)
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    text = "Test"
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font, stroke_width=2 if outline else 0)
    origin = (70 - left, 32 - top)
    if shadow:
        draw.text(
            (origin[0] + 3, origin[1] + 3),
            text,
            font=font,
            fill=shadow,
            stroke_width=2 if outline else 0,
            stroke_fill=outline,
        )
    draw.text(
        origin,
        text,
        font=font,
        fill=colour,
        stroke_width=2 if outline else 0,
        stroke_fill=outline,
    )
    shadow_padding = 3 if shadow else 0
    rectangle = (
        origin[0] + left - 2,
        origin[1] + top - 2,
        origin[0] + right + 2 + shadow_padding,
        origin[1] + bottom + 2 + shadow_padding,
    )
    if angle:
        layer = layer.rotate(angle, resample=Image.Resampling.BICUBIC)
        polygon = _rotate_rectangle(rectangle, image.size, angle)
    else:
        polygon = (
            (rectangle[0], rectangle[1]),
            (rectangle[2], rectangle[1]),
            (rectangle[2], rectangle[3]),
            (rectangle[0], rectangle[3]),
        )
    rendered = Image.alpha_composite(image, layer)
    return rendered, OcrText(
        "Test",
        1.0,
        BoundingPolygon(tuple(PixelPoint(x, y) for x, y in polygon)),
    )


def _rotate_rectangle(
    rectangle: tuple[float, float, float, float], image_size: tuple[int, int], angle: float
) -> tuple[tuple[float, float], ...]:
    center_x = image_size[0] / 2.0
    center_y = image_size[1] / 2.0
    angle_radians = radians(angle)
    corners = (
        (rectangle[0], rectangle[1]),
        (rectangle[2], rectangle[1]),
        (rectangle[2], rectangle[3]),
        (rectangle[0], rectangle[3]),
    )
    return tuple(
        (
            center_x + cos(angle_radians) * (x - center_x) - sin(angle_radians) * (y - center_y),
            center_y + sin(angle_radians) * (x - center_x) + cos(angle_radians) * (y - center_y),
        )
        for x, y in corners
    )


def _assert_colour_near(
    test_case: unittest.TestCase,
    actual: RgbaColour,
    expected: tuple[int, int, int, int],
    *,
    tolerance: int = 12,
) -> None:
    for actual_value, expected_value in zip(
        (actual.red, actual.green, actual.blue, actual.alpha), expected, strict=True
    ):
        test_case.assertLessEqual(abs(actual_value - expected_value), tolerance)
