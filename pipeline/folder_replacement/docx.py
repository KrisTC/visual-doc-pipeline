"""DOCX native replacement with bounded DrawingML text-box fitting."""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5
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
    for index, (classification, bold) in enumerate(
        ((classification, bold) for classification in ("sans-serif", "serif", "fixed-width") for bold in (False, True)),
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
