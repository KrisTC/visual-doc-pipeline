"""Synthetic tests for the Cloud Vision OCR provider's API and data boundary."""

from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
import unittest
from unittest.mock import Mock, patch

from google.cloud import vision_v1
from PIL import Image

from pipeline import provider_cache
from pipeline.folder_replacement.bitmap import plan_bitmap
from pipeline.ocr import OcrProviderFactory
from pipeline.ocr.errors import OcrProviderError
from pipeline.ocr.models import OcrRequest
from pipeline.ocr_plugins import google_cloud_vision
from pipeline.provider_cache import CachingOcrProvider
from scripts import ocr_evaluations


def _word(
    text: str,
    vertices: tuple[tuple[int, int], ...],
    confidence: float = 0.9,
    break_type: str | None = None,
) -> dict[str, object]:
    symbols: list[dict[str, object]] = [{"text": character} for character in text]
    if break_type is not None:
        symbols[-1]["property"] = {"detected_break": {"type_": break_type}}
    return {
        "symbols": symbols,
        "confidence": confidence,
        "bounding_box": {
            "vertices": [{"x": x, "y": y} for x, y in vertices],
        },
    }


def _box(left: int, top: int, right: int, bottom: int) -> tuple[tuple[int, int], ...]:
    return ((left, top), (right, top), (right, bottom), (left, bottom))


def _line_response(*words: dict[str, object]) -> vision_v1.BatchAnnotateImagesResponse:
    return vision_v1.BatchAnnotateImagesResponse(
        {
            "responses": [
                {
                    "full_text_annotation": {
                        "pages": [{"blocks": [{"paragraphs": [{"words": list(words)}]}]}]
                    }
                }
            ]
        }
    )


