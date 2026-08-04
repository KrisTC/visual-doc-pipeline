"""Replace native text records in SVG, EMF, and WMF without rasterization."""

from __future__ import annotations

from collections.abc import Callable
import base64
from io import BytesIO
import struct
import xml.etree.ElementTree as ElementTree

from PIL import Image
from pipeline.vector_text.common import VectorReplacementResult
from pipeline.text_replacement import TextReplacementProvider


_EMR_EXTTEXTOUTA = 83
_EMR_EXTTEXTOUTW = 84
_EMR_STRETCHDIBITS = 81
_META_EXTTEXTOUT = 0x0A32
_META_TEXTOUT = 0x0521
_META_CREATEFONTINDIRECT = 0x02FB
_META_SELECTOBJECT = 0x012D
_META_DELETEOBJECT = 0x01F0
_META_STRETCHDIB = 0x0F43
_META_PLACEABLE_KEY = b"\xd7\xcd\xc6\x9a"
_ETO_CLIPPED = 0x0004
_ETO_OPAQUE = 0x0002
_SVG_TEXT_ELEMENT_NAMES = frozenset({"text", "tspan", "textPath"})


def replace_vector_text(
    data: bytes,
    extension: str,
    replace_text: Callable[[str], str],
    source_language: str,
    replace_image: Callable[[Image.Image], int] | None = None,
    *,
    document_text_layout: str = "preserve-source-formatting",
    replacement_provider: TextReplacementProvider | None = None,
    target_language: str | None = None,
) -> VectorReplacementResult:
    """Replace editable vector text for ``extension`` without OCR or rasterization."""
    normalised_extension = extension.lower()
    if normalised_extension == ".svg":
        from pipeline.vector_text.svg import replace_svg
        return replace_svg(
            data,
            replace_text,
            replace_image,
            document_text_layout=document_text_layout,
            replacement_provider=replacement_provider,
            source_language=source_language,
            target_language=target_language,
        )
    if normalised_extension == ".emf":
        from pipeline.vector_text.emf import replace_emf
        return replace_emf(
            data, replace_text, replace_image,
            document_text_layout=document_text_layout,
            replacement_provider=replacement_provider,
            source_language=source_language, target_language=target_language,
        )
    if normalised_extension == ".wmf":
        from pipeline.vector_text.wmf import replace_wmf
        return replace_wmf(
            data, replace_text, source_language, replace_image,
            document_text_layout=document_text_layout,
            replacement_provider=replacement_provider, target_language=target_language,
        )
    raise ValueError(f"Unsupported vector graphic extension: {extension}")


def _replace_svg_text(
    data: bytes,
    replace_text: Callable[[str], str],
    replace_image: Callable[[Image.Image], int] | None,
) -> VectorReplacementResult:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise ValueError("Invalid SVG image.") from error
    replaced_items, replaced_regions, has_bitmaps = _replace_svg_element(
        root, False, replace_text, replace_image
    )
    if not replaced_items and not replaced_regions:
        return VectorReplacementResult(data, 0, False)
    return VectorReplacementResult(
        ElementTree.tostring(root, encoding="utf-8", xml_declaration=True),
        replaced_items,
        bool(replaced_items),
        replaced_regions,
        has_bitmaps,
    )


def _replace_svg_element(
    element: ElementTree.Element,
    inside_text: bool,
    replace_text: Callable[[str], str],
    replace_image: Callable[[Image.Image], int] | None,
) -> tuple[int, int, bool]:
    is_text_element = _local_name(element.tag) in _SVG_TEXT_ELEMENT_NAMES
    text_context = inside_text or is_text_element
    replaced_items = 0
    replaced_regions = 0
    has_bitmaps = False
    if text_context and element.text:
        element.text = replace_text(element.text)
        replaced_items += 1
    if _local_name(element.tag) == "image" and replace_image is not None:
        replaced_regions, has_bitmaps = _replace_svg_data_image(element, replace_image)
    for child in element:
        child_items, child_regions, child_bitmaps = _replace_svg_element(
            child, text_context, replace_text, replace_image
        )
        replaced_items += child_items
        replaced_regions += child_regions
        has_bitmaps = has_bitmaps or child_bitmaps
        if text_context and child.tail:
            child.tail = replace_text(child.tail)
            replaced_items += 1
    return replaced_items, replaced_regions, has_bitmaps


