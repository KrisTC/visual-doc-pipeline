"""Synthetic tests for Skia-backed OCR text-region replacement."""

from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np
from PIL import Image, ImageDraw
# skia-python does not publish PEP 561 stubs; the test creates a native Typeface.
import skia  # type: ignore[import-not-found]

from pipeline.ocr import BoundingPolygon, OcrText, PixelPoint
from pipeline.text_region_colours import BackgroundKind, RgbaColour, TextRegionColourEstimate
from pipeline.text_region_rendering import (
    TextRegionReplacement,
    render_replacement_text,
    replace_text_region,
    replace_text_regions,
    wipe_text_region_background,
)
from pipeline.text_region_rendering.renderer import (
    _fit_text,
    _placement_coordinate,
    _render_text_colour,
    _select_render_plan,
)


FONT_PATH = Path(__file__).parent / "assets" / "fonts" / "NotoSansJP[wght].ttf"
BACKGROUND = RgbaColour(246, 240, 210)
FOREGROUND = RgbaColour(30, 30, 30)
ESTIMATE = TextRegionColourEstimate(
    text_colour=FOREGROUND,
    background_colour=BACKGROUND,
    text_colour_confidence=1.0,
    background_colour_confidence=1.0,
    background_kind=BackgroundKind.FLAT,
)


