#!/usr/bin/env python3
"""Synthetic regression tests for PDF folder replacement."""

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

from PIL import Image
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

class FolderReplacementPdfTests(FolderReplacementTestCase):
    # Verifies FR-2026-08-04-07.
    def test_pdf_basic_layout_embeds_a_fitted_font_for_bounded_freetext(self) -> None:
        with TemporaryDirectory() as temporary:
            input_root = Path(temporary) / "input"; input_root.mkdir()
            output_root = Path(temporary) / "output"
            source = input_root / "annotation.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 100)
            annotation = DictionaryObject({
                NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/FreeText"),
                NameObject("/Rect"): ArrayObject([NumberObject(10), NumberObject(10), NumberObject(100), NumberObject(30)]),
                NameObject("/Contents"): TextStringObject("short"), NameObject("/DA"): TextStringObject("/Helv 16 Tf 0 g"),
            })
            page[NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])
            with source.open("wb") as handle: writer.write(handle)

            result = self._run(input_root, output_root, _EmptyOcrProvider(), _RecordingReplacementProvider(replacement_text="A longer fitted annotation"), document_text_layout="preserve-basic-layout")

            self.assertEqual(1, result.processed_files)
            from pypdf import PdfReader
            output = PdfReader(output_root / "annotation.pdf")
            annotations = cast(ArrayObject, output.pages[0].get("/Annots"))
            annotation_output = cast(DictionaryObject, annotations[0].get_object())
            self.assertIn("longer fitted", str(annotation_output.get("/Contents")))
            annotation_appearance = annotation_output.get("/AP")
            assert annotation_appearance is not None
            appearance_dictionary = cast(DictionaryObject, annotation_appearance.get_object())
            normal_appearance = appearance_dictionary.get("/N")
            assert normal_appearance is not None
            appearance = cast(DictionaryObject, normal_appearance.get_object())
            resources = cast(DictionaryObject, appearance.get("/Resources"))
            fonts = cast(DictionaryObject, resources.get("/Font"))
            self.assertIn("/PipelineNoto", str(resources))
            embedded_font = fonts.get("/PipelineNoto")
            assert embedded_font is not None
            type_zero = cast(DictionaryObject, embedded_font.get_object())
            descendants = type_zero.get("/DescendantFonts")
            assert isinstance(descendants, ArrayObject)
            descendant = cast(DictionaryObject, descendants[0].get_object())
            font_descriptor = descendant.get("/FontDescriptor")
            assert font_descriptor is not None
            descriptor = cast(DictionaryObject, font_descriptor.get_object())
            self.assertIsNotNone(descriptor.get("/FontFile2"))

    # Verifies FR-2026-08-03-03.
    def test_replaces_native_pdf_text_content(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter()
            page = writer.add_blank_page(100, 100)
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 12 Tf 10 10 Td (Hello) Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as source_file:
                writer.write(source_file)

            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), _RecordingReplacementProvider()
            )

            self.assertEqual(1, result.processed_files)
            self.assertEqual(1, result.replaced_native_text_items)
            self.assertIn(b"\\043\\043\\043\\043\\043", (output_root / "document.pdf").read_bytes())

    # Verifies FR-2026-08-29-01 and SR-2026-08-29-01.
    def test_replaces_outlined_pdf_vector_text_through_a_200_dpi_ocr_overlay(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            source = input_root / "outlined.pdf"
            writer = PdfWriter()
            page = writer.add_blank_page(100, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"q 0.8 0.9 1 rg 18 28 65 27 re f "
                b"0 0 0 rg 26 36 4 12 re f 35 36 4 12 re f Q"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as source_file:
                writer.write(source_file)

            ocr_provider = _VectorOutlineOcrProvider()
            result = self._run(
                input_root,
                output_root,
                ocr_provider,
                _RecordingReplacementProvider(),
                diagnostics_enabled=True,
            )

            self.assertEqual(1, result.processed_files)
            self.assertEqual(1, ocr_provider.calls)
            self.assertEqual(1, result.replaced_image_regions)
            output = PdfReader(output_root / "outlined.pdf")
            self.assertIn("#######", output.pages[0].extract_text())
            report = json.loads(
                (output_root / "outlined.pdf.diagnostics.json").read_text(encoding="utf-8")
            )
            summary = report["entries"][0]
            self.assertEqual("vector_ocr_summary", summary["kind"])
            self.assertEqual(1, summary["replacement_written_regions"])
            self.assertNotIn("outlined", json.dumps(summary))

    # Verifies FR-2026-08-29-01.
    def test_replaces_slightly_skewed_vector_ocr_region_with_upright_pdf_text(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            source = input_root / "skewed.pdf"
            writer = PdfWriter()
            page = writer.add_blank_page(100, 100)
            contents = DecodedStreamObject()
            contents.set_data(b"0.8 0.9 1 rg 0 0 100 100 re f")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as source_file:
                writer.write(source_file)

            ocr_provider = _VectorOutlineOcrProvider(polygon=BoundingPolygon((
                PixelPoint(50, 130),
                PixelPoint(230, 136),
                PixelPoint(229, 200),
                PixelPoint(49, 194),
            )))
            result = self._run(
                input_root,
                output_root,
                ocr_provider,
                _RecordingReplacementProvider(),
                diagnostics_enabled=True,
            )

            self.assertEqual(1, result.replaced_image_regions)
            output = PdfReader(output_root / "skewed.pdf")
            stream = ContentStream(output.pages[0].get_contents(), output)
            text_matrix = next(
                operands for operands, operator in stream.operations
                if operator == b"Tm" and len(operands) == 6
            )
            self.assertEqual([1.0, 0.0, 0.0, 1.0], [float(value) for value in text_matrix[:4]])
            report = json.loads(
                (output_root / "skewed.pdf.diagnostics.json").read_text(encoding="utf-8")
            )
            self.assertEqual(1, report["entries"][0]["replacement_written_regions"])

    # Verifies FR-2026-08-29-01 and FR-2026-08-31-01.
    def test_retains_materially_rotated_vector_ocr_region(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            source = input_root / "rotated.pdf"
            writer = PdfWriter()
            page = writer.add_blank_page(100, 100)
            contents = DecodedStreamObject()
            contents.set_data(b"0.8 0.9 1 rg 0 0 100 100 re f")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as source_file:
                writer.write(source_file)

            ocr_provider = _VectorOutlineOcrProvider(polygon=BoundingPolygon((
                PixelPoint(50, 130),
                PixelPoint(230, 150),
                PixelPoint(223, 214),
                PixelPoint(43, 194),
            )))
            result = self._run(
                input_root,
                output_root,
                ocr_provider,
                _RecordingReplacementProvider(),
                diagnostics_enabled=True,
            )

            self.assertEqual(0, result.replaced_image_regions)
            report = json.loads(
                (output_root / "rotated.pdf.diagnostics.json").read_text(encoding="utf-8")
            )
            summary = report["entries"][0]
            self.assertEqual(
                {"vector_ocr_polygon_orientation_unsupported": 1},
                summary["retained_reason_counts"],
            )
            self.assertEqual(
                [{
                    "reason_code": "vector_ocr_polygon_orientation_unsupported",
                    "detected_text": "outlined",
                    "baseline_angle_degrees": 6.3,
                }],
                summary["retained_region_details"],
            )

    # Verifies FR-2026-08-29-01 and TR-2026-08-29-01.
    def test_skips_pdfium_and_ocr_for_native_text_only_pdf_page(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            source = input_root / "native.pdf"
            writer = PdfWriter()
            page = writer.add_blank_page(100, 100)
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 12 Tf 10 10 Td (Hello) Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as source_file:
                writer.write(source_file)

            ocr_provider = _CountingOcrProvider()
            with patch("pipeline.folder_replacement.pdf.pdfium.PdfDocument") as renderer:
                result = self._run(
                    input_root, output_root, ocr_provider, _RecordingReplacementProvider()
                )

            self.assertEqual(1, result.processed_files)
            self.assertEqual(0, ocr_provider.calls)
            renderer.assert_not_called()

    # Verifies FR-2026-08-29-02.
    def test_runs_one_ocr_pass_for_undecodable_native_pdf_text_and_writes_overlay(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "undecodable.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(100, 100)
            font = writer._add_object(DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type0"),
                NameObject("/BaseFont"): NameObject("/Synthetic"),
                NameObject("/Encoding"): NameObject("/Identity-H"),
                NameObject("/DescendantFonts"): ArrayObject([writer._add_object(DictionaryObject({
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/CIDFontType2"),
                    NameObject("/DW"): NumberObject(1000),
                }))]),
            }))
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
            })
            contents = DecodedStreamObject(); contents.set_data(b"BT /F1 12 Tf 10 10 Td <0001> Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as source_file: writer.write(source_file)

            provider = _VectorOutlineOcrProvider()
            result = self._run(
                input_root, output_root, provider, _RecordingReplacementProvider(),
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(1, result.replaced_image_regions)
            output_reader = PdfReader(output_root / "undecodable.pdf")
            stream = ContentStream(output_reader.pages[0].get_contents(), output_reader)
            self.assertTrue(any(
                operator == b"Tf" and operands[0] == "/PipelineNoto"
                for operands, operator in stream.operations
            ))

    # Verifies FR-2026-08-29-01 and TR-2026-08-29-01.
    def test_runs_vector_ocr_when_only_an_invoked_form_paints_vectors(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            source = input_root / "form.pdf"
            writer = PdfWriter()
            page = writer.add_blank_page(100, 100)
            form = DecodedStreamObject()
            form.set_data(b"0 0 0 rg 10 10 30 20 re f")
            form.update({
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Form"),
                NameObject("/BBox"): ArrayObject([
                    NumberObject(0), NumberObject(0), NumberObject(100), NumberObject(100)
                ]),
            })
            form_reference = writer._add_object(form)
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/XObject"): DictionaryObject({NameObject("/Form1"): form_reference})
            })
            contents = DecodedStreamObject()
            contents.set_data(b"q /Form1 Do Q")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as source_file:
                writer.write(source_file)

            ocr_provider = _CountingOcrProvider()
            result = self._run(
                input_root, output_root, ocr_provider, _RecordingReplacementProvider()
            )

            self.assertEqual(1, result.processed_files)
            self.assertEqual(1, ocr_provider.calls)

    # Verifies FR-2026-08-29-01.
    def test_retains_low_confidence_outlined_pdf_vector_text(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            source = input_root / "outlined.pdf"
            writer = PdfWriter()
            page = writer.add_blank_page(100, 100)
            contents = DecodedStreamObject()
            contents.set_data(b"0.8 0.9 1 rg 18 28 65 27 re f")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as source_file:
                writer.write(source_file)

            result = self._run(
                input_root,
                output_root,
                _VectorOutlineOcrProvider(0.64),
                _RecordingReplacementProvider(),
                diagnostics_enabled=True,
            )

            self.assertEqual(0, result.replaced_image_regions)
            report = json.loads(
                (output_root / "outlined.pdf.diagnostics.json").read_text(encoding="utf-8")
            )
            summary = report["entries"][0]
            self.assertEqual(
                {"vector_ocr_confidence_below_threshold": 1},
                summary["retained_reason_counts"],
            )

    # Verifies SR-2026-08-29-01.
    def test_retains_oversized_pdf_page_before_vector_renderer_invocation(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            source = input_root / "oversized.pdf"
            writer = PdfWriter()
            page = writer.add_blank_page(3_000, 3_000)
            contents = DecodedStreamObject()
            contents.set_data(b"0 0 0 rg 1 1 1 1 re f")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as source_file:
                writer.write(source_file)

            ocr_provider = _CountingOcrProvider()
            result = self._run(
                input_root,
                output_root,
                ocr_provider,
                _RecordingReplacementProvider(),
                diagnostics_enabled=True,
            )

            self.assertEqual(0, result.replaced_image_regions)
            self.assertEqual(0, ocr_provider.calls)
            report = json.loads(
                (output_root / "oversized.pdf.diagnostics.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                {"vector_ocr_page_size_limit": 1},
                report["entries"][0]["retained_reason_counts"],
            )

    # Verifies FR-2026-08-23-01.
    def test_basic_layout_pdf_content_uses_the_safe_replacement_font(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(100, 100)
            contents = DecodedStreamObject(); contents.set_data(b"BT /F1 12 Tf 10 10 Td [(Hel) 0 (lo)] TJ ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as source_file: writer.write(source_file)

            provider = _RecordingReplacementProvider()
            self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )
            self.assertEqual(["Hello"], [
                request.text for request in provider.requests if not request.is_filename
            ])

            output = PdfReader(output_root / "document.pdf")
            stream = ContentStream(output.pages[0].get_contents(), output)
            self.assertTrue(any(operator == b"Tf" and operands[0] == "/PipelineNoto" for operands, operator in stream.operations))
            self.assertTrue(any(
                operator == b"Tr" and operands and int(operands[0]) == 3
                for operands, operator in stream.operations
            ))
            self.assertNotIn("Hello", output.pages[0].extract_text())
            fonts = cast(DictionaryObject, cast(DictionaryObject, output.pages[0]["/Resources"])["/Font"])
            type_zero = cast(DictionaryObject, fonts["/PipelineNoto"].get_object())
            descendant = cast(DictionaryObject, cast(ArrayObject, type_zero["/DescendantFonts"])[0].get_object())
            self.assertTrue(descendant.get("/W"))

    # Verifies FR-2026-08-02-06 and FR-2026-08-24-02.
    def test_basic_layout_pdf_character_mask_preserves_distinct_whitespace_semantics(self) -> None:
        """Assign separate CIDs when the embedded font reuses a whitespace glyph."""
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(100, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"BT /F1 12 Tf 10 10 Td <FEFF0041002000A00042> Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as source_file:
                writer.write(source_file)

            result = self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                CharacterMaskProvider(),
                document_text_layout="preserve-basic-layout",
                diagnostics_enabled=True,
            )

            self.assertEqual(1, result.replaced_native_text_items)
            self.assertEqual([], result.diagnostic_sidecars)
            output = PdfReader(output_root / "document.pdf")
            self.assertIn("# \u00A0#", output.pages[0].extract_text())
            fonts = cast(DictionaryObject, cast(DictionaryObject, output.pages[0]["/Resources"])["/Font"])
            type_zero = cast(DictionaryObject, fonts["/PipelineNoto"].get_object())
            to_unicode = cast(DecodedStreamObject, type_zero["/ToUnicode"].get_object())
            mapping = to_unicode.get_data()
            self.assertIn(b"<0002> <0020>", mapping)
            self.assertIn(b"<0003> <00A0>", mapping)

    # Verifies FR-2026-08-27-06.
    def test_basic_layout_pdf_reports_font_serialization_not_region_reconstruction(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(100, 100)
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 12 Tf 10 10 Td (source) Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as source_file:
                writer.write(source_file)

            with patch(
                "pipeline.folder_replacement.pdf._pdf_static_glyph_bytes",
                side_effect=_PdfReplacementSerializationError(
                    "pdf_replacement_font_encoding_invalid",
                    "Synthetic portable-font serialization failure.",
                    "######",
                ),
            ):
                result = self._run(
                    input_root,
                    output_root,
                    _EmptyOcrProvider(),
                    _RecordingReplacementProvider(),
                    document_text_layout="preserve-basic-layout",
                    diagnostics_enabled=True,
                )

            self.assertEqual(0, result.replaced_native_text_items)
            self.assertEqual(1, len(result.diagnostic_sidecars))
            report = json.loads(result.diagnostic_sidecars[0].read_text(encoding="utf-8"))
            self.assertEqual(
                [{
                    "kind": "unsupported",
                    "reason_code": "pdf_replacement_font_encoding_invalid",
                    "container_kind": "pdf_visual_text",
                    "page": 1,
                    "replacement_text": "######",
                }],
                [{key: entry[key] for key in (
                    "kind", "reason_code", "container_kind", "page", "replacement_text"
                )} for entry in report["entries"]],
            )

    # Verifies FR-2026-08-27-06.
    def test_basic_layout_pdf_records_unsupported_portable_text_and_keeps_the_region(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(100, 100)
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 12 Tf 10 10 Td (Hello) Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as source_file:
                writer.write(source_file)

            with patch(
                "pipeline.folder_replacement.pdf._pdf_fitted_region_operations",
                side_effect=PortableTextUnsupportedError(
                    "portable_font_coverage_unsupported",
                    "\U0001f9ea",
                    ("Noto Sans", "Noto Sans Symbols 2"),
                    replacement_text="\U0001f9ea",
                ),
            ):
                result = self._run(
                    input_root,
                    output_root,
                    _EmptyOcrProvider(),
                    _RecordingReplacementProvider(replacement_text="\U0001f9ea"),
                    document_text_layout="preserve-basic-layout",
                    diagnostics_enabled=True,
                )

            self.assertEqual(1, result.processed_files)
            self.assertEqual(0, result.failed_files)
            self.assertIn(b"(Hello)", (output_root / "document.pdf").read_bytes())
            sidecar = json.loads(
                (output_root / "document.pdf.diagnostics.json").read_text(encoding="utf-8")
            )
            self.assertEqual("pdf_visual_text", sidecar["entries"][0]["container_kind"])
            self.assertEqual(
                ["Noto Sans", "Noto Sans Symbols 2"],
                sidecar["entries"][0]["candidate_faces"],
            )
            self.assertEqual(["U+1F9EA"], sidecar["entries"][0]["code_points"])
            self.assertEqual("Hello", sidecar["entries"][0]["source_text"])
            self.assertEqual("\U0001f9ea", sidecar["entries"][0]["replacement_text"])
            self.assertEqual(
                "pdf_page_user_space",
                sidecar["entries"][0]["region_location"]["coordinate_space"],
            )
            self.assertEqual(
                ["source_text", "replacement_text"],
                list(sidecar["entries"][0])[:2],
            )

    # Verifies FR-2026-08-31-02.
    def test_basic_layout_pdf_classifies_a_leading_private_use_bullet_candidate(self) -> None:
        region = _synthetic_pdf_visual_region("\uf0d8Inputs\n\uf0d8Scope", "/F1")
        error = PortableTextUnsupportedError(
            "portable_font_coverage_unsupported",
            "\uf0d8",
            ("Noto Sans JP", "Noto Sans Math", "Noto Sans Symbols 2"),
            replacement_text="➢ Inputs for analysis\n\uf0d8 Scope",
        )

        self.assertTrue(_pdf_is_candidate_bullet_error(region, error))
        self.assertFalse(_pdf_is_candidate_bullet_error(
            _synthetic_pdf_visual_region("Inputs\nScope \uf0d8", "/F1"), error
        ))
        self.assertFalse(_pdf_is_candidate_bullet_error(
            _synthetic_pdf_visual_region("\uf0d8X", "/F1"),
            PortableTextUnsupportedError(
                "portable_font_coverage_unsupported",
                "\uf0d8",
                error.selected_faces,
                replacement_text="\uf0d8 X",
            ),
        ))
        self.assertFalse(_pdf_is_candidate_bullet_error(
            region,
            PortableTextUnsupportedError(
                "portable_font_coverage_unsupported",
                "\uf0d8x",
                error.selected_faces,
                replacement_text=error.replacement_text,
            ),
        ))

    # Verifies FR-2026-08-31-02.
    def test_basic_layout_pdf_places_candidate_fields_before_region_location(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(100, 100)
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 12 Tf 10 10 Td (source) Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as source_file:
                writer.write(source_file)

            region = _synthetic_pdf_visual_region("\uf0d8Subject", "/F3")
            error = PortableTextUnsupportedError(
                "portable_font_coverage_unsupported",
                "\uf0d8",
                ("Noto Sans JP", "Noto Sans Symbols 2"),
                replacement_text="\uf0d8 Subject",
            )
            with patch(
                "pipeline.folder_replacement.pdf._pdf_visual_regions",
                return_value=(region,),
            ), patch(
                "pipeline.folder_replacement.pdf._pdf_fitted_region_operations",
                side_effect=error,
            ):
                self._run(
                    input_root,
                    output_root,
                    _EmptyOcrProvider(),
                    _RecordingReplacementProvider(),
                    document_text_layout="preserve-basic-layout",
                    diagnostics_enabled=True,
                )

            entry = json.loads(
                (output_root / "document.pdf.diagnostics.json").read_text(encoding="utf-8")
            )["entries"][0]
            self.assertEqual(
                ["code_points", "candidate_kind", "source_font_resource_name", "region_location"],
                list(entry)[list(entry).index("code_points"):list(entry).index("region_location") + 1],
            )

    # Verifies FR-2026-08-31-02.
    def test_basic_layout_pdf_applies_a_reviewed_leading_bullet_mapping_once(self) -> None:
        box = BoundedTextBox(
            1_000, 1_000, 0, 0, 0, 0, None,
            (BoundedTextParagraph(
                None, None, None, None, None, 0, None, None, None, None, None,
                (BoundedTextRun("\uf0d8 Subject\n\uf0d8 Scope", None, "sans-serif", 12, False, False, "none", None),),
            ),),
        )
        with patch(
            "pipeline.portable_bullet_overrides.LEGACY_BULLET_OVERRIDES",
            (LegacyBulletOverride("\uf0d8", "➢", "/F1"),),
        ):
            mapped = _pdf_apply_legacy_bullet_override(
                box, "\uf0d8Subject\n\uf0d8Scope", "/F1"
            )

        self.assertEqual("➢ Subject\n➢ Scope", mapped.paragraphs[0].runs[0].text)

    # Verifies FR-2026-09-01-01 and FR-2026-08-31-02.
    def test_basic_layout_pdf_maps_a_colour_span_bullet_with_following_context(self) -> None:
        marker = _synthetic_pdf_visual_region("\uf097", "/F9").anchor
        prose = _synthetic_pdf_visual_region("Subject", "/F1").anchor
        source_spans = (
            _PdfPaintSpan("\uf097", marker),
            _PdfPaintSpan("Subject", prose),
        )
        replacement_spans = [
            _PdfPaintSpan("\uf097", marker),
            _PdfPaintSpan("translated subject", prose),
        ]

        mapped = _pdf_apply_paint_span_bullet_overrides(
            source_spans, replacement_spans
        )

        self.assertEqual("➢", mapped[0].text)
        self.assertEqual("translated subject", mapped[1].text)

    # Verifies FR-2026-08-31-02.
    def test_basic_layout_pdf_uses_a_reviewed_mapping_for_output_without_a_second_request(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(100, 100)
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 12 Tf 10 10 Td (@Hello) Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as source_file:
                writer.write(source_file)

            provider = _RecordingReplacementProvider(replacement_text="@ Subject")
            with patch(
                "pipeline.portable_bullet_overrides.LEGACY_BULLET_OVERRIDES",
                (LegacyBulletOverride("@", "•", "/F1"),),
            ):
                result = self._run(
                    input_root,
                    output_root,
                    _EmptyOcrProvider(),
                    provider,
                    document_text_layout="preserve-basic-layout",
                )

            self.assertEqual(1, result.replaced_native_text_items)
            self.assertEqual(["@Hello"], [
                request.text for request in provider.requests if not request.is_filename
            ])
            self.assertIn("• Subject", PdfReader(output_root / "document.pdf").pages[0].extract_text())

    # Verifies FR-2026-08-23-01.
    def test_basic_layout_pdf_splits_widely_spaced_tj_fragments_into_visual_regions(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(240, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"BT /F1 12 Tf 10 60 Td [(one) -5000 (two) -5000 (three) -5000 (four)] TJ ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as source_file:
                writer.write(source_file)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(4, result.replaced_native_text_items)
            self.assertEqual(["one", "two", "three", "four"], [
                request.text for request in provider.requests if not request.is_filename
            ])
            output = PdfReader(output_root / "document.pdf")
            stream = ContentStream(output.pages[0].get_contents(), output)
            font_name = ""
            text_matrix: list[float] | None = None
            generated_x_positions: list[float] = []
            for operands, operator in stream.operations:
                if operator == b"Tf":
                    font_name = str(operands[0])
                elif operator == b"Tm":
                    text_matrix = [float(value) for value in operands]
                elif operator == b"Tj" and font_name == "/PipelineNoto" and text_matrix is not None:
                    generated_x_positions.append(text_matrix[4])
            self.assertEqual(4, len(generated_x_positions))
            self.assertEqual(generated_x_positions, sorted(generated_x_positions))
            self.assertGreater(min(
                right - left for left, right in zip(generated_x_positions, generated_x_positions[1:])
            ), 40.0)

    # Verifies FR-2026-08-30-05.
    def test_basic_layout_pdf_widens_a_clear_single_line_corridor(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(600, 100)
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 20 Tf 10 60 Td (A) Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file:
                writer.write(output_file)

            for layout_mode in ("preserve-basic-layout", "preserve-basic-layout-source-font"):
                mode_output = output_root / layout_mode
                result = self._run(
                    input_root,
                    mode_output,
                    _EmptyOcrProvider(),
                    _RecordingReplacementProvider(
                        replacement_text="A deliberately much longer translated heading"
                    ),
                    document_text_layout=layout_mode,
                )

                self.assertEqual(1, result.replaced_native_text_items)
                self.assertAlmostEqual(
                    self._pdf_generated_replacement_font_size(mode_output / "document.pdf"),
                    20.0,
                    places=4,
                )

    # Verifies FR-2026-08-30-05.
    def test_basic_layout_pdf_accepts_an_80_percent_source_sized_single_line(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(370, 100)
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 20 Tf 10 60 Td (A) Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file:
                writer.write(output_file)

            self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(
                    replacement_text="A deliberately much longer translated heading"
                ),
                document_text_layout="preserve-basic-layout",
                diagnostics_enabled=True,
            )

            font_size = self._pdf_generated_replacement_font_size(
                output_root / "document.pdf"
            )
            self.assertGreaterEqual(font_size, 16.0)
            self.assertLess(font_size, 20.0)
            self.assertFalse((output_root / "document.pdf.diagnostics.json").exists())

    # Verifies FR-2026-08-30-05.
    def test_basic_layout_pdf_widens_past_a_non_intersecting_form_background(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(600, 100)
            background = DecodedStreamObject()
            background.set_data(b"1 g 0 0 600 100 re f")
            background.update({
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Form"),
                NameObject("/BBox"): ArrayObject([
                    NumberObject(0), NumberObject(0), NumberObject(600), NumberObject(100),
                ]),
            })
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/XObject"): DictionaryObject({NameObject("/Background"): background}),
            })
            contents = DecodedStreamObject()
            contents.set_data(b"q /Background Do Q BT /F1 20 Tf 10 60 Td (A) Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file:
                writer.write(output_file)

            self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(
                    replacement_text="A deliberately much longer translated heading"
                ),
                document_text_layout="preserve-basic-layout",
            )

            self.assertAlmostEqual(
                self._pdf_generated_replacement_font_size(output_root / "document.pdf"),
                20.0,
                places=4,
            )

    # Verifies FR-2026-08-30-05.
    def test_basic_layout_pdf_widens_within_a_rectangular_clip_over_an_artifact_background(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(600, 100)
            background = DecodedStreamObject(); background.set_data(b"\xff\xff\xff")
            background.update({
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(1),
                NameObject("/Height"): NumberObject(1),
                NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
                NameObject("/BitsPerComponent"): NumberObject(8),
            })
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/XObject"): DictionaryObject({NameObject("/Background"): background}),
            })
            contents = DecodedStreamObject()
            contents.set_data(
                b"/Artifact BMC q 600 0 0 100 0 0 cm /Background Do Q EMC "
                b"q 0 0 600 100 re W n BT /F1 20 Tf 10 60 Td (A) Tj ET Q"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file:
                writer.write(output_file)

            self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(
                    replacement_text="A deliberately much longer translated heading"
                ),
                document_text_layout="preserve-basic-layout",
            )

            self.assertAlmostEqual(
                self._pdf_generated_replacement_font_size(output_root / "document.pdf"),
                20.0,
                places=4,
            )

    # Verifies FR-2026-08-30-05.
    def test_basic_layout_pdf_widens_inside_a_filled_rounded_container_but_not_through_a_connector(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            rounded_container = (
                b"0.8 g "
                b"20 25 m 190 25 l 198.284 25 205 31.716 205 40 c "
                b"205 60 l 205 68.284 198.284 75 190 75 c "
                b"20 75 l 11.716 75 5 68.284 5 60 c "
                b"5 40 l 5 31.716 11.716 25 20 25 c h f "
            )
            inputs = {
                "contained.pdf": rounded_container + b"BT /F1 20 Tf 10 45 Td (A) Tj ET",
                "connector.pdf": (
                    rounded_container
                    + b"0 0 0 RG 45 25 m 45 75 l S "
                    + b"BT /F1 20 Tf 10 45 Td (A) Tj ET"
                ),
            }
            for filename, data in inputs.items():
                writer = PdfWriter(); page = writer.add_blank_page(240, 100)
                contents = DecodedStreamObject(); contents.set_data(data)
                page.replace_contents(ContentStream(contents, writer))
                with (input_root / filename).open("wb") as output_file:
                    writer.write(output_file)

            self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(replacement_text="A much longer label"),
                document_text_layout="preserve-basic-layout",
            )

            contained_size = self._pdf_generated_replacement_font_size(
                output_root / "contained.pdf"
            )
            self.assertAlmostEqual(contained_size, 20.0, places=4)
            self.assertLess(
                self._pdf_generated_replacement_font_size(output_root / "connector.pdf"),
                contained_size,
            )

    # Verifies FR-2026-08-30-05.
    def test_basic_layout_pdf_does_not_widen_into_a_vector_rule_or_multiline_block(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            replacement = "A deliberately much longer translated heading"
            inputs = {
                "clear.pdf": b"BT /F1 20 Tf 10 60 Td (A) Tj ET",
                "vector-rule.pdf": (
                    b"0 0 0 RG 25 45 m 25 75 l S "
                    b"BT /F1 20 Tf 10 60 Td (A) Tj ET"
                ),
                "multiline.pdf": b"BT /F1 20 Tf 24 TL 10 70 Td (A) Tj T* (B) Tj ET",
            }
            for filename, data in inputs.items():
                writer = PdfWriter(); page = writer.add_blank_page(600, 100)
                contents = DecodedStreamObject(); contents.set_data(data)
                page.replace_contents(ContentStream(contents, writer))
                with (input_root / filename).open("wb") as output_file:
                    writer.write(output_file)

            result = self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(replacement_text=replacement),
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(3, result.replaced_native_text_items)
            clear_size = self._pdf_generated_replacement_font_size(output_root / "clear.pdf")
            self.assertLess(
                self._pdf_generated_replacement_font_size(output_root / "vector-rule.pdf"),
                clear_size / 2.0,
            )
            self.assertLess(
                self._pdf_generated_replacement_font_size(output_root / "multiline.pdf"),
                clear_size / 2.0,
            )

    # Verifies FR-2026-08-30-05.
    def test_basic_layout_pdf_bounds_unsupported_curves_locally_for_expansion(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            replacement = "A deliberately much longer translated heading"
            inputs = {
                "distant-curve.pdf": (
                    b"0 g 300 10 m 320 10 330 30 340 30 c S "
                    b"BT /F1 20 Tf 10 60 Td (A) Tj ET"
                ),
                "blocking-curve.pdf": (
                    b"0 g 24 45 m 24 50 24 70 24 75 c S "
                    b"BT /F1 20 Tf 10 60 Td (A) Tj ET"
                ),
            }
            for filename, data in inputs.items():
                writer = PdfWriter(); page = writer.add_blank_page(600, 100)
                contents = DecodedStreamObject(); contents.set_data(data)
                page.replace_contents(ContentStream(contents, writer))
                with (input_root / filename).open("wb") as output_file:
                    writer.write(output_file)

            self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(replacement_text=replacement),
                document_text_layout="preserve-basic-layout",
                diagnostics_enabled=True,
            )

            self.assertAlmostEqual(
                self._pdf_generated_replacement_font_size(
                    output_root / "distant-curve.pdf"
                ),
                20.0,
                places=4,
            )
            distant_report = output_root / "distant-curve.pdf.diagnostics.json"
            self.assertFalse(distant_report.exists())

            blocking_report = json.loads((
                output_root / "blocking-curve.pdf.diagnostics.json"
            ).read_text(encoding="utf-8"))
            fallback = next(
                entry for entry in blocking_report["entries"]
                if entry["kind"] == "layout_fallback"
            )
            self.assertEqual(
                "pdf_single_line_expansion_corridor_too_narrow",
                fallback["reason_code"],
            )
            self.assertIn("full_corridor_fit_status", fallback)

    # Verifies FR-2026-08-30-05.
    def test_basic_layout_pdf_treats_only_unbounded_graphics_or_annotations_as_unknown(self) -> None:
        self.assertFalse(_pdf_expansion_geometry_is_known([([], b"Do")]))
        self.assertFalse(_pdf_expansion_geometry_is_known([([], b"INLINE IMAGE")]))
        self.assertTrue(_pdf_expansion_geometry_is_known([([], b"W")]))
        self.assertFalse(_pdf_expansion_geometry_is_known([([], b"c")]))

        writer = PdfWriter()
        page = writer.add_blank_page(100, 100)
        page[NameObject("/Annots")] = ArrayObject([DictionaryObject()])
        self.assertTrue(_pdf_content_has_annotations(page))

    # Verifies FR-2026-08-30-05.
    def test_basic_layout_pdf_records_only_failed_single_line_expansions(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            inputs = {
                "unknown-geometry.pdf": (
                    b"/MissingTemplate Do BT /F1 20 Tf 10 60 Td (A) Tj ET"
                ),
                "no-corridor.pdf": (
                    b"0 g BT /F1 20 Tf 10 60 Td (A) Tj ET "
                    b"1 0 0 rg BT /F1 20 Tf 21 60 Td (B) Tj ET"
                ),
                "narrow-corridor.pdf": (
                    b"0 0 0 RG 25 45 m 25 75 l S "
                    b"BT /F1 20 Tf 10 60 Td (A) Tj ET"
                ),
            }
            for filename, data in inputs.items():
                writer = PdfWriter(); page = writer.add_blank_page(600, 100)
                contents = DecodedStreamObject(); contents.set_data(data)
                page.replace_contents(ContentStream(contents, writer))
                with (input_root / filename).open("wb") as output_file:
                    writer.write(output_file)

            self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(
                    replacement_text="A deliberately much longer translated heading"
                ),
                document_text_layout="preserve-basic-layout",
                diagnostics_enabled=True,
            )

            expected_reasons = {
                "unknown-geometry.pdf": "pdf_single_line_expansion_geometry_unavailable",
                # FR-2026-09-01-01 treats the adjacent colour-only text as
                # one visual flow, so its remaining page corridor is fitted.
                "no-corridor.pdf": "pdf_single_line_expansion_corridor_too_narrow",
                "narrow-corridor.pdf": "pdf_single_line_expansion_corridor_too_narrow",
            }
            for filename, expected_reason in expected_reasons.items():
                report = json.loads(
                    (output_root / f"{filename}.diagnostics.json").read_text(encoding="utf-8")
                )
                entries = [
                    entry for entry in report["entries"]
                    if entry["kind"] == "layout_fallback"
                ]
                self.assertEqual(1, len(entries))
                self.assertEqual(expected_reason, entries[0]["reason_code"])
                self.assertIn("source_region_width", entries[0])
                self.assertIn("source_effective_font_size", entries[0])
                expected_source_text = "AB" if filename == "no-corridor.pdf" else "A"
                self.assertEqual(expected_source_text, entries[0]["source_text"])
                expected_replacement_text = "A deliberately much longer translated heading" * (
                    2 if filename == "no-corridor.pdf" else 1
                )
                if filename == "no-corridor.pdf":
                    expected_replacement_text = (
                        "A deliberately much longer translated heading "
                        "A deliberately much longer translated heading"
                    )
                self.assertEqual(
                    expected_replacement_text,
                    entries[0]["replacement_text"],
                )
                if filename in {"narrow-corridor.pdf", "no-corridor.pdf"}:
                    self.assertIn("full_corridor_fit_status", entries[0])
                    self.assertIn("full_corridor_font_scale", entries[0])
                    self.assertIn("full_corridor_effective_font_size", entries[0])
                    self.assertIn("full_corridor_line_count", entries[0])
                else:
                    self.assertNotIn("full_corridor_fit_status", entries[0])

    # Verifies FR-2026-08-30-05.
    def test_basic_layout_pdf_omits_diagnostics_for_successful_or_non_candidate_lines_that_fit(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            inputs = {
                "successful.pdf": b"BT /F1 20 Tf 10 60 Td (A) Tj ET",
                "already-fitting.pdf": (
                    b"BT /F1 5 Tf 10 60 Td " + b"(" + b"W" * 50 + b") Tj ET"
                ),
                "multiline.pdf": b"BT /F1 20 Tf 24 TL 10 70 Td (A) Tj T* (B) Tj ET",
            }
            for filename, data in inputs.items():
                writer = PdfWriter(); page = writer.add_blank_page(600, 100)
                contents = DecodedStreamObject(); contents.set_data(data)
                page.replace_contents(ContentStream(contents, writer))
                with (input_root / filename).open("wb") as output_file:
                    writer.write(output_file)

            self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(
                    replacement_text="A deliberately much longer translated heading"
                ),
                document_text_layout="preserve-basic-layout",
                diagnostics_enabled=True,
            )

            for filename in ("successful.pdf", "already-fitting.pdf"):
                self.assertFalse((output_root / f"{filename}.diagnostics.json").exists())
            multiline_report = json.loads(
                (output_root / "multiline.pdf.diagnostics.json").read_text(encoding="utf-8")
            )
            multiline_entries = [
                entry for entry in multiline_report["entries"]
                if entry["kind"] == "layout_expansion_excluded"
            ]
            self.assertEqual(1, len(multiline_entries))
            self.assertEqual(
                "pdf_single_line_expansion_excluded_inferred_multiline_region",
                multiline_entries[0]["reason_code"],
            )

    # Verifies FR-2026-08-30-05.
    def test_basic_layout_pdf_records_wrapped_single_line_excluded_by_clipping(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            writer = PdfWriter(); page = writer.add_blank_page(220, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"q 0 0 m 220 0 l 110 100 l h W n BT /F1 20 Tf 10 60 Td (A) Tj ET Q"
            )
            page.replace_contents(ContentStream(contents, writer))
            with (input_root / "clipped.pdf").open("wb") as output_file:
                writer.write(output_file)

            replacement_text = "A deliberately much longer translated heading"
            self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(replacement_text=replacement_text),
                document_text_layout="preserve-basic-layout",
                diagnostics_enabled=True,
            )

            report = json.loads(
                (output_root / "clipped.pdf.diagnostics.json").read_text(encoding="utf-8")
            )
            entries = [
                entry for entry in report["entries"]
                if entry["kind"] == "layout_expansion_excluded"
            ]
            self.assertEqual(1, len(entries))
            self.assertEqual(
                "pdf_single_line_expansion_excluded_clipping", entries[0]["reason_code"]
            )
            self.assertEqual("A", entries[0]["source_text"])
            self.assertEqual(replacement_text, entries[0]["replacement_text"])
            self.assertEqual(1, entries[0]["source_visual_line_count"])
            self.assertTrue(
                entries[0]["normal_output_line_count"] > 1
                or entries[0]["normal_font_scale"] < 0.8
            )

    # Verifies FR-2026-08-23-01.
    def test_basic_layout_pdf_splits_close_tj_fragments_at_a_table_cell_gap(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(120, 100)
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 12 Tf 10 60 Td [(value) -600 (unit)] TJ ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as source_file:
                writer.write(source_file)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(2, result.replaced_native_text_items)
            self.assertEqual(["value", "unit"], [
                request.text for request in provider.requests if not request.is_filename
            ])

    # Verifies FR-2026-08-24-02.
    def test_basic_layout_pdf_identity_replaces_through_the_fitted_output_path(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(100, 100)
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 12 Tf 10 10 Td (Hello) Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider(replacement_text="Hello")
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(1, result.replaced_native_text_items)
            self.assertEqual(["Hello"], [request.text for request in provider.requests if not request.is_filename])
            output = PdfReader(output_root / "document.pdf")
            stream = ContentStream(output.pages[0].get_contents(), output)
            self.assertTrue(any(
                operator == b"Tf" and operands[0] == "/PipelineNoto"
                for operands, operator in stream.operations
            ))
            self.assertFalse(any(
                operator == b"Tj" and operands and str(operands[0]) == "Hello"
                for operands, operator in stream.operations
            ))
            self.assertEqual("Hello", output.pages[0].extract_text().strip())
            pipeline_font_index = next(
                index for index, (operands, operator) in enumerate(stream.operations)
                if operator == b"Tf" and operands[0] == "/PipelineNoto"
            )
            self.assertTrue(any(
                operator == b"Tj" and operands and str(operands[0])
                for operands, operator in stream.operations[pipeline_font_index:]
            ))

    # Verifies FR-2026-08-24-02.
    def test_basic_layout_pdf_replaces_the_extractable_source_text(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(150, 100)
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 12 Tf 10 10 Td (source) Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file:
                writer.write(output_file)

            self._run(
                input_root, output_root, _EmptyOcrProvider(),
                _RecordingReplacementProvider(replacement_text="replacement"),
                document_text_layout="preserve-basic-layout",
            )

            output = PdfReader(output_root / "document.pdf")
            extracted = output.pages[0].extract_text()
            self.assertIn("replacement", extracted)
            self.assertNotIn("source", extracted)
            fonts = cast(DictionaryObject, cast(DictionaryObject, output.pages[0]["/Resources"])["/Font"])
            type_zero = cast(DictionaryObject, fonts["/PipelineNoto"].get_object())
            self.assertIsNotNone(type_zero.get("/ToUnicode"))

    # Verifies FR-2026-08-24-02 and FR-2026-08-28-04.
    def test_basic_layout_pdf_replaces_a_text_only_actual_text_scope(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(150, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"BT /F1 12 Tf 10 10 Td /Span << /ActualText (alternate) >> BDC "
                b"(protected) Tj EMC 0 -20 Td (replaceable) Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file:
                writer.write(output_file)

            provider = _RecordingReplacementProvider(replacement_text="replacement")
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(2, result.replaced_native_text_items)
            self.assertEqual(["protected", "replaceable"], [
                request.text for request in provider.requests if not request.is_filename
            ])
            output = PdfReader(output_root / "document.pdf")
            self.assertNotIn("protected", output.pages[0].extract_text())
            self.assertNotIn("alternate", output.pages[0].extract_text())
            self.assertIn("replacement", output.pages[0].extract_text())
            stream = ContentStream(output.pages[0].get_contents(), output)
            self.assertTrue(any(
                operator == b"BDC" and len(operands) >= 2
                and isinstance(operands[1], DictionaryObject)
                and "/ActualText" not in operands[1]
                for operands, operator in stream.operations
            ))

    # Verifies FR-2026-08-28-04.
    def test_basic_layout_pdf_rewrites_only_the_replaced_actual_text_invocation(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(150, 100)
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Properties"): DictionaryObject({
                    NameObject("/Shared"): DictionaryObject({
                        NameObject("/ActualText"): TextStringObject("alternate"),
                    }),
                }),
            })
            contents = DecodedStreamObject()
            contents.set_data(
                b"BT /F1 12 Tf 10 10 Td /Span /Shared BDC (replaceable) Tj EMC "
                b"0 -20 Td /Span /Shared BDC /Artifact BMC (retained) Tj EMC EMC ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file:
                writer.write(output_file)

            result = self._run(
                input_root, output_root, _EmptyOcrProvider(),
                _RecordingReplacementProvider(replacement_text="replacement"),
                document_text_layout="preserve-basic-layout",
                diagnostics_enabled=True,
            )

            self.assertEqual(1, result.replaced_native_text_items)
            output = PdfReader(output_root / "document.pdf")
            stream = ContentStream(output.pages[0].get_contents(), output)
            shared_scopes = [
                operands for operands, operator in stream.operations
                if operator == b"BDC" and len(operands) >= 2
            ]
            self.assertIsInstance(shared_scopes[0][1], DictionaryObject)
            self.assertNotIn("/ActualText", shared_scopes[0][1])
            self.assertEqual("/Shared", str(shared_scopes[1][1]))
            resources = cast(DictionaryObject, output.pages[0].get("/Resources"))
            properties = cast(DictionaryObject, resources.get("/Properties"))
            shared_property = cast(DictionaryObject, properties.get("/Shared"))
            self.assertEqual("alternate", str(shared_property.get("/ActualText")))
            diagnostic = json.loads((output_root / "document.pdf.diagnostics.json").read_text())
            self.assertTrue(any(
                entry.get("reason_code") == "pdf_text_marked_content_actual_text"
                for entry in diagnostic["entries"]
            ))

    # Verifies FR-2026-08-23-02 and FR-2026-08-24-02.
    def test_basic_layout_pdf_keeps_each_fitted_region_in_its_source_paint_state(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 100)
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/ExtGState"): DictionaryObject({
                    NameObject("/Full"): DictionaryObject({NameObject("/ca"): NumberObject(1)}),
                    NameObject("/Half"): DictionaryObject({NameObject("/ca"): FloatObject(0.5)}),
                }),
            })
            contents = DecodedStreamObject()
            contents.set_data(
                b"BT /F1 12 Tf 10 70 Td 1 0 0 rg /Full gs (first) Tj "
                b"0 0 1 rg /Half gs 0 -20 Td (second) Tj "
                b"1 0 0 rg /Full gs 0 -20 Td (third) Tj 14 TL T* 1 Tr (outline) Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider(replacement_text="mask")
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(3, result.replaced_native_text_items)
            self.assertEqual(["first", "second", "third"], [
                request.text for request in provider.requests if not request.is_filename
            ])
            output = PdfReader(output_root / "document.pdf")
            stream = ContentStream(output.pages[0].get_contents(), output)
            self.assertEqual(1, sum(operator == b"BT" for _operands, operator in stream.operations))
            self.assertEqual(1, sum(operator == b"ET" for _operands, operator in stream.operations))
            self.assertFalse(any(
                operator == b"Tj" and operands and str(operands[0]) in {"first", "second", "third"}
                for operands, operator in stream.operations
            ))
            outline_index = next(
                index for index, (operands, operator) in enumerate(stream.operations)
                if operator == b"Tj" and operands and str(operands[0]) == "outline"
            )
            self.assertEqual(b"Tr", stream.operations[outline_index - 1][1])
            self.assertEqual(1, int(stream.operations[outline_index - 1][0][0]))

            fill_colour: tuple[float, float, float] | None = None
            opacity: str | None = None
            fitted_paint_states: list[tuple[tuple[float, float, float] | None, str | None]] = []
            for operands, operator in stream.operations:
                if operator == b"rg":
                    fill_colour = (float(operands[0]), float(operands[1]), float(operands[2]))
                elif operator == b"gs":
                    opacity = str(operands[0])
                elif operator == b"Tf" and operands[0] == "/PipelineNoto":
                    fitted_paint_states.append((fill_colour, opacity))
            self.assertEqual([
                ((1.0, 0.0, 0.0), "/Full"),
                ((0.0, 0.0, 1.0), "/Half"),
                ((1.0, 0.0, 0.0), "/Full"),
            ], fitted_paint_states)

    # Verifies FR-2026-08-23-03.
    def test_basic_layout_pdf_replaces_fill_and_stroke_with_fill_only_output(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"2 w 1 0 0 rg 0 0 1 RG BT /F1 12 Tf 14 TL 10 70 Td "
                b"2 Tr (filled and stroked) Tj 0 Tr T* (fill only) Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider(replacement_text="mask")
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(2, result.replaced_native_text_items)
            self.assertEqual(["filled and stroked", "fill only"], [
                request.text for request in provider.requests if not request.is_filename
            ])
            output = PdfReader(output_root / "document.pdf")
            stream = ContentStream(output.pages[0].get_contents(), output)
            self.assertEqual(1, sum(operator == b"BT" for _operands, operator in stream.operations))
            self.assertEqual(1, sum(operator == b"ET" for _operands, operator in stream.operations))

            text_rendering_mode = 0
            generated_modes: list[int] = []
            for operands, operator in stream.operations:
                if operator == b"Tr":
                    text_rendering_mode = int(operands[0])
                elif operator == b"Tf" and operands[0] == "/PipelineNoto":
                    generated_modes.append(text_rendering_mode)
            self.assertEqual([0, 0], generated_modes)
            self.assertTrue(any(
                operator == b"w" and float(operands[0]) == 2.0
                for operands, operator in stream.operations
            ))

    # Verifies FR-2026-08-23-01 and FR-2026-08-24-02.
    def test_basic_layout_pdf_uses_text_matrix_and_ctm_for_fitted_geometry(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(100, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"q 2 0 0 2 0 0 cm BT /F1 10 Tf .5 0 0 .5 10 20 Tm (test) Tj ET Q"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), _RecordingReplacementProvider(),
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(1, result.replaced_native_text_items)
            output = PdfReader(output_root / "document.pdf")
            stream = ContentStream(output.pages[0].get_contents(), output)
            pipeline_font_index = next(
                index for index, (operands, operator) in enumerate(stream.operations)
                if operator == b"Tf" and operands[0] == "/PipelineNoto"
            )
            generated_matrix = next(
                operands for operands, operator in stream.operations[pipeline_font_index:]
                if operator == b"Tm"
            )
            self.assertEqual([0.5, 0.0, 0.0, 0.5], [round(float(value), 4) for value in generated_matrix[:4]])

    # Verifies FR-2026-08-23-01.
    def test_basic_layout_pdf_preserves_an_axis_aligned_nonuniform_transform(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(100, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"q 1.2 0 0 .8 0 0 cm BT /F1 10 Tf 1 0 0 1 10 70 Tm (cell) Tj ET Q"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider(replacement_text="mask")
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(1, result.replaced_native_text_items)
            self.assertEqual(["cell"], [request.text for request in provider.requests if not request.is_filename])
            output = PdfReader(output_root / "document.pdf")
            stream = ContentStream(output.pages[0].get_contents(), output)
            self.assertFalse(any(
                operator == b"Tj" and operands and str(operands[0]) == "cell"
                for operands, operator in stream.operations
            ))
            pipeline_font_index = next(
                index for index, (operands, operator) in enumerate(stream.operations)
                if operator == b"Tf" and operands[0] == "/PipelineNoto"
            )
            generated_matrix = next(
                operands for operands, operator in stream.operations[pipeline_font_index:]
                if operator == b"Tm"
            )
            # The fitted font size absorbs the source's vertical 0.8 scale;
            # the matrix retains the resulting 1.5 horizontal-to-vertical ratio.
            self.assertEqual([1.25, 0.0, 0.0, 1.25], [round(float(value), 4) for value in generated_matrix[:4]])

    # Verifies FR-2026-08-23-01.
    def test_basic_layout_pdf_groups_compatible_text_objects_into_one_visual_block(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"BT /F1 12 Tf 10 70 Td (first line) Tj ET BT /F1 12 Tf 10 56 Td (second line) Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider(replacement_text="a fitted replacement")
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(1, result.replaced_native_text_items)
            self.assertEqual(["first line\nsecond line"], [
                request.text for request in provider.requests if not request.is_filename
            ])

    # Verifies FR-2026-08-23-01.
    def test_basic_layout_pdf_keeps_an_undecodable_operation_but_replaces_a_reset_neighbour(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(100, 100)
            to_unicode = DecodedStreamObject()
            to_unicode.set_data(b"1 beginbfchar\n<0001> <0041>\nendbfchar\n")
            font = writer._add_object(DictionaryObject({
                NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type0"),
                NameObject("/BaseFont"): NameObject("/SyntheticIdentity"), NameObject("/Encoding"): NameObject("/Identity-H"),
                NameObject("/ToUnicode"): writer._add_object(to_unicode),
            }))
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
            })
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 12 Tf 10 10 Td <0002> Tj 1 0 0 1 10 30 Tm <0001> Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(1, result.replaced_native_text_items)
            self.assertEqual(["A"], [request.text for request in provider.requests if not request.is_filename])
            output = PdfReader(output_root / "document.pdf")
            stream = ContentStream(output.pages[0].get_contents(), output)
            self.assertTrue(any(
                operator == b"Tj" and operands and str(operands[0]) == "\x02"
                for operands, operator in stream.operations
            ))

    # Verifies FR-2026-08-30-06 and FR-2026-08-27-06.
    def test_basic_layout_pdf_retains_unverifiable_legacy_simple_truetype_text(self) -> None:
        """Never send an unverified simple-font Unicode map to a provider."""
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; input_root.mkdir()
            output_root = root / "output"
            source = input_root / "document.pdf"
            # A minimal sfnt directory with one Macintosh-only cmap table. It
            # deliberately contains no Unicode cmap, while the PDF ToUnicode
            # CMap itself looks complete and decodable.
            legacy_font_data = (
                b"\x00\x01\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00"
                b"cmap\x00\x00\x00\x00\x00\x00\x00\x1c\x00\x00\x00\x16"
                b"\x00\x00\x00\x01\x00\x01\x00\x00\x00\x00\x00\x0c"
                b"\x00\x06\x00\x0a\x00\x00\x00\x00\x00\x00"
            )
            writer = PdfWriter(); page = writer.add_blank_page(120, 100)
            to_unicode = DecodedStreamObject()
            to_unicode.set_data(
                b"1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
                b"1 beginbfchar\n<01> <0041>\nendbfchar\n"
            )
            font_program = DecodedStreamObject(); font_program.set_data(legacy_font_data)
            descriptor = writer._add_object(DictionaryObject({
                NameObject("/FontFile2"): writer._add_object(font_program),
            }))
            font = writer._add_object(DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/TrueType"),
                NameObject("/BaseFont"): NameObject("/SyntheticLegacy"),
                NameObject("/FirstChar"): NumberObject(1),
                NameObject("/LastChar"): NumberObject(1),
                NameObject("/Widths"): ArrayObject([NumberObject(600)]),
                NameObject("/FontDescriptor"): descriptor,
                NameObject("/ToUnicode"): writer._add_object(to_unicode),
            }))
            resources = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
            })
            page[NameObject("/Resources")] = resources
            form = DecodedStreamObject()
            form.set_data(b"BT /F1 12 Tf 10 20 Td [<01> 0 <01>] TJ ET")
            form.update({
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Form"),
                NameObject("/BBox"): ArrayObject([
                    NumberObject(0), NumberObject(0), NumberObject(100), NumberObject(40),
                ]),
                NameObject("/Resources"): resources,
            })
            xobjects = DictionaryObject({
                NameObject("/X1"): writer._add_object(form),
            })
            resources[NameObject("/XObject")] = xobjects
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 12 Tf 10 60 Td [<01> 0 <01>] TJ ET q /X1 Do Q")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file:
                writer.write(output_file)

            provider = _RecordingReplacementProvider(replacement_text="replacement")
            result = self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                provider,
                document_text_layout="preserve-basic-layout",
                diagnostics_enabled=True,
            )

            self.assertEqual(0, result.replaced_native_text_items)
            self.assertFalse([request for request in provider.requests if not request.is_filename])
            output = PdfReader(output_root / "document.pdf")
            output_page = output.pages[0]
            output_resources = cast(DictionaryObject, output_page["/Resources"])
            output_xobjects = cast(DictionaryObject, output_resources["/XObject"])
            output_form = cast(DecodedStreamObject, output_xobjects["/X1"].get_object())
            for stream_source in (output_page.get_contents(), output_form):
                stream = ContentStream(stream_source, output)
                text_bytes = [
                    (
                        bytes(value) if isinstance(value, ByteStringObject)
                        else str(value).encode("latin-1")
                    )
                    for operands, operator in stream.operations
                    if operator == b"TJ" and operands and isinstance(operands[0], ArrayObject)
                    for value in operands[0]
                    if isinstance(value, (ByteStringObject, TextStringObject))
                ]
                self.assertEqual([b"\x01", b"\x01"], text_bytes)

            entries = json.loads(
                (output_root / "document.pdf.diagnostics.json").read_text(encoding="utf-8")
            )["entries"]
            retained = [entry for entry in entries if entry["reason_code"] == "pdf_text_undecodable"]
            self.assertEqual(2, len(retained))
            self.assertEqual(
                {"pdf_page_content", "pdf_form_xobject"},
                {entry["container_kind"] for entry in retained},
            )
            for entry in retained:
                self.assertEqual("retained", entry["kind"])
                self.assertEqual("TJ", entry["operator"])
                self.assertIsNone(entry["source_text"])
                self.assertEqual("undecodable", entry["source_text_status"])
                self.assertEqual(
                    "unverifiable_legacy_nonunicode_embedded_truetype",
                    entry["font_encoding_status"],
                )
                self.assertIn("cannot be verified", entry["detail"])

    # Verifies FR-2026-08-23-05.
    def test_basic_layout_pdf_advances_past_undecodable_identity_text(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(100, 100)
            to_unicode = DecodedStreamObject()
            to_unicode.set_data(b"1 beginbfchar\n<0001> <0041>\nendbfchar\n")
            descendant = writer._add_object(DictionaryObject({NameObject("/DW"): NumberObject(1000)}))
            descendants = writer._add_object(ArrayObject([descendant]))
            font = writer._add_object(DictionaryObject({
                NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type0"),
                NameObject("/BaseFont"): NameObject("/SyntheticIdentity"), NameObject("/Encoding"): NameObject("/Identity-H"),
                NameObject("/ToUnicode"): writer._add_object(to_unicode),
                NameObject("/DescendantFonts"): descendants,
            }))
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
            })
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 10 Tf 10 30 Td <0002> Tj <0001> Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(1, result.replaced_native_text_items)
            self.assertEqual(["A"], [request.text for request in provider.requests if not request.is_filename])
            output = PdfReader(output_root / "document.pdf")
            stream = ContentStream(output.pages[0].get_contents(), output)
            unknown_index = next(
                index for index, (operands, operator) in enumerate(stream.operations)
                if operator == b"Tj" and operands and str(operands[0]) == "\x02"
            )
            self.assertNotEqual(b"Tr", stream.operations[unknown_index - 1][1])
            pipeline_font_index = next(
                index for index, (operands, operator) in enumerate(stream.operations)
                if operator == b"Tf" and operands[0] == "/PipelineNoto"
            )
            generated_matrix = next(
                operands for operands, operator in stream.operations[pipeline_font_index:]
                if operator == b"Tm"
            )
            self.assertEqual(20.0, float(generated_matrix[4]))

    # Verifies FR-2026-08-23-05.
    def test_basic_layout_pdf_keeps_barrier_when_undecodable_encoding_is_unknown(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(100, 100)
            to_unicode = DecodedStreamObject()
            to_unicode.set_data(b"1 beginbfchar\n<0001> <0041>\nendbfchar\n")
            encoding = writer._add_object(DecodedStreamObject())
            descendant = writer._add_object(DictionaryObject({NameObject("/DW"): NumberObject(1000)}))
            font = writer._add_object(DictionaryObject({
                NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type0"),
                NameObject("/BaseFont"): NameObject("/SyntheticCustom"), NameObject("/Encoding"): encoding,
                NameObject("/ToUnicode"): writer._add_object(to_unicode),
                NameObject("/DescendantFonts"): ArrayObject([descendant]),
            }))
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
            })
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 10 Tf 10 30 Td <0002> Tj <0001> Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(0, result.replaced_native_text_items)
            self.assertFalse([request for request in provider.requests if not request.is_filename])

    # Verifies FR-2026-08-23-01.
    def test_basic_layout_pdf_recovers_at_line_position_resets_after_unknown_advance(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(100, 120)
            to_unicode = DecodedStreamObject()
            to_unicode.set_data(b"1 beginbfchar\n<0001> <0041>\nendbfchar\n")
            descendant = writer._add_object(DictionaryObject({NameObject("/DW"): NumberObject(1000)}))
            font = writer._add_object(DictionaryObject({
                NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type0"),
                NameObject("/BaseFont"): NameObject("/SyntheticIdentity"), NameObject("/Encoding"): NameObject("/Identity-H"),
                NameObject("/ToUnicode"): writer._add_object(to_unicode),
                NameObject("/DescendantFonts"): ArrayObject([descendant]),
            }))
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
            })
            contents = DecodedStreamObject()
            contents.set_data(
                b"BT /F1 10 Tf 12 TL 10 105 Td <02> Tj 0 -15 Td <0001> Tj ET "
                b"BT /F1 10 Tf 12 TL 10 85 Td <02> Tj 0 -15 TD <0001> Tj ET "
                b"BT /F1 10 Tf 12 TL 10 65 Td <02> Tj T* <0001> Tj ET "
                b"BT /F1 10 Tf 12 TL 10 45 Td <02> Tj <0001> ' ET "
                b"BT /F1 10 Tf 12 TL 10 25 Td <02> Tj 0 0 <0001> \" ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file:
                writer.write(output_file)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(5, result.replaced_native_text_items)
            self.assertEqual(
                ["A"] * 5,
                [request.text for request in provider.requests if not request.is_filename],
            )

    # Verifies FR-2026-08-23-06.
    def test_basic_layout_pdf_recovers_unicode_from_an_embedded_identity_font(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            font_data = static_noto_bytes("sans-serif", False)
            source_face = skia.Typeface.MakeFromData(font_data)
            self.assertIsNotNone(source_face)
            glyph = skia.Font(source_face).textToGlyphs("A")[0]
            self.assertLess(glyph, 256)

            writer = PdfWriter(); page = writer.add_blank_page(100, 100)
            font_stream = DecodedStreamObject(); font_stream.set_data(font_data)
            descriptor = writer._add_object(DictionaryObject({
                NameObject("/FontFile2"): writer._add_object(font_stream),
            }))
            descendant = writer._add_object(DictionaryObject({
                NameObject("/DW"): NumberObject(1000),
                NameObject("/CIDToGIDMap"): NameObject("/Identity"),
                NameObject("/FontDescriptor"): descriptor,
            }))
            font = writer._add_object(DictionaryObject({
                NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type0"),
                NameObject("/BaseFont"): NameObject("/SyntheticEmbeddedIdentity"),
                NameObject("/Encoding"): NameObject("/Identity-H"),
                NameObject("/DescendantFonts"): ArrayObject([descendant]),
            }))
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
            })
            source_font = cast(DictionaryObject, font.get_object())
            self.assertEqual(
                "A", _pdf_decode_composite_bytes(glyph.to_bytes(2, "big"), source_font)
            )
            self.assertEqual("A", _pdf_decode_composite_bytes(bytes([glyph]), source_font))
            self.assertIsNone(
                _pdf_decode_composite_bytes(bytes([glyph, glyph, glyph]), source_font)
            )
            non_identity_font = DictionaryObject(source_font)
            non_identity_font[NameObject("/Encoding")] = NameObject("/Identity-V")
            self.assertIsNone(_pdf_decode_composite_bytes(bytes([glyph]), non_identity_font))
            contents = DecodedStreamObject()
            contents.set_data(f"BT /F1 10 Tf 10 30 Td <{glyph:02X}> Tj ET".encode("ascii"))
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file:
                writer.write(output_file)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(1, result.replaced_native_text_items)
            self.assertEqual(
                ["A"],
                [request.text for request in provider.requests if not request.is_filename],
            )

    # Verifies FR-2026-08-24-01.
    def test_type0_pdf_uses_direct_tounicode_parsing_when_the_helper_returns_whitespace(self) -> None:
        to_unicode = DecodedStreamObject()
        to_unicode.set_data(
            b"1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
            b"1 beginbfrange\n<0001> <0001> <0041>\nendbfrange\n"
        )
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type0"),
            NameObject("/Encoding"): NameObject("/Identity-H"),
            NameObject("/ToUnicode"): to_unicode,
        })
        with patch(
            "pipeline.folder_replacement.pdf.get_encoding",
            return_value=("utf-8", {"\x00\x01": " "}),
        ):
            self.assertEqual("A", _pdf_decode_composite_bytes(b"\x00\x01", font))

    # Verifies FR-2026-08-23-01.
    def test_basic_layout_pdf_replaces_tj_text_with_a_whitespace_fragment(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(100, 100)
            to_unicode = DecodedStreamObject()
            to_unicode.set_data(
                b"1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
                b"2 beginbfchar\n<0001> <0041>\n<0002> <0020>\nendbfchar\n"
            )
            descendant = writer._add_object(DictionaryObject({NameObject("/DW"): NumberObject(1000)}))
            font = writer._add_object(DictionaryObject({
                NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type0"),
                NameObject("/BaseFont"): NameObject("/SyntheticIdentity"), NameObject("/Encoding"): NameObject("/Identity-H"),
                NameObject("/ToUnicode"): writer._add_object(to_unicode),
                NameObject("/DescendantFonts"): ArrayObject([descendant]),
            }))
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
            })
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 10 Tf 10 30 Td [<0001> 0 <0002> 0 <0001>] TJ ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file:
                writer.write(output_file)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(1, result.replaced_native_text_items)
            self.assertEqual(["A A"], [
                request.text for request in provider.requests if not request.is_filename
            ])

    # Verifies FR-2026-08-23-01.
    def test_basic_layout_pdf_reflows_one_visual_paragraph_and_replaces_its_source_operations(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"BT /F1 12 Tf 14 TL 10 70 Td (first line) Tj T* (second line) Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider(
                replacement_text="A replacement sentence that needs several wrapped lines."
            )
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(1, result.replaced_native_text_items)
            requests = [request.text for request in provider.requests if not request.is_filename]
            self.assertEqual(["first line\nsecond line"], requests)
            output_reader = PdfReader(output_root / "document.pdf")
            stream = ContentStream(output_reader.pages[0].get_contents(), output_reader)
            self.assertGreaterEqual(sum(operator == b"Tj" for _operands, operator in stream.operations), 3)
            self.assertTrue(any(
                operator == b"Tf" and operands[0] == "/PipelineNoto"
                for operands, operator in stream.operations
            ))

    # Verifies FR-2026-08-29-03.
    def test_basic_layout_pdf_reflows_a_multi_run_prose_block_in_one_request(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"BT /F1 12 Tf 14 TL 10 70 Td (first ) Tj /F2 12 Tf (line) Tj "
                b"T* /F1 12 Tf (second ) Tj /F2 12 Tf (line) Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider(
                replacement_text="One translated sentence that may reflow."
            )
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(1, result.replaced_native_text_items)
            self.assertEqual(["first line\nsecond line"], [
                request.text for request in provider.requests if not request.is_filename
            ])

    # Verifies FR-2026-08-29-03.
    def test_basic_layout_pdf_uses_dominant_style_and_portable_output_for_a_multi_run_line(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"BT /F1 12 Tf 10 70 Td (dominant text ) Tj /F2 12 Tf (x) Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            source_fonts: list[object | None] = []
            def inspect_anchor(
                region: _PdfVisualRegion,
                replacement_provider: TextReplacementProvider,
                source_language: str,
                target_language: str,
                static_fonts: dict[str, tuple[str, object]],
                font_resources: dict[str, object],
                source_font: bool,
                *,
                expanded_width: float | None = None,
            ) -> list[tuple[list[object], bytes]] | None:
                current_font = region.anchor.current_font
                source_fonts.append(current_font[0] if current_font is not None else None)
                return _pdf_fitted_region_operations(
                    region,
                    replacement_provider,
                    source_language,
                    target_language,
                    static_fonts,
                    font_resources,
                    source_font,
                    expanded_width=expanded_width,
                )

            with patch(
                "pipeline.folder_replacement.pdf._pdf_fitted_region_operations",
                side_effect=inspect_anchor,
            ):
                result = self._run(
                    input_root, output_root, _EmptyOcrProvider(), _RecordingReplacementProvider(),
                    document_text_layout="preserve-basic-layout-source-font",
                )

            self.assertEqual(1, result.replaced_native_text_items)
            self.assertEqual(["/F1"], [str(font) for font in source_fonts])
            output_reader = PdfReader(output_root / "document.pdf")
            stream = ContentStream(output_reader.pages[0].get_contents(), output_reader)
            self.assertTrue(any(
                operator == b"Tf" and operands[0] == "/PipelineNoto"
                for operands, operator in stream.operations
            ))

    # Verifies FR-2026-08-29-03.
    def test_basic_layout_pdf_reflows_prose_across_equivalent_graphics_wrappers(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"q 0 g 0 0 200 100 re W* n /Span << >> BDC BT /F1 12 Tf 10 70 Td "
                b"(first line) Tj ET EMC Q "
                b"q 0 g 0 0 200 100 re W* n /Span << >> BDC BT /F1 12 Tf 10 56 Td "
                b"(second line) Tj ET EMC Q"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(1, result.replaced_native_text_items)
            self.assertEqual(["first line\nsecond line"], [
                request.text for request in provider.requests if not request.is_filename
            ])

    # Verifies FR-2026-08-29-03.
    def test_basic_layout_pdf_does_not_merge_across_intervening_styled_heading(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"BT 0 g /F1 18 Tf 10 84 Td (title) Tj ET "
                b"BT 1 0 0 rg /F1 12 Tf 10 70 Td (heading) Tj ET "
                b"BT 0 g /F1 12 Tf 10 56 Td (body) Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(3, result.replaced_native_text_items)
            self.assertEqual(["title", "heading", "body"], [
                request.text for request in provider.requests if not request.is_filename
            ])

    # Verifies FR-2026-08-29-04.
    def test_basic_layout_pdf_does_not_merge_same_style_title_and_smaller_body(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"BT 0 g /F1 18 Tf 10 84 Td (title) Tj ET "
                b"BT 0 g /F1 12 Tf 10 56 Td (body) Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(2, result.replaced_native_text_items)
            self.assertEqual(["title", "body"], [
                request.text for request in provider.requests if not request.is_filename
            ])

    # Verifies FR-2026-08-29-05.
    def test_basic_layout_pdf_keeps_incrementing_numbered_list_items_separate(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 130)
            contents = DecodedStreamObject()
            contents.set_data(
                b"BT /F1 12 Tf 14 TL 10 112 Td (1. first) Tj T* (2. second) Tj "
                b"T* (3. third) Tj T* (4. fourth) Tj T* (5. fifth) Tj T* (6. sixth) Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(6, result.replaced_native_text_items)
            self.assertEqual([
                "1. first", "2. second", "3. third", "4. fourth", "5. fifth", "6. sixth",
            ], [request.text for request in provider.requests if not request.is_filename])

    # Verifies FR-2026-08-30-01.
    def test_basic_layout_pdf_keeps_incrementing_circled_list_items_separate(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"BT /F1 12 Tf 14 TL 10 70 Td <FEFF2460002000660069007200730074> Tj "
                b"T* <FEFF24610020007300650063006F006E0064> Tj "
                b"T* <FEFF2462002000740068006900720064> Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(3, result.replaced_native_text_items)
            self.assertEqual(3, len([request for request in provider.requests if not request.is_filename]))

    # Verifies FR-2026-08-30-01.
    def test_basic_layout_pdf_does_not_treat_an_isolated_circled_marker_as_a_list(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"BT /F1 12 Tf 14 TL 10 70 Td <FEFF2460002000660069007200730074> Tj "
                b"T* (continuation) Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(1, result.replaced_native_text_items)
            self.assertEqual(1, len([request for request in provider.requests if not request.is_filename]))

    # Verifies FR-2026-08-30-01.
    def test_basic_layout_pdf_keeps_incrementing_alpha_and_roman_list_items_separate(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 180)
            contents = DecodedStreamObject()
            contents.set_data(
                b"BT /F1 12 Tf 14 TL 10 154 Td (A. first) Tj T* (B. second) Tj "
                b"T* (C. third) Tj ET "
                b"BT /F1 12 Tf 14 TL 10 98 Td (i\\) first) Tj T* (ii\\) second) Tj "
                b"T* (iii\\) third) Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(6, result.replaced_native_text_items)
            self.assertEqual(6, len([request for request in provider.requests if not request.is_filename]))

    # Verifies FR-2026-08-30-01.
    def test_basic_layout_pdf_requires_three_alpha_or_roman_list_markers(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 180)
            contents = DecodedStreamObject()
            contents.set_data(
                b"BT /F1 12 Tf 14 TL 10 154 Td (A. first) Tj T* (B. second) Tj ET "
                b"BT /F1 12 Tf 14 TL 10 98 Td (i\\) first) Tj T* (ii\\) second) Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(2, result.replaced_native_text_items)
            self.assertEqual(2, len([request for request in provider.requests if not request.is_filename]))

    # Verifies FR-2026-09-01-01.
    def test_basic_layout_pdf_reflows_an_emphasised_ordered_item_with_its_continuation(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(300, 200)
            contents = DecodedStreamObject()
            contents.set_data(
                b"0 G 0 g BT /F1 14 Tf 14 TL 50 160 Td (1. first heading) Tj "
                b"10 0 Td T* (continuation one) Tj ET "
                b"1 0 0 RG 1 0 0 rg BT /F1 14 Tf 10 132 Td (2. emphasised finding) Tj ET "
                b"0 G 0 g BT /F1 14 Tf 14 TL 10 118 Td (continuation two) Tj "
                b"T* (continued) Tj ET "
                b"BT /F1 14 Tf 10 76 Td (3. third heading) Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider(
                replacement_text="A deliberately longer translated replacement sentence."
            )
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(3, result.replaced_native_text_items)
            self.assertEqual([
                "1. first heading\ncontinuation one",
                "2. emphasised finding\n",
                "continuation two\ncontinued",
                "3. third heading",
            ], [request.text for request in provider.requests if not request.is_filename])

    # Verifies FR-2026-09-01-01.
    def test_basic_layout_pdf_reflows_inline_colour_emphasis_with_per_span_translation(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(180, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"BT /F1 16 Tf 10 70 Td 0 g (Before) Tj 1 0 0 rg (emphasis) Tj "
                b"0 g (after) Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as source_file:
                writer.write(source_file)

            class SpanProvider:
                def __init__(self) -> None:
                    self.requests: list[TextReplacementRequest] = []

                def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                    self.requests.append(request)
                    replacements = {
                        "Before": "A longer introduction",
                        "emphasis": "highlighted finding",
                        "after": "followed by a conclusion",
                    }
                    return TextReplacementResult(replacements.get(request.text, request.text), 1.0)

            provider = SpanProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(1, result.replaced_native_text_items)
            self.assertEqual(["Before", "emphasis", "after"], [
                request.text for request in provider.requests if not request.is_filename
            ])
            output = PdfReader(output_root / "document.pdf")
            stream = ContentStream(output.pages[0].get_contents(), output)
            generated_font_sizes = [
                float(operands[1])
                for operands, operator in stream.operations
                if operator == b"Tf" and operands[0] == "/PipelineNoto"
            ]
            self.assertTrue(generated_font_sizes)
            self.assertEqual(1, len(set(generated_font_sizes)))
            self.assertGreater(sum(operator == b"Tm" for _operands, operator in stream.operations), 1)
            self.assertTrue(any(
                operator == b"rg" and tuple(float(value) for value in operands) == (1.0, 0.0, 0.0)
                for operands, operator in stream.operations
            ))
            self.assertIn(
                "A longer introduction highlighted finding followed by a conclusion",
                " ".join(output.pages[0].extract_text().split()),
            )

    # Verifies FR-2026-08-30-03.
    def test_basic_layout_pdf_keeps_interleaved_colour_rows_inside_list_items_separate(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(300, 240)
            contents = DecodedStreamObject()
            contents.set_data(
                b"0 g BT /F1 14 Tf 14 TL 20 210 Td (1. first heading) Tj "
                b"T* (first continuation) Tj ET "
                b"BT /F1 14 Tf 20 168 Td (2. before emphasis) Tj ET "
                b"1 0 0 rg BT /F1 14 Tf 140 154 Td (emphasized row) Tj ET "
                b"0 g BT /F1 14 Tf 20 140 Td (after emphasis) Tj ET "
                b"BT /F1 14 Tf 20 112 Td (3. third heading) Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider(
                replacement_text="A deliberately longer translated replacement sentence."
            )
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(5, result.replaced_native_text_items)
            self.assertEqual([
                "1. first heading\nfirst continuation",
                "2. before emphasis",
                "emphasized row",
                "after emphasis",
                "3. third heading",
            ], [request.text for request in provider.requests if not request.is_filename])

    # Verifies FR-2026-08-29-05.
    def test_basic_layout_pdf_keeps_non_sequential_numeric_prose_eligible_for_grouping(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"BT /F1 12 Tf 14 TL 10 70 Td (2. first line) Tj T* (4. second line) Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(1, result.replaced_native_text_items)
            self.assertEqual(["2. first line\n4. second line"], [
                request.text for request in provider.requests if not request.is_filename
            ])

    # Verifies FR-2026-08-29-03.
    def test_basic_layout_pdf_keeps_borderless_repeated_column_gutters_separate(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"BT /F1 12 Tf 14 TL 10 70 Td (left) Tj 40 0 Td (right) Tj "
                b"1 0 0 1 10 56 Tm (lower) Tj 40 0 Td (value) Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(4, result.replaced_native_text_items)
            self.assertEqual(["left", "right", "lower", "value"], [
                request.text for request in provider.requests if not request.is_filename
            ])

    # Verifies FR-2026-08-29-03.
    def test_basic_layout_pdf_keeps_chunks_separated_by_a_vector_rule(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(100, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"0 0 0 RG 17 60 m 17 80 l S BT /F1 12 Tf 10 70 Td (a) Tj 8 0 Td (b) Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(2, result.replaced_native_text_items)
            self.assertEqual(["a", "b"], [
                request.text for request in provider.requests if not request.is_filename
            ])

    # Verifies FR-2026-08-29-03.
    def test_basic_layout_pdf_ignores_a_decorative_rule_outside_prose_bounds(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 100)
            contents = DecodedStreamObject()
            contents.set_data(
                b"0 0 0 RG 150 60 m 190 60 l S BT /F1 12 Tf 14 TL 10 70 Td "
                b"(first line) Tj T* (second line) Tj ET"
            )
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(1, result.replaced_native_text_items)
            self.assertEqual(["first line\nsecond line"], [
                request.text for request in provider.requests if not request.is_filename
            ])

    # Verifies FR-2026-08-23-01.
    def test_basic_layout_pdf_keeps_distant_same_line_labels_as_independent_regions(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 100)
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 12 Tf 10 70 Td (left) Tj 100 0 Td (right) Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider(replacement_text="replacement")
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(2, result.replaced_native_text_items)
            requests = [request.text for request in provider.requests if not request.is_filename]
            self.assertEqual(["left", "right"], requests)

    # Verifies FR-2026-08-23-01.
    def test_basic_layout_pdf_retains_clipping_text_and_skips_the_provider(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 100)
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 12 Tf 7 Tr 10 70 Td (clip only) Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output: writer.write(output)

            provider = _RecordingReplacementProvider()
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(0, result.replaced_native_text_items)
            self.assertFalse([request for request in provider.requests if not request.is_filename])
            self.assertIn(b"clip only", (output_root / "document.pdf").read_bytes())
            self.assertFalse((output_root / "document.pdf.diagnostics.json").exists())

            debug_output_root = root / "debug-output"
            debug_provider = _RecordingReplacementProvider()
            debug_result = self._run(
                input_root,
                debug_output_root,
                _EmptyOcrProvider(),
                debug_provider,
                document_text_layout="preserve-basic-layout",
                diagnostics_enabled=True,
            )

            self.assertEqual(0, debug_result.replaced_native_text_items)
            self.assertFalse([request for request in debug_provider.requests if not request.is_filename])
            sidecar = json.loads(
                (debug_output_root / "document.pdf.diagnostics.json").read_text(encoding="utf-8")
            )
            entry = sidecar["entries"][0]
            self.assertEqual("retained", entry["kind"])
            self.assertEqual("pdf_text_rendering_mode_ineligible", entry["reason_code"])
            self.assertEqual("clip only", entry["source_text"])
            self.assertEqual(1, entry["page"])
            self.assertEqual("Tj", entry["operator"])

    # Verifies FR-2026-08-23-01.
    def test_basic_layout_pdf_preserves_a_right_angle_text_orientation(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 100)
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 12 Tf 0 1 -1 0 100 10 Tm (vertical) Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output: writer.write(output)

            self._run(
                input_root, output_root, _EmptyOcrProvider(), _RecordingReplacementProvider(),
                document_text_layout="preserve-basic-layout",
            )

            output_reader = PdfReader(output_root / "document.pdf")
            stream = ContentStream(output_reader.pages[0].get_contents(), output_reader)
            self.assertTrue(any(
                operator == b"Tm" and [float(value) for value in operands[:4]] == [0.0, 1.0, -1.0, 0.0]
                for operands, operator in stream.operations
            ))

    # Verifies FR-2026-08-23-01.
    def test_basic_layout_pdf_replaces_text_inside_a_reusable_form_xobject(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(200, 100)
            form = DecodedStreamObject()
            form.set_data(b"BT /F1 12 Tf 10 10 Td (form text) Tj ET")
            form.update({
                NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
                NameObject("/BBox"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(100), NumberObject(30)]),
            })
            form_reference = writer._add_object(form)
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/XObject"): DictionaryObject({NameObject("/Form1"): form_reference})
            })
            contents = DecodedStreamObject(); contents.set_data(b"q /Form1 Do Q")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            provider = _RecordingReplacementProvider(replacement_text="fitted replacement")
            result = self._run(
                input_root, output_root, _EmptyOcrProvider(), provider,
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(1, result.replaced_native_text_items)
            output_reader = PdfReader(output_root / "document.pdf")
            xobjects = cast(DictionaryObject, cast(DictionaryObject, output_reader.pages[0]["/Resources"])["/XObject"])
            updated_form = cast(DecodedStreamObject, xobjects["/Form1"].get_object())
            stream = ContentStream(updated_form, output_reader)
            self.assertTrue(any(
                operator == b"Tf" and operands[0] == "/PipelineNoto"
                for operands, operator in stream.operations
            ))

    # Verifies FR-2026-08-03-03.
    def test_replaces_type0_pdf_text_with_a_tounicode_map(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(100, 100)
            to_unicode = DecodedStreamObject()
            to_unicode.set_data(
                b"1 beginbfchar\n<0001> <0041>\nendbfchar\n"
            )
            font = writer._add_object(DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type0"),
                NameObject("/BaseFont"): NameObject("/SyntheticIdentity"),
                NameObject("/Encoding"): NameObject("/Identity-H"),
                NameObject("/ToUnicode"): writer._add_object(to_unicode),
            }))
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
            })
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 12 Tf 10 10 Td <0001> Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            result = self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(),
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(1, result.replaced_native_text_items)
            basic_reader = PdfReader(output_root / "document.pdf")
            basic_stream = ContentStream(basic_reader.pages[0].get_contents(), basic_reader)
            self.assertTrue(any(
                operator == b"Tf" and operands[0] == "/PipelineNoto"
                for operands, operator in basic_stream.operations
            ))

            identity_basic_output = root / "identity-basic-output"
            self._run(
                input_root,
                identity_basic_output,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(replacement_text="A"),
                document_text_layout="preserve-basic-layout",
            )
            identity_reader = PdfReader(identity_basic_output / "document.pdf")
            identity_stream = ContentStream(identity_reader.pages[0].get_contents(), identity_reader)
            self.assertFalse(any(
                operator == b"Tf" and operands[0] == "/PipelineFallback"
                for operands, operator in identity_stream.operations
            ))
            self.assertIn(b"<0001>", (identity_basic_output / "document.pdf").read_bytes())

            source_font_output = root / "source-font-output"
            self._run(
                input_root,
                source_font_output,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(replacement_text="A"),
                document_text_layout="preserve-basic-layout-source-font",
            )
            source_font_reader = PdfReader(source_font_output / "document.pdf")
            source_font_stream = ContentStream(source_font_reader.pages[0].get_contents(), source_font_reader)
            self.assertFalse(any(
                operator == b"Tf" and operands[0] == "/PipelineFallback"
                for operands, operator in source_font_stream.operations
            ))
            self.assertIn(b"<0001>", (source_font_output / "document.pdf").read_bytes())

            fallback_output = root / "source-font-fallback-output"
            self._run(
                input_root,
                fallback_output,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(),
                document_text_layout="preserve-basic-layout-source-font",
            )
            fallback_reader = PdfReader(fallback_output / "document.pdf")
            fallback_stream = ContentStream(fallback_reader.pages[0].get_contents(), fallback_reader)
            self.assertTrue(any(
                operator == b"Tf" and operands[0] == "/PipelineNoto"
                for operands, operator in fallback_stream.operations
            ))
            fallback_fonts = cast(
                DictionaryObject, cast(DictionaryObject, fallback_reader.pages[0]["/Resources"])["/Font"]
            )
            fallback_font = cast(DictionaryObject, fallback_fonts["/PipelineNoto"].get_object())
            fallback_mapping = cast(
                DecodedStreamObject, fallback_font["/ToUnicode"].get_object()
            ).get_data()
            self.assertIn(b"<0001> <0023>", fallback_mapping)

    # Verifies FR-2026-08-23-04.
    def test_type0_pdf_widths_use_w_overrides_and_dw_fallback(self) -> None:
        to_unicode = DecodedStreamObject()
        to_unicode.set_data(
            b"4 beginbfchar\n<0001> <0041>\n<0002> <0042>\n<0003> <0043>\n<0004> <003F>\nendbfchar\n"
        )
        descendant = DictionaryObject({
            NameObject("/DW"): NumberObject(1000),
            NameObject("/W"): ArrayObject([
                NumberObject(1), ArrayObject([NumberObject(250), NumberObject(750)]),
                NumberObject(3), NumberObject(3), NumberObject(500),
            ]),
        })
        font = DictionaryObject({
            NameObject("/Subtype"): NameObject("/Type0"),
            NameObject("/Encoding"): NameObject("/Identity-H"),
            NameObject("/ToUnicode"): to_unicode,
            NameObject("/DescendantFonts"): ArrayObject([descendant]),
        })
        value = ByteStringObject(b"\x00\x01\x00\x02\x00\x03\x00\x04")
        self.assertEqual("ABC", _pdf_decode_composite_bytes(value[:6], font))
        advance = _pdf_text_advance(
            value,
            "ABC?",
            (NameObject("/F1"), NumberObject(10)),
            {"/F1": font},
            10.0,
            0.0,
            0.0,
            1.0,
        )
        self.assertEqual(25.0, advance)

    # Verifies FR-2026-08-23-04.
    def test_type0_pdf_widths_support_one_byte_codes_and_explicit_nonidentity_cids(self) -> None:
        to_unicode = DecodedStreamObject()
        to_unicode.set_data(b"2 beginbfchar\n<01> <0041>\n<02> <0042>\nendbfchar\n")
        encoding = DecodedStreamObject()
        encoding.set_data(b"2 begincidchar\n<01> 7\n<02> 9\nendcidchar\n")
        descendant = DictionaryObject({
            NameObject("/DW"): NumberObject(1000),
            NameObject("/W"): ArrayObject([
                NumberObject(7), ArrayObject([NumberObject(300)]),
                NumberObject(9), NumberObject(9), NumberObject(700),
            ]),
        })
        font = DictionaryObject({
            NameObject("/Subtype"): NameObject("/Type0"),
            NameObject("/Encoding"): encoding,
            NameObject("/ToUnicode"): to_unicode,
            NameObject("/DescendantFonts"): ArrayObject([descendant]),
        })
        value = ByteStringObject(b"\x01\x02")
        self.assertEqual("AB", _pdf_decode_composite_bytes(value, font))
        self.assertEqual(
            10.0,
            _pdf_text_advance(
                value,
                "AB",
                (NameObject("/F1"), NumberObject(10)),
                {"/F1": font},
                10.0,
                0.0,
                0.0,
                1.0,
            ),
        )

    # Verifies FR-2026-08-23-04.
    def test_type0_pdf_widths_fall_back_to_dw_when_cid_mapping_is_incomplete(self) -> None:
        to_unicode = DecodedStreamObject()
        to_unicode.set_data(b"2 beginbfchar\n<01> <0041>\n<02> <0042>\nendbfchar\n")
        encoding = DecodedStreamObject()
        encoding.set_data(b"1 begincidchar\n<01> 7\nendcidchar\n")
        descendant = DictionaryObject({
            NameObject("/DW"): NumberObject(1000),
            NameObject("/W"): ArrayObject([NumberObject(7), ArrayObject([NumberObject(300)])]),
        })
        font = DictionaryObject({
            NameObject("/Subtype"): NameObject("/Type0"),
            NameObject("/Encoding"): encoding,
            NameObject("/ToUnicode"): to_unicode,
            NameObject("/DescendantFonts"): ArrayObject([descendant]),
        })
        self.assertEqual(
            20.0,
            _pdf_text_advance(
                ByteStringObject(b"\x01\x02"),
                "AB",
                (NameObject("/F1"), NumberObject(10)),
                {"/F1": font},
                10.0,
                0.0,
                0.0,
                1.0,
            ),
        )

    # Verifies FR-2026-08-23-04.
    def test_basic_layout_pdf_type0_widths_control_the_fitted_replacement_size(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; input_root.mkdir()
            narrow_source = input_root / "narrow.pdf"
            wide_source = input_root / "wide.pdf"

            def write_source(path: Path, widths: ArrayObject | None) -> None:
                writer = PdfWriter(); page = writer.add_blank_page(100, 100)
                to_unicode = DecodedStreamObject()
                to_unicode.set_data(b"2 beginbfchar\n<0001> <0041>\n<0002> <0042>\nendbfchar\n")
                descendant = DictionaryObject({NameObject("/DW"): NumberObject(1000)})
                if widths is not None:
                    descendant[NameObject("/W")] = widths
                font = writer._add_object(DictionaryObject({
                    NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type0"),
                    NameObject("/BaseFont"): NameObject("/SyntheticIdentity"), NameObject("/Encoding"): NameObject("/Identity-H"),
                    NameObject("/ToUnicode"): writer._add_object(to_unicode),
                    NameObject("/DescendantFonts"): ArrayObject([writer._add_object(descendant)]),
                }))
                page[NameObject("/Resources")] = DictionaryObject({
                    NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
                })
                contents = DecodedStreamObject()
                contents.set_data(
                    b"q 0 0 m 100 0 l 50 100 l h W n BT /F1 10 Tf 10 20 Td <00010002> Tj ET Q"
                )
                page.replace_contents(ContentStream(contents, writer))
                with path.open("wb") as output_file: writer.write(output_file)

            write_source(narrow_source, ArrayObject([NumberObject(1), ArrayObject([NumberObject(250), NumberObject(750)])]))
            write_source(wide_source, None)

            output_root = root / "output"
            result = self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(replacement_text="########"),
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(2, result.replaced_native_text_items)

            def fitted_size(path: Path) -> float:
                output = PdfReader(path)
                stream = ContentStream(output.pages[0].get_contents(), output)
                return next(
                    float(operands[1]) for operands, operator in stream.operations
                    if operator == b"Tf" and operands[0] == "/PipelineNoto"
                )

            self.assertLess(fitted_size(output_root / "narrow.pdf"), fitted_size(output_root / "wide.pdf"))

    # Verifies FR-2026-08-03-03.
    def test_replaces_one_byte_type0_tj_fragments(self) -> None:
        """Use ToUnicode code widths, rather than the declared Identity encoding."""
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(100, 100)
            to_unicode = DecodedStreamObject()
            to_unicode.set_data(b"1 beginbfchar\n<01> <0041>\nendbfchar\n")
            font = writer._add_object(DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type0"),
                NameObject("/BaseFont"): NameObject("/SyntheticIdentity"),
                NameObject("/Encoding"): NameObject("/Identity-H"),
                NameObject("/ToUnicode"): writer._add_object(to_unicode),
            }))
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
            })
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 12 Tf 10 10 Td [<01> 20 <01>] TJ ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output: writer.write(output)

            result = self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(),
                document_text_layout="preserve-basic-layout-source-font",
            )

            self.assertEqual(1, result.replaced_native_text_items)
            output_reader = PdfReader(output_root / "document.pdf")
            stream = ContentStream(output_reader.pages[0].get_contents(), output_reader)
            self.assertTrue(any(
                operator == b"Tf" and operands[0] == "/PipelineNoto"
                for operands, operator in stream.operations
            ))
            fonts = cast(DictionaryObject, cast(DictionaryObject, output_reader.pages[0]["/Resources"])["/Font"])
            type_zero = cast(DictionaryObject, fonts["/PipelineNoto"].get_object())
            mapping = cast(DecodedStreamObject, type_zero["/ToUnicode"].get_object()).get_data()
            self.assertIn(b"<0001> <0023>", mapping)

    # Verifies FR-2026-08-03-03.
    def test_source_font_pdf_falls_back_when_tounicode_lacks_replacement_glyph(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(100, 100)
            to_unicode = DecodedStreamObject()
            to_unicode.set_data(b"1 beginbfchar\n<41> <0041>\nendbfchar\n")
            font = writer._add_object(DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/TrueType"),
                NameObject("/BaseFont"): NameObject("/SyntheticSubset"),
                NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
                NameObject("/ToUnicode"): writer._add_object(to_unicode),
            }))
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
            })
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 12 Tf 10 10 Td (A) Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as output_file: writer.write(output_file)

            self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(),
                document_text_layout="preserve-basic-layout-source-font",
            )

            output_reader = PdfReader(output_root / "document.pdf")
            stream = ContentStream(output_reader.pages[0].get_contents(), output_reader)
            self.assertTrue(any(
                operator == b"Tf" and operands[0] == "/PipelineNoto"
                for operands, operator in stream.operations
            ))
            fonts = cast(DictionaryObject, cast(DictionaryObject, output_reader.pages[0]["/Resources"])["/Font"])
            type_zero = cast(DictionaryObject, fonts["/PipelineNoto"].get_object())
            mapping = cast(DecodedStreamObject, type_zero["/ToUnicode"].get_object()).get_data()
            self.assertIn(b"<0001> <0023>", mapping)

    # Verifies FR-2026-08-03-04, FR-2026-08-27-11, and FR-2026-08-29-01.
    def test_reports_pdf_native_and_vector_review_progress_for_each_page(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter()
            writer.add_blank_page(100, 100)
            writer.add_blank_page(100, 100)
            with source.open("wb") as output_file:
                writer.write(output_file)
            progress_bars: list[_RecordedProgress] = []

            def make_progress(total: int, label: str) -> ProgressReporter:
                progress = _RecordedProgress(total, label)
                progress_bars.append(progress)
                return progress

            result = self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(),
                show_progress=True,
                progress_factory=make_progress,
            )

            self.assertEqual(1, result.processed_files)
            self.assertEqual(1, len(progress_bars))
            self.assertEqual(5, progress_bars[0].total)
            self.assertEqual(
                [
                    "native text page 1/2",
                    "native text page 2/2",
                    "native form fields",
                    "vector OCR page 1/2",
                    "vector OCR page 2/2",
                ],
                progress_bars[0].postfixes,
            )
            self.assertEqual(5, progress_bars[0].updates)



if __name__ == "__main__":
    unittest.main()
