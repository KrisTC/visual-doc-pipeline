"""Replace native text records in SVG, EMF, and WMF without rasterization."""

from __future__ import annotations

from collections.abc import Callable
import base64
from dataclasses import dataclass
from io import BytesIO
import struct
from typing import TYPE_CHECKING
import xml.etree.ElementTree as ElementTree

from PIL import Image
# skia-python does not publish PEP 561 stubs; this is the native measurement boundary.
import skia  # type: ignore[import-not-found]
from pipeline.vector_text.common import VectorReplacementResult
from pipeline.text_replacement import TextReplacementProvider

if TYPE_CHECKING:
    from pipeline.bounded_text_layout import BoundedTextBox


_EMR_EXTTEXTOUTA = 83
_EMR_EXTTEXTOUTW = 84
_EMR_STRETCHDIBITS = 81
_EMR_SETWINDOWEXTEX = 9
_EMR_SETWINDOWORGEX = 10
_EMR_SETVIEWPORTEXTEX = 11
_EMR_SETVIEWPORTORGEX = 12
_EMR_SETWORLDTRANSFORM = 35
_EMR_MODIFYWORLDTRANSFORM = 36
_EMR_SELECTOBJECT = 37
_EMR_DELETEOBJECT = 40
_EMR_SETTEXTALIGN = 22
_EMR_MOVETOEX = 27
_EMR_LINETO = 54
_EMR_EXTCREATEFONTINDIRECTW = 82
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
_TA_ALIGNMENT_MASK = 0x0006
_TA_RIGHT = 0x0002
_TA_CENTER = 0x0006
_EMU_PER_EMF_UNIT = 9_525
_POINTS_PER_EMF_UNIT = 72.0 / 96.0
_EMF_SOURCE_BOUNDS_TOLERANCE = 1.5
_EMF_SOURCE_BOUNDS_ROUNDING_TOLERANCE = 1


