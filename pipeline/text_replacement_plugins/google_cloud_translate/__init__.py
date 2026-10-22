"""Google Cloud Translation Advanced v3 text-replacement provider."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
import json
import logging
import os
from pathlib import Path
import random
import re
import time
from typing import Protocol, cast

from pipeline.provider_metrics import record_run_rate_limit_wait
from pipeline.text_replacement.errors import TextReplacementProviderError, TextReplacementProviderRequestError
from pipeline.text_replacement.helpers import check_result_length
from pipeline.text_replacement.models import (
    BatchLimits,
    TextReplacementItem,
    TextReplacementRequest,
    TextReplacementResult,
)
from pipeline.text_replacement.provider import TextReplacementProvider


LOCAL_EVALUATION_ELIGIBLE = False
SHORT_NAME = "gct"

_CREDENTIALS_ENVIRONMENT_VARIABLE = "GOOGLE_APPLICATION_CREDENTIALS"
_PROJECT_ENVIRONMENT_VARIABLE = "GOOGLE_CLOUD_PROJECT"
_LOCATION_ENVIRONMENT_VARIABLE = "GOOGLE_CLOUD_TRANSLATION_LOCATION"
_BATCH_MAX_ITEMS_VARIABLE = "GOOGLE_CLOUD_TRANSLATION_BATCH_MAX_ITEMS"
_BATCH_TARGET_CHARACTERS_VARIABLE = "GOOGLE_CLOUD_TRANSLATION_BATCH_TARGET_CHARACTERS"
_BATCH_MAX_CHARACTERS_VARIABLE = "GOOGLE_CLOUD_TRANSLATION_BATCH_MAX_CHARACTERS"
_TIMEOUT_SECONDS_VARIABLE = "GOOGLE_CLOUD_TRANSLATION_TIMEOUT_SECONDS"
_RATE_LIMIT_MAX_WAIT_VARIABLE = "GOOGLE_CLOUD_TRANSLATION_RATE_LIMIT_MAX_WAIT_SECONDS"
_EU_ENDPOINT = "translate-eu.googleapis.com"
_DEFAULT_LOCATION = "europe-west1"
_PROVIDER_NAME = "google_cloud_translate"
_LOGGER = logging.getLogger(__name__)


def cache_identity() -> str:
    """Return the non-secret output-affecting Google configuration for cache keys."""
    project = os.environ.get(_PROJECT_ENVIRONMENT_VARIABLE, "").strip()
    credential_path = os.environ.get(_CREDENTIALS_ENVIRONMENT_VARIABLE, "").strip()
    if not project and credential_path:
        try:
            project = _validate_service_account_credential(Path(credential_path)) or ""
        except TextReplacementProviderError:
            pass
    location = os.environ.get(_LOCATION_ENVIRONMENT_VARIABLE, "").strip() or _DEFAULT_LOCATION
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

    def translate_text(self, *, request: Mapping[str, object], timeout: float) -> _TranslateTextResponse:
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
    """Translate batches of text through Cloud Translation Advanced v3."""

    def __init__(
        self,
        *,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._configuration: _Configuration | None = None
        self._client: _TranslationClient | None = None
        self._sleep = sleep
        self._jitter = jitter
        max_characters = _integer_environment(_BATCH_MAX_CHARACTERS_VARIABLE, 30_000, 1, 30_000)
        self.batch_limits = BatchLimits(
            max_items=_integer_environment(_BATCH_MAX_ITEMS_VARIABLE, 1024, 1, 1024),
            target_characters=_integer_environment(
                _BATCH_TARGET_CHARACTERS_VARIABLE, min(5000, max_characters), 1, max_characters
            ),
            max_characters=max_characters,
        )
        self._deadline_seconds = float(_integer_environment(_TIMEOUT_SECONDS_VARIABLE, 300, 1, 3600))
        self._rate_limit_max_wait = float(
            _integer_environment(_RATE_LIMIT_MAX_WAIT_VARIABLE, 1800, 0, 86400)
        )

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        """Translate a batch, retaining each input filename's suffix unchanged."""
        same_language = request.source_language.casefold() == request.target_language.casefold()
        items: list[TextReplacementItem | None] = [None] * len(request.texts)
        pending: list[tuple[int, str, str]] = []
        for index, original in enumerate(request.texts):
            if not original or same_language:
                items[index] = TextReplacementItem(original, 0.0)
                continue
            if request.is_filename:
                filename = Path(original)
                text, suffix = filename.stem, filename.suffix
            else:
                text, suffix = original, ""
            self._reject_oversized_text(text)
            pending.append((index, text, suffix))

        translated_texts = self._translate_texts(
            [text for _, text, _ in pending], request.source_language, request.target_language
        )
        for (index, text, suffix), translated in zip(pending, translated_texts, strict=True):
            if not _is_usable_translation(translated, request.is_filename):
                translated = self._translate_alone(
                    text, request.source_language, request.target_language
                )
                if not _is_usable_translation(translated, request.is_filename):
                    if request.is_filename and translated:
                        _validate_filename_stem(translated)
                    message = "Google Cloud Translation returned no translation."
                    raise TextReplacementProviderError(message)
            items[index] = TextReplacementItem(f"{translated}{suffix}", 0.0)
        return check_result_length(
            len(request.texts), TextReplacementResult(tuple(cast("list[TextReplacementItem]", items)))
        )

    def _reject_oversized_text(self, text: str) -> None:
        limit = self.batch_limits.max_characters
        if limit is not None and len(text) > limit:
            message = "A text exceeds the Google Cloud Translation request character limit."
            raise TextReplacementProviderRequestError(
                message,
                {
                    "provider": _PROVIDER_NAME,
                    "failure_category": "text_exceeds_request_limit",
                    "text_count": 1,
                    "input_character_count": len(text),
                    "configured_max_characters": limit,
                },
            )

    def _translate_texts(
        self, texts: list[str], source_language: str, target_language: str
    ) -> list[str]:
        """Pack texts into requests by the configured limits and translate each group."""
        limits = self.batch_limits
        max_items = limits.max_items or 1
        target_characters = limits.target_characters or 1
        translations: list[str] = []
        group: list[str] = []
        group_characters = 0
        for text in texts:
            if group and (
                len(group) >= max_items or group_characters + len(text) > target_characters
            ):
                translations.extend(self._translate_group(group, source_language, target_language))
                group, group_characters = [], 0
            group.append(text)
            group_characters += len(text)
        if group:
            translations.extend(self._translate_group(group, source_language, target_language))
        return translations

    def _translate_group(
        self, texts: list[str], source_language: str, target_language: str
    ) -> list[str]:
        """Translate one group, bisecting it when request content caused the failure."""
        try:
            return self._translate(texts, source_language, target_language)
        except _ContentCausedRequestError:
            if len(texts) == 1:
                raise
            middle = len(texts) // 2
            return self._translate_group(
                texts[:middle], source_language, target_language
            ) + self._translate_group(texts[middle:], source_language, target_language)

    def _translate_alone(self, text: str, source_language: str, target_language: str) -> str:
        return self._translate([text], source_language, target_language)[0]

    def _translate(
        self, texts: list[str], source_language: str, target_language: str
    ) -> list[str]:
        """Issue one pre-trained NMT request and return one translation per sent text."""
        configuration, client = self._initialized_client()
        request: Mapping[str, object] = {
            "parent": f"projects/{configuration.project_id}/locations/{configuration.location}",
            "contents": texts,
            "mime_type": "text/plain",
            "source_language_code": source_language,
            "target_language_code": target_language,
        }
        attempts = 0
        waits = 0
        waited = 0.0
        while True:
            try:
                response = client.translate_text(request=request, timeout=self._deadline_seconds)
                break
            except TextReplacementProviderError:
                raise
            except Exception as error:
                def failure(category: str, message: str) -> TextReplacementProviderRequestError:
                    return _request_failure(
                        TextReplacementProviderRequestError, message, category, texts,
                        attempts + waits, self._deadline_seconds, waits, waited,
                    )

                if _is_daily_limit_error(error):
                    raise failure(
                        "daily_quota_exhausted", "Google Cloud Translation daily quota is exhausted."
                    ) from error
                if _is_rate_limit_error(error):
                    wait = self._rate_limit_wait(waits, error)
                    if waited + wait > self._rate_limit_max_wait:
                        raise failure(
                            "rate_limit_exhausted",
                            "Google Cloud Translation rate limit did not clear within the allowed wait.",
                        ) from error
                    waits += 1
                    waited += wait
                    _LOGGER.warning(
                        "Google Cloud Translation rate limit: wait %d of %.1f seconds for %d texts.",
                        waits, wait, len(texts),
                    )
                    record_run_rate_limit_wait("text_replacement", _PROVIDER_NAME, wait)
                    self._sleep(wait)
                    continue
                attempts += 1
                transient = _is_transient_translation_error(error)
                if attempts < _TRANSLATE_ATTEMPT_LIMIT and transient:
                    continue
                message = "Google Cloud Translation could not translate the requested text."
                if _is_content_caused_error(error):
                    raise _request_failure(
                        _ContentCausedRequestError, message, "invalid_request", texts,
                        attempts + waits, self._deadline_seconds, waits, waited,
                    ) from error
                raise failure(_translation_failure_category(error, transient), message) from error

        translations = [translation.translated_text for translation in response.translations]
        if len(translations) != len(texts):
            message = (
                "Google Cloud Translation returned "
                f"{len(translations)} translations for {len(texts)} texts."
            )
            raise TextReplacementProviderError(message)
        return translations

    def _rate_limit_wait(self, previous_waits: int, error: Exception) -> float:
        """Return an exponential wait with downward jitter, or the server's longer delay."""
        delay = min(
            _RATE_LIMIT_MAXIMUM_WAIT_SECONDS,
            _RATE_LIMIT_INITIAL_WAIT_SECONDS * (1 << min(previous_waits, 10)),
        )
        wait = delay * (1 - 0.25 * self._jitter())
        return max(wait, _server_retry_delay(error))

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


