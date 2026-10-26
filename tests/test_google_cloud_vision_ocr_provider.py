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

from pipeline.folder_replacement.bitmap import plan_bitmap
from pipeline.ocr.errors import OcrProviderError
from pipeline.ocr.models import OcrRequest
from pipeline.ocr_plugins import google_cloud_vision
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
            _word("tail", _box(63, 0, 82, 14), break_type="SPACE"),
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
