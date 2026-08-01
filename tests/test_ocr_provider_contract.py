"""Synthetic contract tests applied to all eligible OCR providers."""

from __future__ import annotations

from pathlib import Path
import unittest

from PIL import Image, ImageDraw, ImageFont

from pipeline.ocr.factory import OcrProviderFactory
from pipeline.ocr.models import OcrRequest, OcrText
from pipeline.ocr.provider import OcrProvider


SYSTEM_FONT = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
SYNTHETIC_TEXT_CASES = (("en", "HELLO"), ("ja", "日本語"))


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

        executed_cases = 0
        for language, expected_text in SYNTHETIC_TEXT_CASES:
            if language not in provider.supported_languages:
                continue
            with self.subTest(provider=provider_name, language=language):
                result = provider.recognize(OcrRequest(_text_image(expected_text), language))
                _assert_result_contains_text(self, result.text_items, expected_text)
            executed_cases += 1
        return executed_cases


def _text_image(text: str) -> Image.Image:
    if not SYSTEM_FONT.is_file():
        message = f"The synthetic Japanese OCR test requires {SYSTEM_FONT}."
        raise RuntimeError(message)
    image = Image.new("RGB", (900, 240), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(SYSTEM_FONT, size=128)
    draw.text((40, 40), text, font=font, fill="black")
    return image


def _assert_result_contains_text(
    test_case: unittest.TestCase, text_items: tuple[OcrText, ...], expected_text: str
) -> None:
    recognized_text = "".join(text_item.text for text_item in text_items)
    test_case.assertIn(expected_text, recognized_text)
    for text_item in text_items:
        test_case.assertGreaterEqual(text_item.confidence, 0.0)
        test_case.assertLessEqual(text_item.confidence, 1.0)
        test_case.assertGreaterEqual(len(text_item.bounding_polygon.vertices), 3)