@dataclass(frozen=True, slots=True)
class _EmfRectangle:
    """An axis-aligned rectangle in the current EMF logical coordinate system."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True, slots=True)
class _EmfFont:
    """The subset of a selected LOGFONTW needed for fitting one text record."""

    family: str
    size_points: float
    bold: bool
    italic: bool


@dataclass(frozen=True, slots=True)
class _EmfTextFitContext:
    """Safe source geometry and typography for one un-clipped EMF text record."""

    source_bounds: _EmfRectangle
    fitting_bounds: _EmfRectangle
    font: _EmfFont
    font_handle: int
    font_record: bytes
    source_text: str


@dataclass(frozen=True, slots=True)
class _EmfTextCandidate:
    """A source text record collected before any EMF replacement is written."""

    offset: int
    bounds: _EmfRectangle
    text: str
    font: _EmfFont | None
    font_handle: int | None
    font_record: bytes | None
    text_alignment: int
    coordinate_system_safe: bool


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
    fitted_contexts = (
        _emf_unclipped_fit_contexts(
            data,
            measure_source_fonts=document_text_layout == "preserve-basic-layout-source-font",
        )
        if document_text_layout
        in {"preserve-basic-layout", "preserve-basic-layout-source-font"}
        else {}
    )
    records: list[bytes] = []
    scaled_fonts: list[bytes] = []
    next_font_handle = _emf_next_font_handle(data)
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
            context = fitted_contexts.get(offset)
            record, changed, editable, fitted_scale = _replace_emf_exttext_record(
                record, record_type, replace_text,
                document_text_layout=document_text_layout,
                replacement_provider=replacement_provider,
                source_language=source_language,
                target_language=target_language,
                unclipped_fit_context=context,
            )
            replaced_items += changed
            has_editable_text = has_editable_text or editable
            if context is not None and 0.0 < fitted_scale < 1.0:
                scaled_font = _emf_scaled_font_record(
                    context.font_record, next_font_handle, fitted_scale
                )
                scaled_fonts.append(scaled_font)
                records.extend((
                    _emf_select_object_record(next_font_handle),
                    record,
                    _emf_select_object_record(context.font_handle),
                ))
                next_font_handle += 1
                offset += record_size
                continue
        elif record_type == _EMR_STRETCHDIBITS and replace_image is not None:
            record, replaced_regions, has_bitmap = _replace_emf_stretchdibits_record(
                record, replace_image
            )
            replaced_image_regions += replaced_regions
            has_embedded_bitmaps = has_embedded_bitmaps or has_bitmap
        records.append(record)
        offset += record_size
    if scaled_fonts:
        records[1:1] = scaled_fonts
    result = bytearray(b"".join(records))
    if has_editable_text and len(result) >= 56:
        struct.pack_into("<I", result, 48, len(result))
        struct.pack_into("<I", result, 52, _emf_record_count(result))
        struct.pack_into("<H", result, 56, next_font_handle)
    return VectorReplacementResult(
        bytes(result),
        replaced_items,
        has_editable_text,
        replaced_image_regions,
        has_embedded_bitmaps,
    )


def _emf_unclipped_fit_contexts(
    data: bytes, *, measure_source_fonts: bool
) -> dict[int, _EmfTextFitContext]:
    """Collect conservative measured bounds for eligible un-clipped EMF text."""
    candidates: list[_EmfTextCandidate] = []
    source_rectangles: list[tuple[int, _EmfRectangle]] = []
    lines: list[tuple[tuple[int, int], tuple[int, int]]] = []
    fonts: dict[int, _EmfFont] = {}
    font_records: dict[int, bytes] = {}
    selected_font: _EmfFont | None = None
    selected_font_handle: int | None = None
    text_alignment = 0
    current_position: tuple[int, int] | None = None
    coordinate_system_safe = True
    offset = 0
    while offset < len(data):
        if offset + 8 > len(data):
            return {}
        record_type, record_size = struct.unpack_from("<II", data, offset)
        if record_size < 8 or offset + record_size > len(data):
            return {}
        record = data[offset : offset + record_size]
        if record_type == _EMR_EXTCREATEFONTINDIRECTW:
            font = _emf_font(record)
            if font is not None:
                handle = struct.unpack_from("<I", record, 8)[0]
                fonts[handle] = font
                font_records[handle] = record
        elif record_type == _EMR_SELECTOBJECT and len(record) >= 12:
            handle = struct.unpack_from("<I", record, 8)[0]
            selected = fonts.get(handle)
            if selected is not None:
                selected_font = selected
                selected_font_handle = handle
        elif record_type == _EMR_DELETEOBJECT and len(record) >= 12:
            handle = struct.unpack_from("<I", record, 8)[0]
            deleted_font = fonts.pop(handle, None)
            font_records.pop(handle, None)
            if deleted_font == selected_font:
                selected_font = None
                selected_font_handle = None
        elif record_type == _EMR_SETTEXTALIGN and len(record) >= 12:
            text_alignment = struct.unpack_from("<I", record, 8)[0]
        elif record_type == _EMR_MOVETOEX and len(record) >= 16:
            current_position = struct.unpack_from("<ii", record, 8)
        elif record_type == _EMR_LINETO and len(record) >= 16:
            end = struct.unpack_from("<ii", record, 8)
            if current_position is not None:
                lines.append((current_position, end))
            current_position = end
        elif record_type in {_EMR_SETWORLDTRANSFORM, _EMR_MODIFYWORLDTRANSFORM}:
            coordinate_system_safe = False
        elif record_type in {
            _EMR_SETWINDOWEXTEX,
            _EMR_SETWINDOWORGEX,
            _EMR_SETVIEWPORTEXTEX,
            _EMR_SETVIEWPORTORGEX,
        } and not _emf_coordinate_record_is_noop(record_type, record):
            coordinate_system_safe = False

        if record_type in {_EMR_EXTTEXTOUTA, _EMR_EXTTEXTOUTW}:
            bounds = _emf_record_bounds(record)
            if bounds is not None:
                source_rectangles.append((offset, bounds))
            candidate = _emf_text_candidate(
                offset, record, record_type, selected_font, selected_font_handle,
                None if selected_font_handle is None else font_records.get(selected_font_handle), text_alignment,
                coordinate_system_safe,
            )
            if candidate is not None:
                candidates.append(candidate)
        offset += record_size

    result: dict[int, _EmfTextFitContext] = {}
    for candidate in candidates:
        if not _eligible_unclipped_emf_candidate(candidate):
            continue
        measured_bounds = _emf_measured_source_bounds(candidate, measure_source_fonts)
        if measured_bounds is None:
            continue
        fitting_bounds = _emf_expand_fitting_bounds(
            measured_bounds,
            candidate.text_alignment,
            tuple(
                rectangle
                for other_offset, rectangle in source_rectangles
                if other_offset != candidate.offset
            ),
            lines,
        )
        if fitting_bounds is None:
            continue
        assert candidate.font is not None
        assert candidate.font_handle is not None
        assert candidate.font_record is not None
        result[candidate.offset] = _EmfTextFitContext(
            candidate.bounds, fitting_bounds, candidate.font, candidate.font_handle,
            candidate.font_record, candidate.text,
        )
    return result


def _emf_record_bounds(record: bytes) -> _EmfRectangle | None:
    """Return a text record's non-degenerate rendered bounds when present."""
    if len(record) < 24:
        return None
    bounds = _EmfRectangle(*struct.unpack_from("<iiii", record, 8))
    return bounds if bounds.width > 0 and bounds.height > 0 else None