def _two_surface_image(left: tuple[int, int, int], right: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGB", (100, 40), left)
    image.paste(right, (42, 0, 100, 40))
    return image


def _response_with_paragraph() -> vision_v1.BatchAnnotateImagesResponse:
    return vision_v1.BatchAnnotateImagesResponse(
        {
            "responses": [
                {
                    "full_text_annotation": {
                        "pages": [
                            {
                                "blocks": [
                                    {
                                        "paragraphs": [
                                            {
                                                "confidence": 0.875,
                                                "bounding_box": {
                                                    "vertices": [
                                                        {"x": 2, "y": 3},
                                                        {"x": 15, "y": 3},
                                                        {"x": 15, "y": 13},
                                                        {"x": 2, "y": 13},
                                                    ]
                                                },
                                                "words": [
                                                    _word("Hi", _box(2, 3, 12, 13), 0.875),
                                                    _word("!", _box(13, 3, 15, 13), 0.75),
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                }
            ]
        }
    )


class GoogleCloudVisionOcrProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.credential_path = Path(self.temporary_directory.name) / "synthetic-credential.json"
        self.credential_path.write_text(
            json.dumps({"type": "service_account", "project_id": "credential-project"}),
            encoding="utf-8",
        )

    def _environment(self, **overrides: str) -> dict[str, str]:
        return {
            "GOOGLE_APPLICATION_CREDENTIALS": str(self.credential_path),
            **overrides,
        }

    # Verifies FR-2026-10-24-03.
    def test_groups_japanese_words_and_splits_at_detected_line_breaks(self) -> None:
        words = [
            _word("猫", _box(1, 1, 5, 10), 0.92),
            _word("です。", _box(5, 1, 18, 10), 0.92, "LINE_BREAK"),
            _word("A", _box(20, 1, 24, 10), 0.8, "SPACE"),
            _word("B", _box(27, 1, 31, 10), 0.8),
            _word("C", _box(35, 1, 39, 10), 0.7),
        ]
        words[3]["property"] = {"detected_break": {"type_": "EOL_SURE_SPACE"}}
        response = vision_v1.BatchAnnotateImagesResponse(
            {
                "responses": [
                    {
                        "full_text_annotation": {
                            "pages": [{"blocks": [{"paragraphs": [{"words": words}]}]}]
                        }
                    }
                ]
            }
        )

        result = google_cloud_vision._parse_response(response)

        self.assertEqual(["猫です。", "A B", "C"], [item.text for item in result.text_items])
        self.assertAlmostEqual(0.92, result.text_items[0].confidence)
        self.assertAlmostEqual(0.8, result.text_items[1].confidence)
        self.assertEqual((1.0, 1.0), (
            result.text_items[0].bounding_polygon.vertices[0].x,
            result.text_items[0].bounding_polygon.vertices[0].y,
        ))

    # Verifies FR-2026-10-24-03.
    def test_geometry_separates_indented_lines_and_distant_text_without_breaks(self) -> None:
        words = [
            _word("•", _box(1, 1, 5, 11), 0.9, "SPACE"),
            _word("First", _box(9, 1, 34, 11), 0.8, "SPACE"),
            _word("item.", _box(38, 1, 65, 11), 0.9),
            _word("Second", _box(20, 22, 56, 32), 0.85, "SPACE"),
            _word("line", _box(60, 22, 80, 32), 0.9),
            _word("Column", _box(150, 22, 180, 32), 0.7),
        ]
        response = vision_v1.BatchAnnotateImagesResponse(
            {
                "responses": [
                    {
                        "full_text_annotation": {
                            "pages": [{"blocks": [{"paragraphs": [{"words": words}]}]}]
                        }
                    }
                ]
            }
        )

        result = google_cloud_vision._parse_response(response)

        self.assertEqual(
            ["• First item.", "Second line", "Column"],
            [item.text for item in result.text_items],
        )
        self.assertEqual(
            [(1.0, 1.0), (65.0, 1.0), (65.0, 11.0), (1.0, 11.0)],
            [
                (point.x, point.y)
                for point in result.text_items[0].bounding_polygon.vertices
            ],
        )

    # Verifies FR-2026-10-24-03.
    def test_wide_spacing_separates_neighboring_table_cells(self) -> None:
        words = [
            _word("12", _box(2, 2, 25, 14), break_type="SPACE"),
            _word("kg", _box(29, 2, 42, 14), break_type="SPACE"),
            _word("34", _box(62, 2, 86, 14)),
        ]
        response = vision_v1.BatchAnnotateImagesResponse(
            {
                "responses": [
                    {
                        "full_text_annotation": {
                            "pages": [{"blocks": [{"paragraphs": [{"words": words}]}]}]
                        }
                    }
                ]
            }
        )

        result = google_cloud_vision._parse_response(response)

        self.assertEqual(["12 kg", "34"], [item.text for item in result.text_items])
        self.assertEqual(42.0, result.text_items[0].bounding_polygon.vertices[1].x)
        self.assertEqual(62.0, result.text_items[1].bounding_polygon.vertices[0].x)

    # Verifies FR-2026-10-24-03.
    def test_rotated_word_boxes_form_one_rotated_line(self) -> None:
        words = [
            _word("A", ((30, 10), (30, 20), (20, 20), (20, 10)), 0.8, "SPACE"),
            _word("B", ((30, 24), (30, 34), (20, 34), (20, 24)), 0.9),
        ]
        response = vision_v1.BatchAnnotateImagesResponse(
            {
                "responses": [
                    {
                        "full_text_annotation": {
                            "pages": [{"blocks": [{"paragraphs": [{"words": words}]}]}]
                        }
                    }
                ]
            }
        )

        result = google_cloud_vision._parse_response(response)

        self.assertEqual(["A B"], [item.text for item in result.text_items])
        self.assertEqual(
            [(30.0, 10.0), (30.0, 34.0), (20.0, 34.0), (20.0, 10.0)],
            [(point.x, point.y) for point in result.text_items[0].bounding_polygon.vertices],
        )

    # Verifies FR-2026-10-24-03.
    def test_two_sentences_on_one_visual_line_remain_one_region(self) -> None:
        response = vision_v1.BatchAnnotateImagesResponse(
            {
                "responses": [
                    {
                        "full_text_annotation": {
                            "pages": [
                                {
                                    "blocks": [
                                        {
                                            "paragraphs": [
                                                {
                                                    "words": [
                                                        _word(
                                                            "One.",
                                                            _box(1, 1, 20, 11),
                                                            break_type="SPACE",
                                                        ),
                                                        _word("Two.", _box(24, 1, 44, 11)),
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ]
            }
        )

        result = google_cloud_vision._parse_response(response)

        self.assertEqual(["One. Two."], [item.text for item in result.text_items])

    # Verifies FR-2026-10-24-03.
    def test_distinct_text_size_splits_adjacent_regions_on_one_baseline(self) -> None:
        words = [
            _word("•", _box(1, 7, 5, 11), break_type="SPACE"),
            _word("Alpha", _box(8, 2, 32, 14)),
            _word(",", _box(33, 8, 35, 13), break_type="SPACE"),
            _word("beta", _box(39, 1, 59, 14), break_type="SPACE"),
            _word("tail", _box(63, 1, 82, 14), break_type="SPACE"),
            _word("Title", _box(86, -1, 130, 17), break_type="SPACE"),
            _word("note", _box(134, 2, 155, 14)),
        ]
        response = vision_v1.BatchAnnotateImagesResponse(
            {
                "responses": [
                    {
                        "full_text_annotation": {
                            "pages": [{"blocks": [{"paragraphs": [{"words": words}]}]}]
                        }
                    }
                ]
            }
        )

        result = google_cloud_vision._parse_response(response)

        self.assertEqual(
            ["• Alpha, beta tail", "Title", "note"],
            [item.text for item in result.text_items],
        )
        self.assertEqual(
            [(86.0, -1.0), (130.0, -1.0), (130.0, 17.0), (86.0, 17.0)],
            [(point.x, point.y) for point in result.text_items[1].bounding_polygon.vertices],
        )

    # Verifies FR-2026-10-24-03.
    def test_moderately_larger_adjacent_text_splits_but_minor_variation_does_not(self) -> None:
        words = [
            _word("small", _box(0, 0, 40, 20), break_type="SPACE"),
            _word("same", _box(44, 0, 84, 21), break_type="SPACE"),
            _word("big", _box(88, -3, 128, 24)),
        ]
        response = vision_v1.BatchAnnotateImagesResponse(
            {
                "responses": [
                    {
                        "full_text_annotation": {
                            "pages": [{"blocks": [{"paragraphs": [{"words": words}]}]}]
                        }
                    }
                ]
            }
        )

        result = google_cloud_vision._parse_response(response)

        self.assertEqual(["small same", "big"], [item.text for item in result.text_items])

    # Verifies FR-2026-10-27-03.
    def test_extra_records_original_words_and_grouping_decisions(self) -> None:
        words = [
            _word("One", _box(0, 0, 30, 10), break_type="SPACE"),
            _word("two", _box(34, 0, 64, 10)),
            _word("BIG", _box(68, -4, 120, 16)),
        ]
        response = vision_v1.BatchAnnotateImagesResponse(
            {
                "responses": [
                    {
                        "full_text_annotation": {
                            "pages": [{"blocks": [{"paragraphs": [{"words": words}]}]}]
                        }
                    }
                ]
            }
        )

        result = google_cloud_vision._parse_response(response)

        self.assertEqual(["One two", "BIG"], [item.text for item in result.text_items])
        first = cast(dict[str, dict[str, object]], result.text_items[0].extra)["google_cloud_vision"]
        second = cast(dict[str, dict[str, object]], result.text_items[1].extra)["google_cloud_vision"]
        first_words = cast(list[dict[str, object]], first["words"])
        self.assertEqual(["One ", "two"], [word["text"] for word in first_words])
        self.assertEqual(
            [[0.0, 0.0], [30.0, 0.0], [30.0, 10.0], [0.0, 10.0]], first_words[0]["polygon"]
        )
        self.assertNotIn("joined_measurements", first_words[0])
        joined = cast(dict[str, float], first_words[1]["joined_measurements"])
        self.assertEqual({"direction_alignment", "baseline_offset_ratio", "gap_ratio", "character_size_ratio"}, set(joined))
        self.assertEqual(
            {"reason": "paragraph_start", "measurements": {}}, first["region_started_by"]
        )
        started_by = cast(dict[str, object], second["region_started_by"])
        self.assertEqual("character_size", started_by["reason"])
        self.assertGreaterEqual(
            cast(dict[str, float], started_by["measurements"])["character_size_ratio"],
            google_cloud_vision._CHARACTER_SIZE_SPLIT_RATIO,
        )
        self.assertEqual(
            google_cloud_vision._CHARACTER_SIZE_SPLIT_RATIO,
            cast(dict[str, float], first["thresholds"])["character_size_split_ratio"],
        )

    # Verifies FR-2026-10-27-03.
    def test_extra_records_symbol_boxes_when_supplied(self) -> None:
        word = _word("ab", _box(0, 0, 20, 10))
        symbols = cast(list[dict[str, object]], word["symbols"])
        symbols[0]["bounding_box"] = {"vertices": [{"x": 0, "y": 1}, {"x": 8, "y": 1}, {"x": 8, "y": 9}, {"x": 0, "y": 9}]}
        response = vision_v1.BatchAnnotateImagesResponse(
            {
                "responses": [
                    {
                        "full_text_annotation": {
                            "pages": [{"blocks": [{"paragraphs": [{"words": [word]}]}]}]
                        }
                    }
                ]
            }
        )

        result = google_cloud_vision._parse_response(response)

        extra = cast(dict[str, dict[str, object]], result.text_items[0].extra)["google_cloud_vision"]
        recorded = cast(list[dict[str, object]], extra["words"])[0]["symbols"]
        self.assertEqual(
            [
                {"text": "a", "polygon": [[0.0, 1.0], [8.0, 1.0], [8.0, 9.0], [0.0, 9.0]]},
                {"text": "b"},
            ],
            recorded,
        )

    # Verifies FR-2026-10-27-03.
    def test_extra_survives_json_and_provider_cache_round_trip(self) -> None:
        words = [_word("One", _box(0, 0, 30, 10), break_type="SPACE"), _word("two", _box(34, 0, 64, 10))]
        response = vision_v1.BatchAnnotateImagesResponse(
            {
                "responses": [
                    {
                        "full_text_annotation": {
                            "pages": [{"blocks": [{"paragraphs": [{"words": words}]}]}]
                        }
                    }
                ]
            }
        )
        result = google_cloud_vision._parse_response(response)

        restored = provider_cache._ocr_result_from_payload(
            json.loads(json.dumps(provider_cache._ocr_result_payload(result)))
        )

        self.assertEqual(result, restored)

    # Verifies FR-2026-10-27-03.
    def test_line_break_split_reason_has_no_geometry_measurements(self) -> None:
        words = [
            _word("One", _box(0, 0, 30, 10), break_type="LINE_BREAK"),
            _word("Two", _box(0, 14, 30, 24)),
        ]
        response = vision_v1.BatchAnnotateImagesResponse(
            {
                "responses": [
                    {
                        "full_text_annotation": {
                            "pages": [{"blocks": [{"paragraphs": [{"words": words}]}]}]
                        }
                    }
                ]
            }
        )

        result = google_cloud_vision._parse_response(response)

        second = cast(dict[str, dict[str, object]], result.text_items[1].extra)["google_cloud_vision"]
        self.assertEqual(
            {"reason": "previous_word_ends_line", "measurements": {}}, second["region_started_by"]
        )

    # Verifies FR-2026-10-27-04.
    def test_words_on_different_backgrounds_are_not_joined(self) -> None:
        response = _line_response(
            _word("left", _box(0, 10, 40, 22), break_type="SPACE"),
            _word("right", _box(44, 10, 84, 22)),
        )

        result = google_cloud_vision._parse_response(response, _two_surface_image((255, 255, 255), (20, 40, 160)))

        self.assertEqual(["left", "right"], [item.text for item in result.text_items])
        extra = cast(dict[str, dict[str, object]], result.text_items[1].extra)["google_cloud_vision"]
        started_by = cast(dict[str, object], extra["region_started_by"])
        self.assertEqual("background_colour", started_by["reason"])
        measurements = cast(dict[str, float], started_by["measurements"])
        self.assertGreaterEqual(
            measurements["background_colour_difference"], google_cloud_vision._SURFACE_DIFFERENCE_SPLIT
        )
        self.assertEqual(
            google_cloud_vision._SURFACE_DIFFERENCE_SPLIT,
            cast(dict[str, float], extra["thresholds"])["surface_difference_split"],
        )

    # Verifies FR-2026-10-27-04.
    def test_words_on_the_same_background_join_and_record_the_difference(self) -> None:
        response = _line_response(
            _word("left", _box(0, 10, 40, 22), break_type="SPACE"),
            _word("right", _box(44, 10, 84, 22)),
        )

        result = google_cloud_vision._parse_response(response, _two_surface_image((255, 255, 255), (250, 250, 250)))

        self.assertEqual(["left right"], [item.text for item in result.text_items])
        extra = cast(dict[str, dict[str, object]], result.text_items[0].extra)["google_cloud_vision"]
        joined = cast(dict[str, float], cast(list[dict[str, object]], extra["words"])[1]["joined_measurements"])
        self.assertLess(joined["background_colour_difference"], google_cloud_vision._SURFACE_DIFFERENCE_SPLIT)

    # Verifies FR-2026-10-27-04.
    def test_text_glyphs_inside_the_boxes_do_not_affect_the_background_comparison(self) -> None:
        image = _two_surface_image((255, 255, 255), (255, 255, 255))
        image.paste((0, 0, 0), (2, 12, 38, 20))
        image.paste((0, 0, 0), (46, 12, 82, 20))
        response = _line_response(
            _word("left", _box(0, 10, 40, 22), break_type="SPACE"),
            _word("right", _box(44, 10, 84, 22)),
        )

        result = google_cloud_vision._parse_response(response, image)

        self.assertEqual(["left right"], [item.text for item in result.text_items])

    # Verifies FR-2026-10-27-04.
    def test_without_an_image_the_background_rule_is_skipped(self) -> None:
        response = _line_response(
            _word("left", _box(0, 10, 40, 22), break_type="SPACE"),
            _word("right", _box(44, 10, 84, 22)),
        )

        result = google_cloud_vision._parse_response(response)

        self.assertEqual(["left right"], [item.text for item in result.text_items])
        extra = cast(dict[str, dict[str, object]], result.text_items[0].extra)["google_cloud_vision"]
        joined = cast(dict[str, float], cast(list[dict[str, object]], extra["words"])[1]["joined_measurements"])
        self.assertNotIn("background_colour_difference", joined)

    # Verifies FR-2026-10-27-04.
    def test_background_rule_is_not_evaluated_when_an_earlier_rule_splits(self) -> None:
        response = _line_response(
            _word("left", _box(0, 10, 40, 22), break_type="SPACE"),
            _word("right", _box(70, 10, 84, 22)),
        )

        result = google_cloud_vision._parse_response(response, _two_surface_image((255, 255, 255), (20, 40, 160)))

        extra = cast(dict[str, dict[str, object]], result.text_items[1].extra)["google_cloud_vision"]
        started_by = cast(dict[str, object], extra["region_started_by"])
        self.assertEqual("word_gap", started_by["reason"])
        self.assertNotIn("background_colour_difference", cast(dict[str, float], started_by["measurements"]))

    # Verifies FR-2026-10-27-04.
    def test_background_rule_is_skipped_when_word_boxes_overlap(self) -> None:
        response = _line_response(
            _word("left", _box(0, 10, 44, 22), break_type="SPACE"),
            _word("right", _box(40, 10, 84, 22)),
        )

        result = google_cloud_vision._parse_response(response, _two_surface_image((255, 255, 255), (20, 40, 160)))

        self.assertEqual(["left right"], [item.text for item in result.text_items])
        extra = cast(dict[str, dict[str, object]], result.text_items[0].extra)["google_cloud_vision"]
        joined = cast(dict[str, float], cast(list[dict[str, object]], extra["words"])[1]["joined_measurements"])
        self.assertNotIn("background_colour_difference", joined)

    # Verifies FR-2026-10-27-04.
    def test_recognize_passes_the_prepared_image_to_the_background_rule(self) -> None:
        response = _line_response(
            _word("left", _box(0, 10, 40, 22), break_type="SPACE"),
            _word("right", _box(44, 10, 84, 22)),
        )
        client = Mock()
        client.batch_annotate_images.return_value = response
        factory = Mock(return_value=client)
        module = Mock(ImageAnnotatorClient=factory)

        with (
            patch.dict(os.environ, self._environment(), clear=True),
            patch.object(google_cloud_vision, "import_module", return_value=module),
        ):
            result = google_cloud_vision.GoogleCloudVisionProvider().recognize(
                OcrRequest(_two_surface_image((255, 255, 255), (20, 40, 160)), "ja")
            )

        self.assertEqual(["left", "right"], [item.text for item in result.text_items])

    # Verifies FR-2026-08-27-10.
    def test_cache_identity_tracks_grouping_parameters(self) -> None:
        original = google_cloud_vision.cache_identity()

        with patch.object(google_cloud_vision, "_CHARACTER_SIZE_SPLIT_RATIO", 1.2):
            changed = google_cloud_vision.cache_identity()

        with patch.object(google_cloud_vision, "_SURFACE_DIFFERENCE_SPLIT", 50.0):
            surface_changed = google_cloud_vision.cache_identity()

        self.assertNotEqual(original, changed)
        self.assertNotEqual(original, surface_changed)
        self.assertEqual(original, google_cloud_vision.cache_identity())
        self.assertNotIn("\n", original)

    # Verifies FR-2026-08-27-10.
    def test_factory_caches_provider_only_when_cache_is_enabled(self) -> None:
        factory = OcrProviderFactory.discover_default_plugins()

        with patch.dict(os.environ, {"PIPELINE_PLUGIN_CACHE": "1"}):
            enabled = factory.create("google_cloud_vision")
        with patch.dict(os.environ, {}, clear=True):
            disabled = factory.create("google_cloud_vision")

        self.assertIsInstance(enabled, CachingOcrProvider)
        self.assertNotIsInstance(disabled, CachingOcrProvider)

    # Verifies FR-2026-10-24-03.
    def test_evaluation_artifact_version_changes_with_grouping_parameters(self) -> None:
        original = ocr_evaluations._artifact_format_version("google_cloud_vision")

        with patch.object(google_cloud_vision, "_CHARACTER_SIZE_SPLIT_RATIO", 1.2):
            changed = ocr_evaluations._artifact_format_version("google_cloud_vision")

        self.assertNotEqual(original, changed)

    # Verifies FR-2026-10-24-01 and SR-2026-10-24-01.
    def test_sends_inline_image_to_eu_without_language_hint_and_maps_line(self) -> None:
        client = Mock()
        client.batch_annotate_images.return_value = _response_with_paragraph()
        module = Mock()
        module.ImageAnnotatorClient.return_value = client
        image = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
        image.putpixel((0, 0), (255, 0, 0, 255))
        image.info["exif"] = b"synthetic-image-metadata"
        with (
            patch.dict(os.environ, self._environment(GOOGLE_CLOUD_PROJECT="override-project"), clear=True),
            patch.object(google_cloud_vision, "import_module", return_value=module),
            patch(
                "pipeline.folder_replacement.bitmap.estimate_replacement_colours",
                side_effect=lambda _image, regions, *_: [Mock() for _ in regions],
            ),
        ):
            provider = google_cloud_vision.GoogleCloudVisionProvider()
            first = provider.recognize(OcrRequest(image, "en"))
            second = provider.recognize(OcrRequest(image, "en"))
            planned = plan_bitmap(image, provider, "en")

        self.assertEqual(first, second)
        self.assertEqual(("Hi!",), tuple(planned.units())[0].texts)
        self.assertEqual(["Hi!"], [item.text for item in first.text_items])
        evaluation_image = ocr_evaluations.EvaluationImage(
            "en", Path("input/en/image.png"), Path("en/image.png")
        )
        evaluation_payload = ocr_evaluations._successful_payload(
            first, image, Path(self.temporary_directory.name) / "output", evaluation_image
        )
        self.assertEqual(
            ["Hi!"],
            [
                item["text"]
                for item in cast(list[dict[str, object]], evaluation_payload["text_items"])
            ],
        )
        self.assertAlmostEqual((0.875 * 2 + 0.75) / 3, first.text_items[0].confidence)
        self.assertEqual(
            [(2.0, 3.0), (15.0, 3.0), (15.0, 13.0), (2.0, 13.0)],
            [(point.x, point.y) for point in first.text_items[0].bounding_polygon.vertices],
        )
        module.ImageAnnotatorClient.assert_called_once_with(
            client_options={"api_endpoint": "eu-vision.googleapis.com"}
        )
        api_request = client.batch_annotate_images.call_args.kwargs["request"]
        self.assertEqual("projects/override-project/locations/eu", api_request["parent"])
        self.assertEqual("DOCUMENT_TEXT_DETECTION", api_request["requests"][0]["features"][0]["type_"])
        self.assertEqual({"parent", "requests"}, set(api_request))
        self.assertEqual({"image", "features"}, set(api_request["requests"][0]))
        with Image.open(BytesIO(api_request["requests"][0]["image"]["content"])) as sent_image:
            self.assertEqual((20, 20), sent_image.size)
            self.assertEqual((255, 0, 0), sent_image.getpixel((0, 0)))
            self.assertEqual((255, 255, 255), sent_image.getpixel((1, 1)))
            self.assertNotIn("exif", sent_image.info)

    # Verifies FR-2026-10-24-01 and SR-2026-10-24-01.
    def test_rejects_unapproved_location_and_oversized_image_before_api_call(self) -> None:
        module = Mock()
        client = module.ImageAnnotatorClient.return_value
        with (
            patch.dict(
                os.environ,
                self._environment(GOOGLE_CLOUD_TRANSLATION_LOCATION="us-central1"),
                clear=True,
            ),
            patch.object(google_cloud_vision, "import_module", return_value=module),
        ):
            with self.assertRaisesRegex(OcrProviderError, "European location"):
                google_cloud_vision.GoogleCloudVisionProvider().recognize(
                    OcrRequest(Image.new("RGB", (2, 2)), "en")
                )
        module.ImageAnnotatorClient.assert_not_called()

        oversized_image = Mock(spec=Image.Image)
        oversized_image.size = (75_000_001, 1)
        with (
            patch.dict(os.environ, self._environment(), clear=True),
            patch.object(google_cloud_vision, "import_module", return_value=module),
        ):
            with self.assertRaisesRegex(OcrProviderError, "dimensions exceed"):
                google_cloud_vision.GoogleCloudVisionProvider().recognize(
                    OcrRequest(oversized_image, "en")
                )
        client.batch_annotate_images.assert_not_called()

    # Verifies SR-2026-10-24-01.
    def test_reuses_translation_location_override_and_credential_project(self) -> None:
        client = Mock()
        client.batch_annotate_images.return_value = vision_v1.BatchAnnotateImagesResponse(
            {"responses": [{}]}
        )
        module = Mock()
        module.ImageAnnotatorClient.return_value = client
        with (
            patch.dict(
                os.environ,
                self._environment(GOOGLE_CLOUD_TRANSLATION_LOCATION="europe-west3"),
                clear=True,
            ),
            patch.object(google_cloud_vision, "import_module", return_value=module),
        ):
            google_cloud_vision.GoogleCloudVisionProvider().recognize(
                OcrRequest(Image.new("RGB", (2, 2)), "ja")
            )
        api_request = client.batch_annotate_images.call_args.kwargs["request"]
        self.assertEqual("projects/credential-project/locations/eu", api_request["parent"])
        self.assertNotIn("image_context", api_request["requests"][0])

        with (
            patch.dict(os.environ, {"GOOGLE_API_KEY": "synthetic-key"}, clear=True),
            patch.object(google_cloud_vision, "import_module", return_value=module),
        ):
            with self.assertRaisesRegex(OcrProviderError, "service-account credentials"):
                google_cloud_vision.GoogleCloudVisionProvider().recognize(
                    OcrRequest(Image.new("RGB", (2, 2)), "en")
                )
        module.ImageAnnotatorClient.assert_called_once()

    # Verifies FR-2026-10-24-01 and SR-2026-10-24-01.
    def test_rejects_oversized_payload_and_malformed_response(self) -> None:
        client = Mock()
        malformed_paragraph = {
            "words": [
                {
                    "symbols": [{"text": "x"}],
                    "confidence": 0.5,
                    "bounding_box": {"vertices": [{"x": 1, "y": 1}]},
                }
            ],
        }
        client.batch_annotate_images.return_value = vision_v1.BatchAnnotateImagesResponse(
            {
                "responses": [
                    {
                        "full_text_annotation": {
                            "pages": [
                                {
                                    "blocks": [
                                        {"paragraphs": [malformed_paragraph]}
                                    ]
                                }
                            ]
                        }
                    }
                ]
            }
        )
        module = Mock()
        module.ImageAnnotatorClient.return_value = client
        with (
            patch.dict(os.environ, self._environment(), clear=True),
            patch.object(google_cloud_vision, "import_module", return_value=module),
        ):
            provider = google_cloud_vision.GoogleCloudVisionProvider()
            with patch.object(google_cloud_vision, "_MAXIMUM_IMAGE_BYTES", 8):
                with self.assertRaisesRegex(OcrProviderError, "request size limit"):
                    provider.recognize(OcrRequest(Image.new("RGB", (2, 2)), "en"))
            client.batch_annotate_images.assert_not_called()
            with self.assertRaisesRegex(OcrProviderError, "malformed OCR data"):
                provider.recognize(OcrRequest(Image.new("RGB", (2, 2)), "en"))

    # Verifies FR-2026-10-24-01 and SR-2026-10-24-01.
    def test_valid_no_text_result_and_safe_api_failure(self) -> None:
        client = Mock()
        client.batch_annotate_images.return_value = vision_v1.BatchAnnotateImagesResponse(
            {"responses": [{}]}
        )
        module = Mock()
        module.ImageAnnotatorClient.return_value = client
        with (
            patch.dict(os.environ, self._environment(), clear=True),
            patch.object(google_cloud_vision, "import_module", return_value=module),
        ):
            provider = google_cloud_vision.GoogleCloudVisionProvider()
            self.assertEqual(
                (), provider.recognize(OcrRequest(Image.new("RGB", (2, 2)), "en")).text_items
            )
            client.batch_annotate_images.side_effect = RuntimeError("secret API response")
            with self.assertRaises(OcrProviderError) as raised:
                provider.recognize(OcrRequest(Image.new("RGB", (2, 2)), "en"))
        self.assertNotIn("secret", str(raised.exception))
        self.assertFalse(provider.supports_local_contract_test)
