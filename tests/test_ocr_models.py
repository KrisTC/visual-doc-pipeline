"""Tests for OCR task request and result models."""

from __future__ import annotations

import unittest

from PIL import Image

from pipeline.ocr.models import BoundingPolygon, OcrRequest, OcrText, PixelPoint


class OcrModelTests(unittest.TestCase):
    # Verifies FR-2026-08-01-02.
    def test_models_preserve_the_request_and_recognized_text_fields(self) -> None:
        image = Image.new("RGB", (8, 8), "white")
        request = OcrRequest(image=image, language="ja")
        polygon = BoundingPolygon(
            (
                PixelPoint(1.0, 2.0),
                PixelPoint(3.0, 2.0),
                PixelPoint(3.0, 4.0),
                PixelPoint(1.0, 4.0),
            )
        )
        text = OcrText("日本語", 0.99, polygon, {"source": "test"})

        self.assertIs(image, request.image)
        self.assertEqual("ja", request.language)
        self.assertEqual("日本語", text.text)
        self.assertEqual(0.99, text.confidence)
        self.assertEqual(polygon, text.bounding_polygon)
        self.assertEqual({"source": "test"}, text.extra)