def _emf_coordinate_record_is_noop(record_type: int, record: bytes) -> bool:
    """Accept only EMF coordinate-state records that retain the default mapping."""
    if record_type in {_EMR_SETWINDOWORGEX, _EMR_SETVIEWPORTORGEX}:
        return len(record) >= 16 and struct.unpack_from("<ii", record, 8) == (0, 0)
    return False


def _emf_font(record: bytes) -> _EmfFont | None:
    """Decode a directly created LOGFONTW without reading an external font resource."""
    logfont_offset = 12
    face_offset = logfont_offset + 28
    face_end = face_offset + 64
    if len(record) < face_end:
        return None
    height, _width, _escapement, _orientation, weight = struct.unpack_from(
        "<iiiii", record, logfont_offset
    )
    if height == 0:
        return None
    family = record[face_offset:face_end].decode("utf-16-le", errors="ignore").split("\0", 1)[0]
    if not family:
        return None
    return _EmfFont(
        family,
        abs(height) * _POINTS_PER_EMF_UNIT,
        weight >= 700,
        bool(record[logfont_offset + 20]),
    )


def _emf_next_font_handle(data: bytes) -> int:
    """Return an unused directly-created GDI font handle for this EMF."""
    handles: set[int] = set()
    offset = 0
    while offset + 8 <= len(data):
        record_type, record_size = struct.unpack_from("<II", data, offset)
        if record_size < 8 or offset + record_size > len(data):
            break
        if record_type == _EMR_EXTCREATEFONTINDIRECTW and record_size >= 12:
            handles.add(struct.unpack_from("<I", data, offset + 8)[0])
        offset += record_size
    declared_handle_count = struct.unpack_from("<H", data, 56)[0] if len(data) >= 58 else 0
    return max(declared_handle_count, max(handles, default=0) + 1)


def _emf_scaled_font_record(record: bytes, handle: int, scale: float) -> bytes:
    """Clone one directly-created LOGFONTW with a smaller rendered height."""
    if len(record) < 40 or not 0.0 < scale < 1.0:
        raise ValueError("Invalid EMF font scaling request.")
    result = bytearray(record)
    height = struct.unpack_from("<i", result, 12)[0]
    if height == 0:
        raise ValueError("Cannot scale an EMF font with no height.")
    # LOGFONT height is integral.  Rounding up can exceed a tightly fitted
    # horizontal bound.  Keep one additional logical unit of headroom because
    # PowerPoint renders the retained source GDI font, not the layout face.
    scaled_height = max(1, int(abs(height) * scale) - 1)
    struct.pack_into("<I", result, 8, handle)
    struct.pack_into("<i", result, 12, -scaled_height if height < 0 else scaled_height)
    return bytes(result)


def _emf_select_object_record(handle: int) -> bytes:
    return struct.pack("<III", _EMR_SELECTOBJECT, 12, handle)


