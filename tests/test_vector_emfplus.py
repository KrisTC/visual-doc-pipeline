"""Tests for EMF+ text translation inside EMF graphics."""

from __future__ import annotations

import struct
import unittest
from collections.abc import Callable
from unittest.mock import patch

from pipeline.text_replacement import TextReplacementProvider
from pipeline.vector_text import analyse_vector_text, emf
from pipeline.vector_text.common import VectorDocument, VectorReplacementResult
from test_vector_text_replacer import (
    _emf_exttextout_record,
    _emf_font_record,
    _emf_is_structurally_valid,
    _emf_record_types,
    _emf_select_object_record,
    _emf_with_stretchdibits_image,
    _LongReplacementProvider,
)

_EMR_COMMENT = 70
_PLUS_HEADER = 0x4001
_PLUS_OBJECT = 0x4008
_PLUS_DRAW_STRING = 0x401C
_PLUS_DRAW_DRIVER_STRING = 0x4036
_PLUS_VERSION = 0xDBC01002
_UNIT_PIXEL = 2
_UNIT_POINT = 3
_CMAP_LOOKUP = 1
_VERTICAL = 2
_REALIZED_ADVANCE = 4
_LONG_TEXT = "A considerably longer heading"


def _pad4(data: bytes) -> bytes:
    return data + b"\0" * ((-len(data)) % 4)


def _plus_record(record_type: int, flags: int, data: bytes) -> bytes:
    data = _pad4(data)
    return struct.pack("<HHII", record_type, flags, 12 + len(data), len(data)) + data


def _plus_header() -> bytes:
    return _plus_record(_PLUS_HEADER, 0x01, struct.pack("<IIII", _PLUS_VERSION, 1, 96, 96))


def _plus_font(object_id: int, *, em_size: float = 20.0, unit: int = _UNIT_PIXEL, family: str = "Arial") -> bytes:
    name = family.encode("utf-16-le")
    data = struct.pack("<IfIIII", _PLUS_VERSION, em_size, unit, 0, 0, len(family)) + name
    return _plus_record(_PLUS_OBJECT, 0x0600 | object_id, data)


def _plus_draw_string(font_id: int, text: str, *, width: float = 100.0, height: float = 30.0) -> bytes:
    data = struct.pack("<III", 0, 0, len(text)) + struct.pack("<ffff", 10.0, 10.0, width, height)
    return _plus_record(_PLUS_DRAW_STRING, font_id, data + text.encode("utf-16-le"))


def _plus_driver_string(
    font_id: int,
    text: str,
    *,
    options: int = _CMAP_LOOKUP,
    positions: tuple[tuple[float, float], ...] | None = None,
) -> bytes:
    if positions is None:
        positions = tuple((10.0 + 12.0 * index, 30.0) for index in range(len(text)))
    data = struct.pack("<IIII", 0, options, 0, len(text)) + _pad4(text.encode("utf-16-le"))
    for x, y in positions:
        data += struct.pack("<ff", x, y)
    return _plus_record(_PLUS_DRAW_DRIVER_STRING, font_id, data)


def _comment(plus_records: bytes) -> bytes:
    return struct.pack("<III", _EMR_COMMENT, 16 + len(plus_records), 4 + len(plus_records)) + b"EMF+" + plus_records


def _emf_from_records(*records: bytes) -> bytes:
    header = bytearray(88)
    struct.pack_into("<II", header, 0, 1, len(header))
    struct.pack_into("<iiii", header, 8, 0, -100, 200, 100)
    eof = struct.pack("<IIIII", 14, 20, 0, 0, 0)
    result = bytearray(header + b"".join(records) + eof)
    struct.pack_into("<I", result, 48, len(result))
    struct.pack_into("<I", result, 52, len(records) + 2)
    return bytes(result)


def _emf_records(data: bytes) -> list[bytes]:
    records = []
    offset = 0
    while offset < len(data):
        size = struct.unpack_from("<I", data, offset + 4)[0]
        records.append(data[offset : offset + size])
        offset += size
    return records


