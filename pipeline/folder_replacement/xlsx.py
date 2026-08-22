"""XLSX native replacement with finite worksheet-cell text fitting."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from io import BytesIO
from math import isfinite
from pathlib import Path
import posixpath
from typing import cast
from zipfile import ZIP_DEFLATED, ZipFile
import xml.etree.ElementTree as ElementTree

from openpyxl.utils.cell import (
    column_index_from_string,
    coordinate_from_string,
    get_column_letter,
    range_boundaries,
)
# skia-python does not publish PEP 561 stubs; this is the native measurement boundary.
import skia  # type: ignore[import-not-found]

from pipeline.bounded_text_layout import (
    BoundedTextBox,
    BoundedTextParagraph,
    BoundedTextRun,
    SourceTypefaceReference,
    noto_typefaces,
    replace_and_fit_text_box,
)
from pipeline.pptx_theme_fonts import PptxThemeFonts, resolve_theme_typefaces, theme_fonts_from_xml
from pipeline.folder_replacement.office_xml import (
    _namespace_bindings,
    _serialize_with_compatibility_bindings,
)
from pipeline.ocr import OcrProvider
from pipeline.text_replacement import TextReplacementProvider, TextReplacementRequest


_SPREADSHEET_NAMESPACE = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DRAWING_NAMESPACE = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
_DRAWING_MAIN_NAMESPACE = "http://schemas.openxmlformats.org/drawingml/2006/main"
_OFFICE_RELATIONSHIPS_NAMESPACE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_RELATIONSHIPS_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"
_EMUS_PER_POINT = 12_700
_EMUS_PER_PIXEL = 9_525
_NS = {
    "x": _SPREADSHEET_NAMESPACE,
    "xdr": _DRAWING_NAMESPACE,
    "a": _DRAWING_MAIN_NAMESPACE,
    "r": _OFFICE_RELATIONSHIPS_NAMESPACE,
}


def replace_xlsx_file(
    source: Path,
    destination: Path,
    ocr: OcrProvider,
    replacement: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typeface: skia.Typeface,
    completed: Callable[[str], None],
    document_text_layout: str = "preserve-source-formatting",
) -> tuple[int, int, int]:
    """Replace XLSX cells without rewriting unrelated workbook package parts."""
    from pipeline.folder_replacement.processor import _replace_office_file

    if document_text_layout == "preserve-source-formatting":
        return _replace_office_file(
            source, destination, ocr, replacement, source_language, target_language, typeface, completed
        )
    if document_text_layout not in {
        "preserve-basic-layout",
        "preserve-basic-layout-source-font",
    }:
        raise ValueError(f"Unsupported document text layout mode: {document_text_layout!r}")
    native_items, image_regions, retained_vectors = _replace_office_file(
        source,
        destination,
        ocr,
        replacement,
        source_language,
        target_language,
        typeface,
        completed,
        skip_native_xml_part=_is_custom_xlsx_part,
    )
    native_items += _replace_xlsx_cells(
        destination,
        replacement,
        source_language,
        target_language,
        # XLSX has no interoperable, package-level embedded-font path.  Keep
        # the source face and apply the shared Noto-derived fitted size.
        preserve_source_font_family=True,
        measure_source_fonts=document_text_layout == "preserve-basic-layout-source-font",
    )
    completed("native text layout")
    return native_items, image_regions, retained_vectors


def _is_custom_xlsx_part(name: str) -> bool:
    return (
        name == "xl/sharedStrings.xml"
        or name.startswith("xl/worksheets/")
        or name.startswith("xl/drawings/")
        or name.startswith("xl/tables/")
    )


def _replace_xlsx_cells(
    path: Path,
    replacement: TextReplacementProvider,
    source_language: str,
    target_language: str,
    *,
    preserve_source_font_family: bool,
    measure_source_fonts: bool,
) -> int:
    """Fit explicitly bounded cells and retain all unknown package parts byte-for-byte."""
    with ZipFile(path) as archive:
        entries = [(entry, archive.read(entry.filename)) for entry in archive.infolist()]
    parts = {entry.filename: data for entry, data in entries}
    shared_strings = _shared_strings(parts.get("xl/sharedStrings.xml"))
    theme = _workbook_theme(parts)
    styles = _Styles(parts.get("xl/styles.xml"), theme)
    typefaces = noto_typefaces()
    table_headers = _table_header_cells(parts)
    replacements = 0
    changed_parts: dict[str, bytes] = {}
    for name, data in parts.items():
        if not name.startswith("xl/worksheets/") or not name.endswith(".xml"):
            continue
        updated, count = _replace_worksheet(
            data,
            shared_strings,
            styles,
            replacement,
            source_language,
            target_language,
            typefaces,
            preserve_source_font_family,
            measure_source_fonts,
            table_headers.get(name, frozenset()),
        )
        changed_parts[name] = updated
        replacements += count
    for name, data in parts.items():
        if not name.startswith("xl/drawings/") or not name.endswith(".xml"):
            continue
        updated, count = _replace_drawing(
            data, replacement, source_language, target_language, typefaces,
            preserve_source_font_family, measure_source_fonts, theme,
        )
        changed_parts[name] = updated
        replacements += count
    if styles.changed:
        changed_parts["xl/styles.xml"] = styles.serialize()
    if not changed_parts:
        return replacements
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for entry, data in entries:
            archive.writestr(entry, changed_parts.get(entry.filename, data))
    path.write_bytes(output.getvalue())
    return replacements


def _replace_worksheet(
    data: bytes,
    shared_strings: tuple[str, ...],
    styles: "_Styles",
    replacement: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typefaces: dict[str, skia.Typeface],
    preserve_source_font_family: bool,
    measure_source_fonts: bool,
    table_headers: frozenset[str],
) -> tuple[bytes, int]:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return data, 0
    column_widths = _column_widths(root)
    row_heights = _row_heights(root)
    merged_cells = _merged_cells(root)
    replaced = 0
    for cell in root.findall(".//x:sheetData/x:row/x:c", _NS):
        if cell.get("r") in table_headers:
            # A structured-table header is an identifier referenced by table
            # formulas and metadata, rather than ordinary display text.
            continue
        text = _cell_text(cell, shared_strings)
        if text is None or not text.strip() or cell.find("x:f", _NS) is not None:
            continue
        bounds = _cell_bounds(cell, column_widths, row_heights, merged_cells)
        if not styles.can_write_explicit_fit:
            bounds = None
        if bounds is None:
            _write_cell_text(
                cell,
                _replace_text(text, replacement, source_language, target_language),
            )
            replaced += 1
            continue
        source_run = styles.run_for(cell)
        text_box = BoundedTextBox(
            width_emu=bounds[0],
            height_emu=bounds[1],
            margin_left_emu=0,
            margin_top_emu=0,
            margin_right_emu=0,
            margin_bottom_emu=0,
            text_direction=None,
            paragraphs=(
                BoundedTextParagraph(
                    alignment=styles.alignment_for(cell),
                    space_before_points=None,
                    space_after_points=None,
                    line_spacing=None,
                    line_spacing_kind=None,
                    level=0,
                    margin_left_emu=None,
                    indent_emu=None,
                    bullet_kind=None,
                    bullet_marker=None,
                    empty_line_font_size_points=None,
                    runs=(replace_run_text(source_run, text),),
                ),
            ),
        )
        fitted = replace_and_fit_text_box(
            text_box,
            replacement,
            source_language,
            target_language,
            typefaces,
            preserve_source_font_family=preserve_source_font_family,
            measure_source_fonts=measure_source_fonts,
        )
        explicit_run = fitted.text_box.paragraphs[0].runs[0]
        _write_cell_text(cell, explicit_run.text)
        styles.apply_explicit_fit(cell, explicit_run)
        replaced += 1
    return _serialize_with_compatibility_bindings(root, _namespace_bindings(data)), replaced


def _table_header_cells(parts: dict[str, bytes]) -> dict[str, frozenset[str]]:
    """Return header-cell references that must agree with table metadata.

    A worksheet table's header row is duplicated in ``xl/tables/*.xml`` as
    structured-reference names.  Replacing only the visible cell text leaves
    those two representations inconsistent, which Excel repairs by rebuilding
    the table.  Keep both header forms unchanged; body cells remain ordinary
    worksheet text and are processed below.
    """
    headers_by_sheet: dict[str, frozenset[str]] = {}
    for sheet_name, sheet_data in parts.items():
        if not sheet_name.startswith("xl/worksheets/") or not sheet_name.endswith(".xml"):
            continue
        try:
            sheet = ElementTree.fromstring(sheet_data)
        except ElementTree.ParseError:
            continue
        relationships = _part_relationships(parts, sheet_name)
        headers: set[str] = set()
        for table_part in sheet.findall(".//x:tableParts/x:tablePart", _NS):
            relationship_id = table_part.get(f"{{{_OFFICE_RELATIONSHIPS_NAMESPACE}}}id")
            target = None if relationship_id is None else relationships.get(relationship_id)
            if target is None:
                continue
            table_data = parts.get(_resolve_part_target(sheet_name, target))
            if table_data is None:
                continue
            try:
                table = ElementTree.fromstring(table_data)
                reference = table.get("ref")
                if reference is None:
                    continue
                min_column, min_row, max_column, _max_row = range_boundaries(reference)
            except (ElementTree.ParseError, ValueError):
                continue
            if min_column is None or min_row is None or max_column is None:
                continue
            headers.update(
                f"{get_column_letter(column)}{min_row}"
                for column in range(min_column, max_column + 1)
            )
        headers_by_sheet[sheet_name] = frozenset(headers)
    return headers_by_sheet


def _part_relationships(parts: dict[str, bytes], part_name: str) -> dict[str, str]:
    parent, basename = posixpath.split(part_name)
    relationships_name = f"{parent}/_rels/{basename}.rels"
    data = parts.get(relationships_name)
    if data is None:
        return {}
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return {}
    relationships: dict[str, str] = {}
    for relationship in root.findall(f"{{{_PACKAGE_RELATIONSHIPS_NAMESPACE}}}Relationship"):
        relationship_id = relationship.get("Id")
        target = relationship.get("Target")
        if relationship_id is not None and target is not None and relationship.get("TargetMode") != "External":
            relationships[relationship_id] = target
    return relationships


def _workbook_theme(parts: dict[str, bytes]) -> PptxThemeFonts | None:
    relationships_name = "xl/_rels/workbook.xml.rels"
    data = parts.get(relationships_name)
    if data is None:
        return None
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return None
    for relationship in root.findall(f"{{{_PACKAGE_RELATIONSHIPS_NAMESPACE}}}Relationship"):
        if relationship.get("TargetMode") == "External" or not (relationship.get("Type") or "").endswith("/theme"):
            continue
        target = relationship.get("Target")
        if target:
            return theme_fonts_from_xml(parts.get(_resolve_part_target("xl/workbook.xml", target)))
    return None


def _resolve_part_target(part_name: str, target: str) -> str:
    """Resolve a package-relative relationship target without filesystem access."""
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(part_name), target))


def _replace_drawing(
    data: bytes,
    provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typefaces: dict[str, skia.Typeface],
    preserve_source_font_family: bool,
    measure_source_fonts: bool = False,
    theme: PptxThemeFonts | None = None,
) -> tuple[bytes, int]:
    """Fit SpreadsheetDrawing shape text against its ``a:xfrm/a:ext`` box."""
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return data, 0
    parents = {child: parent for parent in root.iter() for child in parent}
    fitted_text: set[ElementTree.Element] = set()
    count = 0
    for body in root.findall(".//xdr:sp/xdr:txBody", _NS):
        shape = parents.get(body)
        extent = None if shape is None else shape.find("xdr:spPr/a:xfrm/a:ext", _NS)
        if extent is None:
            continue
        try:
            width, height = int(extent.get("cx", "0")), int(extent.get("cy", "0"))
        except ValueError:
            continue
        paragraphs = tuple(_drawing_paragraph(paragraph, theme) for paragraph in body.findall("a:p", _NS))
        if width <= 0 or height <= 0 or not any(run.text.strip() for paragraph in paragraphs for run in paragraph.runs):
            continue
        body_properties = body.find("a:bodyPr", _NS)
        box = BoundedTextBox(
            width, height,
            _int_attribute(body_properties, "lIns", 91_440), _int_attribute(body_properties, "tIns", 45_720),
            _int_attribute(body_properties, "rIns", 91_440), _int_attribute(body_properties, "bIns", 45_720),
            None, paragraphs,
        )
        fitted = replace_and_fit_text_box(
            box, provider, source_language, target_language, typefaces,
            preserve_source_font_family=preserve_source_font_family,
            measure_source_fonts=measure_source_fonts,
        )
        for element in body.iter(_a_tag("t")):
            fitted_text.add(element)
        for destination, explicit in zip(body.findall("a:p", _NS), fitted.text_box.paragraphs, strict=True):
            _write_drawing_paragraph(destination, explicit)
        for element in body.iter(_a_tag("t")):
            fitted_text.add(element)
        count += sum(bool("".join(run.text for run in paragraph.runs).strip()) for paragraph in paragraphs)
    for element in root.iter(_a_tag("t")):
        if element not in fitted_text and element.text:
            element.text = _replace_text(element.text, provider, source_language, target_language)
            count += 1
    return _serialize_with_compatibility_bindings(root, _namespace_bindings(data)), count


def _drawing_paragraph(element: ElementTree.Element, theme: PptxThemeFonts | None) -> BoundedTextParagraph:
    properties = element.find("a:pPr", _NS)
    alignment = None if properties is None else properties.get("algn")
    runs = tuple(_drawing_run(run, theme) for run in element.findall("a:r", _NS))
    return BoundedTextParagraph(alignment or "left", None, None, None, None, 0, None, None,
                                None, None, None, runs)


def _drawing_run(element: ElementTree.Element, theme: PptxThemeFonts | None) -> BoundedTextRun:
    properties = element.find("a:rPr", _NS)
    references = _drawing_source_typefaces(properties, theme, "".join(item.text or "" for item in element.iter(_a_tag("t"))))
    family = next((item.original_family for item in references if item.script == "latin"), None)
    size = _finite_float(None if properties is None else properties.get("sz"))
    return BoundedTextRun(
        "".join(item.text or "" for item in element.iter(_a_tag("t"))), family,
        _font_classification(family), None if size is None else size / 100.0,
        properties is not None and properties.get("b") == "1", properties is not None and properties.get("i") == "1",
        "single" if properties is not None and properties.get("u") not in {None, "none"} else "none", None, references,
    )


def _drawing_source_typefaces(
    properties: ElementTree.Element | None, theme: PptxThemeFonts | None, text: str
) -> tuple[SourceTypefaceReference, ...]:
    if properties is None:
        return ()
    references: list[SourceTypefaceReference] = []
    for script, tag in (("latin", "latin"), ("eastAsian", "ea"), ("complex", "cs")):
        element = properties.find(_a_tag(tag))
        if element is not None and element.get("typeface"):
            references.append(SourceTypefaceReference(script, element.get("typeface")))
    return resolve_theme_typefaces(tuple(references), theme, text)


def _write_drawing_paragraph(element: ElementTree.Element, paragraph: BoundedTextParagraph) -> None:
    for child in tuple(element):
        if child.tag in {_a_tag("r"), _a_tag("br"), _a_tag("fld")}:
            element.remove(child)
    end_paragraph = element.find("a:endParaRPr", _NS)
    insertion_index = len(element) if end_paragraph is None else list(element).index(end_paragraph)
    for run in paragraph.runs:
        destination = ElementTree.Element(_a_tag("r"))
        properties = ElementTree.SubElement(destination, _a_tag("rPr"))
        references = run.source_typefaces or (SourceTypefaceReference("latin", run.font_family or "Noto Sans JP"),)
        for item in references:
            ElementTree.SubElement(properties, _a_tag({"latin": "latin", "eastAsian": "ea", "complex": "cs"}[item.script]), {"typeface": item.original_family or "Noto Sans JP"})
        properties.set("sz", str(max(100, round((run.font_size_points or 18.0) * 100))))
        if run.bold: properties.set("b", "1")
        if run.italic: properties.set("i", "1")
        if run.underline not in {None, "none"}: properties.set("u", "sng")
        ElementTree.SubElement(destination, _a_tag("t")).text = run.text
        element.insert(insertion_index, destination)
        insertion_index += 1


def _int_attribute(element: ElementTree.Element | None, name: str, default: int) -> int:
    try:
        return int(default if element is None else element.get(name, str(default)))
    except ValueError:
        return default


def _a_tag(local_name: str) -> str:
    return f"{{{_DRAWING_MAIN_NAMESPACE}}}{local_name}"


def replace_run_text(run: BoundedTextRun, text: str) -> BoundedTextRun:
    """Retain a source run's style while supplying its complete cell value."""
    return BoundedTextRun(
        text=text,
        font_family=run.font_family,
        font_classification=run.font_classification,
        font_size_points=run.font_size_points,
        bold=run.bold,
        italic=run.italic,
        underline=run.underline,
        baseline=run.baseline,
        source_typefaces=run.source_typefaces,
    )


