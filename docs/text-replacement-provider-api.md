# Text-replacement provider API

A text-replacement provider implements `TextReplacementProvider`, which receives one `TextReplacementRequest` and returns one `TextReplacementResult`. Built-in and future providers are discovered from `pipeline/text_replacement_plugins/`.

## Task model

`TextReplacementRequest` contains:

| Property | Type | Contract |
|---|---|---|
| `text` | `str` | The string to replace. |
| `is_filename` | `bool` | Whether `text` is a filename and should receive filename-specific handling. |
| `source_language` | `str` | A non-empty source BCP 47 language tag, such as `en` or `ja`. |
| `target_language` | `str` | A non-empty requested target BCP 47 language tag, such as `en` or `ja`. |

`TextReplacementResult` contains:

| Property | Type | Contract |
|---|---|---|
| `text` | `str` | The replacement string. |
| `confidence` | `float` | A value from `0.0` to `1.0`, inclusive. Higher confidence is provider-defined; scores from different providers are not necessarily calibrated alike. |
| `extra` | `dict[str, object]` | Optional provider-specific data. It defaults to `{}` and must not be required by pipeline consumers or other providers. |

## Provider plugin shape

Each module in `pipeline/text_replacement_plugins/` provides a `register_providers(factory)` function. Register a constructor rather than an instance so the factory creates a fresh provider when requested.

```python
from pipeline.text_replacement.factory import TextReplacementProviderFactory
from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult


class ExampleProvider:
    name = "example"

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        return TextReplacementResult(text=request.text, confidence=1.0)


def register_providers(factory: TextReplacementProviderFactory) -> None:
    factory.register(ExampleProvider.name, ExampleProvider)
```

Provider names must be unique. The factory rejects duplicate names and raises `TextReplacementProviderNotFoundError` when a requested provider is unavailable.

## Optional provider information

Use `extra` for optional information that may enrich a future interactive viewer or another provider-specific consumer, without changing the stable replacement contract. For example, a translation provider may return details that help explain a translation or present word-to-word correspondences when its underlying model supplies them.

No schema is prescribed for this information: not every provider can produce it, and its meaning may differ by provider and model. A consumer that wants to use it must explicitly understand the provider's documented data; all other consumers must treat it as optional and safely ignore absent or unknown values. Keep `text` and `confidence` as the normalized replacement result rather than using `extra` to alter their meaning.

The generic contract test checks only the stable result shape. Each provider must add its own behavioural tests with independently specified expected output; semantic validation is necessarily provider-specific for translation and other replacement tasks.
