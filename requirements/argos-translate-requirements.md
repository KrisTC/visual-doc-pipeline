# Argos Translate Requirements

Argos Translate provider behaviour.

## FR-2026-08-04-12

| Property | Value |
|----------|-------|
| Title | Translate text and filenames with Argos Translate |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-04 |
| Related Requirements | FR-2026-08-02-06, FR-2026-08-03-03, SR-2026-08-01-01 |

### Description

The default text-replacement provider factory shall discover an `argos_translate` provider. The provider shall use the Argos Translate Python library to translate ordinary text from the request's source BCP 47 language tag to its target BCP 47 language tag.

For filename requests, the provider shall translate the filename while retaining a safe filename and the source file extension. The existing folder-replacement collision and output-root safety checks shall continue to apply.

### Rationale

An offline translation provider enables the existing visible-text and folder-replacement pipeline to produce translated text and translated output filenames without using a remote translation service.

### Notes

The provider shall reduce a source or target BCP 47 tag to its lowercase primary-language subtag when selecting Argos packages. It shall download missing language packages on demand from Argos Translate's default official package index and use the library's default local package and download-cache locations. A package-index refresh, package download, package installation, or translation failure shall raise `TextReplacementProviderError`; the provider shall not use a different package index or remote translation service as a fallback.

The provider shall support every source-to-target route that the installed Argos package graph can perform, including Argos's intermediate-language pivot routes. If no installed or downloadable route can provide the requested translation, it shall raise `TextReplacementProviderError`.

Argos does not provide a calibrated translation-confidence score. The provider shall return normalized confidence `0.0` for successful translations to represent unavailable confidence, rather than implying translation quality.

For filename requests, the provider shall translate only the filename stem and append the original suffix unchanged. It shall reject an empty translated stem or a translated stem containing a path separator, NUL character, `.` or `..`, by raising `TextReplacementProviderError`.

The provider shall participate in automatic local text-replacement evaluation artifacts. Those evaluations may acquire missing Argos language packages from Argos Translate's default official package index; translation input and replacement text shall continue to be processed locally and shall not be sent to that index. The provider factory shall expose the eligible subset of providers so evaluators do not hard-code provider names.

Provider-owned behavioural tests shall use synthetic text and filename cases with a mocked Argos library. They shall not depend on model downloads, sample data, or confidential inputs. The generic response-shape contract test shall show `argos_translate` as an individually skipped case because automated tests shall not acquire dynamic model artifacts; provider-owned tests shall cover its stable result shape as well as its behaviour.

---
