"""DOCX native replacement with bounded DrawingML text-box fitting."""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zipfile import ZIP_DEFLATED, ZipFile
import xml.etree.ElementTree as ElementTree

import skia  # type: ignore[import-not-found]

from pipeline.bounded_text_layout import (
    BoundedTextBox,
    BoundedTextParagraph,
    BoundedTextRun,
    noto_typefaces,
    replace_and_fit_text_box,
)
from pipeline.folder_replacement.office_xml import (
    _namespace_bindings,
    _serialize_with_compatibility_bindings,
)
from pipeline.ocr import OcrProvider
from pipeline.portable_fonts import static_noto_bytes, static_noto_font
from pipeline.text_replacement import TextReplacementProvider, TextReplacementRequest


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_WPS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_RELATIONSHIPS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
_NS = {"w": _W, "wp": _WP, "wps": _WPS, "a": _A}


def replace_docx_file(
    source: Path, destination: Path, ocr: OcrProvider, replacement: TextReplacementProvider,
    source_language: str, target_language: str, typeface: skia.Typeface,
    completed: Callable[[str], None], document_text_layout: str = "preserve-source-formatting",
) -> tuple[int, int, int]:
    """Fit Word DrawingML text boxes while retaining ordinary flow text behaviour."""
    from pipeline.folder_replacement.processor import _replace_office_file
    if document_text_layout == "preserve-source-formatting":
        return _replace_office_file(source, destination, ocr, replacement, source_language, target_language, typeface, completed)
    native, images, vectors = _replace_office_file(
        source, destination, ocr, replacement, source_language, target_language, typeface,
        completed, skip_native_xml_part=lambda name: name.startswith("word/") and name.endswith(".xml"),
    )
    native += _replace_docx_parts(destination, replacement, source_language, target_language,
        document_text_layout == "preserve-basic-layout-source-font")
    if document_text_layout == "preserve-basic-layout":
        _embed_docx_static_fonts(destination)
    completed("native text layout")
    return native, images, vectors


def _replace_docx_parts(path: Path, provider: TextReplacementProvider, source: str, target: str, preserve_font: bool) -> int:
    with ZipFile(path) as archive:
        entries = [(entry, archive.read(entry.filename)) for entry in archive.infolist()]
    changed: dict[str, bytes] = {}
    count = 0
    faces = noto_typefaces()
    for entry, data in entries:
        if not entry.filename.startswith("word/") or not entry.filename.endswith(".xml"):
            continue
        updated, changed_count = _replace_docx_xml(data, provider, source, target, faces, preserve_font)
        changed[entry.filename] = updated
        count += changed_count
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for entry, data in entries:
            archive.writestr(entry, changed.get(entry.filename, data))
    path.write_bytes(output.getvalue())
    return count


def _replace_docx_xml(data: bytes, provider: TextReplacementProvider, source: str, target: str,
    faces: dict[str, skia.Typeface], preserve_font: bool) -> tuple[bytes, int]:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return data, 0
    parents = {child: parent for parent in root.iter() for child in parent}
    fitted_text: set[ElementTree.Element] = set()
    count = 0
    for textbox in root.findall(".//w:txbxContent", _NS):
        bounds = _textbox_bounds(textbox, parents)
        paragraphs = tuple(_paragraph(paragraph) for paragraph in textbox.findall("w:p", _NS))
        if bounds is None or not any(run.text.strip() for paragraph in paragraphs for run in paragraph.runs):
            continue
        box = BoundedTextBox(*bounds, 0, 0, 0, 0, None, paragraphs)
        fitted = replace_and_fit_text_box(box, provider, source, target, faces,
            preserve_source_font_family=preserve_font)
        for element in textbox.iter(_tag(_W, "t")):
            fitted_text.add(element)
        for destination, explicit in zip(textbox.findall("w:p", _NS), fitted.text_box.paragraphs, strict=True):
            _write_paragraph(destination, explicit)
        for element in textbox.iter(_tag(_W, "t")):
            fitted_text.add(element)
        count += sum(bool("".join(run.text for run in p.runs).strip()) for p in paragraphs)
    for text in root.iter(_tag(_W, "t")):
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