def _replace_svg_data_image(
    element: ElementTree.Element, replace_image: Callable[[Image.Image], int]
) -> tuple[int, bool]:
    href = element.attrib.get("href") or element.attrib.get("{http://www.w3.org/1999/xlink}href")
    if href is None or not href.startswith("data:image/") or ";base64," not in href:
        return 0, False
    metadata, encoded = href.split(",", 1)
    mime_type = metadata[5:].split(";", 1)[0].lower()
    formats = {"image/png": "PNG", "image/jpeg": "JPEG", "image/gif": "GIF", "image/bmp": "BMP", "image/tiff": "TIFF", "image/webp": "WEBP"}
    format_name = formats.get(mime_type)
    if format_name is None:
        return 0, False
    try:
        image_data = base64.b64decode(encoded, validate=True)
        with Image.open(BytesIO(image_data)) as opened:
            image = opened.copy()
    except (OSError, ValueError):
        return 0, False
    replaced_regions = replace_image(image)
    if replaced_regions:
        output = BytesIO()
        image.save(output, format=format_name)
        attribute = "href" if "href" in element.attrib else "{http://www.w3.org/1999/xlink}href"
        element.attrib[attribute] = f"data:{mime_type};base64," + base64.b64encode(output.getvalue()).decode("ascii")
    return replaced_regions, True


def _local_name(tag: str) -> str:
    return tag.rpartition("}")[2]


def _replace_emf_text(
    data: bytes,
    replace_text: Callable[[str], str],
    replace_image: Callable[[Image.Image], int] | None,
    *,
    document_text_layout: str = "preserve-source-formatting",
    replacement_provider: TextReplacementProvider | None = None,
    source_language: str = "",
    target_language: str | None = None,
) -> VectorReplacementResult:
    if len(data) < 8:
        raise ValueError("Invalid EMF image.")
    records: list[bytes] = []
    offset = 0
    replaced_items = 0
    replaced_image_regions = 0
    has_editable_text = False
    has_embedded_bitmaps = False
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError("Invalid EMF record header.")
        record_type, record_size = struct.unpack_from("<II", data, offset)
        if record_size < 8 or offset + record_size > len(data):
            raise ValueError("Invalid EMF record size.")
        record = data[offset : offset + record_size]
        if record_type in {_EMR_EXTTEXTOUTA, _EMR_EXTTEXTOUTW}:
            record, changed, editable = _replace_emf_exttext_record(
                record, record_type, replace_text,
                document_text_layout=document_text_layout,
                replacement_provider=replacement_provider,
                source_language=source_language,
                target_language=target_language,
            )
            replaced_items += changed
            has_editable_text = has_editable_text or editable
        elif record_type == _EMR_STRETCHDIBITS and replace_image is not None:
            record, replaced_regions, has_bitmap = _replace_emf_stretchdibits_record(
                record, replace_image
            )
            replaced_image_regions += replaced_regions
            has_embedded_bitmaps = has_embedded_bitmaps or has_bitmap
        records.append(record)
        offset += record_size
    result = bytearray(b"".join(records))
    if has_editable_text and len(result) >= 52:
        struct.pack_into("<I", result, 48, len(result))
    return VectorReplacementResult(
        bytes(result),
        replaced_items,
        has_editable_text,
        replaced_image_regions,
        has_embedded_bitmaps,
    )


