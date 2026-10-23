"""Generic response-shape contract tests for text-replacement providers."""

from __future__ import annotations

import unittest

from pipeline.text_replacement.factory import TextReplacementProviderFactory
from pipeline.text_replacement.models import TextReplacementRequest
from pipeline.text_replacement.provider import TextReplacementProvider


CONTRACT_REQUESTS = (
    TextReplacementRequest(("ordinary text",), False, "en", "ja"),
    TextReplacementRequest(("report.txt",), True, "en", "ja"),
    TextReplacementRequest(("first text", "", "second  text", "third"), False, "en", "ja"),
    TextReplacementRequest(("a.txt", "b.docx"), True, "en", "ja"),
)


class TextReplacementProviderContractTests(unittest.TestCase):
    # Verifies FR-2026-08-02-06, FR-2026-10-22-01.
    def test_providers_return_a_valid_response_for_each_contract_request(self) -> None:
        factory = TextReplacementProviderFactory.discover_default_plugins()
        executed_cases = 0

        for provider_name in factory.provider_names:
            if provider_name in {"argos_translate", "google_cloud_translate"}:
                self._skip_external_provider(provider_name)
                continue
            provider = factory.create(provider_name)
            executed_cases += self._test_provider_cases(provider_name, provider)

        self.assertGreater(executed_cases, 0, "No text-replacement provider contract cases ran.")

    def _test_provider_cases(self, provider_name: str, provider: TextReplacementProvider) -> int:
        for request in CONTRACT_REQUESTS:
            with self.subTest(provider=provider_name, request=request):
                result = provider.replace(request)
                self.assertEqual(len(request.texts), len(result.items))
                for item in result.items:
                    self.assertIsInstance(item.text, str)
                    self.assertGreaterEqual(item.confidence, 0.0)
                    self.assertLessEqual(item.confidence, 1.0)
                    self.assertIsInstance(item.extra, dict)
        return len(CONTRACT_REQUESTS)

    # Verifies FR-2026-10-22-01.
    def test_local_providers_give_each_text_the_same_result_alone_or_in_a_batch(self) -> None:
        factory = TextReplacementProviderFactory.discover_default_plugins()
        texts = ("first text", "", "second  text", "third")

        for provider_name in factory.provider_names:
            if provider_name in {"argos_translate", "google_cloud_translate"}:
                continue
            provider = factory.create(provider_name)
            with self.subTest(provider=provider_name):
                batch = provider.replace(TextReplacementRequest(texts, False, "en", "ja"))
                alone = [
                    provider.replace(TextReplacementRequest((text,), False, "en", "ja")).items[0]
                    for text in texts
                ]
                self.assertEqual(alone, list(batch.items))

    def _skip_external_provider(self, provider_name: str) -> None:
        """Record a visible skip for providers that require external credentials or artifacts."""
        with self.subTest(provider=provider_name):
            reasons = {
                "argos_translate": "Argos Translate needs dynamic model packages; its mocked provider tests cover it.",
                "google_cloud_translate": "Google Cloud Translation requires a remote service; its mocked provider tests cover it.",
            }
            self.skipTest(reasons[provider_name])
