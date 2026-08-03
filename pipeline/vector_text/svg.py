"""SVG native text and self-contained raster replacement."""
from __future__ import annotations
import base64
from collections.abc import Callable
from io import BytesIO
import xml.etree.ElementTree as ElementTree
from PIL import Image
from pipeline.vector_text.common import VectorReplacementResult

_TEXT = frozenset({"text", "tspan", "textPath"})
_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/gif": "GIF", "image/bmp": "BMP", "image/tiff": "TIFF", "image/webp": "WEBP"}

def replace_svg(data: bytes, replace_text: Callable[[str], str], replace_image: Callable[[Image.Image], int] | None) -> VectorReplacementResult:
    try: root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error: raise ValueError("Invalid SVG image.") from error
    items, regions, bitmaps = _walk(root, False, replace_text, replace_image)
    if not items and not regions: return VectorReplacementResult(data, 0, False)
    return VectorReplacementResult(ElementTree.tostring(root, encoding="utf-8", xml_declaration=True), items, bool(items), regions, bitmaps)

def _walk(element: ElementTree.Element, inside_text: bool, replace_text: Callable[[str], str], replace_image: Callable[[Image.Image], int] | None) -> tuple[int, int, bool]:
    text_context = inside_text or _name(element.tag) in _TEXT
    items = 0
    if text_context and element.text: element.text = replace_text(element.text); items += 1
    regions, bitmaps = _replace_data_image(element, replace_image) if _name(element.tag) == "image" and replace_image else (0, False)
    for child in element:
        child_items, child_regions, child_bitmaps = _walk(child, text_context, replace_text, replace_image)
        items += child_items; regions += child_regions; bitmaps = bitmaps or child_bitmaps
        if text_context and child.tail: child.tail = replace_text(child.tail); items += 1
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
