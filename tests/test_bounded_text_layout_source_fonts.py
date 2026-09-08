"""Synthetic tests for source-face selection in bounded-text fitting."""

from __future__ import annotations

import shutil
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import call, patch

import skia  # type: ignore[import-not-found]

from pipeline import bounded_text_layout
from pipeline.bounded_text_layout import (
    BoundedTextBox,
    BoundedTextParagraph,
    BoundedTextRun,
    EmbeddedTypefaceCandidate,
    SourceTypefaceReference,
    _portable_segments,
    fit_explicit_noto_text_box,
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

    # Verifies FR-2026-09-07-04.
    def test_uses_an_exact_face_from_the_optional_mounted_font_catalog(self) -> None:
        assert self.typeface is not None
        with TemporaryDirectory() as temporary_directory:
            mounted_directory = Path(temporary_directory)
            shutil.copyfile(FONT_PATH, mounted_directory / FONT_PATH.name)
            with patch.object(
                bounded_text_layout, "MOUNTED_FONT_DIRECTORY", mounted_directory
            ):
                bounded_text_layout._mounted_font_manager.cache_clear()
                try:
                    measurement = source_font_measurement(self._box())
                finally:
                    bounded_text_layout._mounted_font_manager.cache_clear()

        self.assertEqual("mounted-source-face", measurement.selections[0].source)
        key = measurement.text_box.paragraphs[0].runs[0].font_classification
        self.assertEqual(FONT_FAMILY, measurement.typefaces[key].getFamilyName())

    # Verifies FR-2026-09-07-04.
    def test_mounted_face_can_be_used_for_source_font_output(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            mounted_directory = Path(temporary_directory)
            shutil.copyfile(FONT_PATH, mounted_directory / FONT_PATH.name)
            with patch.object(
                bounded_text_layout, "MOUNTED_FONT_DIRECTORY", mounted_directory
            ):
                bounded_text_layout._mounted_font_manager.cache_clear()
                try:
                    fitted = fit_explicit_noto_text_box(
                        self._box(),
                        preserve_source_font_family=True,
                        measure_source_fonts=True,
                    )
                finally:
                    bounded_text_layout._mounted_font_manager.cache_clear()

        output_run = fitted.text_box.paragraphs[0].runs[0]
        self.assertEqual(FONT_FAMILY, output_run.font_family)
        self.assertEqual(
            (SourceTypefaceReference("latin", FONT_FAMILY),),
            output_run.source_typefaces,
        )

    # Verifies FR-2026-09-07-04.
    def test_ignores_a_malformed_mounted_font_and_uses_the_existing_fallback(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            mounted_directory = Path(temporary_directory)
            (mounted_directory / "broken.ttf").write_bytes(b"not a font")
            with patch.object(
                bounded_text_layout, "MOUNTED_FONT_DIRECTORY", mounted_directory
            ):
                bounded_text_layout._mounted_font_manager.cache_clear()
                try:
                    measurement = source_font_measurement(self._box())
                finally:
                    bounded_text_layout._mounted_font_manager.cache_clear()

        self.assertEqual("noto-fallback", measurement.selections[0].source)

    # Verifies FR-2026-09-07-04.
    def test_discovers_every_face_in_a_mounted_font_collection(self) -> None:
        assert self.typeface is not None
        with TemporaryDirectory() as temporary_directory:
            mounted_directory = Path(temporary_directory)
            collection = mounted_directory / "collection.ttc"
            # TTC header, version 1.0, two face offsets, then enough padding
            # to make the header structurally valid for catalog enumeration.
            collection.write_bytes(
                b"ttcf" + b"\x00\x01\x00\x00" + b"\x00\x00\x00\x02"
                + b"\x00\x00\x00\x14\x00\x00\x00\x18" + b"\x00" * 16
            )
            with (
                patch.object(bounded_text_layout, "MOUNTED_FONT_DIRECTORY", mounted_directory),
                patch.object(
                    skia.Typeface,
                    "MakeFromFile",
                    return_value=self.typeface,
                ) as load_face,
            ):
                bounded_text_layout._mounted_font_manager.cache_clear()
                try:
                    manager = bounded_text_layout._mounted_font_manager()
                finally:
                    bounded_text_layout._mounted_font_manager.cache_clear()

        self.assertIsNotNone(manager)
        self.assertEqual(
            [(str(collection), 0), (str(collection), 1)],
            [call.args for call in load_face.call_args_list],
        )

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

    # Verifies FR-2026-09-06-05.
    def test_applies_the_height_safety_margin_only_when_the_output_uses_noto(self) -> None:
        assert self.typeface is not None
        noto_fitted = fit_explicit_noto_text_box(
            self._box(), source_content_height_safety_factor=0.90
        )
        source_fitted = fit_explicit_noto_text_box(
            self._box(),
            embedded_faces=(
                EmbeddedTypefaceCandidate(FONT_FAMILY, self.typeface.fontStyle(), self.typeface),
            ),
            font_manager=_FontManager(None),
            preserve_source_font_family=True,
            measure_source_fonts=True,
            source_content_height_safety_factor=0.90,
        )
        fallback_fitted = fit_explicit_noto_text_box(
            self._box(),
            font_manager=_FontManager(None),
            preserve_source_font_family=True,
            measure_source_fonts=True,
            source_content_height_safety_factor=0.90,
        )
        dense_box = replace(self._box("Replacement " * 20), height_emu=400_000)
        dense_without_margin = fit_explicit_noto_text_box(dense_box)
        dense_with_margin = fit_explicit_noto_text_box(
            dense_box, source_content_height_safety_factor=0.90
        )

        self.assertEqual(450_000, noto_fitted.text_box.height_emu)
        self.assertEqual(500_000, source_fitted.text_box.height_emu)
        self.assertEqual(450_000, fallback_fitted.text_box.height_emu)
        self.assertLess(dense_with_margin.font_scale, dense_without_margin.font_scale)

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
