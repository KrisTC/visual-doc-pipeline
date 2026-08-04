"""Generic response-shape contract tests for text-replacement providers."""

from __future__ import annotations

import unittest

from pipeline.text_replacement.factory import TextReplacementProviderFactory
from pipeline.text_replacement.models import TextReplacementRequest
from pipeline.text_replacement.provider import TextReplacementProvider


CONTRACT_REQUESTS = (
    TextReplacementRequest("ordinary text", False, "en", "ja"),
    TextReplacementRequest("report.txt", True, "en", "ja"),
)


class TextReplacementProviderContractTests(unittest.TestCase):
    # Verifies FR-2026-08-02-06.
    def test_providers_return_a_valid_response_for_each_contract_request(self) -> None:
        factory = TextReplacementProviderFactory.discover_default_plugins()
        executed_cases = 0

        for provider_name in factory.provider_names:
            if provider_name == "argos_translate":
                self._skip_model_dependent_provider(provider_name)
                continue
            provider = factory.create(provider_name)
            executed_cases += self._test_provider_cases(provider_name, provider)

        self.assertGreater(executed_cases, 0, "No text-replacement provider contract cases ran.")

    def _test_provider_cases(self, provider_name: str, provider: TextReplacementProvider) -> int:
        for request in CONTRACT_REQUESTS:
            with self.subTest(provider=provider_name, request=request):
                result = provider.replace(request)
                self.assertIsInstance(result.text, str)
                self.assertGreaterEqual(result.confidence, 0.0)
                self.assertLessEqual(result.confidence, 1.0)
                self.assertIsInstance(result.extra, dict)
        return len(CONTRACT_REQUESTS)

    def _skip_model_dependent_provider(self, provider_name: str) -> None:
        """Record a visible skip for providers that need downloaded runtime artifacts."""
        with self.subTest(provider=provider_name):
            self.skipTest(
                "Argos Translate needs dynamic model packages; its mocked provider tests cover it."
            )
