"""Tests for the shared vector graphic plan and apply steps."""

from __future__ import annotations

import base64
from io import BytesIO
import struct
import unittest

from PIL import Image

from folder_replacement_test_support import _EmptyOcrProvider
from pipeline.folder_replacement.bitmap import replace_image
from pipeline.folder_replacement.planning import (
    NESTED_DOCUMENT_MAX_DEPTH,
    child_unit_id,
    plan_and_apply,
)
from pipeline.folder_replacement.vector import (
    apply_vector,
    plan_vector,
    replace_vector_bytes,
)
from pipeline.text_replacement import (
    BatchLimits,
    TextReplacementItem,
    TextReplacementRequest,
    TextReplacementResult,
    TextUnit,
    TranslationEngine,
    replace_each,
    replace_text,
)
from pipeline.text_replacement_plugins.character_mask import CharacterMaskProvider
from pipeline.vector_text import analyse_vector_text, replace_vector_text
from pipeline.vector_text.replacer import vector_format
from test_batch_engine import (
    _RecordingProvider,
    _RegionsOcr,
    _synthetic_png,
    _typeface,
)
from test_vector_text_replacer import (
    _emf_with_stretchdibits_image,
    _emf_with_text,
    _wmf_stretchdib_pixel,
    _wmf_with_stretchdib_image,
    _wmf_with_text,
)

_LAYOUT_MODES = (
    "preserve-source-formatting",
    "preserve-basic-layout",
    "preserve-basic-layout-source-font",
)


def _svg_with_text_and_image() -> bytes:
    return (
        b'<svg xmlns="http://www.w3.org/2000/svg"><defs><clipPath id="box">'
        b'<rect width="400" height="40"/></clipPath></defs>'
        b'<text clip-path="url(#box)" font-size="20">first label</text>'
        b'<text font-size="20">second label</text>'
        b'<image href="data:image/png;base64,' + base64.b64encode(_synthetic_png()) + b'"/></svg>'
    )


def _legacy_vector_output(data: bytes, extension: str, texts: tuple[str, ...], layout: str) -> bytes:
    """Reproduce the interleaved path that plan and apply replaced."""
    provider = CharacterMaskProvider()
    result = replace_vector_text(
        data,
        extension,
        lambda text: replace_text(
            provider, text, is_filename=False, source_language="en", target_language="en"
        ).text,
        "en",
        lambda image: replace_image(image, _RegionsOcr(texts), provider, "en", "en", _typeface()),
        document_text_layout=layout,
        replacement_provider=provider,
        target_language="en",
    )
    return result.data


