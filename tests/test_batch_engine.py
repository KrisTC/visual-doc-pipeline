"""Tests for the batching engine, the plan and apply convention, and the bitmap handler."""

from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image
# skia-python does not publish PEP 561 stubs; this is the native rendering boundary.
import skia  # type: ignore[import-not-found]

from pipeline.folder_replacement.bitmap import (
    apply_bitmap,
    bitmap_plan_bytes,
    plan_bitmap,
    plan_bitmap_bytes,
    plan_bitmap_file,
    replace_bitmap_bytes,
    replace_image,
    save_bitmap_file,
)
from pipeline.folder_replacement.planning import (
    NESTED_DOCUMENT_MAX_DEPTH,
    PhaseProgress,
    child_unit_id,
    enter_nested,
    plan_and_apply,
)
from pipeline.ocr import BoundingPolygon, OcrRequest, OcrResult, OcrText, PixelPoint
from pipeline.ocr.image_preparation import opaque_rgb_for_ocr
from pipeline.provider_cache import CACHE_FILENAME_SUFFIX, CachingTextReplacementProvider, source_cache_scope
from pipeline.provider_metrics import RunMetrics
from pipeline.text_region_colours import estimate_replacement_colours
from pipeline.text_region_rendering import TextRegionReplacement, replace_text_regions
from pipeline.text_replacement import (
    BatchLimits,
    TextReplacementItem,
    TextReplacementRequest,
    TextReplacementResult,
    TextUnit,
    TranslationEngine,
    notify_rate_limit_wait,
    replace_each,
)
from pipeline.text_replacement.errors import TextReplacementProviderError
from pipeline.text_replacement_plugins.character_mask import CharacterMaskProvider
from folder_replacement_test_support import FONT_PATH, _EmptyOcrProvider


class _RecordingProvider:
    """Translates by prefixing, and records every request it receives."""

    def __init__(
        self,
        limits: BatchLimits | None = None,
        cached: set[str] | None = None,
        wait_before_first_request: float | None = None,
    ) -> None:
        self.batch_limits = limits
        self.requests: list[TextReplacementRequest] = []
        self._cached = cached
        self._wait = wait_before_first_request

    def cached_flags(self, request: TextReplacementRequest) -> tuple[bool, ...]:
        return tuple(text in (self._cached or set()) for text in request.texts)

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        if self._wait is not None:
            notify_rate_limit_wait(self._wait)
            self._wait = None
        self.requests.append(request)
        return replace_each(request, lambda text: TextReplacementItem(f"T:{text}", 1.0))


class _NoLimitsProvider:
    """A provider that states neither batch limits nor a cache probe."""

    def __init__(self) -> None:
        self.requests: list[TextReplacementRequest] = []

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        self.requests.append(request)
        return replace_each(request, lambda text: TextReplacementItem(f"T:{text}", 1.0))


class _RegionsOcr(_EmptyOcrProvider):
    """Return a fixed list of confident synthetic regions and count calls."""

    def __init__(self, texts: tuple[str, ...]) -> None:
        self.texts = texts
        self.calls = 0

    def recognize(self, request: OcrRequest) -> OcrResult:
        self.calls += 1
        return OcrResult(
            tuple(
                OcrText(
                    text,
                    0.99,
                    BoundingPolygon(
                        (
                            PixelPoint(5 + 45 * index, 5),
                            PixelPoint(45 + 45 * index, 5),
                            PixelPoint(45 + 45 * index, 30),
                            PixelPoint(5 + 45 * index, 30),
                        )
                    ),
                )
                for index, text in enumerate(self.texts)
            )
        )


class _ProgressLog:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.total_growth: list[int] = []

    def progress(self) -> PhaseProgress:
        return PhaseProgress(
            lambda label: self.events.append(("advance", label)),
            lambda label: self.events.append(("label", label)),
            self.total_growth.append,
        )


