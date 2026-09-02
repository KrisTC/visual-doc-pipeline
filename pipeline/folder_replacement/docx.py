"""DOCX native replacement with bounded DrawingML text-box fitting."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from dataclasses import dataclass
import re
import unicodedata
from uuid import NAMESPACE_URL, UUID, uuid5
from zipfile import ZIP_DEFLATED, ZipFile
import xml.etree.ElementTree as ElementTree

import skia  # type: ignore[import-not-found]

from pipeline.bounded_text_layout import (
    BoundedTextBox,
    BoundedTextParagraph,
    BoundedTextRun,
    SourceTypefaceReference,
    noto_typefaces,
    replace_and_fit_text_box,
)
from pipeline.pptx_theme_fonts import PptxThemeFonts, theme_fonts_from_xml
from pipeline.folder_replacement.office_xml import (
    _namespace_bindings,
    _serialize_with_compatibility_bindings,
)
from pipeline.folder_replacement.failure_diagnostics import FailureContext
from pipeline.ocr import OcrProvider
from pipeline.ocr.image_preparation import RgbColour
from pipeline.portable_fonts import optional_static_typefaces, static_noto_bytes, static_noto_font
from pipeline.text_replacement import TextReplacementProvider, TextReplacementRequest


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_WPS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_RELATIONSHIPS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
_NS = {"w": _W, "wp": _WP, "wps": _WPS, "a": _A}
_SETTINGS_BEFORE_EMBED_TRUE_TYPE_FONTS = frozenset({
    "writeProtection", "view", "zoom", "removePersonalInformation",
    "removeDateAndTime", "doNotDisplayPageBoundaries", "displayBackgroundShape",
    "printPostScriptOverText", "printFractionalCharacterWidth", "printFormsData",
})
_FONT_CHILD_ORDER = {
    name: index
    for index, name in enumerate((
        "altName", "panose1", "charset", "family", "notTrueType", "pitch", "sig",
        "embedRegular", "embedBold", "embedItalic", "embedBoldItalic",
    ))
}
_FAMILY_CLASS_VALUES = {
    **{value: "roman" for value in range(1, 8)},
    8: "swiss",
    9: "decorative",
    10: "script",
}
_CODE_PAGE_CHARSETS = (
    (17, "80"), (18, "81"), (19, "82"), (20, "86"), (21, "88"),
    (0, "00"), (1, "EE"), (2, "CC"), (3, "A1"), (4, "A2"), (5, "A3"),
    (6, "A4"), (7, "A5"), (8, "CC"), (16, "A2"),
)
_DYNAMIC_NUMERIC_FIELD_KINDS = frozenset({"PAGE", "NUMPAGES", "SECTION", "SECTIONPAGES"})


def replace_docx_file(
    source: Path, destination: Path, ocr: OcrProvider, replacement: TextReplacementProvider,
    source_language: str, target_language: str, typeface: skia.Typeface,
    completed: Callable[[str], None], document_text_layout: str = "preserve-source-formatting",
    failure_context: FailureContext | None = None,
    diagnostics: list[dict[str, object]] | None = None,
) -> tuple[int, int, int]:
    """Fit Word DrawingML text boxes while retaining ordinary flow text behaviour."""
    from pipeline.folder_replacement.processor import _replace_office_file
    if failure_context is not None:
        failure_context.set_location(
            stage="docx_background_detection",
            container_kind="docx_document",
            operation="read",
        )
    ocr_backgrounds = _docx_ocr_backgrounds(source)
    if document_text_layout == "preserve-source-formatting":
        native, images, vectors = _replace_office_file(
            source, destination, ocr, replacement, source_language, target_language, typeface,
            completed,
            skip_native_xml_part=lambda name: name.startswith("word/") and name.endswith(".xml"),
            ocr_backgrounds=ocr_backgrounds,
            failure_context=failure_context,
        )
        native += _replace_docx_parts(
            destination, replacement, source_language, target_language, False, failure_context,
            source_formatting=True, fit_textboxes=False,
            diagnostics=diagnostics, document_text_layout=document_text_layout,
        )
        completed("native text layout")
        return native, images, vectors
    native, images, vectors = _replace_office_file(
        source, destination, ocr, replacement, source_language, target_language, typeface,
        completed,
        skip_native_xml_part=lambda name: name.startswith("word/") and name.endswith(".xml"),
        ocr_backgrounds=ocr_backgrounds,
        failure_context=failure_context,
    )
    native += _replace_docx_parts(destination, replacement, source_language, target_language,
        document_text_layout == "preserve-basic-layout-source-font", failure_context,
        diagnostics=diagnostics, document_text_layout=document_text_layout)
    if document_text_layout == "preserve-basic-layout":
        if failure_context is not None:
            failure_context.set_location(
                stage="docx_font_embedding",
                container_kind="docx_document",
                operation="write",
            )
        _embed_docx_static_fonts(destination)
    completed("native text layout")
    return native, images, vectors


def _docx_ocr_backgrounds(source: Path) -> dict[str, RgbColour]:
    """Return the direct document background for every embedded Word image."""
    with ZipFile(source) as archive:
        try:
            document = ElementTree.fromstring(archive.read("word/document.xml"))
        except (KeyError, ElementTree.ParseError):
            return {}
        background = document.find(_tag(_W, "background"))
        colour = None if background is None else _rgb_value(background.get(_tag(_W, "color")))
        if colour is None:
            return {}
        return {
            name: colour
            for name in archive.namelist()
            if name.startswith("word/media/")
        }


def _rgb_value(value: str | None) -> RgbColour | None:
    if value is None or len(value) != 6:
        return None
    try:
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    except ValueError:
        return None


def _replace_docx_parts(
    path: Path,
    provider: TextReplacementProvider,
    source: str,
    target: str,
    preserve_font: bool,
    failure_context: FailureContext | None = None,
    *,
    source_formatting: bool = False,
    fit_textboxes: bool = True,
    diagnostics: list[dict[str, object]] | None = None,
    document_text_layout: str = "preserve-source-formatting",
) -> int:
    if failure_context is not None:
        failure_context.set_location(
            stage="native_xml" if source_formatting else "docx_fitted_layout_read",
            container_kind="office_xml" if source_formatting else "docx_document",
            operation="read",
        )
    with ZipFile(path) as archive:
        entries = [(entry, archive.read(entry.filename)) for entry in archive.infolist()]
    changed: dict[str, bytes] = {}
    count = 0
    faces = noto_typefaces()
    parts = {entry.filename: data for entry, data in entries}
    font_resolver = _DocxFontResolver.from_parts(parts)
    emphasis_resolver = _DocxEmphasisResolver.from_parts(parts)
    for entry, data in entries:
        if not entry.filename.startswith("word/") or not entry.filename.endswith(".xml"):
            continue
        if failure_context is not None:
            failure_context.set_location(
                stage="native_xml" if source_formatting else "docx_fitted_layout",
                container_kind="office_xml" if source_formatting else "docx_xml",
                operation="text_replacement",
                package_part=entry.filename,
            )
        updated, changed_count = _replace_docx_xml(
            data, provider, source, target, faces, preserve_font, font_resolver, emphasis_resolver,
            fit_textboxes=fit_textboxes, diagnostics=diagnostics,
            package_part=entry.filename, document_text_layout=document_text_layout,
        )
        changed[entry.filename] = updated
        count += changed_count
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for entry, data in entries:
            if failure_context is not None:
                failure_context.set_location(
                    stage="office_package_write" if source_formatting else "docx_fitted_layout_write",
                    container_kind="office_package_part" if source_formatting else "docx_package_part",
                    operation="write",
                    package_part=entry.filename,
                )
            archive.writestr(entry, changed.get(entry.filename, data))
    if failure_context is not None:
        failure_context.set_location(
            stage="office_package_write" if source_formatting else "docx_fitted_layout_write",
            container_kind="office_document" if source_formatting else "docx_document",
            operation="write",
        )
    path.write_bytes(output.getvalue())
    return count


def _replace_docx_xml(data: bytes, provider: TextReplacementProvider, source: str, target: str,
    faces: dict[str, skia.Typeface], preserve_font: bool, font_resolver: "_DocxFontResolver",
    emphasis_resolver: "_DocxEmphasisResolver",
    *,
    fit_textboxes: bool,
    diagnostics: list[dict[str, object]] | None,
    package_part: str,
    document_text_layout: str,
) -> tuple[bytes, int]:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return data, 0
    parents = {child: parent for parent in root.iter() for child in parent}
    fitted_text: set[ElementTree.Element] = set()
    count = 0
    for textbox in root.findall(".//w:txbxContent", _NS) if fit_textboxes else ():
        bounds = _textbox_bounds(textbox, parents)
        paragraphs = tuple(_paragraph(paragraph, font_resolver) for paragraph in textbox.findall("w:p", _NS))
        if bounds is None or not any(run.text.strip() for paragraph in paragraphs for run in paragraph.runs):
            continue
        box = BoundedTextBox(*bounds, 0, 0, 0, 0, None, paragraphs)
        fitted = replace_and_fit_text_box(box, provider, source, target, faces,
            preserve_source_font_family=preserve_font, measure_source_fonts=preserve_font)
        for element in textbox.iter(_tag(_W, "t")):
            fitted_text.add(element)
        for destination, explicit in zip(textbox.findall("w:p", _NS), fitted.text_box.paragraphs, strict=True):
            _write_paragraph(destination, explicit)
        for element in textbox.iter(_tag(_W, "t")):
            fitted_text.add(element)
        count += sum(bool("".join(run.text for run in p.runs).strip()) for p in paragraphs)
    field_paragraphs = {
        paragraph: _complex_fields(paragraph)
        for paragraph in root.iter(_tag(_W, "p"))
        if not _has_textbox_ancestor(paragraph, parents)
    }
    all_fields = tuple(field for fields in field_paragraphs.values() for field in fields)
    element_positions = {element: index for index, element in enumerate(root.iter())}
    _toc_text, toc_page_result_text, toc_paragraphs = _toc_result_context(root, parents)
    bookmarks = _bookmark_ranges(root)
    bookmark_display_text = {
        bookmark_range: _bookmark_visible_text(element_positions, parents, *bookmark_range)
        for ranges in bookmarks.values()
        for bookmark_range in ranges
    }
    caption_replacements: dict[tuple[ElementTree.Element, ElementTree.Element], str] = {}
    for paragraph_index, paragraph in enumerate(root.iter(_tag(_W, "p"))):
        if _has_textbox_ancestor(paragraph, parents):
            continue
        source_text = _paragraph_visible_text(paragraph)
        if not source_text:
            continue
        if paragraph in toc_paragraphs:
            replaced, handled_text = _replace_toc_paragraph(
                paragraph, toc_page_result_text, provider, source, target
            )
            count += replaced
            fitted_text.update(handled_text)
            continue
        fields = field_paragraphs[paragraph]
        if fields:
            replaced, handled_text, fallbacks = _replace_field_paragraph(
                paragraph, fields, all_fields, element_positions, bookmarks, bookmark_display_text,
                caption_replacements, provider, source, target, emphasis_resolver,
            )
            count += replaced
            fitted_text.update(handled_text)
            if diagnostics is not None:
                for field, reason_code in fallbacks:
                    diagnostics.append(_field_fallback_diagnostic(
                        field, reason_code, package_part, paragraph_index, document_text_layout
                    ))
            continue
        replaced, structure_reasons = _replace_flowing_paragraph(
            paragraph, provider, source, target, emphasis_resolver
        )
        count += replaced
        if structure_reasons:
            if diagnostics is not None:
                diagnostics.append({
                    "kind": "fallback",
                    "reason_code": "docx_flowing_paragraph_structure_fallback",
                    "container_kind": "docx_flowing_paragraph",
                    "location": {"package_part": package_part, "paragraph_index": paragraph_index},
                    "source_text": source_text,
                    "structure_reasons": list(structure_reasons),
                    "document_text_layout": document_text_layout,
                })
        else:
            fitted_text.update(paragraph.iter(_tag(_W, "t")))
    for text in root.iter():
        if text.tag not in {_tag(_W, "t"), _tag(_W, "delText")}:
            continue
        if text in fitted_text or not text.text:
            continue
        text.text = _replace(text.text, provider, source, target)
        count += 1
    return _serialize_with_compatibility_bindings(root, _namespace_bindings(data)), count


def _textbox_bounds(textbox: ElementTree.Element, parents: dict[ElementTree.Element, ElementTree.Element]) -> tuple[int, int] | None:
    current: ElementTree.Element | None = textbox
    while current is not None:
        extent = current.find(_tag(_WP, "extent"))
        if extent is not None:
            try:
                width, height = int(extent.get("cx", "0")), int(extent.get("cy", "0"))
            except ValueError:
                return None
            return (width, height) if width > 0 and height > 0 else None
        current = parents.get(current)
    return None


def _has_textbox_ancestor(
    element: ElementTree.Element, parents: dict[ElementTree.Element, ElementTree.Element]
) -> bool:
    current = parents.get(element)
    while current is not None:
        if current.tag == _tag(_W, "txbxContent"):
            return True
        current = parents.get(current)
    return False


@dataclass(frozen=True, slots=True)
class _WordEmphasis:
    """The Word emphasis properties that delimit independent translations."""

    colour: tuple[tuple[str, str], ...]
    vertical_alignment: str
    strikethrough: str


@dataclass(frozen=True, slots=True)
class _FlowingWordRun:
    """One safely replaceable source run in an ordinary Word paragraph."""

    element: ElementTree.Element
    text: str
    emphasis: _WordEmphasis


@dataclass(eq=False, slots=True)
class _DocxComplexField:
    """One complex Word field and its cached visible result."""

    paragraph: ElementTree.Element
    begin: ElementTree.Element
    instruction: str = ""
    result_text: tuple[ElementTree.Element, ...] = ()
    end: ElementTree.Element | None = None
    invalid_reason: str | None = None
    replacement: str | None = None

    @property
    def kind(self) -> str | None:
        match = re.match(r"\s*([A-Za-z]+)", self.instruction)
        return None if match is None else match.group(1).upper()

    @property
    def bookmark_name(self) -> str | None:
        if self.kind not in {"REF", "PAGEREF"}:
            return None
        match = re.match(r"\s*(?:REF|PAGEREF)\s+([^\s\\]+)", self.instruction, re.IGNORECASE)
        return None if match is None else match.group(1)

    @property
    def visible_text(self) -> str:
        return "".join(item.text or "" for item in self.result_text)


@dataclass(frozen=True, slots=True)
class _DocxTextSpan:
    """A visible field result or an outside-field maximal emphasis span."""

    text_elements: tuple[ElementTree.Element, ...]
    source_text: str
    replacement: str
    emphasis: _WordEmphasis | None
    field: _DocxComplexField | None = None


@dataclass(slots=True)
class _DocxFieldContext:
    """Parser state used to recognise a TOC field spanning several paragraphs."""

    instruction_parts: list[str]
    state: str = "instruction"
    kind: str | None = None


def _complex_fields(paragraph: ElementTree.Element) -> tuple[_DocxComplexField, ...]:
    """Parse balanced complex fields without treating instructions as visible text."""
    fields: list[_DocxComplexField] = []
    stack: list[tuple[_DocxComplexField, str, list[str], list[ElementTree.Element]]] = []
    for element in paragraph.iter():
        if element.tag == _tag(_W, "fldChar"):
            field_type = element.get(_tag(_W, "fldCharType"), "")
            if field_type == "begin":
                field = _DocxComplexField(paragraph, element)
                if stack:
                    field.invalid_reason = "nested_field_unsupported"
                    outer, state, instruction, result = stack[-1]
                    outer.invalid_reason = outer.invalid_reason or "nested_field_unsupported"
                    stack[-1] = (outer, state, instruction, result)
                fields.append(field)
                stack.append((field, "instruction", [], []))
            elif field_type == "separate":
                if stack:
                    field, state, instruction, result = stack[-1]
                    if state != "instruction":
                        field.invalid_reason = field.invalid_reason or "malformed_field"
                    stack[-1] = (field, "result", instruction, result)
            elif field_type == "end":
                if stack:
                    field, _state, instruction, result = stack.pop()
                    field.instruction = "".join(instruction)
                    field.result_text = tuple(result)
                    field.end = element
            continue
        if not stack:
            continue
        field, state, instruction, result = stack[-1]
        if element.tag == _tag(_W, "instrText") and state == "instruction":
            instruction.append(element.text or "")
        elif element.tag == _tag(_W, "t") and state == "result":
            result.append(element)
        stack[-1] = (field, state, instruction, result)
    for field, _state, instruction, result in stack:
        field.instruction = "".join(instruction)
        field.result_text = tuple(result)
        field.invalid_reason = field.invalid_reason or "unbalanced_field"
    return tuple(fields)


def _toc_result_context(
    root: ElementTree.Element,
    parents: dict[ElementTree.Element, ElementTree.Element],
) -> tuple[set[ElementTree.Element], set[ElementTree.Element], set[ElementTree.Element]]:
    """Identify visible TOC result text and its nested page-number displays."""
    stack: list[_DocxFieldContext] = []
    toc_text: set[ElementTree.Element] = set()
    page_result_text: set[ElementTree.Element] = set()
    toc_paragraphs: set[ElementTree.Element] = set()
    for element in root.iter():
        if element.tag == _tag(_W, "fldChar"):
            field_type = element.get(_tag(_W, "fldCharType"), "")
            if field_type == "begin":
                stack.append(_DocxFieldContext([]))
            elif field_type == "separate" and stack:
                context = stack[-1]
                context.state = "result"
                match = re.match(r"\s*([A-Za-z]+)", "".join(context.instruction_parts))
                context.kind = None if match is None else match.group(1).upper()
            elif field_type == "end" and stack:
                stack.pop()
            continue
        if not stack:
            continue
        if element.tag == _tag(_W, "instrText") and stack[-1].state == "instruction":
            stack[-1].instruction_parts.append(element.text or "")
            continue
        if element.tag != _tag(_W, "t"):
            continue
        if not any(context.kind == "TOC" and context.state == "result" for context in stack):
            continue
        toc_text.add(element)
        paragraph = _paragraph_ancestor(element, parents)
        if paragraph is not None:
            toc_paragraphs.add(paragraph)
        if stack[-1].kind == "PAGEREF" and stack[-1].state == "result":
            page_result_text.add(element)
    return toc_text, page_result_text, toc_paragraphs


def _paragraph_ancestor(
    element: ElementTree.Element, parents: dict[ElementTree.Element, ElementTree.Element]
) -> ElementTree.Element | None:
    current: ElementTree.Element | None = element
    while current is not None:
        if current.tag == _tag(_W, "p"):
            return current
        current = parents.get(current)
    return None


def _replace_toc_paragraph(
    paragraph: ElementTree.Element,
    page_result_text: set[ElementTree.Element],
    provider: TextReplacementProvider,
    source: str,
    target: str,
) -> tuple[int, set[ElementTree.Element]]:
    """Translate TOC labels in place without changing their tab-driven layout."""
    text_elements = tuple(paragraph.iter(_tag(_W, "t")))
    handled = set(text_elements)
    count = 0
    for text in text_elements:
        if text in page_result_text or not (text.text or "").strip():
            continue
        text.text = _replace(text.text or "", provider, source, target)
        count += 1
    return count, handled


def _bookmark_ranges(
    root: ElementTree.Element,
) -> dict[str, tuple[tuple[ElementTree.Element, ElementTree.Element], ...]]:
    """Return package-part bookmark ranges, preserving ambiguous names for fallback."""
    starts: dict[str, ElementTree.Element] = {}
    ranges: dict[str, list[tuple[ElementTree.Element, ElementTree.Element]]] = {}
    for element in root.iter():
        if element.tag == _tag(_W, "bookmarkStart"):
            identifier = element.get(_tag(_W, "id"))
            if identifier:
                starts[identifier] = element
        elif element.tag == _tag(_W, "bookmarkEnd"):
            identifier = element.get(_tag(_W, "id"))
            start = None if identifier is None else starts.pop(identifier, None)
            if start is None:
                continue
            name = start.get(_tag(_W, "name"))
            if name:
                ranges.setdefault(name, []).append((start, element))
    return {name: tuple(value) for name, value in ranges.items()}


def _replace_field_paragraph(
    paragraph: ElementTree.Element,
    fields: tuple[_DocxComplexField, ...],
    all_fields: tuple[_DocxComplexField, ...],
    element_positions: dict[ElementTree.Element, int],
    bookmarks: dict[str, tuple[tuple[ElementTree.Element, ElementTree.Element], ...]],
    bookmark_display_text: dict[tuple[ElementTree.Element, ElementTree.Element], str],
    caption_replacements: dict[tuple[ElementTree.Element, ElementTree.Element], str],
    provider: TextReplacementProvider,
    source: str,
    target: str,
    emphasis_resolver: "_DocxEmphasisResolver",
) -> tuple[int, set[ElementTree.Element], tuple[tuple[_DocxComplexField, str], ...]]:
    """Translate field displays while retaining every live Word field element."""
    handled: set[ElementTree.Element] = set()
    fallbacks: list[tuple[_DocxComplexField, str]] = []
    preserved_fields: set[_DocxComplexField] = set()
    field_by_result = {
        item: field for field in fields for item in field.result_text
    }
    for field in fields:
        if field.invalid_reason is not None:
            fallbacks.append((field, field.invalid_reason))
            continue
        if field.kind == "SEQ":
            if not field.result_text:
                fallbacks.append((field, "field_result_missing"))
                continue
            if field.replacement is None:
                field.replacement = _replace(field.visible_text, provider, source, target)
        elif field.kind in _DYNAMIC_NUMERIC_FIELD_KINDS:
            if field.result_text:
                preserved_fields.add(field)
            else:
                fallbacks.append((field, "field_result_missing"))
        elif field.kind not in {"REF", "PAGEREF"}:
            fallbacks.append((field, "unsupported_field_kind"))
    for field in fields:
        if field.invalid_reason is not None or field.kind not in {"REF", "PAGEREF"}:
            continue
        bookmark_name = field.bookmark_name
        ranges = () if bookmark_name is None else bookmarks.get(bookmark_name, ())
        if bookmark_name is None:
            fallbacks.append((field, "malformed_reference_instruction"))
            continue
        if len(ranges) != 1:
            fallbacks.append((field, "bookmark_missing" if not ranges else "bookmark_ambiguous"))
            continue
        start, end = ranges[0]
        source_fields = _fields_in_bookmark(all_fields, element_positions, start, end)
        if field.kind == "PAGEREF":
            if field.result_text:
                handled.update(field.result_text)
                preserved_fields.add(field)
            else:
                fallbacks.append((field, "field_result_missing"))
            continue
        sequence_fields = [item for item in source_fields if item.kind == "SEQ" and item.result_text]
        if len(sequence_fields) != 1:
            fallbacks.append((field, "caption_seq_missing" if not sequence_fields else "caption_seq_ambiguous"))
            continue
        if not field.result_text:
            fallbacks.append((field, "field_result_missing"))
            continue
        caption_source_text = bookmark_display_text[(start, end)]
        if not caption_source_text.strip():
            fallbacks.append((field, "caption_display_missing"))
            continue
        caption_range = (start, end)
        if caption_range not in caption_replacements:
            caption_replacements[caption_range] = _replace(caption_source_text, provider, source, target)
        field.replacement = caption_replacements[caption_range]
    replacement_fields = {
        field for field in fields if field.replacement is not None
    }
    for field in (*replacement_fields, *preserved_fields):
        handled.update(field.result_text)
    spans = _field_paragraph_spans(
        paragraph, field_by_result, replacement_fields, preserved_fields, provider, source, target,
        emphasis_resolver,
    )
    replacements = [span.replacement for span in spans]
    field_joiners: list[_DocxComplexField] = []
    for index in range(1, len(replacements)):
        preceding_field = spans[index - 1].field
        if preceding_field is not None and spans[index].field is not None:
            continue
        if _needs_field_to_text_space(
            preceding_field, replacements[index - 1], replacements[index],
            spans[index - 1].source_text, spans[index].source_text,
        ):
            if preceding_field is not None and spans[index].field is None:
                field_joiners.append(preceding_field)
            else:
                replacements[index - 1] += " "
    for span, replacement in zip(spans, replacements, strict=True):
        if span.field is None or span.field.replacement is not None:
            _write_text_elements(span.text_elements, replacement)
        handled.update(span.text_elements)
    handled.update(_insert_field_joiners(field_joiners))
    return (
        sum(bool(span.source_text.strip()) for span in spans if span.replacement != span.source_text),
        handled,
        tuple(dict.fromkeys(fallbacks)),
    )


def _fields_in_bookmark(
    fields: tuple[_DocxComplexField, ...], element_positions: dict[ElementTree.Element, int],
    start: ElementTree.Element,
    end: ElementTree.Element,
) -> tuple[_DocxComplexField, ...]:
    start_position, end_position = element_positions[start], element_positions[end]
    return tuple(
        field for field in fields
        if field.begin in element_positions and start_position < element_positions[field.begin] < end_position
    )


def _bookmark_visible_text(
    element_positions: dict[ElementTree.Element, int],
    parents: dict[ElementTree.Element, ElementTree.Element],
    start: ElementTree.Element,
    end: ElementTree.Element,
) -> str:
    """Return the bookmark's source display before any translation changes it."""
    start_position, end_position = element_positions[start], element_positions[end]
    return "".join(
        element.text or ""
        for element, position in element_positions.items()
        if (
            start_position < position < end_position
            and element.tag == _tag(_W, "t")
            and not _has_textbox_ancestor(element, parents)
        )
    )


