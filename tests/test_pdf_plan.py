#!/usr/bin/env python3
"""Plan and apply tests for the PDF handler."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import skia  # type: ignore[import-not-found]
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    ContentStream,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from folder_replacement_test_support import FONT_PATH, _EmptyOcrProvider
from pipeline.folder_replacement.pdf import apply_pdf, pdf_work_total, plan_pdf
from pipeline.folder_replacement.planning import PhaseProgress, plan_and_apply
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


class _BatchProvider:
    """Translate by suffixing, and record the texts of each request."""

    def __init__(self, limits: BatchLimits | None = None) -> None:
        self.batch_limits = limits
        self.requests: list[tuple[str, ...]] = []

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        self.requests.append(request.texts)
        return replace_each(request, lambda text: TextReplacementItem(f"{text} translated", 1.0))


class _RegionOcr(_EmptyOcrProvider):
    """Return one confident region for a page render or an embedded image."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def recognize(self, request: OcrRequest) -> OcrResult:
        self.calls += 1
        if request.image.width > 150:
            points = (PixelPoint(50, 130), PixelPoint(230, 130), PixelPoint(230, 200), PixelPoint(50, 200))
        else:
            points = (PixelPoint(5, 5), PixelPoint(95, 5), PixelPoint(95, 30), PixelPoint(5, 30))
        return OcrResult((OcrText(self.text, 0.99, BoundingPolygon(points)),))


def _typeface() -> skia.Typeface:
    typeface = skia.Typeface.MakeFromFile(str(FONT_PATH))
    if typeface is None:
        raise AssertionError("Could not load test typeface.")
    return typeface


def _font(writer: PdfWriter) -> object:
    return writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
        NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
    }))


def _image(writer: PdfWriter) -> object:
    stream = DecodedStreamObject()
    stream.set_data(bytes((x * 7 + y * 3 + c * 50) % 256 for y in range(40) for x in range(100) for c in range(3)))
    stream.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Image"),
        NameObject("/Width"): NumberObject(100),
        NameObject("/Height"): NumberObject(40),
        NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
        NameObject("/BitsPerComponent"): NumberObject(8),
    })
    return writer._add_object(stream)


def _pdf_bytes(*, annotated: bool = True, form_field: bool = True) -> bytes:
    """Build a synthetic three-page PDF: native text, an image, a form XObject, an annotation,
    a form field, a vector-only page and a second image."""
    writer = PdfWriter()
    font = _font(writer)
    page = writer.add_blank_page(300, 300)
    form = DecodedStreamObject()
    form.set_data(b"BT /F1 11 Tf 10 10 Td (Inside form) Tj ET")
    form.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(200), NumberObject(30)]),
        NameObject("/Resources"): DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        NameObject("/XObject"): DictionaryObject({
            NameObject("/Im1"): _image(writer),
            NameObject("/Fm1"): writer._add_object(form),
        }),
    })
    contents = DecodedStreamObject()
    contents.set_data(
        b"BT /F1 14 Tf 20 270 Td (Hello world) Tj ET "
        b"BT /F1 10 Tf 20 250 Td (Second line of text) Tj 0 -14 Td (Third) Tj ET "
        b"q 100 0 0 40 20 150 cm /Im1 Do Q "
        b"q 1 0 0 1 20 100 cm /Fm1 Do Q "
        b"q 0.8 0.9 1 rg 150 20 65 27 re f 0 0 0 rg 160 28 4 12 re f Q"
    )
    page.replace_contents(ContentStream(contents, writer))
    if annotated:
        annotation = DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/FreeText"),
            NameObject("/Rect"): ArrayObject([NumberObject(180), NumberObject(250), NumberObject(290), NumberObject(280)]),
            NameObject("/Contents"): TextStringObject("annotation text"),
            NameObject("/DA"): TextStringObject("/Helv 12 Tf 0 g"),
        })
        page[NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])
    if form_field:
        widget = writer._add_object(DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/FT"): NameObject("/Tx"),
            NameObject("/T"): TextStringObject("field"),
            NameObject("/V"): TextStringObject("field value"),
            NameObject("/Rect"): ArrayObject([NumberObject(180), NumberObject(200), NumberObject(290), NumberObject(230)]),
            NameObject("/DA"): TextStringObject("/Helv 12 Tf 0 g"),
        }))
        writer._root_object[NameObject("/AcroForm")] = DictionaryObject({
            NameObject("/Fields"): ArrayObject([widget]),
            NameObject("/DA"): TextStringObject("/Helv 12 Tf 0 g"),
        })
    vector_page = writer.add_blank_page(100, 100)
    vector = DecodedStreamObject()
    vector.set_data(b"q 0.8 0.9 1 rg 18 28 65 27 re f 0 0 0 rg 26 36 4 12 re f 35 36 4 12 re f Q")
    vector_page.replace_contents(ContentStream(vector, writer))
    third = writer.add_blank_page(200, 100)
    third[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        NameObject("/XObject"): DictionaryObject({NameObject("/Im1"): _image(writer)}),
    })
    text = DecodedStreamObject()
    text.set_data(b"BT /F1 12 Tf 10 80 Td (Page three) Tj ET q 100 0 0 40 10 20 cm /Im1 Do Q")
    third.replace_contents(ContentStream(text, writer))
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _run_batched(
    source: Path,
    destination: Path,
    layout: str,
    ocr: _EmptyOcrProvider,
    limits: BatchLimits | None = None,
) -> tuple[TranslationEngine, _BatchProvider, tuple[int, int]]:
    provider = _BatchProvider(limits)
    plan = plan_pdf(source, ocr, "en", "fr", document_text_layout=layout)
    engine = TranslationEngine(provider, "en", "fr")
    counts = plan_and_apply(
        plan, engine, lambda translate: apply_pdf(plan, translate, _typeface(), destination)
    )
    return engine, provider, counts


