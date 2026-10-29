"""Parse and rewrite the EMF+ text records stored inside ``EMR_COMMENT`` records.

An EMF+ stream is a series of records carried in ``EMR_COMMENT`` records whose data starts
with the identifier ``EMF+``. This module reads those records and builds the replacement
bytes. Deciding what to replace and how to fit it lives in ``emf.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct

# skia-python does not publish PEP 561 stubs; this is the native measurement boundary.
import skia  # type: ignore[import-not-found]

EMR_COMMENT = 70
EMFPLUS_IDENTIFIER = b"EMF+"
EMFPLUS_HEADER = 0x4001
EMFPLUS_OBJECT = 0x4008
EMFPLUS_DRAW_STRING = 0x401C
EMFPLUS_DRAW_DRIVER_STRING = 0x4036
FONT_OBJECT_TYPE = 6
OBJECT_ID_COUNT = 64
UNIT_WORLD = 0
UNIT_PIXEL = 2
FONT_STYLE_BOLD = 1
FONT_STYLE_ITALIC = 2
_CMAP_LOOKUP = 1
_VERTICAL = 2
_REALIZED_ADVANCE = 4
_RECORD_HEADER_SIZE = 12
_DRAW_STRING_FIXED_SIZE = 28
_DRIVER_STRING_FIXED_SIZE = 16
_MATRIX_SIZE = 24
_FONT_FIXED_SIZE = 24


@dataclass(frozen=True, slots=True)
class PlusFont:
    """One EMF+ font object: its size, size unit, style and original object data."""

    em_size: float
    unit: int
    style: int
    family: str
    data: bytes


@dataclass(frozen=True, slots=True)
class DriverString:
    """The parts of an ``EmfPlusDrawDriverString`` payload that a replacement rewrites."""

    head: bytes
    options: int
    glyph_count: int
    positions: tuple[tuple[float, float], ...]
    single_position: bool
    matrix: bytes


@dataclass(slots=True)
class PlusRecord:
    """One EMF+ record, with the source text and font of a text-bearing record."""

    record_type: int
    flags: int
    raw: bytes
    data: bytes
    font: PlusFont | None = None
    text: str | None = None
    unsupported_reason: str | None = None


def is_emfplus_comment(record: bytes) -> bool:
    """Return whether an EMR_COMMENT record carries an EMF+ stream."""
    return (
        len(record) >= 16
        and struct.unpack_from("<I", record, 0)[0] == EMR_COMMENT
        and record[12:16] == EMFPLUS_IDENTIFIER
    )


def starts_with_emfplus_header(record: bytes) -> bool:
    """Return whether an EMR_COMMENT record begins with the EMF+ header record."""
    return (
        is_emfplus_comment(record)
        and len(record) >= 18
        and struct.unpack_from("<H", record, 16)[0] == EMFPLUS_HEADER
    )


def parse_comment(
    record: bytes, fonts: dict[int, PlusFont], object_ids: set[int]
) -> list[PlusRecord]:
    """Split an EMF+ comment into records, tracking font objects in stream order.

    ``fonts`` and ``object_ids`` carry the object table across comments. Raises
    ``ValueError`` when the comment is structurally invalid.
    """
    data_size = struct.unpack_from("<I", record, 8)[0]
    end = _RECORD_HEADER_SIZE + data_size
    if data_size < 4 or end > len(record):
        raise ValueError("Invalid EMF+ comment size.")
    records: list[PlusRecord] = []
    offset = 16
    while offset < end:
        if offset + _RECORD_HEADER_SIZE > end:
            raise ValueError("Invalid EMF+ record header.")
        record_type, flags, size, data_length = struct.unpack_from("<HHII", record, offset)
        if size < _RECORD_HEADER_SIZE or offset + size > end or data_length > size - _RECORD_HEADER_SIZE:
            raise ValueError("Invalid EMF+ record size.")
        data = record[offset + _RECORD_HEADER_SIZE : offset + _RECORD_HEADER_SIZE + data_length]
        plus = PlusRecord(record_type, flags, record[offset : offset + size], data)
        if record_type == EMFPLUS_OBJECT:
            _track_object(plus, fonts, object_ids)
        elif record_type == EMFPLUS_DRAW_STRING:
            _read_draw_string(plus, fonts)
        elif record_type == EMFPLUS_DRAW_DRIVER_STRING:
            _read_driver_string(plus, fonts)
        records.append(plus)
        offset += size
    return records


def _track_object(plus: PlusRecord, fonts: dict[int, PlusFont], object_ids: set[int]) -> None:
    object_id = plus.flags & 0xFF
    object_ids.add(object_id)
    fonts.pop(object_id, None)
    is_continued = bool(plus.flags & 0x8000)
    if (plus.flags >> 8) & 0x7F != FONT_OBJECT_TYPE or is_continued:
        return
    if len(plus.data) < _FONT_FIXED_SIZE:
        return
    _version, em_size, unit, style, _reserved, length = struct.unpack_from("<IfIIII", plus.data, 0)
    family_end = _FONT_FIXED_SIZE + (2 * length)
    if family_end > len(plus.data):
        return
    try:
        family = plus.data[_FONT_FIXED_SIZE:family_end].decode("utf-16-le")
    except UnicodeDecodeError:
        return
    fonts[object_id] = PlusFont(em_size, unit, style, family, plus.data)


def _read_draw_string(plus: PlusRecord, fonts: dict[int, PlusFont]) -> None:
    parsed = parse_draw_string(plus.data)
    if parsed is None:
        plus.unsupported_reason = "emfplus_text_record_malformed"
        return
    plus.text = parsed or None
    plus.font = fonts.get(plus.flags & 0xFF)


def _read_driver_string(plus: PlusRecord, fonts: dict[int, PlusFont]) -> None:
    driver = parse_driver_string(plus.data)
    if driver is None:
        plus.unsupported_reason = "emfplus_text_record_malformed"
        return
    if not driver.options & _CMAP_LOOKUP:
        plus.unsupported_reason = "emfplus_driver_string_glyph_indices"
    elif driver.options & _VERTICAL:
        plus.unsupported_reason = "emfplus_driver_string_vertical"
    elif driver.glyph_count:
        plus.text = driver_text(plus.data, driver)
        plus.font = fonts.get(plus.flags & 0xFF)


def parse_draw_string(data: bytes) -> str | None:
    """Return a ``DrawString`` payload's text, or ``None`` when the payload is invalid."""
    if len(data) < _DRAW_STRING_FIXED_SIZE:
        return None
    length = struct.unpack_from("<I", data, 8)[0]
    end = _DRAW_STRING_FIXED_SIZE + (2 * length)
    if end > len(data):
        return None
    try:
        return data[_DRAW_STRING_FIXED_SIZE:end].decode("utf-16-le")
    except UnicodeDecodeError:
        return None