class VectorPlanApplyTests(unittest.TestCase):
    # Verifies FR-2026-10-22-04's output equivalence for vector graphics.
    def test_svg_output_is_identical_to_the_interleaved_path_in_every_layout_mode(self) -> None:
        texts = ("alpha", "beta")
        for layout in _LAYOUT_MODES:
            with self.subTest(layout=layout):
                data = replace_vector_bytes(
                    _svg_with_text_and_image(), ".svg", _RegionsOcr(texts), CharacterMaskProvider(),
                    "en", "en", _typeface(), document_text_layout=layout,
                ).data

                self.assertEqual(
                    _legacy_vector_output(_svg_with_text_and_image(), ".svg", texts, layout), data
                )

    # Verifies FR-2026-10-22-04's plan completeness: apply needs no single-text fallback.
    def test_apply_needs_no_plan_miss_in_any_layout_mode(self) -> None:
        for layout in _LAYOUT_MODES:
            with self.subTest(layout=layout):
                plan = plan_vector(
                    _svg_with_text_and_image(), ".svg", _RegionsOcr(("alpha", "beta")), "en", "en",
                    document_text_layout=layout,
                )
                engine = TranslationEngine(_RecordingProvider(), "en", "en")

                plan_and_apply(plan, engine, lambda translate: apply_vector(plan, translate, _typeface()))

                self.assertEqual(0, engine.plan_misses)

    # Verifies FR-2026-10-22-04's plan-has-no-side-effects rule for vector graphics.
    def test_plan_calls_no_text_provider_and_runs_ocr_once_per_embedded_image(self) -> None:
        ocr = _RegionsOcr(("alpha", "beta"))
        provider = _RecordingProvider()

        plan = plan_vector(_svg_with_text_and_image(), ".svg", ocr, "en", "en")

        self.assertEqual([], provider.requests)
        self.assertEqual(1, ocr.calls)
        self.assertEqual(("first label", "second label"), plan.texts)

    # Verifies FR-2026-10-22-04's one-request-per-batch rule across a graphic and its images.
    def test_request_count_matches_packing_over_text_and_image_units(self) -> None:
        provider = _RecordingProvider(BatchLimits(max_items=2, target_characters=1000, max_characters=2000))

        replace_vector_bytes(
            _svg_with_text_and_image(), ".svg", _RegionsOcr(("alpha", "beta", "gamma")), provider,
            "en", "en", _typeface(),
        )

        self.assertEqual(
            [("first label", "second label"), ("alpha", "beta"), ("gamma",)],
            [request.texts for request in provider.requests],
        )

    # Verifies FR-2026-10-22-05's path-style unit identifiers for a vector parent and image child.
    def test_units_use_path_style_identifiers_depth_first(self) -> None:
        plan = plan_vector(_svg_with_text_and_image(), ".svg", _RegionsOcr(("alpha",)), "en", "en")

        self.assertEqual(
            [
                TextUnit("vector", ("first label", "second label")),
                TextUnit("vector/image-1", ("alpha",)),
            ],
            list(plan.units()),
        )

    # Verifies FR-2026-10-22-05's nested unit identifiers one level below a parent document.
    def test_a_nested_vector_plan_takes_its_parent_path(self) -> None:
        plan = plan_vector(
            _svg_with_text_and_image(), ".svg", _RegionsOcr(("alpha",)), "en", "en",
            unit_id=child_unit_id("docx", "graphic-1"),
        )

        self.assertEqual(
            ["docx/graphic-1", "docx/graphic-1/image-1"], [unit.unit_id for unit in plan.units()]
        )

    # Verifies FR-2026-10-22-05's single implementation for root and nested documents.
    def test_a_nested_image_equals_the_same_bytes_processed_as_a_root_file(self) -> None:
        texts = ("alpha", "beta", "gamma")
        source = (
            b'<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,'
            + base64.b64encode(_synthetic_png()) + b'"/></svg>'
        )

        result = replace_vector_bytes(
            source, ".svg", _RegionsOcr(texts), CharacterMaskProvider(), "en", "en", _typeface()
        )
        embedded = base64.b64decode(result.data.split(b"base64,")[1].split(b'"')[0])

        root, count = _replace_root_bitmap(texts)
        self.assertEqual(3, result.replaced_image_regions)
        self.assertEqual(3, count)
        self.assertEqual(
            Image.open(BytesIO(root)).convert("RGBA").tobytes(),
            Image.open(BytesIO(embedded)).convert("RGBA").tobytes(),
        )

    # Verifies FR-2026-10-22-05's depth limit and the debug-only sidecar entry.
    def test_images_beyond_the_depth_limit_are_left_unprocessed_without_ocr(self) -> None:
        ocr = _RegionsOcr(("alpha",))
        diagnostics: list[dict[str, object]] = []

        plan = plan_vector(
            _svg_with_text_and_image(), ".svg", ocr, "en", "en",
            depth=NESTED_DOCUMENT_MAX_DEPTH, package_part="word/media/deep.svg",
            diagnostics=diagnostics,
        )
        engine = TranslationEngine(_RecordingProvider(), "en", "en")
        result = plan_and_apply(plan, engine, lambda translate: apply_vector(plan, translate, _typeface()))

        self.assertEqual(0, ocr.calls)
        self.assertEqual(0, result.replaced_image_regions)
        self.assertEqual(1, len(diagnostics))
        self.assertEqual("nested_document_depth_limit_exceeded", diagnostics[0]["reason_code"])
        self.assertIn(b"T:first label", result.data)

    # Verifies FR-2026-10-22-05's debug-only reporting.
    def test_the_depth_limit_writes_no_entry_without_diagnostics(self) -> None:
        plan = plan_vector(
            _svg_with_text_and_image(), ".svg", _RegionsOcr(("alpha",)), "en", "en",
            depth=NESTED_DOCUMENT_MAX_DEPTH,
        )

        self.assertEqual([None], plan.images)

    # Verifies FR-2026-10-22-04's per-text equivalence for EMF and WMF text.
    def test_emf_and_wmf_text_equals_the_interleaved_path(self) -> None:
        for extension, source in ((".emf", _emf_with_text("Hello")), (".wmf", _wmf_with_text("Hello"))):
            with self.subTest(extension=extension):
                plan = plan_vector(source, extension, _EmptyOcrProvider(), "en", "en")
                data = replace_vector_bytes(
                    source, extension, _EmptyOcrProvider(), CharacterMaskProvider(), "en", "en",
                    _typeface(),
                ).data

                self.assertEqual(("Hello",), plan.texts)
                self.assertEqual(_legacy_vector_output(source, extension, (), "preserve-source-formatting"), data)

    # Verifies FR-2026-10-22-05's image children for EMF and WMF device-independent bitmaps.
    def test_emf_and_wmf_images_are_planned_as_nested_bitmaps(self) -> None:
        for extension, source in (
            (".emf", _emf_with_stretchdibits_image()),
            (".wmf", _wmf_with_stretchdib_image()),
        ):
            with self.subTest(extension=extension):
                plan = plan_vector(source, extension, _EmptyOcrProvider(), "en", "en")

                self.assertEqual(["vector", "vector/image-1"], [unit.unit_id for unit in plan.units()])

    # Verifies FR-2026-10-22-04's guard against a plan that does not match the graphic.
    def test_apply_rejects_a_plan_with_a_different_number_of_images(self) -> None:
        plan = plan_vector(_svg_with_text_and_image(), ".svg", _RegionsOcr(("alpha",)), "en", "en")
        plan.images.clear()
        engine = TranslationEngine(_RecordingProvider(), "en", "en")

        with self.assertRaisesRegex(RuntimeError, "more embedded images"):
            plan_and_apply(plan, engine, lambda translate: apply_vector(plan, translate, _typeface()))


