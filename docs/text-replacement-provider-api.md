# Text-replacement provider API

A text-replacement provider implements `TextReplacementProvider`: it receives one `TextReplacementRequest` holding a batch of texts and returns one `TextReplacementResult` holding one item per text. A single text is a batch of one. The default factory discovers providers below `pipeline/text_replacement_plugins/`.

`replace` is the only method a provider implements to replace text. The pipeline lists the texts of a document first and sends them to the provider in batches, so a remote provider can translate many texts per call.

**Breaking change from the single-text API.** A provider used to receive one `text` and return one `text`, `confidence` and `extra`. It now receives `texts` and returns `items`. To migrate a provider that handles one text at a time, move its per-text logic into a function that returns a `TextReplacementItem` and call `replace_each` (see the worked example below). All other provider rules, including filename handling, confidence and error behaviour, apply to each text independently and are unchanged.

## Task model

`TextReplacementRequest` contains:

| Property | Type | Contract |
|---|---|---|
| `texts` | `tuple[str, ...]` | The strings to replace: a non-empty tuple of strings, so a request is never empty. |
| `is_filename` | `bool` | Whether every text is a filename and needs filename-specific handling. One request is all filenames or none. |
| `source_language` | `str` | A non-empty source BCP 47 language tag, such as `en` or `ja`. |
| `target_language` | `str` | A non-empty requested target BCP 47 language tag, such as `en` or `ja`. |

A request has one language pair and one filename flag, so a provider never needs to group its texts. Construction raises `ValueError` for an empty tuple, a non-string text or a blank language tag.

`TextReplacementResult` contains `items`, a tuple with exactly one `TextReplacementItem` per request text, in the same order. Each `TextReplacementItem` contains:

| Property | Type | Contract |
|---|---|---|
| `text` | `str` | The replacement string. |
| `confidence` | `float` | A normalized value from `0.0` to `1.0`, inclusive. Its meaning is provider-defined; scores from different providers are not necessarily calibrated alike. |
| `extra` | `dict[str, object]` | Optional provider-specific data. It defaults to `{}` and must not be required by pipeline consumers or other providers. |

Provider failures must raise `TextReplacementProviderError` and must not return a partial result. A provider may recover an individual text internally. A result whose length differs from the request's text count is a provider error: the code that receives it (every wrapper and the translation engine) rejects it with a diagnostic that contains counts only, never text. `check_result_length(count, result)` applies that check. A request for an unavailable provider raises `TextReplacementProviderNotFoundError`.

## Helpers

These are plain functions in `pipeline.text_replacement`, not base classes:

| Helper | Use |
|---|---|
| `replace_each(request, function)` | Applies a per-text function returning a `TextReplacementItem` to each request text in order and builds the result. Use it when a provider handles one text at a time. |
| `replace_text(provider, text, *, is_filename, source_language, target_language)` | Replaces one text as a batch of one and returns its `TextReplacementItem`. It is for texts that are inherently alone, such as a filename, and for the engine's fallback when a plan missed a text. It is not part of the provider API. |
| `batch_limits_of(provider)` | Returns a provider's optional `BatchLimits`, or `None`. |

## Batch limits

A provider may expose an optional `batch_limits` attribute holding a `BatchLimits` value with three optional fields, each unset when the provider has no such limit:

| Field | Meaning |
|---|---|
| `max_items` | The most texts the provider accepts in one request. |
| `target_characters` | A soft character target per request. A single text longer than the target is sent alone. |
| `max_characters` | A hard maximum of characters per request, counted as Python string code points. |

A provider with no `batch_limits` has no limit. The translation engine reads the limits to pack the document's unique texts into requests, so a provider normally does not split requests itself. A provider that sends several remote calls for one request (as `google_cloud_translate` does when a request exceeds its own limits) still returns one result for the whole request. Every wrapper provider forwards the wrapped provider's `batch_limits`.

A provider that waits for a remote rate limit may report each wait with `notify_rate_limit_wait(seconds)`, so the progress display can show "Waiting for translation quota". Report the wait count and length only, never request text.