def draw_string_layout_size(data: bytes) -> tuple[float, float]:
    """Return a valid ``DrawString`` payload's layout rectangle width and height."""
    width, height = struct.unpack_from("<ff", data, 20)
    return width, height


def draw_string_with_text(data: bytes, text: str) -> bytes:
    encoded = text.encode("utf-16-le")
    updated = data[:8] + struct.pack("<I", len(encoded) // 2) + data[12:_DRAW_STRING_FIXED_SIZE] + encoded
    return _pad4(updated)


def parse_driver_string(data: bytes) -> DriverString | None:
    """Parse a ``DrawDriverString`` payload, or return ``None`` when it is invalid."""
    if len(data) < _DRIVER_STRING_FIXED_SIZE:
        return None
    _brush, options, has_matrix, glyph_count = struct.unpack_from("<IIII", data, 0)
    if has_matrix not in (0, 1):
        return None
    glyphs_end = _DRIVER_STRING_FIXED_SIZE + 2 * glyph_count
    matrix_size = _MATRIX_SIZE if has_matrix == 1 else 0
    positions_size = len(data) - glyphs_end - matrix_size
    if 8 * glyph_count <= positions_size <= 8 * glyph_count + 3:
        position_count = glyph_count
        single_position = glyph_count == 1 and bool(options & _REALIZED_ADVANCE)
    elif glyph_count and 8 <= positions_size <= 11:
        position_count, single_position = 1, True
    else:
        return None
    positions = tuple(
        struct.unpack_from("<ff", data, glyphs_end + (8 * index)) for index in range(position_count)
    )
    matrix_start = glyphs_end + 8 * position_count
    matrix = data[matrix_start : matrix_start + matrix_size] if matrix_size else b""
    return DriverString(data[:8], options, glyph_count, positions, single_position, matrix)


def driver_text(data: bytes, driver: DriverString) -> str | None:
    """Return the characters of a ``CmapLookup`` driver string."""
    end = _DRIVER_STRING_FIXED_SIZE + (2 * driver.glyph_count)
    try:
        return data[_DRIVER_STRING_FIXED_SIZE:end].decode("utf-16-le")
    except UnicodeDecodeError:
        return None


def driver_string_with_text(driver: DriverString, text: str, advances: list[float]) -> bytes:
    """Rewrite a driver string with ``text``, placing each character after the advance before it."""
    encoded = text.encode("utf-16-le")
    count = len(encoded) // 2
    first_x, first_y = driver.positions[0]
    if driver.single_position:
        positions = [(first_x, first_y)]
    else:
        positions = []
        x = first_x
        for advance in advances:
            positions.append((x, first_y))
            x += advance
    body = bytearray(driver.head)
    body += struct.pack("<II", 1 if driver.matrix else 0, count)
    body += encoded
    for x, y in positions:
        body += struct.pack("<ff", x, y)
    body += driver.matrix
    return bytes(body)


def can_encode_driver_text(text: str) -> bool:
    """Return whether every character is one UTF-16 unit, which a driver string needs."""
    return all(ord(character) <= 0xFFFF for character in text)


def driver_source_width(driver: DriverString, advances: list[float]) -> float:
    """Return the horizontal extent of a driver string's source glyphs."""
    if driver.single_position or len(driver.positions) < 2:
        return sum(advances)
    return (driver.positions[-1][0] - driver.positions[0][0]) + (advances[-1] if advances else 0.0)


def measure_advances(text: str, typeface: object, size: float, style: int) -> list[float]:
    """Measure each character's advance in a Noto face at ``size`` world units."""
    font = skia.Font(typeface, size)
    font.setEmbolden(bool(style & FONT_STYLE_BOLD))
    if style & FONT_STYLE_ITALIC:
        font.setSkewX(-0.2)
    return [float(width) for width in font.getWidths(font.textToGlyphs(text))]


def font_object_record(object_id: int, source: PlusFont, scale: float) -> bytes:
    """Return a new Font object record: ``source`` with its em size scaled by ``scale``."""
    data = bytearray(source.data)
    struct.pack_into("<f", data, 4, source.em_size * scale)
    flags = (FONT_OBJECT_TYPE << 8) | object_id
    return plus_record(EMFPLUS_OBJECT, flags, bytes(data))


def plus_record(record_type: int, flags: int, data: bytes) -> bytes:
    padded = _pad4(data)
    return struct.pack("<HHII", record_type, flags, _RECORD_HEADER_SIZE + len(padded), len(padded)) + padded


def with_font_id(flags: int, object_id: int) -> int:
    return (flags & ~0xFF) | object_id


def comment_record(plus_records: bytes) -> bytes:
    """Wrap EMF+ records in an ``EMR_COMMENT`` record."""
    payload = _pad4(EMFPLUS_IDENTIFIER + plus_records)
    return struct.pack("<III", EMR_COMMENT, 12 + len(payload), len(payload)) + payload


def first_free_object_id(object_ids: set[int]) -> int | None:
    for candidate in range(OBJECT_ID_COUNT):
        if candidate not in object_ids:
            return candidate
    return None


def _pad4(data: bytes) -> bytes:
    return data + b"\0" * (-len(data) % 4)
