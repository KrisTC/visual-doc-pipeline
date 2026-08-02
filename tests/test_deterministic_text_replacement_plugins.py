"""Behavioural tests owned by deterministic text-replacement test providers."""

from __future__ import annotations

import unittest

from pipeline.text_replacement.models import TextReplacementRequest
from pipeline.text_replacement_plugins.double_character_mask import DoubleCharacterMaskProvider
from pipeline.text_replacement_plugins.half_character_mask import HalfCharacterMaskProvider
from pipeline.text_replacement_plugins.identity import IdentityProvider


class DeterministicTextReplacementProviderTests(unittest.TestCase):
    # Verifies FR-2026-08-02-11.
    def test_identity_preserves_ordinary_text(self) -> None:
        input_text = "Héllo 世界"

        result = IdentityProvider().replace(TextReplacementRequest(input_text, False, "ja", "en"))

        self.assertEqual(input_text, result.text)
        self.assertEqual(1.0, result.confidence)
        self.assertEqual({}, result.extra)

    # Verifies FR-2026-08-02-11.
    def test_double_character_mask_doubles_python_character_length(self) -> None:
        input_text = "Héllo 世界"

        result = DoubleCharacterMaskProvider().replace(
            TextReplacementRequest(input_text, False, "ja", "en")
        )

        self.assertEqual("#" * (2 * len(input_text)), result.text)
        self.assertEqual(2 * len(input_text), len(result.text))

    # Verifies FR-2026-08-02-11.
    def test_half_character_mask_uses_flooring_and_a_minimum_of_one(self) -> None:
        input_text = "Héllo 世界"

        result = HalfCharacterMaskProvider().replace(
            TextReplacementRequest(input_text, False, "ja", "en")
        )
        empty_result = HalfCharacterMaskProvider().replace(
            TextReplacementRequest("", False, "ja", "en")
        )

        self.assertEqual("#" * (len(input_text) // 2), result.text)
        self.assertEqual(1, len(empty_result.text))
        self.assertEqual("#", empty_result.text)

    # Verifies FR-2026-08-02-11.
    def test_providers_preserve_filenames_unchanged(self) -> None:
        input_text = "quarterly report_日本語.pptx"
        request = TextReplacementRequest(input_text, True, "ja", "en")

        for provider in (
            IdentityProvider(),
            DoubleCharacterMaskProvider(),
            HalfCharacterMaskProvider(),
        ):
            with self.subTest(provider=provider.name):
                result = provider.replace(request)
                self.assertEqual(input_text, result.text)
                self.assertEqual(1.0, result.confidence)
                self.assertEqual({}, result.extra)