def _emf_record_count(data: bytes | bytearray) -> int:
    """Count structurally valid records after adding local GDI font records."""
    count = 0
    offset = 0
    while offset + 8 <= len(data):
        _record_type, record_size = struct.unpack_from("<II", data, offset)
        if record_size < 8 or offset + record_size > len(data):
            raise ValueError("Invalid EMF record size.")
        count += 1
        offset += record_size
    if offset != len(data):
        raise ValueError("Invalid EMF trailing bytes.")
    return count


def _emf_text_candidate(
    offset: int,
    record: bytes,
    record_type: int,
    font: _EmfFont | None,
    font_handle: int | None,
    font_record: bytes | None,
    text_alignment: int,
    coordinate_system_safe: bool,
) -> _EmfTextCandidate | None:
    """Extract source-only EMF geometry without changing the record."""
    if len(record) < 76:
        return None
    bounds = _emf_record_bounds(record)
    character_count = struct.unpack_from("<I", record, 44)[0]
    string_offset = struct.unpack_from("<I", record, 48)[0]
    options = struct.unpack_from("<I", record, 52)[0]
    unit_size = 2 if record_type == _EMR_EXTTEXTOUTW else 1
    string_end = string_offset + (character_count * unit_size)
    if (
        bounds is None
        or options & _ETO_CLIPPED
        or string_offset < 76
        or string_end > len(record)
    ):
        return None
    try:
        text = record[string_offset:string_end].decode(
            "utf-16-le" if unit_size == 2 else "latin-1"
        )
    except UnicodeDecodeError:
        return None
    return _EmfTextCandidate(
        offset, bounds, text, font, font_handle, font_record, text_alignment,
        coordinate_system_safe
    )


def _eligible_unclipped_emf_candidate(candidate: _EmfTextCandidate) -> bool:
    """Reject any candidate whose record cannot provide a safe one-line source box."""
    return (
        candidate.coordinate_system_safe
        and candidate.font is not None
        and candidate.font_handle is not None
        and candidate.font_record is not None
        and candidate.bounds.width > 0
        and candidate.bounds.height > 0
        and bool(candidate.text.strip())
        and not any(character in candidate.text for character in "\r\n\v")
    )


def _emf_measured_source_bounds(
    candidate: _EmfTextCandidate, measure_source_fonts: bool
) -> _EmfRectangle | None:
    """Measure source text using the selected fitted-mode measurement face."""
    assert candidate.font is not None
    from pipeline.bounded_text_layout import (
        fit_explicit_noto_text_box,
        fitted_text_lines,
        noto_typefaces,
    )

    source_box = _emf_text_box(
        candidate.text,
        candidate.font,
        candidate.bounds.width * 10,
        candidate.bounds.height * 10,
    )
    measured = fit_explicit_noto_text_box(
        source_box,
        noto_typefaces(),
        preserve_source_font_family=True,
        measure_source_fonts=measure_source_fonts,
    )
    lines = fitted_text_lines(measured)
    if len(lines) != 1 or measured.font_scale != 1.0:
        return None
    measured_width = round(lines[0].width_pixels)
    measured_height = round(lines[0].height_pixels)
    if (
        measured_width <= 0
        or measured_height <= 0
        or measured_width > candidate.bounds.width * _EMF_SOURCE_BOUNDS_TOLERANCE
        or measured_height > candidate.bounds.height * _EMF_SOURCE_BOUNDS_TOLERANCE
    ):
        return None
    alignment = candidate.text_alignment & _TA_ALIGNMENT_MASK
    if alignment == _TA_RIGHT:
        right = candidate.bounds.right
        left = right - measured_width
    elif alignment == _TA_CENTER:
        center = (candidate.bounds.left + candidate.bounds.right) / 2.0
        left = round(center - (measured_width / 2.0))
        right = left + measured_width
    else:
        left = candidate.bounds.left
        right = left + measured_width
    if (
        left < candidate.bounds.left - _EMF_SOURCE_BOUNDS_ROUNDING_TOLERANCE
        or right > candidate.bounds.right + _EMF_SOURCE_BOUNDS_ROUNDING_TOLERANCE
    ):
        return None
    return _EmfRectangle(
        max(left, candidate.bounds.left),
        candidate.bounds.top,
        min(right, candidate.bounds.right),
        candidate.bounds.bottom,
    )