def _units(engine: TranslationEngine, *units: TextUnit) -> None:
    for unit in units:
        engine.add_unit(unit.unit_id, unit.texts)


def _typeface() -> skia.Typeface:
    typeface = skia.Typeface.MakeFromFile(str(FONT_PATH))
    if typeface is None:
        raise AssertionError("Could not load test typeface.")
    return typeface


def _synthetic_png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (200, 40), "white").save(output, "PNG")
    return output.getvalue()


def _identity_item(text: str) -> TextReplacementItem:
    return TextReplacementItem(text, 1.0)


class TranslationEnginePackingTests(unittest.TestCase):
    # Verifies FR-2026-10-22-04's limits, order and request shape.
    def test_batches_obey_item_and_character_limits_in_document_order(self) -> None:
        provider = _RecordingProvider(BatchLimits(max_items=3, target_characters=10, max_characters=50))
        engine = TranslationEngine(provider, "ja", "en")
        _units(engine, TextUnit("doc", ("aa", "bb", "cc", "dd", "eeeeee", "fff")))

        engine.resolve()

        self.assertEqual(
            [("aa", "bb", "cc"), ("dd", "eeeeee"), ("fff",)],
            [request.texts for request in provider.requests],
        )
        for request in provider.requests:
            self.assertFalse(request.is_filename)
            self.assertEqual(("ja", "en"), (request.source_language, request.target_language))
        self.assertEqual("T:eeeeee", engine.lookup("eeeeee").text)

    # Verifies FR-2026-10-22-04's oversized-text rule.
    def test_a_text_above_the_target_is_sent_alone(self) -> None:
        provider = _RecordingProvider(BatchLimits(max_items=10, target_characters=5, max_characters=100))
        engine = TranslationEngine(provider, "ja", "en")
        _units(engine, TextUnit("doc", ("ab", "0123456789", "cd")))

        engine.resolve()

        self.assertEqual([("ab",), ("0123456789",), ("cd",)], [r.texts for r in provider.requests])

    # Verifies FR-2026-10-22-04's hard maximum and the text-free diagnostic.
    def test_a_text_above_the_hard_maximum_is_rejected_without_its_content(self) -> None:
        provider = _RecordingProvider(BatchLimits(max_items=10, target_characters=5, max_characters=8))
        engine = TranslationEngine(provider, "ja", "en")
        _units(engine, TextUnit("doc", ("secret-synthetic-text",)))

        with self.assertRaises(TextReplacementProviderError) as raised:
            engine.resolve()

        self.assertNotIn("secret-synthetic-text", str(raised.exception))
        self.assertEqual([], provider.requests)

    # Verifies FR-2026-10-22-04's no-limits rule.
    def test_a_provider_without_limits_gets_one_request_per_unit(self) -> None:
        provider = _NoLimitsProvider()
        engine = TranslationEngine(provider, "ja", "en")
        _units(engine, TextUnit("a", tuple(str(index) for index in range(300))), TextUnit("b", ("x", "y")))

        engine.resolve()

        self.assertEqual([300, 2], [len(request.texts) for request in provider.requests])

    # Verifies FR-2026-10-22-04's deduplication and unit boundary rules.
    def test_texts_are_deduplicated_across_units_and_batches_never_span_units(self) -> None:
        provider = _RecordingProvider(BatchLimits(max_items=100, target_characters=1000, max_characters=2000))
        engine = TranslationEngine(provider, "ja", "en")
        _units(
            engine,
            TextUnit("doc", ("one", "two", "one")),
            TextUnit("doc/image-1", ("two", "three")),
            TextUnit("doc/image-2", ("one", "two")),
        )

        batches = engine.plan_batches()
        engine.resolve()

        self.assertEqual([("doc", ("one", "two")), ("doc/image-1", ("three",))], [(b.unit_id, b.texts) for b in batches])
        self.assertEqual(3, engine.unique_texts)
        self.assertEqual([("one", "two"), ("three",)], [r.texts for r in provider.requests])
        for text in ("one", "two", "three"):
            self.assertEqual(f"T:{text}", engine.lookup(text).text)
        self.assertEqual(0, engine.plan_misses)

    # Verifies FR-2026-10-22-04's per-text equivalence.
    def test_results_equal_unbatched_per_text_translation(self) -> None:
        texts = tuple(f"text {index}" for index in range(25))
        batched = TranslationEngine(
            _RecordingProvider(BatchLimits(max_items=4, target_characters=30, max_characters=60)), "ja", "en"
        )
        _units(batched, TextUnit("doc", texts))
        batched.resolve()
        reference = CharacterMaskProvider()
        single = [
            reference.replace(TextReplacementRequest((text,), False, "ja", "en")).items[0] for text in texts
        ]
        masked = TranslationEngine(CharacterMaskProvider(), "ja", "en")
        _units(masked, TextUnit("doc", texts))
        masked.resolve()

        self.assertEqual(single, [masked.lookup(text) for text in texts])
        self.assertEqual(["T:" + text for text in texts], [batched.lookup(text).text for text in texts])

    # Verifies FR-2026-10-22-04's plan-miss fallback.
    def test_a_text_missing_from_the_plan_is_translated_singly_and_counted(self) -> None:
        provider = _RecordingProvider(BatchLimits(max_items=10))
        engine = TranslationEngine(provider, "ja", "en")
        _units(engine, TextUnit("doc", ("planned",)))
        with RunMetrics() as metrics:
            engine.resolve()

            self.assertEqual("T:unplanned", engine.lookup("unplanned").text)
            self.assertEqual("T:unplanned", engine.lookup("unplanned").text)

        self.assertEqual(1, engine.plan_misses)
        self.assertEqual(1, metrics.plan_misses)
        self.assertEqual(1, metrics.unique_texts)
        self.assertEqual([("planned",), ("unplanned",)], [r.texts for r in provider.requests])

    # Verifies FR-2026-10-22-04's resolve-once sequencing.
    def test_engine_rejects_misuse(self) -> None:
        engine = TranslationEngine(_RecordingProvider(), "ja", "en")
        engine.add_unit("doc", ("a",))
        with self.assertRaises(ValueError):
            engine.add_unit("doc", ("b",))
        with self.assertRaises(RuntimeError):
            engine.lookup("a")
        engine.resolve()
        with self.assertRaises(RuntimeError):
            engine.resolve()
        with self.assertRaises(RuntimeError):
            engine.add_unit("later", ("c",))

    # Verifies FR-2026-10-22-04's failure propagation to per-source isolation.
    def test_a_provider_failure_for_a_batch_propagates(self) -> None:
        class _Failing:
            batch_limits = None

            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                raise TextReplacementProviderError("synthetic failure")

        engine = TranslationEngine(_Failing(), "ja", "en")
        engine.add_unit("doc", ("a",))
        with self.assertRaises(TextReplacementProviderError):
            engine.resolve()


