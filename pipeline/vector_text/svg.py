"""SVG native text replacement, with fitting for explicitly clipped text."""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
import re
import xml.etree.ElementTree as ElementTree

from PIL import Image

from pipeline.bounded_text_layout import (
    BoundedTextBox,
    BoundedTextParagraph,
    BoundedTextRun,
    PortableTextUnsupportedError,
    SourceTypefaceReference,
    bounded_text_box_text,
    noto_typefaces,
    replace_and_fit_text_box,
    unsupported_text_diagnostic,
)
from pipeline.portable_fonts import static_noto_bytes, static_noto_font
from pipeline.text_replacement import TextReplacementProvider
from pipeline.vector_text.common import (
    NestedGraphic,
    SourceLineFont,
    VectorReplacementResult,
    measure_source_line,
    translate_and_fit_line,
)


_TEXT = frozenset({"text", "tspan", "textPath"})
_TRANSFORM = re.compile(r"([A-Za-z]+)\s*\(([^)]*)\)")
_DEFAULT_FONT_SIZE_PX = 16.0
_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/gif": "GIF", "image/bmp": "BMP", "image/tiff": "TIFF", "image/webp": "WEBP"}
_PX_TO_EMU = 9_525
_URL = re.compile(r"^url\(#([^)]*)\)$")
_LENGTH = re.compile(r"^\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?:px|pt)?\s*$")


@dataclass(slots=True)
class _ClippedText:
    """A clipped ``text`` element whose replacement is fitted into its clip rectangle."""

    element: ElementTree.Element
    box: BoundedTextBox
    text: str


@dataclass(slots=True)
class _FreeText:
    """An un-clipped text fitted to the extent its source text occupies (FR-2026-10-22-12)."""

    element: ElementTree.Element
    font: SourceLineFont
    size_px: float
    text: str
    measured: tuple[float, float]


@dataclass(slots=True)
class _TextSlot:
    """One piece of text (an element's own text or a child's tail) in a text context."""

    element: ElementTree.Element
    is_tail: bool
    text: str


@dataclass(slots=True)
class _DataImage:
    element: ElementTree.Element
    attribute: str
    mime: str
    format_name: str
    image: Image.Image


