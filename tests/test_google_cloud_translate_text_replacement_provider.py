"""Behavioural tests for the Google Cloud Translation text-replacement provider."""

from __future__ import annotations

import json
import os
import unittest
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import Mock, patch

from pipeline.text_replacement.errors import TextReplacementProviderError
from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult
from pipeline.text_replacement_plugins.google_cloud_translate import (
    GoogleCloudTranslateProvider,
    _Configuration,
    _GoogleModules,
    _TranslationClient,
)


@dataclass(frozen=True, slots=True)
class _FakeTranslation:
    translated_text: str


@dataclass(frozen=True, slots=True)
class _FakeResponse:
    translations: Sequence[_FakeTranslation]


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.requests: list[Mapping[str, object]] = []

    def translate_text(self, *, request: Mapping[str, object]) -> _FakeResponse:
        self.requests.append(request)
        return self.response


class _FakeClientFactory:
    def __init__(self, response: _FakeResponse) -> None:
        self.client = _FakeClient(response)
        self.endpoints: list[str] = []

    def create_client(self, endpoint: str) -> _FakeClient:
        self.endpoints.append(endpoint)
        return self.client


class GoogleCloudTranslateProviderTests(unittest.TestCase):
    # Verifies FR-2026-08-24-04.
    def test_translates_text_through_the_global_endpoint(self) -> None:
        client_factory = _FakeClientFactory(_FakeResponse([_FakeTranslation("Hola")]))

        result = self._replace(
            TextReplacementRequest("Hello", False, "en-GB", "es-MX"), client_factory
        )

        self.assertEqual("Hola", result.text)
        self.assertEqual(0.0, result.confidence)
        self.assertEqual(["translate.googleapis.com"], client_factory.endpoints)
        self.assertEqual(
            "projects/synthetic-project/locations/global",
            client_factory.client.requests[0]["parent"],
        )
        self.assertEqual(["Hello"], client_factory.client.requests[0]["contents"])
        self.assertEqual("en-GB", client_factory.client.requests[0]["source_language_code"])
        self.assertEqual("es-MX", client_factory.client.requests[0]["target_language_code"])

    # Verifies FR-2026-08-24-04.
    def test_translates_a_filename_stem_through_the_eu_endpoint(self) -> None:
        client_factory = _FakeClientFactory(_FakeResponse([_FakeTranslation("rapport")]))

        result = self._replace(
            TextReplacementRequest("report.docx", True, "en", "fr"),
            client_factory,
            {"GOOGLE_CLOUD_TRANSLATION_LOCATION": "europe-west1"},
        )

        self.assertEqual("rapport.docx", result.text)
        self.assertEqual(["translate-eu.googleapis.com"], client_factory.endpoints)
        self.assertEqual(
            "projects/synthetic-project/locations/europe-west1",
            client_factory.client.requests[0]["parent"],
        )
        self.assertEqual(["report"], client_factory.client.requests[0]["contents"])

    # Verifies FR-2026-08-24-04.
    def test_returns_empty_and_same_language_requests_without_loading_the_client(self) -> None:
        provider = GoogleCloudTranslateProvider()
        with (
            patch(
                "pipeline.text_replacement_plugins.google_cloud_translate._load_google_modules"
            ) as load_modules,
            patch(
                "pipeline.text_replacement_plugins.google_cloud_translate._load_configuration"
            ) as load_configuration,
            patch.dict(os.environ, {}, clear=True),
        ):
            empty_result = provider.replace(TextReplacementRequest("", False, "en", "fr"))
            same_language_result = provider.replace(
                TextReplacementRequest("Hello", False, "EN", "en")
            )

        self.assertEqual("", empty_result.text)
        self.assertEqual("Hello", same_language_result.text)
        load_modules.assert_not_called()
        load_configuration.assert_not_called()

    # Verifies FR-2026-08-28-01.
    def test_reuses_one_configuration_and_client_for_multiple_replacements(self) -> None:
        client_factory = _FakeClientFactory(
            _FakeResponse([_FakeTranslation("translated")])
        )
        configuration = _Configuration("synthetic-project", "global", "translate.googleapis.com")
        modules = _GoogleModules(cast(Callable[[str], _TranslationClient], client_factory.create_client))
        provider = GoogleCloudTranslateProvider()
        with (
            patch(
                "pipeline.text_replacement_plugins.google_cloud_translate._load_configuration",
                return_value=configuration,
            ) as load_configuration,
            patch(
                "pipeline.text_replacement_plugins.google_cloud_translate._load_google_modules",
                return_value=modules,
            ) as load_modules,
        ):
            provider.replace(TextReplacementRequest("first", False, "en", "fr"))
            provider.replace(TextReplacementRequest("second", False, "en", "fr"))

        load_configuration.assert_called_once_with()
        load_modules.assert_called_once_with()
        self.assertEqual(["translate.googleapis.com"], client_factory.endpoints)
        self.assertEqual(2, len(client_factory.client.requests))

    # Verifies FR-2026-08-28-01.
    def test_retries_client_initialization_after_construction_failure(self) -> None:
        configuration = _Configuration("synthetic-project", "global", "translate.googleapis.com")
        client = _FakeClient(_FakeResponse([_FakeTranslation("translated")]))
        create_client = Mock(side_effect=[RuntimeError("temporary"), client])
        modules = _GoogleModules(cast(Callable[[str], _TranslationClient], create_client))
        provider = GoogleCloudTranslateProvider()
        request = TextReplacementRequest("text", False, "en", "fr")
        with (
            patch(
                "pipeline.text_replacement_plugins.google_cloud_translate._load_configuration",
                return_value=configuration,
            ) as load_configuration,
            patch(
                "pipeline.text_replacement_plugins.google_cloud_translate._load_google_modules",
                return_value=modules,
            ),
        ):
            with self.assertRaisesRegex(TextReplacementProviderError, "could not translate"):
                provider.replace(request)
            self.assertEqual("translated", provider.replace(request).text)

        self.assertEqual(2, create_client.call_count)
        self.assertEqual(2, load_configuration.call_count)

    # Verifies FR-2026-08-28-01.
    def test_a_new_provider_instance_loads_fresh_configuration(self) -> None:
        client_factory = _FakeClientFactory(_FakeResponse([_FakeTranslation("translated")]))
        modules = _GoogleModules(cast(Callable[[str], _TranslationClient], client_factory.create_client))
        configurations = [
            _Configuration("first-project", "global", "translate.googleapis.com"),
            _Configuration("second-project", "europe-west1", "translate-eu.googleapis.com"),
        ]
        request = TextReplacementRequest("text", False, "en", "fr")
        with (
            patch(
                "pipeline.text_replacement_plugins.google_cloud_translate._load_configuration",
                side_effect=configurations,
            ) as load_configuration,
            patch(
                "pipeline.text_replacement_plugins.google_cloud_translate._load_google_modules",
                return_value=modules,
            ),
        ):
            GoogleCloudTranslateProvider().replace(request)
            GoogleCloudTranslateProvider().replace(request)

        self.assertEqual(2, load_configuration.call_count)
        self.assertEqual(
            ["translate.googleapis.com", "translate-eu.googleapis.com"], client_factory.endpoints
        )

    # Verifies FR-2026-08-24-04 and SR-2026-08-24-01.
    def test_rejects_missing_or_invalid_configuration_without_loading_the_client(self) -> None:
        provider = GoogleCloudTranslateProvider()
        cases: tuple[dict[str, str], ...] = (
            {},
            {"GOOGLE_API_KEY": "synthetic-api-key"},
            {"GOOGLE_CLOUD_PROJECT": "project"},
        )
        with patch(
            "pipeline.text_replacement_plugins.google_cloud_translate._load_google_modules"
        ) as load_modules:
            for environment in cases:
                with (
                    self.subTest(environment=environment),
                    patch.dict(os.environ, environment, clear=True),
                    self.assertRaisesRegex(TextReplacementProviderError, "configuration"),
                ):
                    provider.replace(TextReplacementRequest("Hello", False, "en", "fr"))

        load_modules.assert_not_called()

    # Verifies FR-2026-08-24-04.
    def test_rejects_a_non_european_location_without_loading_the_client(self) -> None:
        provider = GoogleCloudTranslateProvider()
        with TemporaryDirectory() as temporary_directory:
            credential_path = _write_synthetic_credential(Path(temporary_directory))
            environment = _environment(credential_path, GOOGLE_CLOUD_TRANSLATION_LOCATION="us-central1")
            with (
                patch(
                    "pipeline.text_replacement_plugins.google_cloud_translate._load_google_modules"
                ) as load_modules,
                patch.dict(os.environ, environment, clear=True),
                self.assertRaisesRegex(TextReplacementProviderError, "continental-European"),
            ):
                provider.replace(TextReplacementRequest("Hello", False, "en", "fr"))

        load_modules.assert_not_called()

    # Verifies FR-2026-08-24-04.
    def test_rejects_an_unsafe_translated_filename_stem(self) -> None:
        client_factory = _FakeClientFactory(_FakeResponse([_FakeTranslation("unsafe/name")]))

        with self.assertRaisesRegex(TextReplacementProviderError, "unsafe"):
            self._replace(TextReplacementRequest("report.docx", True, "en", "fr"), client_factory)

    def _replace(
        self,
        request: TextReplacementRequest,
        client_factory: _FakeClientFactory,
        additional_environment: dict[str, str] | None = None,
    ) -> TextReplacementResult:
        with TemporaryDirectory() as temporary_directory:
            credential_path = _write_synthetic_credential(Path(temporary_directory))
            environment = _environment(credential_path, **(additional_environment or {}))
            modules = _GoogleModules(
                cast(Callable[[str], _TranslationClient], client_factory.create_client)
            )
            with (
                patch.dict(os.environ, environment, clear=True),
                patch(
                    "pipeline.text_replacement_plugins.google_cloud_translate._load_google_modules",
                    return_value=modules,
                ),
            ):
                return GoogleCloudTranslateProvider().replace(request)


def _environment(credential_path: Path, **additional_values: str) -> dict[str, str]:
    """Return an isolated provider environment with one synthetic credential file."""
    return {
        "GOOGLE_APPLICATION_CREDENTIALS": str(credential_path),
        "GOOGLE_CLOUD_PROJECT": "synthetic-project",
        **additional_values,
    }


def _write_synthetic_credential(directory: Path) -> Path:
    """Create a minimal non-secret service-account-shaped JSON file for validation."""
    credential_path = directory / "credential.json"
    credential_path.write_text(json.dumps({"type": "service_account"}), encoding="utf-8")
    return credential_path


if __name__ == "__main__":
    unittest.main()
