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

Every provider shall declare the BCP 47 language tags it supports, whether it is eligible for the default local contract test, and any individual cases or angles that are temporarily skipped by that test. Remote or credential-dependent providers shall declare themselves ineligible and are excluded from the default local test suite. A skipped case shall remain visible as an individually skipped subtest, with a provider-declared reason; it shall not be removed from the test matrix.

The generic OCR-provider contract test shall use a repository-owned, test-only Noto Japanese font pack rather than operating-system fonts or runtime font downloads. The pack shall include multiple font faces and its upstream version, source URL, license, and file hashes shall be recorded with the assets. The fonts shall be licensed for redistribution under the SIL Open Font License.

The contract test shall render the English phrase "The quick brown fox jumps over the lazy dog." and the Japanese phrase "素早い茶色の狐が怠惰な犬を飛び越える。" in each applicable font face at rotations of 0, 45, 90, 135, 180, 225, 270, and 315 degrees. For every angle, font, and language, it shall test the full set of slide-style foreground and background colour pairs: black (`#000000`) on white (`#FFFFFF`), white (`#FFFFFF`) on black (`#000000`), white on navy (`#1F4E79`), charcoal (`#1F1F1F`) on pale yellow (`#FFF2CC`), and white on purple (`#7030A0`). It shall continue to verify the expected extracted text, normalized confidence, and bounding polygon without sample data.

For every non-skipped rotated case, the contract test shall verify that the provider's returned text-region polygons overlap the known rendered text region with a mask intersection-over-union score of at least 0.5. This establishes that the detected regions are sufficiently accurate for subsequent text masking or replacement. PaddleOCR shall initially skip 90, 135, 180, and 225 degrees, until rotation handling is implemented. It shall also skip its known unsupported dark-style cases: English Noto Sans JP Bold at 0 and 270 degrees, with white text on a black background.

---

## FR-2026-08-01-03

| Property | Value |
|----------|-------|
| Title | Generate manual OCR-evaluation results and viewer |
| Owner | |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-01 |
| Related Requirements | FR-2026-08-01-01, FR-2026-08-01-02 |

### Description

The project shall provide a command that evaluates every supported bitmap image in `outputs/evaluations/ocr/input/` with every discovered OCR-provider plugin. The input image's enclosing language-code directory shall supply the BCP 47 language passed to the provider.

The command shall use the existing OCR-provider factory and OCR task request and response abstractions in `pipeline/ocr/`. It shall not implement, discover, or invoke provider-specific OCR logic independently.

For each provider, the command shall create a corresponding provider root in `outputs/evaluations/ocr/output/`. Beneath that root, it shall mirror the input hierarchy. For every input image, it shall write a JSON serialization of the normalized OCR response together with a status, a copy of the source image with every detected text region masked in black, and one clipped bitmap image for each detected text region, using that region's bounding box. When a provider does not support an image's language, or when OCR fails for an image with a supported language, the command shall continue evaluating other images and providers, write a JSON file containing only a failed status for that image, and shall not create visual OCR artifacts for that image.

Each provider root shall contain a generated static HTML viewer that lets a user browse that provider's image evaluations, including the input image, masked image, detected-region clips, and OCR result data.

### Rationale

Persisting visual artifacts alongside normalized provider output makes it practical to inspect detection coverage and compare OCR providers against the local, real-data corpus.

### Notes

Evaluation outputs are local generated artifacts and remain ignored by Git. The command may process confidential inputs locally, but it shall not send their contents, paths, metadata, or extracted text to external services or commit them to repository artifacts.

The static viewer may load jQuery from a CDN. The precise success-status JSON shape and generated-file naming shall be defined by the implementation.

Each provider root shall contain a checksum representing its complete evaluation input tree. The command shall skip regenerating a provider's output only when that checksum matches the current input tree and the provider root's `index.html` exists. Removing either the checksum or `index.html` shall force that provider's output to be regenerated.

---

## FR-2026-08-02-01

| Property | Value |
|----------|-------|
| Title | Report OCR-evaluation progress |
| Owner | |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-02 |
| Related Requirements | FR-2026-08-01-03, TR-2026-08-01-01 |

### Description

The OCR-evaluation command shall use Rich to render live terminal progress while it evaluates images. It shall display a progress bar for each folder below an input language-code directory.

### Rationale

OCR evaluation against the local real-data corpus can take substantial time. Folder-level progress gives the user useful visibility into work completed without requiring them to infer it from model output files.

### Notes