def _field_paragraph_spans(
    paragraph: ElementTree.Element,
    field_by_result: dict[ElementTree.Element, _DocxComplexField],
    replacement_fields: set[_DocxComplexField],
    preserved_fields: set[_DocxComplexField],
    provider: TextReplacementProvider,
    source: str,
    target: str,
    emphasis_resolver: "_DocxEmphasisResolver",
) -> tuple[_DocxTextSpan, ...]:
    """Build source-order visible spans, leaving markup and wrappers untouched."""
    parents = {child: parent for parent in paragraph.iter() for child in parent}
    spans: list[_DocxTextSpan] = []
    emitted_fields: set[_DocxComplexField] = set()
    ordinary_text_can_continue = False
    for element in paragraph.iter():
        if element.tag == _tag(_W, "fldChar"):
            ordinary_text_can_continue = False
            continue
        if element.tag != _tag(_W, "t"):
            continue
        field = field_by_result.get(element)
        if field is not None:
            ordinary_text_can_continue = False
            if field not in replacement_fields | preserved_fields or field in emitted_fields:
                continue
            emitted_fields.add(field)
            spans.append(_DocxTextSpan(
                field.result_text, field.visible_text, field.replacement or field.visible_text, None, field
            ))
            continue
        run = _run_ancestor(element, parents)
        if run is None:
            ordinary_text_can_continue = False
            continue
        emphasis = emphasis_resolver.emphasis_for(run, paragraph)
        if ordinary_text_can_continue and spans and spans[-1].field is None and spans[-1].emphasis == emphasis:
            previous = spans[-1]
            spans[-1] = _DocxTextSpan(
                (*previous.text_elements, element), previous.source_text + (element.text or ""),
                previous.replacement + (element.text or ""), emphasis,
            )
        else:
            value = element.text or ""
            spans.append(_DocxTextSpan((element,), value, value, emphasis))
        ordinary_text_can_continue = True
    updated: list[_DocxTextSpan] = []
    for span in spans:
        if span.emphasis is None or not span.source_text.strip():
            updated.append(span)
        else:
            updated.append(_DocxTextSpan(
                span.text_elements, span.source_text, _replace(span.source_text, provider, source, target),
                span.emphasis, span.field,
            ))
    return tuple(updated)


