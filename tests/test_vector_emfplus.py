"""Tests for EMF+ text translation inside EMF graphics."""

from __future__ import annotations

import struct
import unittest
from collections.abc import Callable
from unittest.mock import patch
from types import SimpleNamespace

from pipeline.folder_replacement.planning import LookupProvider
from pipeline.bounded_text_layout import noto_typefaces
from pipeline.text_replacement import (
    TextReplacementItem,
    TextReplacementProvider,
    TextReplacementRequest,
    TextReplacementResult,
    replace_each,
)
from pipeline.text_replacement.batching import TranslationEngine
from pipeline.vector_text import analyse_vector_text, emf
from pipeline.vector_text.common import VectorDocument, VectorReplacementResult
from pipeline.vector_text.emfplus import driver_string_with_text, parse_driver_string
from test_vector_text_replacer import (
    _emf_exttextout_record,
    _emf_font_record,
    _emf_is_structurally_valid,
    _emf_record_types,
    _emf_select_object_record,
    _emf_texts,
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


def _plus_solid_brush(object_id: int, color: int) -> bytes:
    return _plus_record(_PLUS_OBJECT, 0x0100 | object_id, struct.pack("<III", _PLUS_VERSION, 0, color))


def _plus_string_format(object_id: int) -> bytes:
    data = bytearray(60)
    struct.pack_into("<I", data, 0, _PLUS_VERSION)
    struct.pack_into("<f", data, 44, 1.0)
    return _plus_record(_PLUS_OBJECT, 0x0700 | object_id, bytes(data))


def _plus_draw_string(
    font_id: int, text: str, *, width: float = 100.0, height: float = 30.0,
    x: float = 10.0, y: float = 10.0, color: int | None = None, format_id: int = 0,
) -> bytes:
    data = struct.pack("<III", 0 if color is None else color, format_id, len(text)) + struct.pack(
        "<ffff", x, y, width, height,
    )
    return _plus_record(
        _PLUS_DRAW_STRING, font_id | (0x8000 if color is not None else 0),
        data + text.encode("utf-16-le"),
    )


def _plus_driver_string(
    font_id: int,
    text: str,
    *,
    options: int = _CMAP_LOOKUP,
    positions: tuple[tuple[float, float], ...] | None = None,
    color: int | None = None,
    brush_id: int = 0,
) -> bytes:
    if positions is None:
        positions = tuple((10.0 + 12.0 * index, 30.0) for index in range(len(text)))
    data = struct.pack("<IIII", brush_id if color is None else color, options, 0, len(text)) + text.encode("utf-16-le")
    for x, y in positions:
        data += struct.pack("<ff", x, y)
    return _plus_record(_PLUS_DRAW_DRIVER_STRING, font_id | (0x8000 if color is not None else 0), data)


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
    positions_offset = 16 + 2 * count
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

    # Verifies FR-2026-10-22-10: odd-length strings place positions and matrices before record padding.
    def test_driver_string_odd_length_positions_and_matrix(self) -> None:
        matrix = struct.pack("<ffffff", 1.0, 0.0, 0.0, 1.0, 3.0, 4.0)
        body = _pad4(
            struct.pack("<IIII", 0, _CMAP_LOOKUP, 1, 1)
            + "A".encode("utf-16-le") + struct.pack("<ff", 10.0, 30.0) + matrix
        )
        driver = parse_driver_string(body)
        self.assertIsNotNone(driver)
        assert driver is not None
        self.assertEqual(((10.0, 30.0),), driver.positions)
        self.assertEqual(matrix, driver.matrix)
        rewritten = parse_driver_string(_pad4(driver_string_with_text(driver, "XYZ", [4.0, 5.0, 6.0])))
        self.assertIsNotNone(rewritten)
        assert rewritten is not None
        self.assertEqual(((10.0, 30.0), (14.0, 30.0), (19.0, 30.0)), rewritten.positions)
        self.assertEqual(matrix, rewritten.matrix)

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

    # Verifies FR-2026-10-22-10 when a one-character source uses realized advances.
    def test_one_character_realized_advance_keeps_one_position(self) -> None:
        source = _emf_from_records(_comment(
            _plus_header() + _plus_font(0)
            + _plus_driver_string(0, "A", options=_CMAP_LOOKUP | _REALIZED_ADVANCE,
                                  positions=((7.0, 9.0),))
        ))
        _document, result = _apply(source, lambda text: "WXYZ")
        body = next(body for kind, _flags, body in _plus_records(result.data) if kind == _PLUS_DRAW_DRIVER_STRING)
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
    def setUp(self) -> None:
        for name, value in (
            ("source_line_typeface", noto_typefaces()["sans-serif"]),
            ("source_line_ascent", 18.0), ("source_line_height", 30.0),
        ):
            patcher = patch(f"pipeline.vector_text.emf.{name}", return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _fitted(
        self, source: bytes, layout: str = "preserve-basic-layout"
    ) -> tuple[VectorDocument, VectorReplacementResult]:
        return _apply(
            source, lambda text: _LONG_TEXT, layout=layout, provider=_LongReplacementProvider()
        )

    # Verifies FR-2026-10-29-01 and FR-2026-10-29-02 for adjacent EMF+ spans.
    def test_driver_line_fits_multiple_colours_together(self) -> None:
        class Provider:
            def __init__(self) -> None:
                self.requests: list[str] = []

            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                self.requests.extend(request.texts)
                return replace_each(
                    request,
                    lambda text: TextReplacementItem({"A": "Translated", "B": "colour"}[text], 1.0),
                )

        source = _emf_from_records(_comment(
            _plus_header() + _plus_font(0)
            + _plus_driver_string(0, "A", positions=((10.0, 30.0),), color=0xFF000000)
            + _plus_driver_string(0, "B", positions=((11.0, 30.0),), color=0xFFFF0000)
        ))
        provider = Provider()
        document, result = _apply(
            source, lambda text: text, layout="preserve-basic-layout", provider=provider,
        )
        self.assertIn("A", document.texts())
        self.assertIn("B", document.texts())
        self.assertEqual(["A", "B"], provider.requests)
        draws = [record for record in _plus_records(result.data) if record[0] == _PLUS_DRAW_DRIVER_STRING]
        self.assertEqual(["Translated ", "colour"], [_driver_string_parts(record[2])[0] for record in draws])
        self.assertEqual([0xFF000000, 0xFFFF0000], [struct.unpack_from("<I", record[2])[0] for record in draws])
        self.assertEqual(draws[0][1] & 0xFF, draws[1][1] & 0xFF)
        self.assertGreater(_driver_string_parts(draws[1][2])[1][0][0], 10.0)
        self.assertEqual(2, result.replaced_text_items)
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-02: returning colours, punctuation and language-specific spacing.
    def test_driver_line_three_spans_keep_order_and_boundary_spacing(self) -> None:
        class Provider:
            def __init__(self) -> None:
                self.requests: list[str] = []

            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                self.requests.extend(request.texts)
                return replace_each(
                    request, lambda text: TextReplacementItem({"A": "Word", "B": "1!", "C": "Next"}[text], 1.0)
                )

        source = _emf_from_records(_comment(
            _plus_header() + _plus_font(0)
            + _plus_driver_string(0, "A", positions=((10.0, 30.0),), color=0xFF000000)
            + _plus_driver_string(0, "B", positions=((11.0, 30.0),), color=0xFFFF0000)
            + _plus_driver_string(0, "C", positions=((12.0, 30.0),), color=0xFF000000)
        ))
        for layout in ("preserve-basic-layout", "preserve-basic-layout-source-font"):
            for language, expected in (("en", ["Word ", "1!", "Next"]), ("ja", ["Word", "1!", "Next"])):
                with self.subTest(layout=layout, language=language):
                    provider = Provider()
                    document = analyse_vector_text(source, ".emf", "en", language, document_text_layout=layout)
                    self.assertEqual(("A", "B", "C", "A", "B", "C"), document.texts())
                    result = document.apply(lambda text: text, provider, None)
                    self.assertEqual(["A", "B", "C"], provider.requests)
                    draws = [record for record in _plus_records(result.data) if record[0] == _PLUS_DRAW_DRIVER_STRING]
                    self.assertEqual(expected, [_driver_string_parts(record[2])[0] for record in draws])
                    self.assertEqual(
                        [0xFF000000, 0xFFFF0000, 0xFF000000],
                        [struct.unpack_from("<I", record[2])[0] for record in draws],
                    )
                    self.assertEqual(1, len({flags & 0xFF for _kind, flags, _body in draws}))
                    self.assertEqual(3, result.replaced_text_items)
                    self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-02: adjacent same-colour records form one translation span.
    def test_driver_line_combines_adjacent_records_of_same_colour(self) -> None:
        class Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(request, lambda text: TextReplacementItem("T:" + text, 1.0))

        source = _emf_from_records(_comment(
            _plus_header() + _plus_font(0)
            + _plus_driver_string(0, "A", positions=((10.0, 30.0),), color=0xFF000000)
            + _plus_driver_string(0, "B", positions=((11.0, 30.0),), color=0xFF000000)
            + _plus_driver_string(0, "C", positions=((12.0, 30.0),), color=0xFFFF0000)
        ))
        document = emf.analyse_emf(
            source, source_language="en", target_language="en", document_text_layout="preserve-basic-layout",
        )
        self.assertEqual(("A", "B", "C", "AB", "C"), document.texts())
        engine = TranslationEngine(Provider(), "en", "en")
        engine.add_unit("vector", document.texts())
        engine.resolve()
        result = document.apply(lambda text: engine.lookup(text).text, LookupProvider(engine.lookup))
        self.assertEqual(0, engine.plan_misses)
        draws = [record for record in _plus_records(result.data) if record[0] == _PLUS_DRAW_DRIVER_STRING]
        self.assertEqual(["T:AB ", "T:C"], [_driver_string_parts(body)[0] for _, _, body in draws])
        self.assertEqual([0xFF000000, 0xFFFF0000], [struct.unpack_from("<I", body)[0] for _, _, body in draws])
        self.assertEqual(1, len({flags & 0xFF for _, flags, _ in draws}))
        self.assertEqual(3, result.replaced_text_items)
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-02: grouped and fallback requests are planned and tracing is inert.
    def test_driver_line_plan_covers_atomic_fallback(self) -> None:
        source = _emf_from_records(_comment(
            _plus_header() + _plus_font(0)
            + _plus_driver_string(0, "A", positions=((10.0, 30.0),), color=0xFF000000)
            + _plus_driver_string(0, "B", positions=((11.0, 30.0),), color=0xFFFF0000)
        ))
        for fail_group in (False, True):
            outputs = []
            for trace in (False, True):
                with self.subTest(fail_group=fail_group, trace=trace):
                    document = emf.analyse_emf(
                        source, source_language="en", target_language="en",
                        document_text_layout="preserve-basic-layout", trace_layout=trace,
                    )
                    engine = TranslationEngine(_LongReplacementProvider(), "en", "en")
                    engine.add_unit("vector", document.texts())
                    engine.resolve()
                    if fail_group:
                        with patch("pipeline.vector_text.emf.translate_and_fit_line", return_value=None):
                            result = document.apply(lambda text: engine.lookup(text).text, LookupProvider(engine.lookup))
                    else:
                        result = document.apply(lambda text: engine.lookup(text).text, LookupProvider(engine.lookup))
                    self.assertEqual(0, engine.plan_misses)
                    self.assertEqual(2, result.replaced_text_items)
                    self.assertEqual(
                        fail_group, any(item["reason_code"] == "emfplus_group_fit_unsuccessful"
                                        for item in result.diagnostics),
                    )
                    self.assertTrue(_emf_is_structurally_valid(result.data))
                    outputs.append(result.data)
            self.assertEqual(outputs[0], outputs[1])

    # Verifies FR-2026-10-29-02: unavailable output fonts fall back without unplanned requests.
    def test_driver_line_falls_back_when_output_face_is_unavailable(self) -> None:
        source = _emf_from_records(_comment(
            _plus_header() + _plus_font(0)
            + _plus_driver_string(0, "A", positions=((10.0, 30.0),), color=0xFF000000)
            + _plus_driver_string(0, "B", positions=((11.0, 30.0),), color=0xFFFF0000)
        ))
        document = emf.analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout",
        )
        engine = TranslationEngine(_LongReplacementProvider(), "en", "en")
        engine.add_unit("vector", document.texts())
        engine.resolve()
        with patch("pipeline.vector_text.emf.source_line_typeface", return_value=None):
            result = document.apply(lambda text: engine.lookup(text).text, LookupProvider(engine.lookup))
        self.assertEqual(0, engine.plan_misses)
        self.assertTrue(any(item["reason_code"] == "emfplus_group_fit_unsuccessful" for item in result.diagnostics))
        draws = [body for kind, _, body in _plus_records(result.data) if kind == _PLUS_DRAW_DRIVER_STRING]
        self.assertEqual(2, len(draws))
        self.assertEqual([_LONG_TEXT, _LONG_TEXT], [_driver_string_parts(body)[0] for body in draws])
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-02: solid brush objects retain their colours.
    def test_driver_line_resolves_solid_brush_objects(self) -> None:
        source = _emf_from_records(_comment(
            _plus_header() + _plus_font(0)
            + _plus_solid_brush(1, 0xFF000000) + _plus_solid_brush(2, 0xFF0000FF)
            + _plus_driver_string(0, "A", positions=((10.0, 30.0),), brush_id=1)
            + _plus_driver_string(0, "B", positions=((11.0, 30.0),), brush_id=2)
        ))
        document, result = _apply(
            source, lambda text: text, layout="preserve-basic-layout",
            provider=_LongReplacementProvider(),
        )
        self.assertIn("A", document.texts())
        draws = [record for record in _plus_records(result.data) if record[0] == _PLUS_DRAW_DRIVER_STRING]
        self.assertEqual([0xFF000000, 0xFF0000FF], [struct.unpack_from("<I", record[2])[0] for record in draws])
        self.assertTrue(all(flags & 0x8000 for _kind, flags, _body in draws))
        self.assertEqual(2, result.replaced_text_items)

    # Verifies FR-2026-10-29-01 across consecutive EMF+ comments.
    def test_driver_line_groups_across_emfplus_comments(self) -> None:
        source = _emf_from_records(
            _comment(
                _plus_header() + _plus_font(0)
                + _plus_driver_string(0, "A", positions=((10.0, 30.0),), color=0xFF000000)
            ),
            _comment(_plus_driver_string(0, "B", positions=((11.0, 30.0),), color=0xFF000000)),
        )
        document, result = _apply(
            source, lambda text: text, layout="preserve-basic-layout",
            provider=_LongReplacementProvider(),
        )
        self.assertIn("AB", document.texts())
        draws = [record for record in _plus_records(result.data) if record[0] == _PLUS_DRAW_DRIVER_STRING]
        self.assertEqual([_LONG_TEXT], [_driver_string_parts(record[2])[0] for record in draws])
        self.assertEqual(2, result.replaced_text_items)
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-01 with a resolved scaled and translated EMF+ transform.
    def test_driver_line_groups_under_positive_world_transform(self) -> None:
        transform = _plus_record(0x402A, 0, struct.pack("<ffffff", 2, 0, 0, 3, 5, 9))
        source = _emf_from_records(_comment(
            _plus_header() + _plus_font(0) + transform
            + _plus_driver_string(0, "A", positions=((10.0, 30.0),), color=0xFF000000)
            + _plus_driver_string(0, "B", positions=((12.0, 30.0),), color=0xFF000000)
        ))
        document, result = _apply(
            source, lambda text: text, layout="preserve-basic-layout",
            provider=_LongReplacementProvider(),
        )
        self.assertIn("AB", document.texts())
        self.assertIn(transform, result.data)
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-01: baselines are compared in rendered coordinates.
    def test_driver_line_resolves_translation_changes_and_baseline_limit(self) -> None:
        for baseline_delta, grouped in ((1.0, True), (1.1, False)):
            with self.subTest(baseline_delta=baseline_delta):
                transform = _plus_record(
                    0x402A, 0, struct.pack("<ffffff", 2, 0, 0, 3, 5, 9 + baseline_delta)
                )
                translated = _plus_record(
                    0x402A, 0, struct.pack("<ffffff", 2, 0, 0, 3, 7, 9)
                )
                source = _emf_from_records(_comment(
                    _plus_header() + _plus_font(0) + translated
                    + _plus_driver_string(0, "A", positions=((10.0, 30.0),), color=0xFF000000)
                    + transform
                    + _plus_driver_string(0, "B", positions=((12.0, 30.0),), color=0xFF000000)
                ))
                document, result = _apply(
                    source, lambda text: text, layout="preserve-basic-layout",
                    provider=_LongReplacementProvider(),
                )
                self.assertEqual(grouped, "AB" in document.texts())
                self.assertIn(transform, result.data)
                self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-01: the four-line-height gap limit is inclusive.
    def test_driver_line_respects_rendered_gap_limit(self) -> None:
        for second_x, grouped in ((65.0, True), (65.1, False)):
            with self.subTest(second_x=second_x):
                source = _emf_from_records(_comment(
                    _plus_header() + _plus_font(0)
                    + _plus_driver_string(0, "A", positions=((10.0, 30.0),), color=0xFF000000)
                    + _plus_driver_string(0, "B", positions=((second_x, 30.0),), color=0xFF000000)
                ))
                with patch("pipeline.vector_text.emf.measure_advances", side_effect=lambda text, _face, _size, _style: [10.0] * len(text)):
                    document, result = _apply(
                        source, lambda text: text, layout="preserve-basic-layout",
                        provider=_LongReplacementProvider(),
                    )
                self.assertEqual(grouped, "A B" in document.texts())
                self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-01: EMF+ standalone numbers more than 0.25 line heights
    # apart stay separate, while closer number pieces still join.
    def test_driver_line_keeps_standalone_numbers_apart(self) -> None:
        for second_text, second_x, grouped in (("2014", 60.0, False), ("2014", 55.0, True), ("year", 60.0, True)):
            with self.subTest(second_text=second_text, second_x=second_x):
                source = _emf_from_records(_comment(
                    _plus_header() + _plus_font(0)
                    + _plus_driver_string(0, "2012", positions=((10.0, 30.0),), color=0xFF000000)
                    + _plus_driver_string(0, second_text, positions=((second_x, 30.0),), color=0xFF000000)
                ))
                with patch("pipeline.vector_text.emf.measure_advances", side_effect=lambda text, _face, _size, _style: [10.0] * len(text)):
                    document = emf.analyse_emf(
                        source, source_language="en", target_language="en",
                        document_text_layout="preserve-basic-layout",
                    )
                self.assertEqual(grouped, bool(document._plus_lines))

    # Verifies FR-2026-10-29-01: tall layout rectangles do not inflate the line-height gap limit.
    def test_draw_string_gap_limit_uses_font_line_height(self) -> None:
        for second_x, grouped in ((65.0, True), (65.1, False)):
            with self.subTest(second_x=second_x):
                source = _emf_from_records(_comment(
                    _plus_header() + _plus_font(0) + _plus_string_format(1)
                    + _plus_draw_string(0, "A", x=10.0, width=10.0, height=300.0,
                                        color=0xFF000000, format_id=1)
                    + _plus_draw_string(0, "B", x=second_x, width=10.0, height=300.0,
                                        color=0xFF000000, format_id=1)
                ))
                document, result = _apply(
                    source, lambda text: text, layout="preserve-basic-layout",
                    provider=_LongReplacementProvider(),
                )
                self.assertEqual(grouped, "A B" in document.texts())
                self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-01 and FR-2026-10-22-11 for minimum-size overflow.
    def test_grouped_line_keeps_minimum_font_size_for_overflow(self) -> None:
        class Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(request, lambda _text: TextReplacementItem("M" * 200, 1.0))

        for first_driver, second_driver in ((False, False), (True, True), (False, True), (True, False)):
            for layout in ("preserve-basic-layout", "preserve-basic-layout-source-font"):
                with self.subTest(first_driver=first_driver, second_driver=second_driver, layout=layout):
                    first = (
                        _plus_driver_string(0, "A", positions=((10.0, 28.0),), color=0xFF000000)
                        if first_driver else
                        _plus_draw_string(0, "A", x=10.0, width=10.0, color=0xFF000000, format_id=1)
                    )
                    second = (
                        _plus_driver_string(0, "B", positions=((20.0, 28.0),), color=0xFFFF0000)
                        if second_driver else
                        _plus_draw_string(0, "B", x=20.0, width=10.0, color=0xFFFF0000, format_id=1)
                    )
                    source = _emf_from_records(_comment(
                        _plus_header() + _plus_font(0) + _plus_string_format(1) + first + second
                    ))
                    _, result = _apply(source, lambda text: text, layout=layout, provider=Provider())
                    driver_output = first_driver and second_driver
                    draws = [record for record in _plus_records(result.data)
                             if record[0] == (_PLUS_DRAW_DRIVER_STRING if driver_output else _PLUS_DRAW_STRING)]
                    self.assertEqual(2, len(draws))
                    self.assertEqual(1, len({flags & 0xFF for _, flags, _ in draws}))
                    self.assertGreaterEqual(_font_objects(result.data)[draws[0][1] & 0xFF][0], 1.0)
                    self.assertFalse(any(item["reason_code"] == "emfplus_group_fit_unsuccessful"
                                         for item in result.diagnostics))
                    actual_text = [
                        _driver_string_parts(body)[0] if driver_output else _draw_string_text(body)
                        for _, _, body in draws
                    ]
                    self.assertEqual(["M" * 200 + " ", "M" * 200], actual_text)
                    if not driver_output:
                        format_id = struct.unpack_from("<I", draws[0][2], 4)[0]
                        formats = [body for kind, flags, body in _plus_records(result.data)
                                   if kind == _PLUS_OBJECT and flags == (0x0700 | format_id)]
                        self.assertEqual(0x5000, struct.unpack_from("<I", formats[-1], 4)[0] & 0x5000)
                    self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-01 and FR-2026-10-22-11 for large source fonts.
    def test_grouped_overflow_can_reach_one_pixel_below_one_percent_scale(self) -> None:
        class Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(request, lambda _text: TextReplacementItem("M" * 200, 1.0))

        source = _emf_from_records(_comment(
            _plus_header() + _plus_font(0, em_size=500.0)
            + _plus_driver_string(0, "A", positions=((10.0, 30.0),), color=0xFF000000)
            + _plus_driver_string(0, "B", positions=((11.0, 30.0),), color=0xFFFF0000)
        ))
        _, result = _apply(
            source, lambda text: text, layout="preserve-basic-layout", provider=Provider(),
        )
        draws = [record for record in _plus_records(result.data) if record[0] == _PLUS_DRAW_DRIVER_STRING]
        self.assertEqual(2, len(draws))
        self.assertEqual(1, len({flags & 0xFF for _, flags, _ in draws}))
        self.assertAlmostEqual(1.0, _font_objects(result.data)[draws[0][1] & 0xFF][0], places=5)
        self.assertFalse(any(item["reason_code"] == "emfplus_group_fit_unsuccessful"
                             for item in result.diagnostics))
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-01 and FR-2026-10-29-02 grouping boundaries.
    def test_driver_line_rejects_incompatible_font_alpha_and_paint(self) -> None:
        for middle, second_font, second_color in (
            (_plus_font(1, em_size=30.0), 1, 0xFF000000),
            (b"", 0, 0x80000000),
            (_plus_record(0x400A, 0, b""), 0, 0xFF000000),
        ):
            with self.subTest(second_font=second_font, second_color=second_color, middle=middle):
                source = _emf_from_records(_comment(
                    _plus_header() + _plus_font(0)
                    + _plus_driver_string(0, "A", positions=((10.0, 30.0),), color=0xFF000000)
                    + middle
                    + _plus_driver_string(second_font, "B", positions=((11.0, 30.0),), color=second_color)
                ))
                document, _result = _apply(
                    source, lambda text: text, layout="preserve-basic-layout",
                    provider=_LongReplacementProvider(),
                )
                self.assertNotIn("AB", document.texts())

    # Verifies FR-2026-10-29-01 and -02 for compatible, changed and unresolved clips.
    def test_driver_line_resolves_clip_changes(self) -> None:
        rect = _plus_record(0x4032, 0, struct.pack("<ffff", 0, 0, 80, 80))
        changed = _plus_record(0x4032, 0, struct.pack("<ffff", 0, 0, 40, 80))
        unknown = _plus_record(0x4033, 0, b"")
        reset = _plus_record(0x4031, 0, b"")
        for before, between, grouped in (
            (rect, rect, True), (rect, changed, False), (unknown, b"", False),
            (unknown + reset, b"", True),
        ):
            with self.subTest(before=before, between=between):
                source = _emf_from_records(_comment(
                    _plus_header() + _plus_font(0) + before
                    + _plus_driver_string(0, "A", positions=((10.0, 30.0),), color=0xFF000000)
                    + between
                    + _plus_driver_string(0, "B", positions=((11.0, 30.0),), color=0xFF000000)
                ))
                document, result = _apply(
                    source, lambda text: text, layout="preserve-basic-layout",
                    provider=_LongReplacementProvider(),
                )
                self.assertEqual(grouped, "AB" in document.texts())
                original_clips = [r for r in _plus_records(source) if 0x4031 <= r[0] <= 0x4035]
                result_clips = [r for r in _plus_records(result.data) if 0x4031 <= r[0] <= 0x4035]
                self.assertEqual(original_clips, result_clips)
                self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-01: drawn cell and column boundaries split source lines.
    def test_driver_line_respects_drawn_separators_in_either_paint_order(self) -> None:
        line = _plus_record(0x400D, 0, struct.pack("<Iffff", 2, 20, 0, 20, 50))
        integer_line = _plus_record(0x400D, 0x4000, struct.pack("<Ihhhh", 2, 20, 0, 20, 50))
        rectangle = _plus_record(0x400B, 0, struct.pack("<Iffff", 1, 20, 0, 50, 50))
        distant = _plus_record(0x400D, 0, struct.pack("<Iffff", 2, 20, 70, 20, 90))
        for separator, grouped in ((line, False), (integer_line, False), (rectangle, False), (distant, True)):
            for before in (False, True):
                with self.subTest(separator=separator, before=before):
                    texts = (
                        _plus_driver_string(0, "A", positions=((10.0, 30.0),), color=0xFF000000)
                        + _plus_driver_string(0, "B", positions=((30.0, 30.0),), color=0xFF000000)
                    )
                    source = _emf_from_records(_comment(
                        _plus_header() + _plus_font(0) + (separator + texts if before else texts + separator)
                    ))
                    document, result = _apply(
                        source, lambda text: text, layout="preserve-basic-layout",
                        provider=_LongReplacementProvider(),
                    )
                    self.assertEqual(grouped, "A B" in document.texts())
                    self.assertIn(separator, result.data)
                    self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-03: EMF+ sizes within 70% of the line's largest size join
    # one line; the bound is relative to the largest member, not each neighbour.
    def test_emfplus_size_spans_group_within_tolerance(self) -> None:
        for sizes, expected_members in (
            ((20.0, 15.0, 20.0), 3),
            ((20.0, 13.0), 0),
            ((20.0, 16.0, 13.0), 2),
        ):
            with self.subTest(sizes=sizes):
                fonts = b"".join(_plus_font(index, em_size=size) for index, size in enumerate(sizes))
                draws = b"".join(
                    _plus_driver_string(index, "AB"[index % 2], positions=((10.0 + 14.0 * index, 30.0),),
                                        color=0xFF000000)
                    for index in range(len(sizes))
                )
                source = _emf_from_records(_comment(_plus_header() + fonts + draws))
                document = emf.analyse_emf(
                    source, source_language="en", target_language="en",
                    document_text_layout="preserve-basic-layout",
                )
                members = [len(line.members) for line in document._plus_lines.values()]
                self.assertEqual(expected_members, sum(members))
                if expected_members == 3:
                    [line] = document._plus_lines.values()
                    self.assertEqual(20.0, line.font.em_size)
                    self.assertEqual(
                        [20.0, 15.0, 20.0],
                        [span.font.em_size for span in line.spans if span.font is not None],
                    )

    # Verifies FR-2026-10-29-03: each EMF+ span keeps its relative size under one scale.
    def test_emfplus_driver_size_spans_keep_relative_sizes(self) -> None:
        class Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(request, lambda text: TextReplacementItem(text.strip().upper() * 8, 1.0))

        source = _emf_from_records(_comment(
            _plus_header() + _plus_font(0) + _plus_font(1, em_size=15.0)
            + _plus_driver_string(0, "main", positions=((10.0, 30.0),), color=0xFF000000)
            + _plus_driver_string(1, "note", positions=((60.0, 30.0),), color=0xFF000000)
        ))
        document = emf.analyse_emf(
            source, source_language="en", target_language="en", document_text_layout="preserve-basic-layout",
        )
        engine = TranslationEngine(Provider(), "en", "en")
        engine.add_unit("vector", document.texts())
        engine.resolve()
        result = document.apply(lambda text: engine.lookup(text).text, LookupProvider(engine.lookup))
        self.assertEqual(0, engine.plan_misses)
        fonts = _font_objects(result.data)
        drivers = [record for record in _plus_records(result.data) if record[0] == _PLUS_DRAW_DRIVER_STRING]
        drawn = [(_driver_string_parts(body)[0], flags & 0xFF, _driver_string_parts(body)[1][0])
                 for _kind, flags, body in drivers]
        self.assertEqual(["MAINMAINMAINMAINMAINMAINMAINMAIN ", "NOTENOTENOTENOTENOTENOTENOTENOTE"],
                         [text for text, _font, _position in drawn])
        large, small = (fonts[font_id][0] for _text, font_id, _position in drawn)
        self.assertLess(large, 20.0)
        self.assertAlmostEqual(0.75, small / large, places=6)
        self.assertEqual([30.0, 30.0], [position[1] for _text, _font, position in drawn])
        self.assertLess(drawn[0][2][0], drawn[1][2][0])
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-03: DrawString spans of different sizes share the anchor baseline.
    def test_emfplus_draw_string_size_spans_share_baseline(self) -> None:
        class Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(request, lambda text: TextReplacementItem(text.strip().upper() * 6, 1.0))

        def ascent(font: object) -> float:
            return float(getattr(font, "size_points")) / 0.75 * 0.9

        source = _emf_from_records(_comment(
            _plus_header() + _plus_font(0) + _plus_font(1, em_size=15.0) + _plus_string_format(2)
            + _plus_draw_string(0, "main", x=10.0, y=10.0, width=40.0, color=0xFF000000, format_id=2)
            + _plus_draw_string(1, "note", x=52.0, y=14.5, width=30.0, color=0xFF000000, format_id=2)
        ))
        with patch("pipeline.vector_text.emf.source_line_ascent", side_effect=ascent):
            document, result = _apply(
                source, lambda text: text, layout="preserve-basic-layout", provider=Provider(),
            )
        fonts = _font_objects(result.data)
        draws = [record for record in _plus_records(result.data) if record[0] == _PLUS_DRAW_STRING]
        self.assertEqual(2, len(draws))
        (large_flags, large_body), (small_flags, small_body) = ((flags, body) for _kind, flags, body in draws)
        large_size = fonts[large_flags & 0xFF][0]
        small_size = fonts[small_flags & 0xFF][0]
        self.assertAlmostEqual(0.75, small_size / large_size, places=6)
        large_top = struct.unpack_from("<f", large_body, 16)[0]
        small_top = struct.unpack_from("<f", small_body, 16)[0]
        self.assertAlmostEqual(large_top + large_size * 0.9, small_top + small_size * 0.9, places=3)
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-01: equivalent font objects do not split the line.
    def test_driver_line_groups_equivalent_font_object_ids(self) -> None:
        source = _emf_from_records(_comment(
            _plus_header() + _plus_font(0) + _plus_font(1)
            + _plus_driver_string(0, "A", positions=((10.0, 30.0),), color=0xFF000000)
            + _plus_driver_string(1, "B", positions=((11.0, 30.0),), color=0xFF000000)
        ))
        document, result = _apply(
            source, lambda text: text, layout="preserve-basic-layout", provider=_LongReplacementProvider(),
        )
        self.assertIn("AB", document.texts())
        self.assertEqual(2, result.replaced_text_items)
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-01 and FR-2026-10-29-02 for EMF+ layout rectangles.
    def test_draw_string_line_preserves_colour_and_uniform_font(self) -> None:
        class Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request,
                    lambda text: TextReplacementItem({"A": "Translated", "B": "colour"}[text], 1.0),
                )

        source = _emf_from_records(_comment(
            _plus_header() + _plus_font(0) + _plus_string_format(1)
            + _plus_draw_string(0, "A", x=10.0, width=20.0, color=0xFF000000, format_id=1)
            + _plus_draw_string(0, "B", x=30.0, width=20.0, color=0xFFFF0000, format_id=1)
        ))
        with patch("pipeline.vector_text.emf.source_line_ascent", return_value=18.0):
            document, result = _apply(
                source, lambda text: text, layout="preserve-basic-layout", provider=Provider(),
            )
        self.assertIn("A", document.texts())
        self.assertIn("B", document.texts())
        draws = [record for record in _plus_records(result.data) if record[0] == _PLUS_DRAW_STRING]
        self.assertEqual(["Translated ", "colour"], [_draw_string_text(record[2]) for record in draws])
        self.assertEqual([0xFF000000, 0xFFFF0000], [struct.unpack_from("<I", record[2])[0] for record in draws])
        self.assertEqual(draws[0][1] & 0xFF, draws[1][1] & 0xFF)
        self.assertGreater(struct.unpack_from("<f", draws[1][2], 12)[0], 10.0)
        self.assertEqual(2, result.replaced_text_items)
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-01: the union width, not each fragment, determines the fitted size.
    def test_draw_string_line_fit_uses_full_union_width(self) -> None:
        source = _emf_from_records(_comment(
            _plus_header() + _plus_font(0) + _plus_string_format(1)
            + _plus_draw_string(0, "A", x=10.0, width=20.0, color=0xFF000000, format_id=1)
            + _plus_draw_string(0, "B", x=30.0, width=20.0, color=0xFF000000, format_id=1)
        ))
        fit = SimpleNamespace(text="WIDE", scale=1.0, layout_width=80.0, layout_typeface=object())
        class Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(request, lambda _text: TextReplacementItem("WIDE", 1.0))

        with (
            patch("pipeline.vector_text.emf.source_line_ascent", return_value=18.0),
            patch("pipeline.vector_text.emf.translate_and_fit_line", return_value=fit),
            patch("pipeline.vector_text.emf.measure_advances", return_value=[4.0] * 4),
        ):
            _document, result = _apply(
                source, lambda text: text, layout="preserve-basic-layout", provider=Provider(),
            )
        draw = next(record for record in _plus_records(result.data) if record[0] == _PLUS_DRAW_STRING)
        size = _font_objects(result.data)[draw[1] & 0xFF][0]
        self.assertAlmostEqual(9.4, size, places=4)
        self.assertAlmostEqual(28.0, struct.unpack_from("<f", draw[2], 16)[0] + 18.0 * size / 20, places=4)
        self.assertEqual("WIDE", _draw_string_text(draw[2]))

    # Verifies FR-2026-10-29-01 and -02 for mixed EMF+ records in both paint orders.
    def test_mixed_draw_and_driver_records_form_one_colour_line(self) -> None:
        class Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request, lambda text: TextReplacementItem({"A": "Blue", "B": "Red", "C": "End"}[text], 1.0)
                )

        draw_first = (
            _plus_draw_string(0, "A", x=10.0, y=10.0, width=20.0, color=0xFF0000FF, format_id=1)
            + _plus_driver_string(0, "B", positions=((30.0, 28.0),), color=0xFFFF0000)
            + _plus_driver_string(0, "C", positions=((31.0, 28.0),), color=0xFF0000FF)
        )
        driver_first = (
            _plus_driver_string(0, "A", positions=((10.0, 28.0),), color=0xFF0000FF)
            + _plus_draw_string(0, "B", x=20.0, y=10.0, width=20.0, color=0xFFFF0000, format_id=1)
            + _plus_driver_string(0, "C", positions=((38.0, 28.0),), color=0xFF0000FF)
        )
        for records in (draw_first, driver_first):
            for layout in ("preserve-basic-layout", "preserve-basic-layout-source-font"):
                with self.subTest(records=records, layout=layout):
                    source = _emf_from_records(_comment(
                        _plus_header() + _plus_font(0) + _plus_string_format(1) + records
                    ))
                    with patch("pipeline.vector_text.emf.source_line_ascent", return_value=18.0):
                        document, result = _apply(source, lambda text: text, layout=layout, provider=Provider())
                    self.assertEqual(("A", "B", "C", "A", "B", "C"), document.texts())
                    draws = [record for record in _plus_records(result.data) if record[0] == _PLUS_DRAW_STRING]
                    self.assertEqual(["Blue ", "Red ", "End"], [_draw_string_text(body) for _, _, body in draws])
                    self.assertEqual([0xFF0000FF, 0xFFFF0000, 0xFF0000FF],
                                     [struct.unpack_from("<I", body)[0] for _, _, body in draws])
                    self.assertEqual(1, len({flags & 0xFF for _, flags, _ in draws}))
                    scale = _font_objects(result.data)[draws[0][1] & 0xFF][0] / 20.0
                    for _, _, body in draws:
                        self.assertAlmostEqual(28.0, struct.unpack_from("<f", body, 16)[0] + 18.0 * scale, places=4)
                    self.assertFalse(any(kind == _PLUS_DRAW_DRIVER_STRING for kind, _, _ in _plus_records(result.data)))
                    self.assertEqual(3, result.replaced_text_items)
                    self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-01 when mixed baselines differ or the source font is unavailable.
    def test_mixed_records_split_at_unresolved_or_mismatched_baselines(self) -> None:
        for ascent, baseline, grouped in ((18.0, 29.0, True), (18.0, 29.1, False), (None, 28.0, False)):
            with self.subTest(ascent=ascent, baseline=baseline):
                source = _emf_from_records(_comment(
                    _plus_header() + _plus_font(0) + _plus_string_format(1)
                    + _plus_draw_string(0, "A", x=10.0, y=10.0, width=20.0, color=0xFF000000, format_id=1)
                    + _plus_driver_string(0, "B", positions=((30.0, baseline),), color=0xFF000000)
                ))
                with patch("pipeline.vector_text.emf.source_line_ascent", return_value=ascent):
                    document, result = _apply(
                        source, lambda text: text, layout="preserve-basic-layout",
                        provider=_LongReplacementProvider(),
                    )
                self.assertEqual(grouped, "AB" in document.texts())
                self.assertEqual(2, result.replaced_text_items)
                self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-01: sub-unit rectangles do not expand beyond their source areas.
    def test_draw_string_subunit_source_area_uses_individual_fallback(self) -> None:
        source = _emf_from_records(_comment(
            _plus_header() + _plus_font(0) + _plus_string_format(1)
            + _plus_draw_string(0, "A", x=10.0, y=10.0, width=0.5, color=0xFF000000, format_id=1)
            + _plus_draw_string(0, "B", x=10.5, y=10.0, width=0.5, color=0xFF000000, format_id=1)
        ))
        with patch("pipeline.vector_text.emf.source_line_ascent", return_value=18.0):
            document, result = _apply(
                source, lambda text: text, layout="preserve-basic-layout",
                provider=_LongReplacementProvider(),
            )
        self.assertEqual(("A", "B"), document.texts())
        self.assertEqual(2, result.replaced_text_items)
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-02: no available format ID causes planned, atomic fallback.
    def test_mixed_line_falls_back_when_object_table_is_full(self) -> None:
        objects = b"".join(_plus_solid_brush(index, 0xFF000000) for index in range(2, 64))
        source = _emf_from_records(_comment(
            _plus_header() + _plus_font(0) + _plus_string_format(1) + objects
            + _plus_driver_string(0, "A", positions=((10.0, 28.0),), color=0xFF000000)
            + _plus_draw_string(0, "B", x=20.0, y=10.0, width=20.0, color=0xFFFF0000, format_id=1)
        ))
        with patch("pipeline.vector_text.emf.source_line_ascent", return_value=18.0):
            document = emf.analyse_emf(
                source, source_language="en", target_language="en",
                document_text_layout="preserve-basic-layout",
            )
        engine = TranslationEngine(_LongReplacementProvider(), "en", "en")
        engine.add_unit("vector", document.texts())
        engine.resolve()
        result = document.apply(lambda text: engine.lookup(text).text, LookupProvider(engine.lookup))
        self.assertEqual(0, engine.plan_misses)
        self.assertTrue(any(item["reason_code"] == "emfplus_group_fit_unsuccessful" for item in result.diagnostics))
        draws = [record for record in _plus_records(result.data) if record[0] in (_PLUS_DRAW_STRING, _PLUS_DRAW_DRIVER_STRING)]
        self.assertEqual([_PLUS_DRAW_DRIVER_STRING, _PLUS_DRAW_STRING], [kind for kind, _, _ in draws])
        self.assertEqual(2, result.replaced_text_items)
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-01 and -02 for different GDI and EMF+ stream segmentation.
    def test_dual_streams_plan_and_replace_different_colour_boundaries(self) -> None:
        class Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(request, lambda text: TextReplacementItem("T:" + text, 1.0))

        source = _emf_from_records(
            _comment(
                _plus_header() + _plus_font(0)
                + _plus_driver_string(0, "A", positions=((10.0, 30.0),), color=0xFF000000)
                + _plus_driver_string(0, "B", positions=((11.0, 30.0),), color=0xFFFF0000)
            ),
            _emf_font_record("Noto Sans JP"), _comment(_plus_record(0x4004, 0, b"")),
            _emf_select_object_record(1),
            _emf_exttextout_record("A", 0, 0, 10, 20),
            _emf_exttextout_record("B", 10, 0, 40, 20),
        )
        for layout in ("preserve-basic-layout", "preserve-basic-layout-source-font"):
            with self.subTest(layout=layout):
                document = emf.analyse_emf(
                    source, source_language="en", target_language="en", document_text_layout=layout,
                )
                self.assertIn("AB", document.texts())
                engine = TranslationEngine(Provider(), "en", "en")
                engine.add_unit("vector", document.texts())
                engine.resolve()
                result = document.apply(lambda text: engine.lookup(text).text, LookupProvider(engine.lookup))
                self.assertEqual(0, engine.plan_misses)
                self.assertEqual(["T:AB", ""], _emf_texts(result.data))
                draws = [body for kind, _, body in _plus_records(result.data) if kind == _PLUS_DRAW_DRIVER_STRING]
                self.assertEqual(["T:A ", "T:B"], [_driver_string_parts(body)[0] for body in draws])
                self.assertEqual(4, result.replaced_text_items)
                self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-01: unresolved DrawString layout effects are grouping boundaries.
    def test_draw_string_line_rejects_margins_and_other_formatting(self) -> None:
        for offset, value in ((20, 1), (32, 1), (36, 0xBF800000), (40, 0x7FC00000),
                              (44, 0), (48, 2)):
            with self.subTest(offset=offset):
                fmt = bytearray(_plus_string_format(1))
                struct.pack_into("<I", fmt, 12 + offset, value)
                source = _emf_from_records(_comment(
                    _plus_header() + _plus_font(0) + bytes(fmt)
                    + _plus_draw_string(0, "A", x=10.0, width=20.0, color=0xFF000000, format_id=1)
                    + _plus_draw_string(0, "B", x=30.0, width=20.0, color=0xFFFF0000, format_id=1)
                ))
                document, _result = _apply(
                    source, lambda text: text, layout="preserve-basic-layout",
                    provider=_LongReplacementProvider(),
                )
                self.assertEqual(("A", "B"), document.texts())

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

    # Verifies FR-2026-10-28-03: fitted fonts are created in the active GDI interval.
    def test_fitted_gdi_font_is_created_inside_getdc_interval(self) -> None:
        header_comment = _comment(_plus_header())
        getdc_comment = _comment(_plus_record(0x4004, 0, b""))
        source = _emf_from_records(
            header_comment,
            _emf_font_record("Noto Sans JP"),
            getdc_comment,
            _emf_select_object_record(1),
            _emf_exttextout_record("Old", 0, 0, 40, 20),
        )

        _document, result = self._fitted(source, "preserve-basic-layout-source-font")

        records = _emf_records(result.data)
        self.assertEqual(header_comment, records[1])
        self.assertEqual(getdc_comment, records[3])
        text_index = next(index for index, record in enumerate(records) if struct.unpack_from("<I", record)[0] == 84)
        generated_font, generated_selection = records[text_index - 2:text_index]
        self.assertEqual(82, struct.unpack_from("<I", generated_font)[0])
        self.assertEqual(37, struct.unpack_from("<I", generated_selection)[0])
        self.assertEqual(struct.unpack_from("<I", generated_font, 8)[0], struct.unpack_from("<I", generated_selection, 8)[0])
        self.assertLess(struct.unpack_from("<I", generated_font, 8)[0], struct.unpack_from("<H", result.data, 56)[0])
        self.assertEqual(1, struct.unpack_from("<I", records[text_index + 1], 8)[0])
        self.assertTrue(_emf_is_structurally_valid(result.data))
        traced = emf.analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout-source-font", trace_layout=True,
        ).apply(lambda text: _LONG_TEXT, _LongReplacementProvider())
        self.assertEqual(result.data, traced.data)
        [trace] = traced.emf_layout_trace
        generated = trace["generated_font"]
        assert isinstance(generated, dict)
        self.assertTrue(generated["within_emfplus_getdc"])

    # Verifies FR-2026-10-28-03.
    def test_grouped_gdi_font_is_created_inside_getdc_interval(self) -> None:
        header_comment = _comment(_plus_header())
        getdc_comment = _comment(_plus_record(0x4004, 0, b""))
        source = _emf_from_records(
            header_comment,
            _emf_font_record("Noto Sans JP"),
            getdc_comment,
            _emf_select_object_record(1),
            _emf_exttextout_record("A", 0, 0, 10, 20),
            _emf_exttextout_record("B", 10, 0, 40, 20),
        )
        _document, result = self._fitted(source, "preserve-basic-layout-source-font")
        records = _emf_records(result.data)
        self.assertEqual(header_comment, records[1])
        self.assertEqual(getdc_comment, records[3])
        text_indices = [index for index, record in enumerate(records) if struct.unpack_from("<I", record)[0] == 84]
        self.assertEqual(2, len(text_indices))
        anchor = text_indices[0]
        self.assertEqual(82, struct.unpack_from("<I", records[anchor - 2])[0])
        self.assertEqual(37, struct.unpack_from("<I", records[anchor - 1])[0])
        self.assertEqual(struct.unpack_from("<I", records[anchor - 2], 8)[0],
                         struct.unpack_from("<I", records[anchor - 1], 8)[0])
        self.assertEqual(1, struct.unpack_from("<I", records[anchor + 1], 8)[0])
        self.assertEqual(0, struct.unpack_from("<I", records[text_indices[1]], 44)[0])
        self.assertTrue(_emf_is_structurally_valid(result.data))


if __name__ == "__main__":
    unittest.main()