class TranslationEngineProgressTests(unittest.TestCase):
    # Verifies FR-2026-10-22-07's batch-count timing and per-batch steps.
    def test_progress_reports_remote_batches_once_and_each_batch(self) -> None:
        log = _ProgressLog()
        provider = _RecordingProvider(BatchLimits(max_items=2))
        engine = TranslationEngine(provider, "ja", "en")

        plan_and_apply(_OneUnitPlan(("a", "b", "c", "d", "e")), engine, lambda translate: translate("a"), log.progress())

        self.assertEqual([3], log.total_growth)
        self.assertEqual(
            [
                ("label", "Translating batch 1 of 3"),
                ("advance", "Translating batch 1 of 3"),
                ("label", "Translating batch 2 of 3"),
                ("advance", "Translating batch 2 of 3"),
                ("label", "Translating batch 3 of 3"),
                ("advance", "Translating batch 3 of 3"),
            ],
            log.events,
        )

    # Verifies FR-2026-10-22-07's fully cached source has no translate step.
    def test_batches_held_by_the_cache_add_no_translate_progress(self) -> None:
        log = _ProgressLog()
        provider = _RecordingProvider(BatchLimits(max_items=2), cached={"a", "b", "c", "d"})
        engine = TranslationEngine(provider, "ja", "en")

        plan_and_apply(_OneUnitPlan(("a", "b", "c", "d", "e")), engine, lambda translate: translate("a"), log.progress())

        self.assertEqual([1], log.total_growth)
        self.assertEqual(
            [("label", "Translating batch 1 of 1"), ("advance", "Translating batch 1 of 1")], log.events
        )
        self.assertEqual(3, len(provider.requests))

        fully_cached = _ProgressLog()
        provider = _RecordingProvider(BatchLimits(max_items=2), cached={"a", "b"})
        engine = TranslationEngine(provider, "ja", "en")
        plan_and_apply(_OneUnitPlan(("a", "b")), engine, lambda translate: translate("a"), fully_cached.progress())
        self.assertEqual([], fully_cached.total_growth)
        self.assertEqual([], fully_cached.events)

    # Verifies FR-2026-10-22-07's rate-limit label.
    def test_a_rate_limit_wait_shows_the_quota_label(self) -> None:
        log = _ProgressLog()
        provider = _RecordingProvider(wait_before_first_request=1.0)
        engine = TranslationEngine(provider, "ja", "en")

        plan_and_apply(_OneUnitPlan(("a",)), engine, lambda translate: translate("a"), log.progress())

        self.assertEqual(
            [
                ("label", "Translating batch 1 of 1"),
                ("label", "Waiting for translation quota"),
                ("advance", "Translating batch 1 of 1"),
            ],
            log.events,
        )

    # Verifies FR-2026-10-22-07's plan and apply labels.
    def test_plan_and_apply_items_advance_with_their_labels(self) -> None:
        log = _ProgressLog()
        progress = log.progress()

        progress.plan_item(3, 40, "page")
        progress.apply_item(3, 40, "page")

        self.assertEqual(
            [("advance", "Planning page 3 of 40"), ("advance", "Applying page 3 of 40")], log.events
        )

    # Verifies FR-2026-10-22-07's cache presence check without side effects.
    def test_cache_presence_check_reads_nothing_and_records_nothing(self) -> None:
        inner = _RecordingProvider()
        proxy = CachingTextReplacementProvider(inner, "synthetic:v1", "synthetic")
        request = TextReplacementRequest(("one", "two"), False, "ja", "en")
        with TemporaryDirectory() as directory, patch.dict("os.environ", {"PIPELINE_PLUGIN_CACHE": "1"}):
            source = Path(directory) / "sample.txt"
            with RunMetrics() as metrics, source_cache_scope(source):
                self.assertEqual((False, False), proxy.cached_flags(request))
                proxy.replace(TextReplacementRequest(("one",), False, "ja", "en"))
                calls_before = metrics.report(1)[0]["successful_calls"]
                self.assertEqual((True, False), proxy.cached_flags(request))
                self.assertEqual(calls_before, metrics.report(1)[0]["successful_calls"])
            self.assertTrue(source.with_name(f"{source.name}{CACHE_FILENAME_SUFFIX}").is_file())
        self.assertEqual(1, len(inner.requests))


