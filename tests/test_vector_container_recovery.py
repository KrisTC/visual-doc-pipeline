"""Synthetic tests that one unsupported vector text container never fails the graphic."""

from __future__ import annotations

import struct
import unittest

from pipeline.text_replacement import (
    TextReplacementItem,
    TextReplacementRequest,
    TextReplacementResult,
    replace_each,
)
from pipeline.vector_text import replace_vector_text
from test_vector_plan import _wmf_with_clipped_text
from test_vector_text_replacer import (
    _emf_exttextout_record,
    _emf_font_record,
    _emf_is_structurally_valid,
    _emf_select_object_record,
    _emf_texts,
)

# No approved portable face covers a private-use code point.
_UNCOVERED = "\ue000"


class _SelectiveProvider:
    """Returns an uncovered character for "Old" and a plain replacement for anything else."""

    def __init__(self) -> None:
        self.requested: list[str] = []

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        def one(text: str) -> TextReplacementItem:
            self.requested.append(text)
            return TextReplacementItem(_UNCOVERED if text == "Old" else "Fine", 1.0)

        return replace_each(request, one)


def _identity(text: str) -> str:
    return text


def _two_clipped_emf_texts() -> bytes:
    records = [
        _emf_font_record("Noto Sans JP"),
        _emf_select_object_record(1),
        _emf_exttextout_record("Old", 0, 0, 40, 20, clipped=True),
        _emf_exttextout_record("New", 0, 30, 40, 50, clipped=True),
    ]
    header = bytearray(88)
    struct.pack_into("<II", header, 0, 1, len(header))
    struct.pack_into("<iiii", header, 8, 0, -100, 200, 100)
    eof = struct.pack("<IIIII", 14, 20, 0, 0, 0)
    result = bytearray(header + b"".join(records) + eof)
    struct.pack_into("<I", result, 48, len(result))
    struct.pack_into("<I", result, 52, len(records) + 2)
    return bytes(result)


class VectorContainerRecoveryTests(unittest.TestCase):
    def _assert_diagnostic(self, diagnostics: tuple[dict[str, object], ...], vector_format: str) -> None:
        entries = [entry for entry in diagnostics if entry.get("kind") == "unsupported"]
        self.assertEqual(1, len(entries))
        entry = entries[0]
        self.assertEqual(vector_format, entry["vector_format"])
        self.assertEqual("Old", entry["source_text"])
        self.assertEqual(_UNCOVERED, entry["replacement_text"])
        self.assertEqual(["U+E000"], entry["code_points"])

    # Verifies FR-2026-08-27-09.
    def test_svg_retains_one_unsupported_clipped_text_and_replaces_its_neighbour(self) -> None:
        provider = _SelectiveProvider()
        result = replace_vector_text(
            b'<svg xmlns="http://www.w3.org/2000/svg"><defs><clipPath id="box">'
            b'<rect width="40" height="20"/></clipPath></defs>'
            b'<text clip-path="url(#box)" font-size="20">Old</text>'
            b'<text clip-path="url(#box)" font-size="20">New</text></svg>',
            ".svg", _identity, "en", document_text_layout="preserve-basic-layout",
            replacement_provider=provider, target_language="en",
        )

        self.assertIn(b">Old<", result.data)
        self.assertIn(b">Fine<", result.data)
        self.assertNotIn(_UNCOVERED.encode(), result.data)
        self.assertEqual(1, result.replaced_text_items)
        self._assert_diagnostic(result.diagnostics, "svg")
        self.assertEqual(1, provider.requested.count("Old"))

    # Verifies FR-2026-08-27-09.
    def test_emf_retains_one_unsupported_clipped_text_and_replaces_its_neighbour(self) -> None:
        provider = _SelectiveProvider()
        result = replace_vector_text(
            _two_clipped_emf_texts(), ".emf", _identity, "en",
            document_text_layout="preserve-basic-layout",
            replacement_provider=provider, target_language="en",
        )

        self.assertTrue(_emf_is_structurally_valid(result.data))
        self.assertEqual(["Old", "Fine"], _emf_texts(result.data))
        self.assertEqual(1, result.replaced_text_items)
        self._assert_diagnostic(result.diagnostics, "emf")
        self.assertEqual(1, provider.requested.count("Old"))

    # Verifies FR-2026-08-27-09.
    def test_wmf_retains_an_unsupported_clipped_text_and_still_returns_a_valid_graphic(self) -> None:
        source = _wmf_with_clipped_text("Old")
        provider = _SelectiveProvider()
        result = replace_vector_text(
            source, ".wmf", _identity, "en", document_text_layout="preserve-basic-layout",
            replacement_provider=provider, target_language="en",
        )

        self.assertEqual(source, result.data)
        self.assertEqual(0, result.replaced_text_items)
        self._assert_diagnostic(result.diagnostics, "wmf")
        self.assertEqual(1, provider.requested.count("Old"))


if __name__ == "__main__":
    unittest.main()
