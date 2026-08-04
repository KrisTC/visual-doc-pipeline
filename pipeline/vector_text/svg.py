"""SVG native text replacement, with fitting for explicitly clipped text."""

from __future__ import annotations

import base64
from collections.abc import Callable
from io import BytesIO
import re
import xml.etree.ElementTree as ElementTree

from PIL import Image

from pipeline.bounded_text_layout import (
    BoundedTextBox,
    BoundedTextParagraph,
    BoundedTextRun,
    noto_typefaces,
    replace_and_fit_text_box,
)
from pipeline.portable_fonts import static_noto_bytes, static_noto_font
from pipeline.text_replacement import TextReplacementProvider
from pipeline.vector_text.common import VectorReplacementResult


_TEXT = frozenset({"text", "tspan", "textPath"})
_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/gif": "GIF", "image/bmp": "BMP", "image/tiff": "TIFF", "image/webp": "WEBP"}
_PX_TO_EMU = 9_525
_URL = re.compile(r"^url\(#([^)]*)\)$")
_LENGTH = re.compile(r"^\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?:px|pt)?\s*$")


def replace_svg(
    data: bytes,
    replace_text: Callable[[str], str],
    replace_image: Callable[[Image.Image], int] | None,
    *,
    document_text_layout: str = "preserve-source-formatting",
    replacement_provider: TextReplacementProvider | None = None,
    source_language: str = "",
    target_language: str | None = None,
) -> VectorReplacementResult:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise ValueError("Invalid SVG image.") from error
    fitted = 0
    fitted_elements: set[int] = set()
    embedded: set[tuple[str, bool]] = set()
    if (
        document_text_layout in {"preserve-basic-layout", "preserve-basic-layout-source-font"}
        and replacement_provider is not None
        and target_language is not None
    ):
        fitted, embedded, fitted_elements = _fit_clipped_text(
            root, replacement_provider, source_language, target_language,
            document_text_layout == "preserve-basic-layout-source-font",
        )
        if embedded:
            _embed_faces(root, embedded)
    items, regions, bitmaps = _walk(root, False, replace_text, replace_image, fitted_elements)
    # A fitted text element is deliberately not sent through generic replacement
    # a second time.  The fallback walker still replaces every unqualified text.
    if not items and not regions and not fitted:
        return VectorReplacementResult(data, 0, False)
    return VectorReplacementResult(
        ElementTree.tostring(root, encoding="utf-8", xml_declaration=True),
        items + fitted,
        bool(items or fitted), regions, bitmaps,
    )


def _fit_clipped_text(
    root: ElementTree.Element,
    provider: TextReplacementProvider,
    source: str,
    target: str,
    preserve_source_font: bool,
) -> tuple[int, set[tuple[str, bool]], set[int]]:
    clips = _clip_rectangles(root)
    typefaces = noto_typefaces()
    count = 0
    embedded: set[tuple[str, bool]] = set()
    elements: set[int] = set()
    for element in root.iter():
        if _name(element.tag) != "text" or list(element):
            continue
        text = element.text or ""
        clip = _clip_for(element, clips)
        if not text.strip() or clip is None:
            continue
        width, height = clip
        family = _attribute(element, "font-family")
        classification = _classification(family)
        bold = _attribute(element, "font-weight") in {"bold", "700", "800", "900"}
        size_px = _length(_attribute(element, "font-size")) or 16.0
        box = BoundedTextBox(
            round(width * _PX_TO_EMU), round(height * _PX_TO_EMU), 0, 0, 0, 0, None,
            (BoundedTextParagraph("left", None, None, None, None, 0, None, None, None, None,
                                  None, (BoundedTextRun(text, family, classification, size_px * 0.75,
                                                        bold, False, "none", None),)),),
        )
        fitted = replace_and_fit_text_box(
            box, provider, source, target, typefaces,
            preserve_source_font_family=preserve_source_font,
        )
        run = fitted.text_box.paragraphs[0].runs[0]
        element.text = run.text
        element.set("font-size", f"{(run.font_size_points or 12.0) / 0.75:.4f}px")
        if not preserve_source_font:
            family_name, _path = static_noto_font(classification, bold)
            element.set("font-family", family_name)
            embedded.add((classification, bool(bold)))
        count += 1
        elements.add(id(element))
    return count, embedded, elements


