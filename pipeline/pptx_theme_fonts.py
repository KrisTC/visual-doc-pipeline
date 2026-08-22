"""Relationship-safe PPTX theme typeface lookup for source-font layout."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import posixpath
import unicodedata
import xml.etree.ElementTree as ElementTree
from zipfile import ZipFile

from pipeline.bounded_text_layout import SourceTypefaceReference


_DRAWING = "http://schemas.openxmlformats.org/drawingml/2006/main"
_PRESENTATION = "http://schemas.openxmlformats.org/presentationml/2006/main"
_RELATIONSHIPS = "http://schemas.openxmlformats.org/package/2006/relationships"
_OFFICE_RELATIONSHIPS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


@dataclass(frozen=True, slots=True)
class PptxThemeFonts:
    """Concrete families supplied by one reachable DrawingML theme."""

    slots: dict[tuple[str, str], str]
    script_fonts: dict[tuple[str, str], dict[str, str]]

    def resolve(self, alias: str | None, script: str, text: str = "") -> str | None:
        if not alias or not alias.startswith("+"):
            return alias
        alias_slots = {
            "+mj-lt": ("major", "latin"), "+mj-ea": ("major", "eastAsian"),
            "+mj-cs": ("major", "complex"), "+mn-lt": ("minor", "latin"),
            "+mn-ea": ("minor", "eastAsian"), "+mn-cs": ("minor", "complex"),
        }
        slot = alias_slots.get(alias.lower())
        if slot is None:
            return None
        family = self.slots.get(slot)
        if family:
            return family
        fonts = self.script_fonts.get((slot[0], "eastAsian" if script == "eastAsian" else slot[1]), {})
        for code in _drawingml_script_codes(script, text):
            if fonts.get(code):
                return fonts[code]
        return None


def pptx_themes_by_slide(source: Path) -> tuple[PptxThemeFonts | None, ...]:
    """Return each slide's reachable theme without following external targets."""
    with ZipFile(source) as archive:
        parts = frozenset(archive.namelist())
        presentation_part = _root_presentation_part(archive, parts)
        if presentation_part is None:
            return ()
        try:
            presentation = ElementTree.fromstring(archive.read(presentation_part))
        except ElementTree.ParseError:
            return ()
        relationships = _relationships(archive, parts, presentation_part)
        themes: list[PptxThemeFonts | None] = []
        for slide in presentation.findall(f".//{{{_PRESENTATION}}}sldId"):
            relationship_id = slide.get(f"{{{_OFFICE_RELATIONSHIPS}}}id")
            slide_part = relationships.get(relationship_id or "")
            themes.append(_theme_from_slide(archive, parts, slide_part))
        return tuple(themes)


def _root_presentation_part(archive: ZipFile, parts: frozenset[str]) -> str | None:
    for relationship_id, target in _relationships(archive, parts, None).items():
        if relationship_id and target.endswith(".xml") and target.startswith("ppt/"):
            return target
    return None


def _theme_from_slide(
    archive: ZipFile, parts: frozenset[str], slide_part: str | None
) -> PptxThemeFonts | None:
    current = slide_part
    for required_suffix in ("/slideLayout", "/slideMaster", "/theme"):
        if current is None:
            return None
        relationships = _typed_relationships(archive, parts, current)
        current = next((target for relationship_type, target in relationships.values()
                        if relationship_type.endswith(required_suffix)), None)
    if current is None:
        return None
    try:
        theme = ElementTree.fromstring(archive.read(current))
    except (KeyError, ElementTree.ParseError):
        return None
    return _parse_theme(theme)


