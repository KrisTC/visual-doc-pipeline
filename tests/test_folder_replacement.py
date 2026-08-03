#!/usr/bin/env python3
"""Synthetic regression tests for the folder replacement command."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image
# pypdf does not publish PEP 561 metadata for its generic object model.
from pypdf import PdfWriter
from pypdf.generic import ContentStream, DecodedStreamObject
# skia-python does not publish PEP 561 stubs; this is the native rendering boundary.
import skia  # type: ignore[import-not-found]

from pipeline.folder_replacement import FolderReplacementResult, replace_input_folder
from pipeline.folder_replacement.processor import ProgressFactory, ProgressReporter
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
    def __init__(self, filename: str | None = None) -> None:
        self.filename = filename
        self.requests: list[TextReplacementRequest] = []

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        self.requests.append(request)
        if request.is_filename and self.filename is not None:
            return TextReplacementResult(self.filename, 1.0)
        if request.is_filename:
            return TextReplacementResult(request.text, 1.0)
        return TextReplacementResult("#" * len(request.text), 1.0)


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

    @staticmethod
    def _write_png(path: Path) -> None:
        Image.new("RGB", (30, 20), "white").save(path, "PNG")

    def _run(
        self,
        input_root: Path,
        output_root: Path,
        ocr_provider: _EmptyOcrProvider,
        replacement_provider: _RecordingReplacementProvider,
        *,
        show_progress: bool = False,
        progress_factory: ProgressFactory | None = None,
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
            show_progress=show_progress,
            progress_factory=progress_factory,
        )


if __name__ == "__main__":
    unittest.main()