class _OneUnitPlan:
    def __init__(self, texts: tuple[str, ...]) -> None:
        self._texts = texts

    def units(self) -> Iterator[TextUnit]:
        yield TextUnit("doc", self._texts)


class _TreePlan:
    """A synthetic nested document plan, planned the same way at every level."""

    def __init__(self, unit_id: str, texts: tuple[str, ...], children: tuple[_TreePlan, ...] = ()) -> None:
        self.unit_id = unit_id
        self.texts = texts
        self.children = children

    def units(self) -> Iterator[TextUnit]:
        yield TextUnit(self.unit_id, self.texts)
        for child in self.children:
            yield from child.units()


class PlanConventionTests(unittest.TestCase):
    # Verifies FR-2026-10-22-05's path-style identifiers and depth-first order.
    def test_three_level_nesting_yields_path_style_units_depth_first_and_one_resolve(self) -> None:
        image = _TreePlan(child_unit_id("docx/xlsx", "image-1"), ("image text",))
        workbook = _TreePlan(child_unit_id("docx", "xlsx"), ("cell", "shared"), (image,))
        sibling = _TreePlan(child_unit_id("docx", "image-2"), ("shared", "other"))
        document = _TreePlan("docx", ("body", "shared"), (workbook, sibling))
        provider = _RecordingProvider(BatchLimits(max_items=100, target_characters=1000, max_characters=2000))
        engine = TranslationEngine(provider, "ja", "en")

        plan_and_apply(document, engine, lambda translate: [translate(text) for text in ("body", "image text")])

        self.assertEqual(
            ["docx", "docx/xlsx", "docx/xlsx/image-1", "docx/image-2"],
            [unit.unit_id for unit in document.units()],
        )
        self.assertEqual(
            [("body", "shared"), ("cell",), ("image text",), ("other",)],
            [request.texts for request in provider.requests],
        )
        self.assertEqual(0, engine.plan_misses)

    # Verifies FR-2026-10-22-05's depth limit and the debug-only sidecar entry.
    def test_nested_documents_deeper_than_six_levels_are_left_unprocessed(self) -> None:
        self.assertEqual(6, NESTED_DOCUMENT_MAX_DEPTH)
        diagnostics: list[dict[str, object]] = []

        self.assertEqual(1, enter_nested(0, "word/embeddings/one.xlsx", diagnostics))
        self.assertEqual(6, enter_nested(5, "word/embeddings/six.xlsx", diagnostics))
        self.assertEqual([], diagnostics)
        self.assertIsNone(enter_nested(6, "word/embeddings/seven.xlsx", diagnostics))

        self.assertEqual(
            [
                {
                    "kind": "skipped",
                    "reason_code": "nested_document_depth_limit_exceeded",
                    "location": {"package_part": "word/embeddings/seven.xlsx"},
                    "depth": 7,
                }
            ],
            diagnostics,
        )

    # Verifies FR-2026-10-22-05's debug-only reporting.
    def test_the_depth_limit_writes_no_entry_without_diagnostics(self) -> None:
        self.assertIsNone(enter_nested(6, "word/embeddings/seven.xlsx", None))

    # Verifies FR-2026-10-22-05's single implementation for root and nested documents.
    def test_a_nested_bitmap_equals_the_same_bytes_processed_as_a_root_file(self) -> None:
        texts = ("alpha", "beta", "gamma")
        typeface = _typeface()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            source.write_bytes(_synthetic_png())

            root_plan = plan_bitmap_file(source, _RegionsOcr(texts), "en")
            root_engine = TranslationEngine(CharacterMaskProvider(), "en", "en")
            plan_and_apply(
                root_plan, root_engine, lambda translate: apply_bitmap(root_plan, translate, typeface, "en")
            )
            save_bitmap_file(root_plan, root / "root.png")

            nested_data, count = replace_bitmap_bytes(
                source.read_bytes(), _RegionsOcr(texts), CharacterMaskProvider(), "en", "en", typeface
            )

            self.assertEqual(3, count)
            self.assertEqual((root / "root.png").read_bytes(), nested_data)


