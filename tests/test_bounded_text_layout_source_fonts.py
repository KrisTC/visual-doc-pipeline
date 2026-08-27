"""Synthetic tests for source-face selection in bounded-text fitting."""

from __future__ import annotations

from pathlib import Path
from dataclasses import replace
import unittest
from unittest.mock import patch

import skia  # type: ignore[import-not-found]

from pipeline.bounded_text_layout import (
    BoundedTextBox,
    BoundedTextParagraph,
    BoundedTextRun,
    EmbeddedTypefaceCandidate,
    SourceTypefaceReference,
    fit_explicit_noto_text_box,
    _portable_segments,
    source_font_measurement,
)


FONT_PATH = Path(__file__).parent / "assets" / "fonts" / "NotoSansCJKjp-Regular.ttf"
FONT_FAMILY = "Noto Sans CJK JP"


class _FontManager:
    def __init__(self, typeface: skia.Typeface | None) -> None:
        self.typeface = typeface

    def matchFamilyStyle(self, family: str, style: skia.FontStyle) -> skia.Typeface | None:
        return self.typeface


class SourceFontMeasurementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.typeface = skia.Typeface.MakeFromFile(str(FONT_PATH))
        self.assertIsNotNone(self.typeface)

    def _box(self, text: str = "Replacement") -> BoundedTextBox:
        return BoundedTextBox(
            1_000_000,
            500_000,
            0,
            0,
            0,
            0,
            None,
            (
                BoundedTextParagraph(
                    None,
                    None,
                    None,
                    None,
                    None,
                    0,
                    None,
                    None,
                    None,
                    None,
                    None,
                    (BoundedTextRun(text, FONT_FAMILY, "sans-serif", 18.0, False, False, None, None),),
                ),
            ),
        )

    # Verifies FR-2026-08-22-04.
    def test_prefers_a_verified_embedded_source_face(self) -> None:
        assert self.typeface is not None
        measurement = source_font_measurement(
            self._box(),
            embedded_faces=(
                EmbeddedTypefaceCandidate(FONT_FAMILY, self.typeface.fontStyle(), self.typeface),
            ),
            font_manager=_FontManager(None),
        )

        self.assertEqual("embedded-source-face", measurement.selections[0].source)
        key = measurement.text_box.paragraphs[0].runs[0].font_classification
        self.assertIs(self.typeface, measurement.typefaces[key])

    # Verifies FR-2026-08-22-04.
    def test_uses_only_an_exact_installed_family_and_style_match(self) -> None:
        assert self.typeface is not None
        measurement = source_font_measurement(
            self._box(), font_manager=_FontManager(self.typeface)
        )

        self.assertEqual("installed-source-face", measurement.selections[0].source)

    # Verifies FR-2026-08-22-04.
    def test_falls_back_when_the_source_face_lacks_a_replacement_glyph(self) -> None:
        assert self.typeface is not None
        measurement = source_font_measurement(
            self._box("\U0010ffff"), font_manager=_FontManager(self.typeface)
        )

        self.assertEqual("noto-fallback", measurement.selections[0].source)
        self.assertEqual("source-glyphs-unavailable", measurement.selections[0].fallback_reason)

    # Verifies FR-2026-08-27-02.
    def test_uses_the_verified_source_reference_for_output_only_when_selected(self) -> None:
        assert self.typeface is not None
        fitted = fit_explicit_noto_text_box(
            self._box(),
            embedded_faces=(
                EmbeddedTypefaceCandidate(FONT_FAMILY, self.typeface.fontStyle(), self.typeface),
            ),
            font_manager=_FontManager(None),
            preserve_source_font_family=True,
            measure_source_fonts=True,
        )

        output_run = fitted.text_box.paragraphs[0].runs[0]
        self.assertEqual(FONT_FAMILY, output_run.font_family)
        self.assertEqual((SourceTypefaceReference("latin", FONT_FAMILY),), output_run.source_typefaces)

    # Verifies FR-2026-08-22-04 and FR-2026-08-22-10.
    def test_selects_each_resolved_script_slot_and_reports_the_original_alias(self) -> None:
        assert self.typeface is not None
        box = self._box("A日")
        run = replace(
            box.paragraphs[0].runs[0],
            font_family="+mj-lt",
            source_typefaces=(
                SourceTypefaceReference("latin", "+mj-lt", FONT_FAMILY),
                SourceTypefaceReference("eastAsian", "+mj-ea", FONT_FAMILY),
            ),
        )
        box = replace(box, paragraphs=(replace(box.paragraphs[0], runs=(run,)),))
        measurement = source_font_measurement(box, font_manager=_FontManager(self.typeface))

        self.assertEqual(["latin", "eastAsian"], [item.script for item in measurement.selections])
        self.assertEqual(["+mj-lt", "+mj-ea"], [item.original_reference for item in measurement.selections])
        self.assertEqual([FONT_FAMILY, FONT_FAMILY], [item.resolved_family for item in measurement.selections])
        self.assertEqual(2, len(measurement.text_box.paragraphs[0].runs))

    # Verifies FR-2026-08-22-13.
    def test_uses_the_explicit_noto_generic_family_mapping(self) -> None:
        box = self._box()
        run = replace(
            box.paragraphs[0].runs[0],
            font_family="serif",
            source_typefaces=(SourceTypefaceReference("latin", "serif"),),
        )
        measurement = source_font_measurement(
            replace(box, paragraphs=(replace(box.paragraphs[0], runs=(run,)),)),
            font_manager=_FontManager(None),
        )

        self.assertEqual("Noto Serif JP", measurement.selections[0].measured_family)

    # Verifies FR-2026-08-27-05.
    def test_splits_ltr_fallback_at_grapheme_boundaries_and_combines_matching_faces(self) -> None:
        run = self._box("AB♜").paragraphs[0].runs[0]
        coverage = {
            ("base", "A"): True,
            ("base", "B"): True,
            ("base", "♜"): False,
            ("symbols", "A"): False,
            ("symbols", "B"): False,
            ("symbols", "♜"): True,
        }
        with patch(
            "pipeline.bounded_text_layout._glyphs_available",
            side_effect=lambda face, text: coverage[(face, text)],
        ):
            segments = _portable_segments(run, "base", (("symbols", "symbols"),))

        self.assertEqual(["AB", "♜"], [segment.text for segment in segments])
        self.assertEqual(
            ["sans-serif", "symbols"],
            [segment.font_classification for segment in segments],
        )
        self.assertTrue(all(not segment.source_typefaces for segment in segments))

    # Verifies FR-2026-08-27-07.
    def test_prefers_math_fallback_before_symbols(self) -> None:
        run = self._box("𝐶").paragraphs[0].runs[0]
        coverage = {
            ("base", "𝐶"): False,
            ("math", "𝐶"): True,
            ("symbols", "𝐶"): True,
        }
        with patch(
            "pipeline.bounded_text_layout._glyphs_available",
            side_effect=lambda face, text: coverage[(face, text)],
        ):
            segments = _portable_segments(
                run, "base", (("math", "math"), ("symbols", "symbols"))
            )

        self.assertEqual(["math"], [segment.font_classification for segment in segments])
        self.assertFalse(segments[0].bold)
        self.assertFalse(segments[0].italic)

    # Verifies FR-2026-08-27-05.
    def test_rejects_bidi_fallback_before_segmenting(self) -> None:
        run = self._box("Aא").paragraphs[0].runs[0]
        with self.assertRaisesRegex(ValueError, "bidirectional text"):
            _portable_segments(run, "base", (("symbols", "symbols"),))


if __name__ == "__main__":
    unittest.main()
