"""Tests for OCR provider registration and built-in plugin discovery."""

from __future__ import annotations

import unittest
from typing import cast
from unittest.mock import Mock

from PIL import Image

from pipeline.ocr.errors import OcrProviderNotFoundError
from pipeline.ocr.factory import OcrProviderFactory
from pipeline.ocr.models import OcrRequest


class OcrProviderFactoryTests(unittest.TestCase):
    # Verifies FR-2026-08-01-02, FR-2026-08-03-01, and FR-2026-08-04-02.
    def test_discovers_provider_packages_by_their_directory_names(self) -> None:
        factory = OcrProviderFactory.discover_default_plugins()

        self.assertEqual(("no_ocr", "paddleocr"), factory.provider_names)
        self.assertEqual(
            {
                "no_ocr": "Immediate empty-result OCR provider for local pipeline testing.",
                "paddleocr": "PaddleOCR implementation of the product OCR-provider protocol.",
            },
            dict(factory.provider_descriptions),
        )
        self.assertFalse(hasattr(factory.create("paddleocr"), "name"))

    # Verifies FR-2026-08-04-02.
    def test_no_ocr_returns_an_empty_result_without_accessing_the_image(self) -> None:
        image = Mock()
        request = OcrRequest(cast(Image.Image, image), "en")

        result = OcrProviderFactory.discover_default_plugins().create("no_ocr").recognize(request)

        self.assertEqual((), result.text_items)
        self.assertEqual([], image.mock_calls)

    # Verifies FR-2026-08-01-02 and FR-2026-08-03-01.
    def test_reports_unknown_names_without_provider_registration(self) -> None:
        factory = OcrProviderFactory()

        with self.assertRaises(OcrProviderNotFoundError):
            factory.create("missing")
