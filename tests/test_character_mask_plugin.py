"""Behavioural tests owned by the character-mask text-replacement provider."""

from __future__ import annotations

import unittest

from pipeline.text_replacement.models import TextReplacementRequest
from pipeline.text_replacement_plugins.character_mask import CharacterMaskProvider


class CharacterMaskProviderTests(unittest.TestCase):
    # Verifies FR-2026-08-02-06.
    def test_masks_each_non_filename_character_with_a_hash(self) -> None:
        input_text = "Héllo 世界"

        result = CharacterMaskProvider().replace(
            TextReplacementRequest(input_text, False, "en", "ja")
        )

        self.assertEqual("#" * len(input_text), result.text)
        self.assertEqual(len(input_text), len(result.text))
        self.assertEqual(1.0, result.confidence)
        self.assertEqual({}, result.extra)

    # Verifies FR-2026-08-02-06.
    def test_preserves_filenames_unchanged(self) -> None:
        input_text = "quarterly report_日本語.pptx"

        result = CharacterMaskProvider().replace(
            TextReplacementRequest(input_text, True, "en", "ja")
        )

        self.assertEqual(input_text, result.text)
        self.assertEqual(1.0, result.confidence)
        self.assertEqual({}, result.extra)