class SvgDocument:
    """A parsed SVG that lists its texts and images, then applies replacements."""

    def __init__(
        self,
        data: bytes,
        root: ElementTree.Element,
        clipped: list[_ClippedText],
        free: list[_FreeText],
        slots: list[_TextSlot],
        images: list[_DataImage],
        *,
        preserve_source_font: bool,
        source_language: str,
        target_language: str | None,
    ) -> None:
        self._data = data
        self._root = root
        self._clipped = clipped
        self._free = free
        self._slots = slots
        self._images = images
        self._preserve_source_font = preserve_source_font
        self._source_language = source_language
        self._target_language = target_language

    def texts(self) -> tuple[str, ...]:
        """Return the fitted texts, then every other text, in the order they are requested."""
        return (
            tuple(item.text for item in self._clipped)
            + tuple(item.text for item in self._free)
            + tuple(slot.text for slot in self._slots)
        )

    def images(self) -> list[Image.Image]:
        return [item.image for item in self._images]

    def nested(self) -> list[NestedGraphic]:
        return []

    def apply(
        self,
        replace_text: Callable[[str], str],
        replacement_provider: TextReplacementProvider | None,
        replace_image: Callable[[int, Image.Image], int] | None = None,
        replace_nested: Callable[[int], VectorReplacementResult | None] | None = None,
    ) -> VectorReplacementResult:
        fitted = 0
        diagnostics: list[dict[str, object]] = []
        if self._clipped or self._free:
            if replacement_provider is None or self._target_language is None:
                message = "Fitting SVG text needs a provider and a target language."
                raise ValueError(message)
            fitted, embedded = self._fit(replacement_provider, self._target_language, diagnostics)
            free_fitted, free_embedded = self._fit_free(
                replacement_provider, replace_text, self._target_language
            )
            fitted += free_fitted
            embedded |= free_embedded
            if embedded:
                _embed_faces(self._root, embedded)
        items = 0
        for slot in self._slots:
            replacement = replace_text(slot.text)
            if slot.is_tail:
                slot.element.tail = replacement
            else:
                slot.element.text = replacement
            items += 1
        regions = 0
        bitmaps = False
        if replace_image is not None:
            for index, item in enumerate(self._images):
                count = replace_image(index, item.image)
                bitmaps = True
                if count:
                    output = BytesIO()
                    item.image.save(output, format=item.format_name)
                    item.element.attrib[item.attribute] = (
                        f"data:{item.mime};base64," + base64.b64encode(output.getvalue()).decode("ascii")
                    )
                regions += count
        # A fitted text element is deliberately not sent through generic replacement
        # a second time.  The remaining slots still replace every unqualified text.
        if not items and not regions and not fitted:
            return VectorReplacementResult(
                self._data, 0, False, diagnostics=tuple(diagnostics)
            )
        return VectorReplacementResult(
            ElementTree.tostring(self._root, encoding="utf-8", xml_declaration=True),
            items + fitted,
            bool(items or fitted), regions, bitmaps, tuple(diagnostics),
        )

    def _fit(
        self,
        provider: TextReplacementProvider,
        target_language: str,
        diagnostics: list[dict[str, object]],
    ) -> tuple[int, set[tuple[str, bool]]]:
        typefaces = noto_typefaces()
        embedded: set[tuple[str, bool]] = set()
        retained = 0
        for item in self._clipped:
            try:
                fitted = replace_and_fit_text_box(
                    item.box, provider, self._source_language, target_language, typefaces,
                    preserve_source_font_family=self._preserve_source_font,
                    measure_source_fonts=self._preserve_source_font,
                )
            except PortableTextUnsupportedError as error:
                # FR-2026-08-27-09: keep this element as it was and carry on.
                retained += 1
                diagnostics.append(unsupported_text_diagnostic(
                    error, bounded_text_box_text(item.box), "svg_clipped_text", vector_format="svg",
                ))
                continue
            runs = fitted.text_box.paragraphs[0].runs
            element = item.element
            if len(runs) == 1:
                run = runs[0]
                element.text = run.text
                element.set("font-size", f"{(run.font_size_points or 12.0) / 0.75:.4f}px")
                if not self._preserve_source_font or not run.source_typefaces:
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
        return len(self._clipped) - retained, embedded

    def _fit_free(
        self,
        provider: TextReplacementProvider,
        replace_text: Callable[[str], str],
        target_language: str,
    ) -> tuple[int, set[tuple[str, bool]]]:
        embedded: set[tuple[str, bool]] = set()
        for item in self._free:
            width, _height = item.measured
            fitted = translate_and_fit_line(
                item.text, item.font, width, None, provider,
                self._source_language, target_language,
                preserve_source_font_family=self._preserve_source_font,
                measure_source_fonts=self._preserve_source_font,
            )
            if fitted is None:
                item.element.text = replace_text(item.text)
                continue
            item.element.text = fitted.text
            run = fitted.run
            if fitted.scale < 1.0:
                _set_style_property(item.element, "font-size", f"{item.size_px * fitted.scale:.4f}px")
            if not self._preserve_source_font or not run.source_typefaces:
                family_name, _path = static_noto_font(run.font_classification, run.bold)
                _set_style_property(item.element, "font-family", f"'{family_name}'")
                embedded.add((run.font_classification, bool(run.bold)))
        return len(self._free), embedded


def analyse_svg(
    data: bytes,
    *,
    document_text_layout: str = "preserve-source-formatting",
    fit_text: bool = False,
    source_language: str = "",
    target_language: str | None = None,
) -> SvgDocument:
    """Parse an SVG and list its texts and data images; replace nothing yet.

    ``fit_text`` is whether clipped text is fitted, which also removes those elements
    from the generic text list because the fit translates them.
    """
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise ValueError("Invalid SVG image.") from error
    preserve_source_font = document_text_layout == "preserve-basic-layout-source-font"
    parents = {child: parent for parent in root.iter() for child in parent}
    css = _SvgCss(root, parents)
    clipped = _clipped_texts(root, parents, css) if fit_text else []
    clipped_ids = {id(item.element) for item in clipped}
    free = _free_texts(root, parents, css, clipped_ids, preserve_source_font) if fit_text else []
    fitted_ids = clipped_ids | {id(item.element) for item in free}
    slots: list[_TextSlot] = []
    images: list[_DataImage] = []
    _collect(root, False, fitted_ids, slots, images)
    return SvgDocument(
        data, root, clipped, free, slots, images,
        preserve_source_font=preserve_source_font,
        source_language=source_language, target_language=target_language,
    )


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
    fit_text = (
        document_text_layout in {"preserve-basic-layout", "preserve-basic-layout-source-font"}
        and replacement_provider is not None
        and target_language is not None
    )
    document = analyse_svg(
        data, document_text_layout=document_text_layout, fit_text=fit_text,
        source_language=source_language, target_language=target_language,
    )
    return document.apply(
        replace_text, replacement_provider,
        None if replace_image is None else lambda _index, image: replace_image(image),
    )


def _clipped_texts(
    root: ElementTree.Element,
    parents: dict[ElementTree.Element, ElementTree.Element],
    css: _SvgCss,
) -> list[_ClippedText]:
    clips = _clip_rectangles(root)
    candidates: list[_ClippedText] = []
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
        candidates.append(_ClippedText(element, box, text))
    return candidates