def _emf_text_box(
    text: str, font: _EmfFont, width: int, height: int
) -> BoundedTextBox:
    """Build one ordinary horizontal line for the shared bounded-text layout core."""
    from pipeline.bounded_text_layout import (
        BoundedTextBox,
        BoundedTextParagraph,
        BoundedTextRun,
        SourceTypefaceReference,
    )

    run = BoundedTextRun(
        text,
        font.family,
        "sans-serif",
        font.size_points,
        font.bold,
        font.italic,
        "none",
        None,
        (SourceTypefaceReference("latin", font.family),),
    )
    return BoundedTextBox(
        width * _EMU_PER_EMF_UNIT,
        height * _EMU_PER_EMF_UNIT,
        0,
        0,
        0,
        0,
        None,
        (BoundedTextParagraph("left", None, None, None, None, 0, None, None, None, None, None, (run,)),),
    )


def _emf_expand_fitting_bounds(
    source: _EmfRectangle,
    text_alignment: int,
    text_obstacles: tuple[_EmfRectangle, ...],
    lines: list[tuple[tuple[int, int], tuple[int, int]]],
) -> _EmfRectangle | None:
    """Expand a one-line EMF source rectangle only until a known obstacle."""
    left_stops: list[int] = []
    right_stops: list[int] = []
    for obstacle in text_obstacles:
        if not _overlaps(source.top, source.bottom, obstacle.top, obstacle.bottom):
            continue
        if obstacle.right <= source.left:
            left_stops.append(obstacle.right)
        elif obstacle.left >= source.right:
            right_stops.append(obstacle.left)
        else:
            return None
    for start, end in lines:
        if start[0] == end[0]:
            if _overlaps(source.top, source.bottom, min(start[1], end[1]), max(start[1], end[1])):
                if start[0] <= source.left:
                    left_stops.append(start[0])
                elif start[0] >= source.right:
                    right_stops.append(start[0])
                else:
                    return None
        elif start[1] == end[1] and source.top < start[1] < source.bottom:
            if _overlaps(source.left, source.right, min(start[0], end[0]), max(start[0], end[0])):
                return None
    left_limit = max(left_stops) if left_stops else source.left
    right_limit = min(right_stops) if right_stops else source.right
    alignment = text_alignment & _TA_ALIGNMENT_MASK
    if alignment == _TA_RIGHT:
        return _EmfRectangle(left_limit, source.top, source.right, source.bottom)
    if alignment == _TA_CENTER:
        expansion = min(source.left - left_limit, right_limit - source.right)
        return _EmfRectangle(source.left - expansion, source.top, source.right + expansion, source.bottom)
    return _EmfRectangle(source.left, source.top, right_limit, source.bottom)


def _overlaps(first_start: int, first_end: int, second_start: int, second_end: int) -> bool:
    """Return whether two positive-width coordinate intervals overlap."""
    return first_start < second_end and second_start < first_end


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
    unclipped_fit_context: _EmfTextFitContext | None = None,
) -> tuple[bytes, int, bool, float]:
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
        return record, 0, False, 1.0
    try:
        source_text = record[string_offset:string_end].decode(encoding)
    except UnicodeDecodeError as error:
        raise ValueError("Unsupported EMF text encoding.") from error
    fitted_replacement: tuple[str, float] | None = None
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
            fitted_replacement = _fit_clipped_emf_text(
                source_text,
                record,
                replacement_provider,
                source_language,
                target_language,
                document_text_layout == "preserve-basic-layout-source-font",
            )
        elif unclipped_fit_context is not None:
            fitted_replacement = _fit_unclipped_emf_text(
                source_text,
                unclipped_fit_context,
                replacement_provider,
                source_language,
                target_language,
                document_text_layout == "preserve-basic-layout-source-font",
            )
    if fitted_replacement is None:
        replacement = replace_text(source_text)
        fitted_scale = 1.0
    else:
        replacement, fitted_scale = fitted_replacement
    try:
        replacement_bytes = replacement.encode(encoding)
    except UnicodeEncodeError as error:
        raise ValueError("Replacement text cannot be encoded in this EMF record.") from error
    replacement_character_count = len(replacement_bytes) // unit_size
    updated = bytearray(record[:string_offset] + replacement_bytes + record[string_end:])
    byte_delta = len(replacement_bytes) - string_size
    struct.pack_into("<I", updated, string_length_offset, replacement_character_count)
    if fitted_scale != 1.0 and unclipped_fit_context is None:
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
    return bytes(updated), 1, True, fitted_scale


