#!/usr/bin/env python3
"""Synthetic regression tests for COMMON folder replacement."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import time
from typing import cast
import unittest
from unittest.mock import patch
from uuid import UUID
import xml.etree.ElementTree as ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image, ImageDraw
from docx import Document
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, Protection
from openpyxl.worksheet.table import Table
from pptx import Presentation
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.oxml import parse_xml
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt
# pypdf does not publish PEP 561 metadata for its generic object model.
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ByteStringObject, ContentStream, DecodedStreamObject, DictionaryObject, FloatObject, NameObject, NumberObject, TextStringObject
# skia-python does not publish PEP 561 stubs; this is the native rendering boundary.
import skia  # type: ignore[import-not-found]

import pipeline.folder_replacement.processor as folder_processor
from pipeline.folder_replacement import (
    FolderReplacementResult,
    parse_include_patterns,
    replace_input_folder,
)
from pipeline.folder_replacement.processor import ProgressFactory, ProgressReporter
from pipeline.provider_cache import CACHE_FILENAME_SUFFIX, CachingOcrProvider, CachingTextReplacementProvider
from pipeline.folder_replacement.docx import _docx_ocr_backgrounds
from pipeline.folder_replacement.pptx import _pptx_ocr_backgrounds
from pipeline.folder_replacement.pdf import (
    _PdfPaintSpan,
    _PdfShownText,
    _PdfVisualRegion,
    _PdfReplacementSerializationError,
    _pdf_apply_paint_span_bullet_overrides,
    _pdf_apply_legacy_bullet_override,
    _pdf_content_has_annotations,
    _pdf_decode_composite_bytes,
    _pdf_expansion_geometry_is_known,
    _pdf_fitted_region_operations,
    _pdf_is_candidate_bullet_error,
    _pdf_text_advance,
)
from pipeline.folder_replacement.xlsx import _replace_drawing
from pipeline.folder_replacement.docx import _validate_docx_embedded_fonts
from pipeline.bounded_text_layout import (
    BoundedTextBox,
    BoundedTextParagraph,
    BoundedTextRun,
    PortableTextUnsupportedError,
    noto_typefaces,
)
from pipeline.portable_bullet_overrides import LegacyBulletOverride
from pipeline.portable_fonts import static_noto_bytes
from pipeline.ocr import BoundingPolygon, OcrRequest, OcrResult, OcrText, PixelPoint
from pipeline.ocr.provider import LocalContractTestSkip
from pipeline.text_replacement import (
    TextReplacementProvider,
    TextReplacementRequest,
    TextReplacementResult,
)
from pipeline.text_replacement_plugins.character_mask import CharacterMaskProvider



from folder_replacement_test_support import (
    FONT_PATH,
    FolderReplacementTestCase,
    _CountingOcrProvider,
    _EmptyOcrProvider,
    _FailingOcrProvider,
    _LowConfidenceOcrProvider,
    _RecordedProgress,
    _RecordingReplacementProvider,
    _VectorOutlineOcrProvider,
    _synthetic_pdf_visual_region,
)

class FolderReplacementCommonTests(FolderReplacementTestCase):
    # Verifies FR-2026-10-21-01 and SR-2026-10-21-01.
    def test_debug_run_without_cache_does_not_create_a_cache(self) -> None:
        with TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True):
            root = Path(directory)
            input_root = root / "input"
            input_root.mkdir()
            source = input_root / "sample.png"
            self._write_png(source)
            self._run(
                input_root, root / "output", _CountingOcrProvider(),
                _RecordingReplacementProvider(), diagnostics_enabled=True,
            )
            self.assertFalse(source.with_name(f"{source.name}{CACHE_FILENAME_SUFFIX}").exists())
            report = json.loads((root / "output/sample.png.diagnostics.json").read_text("utf-8"))
            self.assertNotIn("cache_inventory", report)
            self.assertEqual(2, len(report["run_activity"]["providers"]))

    # Verifies FR-2026-10-21-01 and SR-2026-10-21-01.
    def test_debug_provider_metrics_with_and_without_cache_opt_in(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            input_root = root / "input"
            input_root.mkdir()
            source = input_root / "sample.png"
            self._write_png(source)
            cache_path = source.with_name(f"{source.name}{CACHE_FILENAME_SUFFIX}")
            ocr = _CountingOcrProvider()
            replacement = _RecordingReplacementProvider()
            cached_ocr = CachingOcrProvider(ocr, "synthetic:v1", "synthetic_ocr")
            cached_replacement = CachingTextReplacementProvider(
                replacement, "synthetic:v1", "synthetic_replacement"
            )
            with patch.dict("os.environ", {"PIPELINE_PLUGIN_CACHE": "1"}):
                self._run(input_root, root / "first", cached_ocr, cached_replacement, diagnostics_enabled=True)
                self._run(input_root, root / "second", cached_ocr, cached_replacement, diagnostics_enabled=True)
            first = json.loads((root / "first/sample.png.diagnostics.json").read_text("utf-8"))
            second = json.loads((root / "second/sample.png.diagnostics.json").read_text("utf-8"))
            self.assertTrue(cache_path.is_file())
            self.assertEqual([], first["entries"])
            self.assertEqual(1, ocr.calls)
            self.assertEqual(1, len(replacement.requests))
            self.assertEqual(first["cache_inventory"], second["cache_inventory"])
            first_run = first["run_activity"]["providers"]
            second_run = second["run_activity"]["providers"]
            self.assertEqual([1, 1], [entry["duration_count"] for entry in first_run])
            self.assertEqual([0, 0], [entry["duration_count"] for entry in second_run])
            self.assertEqual(1, second_run[1]["successful_calls"])
            self.assertEqual(len(source.name), second_run[1]["input_characters"])
            self.assertIsNone(second_run[1]["document_time_share_percent"])
            with patch.dict("os.environ", {}, clear=True):
                self._run(input_root, root / "third", ocr, replacement, diagnostics_enabled=True)
            third = json.loads((root / "third/sample.png.diagnostics.json").read_text("utf-8"))
            self.assertEqual(second["cache_inventory"], third["cache_inventory"])
            self.assertEqual([1, 1], [entry["duration_count"] for entry in third["run_activity"]["providers"]])
            self.assertEqual(1, third["run_activity"]["providers"][1]["successful_calls"])

    # Verifies FR-2026-09-04-02.
    def test_preserves_transparent_paletted_png_alpha_for_standalone_and_docx_media(self) -> None:
        class _TransparentPaletteOcrProvider(_EmptyOcrProvider):
            def recognize(self, request: OcrRequest) -> OcrResult:
                return OcrResult(
                    (
                        OcrText(
                            "source",
                            1.0,
                            BoundingPolygon(
                                (
                                    PixelPoint(10, 8),
                                    PixelPoint(46, 8),
                                    PixelPoint(46, 36),
                                    PixelPoint(10, 36),
                                )
                            ),
                        ),
                    )
                )

        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            image_data = _transparent_paletted_png()
            (input_root / "standalone.png").write_bytes(image_data)
            with ZipFile(input_root / "embedded.docx", "w", ZIP_DEFLATED) as archive:
                archive.writestr("word/media/image1.png", image_data)

            result = self._run(
                input_root,
                output_root,
                _TransparentPaletteOcrProvider(),
                _RecordingReplacementProvider(replacement_text="#"),
            )

            self.assertEqual(2, result.processed_files)
            with Image.open(BytesIO(image_data)) as source_image:
                source_rgba = source_image.convert("RGBA")
            with ZipFile(output_root / "embedded.docx") as archive:
                embedded_data = archive.read("word/media/image1.png")
            for output_data in (
                (output_root / "standalone.png").read_bytes(),
                embedded_data,
            ):
                with Image.open(BytesIO(output_data)) as output_image:
                    self.assertEqual("PNG", output_image.format)
                    self.assertEqual(source_rgba.size, output_image.size)
                    output_rgba = output_image.convert("RGBA")
                self.assertEqual(source_rgba.getpixel((2, 2)), output_rgba.getpixel((2, 2)))
                self.assertEqual(source_rgba.getpixel((70, 50)), output_rgba.getpixel((70, 50)))
                replacement_alpha = [
                    cast(tuple[int, ...], output_rgba.getpixel((x, y)))[3]
                    for x in range(10, 47)
                    for y in range(8, 37)
                ]
                self.assertEqual(255, max(replacement_alpha))

    # Verifies FR-2026-10-27-02.
    def test_embedded_docx_bitmap_skip_is_recorded_with_its_package_part(self) -> None:
        class _TinyRegionOcrProvider(_EmptyOcrProvider):
            def recognize(self, request: OcrRequest) -> OcrResult:
                polygon = BoundingPolygon(
                    (PixelPoint(10, 10), PixelPoint(13, 10), PixelPoint(13, 13), PixelPoint(10, 13))
                )
                return OcrResult((OcrText("xqzv", 0.99, polygon),))

        with TemporaryDirectory() as directory:
            root = Path(directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            image_data = BytesIO()
            Image.new("RGB", (120, 40), "white").save(image_data, "PNG")
            with ZipFile(input_root / "embedded.docx", "w", ZIP_DEFLATED) as archive:
                archive.writestr("word/media/image1.png", image_data.getvalue())

            result = self._run(
                input_root,
                output_root,
                _TinyRegionOcrProvider(),
                _RecordingReplacementProvider(replacement_text="Internationalisation" * 3),
                diagnostics_enabled=True,
            )

            self.assertEqual(0, result.failed_files)
            report = json.loads((output_root / "embedded.docx.diagnostics.json").read_text("utf-8"))
            skipped = [
                entry
                for entry in report["entries"]
                if entry.get("reason_code") == "bitmap_replacement_text_does_not_fit"
            ]
            self.assertEqual(1, len(skipped))
            self.assertEqual({"package_part": "word/media/image1.png"}, skipped[0]["location"])

    # Verifies FR-2026-08-22-02.
    def test_include_patterns_select_relative_supported_paths(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            selected_directory = input_root / "selected"
            selected_directory.mkdir(parents=True)
            self._write_png(selected_directory / "keep.png")
            self._write_png(input_root / "skip.png")

            result = self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(),
                include_patterns=("selected/*.png",),
            )

            self.assertEqual(1, result.processed_files)
            self.assertEqual(1, result.ignored_files)
            self.assertTrue((output_root / "selected" / "keep.png").is_file())
            self.assertFalse((output_root / "skip.png").exists())
            self.assertFalse((output_root / "skip.png.diagnostics.json").exists())

    # Verifies FR-2026-08-22-02.
    def test_include_patterns_allow_comma_separated_repeated_values_and_zero_matches(self) -> None:
        self.assertEqual(
            ("*.png", "nested/*.pdf", "*.docx"),
            parse_include_patterns(("*.png,nested/*.pdf", "*.docx")),
        )
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            parse_include_patterns(("*.png,",))

        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            self._write_png(input_root / "source.png")

            result = self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(),
                include_patterns=("*.pdf",),
            )

            self.assertEqual(0, result.processed_files)
            self.assertEqual(1, result.ignored_files)
            self.assertEqual(
                {
                    "progress": 0,
                    "eta_seconds": None,
                    "files": {"source.png": {"status": "skipped"}},
                },
                json.loads((output_root / "progress.json").read_text(encoding="utf-8")),
            )

    # Verifies FR-2026-08-03-04.
    def test_writes_live_machine_readable_progress_for_all_input_files(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            selected_root = input_root / "selected"
            selected_root.mkdir(parents=True)
            self._write_png(selected_root / "complete.png")
            (selected_root / "failed.docx").write_bytes(b"not a zip archive")
            self._write_png(input_root / "excluded.png")
            (input_root / "unsupported.txt").write_text("synthetic", encoding="utf-8")
            snapshots: list[folder_processor.ProgressEntries] = []
            original_write = folder_processor._write_progress_file

            def capture_progress(
                progress_root: Path,
                progress: int,
                eta_seconds: float | None,
                entries: folder_processor.ProgressEntries,
                eta_status: str | None = None,
            ) -> None:
                original_write(progress_root, progress, eta_seconds, entries, eta_status)
                json.loads((progress_root / "progress.json").read_text(encoding="utf-8"))
                snapshots.append({path: dict(entry) for path, entry in entries.items()})

            with patch.object(
                folder_processor, "_write_progress_file", side_effect=capture_progress
            ):
                result = self._run(
                    input_root,
                    output_root,
                    _EmptyOcrProvider(),
                    _RecordingReplacementProvider(),
                    include_patterns=("selected/*",),
                )

            self.assertEqual(1, result.processed_files)
            self.assertEqual(1, result.failed_files)
            failure_message = result.failures[0].removeprefix(
                f"{selected_root / 'failed.docx'}: "
            )
            self.assertEqual(
                {
                    "progress": 100,
                    "eta_seconds": None,
                    "files": {
                        "excluded.png": {"status": "skipped"},
                        "selected/complete.png": {
                            "status": "completed",
                            "progress": 100,
                            "eta_seconds": 0,
                        },
                        "selected/failed.docx": {
                            "status": "failed",
                            "progress": 0,
                            "details": failure_message,
                        },
                        "unsupported.txt": {"status": "skipped"},
                    },
                },
                json.loads((output_root / "progress.json").read_text(encoding="utf-8")),
            )
            self.assertEqual(
                {
                    "excluded.png": {"status": "skipped"},
                    "selected/complete.png": {"status": "queued"},
                    "selected/failed.docx": {"status": "queued"},
                    "unsupported.txt": {"status": "skipped"},
                },
                snapshots[0],
            )
            self.assertIn(
                "processing",
                [
                    snapshot["selected/complete.png"]["status"]
                    for snapshot in snapshots
                ],
            )
            self.assertIn(
                {
                    "status": "processing",
                    "progress": 0,
                    "eta_seconds": None,
                },
                [snapshot["selected/failed.docx"] for snapshot in snapshots],
            )

    # Verifies FR-2026-10-23-02's details property.
    def test_progress_details_follow_each_step_label_and_clear_on_completion(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            Image.new("RGB", (300, 300), "white").save(input_root / "source.png")
            Image.new("RGB", (20, 20), "white").save(input_root / "other.png")
            snapshots: list[folder_processor.ProgressEntries] = []
            original_write = folder_processor._write_progress_file

            def capture_progress(
                progress_root: Path,
                progress: int,
                eta_seconds: float | None,
                entries: folder_processor.ProgressEntries,
                eta_status: str | None = None,
            ) -> None:
                original_write(progress_root, progress, eta_seconds, entries, eta_status)
                snapshots.append({path: dict(entry) for path, entry in entries.items()})

            with patch.object(folder_processor, "_write_progress_file", side_effect=capture_progress):
                result = self._run(
                    input_root,
                    output_root,
                    _VectorOutlineOcrProvider(),
                    _RecordingReplacementProvider(),
                    include_patterns=("source.png",),
                )

            self.assertEqual(1, result.processed_files)
            entries = [snapshot["source.png"] for snapshot in snapshots]
            self.assertNotIn("details", entries[0])
            self.assertNotIn(
                "details",
                next(entry for entry in entries if entry["status"] == "processing"),
            )
            labels = [entry["details"] for entry in entries if "details" in entry]
            self.assertEqual(
                ["Planning image 1 of 1", "Translating batch 1 of 1", "Applying image 1 of 1"],
                list(dict.fromkeys(labels)),
            )
            self.assertEqual({"status": "completed", "progress": 100, "eta_seconds": 0}, entries[-1])
            self.assertEqual({"status": "skipped"}, snapshots[-1]["other.png"])
            self.assertTrue(all("eta_status" not in entry for entry in entries))

    # Verifies FR-2026-10-23-02's eta_status property.
    def test_unknown_eta_is_labelled_calculating_only_while_an_estimate_is_missing(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            Image.new("RGB", (20, 20), "white").save(input_root / "source.png")
            documents: list[dict[str, object]] = []
            original_write = folder_processor._write_progress_file

            def capture_progress(
                progress_root: Path,
                progress: int,
                eta_seconds: float | None,
                entries: folder_processor.ProgressEntries,
                eta_status: str | None = None,
            ) -> None:
                original_write(progress_root, progress, eta_seconds, entries, eta_status)
                documents.append(json.loads((progress_root / "progress.json").read_text(encoding="utf-8")))

            # The estimate is unknown, known, then unknown again, as Rich reports when timing is poor.
            display = _EtaLiveProgress([None, 12.5, None, 0.0])
            with (
                patch.object(folder_processor, "_write_progress_file", side_effect=capture_progress),
                patch("pipeline.folder_replacement.processor.LiveProgress", return_value=display),
            ):
                self._run(
                    input_root,
                    output_root,
                    _EmptyOcrProvider(),
                    _RecordingReplacementProvider(),
                    show_progress=True,
                )

            for document in documents:
                top_level_known = document["eta_seconds"] is not None
                self.assertEqual(not top_level_known, document.get("eta_status") == "Calculating")
                for entry in cast(dict[str, dict[str, object]], document["files"]).values():
                    if "eta_seconds" in entry:
                        self.assertEqual(
                            entry["eta_seconds"] is None, entry.get("eta_status") == "Calculating"
                        )
                    else:
                        self.assertNotIn("eta_status", entry)
            processing = [
                cast(dict[str, dict[str, object]], document["files"])["source.png"]
                for document in documents
                if cast(dict[str, dict[str, object]], document["files"])["source.png"]["status"]
                == "processing"
            ]
            self.assertIn("Calculating", [entry.get("eta_status") for entry in processing])
            self.assertIn(12.5, [entry["eta_seconds"] for entry in processing])
            self.assertEqual(
                {"status": "completed", "progress": 100, "eta_seconds": 0},
                cast(dict[str, dict[str, object]], documents[-1]["files"])["source.png"],
            )

    # Verifies FR-2026-08-03-04.
    def test_progress_write_retries_a_transient_lock_and_then_succeeds(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory)
            real_replace = os.replace
            attempts: list[int] = []

            def locked_twice(source: Path, destination: Path) -> None:
                attempts.append(1)
                if len(attempts) <= 2:
                    raise PermissionError(5, "Access is denied")
                real_replace(source, destination)

            sleeps: list[float] = []
            with (
                patch.object(os, "replace", side_effect=locked_twice),
                patch.object(time, "sleep", side_effect=sleeps.append),
            ):
                folder_processor._write_progress_file(output_root, 10, None, {"a.png": {"status": "queued"}})

            self.assertEqual(3, len(attempts))
            self.assertEqual(2, len(sleeps))
            self.assertEqual(
                {"progress": 10, "eta_seconds": None, "files": {"a.png": {"status": "queued"}}},
                json.loads((output_root / "progress.json").read_text(encoding="utf-8")),
            )

    # Verifies FR-2026-08-03-04.
    def test_progress_write_gives_up_after_the_five_second_budget(self) -> None:
        clock = [0.0]

        def sleep(seconds: float) -> None:
            clock[0] += seconds

        attempts: list[int] = []

        def always_locked() -> None:
            attempts.append(1)
            raise PermissionError(5, "Access is denied")

        with self.assertRaises(folder_processor.ProgressWriteError) as raised:
            folder_processor._retry_progress_write(
                always_locked, Path("progress.json"), sleep=sleep, monotonic=lambda: clock[0]
            )

        self.assertGreater(len(attempts), 3)
        self.assertGreaterEqual(clock[0], 5.0)
        self.assertLess(clock[0], 5.5)
        self.assertIn("progress.json", str(raised.exception))

    # Verifies FR-2026-08-03-04.
    def test_locked_progress_file_is_skipped_with_one_warning_and_processing_continues(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            self._write_png(input_root / "first.png")
            self._write_png(input_root / "second.png")
            stderr = StringIO()

            def locked(*_: object, **__: object) -> None:
                raise folder_processor.ProgressWriteError(
                    output_root / "progress.json", 5.0, PermissionError(5, "Access is denied")
                )

            with (
                patch.object(folder_processor, "_write_progress_file", side_effect=locked) as write,
                redirect_stderr(stderr),
            ):
                result = self._run(
                    input_root,
                    output_root,
                    _EmptyOcrProvider(),
                    _RecordingReplacementProvider(),
                )

            self.assertGreater(write.call_count, 2)
            self.assertEqual(2, result.processed_files)
            self.assertEqual(0, result.failed_files)
            self.assertEqual([], result.failures)
            self.assertEqual(1, stderr.getvalue().count("Warning: Could not write progress file"))
            self.assertNotIn("Failed:", stderr.getvalue())

    # Verifies FR-2026-10-26-02.
    def test_skips_office_temporary_owner_files(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            nested_root = input_root / "nested"
            owner_directory = input_root / "~$folder"
            nested_root.mkdir(parents=True)
            owner_directory.mkdir()
            for owner_file in (
                input_root / "~$report.docx",
                input_root / "~$book.xlsx",
                nested_root / "~$deck.pptx",
            ):
                owner_file.write_bytes(b"\x05synthetic owner")
            self._write_png(input_root / "plain.png")
            self._write_png(input_root / "~$matched.png")
            self._write_png(owner_directory / "inside.png")

            result = self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(),
                include_patterns=("*.docx", "*.png", "nested/*"),
            )

            self.assertEqual(2, result.processed_files)
            self.assertEqual(0, result.failed_files)
            self.assertEqual([], result.failures)
            self.assertEqual(
                ["inside.png", "plain.png"],
                sorted(path.name for path in output_root.rglob("*.png")),
            )
            self.assertFalse(
                any(path.name.startswith("~$") and path.is_file() for path in output_root.rglob("*"))
            )
            progress = json.loads((output_root / "progress.json").read_text(encoding="utf-8"))
            self.assertEqual(100, progress["progress"])
            self.assertEqual(
                2, sum(entry["status"] == "completed" for entry in progress["files"].values())
            )
            for skipped in ("~$report.docx", "~$book.xlsx", "nested/~$deck.pptx", "~$matched.png"):
                self.assertEqual({"status": "skipped"}, progress["files"][skipped])

    # Verifies FR-2026-08-03-03.
    def test_processes_supported_files_ignores_others_and_resolves_filename_collisions(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            self._write_png(input_root / "first.png")
            self._write_png(input_root / "second.png")
            (input_root / "ignore.txt").write_text("ignore", encoding="utf-8")
            provider = _RecordingReplacementProvider("same.png")

            result = self._run(input_root, output_root, _EmptyOcrProvider(), provider)

            self.assertEqual(2, result.processed_files)
            self.assertEqual(1, result.ignored_files)
            self.assertEqual(0, result.failed_files)
            self.assertTrue((output_root / "same.png").is_file())
            self.assertTrue((output_root / "same (2).png").is_file())
            self.assertFalse((output_root / "ignore.txt.diagnostics.json").exists())

    # Verifies FR-2026-10-27-01.
    def test_sanitises_translated_output_filenames_for_windows(self) -> None:
        cases = {
            "Title: Subtitle.png": "Title- Subtitle.png",
            "A<>:\"|?*B.png": "A-B.png",
            "A  \t B.png": "A - B.png",
            "Name . .png": "Name.png",
            "  Lead.png": "Lead.png",
            "con.png": "_con.png",
            "COM1.png": "_COM1.png",
            "Console.png": "Console.png",
            "???.png": "-.png",
            ". .png": "source.png",
            "Valid name.png": "Valid name.png",
            "Version 1.2: Plan": "Version 1.2- Plan.png",
        }
        for translated, expected in cases.items():
            with self.subTest(translated=translated), TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                input_root = root / "input"
                output_root = root / "output"
                input_root.mkdir()
                self._write_png(input_root / "source.png")

                result = self._run(
                    input_root, output_root, _EmptyOcrProvider(), _RecordingReplacementProvider(translated)
                )

                self.assertEqual(0, result.failed_files)
                self.assertTrue((output_root / expected).is_file())
                progress = json.loads((output_root / "progress.json").read_text(encoding="utf-8"))
                self.assertIn("source.png", progress["files"])

    # Verifies FR-2026-10-27-01.
    def test_sanitised_output_filenames_that_collide_are_numbered(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            self._write_png(input_root / "first.png")
            self._write_png(input_root / "second.png")

            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), _RecordingReplacementProvider("A:B.png")
            )

            self.assertEqual(0, result.failed_files)
            self.assertTrue((output_root / "A-B.png").is_file())
            self.assertTrue((output_root / "A-B (2).png").is_file())

    # Verifies FR-2026-10-27-01.
    def test_path_separators_in_translated_filenames_are_still_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            self._write_png(input_root / "source.png")

            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), _RecordingReplacementProvider("a/b.png")
            )

            self.assertEqual(1, result.failed_files)

    # Verifies FR-2026-10-27-02.
    def test_bitmap_region_whose_text_cannot_fit_is_skipped_without_failing_the_document(self) -> None:
        class _TwoRegionOcrProvider(_EmptyOcrProvider):
            def recognize(self, request: OcrRequest) -> OcrResult:
                def region(text: str, left: int, top: int, right: int, bottom: int) -> OcrText:
                    return OcrText(
                        text,
                        0.99,
                        BoundingPolygon(
                            (
                                PixelPoint(left, top),
                                PixelPoint(right, top),
                                PixelPoint(right, bottom),
                                PixelPoint(left, bottom),
                            )
                        ),
                    )

                return OcrResult((region("fits", 5, 5, 95, 35), region("xqzv", 110, 10, 113, 13)))

        long_word = "Internationalisation" * 3
        for diagnostics_enabled in (False, True):
            with self.subTest(diagnostics_enabled=diagnostics_enabled), TemporaryDirectory() as directory:
                root = Path(directory)
                input_root = root / "input"
                output_root = root / "output"
                input_root.mkdir()
                Image.new("RGB", (120, 40), "white").save(input_root / "sample.png", "PNG")

                result = self._run(
                    input_root,
                    output_root,
                    _TwoRegionOcrProvider(),
                    _RecordingReplacementProvider(replacement_text=long_word),
                    diagnostics_enabled=diagnostics_enabled,
                )

                self.assertEqual(1, result.processed_files)
                self.assertEqual(0, result.failed_files)
                self.assertEqual(1, result.replaced_image_regions)
                self.assertTrue((output_root / "sample.png").is_file())
                sidecar = output_root / "sample.png.diagnostics.json"
                if not diagnostics_enabled:
                    self.assertFalse(sidecar.exists())
                    continue
                text = sidecar.read_text("utf-8")
                skipped = [
                    entry
                    for entry in json.loads(text)["entries"]
                    if entry.get("reason_code") == "bitmap_replacement_text_does_not_fit"
                ]
                self.assertEqual(1, len(skipped))
                self.assertEqual("skipped", skipped[0]["kind"])
                self.assertEqual(1, skipped[0]["region_index"])
                self.assertEqual(3.0, skipped[0]["region_width_pixels"])
                self.assertEqual(3.0, skipped[0]["region_height_pixels"])
                self.assertEqual(len(long_word), skipped[0]["replacement_characters"])
                self.assertNotIn(long_word, text)
                self.assertNotIn("xqzv", text)

    # Verifies FR-2026-08-03-03.
    def test_replaces_office_native_text_in_word_drawing_and_spreadsheet_parts(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            source = input_root / "document.docx"
            with ZipFile(source, "w", ZIP_DEFLATED) as archive:
                archive.writestr(
                    "word/document.xml",
                    """<?xml version=\"1.0\"?><w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:body><w:p><w:r><w:t>Word</w:t></w:r></w:p></w:body></w:document>""",
                )
                archive.writestr(
                    "ppt/slides/slide1.xml",
                    """<?xml version=\"1.0\"?><p:sld xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\" xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\"><a:t>Slide</a:t></p:sld>""",
                )
                archive.writestr(
                    "xl/sharedStrings.xml",
                    """<?xml version=\"1.0\"?><sst xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><si><t>Cell</t></si></sst>""",
                )
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), _RecordingReplacementProvider()
            )

            self.assertEqual(1, result.processed_files)
            self.assertEqual(3, result.replaced_native_text_items)
            with ZipFile(output_root / "document.docx") as archive:
                payload = "\n".join(
                    archive.read(part).decode("utf-8")
                    for part in (
                        "word/document.xml",
                        "ppt/slides/slide1.xml",
                        "xl/sharedStrings.xml",
                    )
                )
            self.assertNotIn("Word", payload)
            self.assertNotIn("Slide", payload)
            self.assertNotIn("Cell", payload)
            self.assertIn("####", payload)
            self.assertIn("#####", payload)

    # Verifies FR-2026-08-03-08.
    def test_preserves_compatibility_prefix_required_by_rewritten_office_xml(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            with ZipFile(input_root / "document.pptx", "w", ZIP_DEFLATED) as archive:
                archive.writestr(
                    "ppt/slides/slide1.xml",
                    """<?xml version=\"1.0\"?>
                    <p:sld xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\"
                      xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\"
                      xmlns:mc=\"http://schemas.openxmlformats.org/markup-compatibility/2006\"
                      xmlns:p14=\"http://schemas.microsoft.com/office/powerpoint/2010/main\">
                      <a:t>Mask</a:t>
                      <mc:AlternateContent><mc:Choice Requires=\"p14\"><p14:content/></mc:Choice></mc:AlternateContent>
                    </p:sld>""",
                )

            self._run(input_root, output_root, _EmptyOcrProvider(), _RecordingReplacementProvider())

            with ZipFile(output_root / "document.pptx") as archive:
                xml = archive.read("ppt/slides/slide1.xml")
            self.assertIn(b'Requires="p14"', xml)
            self.assertIn(
                b'xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main"',
                xml,
            )

    # Verifies FR-2026-08-03-03.
    def test_processes_every_embedded_office_bitmap(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            image_data = BytesIO()
            Image.new("RGB", (20, 20), "white").save(image_data, "PNG")
            with ZipFile(input_root / "document.docx", "w", ZIP_DEFLATED) as archive:
                archive.writestr("word/media/image1.png", image_data.getvalue())
            ocr_provider = _CountingOcrProvider()

            result = self._run(
                input_root, output_root, ocr_provider, _RecordingReplacementProvider()
            )

            self.assertEqual(1, result.processed_files)
            self.assertEqual(1, ocr_provider.calls)
            with ZipFile(output_root / "document.docx") as archive:
                self.assertTrue(archive.read("word/media/image1.png"))

    # Verifies FR-2026-08-03-04.
    def test_reports_file_name_and_document_work_progress(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            image_data = BytesIO()
            Image.new("RGB", (20, 20), "white").save(image_data, "PNG")
            with ZipFile(input_root / "document.docx", "w", ZIP_DEFLATED) as archive:
                archive.writestr("word/media/image1.png", image_data.getvalue())
            progress_bars: list[_RecordedProgress] = []

            def make_progress(total: int, label: str) -> ProgressReporter:
                progress = _RecordedProgress(total, label)
                progress_bars.append(progress)
                return progress

            standard_output = StringIO()
            with redirect_stdout(standard_output):
                result = self._run(
                    input_root,
                    output_root,
                    _CountingOcrProvider(),
                    _RecordingReplacementProvider(),
                    show_progress=True,
                    progress_factory=make_progress,
                )

            self.assertEqual(1, result.processed_files)
            self.assertEqual("Processing: document.docx\n", standard_output.getvalue())
            self.assertEqual(1, len(progress_bars))
            self.assertEqual(2, progress_bars[0].total)
            self.assertEqual("document.docx", progress_bars[0].label)
            self.assertEqual(
                ["Planning image 1 of 1", "Applying image 1 of 1"],
                progress_bars[0].postfixes,
            )
            self.assertEqual(2, progress_bars[0].updates)
            self.assertTrue(progress_bars[0].closed)

    # Verifies FR-2026-09-03-01.
    def test_embedded_bitmap_ocr_uses_the_nested_progress_row(self) -> None:
        class _RecordingLiveProgress:
            def __init__(self) -> None:
                self.started: list[tuple[str, int, str]] = []
                self.advanced: list[str] = []
                self.cleared = 0

            def __enter__(self) -> "_RecordingLiveProgress":
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def start_overall(self, _total: int, _unit: str) -> None:
                return None

            def start_current(self, _name: str, _total: int, _unit: str) -> "_RecordingLiveProgress":
                return self

            def set_postfix_str(self, _label: str) -> None:
                return None

            def update(self) -> None:
                return None

            def set_overall_from_current(self, _completed_sources: int) -> None:
                return None

            def complete_overall_source(self, _completed_sources: int) -> None:
                return None

            def overall_state(self) -> tuple[int, float | None]:
                return 0, None

            def clear_current(self) -> None:
                return None

            def current_state(self) -> tuple[int, float | None]:
                return 0, None

            def start_nested(self, name: str, total: int, unit: str = "stage") -> None:
                self.started.append((name, total, unit))

            def advance_nested(self, label: str) -> None:
                self.advanced.append(label)

            def clear_nested(self) -> None:
                self.cleared += 1

        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            image_data = BytesIO()
            Image.new("RGB", (20, 20), "white").save(image_data, "PNG")
            with ZipFile(input_root / "document.docx", "w", ZIP_DEFLATED) as archive:
                archive.writestr("word/media/image1.png", image_data.getvalue())
            display = _RecordingLiveProgress()
            typeface = skia.Typeface.MakeFromFile(str(FONT_PATH))
            assert typeface is not None
            with patch("pipeline.folder_replacement.processor.LiveProgress", return_value=display):
                replace_input_folder(
                    input_root,
                    output_root,
                    ocr_provider=_CountingOcrProvider(),
                    text_replacement_provider=_RecordingReplacementProvider(),
                    source_language="en",
                    target_language="en",
                    typeface=typeface,
                )

            self.assertEqual([("word/media/image1.png", 2, "stage")], display.started)
            self.assertEqual(
                ["OCR recognition", "process OCR results"],
                display.advanced,
            )
            self.assertEqual(1, display.cleared)

    # Verifies FR-2026-08-03-03.
    def test_skips_low_confidence_ocr_text_and_continues_after_a_file_failure(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            self._write_png(input_root / "good.png")
            (input_root / "broken.png").write_bytes(b"not an image")
            provider = _RecordingReplacementProvider()

            failure_output = StringIO()
            with redirect_stderr(failure_output):
                result = self._run(
                    input_root,
                    output_root,
                    _LowConfidenceOcrProvider(),
                    provider,
                    diagnostics_enabled=True,
                )

            self.assertEqual(1, result.processed_files)
            self.assertEqual(1, result.failed_files)
            self.assertTrue((output_root / "good.png").is_file())
            diagnostic = output_root / "broken.png.diagnostics.json"
            self.assertTrue(diagnostic.is_file())
            self.assertEqual(
                "file_processing_failed",
                json.loads(diagnostic.read_text(encoding="utf-8"))["entries"][0]["reason_code"],
            )
            self.assertFalse(any(not request.is_filename for request in provider.requests))
            self.assertIn("broken.png", failure_output.getvalue())

class _EtaLiveProgress:
    """A stand-in for the Rich display whose Current ETA follows a fixed script."""

    def __init__(self, current_etas: list[float | None]) -> None:
        self._current_etas = current_etas
        self._reads = 0

    def __enter__(self) -> "_EtaLiveProgress":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def start_overall(self, _total: int, _unit: str) -> None:
        return None

    def start_current(self, _name: str, _total: int, _unit: str) -> "_EtaLiveProgress":
        return self

    def set_postfix_str(self, _label: str) -> None:
        return None

    def update(self) -> None:
        return None

    def set_overall_from_current(self, _completed_sources: int) -> None:
        return None

    def complete_overall_source(self, _completed_sources: int) -> None:
        return None

    def overall_state(self) -> tuple[int, float | None]:
        return 0, None

    def clear_current(self) -> None:
        return None

    def current_state(self) -> tuple[int, float | None]:
        eta = self._current_etas[min(self._reads, len(self._current_etas) - 1)]
        self._reads += 1
        return 0, eta

    def start_nested(self, name: str, total: int, unit: str = "stage") -> None:
        return None

    def advance_nested(self, label: str) -> None:
        return None

    def clear_nested(self) -> None:
        return None


def _transparent_paletted_png() -> bytes:
    """Create a synthetic indexed PNG with transparent and opaque palette entries."""
    image = Image.new("P", (80, 60), 0)
    image.putpalette([240, 230, 220, 20, 50, 200] + [0] * 762)
    image.info["transparency"] = bytes([0, 255])
    ImageDraw.Draw(image).text((16, 12), "A", fill=1)
    image.putpixel((70, 50), 1)
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


if __name__ == "__main__":
    unittest.main()
