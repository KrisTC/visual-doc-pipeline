#!/usr/bin/env python3
"""Synthetic tests for direct editable-vector text replacement."""

from __future__ import annotations

from contextlib import AbstractContextManager
from io import BytesIO
import base64
import struct
import unittest
from unittest.mock import patch
from xml.etree import ElementTree
from PIL import Image

from pipeline import bounded_text_layout
from pipeline.folder_replacement.planning import LookupProvider
from pipeline.vector_text import replace_vector_text
from pipeline.vector_text.common import ETO_CLIPPED
from pipeline.vector_text.emf import (
    _EmfCoordinateState,
    _EmfFont,
    _EmfRectangle,
    _EmfTextCandidate,
    _emf_grouped_unclipped_fit_contexts,
    _emf_measured_source_bounds,
    _emf_unclipped_fit_contexts,
    analyse_emf,
)
from pipeline.text_replacement import (
    TextReplacementItem,
    TextReplacementRequest,
    TextReplacementResult,
    replace_each,
)
from pipeline.text_replacement.batching import TranslationEngine


def _mask(text: str) -> str:
    return "#" * len(text)


def _svg_texts(data: bytes) -> list[ElementTree.Element]:
    return list(ElementTree.fromstring(data).iter("{http://www.w3.org/2000/svg}text"))


def _style_font_size(element: ElementTree.Element) -> float:
    for declaration in element.attrib.get("style", "").split(";"):
        name, _, value = declaration.partition(":")
        if name.strip() == "font-size":
            return float(value.strip().removesuffix("px"))
    raise AssertionError("No font-size in the inline style.")


def _stand_in_optional_faces() -> AbstractContextManager[object]:
    """Behave as if the optional Math and Symbols 2 fonts were bootstrapped.

    The fallback segmentation only runs when those faces exist, and CI does not
    download them.  The committed mono face stands in; it has no private-use glyphs.
    """
    mono = bounded_text_layout._base_noto_typefaces()["fixed-width"]
    return patch(
        "pipeline.bounded_text_layout.optional_static_typefaces",
        return_value={"math": mono, "symbols": mono},
    )