class TextRegionRenderingTests(unittest.TestCase):
    """Exercise fitting and drawing with only repository-owned synthetic inputs."""

    def setUp(self) -> None:
        self.typeface = skia.Typeface.MakeFromFile(str(FONT_PATH))
        self.assertIsNotNone(self.typeface)

    # Verifies FR-2026-08-02-10.
    def test_replaces_text_in_place_with_background_and_foreground_colours(self) -> None:
        image = Image.new("RGB", (180, 80), _rgba_tuple(BACKGROUND))
        ImageDraw.Draw(image).rectangle((12, 12, 32, 31), fill=(0, 0, 0))
        region = _region((10, 10), (170, 70))
        image_identity = id(image)

        replace_text_region(
            image, region, ESTIMATE, "replacement", self._typeface(), target_language="en"
        )

        self.assertEqual(image_identity, id(image))
        self.assertEqual(_rgba_tuple(BACKGROUND), image.getpixel((12, 12)))
        pixels = np.asarray(image)
        foreground_pixels = np.all(pixels == _rgba_tuple(FOREGROUND), axis=2)
        self.assertGreater(np.count_nonzero(foreground_pixels), 0)

    # Verifies FR-2026-08-02-10.
    def test_background_wipe_clears_two_pixels_beyond_the_ocr_polygon(self) -> None:
        image = Image.new("RGB", (100, 80), _rgba_tuple(BACKGROUND))
        ImageDraw.Draw(image).rectangle((20, 50, 60, 53), fill=(0, 0, 0))
        region = _region((20, 20), (60, 50))

        replace_text_region(
            image, region, ESTIMATE, "", self._typeface(), target_language="en"
        )

        self.assertEqual(_rgba_tuple(BACKGROUND), image.getpixel((40, 51)))
        self.assertEqual(_rgba_tuple(BACKGROUND), image.getpixel((40, 52)))
        self.assertEqual((0, 0, 0), image.getpixel((40, 53)))

    # Verifies FR-2026-08-03-02.
    def test_explicit_and_batch_two_passes_preserve_text_from_a_later_wipe(self) -> None:
        first_region = _region((10, 20), (90, 60))
        second_region = _region((45, 20), (125, 60))
        expected_foreground_pixel = self._foreground_pixel_inside(second_region, first_region)

        sequential_image = self._blank_image()
        replace_text_region(
            sequential_image,
            first_region,
            ESTIMATE,
            "first",
            self._typeface(),
            target_language="en",
        )
        replace_text_region(
            sequential_image,
            second_region,
            ESTIMATE,
            "",
            self._typeface(),
            target_language="en",
        )
        self.assertEqual(
            _rgba_tuple(BACKGROUND), sequential_image.getpixel(expected_foreground_pixel)
        )

        explicit_pass_image = self._blank_image()
        for region in (first_region, second_region):
            wipe_text_region_background(explicit_pass_image, region, ESTIMATE)
        for region, text in ((first_region, "first"), (second_region, "")):
            render_replacement_text(
                explicit_pass_image,
                region,
                ESTIMATE,
                text,
                self._typeface(),
                target_language="en",
            )
        self.assertEqual(
            _rgba_tuple(FOREGROUND), explicit_pass_image.getpixel(expected_foreground_pixel)
        )

        batch_image = self._blank_image()
        replace_text_regions(
            batch_image,
            (
                TextRegionReplacement(first_region, ESTIMATE, "first"),
                TextRegionReplacement(second_region, ESTIMATE, ""),
            ),
            self._typeface(),
            target_language="en",
        )
        self.assertEqual(
            _rgba_tuple(FOREGROUND), batch_image.getpixel(expected_foreground_pixel)
        )

    # Verifies FR-2026-08-02-10.
    def test_light_text_on_a_dark_background_is_lightened_only_for_rendering(self) -> None:
        source_text_colour = RgbaColour(207, 215, 235, 173)
        dark_background = RgbaColour(56, 119, 198)

        rendered_colour = _render_text_colour(source_text_colour, dark_background)

        self.assertGreater(rendered_colour.red, source_text_colour.red)
        self.assertGreater(rendered_colour.green, source_text_colour.green)
        self.assertGreater(rendered_colour.blue, source_text_colour.blue)
        self.assertEqual(source_text_colour.alpha, rendered_colour.alpha)
        self.assertEqual(
            source_text_colour,
            _render_text_colour(source_text_colour, RgbaColour(240, 240, 240)),
        )
        self.assertEqual(
            source_text_colour,
            _render_text_colour(source_text_colour, RgbaColour(0, 0, 0, 0)),
        )

    # Verifies FR-2026-08-02-10.
    def test_longer_text_uses_a_smaller_wrapped_layout_than_short_text(self) -> None:
        short_layout = _fit_text("short", self._typeface(), 120.0, 50.0, is_axis_aligned=True)
        long_layout = _fit_text(
            "a considerably longer replacement string",
            self._typeface(),
            120.0,
            50.0,
            is_axis_aligned=True,
        )

        self.assertLess(long_layout.font.getSize(), short_layout.font.getSize())
        self.assertGreater(len(long_layout.lines), 1)
        self.assertFalse(long_layout.font.isSubpixel())
        self.assertEqual(skia.FontHinting.kFull, long_layout.font.getHinting())
        self.assertTrue(long_layout.font.isForceAutoHinting())
        self.assertTrue(long_layout.font.isEmbolden())

    # Verifies FR-2026-08-02-10.
    def test_only_axis_aligned_text_uses_pixel_snapped_placement(self) -> None:
        self.assertEqual(13.0, _placement_coordinate(12.6, True))
        self.assertEqual(12.6, _placement_coordinate(12.6, False))

    # Verifies FR-2026-08-02-10.
    def test_single_line_fitting_uses_visible_glyph_height_not_line_advance(self) -> None:
        layout = _fit_text("Dundee", self._typeface(), 50.0, 15.0, is_axis_aligned=True)

        self.assertEqual(14.0, layout.font.getSize())
        self.assertLessEqual(layout.line_bounds[0].width, 50.0)
        self.assertLessEqual(layout.content_bottom - layout.content_top, 15.0)

    # Verifies FR-2026-08-02-10.
    def test_small_ocr_box_skew_prefers_upright_text_without_reducing_font_size(self) -> None:
        polygon = BoundingPolygon(
            (
                PixelPoint(0.0, 0.0),
                PixelPoint(80.0, 3.0),
                PixelPoint(79.0, 24.0),
                PixelPoint(-1.0, 22.0),
            )
        )

        plan = _select_render_plan("Edinburgh", self._typeface(), polygon)

        self.assertEqual(0.0, plan.frame.angle_degrees)
        self.assertGreaterEqual(plan.layout.font.getSize(), 17.0)

    # Verifies FR-2026-08-02-10.
    def test_reversed_longest_baseline_edge_does_not_turn_text_upside_down(self) -> None:
        polygon = BoundingPolygon(
            (
                PixelPoint(0.0, 0.0),
                PixelPoint(80.0, 3.0),
                PixelPoint(81.0, 23.0),
                PixelPoint(0.0, 20.0),
            )
        )

        plan = _select_render_plan("Queen", self._typeface(), polygon)

        self.assertEqual(0.0, plan.frame.angle_degrees)

    # Verifies FR-2026-08-02-10.
    def test_small_skew_preserves_rotation_when_upright_text_requires_a_smaller_font(self) -> None:
        polygon = BoundingPolygon(
            (
                PixelPoint(0.0, 0.0),
                PixelPoint(69.0, 4.0),
                PixelPoint(68.0, 24.0),
                PixelPoint(-1.0, 21.0),
            )
        )

        plan = _select_render_plan("Glasgow", self._typeface(), polygon)

        self.assertGreater(plan.frame.angle_degrees, 3.0)
        self.assertEqual(17.0, plan.layout.font.getSize())

    # Verifies FR-2026-08-02-10.
    def test_small_fitted_text_uses_the_medium_variable_font_weight(self) -> None:
        polygon = BoundingPolygon(
            (
                PixelPoint(0.0, 0.0),
                PixelPoint(80.0, 3.0),
                PixelPoint(79.0, 24.0),
                PixelPoint(-1.0, 22.0),
            )
        )

        plan = _select_render_plan("#" * 18, self._typeface(), polygon)

        weight_coordinate = next(
            coordinate
            for coordinate in plan.layout.font.getTypeface().getVariationDesignPosition()
            if coordinate.axis == 0x77676874
        )
        self.assertLess(plan.layout.font.getSize(), 14.0)
        self.assertEqual(300.0, weight_coordinate.value)

    # Verifies FR-2026-08-02-10.
    def test_rotated_region_clips_replacement_text_to_its_polygon(self) -> None:
        image = Image.new("RGB", (180, 180), _rgba_tuple(BACKGROUND))
        region = OcrText(
            text="old",
            confidence=1.0,
            bounding_polygon=BoundingPolygon(
                (
                    PixelPoint(50.0, 30.0),
                    PixelPoint(150.0, 80.0),
                    PixelPoint(120.0, 140.0),
                    PixelPoint(20.0, 90.0),
                )
            ),
        )

        replace_text_region(
            image,
            region,
            ESTIMATE,
            "long replacement text",
            self._typeface(),
            target_language="en",
        )

        region_mask = Image.new("1", image.size, 0)
        ImageDraw.Draw(region_mask).polygon(
            [(vertex.x, vertex.y) for vertex in region.bounding_polygon.vertices], fill=1
        )
        pixels = np.asarray(image)
        dark_pixels = np.all(pixels < 128, axis=2)
        self.assertTrue(np.all(np.logical_not(dark_pixels) | np.asarray(region_mask, dtype=bool)))

    def _typeface(self) -> skia.Typeface:
        assert self.typeface is not None
        return self.typeface

    def _blank_image(self) -> Image.Image:
        return Image.new("RGB", (140, 80), _rgba_tuple(BACKGROUND))

    def _foreground_pixel_inside(
        self, containing_region: OcrText, rendered_region: OcrText
    ) -> tuple[int, int]:
        foreground_only = self._blank_image()
        render_replacement_text(
            foreground_only,
            rendered_region,
            ESTIMATE,
            "first",
            self._typeface(),
            target_language="en",
        )
        pixels = np.asarray(foreground_only)
        foreground_pixels = np.all(pixels == _rgba_tuple(FOREGROUND), axis=2)
        vertices = containing_region.bounding_polygon.vertices
        left = int(min(vertex.x for vertex in vertices)) - 2
        top = int(min(vertex.y for vertex in vertices)) - 2
        right = int(max(vertex.x for vertex in vertices)) + 2
        bottom = int(max(vertex.y for vertex in vertices)) + 2
        foreground_pixels[:top, :] = False
        foreground_pixels[bottom + 1 :, :] = False
        foreground_pixels[:, :left] = False
        foreground_pixels[:, right + 1 :] = False
        coordinates = np.argwhere(foreground_pixels)
        self.assertGreater(len(coordinates), 0)
        y, x = coordinates[0]
        return (int(x), int(y))


def _region(top_left: tuple[float, float], bottom_right: tuple[float, float]) -> OcrText:
    left, top = top_left
    right, bottom = bottom_right
    return OcrText(
        text="old",
        confidence=1.0,
        bounding_polygon=BoundingPolygon(
            (
                PixelPoint(left, top),
                PixelPoint(right, top),
                PixelPoint(right, bottom),
                PixelPoint(left, bottom),
            )
        ),
    )


def _rgba_tuple(colour: RgbaColour) -> tuple[int, int, int]:
    return (colour.red, colour.green, colour.blue)
