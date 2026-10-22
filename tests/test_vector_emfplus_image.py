"""Tests for translating EMF+ Image objects (bitmaps and nested metafiles) in an EMF."""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
import os
import struct
import unittest

from PIL import Image

from pipeline.folder_replacement.planning import NESTED_DOCUMENT_MAX_DEPTH, plan_and_apply
from pipeline.folder_replacement.vector import apply_vector, plan_vector
from pipeline.text_replacement import TextUnit, TranslationEngine
from pipeline.vector_text import analyse_vector_text
from pipeline.vector_text.common import VectorReplacementResult
from pipeline.vector_text.emfplus import parse_comment
from pipeline.vector_text.emfplus_image import (
    MAX_RECORD_DATA,
    ImageObject,
    decode_bitmap,
    find_image_objects,
    image_object_comments,
)
from test_batch_engine import _RecordingProvider, _typeface
from folder_replacement_test_support import _EmptyOcrProvider
from test_vector_emfplus import (
    _PLUS_DRAW_STRING,
    _PLUS_OBJECT,
    _comment,
    _draw_string_text,
    _emf_from_records,
    _emf_records,
    _plus_draw_string,
    _plus_font,
    _plus_header,
    _plus_records,
)
from test_vector_text_replacer import _emf_is_structurally_valid, _wmf_with_text

_VERSION = 0xDBC01002
_IMAGE_FLAGS = 5 << 8
_ARGB = 0x0026200A
_RGB24 = 0x00021808
_RGB32 = 0x00022009
_RED = (200, 10, 20)