class VectorTextReplacerTests(unittest.TestCase):
    # Verifies FR-2026-10-28-04.
    def test_emf_trace_records_individual_fit_without_changing_output(self) -> None:
        source = _emf_with_unclipped_text(line_x=60)
        results = []
        for enabled in (False, True):
            document = analyse_emf(
                source, source_language="en", target_language="en",
                document_text_layout="preserve-basic-layout", trace_layout=enabled,
            )
            results.append(document.apply(_mask, _LongReplacementProvider()))
        self.assertEqual(results[0].data, results[1].data)
        self.assertEqual((), results[0].emf_layout_trace)
        [trace] = results[1].emf_layout_trace
        self.assertEqual("individual_fit", trace["outcome"])
        self.assertEqual("Old", trace["source_text"])
        self.assertEqual("A considerably longer heading", trace["replacement_text"])
        self.assertIsNotNone(trace["source_bounds"])
        self.assertIsNotNone(trace["fitting_bounds"])
        self.assertIsNotNone(trace["source_measurement_face"])
        self.assertIsNotNone(trace["replacement_layout_face"])
        self.assertEqual(
            {"m11": 1.0, "m12": 0.0, "m21": 0.0, "m22": 1.0, "dx": 0.0, "dy": 0.0},
            trace["effective_transform"],
        )
        font = trace["generated_font"]
        self.assertIsInstance(font, dict)
        assert isinstance(font, dict)
        self.assertEqual(82, struct.unpack_from("<I", results[1].data, font["creation_record_offset"])[0])
        self.assertEqual(37, struct.unpack_from("<I", results[1].data, font["selection_record_offset"])[0])
        self.assertEqual((), results[1].diagnostics)

    # Verifies FR-2026-10-28-04.
    def test_emf_trace_records_groups_and_fallbacks(self) -> None:
        grouped = analyse_emf(
            _emf_with_grouped_unclipped_text(line_x=60), source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _LongReplacementProvider())
        anchor, member = grouped.emf_layout_trace
        self.assertEqual("group_anchor", anchor["outcome"])
        self.assertEqual("suppressed_group_member", member["outcome"])
        self.assertEqual(anchor["record_offset"], member["group_anchor_offset"])
        self.assertEqual(anchor["group_member_offsets"], member["group_member_offsets"])
        self.assertEqual("", member["replacement_text"])

        fallback = analyse_emf(
            _emf_with_unclipped_text(transform_records=(_emf_restore_dc_record(-1),)),
            source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _LongReplacementProvider())
        [fallback_trace] = fallback.emf_layout_trace
        self.assertEqual("fallback", fallback_trace["outcome"])
        self.assertIsNone(fallback_trace["source_measurement_face"])
        self.assertEqual(fallback.diagnostics[0]["reason_code"], fallback_trace["fallback_reason"])
        untraced = analyse_emf(
            _emf_with_unclipped_text(transform_records=(_emf_restore_dc_record(-1),)),
            source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=False,
        ).apply(_mask, _LongReplacementProvider())
        self.assertEqual(untraced.data, fallback.data)
        self.assertEqual(untraced.diagnostics, fallback.diagnostics)

    # Verifies FR-2026-10-28-04: debug traces explain grouping and clipping decisions.
    def test_emf_trace_explains_gdi_grouping_boundaries(self) -> None:
        changed_font = analyse_emf(
            _emf_with_text_state_changed_group(change_paint_state=False),
            source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _LongReplacementProvider())
        first, second = changed_font.emf_layout_trace
        first_grouping = first["grouping"]
        second_grouping = second["grouping"]
        assert isinstance(first_grouping, dict) and isinstance(second_grouping, dict)
        self.assertTrue(first_grouping["eligible_as_member"])
        self.assertEqual(first["record_offset"], second_grouping["previous_record_offset"])
        self.assertIn("font_face_mismatch", second_grouping["previous_boundary_reasons"])
        self.assertIn("font_size_mismatch", second_grouping["previous_boundary_reasons"])
        self.assertEqual(400, first_grouping["font_weight"])
        self.assertFalse(first_grouping["font_italic"])

        for weight, reason in ((500, "font_properties_mismatch"), (700, "font_style_mismatch")):
            with self.subTest(weight=weight):
                second_font = bytearray(_emf_font_record("Noto Sans JP", handle=2))
                struct.pack_into("<i", second_font, 28, weight)
                source = _emf_with_grouped_unclipped_text(intervening_records=(
                    bytes(second_font), _emf_select_object_record(2),
                ))
                result = analyse_emf(
                    source, source_language="en", target_language="en",
                    document_text_layout="preserve-basic-layout", trace_layout=True,
                ).apply(_mask, _LongReplacementProvider())
                first, second = result.emf_layout_trace
                first_grouping, second_grouping = first["grouping"], second["grouping"]
                assert isinstance(first_grouping, dict) and isinstance(second_grouping, dict)
                self.assertEqual(400, first_grouping["font_weight"])
                self.assertEqual(weight, second_grouping["font_weight"])
                self.assertIn(reason, second_grouping["previous_boundary_reasons"])

        exclude = struct.pack("<IIiiii", 29, 24, 0, 0, 10, 10)
        source = _emf_with_grouped_unclipped_text(preamble_records=(
            exclude, struct.pack("<II", 28, 8), struct.pack("<IIII", 75, 16, 0, 5),
        ))
        results = []
        requests = []
        class Provider:
            def __init__(self) -> None:
                self.requests: list[str] = []

            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                self.requests.extend(request.texts)
                return replace_each(request, lambda text: TextReplacementItem("T:" + text, 1.0))

        for enabled in (False, True):
            provider = Provider()
            document = analyse_emf(
                source, source_language="en", target_language="en",
                document_text_layout="preserve-basic-layout", trace_layout=enabled,
            )
            results.append(document.apply(_mask, provider))
            requests.append(provider.requests)
        self.assertEqual(results[0].data, results[1].data)
        self.assertEqual(requests[0], requests[1])
        self.assertEqual((), results[0].emf_layout_trace)
        first, second = results[1].emf_layout_trace
        first_grouping = first["grouping"]
        second_grouping = second["grouping"]
        assert isinstance(first_grouping, dict) and isinstance(second_grouping, dict)
        self.assertFalse(first_grouping["clip_state_known"])
        self.assertTrue(first_grouping["selected_clip_known"])
        self.assertFalse(first_grouping["meta_clip_known"])
        self.assertIsNone(first_grouping["meta_clip_bounds"])
        self.assertIsNone(first_grouping["selected_clip_issue"])
        self.assertEqual(
            {"reason": "unsupported_exclude_clip_rectangle", "record_offset": source.index(exclude)},
            first_grouping["meta_clip_issue"],
        )
        self.assertFalse(first_grouping["eligible_as_member"])
        self.assertIn("clip_state_unresolved", first_grouping["eligibility_reasons"])
        self.assertIn("previous_record_ineligible", second_grouping["previous_boundary_reasons"])

    # Verifies FR-2026-10-28-04: clipping uncertainty retains its origin across DC operations.
    def test_emf_trace_preserves_clipping_uncertainty_origin(self) -> None:
        exclude = struct.pack("<IIiiii", 29, 24, 0, 0, 10, 10)
        reset_clip = struct.pack("<IIII", 75, 16, 0, 5)
        set_meta = struct.pack("<II", 28, 8)
        rect = _emf_extselect_clip_rect_record(0, -100, 65, 100)
        unsupported = bytearray(rect)
        struct.pack_into("<I", unsupported, 12, 4)
        complex_region = (
            struct.pack("<IIII", 75, 80, 64, 1)
            + struct.pack("<IIIIiiii", 32, 1, 2, 32, 0, -100, 65, 100)
            + struct.pack("<iiiiiiii", 0, -100, 20, 100, 40, -100, 65, 100)
        )
        cases = (
            ((exclude, bytes(unsupported)), "selected_clip_issue", "unsupported_exclude_clip_rectangle", exclude),
            ((exclude, complex_region), "selected_clip_issue", "unsupported_exclude_clip_rectangle", exclude),
            ((exclude, _emf_save_dc_record(), reset_clip, _emf_restore_dc_record(-1)),
             "selected_clip_issue", "unsupported_exclude_clip_rectangle", exclude),
            ((exclude, set_meta, _emf_save_dc_record(), reset_clip, _emf_restore_dc_record(-1), rect),
             "meta_clip_issue", "unsupported_exclude_clip_rectangle", exclude),
            ((exclude, reset_clip, bytes(unsupported)),
             "selected_clip_issue", "unsupported_clip_combine_mode", bytes(unsupported)),
        )
        for records, issue_key, reason, origin in cases:
            with self.subTest(issue_key=issue_key, reason=reason, records=records):
                source = _emf_with_grouped_unclipped_text(preamble_records=records)
                result = analyse_emf(
                    source, source_language="en", target_language="en",
                    document_text_layout="preserve-basic-layout", trace_layout=True,
                ).apply(_mask, _LongReplacementProvider())
                grouping = result.emf_layout_trace[0]["grouping"]
                assert isinstance(grouping, dict)
                self.assertEqual(
                    {"reason": reason, "record_offset": source.index(origin)},
                    grouping[issue_key],
                )
                self.assertFalse(grouping["clip_state_known"])

    # Verifies FR-2026-10-28-04: traces identify the first intervening barrier.
    def test_emf_trace_identifies_intervening_barrier_record(self) -> None:
        first_barrier = struct.pack("<III", 18, 12, 1)
        next_barrier = struct.pack("<III", 25, 12, 0)
        source = _emf_with_grouped_unclipped_text(
            include_third=True, intervening_records=(first_barrier, next_barrier),
        )
        results = [
            analyse_emf(
                source, source_language="en", target_language="en",
                document_text_layout="preserve-basic-layout", trace_layout=enabled,
            ).apply(_mask, _LongReplacementProvider())
            for enabled in (False, True)
        ]
        self.assertEqual(results[0].data, results[1].data)
        first, second, third = results[1].emf_layout_trace
        first_grouping = first["grouping"]
        second_grouping = second["grouping"]
        third_grouping = third["grouping"]
        assert isinstance(first_grouping, dict)
        assert isinstance(second_grouping, dict)
        assert isinstance(third_grouping, dict)
        self.assertIsNone(first_grouping["intervening_barrier"])
        self.assertEqual(
            {"record_type": 18, "record_offset": source.index(first_barrier)},
            second_grouping["intervening_barrier"],
        )
        self.assertIn("intervening_paint_or_incompatible_state", second_grouping["previous_boundary_reasons"])
        self.assertIsNone(third_grouping["intervening_barrier"])

    # Verifies FR-2026-10-28-04.
    def test_emf_trace_reports_clipped_fit_and_unknown_stock_font(self) -> None:
        clipped = analyse_emf(
            _emf_with_clipped_text(()), source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _LongReplacementProvider())
        [trace] = clipped.emf_layout_trace
        self.assertEqual("individual_fit", trace["outcome"])
        self.assertEqual(trace["explicit_clip_bounds"], trace["fitting_bounds"])
        decisions = trace["fit_decisions"]
        units = trace["geometry_units"]
        assert isinstance(decisions, dict) and isinstance(units, dict)
        self.assertEqual("explicit_clip", decisions["bound_basis"])
        self.assertEqual("EMF logical units", units["fitting_bounds"])

        stock = analyse_emf(
            _emf_with_stock_font_group(), source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _LongReplacementProvider())
        for item in stock.emf_layout_trace:
            self.assertIsNone(item["requested_source_face"])
            self.assertIsNone(item["source_font_size_points"])

        invalid_clip = bytearray(_emf_with_clipped_text(()))
        text_record = _emf_exttextout_record("Old", 0, 0, 40, 20, clipped=True)
        text_offset = invalid_clip.index(text_record)
        struct.pack_into("<iiii", invalid_clip, text_offset + 56, 0, 0, 0, 20)
        result = analyse_emf(
            bytes(invalid_clip), source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _LongReplacementProvider())
        [invalid_trace] = result.emf_layout_trace
        self.assertEqual("fallback", invalid_trace["outcome"])
        self.assertEqual([0, 0], invalid_trace["origin"])
        self.assertEqual([0, 0, 0, 20], invalid_trace["explicit_clip_bounds"])
        self.assertIsNone(invalid_trace["fitting_bounds"])
        self.assertIsNotNone(invalid_trace["coordinate_state"])

    # Verifies FR-2026-08-04-07, FR-2026-10-22-11 and FR-2026-10-22-12.
    def test_fits_svg_text_with_and_without_a_clip_rectangle(self) -> None:
        result = replace_vector_text(
            b'''<svg xmlns="http://www.w3.org/2000/svg"><defs><clipPath id="box"><rect width="40" height="20"/></clipPath></defs><text clip-path="url(#box)" font-family="Source Sans" font-size="20">old</text><text font-size="20">free</text></svg>''',
            ".svg", _mask, "en", document_text_layout="preserve-basic-layout",
            replacement_provider=_LongReplacementProvider(), target_language="en",
        )

        self.assertIn(b"Noto Sans JP", result.data)
        self.assertNotIn(b"####", result.data)
        self.assertEqual(2, result.replaced_text_items)
        clipped, free = _svg_texts(result.data)
        self.assertEqual("A considerably longer heading", clipped.text)
        self.assertLess(float(clipped.attrib["font-size"].removesuffix("px")), 20.0)
        self.assertEqual("A considerably longer heading", free.text)
        self.assertLess(_style_font_size(free), 20.0)

    # Verifies FR-2026-10-22-12.
    def test_svg_text_without_a_clip_rectangle_is_fitted_in_both_layouts(self) -> None:
        for layout in ("preserve-basic-layout", "preserve-basic-layout-source-font"):
            with self.subTest(layout=layout):
                result = replace_vector_text(
                    b'<svg xmlns="http://www.w3.org/2000/svg"><style>.t{font-size:24px}</style>'
                    b'<text class="t" font-family="No Such Face">free</text></svg>',
                    ".svg", _mask, "en", document_text_layout=layout,
                    replacement_provider=_LongReplacementProvider(), target_language="en",
                )

                text = _svg_texts(result.data)[0]
                self.assertEqual("A considerably longer heading", text.text)
                self.assertLess(_style_font_size(text), 24.0)

    # Verifies FR-2026-10-22-12.
    def test_svg_replacement_no_longer_than_the_source_keeps_its_size(self) -> None:
        class _Short:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(request, lambda text: TextReplacementItem("ab", 1.0))

        result = replace_vector_text(
            b'<svg xmlns="http://www.w3.org/2000/svg"><text font-size="20">free text</text></svg>',
            ".svg", _mask, "en", document_text_layout="preserve-basic-layout",
            replacement_provider=_Short(), target_language="en",
        )

        text = _svg_texts(result.data)[0]
        self.assertEqual("ab", text.text)
        self.assertNotIn("font-size", text.get("style", ""))

    # Verifies FR-2026-10-22-12.
    def test_svg_text_that_cannot_be_placed_safely_is_replaced_at_its_source_size(self) -> None:
        source = (
            b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:x="http://www.w3.org/1999/xlink">'
            b'<g transform="rotate(30)"><text font-size="20">one</text></g>'
            b'<text font-size="20" transform="skewX(10)">two</text>'
            b'<text font-size="20" rotate="15">three</text>'
            b'<text font-size="2em">four</text>'
            b'<text font-size="20"><textPath x:href="#p">five</textPath></text>'
            b'<text font-size="20" writing-mode="tb">six</text>'
            b'<text font-size="20">seven<tspan>eight</tspan></text></svg>'
        )

        result = replace_vector_text(
            source, ".svg", _mask, "en", document_text_layout="preserve-basic-layout",
            replacement_provider=_LongReplacementProvider(), target_language="en",
        )

        # Only the childless tspan inside mixed content is fitted; its parent keeps the source size.
        self.assertEqual(1, result.data.count(b"considerably"))
        for word in (b"one", b"two", b"three", b"four", b"five", b"six", b"seven", b"eight"):
            self.assertNotIn(b">" + word, result.data)
        self.assertEqual(1, result.data.count(b"font-size:"))
        self.assertEqual(8, result.replaced_text_items)

    # Verifies FR-2026-10-22-12: a legacy symbol-font bullet has no approved portable face.
    def test_svg_text_no_portable_face_covers_is_replaced_at_its_source_size(self) -> None:
        for layout in ("preserve-basic-layout", "preserve-basic-layout-source-font"):
            with self.subTest(layout=layout), _stand_in_optional_faces():
                result = replace_vector_text(
                    '<svg xmlns="http://www.w3.org/2000/svg">'
                    '<text font-family="Wingdings" font-size="32">\uf06e</text>'
                    '<text font-size="20">free</text></svg>'.encode(),
                    ".svg", _mask, "en", document_text_layout=layout,
                    replacement_provider=_LongReplacementProvider(), target_language="en",
                )

                bullet, free = _svg_texts(result.data)
                self.assertEqual("#", bullet.text)
                self.assertNotIn("font-size", bullet.get("style", ""))
                self.assertEqual("A considerably longer heading", free.text)
                self.assertEqual(2, result.replaced_text_items)

    # Verifies FR-2026-10-22-12.
    def test_measuring_text_no_portable_face_covers_reports_it_as_unmeasurable(self) -> None:
        from pipeline.vector_text.common import SourceLineFont, measure_source_line

        font = SourceLineFont("Wingdings", 24.0, False, False)

        with _stand_in_optional_faces():
            self.assertIsNone(measure_source_line("\uf06e", font, measure_source_fonts=False))
            self.assertIsNotNone(measure_source_line("abc", font, measure_source_fonts=False))

    # Verifies FR-2026-10-22-11 and FR-2026-10-22-12: overflow stays translated.
    def test_svg_text_that_cannot_fit_is_still_translated(self) -> None:
        class _Huge:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(request, lambda text: TextReplacementItem("W" * 400, 1.0))

        result = replace_vector_text(
            b'<svg xmlns="http://www.w3.org/2000/svg"><text font-size="20">x</text></svg>',
            ".svg", _mask, "en", document_text_layout="preserve-basic-layout",
            replacement_provider=_Huge(), target_language="en",
        )

        self.assertEqual("W" * 400, _svg_texts(result.data)[0].text)

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

    # Verifies FR-2026-10-28-05.
    def test_emf_expansion_respects_enclosing_rectangle_after_restore(self) -> None:
        for translated in (False, True):
            with self.subTest(translated=translated):
                rectangle = struct.pack(
                    "<IIiiii", 43, 24, -30 if translated else -10, -10,
                    40 if translated else 60, 30,
                )
                records = (
                    _emf_save_dc_record(),
                    *(() if not translated else (
                        _emf_modify_world_transform_record(1.0, 0.0, 0.0, 1.0, 20.0, 0.0),
                    )),
                    rectangle,
                    _emf_restore_dc_record(-1),
                )
                source = _emf_with_unclipped_text(transform_records=records)
                context = next(iter(_emf_unclipped_fit_contexts(
                    source, measure_source_fonts=False
                ).values()))
                self.assertGreater(context.fitting_bounds.right, 40)
                self.assertLessEqual(context.fitting_bounds.right, 60)

    # Verifies FR-2026-10-28-05.
    def test_emf_rectangle_expansion_accounts_for_pen_and_brush(self) -> None:
        rectangle = struct.pack("<IIiiii", 43, 24, -10, -10, 60, 30)
        wide_pen = struct.pack("<IIIIiiI", 38, 28, 2, 0, 10, 0, 0)
        cases = (
            ((wide_pen, _emf_select_object_record(2), rectangle), 55),
            ((_emf_select_object_record(0x80000008),
              _emf_select_object_record(0x80000005), rectangle), 200),
        )
        for records, right in cases:
            with self.subTest(right=right):
                context = next(iter(_emf_unclipped_fit_contexts(
                    _emf_with_unclipped_text(transform_records=records),
                    measure_source_fonts=False,
                ).values()))
                self.assertEqual(right, context.fitting_bounds.right)

    # Verifies FR-2026-10-28-05.
    def test_emf_expansion_uses_conservative_polygon_bounds(self) -> None:
        for top, expected in ((0, 54), (50, 200)):
            with self.subTest(top=top):
                polygon = struct.pack(
                    "<IIiiiiIiiiiii", 3, 52, 55, top, 65, top + 20, 3,
                    55, top, 65, top, 60, top + 20,
                )
                source = _emf_with_unclipped_text(transform_records=(polygon,))
                context = next(iter(_emf_unclipped_fit_contexts(
                    source, measure_source_fonts=False
                ).values()))
                self.assertEqual(expected, context.fitting_bounds.right)

    # Verifies FR-2026-10-28-05.
    def test_emf_expansion_uses_bitmap_device_bounds(self) -> None:
        bitmap = bytearray(_emf_with_stretchdibits_image()[88:-20])
        for top, expected in ((0, 55), (50, 200)):
            with self.subTest(top=top):
                struct.pack_into("<iiii", bitmap, 8, 55, top, 65, top + 20)
                context = next(iter(_emf_unclipped_fit_contexts(
                    _emf_with_unclipped_text(transform_records=(bytes(bitmap),)),
                    measure_source_fonts=False,
                ).values()))
                self.assertEqual(expected, context.fitting_bounds.right)

    # Verifies FR-2026-10-28-05: overflow stays visible without an overlap clip.
    def test_emf_overflow_is_not_clipped_near_polytext(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(request, lambda text: TextReplacementItem("W" * 500, 1.0))

        polytext = struct.pack(
            "<IIiiiiIffIiiIIIiiiiI4s", 97, 84, 55, 0, 65, 20, 1, 1.0, 1.0, 1,
            55, 0, 1, 80, 0, 0, 0, 0, 0, 0, b"A\0\0\0",
        )
        for grouped, opaque in ((False, False), (False, True), (True, False), (True, True)):
            with self.subTest(grouped=grouped, opaque=opaque):
                source = bytearray(
                    _emf_with_grouped_unclipped_text(preamble_records=(polytext,)) if grouped else
                    _emf_with_unclipped_text(transform_records=(polytext,))
                )
                if opaque:
                    offset = 0
                    while offset < len(source):
                        record_type, size = struct.unpack_from("<II", source, offset)
                        if record_type == 84:
                            struct.pack_into("<Iiiii", source, offset + 52, 2, 0, 0, 50, 20)
                            break
                        offset += size
                result = analyse_emf(
                    bytes(source), source_language="en", target_language="en",
                    document_text_layout="preserve-basic-layout", trace_layout=True,
                ).apply(_mask, _Provider())
                self.assertEqual("W" * 500, _emf_texts(result.data)[0])
                self.assertFalse(_emf_text_options(result.data)[0] & ETO_CLIPPED)
                self.assertIn(polytext, result.data)
                self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-28-05: unresolved neighbouring text does not prevent fitting.
    def test_emf_unbounded_small_text_does_not_prevent_fitting(self) -> None:
        small_text = struct.pack(
            "<IIiiIIIff4s", 108, 40, 55, 10, 1, 0x300, 1, 1.0, 1.0, b"A\0\0\0",
        )
        for layout in ("preserve-basic-layout", "preserve-basic-layout-source-font"):
            for clipped in (False, True):
                with self.subTest(layout=layout, clipped=clipped):
                    result = analyse_emf(
                        _emf_with_unclipped_text(
                            transform_records=(small_text,), record_clipped=clipped,
                        ),
                        source_language="en", target_language="en",
                        document_text_layout=layout, trace_layout=True,
                    ).apply(_mask, _LongReplacementProvider())
                    self.assertIn(small_text, result.data)
                    [trace] = result.emf_layout_trace
                    self.assertEqual("individual_fit", trace["outcome"])
                    self.assertEqual([], list(result.diagnostics))
                    if not clipped:
                        decisions = trace["fit_decisions"]
                        assert isinstance(decisions, dict)
                        self.assertNotEqual("applied", decisions["expansion_status"])

    # Verifies FR-2026-10-28-05 and FR-2026-10-29-01.
    def test_emf_group_with_unbounded_small_text_is_still_grouped(self) -> None:
        small_text = struct.pack(
            "<IIiiIIIff4s", 108, 40, 55, 10, 1, 0x300, 1, 1.0, 1.0, b"A\0\0\0",
        )
        result = analyse_emf(
            _emf_with_grouped_unclipped_text(preamble_records=(small_text,)),
            source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _LongReplacementProvider())
        self.assertEqual(
            ["group_anchor", "suppressed_group_member"],
            [item["outcome"] for item in result.emf_layout_trace],
        )
        self.assertEqual([], list(result.diagnostics))
        self.assertIn(small_text, result.data)
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-28-05.
    def test_emf_expansion_respects_visible_pixel(self) -> None:
        for vertical, expected in ((10, 55), (50, 200)):
            with self.subTest(vertical=vertical):
                pixel = struct.pack("<IIiiI", 15, 20, 55, vertical, 0)
                context = next(iter(_emf_unclipped_fit_contexts(
                    _emf_with_unclipped_text(transform_records=(pixel,)),
                    measure_source_fonts=False,
                ).values()))
                self.assertEqual(expected, context.fitting_bounds.right)

    # Verifies FR-2026-10-28-05.
    def test_emf_polygon_expansion_accounts_for_pen_width(self) -> None:
        polygon = struct.pack(
            "<IIiiiiIiiiiii", 3, 52, 55, 0, 65, 20, 3,
            55, 0, 65, 0, 60, 20,
        )
        wide_pen = struct.pack("<IIIIiiI", 38, 28, 2, 0, 10, 0, 0)
        context = next(iter(_emf_unclipped_fit_contexts(
            _emf_with_unclipped_text(transform_records=(wide_pen, _emf_select_object_record(2), polygon)),
            measure_source_fonts=False,
        ).values()))
        self.assertEqual(50, context.fitting_bounds.right)

    # Verifies FR-2026-10-28-05.
    def test_invisible_emf_polygon_does_not_limit_expansion(self) -> None:
        polygon = struct.pack(
            "<IIiiiiIiiiiii", 3, 52, 55, 0, 65, 20, 3,
            55, 0, 65, 0, 60, 20,
        )
        records = (
            _emf_select_object_record(0x80000008),
            _emf_select_object_record(0x80000005),
            polygon,
        )
        context = next(iter(_emf_unclipped_fit_contexts(
            _emf_with_unclipped_text(transform_records=records), measure_source_fonts=False,
        ).values()))
        self.assertEqual(200, context.fitting_bounds.right)

    # Verifies FR-2026-10-28-05.
    def test_emf_expansion_stops_for_unresolved_miter_joins(self) -> None:
        pen = bytearray(52)
        struct.pack_into("<III", pen, 0, 95, len(pen), 2)
        struct.pack_into("<II", pen, 28, 0x00012000, 10)
        polygon = struct.pack(
            "<IIiiiiIiiiiii", 3, 52, 55, 0, 65, 20, 3,
            55, 0, 65, 0, 60, 20,
        )
        context = next(iter(_emf_unclipped_fit_contexts(
            _emf_with_unclipped_text(transform_records=(bytes(pen), _emf_select_object_record(2), polygon)),
            measure_source_fonts=False, trace_layout=True,
        ).values()))
        self.assertLessEqual(context.fitting_bounds.right, 40)
        assert context.trace_info is not None
        self.assertEqual("unresolved_graphics_geometry", context.trace_info["expansion_status"])

    # Verifies FR-2026-10-28-05.
    def test_emf_expansion_stops_for_unresolved_clip_or_drawing(self) -> None:
        unresolved_clip = struct.pack("<IIII", 75, 16, 0, 3)
        flood_fill = struct.pack("<IIiiII", 53, 24, 50, 10, 0, 0)
        excluded_clip = struct.pack("<IIiiii", 29, 24, 50, -10, 60, 30)
        offset_clip = struct.pack("<IIii", 26, 16, 1, 0)
        path_clip = struct.pack("<III", 67, 12, 1)
        angle_arc = struct.pack("<IIiiIff", 41, 28, 55, 10, 5, 0.0, 90.0)
        small_text = struct.pack("<IIiiIIIff4s", 108, 40, 55, 10, 1, 0x300, 1, 1.0, 1.0, b"A\0\0\0")
        gl_record = struct.pack("<III", 102, 12, 0)
        bounded_gl_record = struct.pack("<IIiiiiI", 103, 28, 50, 0, 60, 20, 0)
        plus_drawing = struct.pack(
            "<III4sHHIIIIffff", 70, 52, 40, b"EMF+", 0x400A, 0x8000, 36, 24,
            0xFF000000, 1, 55.0, 0.0, 10.0, 20.0,
        )
        for record in (unresolved_clip, flood_fill, plus_drawing, excluded_clip, offset_clip, path_clip,
                   angle_arc, small_text, gl_record, bounded_gl_record):
            with self.subTest(record_type=struct.unpack_from("<I", record)[0]):
                context = next(iter(_emf_unclipped_fit_contexts(
                    _emf_with_unclipped_text(transform_records=(record,)),
                    measure_source_fonts=False, trace_layout=True,
                ).values()))
                self.assertLessEqual(context.fitting_bounds.right, 40)
                assert context.trace_info is not None
                self.assertIn("unresolved", str(context.trace_info["expansion_status"]))
                grouped, _suppressed = _emf_grouped_unclipped_fit_contexts(
                    _emf_with_grouped_unclipped_text(preamble_records=(record,)),
                    measure_source_fonts=False,
                )
                for group_context in grouped.values():
                    self.assertLessEqual(group_context.fitting_bounds.right, 40)

    # Verifies FR-2026-10-28-05.
    def test_emf_meta_region_remains_unresolved_after_rectangular_clip(self) -> None:
        unresolved_clip = struct.pack("<IIiiii", 29, 24, 50, -10, 60, 30)
        meta_clip = struct.pack("<II", 28, 8)
        for mode in (1, 5):
            rectangle_clip = struct.pack(
                "<IIIIIIIIiiiiiiii", 75, 64, 48, mode, 32, 1, 1, 16,
                0, -100, 200, 100, 0, -100, 200, 100,
            )
            with self.subTest(mode=mode):
                context = next(iter(_emf_unclipped_fit_contexts(
                    _emf_with_unclipped_text(transform_records=(unresolved_clip, meta_clip, rectangle_clip)),
                    measure_source_fonts=False, trace_layout=True,
                ).values()))
                self.assertLessEqual(context.fitting_bounds.right, 40)
                assert context.trace_info is not None
                self.assertIn("unresolved", str(context.trace_info["expansion_status"]))

    # Verifies FR-2026-10-28-05.
    def test_emf_colour_management_does_not_restore_invalid_geometry(self) -> None:
        invalid_state = _emf_restore_dc_record(-1)
        colour_management = struct.pack("<III", 98, 12, 1)
        result = analyse_emf(
            _emf_with_unclipped_text(transform_records=(invalid_state, colour_management)),
            source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _LongReplacementProvider())
        [trace] = result.emf_layout_trace
        self.assertEqual("fallback", trace["outcome"])

    # Verifies FR-2026-10-28-05.
    def test_emf_mirrored_layout_does_not_use_unmirrored_expansion(self) -> None:
        for layout, expected_expansion in ((1, False), (0, True)):
            with self.subTest(layout=layout):
                source = _emf_with_unclipped_text(
                    transform_records=(struct.pack("<III", 115, 12, layout),),
                )
                context = next(iter(_emf_unclipped_fit_contexts(
                    source, measure_source_fonts=False,
                ).values()))
                self.assertEqual(expected_expansion, context.allows_expansion)
                if not expected_expansion:
                    self.assertLessEqual(context.fitting_bounds.width, context.source_bounds.width)
                result = analyse_emf(
                    source, source_language="en", target_language="en",
                    document_text_layout="preserve-basic-layout", trace_layout=True,
                ).apply(_mask, _LongReplacementProvider())
                self.assertEqual("individual_fit", result.emf_layout_trace[0]["outcome"])

    # Verifies FR-2026-10-28-05.
    def test_grouped_enclosing_rectangle_respects_paint_order(self) -> None:
        rectangle = struct.pack("<IIiiii", 43, 24, -10, -10, 60, 30)
        null_brush = _emf_select_object_record(0x80000005)
        cases = (
            ((rectangle,), (), 57),
            ((), (rectangle,), 38),
            ((null_brush,), (rectangle,), 57),
        )
        for preamble, trailing, expected_right in cases:
            with self.subTest(preamble=preamble, trailing=trailing):
                contexts, _suppressed = _emf_grouped_unclipped_fit_contexts(
                    _emf_with_grouped_unclipped_text(
                        preamble_records=preamble, trailing_records=trailing,
                    ), measure_source_fonts=False,
                )
                self.assertEqual(1, len(contexts))
                self.assertEqual(expected_right, next(iter(contexts.values())).fitting_bounds.right)

    # Verifies FR-2026-10-28-05.
    def test_emf_plus_state_only_comments_do_not_block_expansion(self) -> None:
        plus_header = struct.pack("<HHIIIIII", 0x4001, 0, 28, 16, 0xDBC01002, 0, 96, 96)
        get_dc = struct.pack("<HHII", 0x4004, 0, 12, 0)
        data = b"EMF+" + plus_header + get_dc
        comment = struct.pack("<III", 70, 12 + len(data), len(data)) + data
        context = next(iter(_emf_unclipped_fit_contexts(
            _emf_with_unclipped_text(transform_records=(comment,)), measure_source_fonts=False,
        ).values()))
        self.assertEqual(200, context.fitting_bounds.right)

    # Verifies FR-2026-10-29-01: EMF+ state-only comments are GDI grouping boundaries
    # only when their EMF+ GetDC state is incompatible or unresolved.
    def test_emf_plus_state_only_comments_between_gdi_members(self) -> None:
        def comment(*plus_records: bytes) -> bytes:
            data = b"EMF+" + b"".join(plus_records)
            return struct.pack("<III", 70, 12 + len(data), len(data)) + data

        def plus_record(record_type: int, payload: bytes = b"", flags: int = 0) -> bytes:
            return struct.pack("<HHII", record_type, flags, 12 + len(payload), len(payload)) + payload

        get_dc = plus_record(0x4004)
        save = plus_record(0x4025, struct.pack("<I", 1))
        restore = plus_record(0x4026, struct.pack("<I", 1))
        hint = plus_record(0x401F, flags=3)
        identity = plus_record(0x402A, struct.pack("<6f", 1, 0, 0, 1, 0, 0))
        shifted = plus_record(0x402A, struct.pack("<6f", 1, 0, 0, 1, 5, 0))
        mirrored = comment(restore, save, hint, identity, get_dc)
        cases = (
            (mirrored, True),
            (comment(restore, save, hint, shifted, get_dc), False),
            (comment(restore, save, identity, get_dc), False),
            (comment(plus_record(0x4026, struct.pack("<I", 9)), hint, identity, get_dc), False),
            (comment(plus_record(0x4028, struct.pack("<I", 2)), hint, identity, get_dc), False),
            (comment(plus_record(0x400A, struct.pack("<II", 0, 0)), hint, identity, get_dc), False),
        )
        for intervening, grouped in cases:
            with self.subTest(intervening=intervening, grouped=grouped):
                source = _emf_with_grouped_unclipped_text(
                    preamble_records=(comment(save, hint, identity, get_dc),),
                    intervening_records=(intervening,),
                )
                trace: dict[int, dict[str, object]] = {}
                contexts, suppressed = _emf_grouped_unclipped_fit_contexts(
                    source, measure_source_fonts=False, trace_grouping=trace,
                )
                self.assertEqual(grouped, bool(contexts))
                self.assertEqual(grouped, bool(suppressed))
                second = trace[max(trace)]
                if grouped:
                    self.assertIsNone(second["intervening_barrier"])
                    self.assertIs(True, second["emfplus_dc_state_matches_previous"])
                else:
                    self.assertEqual(
                        {"record_type": 70, "record_offset": source.index(intervening)},
                        second["intervening_barrier"],
                    )

    # Verifies FR-2026-10-28-05: fitted text that overlaps other text is not clipped.
    def test_emf_overlapping_fitted_lines_acquire_no_overlap_clip(self) -> None:
        records = [
            _emf_font_record("Noto Sans JP"),
            _emf_select_object_record(1),
            _emf_exttextout_record("Upper", 0, 0, 200, 24),
            _emf_exttextout_record("Lower", 60, 20, 260, 44),
        ]
        header = bytearray(88)
        struct.pack_into("<II", header, 0, 1, len(header))
        struct.pack_into("<iiii", header, 8, 0, -100, 400, 100)
        eof = struct.pack("<IIIII", 14, 20, 0, 0, 0)
        source = bytearray(header + b"".join(records) + eof)
        struct.pack_into("<I", source, 48, len(source))
        struct.pack_into("<I", source, 52, len(records) + 2)

        result = analyse_emf(
            bytes(source), source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _LongReplacementProvider())
        self.assertEqual(
            ["individual_fit", "individual_fit"],
            [item["outcome"] for item in result.emf_layout_trace],
        )
        for item in result.emf_layout_trace:
            self.assertNotIn("overlap_protection", item)
        for options in _emf_text_options(result.data):
            self.assertFalse(options & ETO_CLIPPED)

    # Verifies FR-2026-10-29-01 and FR-2026-10-28-04: a record without record bounds
    # is measured at its origin, then fitted in device space.
    def test_emf_unbounded_text_fit_bounds_use_device_space(self) -> None:
        records = [
            _emf_font_record("Noto Sans JP"),
            _emf_select_object_record(1),
            _emf_exttextout_record("Old", 0, 0, 40, 20),
            _emf_set_world_transform_record(1, 0, 0, 1, 200, 0),
            _emf_exttextout_record("Value", 0, 0, 0, 0, bounded=False),
        ]
        header = bytearray(88)
        struct.pack_into("<II", header, 0, 1, len(header))
        struct.pack_into("<iiii", header, 8, 0, -100, 400, 100)
        eof = struct.pack("<IIIII", 14, 20, 0, 0, 0)
        source = bytearray(header + b"".join(records) + eof)
        struct.pack_into("<I", source, 48, len(source))
        struct.pack_into("<I", source, 52, len(records) + 2)

        contexts = _emf_unclipped_fit_contexts(bytes(source), measure_source_fonts=False)
        unbounded = contexts[bytes(source).index(records[-1])]
        self.assertEqual(200, unbounded.source_bounds.left)
        self.assertEqual(unbounded.source_bounds, unbounded.fitting_bounds)

        result = analyse_emf(
            bytes(source), source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _LongReplacementProvider())
        self.assertEqual(2, len(result.emf_layout_trace))
        for item in result.emf_layout_trace:
            self.assertEqual("individual_fit", item["outcome"])
            units = item["geometry_units"]
            assert isinstance(units, dict)
            self.assertEqual("EMF device units", units["source_bounds"])

    # Verifies FR-2026-10-28-05.
    def test_emf_expansion_respects_intersect_clip_rect(self) -> None:
        intersect_clip = struct.pack("<IIiiii", 30, 24, 0, -100, 60, 100)
        transformed_clip = (
            _emf_set_world_transform_record(1, 0, 0, 1, 20, 0),
            struct.pack("<IIiiii", 30, 24, -20, -100, 40, 100),
            _emf_set_world_transform_record(1, 0, 0, 1),
        )
        for records in ((intersect_clip,), transformed_clip):
            with self.subTest(transformed=len(records) > 1):
                individual = _emf_with_unclipped_text(transform_records=records)
                context = next(iter(_emf_unclipped_fit_contexts(individual, measure_source_fonts=False).values()))
                self.assertEqual(context.fitting_bounds.right, 60)
                grouped = _emf_with_grouped_unclipped_text(preamble_records=records)
                contexts, _suppressed = _emf_grouped_unclipped_fit_contexts(grouped, measure_source_fonts=False)
                group_context = next(iter(contexts.values()))
                assert group_context.render_bounds is not None
                self.assertEqual(group_context.render_bounds.right, 60)

    # Verifies FR-2026-10-28-05.
    def test_grouped_emf_expansion_respects_enclosing_rectangle(self) -> None:
        rectangle = struct.pack("<IIiiii", 43, 24, -10, -10, 60, 30)
        source = _emf_with_grouped_unclipped_text(preamble_records=(rectangle,))
        contexts, suppressed = _emf_grouped_unclipped_fit_contexts(
            source, measure_source_fonts=False, trace_layout=True
        )
        self.assertEqual(1, len(suppressed))
        context = next(iter(contexts.values()))
        assert context.render_bounds is not None and context.trace_info is not None
        self.assertGreater(context.render_bounds.right, 40)
        self.assertLessEqual(context.render_bounds.right, 60)
        obstacles = context.trace_info["limiting_obstacles"]
        assert isinstance(obstacles, list)
        self.assertTrue(any(
            obstacle.get("kind") == "shape"
            and obstacle.get("record_offset") == source.find(rectangle)
            and obstacle.get("coordinate_space") == "EMF device units"
            for obstacle in obstacles
        ))

    # Verifies FR-2026-10-28-05.
    def test_emf_text_obstacle_trace_names_record_and_coordinate_space(self) -> None:
        source = _emf_with_unclipped_text(
            adjacent_text_left=60, adjacent_preamble=(_emf_move_to_record(-100, -100),),
        )
        contexts = _emf_unclipped_fit_contexts(source, measure_source_fonts=False, trace_layout=True)
        context = next(iter(contexts.values()))
        assert context.trace_info is not None
        obstacles = context.trace_info["limiting_obstacles"]
        assert isinstance(obstacles, list)
        neighbour = _emf_exttextout_record("Value", 60, 0, 120, 20)
        self.assertTrue(any(
            obstacle.get("kind") == "text"
            and obstacle.get("record_offset") == source.find(neighbour)
            and obstacle.get("coordinate_space") == "EMF device units"
            for obstacle in obstacles
        ))

    # Verifies FR-2026-10-28-05.
    def test_emf_expansion_uses_line_transform_at_draw_time(self) -> None:
        records = (
            _emf_save_dc_record(),
            _emf_modify_world_transform_record(1.0, 0.0, 0.0, 1.0, 20.0, 0.0),
            _emf_move_to_record(40, -10),
            _emf_line_to_record(40, 30),
            _emf_restore_dc_record(-1),
        )
        context = next(iter(_emf_unclipped_fit_contexts(
            _emf_with_unclipped_text(transform_records=records),
            measure_source_fonts=False,
        ).values()))
        self.assertGreaterEqual(context.fitting_bounds.right, 59)
        self.assertLessEqual(context.fitting_bounds.right, 60)

    # Verifies FR-2026-10-28-05.
    def test_emf_expansion_respects_measured_unbounded_neighbour(self) -> None:
        source = _emf_with_unclipped_text(
            adjacent_text_left=60, adjacent_record_bounded=False
        )
        context = next(iter(_emf_unclipped_fit_contexts(
            source, measure_source_fonts=False
        ).values()))
        self.assertGreater(context.fitting_bounds.right, 40)
        self.assertLessEqual(context.fitting_bounds.right, 60)

    # Verifies FR-2026-10-28-05: minimum-size overflow is visible, not clipped.
    def test_emf_minimum_size_overflow_remains_visible(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request,
                    lambda text: TextReplacementItem("W" * 500 if text == "Old" else "Value", 1.0),
                )

        source = _emf_with_unclipped_text(
            adjacent_text_left=60,
            adjacent_preamble=(_emf_move_to_record(-100, -100),),
        )
        result = analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _Provider())
        self.assertEqual("W" * 500, _emf_texts(result.data)[0])
        self.assertIn(-1, _emf_font_heights(result.data))
        self.assertFalse(_emf_text_options(result.data)[0] & ETO_CLIPPED)
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-28-05.
    def test_grouped_emf_minimum_size_overflow_remains_visible(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request,
                    lambda text: TextReplacementItem("Value" if text == "Value" else "W" * 500, 1.0),
                )

        source = _emf_with_grouped_unclipped_text(
            trailing_records=(
                _emf_move_to_record(-100, -100),
                _emf_exttextout_record("Value", 60, 0, 120, 20),
            ),
        )
        result = analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _Provider())
        self.assertEqual("W" * 500, _emf_texts(result.data)[0])
        self.assertEqual("", _emf_texts(result.data)[1])
        self.assertIn(-1, _emf_font_heights(result.data))
        self.assertFalse(_emf_text_options(result.data)[0] & ETO_CLIPPED)
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-28-05 and FR-2026-09-05-02: a clipped group's overflow
    # remains visible because the anchor's source clip is removed.
    def test_grouped_clipped_emf_overflow_remains_visible(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request,
                    lambda text: TextReplacementItem("i" if text == "Value" else "W" * 500, 1.0),
                )

        source = _emf_with_grouped_unclipped_text(
            clipped=True,
            trailing_records=(
                _emf_move_to_record(-100, -100),
                _emf_exttextout_record("Value", 120, 0, 180, 20),
            ),
        )
        result = analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _Provider())
        self.assertEqual("W" * 500, _emf_texts(result.data)[0])
        self.assertEqual("", _emf_texts(result.data)[1])
        self.assertFalse(_emf_text_options(result.data)[0] & ETO_CLIPPED)
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-28-04 and FR-2026-10-28-05.
    def test_emf_opposing_replacements_are_fitted_without_overlap_clips(self) -> None:
        class _Provider:
            calls = 0

            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                self.calls += 1
                return replace_each(request, lambda text: TextReplacementItem("W" * 12, 1.0))

        source = bytearray(_emf_with_unclipped_text(
            adjacent_text_left=300, font_height=-100, header_right=700,
            adjacent_preamble=(
                _emf_move_to_record(-100, -100), _emf_set_text_alignment_record(2),
            ),
        ))
        struct.pack_into("<i", source, 20, 200)
        offset = 0
        text_index = 0
        while offset < len(source):
            record_type, size = struct.unpack_from("<II", source, offset)
            if record_type == 84:
                if text_index == 0:
                    struct.pack_into("<iiii", source, offset + 8, 0, 0, 200, 100)
                else:
                    struct.pack_into("<iiii", source, offset + 8, 300, 0, 500, 100)
                    struct.pack_into("<i", source, offset + 36, 500)
                text_index += 1
            offset += size
        provider = _Provider()
        result = analyse_emf(
            bytes(source), source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, provider)
        self.assertEqual(["W" * 12, "W" * 12], _emf_texts(result.data))
        self.assertEqual(2, provider.calls)
        self.assertFalse(any(option & ETO_CLIPPED for option in _emf_text_options(result.data)))
        self.assertEqual(
            ["individual_fit", "individual_fit"],
            [item["outcome"] for item in result.emf_layout_trace],
        )
        self.assertTrue(_emf_is_structurally_valid(result.data))
        untraced_provider = _Provider()
        untraced = analyse_emf(
            bytes(source), source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout",
        ).apply(_mask, untraced_provider)
        self.assertEqual(result.data, untraced.data)
        self.assertEqual(2, untraced_provider.calls)

    # Verifies FR-2026-10-28-05: a neighbour's source area does not clip replacement text.
    def test_emf_replacement_is_not_clipped_by_neighbour_area(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request,
                    lambda text: TextReplacementItem("W" * 350 if text == "Old" else "i", 1.0),
                )

        source = bytearray(_emf_with_unclipped_text(
            adjacent_text_left=300, font_height=-100, header_right=700,
            transform_records=(
                _emf_save_dc_record(), _emf_set_world_transform_record(1, 0, 0, 1, 1, 0),
            ),
            adjacent_preamble=(
                _emf_restore_dc_record(-1), _emf_move_to_record(-100, -100),
                _emf_set_text_alignment_record(2),
            ),
        ))
        struct.pack_into("<i", source, 20, 200)
        offset = 0
        text_index = 0
        while offset < len(source):
            record_type, size = struct.unpack_from("<II", source, offset)
            if record_type == 84:
                if text_index == 0:
                    struct.pack_into("<iiii", source, offset + 8, 1, 0, 201, 100)
                else:
                    struct.pack_into("<iiii", source, offset + 8, 300, 0, 500, 100)
                    struct.pack_into("<i", source, offset + 36, 500)
                text_index += 1
            offset += size
        result = analyse_emf(
            bytes(source), source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _Provider())
        self.assertEqual("W" * 350, _emf_texts(result.data)[0])
        self.assertFalse(_emf_text_options(result.data)[0] & ETO_CLIPPED)
        self.assertFalse(_emf_text_options(result.data)[1] & ETO_CLIPPED)

    # Verifies FR-2026-10-28-05: opaque text keeps its background without an overlap clip.
    def test_emf_opaque_text_near_neighbour_keeps_background_without_clip(self) -> None:
        class _Provider:
            calls = 0

            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                self.calls += 1
                return replace_each(
                    request,
                    lambda text: TextReplacementItem("W" * 350 if text == "Old" else "i", 1.0),
                )

        source = bytearray(_emf_with_unclipped_text(
            adjacent_text_left=300, font_height=-100, header_right=700,
            transform_records=(
                _emf_save_dc_record(), _emf_set_world_transform_record(1, 0, 0, 1, 1, 0),
            ),
            adjacent_preamble=(
                _emf_restore_dc_record(-1), _emf_move_to_record(-100, -100),
                _emf_set_text_alignment_record(2),
            ),
        ))
        struct.pack_into("<i", source, 20, 200)
        offset = 0
        text_index = 0
        while offset < len(source):
            record_type, size = struct.unpack_from("<II", source, offset)
            if record_type == 84:
                if text_index == 0:
                    struct.pack_into("<iiii", source, offset + 8, 1, 0, 201, 100)
                    struct.pack_into("<Iiiii", source, offset + 52, 2, 0, 0, 250, 100)
                else:
                    struct.pack_into("<iiii", source, offset + 8, 300, 0, 500, 100)
                    struct.pack_into("<i", source, offset + 36, 500)
                text_index += 1
            offset += size
        provider = _Provider()
        result = analyse_emf(
            bytes(source), source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, provider)
        self.assertEqual(["W" * 350, "i"], _emf_texts(result.data))
        self.assertEqual(2, provider.calls)
        options = _emf_text_options(result.data)
        self.assertTrue(options[0] & 2)
        self.assertFalse(options[0] & ETO_CLIPPED)
        self.assertFalse(options[1] & ETO_CLIPPED)
        self.assertEqual((0, 0, 250, 100), _emf_text_clips(result.data)[0])
        self.assertTrue(_emf_is_structurally_valid(result.data))

        class _TwoLongReplacements:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request,
                    lambda text: TextReplacementItem("W" * (350 if text == "Old" else 12), 1.0),
                )

        traced = analyse_emf(
            bytes(source), source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _TwoLongReplacements())
        generated_font = traced.emf_layout_trace[1]["generated_font"]
        assert isinstance(generated_font, dict)
        record_types = _emf_record_types(traced.data)
        for prefix, expected_type in (("creation", 82), ("selection", 37)):
            self.assertEqual(expected_type, record_types[generated_font[f"{prefix}_record_index"]])
            self.assertEqual(expected_type, struct.unpack_from(
                "<I", traced.data, generated_font[f"{prefix}_record_offset"]
            )[0])

    # Verifies FR-2026-10-28-05: overlapping source areas do not clip replacement text.
    def test_emf_overlapping_source_bounds_do_not_clip_replacement(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request,
                    lambda text: TextReplacementItem("W" * 500 if text == "Old" else "i", 1.0),
                )

        source = bytearray(_emf_with_unclipped_text(
            adjacent_text_left=80, font_height=-100, header_right=400,
            transform_records=(
                _emf_save_dc_record(), _emf_set_world_transform_record(1, 0, 0, 1, 1, 0),
            ),
            adjacent_preamble=(
                _emf_restore_dc_record(-1), _emf_move_to_record(-100, -100),
                _emf_set_text_alignment_record(2),
            ),
        ))
        struct.pack_into("<i", source, 20, 200)
        offset = 0
        text_index = 0
        while offset < len(source):
            record_type, size = struct.unpack_from("<II", source, offset)
            if record_type == 84:
                if text_index == 0:
                    struct.pack_into("<iiii", source, offset + 8, 1, 0, 101, 100)
                else:
                    struct.pack_into("<iiii", source, offset + 8, 80, 0, 180, 100)
                    struct.pack_into("<i", source, offset + 36, 180)
                text_index += 1
            offset += size
        result = analyse_emf(
            bytes(source), source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _Provider())
        self.assertEqual("W" * 500, _emf_texts(result.data)[0])
        self.assertFalse(_emf_text_options(result.data)[0] & ETO_CLIPPED)

    # Verifies FR-2026-10-28-05: coincident source areas do not clip either replacement.
    def test_emf_fully_overlapping_sources_are_not_clipped(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(request, lambda text: TextReplacementItem("i", 1.0))

        source = bytearray(_emf_with_unclipped_text(
            adjacent_text_left=1, font_height=-100, header_right=400,
            transform_records=(
                _emf_save_dc_record(), _emf_set_world_transform_record(1, 0, 0, 1, 1, 0),
            ),
            adjacent_preamble=(
                _emf_restore_dc_record(-1), _emf_move_to_record(-100, -100),
                _emf_set_text_alignment_record(2),
            ),
        ))
        struct.pack_into("<i", source, 20, 200)
        offset = 0
        text_index = 0
        while offset < len(source):
            record_type, size = struct.unpack_from("<II", source, offset)
            if record_type == 84:
                struct.pack_into("<iiii", source, offset + 8, 1, 0, 101, 100)
                if text_index == 1:
                    struct.pack_into("<i", source, offset + 36, 101)
                text_index += 1
            offset += size
        result = analyse_emf(
            bytes(source), source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _Provider())
        self.assertEqual(["i", "i"], _emf_texts(result.data))
        self.assertFalse(any(option & ETO_CLIPPED for option in _emf_text_options(result.data)))

    # Verifies FR-2026-10-28-05.
    def test_emf_minimum_size_text_that_fits_does_not_gain_clip(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(request, lambda text: TextReplacementItem("i", 1.0))

        source = bytearray(_emf_with_unclipped_text(
            adjacent_text_left=60,
            adjacent_preamble=(_emf_move_to_record(-100, -100),),
        ))
        offset = 0
        while offset < len(source):
            record_type, size = struct.unpack_from("<II", source, offset)
            if record_type == 84:
                struct.pack_into("<i", source, offset + 20, 1)
                break
            offset += size
        result = analyse_emf(
            bytes(source), source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _Provider())
        self.assertIn(-1, _emf_font_heights(result.data))
        self.assertFalse(_emf_text_options(result.data)[0] & ETO_CLIPPED)

    # Verifies FR-2026-10-28-05: quarter-turned overflow is fitted to its source
    # bound without expansion or an overlap clip.
    def test_emf_quarter_turn_overflow_is_not_clipped(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request,
                    lambda text: TextReplacementItem("W" * 2000 if text == "Old" else "i", 1.0),
                )

        source = bytearray(_emf_with_unclipped_text(
            adjacent_text_left=0, font_height=-100, header_right=700,
            transform_records=(
                _emf_save_dc_record(),
                _emf_set_world_transform_record(0, 1, -1, 0, 100, 0),
            ),
            adjacent_preamble=(_emf_restore_dc_record(-1), _emf_move_to_record(-100, -100)),
        ))
        struct.pack_into("<i", source, 20, 600)
        offset = 0
        text_index = 0
        while offset < len(source):
            record_type, size = struct.unpack_from("<II", source, offset)
            if record_type == 84:
                if text_index == 0:
                    struct.pack_into("<iiii", source, offset + 8, 0, 0, 100, 200)
                else:
                    struct.pack_into("<iiii", source, offset + 8, 0, 300, 100, 400)
                    struct.pack_into("<ii", source, offset + 36, 0, 300)
                text_index += 1
            offset += size
        result = analyse_emf(
            bytes(source), source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _Provider())
        self.assertEqual("W" * 2000, _emf_texts(result.data)[0])
        self.assertFalse(_emf_text_options(result.data)[0] & ETO_CLIPPED)
        self.assertEqual(result.emf_layout_trace[0]["source_bounds"], result.emf_layout_trace[0]["fitting_bounds"])

    # Verifies FR-2026-10-28-05.
    def test_emf_scaled_quarter_turns_are_fitted_without_clip(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request,
                    lambda text: TextReplacementItem("W" * 2000 if text == "Old" else "i", 1.0),
                )

        cases = (
            ((0, 2, -2, 0, 200, 0), (0, 0, 200, 400), (0, 600, 200, 700)),
            ((-2, 0, 0, -2, 800, 200), (400, 0, 800, 200), (0, 0, 200, 200)),
            ((0, -2, 2, 0, 0, 800), (0, 400, 200, 800), (0, 0, 200, 200)),
        )
        for transform, first_bounds, second_bounds in cases:
            with self.subTest(transform=transform):
                source = bytearray(_emf_with_unclipped_text(
                    adjacent_text_left=0, font_height=-100, header_right=1000,
                    transform_records=(_emf_save_dc_record(), _emf_set_world_transform_record(*transform)),
                    adjacent_preamble=(_emf_restore_dc_record(-1), _emf_move_to_record(-100, -100)),
                ))
                struct.pack_into("<i", source, 20, 1000)
                offset = 0
                text_index = 0
                while offset < len(source):
                    record_type, size = struct.unpack_from("<II", source, offset)
                    if record_type == 84:
                        bounds = first_bounds if text_index == 0 else second_bounds
                        struct.pack_into("<iiii", source, offset + 8, *bounds)
                        if text_index == 1:
                            struct.pack_into("<ii", source, offset + 36, bounds[0], bounds[1])
                        text_index += 1
                    offset += size
                result = analyse_emf(
                    bytes(source), source_language="en", target_language="en",
                    document_text_layout="preserve-basic-layout", trace_layout=True,
                ).apply(_mask, _Provider())
                self.assertEqual("W" * 2000, _emf_texts(result.data)[0])
                self.assertFalse(_emf_text_options(result.data)[0] & ETO_CLIPPED)
                self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-28-05: an existing source clip is retained, not tightened.
    def test_emf_quarter_turn_preserves_existing_clip(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request,
                    lambda text: TextReplacementItem("W" * 2000 if text == "Old" else "i", 1.0),
                )

        source = bytearray(_emf_with_unclipped_text(
            adjacent_text_left=0, font_height=-100, header_right=700,
            record_clipped=True, first_clip_bounds=(0, 0, 5000, 100),
            transform_records=(
                _emf_save_dc_record(), _emf_set_world_transform_record(0, 1, -1, 0, 100, 0),
            ),
            adjacent_preamble=(_emf_restore_dc_record(-1), _emf_move_to_record(-100, -100)),
        ))
        struct.pack_into("<i", source, 20, 600)
        offset = 0
        text_index = 0
        while offset < len(source):
            record_type, size = struct.unpack_from("<II", source, offset)
            if record_type == 84:
                if text_index == 0:
                    struct.pack_into("<iiii", source, offset + 8, 0, 0, 100, 200)
                else:
                    struct.pack_into("<iiii", source, offset + 8, 0, 300, 100, 400)
                    struct.pack_into("<ii", source, offset + 36, 0, 300)
                text_index += 1
            offset += size
        result = analyse_emf(
            bytes(source), source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _Provider())
        clip = _emf_text_clips(result.data)[0]
        self.assertEqual("W" * 2000, _emf_texts(result.data)[0])
        self.assertTrue(_emf_text_options(result.data)[0] & ETO_CLIPPED)
        self.assertEqual((0, 0, 5000, 100), clip)

    # Verifies FR-2026-09-04-01 and FR-2026-10-28-05.
    def test_fits_unclipped_emf_text_and_stops_at_a_vertical_line(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(request, lambda text: TextReplacementItem("A considerably longer heading", 1.0))

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

        self.assertEqual(59, context.fitting_bounds.right)
        self.assertEqual("A considerably longer heading", _emf_text(result.data))
        self.assertEqual((0.0, 0.0), _emf_text_scales(result.data)[0])
        font_heights = _emf_font_heights(result.data)
        self.assertLess(abs(font_heights[1]), abs(font_heights[0]))
        self.assertEqual(-20, font_heights[0])
        self.assertEqual([1, 82, 37], _emf_record_types(result.data)[:3])
        self.assertEqual(10, struct.unpack_from("<I", result.data, 52)[0])
        self.assertEqual(3, struct.unpack_from("<H", result.data, 56)[0])

    # Verifies FR-2026-09-05-02 and FR-2026-10-28-05.
    def test_fits_contiguous_emf_records_as_one_expanding_visual_line(self) -> None:
        class _Provider:
            def __init__(self) -> None:
                self.requests: list[str] = []

            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                self.requests.extend(request.texts)
                return replace_each(
                    request, lambda text: TextReplacementItem("A considerably longer grouped heading", 1.0)
                )

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
        self.assertEqual(57, context.fitting_bounds.right)
        assert context.render_bounds is not None
        self.assertEqual(59, context.render_bounds.right)
        self.assertEqual(["AB"], provider.requests)
        self.assertEqual(
            ["A considerably longer grouped heading", ""], _emf_texts(result.data)
        )
        self.assertEqual(2, result.replaced_text_items)
        self.assertLess(abs(_emf_font_heights(result.data)[-1]), 20)
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-09-05-02.
    def test_does_not_group_emf_records_across_a_drawing_record(self) -> None:
        class _Provider:
            def __init__(self) -> None:
                self.requests: list[str] = []

            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                self.requests.extend(request.texts)
                return replace_each(request, lambda text: TextReplacementItem("A considerably longer heading", 1.0))

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
                self.requests.extend(request.texts)
                return replace_each(request, lambda text: TextReplacementItem("One coherent replacement", 1.0))

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

    # Verifies FR-2026-09-05-02 and FR-2026-10-29-01 in rendered coordinate space.
    def test_grouping_uses_device_bounds_only_once_under_transforms(self) -> None:
        source = bytearray(_emf_with_grouped_unclipped_text(
            preamble_records=(_emf_set_world_transform_record(2, 0, 0, 2, 37, 0),),
            intervening_records=(_emf_set_world_transform_record(2, 0, 0, 2, 437, 0),),
        ))
        struct.pack_into("<i", source, 16, 800)
        offset = 0
        text_index = 0
        while offset < len(source):
            record_type, size = struct.unpack_from("<II", source, offset)
            if record_type == 84:
                left, right = ((37, 437), (437, 477))[text_index]
                struct.pack_into("<iiii", source, offset + 8, left, 0, right, 40)
                struct.pack_into("<ii", source, offset + 36, 0, 0)
                text_index += 1
            offset += size
        for layout in ("preserve-basic-layout", "preserve-basic-layout-source-font"):
            with self.subTest(layout=layout):
                document = analyse_emf(
                    bytes(source), source_language="en", target_language="en",
                    document_text_layout=layout, trace_layout=True,
                )
                self.assertIn("AB", document.texts())
                engine = TranslationEngine(_LongReplacementProvider(), "en", "en")
                engine.add_unit("vector", document.texts())
                engine.resolve()
                result = document.apply(lambda text: engine.lookup(text).text, LookupProvider(engine.lookup))
                self.assertEqual(0, engine.plan_misses)
                first, second = result.emf_layout_trace
                self.assertEqual("group_anchor", first["outcome"])
                self.assertEqual("suppressed_group_member", second["outcome"])
                self.assertEqual([37, 0, 477, 40], first["source_bounds"])
                first_grouping = first["grouping"]
                second_grouping = second["grouping"]
                assert isinstance(first_grouping, dict) and isinstance(second_grouping, dict)
                self.assertEqual([37, 0, 437, 40], first_grouping["source_visual_bounds"])
                self.assertEqual([437, 0, 477, 40], second_grouping["source_visual_bounds"])
                self.assertEqual("EMF device units", second_grouping["source_visual_bounds_space"])
                units = first["geometry_units"]
                assert isinstance(units, dict)
                self.assertEqual("EMF device units", units["source_bounds"])
                self.assertEqual("EMF device units", units["fitting_bounds"])
                self.assertFalse(_emf_text_options(result.data)[0] & ETO_CLIPPED)
                self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-09-05-02: transformed clip compatibility uses device coordinates.
    def test_grouping_compares_transformed_explicit_clips(self) -> None:
        for first_clip_right, expected in ((210, True), (100, False)):
            with self.subTest(first_clip_right=first_clip_right):
                source = bytearray(_emf_with_grouped_unclipped_text(
                    clipped=True,
                    preamble_records=(_emf_set_world_transform_record(2, 0, 0, 2, 37, 0),),
                    intervening_records=(_emf_set_world_transform_record(2, 0, 0, 2, 437, 0),),
                ))
                struct.pack_into("<i", source, 16, 800)
                offset = 0
                text_index = 0
                while offset < len(source):
                    record_type, size = struct.unpack_from("<II", source, offset)
                    if record_type == 84:
                        bounds = ((37, 0, 437, 40), (417, 0, 429, 40))[text_index]
                        clip = ((0, 0, first_clip_right, 20), (-10, 0, -4, 20))[text_index]
                        struct.pack_into("<iiii", source, offset + 8, *bounds)
                        struct.pack_into("<ii", source, offset + 36, 0 if text_index == 0 else -10, 0)
                        struct.pack_into("<iiii", source, offset + 56, *clip)
                        text_index += 1
                    offset += size
                contexts, suppressed = _emf_grouped_unclipped_fit_contexts(
                    bytes(source), measure_source_fonts=False,
                )
                self.assertEqual(expected, bool(contexts))
                self.assertEqual(expected, bool(suppressed))

    # Verifies FR-2026-09-05-02 and FR-2026-10-29-02 for rendered gaps and colour spans.
    def test_grouping_transformed_gap_threshold_and_span_boundaries(self) -> None:
        for gap in (0, 1, 60, 61):
            with self.subTest(gap=gap):
                source = bytearray(_emf_with_grouped_unclipped_text(
                    preamble_records=(_emf_set_world_transform_record(2, 0, 0, 2, 37, 0),),
                    intervening_records=(
                        _emf_set_world_transform_record(2, 0, 0, 2, 437 + gap, 0),
                        _emf_set_text_color_record(0x0000FF),
                    ),
                ))
                struct.pack_into("<i", source, 16, 800)
                offset = 0
                text_index = 0
                while offset < len(source):
                    record_type, size = struct.unpack_from("<II", source, offset)
                    if record_type == 84:
                        bounds = ((37, 0, 437, 40), (437 + gap, 0, 477 + gap, 40))[text_index]
                        struct.pack_into("<iiii", source, offset + 8, *bounds)
                        struct.pack_into("<ii", source, offset + 36, 0, 0)
                        text_index += 1
                    offset += size
                contexts, suppressed = _emf_grouped_unclipped_fit_contexts(
                    bytes(source), measure_source_fonts=False,
                )
                self.assertEqual(gap <= 60, bool(contexts))
                self.assertEqual(gap <= 60, bool(suppressed))
                if contexts:
                    context = next(iter(contexts.values()))
                    first_span = "A" if gap == 0 else "A "
                    self.assertEqual(first_span + "B", context.source_text)
                    self.assertEqual(((first_span, 0, 1.0), ("B", 0x0000FF, 1.0)), context.line_spans)

    # Verifies FR-2026-10-29-01: standalone numbers more than 0.25 line heights apart
    # are separate labels or cells; touching number pieces and number-word pairs still join.
    def test_emf_standalone_numbers_are_kept_apart(self) -> None:
        for first, second, gap, grouped in (
            ("2012", "2014", 30, False),
            ("2012", "2014", 5, True),
            ("1,0", "23", 0, True),
            ("２０１２", "50%", 30, False),
            ("-1.5", "+2", 10, False),
            ("2012", "year", 20, True),
        ):
            with self.subTest(first=first, second=second, gap=gap):
                source = _emf_with_sized_line(
                    ((first, 20, 10, 60), (second, 20, 60 + gap, 110 + gap)),
                )
                trace: dict[int, dict[str, object]] = {}
                contexts, _suppressed = _emf_grouped_unclipped_fit_contexts(
                    source, measure_source_fonts=False, trace_grouping=trace,
                )
                self.assertEqual(grouped, bool(contexts))
                reasons = trace[max(trace)]["previous_boundary_reasons"]
                assert isinstance(reasons, list)
                self.assertEqual(not grouped, "standalone_numbers_separated" in reasons)

    # Verifies FR-2026-10-29-03: smaller text before, after, or between larger text
    # joins one GDI line when every member is at least 70% of the largest size.
    def test_emf_size_spans_group_within_tolerance(self) -> None:
        cases = {
            "smaller_follows": ((("Main", 20, 10, 80), ("(note)", 15, 82, 150)), (1.0, 0.75)),
            "smaller_precedes": ((("(note)", 15, 10, 80), ("Main", 20, 82, 150)), (0.75, 1.0)),
            "smaller_between": (
                (("Main", 20, 10, 80), ("(note)", 15, 82, 150), ("tail", 20, 152, 220)),
                (1.0, 0.75, 1.0),
            ),
        }
        for name, (members, ratios) in cases.items():
            with self.subTest(name=name):
                source = _emf_with_sized_line(members)
                trace: dict[int, dict[str, object]] = {}
                contexts, suppressed = _emf_grouped_unclipped_fit_contexts(
                    source, measure_source_fonts=False, trace_grouping=trace,
                )
                [context] = contexts.values()
                self.assertEqual(len(members) - 1, len(suppressed))
                self.assertEqual(ratios, tuple(span[2] for span in context.line_spans))
                self.assertEqual(
                    list(ratios), [trace[offset]["relative_font_size"] for offset in sorted(trace)],
                )

    # Verifies FR-2026-10-29-03: the 70% bound is inclusive and measured against
    # the line's largest member, so gradual size steps cannot accumulate.
    def test_emf_size_tolerance_bound_and_chain(self) -> None:
        for members, expected_members, reason in (
            ((("A", 20, 10, 40), ("B", 14, 42, 70)), 2, None),
            ((("A", 20, 10, 40), ("B", 13, 42, 70)), 0, "font_size_outside_tolerance"),
            ((("A", 20, 10, 40), ("B", 16, 42, 70), ("C", 13, 72, 100)), 2,
             "group_font_size_outside_tolerance"),
        ):
            with self.subTest(members=members):
                source = _emf_with_sized_line(members)
                trace: dict[int, dict[str, object]] = {}
                contexts, suppressed = _emf_grouped_unclipped_fit_contexts(
                    source, measure_source_fonts=False, trace_grouping=trace,
                )
                grouped = sum(len(context.group_offsets) for context in contexts.values())
                self.assertEqual(expected_members, grouped)
                last = trace[max(trace)]
                reasons = last["previous_boundary_reasons"]
                assert isinstance(reasons, list)
                if reason == "font_size_outside_tolerance":
                    self.assertIn(reason, reasons)
                    self.assertNotIn("font_size_mismatch", reasons)
                elif reason is not None:
                    self.assertEqual(reason, last["group_boundary_reason"])

    # Verifies FR-2026-10-29-03: other font differences and non-baseline origins still split.
    def test_emf_size_spans_still_require_face_and_baseline_origins(self) -> None:
        members = (("A", 20, 10, 40), ("B", 15, 42, 70))
        for name, source, reason in (
            ("face", _emf_with_sized_line(members, families=("Noto Sans JP", "Noto Serif")),
             "font_face_mismatch"),
            ("top_aligned", _emf_with_sized_line(members, alignment=0), "font_size_mismatch"),
        ):
            with self.subTest(name=name):
                trace: dict[int, dict[str, object]] = {}
                contexts, _suppressed = _emf_grouped_unclipped_fit_contexts(
                    source, measure_source_fonts=False, trace_grouping=trace,
                )
                self.assertEqual({}, contexts)
                reasons = trace[max(trace)]["previous_boundary_reasons"]
                assert isinstance(reasons, list)
                self.assertIn(reason, reasons)

    # Verifies FR-2026-10-29-03: spans are planned separately and drawn at their own
    # size times one uniform scale, keeping colour and the shared baseline.
    def test_emf_size_spans_keep_relative_sizes_with_one_scale(self) -> None:
        class _Provider:
            def __init__(self) -> None:
                self.requests: list[str] = []

            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                self.requests.extend(request.texts)
                return replace_each(request, lambda text: TextReplacementItem(text.upper() * 3, 1.0))

        source = _emf_with_sized_line(
            (("Main", 20, 10, 80), ("(note)", 15, 82, 150), ("tail", 20, 152, 220), ("end", 20, 222, 260)),
            colors=(0, 0, 0, 0x0000FF),
        )
        for layout in ("preserve-basic-layout", "preserve-basic-layout-source-font"):
            with self.subTest(layout=layout):
                document = analyse_emf(
                    source, source_language="en", target_language="en",
                    document_text_layout=layout, trace_layout=True,
                )
                provider = _Provider()
                engine = TranslationEngine(provider, "en", "en")
                engine.add_unit("vector", document.texts())
                engine.resolve()
                result = document.apply(lambda text: engine.lookup(text).text, LookupProvider(engine.lookup))
                self.assertEqual(0, engine.plan_misses)
                for span in ("Main ", "(note) ", "tail ", "end"):
                    self.assertIn(span, provider.requests)
                drawn = _emf_drawn_text_heights(result.data)
                self.assertEqual(
                    ["MAIN MAIN MAIN ", "(NOTE) (NOTE) (NOTE) ", "TAIL TAIL TAIL ", "ENDENDEND"],
                    [text for text, _height, _baseline in drawn],
                )
                large, small, tail, end = (height for _text, height, _baseline in drawn)
                self.assertEqual(large, tail)
                self.assertEqual(large, end)
                self.assertLessEqual(large, 20)
                self.assertLess(small, large)
                self.assertLessEqual(abs(small - large * 0.75), 1.0)
                self.assertEqual({100}, {baseline for _text, _height, baseline in drawn})
                anchor = result.emf_layout_trace[0]
                self.assertEqual("group_anchor", anchor["outcome"])
                assert isinstance(anchor["fit_scale"], float)
                self.assertLessEqual(anchor["fit_scale"], 1.0)
                self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-09-05-01: baselines include device-context origin changes.
    def test_grouping_baselines_include_viewport_origin(self) -> None:
        for vertical_offset, expected in ((0, True), (2, False)):
            with self.subTest(vertical_offset=vertical_offset):
                source = _emf_with_grouped_unclipped_text(
                    intervening_records=(struct.pack("<IIii", 12, 16, 0, vertical_offset),),
                )
                contexts, suppressed = _emf_grouped_unclipped_fit_contexts(
                    source, measure_source_fonts=False,
                )
                self.assertEqual(expected, bool(contexts))
                self.assertEqual(expected, bool(suppressed))

    # Verifies FR-2026-09-05-01 and FR-2026-10-28-04 for unresolved map-mode geometry.
    def test_grouping_rejects_unresolved_map_mode(self) -> None:
        source = _emf_with_grouped_unclipped_text(
            preamble_records=(struct.pack("<IIi", 17, 12, 8),),
        )
        result = analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _LongReplacementProvider())
        first, second = result.emf_layout_trace
        self.assertNotEqual("group_anchor", first["outcome"])
        self.assertNotEqual("suppressed_group_member", second["outcome"])
        grouping = first["grouping"]
        assert isinstance(grouping, dict)
        self.assertIn("coordinate_state_unsupported", grouping["eligibility_reasons"])

    # Verifies FR-2026-09-05-02 and FR-2026-10-29-02 for restored text paint state.
    def test_grouping_reconciles_temporary_text_paint_state(self) -> None:
        changes = (
            struct.pack("<III", 18, 12, 1),
            struct.pack("<III", 25, 12, 0x123456),
            struct.pack("<IIii", 120, 16, 2, 1),
        )
        for change in changes:
            for restore in (False, True):
                for layout in ("preserve-basic-layout", "preserve-basic-layout-source-font"):
                    with self.subTest(change=change, restore=restore, layout=layout):
                        records = (change, _emf_restore_dc_record(-1)) if restore else (change,)
                        source = _emf_with_grouped_unclipped_text(
                            preamble_records=(_emf_save_dc_record(),),
                            intervening_records=records,
                        )
                        document = analyse_emf(
                            source, source_language="en", target_language="en",
                            document_text_layout=layout, trace_layout=True,
                        )
                        if restore:
                            self.assertIn("AB", document.texts())
                        else:
                            self.assertNotIn("AB", document.texts())
                        result = document.apply(_mask, _LongReplacementProvider())
                        first, second = result.emf_layout_trace
                        grouping = second["grouping"]
                        assert isinstance(grouping, dict)
                        if restore:
                            self.assertEqual("group_anchor", first["outcome"])
                            self.assertEqual("suppressed_group_member", second["outcome"])
                            self.assertIsNone(grouping["intervening_barrier"])
                            self.assertTrue(grouping["text_paint_state_matches_previous"])
                        else:
                            self.assertEqual("individual_fit", first["outcome"])
                            self.assertEqual("individual_fit", second["outcome"])
                            self.assertFalse(grouping["text_paint_state_matches_previous"])
                            self.assertIn("text_paint_state_mismatch", grouping["previous_boundary_reasons"])
                            self.assertEqual(
                                {"record_type": struct.unpack_from("<I", change)[0],
                                 "record_offset": source.index(change)},
                                grouping["intervening_barrier"],
                            )
                        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-09-05-02: restoring paint state cannot remove an intervening drawing boundary.
    def test_restored_text_paint_state_does_not_hide_drawing_barrier(self) -> None:
        move = _emf_move_to_record(60, -10)
        source = _emf_with_grouped_unclipped_text(
            preamble_records=(_emf_save_dc_record(),),
            intervening_records=(
                struct.pack("<III", 18, 12, 1),
                move,
                _emf_line_to_record(60, 30),
                _emf_restore_dc_record(-1),
            ),
        )
        result = analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(_mask, _LongReplacementProvider())
        first, second = result.emf_layout_trace
        self.assertEqual("individual_fit", first["outcome"])
        self.assertEqual("individual_fit", second["outcome"])
        grouping = second["grouping"]
        assert isinstance(grouping, dict)
        self.assertTrue(grouping["text_paint_state_matches_previous"])
        self.assertEqual(
            {"record_type": 27, "record_offset": source.index(move)},
            grouping["intervening_barrier"],
        )

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

    # Verifies FR-2026-09-05-02 and FR-2026-10-28-05 for GDI metaregions.
    def test_grouping_respects_metaregion_after_clip_replacement(self) -> None:
        meta = _emf_extselect_clip_rect_record(0, -100, 65, 100)
        set_meta = struct.pack("<II", 28, 8)
        reset_clip = struct.pack("<IIII", 75, 16, 0, 5)
        replacement = _emf_extselect_clip_rect_record(0, -100, 95, 100)
        for selected in (reset_clip, replacement):
            with self.subTest(selected=selected):
                source = _emf_with_grouped_unclipped_text(
                    preamble_records=(meta, set_meta, selected),
                )
                contexts, suppressed = _emf_grouped_unclipped_fit_contexts(
                    source, measure_source_fonts=False,
                )
                self.assertEqual(1, len(contexts))
                self.assertEqual(1, len(suppressed))
                context = next(iter(contexts.values()))
                self.assertIsNotNone(context.render_bounds)
                assert context.render_bounds is not None
                self.assertEqual(65, context.render_bounds.right)

    # Verifies FR-2026-09-05-02: an unknown metaregion cannot be reset by replacing the clip.
    def test_unknown_metaregion_remains_a_grouping_boundary(self) -> None:
        exclude = struct.pack("<IIiiii", 29, 24, 0, 0, 10, 10)
        set_meta = struct.pack("<II", 28, 8)
        replacement = _emf_extselect_clip_rect_record(0, -100, 95, 100)
        source = _emf_with_grouped_unclipped_text(preamble_records=(exclude, set_meta, replacement))
        contexts, suppressed = _emf_grouped_unclipped_fit_contexts(source, measure_source_fonts=False)
        self.assertFalse(contexts)
        self.assertFalse(suppressed)

    # Verifies FR-2026-09-05-02: restoring or replacing known clip state remains safe.
    def test_metaregion_state_supports_clip_replacement_and_dc_restore(self) -> None:
        rect = _emf_extselect_clip_rect_record(0, -100, 65, 100)
        exclude = struct.pack("<IIiiii", 29, 24, 0, 0, 10, 10)
        reset_clip = struct.pack("<IIII", 75, 16, 0, 5)
        set_meta = struct.pack("<II", 28, 8)
        sequences = (
            (exclude, reset_clip, rect, set_meta),
            (rect, set_meta, _emf_save_dc_record(), exclude, _emf_restore_dc_record(-1)),
        )
        for records in sequences:
            with self.subTest(records=records):
                source = _emf_with_grouped_unclipped_text(preamble_records=records)
                document = analyse_emf(
                    source, source_language="en", target_language="en",
                    document_text_layout="preserve-basic-layout", trace_layout=True,
                )
                result = document.apply(_mask, _LongReplacementProvider())
                first, second = result.emf_layout_trace
                self.assertEqual("group_anchor", first["outcome"])
                self.assertEqual("suppressed_group_member", second["outcome"])
                grouping = first["grouping"]
                assert isinstance(grouping, dict)
                self.assertTrue(grouping["clip_state_known"])
                self.assertEqual([0, -100, 65, 100], grouping["meta_clip_bounds"])
                self.assertEqual(2, result.replaced_text_items)
                self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-09-05-02 for a resolved metaregion change between fragments.
    def test_grouping_across_setmetargn_with_unchanged_effective_clip(self) -> None:
        rect = _emf_extselect_clip_rect_record(0, -100, 65, 100)
        set_meta = struct.pack("<II", 28, 8)
        source = _emf_with_grouped_unclipped_text(
            preamble_records=(rect,), intervening_records=(set_meta,),
        )
        document = analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        )
        result = document.apply(_mask, _LongReplacementProvider())
        first, second = result.emf_layout_trace
        self.assertEqual("group_anchor", first["outcome"])
        self.assertEqual("suppressed_group_member", second["outcome"])
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-02: changed clips must not hide another group's source area.
    def test_group_splits_when_changed_active_clips_exclude_a_member(self) -> None:
        for first_right, second_right, grouped in ((15, 100, False), (100, 15, False), (100, 100, True)):
            with self.subTest(first_right=first_right, second_right=second_right):
                source = _emf_with_grouped_unclipped_text(
                    preamble_records=(_emf_extselect_clip_rect_record(0, -100, first_right, 100),),
                    intervening_records=(_emf_extselect_clip_rect_record(0, -100, second_right, 100),),
                )
                contexts, suppressed = _emf_grouped_unclipped_fit_contexts(
                    source, measure_source_fonts=False,
                )
                self.assertEqual(grouped, bool(contexts))
                self.assertEqual(grouped, bool(suppressed))
                document = analyse_emf(
                    source, source_language="en", target_language="en",
                    document_text_layout="preserve-basic-layout",
                )
                self.assertEqual(grouped, "AB" in document.texts())
                result = document.apply(_mask, _LongReplacementProvider())
                self.assertIn(_emf_extselect_clip_rect_record(0, -100, first_right, 100), result.data)
                self.assertIn(_emf_extselect_clip_rect_record(0, -100, second_right, 100), result.data)
                self.assertEqual(2, result.replaced_text_items)
                self.assertTrue(_emf_is_structurally_valid(result.data))

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
                self.requests.extend(request.texts)
                return replace_each(
                    request, lambda text: TextReplacementItem("A considerably longer grouped heading", 1.0)
                )

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
                self.requests.extend(request.texts)
                return replace_each(
                    request, lambda text: TextReplacementItem("A considerably longer grouped heading", 1.0)
                )

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

    # Verifies FR-2026-10-29-01: different fonts and sizes form separate lines.
    def test_does_not_group_across_font_or_size_changes(self) -> None:
        class _Provider:
            def __init__(self) -> None:
                self.requests: list[str] = []

            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                self.requests.extend(request.texts)
                return replace_each(request, lambda text: TextReplacementItem("A longer coherent replacement", 1.0))

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

        self.assertEqual(["A", "BBB"], provider.requests)
        self.assertEqual(
            ["A longer coherent replacement", "A longer coherent replacement"],
            _emf_texts(result.data),
        )
        self.assertIn(24, _emf_record_types(result.data))
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-01: equal fonts under different handles still group.
    def test_groups_equivalent_gdi_fonts_under_different_handles(self) -> None:
        source = _emf_with_text_state_changed_group(
            second_family="Noto Sans JP", second_height=-20, second_colour=0,
            change_paint_state=False,
        )
        contexts, suppressed = _emf_grouped_unclipped_fit_contexts(
            source, measure_source_fonts=False,
        )
        self.assertEqual(1, len(contexts))
        self.assertEqual(1, len(suppressed))

    # Verifies FR-2026-10-29-01: mixed GDI encodings form one line.
    def test_groups_mixed_gdi_encodings_with_unicode_output(self) -> None:
        for first_ansi, second_ansi in ((True, False), (False, True)):
            with self.subTest(first_ansi=first_ansi, second_ansi=second_ansi):
                source = _emf_with_grouped_unclipped_text(
                    first_ansi=first_ansi, second_ansi=second_ansi,
                )
                document = analyse_emf(
                    source, source_language="en", target_language="en",
                    document_text_layout="preserve-basic-layout",
                )
                self.assertIn("AB", document.texts())
                result = document.apply(_mask, _LongReplacementProvider())
                self.assertEqual("A considerably longer heading", _emf_texts(result.data)[0])
                self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-02: independently translated colour spans share one fit.
    def test_grouped_gdi_color_spans_keep_color_and_uniform_font(self) -> None:
        class _Provider:
            def __init__(self) -> None:
                self.requests: list[str] = []

            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                self.requests.extend(request.texts)
                return replace_each(request, lambda text: TextReplacementItem(
                    {"A": "Hello", "B": "world"}[text], 1.0,
                ))

        for layout in ("preserve-basic-layout", "preserve-basic-layout-source-font"):
            with self.subTest(layout=layout):
                source = _emf_with_grouped_unclipped_text(
                    intervening_records=(_emf_set_text_color_record(0x0000FF),)
                )
                document = analyse_emf(
                    source, source_language="en", target_language="en",
                    document_text_layout=layout,
                )
                self.assertEqual(("A", "A", "B", "B"), document.texts())
                provider = _Provider()
                result = document.apply(_mask, provider)
                self.assertEqual(["A", "B"], provider.requests)
                self.assertEqual(["Hello ", "world", ""], _emf_texts(result.data))
                drawn = _emf_drawn_text_state(result.data)
                self.assertEqual([("Hello ", 0, drawn[0][2]), ("world", 0x0000FF, drawn[0][2])], drawn)
                self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-02 for gaps, returning colours, punctuation and target language.
    def test_grouped_gdi_three_colour_spans_preserve_boundary_rules(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request,
                    lambda text: TextReplacementItem({"A ": "Word", "B": "1!", "C": "Next"}[text], 1.0),
                )

        source = _emf_with_grouped_unclipped_text(
            second_left=12, include_third=True,
            intervening_records=(_emf_set_text_color_record(0x0000FF),),
            third_intervening_records=(_emf_set_text_color_record(0),),
        )
        for layout in ("preserve-basic-layout", "preserve-basic-layout-source-font"):
            for language, words in (("en", ["Word ", "1!", "Next"]), ("ja", ["Word", "1!", "Next"])):
                with self.subTest(layout=layout, language=language):
                    document = analyse_emf(
                        source, source_language="en", target_language=language, document_text_layout=layout,
                    )
                    self.assertEqual(("A", "A ", "B", "C", "B", "C"), document.texts())
                    result = document.apply(_mask, _Provider())
                    drawn = _emf_drawn_text_state(result.data)
                    self.assertEqual(words, [text for text, _color, _font in drawn])
                    self.assertEqual([0, 0x0000FF, 0], [color for _text, color, _font in drawn])
                    self.assertEqual(1, len({font for _text, _color, font in drawn}))
                    self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-02: a failed group leaves both individual records eligible.
    def test_grouped_gdi_fit_failure_falls_back_atomically(self) -> None:
        source = _emf_with_grouped_unclipped_text(
            intervening_records=(_emf_set_text_color_record(0x0000FF),)
        )
        document = analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout",
        )
        with patch("pipeline.vector_text.emf.translate_and_fit_line", return_value=None):
            result = document.apply(_mask, _LongReplacementProvider())
        self.assertEqual(["#", "#"], _emf_texts(result.data))
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-02: grouped and fallback requests are planned and tracing is inert.
    def test_grouped_gdi_plan_and_trace_are_complete(self) -> None:
        source = _emf_with_grouped_unclipped_text(
            intervening_records=(_emf_set_text_color_record(0x0000FF),)
        )
        outputs: list[bytes] = []
        for trace in (False, True):
            document = analyse_emf(
                source, source_language="en", target_language="en",
                document_text_layout="preserve-basic-layout", trace_layout=trace,
            )
            engine = TranslationEngine(_LongReplacementProvider(), "en", "en")
            engine.add_unit("vector", document.texts())
            engine.resolve()
            result = document.apply(lambda text: engine.lookup(text).text, LookupProvider(engine.lookup))
            self.assertEqual(0, engine.plan_misses)
            outputs.append(result.data)
        self.assertEqual(outputs[0], outputs[1])

    # Verifies FR-2026-10-29-02: fallback translations are included in the resolved plan.
    def test_grouped_gdi_fallback_has_no_plan_misses(self) -> None:
        source = _emf_with_grouped_unclipped_text(
            intervening_records=(_emf_set_text_color_record(0x0000FF),)
        )
        for layout in ("preserve-basic-layout", "preserve-basic-layout-source-font"):
            with self.subTest(layout=layout):
                document = analyse_emf(source, source_language="en", target_language="en", document_text_layout=layout)
                engine = TranslationEngine(_LongReplacementProvider(), "en", "en")
                engine.add_unit("vector", document.texts())
                engine.resolve()
                with patch("pipeline.vector_text.emf._emf_fit_color_line", return_value=None):
                    result = document.apply(lambda text: engine.lookup(text).text, LookupProvider(engine.lookup))
                self.assertEqual(0, engine.plan_misses)
                self.assertEqual(["A considerably longer heading"] * 2, _emf_texts(result.data))
                self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-10-29-02: adjacent same-colour records form one translation span.
    def test_grouped_gdi_combines_adjacent_records_of_same_colour(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(request, lambda text: TextReplacementItem("T:" + text, 1.0))

        source = _emf_with_grouped_unclipped_text(
            include_third=True, third_intervening_records=(_emf_set_text_color_record(0x0000FF),),
        )
        document = analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout",
        )
        self.assertIn("AB", document.texts())
        engine = TranslationEngine(_Provider(), "en", "en")
        engine.add_unit("vector", document.texts())
        engine.resolve()
        result = document.apply(lambda text: engine.lookup(text).text, LookupProvider(engine.lookup))
        self.assertEqual(0, engine.plan_misses)
        drawn = _emf_drawn_text_state(result.data)
        self.assertEqual(["T:AB ", "T:C"], [text for text, _, _ in drawn])
        self.assertEqual([0, 0x0000FF], [color for _, color, _ in drawn])
        self.assertEqual(1, len({font for _, _, font in drawn}))
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-09-05-02.
    def test_groups_stock_font_records_using_generated_noto_fallback(self) -> None:
        class _Provider:
            def __init__(self) -> None:
                self.requests: list[str] = []

            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                self.requests.extend(request.texts)
                return replace_each(request, lambda text: TextReplacementItem("A longer coherent replacement", 1.0))

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
        self.assertEqual([1, 37, 82, 37, 84], _emf_record_types(result.data)[:5])
        self.assertTrue(_emf_is_structurally_valid(result.data))

    # Verifies FR-2026-09-05-02.
    def test_groups_mixed_bounded_and_measurement_derived_fragments(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                self.request = request.texts[0]
                return replace_each(request, lambda text: TextReplacementItem("One coherent replacement", 1.0))

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
        self.assertLess(abs(_emf_font_heights(result.data)[-1]), 20)

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
                self.assertLess(abs(_emf_font_heights(result.data)[-1]), 20)
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
        self.assertLess(abs(_emf_font_heights(result.data)[-1]), 20)

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

    # Verifies FR-2026-10-22-11 and FR-2026-09-04-01: a measurement wider than the bounds never vetoes.
    def test_unclipped_emf_text_whose_measurement_exceeds_its_bounds_is_still_fitted(self) -> None:
        source = _emf_with_unclipped_text(font_family="No Such Face", font_height=-40)

        self.assertEqual(1, len(_emf_unclipped_fit_contexts(source, measure_source_fonts=True)))
        for layout in ("preserve-basic-layout", "preserve-basic-layout-source-font"):
            with self.subTest(layout=layout):
                result = replace_vector_text(
                    source, ".emf", _mask, "en", document_text_layout=layout,
                    replacement_provider=_LongReplacementProvider(), target_language="en",
                )

                self.assertEqual("A considerably longer heading", _emf_text(result.data))
                self.assertLess(min(abs(height) for height in _emf_font_heights(result.data)), 40)

    # Verifies FR-2026-10-22-11 and FR-2026-09-04-01: a record without bounds is measured, not skipped.
    def test_unclipped_emf_text_without_record_bounds_is_measured_and_fitted(self) -> None:
        source = _emf_with_unclipped_text(font_family="No Such Face", font_height=-40, record_bounded=False)

        self.assertEqual(1, len(_emf_unclipped_fit_contexts(source, measure_source_fonts=True)))
        result = replace_vector_text(
            source, ".emf", _mask, "en", document_text_layout="preserve-basic-layout-source-font",
            replacement_provider=_LongReplacementProvider(), target_language="en",
        )

        self.assertEqual("A considerably longer heading", _emf_text(result.data))

    # Verifies FR-2026-10-22-11: text that cannot be fitted safely is still translated at its source size.
    def test_unclipped_emf_text_that_cannot_be_fitted_is_still_translated(self) -> None:
        source = _emf_with_unclipped_text(
            record_bounded=False,
            transform_records=(_emf_modify_world_transform_record(0.0, 0.0, 0.0, 1.0),),
        )

        result = replace_vector_text(
            source, ".emf", _mask, "en", document_text_layout="preserve-basic-layout",
            replacement_provider=_LongReplacementProvider(), target_language="en",
        )

        self.assertEqual("###", _emf_text(result.data))
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
        return replace_each(request, lambda text: TextReplacementItem("A considerably longer heading", 1.0))


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
    adjacent_record_bounded: bool = True,
    adjacent_preamble: tuple[bytes, ...] = (),
    transform_records: tuple[bytes, ...] = (),
    font_family: str = "Noto Sans JP",
    header_right: int = 200,
    font_height: int = -20,
    record_bounded: bool = True,
    record_clipped: bool = False,
    first_clip_bounds: tuple[int, int, int, int] | None = None,
) -> bytes:
    records = [_emf_font_record(font_family, height=font_height), _emf_select_object_record(1)]
    records.extend(transform_records)
    if line_x is not None:
        records.extend((_emf_move_to_record(line_x, -10), _emf_line_to_record(line_x, 30)))
    records.append(_emf_exttextout_record(
        "Old", 0, 0, 40, 20, bounded=record_bounded,
        clipped=record_clipped, clip_bounds=first_clip_bounds,
    ))
    if adjacent_text_left is not None:
        records.extend(adjacent_preamble)
        records.append(_emf_exttextout_record(
            "Value", adjacent_text_left, 0, 120, 20, bounded=adjacent_record_bounded
        ))
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
    preamble_records: tuple[bytes, ...] = (),
    trailing_records: tuple[bytes, ...] = (),
    first_ansi: bool = False,
    second_ansi: bool = False,
    intervening_records: tuple[bytes, ...] = (),
    third_intervening_records: tuple[bytes, ...] = (),
) -> bytes:
    records = [
        _emf_font_record("Noto Sans JP"),
        _emf_select_object_record(1),
        *preamble_records,
        _emf_exttextout_record(
            "A", 0, 0, 10, 20, clipped=clipped, ansi=first_ansi,
            clip_bounds=(0, 0, 100, 20) if clipped else None,
        ),
    ]
    if intervening_line:
        records.extend((_emf_move_to_record(60, -10), _emf_line_to_record(60, 30)))
    if state_only_intervening:
        records.extend((
            _emf_save_dc_record(),
            struct.pack("<IIf", 58, 12, 10.0),
            struct.pack("<III", 70, 12, 0),
            _emf_extselect_clip_rect_record(0, -100, 200, 100),
            _emf_restore_dc_record(-1),
        ))
    if state_clip_right is not None:
        records.append(_emf_extselect_clip_rect_record(0, -100, state_clip_right, 100))
    records.extend(intervening_records)
    records.append(_emf_exttextout_record(
        "B", second_left, 0, second_left + 30, 20, clipped=clipped, ansi=second_ansi,
        clip_bounds=(0, 0, 100, 20) if clipped else None,
    ))
    if include_third:
        records.extend(third_intervening_records)
        records.append(_emf_exttextout_record(
            "C", second_left + 10, 0, second_left + 40, 20, clipped=clipped,
            clip_bounds=(0, 0, 100, 20) if clipped else None,
        ))
    if line_x is not None:
        records.extend((_emf_move_to_record(line_x, -10), _emf_line_to_record(line_x, 30)))
    records.extend(trailing_records)
    header = bytearray(88)
    struct.pack_into("<II", header, 0, 1, len(header))
    struct.pack_into("<iiii", header, 8, 0, -100, 200, 100)
    eof = struct.pack("<IIIII", 14, 20, 0, 0, 0)
    result = bytearray(header + b"".join(records) + eof)
    struct.pack_into("<I", result, 48, len(result))
    struct.pack_into("<I", result, 52, len(records) + 2)
    return bytes(result)


