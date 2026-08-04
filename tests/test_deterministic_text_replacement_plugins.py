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
    def test_double_character_mask_doubles_non_whitespace_characters(self) -> None:
        input_text = "Hé\u00a0世界\u3000next\tline\nlast"

        result = DoubleCharacterMaskProvider().replace(
            TextReplacementRequest(input_text, False, "ja", "en")
        )

        self.assertEqual("####\u00a0####\u3000########\t########\n########", result.text)
        self.assertEqual("\u00a0\u3000\t\n", "".join(char for char in result.text if char.isspace()))

    # Verifies FR-2026-08-02-11.
    def test_half_character_mask_halves_each_word_and_preserves_unicode_whitespace(self) -> None:
        input_text = "Héllo\u00a0世界\u3000next\tline\nlast"

        result = HalfCharacterMaskProvider().replace(
            TextReplacementRequest(input_text, False, "ja", "en")
        )
        whitespace_only_result = HalfCharacterMaskProvider().replace(
            TextReplacementRequest(" \u00a0\u3000\t\n", False, "ja", "en")
        )

        self.assertEqual("##\u00a0#\u3000##\t##\n##", result.text)
        self.assertEqual(" \u00a0\u3000\t\n", whitespace_only_result.text)

    # Verifies FR-2026-08-02-11.
    def test_providers_preserve_filenames_unchanged(self) -> None:
        input_text = "quarterly report_日本語.pptx"
        request = TextReplacementRequest(input_text, True, "ja", "en")

        for provider_name, provider in (
            ("identity", IdentityProvider()),
            ("double_character_mask", DoubleCharacterMaskProvider()),
            ("half_character_mask", HalfCharacterMaskProvider()),
        ):
            with self.subTest(provider=provider_name):
                result = provider.replace(request)
                self.assertEqual(input_text, result.text)
                self.assertEqual(1.0, result.confidence)
                self.assertEqual({}, result.extra)
