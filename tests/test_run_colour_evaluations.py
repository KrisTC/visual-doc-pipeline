"""Synthetic tests for the local text-region-colour HTML evaluator."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image, ImageDraw

from scripts.run_colour_evaluations import evaluate_colour_examples


class ColourEvaluationTests(unittest.TestCase):
    # Verifies FR-2026-08-02-09.
    def test_writes_an_html_page_with_escaped_text_clips_and_colour_swatches(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            source_path = input_root / "nested" / "example.png"
            _write_source_image(source_path)
            _write_result(
                source_path.with_name("example.png.json"),
                status="succeeded",
                text="<text & sample>",
            )

            result = evaluate_colour_examples(input_root, output_root)

            page_path = output_root / "nested" / "example.png.html"
            page = page_path.read_text(encoding="utf-8")
            self.assertEqual(1, result.processed_json_files)
            self.assertEqual(1, result.written_pages)
            self.assertEqual(0, result.skipped_json_files)
            self.assertIn('<td class="text-image"><img alt="Padded text region 1"', page)
            self.assertIn("example.png.text-0001.png", page)
            self.assertIn("&lt;text &amp; sample&gt;", page)
            self.assertIn("#1E1E1E", page)
            self.assertIn("#F5EBC8", page)
            self.assertRegex(page, r"(?:flat|gradient|complex)</code>")
            self.assertLess(page.index("<th>Region</th>"), page.index("<th>Text image</th>"))
            self.assertLess(page.index("<th>Text image</th>"), page.index("<th>Recognized text</th>"))
            self.assertIn(
                'class="text" style="background-color: rgba(245, 235, 200, 1.000); color: rgba(30, 30, 30, 1.000);"',
                page,
            )
            self.assertNotIn(str(source_path), page)

    # Verifies FR-2026-08-02-09.
    def test_skips_invalid_failed_missing_and_escaping_clips_without_stopping_other_pages(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            valid_source = input_root / "valid.png"
            failed_source = input_root / "failed.png"
            invalid_source = input_root / "invalid.png"
            missing_source = input_root / "missing.png"
            escaping_source = input_root / "escaping.png"
            for source_path in (
                valid_source,
                failed_source,
                invalid_source,
                missing_source,
                escaping_source,
            ):
                _write_source_image(source_path)
            _write_result(valid_source.with_name("valid.png.json"), status="succeeded", text="valid")
            _write_result(failed_source.with_name("failed.png.json"), status="failed", text="failed")
            invalid_source.with_name("invalid.png.json").write_text("{", encoding="utf-8")
            _write_result(
                missing_source.with_name("missing.png.json"),
                status="succeeded",
                text="missing",
                write_padded_image=False,
            )
            _write_result(
                escaping_source.with_name("escaping.png.json"),
                status="succeeded",
                text="escaping",
                padded_image_path="../outside.png",
            )

            result = evaluate_colour_examples(input_root, output_root)

            self.assertEqual(5, result.processed_json_files)
            self.assertEqual(1, result.written_pages)
            self.assertEqual(4, result.skipped_json_files)
            self.assertTrue((output_root / "valid.png.html").is_file())
            self.assertFalse((output_root / "failed.png.html").exists())
            self.assertFalse((output_root / "invalid.png.html").exists())
            self.assertFalse((output_root / "missing.png.html").exists())
            self.assertFalse((output_root / "escaping.png.html").exists())


def _write_source_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (80, 60), (245, 235, 200))
    ImageDraw.Draw(image).rectangle((20, 20, 60, 40), fill=(30, 30, 30))
    image.save(path, format="PNG")


def _write_result(
    path: Path,
    *,
    status: str,
    text: str,
    padded_image_path: str | None = None,
    write_padded_image: bool = True,
) -> None:
    source_path = path.with_suffix("")
    padded_path = source_path.with_name(f"{source_path.name}.text-0001.png")
    if padded_image_path is None:
        padded_image_path = padded_path.name
    if write_padded_image:
        Image.new("RGB", (40, 20), (245, 235, 200)).save(padded_path, format="PNG")
    path.write_text(
        json.dumps(
            {
                "status": status,
                "text_items": [
                    {
                        "text": text,
                        "confidence": 0.99,
                        "padded_image_path": padded_image_path,
                        "bounding_polygon": [
                            {"x": 20.0, "y": 20.0},
                            {"x": 60.0, "y": 20.0},
                            {"x": 60.0, "y": 40.0},
                            {"x": 20.0, "y": 40.0},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