def _free_texts(
    root: ElementTree.Element,
    parents: dict[ElementTree.Element, ElementTree.Element],
    css: _SvgCss,
    clipped_ids: set[int],
    measure_source_fonts: bool,
) -> list[_FreeText]:
    """List the un-clipped horizontal ``text`` and ``tspan`` elements that can be fitted safely."""
    candidates: list[_FreeText] = []
    for element in root.iter():
        text = element.text or ""
        if (
            _name(element.tag) not in {"text", "tspan"}
            or id(element) in clipped_ids
            or list(element)
            or not text.strip()
            or not _placed_safely(element, parents)
        ):
            continue
        raw_size = css.property_for(element, "font-size")
        size_px = _DEFAULT_FONT_SIZE_PX if raw_size is None else _length(raw_size)
        if size_px is None or size_px <= 0:
            continue
        family = css.property_for(element, "font-family")
        font = SourceLineFont(
            family, size_px * 0.75,
            css.property_for(element, "font-weight") in {"bold", "700", "800", "900"},
            css.property_for(element, "font-style") in {"italic", "oblique"},
            _classification(family), _svg_source_typefaces(family),
        )
        measured = measure_source_line(text, font, measure_source_fonts=measure_source_fonts)
        if measured is not None:
            candidates.append(_FreeText(element, font, size_px, text, measured))
    return candidates


def _placed_safely(
    element: ElementTree.Element, parents: dict[ElementTree.Element, ElementTree.Element]
) -> bool:
    """Whether the text is horizontal and unrotated, outside foreignObject and textPath."""
    current: ElementTree.Element | None = element
    while current is not None:
        if _name(current.tag) in {"foreignObject", "textPath"}:
            return False
        writing_mode = (_attribute(current, "writing-mode") or "").strip().lower()
        if writing_mode.startswith(("tb", "vertical", "rl", "sideways")):
            return False
        rotate = current.get("rotate") if _name(current.tag) in {"text", "tspan"} else None
        if rotate and any(_number(item) != 0.0 for item in rotate.replace(",", " ").split()):
            return False
        if not _unrotated(_attribute(current, "transform")):
            return False
        current = parents.get(current)
    return True


def _number(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 1.0


def _unrotated(transform: str | None) -> bool:
    """Whether every transform function is a translation, a scale or an unrotated matrix."""
    if not transform or not transform.strip():
        return True
    if _TRANSFORM.sub("", transform).strip(" ,"):
        return False
    for name, arguments in _TRANSFORM.findall(transform):
        values = [_number(item) for item in arguments.replace(",", " ").split()]
        if name in {"translate", "scale"}:
            continue
        if name == "matrix" and len(values) == 6 and abs(values[1]) < 1e-9 and abs(values[2]) < 1e-9:
            continue
        if name == "rotate" and values and values[0] % 360.0 == 0.0:
            continue
        return False
    return True


def _set_style_property(element: ElementTree.Element, name: str, value: str) -> None:
    """Write a property into the inline style, which overrides attributes and style sheets."""
    declarations = [
        item.strip() for item in (element.get("style") or "").split(";")
        if item.strip() and item.partition(":")[0].strip() != name
    ]
    declarations.append(f"{name}:{value}")
    element.set("style", ";".join(declarations))


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


def _collect(
    element: ElementTree.Element,
    inside_text: bool,
    fitted_ids: set[int],
    slots: list[_TextSlot],
    images: list[_DataImage],
) -> None:
    if id(element) in fitted_ids:
        # A fitted ``text`` element, with the ``tspan`` children fitting may generate,
        # is replaced by the fit rather than by the generic text path.
        return
    text_context = inside_text or _name(element.tag) in _TEXT
    if text_context and element.text:
        slots.append(_TextSlot(element, False, element.text))
    if _name(element.tag) == "image":
        data_image = _data_image(element)
        if data_image is not None:
            images.append(data_image)
    for child in element:
        _collect(child, text_context, fitted_ids, slots, images)
        if text_context and child.tail:
            slots.append(_TextSlot(child, True, child.tail))


def _data_image(element: ElementTree.Element) -> _DataImage | None:
    attribute = "href" if "href" in element.attrib else "{http://www.w3.org/1999/xlink}href"
    href = element.attrib.get(attribute)
    if href is None or not href.startswith("data:image/") or ";base64," not in href:
        return None
    metadata, encoded = href.split(",", 1)
    mime = metadata[5:].split(";", 1)[0].lower()
    format_name = _FORMATS.get(mime)
    if format_name is None:
        return None
    try:
        with Image.open(BytesIO(base64.b64decode(encoded, validate=True))) as opened:
            image = opened.copy()
    except (OSError, ValueError):
        return None
    return _DataImage(element, attribute, mime, format_name, image)


def _name(tag: str) -> str: return tag.rpartition("}")[2]
