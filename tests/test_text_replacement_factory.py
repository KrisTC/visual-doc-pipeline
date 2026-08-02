"""Tests for text-replacement provider registration and discovery."""

from __future__ import annotations

import unittest

from pipeline.text_replacement.errors import (
    DuplicateTextReplacementProviderError,
    TextReplacementProviderNotFoundError,
)
from pipeline.text_replacement.factory import TextReplacementProviderFactory
from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult


class _ExampleProvider:
    name = "example"

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        return TextReplacementResult(request.text, 1.0)


class TextReplacementProviderFactoryTests(unittest.TestCase):
    # Verifies FR-2026-08-02-06 and FR-2026-08-02-11.
    def test_discovers_the_built_in_text_replacement_plugins(self) -> None:
        factory = TextReplacementProviderFactory.discover_default_plugins()

        self.assertEqual(
            (
                "character_mask",
                "double_character_mask",
                "half_character_mask",
                "identity",
            ),
            factory.provider_names,
        )

    # Verifies FR-2026-08-02-06.
    def test_rejects_duplicate_names_and_reports_unknown_names(self) -> None:
        factory = TextReplacementProviderFactory()
        factory.register("example", _ExampleProvider)

        with self.assertRaises(DuplicateTextReplacementProviderError):
            factory.register("example", _ExampleProvider)
        with self.assertRaises(TextReplacementProviderNotFoundError):
            factory.create("missing")