class BitmapPlanApplyTests(unittest.TestCase):
    def _legacy_output(self, texts: tuple[str, ...], provider: object) -> bytes:
        """Reproduce the interleaved per-region path that plan and apply replaced."""
        image = Image.open(BytesIO(_synthetic_png()))
        image.load()
        detected = _RegionsOcr(texts).recognize(OcrRequest(opaque_rgb_for_ocr(image), "en")).text_items
        prepared = [
            TextRegionReplacement(
                item,
                colours,
                provider.replace(TextReplacementRequest((item.text,), False, "en", "en")).items[0].text,  # type: ignore[attr-defined]
            )
            for item, colours in zip(detected, estimate_replacement_colours(image, detected), strict=True)
        ]
        replace_text_regions(image, prepared, _typeface(), "en")
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    # Verifies FR-2026-10-22-04's output equivalence for bitmaps.
    def test_output_is_identical_to_per_region_translation_for_identity_and_mask_providers(self) -> None:
        texts = ("alpha", "beta", "gamma", "delta")
        identity = _NoLimitsProvider()
        identity.replace = lambda request: replace_each(request, lambda text: _identity_item(text))  # type: ignore[method-assign]
        for provider in (identity, CharacterMaskProvider()):
            with self.subTest(provider=type(provider).__name__):
                data, count = replace_bitmap_bytes(
                    _synthetic_png(), _RegionsOcr(texts), provider, "en", "en", _typeface()
                )

                self.assertEqual(4, count)
                self.assertEqual(self._legacy_output(texts, provider), data)

    # Verifies FR-2026-10-22-04's one-request-per-batch rule for bitmaps.
    def test_ocr_runs_once_and_request_count_matches_packing(self) -> None:
        texts = ("alpha", "beta", "gamma", "delta", "beta")
        ocr = _RegionsOcr(texts)
        provider = _RecordingProvider(BatchLimits(max_items=2, target_characters=1000, max_characters=2000))

        count = replace_image(Image.new("RGB", (240, 40), "white"), ocr, provider, "en", "en", _typeface())

        self.assertEqual(5, count)
        self.assertEqual(1, ocr.calls)
        self.assertEqual([("alpha", "beta"), ("gamma", "delta")], [r.texts for r in provider.requests])

    # Verifies FR-2026-10-22-04's plan-has-no-side-effects rule for bitmaps.
    def test_plan_calls_no_text_provider_and_apply_needs_no_plan_miss(self) -> None:
        ocr = _RegionsOcr(("alpha", "beta"))
        plan = plan_bitmap(Image.new("RGB", (200, 40), "white"), ocr, "en")
        before = plan.image.tobytes()
        provider = _RecordingProvider()

        self.assertEqual(before, plan.image.tobytes())
        self.assertEqual([], provider.requests)
        self.assertEqual([TextUnit("image", ("alpha", "beta"))], list(plan.units()))
        engine = TranslationEngine(provider, "en", "en")

        count = plan_and_apply(plan, engine, lambda translate: apply_bitmap(plan, translate, _typeface(), "en"))

        self.assertEqual(2, count)
        self.assertEqual(0, engine.plan_misses)
        self.assertEqual(1, len(provider.requests))

    # Verifies FR-2026-09-03-01's three nested stage labels.
    def test_nested_stage_labels_are_reported_in_order(self) -> None:
        labels: list[str] = []

        replace_bitmap_bytes(
            _synthetic_png(), _RegionsOcr(("alpha",)), _RecordingProvider(), "en", "en", _typeface(),
            nested_completed=labels.append,
        )

        self.assertEqual(["OCR recognition", "process OCR results", "render replacement image"], labels)

    # Verifies FR-2026-10-22-05's unit identifier for a nested bitmap.
    def test_a_nested_bitmap_plan_takes_its_path_style_unit_identifier(self) -> None:
        plan = plan_bitmap_bytes(
            _synthetic_png(), _RegionsOcr(("alpha",)), "en", unit_id=child_unit_id("docx", "image-1")
        )

        self.assertEqual(["docx/image-1"], [unit.unit_id for unit in plan.units()])
        self.assertEqual(_synthetic_png()[:8], bitmap_plan_bytes(plan)[:8])


if __name__ == "__main__":
    unittest.main()
