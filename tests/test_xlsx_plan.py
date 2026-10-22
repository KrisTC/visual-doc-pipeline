#!/usr/bin/env python3
"""Plan and apply tests for the XLSX handler and the shared Office media stage."""

from __future__ import annotations

from io import BytesIO
from typing import cast
import unittest
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment
from openpyxl.drawing.image import Image as WorkbookImage
from openpyxl.worksheet.table import Table
from openpyxl.worksheet.worksheet import Worksheet
from PIL import Image
# skia-python does not publish PEP 561 stubs; this is the native rendering boundary.
import skia  # type: ignore[import-not-found]

from folder_replacement_test_support import FONT_PATH, _EmptyOcrProvider
from pipeline.folder_replacement.planning import PhaseProgress, child_unit_id, plan_and_apply
from pipeline.folder_replacement.xlsx import (
    apply_xlsx,
    plan_xlsx,
    replace_xlsx_bytes,
    xlsx_work_item_total,
)
from pipeline.ocr import BoundingPolygon, OcrRequest, OcrResult, OcrText, PixelPoint
from pipeline.text_replacement import (
    BatchLimits,
    TextReplacementItem,
    TextReplacementRequest,
    TextReplacementResult,
    TranslationEngine,
    replace_each,
)

LAYOUTS = (
    "preserve-source-formatting",
    "preserve-basic-layout",
    "preserve-basic-layout-source-font",
)
_DRAWING_TEXT_BOX = (
    '<twoCellAnchor xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
    "<from><col>1</col><colOff>0</colOff><row>20</row><rowOff>0</rowOff></from>"
    "<to><col>3</col><colOff>0</colOff><row>22</row><rowOff>0</rowOff></to>"
    '<sp><nvSpPr><cNvPr id="9" name="Box"/><cNvSpPr/></nvSpPr>'
    '<spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="914400" cy="457200"/></a:xfrm></spPr>'
    '<txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr sz="1400"/><a:t>Drawing box text</a:t></a:r></a:p>'
    "</txBody></sp><clientData/></twoCellAnchor>"
)
_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="40"><text x="5" y="20">Vector label</text></svg>'


class _BatchProvider:
    """Translate by suffixing, and record the texts of each request."""

    def __init__(self, limits: BatchLimits | None = None) -> None:
        self.batch_limits = limits
        self.requests: list[tuple[str, ...]] = []

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        self.requests.append(request.texts)
        return replace_each(request, lambda text: TextReplacementItem(f"{text} translated", 1.0))


class _RegionOcr(_EmptyOcrProvider):
    """Return one confident region for any image."""

    def __init__(self, text: str) -> None:
        self.text = text

    def recognize(self, request: OcrRequest) -> OcrResult:
        polygon = BoundingPolygon(
            (PixelPoint(5, 5), PixelPoint(95, 5), PixelPoint(95, 30), PixelPoint(5, 30))
        )
        return OcrResult((OcrText(self.text, 0.99, polygon),))


def _typeface() -> skia.Typeface:
    typeface = skia.Typeface.MakeFromFile(str(FONT_PATH))
    if typeface is None:
        raise AssertionError("Could not load test typeface.")
    return typeface


def _workbook_bytes(*, image: bool = False, svg: bool = False) -> bytes:
    workbook = Workbook()
    sheet = cast(Worksheet, workbook.active)
    sheet.title = "Main"
    sheet.column_dimensions["A"].width = 12
    sheet.row_dimensions[1].height = 30
    sheet["A1"] = "Bounded label"
    sheet["C1"] = "Loose label"
    sheet["C2"] = "123"
    sheet["C3"] = 42
    sheet["C4"] = '=A1&"x"'
    sheet["D1"] = "Noted"
    sheet["D1"].comment = Comment("Comment body", "author")
    sheet["A5"] = "Header one"
    sheet["B5"] = "Header two"
    sheet["A6"] = "Body one"
    sheet["B6"] = "Body two"
    sheet.add_table(Table(displayName="Tbl", ref="A5:B6"))
    chart = BarChart()
    chart.title = "Chart title"
    chart.add_data(Reference(sheet, min_col=1, min_row=6, max_row=6), titles_from_data=False)
    sheet.add_chart(chart, "F2")
    if image:
        picture = BytesIO()
        Image.new("RGB", (100, 40), "white").save(picture, "PNG")
        picture.seek(0)
        sheet.add_image(WorkbookImage(picture), "H8")
    large = workbook.create_sheet("Large")
    large["A1"] = "Large first"
    large["A1001"] = "Large last"
    output = BytesIO()
    workbook.save(output)
    return _with_drawing_text_box(output.getvalue(), svg)


