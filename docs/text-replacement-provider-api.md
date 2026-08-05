# Text-replacement provider API

A text-replacement provider implements `TextReplacementProvider`: it receives one `TextReplacementRequest` and returns one `TextReplacementResult`. The default factory discovers providers below `pipeline/text_replacement_plugins/`.

## Task model

`TextReplacementRequest` contains:

| Property | Type | Contract |
|---|---|---|
| `text` | `str` | The string to replace. |
| `is_filename` | `bool` | Whether `text` is a filename and needs filename-specific handling. |
| `source_language` | `str` | A non-empty source BCP 47 language tag, such as `en` or `ja`. |
| `target_language` | `str` | A non-empty requested target BCP 47 language tag, such as `en` or `ja`. |

`TextReplacementResult` contains:

| Property | Type | Contract |
|---|---|---|
| `text` | `str` | The replacement string. |
| `confidence` | `float` | A normalized value from `0.0` to `1.0`, inclusive. Its meaning is provider-defined; scores from different providers are not necessarily calibrated alike. |
| `extra` | `dict[str, object]` | Optional provider-specific data. It defaults to `{}` and must not be required by pipeline consumers or other providers. |

Provider failures must raise `TextReplacementProviderError`. A request for an unavailable provider raises `TextReplacementProviderNotFoundError`.

## Provider package shape

Each provider is one direct-child Python package in `pipeline/text_replacement_plugins/`. Its directory basename is its sole factory-visible name; providers do not declare a `name` attribute and do not register themselves with the factory.

The package's `__init__.py` must expose a zero-argument `create_provider()` function. Discovery retains that creator and does not instantiate a provider until `TextReplacementProviderFactory.create(name)` is called, so each request receives a fresh provider.

```python
from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult
from pipeline.text_replacement.provider import TextReplacementProvider


class ExampleProvider:
    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        return TextReplacementResult(text=request.text, confidence=1.0)


def create_provider() -> TextReplacementProvider:
    return ExampleProvider()
```

For a provider in `pipeline/text_replacement_plugins/example/`, the factory-visible name is `example`. Names are unique by filesystem construction; the factory does not perform duplicate-name detection.

The package docstring is its optional human-readable description. The factory exposes the trimmed, dedented descriptions through the read-only `provider_descriptions` mapping, keyed by provider name. `provider_names` returns all discovered names in deterministic order.

## Local evaluation eligibility

A package may define the module-level boolean `LOCAL_EVALUATION_ELIGIBLE`. It defaults to `True`; `TextReplacementProviderFactory.local_evaluation_provider_names` returns the eligible subset for automatic local evaluators. This allows evaluators to avoid hard-coding provider names.

Eligibility is an explicit provider decision, not a proxy for whether a provider has dynamic artifacts. For example, `argos_translate` is eligible: it may obtain missing Argos language packages from Argos's official package index during local evaluation, while translation input and output remain local. Its generic contract-test case is skipped because that test suite does not acquire model artifacts.

## Optional provider information and tests

Use `extra` only for optional provider-specific information. No shared schema is prescribed; a consumer must explicitly understand a provider's documented data and otherwise safely ignore absent or unknown values. `text` and `confidence` remain the normalized result and must not be redefined through `extra`.

The generic contract test checks only the stable result shape. Each provider must add behavioural tests with independently specified expected output; semantic validation is necessarily provider-specific for translation and other replacement tasks.

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
