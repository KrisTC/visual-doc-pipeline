#!/usr/bin/env python3
"""Synthetic tests for direct editable-vector text replacement."""

from __future__ import annotations

from io import BytesIO
import base64
import struct
import unittest
from unittest.mock import patch

from PIL import Image

from pipeline import bounded_text_layout
from pipeline.vector_text import replace_vector_text
from pipeline.vector_text.replacer import (
    _EmfCoordinateState,
    _EmfFont,
    _EmfRectangle,
    _EmfTextCandidate,
    _emf_grouped_unclipped_fit_contexts,
    _emf_measured_source_bounds,
    _emf_unclipped_fit_contexts,
)
from pipeline.text_replacement import TextReplacementRequest, TextReplacementResult


def _mask(text: str) -> str:
    return "#" * len(text)


class VectorTextReplacerTests(unittest.TestCase):
    # Verifies FR-2026-08-04-07.
    def test_fits_svg_text_only_when_an_explicit_clip_rectangle_exists(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return TextReplacementResult("A substantially longer replacement", 1.0)

        result = replace_vector_text(
            b'''<svg xmlns="http://www.w3.org/2000/svg"><defs><clipPath id="box"><rect width="40" height="20"/></clipPath></defs><text clip-path="url(#box)" font-family="Source Sans" font-size="20">old</text><text font-size="20">free</text></svg>''',
            ".svg", _mask, "en", document_text_layout="preserve-basic-layout",
            replacement_provider=_Provider(), target_language="en",
        )

        self.assertIn(b"A substantially longer replacement", result.data)
        self.assertIn(b"Noto Sans JP", result.data)
        self.assertLess(float(result.data.split(b'font-size="')[1].split(b"px")[0]), 20.0)
        self.assertIn(b"####", result.data)

    # Verifies FR-2026-08-03-05.
    def test_replaces_svg_text_and_retains_vector_structure(self) -> None:
        result = replace_vector_text(
            b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/><text>Top<tspan>Inner</tspan>Tail</text></svg>',
            ".svg",
            _mask,
            "en",
        )

        self.assertTrue(result.has_editable_text)
        self.assertEqual(3, result.replaced_text_items)
        self.assertIn(b"<ns0:path", result.data)
        self.assertNotIn(b"Top", result.data)
        self.assertNotIn(b"Inner", result.data)
        self.assertNotIn(b"Tail", result.data)

    # Verifies FR-2026-08-03-11 and SR-2026-08-03-02.
    def test_replaces_svg_data_image_without_dereferencing_external_href(self) -> None:
        image = Image.new("RGB", (2, 1), "white")
        encoded = BytesIO(); image.save(encoded, format="PNG")
        source = (
            b'<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,'
            + base64.b64encode(encoded.getvalue())
            + b'"/><image href="https://example.invalid/image.png"/></svg>'
        )
        calls = 0

        def replace_image(embedded: Image.Image) -> int:
            nonlocal calls
            calls += 1
            embedded.paste("black", (0, 0, embedded.width, embedded.height))
            return 1

        result = replace_vector_text(source, ".svg", _mask, "en", replace_image)

        self.assertEqual(1, calls)
        self.assertEqual(1, result.replaced_image_regions)
        self.assertIn(b"https://example.invalid/image.png", result.data)

    # Verifies FR-2026-08-03-05.
    def test_reports_svg_without_editable_text(self) -> None:
        source = b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>'

        result = replace_vector_text(source, ".svg", _mask, "en")

        self.assertFalse(result.has_editable_text)
        self.assertEqual(0, result.replaced_text_items)
        self.assertEqual(source, result.data)

    # Verifies FR-2026-08-03-05.
    def test_replaces_unicode_emf_exttextout_record(self) -> None:
        source = _emf_with_text("Hello")

        result = replace_vector_text(source, ".emf", _mask, "en")

        self.assertTrue(result.has_editable_text)
        self.assertEqual(1, result.replaced_text_items)
        self.assertEqual("#####", _emf_text(result.data))
        self.assertEqual(len(result.data), struct.unpack_from("<I", result.data, 48)[0])

    # Verifies FR-2026-09-04-01.
    def test_fits_unclipped_emf_text_and_stops_at_a_vertical_line(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return TextReplacementResult("A considerably longer heading", 1.0)

        source = _emf_with_unclipped_text(line_x=60)
        contexts = _emf_unclipped_fit_contexts(source, measure_source_fonts=False)
        context = next(iter(contexts.values()))

        result = replace_vector_text(
            source,
            ".emf",
            _mask,
            "en",
            document_text_layout="preserve-basic-layout",
            replacement_provider=_Provider(),
            target_language="en",
        )

        self.assertEqual(60, context.fitting_bounds.right)
        self.assertEqual("A considerably longer heading", _emf_text(result.data))
        self.assertEqual((0.0, 0.0), _emf_text_scales(result.data)[0])
        font_heights = _emf_font_heights(result.data)
        self.assertLess(abs(font_heights[0]), abs(font_heights[1]))
        self.assertEqual(-20, font_heights[1])
        self.assertEqual([1, 82, 82], _emf_record_types(result.data)[:3])
        self.assertEqual(10, struct.unpack_from("<I", result.data, 52)[0])
        self.assertEqual(3, struct.unpack_from("<H", result.data, 56)[0])

    # Verifies FR-2026-09-05-02.
    def test_fits_contiguous_emf_records_as_one_expanding_visual_line(self) -> None:
        class _Provider:
            def __init__(self) -> None:
                self.requests: list[str] = []

            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                self.requests.append(request.text)
                return TextReplacementResult("A considerably longer grouped heading", 1.0)

        provider = _Provider()
        source = _emf_with_grouped_unclipped_text(line_x=60)
        contexts, suppressed = _emf_grouped_unclipped_fit_contexts(
            source, measure_source_fonts=False
        )

        result = replace_vector_text(
            source,
            ".emf",
            _mask,
            "en",
            document_text_layout="preserve-basic-layout",
            replacement_provider=provider,
            target_language="en",
        )

        self.assertEqual(1, len(contexts))
        self.assertEqual(1, len(suppressed))
        context = next(iter(contexts.values()))
        self.assertEqual(58, context.fitting_bounds.right)
        assert context.render_bounds is not None
        self.assertEqual(60, context.render_bounds.right)
        self.assertEqual(["AB"], provider.requests)
        self.assertEqual(
            ["A considerably longer grouped heading", ""], _emf_texts(result.data)
        )
        self.assertEqual(2, result.replaced_text_items)
        self.assertLess(abs(_emf_font_heights(result.data)[0]), 20)
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-09-05-02.
    def test_does_not_group_emf_records_across_a_drawing_record(self) -> None:
        class _Provider:
            def __init__(self) -> None:
                self.requests: list[str] = []

            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                self.requests.append(request.text)
                return TextReplacementResult("A considerably longer heading", 1.0)

        provider = _Provider()
        source = _emf_with_grouped_unclipped_text(intervening_line=True)

        result = replace_vector_text(
            source,
            ".emf",
            _mask,
            "en",
            document_text_layout="preserve-basic-layout",
            replacement_provider=provider,
            target_language="en",
        )

        self.assertEqual(["A", "B"], provider.requests)
        self.assertEqual(2, result.replaced_text_items)
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-09-05-02.
    def test_groups_across_reconciled_non_painting_state_records(self) -> None:
        class _Provider:
            def __init__(self) -> None:
                self.requests: list[str] = []

            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                self.requests.append(request.text)
                return TextReplacementResult("One coherent replacement", 1.0)

        provider = _Provider()
        result = replace_vector_text(
            _emf_with_grouped_unclipped_text(state_only_intervening=True),
            ".emf",
            _mask,
            "en",
            document_text_layout="preserve-basic-layout",
            replacement_provider=provider,
            target_language="en",
        )

        self.assertEqual(["AB"], provider.requests)
        self.assertEqual(["One coherent replacement", ""], _emf_texts(result.data))
        self.assertEqual(0, _emf_text_options(result.data)[0] & 4)
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-09-05-02.
    def test_active_device_context_clip_caps_group_expansion(self) -> None:
        source = _emf_with_grouped_unclipped_text(state_clip_right=45)
        contexts, _suppressed = _emf_grouped_unclipped_fit_contexts(
            source, measure_source_fonts=False
        )

        context = next(iter(contexts.values()))

        self.assertEqual(43, context.fitting_bounds.right)
        assert context.render_bounds is not None
        self.assertEqual(45, context.render_bounds.right)

    # Verifies FR-2026-09-05-02.
    def test_group_fitting_reserves_a_percentage_renderer_safety_margin(self) -> None:
        source = _emf_with_grouped_unclipped_text()
        contexts, _suppressed = _emf_grouped_unclipped_fit_contexts(
            source, measure_source_fonts=False
        )

        context = next(iter(contexts.values()))

        self.assertEqual(194, context.fitting_bounds.right)
        assert context.render_bounds is not None
        self.assertEqual(200, context.render_bounds.right)

    # Verifies FR-2026-09-05-02.
    def test_groups_three_emf_records_and_preserves_a_visual_gap_as_space(self) -> None:
        class _Provider:
            def __init__(self) -> None:
                self.requests: list[str] = []

            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                self.requests.append(request.text)
                return TextReplacementResult("A considerably longer grouped heading", 1.0)

        provider = _Provider()
        source = _emf_with_grouped_unclipped_text(second_left=12, include_third=True)

        result = replace_vector_text(
            source,
            ".emf",
            _mask,
            "en",
            document_text_layout="preserve-basic-layout",
            replacement_provider=provider,
            target_language="en",
        )

        self.assertEqual(["A BC"], provider.requests)
        self.assertEqual(
            ["A considerably longer grouped heading", "", ""], _emf_texts(result.data)
        )
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-09-05-02.
    def test_groups_compatible_clipped_emf_records_without_a_rendering_clip(self) -> None:
        class _Provider:
            def __init__(self) -> None:
                self.requests: list[str] = []

            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                self.requests.append(request.text)
                return TextReplacementResult("A considerably longer grouped heading", 1.0)

        provider = _Provider()
        source = _emf_with_grouped_unclipped_text(line_x=60, clipped=True)

        result = replace_vector_text(
            source,
            ".emf",
            _mask,
            "en",
            document_text_layout="preserve-basic-layout",
            replacement_provider=provider,
            target_language="en",
        )

        self.assertEqual(["AB"], provider.requests)
        self.assertEqual((0, 0, 100, 20), _emf_text_bounds(result.data)[0])
        self.assertEqual(0, _emf_text_options(result.data)[0] & 4)
        self.assertEqual(["A considerably longer grouped heading", ""], _emf_texts(result.data))
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-09-05-02.
    def test_groups_across_text_state_changes_and_uses_dominant_typography(self) -> None:
        class _Provider:
            def __init__(self) -> None:
                self.requests: list[str] = []

            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                self.requests.append(request.text)
                return TextReplacementResult("A longer coherent replacement", 1.0)

        provider = _Provider()
        result = replace_vector_text(
            _emf_with_text_state_changed_group(),
            ".emf",
            _mask,
            "en",
            document_text_layout="preserve-basic-layout",
            replacement_provider=provider,
            target_language="en",
        )

        self.assertEqual(["ABBB"], provider.requests)
        self.assertEqual(["A longer coherent replacement", ""], _emf_texts(result.data))
        self.assertIn(24, _emf_record_types(result.data))
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-09-05-02.
    def test_groups_stock_font_records_using_generated_noto_fallback(self) -> None:
        class _Provider:
            def __init__(self) -> None:
                self.requests: list[str] = []

            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                self.requests.append(request.text)
                return TextReplacementResult("A longer coherent replacement", 1.0)

        provider = _Provider()
        result = replace_vector_text(
            _emf_with_stock_font_group(),
            ".emf",
            _mask,
            "en",
            document_text_layout="preserve-basic-layout",
            replacement_provider=provider,
            target_language="en",
        )

        self.assertEqual(["AB"], provider.requests)
        self.assertEqual(["A longer coherent replacement", ""], _emf_texts(result.data))
        self.assertEqual([1, 82], _emf_record_types(result.data)[:2])
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-09-05-02.
    def test_groups_mixed_bounded_and_measurement_derived_fragments(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                self.request = request.text
                return TextReplacementResult("One coherent replacement", 1.0)

        provider = _Provider()
        result = replace_vector_text(
            _emf_with_mixed_area_group(),
            ".emf",
            _mask,
            "en",
            document_text_layout="preserve-basic-layout",
            replacement_provider=provider,
            target_language="en",
        )

        self.assertEqual("AB", provider.request)
        self.assertEqual(["One coherent replacement", ""], _emf_texts(result.data))
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-09-04-01 and FR-2026-09-05-02.
    def test_emf_header_bounds_cap_and_disable_free_space_expansion(self) -> None:
        capped = _emf_with_unclipped_text(header_right=45)
        capped_context = next(iter(_emf_unclipped_fit_contexts(
            capped, measure_source_fonts=False
        ).values()))
        self.assertEqual(45, capped_context.fitting_bounds.right)

        unreconciled = bytearray(_emf_with_unclipped_text())
        struct.pack_into("<iiii", unreconciled, 8, 0, -100, 35, 100)
        unreconciled_context = next(iter(_emf_unclipped_fit_contexts(
            bytes(unreconciled), measure_source_fonts=False
        ).values()))
        invalid = bytearray(_emf_with_unclipped_text())
        struct.pack_into("<iiii", invalid, 8, 0, 0, 0, 0)
        invalid_context = next(iter(_emf_unclipped_fit_contexts(
            bytes(invalid), measure_source_fonts=False
        ).values()))
        self.assertEqual(
            invalid_context.fitting_bounds, unreconciled_context.fitting_bounds
        )

    # Verifies FR-2026-09-05-01.
    def test_unclipped_emf_fitting_uses_source_bound_for_transforms(self) -> None:
        adjacent_source = _emf_with_unclipped_text(adjacent_text_left=60)
        adjacent_contexts = _emf_unclipped_fit_contexts(
            adjacent_source, measure_source_fonts=False
        )
        first_context = next(iter(adjacent_contexts.values()))
        self.assertEqual(60, first_context.fitting_bounds.right)

        transformed_source = _emf_with_unclipped_text(
            transform_records=(_emf_modify_world_transform_record(0.0, 1.0, -1.0, 0.0),)
        )
        transformed_context = next(iter(_emf_unclipped_fit_contexts(
            transformed_source, measure_source_fonts=False
        ).values()))
        self.assertFalse(transformed_context.allows_expansion)
        self.assertLessEqual(
            transformed_context.fitting_bounds.width, transformed_context.source_bounds.width
        )
        result = replace_vector_text(
            transformed_source,
            ".emf",
            _mask,
            "en",
            document_text_layout="preserve-basic-layout-source-font",
            replacement_provider=_LongReplacementProvider(),
            target_language="en",
        )
        self.assertEqual((0.0, 0.0), _emf_text_scales(result.data)[0])
        self.assertLess(abs(_emf_font_heights(result.data)[0]), 20)

    # Verifies FR-2026-09-05-01.
    def test_unclipped_emf_fitting_accepts_rotation_reflection_and_shear(self) -> None:
        transforms = {
            "rotation": (0.0, 1.0, -1.0, 0.0),
            "reflection": (-1.0, 0.0, 0.0, 1.0),
            "shear": (1.0, 0.5, 0.0, 1.0),
        }
        for name, matrix in transforms.items():
            with self.subTest(transform=name):
                transform_record = _emf_modify_world_transform_record(*matrix)
                source = _emf_with_unclipped_text(
                    transform_records=(transform_record,)
                )
                context = next(iter(_emf_unclipped_fit_contexts(
                    source, measure_source_fonts=False
                ).values()))
                self.assertFalse(context.allows_expansion)
                result = replace_vector_text(
                    source,
                    ".emf",
                    _mask,
                    "en",
                    document_text_layout="preserve-basic-layout",
                    replacement_provider=_LongReplacementProvider(),
                    target_language="en",
                )
                self.assertLess(abs(_emf_font_heights(result.data)[0]), 20)
                self.assertIn(transform_record, result.data)
                self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-09-05-01.
    def test_unclipped_emf_fitting_accepts_affine_mapping_and_saved_state(self) -> None:
        transform_records = (
            _emf_set_map_mode_record(8),
            _emf_set_origin_record(10, 10, 20),
            _emf_set_origin_record(12, 30, 40),
            _emf_set_extent_record(9, 20, 30),
            _emf_set_extent_record(11, 40, 60),
            _emf_scale_extent_record(32, 2, 1, 3, 2),
            _emf_scale_extent_record(31, 3, 2, 4, 3),
            _emf_graphics_mode_record(2),
            _emf_save_dc_record(),
            _emf_modify_world_transform_record(2.0, 0.0, 0.0, 3.0),
            _emf_save_dc_record(),
            _emf_modify_world_transform_record(1.0, 0.0, 0.0, 1.0, 10.0, 20.0),
            _emf_restore_dc_record(-1),
            _emf_restore_dc_record(-1),
            _emf_modify_world_transform_record(1.0, 0.5, 0.0, 1.0),
        )
        source = _emf_with_unclipped_text(transform_records=transform_records)

        context = next(iter(_emf_unclipped_fit_contexts(
            source, measure_source_fonts=False
        ).values()))
        self.assertFalse(context.allows_expansion)
        result = replace_vector_text(
            source,
            ".emf",
            _mask,
            "en",
            document_text_layout="preserve-basic-layout",
            replacement_provider=_LongReplacementProvider(),
            target_language="en",
        )

        self.assertEqual("A considerably longer heading", _emf_text(result.data))
        self.assertLess(abs(_emf_font_heights(result.data)[0]), 20)

    # Verifies FR-2026-09-05-01.
    def test_unclipped_emf_fitting_accepts_all_world_transform_operations(self) -> None:
        transforms = (
            ("set", (_emf_set_world_transform_record(2.0, 0.0, 0.0, 3.0),)),
            ("identity", (_emf_modify_world_transform_record(0.0, 0.0, 0.0, 0.0, mode=1),)),
            ("left", (_emf_modify_world_transform_record(2.0, 0.0, 0.0, 3.0, mode=2),)),
            ("right", (_emf_modify_world_transform_record(2.0, 0.0, 0.0, 3.0, mode=3),)),
            ("modify_set", (_emf_modify_world_transform_record(2.0, 0.0, 0.0, 3.0, mode=4),)),
        )
        for name, records in transforms:
            with self.subTest(operation=name):
                source = _emf_with_unclipped_text(transform_records=records)
                self.assertEqual(1, len(_emf_unclipped_fit_contexts(
                    source, measure_source_fonts=False
                )))

    # Verifies FR-2026-09-05-01.
    def test_unclipped_emf_fitting_accepts_each_map_mode(self) -> None:
        for map_mode in range(1, 9):
            with self.subTest(map_mode=map_mode):
                source = _emf_with_unclipped_text(
                    transform_records=(_emf_set_map_mode_record(map_mode),)
                )
                self.assertEqual(1, len(_emf_unclipped_fit_contexts(
                    source, measure_source_fonts=False
                )))

    # Verifies FR-2026-09-05-01.
    def test_unclipped_emf_fitting_falls_back_for_singular_transform(self) -> None:
        source = _emf_with_unclipped_text(
            transform_records=(_emf_modify_world_transform_record(0.0, 0.0, 0.0, 1.0),)
        )
        self.assertEqual({}, _emf_unclipped_fit_contexts(source, measure_source_fonts=False))
        result = replace_vector_text(
            source,
            ".emf",
            _mask,
            "en",
            document_text_layout="preserve-basic-layout",
            replacement_provider=_LongReplacementProvider(),
            target_language="en",
        )
        self.assertEqual([-20], _emf_font_heights(result.data))

    # Verifies FR-2026-09-05-01.
    def test_unclipped_emf_fitting_falls_back_for_invalid_state_restore(self) -> None:
        source = _emf_with_unclipped_text(transform_records=(_emf_restore_dc_record(-1),))
        self.assertEqual({}, _emf_unclipped_fit_contexts(source, measure_source_fonts=False))

    # Verifies FR-2026-09-05-01.
    def test_clipped_emf_fitting_respects_transformed_state_validity(self) -> None:
        rotated = _emf_with_clipped_text(
            (_emf_modify_world_transform_record(0.0, 1.0, -1.0, 0.0),)
        )
        fitted = replace_vector_text(
            rotated,
            ".emf",
            _mask,
            "en",
            document_text_layout="preserve-basic-layout",
            replacement_provider=_LongReplacementProvider(),
            target_language="en",
        )
        self.assertLess(_emf_text_scales(fitted.data)[0][0], 1.0)

        singular = _emf_with_clipped_text(
            (_emf_modify_world_transform_record(0.0, 0.0, 0.0, 1.0),)
        )
        retained = replace_vector_text(
            singular,
            ".emf",
            _mask,
            "en",
            document_text_layout="preserve-basic-layout",
            replacement_provider=_LongReplacementProvider(),
            target_language="en",
        )
        self.assertEqual((0.0, 0.0), _emf_text_scales(retained.data)[0])

    # Verifies FR-2026-09-04-01.
    def test_unclipped_emf_uses_noto_for_basic_layout_and_requests_source_measurement(self) -> None:
        source = _emf_with_unclipped_text(font_family="Unavailable Test Source Face")
        with patch(
            "pipeline.bounded_text_layout.source_font_measurement",
            wraps=bounded_text_layout.source_font_measurement,
        ) as source_measurement:
            replace_vector_text(
                source,
                ".emf",
                _mask,
                "en",
                document_text_layout="preserve-basic-layout",
                replacement_provider=_LongReplacementProvider(),
                target_language="en",
            )
            self.assertEqual(0, source_measurement.call_count)

        with patch(
            "pipeline.bounded_text_layout.source_font_measurement",
            wraps=bounded_text_layout.source_font_measurement,
        ) as source_measurement:
            replace_vector_text(
                source,
                ".emf",
                _mask,
                "en",
                document_text_layout="preserve-basic-layout-source-font",
                replacement_provider=_LongReplacementProvider(),
                target_language="en",
            )
            self.assertGreater(source_measurement.call_count, 0)

    # Verifies FR-2026-09-04-01.
    def test_unclipped_emf_accepts_one_unit_source_bound_rounding(self) -> None:
        font = _EmfFont("Noto Sans JP", 12.0, False, False)
        wide_candidate = _EmfTextCandidate(
            0,
            _EmfRectangle(0, 0, 1_000, 20),
            "Old",
            font,
            1,
            b"font",
            0,
            _EmfCoordinateState(),
        )
        measured = _emf_measured_source_bounds(wide_candidate, False)
        self.assertIsNotNone(measured)
        assert measured is not None
        tight_candidate = _EmfTextCandidate(
            0,
            _EmfRectangle(0, 0, measured.right - 1, 20),
            "Old",
            font,
            1,
            b"font",
            0,
            _EmfCoordinateState(),
        )
        reconciled = _emf_measured_source_bounds(tight_candidate, False)
        self.assertIsNotNone(reconciled)
        assert reconciled is not None
        assert tight_candidate.bounds is not None
        self.assertEqual(tight_candidate.bounds.right, reconciled.right)

    # Verifies FR-2026-08-03-09.
    def test_replaces_embedded_emf_stretchdibits_image_in_memory(self) -> None:
        source = _emf_with_stretchdibits_image()
        processed_sizes: list[tuple[int, int]] = []

        def replace_image(image: Image.Image) -> int:
            processed_sizes.append(image.size)
            image.paste("black", (0, 0, image.width, image.height))
            return 1

        result = replace_vector_text(source, ".emf", _mask, "en", replace_image)

        self.assertEqual([(2, 1)], processed_sizes)
        self.assertTrue(result.has_embedded_bitmaps)
        self.assertEqual(1, result.replaced_image_regions)
        self.assertEqual((0, 0, 0), _emf_stretchdibits_pixel(result.data))
        self.assertEqual(len(result.data), struct.unpack_from("<I", result.data, 48)[0])
        self.assertEqual(14, struct.unpack_from("<I", result.data, len(result.data) - 20)[0])

    # Verifies FR-2026-08-03-05.
    def test_replaces_wmf_textout_record(self) -> None:
        source = _wmf_with_text("Hello")

        result = replace_vector_text(source, ".wmf", _mask, "en")

        self.assertTrue(result.has_editable_text)
        self.assertEqual(1, result.replaced_text_items)
        self.assertEqual(b"#####", _wmf_text(result.data))
        self.assertEqual(len(result.data) // 2, struct.unpack_from("<I", result.data, 6)[0])

    # Verifies FR-2026-08-03-12.
    def test_replaces_wmf_stretchdib_image_in_memory(self) -> None:
        source = _wmf_with_stretchdib_image()

        def replace_image(image: Image.Image) -> int:
            image.paste("black", (0, 0, image.width, image.height))
            return 1

        result = replace_vector_text(source, ".wmf", _mask, "en", replace_image)

        self.assertTrue(result.has_embedded_bitmaps)
        self.assertEqual(1, result.replaced_image_regions)
        self.assertEqual((0, 0, 0), _wmf_stretchdib_pixel(result.data))


def _emf_with_text(text: str) -> bytes:
    text_bytes = text.encode("utf-16-le")
    record = bytearray(76 + len(text_bytes))
    struct.pack_into("<II", record, 0, 84, len(record))
    struct.pack_into("<I", record, 44, len(text))
    struct.pack_into("<I", record, 48, 76)
    record[76:] = text_bytes
    record.extend(b"\0" * ((-len(record)) % 4))
    struct.pack_into("<I", record, 4, len(record))
    header = bytearray(88)
    struct.pack_into("<II", header, 0, 1, len(header))
    struct.pack_into("<iiii", header, 8, 0, -100, 200, 100)
    eof = struct.pack("<IIIII", 14, 20, 0, 0, 0)
    result = bytearray(header + record + eof)
    struct.pack_into("<I", result, 48, len(result))
    struct.pack_into("<I", result, 52, 3)
    return bytes(result)


def _emf_text(data: bytes) -> str:
    return _emf_texts(data)[0]


def _emf_texts(data: bytes) -> list[str]:
    texts: list[str] = []
    record_offset = 0
    while record_offset < len(data):
        record_type, record_size = struct.unpack_from("<II", data, record_offset)
        if record_type == 84:
            string_length = struct.unpack_from("<I", data, record_offset + 44)[0]
            string_offset = struct.unpack_from("<I", data, record_offset + 48)[0]
            texts.append(data[
                record_offset + string_offset : record_offset + string_offset + (string_length * 2)
            ].decode("utf-16-le"))
        record_offset += record_size
    if not texts:
        raise AssertionError("Expected an EMR_EXTTEXTOUTW record.")
    return texts


def _emf_text_bounds(data: bytes) -> list[tuple[int, int, int, int]]:
    return _emf_text_rectangles(data, 8)


def _emf_text_clips(data: bytes) -> list[tuple[int, int, int, int]]:
    return _emf_text_rectangles(data, 56)


def _emf_text_options(data: bytes) -> list[int]:
    options: list[int] = []
    record_offset = 0
    while record_offset < len(data):
        record_type, record_size = struct.unpack_from("<II", data, record_offset)
        if record_type == 84:
            options.append(struct.unpack_from("<I", data, record_offset + 52)[0])
        record_offset += record_size
    return options


def _emf_text_rectangles(data: bytes, rectangle_offset: int) -> list[tuple[int, int, int, int]]:
    rectangles: list[tuple[int, int, int, int]] = []
    record_offset = 0
    while record_offset < len(data):
        record_type, record_size = struct.unpack_from("<II", data, record_offset)
        if record_type == 84:
            rectangles.append(struct.unpack_from("<iiii", data, record_offset + rectangle_offset))
        record_offset += record_size
    return rectangles


class _LongReplacementProvider:
    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        return TextReplacementResult("A considerably longer heading", 1.0)


def _emf_text_scales(data: bytes) -> list[tuple[float, float]]:
    scales: list[tuple[float, float]] = []
    offset = 0
    while offset < len(data):
        record_type, record_size = struct.unpack_from("<II", data, offset)
        if record_type == 84:
            scales.append(struct.unpack_from("<ff", data, offset + 28))
        offset += record_size
    return scales


def _emf_font_heights(data: bytes) -> list[int]:
    heights: list[int] = []
    offset = 0
    while offset < len(data):
        record_type, record_size = struct.unpack_from("<II", data, offset)
        if record_type == 82:
            heights.append(struct.unpack_from("<i", data, offset + 12)[0])
        offset += record_size
    return heights


def _emf_record_types(data: bytes) -> list[int]:
    record_types: list[int] = []
    offset = 0
    while offset < len(data):
        record_type, record_size = struct.unpack_from("<II", data, offset)
        record_types.append(record_type)
        offset += record_size
    return record_types


def _emf_is_structurally_valid(data: bytes) -> bool:
    offset = 0
    count = 0
    while offset + 8 <= len(data):
        _record_type, record_size = struct.unpack_from("<II", data, offset)
        if record_size < 8 or offset + record_size > len(data):
            return False
        offset += record_size
        count += 1
    return (
        offset == len(data)
        and struct.unpack_from("<I", data, 48)[0] == len(data)
        and struct.unpack_from("<I", data, 52)[0] == count
    )


def _emf_with_unclipped_text(
    *,
    line_x: int | None = None,
    adjacent_text_left: int | None = None,
    transform_records: tuple[bytes, ...] = (),
    font_family: str = "Noto Sans JP",
    header_right: int = 200,
) -> bytes:
    records = [_emf_font_record(font_family), _emf_select_object_record(1)]
    records.extend(transform_records)
    if line_x is not None:
        records.extend((_emf_move_to_record(line_x, -10), _emf_line_to_record(line_x, 30)))
    records.append(_emf_exttextout_record("Old", 0, 0, 40, 20))
    if adjacent_text_left is not None:
        records.append(_emf_exttextout_record("Value", adjacent_text_left, 0, 120, 20))
    header = bytearray(88)
    struct.pack_into("<II", header, 0, 1, len(header))
    struct.pack_into("<iiii", header, 8, 0, -100, header_right, 100)
    eof = struct.pack("<IIIII", 14, 20, 0, 0, 0)
    result = bytearray(header + b"".join(records) + eof)
    struct.pack_into("<I", result, 48, len(result))
    struct.pack_into("<I", result, 52, len(records) + 2)
    return bytes(result)


def _emf_with_grouped_unclipped_text(
    *,
    line_x: int | None = None,
    intervening_line: bool = False,
    second_left: int = 10,
    include_third: bool = False,
    clipped: bool = False,
    state_only_intervening: bool = False,
    state_clip_right: int | None = None,
) -> bytes:
    records = [
        _emf_font_record("Noto Sans JP"),
        _emf_select_object_record(1),
        _emf_exttextout_record(
            "A", 0, 0, 10, 20, clipped=clipped,
            clip_bounds=(0, 0, 100, 20) if clipped else None,
        ),
    ]
    if intervening_line:
        records.extend((_emf_move_to_record(60, -10), _emf_line_to_record(60, 30)))
    if state_only_intervening:
        records.extend((
            _emf_save_dc_record(),
            struct.pack("<III", 28, 12, 10),
            struct.pack("<III", 70, 12, 0),
            _emf_extselect_clip_rect_record(0, -100, 200, 100),
            _emf_restore_dc_record(-1),
        ))
    if state_clip_right is not None:
        records.append(_emf_extselect_clip_rect_record(0, -100, state_clip_right, 100))
    records.append(_emf_exttextout_record(
        "B", second_left, 0, second_left + 30, 20, clipped=clipped,
        clip_bounds=(0, 0, 100, 20) if clipped else None,
    ))
    if include_third:
        records.append(_emf_exttextout_record(
            "C", second_left + 10, 0, second_left + 40, 20, clipped=clipped,
            clip_bounds=(0, 0, 100, 20) if clipped else None,
        ))
    if line_x is not None:
        records.extend((_emf_move_to_record(line_x, -10), _emf_line_to_record(line_x, 30)))
    header = bytearray(88)
    struct.pack_into("<II", header, 0, 1, len(header))
    struct.pack_into("<iiii", header, 8, 0, -100, 200, 100)
    eof = struct.pack("<IIIII", 14, 20, 0, 0, 0)
    result = bytearray(header + b"".join(records) + eof)
    struct.pack_into("<I", result, 48, len(result))
    struct.pack_into("<I", result, 52, len(records) + 2)
    return bytes(result)


def _emf_with_clipped_text(transform_records: tuple[bytes, ...]) -> bytes:
    records = [
        _emf_font_record("Noto Sans JP"),
        _emf_select_object_record(1),
        *transform_records,
        _emf_exttextout_record("Old", 0, 0, 40, 20, clipped=True),
    ]
    header = bytearray(88)
    struct.pack_into("<II", header, 0, 1, len(header))
    struct.pack_into("<iiii", header, 8, 0, -100, 200, 100)
    eof = struct.pack("<IIIII", 14, 20, 0, 0, 0)
    result = bytearray(header + b"".join(records) + eof)
    struct.pack_into("<I", result, 48, len(result))
    struct.pack_into("<I", result, 52, len(records) + 2)
    return bytes(result)


def _emf_with_text_state_changed_group() -> bytes:
    records = [
        _emf_font_record("Noto Sans JP", handle=1, height=-20),
        _emf_select_object_record(1),
        _emf_set_text_color_record(0x000000),
        _emf_exttextout_record("A", 0, 0, 10, 20),
        _emf_font_record("Noto Sans", handle=2, height=-16),
        _emf_select_object_record(2),
        _emf_set_text_color_record(0x0000FF),
        _emf_set_text_alignment_record(0x0002),
        struct.pack("<IIi", 108, 12, 1),
        struct.pack("<IIii", 120, 16, 1, 1),
        _emf_exttextout_record("BBB", 10, 0, 50, 20),
    ]
    header = bytearray(88)
    struct.pack_into("<II", header, 0, 1, len(header))
    struct.pack_into("<iiii", header, 8, 0, -100, 200, 100)
    eof = struct.pack("<IIIII", 14, 20, 0, 0, 0)
    result = bytearray(header + b"".join(records) + eof)
    struct.pack_into("<I", result, 48, len(result))
    struct.pack_into("<I", result, 52, len(records) + 2)
    return bytes(result)


def _emf_with_stock_font_group() -> bytes:
    records = [
        _emf_select_object_record(0x8000000D),
        _emf_exttextout_record("A", 0, 0, 10, 20),
        _emf_exttextout_record("B", 10, 0, 40, 20),
    ]
    header = bytearray(88)
    struct.pack_into("<II", header, 0, 1, len(header))
    struct.pack_into("<iiii", header, 8, 0, -100, 200, 100)
    eof = struct.pack("<IIIII", 14, 20, 0, 0, 0)
    result = bytearray(header + b"".join(records) + eof)
    struct.pack_into("<I", result, 48, len(result))
    struct.pack_into("<I", result, 52, len(records) + 2)
    return bytes(result)


def _emf_with_mixed_area_group() -> bytes:
    records = [
        _emf_font_record("Noto Sans JP"),
        _emf_select_object_record(1),
        _emf_exttextout_record("A", 0, 0, 10, 20),
        _emf_exttextout_record("B", 10, 0, 40, 20, bounded=False),
    ]
    header = bytearray(88)
    struct.pack_into("<II", header, 0, 1, len(header))
    struct.pack_into("<iiii", header, 8, 0, -100, 200, 100)
    eof = struct.pack("<IIIII", 14, 20, 0, 0, 0)
    result = bytearray(header + b"".join(records) + eof)
    struct.pack_into("<I", result, 48, len(result))
    struct.pack_into("<I", result, 52, len(records) + 2)
    return bytes(result)


def _emf_font_record(family: str, *, handle: int = 1, height: int = -20) -> bytes:
    record = bytearray(104)
    struct.pack_into("<II", record, 0, 82, len(record))
    struct.pack_into("<I", record, 8, handle)
    struct.pack_into("<iiiii", record, 12, height, 0, 0, 0, 400)
    record[40:104] = family.encode("utf-16-le").ljust(64, b"\0")
    return bytes(record)


def _emf_select_object_record(handle: int) -> bytes:
    return struct.pack("<III", 37, 12, handle)


def _emf_set_text_color_record(color: int) -> bytes:
    return struct.pack("<III", 24, 12, color)


def _emf_set_text_alignment_record(alignment: int) -> bytes:
    return struct.pack("<III", 22, 12, alignment)


def _emf_extselect_clip_rect_record(left: int, top: int, right: int, bottom: int) -> bytes:
    rectangle = struct.pack("<iiii", left, top, right, bottom)
    region_data = struct.pack("<IIII", 32, 1, 1, 16) + rectangle + rectangle
    return struct.pack("<IIII", 75, 16 + len(region_data), len(region_data), 5) + region_data


def _emf_move_to_record(x: int, y: int) -> bytes:
    return struct.pack("<IIii", 27, 16, x, y)


def _emf_line_to_record(x: int, y: int) -> bytes:
    return struct.pack("<IIii", 54, 16, x, y)


def _emf_modify_world_transform_record(
    m11: float,
    m12: float,
    m21: float,
    m22: float,
    dx: float = 0.0,
    dy: float = 0.0,
    mode: int = 4,
) -> bytes:
    return struct.pack("<IIffffffI", 36, 36, m11, m12, m21, m22, dx, dy, mode)


def _emf_set_world_transform_record(
    m11: float, m12: float, m21: float, m22: float, dx: float = 0.0, dy: float = 0.0
) -> bytes:
    return struct.pack("<IIffffff", 35, 32, m11, m12, m21, m22, dx, dy)


def _emf_set_map_mode_record(mode: int) -> bytes:
    return struct.pack("<IIi", 17, 12, mode)


def _emf_set_extent_record(record_type: int, x: int, y: int) -> bytes:
    return struct.pack("<IIii", record_type, 16, x, y)


def _emf_set_origin_record(record_type: int, x: int, y: int) -> bytes:
    return struct.pack("<IIii", record_type, 16, x, y)


def _emf_scale_extent_record(
    record_type: int, x_numerator: int, x_denominator: int, y_numerator: int, y_denominator: int
) -> bytes:
    return struct.pack(
        "<IIiiii", record_type, 24, x_numerator, x_denominator, y_numerator, y_denominator
    )


def _emf_graphics_mode_record(mode: int) -> bytes:
    return struct.pack("<III", 98, 12, mode)


def _emf_save_dc_record() -> bytes:
    return struct.pack("<II", 33, 8)


def _emf_restore_dc_record(relative: int) -> bytes:
    return struct.pack("<IIi", 34, 12, relative)


def _emf_exttextout_record(
    text: str,
    left: int,
    top: int,
    right: int,
    bottom: int,
    *,
    clipped: bool = False,
    clip_bounds: tuple[int, int, int, int] | None = None,
    bounded: bool = True,
) -> bytes:
    text_bytes = text.encode("utf-16-le")
    record = bytearray(76 + len(text_bytes))
    struct.pack_into("<II", record, 0, 84, len(record))
    if bounded:
        struct.pack_into("<iiii", record, 8, left, top, right, bottom)
    struct.pack_into("<ii", record, 36, left, top)
    struct.pack_into("<I", record, 44, len(text))
    struct.pack_into("<I", record, 48, 76)
    if clipped:
        struct.pack_into("<I", record, 52, 4)
        struct.pack_into("<iiii", record, 56, *(clip_bounds or (left, top, right, bottom)))
    record[76:] = text_bytes
    record.extend(b"\0" * ((-len(record)) % 4))
    struct.pack_into("<I", record, 4, len(record))
    return bytes(record)


def _emf_with_stretchdibits_image() -> bytes:
    image = Image.new("RGB", (2, 1), "white")
    bitmap = BytesIO()
    image.save(bitmap, format="BMP")
    bitmap_data = bitmap.getvalue()
    pixel_offset = struct.unpack_from("<I", bitmap_data, 10)[0]
    bitmap_info = bitmap_data[14:pixel_offset]
    bitmap_bits = bitmap_data[pixel_offset:]
    record = bytearray(80)
    struct.pack_into("<II", record, 0, 81, 80 + len(bitmap_info) + len(bitmap_bits))
    struct.pack_into("<iiiiii", record, 24, 0, 0, 0, 0, 2, 1)
    struct.pack_into("<IIII", record, 48, 80, len(bitmap_info), 80 + len(bitmap_info), len(bitmap_bits))
    struct.pack_into("<ii", record, 72, 2, 1)
    record.extend(bitmap_info)
    record.extend(bitmap_bits)
    record.extend(b"\0" * ((-len(record)) % 4))
    struct.pack_into("<I", record, 4, len(record))
    header = bytearray(88)
    struct.pack_into("<II", header, 0, 1, len(header))
    eof = struct.pack("<IIIII", 14, 20, 0, 0, 0)
    result = bytearray(header + record + eof)
    struct.pack_into("<I", result, 48, len(result))
    struct.pack_into("<I", result, 52, 3)
    return bytes(result)


def _emf_stretchdibits_pixel(data: bytes) -> tuple[int, int, int]:
    record_offset = struct.unpack_from("<I", data, 4)[0]
    bitmap_info_offset, bitmap_info_size, bitmap_bits_offset, bitmap_bits_size = struct.unpack_from(
        "<IIII", data, record_offset + 48
    )
    bitmap_file = _bitmap_file_from_dib(
        data[record_offset + bitmap_info_offset : record_offset + bitmap_info_offset + bitmap_info_size],
        data[record_offset + bitmap_bits_offset : record_offset + bitmap_bits_offset + bitmap_bits_size],
    )
    with Image.open(BytesIO(bitmap_file)) as image:
        pixel = image.convert("RGB").getpixel((0, 0))
    if not isinstance(pixel, tuple) or len(pixel) != 3:
        raise AssertionError("Expected an RGB pixel.")
    return int(pixel[0]), int(pixel[1]), int(pixel[2])


def _bitmap_file_from_dib(bitmap_info: bytes, bitmap_bits: bytes) -> bytes:
    return (
        struct.pack(
            "<2sIHHI", b"BM", 14 + len(bitmap_info) + len(bitmap_bits), 0, 0, 14 + len(bitmap_info)
        )
        + bitmap_info
        + bitmap_bits
    )


def _wmf_with_text(text: str) -> bytes:
    text_bytes = text.encode("latin-1")
    record = bytearray(8)
    struct.pack_into("<H", record, 4, 0x0521)
    struct.pack_into("<H", record, 6, len(text_bytes))
    record.extend(text_bytes)
    if len(text_bytes) % 2:
        record.append(0)
    record.extend(struct.pack("<hh", 0, 0))
    struct.pack_into("<I", record, 0, len(record) // 2)
    eof = struct.pack("<IH", 3, 0)
    header = bytearray(struct.pack("<HHHIHIH", 1, 9, 0x0300, 0, 0, 0, 0))
    result = bytearray(header + record + eof)
    struct.pack_into("<I", result, 6, len(result) // 2)
    return bytes(result)


def _wmf_text(data: bytes) -> bytes:
    header_size = struct.unpack_from("<H", data, 2)[0] * 2
    string_length = struct.unpack_from("<H", data, header_size + 6)[0]
    return data[header_size + 8 : header_size + 8 + string_length]


def _wmf_with_stretchdib_image() -> bytes:
    image = Image.new("RGB", (2, 1), "white")
    bitmap = BytesIO(); image.save(bitmap, format="BMP")
    data = bitmap.getvalue(); offset = struct.unpack_from("<I", data, 10)[0]
    dib = data[14:]
    record = bytearray(28 + len(dib))
    struct.pack_into("<H", record, 4, 0x0F43)
    record[28:] = dib
    if len(record) % 2: record.append(0)
    struct.pack_into("<I", record, 0, len(record) // 2)
    eof = struct.pack("<IH", 3, 0)
    header = bytearray(struct.pack("<HHHIHIH", 1, 9, 0x0300, 0, 0, 0, 0))
    result = bytearray(header + record + eof)
    struct.pack_into("<I", result, 6, len(result) // 2)
    return bytes(result)


def _wmf_stretchdib_pixel(data: bytes) -> tuple[int, int, int]:
    offset = struct.unpack_from("<H", data, 2)[0] * 2
    dib = data[offset + 28 : -6]
    with Image.open(BytesIO(_bitmap_file_from_dib(dib[:40], dib[40:]))) as image:
        pixel = image.convert("RGB").getpixel((0, 0))
    if not isinstance(pixel, tuple) or len(pixel) != 3: raise AssertionError("Expected RGB pixel.")
    return int(pixel[0]), int(pixel[1]), int(pixel[2])


if __name__ == "__main__":
    unittest.main()