def _replace_emf_stretchdibits_record(
    record: bytes,
    replace_image: Callable[[Image.Image], int],
) -> tuple[bytes, int, bool]:
    """Apply the shared raster handler to one EMR_STRETCHDIBITS DIB payload."""
    bitmap_info_offset_offset = 48
    bitmap_info_size_offset = 52
    bitmap_bits_offset_offset = 56
    bitmap_bits_size_offset = 60
    fixed_record_size = 80
    if len(record) < fixed_record_size:
        raise ValueError("Invalid EMF stretch-DIB record.")
    bitmap_info_offset = struct.unpack_from("<I", record, bitmap_info_offset_offset)[0]
    bitmap_info_size = struct.unpack_from("<I", record, bitmap_info_size_offset)[0]
    bitmap_bits_offset = struct.unpack_from("<I", record, bitmap_bits_offset_offset)[0]
    bitmap_bits_size = struct.unpack_from("<I", record, bitmap_bits_size_offset)[0]
    if bitmap_info_size == 0 or bitmap_bits_size == 0:
        return record, 0, False
    bitmap_info_end = bitmap_info_offset + bitmap_info_size
    bitmap_bits_end = bitmap_bits_offset + bitmap_bits_size
    if (
        bitmap_info_offset < fixed_record_size
        or bitmap_bits_offset < fixed_record_size
        or bitmap_info_end > len(record)
        or bitmap_bits_end > len(record)
    ):
        raise ValueError("Invalid EMF stretch-DIB bitmap offsets.")
    bitmap_file = _bitmap_file_from_dib(
        record[bitmap_info_offset:bitmap_info_end], record[bitmap_bits_offset:bitmap_bits_end]
    )
    with Image.open(BytesIO(bitmap_file)) as opened:
        image = opened.copy()
    replaced_regions = replace_image(image)
    if replaced_regions == 0:
        return record, 0, True
    bitmap_info, bitmap_bits = _dib_from_bitmap_image(image)
    payload_end = max(bitmap_info_end, bitmap_bits_end)
    updated = bytearray(record[:bitmap_info_offset])
    updated_info_offset = len(updated)
    updated.extend(bitmap_info)
    updated_bits_offset = len(updated)
    updated.extend(bitmap_bits)
    updated.extend(record[payload_end:])
    padding = (-len(updated)) % 4
    if padding:
        updated.extend(b"\0" * padding)
    struct.pack_into("<I", updated, bitmap_info_offset_offset, updated_info_offset)
    struct.pack_into("<I", updated, bitmap_info_size_offset, len(bitmap_info))
    struct.pack_into("<I", updated, bitmap_bits_offset_offset, updated_bits_offset)
    struct.pack_into("<I", updated, bitmap_bits_size_offset, len(bitmap_bits))
    struct.pack_into("<I", updated, 4, len(updated))
    return bytes(updated), replaced_regions, True


def _bitmap_file_from_dib(bitmap_info: bytes, bitmap_bits: bytes) -> bytes:
    pixel_offset = 14 + len(bitmap_info)
    size = pixel_offset + len(bitmap_bits)
    return struct.pack("<2sIHHI", b"BM", size, 0, 0, pixel_offset) + bitmap_info + bitmap_bits


def _dib_from_bitmap_image(image: Image.Image) -> tuple[bytes, bytes]:
    bitmap = BytesIO()
    image.convert("RGB").save(bitmap, format="BMP")
    bitmap_data = bitmap.getvalue()
    pixel_offset = struct.unpack_from("<I", bitmap_data, 10)[0]
    return bitmap_data[14:pixel_offset], bitmap_data[pixel_offset:]


