"""Tests for OCR provider registration and built-in plugin discovery."""

from __future__ import annotations

import unittest

from pipeline.ocr.errors import (
    DuplicateOcrProviderError,
    OcrProviderNotFoundError,
)
from pipeline.ocr.factory import OcrProviderFactory
from pipeline.ocr.models import OcrRequest, OcrResult


class _ExampleProvider:
    name = "example"
    supported_languages = frozenset({"en"})
    supports_local_contract_test = True

    def recognize(self, request: OcrRequest) -> OcrResult:
        del request
        return OcrResult(())


class OcrProviderFactoryTests(unittest.TestCase):
    # Verifies FR-2026-08-01-02.
    def test_discovers_the_paddleocr_plugin(self) -> None:
        factory = OcrProviderFactory.discover_default_plugins()

        self.assertEqual(("paddleocr",), factory.provider_names)

    # Verifies FR-2026-08-01-02.
    def test_rejects_duplicate_names_and_reports_unknown_names(self) -> None:
        factory = OcrProviderFactory()
        factory.register("example", _ExampleProvider)

        with self.assertRaises(DuplicateOcrProviderError):
            factory.register("example", _ExampleProvider)
        with self.assertRaises(OcrProviderNotFoundError):
            factory.create("missing")