def _with_drawing_text_box(data: bytes, svg: bool) -> bytes:
    """Add a text-box shape to the drawing, and optionally an SVG media part."""
    source = ZipFile(BytesIO(data))
    output = BytesIO()
    with ZipFile(output, "w") as target:
        for entry in source.infolist():
            payload = source.read(entry.filename)
            if entry.filename == "xl/drawings/drawing1.xml":
                text = payload.decode("utf-8")
                payload = text.replace("</wsDr>", _DRAWING_TEXT_BOX + "</wsDr>").encode("utf-8")
            target.writestr(entry, payload)
        if svg:
            target.writestr("xl/media/vector1.svg", _SVG)
    return output.getvalue()


def _parts(data: bytes) -> dict[str, bytes]:
    with ZipFile(BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _run_batched(
    data: bytes, mode: str, layout: str, ocr: _EmptyOcrProvider | None = None
) -> tuple[bytes, TranslationEngine, _BatchProvider]:
    provider = _BatchProvider()
    plan = plan_xlsx(
        data, ocr, "en", "fr", document_text_layout=layout, xlsx_translation_mode=mode
    )
    engine = TranslationEngine(provider, "en", "fr")
    result = plan_and_apply(
        plan, engine, lambda translate: apply_xlsx(plan, translate, _typeface())
    )
    return result.data, engine, provider


class XlsxPlanTests(unittest.TestCase):
    # Verifies FR-2026-10-22-04's coverage of every XLSX text class, and the numeric-text rule.
    def test_fast_plan_lists_cell_comment_chart_and_drawing_text_only(self) -> None:
        plan = plan_xlsx(_workbook_bytes(), None, "en", "fr", xlsx_translation_mode="fast")

        for expected in ("Bounded label", "Loose label", "Comment body", "Chart title", "Drawing box text"):
            self.assertIn(expected, plan.texts)
        for excluded in ("123", "Large first", "Large last"):
            self.assertNotIn(excluded, plan.texts)

    # Verifies FR-2026-10-22-04's rule that a plan lists each part's text once per apply request.
    def test_full_plan_lists_cell_comment_chart_and_drawing_text_in_every_layout(self) -> None:
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                plan = plan_xlsx(
                    _workbook_bytes(), None, "en", "fr", document_text_layout=layout
                )

                for expected in ("Bounded label", "Comment body", "Chart title", "Drawing box text"):
                    self.assertIn(expected, plan.texts)
                self.assertNotIn("123", plan.texts)

    # Verifies FR-2026-10-22-04's plan-miss rule and its identical-to-unbatched rule.
    def test_apply_requests_only_planned_text_and_matches_unbatched_output(self) -> None:
        data = _workbook_bytes()
        for mode in ("full", "fast"):
            for layout in LAYOUTS:
                if mode == "fast" and layout != LAYOUTS[0]:
                    continue
                with self.subTest(mode=mode, layout=layout):
                    batched, engine, provider = _run_batched(data, mode, layout)
                    unbatched_provider = _BatchProvider(BatchLimits(max_items=1, target_characters=1, max_characters=1000))
                    unbatched, _count = replace_xlsx_bytes(
                        data, unbatched_provider, "en", "fr", layout, xlsx_translation_mode=mode
                    )

                    self.assertEqual(0, engine.plan_misses)
                    self.assertEqual(1, len(provider.requests))
                    self.assertGreater(len(unbatched_provider.requests), 1)
                    self.assertEqual(_parts(unbatched), _parts(batched))

    # Verifies FR-2026-10-22-04's one-request packing across a whole workbook.
    def test_one_batch_serves_the_whole_workbook(self) -> None:
        _data, _engine, provider = _run_batched(_workbook_bytes(), "full", LAYOUTS[1])

        self.assertEqual(1, len(provider.requests))
        self.assertEqual(len(set(provider.requests[0])), len(provider.requests[0]))

    # Verifies FR-2026-10-22-04's translated cell content for a planned workbook.
    def test_translated_cells_follow_the_planned_text(self) -> None:
        data, _engine, _provider = _run_batched(_workbook_bytes(), "fast", LAYOUTS[0])

        output = load_workbook(BytesIO(data))
        main = output["Main"]
        self.assertEqual("Bounded label translated", main["A1"].value)
        self.assertEqual("123", main["C2"].value)
        self.assertEqual(42, main["C3"].value)
        self.assertEqual("Large first", output["Large"]["A1"].value)

    # Verifies FR-2026-10-22-05's path-style identifiers for a workbook's media.
    def test_an_image_in_a_workbook_is_a_nested_unit_of_the_workbook(self) -> None:
        data = _workbook_bytes(image=True)
        plan = plan_xlsx(
            data, _RegionOcr("Image words"), "en", "fr", xlsx_translation_mode="fast"
        )
        engine = TranslationEngine(_BatchProvider(), "en", "fr")

        result = plan_and_apply(
            plan, engine, lambda translate: apply_xlsx(plan, translate, _typeface())
        )

        self.assertEqual(["xlsx", "xlsx/image-1"], [unit.unit_id for unit in plan.units()])
        self.assertEqual(("Image words",), list(plan.units())[1].texts)
        self.assertEqual(0, engine.plan_misses)
        self.assertEqual(1, result.image_regions)

    # Verifies FR-2026-10-22-05's rule that a vector graphic is nested in full mode only.
    def test_a_vector_graphic_is_planned_in_full_mode_and_not_in_fast_mode(self) -> None:
        data = _workbook_bytes(svg=True)

        full = plan_xlsx(data, _EmptyOcrProvider(), "en", "fr")
        fast = plan_xlsx(data, _EmptyOcrProvider(), "en", "fr", xlsx_translation_mode="fast")

        self.assertEqual(["xlsx", "xlsx/vector-1"], [unit.unit_id for unit in full.units()][:2])
        self.assertEqual(("Vector label",), list(full.units())[1].texts)
        self.assertEqual(["xlsx"], [unit.unit_id for unit in fast.units()])

    # Verifies FR-2026-10-22-05's rule that a nested workbook uses the same plan as a root file.
    def test_a_nested_workbook_plans_the_same_texts_as_a_root_workbook(self) -> None:
        data = _workbook_bytes()
        root = plan_xlsx(data, None, "en", "fr", xlsx_translation_mode="fast")

        nested = plan_xlsx(
            data, None, "en", "fr", xlsx_translation_mode="fast",
            unit_id=child_unit_id("docx", "chart-1"), depth=1,
        )

        self.assertEqual(root.texts, nested.texts)
        self.assertEqual(["docx/chart-1"], [unit.unit_id for unit in nested.units()])

    # Verifies FR-2026-10-22-07's plan and apply items, which come from the part names alone.
    def test_work_item_total_matches_the_plan_and_apply_ticks(self) -> None:
        data = _workbook_bytes(image=True)
        for mode in ("full", "fast"):
            with self.subTest(mode=mode):
                labels: list[str] = []
                progress = PhaseProgress(labels.append, labels.append, lambda _extra: None)
                plan = plan_xlsx(
                    data, _RegionOcr("Image words"), "en", "fr",
                    xlsx_translation_mode=mode, progress=progress,
                )
                plan_and_apply(
                    plan,
                    TranslationEngine(_BatchProvider(), "en", "fr"),
                    lambda translate: apply_xlsx(plan, translate, _typeface(), progress=progress),
                    progress,
                )
                total = xlsx_work_item_total(_parts(data), "preserve-source-formatting", mode)

                self.assertEqual(total, sum(label.startswith("Planning ") for label in labels))
                self.assertEqual(total, sum(label.startswith("Applying ") for label in labels))
                self.assertTrue(labels[0].endswith(f"1 of {total}"))


if __name__ == "__main__":
    unittest.main()
