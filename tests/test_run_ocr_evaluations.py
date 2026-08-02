#!/usr/bin/env python3
"""Regression tests for local OCR evaluation generation."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from pipeline.ocr import BoundingPolygon, OcrProviderFactory, OcrResult, OcrText, PixelPoint
from pipeline.ocr.errors import OcrProviderError
from pipeline.ocr.models import OcrRequest
from pipeline.ocr.provider import LocalContractTestSkip


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_ocr_evaluations.py"
SPECIFICATION = importlib.util.spec_from_file_location("ocr_evaluation", SCRIPT_PATH)
assert SPECIFICATION is not None and SPECIFICATION.loader is not None
ocr_evaluation = importlib.util.module_from_spec(SPECIFICATION)
sys.modules[SPECIFICATION.name] = ocr_evaluation
SPECIFICATION.loader.exec_module(ocr_evaluation)


class FakeOcrProvider:
    """Predictable provider used to exercise the evaluator through its public protocol."""

    name = "fake"
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
    # Verifies FR-2026-08-02-05.
    def test_prepares_standard_samples_before_evaluating(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            calls: list[tuple[Path, Path]] = []
            factory = OcrProviderFactory()

            def prepare_inputs(source_root: Path, prepared_output_root: Path) -> None:
                calls.append((source_root, prepared_output_root))
                (prepared_output_root / "en").mkdir(parents=True)

            result = ocr_evaluation.prepare_and_evaluate_ocr_inputs(
                input_root, output_root, factory, prepare_inputs
            )

            self.assertEqual([(Path("sample-data"), input_root)], calls)
            self.assertEqual(0, result.successful_images)

    # Verifies FR-2026-08-02-03.
    def test_progress_labels_are_truncated_for_terminal_readability(self) -> None:
        label = ocr_evaluation._progress_label("folder/" + "x" * 100)

        self.assertLessEqual(len(label), ocr_evaluation.MAXIMUM_PROGRESS_LABEL_LENGTH)
        self.assertTrue(label.endswith("…"))

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
            factory.register(provider.name, lambda: provider)

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
            masked_path = success_base.with_name("success.png.masked.png")
            self.assertTrue(masked_path.is_file())
            self.assertTrue(success_base.with_name("success.png.text-0001.png").is_file())
            self.assertTrue(success_base.with_name("success.png.text-0002.png").is_file())
            with Image.open(masked_path) as masked_image:
                self.assertEqual((0, 0, 0, 255), masked_image.getpixel((35, 30)))
                self.assertEqual((255, 0, 0, 255), masked_image.getpixel((0, 0)))
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
            self.assertFalse((provider_root / "collection" / "fr" / "unsupported.png.masked.png").exists())
            self.assertFalse((provider_root / "collection" / "en" / "failed.png.masked.png").exists())
            viewer = (provider_root / "index.html").read_text(encoding="utf-8")
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
                f'<option value="{first_preview_path}">character_mask</option>',
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
