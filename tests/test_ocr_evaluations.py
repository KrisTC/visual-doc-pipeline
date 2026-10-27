#!/usr/bin/env python3
"""Regression tests for local OCR evaluation generation."""

from __future__ import annotations

import importlib.util
from contextlib import redirect_stdout
from io import StringIO
import json
import re
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from PIL import Image

from pipeline.ocr import BoundingPolygon, OcrProviderFactory, OcrResult, OcrText, PixelPoint
from pipeline.ocr.errors import OcrProviderError
from pipeline.ocr.models import OcrRequest
from pipeline.ocr.provider import LocalContractTestSkip
from pipeline.terminal_progress import CurrentProgress
from pipeline.text_replacement import TextReplacementProviderFactory
from pipeline.text_replacement.errors import TextReplacementProviderNotFoundError
from pipeline.text_replacement_plugins.identity import IdentityProvider
from scripts.prepare_ocr_evaluation_inputs import PreparationProgress, PreparationResult


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "ocr_evaluations.py"
SPECIFICATION = importlib.util.spec_from_file_location("ocr_evaluation", SCRIPT_PATH)
assert SPECIFICATION is not None and SPECIFICATION.loader is not None
ocr_evaluation = importlib.util.module_from_spec(SPECIFICATION)
sys.modules[SPECIFICATION.name] = ocr_evaluation
SPECIFICATION.loader.exec_module(ocr_evaluation)


class FakeOcrProvider:
    """Predictable provider used to exercise the evaluator through its public protocol."""

    supported_languages = frozenset({"en"})
    supports_local_contract_test = False
    skipped_local_contract_angles: frozenset[int] = frozenset()
    skipped_local_contract_cases: frozenset[LocalContractTestSkip] = frozenset()

    def __init__(self) -> None:
        self.calls = 0

    def recognize(self, request: OcrRequest) -> OcrResult:
        self.calls += 1
        if request.image.getpixel((0, 0)) == (0, 0, 0):
            raise OcrProviderError("Synthetic OCR failure.")
        return OcrResult(
            (
                OcrText(
                    text="detected",
                    confidence=0.75,
                    bounding_polygon=BoundingPolygon(
                        (
                            PixelPoint(30, 25),
                            PixelPoint(50, 25),
                            PixelPoint(50, 35),
                            PixelPoint(30, 35),
                        )
                    ),
                ),
                OcrText(
                    text="low confidence",
                    confidence=0.64,
                    bounding_polygon=BoundingPolygon(
                        (
                            PixelPoint(55, 25),
                            PixelPoint(75, 25),
                            PixelPoint(75, 35),
                            PixelPoint(55, 35),
                        )
                    ),
                ),
            )
        )


class RecordingDisplay:
    """Records the LiveProgress calls made by the evaluator without rendering anything."""

    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []
        self.closed = False
        self._current_name: str | None = None
        self._advances: dict[str, int] = {}

    def __enter__(self) -> "RecordingDisplay":
        return self

    def __exit__(self, *_: object) -> None:
        self.closed = True

    @property
    def current(self) -> CurrentProgress:
        return CurrentProgress(self)  # type: ignore[arg-type]

    def start_overall(self, total: int | None, unit: str = "task") -> None:
        self.events.append(("overall", total))

    def set_overall_total(self, total: int) -> None:
        self.events.append(("overall_total", total))

    def advance_overall(self, count: int = 1) -> None:
        self.events.append(("overall_advance",))

    def start_current(self, name: str, total: int | None, unit: str) -> CurrentProgress:
        self._current_name = name
        self.events.append(("current", name, total))
        return self.current

    def set_current_label(self, label: str) -> None:
        self.events.append(("label", label))

    def advance_current(self, count: float = 1) -> None:
        self.events.append(("advance",))
        if self._current_name is not None:
            self._advances[self._current_name] = self._advances.get(self._current_name, 0) + 1

    def set_current_total(self, total: int) -> None:
        self.events.append(("current_total", total))

    def clear_current(self) -> None:
        self.events.append(("clear",))

    def stage_names(self) -> list[str]:
        names: list[str] = []
        for event in self.events:
            if event[0] == "current" and (not names or names[-1] != event[1]):
                names.append(str(event[1]))
        return names

    def totals_for(self, name: str) -> list[object]:
        return [event[2] for event in self.events if event[0] == "current" and event[1] == name]

    def advances_in(self, name: str) -> int:
        return self._advances.get(name, 0)

    def overall_advances(self) -> int:
        return self.events.count(("overall_advance",))


def _recording_factory(displays: list[RecordingDisplay]) -> Callable[[], RecordingDisplay]:
    def create() -> RecordingDisplay:
        display = RecordingDisplay()
        displays.append(display)
        return display

    return create


def _make_images(root: Path, count: int) -> tuple[Path, Path]:
    """Create synthetic English images named image-01.png onward; return input and output roots."""
    input_root = root / "input"
    language_root = input_root / "en"
    language_root.mkdir(parents=True)
    for number in range(1, count + 1):
        Image.new("RGB", (80, 60), "red").save(language_root / f"image-{number:02d}.png")
    return input_root, root / "output"