def _emf_drawn_text_state(data: bytes) -> list[tuple[str, int, int]]:
    color = 0
    font = 0
    drawn: list[tuple[str, int, int]] = []
    offset = 0
    while offset < len(data):
        record_type, size = struct.unpack_from("<II", data, offset)
        record = data[offset:offset + size]
        if record_type == 24:
            color = struct.unpack_from("<I", record, 8)[0]
        elif record_type == 37:
            font = struct.unpack_from("<I", record, 8)[0]
        elif record_type == 84:
            text = _emf_texts(record)[0]
            if text:
                drawn.append((text, color, font))
        offset += size
    return drawn


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


def _emf_with_text_state_changed_group(
    *, second_family: str = "Noto Sans", second_height: int = -16,
    second_colour: int = 0x0000FF,
    change_paint_state: bool = True,
) -> bytes:
    records = [
        _emf_font_record("Noto Sans JP", handle=1, height=-20),
        _emf_select_object_record(1),
        _emf_set_text_color_record(0x000000),
        _emf_exttextout_record("A", 0, 0, 10, 20),
        _emf_font_record(second_family, handle=2, height=second_height),
        _emf_select_object_record(2),
        _emf_set_text_color_record(second_colour),
        _emf_set_text_alignment_record(0x0002),
        *((struct.pack("<IIi", 18, 12, 1), struct.pack("<IIii", 120, 16, 1, 1))
          if change_paint_state else ()),
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


def _emf_with_sized_line(
    members: tuple[tuple[str, int, int, int], ...],
    *,
    alignment: int = 24,
    families: tuple[str, ...] | None = None,
    colors: tuple[int, ...] | None = None,
) -> bytes:
    """Build one line of (text, font height, left, right) members on baseline y=100."""
    records: list[bytes] = [_emf_set_text_alignment_record(alignment)]
    for index, (text, height, left, right) in enumerate(members):
        family = "Noto Sans JP" if families is None else families[index]
        records.append(_emf_font_record(family, handle=index + 1, height=-height))
        records.append(_emf_select_object_record(index + 1))
        records.append(_emf_set_text_color_record(0 if colors is None else colors[index]))
        record = bytearray(_emf_exttextout_record(text, left, 100 - height, right, 100))
        struct.pack_into("<ii", record, 36, left, 100)
        records.append(bytes(record))
    header = bytearray(88)
    struct.pack_into("<II", header, 0, 1, len(header))
    struct.pack_into("<iiii", header, 8, 0, 0, 800, 200)
    eof = struct.pack("<IIIII", 14, 20, 0, 0, 0)
    result = bytearray(header + b"".join(records) + eof)
    struct.pack_into("<I", result, 48, len(result))
    struct.pack_into("<I", result, 52, len(records) + 2)
    return bytes(result)


def _emf_drawn_text_heights(data: bytes) -> list[tuple[str, int, int]]:
    """Return (text, selected font height, baseline y) for each painted text record."""
    heights: dict[int, int] = {}
    selected = 0
    drawn: list[tuple[str, int, int]] = []
    offset = 0
    while offset < len(data):
        record_type, size = struct.unpack_from("<II", data, offset)
        if record_type == 82:
            heights[struct.unpack_from("<I", data, offset + 8)[0]] = abs(
                struct.unpack_from("<i", data, offset + 12)[0]
            )
        elif record_type == 37:
            selected = struct.unpack_from("<I", data, offset + 8)[0]
        elif record_type == 84:
            text = _emf_texts(data[offset:offset + size])[0]
            if text:
                drawn.append((text, heights.get(selected, 0), struct.unpack_from("<i", data, offset + 40)[0]))
        offset += size
    return drawn


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
    ansi: bool = False,
) -> bytes:
    text_bytes = text.encode("latin-1" if ansi else "utf-16-le")
    record = bytearray(76 + len(text_bytes))
    struct.pack_into("<II", record, 0, 83 if ansi else 84, len(record))
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
