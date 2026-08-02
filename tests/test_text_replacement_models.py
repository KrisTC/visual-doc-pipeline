"""Tests for text-replacement task request and result models."""

from __future__ import annotations

import unittest

from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult


class TextReplacementModelTests(unittest.TestCase):
    # Verifies FR-2026-08-02-06.
    def test_models_preserve_request_and_replacement_fields(self) -> None:
        request = TextReplacementRequest("hello", False, "en", "ja")
        result = TextReplacementResult("こんにちは", 0.99, {"example": "test"})

        self.assertEqual("hello", request.text)
        self.assertFalse(request.is_filename)
        self.assertEqual("en", request.source_language)
        self.assertEqual("ja", request.target_language)
        self.assertEqual("こんにちは", result.text)
        self.assertEqual(0.99, result.confidence)
        self.assertEqual({"example": "test"}, result.extra)

    # Verifies FR-2026-08-02-06.
    def test_models_reject_missing_languages_and_invalid_confidence(self) -> None:
        with self.assertRaises(ValueError):
            TextReplacementRequest("hello", False, " ", "ja")
        with self.assertRaises(ValueError):
            TextReplacementRequest("hello", False, "en", " ")
        with self.assertRaises(ValueError):
            TextReplacementResult("hello", -0.01)
        with self.assertRaises(ValueError):
            TextReplacementResult("hello", 1.01)