class RunOcrEvaluationsTests(unittest.TestCase):
    # Verifies FR-2026-10-24-02 and SR-2026-10-24-01.
    def test_default_excludes_google_cloud_vision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            image_path = input_root / "en" / "image.png"
            image_path.parent.mkdir(parents=True)
            Image.new("RGB", (80, 60), "red").save(image_path)
            provider = FakeOcrProvider()
            factory = OcrProviderFactory({"google_cloud_vision": lambda: provider})

            result = ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory)

            self.assertEqual(0, result.processed_images)
            self.assertEqual(0, provider.calls)
            self.assertFalse((output_root / "google_cloud_vision").exists())

    # Verifies FR-2026-10-24-02.
    def test_explicit_google_cloud_vision_selection_writes_only_its_viewer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            image_path = input_root / "en" / "image.png"
            image_path.parent.mkdir(parents=True)
            Image.new("RGB", (80, 60), "red").save(image_path)
            vision_provider = FakeOcrProvider()
            other_provider = FakeOcrProvider()
            factory = OcrProviderFactory(
                {
                    "google_cloud_vision": lambda: vision_provider,
                    "other": lambda: other_provider,
                }
            )

            result = ocr_evaluation.evaluate_ocr_inputs(
                input_root, output_root, factory, ocr_provider_name="google_cloud_vision"
            )

            self.assertEqual(1, result.successful_images)
            self.assertEqual(1, vision_provider.calls)
            self.assertEqual(0, other_provider.calls)
            self.assertTrue((output_root / "google_cloud_vision" / "index.html").is_file())
            self.assertFalse((output_root / "other").exists())

    # Verifies FR-2026-10-24-03.
    def test_filtered_evaluation_uses_only_selected_images_and_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            language_root = input_root / "en"
            language_root.mkdir(parents=True)
            Image.new("RGB", (80, 60), "red").save(language_root / "first.png")
            Image.new("RGB", (80, 60), "blue").save(language_root / "second.png")
            provider = FakeOcrProvider()
            factory = OcrProviderFactory({"fake": lambda: provider})

            first = ocr_evaluation.evaluate_ocr_inputs(
                input_root,
                output_root,
                factory,
                selected_image_paths=(Path("en/first.png"),),
            )
            second = ocr_evaluation.evaluate_ocr_inputs(
                input_root,
                output_root,
                factory,
                selected_image_paths=(Path("en/first.png"),),
            )
            third = ocr_evaluation.evaluate_ocr_inputs(
                input_root,
                output_root,
                factory,
                selected_image_paths=(Path("en/second.png"),),
            )

            self.assertEqual(1, first.successful_images)
            self.assertEqual(1, second.skipped_providers)
            self.assertEqual(1, third.successful_images)
            self.assertEqual(2, provider.calls)
            provider_root = output_root / "fake" / "en"
            self.assertFalse((provider_root / "first.png.json").exists())
            self.assertTrue((provider_root / "second.png.json").is_file())

    # Verifies FR-2026-10-24-03.
    def test_preparation_passes_selected_source_images_to_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "prepared"
            output_root = root / "output"
            provider = FakeOcrProvider()
            calls: list[tuple[Path, tuple[str, ...]]] = []

            def prepare_inputs(
                source_root: Path,
                prepared_output_root: Path,
                include_patterns: tuple[str, ...],
                progress: PreparationProgress,
            ) -> PreparationResult:
                calls.append((source_root, include_patterns))
                language_root = prepared_output_root / "en"
                language_root.mkdir(parents=True)
                Image.new("RGB", (80, 60), "red").save(language_root / "selected.png")
                Image.new("RGB", (80, 60), "blue").save(language_root / "old.png")
                return PreparationResult(selected_image_paths=(Path("en/selected.png"),))

            result = ocr_evaluation.prepare_and_evaluate_ocr_inputs(
                input_root,
                output_root,
                OcrProviderFactory({"fake": lambda: provider}),
                prepare_inputs,
                include_patterns=("en/selected.png",),
            )

            self.assertEqual([(Path("sample-data"), ("en/selected.png",))], calls)
            self.assertEqual(1, result.successful_images)
            self.assertEqual(1, provider.calls)
            self.assertFalse((output_root / "fake" / "en" / "old.png.json").exists())

    # Verifies FR-2026-10-24-03.
    def test_empty_filter_preserves_existing_output_without_provider_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_root = root / "output"
            provider_root = output_root / "fake"
            provider_root.mkdir(parents=True)
            sentinel = provider_root / "existing.txt"
            sentinel.write_text("retained", encoding="ascii")
            provider = FakeOcrProvider()

            result = ocr_evaluation.evaluate_ocr_inputs(
                root / "missing-input",
                output_root,
                OcrProviderFactory({"fake": lambda: provider}),
                selected_image_paths=(),
            )

            self.assertEqual(0, result.processed_images)
            self.assertEqual(0, provider.calls)
            self.assertEqual("retained", sentinel.read_text(encoding="ascii"))

    # Verifies FR-2026-10-24-03.
    def test_vision_old_line_artifacts_are_regenerated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            image_path = input_root / "en" / "image.png"
            image_path.parent.mkdir(parents=True)
            Image.new("RGB", (80, 60), "red").save(image_path)
            checksum = ocr_evaluation.input_tree_checksum(
                ocr_evaluation.discover_evaluation_images(input_root)
            )
            provider_root = output_root / "google_cloud_vision"
            provider_root.mkdir(parents=True)
            (provider_root / "index.html").write_text("old", encoding="ascii")
            (provider_root / ocr_evaluation.CHECKSUM_FILENAME).write_text(
                f"{checksum}\n", encoding="ascii"
            )
            (provider_root / ocr_evaluation.ARTIFACT_FORMAT_VERSION_FILENAME).write_text(
                "4-vision-line-v4\n", encoding="ascii"
            )
            provider = FakeOcrProvider()

            result = ocr_evaluation.evaluate_ocr_inputs(
                input_root,
                output_root,
                OcrProviderFactory({"google_cloud_vision": lambda: provider}),
                ocr_provider_name="google_cloud_vision",
            )

            self.assertEqual(1, result.successful_images)
            self.assertEqual(1, provider.calls)
            self.assertEqual(
                ocr_evaluation.VISION_ARTIFACT_FORMAT_VERSION,
                (provider_root / ocr_evaluation.ARTIFACT_FORMAT_VERSION_FILENAME)
                .read_text(encoding="ascii")
                .strip(),
            )

    # Verifies FR-2026-08-02-02 and FR-2026-10-24-03.
    def test_viewer_displays_detected_line_breaks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            provider_root = Path(temporary_directory) / "vision"
            provider_root.mkdir()
            image_path = Path(temporary_directory) / "input" / "ja" / "image.png"
            image_path.parent.mkdir(parents=True)
            Image.new("RGB", (8, 6), "white").save(image_path)
            image = ocr_evaluation.EvaluationImage("ja", image_path, Path("ja/image.png"))
            entry = ocr_evaluation.ViewerEntry(
                image, True, (0.9,), ("日本語\nSecond",), True
            )

            ocr_evaluation._write_viewer(provider_root, [entry])

            viewer = (provider_root / "index.html").read_text(encoding="utf-8")
            self.assertIn("white-space: pre-wrap", viewer)
            self.assertIn('<html lang="en" translate="no">', viewer)
            self.assertIn('<meta name="google" content="notranslate">', viewer)
            self.assertIn(
                '<td class="extracted-text notranslate" lang="ja" translate="no">'
                "日本語\nSecond</td>",
                viewer,
            )

    # Verifies FR-2026-08-01-03 across Windows drives.
    def test_relative_url_falls_back_to_a_file_url_when_no_relative_path_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "image.png"
            with patch.object(ocr_evaluation.os.path, "relpath", side_effect=ValueError):
                url = ocr_evaluation._relative_url(path, Path(temporary_directory) / "viewer")

            self.assertEqual(path.resolve().as_uri(), url)

    # Verifies FR-2026-10-24-02.
    def test_help_states_that_explicit_vision_selection_sends_images_to_google(self) -> None:
        output = StringIO()
        with patch.object(sys, "argv", ["ocr_evaluations.py", "--help"]), redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                ocr_evaluation.parse_arguments()
        self.assertEqual(0, raised.exception.code)
        self.assertIn("sends input image content to Google", " ".join(output.getvalue().split()))

    # Verifies FR-2026-10-24-02.
    def test_cli_selects_vision_without_requiring_paddle_models(self) -> None:
        with (
            patch.object(
                sys,
                "argv",
                [
                    "ocr_evaluations.py",
                    "--ocr",
                    "google_cloud_vision",
                    "--include",
                    "en/*.png,ja/*.pptx",
                    "--include",
                    "en/extra.docx",
                ],
            ),
            patch.object(ocr_evaluation, "require_runtime_assets") as require_assets,
            patch.object(
                ocr_evaluation,
                "prepare_and_evaluate_ocr_inputs",
                return_value=ocr_evaluation.EvaluationRunResult(),
            ) as evaluate,
        ):
            self.assertEqual(0, ocr_evaluation.main())
        require_assets.assert_called_once_with(
            "en", "google_cloud_vision", "preserve-source-formatting"
        )
        evaluate.assert_called_once_with(
            Path("outputs/evaluations/ocr/input"),
            Path("outputs/evaluations/ocr/output"),
            ocr_provider_name="google_cloud_vision",
            text_replacement_provider_name=None,
            include_patterns=("en/*.png", "ja/*.pptx", "en/extra.docx"),
            max_images=25,
        )

    # Verifies FR-2026-08-04-02.
    def test_excludes_the_no_ocr_provider_from_automatic_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            image_path = input_root / "en" / "image.png"
            image_path.parent.mkdir(parents=True)
            Image.new("RGB", (2, 2), "red").save(image_path)
            provider = FakeOcrProvider()
            factory = OcrProviderFactory({"no_ocr": lambda: provider})

            result = ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory)

            self.assertEqual(0, result.processed_images)
            self.assertEqual(0, provider.calls)
            self.assertFalse((output_root / "no_ocr").exists())

    # Verifies FR-2026-08-02-05.
    def test_prepares_standard_samples_before_evaluating(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            calls: list[tuple[Path, Path, tuple[str, ...]]] = []
            factory = OcrProviderFactory()

            def prepare_inputs(
                source_root: Path,
                prepared_output_root: Path,
                include_patterns: tuple[str, ...],
                progress: PreparationProgress,
            ) -> PreparationResult:
                calls.append((source_root, prepared_output_root, include_patterns))
                (prepared_output_root / "en").mkdir(parents=True)
                return PreparationResult()

            result = ocr_evaluation.prepare_and_evaluate_ocr_inputs(
                input_root, output_root, factory, prepare_inputs
            )

            self.assertEqual([(Path("sample-data"), input_root, ())], calls)
            self.assertEqual(0, result.successful_images)

    # Verifies FR-2026-08-02-03.
    def test_progress_labels_are_truncated_for_terminal_readability(self) -> None:
        label = ocr_evaluation._progress_label("folder/" + "x" * 100)

        self.assertLessEqual(len(label), ocr_evaluation.MAXIMUM_PROGRESS_LABEL_LENGTH)
        self.assertTrue(label.endswith("…"))

    # Verifies FR-2026-10-26-02.
    def test_masked_svg_escapes_provider_text_and_region_ids_are_unique_per_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            provider_root = Path(temporary_directory) / "output" / "fake"
            first = ocr_evaluation.EvaluationImage(
                "en", Path(temporary_directory) / "input" / "en" / "a" / "same.png",
                Path("en/a/same.png"),
            )
            second = ocr_evaluation.EvaluationImage(
                "en", Path(temporary_directory) / "input" / "en" / "b" / "same.png",
                Path("en/b/same.png"),
            )
            result = OcrResult(
                (
                    OcrText(
                        text='<b>&"quoted"</b>\x0c',
                        confidence=0.9,
                        bounding_polygon=BoundingPolygon(
                            (PixelPoint(1.5, 2), PixelPoint(9, 2), PixelPoint(9, 8))
                        ),
                    ),
                )
            )

            svg_text = ocr_evaluation._masked_svg(provider_root, first, (10, 10), result)

            root = ElementTree.fromstring(svg_text.split("\n", 1)[1])
            title = root.find("{http://www.w3.org/2000/svg}a/{http://www.w3.org/2000/svg}polygon/{http://www.w3.org/2000/svg}title")
            assert title is not None
            self.assertEqual('<b>&"quoted"</b>', title.text)
            self.assertNotEqual(
                ocr_evaluation._region_element_id(first, 1),
                ocr_evaluation._region_element_id(second, 1),
            )

    # Verifies FR-2026-10-26-03.
    def test_progress_stages_cover_prepare_ocr_and_every_text_replacement_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_root, output_root = _make_images(Path(temporary_directory), 2)
            provider = FakeOcrProvider()
            factory = OcrProviderFactory({"fake": lambda: provider})
            replacement_names = ocr_evaluation.BASELINE_TEXT_REPLACEMENT_PROVIDERS
            displays: list[RecordingDisplay] = []

            with patch.object(ocr_evaluation, "LiveProgress", _recording_factory(displays)):
                ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory)

            display = displays[0]
            self.assertEqual(
                ["Prepare inputs", "OCR"]
                + [f"Text replacement: {name}" for name in replacement_names],
                display.stage_names(),
            )
            self.assertEqual(("overall", None), display.events[0])
            self.assertIn(("overall_total", 2 + len(replacement_names)), display.events)
            self.assertEqual(2 + len(replacement_names), display.overall_advances())
            self.assertEqual([2], display.totals_for("OCR"))
            for name in replacement_names:
                self.assertEqual([2], display.totals_for(f"Text replacement: {name}"))
            self.assertIn(("label", "Writing viewer: fake"), display.events)
            self.assertTrue(display.closed)

    # Verifies FR-2026-10-26-03.
    def test_progress_shows_only_text_replacement_stages_when_ocr_is_current(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_root, output_root = _make_images(Path(temporary_directory), 1)
            provider = FakeOcrProvider()
            factory = OcrProviderFactory({"fake": lambda: provider})
            ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory)
            (output_root / "fake" / "text-replacement.html").unlink()
            replacement_count = len(ocr_evaluation.BASELINE_TEXT_REPLACEMENT_PROVIDERS)
            displays: list[RecordingDisplay] = []

            with patch.object(ocr_evaluation, "LiveProgress", _recording_factory(displays)):
                ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory)

            stages = displays[0].stage_names()
            self.assertEqual("Prepare inputs", stages[0])
            self.assertEqual(1 + replacement_count, len(stages))
            self.assertNotIn("OCR", stages)
            self.assertNotIn("Clean up", stages)
            self.assertIn(("overall_total", 1 + replacement_count), displays[0].events)

    # Verifies FR-2026-10-26-03.
    def test_progress_shows_only_prepare_stage_when_every_output_is_current(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_root, output_root = _make_images(Path(temporary_directory), 1)
            factory = OcrProviderFactory({"fake": FakeOcrProvider})
            ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory)
            displays: list[RecordingDisplay] = []
            output = StringIO()

            with (
                patch.object(ocr_evaluation, "LiveProgress", _recording_factory(displays)),
                redirect_stdout(output),
            ):
                ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory)

            self.assertEqual(["Prepare inputs"], displays[0].stage_names())
            self.assertIn(("overall_total", 1), displays[0].events)
            self.assertIn("Skipping fake", output.getvalue())

    # Verifies FR-2026-10-26-03.
    def test_cleanup_stage_counts_files_removed_from_an_existing_provider_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_root, output_root = _make_images(Path(temporary_directory), 1)
            factory = OcrProviderFactory({"fake": FakeOcrProvider})
            ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory)
            provider_root = output_root / "fake"
            (provider_root / "index.html").unlink()
            file_count = sum(1 for path in provider_root.rglob("*") if path.is_file())
            displays: list[RecordingDisplay] = []

            with patch.object(ocr_evaluation, "LiveProgress", _recording_factory(displays)):
                ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory)

            display = displays[0]
            self.assertEqual(["Prepare inputs", "Clean up", "OCR"], display.stage_names()[:3])
            self.assertEqual([None, file_count], display.totals_for("Clean up"))
            self.assertIn(("label", "Scanning"), display.events)
            self.assertIn(("label", "fake"), display.events)

    # Verifies FR-2026-10-26-03.
    def test_cleanup_failure_closes_the_display_before_the_error_propagates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_root, output_root = _make_images(Path(temporary_directory), 1)
            factory = OcrProviderFactory({"fake": FakeOcrProvider})
            ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory)
            (output_root / "fake" / "index.html").unlink()
            displays: list[RecordingDisplay] = []

            with (
                patch.object(ocr_evaluation, "LiveProgress", _recording_factory(displays)),
                patch.object(ocr_evaluation, "_remove_tree", side_effect=OSError("locked")),
            ):
                with self.assertRaises(OSError):
                    ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory)

            self.assertTrue(displays[0].closed)

    # Verifies FR-2026-10-26-03.
    def test_text_replacement_totals_exclude_images_whose_ocr_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_root, output_root = _make_images(Path(temporary_directory), 1)
            Image.new("RGB", (80, 60), "black").save(input_root / "en" / "failed.png")
            factory = OcrProviderFactory({"fake": FakeOcrProvider})
            displays: list[RecordingDisplay] = []

            with patch.object(ocr_evaluation, "LiveProgress", _recording_factory(displays)):
                ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory)

            display = displays[0]
            self.assertEqual([2], display.totals_for("OCR"))
            replacement_stages = [
                name for name in display.stage_names() if name.startswith("Text replacement: ")
            ]
            self.assertTrue(replacement_stages)
            for name in replacement_stages:
                self.assertEqual([1], display.totals_for(name))
                self.assertEqual(1, display.advances_in(name))

    # Verifies FR-2026-10-26-03.
    def test_text_replacement_failure_still_advances_the_current_row_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_root, output_root = _make_images(Path(temporary_directory), 2)
            factory = OcrProviderFactory({"fake": FakeOcrProvider})
            displays: list[RecordingDisplay] = []

            with (
                patch.object(ocr_evaluation, "LiveProgress", _recording_factory(displays)),
                patch.object(
                    ocr_evaluation, "_write_text_replacement_artifacts",
                    side_effect=ValueError("synthetic"),
                ),
            ):
                ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory)

            display = displays[0]
            for name in display.stage_names():
                if name.startswith("Text replacement: "):
                    self.assertEqual(2, display.advances_in(name))

    # Verifies FR-2026-10-26-03.
    def test_prepare_stage_is_active_while_preparation_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            displays: list[RecordingDisplay] = []

            def prepare_inputs(
                source_root: Path,
                prepared_output_root: Path,
                include_patterns: tuple[str, ...],
                progress: PreparationProgress,
            ) -> PreparationResult:
                self.assertEqual(1, len(displays))
                self.assertEqual(
                    [("overall", None), ("current", "Prepare inputs", None)],
                    displays[0].events[:2],
                )
                progress.start_step("Preparing", 2)
                progress.advance()
                progress.advance()
                (prepared_output_root / "en").mkdir(parents=True)
                return PreparationResult()

            with patch.object(ocr_evaluation, "LiveProgress", _recording_factory(displays)):
                ocr_evaluation.prepare_and_evaluate_ocr_inputs(
                    root / "input", root / "output", OcrProviderFactory(), prepare_inputs
                )

            self.assertIn(("label", "Preparing"), displays[0].events)
            self.assertEqual(2, displays[0].events.count(("advance",)))

    # Verifies FR-2026-10-26-04.
    def test_default_limit_keeps_the_first_25_images_and_reports_the_notice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_root, output_root = _make_images(Path(temporary_directory), 27)
            provider = FakeOcrProvider()
            output = StringIO()

            with redirect_stdout(output):
                result = ocr_evaluation.evaluate_ocr_inputs(
                    input_root, output_root, OcrProviderFactory({"fake": lambda: provider})
                )

            self.assertEqual(25, result.successful_images)
            self.assertEqual(25, provider.calls)
            self.assertTrue((output_root / "fake" / "en" / "image-25.png.json").is_file())
            self.assertFalse((output_root / "fake" / "en" / "image-26.png.json").exists())
            self.assertIn(
                "Limiting evaluation to the first 25 of 27 eligible images", output.getvalue()
            )
            self.assertIn("--max-images 0", output.getvalue())
            self.assertIn("--include", output.getvalue())
            viewer = (output_root / "fake" / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("image-26.png", viewer)

    # Verifies FR-2026-10-26-04.
    def test_zero_limit_evaluates_every_image_without_a_notice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_root, output_root = _make_images(Path(temporary_directory), 27)
            provider = FakeOcrProvider()
            output = StringIO()

            with redirect_stdout(output):
                result = ocr_evaluation.evaluate_ocr_inputs(
                    input_root, output_root, OcrProviderFactory({"fake": lambda: provider}),
                    max_images=0,
                )

            self.assertEqual(27, result.successful_images)
            self.assertNotIn("Limiting evaluation", output.getvalue())

    # Verifies FR-2026-10-26-04.
    def test_limit_applies_after_include_selection_and_in_sorted_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_root, output_root = _make_images(Path(temporary_directory), 6)
            provider = FakeOcrProvider()
            selected = tuple(Path(f"en/image-{number:02d}.png") for number in (6, 3, 5, 2))

            result = ocr_evaluation.evaluate_ocr_inputs(
                input_root, output_root, OcrProviderFactory({"fake": lambda: provider}),
                selected_image_paths=selected, max_images=2,
            )

            self.assertEqual(2, result.successful_images)
            provider_root = output_root / "fake" / "en"
            self.assertTrue((provider_root / "image-02.png.json").is_file())
            self.assertTrue((provider_root / "image-03.png.json").is_file())
            self.assertFalse((provider_root / "image-05.png.json").exists())

    # Verifies FR-2026-10-26-04.
    def test_changing_the_limit_regenerates_provider_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_root, output_root = _make_images(Path(temporary_directory), 4)
            provider = FakeOcrProvider()
            factory = OcrProviderFactory({"fake": lambda: provider})

            ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory, max_images=2)
            unchanged = ocr_evaluation.evaluate_ocr_inputs(
                input_root, output_root, factory, max_images=2
            )
            changed = ocr_evaluation.evaluate_ocr_inputs(
                input_root, output_root, factory, max_images=3
            )

            self.assertEqual(1, unchanged.skipped_providers)
            self.assertEqual(0, changed.skipped_providers)
            self.assertEqual(5, provider.calls)
            self.assertTrue(all(path.exists() for path in input_root.rglob("*.png")))

    # Verifies FR-2026-10-26-04 and FR-2026-10-24-02.
    def test_limit_applies_to_an_explicitly_selected_vision_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_root, output_root = _make_images(Path(temporary_directory), 3)
            provider = FakeOcrProvider()

            ocr_evaluation.evaluate_ocr_inputs(
                input_root, output_root,
                OcrProviderFactory({"google_cloud_vision": lambda: provider}),
                ocr_provider_name="google_cloud_vision", max_images=2,
            )

            self.assertEqual(2, provider.calls)

    # Verifies FR-2026-10-26-04.
    def test_max_images_option_defaults_to_25_and_rejects_invalid_values(self) -> None:
        with patch.object(sys, "argv", ["ocr_evaluations.py"]):
            self.assertEqual(25, ocr_evaluation.parse_arguments().max_images)
        with patch.object(sys, "argv", ["ocr_evaluations.py", "--max-images", "0"]):
            self.assertEqual(0, ocr_evaluation.parse_arguments().max_images)
        for value in ("-1", "many", "2.5"):
            error_output = StringIO()
            with (
                patch.object(sys, "argv", ["ocr_evaluations.py", "--max-images", value]),
                patch.object(sys, "stderr", error_output),
                self.assertRaises(SystemExit) as raised,
            ):
                ocr_evaluation.parse_arguments()
            self.assertEqual(2, raised.exception.code)
            self.assertIn("--max-images", error_output.getvalue())

    # Verifies FR-2026-10-26-04.
    def test_help_documents_the_image_limit_default_and_zero(self) -> None:
        output = StringIO()
        with patch.object(sys, "argv", ["ocr_evaluations.py", "--help"]), redirect_stdout(output):
            with self.assertRaises(SystemExit):
                ocr_evaluation.parse_arguments()
        help_text = " ".join(output.getvalue().split())
        self.assertIn("--max-images N", help_text)
        self.assertIn("default: 25", help_text)
        self.assertIn("0 means no limit", help_text)

    def _replacement_factory(self, created: list[str]) -> TextReplacementProviderFactory:
        def creator(name: str) -> Callable[[], IdentityProvider]:
            def create() -> IdentityProvider:
                created.append(name)
                return IdentityProvider()

            return create

        names = ("character_mask", "identity", "other", "remote_fake")
        return TextReplacementProviderFactory(
            {name: creator(name) for name in names},
            local_evaluation_eligibility={"other": True, "remote_fake": False},
        )

    # Verifies FR-2026-10-26-05.
    def test_default_runs_only_identity_and_character_mask(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_root, output_root = _make_images(Path(temporary_directory), 1)
            created: list[str] = []
            factory = OcrProviderFactory({"fake": FakeOcrProvider})

            ocr_evaluation.evaluate_ocr_inputs(
                input_root, output_root, factory,
                text_replacement_factory=self._replacement_factory(created),
            )

            self.assertEqual(["identity", "character_mask"], created)
            viewer = (output_root / "fake" / "text-replacement.html").read_text(encoding="utf-8")
            self.assertEqual(
                ["identity", "character_mask"],
                re.findall(r"<option [^>]*>([a-z_]+)</option>", viewer),
            )

    # Verifies FR-2026-10-26-05.
    def test_requested_provider_runs_last_even_when_not_locally_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_root, output_root = _make_images(Path(temporary_directory), 1)
            created: list[str] = []
            factory = OcrProviderFactory({"fake": FakeOcrProvider})
            displays: list[RecordingDisplay] = []

            with patch.object(ocr_evaluation, "LiveProgress", _recording_factory(displays)):
                ocr_evaluation.evaluate_ocr_inputs(
                    input_root, output_root, factory,
                    text_replacement_provider_name="remote_fake",
                    text_replacement_factory=self._replacement_factory(created),
                )

            self.assertEqual(["identity", "character_mask", "remote_fake"], created)
            self.assertEqual(
                ["Prepare inputs", "OCR"]
                + [f"Text replacement: {name}" for name in created],
                displays[0].stage_names(),
            )
            viewer = (output_root / "fake" / "text-replacement.html").read_text(encoding="utf-8")
            self.assertEqual(
                ["identity", "character_mask", "remote_fake"],
                re.findall(r"<option [^>]*>([a-z_]+)</option>", viewer),
            )
            self.assertRegex(viewer, r'<option [^>]*provider-0003\.png" selected>remote_fake<')
            self.assertIn('src="en/image-01.png.text-replacements/provider-0003.png"', viewer)

    # Verifies FR-2026-10-26-05.
    def test_naming_a_baseline_provider_runs_it_once_and_selects_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_root, output_root = _make_images(Path(temporary_directory), 1)
            created: list[str] = []
            factory = OcrProviderFactory({"fake": FakeOcrProvider})

            ocr_evaluation.evaluate_ocr_inputs(
                input_root, output_root, factory,
                text_replacement_provider_name="character_mask",
                text_replacement_factory=self._replacement_factory(created),
            )

            self.assertEqual(["identity", "character_mask"], created)
            viewer = (output_root / "fake" / "text-replacement.html").read_text(encoding="utf-8")
            self.assertRegex(viewer, r'provider-0001\.png" selected>identity<')

    # Verifies FR-2026-10-26-05.
    def test_unknown_text_replacement_provider_is_rejected_before_any_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_root, output_root = _make_images(Path(temporary_directory), 1)
            ocr_provider = FakeOcrProvider()
            factory = OcrProviderFactory({"fake": lambda: ocr_provider})
            prepare_calls: list[object] = []

            def prepare(*arguments: object) -> PreparationResult:
                prepare_calls.append(arguments)
                return PreparationResult()

            with self.assertRaisesRegex(
                TextReplacementProviderNotFoundError, "'nope'.*identity"
            ):
                ocr_evaluation.prepare_and_evaluate_ocr_inputs(
                    input_root, output_root, factory, prepare,
                    text_replacement_provider_name="nope",
                    text_replacement_factory=self._replacement_factory([]),
                )

            self.assertEqual([], prepare_calls)
            self.assertEqual(0, ocr_provider.calls)

    # Verifies FR-2026-10-26-05.
    def test_command_line_rejects_unknown_text_replacement_provider(self) -> None:
        error_output = StringIO()
        with (
            patch.object(sys, "argv", ["ocr_evaluations.py", "--text-replacement", "nope"]),
            patch.object(sys, "stderr", error_output),
            self.assertRaises(SystemExit) as raised,
        ):
            ocr_evaluation.parse_arguments()
        self.assertEqual(2, raised.exception.code)
        self.assertIn("--text-replacement", error_output.getvalue())
        self.assertIn("identity", error_output.getvalue())

    # Verifies FR-2026-10-26-05.
    def test_command_line_accepts_google_cloud_translate_and_help_names_remote_text(self) -> None:
        with patch.object(
            sys, "argv", ["ocr_evaluations.py", "--text-replacement", "google_cloud_translate"]
        ):
            arguments = ocr_evaluation.parse_arguments()
        self.assertEqual("google_cloud_translate", arguments.text_replacement)

        output = StringIO()
        with patch.object(sys, "argv", ["ocr_evaluations.py", "--help"]), redirect_stdout(output):
            with self.assertRaises(SystemExit):
                ocr_evaluation.parse_arguments()
        help_text = " ".join(output.getvalue().split())
        self.assertIn("--text-replacement PROVIDER", help_text)
        self.assertIn("sends recognised text to Google", help_text)

    # Verifies FR-2026-10-26-05.
    def test_changed_provider_set_regenerates_only_replacement_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_root, output_root = _make_images(Path(temporary_directory), 1)
            ocr_provider = FakeOcrProvider()
            factory = OcrProviderFactory({"fake": lambda: ocr_provider})
            created: list[str] = []
            replacement_factory = self._replacement_factory(created)

            def run(requested: str | None) -> None:
                ocr_evaluation.evaluate_ocr_inputs(
                    input_root, output_root, factory,
                    text_replacement_provider_name=requested,
                    text_replacement_factory=replacement_factory,
                )

            run(None)
            self.assertEqual(1, ocr_provider.calls)
            created.clear()

            run(None)
            self.assertEqual([], created)

            run("other")
            self.assertEqual(1, ocr_provider.calls)
            self.assertEqual(["identity", "character_mask", "other"], created)
            viewer = (output_root / "fake" / "text-replacement.html").read_text(encoding="utf-8")
            self.assertIn(">other</option>", viewer)
            created.clear()

            run("other")
            self.assertEqual([], created)

            run(None)
            self.assertEqual(["identity", "character_mask"], created)
            viewer = (output_root / "fake" / "text-replacement.html").read_text(encoding="utf-8")
            self.assertNotIn(">other</option>", viewer)
            self.assertEqual(1, ocr_provider.calls)

    # Verifies FR-2026-08-01-03 and FR-2026-08-02-13.
    def test_generates_visual_artifacts_failure_json_viewer_and_checksum_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "outputs" / "evaluations" / "ocr" / "input"
            output_root = root / "outputs" / "evaluations" / "ocr" / "output"
            successful_image = input_root / "collection" / "en" / "nested" / "success.png"
            unsupported_image = input_root / "collection" / "fr" / "unsupported.png"
            failed_image = input_root / "collection" / "en" / "failed.png"
            successful_image.parent.mkdir(parents=True)
            unsupported_image.parent.mkdir(parents=True)
            Image.new("RGB", (80, 60), "red").save(successful_image)
            Image.new("RGB", (80, 60), "blue").save(unsupported_image)
            Image.new("RGB", (80, 60), "black").save(failed_image)

            provider = FakeOcrProvider()
            factory = OcrProviderFactory()
            factory = OcrProviderFactory({"fake": lambda: provider})

            first_run = ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory)

            provider_root = output_root / "fake"
            success_base = provider_root / "collection" / "en" / "nested" / "success.png"
            self.assertEqual(1, first_run.successful_images)
            self.assertEqual(2, first_run.failed_images)
            self.assertEqual(0, first_run.skipped_providers)
            self.assertEqual(2, provider.calls)
            self.assertEqual(
                {
                    "status": "succeeded",
                    "source_language": "en",
                    "text_items": [
                        {
                            "text": "detected",
                            "confidence": 0.75,
                            "bounding_polygon": [
                                {"x": 30, "y": 25},
                                {"x": 50, "y": 25},
                                {"x": 50, "y": 35},
                                {"x": 30, "y": 35},
                            ],
                            "padded_bounding_polygon": [
                                {"x": 20, "y": 20},
                                {"x": 40, "y": 20},
                                {"x": 40, "y": 30},
                                {"x": 20, "y": 30},
                            ],
                            "padded_image_path": "success.png.text-0001.png",
                            "extra": {},
                        },
                        {
                            "text": "low confidence",
                            "confidence": 0.64,
                            "bounding_polygon": [
                                {"x": 55, "y": 25},
                                {"x": 75, "y": 25},
                                {"x": 75, "y": 35},
                                {"x": 55, "y": 35},
                            ],
                            "padded_bounding_polygon": [
                                {"x": 20, "y": 20},
                                {"x": 40, "y": 20},
                                {"x": 40, "y": 30},
                                {"x": 20, "y": 30},
                            ],
                            "padded_image_path": "success.png.text-0002.png",
                            "extra": {},
                        },
                    ],
                },
                json.loads(success_base.with_name("success.png.json").read_text(encoding="utf-8")),
            )
            masked_path = success_base.with_name("success.png.masked.svg")
            self.assertTrue(masked_path.is_file())
            self.assertFalse(success_base.with_name("success.png.masked.png").exists())
            self.assertTrue(success_base.with_name("success.png.text-0001.png").is_file())
            self.assertTrue(success_base.with_name("success.png.text-0002.png").is_file())
            masked_svg = ElementTree.parse(masked_path).getroot()
            svg_namespace = "{http://www.w3.org/2000/svg}"
            self.assertEqual("0 0 80 60", masked_svg.get("viewBox"))
            svg_image = masked_svg.find(f"{svg_namespace}image")
            assert svg_image is not None
            self.assertEqual(
                "../../../../../input/collection/en/nested/success.png",
                svg_image.get("href"),
            )
            svg_polygons = masked_svg.findall(f"{svg_namespace}a/{svg_namespace}polygon")
            self.assertEqual(
                ["30,25 50,25 50,35 30,35", "55,25 75,25 75,35 55,35"],
                [polygon.get("points") for polygon in svg_polygons],
            )
            self.assertEqual(
                ["detected", "low confidence"],
                [polygon.findtext(f"{svg_namespace}title") for polygon in svg_polygons],
            )
            viewer_row_identifiers = re.findall(
                r'<tr id="(region-[0-9a-f]+-\d+)"', (provider_root / "index.html").read_text(encoding="utf-8")
            )
            self.assertEqual(2, len(viewer_row_identifiers))
            self.assertEqual(
                [
                    f"../../../index.html#{identifier}"
                    for identifier in viewer_row_identifiers
                ],
                [link.get("href") for link in masked_svg.findall(f"{svg_namespace}a")],
            )
            self.assertEqual(
                ["_top", "_top"],
                [link.get("target") for link in masked_svg.findall(f"{svg_namespace}a")],
            )
            with Image.open(success_base.with_name("success.png.text-0001.png")) as clip:
                self.assertEqual((60, 50), clip.size)
            replacement_directory = success_base.with_name("success.png.text-replacements")
            self.assertTrue((replacement_directory / "provider-0001.png").is_file())
            self.assertTrue((replacement_directory / "provider-0002.png").is_file())
            self.assertFalse((replacement_directory / "provider-0003.png").exists())
            self.assertTrue(
                (replacement_directory / "region-0001.provider-0001.png").is_file()
            )
            self.assertTrue(
                (replacement_directory / "region-0001.provider-0002.png").is_file()
            )
            self.assertFalse(
                (replacement_directory / "region-0002.provider-0001.png").exists()
            )

            self.assertEqual(
                {"status": "failed"},
                json.loads(
                    (provider_root / "collection" / "fr" / "unsupported.png.json").read_text(
                        encoding="utf-8"
                    )
                ),
            )
            self.assertEqual(
                {"status": "failed"},
                json.loads(
                    (provider_root / "collection" / "en" / "failed.png.json").read_text(
                        encoding="utf-8"
                    )
                ),
            )
            self.assertFalse((provider_root / "collection" / "fr" / "unsupported.png.masked.svg").exists())
            self.assertFalse((provider_root / "collection" / "en" / "failed.png.masked.svg").exists())
            viewer = (provider_root / "index.html").read_text(encoding="utf-8")
            self.assertIn(
                '<object type="image/svg+xml" style="aspect-ratio: 80 / 60; height: auto; '
                'max-width: 100%; width: 80px" data="collection/en/nested/success.png.masked.svg">',
                viewer,
            )
            self.assertIn("tr:target td", viewer)
            self.assertNotIn('alt="Detected text masked in black"', viewer)
            self.assertIn("<table>", viewer)
            self.assertIn("detected", viewer)
            self.assertIn("75.00%", viewer)
            self.assertIn('class="confidence"', viewer)
            self.assertIn('target="_blank"', viewer)
            self.assertNotIn("<pre", viewer)
            self.assertNotIn("toggle-results", viewer)
            self.assertNotIn("character_mask", viewer)
            replacement_viewer = (provider_root / "text-replacement.html").read_text(
                encoding="utf-8"
            )
            self.assertIn("<th>Region</th><th>Original text image</th>", replacement_viewer)
            self.assertIn("character_mask", replacement_viewer)
            self.assertNotIn("double_character_mask", replacement_viewer)
            self.assertNotIn("half_character_mask", replacement_viewer)
            self.assertNotIn("argos_translate", replacement_viewer)
            self.assertIn("identity", replacement_viewer)
            self.assertIn("Language: en→en.", replacement_viewer)
            self.assertIn('data-replacement-preview="replacement-preview-', replacement_viewer)
            self.assertIn('document.querySelectorAll("select[data-replacement-preview]")', replacement_viewer)
            self.assertIn(
                ">Detected regions masked</option>", replacement_viewer
            )
            self.assertIn(
                '<option value="collection/en/nested/success.png.masked.svg">'
                "Detected regions masked</option>",
                replacement_viewer,
            )
            self.assertIn(
                '<object type="image/svg+xml" style="aspect-ratio: 80 / 60; height: auto; '
                'max-width: 100%; width: 80px" id="replacement-preview-2-mask" hidden>',
                replacement_viewer,
            )
            self.assertIn('data-replacement-mask="replacement-preview-2-mask"', replacement_viewer)
            self.assertIn('select.value.endsWith(".svg")', replacement_viewer)
            self.assertIn('.top-previews { display: flex; flex-wrap: nowrap;', replacement_viewer)
            self.assertIn('flex: 0 0 calc(50% - .5rem);', replacement_viewer)
            self.assertIn('.top-preview img { display: block; max-width: 100%; }', replacement_viewer)
            self.assertLess(
                replacement_viewer.index(">identity</option>"),
                replacement_viewer.index(">Detected regions masked</option>"),
            )
            first_preview_path = (
                "collection/en/nested/success.png.text-replacements/provider-0001.png"
            )
            self.assertIn(
                f'<option value="{first_preview_path}" selected>identity</option>',
                replacement_viewer,
            )
            self.assertIn(
                f'<img id="replacement-preview-2" alt="Complete text-replacement preview" '
                f'src="{first_preview_path}">',
                replacement_viewer,
            )
            self.assertIn(
                '<tr><td>1</td>', replacement_viewer
            )
            self.assertNotIn(
                '<tr><td>2</td>', replacement_viewer
            )
            self.assertEqual(
                1,
                replacement_viewer.count('alt="Original input"'),
            )
            self.assertNotIn('alt="Detected text masked in black"', replacement_viewer)
            self.assertTrue((provider_root / ".input.sha256").is_file())
            self.assertEqual(
                ocr_evaluation.ARTIFACT_FORMAT_VERSION,
                (provider_root / ".artifact-format-version").read_text(
                    encoding="ascii"
                ).strip(),
            )
            self.assertEqual(
                ocr_evaluation.TEXT_REPLACEMENT_ARTIFACT_FORMAT_VERSION,
                (
                    provider_root / ".text-replacement-artifact-format-version"
                ).read_text(encoding="ascii").strip(),
            )

            second_run = ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory)
            self.assertEqual(1, second_run.skipped_providers)
            self.assertEqual(2, provider.calls)

            (provider_root / "text-replacement.html").unlink()
            third_run = ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory)
            self.assertEqual(1, third_run.skipped_providers)
            self.assertEqual(2, provider.calls)
            self.assertTrue((provider_root / "text-replacement.html").is_file())

            stale_mirrored_folder = provider_root / "stale mirrored folder"
            stale_mirrored_folder.mkdir()
            (stale_mirrored_folder / "stale.txt").write_text("stale", encoding="ascii")
            (provider_root / "index.html").unlink()
            fourth_run = ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory)
            self.assertEqual(0, fourth_run.skipped_providers)
            self.assertEqual(4, provider.calls)
            self.assertFalse(stale_mirrored_folder.exists())

            (provider_root / ".artifact-format-version").unlink()
            fifth_run = ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory)
            self.assertEqual(0, fifth_run.skipped_providers)
            self.assertEqual(6, provider.calls)

    # Verifies FR-2026-08-02-07.
    def test_pads_text_clips_and_translates_polygon_coordinates(self) -> None:
        source_image = Image.new("RGB", (100, 80), "white")
        vertices = (
            PixelPoint(30, 25),
            PixelPoint(35, 25),
            PixelPoint(35, 28),
            PixelPoint(30, 28),
        )
        self.assertEqual(
            (10, 5, 55, 48),
            ocr_evaluation._padded_clipped_bounds(source_image, vertices),
        )
        self.assertEqual(
            [
                {"x": 20, "y": 20},
                {"x": 25, "y": 20},
                {"x": 25, "y": 23},
                {"x": 20, "y": 23},
            ],
            ocr_evaluation._translated_polygon_payload(vertices, (10, 5, 55, 48)),
        )

        edge_vertices = (
            PixelPoint(1, 1),
            PixelPoint(5, 1),
            PixelPoint(5, 4),
            PixelPoint(1, 4),
        )
        self.assertEqual(
            (0, 0, 25, 24),
            ocr_evaluation._padded_clipped_bounds(source_image, edge_vertices),
        )


if __name__ == "__main__":
    unittest.main()
