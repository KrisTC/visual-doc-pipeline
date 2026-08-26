"""Synthetic tests for OCR-only raster transparency flattening."""

from __future__ import annotations

import unittest

from PIL import Image

from pipeline.ocr.image_preparation import opaque_rgb_for_ocr


class OcrImagePreparationTests(unittest.TestCase):
    # Verifies FR-2026-08-27-01.
    def test_flattens_palette_byte_transparency_onto_requested_background(self) -> None:
        source = Image.new("P", (2, 1))
        source.putpalette([255, 0, 0, 0, 0, 255] + [0] * 762)
        source.putdata([0, 1])
        source.info["transparency"] = bytes([128, 255])

        ocr_image = opaque_rgb_for_ocr(source, (10, 20, 30))

        self.assertEqual("RGB", ocr_image.mode)
        self.assertEqual([(133, 10, 15), (0, 0, 255)], list(ocr_image.get_flattened_data()))
        self.assertEqual("P", source.mode)
        self.assertEqual(bytes([128, 255]), source.info["transparency"])
        self.assertEqual([0, 1], list(source.get_flattened_data()))

    # Verifies FR-2026-08-27-01.
    def test_defaults_to_white_when_no_document_background_is_available(self) -> None:
        source = Image.new("RGBA", (1, 1), (0, 0, 0, 0))

        self.assertEqual((255, 255, 255), opaque_rgb_for_ocr(source).getpixel((0, 0)))