def _replace_text(
    text: str,
    replacement: TextReplacementProvider,
    source_language: str,
    target_language: str,
) -> str:
    return replacement.replace(
        TextReplacementRequest(text, False, source_language, target_language)
    ).text


def _shared_strings(data: bytes | None) -> tuple[str, ...]:
    if data is None:
        return ()
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return ()
    return tuple("".join(element.text or "" for element in item.iter(_tag("t"))) for item in root)


def _cell_text(cell: ElementTree.Element, shared_strings: tuple[str, ...]) -> str | None:
    cell_type = cell.get("t")
    if cell_type == "s":
        value = cell.find("x:v", _NS)
        if value is None or value.text is None:
            return None
        try:
            return shared_strings[int(value.text)]
        except (IndexError, ValueError):
            return None
    if cell_type == "inlineStr":
        inline = cell.find("x:is", _NS)
        return None if inline is None else "".join(element.text or "" for element in inline.iter(_tag("t")))
    return None


def _write_cell_text(cell: ElementTree.Element, text: str) -> None:
    for child in tuple(cell):
        if child.tag in {_tag("v"), _tag("is")}:
            cell.remove(child)
    cell.set("t", "inlineStr")
    inline = ElementTree.SubElement(cell, _tag("is"))
    value = ElementTree.SubElement(inline, _tag("t"))
    value.text = text
    if text[:1].isspace() or text[-1:].isspace():
        value.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def _column_widths(root: ElementTree.Element) -> dict[int, int]:
    widths: dict[int, int] = {}
    for dimension in root.findall("x:cols/x:col", _NS):
        width = _finite_float(dimension.get("width"))
        if width is None:
            continue
        pixels = int(((256 * width + int(128 / 7)) / 256) * 7)
        if pixels <= 0:
            continue
        for column in range(int(dimension.get("min", "0")), int(dimension.get("max", "-1")) + 1):
            widths[column] = pixels * _EMUS_PER_PIXEL
    return widths


