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
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from PIL import Image

from pipeline.ocr import BoundingPolygon, OcrProviderFactory, OcrResult, OcrText, PixelPoint
from pipeline.ocr.errors import OcrProviderError
from pipeline.ocr.models import OcrRequest
from pipeline.ocr.provider import LocalContractTestSkip
from scripts.prepare_ocr_evaluation_inputs import PreparationResult


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
            image = ocr_evaluation.EvaluationImage(
                "ja", image_path, Path("ja"), Path("ja/image.png")
            )
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
            include_patterns=("en/*.png", "ja/*.pptx", "en/extra.docx"),
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
                Path("en/a"), Path("en/a/same.png"),
            )
            second = ocr_evaluation.EvaluationImage(
                "en", Path(temporary_directory) / "input" / "en" / "b" / "same.png",
                Path("en/b"), Path("en/b/same.png"),
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

    # Verifies FR-2026-08-02-01.
    def test_groups_progress_by_language_directory_and_its_immediate_folders(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_root = Path(temporary_directory) / "input"
            direct_image = input_root / "en" / "direct.png"
            nested_image = input_root / "en" / "documents" / "nested" / "nested.png"
            direct_image.parent.mkdir(parents=True)
            nested_image.parent.mkdir(parents=True)
            Image.new("RGB", (2, 2), "red").save(direct_image)
            Image.new("RGB", (2, 2), "red").save(nested_image)

            groups = ocr_evaluation.progress_groups(
                ocr_evaluation.discover_evaluation_images(input_root)
            )

            self.assertEqual(
                {"en": 1, "en/documents": 1},
                {folder.as_posix(): len(images) for folder, images in groups.items()},
            )

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
            self.assertTrue((replacement_directory / "provider-0004.png").is_file())
            self.assertTrue(
                (replacement_directory / "region-0001.provider-0001.png").is_file()
            )
            self.assertTrue(
                (replacement_directory / "region-0001.provider-0004.png").is_file()
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
            self.assertIn("double_character_mask", replacement_viewer)
            self.assertIn("half_character_mask", replacement_viewer)
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
                f'<option value="{first_preview_path}">argos_translate</option>',
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