def _plus_records(data: bytes) -> list[tuple[int, int, bytes]]:
    """Every EMF+ record of every EMF+ comment, checking each comment's declared sizes."""
    found = []
    for record in _emf_records(data):
        if struct.unpack_from("<I", record, 0)[0] != _EMR_COMMENT or record[12:16] != b"EMF+":
            continue
        end = 12 + struct.unpack_from("<I", record, 8)[0]
        if end != len(record):
            raise AssertionError("EMF+ comment data size does not match its record size.")
        offset = 16
        while offset < end:
            record_type, flags, size, data_size = struct.unpack_from("<HHII", record, offset)
            if size < 12 or offset + size > end or data_size != size - 12:
                raise AssertionError("Invalid EMF+ record.")
            found.append((record_type, flags, record[offset + 12 : offset + size]))
            offset += size
        if offset != end:
            raise AssertionError("EMF+ records do not fill their comment.")
    return found


def _draw_string_text(data: bytes) -> str:
    length = struct.unpack_from("<I", data, 8)[0]
    return data[28 : 28 + 2 * length].decode("utf-16-le")


def _driver_string_parts(data: bytes) -> tuple[str, list[tuple[float, float]]]:
    options, _has_matrix, count = struct.unpack_from("<III", data, 4)
    text = data[16 : 16 + 2 * count].decode("utf-16-le")
    positions_offset = 16 + (-(-2 * count // 4) * 4)
    position_count = (len(data) - positions_offset) // 8
    return text, [struct.unpack_from("<ff", data, positions_offset + 8 * index) for index in range(position_count)]


def _font_objects(data: bytes) -> dict[int, tuple[float, bytes]]:
    fonts = {}
    for record_type, flags, body in _plus_records(data):
        if record_type == _PLUS_OBJECT and (flags >> 8) & 0x7F == 6:
            fonts[flags & 0xFF] = (struct.unpack_from("<f", body, 4)[0], body)
    return fonts


def _apply(
    data: bytes,
    replace_text: Callable[[str], str],
    *,
    layout: str = "preserve-source-formatting",
    provider: TextReplacementProvider | None = None,
) -> tuple[VectorDocument, VectorReplacementResult]:
    document = analyse_vector_text(
        data, ".emf", "en", "en", document_text_layout=layout
    )
    return document, document.apply(replace_text, provider, None)


class EmfPlusDirectReplacementTests(unittest.TestCase):
    # Verifies FR-2026-10-22-10: DrawString text is replaced and the EMF+ stream stays valid.
    def test_draw_string_text_is_replaced_and_sizes_stay_consistent(self) -> None:
        source = _emf_from_records(_comment(_plus_header() + _plus_font(0) + _plus_draw_string(0, "Hello")))

        _document, result = _apply(source, lambda text: text.upper() + "!")

        self.assertEqual(1, result.replaced_text_items)
        self.assertTrue(result.has_editable_text)
        self.assertTrue(_emf_is_structurally_valid(result.data))
        draw = [body for record_type, _flags, body in _plus_records(result.data) if record_type == _PLUS_DRAW_STRING]
        self.assertEqual(["HELLO!"], [_draw_string_text(body) for body in draw])

    # Verifies FR-2026-10-22-10: texts() lists the text so a batch can translate it first.
    def test_texts_lists_exactly_what_apply_requests(self) -> None:
        source = _emf_from_records(
            _emf_font_record("Arial"),
            _emf_select_object_record(1),
            _emf_exttextout_record("Plain", 0, 0, 40, 20),
            _comment(
                _plus_header()
                + _plus_font(0)
                + _plus_draw_string(0, "Plus")
                + _plus_driver_string(0, "Driver")
            ),
        )
        requested: list[str] = []

        def record(text: str) -> str:
            requested.append(text)
            return text

        document, _result = _apply(source, record)

        self.assertEqual(["Plain", "Plus", "Driver"], list(document.texts()))
        self.assertEqual(list(document.texts()), requested)

    # Verifies FR-2026-10-22-10: a comment without text records is kept byte for byte.
    def test_comment_without_text_is_unchanged(self) -> None:
        source = _emf_from_records(_comment(_plus_header() + _plus_font(0)), _emf_exttextout_record("A", 0, 0, 40, 20))

        document, result = _apply(source, lambda text: text.lower())

        self.assertEqual(("A",), document.texts())
        self.assertEqual(_emf_records(source)[1], _emf_records(result.data)[1])

    # Verifies FR-2026-10-22-10: a CmapLookup driver string gets one position per new character.
    def test_driver_string_positions_are_regenerated_for_the_new_text(self) -> None:
        source = _emf_from_records(_comment(_plus_header() + _plus_font(0) + _plus_driver_string(0, "AB")))

        _document, result = _apply(source, lambda text: "WXYZ")

        body = next(body for record_type, _f, body in _plus_records(result.data) if record_type == _PLUS_DRAW_DRIVER_STRING)
        text, positions = _driver_string_parts(body)
        self.assertEqual("WXYZ", text)
        self.assertEqual(4, len(positions))
        self.assertEqual((10.0, 30.0), positions[0])
        self.assertEqual(sorted(position[0] for position in positions), [position[0] for position in positions])
        self.assertGreater(positions[3][0], positions[0][0])

    # Verifies FR-2026-10-22-10: a single-position driver string keeps its one position.
    def test_single_position_driver_string_keeps_its_position(self) -> None:
        source = _emf_from_records(
            _comment(
                _plus_header()
                + _plus_font(0)
                + _plus_driver_string(0, "AB", options=_CMAP_LOOKUP | _REALIZED_ADVANCE, positions=((7.0, 9.0),))
            )
        )

        _document, result = _apply(source, lambda text: "WXYZ")

        body = next(body for record_type, _f, body in _plus_records(result.data) if record_type == _PLUS_DRAW_DRIVER_STRING)
        self.assertEqual(("WXYZ", [(7.0, 9.0)]), _driver_string_parts(body))

    # Verifies FR-2026-10-22-10: a single-position driver string needs no font object.
    def test_single_position_driver_string_without_a_font_is_replaced(self) -> None:
        source = _emf_from_records(
            _comment(
                _plus_header()
                + _plus_driver_string(5, "AB", options=_CMAP_LOOKUP | _REALIZED_ADVANCE, positions=((7.0, 9.0),))
            )
        )

        _document, result = _apply(source, lambda text: "WXYZ")

        self.assertEqual(1, result.replaced_text_items)
        self.assertEqual((), result.diagnostics)

    # Verifies FR-2026-10-22-10: a driver string that cannot be repositioned is kept and reported.
    def test_unsupported_driver_strings_are_kept_and_reported(self) -> None:
        cases = {
            "emfplus_driver_string_glyph_indices": (_plus_font(0), _plus_driver_string(0, "AB", options=0)),
            "emfplus_driver_string_vertical": (
                _plus_font(0),
                _plus_driver_string(0, "AB", options=_CMAP_LOOKUP | _VERTICAL),
            ),
            "emfplus_driver_string_font_unavailable": (_plus_font(0, unit=_UNIT_POINT), _plus_driver_string(0, "AB")),
        }
        for reason, (font, draw) in cases.items():
            with self.subTest(reason=reason):
                source = _emf_from_records(_comment(_plus_header() + font + draw))

                document, result = _apply(source, lambda text: "WXYZ")

                self.assertEqual(source, result.data)
                self.assertEqual(0, result.replaced_text_items)
                self.assertEqual([reason], [item["reason_code"] for item in result.diagnostics])
                self.assertEqual("unsupported", result.diagnostics[0]["kind"])
                self.assertEqual("emf", result.diagnostics[0]["vector_format"])

    # Verifies FR-2026-10-22-10: a replacement that needs surrogate pairs is kept unchanged and reported.
    def test_unencodable_driver_string_replacement_is_kept_and_reported(self) -> None:
        source = _emf_from_records(_comment(_plus_header() + _plus_font(0) + _plus_driver_string(0, "AB")))

        _document, result = _apply(source, lambda text: "\U0001F600")

        self.assertEqual(source, result.data)
        self.assertEqual(
            ["emfplus_driver_string_unencodable"], [item["reason_code"] for item in result.diagnostics]
        )

    # Verifies FR-2026-10-22-10: a malformed EMF+ comment is kept and reported without stopping the graphic.
    def test_malformed_comment_is_kept_and_reported(self) -> None:
        broken = _comment(_plus_header() + struct.pack("<HHII", _PLUS_DRAW_STRING, 0, 400, 388))
        source = _emf_from_records(broken, _emf_exttextout_record("Plain", 0, 0, 40, 20))

        document, result = _apply(source, lambda text: text.upper())

        self.assertEqual(("Plain",), document.texts())
        self.assertEqual(1, result.replaced_text_items)
        self.assertEqual(
            ["emfplus_comment_malformed"], [item["reason_code"] for item in result.diagnostics]
        )
        self.assertEqual(_emf_records(source)[1], _emf_records(result.data)[1])

    # Verifies FR-2026-10-22-10: images in an EMF are decoded once and only when requested.
    def test_images_are_decoded_lazily_and_once(self) -> None:
        source = _emf_with_stretchdibits_image()
        with patch.object(emf, "_emf_stretchdibits_image", wraps=emf._emf_stretchdibits_image) as decode:
            untouched = analyse_vector_text(source, ".emf", "en", "en")
            untouched.apply(lambda text: text, None, None)
            self.assertEqual(0, decode.call_count)

            document = analyse_vector_text(source, ".emf", "en", "en")
            self.assertEqual(1, len(document.images()))
            self.assertEqual(1, len(document.images()))
            document.apply(lambda text: text, None, lambda index, image: 0)
            self.assertEqual(1, decode.call_count)


class EmfPlusFittedLayoutTests(unittest.TestCase):
    def _fitted(
        self, source: bytes, layout: str = "preserve-basic-layout"
    ) -> tuple[VectorDocument, VectorReplacementResult]:
        return _apply(
            source, lambda text: _LONG_TEXT, layout=layout, provider=_LongReplacementProvider()
        )

    # Verifies FR-2026-10-22-10: a fitted DrawString gets a smaller copy of its font under an unused object id.
    def test_fitted_draw_string_uses_a_new_scaled_font_object(self) -> None:
        source = _emf_from_records(_comment(_plus_header() + _plus_font(0) + _plus_draw_string(0, "Old")))

        _document, result = self._fitted(source)

        fonts = _font_objects(result.data)
        self.assertEqual({0, 1}, set(fonts))
        self.assertEqual(_font_objects(source)[0], fonts[0])
        self.assertLess(fonts[1][0], 20.0)
        records = _plus_records(result.data)
        types = [record_type for record_type, _f, _b in records]
        self.assertEqual([_PLUS_HEADER, _PLUS_OBJECT, _PLUS_OBJECT, _PLUS_DRAW_STRING], types)
        draw_flags = records[-1][1]
        self.assertEqual(1, draw_flags & 0xFF)
        self.assertEqual(_LONG_TEXT, _draw_string_text(records[-1][2]))
        self.assertTrue(_emf_is_structurally_valid(result.data))
        self.assertEqual((), result.diagnostics)

    # Verifies FR-2026-10-22-10: records with the same font and scale share one new font object.
    def test_repeated_sizes_share_one_scaled_font_object(self) -> None:
        source = _emf_from_records(
            _comment(
                _plus_header()
                + _plus_font(0)
                + _plus_draw_string(0, "Old")
                + _plus_draw_string(0, "Old")
            )
        )

        _document, result = self._fitted(source)

        self.assertEqual({0, 1}, set(_font_objects(result.data)))
        self.assertEqual(2, result.replaced_text_items)

    # Verifies FR-2026-10-22-10: fitted driver strings are rescaled and repositioned.
    def test_fitted_driver_string_is_scaled_and_repositioned(self) -> None:
        source = _emf_from_records(_comment(_plus_header() + _plus_font(0) + _plus_driver_string(0, "AB")))

        _document, result = self._fitted(source, "preserve-basic-layout-source-font")

        fonts = _font_objects(result.data)
        self.assertEqual({0, 1}, set(fonts))
        draw = next(r for r in _plus_records(result.data) if r[0] == _PLUS_DRAW_DRIVER_STRING)
        text, positions = _driver_string_parts(draw[2])
        self.assertEqual(_LONG_TEXT, text)
        self.assertEqual(len(_LONG_TEXT), len(positions))
        self.assertEqual(1, draw[1] & 0xFF)
        last_advance_span = positions[-1][0] - positions[0][0]
        self.assertLess(last_advance_span, 10.0 + 12.0 * 40)

    # Verifies FR-2026-10-22-10: an unusable font only costs the fit, and the fallback is reported.
    def test_font_that_cannot_be_measured_falls_back_to_direct_replacement(self) -> None:
        cases = {
            "emfplus_fitted_layout_font_unavailable": _plus_header() + _plus_draw_string(0, "Old"),
            "emfplus_fitted_layout_font_unit_unsupported": (
                _plus_header() + _plus_font(0, unit=_UNIT_POINT) + _plus_draw_string(0, "Old")
            ),
        }
        for reason, plus in cases.items():
            with self.subTest(reason=reason):
                source = _emf_from_records(_comment(plus))

                _document, result = self._fitted(source)

                self.assertEqual(1, result.replaced_text_items)
                draw = next(r for r in _plus_records(result.data) if r[0] == _PLUS_DRAW_STRING)
                self.assertEqual(_LONG_TEXT, _draw_string_text(draw[2]))
                self.assertEqual([reason], [item["reason_code"] for item in result.diagnostics])
                self.assertEqual("layout_fallback", result.diagnostics[0]["kind"])
                self.assertEqual("Old", result.diagnostics[0]["source_text"])

    # Verifies FR-2026-10-22-10: a source extent that cannot be measured falls back and is reported.
    def test_draw_string_without_a_layout_extent_falls_back(self) -> None:
        source = _emf_from_records(
            _comment(_plus_header() + _plus_font(0) + _plus_draw_string(0, "Old", width=0.0, height=0.0))
        )

        _document, result = self._fitted(source)

        self.assertEqual(
            ["emfplus_fitted_layout_geometry_unavailable"],
            [item["reason_code"] for item in result.diagnostics],
        )

    # Verifies FR-2026-10-22-10: a full object table falls back to direct replacement and is reported.
    def test_full_object_table_falls_back_to_direct_replacement(self) -> None:
        fonts = b"".join(_plus_font(object_id) for object_id in range(64))
        source = _emf_from_records(_comment(_plus_header() + fonts + _plus_draw_string(0, "Old")))

        _document, result = self._fitted(source)

        self.assertEqual(
            ["emfplus_fitted_layout_object_id_unavailable"],
            [item["reason_code"] for item in result.diagnostics],
        )
        self.assertEqual(64, len(_font_objects(result.data)))
        draw = next(r for r in _plus_records(result.data) if r[0] == _PLUS_DRAW_STRING)
        self.assertEqual(_LONG_TEXT, _draw_string_text(draw[2]))

    # Verifies FR-2026-10-22-10: the fitted plain-text font records follow the EMF+ header comment.
    def test_gdi_scaled_font_records_follow_the_emfplus_header_comment(self) -> None:
        header_comment = _comment(_plus_header())
        with_plus = _emf_from_records(
            header_comment,
            _emf_font_record("Noto Sans JP"),
            _emf_select_object_record(1),
            _emf_exttextout_record("Old", 0, 0, 40, 20),
        )
        without_plus = _emf_from_records(
            _emf_font_record("Noto Sans JP"),
            _emf_select_object_record(1),
            _emf_exttextout_record("Old", 0, 0, 40, 20),
        )

        _document, fitted_with_plus = self._fitted(with_plus, "preserve-basic-layout-source-font")
        _document, fitted_without_plus = self._fitted(without_plus, "preserve-basic-layout-source-font")

        with_plus_types = _emf_record_types(fitted_with_plus.data)
        without_plus_types = _emf_record_types(fitted_without_plus.data)
        self.assertEqual(_EMR_COMMENT, with_plus_types[1])
        self.assertEqual(82, with_plus_types[2])
        self.assertEqual(82, without_plus_types[1])
        self.assertEqual(without_plus_types[1:], with_plus_types[2:])
        self.assertTrue(_emf_is_structurally_valid(fitted_with_plus.data))
        self.assertEqual(
            _emf_records(fitted_with_plus.data)[1],
            _emf_records(with_plus)[1],
        )


if __name__ == "__main__":
    unittest.main()