class SvgAnalysisTests(unittest.TestCase):
    # Verifies FR-2026-10-22-04's output equivalence: fixed expected bytes recorded from the pre-refactor handler.
    def test_svg_text_slots_are_listed_in_document_order_and_written_back_exactly(self) -> None:
        source = (
            b'<svg xmlns="http://www.w3.org/2000/svg"><text>Top<tspan>Inner</tspan>Tail</text>'
            b"<g><text> </text></g></svg>"
        )
        document = analyse_vector_text(source, ".svg", "en", "en", document_text_layout="preserve-source-formatting")

        self.assertEqual(("Top", "Inner", "Tail", " "), document.texts())
        self.assertEqual(
            b"<?xml version='1.0' encoding='utf-8'?>\n"
            b'<ns0:svg xmlns:ns0="http://www.w3.org/2000/svg"><ns0:text>TOP<ns0:tspan>INNER</ns0:tspan>'
            b"TAIL</ns0:text><ns0:g><ns0:text> </ns0:text></ns0:g></ns0:svg>",
            document.apply(lambda text: text.upper(), None, None).data,
        )

    # Verifies FR-2026-10-22-04's plan has no side effects: analysis lists texts and images only.
    def test_svg_analysis_lists_texts_and_images_without_replacing_anything(self) -> None:
        for layout in _LAYOUT_MODES:
            with self.subTest(layout=layout):
                document = analyse_vector_text(
                    _svg_with_text_and_image(), ".svg", "en", "en", document_text_layout=layout
                )

                self.assertEqual(("first label", "second label"), document.texts())
                self.assertEqual([(200, 40)], [image.size for image in document.images()])

    # Verifies FR-2026-10-22-04's single decode: apply renders onto the image analysis decoded.
    def test_svg_apply_passes_the_analysed_image_with_its_index(self) -> None:
        document = analyse_vector_text(_svg_with_text_and_image(), ".svg", "en", "en")
        seen: list[tuple[int, object]] = []

        def replace_image(index: int, image: Image.Image) -> int:
            seen.append((index, image))
            return 0

        result = document.apply(lambda text: text.upper(), None, replace_image)

        self.assertEqual([(0, document.images()[0])], seen)
        self.assertEqual(2, result.replaced_text_items)
        self.assertIn(b"FIRST LABEL", result.data)

    # Verifies FR-2026-10-22-04's guard: clipped text cannot be fitted without a provider.
    def test_svg_fitted_apply_requires_a_provider(self) -> None:
        document = analyse_vector_text(
            _svg_with_text_and_image(), ".svg", "en", "en", document_text_layout="preserve-basic-layout"
        )

        with self.assertRaisesRegex(ValueError, "needs a provider"):
            document.apply(lambda text: text, None, None)