def _fit_clipped_emf_text(
    source_text: str,
    record: bytes,
    provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    measure_source_fonts: bool,
) -> tuple[str, float] | None:
    """Return the existing explicit-clip fit without a second provider request."""
    left, top, right, bottom = struct.unpack_from("<iiii", record, 56)
    width, height = abs(right - left), abs(bottom - top)
    if not width or not height:
        return None
    from pipeline.bounded_text_layout import (
        BoundedTextBox,
        BoundedTextParagraph,
        BoundedTextRun,
        noto_typefaces,
        replace_and_fit_text_box,
    )

    box = BoundedTextBox(
        width * _EMU_PER_EMF_UNIT,
        height * _EMU_PER_EMF_UNIT,
        0,
        0,
        0,
        0,
        None,
        (BoundedTextParagraph(
            "left", None, None, None, None, 0, None, None, None, None, None,
            (BoundedTextRun(source_text, None, "sans-serif", 12.0, False, False, "none", None),),
        ),),
    )
    fitted = replace_and_fit_text_box(
        box,
        provider,
        source_language,
        target_language,
        noto_typefaces(),
        preserve_source_font_family=True,
        measure_source_fonts=measure_source_fonts,
    )
    return fitted.text_box.paragraphs[0].runs[0].text, fitted.font_scale


def _fit_unclipped_emf_text(
    source_text: str,
    context: _EmfTextFitContext,
    provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    measure_source_fonts: bool,
) -> tuple[str, float] | None:
    """Fit one safe horizontal EMF line to its measured and expanded bounds."""
    from pipeline.bounded_text_layout import (
        noto_typefaces,
        replace_and_fit_text_box,
    )

    box = _emf_text_box(
        source_text,
        context.font,
        context.fitting_bounds.width,
        context.source_bounds.height,
    )
    fitted = replace_and_fit_text_box(
        box,
        provider,
        source_language,
        target_language,
        noto_typefaces(),
        preserve_source_font_family=True,
        measure_source_fonts=measure_source_fonts,
    )
    replacement_runs = fitted.text_box.paragraphs[0].runs
    replacement = "".join(run.text for run in replacement_runs)
    if len(replacement_runs) != 1 or any(character in replacement for character in "\r\n\v"):
        return None
    run = replacement_runs[0]
    layout_typefaces = fitted.layout_typefaces
    if layout_typefaces is None or run.font_classification not in layout_typefaces:
        return None
    font = skia.Font(
        layout_typefaces[run.font_classification],
        context.font.size_points * (4.0 / 3.0),
    )
    font.setEmbolden(run.bold is True)
    if run.italic is True:
        font.setSkewX(-0.2)
    text_width = float(font.measureText(replacement))
    source_width = float(font.measureText(context.source_text))
    metrics = font.getMetrics()
    line_height = metrics.fDescent - metrics.fAscent + metrics.fLeading
    if text_width <= 0.0 or line_height <= 0.0:
        return None
    scale = min(
        1.0,
        context.fitting_bounds.width / text_width,
        context.source_bounds.height / line_height,
    )
    # The EMF record's rendered bounds capture the source GDI font metrics that
    # PowerPoint will retain.  Calibrate the layout-face measurement to those
    # metrics before writing a smaller clone of that GDI font.
    if source_width > 0.0 and context.source_bounds.width > 0:
        scale *= min(1.0, source_width / context.source_bounds.width)
    if scale <= 0.0:
        return None
    return replacement, scale


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
                                      preserve_source_font_family=True,
                                      measure_source_fonts=document_text_layout == "preserve-basic-layout-source-font")
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