def _replace_emf_exttext_record(
    record: bytes,
    record_type: int,
    replace_text: Callable[[str], str],
    *,
    document_text_layout: str = "preserve-source-formatting",
    replacement_provider: TextReplacementProvider | None = None,
    source_language: str = "",
    target_language: str | None = None,
) -> tuple[bytes, int, bool]:
    emr_text_offset = 36
    string_length_offset = emr_text_offset + 8
    string_offset_offset = emr_text_offset + 12
    dx_offset_offset = emr_text_offset + 36
    if len(record) < dx_offset_offset + 4:
        raise ValueError("Invalid EMF text record.")
    character_count = struct.unpack_from("<I", record, string_length_offset)[0]
    string_offset = struct.unpack_from("<I", record, string_offset_offset)[0]
    encoding = "utf-16-le" if record_type == _EMR_EXTTEXTOUTW else "latin-1"
    unit_size = 2 if record_type == _EMR_EXTTEXTOUTW else 1
    string_size = character_count * unit_size
    string_end = string_offset + string_size
    if string_offset < dx_offset_offset + 4 or string_end > len(record):
        raise ValueError("Invalid EMF text string offset.")
    if character_count == 0:
        return record, 0, False
    try:
        source_text = record[string_offset:string_end].decode(encoding)
    except UnicodeDecodeError as error:
        raise ValueError("Unsupported EMF text encoding.") from error
    replacement = replace_text(source_text)
    fitted_scale = 1.0
    if (
        document_text_layout in {"preserve-basic-layout", "preserve-basic-layout-source-font"}
        and replacement_provider is not None
        and target_language is not None
    ):
        # EMR_EXTTEXTOUT stores a finite clipping rectangle when ETO_CLIPPED
        # is present.  The record's X/Y scale is the only local, safe way to
        # change text size without altering the selected GDI font object.
        options = struct.unpack_from("<I", record, emr_text_offset + 16)[0]
        if options & _ETO_CLIPPED:
            left, top, right, bottom = struct.unpack_from("<iiii", record, emr_text_offset + 20)
            width, height = abs(right - left), abs(bottom - top)
            if width and height:
                from pipeline.bounded_text_layout import (
                    BoundedTextBox, BoundedTextParagraph, BoundedTextRun,
                    noto_typefaces, replace_and_fit_text_box,
                )
                box = BoundedTextBox(width * 9_525, height * 9_525, 0, 0, 0, 0, None,
                    (BoundedTextParagraph("left", None, None, None, None, 0, None, None,
                                          None, None, None,
                                          (BoundedTextRun(source_text, None, "sans-serif", 12.0,
                                                          False, False, "none", None),)),))
                fitted = replace_and_fit_text_box(
                    box, replacement_provider, source_language, target_language, noto_typefaces(),
                    preserve_source_font_family=True,
                )
                replacement = fitted.text_box.paragraphs[0].runs[0].text
                fitted_scale = fitted.font_scale
    try:
        replacement_bytes = replacement.encode(encoding)
    except UnicodeEncodeError as error:
        raise ValueError("Replacement text cannot be encoded in this EMF record.") from error
    replacement_character_count = len(replacement_bytes) // unit_size
    updated = bytearray(record[:string_offset] + replacement_bytes + record[string_end:])
    byte_delta = len(replacement_bytes) - string_size
    struct.pack_into("<I", updated, string_length_offset, replacement_character_count)
    if fitted_scale != 1.0:
        for scale_offset in (28, 32):
            scale = struct.unpack_from("<f", record, scale_offset)[0]
            struct.pack_into("<f", updated, scale_offset, (scale or 1.0) * fitted_scale)
    old_dx_offset = struct.unpack_from("<I", record, dx_offset_offset)[0]
    if old_dx_offset and replacement_character_count == character_count:
        if old_dx_offset > string_offset:
            struct.pack_into("<I", updated, dx_offset_offset, old_dx_offset + byte_delta)
    elif old_dx_offset:
        # Explicit advances no longer match the replacement's character count.
        struct.pack_into("<I", updated, dx_offset_offset, 0)
    padding = (-len(updated)) % 4
    if padding:
        updated.extend(b"\0" * padding)
    struct.pack_into("<I", updated, 4, len(updated))
    return bytes(updated), 1, True