Images directly in a language-code directory shall be represented by that language directory's progress bar. Each bar shall aggregate image evaluations across all providers that are not checksum-skipped and shall show the current provider and image. The command shall write a one-line skipped status for each checksum-skipped provider.

---

## FR-2026-08-02-02

| Property | Value |
|----------|-------|
| Title | Present OCR text regions in the evaluation viewer |
| Owner | |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-02 |
| Related Requirements | FR-2026-08-01-03 |

### Description

The static OCR-evaluation viewer shall not render JSON result content inline. For each successful image evaluation, it shall show the detected text-region clips in a table with an image column and an extracted-text column. Each detected region shall occupy one row.

### Rationale

The table gives a compact, legible visual comparison of every detected region and its OCR result without overwhelming the manual-evaluation view with serialized data.

### Notes

The viewer shall retain the input and black-masked comparison images above the table. It shall retain a JSON-result link that opens in a new browser tab, but shall not render JSON content inline.

---

## FR-2026-08-02-03

| Property | Value |
|----------|-------|
| Title | Render OCR-evaluation progress with tqdm |
| Owner | |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-02 |
| Related Requirements | FR-2026-08-02-01 |

### Description

The OCR-evaluation command shall use tqdm, rather than Rich, to render terminal progress.

### Rationale

tqdm provides the compact notebook-style progress display preferred for this command.

### Notes

The command shall render one folder bar at a time, labelled with the folder. It shall show the current provider and image basename in the bar postfix. Each bar shall aggregate all non-cached provider/image evaluations for that folder, and checksum-skipped providers shall be written as one-line status messages.

---

## FR-2026-08-02-04

| Property | Value |
|----------|-------|
| Title | Show OCR confidence in the evaluation viewer |
| Owner | |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-02 |
| Related Requirements | FR-2026-08-02-02 |

### Description

The detected-region table in the static OCR-evaluation viewer shall include a confidence column. Each region's normalized OCR confidence shall be displayed as a percentage rounded to two decimal places.

### Rationale

Displaying normalized confidence beside each detected region helps manual reviewers judge whether recognition quality corresponds with the provider's confidence.

### Notes

Confidence shall be a narrow third column in the existing one-row-per-detected-region table. A normalized confidence of `0.7543` shall display as `75.43%`.

---

## FR-2026-08-02-05

| Property | Value |
|----------|-------|
| Title | Prepare OCR-evaluation inputs before evaluation |
| Owner | |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-02 |
| Related Requirements | FR-2026-08-01-01, FR-2026-08-01-03 |

### Description

The OCR-evaluation command shall run OCR-evaluation input preparation before it discovers or evaluates input images.

### Rationale

Preparing inputs first ensures the evaluation corpus reflects the current eligible sample-data tree without requiring a separate manual command.

### Notes

The command shall invoke preparation internally with `sample-data/` as its source root and pass the evaluation command's `--input-root` value as the preparation output root. It shall add no preparation-specific command-line options. If preparation fails, evaluation shall not start.

---

## FR-2026-08-02-06

| Property | Value |
|----------|-------|
| Title | Pluggable text-replacement API |
| Owner | |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-02 |
| Related Requirements | FR-2026-08-01-02 |

### Description

The product pipeline shall define a text-replacement task abstraction, including request and response models, a provider API, and a provider factory. The factory shall discover provider plugins from the default codebase directory `pipeline/text_replacement_plugins/` and make each provider available under its declared name.

A text-replacement request shall accept a string of text, a boolean that indicates whether that text is a filename, a source-language BCP 47 tag, and a requested target-language BCP 47 tag. A text-replacement response shall contain the replacement string, normalized confidence from `0.0` to `1.0` inclusive, and an optional dictionary of provider-specific extra data.

The initial provider, named `character_mask`, shall support all language-tag pairs. It shall replace every character of non-filename input with `#`, preserving the input string's Python character length. For filename input, it shall return the input unchanged. In both cases it shall return confidence `1.0` and no extra data.

This feature shall only provide the pipeline-library abstraction and initial plugin. It shall not yet integrate text replacement with document, image, or OCR processing.

### Rationale

The pipeline needs a stable, interchangeable boundary for translation and other visible-text replacement tasks before replacement is integrated with document processing.

### Notes

Provider names shall be unique. The factory shall reject duplicate names and raise a distinct error when a requested provider is unavailable. Provider failures shall raise a distinct provider error.

The test suite shall include generic model, factory, and response-shape contract tests. It shall also include provider-owned behavioural tests with known inputs and expected outputs. The generic contract test shall not delegate semantic validation to a provider, because semantic correctness cannot be established generically for translation or other future replacement providers.

---