def _wmf_record(function: int, body: bytes) -> bytes:
    data = bytearray(struct.pack("<IH", 0, function) + body)
    if len(data) % 2:
        data.append(0)
    struct.pack_into("<I", data, 0, len(data) // 2)
    return bytes(data)


def _wmf_with_clipped_text(text: str) -> bytes:
    """A WMF with a selected font and a clipped ExtTextOut, the case that gets fitted."""
    encoded = text.encode("latin-1")
    records = (
        _wmf_record(0x02FB, struct.pack("<hhhh", -20, 0, 0, 0) + b"\0" * 20),
        _wmf_record(0x012D, struct.pack("<H", 0)),
        _wmf_record(
            0x0A32,
            struct.pack("<hhHH", 5, 5, len(encoded), 0x4) + struct.pack("<hhhh", 0, 0, 40, 10) + encoded,
        ),
        struct.pack("<IH", 3, 0),
    )
    header = struct.pack("<HHHIHIH", 1, 9, 0x0300, 0, 0, 0, 0)
    return header + b"".join(records)


def _wmf_with_fonted_text(text: str, *, extended: bool, height: int = -20, escapement: int = 0) -> bytes:
    """A WMF with a selected font and an unclipped TextOut or ExtTextOut."""
    encoded = text.encode("latin-1")
    logfont = struct.pack("<hhhhh", height, 0, escapement, 0, 400) + bytes(8) + b"No Such Face".ljust(32, b"\0")
    if extended:
        draw = _wmf_record(0x0A32, struct.pack("<hhHH", 5, 5, len(encoded), 0) + encoded)
    else:
        draw = _wmf_record(0x0521, struct.pack("<H", len(encoded)) + encoded + b"\0" * (len(encoded) % 2) + struct.pack("<hh", 5, 5))
    records = (
        _wmf_record(0x02FB, logfont),
        _wmf_record(0x012D, struct.pack("<H", 0)),
        draw,
        struct.pack("<IH", 3, 0),
    )
    header = struct.pack("<HHHIHIH", 1, 9, 0x0300, 0, 0, 0, 0)
    return header + b"".join(records)


def _wmf_functions(data: bytes) -> list[int]:
    functions: list[int] = []
    offset = struct.unpack_from("<H", data, 2)[0] * 2
    while offset < len(data):
        size_words, function = struct.unpack_from("<IH", data, offset)
        functions.append(function)
        offset += size_words * 2
    return functions


class _FixedReplacementProvider:
    def __init__(self, replacement: str) -> None:
        self._replacement = replacement

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        return replace_each(request, lambda text: TextReplacementItem(self._replacement, 1.0))


class WmfUnclippedFitTests(unittest.TestCase):
    def _replace(self, source: bytes, replacement: str) -> bytes:
        return replace_vector_text(
            source, ".wmf", lambda text: "#" * len(text), "en",
            document_text_layout="preserve-basic-layout",
            replacement_provider=_FixedReplacementProvider(replacement), target_language="en",
        ).data

    # Verifies FR-2026-10-22-13.
    def test_a_wider_replacement_is_drawn_with_a_smaller_cloned_font(self) -> None:
        for extended in (False, True):
            with self.subTest(extended=extended):
                result = self._replace(
                    _wmf_with_fonted_text("Hello", extended=extended), "A considerably longer heading"
                )

                self.assertIn(b"A considerably longer heading", result)
                functions = _wmf_functions(result)
                self.assertEqual(2, functions.count(0x02FB))
                self.assertIn(0x01F0, functions)

    # Verifies FR-2026-10-22-13.
    def test_a_replacement_that_is_no_wider_keeps_the_source_font(self) -> None:
        for extended in (False, True):
            with self.subTest(extended=extended):
                result = self._replace(_wmf_with_fonted_text("Hello", extended=extended), "Hi")

                self.assertIn(b"Hi", result)
                self.assertEqual(1, _wmf_functions(result).count(0x02FB))

    # Verifies FR-2026-10-22-13 and FR-2026-10-22-11: unsafe text is still translated, unfitted.
    def test_text_that_cannot_be_fitted_safely_is_replaced_at_its_source_size(self) -> None:
        sources = (
            _wmf_with_fonted_text("Hello", extended=False, escapement=900),
            _wmf_with_fonted_text("Hello", extended=True, height=0),
            _wmf_with_text("Hello"),
        )
        for index, source in enumerate(sources):
            with self.subTest(index=index):
                result = self._replace(source, "A considerably longer heading")

                self.assertIn(b"#####", result)
                self.assertNotIn(b"considerably", result)
                self.assertLessEqual(_wmf_functions(result).count(0x02FB), 1)


class WmfAnalysisTests(unittest.TestCase):
    # Verifies FR-2026-10-22-04's output equivalence: fixed expected bytes from an independent builder.
    def test_wmf_text_slots_are_listed_and_written_back_exactly(self) -> None:
        document = analyse_vector_text(_wmf_with_text("abc"), ".wmf", "en", "en")

        self.assertEqual(("abc",), document.texts())
        self.assertEqual(_wmf_with_text("ABC"), document.apply(lambda text: text.upper(), None, None).data)

    # Verifies FR-2026-10-22-04's plan has no side effects: analysis lists texts and images only.
    def test_wmf_analysis_lists_texts_and_images_without_replacing_anything(self) -> None:
        document = analyse_vector_text(_wmf_with_stretchdib_image(), ".wmf", "en", "en")

        self.assertEqual((), document.texts())
        self.assertEqual([(2, 1)], [image.size for image in document.images()])

    # Verifies FR-2026-10-22-04's single decode: apply renders onto the image analysis decoded.
    def test_wmf_apply_passes_the_analysed_image_with_its_index(self) -> None:
        document = analyse_vector_text(_wmf_with_stretchdib_image(), ".wmf", "en", "en")
        seen: list[tuple[int, object]] = []

        def replace_image(index: int, image: Image.Image) -> int:
            seen.append((index, image))
            image.paste((9, 9, 9), (0, 0, 1, 1))
            return 1

        result = document.apply(lambda text: text, None, replace_image)

        self.assertEqual([(0, document.images()[0])], seen)
        self.assertEqual((9, 9, 9), _wmf_stretchdib_pixel(result.data))

    # Verifies FR-2026-10-22-04's plan completeness for fitted WMF text in every layout mode.
    def test_clipped_wmf_text_needs_no_plan_miss_in_any_layout_mode(self) -> None:
        for layout in _LAYOUT_MODES:
            with self.subTest(layout=layout):
                source = _wmf_with_clipped_text("Hello")
                plan = plan_vector(source, ".wmf", _EmptyOcrProvider(), "en", "en", document_text_layout=layout)
                engine = TranslationEngine(_RecordingProvider(), "en", "en")

                plan_and_apply(plan, engine, lambda translate: apply_vector(plan, translate, _typeface()))

                self.assertEqual(("Hello",), plan.texts)
                self.assertEqual(0, engine.plan_misses)

    # Verifies FR-2026-10-22-04's output equivalence: fitted text keeps the interleaved path's output.
    def test_fitted_wmf_text_equals_the_interleaved_path(self) -> None:
        for layout in ("preserve-basic-layout", "preserve-basic-layout-source-font"):
            with self.subTest(layout=layout):
                source = _wmf_with_clipped_text("Hello")
                data = replace_vector_bytes(
                    source, ".wmf", _EmptyOcrProvider(), CharacterMaskProvider(), "en", "en",
                    _typeface(), document_text_layout=layout,
                ).data

                self.assertEqual(_legacy_vector_output(source, ".wmf", (), layout), data)

    # Verifies FR-2026-10-22-04's rule that without a provider a clipped WMF text is replaced unfitted.
    def test_wmf_fitted_apply_without_a_provider_replaces_text_unfitted(self) -> None:
        document = analyse_vector_text(
            _wmf_with_clipped_text("Hello"), ".wmf", "en", "en", document_text_layout="preserve-basic-layout"
        )

        result = document.apply(lambda text: text.upper(), None, None)

        self.assertEqual(1, result.replaced_text_items)
        self.assertIn(b"HELLO", result.data)


def _emf_with_signature(text: str) -> bytes:
    """A synthetic EMF whose header carries the ` EMF` signature, as every real EMF does."""
    data = bytearray(_emf_with_text(text))
    data[40:44] = b" EMF"
    return bytes(data)


class VectorFormatIdentificationTests(unittest.TestCase):
    # Verifies FR-2026-10-22-09's content-based format identification: an EMF saved as .wmf.
    def test_an_emf_with_a_wmf_extension_is_handled_as_emf(self) -> None:
        source = _emf_with_signature("Hello")

        document = analyse_vector_text(source, ".wmf", "en", "en")
        result = replace_vector_text(source, ".wmf", lambda text: text.upper(), "en", None)

        self.assertEqual(("Hello",), document.texts())
        self.assertEqual(replace_vector_text(source, ".emf", lambda text: text.upper(), "en", None), result)
        self.assertEqual(1, result.replaced_text_items)

    # Verifies FR-2026-10-22-09's content-based format identification: a WMF saved as .emf.
    def test_a_wmf_with_an_emf_extension_is_handled_as_wmf(self) -> None:
        source = _wmf_with_text("Hello")

        document = analyse_vector_text(source, ".emf", "en", "en")
        result = replace_vector_text(source, ".emf", lambda text: text.upper(), "en", None)

        self.assertEqual(("Hello",), document.texts())
        self.assertEqual(_wmf_with_text("HELLO"), result.data)

    # Verifies FR-2026-10-22-09's content-based format identification: placeable WMF and extension fallback.
    def test_placeable_wmf_is_recognised_and_unknown_content_keeps_its_extension(self) -> None:
        placeable = b"\xd7\xcd\xc6\x9a" + b"\0" * 18 + _wmf_with_text("Hello")

        self.assertEqual(".wmf", vector_format(placeable, ".emf"))
        self.assertEqual(".emf", vector_format(b"not a graphic", ".EMF"))
        self.assertEqual(".svg", vector_format(_emf_with_signature("Hello"), ".svg"))
        with self.assertRaisesRegex(ValueError, "Invalid WMF header size"):
            replace_vector_text(b"\x01\x00\x01\x00" + b"\0" * 20, ".wmf", lambda text: text, "en", None)


def _replace_root_bitmap(texts: tuple[str, ...]) -> tuple[bytes, int]:
    from pipeline.folder_replacement.bitmap import replace_bitmap_bytes

    return replace_bitmap_bytes(
        _synthetic_png(), _RegionsOcr(texts), CharacterMaskProvider(), "en", "en", _typeface()
    )


if __name__ == "__main__":
    unittest.main()
