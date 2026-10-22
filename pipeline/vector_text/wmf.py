"""WMF native text and DIB replacement, split into analysis and apply."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
import struct

from PIL import Image

from pipeline.bounded_text_layout import SourceTypefaceReference
from pipeline.text_replacement import TextReplacementProvider
from pipeline.vector_text.common import (
    ETO_CLIPPED,
    ETO_OPAQUE,
    NestedGraphic,
    SourceLineFont,
    VectorReplacementResult,
    bitmap_file_from_dib,
    dib_from_image,
    measure_source_line,
    translate_and_fit_line,
)

_META_EXTTEXTOUT = 0x0A32
_META_TEXTOUT = 0x0521
_META_CREATEFONTINDIRECT = 0x02FB
_META_SELECTOBJECT = 0x012D
_META_DELETEOBJECT = 0x01F0
_META_STRETCHDIB = 0x0F43
_PLACEABLE_KEY = b"\xd7\xcd\xc6\x9a"
_STANDARD_HEADER_WORDS = 9
_STRETCHDIB_HEADER_SIZE = 28


def is_wmf(data: bytes) -> bool:
    """Return whether ``data`` starts with a placeable or standard WMF header."""
    return data.startswith(_PLACEABLE_KEY) or (
        len(data) >= 4
        and struct.unpack_from("<H", data, 0)[0] in {1, 2}
        and struct.unpack_from("<H", data, 2)[0] == _STANDARD_HEADER_WORDS
    )


@dataclass(slots=True)
class _Record:
    """One WMF record with the source text and decoded image analysis found in it."""

    function: int
    data: bytes
    text: str | None = None
    image: tuple[int, Image.Image] | None = None


class WmfDocument:
    """A parsed WMF that lists its texts and images, then applies replacements."""

    def __init__(
        self,
        header: bytes,
        header_offset: int,
        records: list[_Record],
        tail: bytes,
        *,
        encoding: str,
        document_text_layout: str,
        source_language: str,
        target_language: str | None,
    ) -> None:
        self._header = header
        self._header_offset = header_offset
        self._records = records
        self._tail = tail
        self._encoding = encoding
        self._layout = document_text_layout
        self._source_language = source_language
        self._target_language = target_language

    def texts(self) -> tuple[str, ...]:
        return tuple(record.text for record in self._records if record.text is not None)

    def images(self) -> list[Image.Image]:
        return [record.image[1] for record in self._records if record.image is not None]

    def nested(self) -> list[NestedGraphic]:
        return []

    def apply(
        self,
        replace_text: Callable[[str], str],
        replacement_provider: TextReplacementProvider | None,
        replace_image: Callable[[int, Image.Image], int] | None = None,
        replace_nested: Callable[[int], VectorReplacementResult | None] | None = None,
    ) -> VectorReplacementResult:
        output: list[bytes] = [self._header]
        replaced_items = 0
        replaced_image_regions = 0
        has_embedded_bitmaps = False
        occupied_handles: set[int] = set()
        font_records: dict[int, bytes] = {}
        selected_font: int | None = None
        for source in self._records:
            record = source.data
            function = source.function
            if function == _META_CREATEFONTINDIRECT:
                handle = _next_handle(occupied_handles)
                occupied_handles.add(handle)
                font_records[handle] = record
            elif function == _META_SELECTOBJECT and len(record) >= 8:
                selected = struct.unpack_from("<H", record, 6)[0]
                selected_font = selected if selected in font_records else None
            elif function == _META_DELETEOBJECT and len(record) >= 8:
                handle = struct.unpack_from("<H", record, 6)[0]
                occupied_handles.discard(handle)
                font_records.pop(handle, None)
                if selected_font == handle:
                    selected_font = None
            if function in {_META_TEXTOUT, _META_EXTTEXTOUT} and source.text is not None:
                font_record = font_records.get(selected_font) if selected_font is not None else None
                fitted = None
                if font_record is not None:
                    if function == _META_EXTTEXTOUT:
                        fitted = _fitted_exttextout(
                            record, source.text, self._layout, replacement_provider,
                            self._source_language, self._target_language,
                        )
                    if fitted is None:
                        fitted = _fitted_unclipped_text(
                            source.text, font_record, self._layout, replacement_provider,
                            self._source_language, self._target_language, self._encoding,
                        )
                write_text = _textout_with_text if function == _META_TEXTOUT else _exttextout_with_text
                replaced_items += 1
                if fitted is None or selected_font is None:
                    record = write_text(record, replace_text(source.text), self._encoding)
                elif fitted[1] >= 1.0:
                    record = write_text(record, fitted[0], self._encoding)
                else:
                    replacement, scale = fitted
                    clone_handle = _next_handle(occupied_handles)
                    occupied_handles.add(clone_handle)
                    output.append(_scaled_font_record(font_records[selected_font], scale))
                    output.append(_select_object_record(clone_handle))
                    output.append(write_text(record, replacement, self._encoding))
                    output.append(_select_object_record(selected_font))
                    output.append(_delete_object_record(clone_handle))
                    occupied_handles.discard(clone_handle)
                    continue
            elif (
                function == _META_STRETCHDIB
                and replace_image is not None
                and source.image is not None
            ):
                index, image = source.image
                regions = replace_image(index, image)
                has_embedded_bitmaps = True
                if regions:
                    record = _stretchdib_with_image(record, image)
                    replaced_image_regions += regions
            output.append(record)
        output.append(self._tail)
        result = bytearray(b"".join(output))
        if replaced_items:
            struct.pack_into("<I", result, self._header_offset + 6, len(result) // 2)
        return VectorReplacementResult(
            bytes(result), replaced_items, bool(replaced_items),
            replaced_image_regions, has_embedded_bitmaps,
        )


def analyse_wmf(
    data: bytes,
    *,
    source_language: str,
    document_text_layout: str = "preserve-source-formatting",
    target_language: str | None = None,
) -> WmfDocument:
    """Parse a WMF and list its texts and DIB images; replace nothing yet."""
    header_offset = 22 if data.startswith(_PLACEABLE_KEY) else 0
    if len(data) < header_offset + 4:
        raise ValueError("Invalid WMF image.")
    header_words = struct.unpack_from("<H", data, header_offset + 2)[0]
    if header_words < 9:
        raise ValueError("Invalid WMF header size.")
    records_offset = header_offset + (header_words * 2)
    if len(data) < records_offset:
        raise ValueError("Invalid WMF image.")
    encoding = "cp932" if source_language.lower().replace("_", "-").startswith("ja") else "latin-1"
    records: list[_Record] = []
    tail = b""
    image_count = 0
    offset = records_offset
    while offset < len(data):
        if offset + 6 > len(data):
            raise ValueError("Invalid WMF record header.")
        record_words, function = struct.unpack_from("<IH", data, offset)
        record_size = record_words * 2
        if record_words < 3 or offset + record_size > len(data):
            raise ValueError("Invalid WMF record size.")
        record = data[offset : offset + record_size]
        source = _Record(function, record)
        if function == _META_TEXTOUT:
            source.text = _textout_text(record, encoding)
        elif function == _META_EXTTEXTOUT:
            source.text = _exttextout_text(record, encoding)
        elif function == _META_STRETCHDIB:
            image = _stretchdib_image(record)
            if image is not None:
                source.image = (image_count, image)
                image_count += 1
        records.append(source)
        offset += record_size
        if function == 0:
            tail = data[offset:]
            break
    return WmfDocument(
        data[:records_offset], header_offset, records, tail,
        encoding=encoding, document_text_layout=document_text_layout,
        source_language=source_language, target_language=target_language,
    )


def replace_wmf(
    data: bytes,
    replace_text: Callable[[str], str],
    source_language: str,
    replace_image: Callable[[Image.Image], int] | None,
    *,
    document_text_layout: str = "preserve-source-formatting",
    replacement_provider: TextReplacementProvider | None = None,
    target_language: str | None = None,
) -> VectorReplacementResult:
    document = analyse_wmf(
        data, source_language=source_language,
        document_text_layout=document_text_layout, target_language=target_language,
    )
    return document.apply(
        replace_text, replacement_provider,
        None if replace_image is None else lambda _index, image: replace_image(image),
    )


def _fitted_exttextout(
    record: bytes, source_text: str, document_text_layout: str,
    provider: TextReplacementProvider | None, source_language: str, target_language: str | None,
) -> tuple[str, float] | None:
    if (document_text_layout not in {"preserve-basic-layout", "preserve-basic-layout-source-font"}
            or provider is None or target_language is None or len(record) < 22):
        return None
    options = struct.unpack_from("<H", record, 12)[0]
    if not options & ETO_CLIPPED:
        return None
    left, top, right, bottom = struct.unpack_from("<hhhh", record, 14)
    width, height = abs(right - left), abs(bottom - top)
    if not width or not height or not source_text.strip():
        return None
    from pipeline.bounded_text_layout import (
        BoundedTextBox, BoundedTextParagraph, BoundedTextRun, noto_typefaces, replace_and_fit_text_box,
    )
    box = BoundedTextBox(width * 9_525, height * 9_525, 0, 0, 0, 0, None,
        (BoundedTextParagraph("left", None, None, None, None, 0, None, None, None, None, None,
                              (BoundedTextRun(source_text, None, "sans-serif", 12.0, False, False, "none", None),)),))
    fitted = replace_and_fit_text_box(box, provider, source_language, target_language, noto_typefaces(),
                                      preserve_source_font_family=True,
                                      measure_source_fonts=document_text_layout == "preserve-basic-layout-source-font")
    return fitted.text_box.paragraphs[0].runs[0].text, fitted.font_scale


def _fitted_unclipped_text(
    source_text: str, font_record: bytes, document_text_layout: str,
    provider: TextReplacementProvider | None, source_language: str,
    target_language: str | None, encoding: str,
) -> tuple[str, float] | None:
    """Fit a text without a clip rectangle to the extent its source text occupies."""
    if (document_text_layout not in {"preserve-basic-layout", "preserve-basic-layout-source-font"}
            or provider is None or target_language is None or len(font_record) < 26):
        return None
    record = font_record
    height, _width, escapement = struct.unpack_from("<hhh", record, 6)
    if height == 0 or escapement != 0 or any(character in source_text for character in "\r\n\v\f"):
        return None
    weight = struct.unpack_from("<h", record, 14)[0]
    pitch_and_family = record[23]
    face = _decode_text(record[24:].split(b"\0", 1)[0], encoding) or None
    if pitch_and_family & 0x3 == 1:
        classification = "fixed-width"
    else:
        classification = "serif" if (pitch_and_family >> 4) & 0xF == 1 else "sans-serif"
    font = SourceLineFont(
        face, abs(height) * 0.75, weight >= 700, bool(record[16]), classification,
        tuple(SourceTypefaceReference(script, face) for script in ("latin", "eastAsian", "complex"))
        if face else (),
    )
    source_font_layout = document_text_layout == "preserve-basic-layout-source-font"
    measured = measure_source_line(source_text, font, measure_source_fonts=source_font_layout)
    if measured is None:
        return None
    fitted = translate_and_fit_line(
        source_text, font, measured[0], None, provider, source_language, target_language,
        preserve_source_font_family=True, measure_source_fonts=source_font_layout,
    )
    return None if fitted is None else (fitted.text, fitted.scale)


def _next_handle(occupied: set[int]) -> int:
    handle = 0
    while handle in occupied:
        handle += 1
    return handle


def _scaled_font_record(record: bytes, scale: float) -> bytes:
    if len(record) < 10:
        return record
    output = bytearray(record)
    height = struct.unpack_from("<h", output, 6)[0]
    if height:
        struct.pack_into("<h", output, 6, max(-32768, min(32767, round(height * scale))))
    return bytes(output)


def _select_object_record(handle: int) -> bytes:
    return struct.pack("<IHH", 4, _META_SELECTOBJECT, handle)


def _delete_object_record(handle: int) -> bytes:
    return struct.pack("<IHH", 4, _META_DELETEOBJECT, handle)


def _stretchdib_image(record: bytes) -> Image.Image | None:
    if len(record) <= _STRETCHDIB_HEADER_SIZE:
        return None
    dib = record[_STRETCHDIB_HEADER_SIZE:]
    if len(dib) < 40 or struct.unpack_from("<I", dib, 0)[0] != 40 or struct.unpack_from("<I", dib, 16)[0] != 0:
        return None
    bit_count = struct.unpack_from("<H", dib, 14)[0]
    colours_used = struct.unpack_from("<I", dib, 32)[0]
    colour_table_size = colours_used or ((1 << bit_count) if bit_count <= 8 else 0)
    bitmap_info_size = 40 + (colour_table_size * 4)
    if bitmap_info_size > len(dib):
        return None
    with Image.open(BytesIO(bitmap_file_from_dib(dib[:bitmap_info_size], dib[bitmap_info_size:]))) as opened:
        return opened.copy()


def _stretchdib_with_image(record: bytes, image: Image.Image) -> bytes:
    bitmap_info, bitmap_bits = dib_from_image(image)
    updated = bytearray(record[:_STRETCHDIB_HEADER_SIZE] + bitmap_info + bitmap_bits)
    if len(updated) % 2:
        updated.append(0)
    struct.pack_into("<I", updated, 0, len(updated) // 2)
    return bytes(updated)


def _textout_text(record: bytes, encoding: str) -> str | None:
    if len(record) < 12:
        raise ValueError("Invalid WMF TextOut record.")
    string_length = struct.unpack_from("<H", record, 6)[0]
    string_end = 8 + string_length
    if string_end + (string_length % 2) + 4 > len(record):
        raise ValueError("Invalid WMF TextOut string.")
    if string_length == 0:
        return None
    return _decode_text(record[8:string_end], encoding)


def _textout_with_text(record: bytes, replacement: str, encoding: str) -> bytes:
    string_length = struct.unpack_from("<H", record, 6)[0]
    trailing_position = 8 + string_length + (string_length % 2)
    replacement_bytes = _encode_text(replacement, encoding)
    updated = bytearray(record[:6])
    updated.extend(struct.pack("<H", len(replacement_bytes)))
    updated.extend(replacement_bytes)
    if len(replacement_bytes) % 2:
        updated.append(0)
    updated.extend(record[trailing_position:])
    struct.pack_into("<I", updated, 0, len(updated) // 2)
    return bytes(updated)


def _exttextout_text(record: bytes, encoding: str) -> str | None:
    if len(record) < 14:
        raise ValueError("Invalid WMF ExtTextOut record.")
    string_length = struct.unpack_from("<H", record, 10)[0]
    string_start = _exttextout_string_start(record)
    string_end = string_start + string_length
    if string_end > len(record):
        raise ValueError("Invalid WMF ExtTextOut string.")
    if string_length == 0:
        return None
    return _decode_text(record[string_start:string_end], encoding)


def _exttextout_string_start(record: bytes) -> int:
    options = struct.unpack_from("<H", record, 12)[0]
    return 14 + (8 if options & (ETO_CLIPPED | ETO_OPAQUE) else 0)


def _exttextout_with_text(record: bytes, replacement: str, encoding: str) -> bytes:
    replacement_bytes = _encode_text(replacement, encoding)
    updated = bytearray(record[: _exttextout_string_start(record)])
    updated.extend(replacement_bytes)
    if len(replacement_bytes) % 2:
        updated.append(0)
    # Drop optional per-character advances: their old count may not match a translation.
    struct.pack_into("<H", updated, 10, len(replacement_bytes))
    struct.pack_into("<I", updated, 0, len(updated) // 2)
    return bytes(updated)


def _decode_text(data: bytes, encoding: str) -> str:
    try:
        return data.decode(encoding)
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _encode_text(text: str, encoding: str) -> bytes:
    try:
        return text.encode(encoding)
    except UnicodeEncodeError as error:
        raise ValueError("Replacement text cannot be encoded in this WMF record.") from error