def _paragraph(element: ElementTree.Element) -> BoundedTextParagraph:
    runs = tuple(_run(run) for run in element.findall("w:r", _NS))
    properties = element.find("w:pPr", _NS)
    alignment = None if properties is None else properties.find("w:jc", _NS)
    return BoundedTextParagraph("left" if alignment is None else {"center": "center", "right": "right", "both": "justify"}.get(alignment.get("val", ""), "left"), None, None, None, None, 0, None, None, None, None, None, runs)


def _run(element: ElementTree.Element) -> BoundedTextRun:
    properties = element.find("w:rPr", _NS)
    fonts = None if properties is None else properties.find("w:rFonts", _NS)
    size = None if properties is None else properties.find("w:sz", _NS)
    family = None if fonts is None else fonts.get(_tag(_W, "ascii")) or fonts.get(_tag(_W, "hAnsi"))
    size_points = None if size is None else float(size.get(_tag(_W, "val"), "36")) / 2
    return BoundedTextRun("".join(text.text or "" for text in element.iter(_tag(_W, "t"))), family, _classification(family), size_points,
        properties is not None and properties.find("w:b", _NS) is not None,
        properties is not None and properties.find("w:i", _NS) is not None,
        "single" if properties is not None and properties.find("w:u", _NS) is not None else "none", None)


def _write_paragraph(element: ElementTree.Element, paragraph: BoundedTextParagraph) -> None:
    for child in tuple(element):
        if child.tag == _tag(_W, "r"):
            element.remove(child)
    for run in paragraph.runs:
        destination = ElementTree.SubElement(element, _tag(_W, "r"))
        properties = ElementTree.SubElement(destination, _tag(_W, "rPr"))
        fonts = ElementTree.SubElement(properties, _tag(_W, "rFonts"))
        family = run.font_family or "Noto Sans JP"
        if family.startswith("Noto "):
            family, _path = static_noto_font(run.font_classification, run.bold)
        for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
            fonts.set(_tag(_W, attribute), family)
        size = str(max(2, round((run.font_size_points or 18.0) * 2)))
        ElementTree.SubElement(properties, _tag(_W, "sz"), {_tag(_W, "val"): size})
        ElementTree.SubElement(properties, _tag(_W, "szCs"), {_tag(_W, "val"): size})
        if run.bold: ElementTree.SubElement(properties, _tag(_W, "b"))
        if run.italic: ElementTree.SubElement(properties, _tag(_W, "i"))
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
    for index, (classification, bold) in enumerate(
        ((classification, bold) for classification in ("sans-serif", "serif", "fixed-width") for bold in (False, True)),
        start=1,
    ):
        family, _path = static_noto_font(classification, bold)
        key = uuid5(NAMESPACE_URL, f"visual-doc-pipeline/{classification}/{bold}")
        relationship_id = f"rIdPipeline{index}"
        filename = f"fonts/pipeline-{classification}-{'bold' if bold else 'regular'}.odttf"
        font = ElementTree.SubElement(font_table, _tag(_W, "font"), {_tag(_W, "name"): family})
        embed = ElementTree.SubElement(font, _tag(_W, "embedBold" if bold else "embedRegular"))
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


def _obfuscate_font(data: bytes, key: object) -> bytes:
    value = getattr(key, "bytes_le")
    output = bytearray(data)
    for index in range(min(32, len(output))):
        output[index] ^= value[index % 16]
    return bytes(output)


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
        ElementTree.SubElement(root, _tag(_CONTENT_TYPES, "Default"), {
            "Extension": "odttf", "ContentType": "application/vnd.openxmlformats-officedocument.obfuscatedFont",
        })
    if not any(item.get("PartName") == "/word/fontTable.xml" for item in root):
        ElementTree.SubElement(root, _tag(_CONTENT_TYPES, "Override"), {
            "PartName": "/word/fontTable.xml", "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml",
        })
    additions[name] = _serialize_with_compatibility_bindings(root, {})