## Worked example: a minimal provider

A provider that handles one text at a time writes a per-text function and lets `replace_each` build the batch result:

```python
from pipeline.text_replacement import (
    TextReplacementItem,
    TextReplacementProvider,
    TextReplacementRequest,
    TextReplacementResult,
    replace_each,
)


class ExampleProvider:
    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        return replace_each(request, self._replace_one)

    def _replace_one(self, text: str) -> TextReplacementItem:
        return TextReplacementItem(text=text, confidence=1.0)


def create_provider() -> TextReplacementProvider:
    return ExampleProvider()
```

A provider that can translate many texts in one call builds the result itself and states its limits:

```python
from pipeline.text_replacement import BatchLimits, TextReplacementItem, TextReplacementRequest, TextReplacementResult


class RemoteExampleProvider:
    batch_limits = BatchLimits(max_items=100, target_characters=5000, max_characters=20000)

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        translated = self._translate_many(request.texts, request.source_language, request.target_language)
        return TextReplacementResult(tuple(TextReplacementItem(text, 0.0) for text in translated))
```

`_translate_many` stands for the provider's own remote call; it must return exactly one string per text, in order.

## Provider package shape

Each provider is one direct-child Python package in `pipeline/text_replacement_plugins/`. Its directory basename is its sole factory-visible name; providers do not declare a `name` attribute and do not register themselves with the factory.

The package's `__init__.py` must expose a zero-argument `create_provider()` function. Discovery retains that creator and does not instantiate a provider until `TextReplacementProviderFactory.create(name)` is called, so each request receives a fresh provider.

For a provider in `pipeline/text_replacement_plugins/example/`, the factory-visible name is `example`. Names are unique by filesystem construction; the factory does not perform duplicate-name detection.

The package docstring is its optional human-readable description. The factory exposes the trimmed, dedented descriptions through the read-only `provider_descriptions` mapping, keyed by provider name. `provider_names` returns all discovered names in deterministic order.

## Local evaluation eligibility

A package may define the module-level boolean `LOCAL_EVALUATION_ELIGIBLE`. It defaults to `True`; `TextReplacementProviderFactory.local_evaluation_provider_names` returns the eligible subset for automatic local evaluators. This allows evaluators to avoid hard-coding provider names.

Eligibility is an explicit provider decision, not a proxy for whether a provider has dynamic artifacts. For example, `argos_translate` is eligible: it may obtain missing Argos language packages from Argos's official package index during local evaluation, while translation input and output remain local. Its generic contract-test case is skipped because that test suite does not acquire model artifacts.

## Optional provider information and tests

Use `extra` only for optional provider-specific information. No shared schema is prescribed; a consumer must explicitly understand a provider's documented data and otherwise safely ignore absent or unknown values. `text` and `confidence` remain the normalized result and must not be redefined through `extra`.

The generic contract test checks only the stable result shape. Each provider must add behavioural tests with independently specified expected output; semantic validation is necessarily provider-specific for translation and other replacement tasks.

## Optional result-cache identity

When `PIPELINE_PLUGIN_CACHE=1` is set and a source-processing operation supplies
a source-cache scope, the provider factory can wrap a plugin in a transparent
result-cache proxy. The cache is per text: the proxy derives one key for each
text of a request, reads all of them in one transaction, forwards only the
misses to the provider as one smaller request in the original order, and stores
each successful item under its own key. A request whose texts are all hits makes
no provider call, and a failed request stores nothing. Cache keys do not depend
on batch composition or batch limits, so a cache written by the single-text
pipeline still hits. A cacheable package exposes a no-argument module-level
`cache_identity()` function that returns a non-empty compatibility identifier.
Change it whenever an output-affecting implementation, model, or configuration
change makes old replacements unsafe to reuse. A package without this function
is used normally without result caching.

## Built-in providers

### Deterministic providers

