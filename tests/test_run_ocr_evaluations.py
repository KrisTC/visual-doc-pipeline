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
                            PixelPoint(1, 1),
                            PixelPoint(5, 1),
                            PixelPoint(5, 4),
                            PixelPoint(1, 4),
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

    # Verifies FR-2026-08-01-03.
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
            Image.new("RGB", (8, 6), "red").save(successful_image)
            Image.new("RGB", (8, 6), "blue").save(unsupported_image)
            Image.new("RGB", (8, 6), "black").save(failed_image)

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
                    "text_items": [
                        {
                            "text": "detected",
                            "confidence": 0.75,
                            "bounding_polygon": [
                                {"x": 1, "y": 1},
                                {"x": 5, "y": 1},
                                {"x": 5, "y": 4},
                                {"x": 1, "y": 4},
                            ],
                            "extra": {},
                        }
                    ],
                },
                json.loads(success_base.with_name("success.png.json").read_text(encoding="utf-8")),
            )
            masked_path = success_base.with_name("success.png.masked.png")
            self.assertTrue(masked_path.is_file())
            self.assertTrue(success_base.with_name("success.png.text-0001.png").is_file())
            with Image.open(masked_path) as masked_image:
                self.assertEqual((0, 0, 0, 255), masked_image.getpixel((2, 2)))
                self.assertEqual((255, 0, 0, 255), masked_image.getpixel((0, 0)))

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
            self.assertTrue((provider_root / ".input.sha256").is_file())

            second_run = ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory)
            self.assertEqual(1, second_run.skipped_providers)
            self.assertEqual(2, provider.calls)

            stale_mirrored_folder = provider_root / "stale mirrored folder"
            stale_mirrored_folder.mkdir()
            (stale_mirrored_folder / "stale.txt").write_text("stale", encoding="ascii")
            (provider_root / "index.html").unlink()
            third_run = ocr_evaluation.evaluate_ocr_inputs(input_root, output_root, factory)
            self.assertEqual(0, third_run.skipped_providers)
            self.assertEqual(4, provider.calls)
            self.assertFalse(stale_mirrored_folder.exists())


if __name__ == "__main__":
    unittest.main()
