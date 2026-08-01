# Feature Requirements

## Requirement Template

---

## FR-YYYY-MM-DD-NN

| Property | Value |
|----------|-------|
| Title | |
| Owner | |
| Status | Implemented |
| Source | |
| Date Added | YYYY-MM-DD |
| Related Requirements | |

### Description

Describe the capability that the system must provide.

### Rationale

Explain why this requirement exists and what problem it solves.

### Notes

Additional context, assumptions, constraints, unresolved questions, or implementation guidance.

---

## FR-2026-08-01-01

| Property | Value |
|----------|-------|
| Title | Prepare OCR-evaluation image inputs |
| Owner | |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-01 |
| Related Requirements | TR-2026-08-01-02 |

### Description

The project shall provide a script that prepares OCR-evaluation inputs in `outputs/evaluations/ocr/input/` from `sample-data/`. The output directory shall mirror the source directory structure, including locally processed confidential samples.

The script shall copy bitmap source files into the mirrored output structure. For each supported document file (PDF, PowerPoint, Word, and Excel), it shall create a corresponding output directory containing every embedded bitmap image found by recursively traversing document structures, including nested objects such as groups and embedded diagrams.

For each processed document, the corresponding output directory shall store a checksum of the source document. If the source checksum has not changed, the script shall skip reprocessing that document.

### Rationale

Preparing a stable, image-only corpus enables a consistent comparison of OCR libraries across standalone images and images embedded in documents, while avoiding repeated extraction of unchanged documents.

### Notes

`outputs/evaluations/*` is ignored by Git. The script may process confidential source documents locally, but all generated outputs remain local and must not be added, staged, committed, or used as committed tests or fixtures.

The source checksum shall use SHA-256 and be stored as `.source.sha256` in the corresponding document output directory. When a source document changes, the script shall delete and recreate that directory. A document with no embedded images shall still have an output directory containing its checksum.

Supported bitmap formats are PNG, JPEG, TIFF, BMP, GIF, and WebP. Bitmap files shall be copied as exact bytes. A document output directory shall use the source document's complete filename, for example `report.pptx/`, to avoid collisions between documents with the same stem.

The initial supported document extensions are `.pdf`, `.docx`, `.pptx`, and `.xlsx`. Legacy Office binary formats (`.doc`, `.ppt`, and `.xls`) are out of scope because they require separate parsing or conversion support.

Embedded vector images and direct vector content in PDF pages are out of scope for this OCR-preparation feature. They shall be considered by a future structured-document processing feature instead.

Extracted images shall be named deterministically as `image-0001.<ext>`, `image-0002.<ext>`, and so on. PDF extraction shall include raster image XObjects in nested Form XObjects and inline images. Office extraction shall recursively follow internal Open Packaging Convention relationships from the package root and extract reachable raster image parts; external relationships and vector image parts shall be ignored.

OCR-evaluation input preparation shall process only source files in the complete subtree of a language-code directory. The script shall discover language-code directories located at either the first or second directory level below `sample-data/`. A language-code directory name shall be a BCP 47 language tag, such as `en`, `ja`, or `en-GB`. This enables downstream OCR validation to determine the expected language from the source hierarchy.

The output hierarchy shall continue to mirror the eligible source hierarchy. The script shall remove a generated output directory, including its contents, only when the corresponding eligible source directory no longer exists. It shall not eagerly remove individual output files that have no matching source file while their containing generated output directory still exists. Cleanup is limited to generated OCR-evaluation input folders and shall not affect source files.

---

## FR-2026-08-01-02

| Property | Value |
|----------|-------|
| Title | Pluggable OCR-provider API |
| Owner | |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-01 |
| Related Requirements | FR-2026-08-01-01 |

### Description

The product pipeline shall define an OCR-task abstraction, including its request and response models, and an OCR-provider API. It shall provide an OCR-provider factory that discovers provider plugins from the default codebase directory `pipeline/ocr_plugins/` and makes each provider available under its declared name. The initial provider shall be PaddleOCR.

An OCR request shall accept a `PIL.Image.Image` and a language. An OCR response shall contain a collection of identified text items. Each item shall include its extracted string, normalized confidence, bounding polygon, and an optional dictionary of provider-specific extra data.

Bounding polygons shall use source-image pixel coordinates, with an origin at the top left. A polygon shall preserve the provider's detected text-region geometry and contain its vertices in reading order around the region. Rectangular provider output shall be represented by its four vertices. Normalized confidence shall be a number from 0.0 to 1.0 inclusive.

The OCR-task abstraction, provider factory, and provider plugins shall be product code in `pipeline/`, not command-line script code in `scripts/`.

### Rationale

A provider abstraction permits the pipeline to use a consistent OCR result model while allowing OCR implementations to be selected by name.

### Notes

"OCI API" in the source request means the OCR-provider factory and OCR-task abstraction, rather than an OCI-related integration.

PaddleOCR may download its official model artifacts when first instantiated. This creates a runtime network and artifact-supply-chain trust boundary that is separate from the project's locked Python dependency policy. Model downloads shall be limited to PaddleOCR's configured official model source and local cache. A failed download shall raise an OCR-provider error without a fallback to an alternative source.

The OCR-task abstraction shall accept BCP 47 language tags. Each plugin shall map them to its own language convention. Output text items have no public identifier. The factory shall reject duplicate provider names and raise a distinct error when a requested provider is unavailable. OCR-provider failures shall raise a distinct provider error.

The test suite shall include a generic OCR-provider contract test that creates its own English and Japanese text images. It shall apply each case to every registered provider that declares support for the corresponding BCP 47 language and is eligible for local contract testing. It shall verify that the expected text is returned with confidence and a valid bounding polygon. The test shall not use sample data, including confidential sample data.

PaddleOCR 3.7.0 and PaddlePaddle 3.3.1 shall be used initially. The project interpreter is pinned to Python 3.13.14, for which PaddlePaddle publishes a compatible wheel. The runtime model cache shall use PaddleOCR's default local cache location. This feature remains dependent on the availability of compatible wheels for the supported platform.

Every provider shall declare the BCP 47 language tags it supports and whether it is eligible for the default local contract test. Remote or credential-dependent providers shall declare themselves ineligible and are excluded from that local test suite.

---