def _row_heights(root: ElementTree.Element) -> dict[int, int]:
    heights: dict[int, int] = {}
    for row in root.findall(".//x:sheetData/x:row", _NS):
        height = _finite_float(row.get("ht"))
        if height is not None and height > 0 and row.get("r") is not None:
            heights[int(row.get("r", "0"))] = int(round(height * _EMUS_PER_POINT))
    return heights


def _merged_cells(root: ElementTree.Element) -> tuple[tuple[int, int, int, int], ...]:
    merged: list[tuple[int, int, int, int]] = []
    for element in root.findall("x:mergeCells/x:mergeCell", _NS):
        reference = element.get("ref")
        if reference is None:
            continue
        min_column, min_row, max_column, max_row = range_boundaries(reference)
        if None in (min_column, min_row, max_column, max_row):
            continue
        merged.append(cast(tuple[int, int, int, int], (min_column, min_row, max_column, max_row)))
    return tuple(merged)


def _cell_bounds(
    cell: ElementTree.Element,
    column_widths: dict[int, int],
    row_heights: dict[int, int],
    merged_cells: tuple[tuple[int, int, int, int], ...],
) -> tuple[int, int] | None:
    reference = cell.get("r")
    if reference is None:
        return None
    column_name, row = coordinate_from_string(reference)
    column = column_index_from_string(column_name)
    min_column, min_row, max_column, max_row = column, row, column, row
    for candidate in merged_cells:
        if candidate[0] <= column <= candidate[2] and candidate[1] <= row <= candidate[3]:
            if (column, row) != candidate[:2]:
                return None
            min_column, min_row, max_column, max_row = candidate
            break
    widths = tuple(column_widths.get(index) for index in range(min_column, max_column + 1))
    heights = tuple(row_heights.get(index) for index in range(min_row, max_row + 1))
    if any(value is None for value in widths + heights):
        return None
    return (
        sum(value for value in widths if value is not None),
        sum(value for value in heights if value is not None),
    )