def _png(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _bitmap_data(
    width: int, height: int, pixels: bytes, *, compressed: bool, pixel_format: int = _ARGB, stride: int = 0
) -> bytes:
    return (
        struct.pack("<II", _VERSION, 1)
        + struct.pack("<iiiII", width, height, stride, pixel_format, int(compressed))
        + pixels
    )


def _png_bitmap_data(image: Image.Image) -> bytes:
    return _bitmap_data(image.width, image.height, _png(image), compressed=True, stride=0)


def _metafile_data(metafile: bytes, metafile_type: int = 4) -> bytes:
    return struct.pack("<II", _VERSION, 2) + struct.pack("<II", metafile_type, len(metafile)) + metafile


def _emf_with_objects(*object_comments: bytes, trailing: bytes = b"") -> bytes:
    """An EMF+ dual-less EMF: header, the given Image object comments, then ``trailing``."""
    records = [_comment(_plus_header()), *object_comments]
    if trailing:
        records.append(trailing)
    return _emf_from_records(*records)


def _emf_with_image(data: bytes, object_id: int = 0) -> bytes:
    return _emf_with_objects(*image_object_comments(object_id, data))


def _nested_emf(text: str) -> bytes:
    data = bytearray(_emf_from_records(_comment(_plus_header() + _plus_font(0) + _plus_draw_string(0, text))))
    data[40:44] = b" EMF"
    return bytes(data)


def _image_objects(data: bytes) -> list[ImageObject]:
    comments = []
    for index, record in enumerate(_emf_records(data)):
        if struct.unpack_from("<I", record, 0)[0] != 70 or record[12:16] != b"EMF+":
            continue
        comments.append((index, parse_comment(record, {}, set())))
    objects, unsupported = find_image_objects(comments)
    assert not unsupported, unsupported
    return objects


def _paint(image: Image.Image) -> int:
    image.paste(_RED, (0, 0, image.width, image.height))
    return 1


def _apply(
    data: bytes,
    *,
    replace_image: Callable[[int, Image.Image], int] | None = None,
    replace_nested: Callable[[int], VectorReplacementResult | None] | None = None,
) -> VectorReplacementResult:
    document = analyse_vector_text(data, ".emf", "en", "en")
    document.images()
    return document.apply(lambda text: text.upper(), None, replace_image, replace_nested)


def _decoded_png(obj: ImageObject) -> Image.Image:
    return Image.open(BytesIO(obj.payload))


class EmfPlusBitmapObjectTests(unittest.TestCase):
    # Verifies FR-2026-10-22-14: a PNG bitmap object is listed and re-embedded in place.
    def test_a_png_bitmap_object_is_translated_in_place(self) -> None:
        source = _emf_with_image(_png_bitmap_data(Image.new("RGB", (6, 4), "white")), object_id=3)

        result = _apply(source, replace_image=lambda _index, image: _paint(image))

        self.assertTrue(_emf_is_structurally_valid(result.data))
        self.assertEqual(1, result.replaced_image_regions)
        self.assertTrue(result.has_embedded_bitmaps)
        [obj] = _image_objects(result.data)
        self.assertEqual(3, obj.object_id)
        painted = _decoded_png(obj).convert("RGB")
        self.assertEqual((6, 4), painted.size)
        self.assertEqual(_RED, painted.getpixel((0, 0)))

    # Verifies FR-2026-10-22-14: raw pixel formats decode and keep their size and alpha.
    def test_raw_bitmaps_decode_and_are_written_back_as_png_with_alpha(self) -> None:
        cases = {
            _RGB24: (bytes([30, 20, 10]) * 2, 3, "RGB"),
            _RGB32: (bytes([30, 20, 10, 0]) * 2, 4, "RGB"),
            _ARGB: (bytes([30, 20, 10, 77]) * 2, 4, "RGBA"),
        }
        for pixel_format, (pixels, bytes_per_pixel, mode) in cases.items():
            with self.subTest(pixel_format=hex(pixel_format)):
                source = _emf_with_image(
                    _bitmap_data(2, 1, pixels, compressed=False, pixel_format=pixel_format, stride=2 * bytes_per_pixel)
                )
                [obj] = _image_objects(source)
                decoded = decode_bitmap(obj)
                self.assertEqual(mode, decoded.mode)
                self.assertEqual((10, 20, 30), decoded.convert("RGB").getpixel((0, 0)))
                if mode == "RGBA":
                    self.assertEqual(77, decoded.getpixel((0, 0))[3])  # type: ignore[index]

                result = _apply(source, replace_image=lambda _index, image: 1)

                [rewritten] = _image_objects(result.data)
                self.assertTrue(rewritten.is_compressed)
                stored = _decoded_png(rewritten)
                self.assertEqual((2, 1), stored.size)
                self.assertEqual(mode, stored.mode)

    # Verifies FR-2026-10-22-14: a JPEG bitmap object is decoded and listed.
    def test_a_jpeg_bitmap_object_is_listed(self) -> None:
        output = BytesIO()
        Image.new("RGB", (8, 8), "white").save(output, format="JPEG")
        source = _emf_with_image(_bitmap_data(8, 8, output.getvalue(), compressed=True))

        document = analyse_vector_text(source, ".emf", "en", "en")

        self.assertEqual([(8, 8)], [image.size for image in document.images()])

    # Verifies FR-2026-10-22-14: an image with no replaced regions leaves the EMF byte for byte.
    def test_an_unchanged_bitmap_leaves_the_emf_identical(self) -> None:
        source = _emf_with_image(_png_bitmap_data(Image.new("RGB", (6, 4), "white")))

        result = _apply(source, replace_image=lambda _index, _image: 0)

        self.assertEqual(source, result.data)

    # Verifies FR-2026-10-22-14: GDI DIB images are numbered first, then the EMF+ bitmaps.
    def test_emf_plus_bitmaps_follow_the_gdi_images_in_index_order(self) -> None:
        source = _emf_with_image(_png_bitmap_data(Image.new("RGB", (6, 4), "white")))
        document = analyse_vector_text(source, ".emf", "en", "en")
        seen: list[int] = []

        def record(index: int, _image: Image.Image) -> int:
            seen.append(index)
            return 0

        document.images()
        document.apply(lambda text: text, None, record)

        self.assertEqual([0], seen)

    # Verifies FR-2026-10-22-14: a large object is rewritten with valid chunk sizes.
    def test_a_chunked_bitmap_is_reassembled_and_rewritten_with_valid_chunks(self) -> None:
        noise = Image.frombytes("RGB", (200, 200), os.urandom(200 * 200 * 3))
        source = _emf_with_image(_png_bitmap_data(noise))
        self.assertGreater(len(_emf_records(source)), 3)

        result = _apply(source, replace_image=lambda _index, image: _paint(image))

        self.assertTrue(_emf_is_structurally_valid(result.data))
        [obj] = _image_objects(result.data)
        self.assertEqual(_RED, _decoded_png(obj).convert("RGB").getpixel((0, 0)))
        [obj_before] = _image_objects(source)
        for record_type, flags, body in _plus_records(source):
            if record_type == _PLUS_OBJECT and flags & 0x8000:
                self.assertEqual(len(obj_before.data), struct.unpack_from("<I", body, 0)[0])
                self.assertLessEqual(len(body), MAX_RECORD_DATA)

    # Verifies FR-2026-10-22-14: records sharing a comment with an object's last chunk survive.
    def test_text_after_the_last_chunk_in_the_same_comment_is_still_translated(self) -> None:
        noise = Image.frombytes("RGB", (200, 200), os.urandom(200 * 200 * 3))
        comments = image_object_comments(0, _png_bitmap_data(noise))
        last = comments[-1]
        tail = _plus_font(1) + _plus_draw_string(1, "after")
        # Merge the last chunk's records with a later text record in one comment.
        merged = _comment(last[16:] + tail)
        source = _emf_from_records(_comment(_plus_header()), *comments[:-1], merged)

        result = _apply(source, replace_image=lambda _index, image: _paint(image))

        self.assertTrue(_emf_is_structurally_valid(result.data))
        texts = [
            _draw_string_text(body)
            for record_type, _flags, body in _plus_records(result.data)
            if record_type == _PLUS_DRAW_STRING
        ]
        self.assertEqual(["AFTER"], texts)
        [obj] = _image_objects(result.data)
        self.assertEqual(_RED, _decoded_png(obj).convert("RGB").getpixel((0, 0)))


class EmfPlusMetafileObjectTests(unittest.TestCase):
    # Verifies FR-2026-10-22-14: the text of a nested EMF+-only metafile is replaced.
    def test_a_nested_emf_plus_metafile_is_translated_and_resized(self) -> None:
        nested = _nested_emf("inner")
        source = _emf_with_image(_metafile_data(nested))
        document = analyse_vector_text(source, ".emf", "en", "en")
        [graphic] = document.nested()
        self.assertEqual(".emf", graphic.extension)
        inner = analyse_vector_text(graphic.data, ".emf", "en", "en")

        result = document.apply(
            lambda text: text, None, None, lambda _index: inner.apply(lambda text: text + " longer", None, None)
        )

        self.assertEqual(1, result.replaced_text_items)
        self.assertTrue(result.has_editable_text)
        self.assertTrue(_emf_is_structurally_valid(result.data))
        [obj] = _image_objects(result.data)
        self.assertGreater(len(obj.payload), len(nested))
        self.assertEqual(len(obj.payload), struct.unpack_from("<I", obj.data, 12)[0])
        self.assertTrue(_emf_is_structurally_valid(obj.payload))
        texts = [
            _draw_string_text(body)
            for record_type, _flags, body in _plus_records(obj.payload)
            if record_type == _PLUS_DRAW_STRING
        ]
        self.assertEqual(["inner longer"], texts)

    # Verifies FR-2026-10-22-14: a nested metafile left unchanged keeps the EMF identical.
    def test_an_unchanged_nested_metafile_leaves_the_emf_identical(self) -> None:
        textless = bytearray(_emf_from_records(_comment(_plus_header())))
        textless[40:44] = b" EMF"
        source = _emf_with_image(_metafile_data(bytes(textless)))
        inner = analyse_vector_text(bytes(textless), ".emf", "en", "en")

        result = analyse_vector_text(source, ".emf", "en", "en").apply(
            lambda text: text, None, None, lambda _index: inner.apply(lambda text: text, None, None)
        )

        self.assertEqual(source, result.data)

    # Verifies FR-2026-10-22-14: a metafile type with a WMF payload is handled as WMF.
    def test_a_wmf_metafile_object_reports_the_wmf_extension(self) -> None:
        source = _emf_with_image(_metafile_data(_wmf_with_text("inner"), metafile_type=1))

        [graphic] = analyse_vector_text(source, ".emf", "en", "en").nested()

        self.assertEqual(".wmf", graphic.extension)


class EmfPlusImagePlanTests(unittest.TestCase):
    # Verifies FR-2026-10-22-14: nested graphics get path-style units after the parent's.
    def test_nested_graphics_are_planned_as_child_units(self) -> None:
        source = _emf_with_image(_metafile_data(_nested_emf("inner")))

        plan = plan_vector(source, ".emf", _EmptyOcrProvider(), "en", "en")

        self.assertEqual(
            [TextUnit("vector", ()), TextUnit("vector/emfplus-object-1", ("inner",))],
            list(plan.units()),
        )

    # Verifies FR-2026-10-22-14: apply follows the plan with no plan misses.
    def test_apply_replaces_nested_text_without_plan_misses(self) -> None:
        source = _emf_with_image(_metafile_data(_nested_emf("inner")))
        plan = plan_vector(source, ".emf", _EmptyOcrProvider(), "en", "en")
        engine = TranslationEngine(_RecordingProvider(), "en", "en")

        result = plan_and_apply(plan, engine, lambda translate: apply_vector(plan, translate, _typeface()))

        self.assertEqual(0, engine.plan_misses)
        self.assertEqual(1, result.replaced_text_items)
        [obj] = _image_objects(result.data)
        texts = [
            _draw_string_text(body)
            for record_type, _flags, body in _plus_records(obj.payload)
            if record_type == _PLUS_DRAW_STRING
        ]
        self.assertEqual(["T:inner"], texts)

    # Verifies FR-2026-10-22-14: a nested bitmap is planned and rendered as an image unit.
    def test_bitmap_objects_are_planned_as_image_units(self) -> None:
        source = _emf_with_image(_png_bitmap_data(Image.new("RGB", (6, 4), "white")))

        plan = plan_vector(source, ".emf", _EmptyOcrProvider(), "en", "en")

        self.assertEqual(["vector", "vector/image-1"], [unit.unit_id for unit in plan.units()])

    # Verifies FR-2026-10-22-14: nesting beyond the depth limit is skipped and reported.
    def test_nested_metafiles_beyond_the_depth_limit_are_left_unchanged(self) -> None:
        source = _emf_with_image(_metafile_data(_nested_emf("inner")))
        diagnostics: list[dict[str, object]] = []

        plan = plan_vector(
            source, ".emf", _EmptyOcrProvider(), "en", "en",
            depth=NESTED_DOCUMENT_MAX_DEPTH, package_part="word/media/deep.emf",
            diagnostics=diagnostics,
        )

        self.assertEqual([None], plan.nested)
        self.assertEqual(["nested_document_depth_limit_exceeded"], [d["reason_code"] for d in diagnostics])


class EmfPlusUnsupportedImageTests(unittest.TestCase):
    # Verifies FR-2026-10-22-14: unsupported objects stay unchanged and are reported.
    def test_unsupported_objects_are_kept_and_reported(self) -> None:
        cases = {
            "emfplus_image_object_malformed": struct.pack("<II", _VERSION, 1) + b"\0" * 4,
            "emfplus_image_object_type_unsupported": struct.pack("<II", _VERSION, 9) + b"\0" * 8,
            "emfplus_image_object_format_unsupported": _bitmap_data(
                2, 2, bytes(16), compressed=False, pixel_format=0x00030101, stride=8
            ),
        }
        for reason, data in cases.items():
            with self.subTest(reason=reason):
                source = _emf_with_image(data)

                result = _apply(source, replace_image=lambda _index, image: _paint(image))

                self.assertEqual(source, result.data)
                reasons = [entry["reason_code"] for entry in result.diagnostics]
                self.assertEqual([reason], reasons)
                self.assertEqual("unsupported", result.diagnostics[0]["kind"])

    # Verifies FR-2026-10-22-14: chunks whose sizes contradict each other are unsupported.
    def test_chunks_with_a_mismatched_total_are_unsupported(self) -> None:
        noise = Image.frombytes("RGB", (200, 200), os.urandom(200 * 200 * 3))
        comments = image_object_comments(0, _png_bitmap_data(noise))
        record = bytearray(comments[1])
        # Corrupt the total-size prefix of the second chunk.
        struct.pack_into("<I", record, 16 + 12, 12345)
        source = _emf_from_records(_comment(_plus_header()), comments[0], bytes(record), *comments[2:])

        result = _apply(source, replace_image=lambda _index, image: _paint(image))

        self.assertEqual(source, result.data)
        self.assertEqual(
            ["emfplus_image_object_chunks_invalid"], [entry["reason_code"] for entry in result.diagnostics]
        )
