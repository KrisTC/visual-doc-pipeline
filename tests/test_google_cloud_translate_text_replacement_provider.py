"""Behavioural tests for the Google Cloud Translation text-replacement provider."""

from __future__ import annotations

import json
import os
import unittest
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import Mock, patch

from pipeline.folder_replacement.failure_diagnostics import (
    ContextualTextReplacementProvider,
    FailureContext,
)
from pipeline.text_replacement.errors import (
    TextReplacementProviderError,
    TextReplacementProviderRequestError,
)
from pipeline.text_replacement.models import (
    BatchLimits,
    TextReplacementRequest,
    TextReplacementResult,
)
from pipeline.text_replacement_plugins.google_cloud_translate import (
    GoogleCloudTranslateProvider,
    _Configuration,
    _GoogleModules,
    _TranslationClient,
)


def _request(*texts: str, is_filename: bool = False, source: str = "en", target: str = "fr") -> TextReplacementRequest:
    return TextReplacementRequest(texts, is_filename, source, target)


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
        self.timeouts: list[float] = []

    def translate_text(self, *, request: Mapping[str, object], timeout: float) -> _FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        return self.response


class _SequenceClient:
    def __init__(self, outcomes: list[_FakeResponse | Exception]) -> None:
        self._outcomes = outcomes
        self.requests: list[Mapping[str, object]] = []
        self.timeouts: list[float] = []

    def translate_text(self, *, request: Mapping[str, object], timeout: float) -> _FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeClientFactory:
    def __init__(self, response: _FakeResponse) -> None:
        self.client = _FakeClient(response)
        self.endpoints: list[str] = []

    def create_client(self, endpoint: str) -> _FakeClient:
        self.endpoints.append(endpoint)
        return self.client