def _clip_rectangles(root: ElementTree.Element) -> dict[str, tuple[float, float]]:
    rectangles: dict[str, tuple[float, float]] = {}
    for element in root.iter():
        if _name(element.tag) != "clipPath" or not element.get("id"):
            continue
        rectangle = next((item for item in element if _name(item.tag) == "rect"), None)
        if rectangle is None:
            continue
        width, height = _length(rectangle.get("width")), _length(rectangle.get("height"))
        if width is not None and height is not None and width > 0 and height > 0:
            rectangles[element.get("id", "")] = (width, height)
    return rectangles


def _clip_for(element: ElementTree.Element, clips: dict[str, tuple[float, float]]) -> tuple[float, float] | None:
    value = _attribute(element, "clip-path")
    match = None if value is None else _URL.match(value)
    return None if match is None else clips.get(match.group(1))


def _attribute(element: ElementTree.Element, name: str) -> str | None:
    direct = element.get(name)
    if direct is not None:
        return direct
    for declaration in (element.get("style") or "").split(";"):
        key, separator, value = declaration.partition(":")
        if separator and key.strip() == name:
            return value.strip()
    return None


def _length(value: str | None) -> float | None:
    match = None if value is None else _LENGTH.match(value)
    return None if match is None else float(match.group(1))


def _classification(family: str | None) -> str:
    value = (family or "").lower()
    if any(marker in value for marker in ("mono", "code", "courier", "fixed")):
        return "fixed-width"
    if any(marker in value for marker in ("serif", "mincho", "ming", "song")):
        return "serif"
    return "sans-serif"


def _embed_faces(root: ElementTree.Element, faces: set[tuple[str, bool]]) -> None:
    namespace = root.tag.rpartition("}")[0].lstrip("{") or "http://www.w3.org/2000/svg"
    definitions = next((item for item in root if _name(item.tag) == "defs"), None)
    if definitions is None:
        definitions = ElementTree.Element(f"{{{namespace}}}defs")
        root.insert(0, definitions)
    style = ElementTree.SubElement(definitions, f"{{{namespace}}}style", {"type": "text/css"})
    rules: list[str] = []
    for classification, bold in sorted(faces):
        family, _path = static_noto_font(classification, bold)
        encoded = base64.b64encode(static_noto_bytes(classification, bold)).decode("ascii")
        rules.append(
            "@font-face{font-family:'%s';font-style:normal;font-weight:%d;"
            "src:url(data:font/ttf;base64,%s) format('truetype');}" % (family, 700 if bold else 400, encoded)
        )
    style.text = "".join(rules)


def _walk(element: ElementTree.Element, inside_text: bool, replace_text: Callable[[str], str],
          replace_image: Callable[[Image.Image], int] | None, fitted_elements: set[int]) -> tuple[int, int, bool]:
    text_context = inside_text or _name(element.tag) in _TEXT
    items = 0
    if text_context and element.text and id(element) not in fitted_elements:
        element.text = replace_text(element.text); items += 1
    regions, bitmaps = _replace_data_image(element, replace_image) if _name(element.tag) == "image" and replace_image else (0, False)
    for child in element:
        child_items, child_regions, child_bitmaps = _walk(child, text_context, replace_text, replace_image, fitted_elements)
        items += child_items; regions += child_regions; bitmaps = bitmaps or child_bitmaps
        if text_context and child.tail:
            child.tail = replace_text(child.tail); items += 1
    return items, regions, bitmaps


def _replace_data_image(element: ElementTree.Element, replace_image: Callable[[Image.Image], int]) -> tuple[int, bool]:
    attribute = "href" if "href" in element.attrib else "{http://www.w3.org/1999/xlink}href"
    href = element.attrib.get(attribute)
    if href is None or not href.startswith("data:image/") or ";base64," not in href: return 0, False
    metadata, encoded = href.split(",", 1); mime = metadata[5:].split(";", 1)[0].lower(); format_name = _FORMATS.get(mime)
    if format_name is None: return 0, False
    try:
        with Image.open(BytesIO(base64.b64decode(encoded, validate=True))) as opened: image = opened.copy()
    except (OSError, ValueError): return 0, False
    regions = replace_image(image)
    if regions:
        output = BytesIO(); image.save(output, format=format_name)
        element.attrib[attribute] = f"data:{mime};base64," + base64.b64encode(output.getvalue()).decode("ascii")
    return regions, True


def _name(tag: str) -> str: return tag.rpartition("}")[2]
