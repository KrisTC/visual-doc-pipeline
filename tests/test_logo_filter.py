"""Synthetic coverage for folder-replacement logo preservation."""

from contextlib import redirect_stderr
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, ContentStream, DecodedStreamObject, DictionaryObject, NameObject, NumberObject
import skia  # type: ignore[import-not-found]

from folder_replacement_test_support import FONT_PATH, _EmptyOcrProvider, _RecordingReplacementProvider
from pipeline.folder_replacement import replace_input_folder
from pipeline.folder_replacement.logo_filter import LogoFilteringOcrProvider
from pipeline.ocr import BoundingPolygon, OcrRequest, OcrResult, OcrText, PixelPoint
from pipeline.provider_cache import CachingOcrProvider, source_cache_scope
from scripts import container_entrypoint, folder_replacement


def region(text: str, x: int = 5) -> OcrText:
    return OcrText(text, 0.99, BoundingPolygon((
        PixelPoint(x, 5), PixelPoint(x + 75, 5),
        PixelPoint(x + 75, 30), PixelPoint(x, 30),
    )))


class FakeOcr(_EmptyOcrProvider):
    def __init__(self, items: tuple[OcrText, ...]) -> None:
        self.items = items
        self.calls = 0

    def recognize(self, request: OcrRequest) -> OcrResult:
        self.calls += 1
        return OcrResult(self.items)


class LogoFilterTests(unittest.TestCase):
    # Verifies FR-2026-10-29-04.
    def test_exact_case_sensitive_results_and_cached_unfiltered_values(self) -> None:
        items = tuple(region(text) for text in (
            " NovaCorp ", "novacorp", "NovaCorp lamp", "NovaCorporatiion", "Other"
        ))
        provider = FakeOcr(items)
        cached = CachingOcrProvider(provider, "synthetic:v1")
        request = OcrRequest(Image.new("RGB", (100, 40), "white"), "en")
        with (
            TemporaryDirectory() as directory,
            patch.dict("os.environ", {"PIPELINE_PLUGIN_CACHE": "1"}),
            source_cache_scope(Path(directory) / "image.png"),
        ):
            first = LogoFilteringOcrProvider(cached, frozenset({"NovaCorp", "Other"}))
            second = LogoFilteringOcrProvider(cached, frozenset({"novacorp"}))
            self.assertEqual(items[1:4], first.recognize(request).text_items)
            self.assertEqual((items[0], *items[2:]), second.recognize(request).text_items)
            self.assertEqual(1, provider.calls)

    # Verifies FR-2026-10-29-04.
    def test_folder_bitmap_excludes_logo_from_translation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            input_root = root / "input"
            input_root.mkdir()
            image = Image.new("RGB", (200, 40), "white")
            image.putpixel((10, 10), (0, 0, 0))
            image.save(input_root / "sample.png")
            provider = FakeOcr((region(" NovaCorp "), region("lamp", 70)))
            replacement = _RecordingReplacementProvider(replacement_text="light")
            result = replace_input_folder(
                input_root, root / "output", ocr_provider=provider,
                text_replacement_provider=replacement, source_language="en", target_language="en",
                typeface=skia.Typeface.MakeFromFile(str(FONT_PATH)),
                preserve_logo_text=(" NovaCorp ",), show_progress=False,
            )
            self.assertEqual(0, result.failed_files)
            self.assertEqual(1, result.replaced_image_regions)
            self.assertEqual(["lamp"], [r.text for r in replacement.requests if not r.is_filename])
            with Image.open(root / "output" / "sample.png") as output:
                self.assertEqual((0, 0, 0), output.getpixel((10, 10)))

    # Verifies FR-2026-10-29-04.
    def test_embedded_bitmap_and_pdf_ocr_paths_filter_results(self) -> None:
        for kind in ("embedded", "vector", "undecodable"):
            with self.subTest(kind=kind), TemporaryDirectory() as directory:
                root = Path(directory)
                input_root = root / "input"
                input_root.mkdir()
                if kind == "embedded":
                    data = BytesIO()
                    Image.new("RGB", (100, 40), "white").save(data, "PNG")
                    with ZipFile(input_root / "source.docx", "w", ZIP_DEFLATED) as archive:
                        archive.writestr("word/media/image.png", data.getvalue())
                else:
                    writer = PdfWriter()
                    page = writer.add_blank_page(100, 100)
                    stream = DecodedStreamObject()
                    if kind == "vector":
                        stream.set_data(b"q 0 0 0 rg 26 36 4 12 re f Q")
                    else:
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
                        stream.set_data(b"BT /F1 12 Tf 10 10 Td <0001> Tj ET")
                    page.replace_contents(ContentStream(stream, writer))
                    with (input_root / "source.pdf").open("wb") as output:
                        writer.write(output)
                ocr = FakeOcr((region("NovaCorp"),))
                replacement = _RecordingReplacementProvider()
                result = replace_input_folder(
                    input_root, root / "output", ocr_provider=ocr,
                    text_replacement_provider=replacement, source_language="en", target_language="en",
                    typeface=skia.Typeface.MakeFromFile(str(FONT_PATH)),
                    document_text_layout=("preserve-source-formatting" if kind == "embedded"
                                          else "preserve-basic-layout"),
                    preserve_logo_text=("NovaCorp",),
                    show_progress=False,
                )
                self.assertEqual(0, result.failed_files)
                self.assertEqual(1, ocr.calls)
                self.assertEqual(0, result.replaced_image_regions)
                self.assertNotIn("NovaCorp", [r.text for r in replacement.requests if not r.is_filename])

    # Verifies FR-2026-10-29-04.
    def test_cli_rejects_empty_values_and_container_forwards_repeated_options(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            input_root = root / "input"
            input_root.mkdir()
            args = ["--source-language", "en", "--preserve-logo-text", "  "]
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
                folder_replacement.main(args, fixed_roots=(input_root, root / "out"))
            self.assertEqual(2, error.exception.code)
            args = ["--source-language", "en", "--preserve-logo-text", "NovaCorp",
                    "--preserve-logo-text", "NOVACORP"]
            with patch.object(container_entrypoint, "INPUT_DIRECTORY", input_root), patch.object(
                container_entrypoint, "OUTPUT_DIRECTORY", root / "out"
            ), patch.object(container_entrypoint, "bootstrap_completed", return_value=True), patch.object(
                folder_replacement, "main", return_value=0
            ) as command:
                self.assertEqual(0, container_entrypoint.main(args))
            command.assert_called_once_with(args, fixed_roots=(input_root, root / "out"))
            parsed = folder_replacement._argument_parser((input_root, root / "out")).parse_args(args)
            self.assertEqual(["NovaCorp", "NOVACORP"], parsed.preserve_logo_text)
