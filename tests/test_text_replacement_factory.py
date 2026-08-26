"""Tests for text-replacement provider registration and discovery."""

from __future__ import annotations

import unittest

from pipeline.text_replacement.errors import TextReplacementProviderNotFoundError
from pipeline.text_replacement.factory import TextReplacementProviderFactory


class TextReplacementProviderFactoryTests(unittest.TestCase):
    # Verifies FR-2026-08-02-06, FR-2026-08-02-11, FR-2026-08-03-01, FR-2026-08-04-12, and FR-2026-08-24-04.
    def test_discovers_built_in_provider_packages_by_their_directory_names(self) -> None:
        factory = TextReplacementProviderFactory.discover_default_plugins()

        self.assertEqual(
            (
                "argos_translate",
                "character_mask",
                "double_character_mask",
                "google_cloud_translate",
                "half_character_mask",
                "identity",
            ),
            factory.provider_names,
        )
        self.assertEqual(
            {
                "argos_translate": "Offline Argos Translate text and filename translation provider.",
                "character_mask": "Deterministic placeholder text-replacement provider.",
                "double_character_mask": (
                    "Deterministic text-replacement provider with double-length hash output."
                ),
                "google_cloud_translate": "Google Cloud Translation Advanced v3 text-replacement provider.",
                "half_character_mask": (
                    "Deterministic text-replacement provider with half-length hash output."
                ),
                "identity": "Deterministic text-replacement provider that preserves ordinary text.",
            },
            dict(factory.provider_descriptions),
        )
        self.assertFalse(hasattr(factory.create("character_mask"), "name"))
        self.assertEqual(
            (
                "argos_translate",
                "character_mask",
                "double_character_mask",
                "half_character_mask",
                "identity",
            ),
            factory.local_evaluation_provider_names,
        )

    # Verifies FR-2026-08-02-06 and FR-2026-08-03-01.
    def test_reports_unknown_names_without_provider_registration(self) -> None:
        factory = TextReplacementProviderFactory()

        with self.assertRaises(TextReplacementProviderNotFoundError):
            factory.create("missing")
