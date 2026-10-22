"""Tests for text-replacement task request and result models."""

from __future__ import annotations

import unittest

from pipeline.text_replacement import (
    BatchLimits,
    TextReplacementItem,
    check_result_length,
    replace_each,
    replace_text,
)
from pipeline.text_replacement.errors import TextReplacementProviderError
from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult
from pipeline.text_replacement_plugins.identity import IdentityProvider


class TextReplacementModelTests(unittest.TestCase):
    # Verifies FR-2026-08-02-06, FR-2026-10-22-01.
    def test_models_preserve_request_and_replacement_fields(self) -> None:
        request = TextReplacementRequest(("hello", "world"), False, "en", "ja")
        item = TextReplacementItem("こんにちは", 0.99, {"example": "test"})
        result = TextReplacementResult((item,))

        self.assertEqual(("hello", "world"), request.texts)
        self.assertFalse(request.is_filename)
        self.assertEqual("en", request.source_language)
        self.assertEqual("ja", request.target_language)
        self.assertEqual("こんにちは", item.text)
        self.assertEqual(0.99, item.confidence)
        self.assertEqual({"example": "test"}, item.extra)
        self.assertEqual((item,), result.items)

    # Verifies FR-2026-08-02-06, FR-2026-10-22-01.
    def test_models_reject_missing_languages_and_invalid_confidence(self) -> None:
        with self.assertRaises(ValueError):
            TextReplacementRequest(("hello",), False, " ", "ja")
        with self.assertRaises(ValueError):
            TextReplacementRequest(("hello",), False, "en", " ")
        with self.assertRaises(ValueError):
            TextReplacementItem("hello", -0.01)
        with self.assertRaises(ValueError):
            TextReplacementItem("hello", 1.01)

    # Verifies FR-2026-10-22-01.
    def test_request_requires_a_non_empty_tuple_of_strings(self) -> None:
        with self.assertRaises(ValueError):
            TextReplacementRequest((), False, "en", "ja")
        with self.assertRaises(ValueError):
            TextReplacementRequest(["hello"], False, "en", "ja")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            TextReplacementRequest(("hello", 3), False, "en", "ja")  # type: ignore[arg-type]

    # Verifies FR-2026-10-22-01.
    def test_an_empty_string_is_a_valid_text(self) -> None:
        request = TextReplacementRequest(("",), False, "en", "ja")

        self.assertEqual(("",), request.texts)

    # Verifies FR-2026-10-22-01.
    def test_batch_limits_default_to_unlimited(self) -> None:
        limits = BatchLimits()

        self.assertIsNone(limits.max_items)
        self.assertIsNone(limits.target_characters)
        self.assertIsNone(limits.max_characters)


class TextReplacementHelperTests(unittest.TestCase):
    # Verifies FR-2026-10-22-01.
    def test_replace_each_returns_one_item_per_text_in_order(self) -> None:
        request = TextReplacementRequest(("a", "bb", "ccc"), False, "en", "ja")

        result = replace_each(request, lambda text: TextReplacementItem(text.upper(), 0.5))

        self.assertEqual(["A", "BB", "CCC"], [item.text for item in result.items])

    # Verifies FR-2026-10-22-01.
    def test_replace_text_is_a_batch_of_one(self) -> None:
        item = replace_text(
            IdentityProvider(), "hello", is_filename=False, source_language="en", target_language="ja"
        )

        self.assertEqual("hello", item.text)
        self.assertEqual(1.0, item.confidence)

    # Verifies FR-2026-10-22-01, SR-2026-10-22-01.
    def test_check_result_length_rejects_a_wrong_count_without_exposing_text(self) -> None:
        result = TextReplacementResult((TextReplacementItem("secret-output", 0.0),))

        with self.assertRaises(TextReplacementProviderError) as raised:
            check_result_length(2, result)

        self.assertIn("1 items for 2 texts", str(raised.exception))
        self.assertNotIn("secret-output", str(raised.exception))
        self.assertIs(result, check_result_length(1, result))

    # Verifies FR-2026-10-22-01.
    def test_replace_text_rejects_a_provider_returning_the_wrong_count(self) -> None:
        class WrongCountProvider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return TextReplacementResult(())

        with self.assertRaises(TextReplacementProviderError):
            replace_text(
                WrongCountProvider(), "hello", is_filename=False, source_language="en", target_language="ja"
            )
