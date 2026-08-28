"""Tests for transparent source-adjacent provider-result caching."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar
import unittest
from unittest.mock import patch

from PIL import Image

from pipeline.ocr.factory import OcrProviderFactory
from pipeline.ocr.models import BoundingPolygon, OcrRequest, OcrResult, OcrText, PixelPoint
from pipeline.ocr.provider import LocalContractTestSkip
from pipeline.provider_cache import CACHE_FILENAME_SUFFIX, source_cache_scope
from pipeline.text_replacement.factory import TextReplacementProviderFactory
from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult


class _RecordingOcrProvider:
    supported_languages = frozenset({"en"})
    supports_local_contract_test = False
    skipped_local_contract_angles = frozenset[int]()
    skipped_local_contract_cases: ClassVar[frozenset[LocalContractTestSkip]] = frozenset()

    def __init__(self) -> None:
        self.calls = 0

    def recognize(self, request: OcrRequest) -> OcrResult:
        self.calls += 1
        pixel = request.image.getpixel((0, 0))
        return OcrResult(
            (
                OcrText(
                    text=str(pixel),
                    confidence=0.9,
                    bounding_polygon=BoundingPolygon(
                        (PixelPoint(0, 0), PixelPoint(1, 0), PixelPoint(1, 1))
                    ),
                ),
            )
        )


class _RecordingTextProvider:
    def __init__(self) -> None:
        self.calls = 0

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        self.calls += 1
        return TextReplacementResult(text=f"translated:{request.text}", confidence=0.5)


class ProviderCacheTests(unittest.TestCase):
    # Verifies FR-2026-08-27-10 and SR-2026-08-27-01.
    def test_factory_proxy_caches_text_results_in_the_source_sidecar(self) -> None:
        provider = _RecordingTextProvider()
        factory = TextReplacementProviderFactory(
            {"fake": lambda: provider}, cache_identities={"fake": lambda: "fake:v1"}
        )
        request = TextReplacementRequest("hello", False, "en", "ja")

        with TemporaryDirectory() as directory, patch.dict("os.environ", {"PIPELINE_PLUGIN_CACHE": "1"}):
            source = Path(directory) / "report.pptx"
            with patch("pipeline.provider_cache.sqlite3.connect", wraps=sqlite3.connect) as connect:
                with source_cache_scope(source):
                    self.assertEqual("translated:hello", factory.create("fake").replace(request).text)
                    self.assertEqual("translated:hello", factory.create("fake").replace(request).text)

            self.assertEqual(1, connect.call_count)

            self.assertEqual(1, provider.calls)
            self.assertTrue(source.with_name(f"{source.name}{CACHE_FILENAME_SUFFIX}").is_file())

    # Verifies FR-2026-08-27-10's embedded-image identity rule.
    def test_ocr_cache_reuses_equal_image_pixels_without_an_embedded_image_id(self) -> None:
        provider = _RecordingOcrProvider()
        factory = OcrProviderFactory(
            {"fake": lambda: provider}, cache_identities={"fake": lambda: "fake:v1"}
        )

        with TemporaryDirectory() as directory, patch.dict("os.environ", {"PIPELINE_PLUGIN_CACHE": "1"}):
            source = Path(directory) / "report.docx"
            with source_cache_scope(source):
                proxy = factory.create("fake")
                proxy.recognize(OcrRequest(Image.new("RGB", (2, 2), "white"), "en"))
                proxy.recognize(OcrRequest(Image.new("RGB", (2, 2), "white"), "en"))
                proxy.recognize(OcrRequest(Image.new("RGB", (2, 2), "black"), "en"))

        self.assertEqual(2, provider.calls)

    # Verifies FR-2026-08-27-10's explicit opt-in rule.
    def test_factory_returns_the_unwrapped_provider_when_caching_is_disabled(self) -> None:
        provider = _RecordingTextProvider()
        factory = TextReplacementProviderFactory(
            {"fake": lambda: provider}, cache_identities={"fake": lambda: "fake:v1"}
        )

        with patch.dict("os.environ", {}, clear=True):
            self.assertIs(provider, factory.create("fake"))

    # Verifies SR-2026-08-27-01's malformed-cache recovery rule.
    def test_malformed_cached_result_is_ignored_and_replaced(self) -> None:
        provider = _RecordingTextProvider()
        factory = TextReplacementProviderFactory(
            {"fake": lambda: provider}, cache_identities={"fake": lambda: "fake:v1"}
        )
        request = TextReplacementRequest("hello", False, "en", "ja")

        with TemporaryDirectory() as directory, patch.dict("os.environ", {"PIPELINE_PLUGIN_CACHE": "1"}):
            source = Path(directory) / "report.pdf"
            with source_cache_scope(source):
                proxy = factory.create("fake")
                proxy.replace(request)
            cache_path = source.with_name(f"{source.name}{CACHE_FILENAME_SUFFIX}")
            connection = sqlite3.connect(cache_path)
            try:
                connection.execute("UPDATE provider_result_cache SET result_json = ?", ("{bad",))
                connection.commit()
            finally:
                connection.close()
            with source_cache_scope(source):
                self.assertEqual("translated:hello", proxy.replace(request).text)

        self.assertEqual(2, provider.calls)


if __name__ == "__main__":
    unittest.main()
