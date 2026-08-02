"""Synthetic tests for the local text-replacement evaluation command."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image, ImageDraw

from scripts.run_text_replacement_evaluations import (
    DEFAULT_FONT_WEIGHT,
    FONT_WEIGHT_AXIS_TAG,
    _is_confidential_sample_path,
    _load_default_typeface,
    evaluate_text_replacement_examples,
)


class TextReplacementEvaluationTests(unittest.TestCase):
    # Verifies FR-2026-08-02-10.
    def test_writes_provider_columns_and_clipped_replacement_images(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            source_path = input_root / "nested" / "example.png"
            _write_source_and_result(source_path)

            result = evaluate_text_replacement_examples(input_root, output_root)

            page_path = output_root / "nested" / "example.png.html"
            page = page_path.read_text(encoding="utf-8")
            rendered_path = (
                output_root
                / "nested"
                / "example.png.replacement-images"
                / "region-0001.provider-0001.png"
            )
            self.assertEqual(1, result.processed_json_files)
            self.assertEqual(1, result.written_pages)
            self.assertEqual(0, result.skipped_json_files)
            self.assertIn("<h1>Text-replacement evaluation</h1>", page)
            self.assertNotIn("Japanese-to-English", page)
            self.assertIn("<code>nested/example.png.json</code> <span>ko→en</span>", page)
            self.assertIn(
                "table { background: white; border-collapse: collapse; width: auto; }", page
            )
            self.assertIn(
                "<th>Region</th><th>Original text image</th><th>character_mask</th>"
                "<th>double_character_mask</th><th>half_character_mask</th><th>identity</th>",
                page,
            )
            self.assertIn("example.png.text-0001.png", page)
            self.assertIn("region-0001.provider-0001.png", page)
            self.assertEqual(2, page.count("<tr>"))
            self.assertTrue(rendered_path.is_file())
            with Image.open(rendered_path) as rendered:
                self.assertEqual((100, 80), rendered.size)

    # Verifies FR-2026-08-02-10.
    def test_identifies_the_confidential_sample_subtree_for_exclusion(self) -> None:
        confidential_path = (
            Path(__file__).resolve().parents[1]
            / "sample-data"
            / "confidential"
            / "nested"
            / "example.png.json"
        )

        self.assertTrue(_is_confidential_sample_path(confidential_path))

    # Verifies FR-2026-08-02-10.
    def test_loads_the_committed_default_font_at_bold_weight(self) -> None:
        typeface = _load_default_typeface()

        coordinates = typeface.getVariationDesignPosition()
        weight_coordinate = next(
            coordinate for coordinate in coordinates if coordinate.axis == FONT_WEIGHT_AXIS_TAG
        )
        self.assertEqual(DEFAULT_FONT_WEIGHT, weight_coordinate.value)


def _write_source_and_result(source_path: Path) -> None:
    source_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (120, 100), (245, 235, 200))
    ImageDraw.Draw(image).rectangle((30, 30, 90, 70), fill=(30, 30, 30))
    image.save(source_path, format="PNG")
    padded_path = source_path.with_name("example.png.text-0001.png")
    Image.new("RGB", (100, 80), (245, 235, 200)).save(padded_path, format="PNG")
    source_path.with_name("example.png.json").write_text(
        json.dumps(
            {
                "status": "succeeded",
                "source_language": "ko",
                "text_items": [
                    {
                        "text": "日本語",
                        "confidence": 0.99,
                        "padded_image_path": padded_path.name,
                        "bounding_polygon": [
                            {"x": 30.0, "y": 30.0},
                            {"x": 90.0, "y": 30.0},
                            {"x": 90.0, "y": 70.0},
                            {"x": 30.0, "y": 70.0},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
