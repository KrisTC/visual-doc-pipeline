"""Google Cloud Translation Advanced v3 text-replacement provider."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
import json
import os
from pathlib import Path
from typing import Protocol, cast

from pipeline.text_replacement.errors import TextReplacementProviderError
from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult
from pipeline.text_replacement.provider import TextReplacementProvider


LOCAL_EVALUATION_ELIGIBLE = False

_CREDENTIALS_ENVIRONMENT_VARIABLE = "GOOGLE_APPLICATION_CREDENTIALS"
_PROJECT_ENVIRONMENT_VARIABLE = "GOOGLE_CLOUD_PROJECT"
_LOCATION_ENVIRONMENT_VARIABLE = "GOOGLE_CLOUD_TRANSLATION_LOCATION"
_GLOBAL_ENDPOINT = "translate.googleapis.com"
_EU_ENDPOINT = "translate-eu.googleapis.com"


def cache_identity() -> str:
    """Return the non-secret output-affecting Google configuration for cache keys."""
    project = os.environ.get(_PROJECT_ENVIRONMENT_VARIABLE, "").strip()
    location = os.environ.get(_LOCATION_ENVIRONMENT_VARIABLE, "global").strip() or "global"
    return f"google_cloud_translate:v3:v1:{project}:{location}"


class _Translation(Protocol):
    """The response fields used from one Google translation result."""

    translated_text: str


class _TranslateTextResponse(Protocol):
    """The response fields used from Google Cloud Translation."""

    @property
    def translations(self) -> Sequence[_Translation]:
        """Return translations in the same order as the request contents."""


class _TranslationClient(Protocol):
    """The subset of the Google client used by this provider."""

    def translate_text(self, *, request: Mapping[str, object]) -> _TranslateTextResponse:
        """Translate the text described by the supplied request."""


@dataclass(frozen=True, slots=True)
class _GoogleModules:
    """Dynamically loaded Google API boundary."""

    create_client: Callable[[str], _TranslationClient]


@dataclass(frozen=True, slots=True)
class _Configuration:
    """Non-secret provider configuration derived from the local environment."""

    project_id: str
    location: str
    endpoint: str


class GoogleCloudTranslateProvider:
    """Translate text through Cloud Translation Advanced v3."""

    def __init__(self) -> None:
        self._configuration: _Configuration | None = None
        self._client: _TranslationClient | None = None

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        """Translate one request, retaining an input filename's suffix unchanged."""
        if not request.text or request.source_language.casefold() == request.target_language.casefold():
            return TextReplacementResult(text=request.text, confidence=0.0)

        filename_suffix = ""
        text = request.text
        if request.is_filename:
            filename = Path(request.text)
            filename_suffix = filename.suffix
            text = filename.stem

        configuration, client = self._initialized_client()
        translated = self._translate(
            text, request.source_language, request.target_language, configuration, client
        )
        if request.is_filename:
            _validate_filename_stem(translated)
            translated = f"{translated}{filename_suffix}"
        return TextReplacementResult(text=translated, confidence=0.0)

    def _translate(
        self,
        text: str,
        source_language: str,
        target_language: str,
        configuration: _Configuration,
        client: _TranslationClient,
    ) -> str:
        """Issue one pre-trained NMT translation request."""
        request: Mapping[str, object] = {
            "parent": f"projects/{configuration.project_id}/locations/{configuration.location}",
            "contents": [text],
            "mime_type": "text/plain",
            "source_language_code": source_language,
            "target_language_code": target_language,
        }
        try:
            response = client.translate_text(request=request)
        except TextReplacementProviderError:
            raise
        except Exception as error:
            message = "Google Cloud Translation could not translate the requested text."
            raise TextReplacementProviderError(message) from error

        if not response.translations or not response.translations[0].translated_text:
            message = "Google Cloud Translation returned no translation."
            raise TextReplacementProviderError(message)
        return response.translations[0].translated_text

    def _initialized_client(self) -> tuple[_Configuration, _TranslationClient]:
        """Lazily initialize and retain the configuration and endpoint client."""
        if self._configuration is not None and self._client is not None:
            return self._configuration, self._client
        configuration = _load_configuration()
        try:
            client = _load_google_modules().create_client(configuration.endpoint)
        except TextReplacementProviderError:
            raise
        except Exception as error:
            message = "Google Cloud Translation could not translate the requested text."
            raise TextReplacementProviderError(message) from error
        self._configuration = configuration
        self._client = client
        return configuration, client


def create_provider() -> TextReplacementProvider:
    """Create the provider selected by this package's directory name."""
    return GoogleCloudTranslateProvider()


def _load_configuration() -> _Configuration:
    """Validate the local credential-file and endpoint configuration before a request."""
    project_id = os.environ.get(_PROJECT_ENVIRONMENT_VARIABLE, "").strip()
    credential_path = os.environ.get(_CREDENTIALS_ENVIRONMENT_VARIABLE, "").strip()
    if not project_id or not credential_path:
        message = "Google Cloud Translation requires project and service-account credential configuration."
        raise TextReplacementProviderError(message)

    _validate_service_account_credential(Path(credential_path))
    location = os.environ.get(_LOCATION_ENVIRONMENT_VARIABLE, "").strip()
    if not location:
        return _Configuration(project_id, "global", _GLOBAL_ENDPOINT)
    if not location.casefold().startswith("europe-"):
        message = "Google Cloud Translation supports only global or continental-European locations."
        raise TextReplacementProviderError(message)
    return _Configuration(project_id, location, _EU_ENDPOINT)


def _validate_service_account_credential(credential_path: Path) -> None:
    """Reject missing, malformed, or non-service-account JSON without exposing it."""
    if not credential_path.is_absolute() or not credential_path.is_file():
        message = "Google Cloud Translation service-account credential configuration is invalid."
        raise TextReplacementProviderError(message)
    try:
        credential_data = cast(Mapping[str, object], json.loads(credential_path.read_text("utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        message = "Google Cloud Translation service-account credential configuration is invalid."
        raise TextReplacementProviderError(message) from error
    if credential_data.get("type") != "service_account":
        message = "Google Cloud Translation service-account credential configuration is invalid."
        raise TextReplacementProviderError(message)


def _load_google_modules() -> _GoogleModules:
    """Load the Google client only when this remote provider is used."""
    translate_module = import_module("google.cloud.translate_v3")
    client_factory = cast(_TranslationClientFactory, translate_module.TranslationServiceClient)

    def create_client(endpoint: str) -> _TranslationClient:
        return client_factory(client_options={"api_endpoint": endpoint})

    return _GoogleModules(create_client)


class _TranslationClientFactory(Protocol):
    """Construct a Translation client with a selected API endpoint."""

    def __call__(self, *, client_options: Mapping[str, str]) -> _TranslationClient:
        """Create one configured translation client."""


def _validate_filename_stem(stem: str) -> None:
    """Reject a translated filename stem that cannot safely become a destination file."""
    if not stem or stem in {".", ".."} or "\x00" in stem or "/" in stem or "\\" in stem:
        message = "Google Cloud Translation returned an unsafe translated filename stem."
        raise TextReplacementProviderError(message)