def _replace_wmf_text(
    data: bytes,
    replace_text: Callable[[str], str],
    source_language: str,
    replace_image: Callable[[Image.Image], int] | None,
    *,
    document_text_layout: str = "preserve-source-formatting",
    replacement_provider: TextReplacementProvider | None = None,
    target_language: str | None = None,
) -> VectorReplacementResult:
    header_offset = 22 if data.startswith(_META_PLACEABLE_KEY) else 0
    if len(data) < header_offset + 4:
        raise ValueError("Invalid WMF image.")
    header_words = struct.unpack_from("<H", data, header_offset + 2)[0]
    if header_words < 9:
        raise ValueError("Invalid WMF header size.")
    records_offset = header_offset + (header_words * 2)
    if len(data) < records_offset:
        raise ValueError("Invalid WMF image.")
    records: list[bytes] = [data[:records_offset]]
    offset = records_offset
    replaced_items = 0
    has_editable_text = False
    replaced_image_regions = 0
    has_embedded_bitmaps = False
    occupied_handles: set[int] = set()
    font_records: dict[int, bytes] = {}
    selected_font: int | None = None
    encoding = "cp932" if source_language.lower().replace("_", "-").startswith("ja") else "latin-1"
    while offset < len(data):
        if offset + 6 > len(data):
            raise ValueError("Invalid WMF record header.")
        record_words, record_function = struct.unpack_from("<IH", data, offset)
        record_size = record_words * 2
        if record_words < 3 or offset + record_size > len(data):
            raise ValueError("Invalid WMF record size.")
        record = data[offset : offset + record_size]
        if record_function == _META_CREATEFONTINDIRECT:
            handle = _wmf_next_handle(occupied_handles)
            occupied_handles.add(handle)
            font_records[handle] = record
        elif record_function == _META_SELECTOBJECT and len(record) >= 8:
            selected = struct.unpack_from("<H", record, 6)[0]
            selected_font = selected if selected in font_records else None
        elif record_function == _META_DELETEOBJECT and len(record) >= 8:
            handle = struct.unpack_from("<H", record, 6)[0]
            occupied_handles.discard(handle)
            font_records.pop(handle, None)
            if selected_font == handle:
                selected_font = None
        if record_function == _META_TEXTOUT:
            record, changed, editable = _replace_wmf_textout_record(
                record, replace_text, encoding
            )
            replaced_items += changed
            has_editable_text = has_editable_text or editable
        elif record_function == _META_EXTTEXTOUT:
            fitted = _wmf_fitted_exttextout(
                record, encoding, document_text_layout, replacement_provider,
                source_language, target_language,
            )
            clone_handle: int | None = None
            if fitted is not None and selected_font is not None and selected_font in font_records:
                replacement, scale = fitted
                clone = _wmf_scaled_font_record(font_records[selected_font], scale)
                clone_handle = _wmf_next_handle(occupied_handles)
                occupied_handles.add(clone_handle)
                records.append(clone)
                records.append(_wmf_select_object_record(clone_handle))
                record, changed, editable = _replace_wmf_exttextout_record(
                    record, replace_text, encoding, replacement_override=replacement
                )
            else:
                record, changed, editable = _replace_wmf_exttextout_record(
                    record, replace_text, encoding
                )
            replaced_items += changed
            has_editable_text = has_editable_text or editable
            if clone_handle is not None and selected_font is not None:
                records.append(record)
                records.append(_wmf_select_object_record(selected_font))
                records.append(_wmf_delete_object_record(clone_handle))
                occupied_handles.discard(clone_handle)
                offset += record_size
                continue
        elif record_function == _META_STRETCHDIB and replace_image is not None:
            record, replaced_regions, has_bitmap = _replace_wmf_stretchdib_record(record, replace_image)
            replaced_image_regions += replaced_regions
            has_embedded_bitmaps = has_embedded_bitmaps or has_bitmap
        records.append(record)
        offset += record_size
        if record_function == 0:
            records.append(data[offset:])
            break
    result = bytearray(b"".join(records))
    if has_editable_text:
        struct.pack_into("<I", result, header_offset + 6, len(result) // 2)
    return VectorReplacementResult(bytes(result), replaced_items, has_editable_text, replaced_image_regions, has_embedded_bitmaps)


def _wmf_fitted_exttextout(
    record: bytes, encoding: str, document_text_layout: str,
    provider: TextReplacementProvider | None, source_language: str, target_language: str | None,
) -> tuple[str, float] | None:
    if (document_text_layout not in {"preserve-basic-layout", "preserve-basic-layout-source-font"}
            or provider is None or target_language is None or len(record) < 22):
        return None
    string_length = struct.unpack_from("<H", record, 10)[0]
    options = struct.unpack_from("<H", record, 12)[0]
    if not options & _ETO_CLIPPED:
        return None
    left, top, right, bottom = struct.unpack_from("<hhhh", record, 14)
    width, height = abs(right - left), abs(bottom - top)
    string_start = 22
    string_end = string_start + string_length
    if not width or not height or string_end > len(record):
        return None
    source_text = _decode_wmf_text(record[string_start:string_end], encoding)
    if not source_text.strip():
        return None
    from pipeline.bounded_text_layout import (
        BoundedTextBox, BoundedTextParagraph, BoundedTextRun, noto_typefaces, replace_and_fit_text_box,
    )
    box = BoundedTextBox(width * 9_525, height * 9_525, 0, 0, 0, 0, None,
        (BoundedTextParagraph("left", None, None, None, None, 0, None, None, None, None, None,
                              (BoundedTextRun(source_text, None, "sans-serif", 12.0, False, False, "none", None),)),))
    fitted = replace_and_fit_text_box(box, provider, source_language, target_language, noto_typefaces(),
                                      preserve_source_font_family=True)
    return fitted.text_box.paragraphs[0].runs[0].text, fitted.font_scale


def _wmf_next_handle(occupied: set[int]) -> int:
    handle = 0
    while handle in occupied:
        handle += 1
    return handle


def _wmf_scaled_font_record(record: bytes, scale: float) -> bytes:
    if len(record) < 10:
        return record
    output = bytearray(record)
    height = struct.unpack_from("<h", output, 6)[0]
    if height:
        struct.pack_into("<h", output, 6, max(-32768, min(32767, round(height * scale))))
    return bytes(output)


def _wmf_select_object_record(handle: int) -> bytes:
    return struct.pack("<IHH", 4, _META_SELECTOBJECT, handle)


def _wmf_delete_object_record(handle: int) -> bytes:
    return struct.pack("<IHH", 4, _META_DELETEOBJECT, handle)


def _replace_wmf_stretchdib_record(record: bytes, replace_image: Callable[[Image.Image], int]) -> tuple[bytes, int, bool]:
    dib_offset = 28
    if len(record) <= dib_offset:
        return record, 0, False
    dib = record[dib_offset:]
    if len(dib) < 40 or struct.unpack_from("<I", dib, 0)[0] != 40 or struct.unpack_from("<I", dib, 16)[0] != 0:
        return record, 0, False
    bit_count = struct.unpack_from("<H", dib, 14)[0]
    colours_used = struct.unpack_from("<I", dib, 32)[0]
    colour_table_size = colours_used or ((1 << bit_count) if bit_count <= 8 else 0)
    bitmap_info_size = 40 + (colour_table_size * 4)
    if bitmap_info_size > len(dib):
        return record, 0, False
    with Image.open(BytesIO(_bitmap_file_from_dib(dib[:bitmap_info_size], dib[bitmap_info_size:])) ) as opened:
        image = opened.copy()
    replaced_regions = replace_image(image)
    if not replaced_regions:
        return record, 0, True
    bitmap_info, bitmap_bits = _dib_from_bitmap_image(image)
    updated = bytearray(record[:dib_offset] + bitmap_info + bitmap_bits)
    if len(updated) % 2:
        updated.append(0)
    struct.pack_into("<I", updated, 0, len(updated) // 2)
    return bytes(updated), replaced_regions, True


def _replace_wmf_textout_record(
    record: bytes,
    replace_text: Callable[[str], str],
    encoding: str,
) -> tuple[bytes, int, bool]:
    if len(record) < 12:
        raise ValueError("Invalid WMF TextOut record.")
    string_length = struct.unpack_from("<H", record, 6)[0]
    string_start = 8
    string_end = string_start + string_length
    string_padding = string_length % 2
    if string_end + string_padding + 4 > len(record):
        raise ValueError("Invalid WMF TextOut string.")
    if string_length == 0:
        return record, 0, False
    source_text = _decode_wmf_text(record[string_start:string_end], encoding)
    replacement_bytes = _encode_wmf_text(replace_text(source_text), encoding)
    trailing_position = string_end + string_padding
    updated = bytearray(record[:6])
    updated.extend(struct.pack("<H", len(replacement_bytes)))
    updated.extend(replacement_bytes)
    if len(replacement_bytes) % 2:
        updated.append(0)
    updated.extend(record[trailing_position:])
    struct.pack_into("<I", updated, 0, len(updated) // 2)
    return bytes(updated), 1, True


def _replace_wmf_exttextout_record(
    record: bytes,
    replace_text: Callable[[str], str],
    encoding: str,
    *,
    replacement_override: str | None = None,
) -> tuple[bytes, int, bool]:
    if len(record) < 14:
        raise ValueError("Invalid WMF ExtTextOut record.")
    string_length = struct.unpack_from("<H", record, 10)[0]
    options = struct.unpack_from("<H", record, 12)[0]
    string_start = 14 + (8 if options & (_ETO_CLIPPED | _ETO_OPAQUE) else 0)
    string_end = string_start + string_length
    if string_end > len(record):
        raise ValueError("Invalid WMF ExtTextOut string.")
    if string_length == 0:
        return record, 0, False
    source_text = _decode_wmf_text(record[string_start:string_end], encoding)
    replacement_bytes = _encode_wmf_text(
        replacement_override if replacement_override is not None else replace_text(source_text), encoding
    )
    updated = bytearray(record[:string_start])
    updated.extend(replacement_bytes)
    if len(replacement_bytes) % 2:
        updated.append(0)
    # Drop optional per-character advances: their old count may not match a translation.
    struct.pack_into("<H", updated, 10, len(replacement_bytes))
    struct.pack_into("<I", updated, 0, len(updated) // 2)
    return bytes(updated), 1, True


def _decode_wmf_text(data: bytes, encoding: str) -> str:
    try:
        return data.decode(encoding)
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _encode_wmf_text(text: str, encoding: str) -> bytes:
    try:
        return text.encode(encoding)
    except UnicodeEncodeError as error:
        raise ValueError("Replacement text cannot be encoded in this WMF record.") from error
