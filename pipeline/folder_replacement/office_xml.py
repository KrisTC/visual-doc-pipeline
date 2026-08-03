"""Shared OOXML native-text replacement and compatibility preservation."""

from __future__ import annotations

from collections.abc import Iterable
from io import BytesIO
import xml.etree.ElementTree as ElementTree

from pipeline.folder_replacement.common import replace_native_text
from pipeline.text_replacement import TextReplacementProvider


_WORDPROCESSING_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_DRAWING_NAMESPACE = "http://schemas.openxmlformats.org/drawingml/2006/main"
_SPREADSHEET_NAMESPACE = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_HTML_NAMESPACE = "http://www.w3.org/1999/xhtml"
_MARKUP_COMPATIBILITY_NAMESPACE = "http://schemas.openxmlformats.org/markup-compatibility/2006"

_MARKUP_COMPATIBILITY_PREFIX_LIST_ATTRIBUTES = frozenset(
    {
        f"{{{_MARKUP_COMPATIBILITY_NAMESPACE}}}Ignorable",
        f"{{{_MARKUP_COMPATIBILITY_NAMESPACE}}}Requires",
    }
)
_MARKUP_COMPATIBILITY_QNAME_LIST_ATTRIBUTES = frozenset(
    {
        f"{{{_MARKUP_COMPATIBILITY_NAMESPACE}}}PreserveAttributes",
        f"{{{_MARKUP_COMPATIBILITY_NAMESPACE}}}PreserveElements",
        f"{{{_MARKUP_COMPATIBILITY_NAMESPACE}}}ProcessContent",
    }
)


def replace_office_xml_text(
    data: bytes,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
) -> tuple[bytes, int]:
    """Replace visible OOXML text while retaining compatibility namespace bindings."""
    try:
        namespaces = _namespace_bindings(data)
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return data, 0
    replaced_items = 0
    for element in root.iter():
        if element.text is None or not _is_visible_office_text_element(element.tag):
            continue
        element.text = replace_native_text(
            element.text, replacement_provider, source_language, target_language
        )
        replaced_items += 1
    if not replaced_items:
        return data, 0
    return _serialize_with_compatibility_bindings(root, namespaces), replaced_items


def _namespace_bindings(data: bytes) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for _event, binding in ElementTree.iterparse(BytesIO(data), events=("start-ns",)):
        prefix, uri = binding
        if prefix not in bindings:
            bindings[prefix] = uri
    return bindings


def _serialize_with_compatibility_bindings(
    root: ElementTree.Element,
    namespace_bindings: dict[str, str],
) -> bytes:
    # ElementTree's stubs leave this encoding-selected return type dynamic.
    serialized = bytes(ElementTree.tostring(root, encoding="utf-8", xml_declaration=True))
    required_prefixes = _compatibility_prefixes(root)
    root_tag_start = serialized.find(b"<", serialized.find(b"?>") + 2)
    root_tag_end = serialized.find(b">", root_tag_start)
    existing_bindings = _namespace_prefixes(serialized[: root_tag_end + 1])
    missing_bindings = {
        prefix: namespace_bindings[prefix]
        for prefix in required_prefixes
        if prefix not in existing_bindings and prefix in namespace_bindings
    }
    if not missing_bindings:
        return serialized
    declarations = b"".join(
        f' xmlns:{prefix}="{uri}"'.encode("utf-8")
        for prefix, uri in sorted(missing_bindings.items())
    )
    return serialized[:root_tag_end] + declarations + serialized[root_tag_end:]


def _compatibility_prefixes(root: ElementTree.Element) -> set[str]:
    prefixes: set[str] = set()
    for element in root.iter():
        for attribute, value in element.attrib.items():
            if (
                attribute in _MARKUP_COMPATIBILITY_PREFIX_LIST_ATTRIBUTES
                or (
                    element.tag == f"{{{_MARKUP_COMPATIBILITY_NAMESPACE}}}Choice"
                    and attribute == "Requires"
                )
            ):
                prefixes.update(value.split())
            elif attribute in _MARKUP_COMPATIBILITY_QNAME_LIST_ATTRIBUTES:
                prefixes.update(_qname_prefixes(value.split()))
    return prefixes


def _qname_prefixes(values: Iterable[str]) -> set[str]:
    return {value.partition(":")[0] for value in values if ":" in value}


def _namespace_prefixes(start_tag: bytes) -> set[str]:
    prefixes: set[str] = set()
    cursor = 0
    while True:
        start = start_tag.find(b" xmlns:", cursor)
        if start < 0:
            return prefixes
        prefix_start = start + len(b" xmlns:")
        prefix_end = start_tag.find(b"=", prefix_start)
        if prefix_end < 0:
            return prefixes
        prefixes.add(start_tag[prefix_start:prefix_end].decode("ascii"))
        cursor = prefix_end + 1


def _is_visible_office_text_element(tag: str) -> bool:
    return tag in {
        f"{{{_WORDPROCESSING_NAMESPACE}}}t",
        f"{{{_WORDPROCESSING_NAMESPACE}}}delText",
        f"{{{_DRAWING_NAMESPACE}}}t",
        f"{{{_SPREADSHEET_NAMESPACE}}}t",
        f"{{{_HTML_NAMESPACE}}}div",
        f"{{{_HTML_NAMESPACE}}}span",
        "div",
        "span",
    }
