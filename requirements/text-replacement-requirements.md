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
| Related Requirements | FR-2026-08-01-02 |

### Description

The product pipeline shall define a text-replacement task abstraction, including request and response models, a provider API, and a provider factory. The factory shall discover provider plugins from the default codebase directory `pipeline/text_replacement_plugins/` and make each provider available under its declared name.

A text-replacement request shall accept a string of text, a boolean that indicates whether that text is a filename, a source-language BCP 47 tag, and a requested target-language BCP 47 tag. A text-replacement response shall contain the replacement string, normalized confidence from `0.0` to `1.0` inclusive, and an optional dictionary of provider-specific extra data.

The initial provider, named `character_mask`, shall support all language-tag pairs. For non-filename input, it shall replace every non-whitespace character with `#` while preserving every Unicode whitespace character exactly, including ordinary, non-breaking, and ideographic spaces, tabs, and line breaks. Whitespace is defined by Python `str.isspace()`. It shall preserve the input string's Python character length. For filename input, it shall return the input unchanged. In both cases it shall return confidence `1.0` and no extra data.

This feature shall only provide the pipeline-library abstraction and initial plugin. It shall not yet integrate text replacement with document, image, or OCR processing.

### Rationale

The pipeline needs a stable, interchangeable boundary for translation and other visible-text replacement tasks before replacement is integrated with document processing.

### Notes

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
