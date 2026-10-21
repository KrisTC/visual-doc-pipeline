"""Tests for transparent source-adjacent provider-result caching."""

from __future__ import annotations

from contextlib import closing, redirect_stderr, redirect_stdout
from io import StringIO
import json
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
from pipeline.folder_replacement.processor import _diagnostic_options
from pipeline.provider_cache import (
    CACHE_FILENAME_SUFFIX,
    CacheInspectionError,
    CachingOcrProvider,
    CachingTextReplacementProvider,
    inspect_cache,
    provider_diagnostic_name,
    source_cache_scope,
)
from pipeline.provider_metrics import RunMetrics
from pipeline.text_replacement.factory import TextReplacementProviderFactory
from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult
from scripts.cache_metrics import main as cache_metrics_main


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
    # Verifies FR-2026-10-21-01's in-place legacy schema migration.
    def test_legacy_three_column_cache_remains_usable_and_inspectable(self) -> None:
        provider = _RecordingTextProvider()
        factory = TextReplacementProviderFactory(
            {"synthetic": lambda: provider},
            cache_identities={"synthetic": lambda: "synthetic:v1"},
        )
        with TemporaryDirectory() as directory:
            source = Path(directory) / "sample.txt"
            cache_path = source.with_name(f"{source.name}{CACHE_FILENAME_SUFFIX}")
            with closing(sqlite3.connect(cache_path)) as connection, connection:
                connection.execute(
                    "CREATE TABLE provider_result_cache (result_kind TEXT NOT NULL, "
                    "cache_key TEXT NOT NULL, result_json TEXT NOT NULL, "
                    "PRIMARY KEY(result_kind, cache_key))"
                )
                connection.execute(
                    "INSERT INTO provider_result_cache VALUES ('ocr', 'old-key', '{}')"
                )
            self.assertEqual(1, inspect_cache(cache_path)[0]["cached_results"])
            with patch.dict("os.environ", {"PIPELINE_PLUGIN_CACHE": "1"}):
                with source_cache_scope(source):
                    factory.create("synthetic").replace(
                        TextReplacementRequest("one", False, "en", "fr")
                    )
            inventory = inspect_cache(cache_path)
            self.assertIsNone(inventory[0]["provider_name"])
            self.assertEqual(1, inventory[1]["cached_results"])
            self.assertEqual(3, inventory[1]["known_input_characters"])

    # Verifies FR-2026-10-21-01's duration denominator and unavailable share.
    def test_run_metrics_does_not_assign_time_to_hits_or_zero_document_time(self) -> None:
        metrics = RunMetrics()
        metrics.record("text_replacement", "synthetic", 3, 2.0)
        metrics.record("text_replacement", "synthetic", 3, None)
        report = metrics.report(0)[0]
        self.assertEqual(2, report["successful_calls"])
        self.assertEqual(6, report["input_characters"])
        self.assertEqual(1, report["duration_count"])
        self.assertEqual(2, report["duration_average_seconds"])
        self.assertIsNone(report["document_time_share_percent"])
        self.assertEqual(50, metrics.report(4)[0]["document_time_share_percent"])

    # Verifies FR-2026-10-21-01's underlying-call timing and hit exclusion.
    def test_provider_duration_is_measured_only_on_the_cache_miss(self) -> None:
        provider = _RecordingTextProvider()
        request = TextReplacementRequest("one", True, "en", "fr")
        with TemporaryDirectory() as directory, patch.dict("os.environ", {"PIPELINE_PLUGIN_CACHE": "1"}):
            source = Path(directory) / "sample.txt"
            proxy = CachingTextReplacementProvider(provider, "synthetic:v1", "synthetic")
            with patch("pipeline.provider_cache.perf_counter", side_effect=[5.0, 7.5]) as clock:
                with RunMetrics() as metrics, source_cache_scope(source):
                    proxy.replace(request)
                    proxy.replace(request)
                self.assertEqual(2, clock.call_count)
            self.assertEqual(1, provider.calls)
            report = metrics.report(10)[0]
            self.assertEqual(2, report["successful_calls"])
            self.assertEqual(1, report["duration_count"])
            self.assertEqual(2.5, report["duration_total_seconds"])
            self.assertEqual(25, report["document_time_share_percent"])
            inventory = inspect_cache(source.with_name(f"{source.name}{CACHE_FILENAME_SUFFIX}"))
            self.assertEqual(1, inventory[0]["duration_count"])
            self.assertEqual(2.5, inventory[0]["duration_average_seconds"])

    # Verifies SR-2026-10-21-01's locked-cache failure boundary.
    def test_locked_inspection_is_content_free_and_does_not_write(self) -> None:
        with TemporaryDirectory() as directory:
            cache_path = Path(directory) / f"sample.txt{CACHE_FILENAME_SUFFIX}"
            cache_path.write_bytes(b"synthetic cache bytes")
            with patch("pipeline.provider_cache.sqlite3.connect", side_effect=sqlite3.OperationalError("private path")):
                with self.assertRaisesRegex(CacheInspectionError, "^Cache inventory unavailable\\.$"):
                    inspect_cache(cache_path)
            self.assertEqual(b"synthetic cache bytes", cache_path.read_bytes())

    # Verifies FR-2026-10-21-01 and SR-2026-10-21-01.
    def test_inventory_migrates_and_backfills_legacy_rows_without_changing_results(self) -> None:
        provider = _RecordingTextProvider()
        request = TextReplacementRequest("caf\u00e9\U0001f600", True, "en", "ja")
        cache_factory = TextReplacementProviderFactory(
            {"synthetic": lambda: provider},
            cache_identities={"synthetic": lambda: "synthetic:v1"},
        )
        with TemporaryDirectory() as directory, patch.dict("os.environ", {"PIPELINE_PLUGIN_CACHE": "1"}):
            source = Path(directory) / "example.txt"
            cache_path = source.with_name(f"{source.name}{CACHE_FILENAME_SUFFIX}")
            with source_cache_scope(source):
                proxy = cache_factory.create("synthetic")
                proxy.replace(request)
            with closing(sqlite3.connect(cache_path)) as connection, connection:
                key, value = connection.execute(
                    "SELECT cache_key, result_json FROM provider_result_cache"
                ).fetchone()
                connection.execute(
                    "UPDATE provider_result_cache SET provider_name = NULL, "
                    "input_characters = NULL, provider_seconds = NULL"
                )
                connection.execute(
                    "INSERT INTO provider_result_cache (result_kind, cache_key, result_json) "
                    "VALUES ('ocr', 'legacy-key', '{}')"
                )
            with patch.dict("os.environ", {}, clear=True):
                before = inspect_cache(cache_path)
                self.assertEqual(1, before[0]["cached_results"])
                self.assertIsNone(before[0]["provider_name"])
                self.assertEqual(1, before[1]["unknown_input_count"])
            with source_cache_scope(source):
                self.assertEqual("translated:caf\u00e9\U0001f600", proxy.replace(request).text)
            self.assertEqual(1, provider.calls)
            with closing(sqlite3.connect(cache_path)) as connection, connection:
                self.assertEqual(
                    (key, value, "synthetic", 5, None),
                    connection.execute(
                        "SELECT cache_key, result_json, provider_name, input_characters, "
                        "provider_seconds FROM provider_result_cache "
                        "WHERE result_kind = 'text_replacement'"
                    ).fetchone(),
                )
            after = inspect_cache(cache_path)
            self.assertEqual(5, after[1]["known_input_characters"])
            self.assertEqual(1, after[1]["unknown_duration_count"])

    # Verifies FR-2026-10-21-01's content-free, read-only inspection.
    def test_inventory_command_rejects_missing_and_malformed_cache_without_disclosure(self) -> None:
        with TemporaryDirectory() as directory:
            cache_path = Path(directory) / "sensitive.plugin-cache.sqlite3"
            stderr = StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(1, cache_metrics_main([str(cache_path)]))
            self.assertFalse(cache_path.exists())
            self.assertEqual("Cache inventory unavailable.\n", stderr.getvalue())
            cache_path.write_bytes(b"not a database: secret")
            with self.assertRaises(CacheInspectionError):
                inspect_cache(cache_path)
            with redirect_stderr(stderr):
                self.assertEqual(1, cache_metrics_main([str(cache_path)]))
            self.assertNotIn("sensitive", stderr.getvalue())
            self.assertNotIn("secret", stderr.getvalue())

    # Verifies FR-2026-10-21-01's measured and unknown duration totals.
    def test_inventory_aggregates_known_durations_without_result_content(self) -> None:
        with TemporaryDirectory() as directory:
            cache_path = Path(directory) / f"doc.txt{CACHE_FILENAME_SUFFIX}"
            with closing(sqlite3.connect(cache_path)) as connection, connection:
                connection.execute(
                    "CREATE TABLE provider_result_cache (result_kind TEXT NOT NULL, "
                    "cache_key TEXT NOT NULL, result_json TEXT NOT NULL, "
                    "provider_name TEXT, input_characters INTEGER, provider_seconds REAL, "
                    "PRIMARY KEY(result_kind, cache_key))"
                )
                connection.executemany(
                    "INSERT INTO provider_result_cache VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        ("text_replacement", "a", "secret", "synthetic", 2, 1.0),
                        ("text_replacement", "b", "secret", "synthetic", 3, 3.0),
                        ("text_replacement", "c", "secret", "synthetic", -1, -2.0),
                        ("ocr", "d", "secret", "bad/name", None, None),
                    ],
                )
            stdout = StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(0, cache_metrics_main([str(cache_path)]))
            self.assertNotIn("secret", stdout.getvalue())
            self.assertNotIn("bad/name", stdout.getvalue())
            self.assertNotIn(str(cache_path), stdout.getvalue())
            inventory = json.loads(stdout.getvalue())["cache_inventory"]
            self.assertIsNone(inventory[0]["provider_name"])
            self.assertEqual(5, inventory[1]["known_input_characters"])
            self.assertEqual(1, inventory[1]["unknown_input_count"])
            self.assertEqual(2, inventory[1]["duration_count"])
            self.assertEqual(1, inventory[1]["duration_min_seconds"])
            self.assertEqual(3, inventory[1]["duration_max_seconds"])
            self.assertEqual(2, inventory[1]["duration_average_seconds"])

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

    # Verifies FR-2026-08-28-02.
    def test_diagnostic_names_preserve_wrapped_provider_types(self) -> None:
        ocr_provider = _RecordingOcrProvider()
        text_provider = _RecordingTextProvider()

        self.assertEqual("_RecordingOcrProvider", provider_diagnostic_name(ocr_provider))
        self.assertEqual(
            "_RecordingOcrProvider (cached)",
            provider_diagnostic_name(CachingOcrProvider(ocr_provider, "fake:v1")),
        )
        self.assertEqual(
            "_RecordingTextProvider (cached)",
            provider_diagnostic_name(CachingTextReplacementProvider(text_provider, "fake:v1")),
        )
        options = _diagnostic_options(
            "en",
            "fr",
            "preserve-source-formatting",
            (),
            CachingOcrProvider(ocr_provider, "fake:v1"),
            CachingTextReplacementProvider(text_provider, "fake:v1"),
        )
        self.assertEqual("_RecordingOcrProvider (cached)", options["ocr_provider"])
        self.assertEqual("_RecordingTextProvider (cached)", options["text_replacement_provider"])

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
