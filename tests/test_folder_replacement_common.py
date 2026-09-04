#!/usr/bin/env python3
"""Synthetic regression tests for COMMON folder replacement."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
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

from pipeline.folder_replacement import (
    FolderReplacementResult,
    parse_include_patterns,
    replace_input_folder,
)
from pipeline.folder_replacement.processor import ProgressFactory, ProgressReporter
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
            self.assertFalse(output_root.exists())

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
            self.assertEqual(5, progress_bars[0].total)
            self.assertEqual("document.docx", progress_bars[0].label)
            self.assertEqual(
                [
                    "embedded image 1",
                    "native text",
                    "native text layout",
                    "chart cache synchronization",
                    "package write",
                ],
                progress_bars[0].postfixes,
            )
            self.assertEqual(5, progress_bars[0].updates)
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

            def clear_current(self) -> None:
                return None

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

            self.assertEqual([("word/media/image1.png", 3, "stage")], display.started)
            self.assertEqual(
                ["OCR recognition", "process OCR results", "render replacement image"],
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
