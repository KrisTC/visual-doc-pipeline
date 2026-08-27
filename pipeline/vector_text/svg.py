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
    SourceTypefaceReference,
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
    parents = {child: parent for parent in root.iter() for child in parent}
    css = _SvgCss(root, parents)
    typefaces = noto_typefaces()
    count = 0
    embedded: set[tuple[str, bool]] = set()
    elements: set[int] = set()
    for element in root.iter():
        if _name(element.tag) != "text" or list(element) or _inside_foreign_object(element, parents):
            continue
        text = element.text or ""
        clip = _clip_for(element, clips)
        if not text.strip() or clip is None:
            continue
        width, height = clip
        family = css.property_for(element, "font-family")
        classification = _classification(family)
        bold = css.property_for(element, "font-weight") in {"bold", "700", "800", "900"}
        italic = css.property_for(element, "font-style") in {"italic", "oblique"}
        size_px = _length(css.property_for(element, "font-size")) or 16.0
        references = _svg_source_typefaces(family)
        box = BoundedTextBox(
            round(width * _PX_TO_EMU), round(height * _PX_TO_EMU), 0, 0, 0, 0, None,
            (BoundedTextParagraph("left", None, None, None, None, 0, None, None, None, None,
                                  None, (BoundedTextRun(text, family, classification, size_px * 0.75,
                                                        bold, italic, "none", None, references),)),),
        )
        fitted = replace_and_fit_text_box(
            box, provider, source, target, typefaces,
            preserve_source_font_family=preserve_source_font,
            measure_source_fonts=preserve_source_font,
        )
        runs = fitted.text_box.paragraphs[0].runs
        if len(runs) == 1:
            run = runs[0]
            element.text = run.text
            element.set("font-size", f"{(run.font_size_points or 12.0) / 0.75:.4f}px")
            if not preserve_source_font or not run.source_typefaces:
                family_name, _path = static_noto_font(run.font_classification, run.bold)
                element.set("font-family", family_name)
                embedded.add((run.font_classification, bool(run.bold)))
        else:
            element.text = None
            for run in runs:
                span = ElementTree.SubElement(element, "tspan")
                span.text = run.text
                span.set("font-size", f"{(run.font_size_points or 12.0) / 0.75:.4f}px")
                family_name, _path = static_noto_font(run.font_classification, run.bold)
                span.set("font-family", family_name)
                embedded.add((run.font_classification, bool(run.bold)))
        count += 1
        elements.add(id(element))
    return count, embedded, elements


def _inside_foreign_object(
    element: ElementTree.Element, parents: dict[ElementTree.Element, ElementTree.Element]
) -> bool:
    current: ElementTree.Element | None = element
    while current is not None:
        if _name(current.tag) == "foreignObject":
            return True
        current = parents.get(current)
    return False


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


def _svg_source_typefaces(family: str | None) -> tuple[SourceTypefaceReference, ...]:
    """Return ordered per-script CSS candidates without treating generics as host faces."""
    candidates = _css_font_families(family)
    references: list[SourceTypefaceReference] = []
    for script in ("latin", "eastAsian", "complex"):
        for candidate in candidates:
            references.append(SourceTypefaceReference(script, candidate))
    return tuple(references)


def _css_font_families(value: str | None) -> tuple[str, ...]:
    if not value or "var(" in value.lower():
        return ()
    families: list[str] = []
    for raw in value.split(","):
        family = raw.strip().strip("'\"")
        if not family or any(token in family for token in ("(", ")", ";")):
            continue
        generic = {"serif", "monospace", "sans-serif"}
        if family.lower() in generic:
            # The common resolver's committed Noto fallback classification is
            # the explicit generic-family policy; no host generic is accepted.
            families.append(family.lower())
        else:
            families.append(family)
    return tuple(families)


class _SvgCss:
    """Small contained-only CSS cascade for SVG typography properties."""

    def __init__(self, root: ElementTree.Element, parents: dict[ElementTree.Element, ElementTree.Element]) -> None:
        self._parents = parents
        self._rules: list[tuple[tuple[str, ...], dict[str, str], int, int]] = []
        order = 0
        for style in root.iter():
            if _name(style.tag) != "style" or not style.text:
                continue
            for selector_text, declarations in re.findall(r"([^{}@]+)\{([^{}]*)\}", style.text):
                values = _css_declarations(declarations)
                if not values:
                    continue
                for selector in selector_text.split(","):
                    tokens = tuple(token for token in selector.strip().split() if token)
                    if tokens and all(_simple_selector(token) for token in tokens):
                        self._rules.append((tokens, values, _selector_specificity(tokens), order))
                        order += 1

    def property_for(self, element: ElementTree.Element, name: str) -> str | None:
        inherited = self.property_for(self._parents[element], name) if element in self._parents else None
        best: tuple[int, int, str] | None = None
        for tokens, values, specificity, order in self._rules:
            if name in values and _matches_selector(element, tokens, self._parents):
                candidate = (specificity, order, values[name])
                if best is None or candidate[:2] >= best[:2]:
                    best = candidate
        value = inherited if best is None else best[2]
        inline = _attribute(element, name)
        return inline if inline is not None and "var(" not in inline.lower() else value


def _css_declarations(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for declaration in text.split(";"):
        key, separator, value = declaration.partition(":")
        key, value = key.strip(), value.strip()
        if separator and key in {"font-family", "font-weight", "font-style", "font-size", "clip-path"} and "var(" not in value.lower():
            result[key] = value
    return result


def _simple_selector(value: str) -> bool:
    return bool(re.fullmatch(r"(?:[A-Za-z_][\w-]*)?(?:[.#][A-Za-z_][\w-]*)*", value))


def _selector_specificity(tokens: tuple[str, ...]) -> int:
    return sum(100 * token.count("#") + 10 * token.count(".") + (1 if token[:1].isalpha() else 0) for token in tokens)


def _matches_selector(element: ElementTree.Element, tokens: tuple[str, ...], parents: dict[ElementTree.Element, ElementTree.Element]) -> bool:
    current: ElementTree.Element | None = element
    for token in reversed(tokens):
        while current is not None and not _matches_simple_selector(current, token):
            current = parents.get(current)
        if current is None:
            return False
        current = parents.get(current)
    return True


def _matches_simple_selector(element: ElementTree.Element, selector: str) -> bool:
    name = re.match(r"^[A-Za-z_][\w-]*", selector)
    if name and _name(element.tag) != name.group(0):
        return False
    identifier = re.search(r"#([A-Za-z_][\w-]*)", selector)
    if identifier and element.get("id") != identifier.group(1):
        return False
    classes = set((element.get("class") or "").split())
    return all(class_name in classes for class_name in re.findall(r"\.([A-Za-z_][\w-]*)", selector))


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
    if id(element) in fitted_elements:
        # A multi-face fitted ``text`` element owns its generated ``tspan``
        # children; do not send them through the generic replacement path.
        return 0, 0, False
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