Each deterministic provider supports every language pair, returns confidence `1.0` with no extra data, and preserves filename inputs unchanged. For ordinary text, masking providers preserve every Unicode whitespace character exactly, as determined by Python `str.isspace()`, including non-breaking and ideographic spaces, tabs, and line breaks.

| Provider | Ordinary text result |
|---|---|
| `identity` | Original text unchanged. |
| `character_mask` | One `#` per non-whitespace Python character. |
| `double_character_mask` | Two `#` characters per non-whitespace Python character. |
| `half_character_mask` | For each contiguous non-whitespace sequence, half as many `#` characters, rounded down, with at least one. |

### `argos_translate`

`argos_translate` translates ordinary text with the Argos Translate Python library. It reduces BCP 47 tags to lowercase primary-language subtags when selecting packages and supports installed direct and pivot routes. When needed, it refreshes and downloads packages only from Argos's default official package index and uses Argos's default local package and download-cache locations. It raises `TextReplacementProviderError` for package-index refresh, download, installation, translation, or unavailable-route failures, and does not fall back to another index or a remote translation service.

Argos has no calibrated translation-confidence score, so successful translations return confidence `0.0`. Empty text and requests whose source and target primary-language subtags match are returned unchanged with confidence `0.0`.

For filenames, it translates only the stem, retains the original suffix unchanged, and rejects an empty or unsafe translated stem. An unsafe stem includes `.` or `..`, a path separator, or a NUL character.

### `google_cloud_translate`

`google_cloud_translate` is the Google Cloud Translation Advanced v3 provider defined by FR-2026-08-24-04. It translates ordinary text through the configured Google Cloud project using Application Default Credentials. It returns confidence `0.0`, because Cloud Translation does not supply a calibrated translation-confidence score. Empty text and case-insensitively equal source and target language tags are returned unchanged without an API call.

The provider derives its project from the service-account credential JSON when `GOOGLE_CLOUD_PROJECT` is unset; a non-empty environment value is an explicit override. It uses `europe-west1` with `translate-eu.googleapis.com` when `GOOGLE_CLOUD_TRANSLATION_LOCATION` is unset. Set that variable to another supported continental-European location, such as `europe-west3`, to select that EU resource location. Google's [Global and multi-regional endpoints documentation](https://docs.cloud.google.com/translate/docs/advanced/endpoints) describes the required endpoint and location pairing, along with the EU data-residency behavior.

It translates a batch with one synchronous `translateText` call (FR-2026-10-22-02), sending the texts as `text/plain` `contents`, and never uses `batchTranslateText` or `translateDocument`. It exposes `batch_limits` of 1,024 texts, a soft target of 5,000 characters and a hard maximum of 30,000 characters per call, and splits a larger request into several calls. A text longer than the hard maximum is rejected. If a response item is missing or empty, it retries that text alone; if a multi-text call fails because of its content, it bisects the call to isolate the offending text. Authentication, authorization, configuration and daily-quota failures fail immediately. A per-minute quota response (`429`, or a `403` for `User Rate Limit Exceeded`) is waited out with exponential backoff instead of failing; see [Google Cloud setup](google-cloud-setup.md#batching-deadlines-and-quota) for the limits, deadline and environment variables.

Google's [Cloud Translation data usage FAQ](https://docs.cloud.google.com/translate/data-usage) describes its request-data handling. Provider configuration and credentials must comply with SR-2026-08-24-01. The provider uses a service-account Application Default Credentials JSON file identified by `GOOGLE_APPLICATION_CREDENTIALS`; it does not support `GOOGLE_API_KEY`. In the Google Cloud project role picker, assign that service account **Cloud Translation API User** (`roles/cloudtranslate.user`), not the Viewer, Editor, or Admin role. `scripts/configure_google_cloud_translation.py` validates the supplied local credential with synthetic text and writes its quoted forward-slash path and any non-default location setting to `.env.local` only after successful validation. The provider is not eligible for automatic local evaluation, but it may process confidential samples when the user requests it under the repository's documented-external-service policy. See [Google Cloud setup](google-cloud-setup.md) for the local configuration command.