def _finite_float(value: str | None) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    return parsed if isfinite(parsed) else None


class _Styles:
    """Mutable styles.xml subset used to attach explicit fitted cell formatting."""

    def __init__(self, data: bytes | None, theme: PptxThemeFonts | None = None) -> None:
        self._data = data
        self._root = ElementTree.fromstring(data) if data is not None else None
        self.changed = False
        self._theme = theme

    @property
    def can_write_explicit_fit(self) -> bool:
        return (
            self._root is not None
            and self._root.find(_tag("fonts")) is not None
            and self._root.find(_tag("cellXfs")) is not None
        )

    def run_for(self, cell: ElementTree.Element) -> BoundedTextRun:
        font = self._font_for(cell)
        scheme = None if font is None else font.find(_tag("scheme"))
        scheme_value = None if scheme is None else scheme.get("val")
        alias = {"major": "+mj-lt", "minor": "+mn-lt"}.get(scheme_value or "")
        references = () if alias is None or _font_name(font) else (
            SourceTypefaceReference("latin", scheme_value, self._theme.resolve(alias, "latin") if self._theme else None),
        )
        family = _font_name(font)
        return BoundedTextRun(
            text="",
            font_family=family,
            font_classification=_font_classification(family),
            font_size_points=_font_size(font),
            bold=font is not None and font.find(_tag("b")) is not None,
            italic=font is not None and font.find(_tag("i")) is not None,
            underline="single" if font is not None and font.find(_tag("u")) is not None else "none",
            baseline=_font_baseline(font),
            source_typefaces=references,
        )

    def alignment_for(self, cell: ElementTree.Element) -> str:
        xf = self._xf_for(cell)
        alignment = None if xf is None else xf.find(_tag("alignment"))
        return {"center": "center", "right": "right", "justify": "justify"}.get(
            alignment.get("horizontal", "") if alignment is not None else "", "left"
        )

    def apply_explicit_fit(self, cell: ElementTree.Element, run: BoundedTextRun) -> None:
        if self._root is None:
            return
        fonts = self._root.find(_tag("fonts"))
        cell_xfs = self._root.find(_tag("cellXfs"))
        source_xf = self._xf_for(cell)
        source_font = self._font_for(cell)
        if fonts is None or cell_xfs is None or source_xf is None:
            return
        font = deepcopy(source_font) if source_font is not None else ElementTree.Element(_tag("font"))
        if not run.source_typefaces:
            _set_font_value(font, "name", "val", run.font_family or "Noto Sans JP")
        _set_font_value(font, "sz", "val", f"{run.font_size_points or 18.0:.4f}")
        fonts.append(font)
        fonts.set("count", str(len(fonts)))
        xf = deepcopy(source_xf)
        xf.set("fontId", str(len(fonts) - 1))
        xf.set("applyFont", "1")
        alignment = xf.find(_tag("alignment"))
        if alignment is None:
            alignment = ElementTree.Element(_tag("alignment"))
            protection = xf.find(_tag("protection"))
            if protection is None:
                xf.append(alignment)
            else:
                xf.insert(list(xf).index(protection), alignment)
        alignment.set("wrapText", "1")
        alignment.set("shrinkToFit", "0")
        cell_xfs.append(xf)
        cell_xfs.set("count", str(len(cell_xfs)))
        cell.set("s", str(len(cell_xfs) - 1))
        self.changed = True

    def serialize(self) -> bytes:
        if self._root is None or self._data is None:
            return self._data or b""
        return _serialize_with_compatibility_bindings(self._root, _namespace_bindings(self._data))

    def _xf_for(self, cell: ElementTree.Element) -> ElementTree.Element | None:
        if self._root is None:
            return None
        cell_xfs = self._root.find(_tag("cellXfs"))
        if cell_xfs is None:
            return None
        index = int(cell.get("s", "0"))
        return cell_xfs[index] if 0 <= index < len(cell_xfs) else None

    def _font_for(self, cell: ElementTree.Element) -> ElementTree.Element | None:
        if self._root is None:
            return None
        xf = self._xf_for(cell)
        fonts = self._root.find(_tag("fonts"))
        if xf is None or fonts is None:
            return None
        index = int(xf.get("fontId", "0"))
        return fonts[index] if 0 <= index < len(fonts) else None