_TRANSLATE_ATTEMPT_LIMIT = 3
_RATE_LIMIT_INITIAL_WAIT_SECONDS = 2.0
_RATE_LIMIT_MAXIMUM_WAIT_SECONDS = 60.0


class _ContentCausedRequestError(TextReplacementProviderRequestError):
    """A request failed in a way that its own content could have caused."""


def _request_failure(
    kind: type[TextReplacementProviderRequestError],
    message: str,
    category: str,
    texts: Sequence[str],
    attempted_calls: int,
    deadline_seconds: float,
    rate_limit_waits: int,
    rate_limit_wait_seconds: float,
) -> TextReplacementProviderRequestError:
    """Build a failure whose diagnostic holds counts and settings, never text."""
    return kind(
        message,
        {
            "provider": _PROVIDER_NAME,
            "failure_category": category,
            "attempted_call_count": attempted_calls,
            "attempt_deadline_seconds": deadline_seconds,
            "configured_attempt_limit": _TRANSLATE_ATTEMPT_LIMIT,
            "text_count": len(texts),
            "input_character_count": sum(len(text) for text in texts),
            "rate_limit_waits": rate_limit_waits,
            "rate_limit_wait_seconds": rate_limit_wait_seconds,
        },
    )


def _integer_environment(name: str, default: int, minimum: int, maximum: int) -> int:
    """Read an optional bounded integer setting, failing safely without echoing its value."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    if re.fullmatch(r"[0-9]+", raw) is None or not minimum <= int(raw) <= maximum:
        message = f"{name} must be an integer from {minimum} through {maximum}."
        raise TextReplacementProviderError(message)
    return int(raw)


def _is_usable_translation(translated: str, is_filename: bool) -> bool:
    return bool(translated) and (not is_filename or _is_safe_filename_stem(translated))


def _error_description(error: Exception) -> str:
    """Return lowercase error text for classification only; it is never logged or returned."""
    return f"{error} {getattr(error, 'errors', '')}".casefold()


def _is_daily_limit_error(error: Exception) -> bool:
    return "daily limit exceeded" in _error_description(error)


def _is_rate_limit_error(error: Exception) -> bool:
    name = type(error).__name__
    if name in {"TooManyRequests", "ResourceExhausted"}:
        return True
    description = _error_description(error)
    return name == "Forbidden" and (
        "user rate limit exceeded" in description or "ratelimitexceeded" in description
    )


def _is_content_caused_error(error: Exception) -> bool:
    return type(error).__name__ in {"InvalidArgument", "BadRequest"}


def _server_retry_delay(error: Exception) -> float:
    """Return a server-supplied retry delay in seconds, or 0 when none is present.

    gRPC errors carry a ``RetryInfo`` entry in ``details`` (``retry_delay`` is a protobuf
    Duration); REST errors carry a ``Retry-After`` header on the response. Neither is always
    sent, and a value that is missing or unparseable (such as an HTTP date) is ignored.
    """
    delays: list[float] = []
    try:
        for detail in getattr(error, "details", None) or ():
            retry_delay = getattr(detail, "retry_delay", None)
            if retry_delay is not None:
                delays.append(
                    float(retry_delay.total_seconds())
                    if hasattr(retry_delay, "total_seconds")
                    else float(retry_delay.seconds) + float(retry_delay.nanos) / 1e9
                )
        headers = getattr(getattr(error, "response", None), "headers", None)
        header_value = headers.get("Retry-After") if headers is not None else None
        if isinstance(header_value, str) and re.fullmatch("[0-9]+", header_value.strip()):
            delays.append(float(header_value))
    except (AttributeError, TypeError, ValueError):
        return 0.0
    return max((delay for delay in delays if delay > 0), default=0.0)


def _is_timeout_error(error: Exception) -> bool:
    return type(error).__name__ in {"DeadlineExceeded", "TimeoutError"}


def _is_transient_translation_error(error: Exception) -> bool:
    return _is_timeout_error(error) or type(error).__name__ in {
        "ServiceUnavailable", "InternalServerError",
    }


def _translation_failure_category(error: Exception, transient: bool) -> str:
    if _is_timeout_error(error):
        return "timeout"
    if transient:
        return "transient_transport_failure"
    return "non_transient_api_failure"


def create_provider() -> TextReplacementProvider:
    """Create the provider selected by this package's directory name."""
    return GoogleCloudTranslateProvider()


