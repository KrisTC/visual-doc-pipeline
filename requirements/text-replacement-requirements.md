# Text-Replacement Requirements

Text-replacement provider contracts and provider-specific test support.

## FR-2026-08-02-06

| Property | Value |
|----------|-------|
| Title | Pluggable text-replacement API |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-02 |
| Related Requirements | FR-2026-08-01-02, FR-2026-10-22-01 |

### Description

The product pipeline shall define a text-replacement task abstraction, including request and response models, a provider API, and a provider factory. The factory shall discover provider plugins from the default codebase directory `pipeline/text_replacement_plugins/` and make each provider available under its declared name.

A text-replacement request shall accept a string of text, a boolean that indicates whether that text is a filename, a source-language BCP 47 tag, and a requested target-language BCP 47 tag. A text-replacement response shall contain the replacement string, normalized confidence from `0.0` to `1.0` inclusive, and an optional dictionary of provider-specific extra data.

The initial provider, named `character_mask`, shall support all language-tag pairs. For non-filename input, it shall replace every non-whitespace character with `#` while preserving every Unicode whitespace character exactly, including ordinary, non-breaking, and ideographic spaces, tabs, and line breaks. Whitespace is defined by Python `str.isspace()`. It shall preserve the input string's Python character length. For filename input, it shall return the input unchanged. In both cases it shall return confidence `1.0` and no extra data.

This feature shall only provide the pipeline-library abstraction and initial plugin. It shall not yet integrate text replacement with document, image, or OCR processing.

### Rationale

The pipeline needs a stable, interchangeable boundary for translation and other visible-text replacement tasks before replacement is integrated with document processing.

### Notes

FR-2026-10-22-01 supersedes this requirement's single-string request and single-item response shapes with a batch request and result. Its factory, discovery, unique-name, error, and `character_mask` per-text behaviour clauses remain in force and apply to each text of a batch.

Provider names shall be unique. The factory shall reject duplicate names and raise a distinct error when a requested provider is unavailable. Provider failures shall raise a distinct provider error.

The test suite shall include generic model, factory, and response-shape contract tests. It shall also include provider-owned behavioural tests with known inputs and expected outputs. The generic contract test shall not delegate semantic validation to a provider, because semantic correctness cannot be established generically for translation or other future replacement providers.

---

## FR-2026-08-02-11

| Property | Value |
|----------|-------|
| Title | Add deterministic text-replacement test providers |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-02 |
| Related Requirements | FR-2026-08-02-06, FR-2026-08-02-10 |

### Description

The default text-replacement provider factory shall additionally discover three deterministic providers, each of which supports every language-tag pair and returns confidence `1.0` with no extra data:

- `identity` shall return input text unchanged.
- `double_character_mask` shall replace each non-whitespace input character with two `#` characters and preserve every Unicode whitespace character exactly, as defined by Python `str.isspace()`.
- `half_character_mask` shall preserve every Unicode whitespace character exactly, as defined by Python `str.isspace()`. For each contiguous sequence of non-whitespace input characters, it shall return `#` characters equal to half that sequence's Python character length, rounded down, with a minimum of one.

### Rationale

Deterministic same-length, longer, and shorter outputs make the local visual evaluator exercise the text-region renderer's fitting behaviour without depending on a translation service.

### Notes

For requests where `is_filename` is true, every provider shall return the input text unchanged. For non-filename whitespace-only input, every deterministic provider shall return the input unchanged.

The providers shall have provider-owned behavioural tests and continue to participate in the existing generic provider contract tests.

---

## FR-2026-10-22-01

| Property | Value |
|----------|-------|
| Title | Replace a batch of texts with one provider call |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request: batch text replacement (`docs/batch-text-replacement-plan.md`) |
| Date Added | 2026-10-22 |
| Related Requirements | FR-2026-08-02-06, FR-2026-08-02-11, FR-2026-08-27-10, FR-2026-10-22-02, FR-2026-10-22-04, FR-2026-10-22-06 |

### Description

The text-replacement provider API shall replace a batch of texts in one call. A request shall carry a non-empty tuple of one or more texts, one boolean that indicates whether those texts are filenames, one source-language BCP 47 tag, and one target-language BCP 47 tag. A result shall carry one item per request text, in the same order and of the same length. Each item shall carry the replacement string, normalized confidence from `0.0` to `1.0` inclusive, and an optional dictionary of provider-specific extra data, as FR-2026-08-02-06 defined for a single response. This requirement supersedes FR-2026-08-02-06's single-string request and single-response shapes. Every other clause of FR-2026-08-02-06 and FR-2026-08-02-11, including per-text provider behaviour, remains in force and applies to each text independently.

`replace` shall be the only method a provider implements to replace text. A single text is a batch of one.

A provider failure shall raise the existing provider error and shall not return a partial result. A provider may recover an individual text internally. A result whose length differs from the request's text count shall be treated as a provider error by the code that receives it, including every wrapper and the translation engine of FR-2026-10-22-04. Its diagnostic shall contain counts only and never request or result text.

A provider may expose an optional `batch_limits` value stating its maximum item count, its soft target character count, and its hard maximum character count per request. Each limit may be unset. A provider with no `batch_limits` value has no limit. Every wrapper provider shall forward the wrapped provider's `batch_limits`.

The project shall provide a shared plain helper, `replace_each(request, function)`, that applies a per-text function to each request text in order and builds the result, so that a provider which handles one text at a time needs no batch code. It shall not be a base class. `identity`, `character_mask`, `double_character_mask`, `half_character_mask`, and `argos_translate` shall use it or be equivalent to it, with unchanged per-text output, confidence, and extra data.

The caching, metering, and contextual wrappers shall implement the batch `replace` and preserve provider metadata.

This is an intentional breaking change to the provider API. `docs/text-replacement-provider-api.md` and the changelog shall describe it, and the provider documentation shall include a worked example of a minimal provider.

### Rationale

Translating a large document string by string takes thousands of sequential remote requests: measured Word, PDF, PowerPoint and Excel documents needed about 6,900, 3,400, 1,800 and 220 requests, at roughly 0.11 to 0.15 seconds each, for strings averaging 11 to 26 characters. A batch `replace` lets a remote provider send many texts per request: measured against the real service, batches of 100 to 1,000 texts translated 90 to 320 times faster than single-text calls. It is the only provider method, so a new provider implements one function, and a provider that handles one text at a time uses `replace_each`. This is a breaking change to the provider API.

### Verification

Automated tests shall use synthetic text only. They shall verify request validation, result length and order, rejection of a wrong-length result with a text-free diagnostic, `replace_each`, `batch_limits` forwarding through every wrapper, and unchanged per-text results for every built-in provider. The generic provider contract tests shall run against the batch API.

---
