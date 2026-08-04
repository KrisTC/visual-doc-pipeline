#!/usr/bin/env python3
"""Synthetic regression tests for the folder replacement command."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import cast
import unittest
import xml.etree.ElementTree as ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, Protection
from openpyxl.worksheet.table import Table
from pptx import Presentation
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.oxml import parse_xml
from pptx.util import Inches, Pt
# pypdf does not publish PEP 561 metadata for its generic object model.
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ContentStream, DecodedStreamObject, DictionaryObject, NameObject, NumberObject, TextStringObject
# skia-python does not publish PEP 561 stubs; this is the native rendering boundary.
import skia  # type: ignore[import-not-found]

from pipeline.folder_replacement import FolderReplacementResult, replace_input_folder
from pipeline.folder_replacement.processor import ProgressFactory, ProgressReporter
from pipeline.folder_replacement.xlsx import _replace_drawing
from pipeline.bounded_text_layout import noto_typefaces
from pipeline.ocr import BoundingPolygon, OcrRequest, OcrResult, OcrText, PixelPoint
from pipeline.ocr.provider import LocalContractTestSkip
from pipeline.text_replacement import TextReplacementRequest, TextReplacementResult


FONT_PATH = Path(__file__).parent / "assets" / "fonts" / "NotoSansJP[wght].ttf"


class _EmptyOcrProvider:
    supported_languages = frozenset({"en"})
    supports_local_contract_test = False
    skipped_local_contract_angles: frozenset[int] = frozenset()
    skipped_local_contract_cases: frozenset[LocalContractTestSkip] = frozenset()

    def recognize(self, request: OcrRequest) -> OcrResult:
        return OcrResult(())


class _CountingOcrProvider(_EmptyOcrProvider):
    def __init__(self) -> None:
        self.calls = 0

    def recognize(self, request: OcrRequest) -> OcrResult:
        self.calls += 1
        return OcrResult(())


class _LowConfidenceOcrProvider(_EmptyOcrProvider):
    def recognize(self, request: OcrRequest) -> OcrResult:
        return OcrResult(
            (
                OcrText(
                    "skip me",
                    0.64,
                    BoundingPolygon(
                        (
                            PixelPoint(1, 1),
                            PixelPoint(20, 1),
                            PixelPoint(20, 10),
                            PixelPoint(1, 10),
                        )
                    ),
                ),
            )
        )


class _RecordingReplacementProvider:
    def __init__(self, filename: str | None = None, replacement_text: str | None = None) -> None:
        self.filename = filename
        self.replacement_text = replacement_text
        self.requests: list[TextReplacementRequest] = []

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        self.requests.append(request)
        if request.is_filename and self.filename is not None:
            return TextReplacementResult(self.filename, 1.0)
        if request.is_filename:
            return TextReplacementResult(request.text, 1.0)
        return TextReplacementResult(self.replacement_text or "#" * len(request.text), 1.0)


class _RecordedProgress:
    def __init__(self, total: int, label: str) -> None:
        self.total = total
        self.label = label
        self.postfixes: list[str] = []
        self.updates = 0
        self.closed = False

    def set_postfix_str(self, text: str) -> None:
        self.postfixes.append(text)

    def update(self, count: float | None = None) -> bool | None:
        self.updates += 1 if count is None else int(count)
        return None

    def close(self) -> None:
        self.closed = True


class FolderReplacementTests(unittest.TestCase):
    # Verifies FR-2026-08-04-07.
    def test_xlsx_drawing_layout_writes_schema_ordered_run_properties(self) -> None:
        drawing = b'''<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><xdr:sp><xdr:spPr><a:xfrm><a:ext cx="914400" cy="457200"/></a:xfrm></xdr:spPr><xdr:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr sz="2400"><a:latin typeface="Source Sans"/></a:rPr><a:t>Original</a:t></a:r><a:endParaRPr/></a:p></xdr:txBody></xdr:sp></xdr:wsDr>'''
        updated, count = _replace_drawing(
            drawing, _RecordingReplacementProvider(replacement_text="A longer replacement"), "en", "en",
            noto_typefaces(),
            True,
        )
        self.assertEqual(1, count)
        root = ElementTree.fromstring(updated)
        paragraph = next(item for item in root.iter() if item.tag.endswith("}p"))
        children = list(paragraph)
        self.assertLess(next(index for index, item in enumerate(children) if item.tag.endswith("}r")), next(index for index, item in enumerate(children) if item.tag.endswith("}endParaRPr")))
        run_properties = next(item for item in root.iter() if item.tag.endswith("}rPr"))
        self.assertNotIn("typeface", run_properties.attrib)
        self.assertTrue(any(item.tag.endswith("}latin") for item in run_properties))

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

    # Verifies FR-2026-08-03-14, FR-2026-08-03-15, and FR-2026-08-03-16.
    def test_pptx_basic_layout_replaces_and_explicitly_fits_text_frames(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            source = input_root / "deck.pptx"
            presentation = Presentation()
            slide = presentation.slides.add_slide(presentation.slide_layouts[1])
            slide.shapes.title.text = "Placeholder text"
            text_box = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(2), Inches(0.5))
            text_frame = text_box.text_frame
            text_frame.paragraphs[0].text = "Short text"
            text_frame.paragraphs[0].runs[0].font.size = Pt(36)
            paragraph_properties = text_frame.paragraphs[0]._p.get_or_add_pPr()
            default_run_properties = paragraph_properties.get_or_add_defRPr()
            paragraph_properties.remove(default_run_properties)
            paragraph_properties.append(
                parse_xml(
                    '<a:buAutoNum xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                    'type="arabicPeriod"/>'
                )
            )
            paragraph_properties.append(default_run_properties)
            text_frame.paragraphs[0].line_spacing = Pt(14)
            text_frame.add_paragraph()
            group = slide.shapes.add_group_shape()
            group.shapes.add_textbox(Inches(1), Inches(1), Inches(2), Inches(0.5)).text = "Grouped text"
            table_frame = slide.shapes.add_table(2, 3, Inches(1), Inches(3), Inches(4), Inches(1))
            table = table_frame.table
            table.cell(0, 0).text = "Table text"
            table.cell(0, 1).text = "Fallback text"
            fallback_run = table.cell(0, 1).text_frame.paragraphs[0].runs[0]
            fallback_run.font.name = "Source Fallback Font"
            fallback_run.font.size = Pt(31)
            table.cell(1, 0).text = "Merged table text"
            table.cell(1, 0).merge(table.cell(1, 1))
            table.columns[1].width = 0
            expected_table_widths = tuple(int(column.width) for column in table.columns)
            expected_table_heights = tuple(int(row.height) for row in table.rows)
            presentation.save(str(source))

            result = self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(replacement_text="Long replacement text " * 500),
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(1, result.processed_files)
            self.assertEqual(6, result.replaced_native_text_items)
            output = output_root / "deck.pptx"
            output_presentation = Presentation(str(output))
            preserved_blank_paragraph_shape = next(
                shape
                for shape in output_presentation.slides[0].shapes
                if shape.has_text_frame and len(shape.text_frame.paragraphs) == 2
            )
            self.assertEqual("", preserved_blank_paragraph_shape.text_frame.paragraphs[1].text)
            output_table = next(
                shape.table for shape in output_presentation.slides[0].shapes if shape.has_table
            )
            self.assertEqual(
                expected_table_widths,
                tuple(int(column.width) for column in output_table.columns),
            )
            self.assertEqual(
                expected_table_heights,
                tuple(int(row.height) for row in output_table.rows),
            )
            self.assertIn("Long replacement text", output_table.cell(0, 0).text)
            self.assertIn("Long replacement text", output_table.cell(0, 1).text)
            self.assertTrue(output_table.cell(1, 0).is_merge_origin)
            self.assertIn("Long replacement text", output_table.cell(1, 0).text)
            fallback_output_run = output_table.cell(0, 1).text_frame.paragraphs[0].runs[0]
            self.assertEqual("Source Fallback Font", fallback_output_run.font.name)
            self.assertEqual(31.0, fallback_output_run.font.size.pt)
            with ZipFile(output) as archive:
                slide_xml = archive.read("ppt/slides/slide1.xml")
                package_parts = archive.namelist()
            self.assertIn(b"noAutofit", slide_xml)
            self.assertIn(b"Noto Sans JP", slide_xml)
            self.assertNotIn(b"Placeholder text", slide_xml)
            self.assertNotIn(b"Short text", slide_xml)
            self.assertNotIn(b"Grouped text", slide_xml)
            self.assertFalse(any(part.startswith("ppt/fonts/") for part in package_parts))
            self.assertTrue(
                any(int(size) < 3600 for size in re.findall(rb' sz="(\d+)"', slide_xml))
            )
            self.assertIn(b'sz="100"', slide_xml)
            self._assert_valid_drawingml_font_sizes(slide_xml)
            self._assert_drawingml_paragraph_property_order(slide_xml)

    # Verifies FR-2026-08-04-05.
    def test_pptx_no_autofit_uses_source_width_and_natural_height(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            source = input_root / "deck.pptx"
            presentation = Presentation()
            slide = presentation.slides.add_slide(presentation.slide_layouts[6])
            no_autofit = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(0.2))
            no_autofit.name = "no-autofit"
            no_autofit.text = "Source text " * 40
            no_autofit.text_frame.paragraphs[0].runs[0].font.size = Pt(24)
            no_autofit.text_frame.auto_size = MSO_AUTO_SIZE.NONE
            no_autofit_dimensions = (int(no_autofit.width), int(no_autofit.height))
            text_to_fit_shape = slide.shapes.add_textbox(
                Inches(1), Inches(2), Inches(6), Inches(0.2)
            )
            text_to_fit_shape.name = "text-to-fit-shape"
            text_to_fit_shape.text = "Source text " * 40
            text_to_fit_shape.text_frame.paragraphs[0].runs[0].font.size = Pt(24)
            text_to_fit_shape.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
            table = slide.shapes.add_table(1, 1, Inches(1), Inches(3), Inches(6), Inches(0.2)).table
            table.cell(0, 0).text = "Source text " * 40
            table.cell(0, 0).text_frame.paragraphs[0].runs[0].font.size = Pt(24)
            presentation.save(str(source))

            self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(replacement_text="Replacement text " * 25),
                document_text_layout="preserve-basic-layout",
            )

            output_presentation = Presentation(str(output_root / "deck.pptx"))
            output_slide = output_presentation.slides[0]
            output_no_autofit = next(
                shape for shape in output_slide.shapes if shape.name == "no-autofit"
            )
            output_text_to_fit_shape = next(
                shape for shape in output_slide.shapes if shape.name == "text-to-fit-shape"
            )
            output_table = next(shape.table for shape in output_slide.shapes if shape.has_table)
            no_autofit_size = output_no_autofit.text_frame.paragraphs[0].runs[0].font.size.pt
            text_to_fit_shape_size = (
                output_text_to_fit_shape.text_frame.paragraphs[0].runs[0].font.size.pt
            )
            table_size = output_table.cell(0, 0).text_frame.paragraphs[0].runs[0].font.size.pt
            self.assertEqual(no_autofit_dimensions, (int(output_no_autofit.width), int(output_no_autofit.height)))
            self.assertGreater(no_autofit_size, text_to_fit_shape_size)
            self.assertGreater(no_autofit_size, table_size)

    # Verifies FR-2026-08-04-06.
    def test_pptx_basic_layout_source_font_preserves_resolved_typeface_references(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            source = input_root / "deck.pptx"
            presentation = Presentation()
            slide = presentation.slides.add_slide(presentation.slide_layouts[6])
            named_source = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1))
            named_source.name = "named-source"
            named_source.text = "Named source font"
            named_run = named_source.text_frame.paragraphs[0].runs[0]
            named_run.font.name = "Source Presentation Font"
            named_run.font.size = Pt(24)
            unnamed_source = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(3), Inches(1))
            unnamed_source.name = "unnamed-source"
            unnamed_source.text = "Fallback font"
            unnamed_source.text_frame.paragraphs[0].runs[0].font.size = Pt(24)
            presentation.save(str(source))

            self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(replacement_text="Replacement text " * 20),
                document_text_layout="preserve-basic-layout-source-font",
            )

            output_presentation = Presentation(str(output_root / "deck.pptx"))
            output_shapes = output_presentation.slides[0].shapes
            output_named = next(shape for shape in output_shapes if shape.name == "named-source")
            output_unnamed = next(shape for shape in output_shapes if shape.name == "unnamed-source")
            self.assertEqual(
                "Source Presentation Font",
                output_named.text_frame.paragraphs[0].runs[0].font.name,
            )
            self.assertEqual(
                "Noto Sans JP",
                output_unnamed.text_frame.paragraphs[0].runs[0].font.name,
            )
            self.assertEqual(MSO_AUTO_SIZE.NONE, output_named.text_frame.auto_size)

    # Verifies FR-2026-08-03-14.
    def test_xlsx_basic_layout_fits_only_explicitly_bounded_cells(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            source = input_root / "workbook.xlsx"
            workbook = Workbook()
            worksheet = workbook.active
            self.assertIsNotNone(worksheet)
            assert worksheet is not None
            worksheet.column_dimensions["A"].width = 12
            worksheet.column_dimensions["B"].width = 12
            worksheet.row_dimensions[1].height = 30
            worksheet.row_dimensions[2].height = 30
            worksheet["A1"] = "Bounded source"
            worksheet["A1"].font = Font(name="Source Sans", sz=24, bold=True)
            worksheet["A1"].alignment = Alignment(horizontal="center", wrap_text=False)
            worksheet["A1"].protection = Protection(locked=False)
            worksheet.merge_cells("A2:B2")
            worksheet["A2"] = "Merged source"
            worksheet["C1"] = "Unbounded source"
            workbook.save(source)

            result = self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(replacement_text="Long replacement text " * 30),
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(1, result.processed_files)
            self.assertEqual(3, result.replaced_native_text_items)
            output = load_workbook(output_root / "workbook.xlsx")
            output_sheet = output.active
            self.assertIsNotNone(output_sheet)
            assert output_sheet is not None
            self.assertIn("Long replacement text", output_sheet["A1"].value)
            # FR-2026-08-04-07: XLSX has no portable embedded-font path, so the
            # bounded cell keeps its source face while using the shared fitted size.
            self.assertEqual("Source Sans", output_sheet["A1"].font.name)
            self.assertLess(output_sheet["A1"].font.sz, 24)
            self.assertTrue(output_sheet["A1"].alignment.wrap_text)
            self.assertFalse(output_sheet["A1"].alignment.shrink_to_fit)
            with ZipFile(output_root / "workbook.xlsx") as archive:
                styles = ElementTree.fromstring(archive.read("xl/styles.xml"))
            namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
            cell_xfs = styles.find(namespace + "cellXfs")
            assert cell_xfs is not None
            self.assertFalse(any(
                [child.tag for child in xf].index(namespace + "protection")
                < [child.tag for child in xf].index(namespace + "alignment")
                for xf in cell_xfs
                if namespace + "protection" in [child.tag for child in xf]
                and namespace + "alignment" in [child.tag for child in xf]
            ))
            self.assertIn("Long replacement text", output_sheet["A2"].value)
            self.assertEqual("Calibri", output_sheet["A2"].font.name)
            self.assertIn("Long replacement text", output_sheet["C1"].value)
            self.assertEqual("Calibri", output_sheet["C1"].font.name)

    # Verifies FR-2026-08-03-14.
    def test_xlsx_basic_layout_retains_structured_table_headers(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            source = input_root / "workbook.xlsx"
            workbook = Workbook()
            worksheet = workbook.active
            self.assertIsNotNone(worksheet)
            assert worksheet is not None
            worksheet.column_dimensions["A"].width = 16
            worksheet.column_dimensions["B"].width = 16
            worksheet.row_dimensions[1].height = 24
            worksheet.row_dimensions[2].height = 24
            worksheet.append(["Synthetic Header One", "Synthetic Header Two"])
            worksheet.append(["First body value", "Second body value"])
            worksheet.add_table(Table(displayName="SyntheticTable", ref="A1:B2"))
            workbook.save(source)

            result = self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _RecordingReplacementProvider(replacement_text="Replacement body value"),
                document_text_layout="preserve-basic-layout",
            )

            self.assertEqual(2, result.replaced_native_text_items)
            output = load_workbook(output_root / "workbook.xlsx")
            output_sheet = output.active
            self.assertIsNotNone(output_sheet)
            assert output_sheet is not None
            self.assertEqual("Synthetic Header One", output_sheet["A1"].value)
            self.assertEqual("Synthetic Header Two", output_sheet["B1"].value)
            self.assertEqual("Replacement body value", output_sheet["A2"].value)
            self.assertEqual("Replacement body value", output_sheet["B2"].value)
            with ZipFile(source) as source_archive, ZipFile(output_root / "workbook.xlsx") as output_archive:
                self.assertEqual(
                    source_archive.read("xl/tables/table1.xml"),
                    output_archive.read("xl/tables/table1.xml"),
                )

    # Verifies FR-2026-08-04-07.
    def test_docx_basic_layout_fits_drawing_text_but_not_flowing_text(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            source = input_root / "document.docx"
            with ZipFile(source, "w", ZIP_DEFLATED) as archive:
                archive.writestr(
                    "word/document.xml",
                    """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
                    xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">
                    <w:body><w:p><w:r><w:t>Flow text</w:t></w:r></w:p><w:p><w:r><w:drawing><wp:inline>
                    <wp:extent cx="914400" cy="457200"/><w:txbxContent><w:p><w:r><w:rPr><w:sz w:val="48"/></w:rPr><w:t>Box text</w:t></w:r></w:p></w:txbxContent>
                    </wp:inline></w:drawing></w:r></w:p></w:body></w:document>""",
                )
            self._run(
                input_root, output_root, _EmptyOcrProvider(),
                _RecordingReplacementProvider(replacement_text="Long replacement text " * 20),
                document_text_layout="preserve-basic-layout",
            )
            with ZipFile(output_root / "document.docx") as archive:
                data = archive.read("word/document.xml")
            self.assertIn(b"Noto Sans JP", data)
            self.assertIn("word/fonts/pipeline-sans-serif-regular.odttf", archive.namelist())
            self.assertIn(b"Long replacement text", data)

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
            self.assertEqual(["embedded image 1", "native text"], progress_bars[0].postfixes)
            self.assertEqual(2, progress_bars[0].updates)
            self.assertTrue(progress_bars[0].closed)

    # Verifies FR-2026-08-03-05.
    def test_replaces_editable_svg_vector_text_without_ocr(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            with ZipFile(input_root / "document.docx", "w", ZIP_DEFLATED) as archive:
                archive.writestr(
                    "word/media/vector.svg",
                    b'<svg xmlns="http://www.w3.org/2000/svg"><text>Mask</text></svg>',
                )
            ocr_provider = _CountingOcrProvider()

            result = self._run(
                input_root, output_root, ocr_provider, _RecordingReplacementProvider()
            )

            self.assertEqual(1, result.processed_files)
            self.assertEqual(1, result.replaced_native_text_items)
            self.assertEqual(0, result.replaced_image_regions)
            self.assertEqual(0, result.retained_vector_graphics)
            self.assertEqual(0, ocr_provider.calls)
            with ZipFile(output_root / "document.docx") as archive:
                vector_data = archive.read("word/media/vector.svg")
            self.assertIn(b"####", vector_data)
            self.assertNotIn(b"Mask", vector_data)

    # Verifies FR-2026-08-03-05.
    def test_retains_noneditable_vector_and_reports_it(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            vector_data = b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>'
            with ZipFile(input_root / "document.docx", "w", ZIP_DEFLATED) as archive:
                archive.writestr("word/media/vector.svg", vector_data)

            standard_error = StringIO()
            with redirect_stderr(standard_error):
                result = self._run(
                    input_root, output_root, _EmptyOcrProvider(), _RecordingReplacementProvider()
                )

            self.assertEqual(1, result.processed_files)
            self.assertEqual(1, result.retained_vector_graphics)
            self.assertIn("Retained vector", standard_error.getvalue())
            with ZipFile(output_root / "document.docx") as archive:
                self.assertEqual(vector_data, archive.read("word/media/vector.svg"))

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
                result = self._run(input_root, output_root, _LowConfidenceOcrProvider(), provider)

            self.assertEqual(1, result.processed_files)
            self.assertEqual(1, result.failed_files)
            self.assertTrue((output_root / "good.png").is_file())
            self.assertFalse(any(not request.is_filename for request in provider.requests))
            self.assertIn("broken.png", failure_output.getvalue())

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

    # Verifies FR-2026-08-04-07.
    def test_basic_layout_pdf_content_uses_the_safe_replacement_font(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"; output_root = root / "output"; input_root.mkdir()
            source = input_root / "document.pdf"
            writer = PdfWriter(); page = writer.add_blank_page(100, 100)
            contents = DecodedStreamObject(); contents.set_data(b"BT /F1 12 Tf 10 10 Td (Hello) Tj ET")
            page.replace_contents(ContentStream(contents, writer))
            with source.open("wb") as source_file: writer.write(source_file)

            self._run(input_root, output_root, _EmptyOcrProvider(), _RecordingReplacementProvider(), document_text_layout="preserve-basic-layout")

            output = PdfReader(output_root / "document.pdf")
            stream = ContentStream(output.pages[0].get_contents(), output)
            self.assertTrue(any(operator == b"Tf" and operands[0] == "/PipelineFallback" for operands, operator in stream.operations))
            self.assertIn(b"<2323232323>", (output_root / "document.pdf").read_bytes())

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
            self.assertIn(b"<23>", (output_root / "document.pdf").read_bytes())

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
                operator == b"Tf" and operands[0] == "/PipelineFallback"
                for operands, operator in fallback_stream.operations
            ))
            self.assertIn(b"<23>", (fallback_output / "document.pdf").read_bytes())

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

            self.assertEqual(2, result.replaced_native_text_items)
            output_reader = PdfReader(output_root / "document.pdf")
            stream = ContentStream(output_reader.pages[0].get_contents(), output_reader)
            self.assertTrue(any(
                operator == b"Tf" and operands[0] == "/PipelineFallback"
                for operands, operator in stream.operations
            ))
            self.assertGreaterEqual((output_root / "document.pdf").read_bytes().count(b"<23>"), 2)

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
                operator == b"Tf" and operands[0] == "/PipelineFallback"
                for operands, operator in stream.operations
            ))
            self.assertIn(b"<23>", (output_root / "document.pdf").read_bytes())

    @staticmethod
    def _write_png(path: Path) -> None:
        Image.new("RGB", (30, 20), "white").save(path, "PNG")

    def _assert_drawingml_paragraph_property_order(self, data: bytes) -> None:
        """Verify the schema order that PowerPoint requires for ``a:pPr`` children."""
        namespace = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
        order = (
            "lnSpc",
            "spcBef",
            "spcAft",
            "buClrTx",
            "buClr",
            "buSzTx",
            "buSzPct",
            "buSzPts",
            "buFontTx",
            "buFont",
            "buNone",
            "buAutoNum",
            "buChar",
            "buBlip",
            "tabLst",
            "defRPr",
            "extLst",
        )
        ranks = {name: index for index, name in enumerate(order)}
        for properties in ElementTree.fromstring(data).iter(f"{namespace}pPr"):
            child_names = [child.tag.removeprefix(namespace) for child in properties]
            self.assertEqual(
                sorted(child_names, key=lambda name: ranks.get(name, len(ranks))),
                child_names,
            )

    def _assert_valid_drawingml_font_sizes(self, data: bytes) -> None:
        """Verify explicit run sizes stay within the OOXML DrawingML range."""
        namespace = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
        run_tags = {f"{namespace}rPr", f"{namespace}endParaRPr", f"{namespace}defRPr"}
        for properties in ElementTree.fromstring(data).iter():
            if properties.tag not in run_tags or "sz" not in properties.attrib:
                continue
            self.assertGreaterEqual(int(properties.attrib["sz"]), 100)
            self.assertLessEqual(int(properties.attrib["sz"]), 400_000)

    def _run(
        self,
        input_root: Path,
        output_root: Path,
        ocr_provider: _EmptyOcrProvider,
        replacement_provider: _RecordingReplacementProvider,
        *,
        show_progress: bool = False,
        progress_factory: ProgressFactory | None = None,
        document_text_layout: str = "preserve-source-formatting",
    ) -> FolderReplacementResult:
        typeface = skia.Typeface.MakeFromFile(str(FONT_PATH))
        if typeface is None:
            self.fail("Could not load test typeface.")
        return replace_input_folder(
            input_root,
            output_root,
            ocr_provider=ocr_provider,
            text_replacement_provider=replacement_provider,
            source_language="en",
            target_language="en",
            typeface=typeface,
            document_text_layout=document_text_layout,
            show_progress=show_progress,
            progress_factory=progress_factory,
        )


if __name__ == "__main__":
    unittest.main()
