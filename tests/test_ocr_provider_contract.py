"""Synthetic contract tests applied to all eligible OCR providers."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from math import ceil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pipeline.ocr.factory import OcrProviderFactory
from pipeline.ocr.models import OcrRequest, OcrText
from pipeline.ocr.provider import LocalContractTestCase, OcrProvider

FONT_DIRECTORY = Path(__file__).parent / "assets" / "fonts"
SYNTHETIC_TEXT_CASES = (
    ("en", "The quick brown fox jumps over the lazy dog."),
    ("ja", "素早い茶色の狐が怠惰な犬を飛び越える。"),
)
ROTATION_ANGLES = (0, 45, 90, 135, 180, 225, 270, 315)
TEXT_PADDING = 40

@dataclass(frozen=True)
class FontFace:
    """A named variation from the committed test-font pack."""

    name: str
    path: Path
    variation_name: bytes


@dataclass(frozen=True)
class SyntheticTextImage:
    """A rendered OCR input and the source-image mask for its text region."""

    image: Image.Image
    text_region_mask: Image.Image


@dataclass(frozen=True)
class ColorCombination:
    """A slide-style foreground and background pair for synthetic OCR input."""

    name: str
    foreground: str
    background: str


FONT_FACES = (
    FontFace("Noto Sans JP Regular", FONT_DIRECTORY / "NotoSansJP[wght].ttf", b"Regular"),
    FontFace("Noto Sans JP Bold", FONT_DIRECTORY / "NotoSansJP[wght].ttf", b"Bold"),
    FontFace("Noto Serif JP Regular", FONT_DIRECTORY / "NotoSerifJP[wght].ttf", b"Regular"),
)
COLOR_COMBINATIONS = (
    ColorCombination("light", "#000000", "#FFFFFF"),
    ColorCombination("dark", "#FFFFFF", "#000000"),
    ColorCombination("navy", "#FFFFFF", "#1F4E79"),
    ColorCombination("warm", "#1F1F1F", "#FFF2CC"),
    ColorCombination("purple", "#FFFFFF", "#7030A0"),
)


class OcrProviderContractTests(unittest.TestCase):
    # Verifies FR-2026-08-01-02.
    def test_eligible_providers_recognize_their_synthetic_languages(self) -> None:
        factory = OcrProviderFactory.discover_default_plugins()
        executed_cases = 0

        for provider_name in factory.provider_names:
            provider = factory.create(provider_name)
            executed_cases += self._test_provider_cases(provider_name, provider)

        self.assertGreater(executed_cases, 0, "No eligible OCR-provider contract cases ran.")

    def _test_provider_cases(self, provider_name: str, provider: OcrProvider) -> int:
        if not provider.supports_local_contract_test:
            return 0

        unsupported_angles = provider.skipped_local_contract_angles
        unknown_angles = unsupported_angles.difference(ROTATION_ANGLES)
        self.assertFalse(
            unknown_angles,
            f"{provider_name} skips angles outside the contract matrix: {unknown_angles}.",
        )
        skipped_cases = {
            skipped_case.case: skipped_case.reason
            for skipped_case in provider.skipped_local_contract_cases
        }
        self.assertEqual(
            len(skipped_cases),
            len(provider.skipped_local_contract_cases),
            f"{provider_name} declares the same local contract-test case more than once.",
        )

        executed_cases = 0
        for language, expected_text in SYNTHETIC_TEXT_CASES:
            if language not in provider.supported_languages:
                continue
            for font_face in FONT_FACES:
                for angle in ROTATION_ANGLES:
                    for colors in COLOR_COMBINATIONS:
                        with self.subTest(
                            provider=provider_name,
                            language=language,
                            font=font_face.name,
                            angle=angle,
                            colors=colors.name,
                        ):
                            if angle in unsupported_angles:
                                self.skipTest(
                                    f"{provider_name} does not yet support {angle}° text "
                                    "without rotation handling."
                                )
                            case = LocalContractTestCase(
                                language, font_face.name, angle, colors.name
                            )
                            if reason := skipped_cases.get(case):
                                self.skipTest(reason)
                            synthetic_image = _text_image(
                                expected_text, font_face, angle, colors
                            )
                            result = provider.recognize(
                                OcrRequest(synthetic_image.image, language)
                            )
                            _assert_result_contains_text(
                                self, result.text_items, expected_text
                            )
                            _assert_region_overlap(
                                self, result.text_items, synthetic_image.text_region_mask
                            )
                        executed_cases += 1
        return executed_cases


def _text_image(
    text: str,
    font_face: FontFace,
    angle: int,
    colors: ColorCombination,
) -> SyntheticTextImage:
    if not font_face.path.is_file():
        message = f"The synthetic OCR test requires {font_face.path}."
        raise RuntimeError(message)
    font = ImageFont.truetype(font_face.path, size=64)
    font.set_variation_by_name(font_face.variation_name)
    measurement_image = Image.new("RGB", (1, 1), "white")
    draw = ImageDraw.Draw(measurement_image)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    text_width = ceil(right - left)
    text_height = ceil(bottom - top)
    content_size = (text_width + 2 * TEXT_PADDING, text_height + 2 * TEXT_PADDING)
    text_layer = Image.new("RGBA", content_size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(text_layer)
    draw.text(
        (TEXT_PADDING - left, TEXT_PADDING - top), text, font=font, fill=colors.foreground
    )

    text_region_mask = Image.new("1", content_size, 0)
    ImageDraw.Draw(text_region_mask).rectangle(
        (
            TEXT_PADDING,
            TEXT_PADDING,
            TEXT_PADDING + text_width - 1,
            TEXT_PADDING + text_height - 1,
        ),
        fill=1,
    )
    rotated_text_layer = text_layer.rotate(
        angle, resample=Image.Resampling.BICUBIC, expand=True
    )
    rotated_region_mask = text_region_mask.rotate(
        angle, resample=Image.Resampling.NEAREST, expand=True
    )

    image_size = (
        rotated_text_layer.width + 2 * TEXT_PADDING,
        rotated_text_layer.height + 2 * TEXT_PADDING,
    )
    image = Image.new("RGB", image_size, colors.background)
    image.paste(rotated_text_layer, (TEXT_PADDING, TEXT_PADDING), rotated_text_layer)
    expected_region_mask = Image.new("1", image_size, 0)
    expected_region_mask.paste(rotated_region_mask, (TEXT_PADDING, TEXT_PADDING))
    return SyntheticTextImage(image, expected_region_mask)


def _assert_result_contains_text(
    test_case: unittest.TestCase, text_items: tuple[OcrText, ...], expected_text: str
) -> None:
    recognized_text = "".join(text_item.text for text_item in text_items)
    test_case.assertIn(expected_text, recognized_text)
    for text_item in text_items:
        test_case.assertGreaterEqual(text_item.confidence, 0.0)
        test_case.assertLessEqual(text_item.confidence, 1.0)
        test_case.assertGreaterEqual(len(text_item.bounding_polygon.vertices), 3)


def _assert_region_overlap(
    test_case: unittest.TestCase,
    text_items: tuple[OcrText, ...],
    expected_region_mask: Image.Image,
) -> None:
    """Verify FR-2026-08-01-02 polygon suitability for masking or replacement."""
    detected_region_mask = Image.new("1", expected_region_mask.size, 0)
    draw = ImageDraw.Draw(detected_region_mask)
    for text_item in text_items:
        draw.polygon(
            [(point.x, point.y) for point in text_item.bounding_polygon.vertices],
            fill=1,
        )

    expected_pixels = np.asarray(expected_region_mask, dtype=bool)
    detected_pixels = np.asarray(detected_region_mask, dtype=bool)
    union = np.count_nonzero(expected_pixels | detected_pixels)
    intersection = np.count_nonzero(expected_pixels & detected_pixels)
    overlap = intersection / union if union else 0.0
    test_case.assertGreaterEqual(overlap, 0.5, f"Text-region IoU was {overlap:.3f}.")
