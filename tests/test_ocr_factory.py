"""Tests for OCR provider registration and built-in plugin discovery."""

from __future__ import annotations

import unittest

from pipeline.ocr.errors import OcrProviderNotFoundError
from pipeline.ocr.factory import OcrProviderFactory


class OcrProviderFactoryTests(unittest.TestCase):
    # Verifies FR-2026-08-01-02 and FR-2026-08-03-01.
    def test_discovers_the_paddleocr_package_by_its_directory_name(self) -> None:
        factory = OcrProviderFactory.discover_default_plugins()

        self.assertEqual(("paddleocr",), factory.provider_names)
        self.assertEqual(
            {"paddleocr": "PaddleOCR implementation of the product OCR-provider protocol."},
            dict(factory.provider_descriptions),
        )
        self.assertFalse(hasattr(factory.create("paddleocr"), "name"))

    # Verifies FR-2026-08-01-02 and FR-2026-08-03-01.
    def test_reports_unknown_names_without_provider_registration(self) -> None:
        factory = OcrProviderFactory()

        with self.assertRaises(OcrProviderNotFoundError):
            factory.create("missing")