class GoogleCloudTranslateProviderTests(unittest.TestCase):
    # Verifies FR-2026-08-24-04.
    def test_derives_the_project_and_uses_the_default_eu_endpoint(self) -> None:
        client_factory = _FakeClientFactory(_FakeResponse([_FakeTranslation("Hola")]))

        result = self._replace(
            TextReplacementRequest(("Hello",), False, "en-GB", "es-MX"), client_factory
        ).items[0]

        self.assertEqual("Hola", result.text)
        self.assertEqual(0.0, result.confidence)
        self.assertEqual(["translate-eu.googleapis.com"], client_factory.endpoints)
        self.assertEqual(
            "projects/synthetic-project/locations/europe-west1",
            client_factory.client.requests[0]["parent"],
        )
        self.assertEqual(["Hello"], client_factory.client.requests[0]["contents"])
        self.assertEqual("en-GB", client_factory.client.requests[0]["source_language_code"])
        self.assertEqual("es-MX", client_factory.client.requests[0]["target_language_code"])
        self.assertEqual([300.0], client_factory.client.timeouts)

    # Verifies FR-2026-08-24-04.
    def test_translates_a_filename_stem_through_the_eu_endpoint(self) -> None:
        client_factory = _FakeClientFactory(_FakeResponse([_FakeTranslation("rapport")]))

        result = self._replace(
            _request("report.docx", is_filename=True),
            client_factory,
            {"GOOGLE_CLOUD_TRANSLATION_LOCATION": "europe-west3"},
        ).items[0]

        self.assertEqual("rapport.docx", result.text)
        self.assertEqual(["translate-eu.googleapis.com"], client_factory.endpoints)
        self.assertEqual(
            "projects/synthetic-project/locations/europe-west3",
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
            empty_result = provider.replace(_request("")).items[0]
            same_language_result = provider.replace(
                TextReplacementRequest(("Hello",), False, "EN", "en")
            ).items[0]

        self.assertEqual("", empty_result.text)
        self.assertEqual("Hello", same_language_result.text)
        load_modules.assert_not_called()
        load_configuration.assert_not_called()

    # Verifies FR-2026-08-28-01.
    def test_reuses_one_configuration_and_client_for_multiple_replacements(self) -> None:
        client_factory = _FakeClientFactory(
            _FakeResponse([_FakeTranslation("translated")])
        )
        configuration = _Configuration("synthetic-project", "europe-west1", "translate-eu.googleapis.com")
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
            provider.replace(_request("first"))
            provider.replace(_request("second"))

        load_configuration.assert_called_once_with()
        load_modules.assert_called_once_with()
        self.assertEqual(["translate-eu.googleapis.com"], client_factory.endpoints)
        self.assertEqual(2, len(client_factory.client.requests))

    # Verifies FR-2026-09-03-04.
    def test_retries_a_timeout_and_applies_the_deadline_to_each_attempt(self) -> None:
        client = _SequenceClient([
            TimeoutError(),
            _FakeResponse([_FakeTranslation("translated")]),
        ])

        result = self._replace_with_client(
            _request("synthetic"),
            cast(_TranslationClient, client),
        ).items[0]

        self.assertEqual("translated", result.text)
        self.assertEqual([300.0, 300.0], client.timeouts)

    # Verifies FR-2026-09-03-04.
    def test_stops_after_three_timeouts_and_records_safe_failure_metadata(self) -> None:
        client = _SequenceClient([TimeoutError(), TimeoutError(), TimeoutError()])
        provider = GoogleCloudTranslateProvider()
        failure_context = FailureContext()
        contextual_provider = ContextualTextReplacementProvider(provider, failure_context)

        with self._patched_client(cast(_TranslationClient, client)):
            with self.assertRaises(TextReplacementProviderRequestError) as raised:
                contextual_provider.replace(_request("synthetic text"))

        self.assertEqual([300.0, 300.0, 300.0], client.timeouts)
        self.assertEqual(
            {
                "kind": "text_replacement",
                "source_language": "en",
                "target_language": "fr",
                "is_filename": False,
                "text_count": 1,
                "input_character_count": 14,
                "provider": "google_cloud_translate",
                "failure_category": "timeout",
                "attempted_call_count": 3,
                "attempt_deadline_seconds": 300.0,
                "configured_attempt_limit": 3,
                "rate_limit_waits": 0,
                "rate_limit_wait_seconds": 0.0,
            },
            failure_context.as_diagnostic()["request"],
        )
        self.assertNotIn("synthetic text", str(raised.exception.diagnostic))

    # Verifies FR-2026-09-03-04.
    def test_does_not_retry_a_non_transient_api_failure(self) -> None:
        client = _SequenceClient([ValueError("invalid request")])

        with self.assertRaises(TextReplacementProviderRequestError) as raised:
            self._replace_with_client(
                _request("synthetic"),
                cast(_TranslationClient, client),
            )

        self.assertEqual([300.0], client.timeouts)
        self.assertEqual("non_transient_api_failure", raised.exception.diagnostic["failure_category"])

    # Verifies FR-2026-08-28-01.
    def test_retries_client_initialization_after_construction_failure(self) -> None:
        configuration = _Configuration("synthetic-project", "europe-west1", "translate-eu.googleapis.com")
        client = _FakeClient(_FakeResponse([_FakeTranslation("translated")]))
        create_client = Mock(side_effect=[RuntimeError("temporary"), client])
        modules = _GoogleModules(cast(Callable[[str], _TranslationClient], create_client))
        provider = GoogleCloudTranslateProvider()
        request = _request("text")
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
            self.assertEqual("translated", provider.replace(request).items[0].text)

        self.assertEqual(2, create_client.call_count)
        self.assertEqual(2, load_configuration.call_count)

    # Verifies FR-2026-08-28-01.
    def test_a_new_provider_instance_loads_fresh_configuration(self) -> None:
        client_factory = _FakeClientFactory(_FakeResponse([_FakeTranslation("translated")]))
        modules = _GoogleModules(cast(Callable[[str], _TranslationClient], client_factory.create_client))
        configurations = [
            _Configuration("first-project", "europe-west1", "translate-eu.googleapis.com"),
            _Configuration("second-project", "europe-west3", "translate-eu.googleapis.com"),
        ]
        request = _request("text")
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
            ["translate-eu.googleapis.com", "translate-eu.googleapis.com"], client_factory.endpoints
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
                    provider.replace(_request("Hello"))

        load_modules.assert_not_called()

    # Verifies FR-2026-08-24-04 and SR-2026-08-24-01.
    def test_uses_an_explicit_project_when_the_credential_has_no_project_id(self) -> None:
        client_factory = _FakeClientFactory(_FakeResponse([_FakeTranslation("translated")]))
        with TemporaryDirectory() as temporary_directory:
            credential_path = _write_synthetic_credential(Path(temporary_directory), project_id=None)
            environment = _environment(credential_path, GOOGLE_CLOUD_PROJECT="explicit-project")
            modules = _GoogleModules(cast(Callable[[str], _TranslationClient], client_factory.create_client))
            with (
                patch.dict(os.environ, environment, clear=True),
                patch(
                    "pipeline.text_replacement_plugins.google_cloud_translate._load_google_modules",
                    return_value=modules,
                ),
            ):
                GoogleCloudTranslateProvider().replace(_request("text"))

        self.assertEqual(
            "projects/explicit-project/locations/europe-west1", client_factory.client.requests[0]["parent"]
        )

    # Verifies FR-2026-08-24-04 and SR-2026-08-24-01.
    def test_rejects_a_credential_without_a_project_id_when_not_overridden(self) -> None:
        provider = GoogleCloudTranslateProvider()
        with TemporaryDirectory() as temporary_directory:
            credential_path = _write_synthetic_credential(Path(temporary_directory), project_id=None)
            with (
                patch.dict(os.environ, _environment(credential_path), clear=True),
                patch(
                    "pipeline.text_replacement_plugins.google_cloud_translate._load_google_modules"
                ) as load_modules,
                self.assertRaisesRegex(TextReplacementProviderError, "configuration"),
            ):
                provider.replace(_request("text"))

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
                provider.replace(_request("Hello"))

        load_modules.assert_not_called()

    # Verifies FR-2026-08-24-04.
    def test_rejects_an_unsafe_translated_filename_stem(self) -> None:
        client_factory = _FakeClientFactory(_FakeResponse([_FakeTranslation("unsafe/name")]))

        with self.assertRaisesRegex(TextReplacementProviderError, "unsafe"):
            self._replace(_request("report.docx", is_filename=True), client_factory)

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

    def _replace_with_client(
        self, request: TextReplacementRequest, client: _TranslationClient
    ) -> TextReplacementResult:
        with self._patched_client(client):
            return GoogleCloudTranslateProvider().replace(request)

    def _patched_client(self, client: _TranslationClient) -> AbstractContextManager[None]:
        configuration = _Configuration("synthetic-project", "europe-west1", "translate-eu.googleapis.com")
        modules = _GoogleModules(lambda _endpoint: client)
        return _patch_client_configuration(configuration, modules)


def _environment(credential_path: Path, **additional_values: str) -> dict[str, str]:
    """Return an isolated provider environment with one synthetic credential file."""
    return {
        "GOOGLE_APPLICATION_CREDENTIALS": str(credential_path),
        **additional_values,
    }


def _write_synthetic_credential(directory: Path, project_id: str | None = "synthetic-project") -> Path:
    """Create a minimal non-secret service-account-shaped JSON file for validation."""
    credential_path = directory / "credential.json"
    credential = {"type": "service_account"}
    if project_id is not None:
        credential["project_id"] = project_id
    credential_path.write_text(json.dumps(credential), encoding="utf-8")
    return credential_path


@contextmanager
def _patch_client_configuration(
    configuration: _Configuration, modules: _GoogleModules
) -> Iterator[None]:
    with (
        patch(
            "pipeline.text_replacement_plugins.google_cloud_translate._load_configuration",
            return_value=configuration,
        ),
        patch(
            "pipeline.text_replacement_plugins.google_cloud_translate._load_google_modules",
            return_value=modules,
        ),
    ):
        yield


class InvalidArgument(Exception):
    """Named like the Google API error that reports a request its content made invalid."""


class TooManyRequests(Exception):
    """Named like the Google API error for an HTTP 429 response."""

    def __init__(
        self,
        message: str = "",
        details: Sequence[object] = (),
        response: object | None = None,
    ) -> None:
        super().__init__(message)
        self.details = list(details)
        self.response = response


@dataclass(frozen=True, slots=True)
class _FakeResponseWithHeaders:
    headers: Mapping[str, str]


class Forbidden(Exception):
    """Named like the Google API error for an HTTP 403 response."""


class PermissionDenied(Exception):
    """Named like the Google API error for an authorization failure."""


class ServiceUnavailable(Exception):
    """Named like the Google API error for a transient service failure."""


class _EchoClient:
    """Translate each content to ``T:<content>`` unless a scripted outcome says otherwise."""

    def __init__(self, script: Sequence[Exception | Callable[[list[str]], list[str]] | None] = ()) -> None:
        self._script = list(script)
        self.requests: list[Mapping[str, object]] = []
        self.timeouts: list[float] = []

    @property
    def sent(self) -> list[list[str]]:
        return [list(cast(Sequence[str], request["contents"])) for request in self.requests]

    def translate_text(self, *, request: Mapping[str, object], timeout: float) -> _FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        contents = list(cast(Sequence[str], request["contents"]))
        outcome = self._script.pop(0) if self._script else None
        if isinstance(outcome, Exception):
            raise outcome
        translations = outcome(contents) if outcome is not None else [f"T:{text}" for text in contents]
        return _FakeResponse([_FakeTranslation(text) for text in translations])


class _RejectingClient(_EchoClient):
    """Reject any request whose contents include the offending text."""

    def __init__(self, offending: str) -> None:
        super().__init__()
        self._offending = offending

    def translate_text(self, *, request: Mapping[str, object], timeout: float) -> _FakeResponse:
        if self._offending in cast(Sequence[str], request["contents"]):
            self.requests.append(request)
            self.timeouts.append(timeout)
            raise InvalidArgument("synthetic invalid argument")
        return super().translate_text(request=request, timeout=timeout)


class GoogleBatchTranslationTests(unittest.TestCase):
    def _provider(
        self,
        environment: dict[str, str] | None = None,
        sleeps: list[float] | None = None,
    ) -> GoogleCloudTranslateProvider:
        recorded = sleeps if sleeps is not None else []
        with patch.dict(os.environ, environment or {}, clear=True):
            return GoogleCloudTranslateProvider(sleep=recorded.append, jitter=lambda: 0.0)

    def _replace(
        self, provider: GoogleCloudTranslateProvider, request: TextReplacementRequest, client: _EchoClient
    ) -> TextReplacementResult:
        configuration = _Configuration("synthetic-project", "europe-west1", "translate-eu.googleapis.com")
        modules = _GoogleModules(lambda _endpoint: cast(_TranslationClient, client))
        with _patch_client_configuration(configuration, modules):
            return provider.replace(request)

    # Verifies FR-2026-10-22-02.
    def test_sends_all_texts_in_one_request_and_returns_items_in_order(self) -> None:
        client = _EchoClient()

        result = self._replace(self._provider(), _request("one", "two", "three"), client)

        self.assertEqual([["one", "two", "three"]], client.sent)
        self.assertEqual("text/plain", client.requests[0]["mime_type"])
        self.assertEqual(["T:one", "T:two", "T:three"], [item.text for item in result.items])
        self.assertEqual([0.0, 0.0, 0.0], [item.confidence for item in result.items])

    # Verifies FR-2026-10-22-02.
    def test_exposes_the_default_batch_limits(self) -> None:
        self.assertEqual(BatchLimits(1024, 5000, 30000), self._provider().batch_limits)

    # Verifies FR-2026-10-22-02.
    def test_splits_requests_at_the_maximum_item_count(self) -> None:
        client = _EchoClient()
        provider = self._provider({"GOOGLE_CLOUD_TRANSLATION_BATCH_MAX_ITEMS": "2"})

        result = self._replace(provider, _request("a", "b", "c", "d", "e"), client)

        self.assertEqual([["a", "b"], ["c", "d"], ["e"]], client.sent)
        self.assertEqual(["T:a", "T:b", "T:c", "T:d", "T:e"], [item.text for item in result.items])

    # Verifies FR-2026-10-22-02.
    def test_maximum_item_count_of_one_reproduces_single_text_requests(self) -> None:
        client = _EchoClient()
        provider = self._provider({"GOOGLE_CLOUD_TRANSLATION_BATCH_MAX_ITEMS": "1"})

        self._replace(provider, _request("a", "b", "c"), client)

        self.assertEqual([["a"], ["b"], ["c"]], client.sent)

    # Verifies FR-2026-10-22-02.
    def test_splits_requests_at_the_target_character_count(self) -> None:
        client = _EchoClient()
        provider = self._provider({"GOOGLE_CLOUD_TRANSLATION_BATCH_TARGET_CHARACTERS": "10"})

        self._replace(provider, _request("aaaa", "bbbb", "cccc", "dddd", "eeee"), client)

        self.assertEqual([["aaaa", "bbbb"], ["cccc", "dddd"], ["eeee"]], client.sent)

    # Verifies FR-2026-10-22-02.
    def test_a_text_longer_than_the_soft_target_is_sent_alone(self) -> None:
        client = _EchoClient()
        provider = self._provider({"GOOGLE_CLOUD_TRANSLATION_BATCH_TARGET_CHARACTERS": "5"})

        self._replace(provider, _request("ab", "abcdefgh", "cd", "ef"), client)

        self.assertEqual([["ab"], ["abcdefgh"], ["cd", "ef"]], client.sent)

    # Verifies FR-2026-10-22-02, SR-2026-10-22-01.
    def test_rejects_a_text_above_the_hard_maximum_without_a_call_or_text_in_the_diagnostic(self) -> None:
        client = _EchoClient()
        provider = self._provider(
            {
                "GOOGLE_CLOUD_TRANSLATION_BATCH_MAX_CHARACTERS": "20",
                "GOOGLE_CLOUD_TRANSLATION_BATCH_TARGET_CHARACTERS": "10",
            }
        )
        oversized = "secret-" + "x" * 20

        with self.assertRaises(TextReplacementProviderRequestError) as raised:
            self._replace(provider, _request("fine", oversized), client)

        self.assertEqual([], client.requests)
        self.assertEqual("text_exceeds_request_limit", raised.exception.diagnostic["failure_category"])
        self.assertEqual(27, raised.exception.diagnostic["input_character_count"])
        self.assertNotIn("secret", str(raised.exception.diagnostic) + str(raised.exception))

    # Verifies FR-2026-10-22-02.
    def test_empty_texts_are_returned_unchanged_and_not_sent(self) -> None:
        client = _EchoClient()

        result = self._replace(self._provider(), _request("", "one", ""), client)

        self.assertEqual([["one"]], client.sent)
        self.assertEqual(["", "T:one", ""], [item.text for item in result.items])
        self.assertEqual([0.0, 0.0, 0.0], [item.confidence for item in result.items])

    # Verifies FR-2026-10-22-02.
    def test_a_request_needing_no_translation_makes_no_call(self) -> None:
        client = _EchoClient()
        provider = self._provider()

        same_language = self._replace(
            provider, _request("one", "two", source="EN", target="en"), client
        )
        empty = self._replace(provider, _request("", ""), client)

        self.assertEqual([], client.requests)
        self.assertEqual(["one", "two"], [item.text for item in same_language.items])
        self.assertEqual(["", ""], [item.text for item in empty.items])

    # Verifies FR-2026-10-22-02.
    def test_translates_each_filename_stem_and_keeps_each_suffix(self) -> None:
        client = _EchoClient()

        result = self._replace(
            self._provider(), _request("report.docx", "notes", ".hidden", is_filename=True), client
        )

        self.assertEqual([["report", "notes", ".hidden"]], client.sent)
        self.assertEqual(["T:report.docx", "T:notes", "T:.hidden"], [item.text for item in result.items])

    # Verifies FR-2026-10-22-02, SR-2026-10-22-01.
    def test_rejects_a_response_with_the_wrong_translation_count_without_exposing_text(self) -> None:
        client = _EchoClient([lambda contents: ["only-one"]])

        with self.assertRaises(TextReplacementProviderError) as raised:
            self._replace(self._provider(), _request("secret one", "secret two"), client)

        self.assertIn("1 translations for 2 texts", str(raised.exception))
        self.assertNotIn("secret", str(raised.exception))

    # Verifies FR-2026-10-22-02.
    def test_retries_one_empty_response_item_alone_once(self) -> None:
        client = _EchoClient([lambda contents: ["T:a", "", "T:c"]])

        result = self._replace(self._provider(), _request("a", "b", "c"), client)

        self.assertEqual([["a", "b", "c"], ["b"]], client.sent)
        self.assertEqual(["T:a", "T:b", "T:c"], [item.text for item in result.items])

    # Verifies FR-2026-10-22-02.
    def test_raises_when_an_item_is_still_empty_after_its_single_retry(self) -> None:
        client = _EchoClient([lambda contents: ["T:a", ""], lambda contents: [""]])

        with self.assertRaisesRegex(TextReplacementProviderError, "no translation"):
            self._replace(self._provider(), _request("a", "b"), client)

        self.assertEqual([["a", "b"], ["b"]], client.sent)

    # Verifies FR-2026-10-22-02.
    def test_retries_an_unsafe_filename_stem_alone_once(self) -> None:
        client = _EchoClient([lambda contents: ["safe", "unsafe/name"], lambda contents: ["fine"]])

        result = self._replace(self._provider(), _request("a.txt", "b.txt", is_filename=True), client)

        self.assertEqual([["a", "b"], ["b"]], client.sent)
        self.assertEqual(["safe.txt", "fine.txt"], [item.text for item in result.items])

    # Verifies FR-2026-10-22-02, SR-2026-10-22-01.
    def test_bisects_a_failed_batch_to_the_one_offending_text(self) -> None:
        client = _RejectingClient("bad")

        with self.assertRaises(TextReplacementProviderRequestError) as raised:
            self._replace(self._provider(), _request("a", "b", "bad", "d"), client)

        self.assertEqual([["a", "b", "bad", "d"], ["a", "b"], ["bad", "d"], ["bad"]], client.sent)
        self.assertEqual("invalid_request", raised.exception.diagnostic["failure_category"])
        self.assertEqual(1, raised.exception.diagnostic["text_count"])
        self.assertEqual(3, raised.exception.diagnostic["input_character_count"])
        self.assertNotIn("bad", str(raised.exception.diagnostic))

    # Verifies FR-2026-10-22-02.
    def test_authorization_failures_fail_immediately_without_bisecting(self) -> None:
        for error in (PermissionDenied("synthetic"), Forbidden("synthetic permission problem")):
            with self.subTest(error=type(error).__name__):
                client = _EchoClient([error])

                with self.assertRaises(TextReplacementProviderRequestError) as raised:
                    self._replace(self._provider(), _request("a", "b", "c"), client)

                self.assertEqual(1, len(client.requests))
                self.assertEqual(
                    "non_transient_api_failure", raised.exception.diagnostic["failure_category"]
                )

    # Verifies FR-2026-10-22-02.
    def test_environment_limits_use_defaults_when_blank_and_reject_invalid_values(self) -> None:
        for name, invalid_values in (
            ("GOOGLE_CLOUD_TRANSLATION_BATCH_MAX_ITEMS", ("0", "1025", "-1", "1.5", "many")),
            ("GOOGLE_CLOUD_TRANSLATION_BATCH_TARGET_CHARACTERS", ("0", "30001", "abc")),
            ("GOOGLE_CLOUD_TRANSLATION_BATCH_MAX_CHARACTERS", ("0", "30001", "abc")),
            ("GOOGLE_CLOUD_TRANSLATION_TIMEOUT_SECONDS", ("0", "3601", "abc")),
            ("GOOGLE_CLOUD_TRANSLATION_RATE_LIMIT_MAX_WAIT_SECONDS", ("86401", "-1", "abc")),
        ):
            self.assertEqual(
                BatchLimits(1024, 5000, 30000), self._provider({name: "  "}).batch_limits
            )
            for value in invalid_values:
                with self.subTest(name=name, value=value):
                    with self.assertRaises(TextReplacementProviderError) as raised:
                        self._provider({name: value})
                    self.assertIn(name, str(raised.exception))
                    self.assertIn("must be an integer from", str(raised.exception))

    # Verifies FR-2026-10-22-02.
    def test_target_characters_may_not_exceed_the_configured_maximum(self) -> None:
        with self.assertRaises(TextReplacementProviderError):
            self._provider(
                {
                    "GOOGLE_CLOUD_TRANSLATION_BATCH_MAX_CHARACTERS": "100",
                    "GOOGLE_CLOUD_TRANSLATION_BATCH_TARGET_CHARACTERS": "101",
                }
            )
        self.assertEqual(
            BatchLimits(1024, 100, 100),
            self._provider({"GOOGLE_CLOUD_TRANSLATION_BATCH_MAX_CHARACTERS": "100"}).batch_limits,
        )

    # Verifies FR-2026-10-22-03.
    def test_applies_the_configured_deadline_to_every_request(self) -> None:
        client = _EchoClient()
        provider = self._provider({"GOOGLE_CLOUD_TRANSLATION_TIMEOUT_SECONDS": "45"})

        self._replace(provider, _request("a", "b"), client)

        self.assertEqual([45.0], client.timeouts)

    # Verifies FR-2026-10-22-03.
    def test_rate_limit_backs_off_with_doubling_waits_capped_at_sixty_seconds(self) -> None:
        sleeps: list[float] = []
        client = _EchoClient([TooManyRequests()] * 7)

        result = self._replace(self._provider(sleeps=sleeps), _request("a"), client)

        self.assertEqual([2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0], sleeps)
        self.assertEqual("T:a", result.items[0].text)
        self.assertEqual(8, len(client.requests))

    # Verifies FR-2026-10-22-03.
    def test_rate_limit_waits_do_not_consume_the_attempt_limit(self) -> None:
        sleeps: list[float] = []
        client = _EchoClient([TooManyRequests(), ServiceUnavailable(), TooManyRequests(), ServiceUnavailable()])

        result = self._replace(self._provider(sleeps=sleeps), _request("a"), client)

        self.assertEqual("T:a", result.items[0].text)
        self.assertEqual(2, len(sleeps))
        self.assertEqual(5, len(client.requests))

    # Verifies FR-2026-10-22-03.
    def test_honours_a_longer_grpc_retry_info_delay(self) -> None:
        from google.protobuf.duration_pb2 import Duration  # type: ignore[import-untyped]
        from google.rpc.error_details_pb2 import RetryInfo  # type: ignore[import-untyped]

        sleeps: list[float] = []
        retry_info = RetryInfo(retry_delay=Duration(seconds=45, nanos=500_000_000))
        client = _EchoClient([TooManyRequests(details=[retry_info])])

        self._replace(self._provider(sleeps=sleeps), _request("a"), client)

        self.assertEqual([45.5], sleeps)

    # Verifies FR-2026-10-22-03.
    def test_honours_a_longer_rest_retry_after_header(self) -> None:
        sleeps: list[float] = []
        error = TooManyRequests(response=_FakeResponseWithHeaders({"Retry-After": "30"}))
        client = _EchoClient([error])

        self._replace(self._provider(sleeps=sleeps), _request("a"), client)

        self.assertEqual([30.0], sleeps)

    # Verifies FR-2026-10-22-03.
    def test_ignores_a_missing_or_unparseable_server_delay(self) -> None:
        sleeps: list[float] = []
        client = _EchoClient(
            [
                TooManyRequests(response=_FakeResponseWithHeaders({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})),
                TooManyRequests(response=object(), details=[object()]),
            ]
        )

        self._replace(self._provider(sleeps=sleeps), _request("a"), client)

        self.assertEqual([2.0, 4.0], sleeps)

    # Verifies FR-2026-10-22-03.
    def test_a_server_delay_shorter_than_the_schedule_does_not_shorten_the_wait(self) -> None:
        sleeps: list[float] = []
        error = TooManyRequests(response=_FakeResponseWithHeaders({"Retry-After": "1"}))

        self._replace(self._provider(sleeps=sleeps), _request("a"), _EchoClient([error]))

        self.assertEqual([2.0], sleeps)

    # Verifies FR-2026-10-22-03.
    def test_jitter_only_shortens_a_wait_and_never_exceeds_the_schedule(self) -> None:
        sleeps: list[float] = []
        with patch.dict(os.environ, {}, clear=True):
            provider = GoogleCloudTranslateProvider(sleep=sleeps.append, jitter=lambda: 1.0)
        client = _EchoClient([TooManyRequests()] * 2)

        self._replace(provider, _request("a"), client)

        self.assertEqual([1.5, 3.0], sleeps)

    # Verifies FR-2026-10-22-03, SR-2026-10-22-01.
    def test_stops_with_a_safe_error_after_the_total_wait_cap(self) -> None:
        sleeps: list[float] = []
        client = _EchoClient([TooManyRequests("secret detail")] * 10)
        provider = self._provider(
            {"GOOGLE_CLOUD_TRANSLATION_RATE_LIMIT_MAX_WAIT_SECONDS": "5"}, sleeps
        )

        with self.assertRaises(TextReplacementProviderRequestError) as raised:
            self._replace(provider, _request("secret text"), client)

        self.assertEqual([2.0], sleeps)
        self.assertEqual("rate_limit_exhausted", raised.exception.diagnostic["failure_category"])
        self.assertEqual(1, raised.exception.diagnostic["rate_limit_waits"])
        self.assertEqual(2.0, raised.exception.diagnostic["rate_limit_wait_seconds"])
        self.assertEqual(1, raised.exception.diagnostic["text_count"])
        self.assertNotIn("secret", str(raised.exception.diagnostic) + str(raised.exception))

    # Verifies FR-2026-10-22-03.
    def test_a_zero_wait_cap_disables_the_backoff(self) -> None:
        sleeps: list[float] = []
        client = _EchoClient([TooManyRequests()])
        provider = self._provider(
            {"GOOGLE_CLOUD_TRANSLATION_RATE_LIMIT_MAX_WAIT_SECONDS": "0"}, sleeps
        )

        with self.assertRaises(TextReplacementProviderRequestError):
            self._replace(provider, _request("a"), client)

        self.assertEqual([], sleeps)
        self.assertEqual(1, len(client.requests))

    # Verifies FR-2026-10-22-03.
    def test_a_403_user_rate_limit_backs_off_like_a_429(self) -> None:
        sleeps: list[float] = []
        client = _EchoClient([Forbidden("User Rate Limit Exceeded")])

        result = self._replace(self._provider(sleeps=sleeps), _request("a"), client)

        self.assertEqual([2.0], sleeps)
        self.assertEqual("T:a", result.items[0].text)

    # Verifies FR-2026-10-22-03.
    def test_a_daily_limit_fails_immediately_with_its_own_reason(self) -> None:
        sleeps: list[float] = []
        client = _EchoClient([Forbidden("Daily Limit Exceeded")])

        with self.assertRaises(TextReplacementProviderRequestError) as raised:
            self._replace(self._provider(sleeps=sleeps), _request("a", "b"), client)

        self.assertEqual([], sleeps)
        self.assertEqual(1, len(client.requests))
        self.assertEqual("daily_quota_exhausted", raised.exception.diagnostic["failure_category"])
        self.assertIn("daily quota", str(raised.exception))

    # Verifies FR-2026-10-22-03.
    def test_an_unrelated_403_is_not_retried(self) -> None:
        sleeps: list[float] = []
        client = _EchoClient([Forbidden("Billing is disabled")])

        with self.assertRaises(TextReplacementProviderRequestError) as raised:
            self._replace(self._provider(sleeps=sleeps), _request("a"), client)

        self.assertEqual([], sleeps)
        self.assertEqual("non_transient_api_failure", raised.exception.diagnostic["failure_category"])

    # Verifies FR-2026-10-22-03, SR-2026-10-22-01.
    def test_rate_limit_waits_are_logged_and_metered_without_request_text(self) -> None:
        from pipeline.provider_metrics import RunMetrics

        client = _EchoClient([TooManyRequests("secret detail"), TooManyRequests()])

        with RunMetrics() as metrics:
            with self.assertLogs(
                "pipeline.text_replacement_plugins.google_cloud_translate", level="WARNING"
            ) as logs:
                self._replace(self._provider(), _request("secret one", "secret two"), client)

        self.assertEqual(2, len(logs.output))
        self.assertIn("wait 1 of 2.0 seconds for 2 texts", logs.output[0])
        self.assertNotIn("secret", "".join(logs.output))
        report = metrics.report(10)[0]
        self.assertEqual(2, report["rate_limit_waits"])
        self.assertEqual(6.0, report["rate_limit_wait_seconds"])

    # Verifies FR-2026-10-22-03, SR-2026-10-22-01.
    def test_failure_diagnostics_include_counts_and_exclude_text(self) -> None:
        client = _EchoClient([ValueError("secret body")])

        with self.assertRaises(TextReplacementProviderRequestError) as raised:
            self._replace(self._provider(), _request("secret one", "two"), client)

        self.assertEqual(2, raised.exception.diagnostic["text_count"])
        self.assertEqual(13, raised.exception.diagnostic["input_character_count"])
        self.assertEqual(300.0, raised.exception.diagnostic["attempt_deadline_seconds"])
        self.assertNotIn("secret", str(raised.exception.diagnostic) + str(raised.exception))


if __name__ == "__main__":
    unittest.main()