def _load_configuration() -> _Configuration:
    """Validate the local credential-file and endpoint configuration before a request."""
    credential_path = os.environ.get(_CREDENTIALS_ENVIRONMENT_VARIABLE, "").strip()
    if not credential_path:
        message = "Google Cloud Translation requires project and service-account credential configuration."
        raise TextReplacementProviderError(message)

    credential_project_id = _validate_service_account_credential(Path(credential_path))
    project_id = os.environ.get(_PROJECT_ENVIRONMENT_VARIABLE, "").strip() or credential_project_id
    if not project_id:
        message = "Google Cloud Translation requires project and service-account credential configuration."
        raise TextReplacementProviderError(message)
    location = os.environ.get(_LOCATION_ENVIRONMENT_VARIABLE, "").strip() or _DEFAULT_LOCATION
    if not location.casefold().startswith("europe-"):
        message = "Google Cloud Translation supports only global or continental-European locations."
        raise TextReplacementProviderError(message)
    return _Configuration(project_id, location, _EU_ENDPOINT)


def _validate_service_account_credential(credential_path: Path) -> str | None:
    """Return an optional service-account project ID without exposing credential data."""
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
    project_id = credential_data.get("project_id")
    return project_id.strip() if isinstance(project_id, str) and project_id.strip() else None


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


def _is_safe_filename_stem(stem: str) -> bool:
    return bool(stem) and stem not in {".", ".."} and "\x00" not in stem and "/" not in stem and "\\" not in stem


def _validate_filename_stem(stem: str) -> None:
    """Reject a translated filename stem that cannot safely become a destination file."""
    if not _is_safe_filename_stem(stem):
        message = "Google Cloud Translation returned an unsafe translated filename stem."
        raise TextReplacementProviderError(message)