def _relationships(
    archive: ZipFile, parts: frozenset[str], source_part: str | None
) -> dict[str, str]:
    relationships_part = _relationships_part_name(source_part)
    if relationships_part not in parts:
        return {}
    try:
        root = ElementTree.fromstring(archive.read(relationships_part))
    except ElementTree.ParseError:
        return {}
    result: dict[str, str] = {}
    for relationship in root:
        if relationship.tag != f"{{{_RELATIONSHIPS}}}Relationship" or relationship.get("TargetMode") == "External":
            continue
        target = _target_part_name(source_part, relationship.get("Target"))
        relationship_id = relationship.get("Id")
        if not relationship_id or target is None or target not in parts:
            continue
        result[relationship_id] = target
    return result


def _typed_relationships(
    archive: ZipFile, parts: frozenset[str], source_part: str | None
) -> dict[str, tuple[str, str]]:
    relationships_part = _relationships_part_name(source_part)
    if relationships_part not in parts:
        return {}
    try:
        root = ElementTree.fromstring(archive.read(relationships_part))
    except ElementTree.ParseError:
        return {}
    result: dict[str, tuple[str, str]] = {}
    for relationship in root:
        if relationship.tag != f"{{{_RELATIONSHIPS}}}Relationship" or relationship.get("TargetMode") == "External":
            continue
        target = _target_part_name(source_part, relationship.get("Target"))
        relationship_id = relationship.get("Id")
        if relationship_id and target is not None and target in parts:
            result[relationship_id] = (relationship.get("Type") or "", target)
    return result


def _relationships_part_name(source_part: str | None) -> str:
    if source_part is None:
        return "_rels/.rels"
    parent, basename = posixpath.split(source_part)
    return posixpath.join(parent, "_rels", f"{basename}.rels")


def _target_part_name(source_part: str | None, target: str | None) -> str | None:
    if not target:
        return None
    base = "" if source_part is None else posixpath.dirname(source_part)
    result = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join(base, target))
    return None if result in {"", ".", ".."} or result.startswith("../") else result


def _parse_theme(theme: ElementTree.Element) -> PptxThemeFonts | None:
    scheme = theme.find(f".//{{{_DRAWING}}}fontScheme")
    if scheme is None:
        return None
    slots: dict[tuple[str, str], str] = {}
    scripts: dict[tuple[str, str], dict[str, str]] = {}
    for kind, element_name in (("major", "majorFont"), ("minor", "minorFont")):
        element = scheme.find(f"{{{_DRAWING}}}{element_name}")
        if element is None:
            continue
        for script, tag in (("latin", "latin"), ("eastAsian", "ea"), ("complex", "cs")):
            family = element.find(f"{{{_DRAWING}}}{tag}")
            if family is not None and family.get("typeface"):
                slots[(kind, script)] = family.get("typeface") or ""
        scripts[(kind, "eastAsian")] = {
            font.get("script") or "": font.get("typeface") or ""
            for font in element.findall(f"{{{_DRAWING}}}font") if font.get("typeface")
        }
    return PptxThemeFonts(slots, scripts)


def resolve_theme_typefaces(
    references: tuple[SourceTypefaceReference, ...], theme: PptxThemeFonts | None, text: str = ""
) -> tuple[SourceTypefaceReference, ...]:
    """Keep original aliases while adding concrete source-face requests."""
    return tuple(
        SourceTypefaceReference(
            item.script, item.original_family,
            None if theme is None else theme.resolve(item.original_family, item.script, text),
        )
        for item in references
    )


def theme_fonts_from_xml(data: bytes | None) -> PptxThemeFonts | None:
    """Parse a contained DrawingML theme part without following any target."""
    if data is None:
        return None
    try:
        return _parse_theme(ElementTree.fromstring(data))
    except ElementTree.ParseError:
        return None


def _drawingml_script_codes(script: str, text: str) -> tuple[str, ...]:
    if script != "eastAsian":
        return ()
    names = " ".join(unicodedata.name(character, "") for character in text)
    if "HIRAGANA" in names or "KATAKANA" in names:
        return ("Jpan",)
    if "HANGUL" in names:
        return ("Hang", "Kore")
    return ("Hans", "Hant", "Jpan", "Hang", "Kore")
