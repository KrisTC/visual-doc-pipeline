# OCR provider API

An OCR provider implements `OcrProvider`, which receives one `OcrRequest` and returns one `OcrResult`. Built-in and future providers are discovered from `pipeline/ocr_plugins/`.

## Task model

`OcrRequest` contains:

| Property | Type | Contract |
|---|---|---|
| `image` | `PIL.Image.Image` | The input image held in memory. Providers must not require a file path. |
| `language` | `str` | A non-empty BCP 47 language tag, such as `en` or `ja`. A provider maps it to its own native setting. |

`OcrResult.text_items` is a tuple of `OcrText` values. Each `OcrText` has:

| Property | Type | Contract |
|---|---|---|
| `text` | `str` | The extracted string. Preserve the provider's result rather than normalising whitespace or punctuation. |
| `confidence` | `float` | A value from `0.0` to `1.0`, inclusive. Higher is more confident according to that provider. Scores from different providers are not necessarily calibrated alike. |
| `bounding_polygon` | `BoundingPolygon` | The detected text region in source-image pixels. Its `vertices` contain at least three `PixelPoint(x, y)` values around the region. Preserve rotated or irregular geometry; do not replace it with an axis-aligned box. |
| `extra` | `dict[str, object]` | Optional provider-specific data. It defaults to `{}` and must not be required by pipeline consumers or other providers. |

Coordinates have their origin at the source image's top-left corner. A point's `x` increases to the right and `y` increases downward.

## Adding provider-specific data

Keep information that every provider can produce in the standard fields. Put only implementation-specific data in `extra`, using a namespaced key so it cannot collide with another provider's values.

```python
OcrText(
    text="東京",
    confidence=0.98,
    bounding_polygon=polygon,
    extra={
        "paddleocr": {
            "recognition_model": "PP-OCRv6_medium_rec",
            "raw_score": 0.98,
        }
    },
)
```

Consumers must handle absent `extra` keys. Do not use `extra` to change the meaning of `text`, `confidence`, or `bounding_polygon`.

## Provider plugin shape

Each module in `pipeline/ocr_plugins/` provides a `register_providers(factory)` function. Register a constructor rather than an instance so the factory creates a fresh provider when requested.

Providers must also declare `supported_languages` as a `frozenset` of BCP 47 language tags, `supports_local_contract_test` as a boolean, `skipped_local_contract_angles` as a `frozenset` of integer rotations, and `skipped_local_contract_cases` as a `frozenset` of `LocalContractTestSkip` values. The generic synthetic contract test runs every supported English and Japanese case for providers marked `True`. A skipped angle or case is still reported as an individual skipped case; use it only for an explicit, temporary capability limitation. Set `supports_local_contract_test` to `False` for remote or credential-dependent providers; they are excluded from the default local suite.

The contract test renders its phrases with the repository-owned Noto test-font pack in `tests/assets/fonts/`; it never depends on an operating-system font or downloads fonts during a test run. It runs each case across its defined slide-style foreground and background colour combinations.

```python
from pipeline.ocr.factory import OcrProviderFactory
from pipeline.ocr.models import OcrRequest, OcrResult
from pipeline.ocr.provider import LocalContractTestCase, LocalContractTestSkip


class ExampleProvider:
    name = "example"
    supported_languages = frozenset({"en"})
    supports_local_contract_test = True
    skipped_local_contract_angles = frozenset[int]()
    skipped_local_contract_cases = frozenset(
        {
            LocalContractTestSkip(
                LocalContractTestCase("en", "Example Font", 0, "dark"),
                "Explain the temporary provider limitation here.",
            )
        }
    )

    def recognize(self, request: OcrRequest) -> OcrResult:
        # Call the provider and return normalized OcrText values.
        return OcrResult(())


def register_providers(factory: OcrProviderFactory) -> None:
    factory.register(ExampleProvider.name, ExampleProvider)
```

Provider names must be unique. The factory rejects duplicate names and raises `OcrProviderNotFoundError` when a requested provider is unavailable.

## Optional result-cache identity

When `PIPELINE_PLUGIN_CACHE=1` is set and a source-processing operation supplies
a source-cache scope, the provider factory can wrap a plugin in a transparent
result-cache proxy. A cacheable plugin exposes a no-argument module-level
`cache_identity()` function that returns a non-empty compatibility identifier.
Change it whenever an output-affecting implementation, model, or configuration
change makes old OCR results unsafe to reuse. A plugin without this function is
used normally without result caching.
