#!/usr/bin/env python3
"""Synthetic tests for direct editable-vector text replacement."""

from __future__ import annotations

from io import BytesIO
import base64
import struct
import unittest

from PIL import Image

from pipeline.vector_text import replace_vector_text
from pipeline.text_replacement import TextReplacementRequest, TextReplacementResult


def _mask(text: str) -> str:
    return "#" * len(text)


class VectorTextReplacerTests(unittest.TestCase):
    # Verifies FR-2026-08-04-07.
    def test_fits_svg_text_only_when_an_explicit_clip_rectangle_exists(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return TextReplacementResult("A substantially longer replacement", 1.0)

        result = replace_vector_text(
            b'''<svg xmlns="http://www.w3.org/2000/svg"><defs><clipPath id="box"><rect width="40" height="20"/></clipPath></defs><text clip-path="url(#box)" font-family="Source Sans" font-size="20">old</text><text font-size="20">free</text></svg>''',
            ".svg", _mask, "en", document_text_layout="preserve-basic-layout",
            replacement_provider=_Provider(), target_language="en",
        )

        self.assertIn(b"A substantially longer replacement", result.data)
        self.assertIn(b"Noto Sans JP", result.data)
        self.assertLess(float(result.data.split(b'font-size="')[1].split(b"px")[0]), 20.0)
        self.assertIn(b"####", result.data)

    # Verifies FR-2026-08-03-05.
    def test_replaces_svg_text_and_retains_vector_structure(self) -> None:
        result = replace_vector_text(
            b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/><text>Top<tspan>Inner</tspan>Tail</text></svg>',
            ".svg",
            _mask,
            "en",
        )

        self.assertTrue(result.has_editable_text)
        self.assertEqual(3, result.replaced_text_items)
        self.assertIn(b"<ns0:path", result.data)
        self.assertNotIn(b"Top", result.data)
        self.assertNotIn(b"Inner", result.data)
        self.assertNotIn(b"Tail", result.data)

    # Verifies FR-2026-08-03-11 and SR-2026-08-03-02.
    def test_replaces_svg_data_image_without_dereferencing_external_href(self) -> None:
        image = Image.new("RGB", (2, 1), "white")
        encoded = BytesIO(); image.save(encoded, format="PNG")
        source = (
            b'<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,'
            + base64.b64encode(encoded.getvalue())
            + b'"/><image href="https://example.invalid/image.png"/></svg>'
        )
        calls = 0

        def replace_image(embedded: Image.Image) -> int:
            nonlocal calls
            calls += 1
            embedded.paste("black", (0, 0, embedded.width, embedded.height))
            return 1

        result = replace_vector_text(source, ".svg", _mask, "en", replace_image)

        self.assertEqual(1, calls)
        self.assertEqual(1, result.replaced_image_regions)
        self.assertIn(b"https://example.invalid/image.png", result.data)

    # Verifies FR-2026-08-03-05.
    def test_reports_svg_without_editable_text(self) -> None:
        source = b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>'

        result = replace_vector_text(source, ".svg", _mask, "en")

        self.assertFalse(result.has_editable_text)
        self.assertEqual(0, result.replaced_text_items)
        self.assertEqual(source, result.data)

    # Verifies FR-2026-08-03-05.
    def test_replaces_unicode_emf_exttextout_record(self) -> None:
        source = _emf_with_text("Hello")

        result = replace_vector_text(source, ".emf", _mask, "en")

        self.assertTrue(result.has_editable_text)
        self.assertEqual(1, result.replaced_text_items)
        self.assertEqual("#####", _emf_text(result.data))
        self.assertEqual(len(result.data), struct.unpack_from("<I", result.data, 48)[0])

    # Verifies FR-2026-08-03-09.
    def test_replaces_embedded_emf_stretchdibits_image_in_memory(self) -> None:
        source = _emf_with_stretchdibits_image()
        processed_sizes: list[tuple[int, int]] = []

        def replace_image(image: Image.Image) -> int:
            processed_sizes.append(image.size)
            image.paste("black", (0, 0, image.width, image.height))
            return 1

        result = replace_vector_text(source, ".emf", _mask, "en", replace_image)

        self.assertEqual([(2, 1)], processed_sizes)
        self.assertTrue(result.has_embedded_bitmaps)
        self.assertEqual(1, result.replaced_image_regions)
        self.assertEqual((0, 0, 0), _emf_stretchdibits_pixel(result.data))
        self.assertEqual(len(result.data), struct.unpack_from("<I", result.data, 48)[0])
        self.assertEqual(14, struct.unpack_from("<I", result.data, len(result.data) - 20)[0])

    # Verifies FR-2026-08-03-05.
    def test_replaces_wmf_textout_record(self) -> None:
        source = _wmf_with_text("Hello")

        result = replace_vector_text(source, ".wmf", _mask, "en")

        self.assertTrue(result.has_editable_text)
        self.assertEqual(1, result.replaced_text_items)
        self.assertEqual(b"#####", _wmf_text(result.data))
        self.assertEqual(len(result.data) // 2, struct.unpack_from("<I", result.data, 6)[0])

    # Verifies FR-2026-08-03-12.
    def test_replaces_wmf_stretchdib_image_in_memory(self) -> None:
        source = _wmf_with_stretchdib_image()

        def replace_image(image: Image.Image) -> int:
            image.paste("black", (0, 0, image.width, image.height))
            return 1

        result = replace_vector_text(source, ".wmf", _mask, "en", replace_image)

        self.assertTrue(result.has_embedded_bitmaps)
        self.assertEqual(1, result.replaced_image_regions)
        self.assertEqual((0, 0, 0), _wmf_stretchdib_pixel(result.data))


def _emf_with_text(text: str) -> bytes:
    text_bytes = text.encode("utf-16-le")
    record = bytearray(76 + len(text_bytes))
    struct.pack_into("<II", record, 0, 84, len(record))
    struct.pack_into("<I", record, 44, len(text))
    struct.pack_into("<I", record, 48, 76)
    record[76:] = text_bytes
    record.extend(b"\0" * ((-len(record)) % 4))
    struct.pack_into("<I", record, 4, len(record))
    header = bytearray(88)
    struct.pack_into("<II", header, 0, 1, len(header))
    eof = struct.pack("<IIIII", 14, 20, 0, 0, 0)
    result = bytearray(header + record + eof)
    struct.pack_into("<I", result, 48, len(result))
    struct.pack_into("<I", result, 52, 3)
    return bytes(result)


def _emf_text(data: bytes) -> str:
    record_offset = struct.unpack_from("<I", data, 4)[0]
    string_length = struct.unpack_from("<I", data, record_offset + 44)[0]
    string_offset = struct.unpack_from("<I", data, record_offset + 48)[0]
    return data[
        record_offset + string_offset : record_offset + string_offset + (string_length * 2)
    ].decode("utf-16-le")


def _emf_with_stretchdibits_image() -> bytes:
    image = Image.new("RGB", (2, 1), "white")
    bitmap = BytesIO()
    image.save(bitmap, format="BMP")
    bitmap_data = bitmap.getvalue()
    pixel_offset = struct.unpack_from("<I", bitmap_data, 10)[0]
    bitmap_info = bitmap_data[14:pixel_offset]
    bitmap_bits = bitmap_data[pixel_offset:]
    record = bytearray(80)
    struct.pack_into("<II", record, 0, 81, 80 + len(bitmap_info) + len(bitmap_bits))
    struct.pack_into("<iiiiii", record, 24, 0, 0, 0, 0, 2, 1)
    struct.pack_into("<IIII", record, 48, 80, len(bitmap_info), 80 + len(bitmap_info), len(bitmap_bits))
    struct.pack_into("<ii", record, 72, 2, 1)
    record.extend(bitmap_info)
    record.extend(bitmap_bits)
    record.extend(b"\0" * ((-len(record)) % 4))
    struct.pack_into("<I", record, 4, len(record))
    header = bytearray(88)
    struct.pack_into("<II", header, 0, 1, len(header))
    eof = struct.pack("<IIIII", 14, 20, 0, 0, 0)
    result = bytearray(header + record + eof)
    struct.pack_into("<I", result, 48, len(result))
    struct.pack_into("<I", result, 52, 3)
    return bytes(result)


def _emf_stretchdibits_pixel(data: bytes) -> tuple[int, int, int]:
    record_offset = struct.unpack_from("<I", data, 4)[0]
    bitmap_info_offset, bitmap_info_size, bitmap_bits_offset, bitmap_bits_size = struct.unpack_from(
        "<IIII", data, record_offset + 48
    )
    bitmap_file = _bitmap_file_from_dib(
        data[record_offset + bitmap_info_offset : record_offset + bitmap_info_offset + bitmap_info_size],
        data[record_offset + bitmap_bits_offset : record_offset + bitmap_bits_offset + bitmap_bits_size],
    )
    with Image.open(BytesIO(bitmap_file)) as image:
        pixel = image.convert("RGB").getpixel((0, 0))
    if not isinstance(pixel, tuple) or len(pixel) != 3:
        raise AssertionError("Expected an RGB pixel.")
    return int(pixel[0]), int(pixel[1]), int(pixel[2])


def _bitmap_file_from_dib(bitmap_info: bytes, bitmap_bits: bytes) -> bytes:
    return (
        struct.pack(
            "<2sIHHI", b"BM", 14 + len(bitmap_info) + len(bitmap_bits), 0, 0, 14 + len(bitmap_info)
        )
        + bitmap_info
        + bitmap_bits
    )


def _wmf_with_text(text: str) -> bytes:
    text_bytes = text.encode("latin-1")
    record = bytearray(8)
    struct.pack_into("<H", record, 4, 0x0521)
    struct.pack_into("<H", record, 6, len(text_bytes))
    record.extend(text_bytes)
    if len(text_bytes) % 2:
        record.append(0)
    record.extend(struct.pack("<hh", 0, 0))
    struct.pack_into("<I", record, 0, len(record) // 2)
    eof = struct.pack("<IH", 3, 0)
    header = bytearray(struct.pack("<HHHIHIH", 1, 9, 0x0300, 0, 0, 0, 0))
    result = bytearray(header + record + eof)
    struct.pack_into("<I", result, 6, len(result) // 2)
    return bytes(result)


def _wmf_text(data: bytes) -> bytes:
    header_size = struct.unpack_from("<H", data, 2)[0] * 2
    string_length = struct.unpack_from("<H", data, header_size + 6)[0]
    return data[header_size + 8 : header_size + 8 + string_length]


def _wmf_with_stretchdib_image() -> bytes:
    image = Image.new("RGB", (2, 1), "white")
    bitmap = BytesIO(); image.save(bitmap, format="BMP")
    data = bitmap.getvalue(); offset = struct.unpack_from("<I", data, 10)[0]
    dib = data[14:]
    record = bytearray(28 + len(dib))
    struct.pack_into("<H", record, 4, 0x0F43)
    record[28:] = dib
    if len(record) % 2: record.append(0)
    struct.pack_into("<I", record, 0, len(record) // 2)
    eof = struct.pack("<IH", 3, 0)
    header = bytearray(struct.pack("<HHHIHIH", 1, 9, 0x0300, 0, 0, 0, 0))
    result = bytearray(header + record + eof)
    struct.pack_into("<I", result, 6, len(result) // 2)
    return bytes(result)


def _wmf_stretchdib_pixel(data: bytes) -> tuple[int, int, int]:
    offset = struct.unpack_from("<H", data, 2)[0] * 2
    dib = data[offset + 28 : -6]
    with Image.open(BytesIO(_bitmap_file_from_dib(dib[:40], dib[40:]))) as image:
        pixel = image.convert("RGB").getpixel((0, 0))
    if not isinstance(pixel, tuple) or len(pixel) != 3: raise AssertionError("Expected RGB pixel.")
    return int(pixel[0]), int(pixel[1]), int(pixel[2])


if __name__ == "__main__":
    unittest.main()