def _run_ancestor(
    element: ElementTree.Element, parents: dict[ElementTree.Element, ElementTree.Element]
) -> ElementTree.Element | None:
    current = parents.get(element)
    while current is not None:
        if current.tag == _tag(_W, "r"):
            return current
        current = parents.get(current)
    return None


def _write_text_elements(elements: tuple[ElementTree.Element, ...], replacement: str) -> None:
    if not elements:
        return
    elements[0].text = replacement
    if replacement[:1].isspace() or replacement[-1:].isspace():
        elements[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    for element in elements[1:]:
        element.text = ""


def _insert_field_joiners(fields: list[_DocxComplexField]) -> set[ElementTree.Element]:
    """Write field-to-text joiners outside live field results and instructions."""
    text_elements: set[ElementTree.Element] = set()
    for field in dict.fromkeys(fields):
        if field.end is None:
            continue
        parents = {child: parent for parent in field.paragraph.iter() for child in parent}
        run = _run_ancestor(field.end, parents)
        if run is None:
            continue
        parent = parents.get(run)
        if parent is None:
            continue
        joiner = ElementTree.Element(_tag(_W, "r"))
        style_run = _run_ancestor(field.result_text[-1], parents) if field.result_text else run
        properties = (style_run if style_run is not None else run).find("w:rPr", _NS)
        if properties is not None:
            joiner.append(deepcopy(properties))
        text = ElementTree.SubElement(joiner, _tag(_W, "t"))
        text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        text.text = " "
        parent.insert(list(parent).index(run) + 1, joiner)
        text_elements.add(text)
    return text_elements


def _needs_field_to_text_space(
    field: _DocxComplexField | None,
    previous: str,
    current: str,
    previous_source: str,
    current_source: str,
) -> bool:
    """Apply the normal joiner, tolerating provider-consumed caption spacing."""
    if field is None or field.kind != "SEQ":
        return _needs_latin_emphasis_space(previous, current, previous_source, current_source)
    return bool(
        previous
        and current
        and not previous[-1].isspace()
        and not current[0].isspace()
        and _is_latin_letter_or_decimal_number(previous[-1])
        and _is_latin_letter_or_decimal_number(current[0])
    )


def _field_fallback_diagnostic(
    field: _DocxComplexField,
    reason_code: str,
    package_part: str,
    paragraph_index: int,
    document_text_layout: str,
) -> dict[str, object]:
    return {
        "kind": "fallback",
        "reason_code": f"docx_cross_reference_{reason_code}",
        "container_kind": "docx_cross_reference",
        "location": {"package_part": package_part, "paragraph_index": paragraph_index},
        "field_kind": field.kind,
        "field_result_text": field.visible_text,
        "bookmark_identity": field.bookmark_name,
        "document_text_layout": document_text_layout,
    }


def _replace_flowing_paragraph(
    paragraph: ElementTree.Element,
    provider: TextReplacementProvider,
    source: str,
    target: str,
    emphasis_resolver: "_DocxEmphasisResolver",
) -> tuple[int, tuple[str, ...]]:
    """Replace maximal emphasis runs or report a direct-text fallback."""
    source_runs, structure_reasons = _flowing_word_runs(paragraph, emphasis_resolver)
    if source_runs is None:
        return 0, structure_reasons
    if not source_runs:
        return 0, ()
    groups: list[list[_FlowingWordRun]] = []
    for run in source_runs:
        if groups and groups[-1][0].emphasis == run.emphasis:
            groups[-1].append(run)
        else:
            groups.append([run])
    replacements: list[str] = []
    for group in groups:
        text = "".join(run.text for run in group)
        replacements.append(_replace(text, provider, source, target) if text.strip() else text)
    for index in range(1, len(replacements)):
        if _needs_latin_emphasis_space(
            replacements[index - 1], replacements[index], groups[index - 1][-1].text, groups[index][0].text
        ):
            replacements[index - 1] += " "
    for child in tuple(paragraph):
        if child.tag == _tag(_W, "r"):
            paragraph.remove(child)
    for group, replacement in zip(groups, replacements, strict=True):
        destination = ElementTree.SubElement(paragraph, _tag(_W, "r"))
        properties = group[_dominant_flowing_run_index(group)].element.find("w:rPr", _NS)
        if properties is not None:
            destination.append(deepcopy(properties))
        text_element = ElementTree.SubElement(destination, _tag(_W, "t"))
        text_element.text = replacement
        if replacement[:1].isspace() or replacement[-1:].isspace():
            text_element.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return sum(bool("".join(run.text for run in group).strip()) for group in groups), ()


def _flowing_word_runs(
    paragraph: ElementTree.Element, emphasis_resolver: "_DocxEmphasisResolver"
) -> tuple[tuple[_FlowingWordRun, ...] | None, tuple[str, ...]]:
    """Return plain runs only when the paragraph can be rebuilt safely."""
    runs: list[_FlowingWordRun] = []
    structure_reasons: list[str] = []
    for child in paragraph:
        if child.tag == _tag(_W, "pPr"):
            continue
        if child.tag != _tag(_W, "r"):
            structure_reasons.append(f"docx_paragraph_child_{_local_name(child)}")
            continue
        text_elements = tuple(child.findall("w:t", _NS))
        if not text_elements:
            structure_reasons.append("docx_run_without_visible_text")
        for item in child:
            if item.tag not in {_tag(_W, "rPr"), _tag(_W, "t")}:
                structure_reasons.append(f"docx_run_child_{_local_name(item)}")
        if not text_elements:
            continue
        runs.append(_FlowingWordRun(
            child,
            "".join(item.text or "" for item in text_elements),
            emphasis_resolver.emphasis_for(child, paragraph),
        ))
    if structure_reasons:
        return None, tuple(dict.fromkeys(structure_reasons))
    return tuple(runs), ()


def _paragraph_visible_text(paragraph: ElementTree.Element) -> str:
    return "".join(
        item.text or ""
        for item in paragraph.iter()
        if item.tag in {_tag(_W, "t"), _tag(_W, "delText")}
    )


def _local_name(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _dominant_flowing_run_index(runs: list[_FlowingWordRun]) -> int:
    return max(
        range(len(runs)),
        key=lambda index: (sum(not character.isspace() for character in runs[index].text), -index),
    )


def _needs_latin_emphasis_space(
    previous: str, current: str, previous_source: str, current_source: str
) -> bool:
    """Prevent independently translated Latin emphasis spans from running together."""
    return bool(
        previous
        and current
        and previous_source
        and current_source
        and not previous[-1].isspace()
        and not current[0].isspace()
        and not previous_source[-1].isspace()
        and not current_source[0].isspace()
        and _is_latin_letter_or_decimal_number(previous[-1])
        and _is_latin_letter_or_decimal_number(current[0])
    )


def _is_latin_letter_or_decimal_number(character: str) -> bool:
    """Return whether the character is a Latin letter or a decimal digit."""
    category = unicodedata.category(character)
    if category == "Nd":
        return True
    return category.startswith("L") and unicodedata.name(character, "").startswith("LATIN ")


def _paragraph(element: ElementTree.Element, font_resolver: "_DocxFontResolver") -> BoundedTextParagraph:
    runs = tuple(_run(run, element, font_resolver) for run in element.findall("w:r", _NS))
    properties = element.find("w:pPr", _NS)
    alignment = None if properties is None else properties.find("w:jc", _NS)
    return BoundedTextParagraph("left" if alignment is None else {"center": "center", "right": "right", "both": "justify"}.get(alignment.get("val", ""), "left"), None, None, None, None, 0, None, None, None, None, None, runs)


def _run(
    element: ElementTree.Element, paragraph: ElementTree.Element, font_resolver: "_DocxFontResolver"
) -> BoundedTextRun:
    properties = element.find("w:rPr", _NS)
    fonts = None if properties is None else properties.find("w:rFonts", _NS)
    size = None if properties is None else properties.find("w:sz", _NS)
    text = "".join(text.text or "" for text in element.iter(_tag(_W, "t")))
    references = font_resolver.references_for(element, paragraph, text)
    family = next((item.original_family for item in references if item.script == "latin"), None)
    size_points = None if size is None else float(size.get(_tag(_W, "val"), "36")) / 2
    return BoundedTextRun(text, family, _classification(family), size_points,
        properties is not None and properties.find("w:b", _NS) is not None,
        properties is not None and properties.find("w:i", _NS) is not None,
        "single" if properties is not None and properties.find("w:u", _NS) is not None else "none", None, references)


@dataclass(frozen=True, slots=True)
class _DocxEmphasisResolver:
    """Resolve the style properties that delimit flowing-text translations."""

    defaults: ElementTree.Element | None
    styles: dict[str, tuple[str | None, ElementTree.Element | None]]

    @classmethod
    def from_parts(cls, parts: dict[str, bytes]) -> "_DocxEmphasisResolver":
        styles_root = _xml(parts.get("word/styles.xml"))
        if styles_root is None:
            return cls(None, {})
        defaults = styles_root.find("w:docDefaults/w:rPrDefault/w:rPr", _NS)
        styles: dict[str, tuple[str | None, ElementTree.Element | None]] = {}
        for style in styles_root.findall("w:style", _NS):
            style_id = style.get(_tag(_W, "styleId"))
            if not style_id:
                continue
            based_on = style.find("w:basedOn", _NS)
            styles[style_id] = (
                None if based_on is None else based_on.get(_tag(_W, "val")),
                style.find("w:rPr", _NS),
            )
        return cls(defaults, styles)

    def emphasis_for(self, run: ElementTree.Element, paragraph: ElementTree.Element) -> _WordEmphasis:
        properties: list[ElementTree.Element | None] = [self.defaults]
        paragraph_properties = paragraph.find("w:pPr", _NS)
        paragraph_style = None if paragraph_properties is None else paragraph_properties.find("w:pStyle", _NS)
        properties.extend(self._style_properties(
            None if paragraph_style is None else paragraph_style.get(_tag(_W, "val"))
        ))
        properties.append(None if paragraph_properties is None else paragraph_properties.find("w:rPr", _NS))
        run_properties = run.find("w:rPr", _NS)
        run_style = None if run_properties is None else run_properties.find("w:rStyle", _NS)
        properties.extend(self._style_properties(
            None if run_style is None else run_style.get(_tag(_W, "val"))
        ))
        properties.append(run_properties)
        colour: ElementTree.Element | None = None
        vertical_alignment: ElementTree.Element | None = None
        strike: ElementTree.Element | None = None
        double_strike: ElementTree.Element | None = None
        for item in properties:
            if item is None:
                continue
            candidate = item.find("w:color", _NS)
            if candidate is not None:
                colour = candidate
            candidate = item.find("w:vertAlign", _NS)
            if candidate is not None:
                vertical_alignment = candidate
            candidate = item.find("w:strike", _NS)
            if candidate is not None:
                strike = candidate
            candidate = item.find("w:dstrike", _NS)
            if candidate is not None:
                double_strike = candidate
        return _WordEmphasis(
            _word_colour_value(colour),
            "baseline" if vertical_alignment is None else vertical_alignment.get(_tag(_W, "val"), "baseline"),
            _word_strikethrough_value(strike, double_strike),
        )

    def _style_properties(self, style_id: str | None) -> tuple[ElementTree.Element | None, ...]:
        values: list[ElementTree.Element | None] = []
        seen: set[str] = set()
        while style_id and style_id not in seen:
            seen.add(style_id)
            style = self.styles.get(style_id)
            if style is None:
                break
            style_id, properties = style
            values.append(properties)
        return tuple(reversed(values))


def _word_colour_value(element: ElementTree.Element | None) -> tuple[tuple[str, str], ...]:
    if element is None:
        return (("val", "auto"),)
    values = tuple(sorted(
        (attribute.rsplit("}", 1)[-1], value)
        for attribute, value in element.attrib.items()
    ))
    return values or (("val", "auto"),)


def _word_strikethrough_value(
    strike: ElementTree.Element | None, double_strike: ElementTree.Element | None
) -> str:
    if _word_on_off(double_strike):
        return "double"
    return "single" if _word_on_off(strike) else "none"


def _word_on_off(element: ElementTree.Element | None) -> bool:
    if element is None:
        return False
    return element.get(_tag(_W, "val"), "true").casefold() not in {"0", "false", "off"}


@dataclass(frozen=True, slots=True)
class _DocxFontResolver:
    defaults: tuple[SourceTypefaceReference, ...]
    styles: dict[str, tuple[str | None, tuple[SourceTypefaceReference, ...]]]
    theme: PptxThemeFonts | None

    @classmethod
    def from_parts(cls, parts: dict[str, bytes]) -> "_DocxFontResolver":
        styles_root = _xml(parts.get("word/styles.xml"))
        defaults: tuple[SourceTypefaceReference, ...] = ()
        styles: dict[str, tuple[str | None, tuple[SourceTypefaceReference, ...]]] = {}
        if styles_root is not None:
            default_properties = styles_root.find("w:docDefaults/w:rPrDefault/w:rPr", _NS)
            defaults = _word_source_typefaces(default_properties, None, "")
            for style in styles_root.findall("w:style", _NS):
                style_id = style.get(_tag(_W, "styleId"))
                if not style_id:
                    continue
                based_on = style.find("w:basedOn", _NS)
                parent = None if based_on is None else based_on.get(_tag(_W, "val"))
                properties = style.find("w:rPr", _NS)
                styles[style_id] = (parent, _word_source_typefaces(properties, None, ""))
        theme = _docx_theme(parts)
        return cls(defaults, styles, theme)

    def references_for(
        self, run: ElementTree.Element, paragraph: ElementTree.Element, text: str
    ) -> tuple[SourceTypefaceReference, ...]:
        references = self.defaults
        paragraph_properties = paragraph.find("w:pPr", _NS)
        paragraph_style = None if paragraph_properties is None else paragraph_properties.find("w:pStyle", _NS)
        if paragraph_style is not None:
            references = _merge_word_typefaces(references, self._style_references(paragraph_style.get(_tag(_W, "val"))))
        run_properties = run.find("w:rPr", _NS)
        run_style = None if run_properties is None else run_properties.find("w:rStyle", _NS)
        if run_style is not None:
            references = _merge_word_typefaces(references, self._style_references(run_style.get(_tag(_W, "val"))))
        return _resolve_word_theme_typefaces(
            _merge_word_typefaces(references, _word_source_typefaces(run_properties, None, text)), self.theme, text
        )

    def _style_references(self, style_id: str | None) -> tuple[SourceTypefaceReference, ...]:
        references: tuple[SourceTypefaceReference, ...] = ()
        seen: set[str] = set()
        while style_id and style_id not in seen:
            seen.add(style_id)
            style = self.styles.get(style_id)
            if style is None:
                break
            style_id, direct = style
            references = _merge_word_typefaces(direct, references)
        return references


def _xml(data: bytes | None) -> ElementTree.Element | None:
    if data is None:
        return None
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return None


def _docx_theme(parts: dict[str, bytes]) -> PptxThemeFonts | None:
    relationships = _xml(parts.get("word/_rels/document.xml.rels"))
    if relationships is None:
        return None
    for relationship in relationships:
        if relationship.tag != _tag(_PACKAGE_RELATIONSHIPS, "Relationship") or relationship.get("TargetMode") == "External":
            continue
        if not (relationship.get("Type") or "").endswith("/theme"):
            continue
        target = relationship.get("Target")
        if target:
            return theme_fonts_from_xml(parts.get("word/" + target.lstrip("/").replace("../", "")))
    return None


def _word_source_typefaces(
    properties: ElementTree.Element | None, _theme: PptxThemeFonts | None, _text: str
) -> tuple[SourceTypefaceReference, ...]:
    fonts = None if properties is None else properties.find("w:rFonts", _NS)
    if fonts is None:
        return ()
    values = {
        "latin": fonts.get(_tag(_W, "ascii")) or fonts.get(_tag(_W, "hAnsi")) or fonts.get(_tag(_W, "asciiTheme")) or fonts.get(_tag(_W, "hAnsiTheme")),
        "eastAsian": fonts.get(_tag(_W, "eastAsia")) or fonts.get(_tag(_W, "eastAsiaTheme")),
        "complex": fonts.get(_tag(_W, "cs")) or fonts.get(_tag(_W, "cstheme")),
    }
    return tuple(SourceTypefaceReference(script, value) for script, value in values.items() if value)


def _resolve_word_theme_typefaces(
    references: tuple[SourceTypefaceReference, ...], theme: PptxThemeFonts | None, text: str
) -> tuple[SourceTypefaceReference, ...]:
    aliases = {
        "majorAscii": "+mj-lt", "majorHAnsi": "+mj-lt", "majorEastAsia": "+mj-ea", "majorBidi": "+mj-cs",
        "minorAscii": "+mn-lt", "minorHAnsi": "+mn-lt", "minorEastAsia": "+mn-ea", "minorBidi": "+mn-cs",
    }
    return tuple(
        SourceTypefaceReference(
            item.script, item.original_family,
            None if theme is None else theme.resolve(aliases.get(item.original_family or "", item.original_family), item.script, text),
        )
        for item in references
    )


def _merge_word_typefaces(
    inherited: tuple[SourceTypefaceReference, ...], direct: tuple[SourceTypefaceReference, ...]
) -> tuple[SourceTypefaceReference, ...]:
    values = {item.script: item for item in inherited}
    values.update({item.script: item for item in direct})
    return tuple(values[script] for script in ("latin", "eastAsian", "complex") if script in values)


def _write_word_font_reference(fonts: ElementTree.Element, reference: SourceTypefaceReference) -> None:
    value = reference.original_family or "Noto Sans JP"
    theme = value.startswith("major") or value.startswith("minor")
    attributes = {
        "latin": ("asciiTheme", "hAnsiTheme") if theme else ("ascii", "hAnsi"),
        "eastAsian": ("eastAsiaTheme",) if theme else ("eastAsia",),
        "complex": ("cstheme",) if theme else ("cs",),
    }[reference.script]
    for attribute in attributes:
        fonts.set(_tag(_W, attribute), value)


def _write_paragraph(element: ElementTree.Element, paragraph: BoundedTextParagraph) -> None:
    for child in tuple(element):
        if child.tag == _tag(_W, "r"):
            element.remove(child)
    for run in paragraph.runs:
        destination = ElementTree.SubElement(element, _tag(_W, "r"))
        properties = ElementTree.SubElement(destination, _tag(_W, "rPr"))
        fonts = ElementTree.SubElement(properties, _tag(_W, "rFonts"))
        references = run.source_typefaces
        if not references:
            family = run.font_family or "Noto Sans JP"
            if family.startswith("Noto "):
                family, _path = static_noto_font(run.font_classification, run.bold)
            references = (SourceTypefaceReference("latin", family),)
        for reference in references:
            _write_word_font_reference(fonts, reference)
        if run.bold: ElementTree.SubElement(properties, _tag(_W, "b"))
        if run.italic: ElementTree.SubElement(properties, _tag(_W, "i"))
        size = str(max(2, round((run.font_size_points or 18.0) * 2)))
        ElementTree.SubElement(properties, _tag(_W, "sz"), {_tag(_W, "val"): size})
        ElementTree.SubElement(properties, _tag(_W, "szCs"), {_tag(_W, "val"): size})
        if run.underline not in {None, "none"}: ElementTree.SubElement(properties, _tag(_W, "u"), {_tag(_W, "val"): "single"})
        text = ElementTree.SubElement(destination, _tag(_W, "t")); text.text = run.text


def _replace(text: str, provider: TextReplacementProvider, source: str, target: str) -> str:
    return provider.replace(TextReplacementRequest(text, False, source, target)).text


def _classification(family: str | None) -> str:
    value = (family or "").lower()
    return "fixed-width" if any(x in value for x in ("mono", "code", "courier")) else "serif" if any(x in value for x in ("serif", "mincho")) else "sans-serif"


def _tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def _embed_docx_static_fonts(path: Path) -> None:
    """Add standard Word obfuscated-font parts for the static Noto faces."""
    with ZipFile(path) as archive:
        entries = [(entry, archive.read(entry.filename)) for entry in archive.infolist()]
    parts = {entry.filename: data for entry, data in entries}
    font_table_name = "word/fontTable.xml"
    font_table = _xml_or_new(parts.get(font_table_name), _tag(_W, "fonts"))
    relationships_name = "word/_rels/fontTable.xml.rels"
    relationships = _xml_or_new(parts.get(relationships_name), _tag(_PACKAGE_RELATIONSHIPS, "Relationships"))
    additions: dict[str, bytes] = {}
    relationship_ids = {relationship.get("Id", "") for relationship in relationships}
    classifications: tuple[str, ...] = ("sans-serif", "serif", "fixed-width")
    optional_faces = optional_static_typefaces()
    classifications = (*classifications, *(name for name in ("math", "symbols") if name in optional_faces))
    for index, (classification, bold) in enumerate(
        (
            (classification, bold)
            for classification in classifications
            for bold in ((False,) if classification == "math" else (False, True))
        ),
        start=1,
    ):
        family, _path = static_noto_font(classification, bold)
        font = next(
            (
                item
                for item in font_table.findall(_tag(_W, "font"))
                if item.get(_tag(_W, "name")) == family
            ),
            None,
        )
        if font is None:
            font = ElementTree.SubElement(font_table, _tag(_W, "font"), {_tag(_W, "name"): family})
            _add_font_substitution_metadata(font, static_noto_bytes(classification, bold))
        embedding_tag = _tag(_W, "embedBold" if bold else "embedRegular")
        if font.find(embedding_tag) is not None:
            continue
        key = uuid5(NAMESPACE_URL, f"visual-doc-pipeline/{classification}/{bold}")
        relationship_id = _next_pipeline_relationship_id(relationship_ids, index)
        relationship_ids.add(relationship_id)
        filename = f"fonts/pipeline-{classification}-{'bold' if bold else 'regular'}.odttf"
        embed = ElementTree.SubElement(font, embedding_tag)
        embed.set(_tag(_R, "id"), relationship_id)
        embed.set(_tag(_W, "fontKey"), "{" + str(key).upper() + "}")
        ElementTree.SubElement(relationships, _tag(_PACKAGE_RELATIONSHIPS, "Relationship"), {
            "Id": relationship_id,
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font",
            "Target": filename,
        })
        additions[f"word/{filename}"] = _obfuscate_font(static_noto_bytes(classification, bold), key)
    additions[font_table_name] = _serialize_with_compatibility_bindings(font_table, {"w": _W, "r": _R})
    additions[relationships_name] = _serialize_with_compatibility_bindings(relationships, {})
    _ensure_docx_font_table_relationship(parts, additions)
    _ensure_docx_font_content_type(parts, additions)
    _ensure_docx_font_embedding_setting(parts, additions)
    output_parts = parts | additions
    _validate_docx_embedded_fonts(output_parts)
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        seen: set[str] = set()
        for entry, data in entries:
            archive.writestr(entry, additions.get(entry.filename, data)); seen.add(entry.filename)
        for name, data in additions.items():
            if name not in seen:
                archive.writestr(name, data)
    path.write_bytes(output.getvalue())


def _xml_or_new(data: bytes | None, tag: str) -> ElementTree.Element:
    if data is not None:
        try:
            return ElementTree.fromstring(data)
        except ElementTree.ParseError:
            pass
    return ElementTree.Element(tag)


def _obfuscate_font(data: bytes, key: UUID) -> bytes:
    value = key.bytes[::-1]
    output = bytearray(data)
    for index in range(min(32, len(output))):
        output[index] ^= value[index % 16]
    return bytes(output)


def _add_font_substitution_metadata(font: ElementTree.Element, data: bytes) -> None:
    for name, attributes in _font_substitution_metadata(data):
        ElementTree.SubElement(font, _tag(_W, name), {_tag(_W, key): value for key, value in attributes.items()})


def _font_substitution_metadata(data: bytes) -> tuple[tuple[str, dict[str, str]], ...]:
    tables = _sfnt_tables(data)
    os2 = tables.get("OS/2")
    post = tables.get("post")
    if os2 is None or post is None or os2 + 86 > len(data) or post + 16 > len(data):
        raise ValueError("Embedded DOCX font has no usable SFNT substitution metadata.")
    family_class = int.from_bytes(data[os2 + 30:os2 + 32], "big") >> 8
    code_page_range = int.from_bytes(data[os2 + 78:os2 + 82], "big")
    charset = next(
        (value for bit, value in _CODE_PAGE_CHARSETS if code_page_range & (1 << bit)),
        "00",
    )
    return (
        ("panose1", {"val": data[os2 + 32:os2 + 42].hex().upper()}),
        ("charset", {"val": charset}),
        ("family", {"val": _FAMILY_CLASS_VALUES.get(family_class, "auto")}),
        ("pitch", {"val": "fixed" if int.from_bytes(data[post + 12:post + 16], "big") else "variable"}),
        (
            "sig",
            {
                "usb0": data[os2 + 42:os2 + 46].hex().upper(),
                "usb1": data[os2 + 46:os2 + 50].hex().upper(),
                "usb2": data[os2 + 50:os2 + 54].hex().upper(),
                "usb3": data[os2 + 54:os2 + 58].hex().upper(),
                "csb0": data[os2 + 78:os2 + 82].hex().upper(),
                "csb1": data[os2 + 82:os2 + 86].hex().upper(),
            },
        ),
    )


def _sfnt_tables(data: bytes) -> dict[str, int]:
    if len(data) < 12:
        raise ValueError("Embedded DOCX font is not a valid SFNT file.")
    table_count = int.from_bytes(data[4:6], "big")
    if len(data) < 12 + table_count * 16:
        raise ValueError("Embedded DOCX font has an incomplete SFNT table directory.")
    tables: dict[str, int] = {}
    for index in range(table_count):
        start = 12 + index * 16
        name = data[start:start + 4].decode("ascii")
        offset = int.from_bytes(data[start + 8:start + 12], "big")
        length = int.from_bytes(data[start + 12:start + 16], "big")
        if offset + length > len(data):
            raise ValueError("Embedded DOCX font has an invalid SFNT table range.")
        tables[name] = offset
    return tables


def _next_pipeline_relationship_id(existing: set[str], index: int) -> str:
    candidate_index = index
    while True:
        candidate = f"rIdPipelineFont{candidate_index}"
        if candidate not in existing:
            return candidate
        candidate_index += 1


def _validate_docx_embedded_fonts(parts: dict[str, bytes]) -> None:
    """Verify every pipeline-added Word font is reachable and decodes as a font."""
    font_table = _required_xml_part(parts, "word/fontTable.xml")
    font_relationships = _required_xml_part(parts, "word/_rels/fontTable.xml.rels")
    document_relationships = _required_xml_part(parts, "word/_rels/document.xml.rels")
    content_types = _required_xml_part(parts, "[Content_Types].xml")
    _validate_font_table_relationship(document_relationships)
    _validate_font_content_types(content_types)
    _validate_font_embedding_settings(parts, document_relationships, content_types)
    _validate_font_table_order(font_table)
    targets = _relationship_targets(font_relationships)
    seen_relationship_ids: set[str] = set()
    family_entries: dict[str, int] = {}
    for font in font_table.findall(_tag(_W, "font")):
        family = font.get(_tag(_W, "name"))
        if family is not None:
            family_entries[family] = family_entries.get(family, 0) + 1
    for font in font_table.findall(_tag(_W, "font")):
        family = font.get(_tag(_W, "name"))
        for embedding_name in ("embedRegular", "embedBold", "embedItalic", "embedBoldItalic"):
            embed = font.find(_tag(_W, embedding_name))
            if embed is None:
                continue
            relationship_id = embed.get(_tag(_R, "id"), "")
            if not relationship_id.startswith("rIdPipelineFont"):
                continue
            if not family or family_entries[family] > 1:
                raise ValueError(f"Embedded DOCX font family is duplicated or unnamed: {family!r}.")
            if relationship_id in seen_relationship_ids:
                raise ValueError(f"DOCX embedded font relationship ID is duplicated: {relationship_id}.")
            seen_relationship_ids.add(relationship_id)
            key_text = embed.get(_tag(_W, "fontKey"))
            if key_text is None:
                raise ValueError(f"DOCX embedded font {relationship_id} has no font key.")
            try:
                key = UUID(key_text.strip("{}"))
            except ValueError as error:
                raise ValueError(f"DOCX embedded font {relationship_id} has an invalid font key.") from error
            target = targets.get(relationship_id)
            if target is None or not target.startswith("fonts/"):
                raise ValueError(f"DOCX embedded font {relationship_id} has an invalid target.")
            part_name = f"word/{target}"
            if part_name not in parts:
                raise ValueError(f"DOCX embedded font {relationship_id} has no font part.")
            recovered = _obfuscate_font(parts[part_name], key)
            recovered_typeface = skia.Typeface.MakeFromData(skia.Data.MakeWithCopy(recovered))
            if recovered_typeface is None:
                raise ValueError(f"DOCX embedded font {relationship_id} is not a loadable OpenType font.")
            if recovered_typeface.getFamilyName() != family:
                raise ValueError(f"DOCX embedded font {relationship_id} does not match its font-table family.")


def _required_xml_part(parts: dict[str, bytes], name: str) -> ElementTree.Element:
    data = parts.get(name)
    if data is None:
        raise ValueError(f"DOCX font embedding requires package part {name}.")
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise ValueError(f"DOCX font embedding package part is invalid XML: {name}.") from error


def _relationship_targets(relationships: ElementTree.Element) -> dict[str, str]:
    targets: dict[str, str] = {}
    for relationship in relationships:
        identifier = relationship.get("Id")
        target = relationship.get("Target")
        if identifier is None or target is None:
            continue
        if identifier in targets:
            raise ValueError(f"DOCX font relationship ID is duplicated: {identifier}.")
        targets[identifier] = target
    return targets


def _validate_font_table_relationship(relationships: ElementTree.Element) -> None:
    font_tables = [
        relationship
        for relationship in relationships
        if relationship.get("Type") == "http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable"
    ]
    if len(font_tables) != 1 or font_tables[0].get("Target") != "fontTable.xml":
        raise ValueError("DOCX font table relationship is missing or invalid.")


def _validate_font_content_types(content_types: ElementTree.Element) -> None:
    font_defaults = [
        item
        for item in content_types
        if item.get("Extension") == "odttf"
    ]
    font_tables = [
        item
        for item in content_types
        if item.get("PartName") == "/word/fontTable.xml"
    ]
    if len(font_defaults) != 1 or font_defaults[0].get("ContentType") != "application/vnd.openxmlformats-officedocument.obfuscatedFont":
        raise ValueError("DOCX obfuscated-font content type is missing or invalid.")
    if len(font_tables) != 1 or font_tables[0].get("ContentType") != "application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml":
        raise ValueError("DOCX font-table content type is missing or invalid.")
    first_override = next(
        (
            index
            for index, item in enumerate(content_types)
            if item.tag == _tag(_CONTENT_TYPES, "Override")
        ),
        len(content_types),
    )
    if any(
        item.tag == _tag(_CONTENT_TYPES, "Default")
        for item in tuple(content_types)[first_override:]
    ):
        raise ValueError("DOCX content-type defaults must precede overrides.")


def _validate_font_table_order(font_table: ElementTree.Element) -> None:
    for font in font_table.findall(_tag(_W, "font")):
        child_names = [child.tag.rsplit("}", 1)[-1] for child in font]
        if child_names != sorted(
            child_names, key=lambda name: _FONT_CHILD_ORDER.get(name, len(_FONT_CHILD_ORDER))
        ):
            raise ValueError("DOCX font-table properties are not in CT_Font order.")


def _validate_font_embedding_settings(
    parts: dict[str, bytes], document_relationships: ElementTree.Element,
    content_types: ElementTree.Element,
) -> None:
    settings = _required_xml_part(parts, "word/settings.xml")
    settings_relationships = [
        relationship
        for relationship in document_relationships
        if relationship.get("Type")
        == "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings"
    ]
    if len(settings_relationships) != 1 or settings_relationships[0].get("Target") != "settings.xml":
        raise ValueError("DOCX settings relationship is missing or invalid.")
    settings_content_types = [
        item
        for item in content_types
        if item.get("PartName") == "/word/settings.xml"
    ]
    if len(settings_content_types) != 1 or settings_content_types[0].get("ContentType") != (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"
    ):
        raise ValueError("DOCX settings content type is missing or invalid.")
    embedding_settings = settings.findall(_tag(_W, "embedTrueTypeFonts"))
    if len(embedding_settings) != 1 or embedding_settings[0].attrib or len(embedding_settings[0]):
        raise ValueError("DOCX embedded-font setting is missing or invalid.")
    setting_index = list(settings).index(embedding_settings[0])
    if any(
        child.tag.rsplit("}", 1)[-1] not in _SETTINGS_BEFORE_EMBED_TRUE_TYPE_FONTS
        for child in list(settings)[:setting_index]
    ) or any(
        child.tag.rsplit("}", 1)[-1] in _SETTINGS_BEFORE_EMBED_TRUE_TYPE_FONTS
        for child in list(settings)[setting_index + 1:]
    ):
        raise ValueError("DOCX embedded-font setting is not in CT_Settings order.")


def _ensure_docx_font_table_relationship(parts: dict[str, bytes], additions: dict[str, bytes]) -> None:
    name = "word/_rels/document.xml.rels"
    if name not in parts:
        return
    root = _xml_or_new(parts[name], _tag(_PACKAGE_RELATIONSHIPS, "Relationships"))
    if not any(item.get("Type", "").endswith("/fontTable") for item in root):
        ElementTree.SubElement(root, _tag(_PACKAGE_RELATIONSHIPS, "Relationship"), {
            "Id": "rIdPipelineFontTable", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable", "Target": "fontTable.xml",
        })
    additions[name] = _serialize_with_compatibility_bindings(root, {})


def _ensure_docx_font_content_type(parts: dict[str, bytes], additions: dict[str, bytes]) -> None:
    name = "[Content_Types].xml"
    if name not in parts:
        return
    root = _xml_or_new(parts[name], _tag(_CONTENT_TYPES, "Types"))
    if not any(item.get("Extension") == "odttf" for item in root):
        font_default = ElementTree.Element(_tag(_CONTENT_TYPES, "Default"), {
            "Extension": "odttf", "ContentType": "application/vnd.openxmlformats-officedocument.obfuscatedFont",
        })
        first_override = next(
            (
                index
                for index, item in enumerate(root)
                if item.tag == _tag(_CONTENT_TYPES, "Override")
            ),
            len(root),
        )
        root.insert(first_override, font_default)
    if not any(item.get("PartName") == "/word/fontTable.xml" for item in root):
        ElementTree.SubElement(root, _tag(_CONTENT_TYPES, "Override"), {
            "PartName": "/word/fontTable.xml", "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml",
        })
    additions[name] = _serialize_with_compatibility_bindings(root, {})


def _ensure_docx_font_embedding_setting(parts: dict[str, bytes], additions: dict[str, bytes]) -> None:
    name = "word/settings.xml"
    root = _xml_or_new(parts.get(name), _tag(_W, "settings"))
    if root.find(_tag(_W, "embedTrueTypeFonts")) is None:
        insertion_index = next(
            (
                index
                for index, child in enumerate(root)
                if child.tag.rsplit("}", 1)[-1]
                not in _SETTINGS_BEFORE_EMBED_TRUE_TYPE_FONTS
            ),
            len(root),
        )
        root.insert(insertion_index, ElementTree.Element(_tag(_W, "embedTrueTypeFonts")))
    additions[name] = _serialize_with_compatibility_bindings(root, {"w": _W})
    _ensure_docx_settings_relationship(parts, additions)
    _ensure_docx_settings_content_type(parts, additions)


def _ensure_docx_settings_relationship(parts: dict[str, bytes], additions: dict[str, bytes]) -> None:
    name = "word/_rels/document.xml.rels"
    root = _xml_or_new(additions.get(name, parts.get(name)), _tag(_PACKAGE_RELATIONSHIPS, "Relationships"))
    if not any(item.get("Type", "").endswith("/settings") for item in root):
        existing_ids = {item.get("Id", "") for item in root}
        relationship_id = "rIdPipelineSettings"
        index = 1
        while relationship_id in existing_ids:
            relationship_id = f"rIdPipelineSettings{index}"
            index += 1
        ElementTree.SubElement(root, _tag(_PACKAGE_RELATIONSHIPS, "Relationship"), {
            "Id": relationship_id,
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings",
            "Target": "settings.xml",
        })
    additions[name] = _serialize_with_compatibility_bindings(root, {})


def _ensure_docx_settings_content_type(parts: dict[str, bytes], additions: dict[str, bytes]) -> None:
    name = "[Content_Types].xml"
    root = _xml_or_new(additions.get(name, parts.get(name)), _tag(_CONTENT_TYPES, "Types"))
    if not any(item.get("PartName") == "/word/settings.xml" for item in root):
        ElementTree.SubElement(root, _tag(_CONTENT_TYPES, "Override"), {
            "PartName": "/word/settings.xml",
            "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml",
        })
    additions[name] = _serialize_with_compatibility_bindings(root, {})