def _all_texts(plan_units: object) -> set[str]:
    return {text for unit in plan_units for text in unit.texts}  # type: ignore[attr-defined]


class PdfPlanTests(unittest.TestCase):
    # Verifies FR-2026-10-22-04's coverage of every PDF text class in every layout mode.
    def test_plan_lists_every_pdf_text_class_without_calling_a_provider(self) -> None:
        for layout in LAYOUTS:
            with self.subTest(layout=layout), TemporaryDirectory() as directory:
                source = Path(directory) / "source.pdf"
                source.write_bytes(_pdf_bytes(annotated=layout != LAYOUTS[0], form_field=layout != LAYOUTS[0]))
                ocr = _RegionOcr("outlined")

                plan = plan_pdf(source, ocr, "en", "fr", document_text_layout=layout)

                texts = _all_texts(plan.units())
                self.assertIn("Page three", texts)
                self.assertIn("outlined", texts)
                self.assertTrue(any(text.startswith("Hello world") for text in texts))
                if layout != LAYOUTS[0]:
                    self.assertIn("Inside form", texts)
                    self.assertIn("annotation text", texts)
                    self.assertIn("field value", texts)

    # Verifies FR-2026-10-22-05's path-style identifiers for pages, form fields and images.
    def test_units_have_path_style_identifiers(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.pdf"
            source.write_bytes(_pdf_bytes())

            plan = plan_pdf(source, _RegionOcr("outlined"), "en", "fr", document_text_layout=LAYOUTS[1])

            self.assertEqual(
                ["pdf/page-1", "pdf/page-2", "pdf/page-3", "pdf/form-fields", "pdf/image-1", "pdf/image-2"],
                [unit.unit_id for unit in plan.units()],
            )

    # Verifies FR-2026-10-22-04's rule that OCR runs once per image and vector-only page.
    def test_ocr_runs_once_per_image_and_vector_page_across_plan_and_apply(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.pdf"
            source.write_bytes(_pdf_bytes())
            ocr = _RegionOcr("outlined")

            _run_batched(source, Path(directory) / "out.pdf", LAYOUTS[1], ocr)

            self.assertEqual(4, ocr.calls)

    # Verifies FR-2026-10-22-04's plan-miss rule and its identical-to-unbatched rule.
    def test_apply_requests_only_planned_text_and_matches_unbatched_output(self) -> None:
        for layout in LAYOUTS:
            with self.subTest(layout=layout), TemporaryDirectory() as directory:
                source = Path(directory) / "source.pdf"
                source.write_bytes(_pdf_bytes(annotated=layout != LAYOUTS[0], form_field=False))
                batched_path = Path(directory) / "batched.pdf"
                unbatched_path = Path(directory) / "unbatched.pdf"

                engine, provider, _counts = _run_batched(
                    source, batched_path, layout, _RegionOcr("outlined")
                )
                _engine, unbatched_provider, _counts = _run_batched(
                    source, unbatched_path, layout, _RegionOcr("outlined"),
                    BatchLimits(max_items=1, target_characters=1, max_characters=1000),
                )

                self.assertEqual(0, engine.plan_misses)
                self.assertLess(len(provider.requests), len(unbatched_provider.requests))
                self.assertEqual(unbatched_path.read_bytes(), batched_path.read_bytes())
                for request in provider.requests:
                    self.assertEqual(len(set(request)), len(request))

    # Verifies FR-2026-10-22-04's rule that translated text lands in the planned places.
    def test_translated_text_is_written_to_the_pages(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.pdf"
            source.write_bytes(_pdf_bytes(annotated=False, form_field=False))
            destination = Path(directory) / "out.pdf"

            _run_batched(source, destination, LAYOUTS[0], _RegionOcr("outlined"))

            pages = PdfReader(destination).pages
            self.assertIn("Hello world translated", pages[0].extract_text())
            self.assertIn("Page three translated", pages[2].extract_text())

    # Verifies FR-2026-10-22-07's plan and apply items, which come from the document alone.
    def test_work_total_matches_the_plan_and_apply_ticks(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.pdf"
            source.write_bytes(_pdf_bytes())
            labels: list[str] = []
            progress = PhaseProgress(labels.append, labels.append, lambda _extra: None)
            plan = plan_pdf(
                source, _RegionOcr("outlined"), "en", "fr",
                document_text_layout=LAYOUTS[1], progress=progress,
            )

            plan_and_apply(
                plan,
                TranslationEngine(_BatchProvider(), "en", "fr"),
                lambda translate: apply_pdf(
                    plan, translate, _typeface(), Path(directory) / "out.pdf", progress=progress
                ),
                progress,
            )
            total = pdf_work_total(source)

            self.assertEqual(total // 2, sum(label.startswith("Planning ") for label in labels))
            self.assertEqual(total // 2, sum(label.startswith("Applying ") for label in labels))
            self.assertEqual("Planning page 1 of 6", labels[0])


if __name__ == "__main__":
    unittest.main()