def _font_name(font: ElementTree.Element | None) -> str | None:
    name = None if font is None else font.find(_tag("name"))
    return None if name is None else name.get("val")


def _font_size(font: ElementTree.Element | None) -> float | None:
    size = None if font is None else font.find(_tag("sz"))
    return _finite_float(None if size is None else size.get("val"))


def _font_baseline(font: ElementTree.Element | None) -> int | None:
    value = None if font is None else font.find(_tag("vertAlign"))
    if value is None:
        return None
    return {"superscript": 30_000, "subscript": -25_000}.get(value.get("val", ""))


def _set_font_value(font: ElementTree.Element, name: str, attribute: str, value: str) -> None:
    child = font.find(_tag(name))
    if child is None:
        child = ElementTree.SubElement(font, _tag(name))
    child.set(attribute, value)


def _font_classification(family: str | None) -> str:
    normalized = (family or "").lower()
    if any(marker in normalized for marker in ("mono", "code", "courier", "fixed")):
        return "fixed-width"
    if any(marker in normalized for marker in ("serif", "mincho", "ming", "song")):
        return "serif"
    return "sans-serif"


def _tag(local_name: str) -> str:
    return f"{{{_SPREADSHEET_NAMESPACE}}}{local_name}"


__all__ = ["replace_xlsx_file"]
