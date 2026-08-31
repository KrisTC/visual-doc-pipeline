# Feature Requirements

## Requirement Template

---

## FR-YYYY-MM-DD-NN

| Property | Value |
|----------|-------|
| Title | |
| Owner | KrisTC |
| Status | Proposed |
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
| Owner | KrisTC |
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
| Owner | KrisTC |
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

FR-2026-08-27-04 defines an optional bootstrap that pre-triggers PaddleOCR's
normal model download. PaddleOCR retains ownership of its normal model cache;
the project does not add a separate model cache or model-integrity system.

The OCR-task abstraction shall accept BCP 47 language tags. Each plugin shall map them to its own language convention. Output text items have no public identifier. The factory shall reject duplicate provider names and raise a distinct error when a requested provider is unavailable. OCR-provider failures shall raise a distinct provider error.

The test suite shall include a generic OCR-provider contract test that creates its own English and Japanese text images. It shall apply each case to every registered provider that declares support for the corresponding BCP 47 language and is eligible for local contract testing. It shall verify that the expected text is returned with confidence and a valid bounding polygon. The test shall not use sample data, including confidential sample data.

PaddleOCR 3.7.0 and PaddlePaddle 3.3.1 shall be used initially. The project interpreter is pinned to Python 3.13.14, for which PaddlePaddle publishes a compatible wheel. The runtime model cache shall use PaddleOCR's default local cache location. This feature remains dependent on the availability of compatible wheels for the supported platform.

Every provider shall declare the BCP 47 language tags it supports, whether it is eligible for the default local contract test, and any individual cases or angles that are temporarily skipped by that test. Remote or credential-dependent providers shall declare themselves ineligible and are excluded from the default local test suite. A skipped case shall remain visible as an individually skipped subtest, with a provider-declared reason; it shall not be removed from the test matrix.

The generic OCR-provider contract test shall use a repository-owned Noto Japanese font pack rather than operating-system fonts or runtime font downloads. The pack shall include multiple font faces and its upstream version, source URL, license, and file hashes shall be recorded with the assets. The fonts shall be licensed for redistribution under the SIL Open Font License.

The contract test shall render the English phrase "The quick brown fox jumps over the lazy dog." and the Japanese phrase "素早い茶色の狐が怠惰な犬を飛び越える。" in each applicable font face at rotations of 0, 45, 90, 135, 180, 225, 270, and 315 degrees. For every angle, font, and language, it shall test the full set of slide-style foreground and background colour pairs: black (`#000000`) on white (`#FFFFFF`), white (`#FFFFFF`) on black (`#000000`), white on navy (`#1F4E79`), charcoal (`#1F1F1F`) on pale yellow (`#FFF2CC`), and white on purple (`#7030A0`). It shall continue to verify the expected extracted text, normalized confidence, and bounding polygon without sample data.

For every non-skipped rotated case, the contract test shall verify that the provider's returned text-region polygons overlap the known rendered text region with a mask intersection-over-union score of at least 0.5. This establishes that the detected regions are sufficiently accurate for subsequent text masking or replacement. PaddleOCR shall initially skip 90, 135, 180, and 225 degrees, until rotation handling is implemented. It shall also skip its known unsupported dark-style cases: English Noto Sans JP Bold at 0 and 270 degrees, with white text on a black background.

---

## FR-2026-08-21-01

| Property | Value |
|----------|-------|
| Title | PaddleOCR Windows and accelerator runtime support |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request following Windows PaddleOCR runtime failure |
| Date Added | 2026-08-21 |
| Related Requirements | FR-2026-08-01-02, TR-2026-08-01-01, SR-2026-08-01-01, SR-2026-08-21-01 |

### Description

The PaddleOCR provider shall select its execution device automatically after PaddleOCR has initialized. It shall use NVIDIA GPU 0 when the installed PaddlePaddle runtime is CUDA-enabled and reports an available GPU; otherwise it shall use CPU. GPU acceleration is an opportunistic performance improvement, not a separately guaranteed CI target.

When automatic-engine initialization or inference fails, the provider shall retry the request once with an explicit CPU engine. A failure from that CPU retry shall raise `OcrProviderError` without further fallback.

On Windows CPU inference, the provider shall disable PaddleOCR's OneDNN/MKLDNN execution path and use Paddle's ordinary CPU execution mode. This workaround shall not apply to GPU inference or non-Windows CPU inference.

### Rationale

PaddleOCR documents NVIDIA GPU acceleration and the project now provides a Windows test runner. The pinned Windows CPU runtime fails in OneDNN execution, while the same test input succeeds with OneDNN disabled. Automatic GPU selection preserves available performance improvements without making GPU hardware mandatory.

### Notes

The provider shall not add a device-selection command-line option in this feature. Its automatic GPU choice depends on the PaddlePaddle distribution and the locally installed NVIDIA driver and CUDA runtime. The current CPU-only environment remains valid and shall select CPU. A CUDA-enabled PaddlePaddle distribution may be adopted only when it can comply with the repository's uv lockfile, PyPI-only, no-source-build, and dependency-cooldown policies. The provider shall not import PaddlePaddle separately to probe device availability before PaddleOCR initializes.

Automated tests shall mock Paddle runtime availability and engine behavior to verify device selection, the Windows CPU OneDNN setting, and the single GPU-to-CPU fallback without requiring CUDA hardware. GPU inference verification remains an optional local check on compatible hardware.

---

## FR-2026-08-01-03

| Property | Value |
|----------|-------|
| Title | Generate manual OCR-evaluation results and viewer |
| Owner | KrisTC |
| Status | Proposed |
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
| Owner | KrisTC |
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
| Owner | KrisTC |
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
| Owner | KrisTC |
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
| Owner | KrisTC |
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
| Owner | KrisTC |
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

## FR-2026-08-02-07

| Property | Value |
|----------|-------|
| Title | Include context and clip-local coordinates in OCR-evaluation text clips |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-02 |
| Related Requirements | FR-2026-08-01-03 |

### Description

For every successful detected text region, the OCR-evaluation command shall create its text-region bitmap from the detected region's axis-aligned bounding box expanded by 20 source-image pixels on each side. The crop shall be constrained to the source-image bounds; the command shall not add artificial pixels beyond an image edge.

The successful-result JSON shall retain `bounding_polygon` in source-image pixel coordinates. Each text item shall additionally include `padded_bounding_polygon`, containing the same detected-region vertices translated into the coordinate space of that item's padded text-region bitmap, whose origin is its top-left pixel. Each text item shall also include a relative path to its corresponding padded text-region bitmap.

### Rationale

Small amounts of surrounding source-image context make text-region bitmaps more useful as test inputs. Clip-local coordinates allow downstream processing to select the detected text within those padded bitmaps without recalculating the crop offset.

### Notes

The crop's unpadded bounds shall be calculated from the detected polygon using the current floor/ceiling semantics, before applying the 20-pixel expansion and source-image clipping. A clip that reaches a source-image edge may consequently include less than 20 pixels of context on that side.

The additional JSON polygon shall preserve the provider's vertex order and coordinate precision. Its coordinates shall be calculated by subtracting the padded crop's left and top source-image coordinates from the corresponding `bounding_polygon` coordinates. The existing `bounding_polygon` field shall not change meaning.

The field shall be named `padded_image_path`. It shall be a POSIX-style path relative to the successful-result JSON file's containing directory, so the JSON remains self-contained when its containing output subtree is moved.

---

## FR-2026-08-02-08

| Property | Value |
|----------|-------|
| Title | Handle cached OCR-evaluation artifacts after output-format changes |
| Owner | KrisTC |
| Status | Implemented |
| Source | Implementation review |
| Date Added | 2026-08-02 |
| Related Requirements | FR-2026-08-01-03, FR-2026-08-02-07 |

### Description

The OCR-evaluation command shall automatically regenerate a provider's output when its generated visual-artifact or successful-result JSON format version changes, even if that provider's input-tree checksum matches. It shall store the evaluator-artifact format version in a marker file in the provider output root and consider an output current only when that marker matches the command's current version, as well as satisfying the existing checksum and viewer conditions.

### Rationale

The current cache is based only on input files. Without defined invalidation behaviour, an unchanged input tree causes the command to retain artifacts generated by an older evaluator format, including clips and JSON that lack newly required data.

### Notes

The evaluator-artifact format version shall be incremented whenever a change would make existing generated clips, JSON, or viewer output stale. A provider root created by a prior version has no matching marker and is therefore regenerated once.

---

## FR-2026-08-02-09

| Property | Value |
|----------|-------|
| Title | Estimate, document, and evaluate OCR text-region colours |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-02 |
| Related Requirements | FR-2026-08-01-02 |

### Description

The product pipeline shall provide a library function that accepts the original in-memory image and an OCR text region represented by an `OcrText` value. It shall estimate and return a primary text colour and the immediate background colour behind that text for the region. The function shall use the `OcrText.bounding_polygon` in source-image pixel coordinates and shall not require an image file path. The background is the local label panel or surface behind glyphs when one is present; surrounding image context is fallback evidence only.

The result shall include normalized confidence values for the text-colour and background-colour estimates, and an advisory background classification of `flat`, `gradient`, or `complex`. It shall return the classification and confidence values even when the background is not flat; callers shall not need to use that metadata.

This feature shall estimate colours only. It shall not mask, blur, inpaint, fill, remove, replace, or render text or other image content.

The project shall document the public text-region-colour-estimation API so a developer can use every result property without inspecting the implementation. The documentation shall cover the `TextRegionColourEstimate`, `RgbaColour`, and `BackgroundKind` models and the `estimate_text_region_colours` function.

The project shall also provide a developer-facing design note that explains the colour-estimation algorithm, its decision stages and scoring signals, the rationale and trade-offs for each stage, and known limitations. It shall distinguish current implementation facts from future replacement or reconstruction work.

`RgbaColour` values are non-premultiplied, eight-bit sRGB channel values. `red`, `green`, `blue`, and `alpha` are integers from 0 through 255 inclusive; alpha 0 is fully transparent and alpha 255 is fully opaque. An estimated colour represents the source image's observed stored colour. It is not an inferred colour of an unobserved layer before alpha compositing.

Text-colour and background-colour confidence are normalized heuristic reliability scores from 0.0 through 1.0 inclusive. 0.0 means the estimator found no usable supporting evidence and 1.0 means the strongest evidence available to that estimator; neither value is a probability, an OCR confidence, nor a guarantee of visual correctness. Confidence values are comparable only between estimates from the same estimator version. The documentation shall explain the evidence used for each score and advise callers to review or use a fallback for low-confidence results.

The background classification is advisory. In particular, a representative background colour is not sufficient to reconstruct a `gradient` or `complex` background.

The project shall provide a local command that evaluates colour estimates for every successful OCR-result JSON file in `sample-data/color-detection-examples/` that has an adjacent source image named by removing the `.json` suffix. By default, it shall write one static HTML page per processed JSON file below `outputs/evaluations/color-detection-examples/`, preserving the JSON path relative to the input root and replacing its `.json` suffix with `.html`.

Each generated page shall contain a simple HTML table. The padded text-region bitmap from the existing `padded_image_path` field shall be displayed in a right-aligned text-image cell immediately after the Region column. Each row shall then show its recognized text, followed by the background estimate before the foreground estimate. Each primary-colour cell shall be a colour swatch that displays its compact HTML hexadecimal colour code on the first line and its confidence on the second line. The background cell shall show its `flat`, `gradient`, or `complex` classification on a third line. Opaque colours shall use `#RRGGBB`; non-opaque colours shall use `#RRGGBBAA` to retain alpha. Each recognized-text cell shall use its detected background colour as the CSS background colour and its detected foreground colour as the CSS font colour. The generated HTML shall reference the existing text-region bitmaps through file-relative paths and shall not generate derived bitmap artifacts.

### Rationale

Reliable colour estimates are an enabling capability for later visual-text masking and replacement. Identifying the immediate glyph background, rather than merely the surrounding image context, is necessary for label panels and other strong local surfaces. Clear API documentation and static local pages let developers correctly interpret these estimates and compare them against complex examples without introducing a new rendering or image-processing step.

### Notes

The estimator shall crop context from the original image by expanding the OCR region's axis-aligned bounds by 12 source-image pixels on every side and clipping the crop to the source-image bounds. It shall not add artificial pixels outside the image. The implementation may make this padding caller-configurable while retaining 12 pixels as the default.

The analysis shall operate in a perceptual colour space, initially CIELAB. It shall first identify an immediate background candidate inside the OCR polygon, including a broad, coherent label panel when present. A sufficiently supported alpha-zero surface inside the polygon shall be retained as a transparent background candidate rather than discarded as absent evidence. It shall use outer-ring crop clusters only as fallback evidence. A background candidate's confidence shall reflect its local support and consistency; `complex` classification alone shall not impose a confidence penalty.

The implementation shall derive text candidates from perceptual difference from the dominant immediate background surface, clean candidate masks with small morphology and connected-component filtering, and restrict them to the OCR polygon. Alpha-zero pixels shall not be text candidates. High variation in surrounding or secondary background evidence shall not expand the text-difference threshold sufficiently to absorb a compact, contrasting glyph candidate. It shall select the primary text colour using contrast, stroke-like geometry, core-pixel purity, and separation from competing candidates. When a loose OCR polygon contains both a thin, high-contrast glyph candidate and a lower-contrast fill-like map or design component, its score shall not select the fill-like component solely because it has a thicker interior. Large, fill-like components shall not be selected as text solely because they contrast with surrounding context. Border-like evidence may be used internally to distinguish text fill, but outline and shadow colours are out of scope for the public result.

The background classification shall be based on non-text local pixels: low variation is `flat`; variation adequately represented by a smooth colour gradient is `gradient`; other cases are `complex`. The classification is advisory and shall not perform or prescribe later background reconstruction.

The API documentation may be provided by public model/function docstrings and a repository documentation page. It shall be kept accurate when the public model changes.

The local command shall use the existing OCR JSON shape, `bounding_polygon` source-image coordinates, and clip-local `padded_image_path` values. It shall not run OCR, call external services, modify input files, or process files from `sample-data/confidential/`. A missing paired source image, text-region bitmap, invalid JSON, or failed JSON status shall be reported and skipped while other eligible inputs continue. The HTML generator shall escape recognized text and all generated attribute values. It shall reject an absolute or escaping `padded_image_path` rather than link outside the input tree.

The automated test suite shall use repository-owned synthetic images with known colours and shall verify estimates with declared perceptual colour-distance tolerances. It shall cover flat backgrounds, light and dark text, antialiasing, rotated OCR polygons, gradients, patterned backgrounds, transparency, dark text on a high-variation local background, thin dark text beside a lower-contrast fill-like component, text on a strong label panel, and text with an outline or shadow. Tests for the HTML generator shall create synthetic images and OCR-result JSON in a temporary directory; they shall not use `sample-data/` or other real sample files. The user-supplied colour-detection examples may be used for local manual evaluation, but synthetic cases shall provide the automated oracle.

The initial implementation may use Pillow and NumPy. Adding OpenCV requires a separate dependency change that continues to satisfy the project's dependency-security requirements.

---

## FR-2026-08-02-10

| Property | Value |
|----------|-------|
| Title | Render replacement text into OCR regions with Skia |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-02 |
| Related Requirements | FR-2026-08-02-06, FR-2026-08-02-09 |

### Description

The product pipeline shall provide an in-place image utility, implemented with the `skia-python` binding, that accepts a Pillow `Image.Image`, an `OcrText` region, a `TextRegionColourEstimate`, replacement text, a `skia.Typeface`, and a target-language BCP 47 tag. It shall modify the supplied image directly; callers that need the original shall copy it before calling the utility.

For each call, the utility shall first cover the detected OCR region with the estimate's immediate background colour, removing the original visible text. The background wipe shall extend two source-image pixels outward from the detected polygon to cover antialiased source glyph edges. This wipe-only expansion shall not change the region used to fit or clip the replacement text. It shall then render the replacement text in the estimate's primary text colour. It shall calculate a layout and choose the largest font size that contains the replacement text within the detected OCR region. The layout may wrap text onto more lines or combine detected source lines into fewer lines. It shall respect the region geometry, including rotation, when laying out and rendering text.

The utility shall receive the target language as part of its public API. Language-specific shaping and non-Western layout behaviour are deferred unless separately specified.

The project shall provide a local source-language-to-English replacement evaluation command based on the successful OCR-result JSON and paired source images in `sample-data/color-detection-examples/`. Each eligible successful JSON result shall contain a non-empty top-level `source_language` BCP 47 string. For each eligible text region and each registered text-replacement provider, the command shall obtain the replacement using that source language and the fixed target language `en`, estimate region colours, render the replacement into an image copy, and write a clipped bitmap of the resulting text region. It shall generate a static HTML page with a header row containing the region number, original padded text bitmap, and one rendered text-image column for every registered provider; it shall contain one subsequent row per eligible OCR JSON text item. The page shall display the resulting `source_language→en` direction beside the OCR-result identifier, rather than in its title. Its table shall size to its contents rather than the page width. The command shall not modify inputs and shall not process `sample-data/confidential/`.

### Rationale

The replacement-provider API, OCR geometry, and colour estimates provide the inputs needed to make translated or substituted text visibly fit the source image while avoiding a full-image copy for every individual region.

### Notes

The `skia.Typeface` must be loaded by the caller and may be reused for successive utility calls. No project-wide font abstraction is introduced. Existing Pillow-based test image creation remains unchanged because it is test-fixture generation, rather than a public font or rendering API.

The evaluator shall always render by filling with the representative background colour, including for `gradient` and `complex` classifications. It does not reconstruct the source background and its resulting output is expected to be visually approximate for those cases.

`skia-python` shall be added as a locked dependency only if a compatible binary wheel is available for every supported project platform and Python 3.13. The dependency change shall continue to comply with the existing no-source-build and dependency-cooldown security requirements.

The evaluator shall load its default typeface directly from the committed Noto font assets in `tests/assets/fonts/`, initially the `wght=500` bold variation of `NotoSansJP[wght].ttf`. When the preliminary fit of that face is below 14 pixels, the renderer shall re-fit using the face's `wght=300` variation. It shall not depend on an operating-system font or runtime font download.

The renderer shall calculate fitting and centring from Skia's visible glyph bounds, rather than its full typographic ascent/descent line box. For multiple lines, typographic line advance shall control spacing between baselines but shall not itself reserve top or bottom padding. For OCR regions whose text direction is axis-aligned, the Skia renderer shall place each replacement line on integer source-image pixel coordinates, disable subpixel glyph positioning, enable full hinting and automatic hinting, and use Skia synthetic emboldening. The fitted layout shall measure text with the same font settings used to draw it. For non-axis-aligned regions, it shall retain antialiasing and shall not snap transformed text geometry to the source pixel grid. It shall continue to fit and clip text to the OCR polygon. The initial clarity improvement shall not add an outline or shadow.

For a region whose direction differs from a horizontal or vertical axis by no more than five degrees, the renderer may prefer an upright, pixel-aligned layout only when the complete visible-glyph bounds fit inside the OCR polygon and it does not require a smaller fitted font size than retaining the detected rotation. It shall otherwise preserve the detected rotation.

When determining a region's text direction from an OCR polygon edge, the renderer shall normalize equivalent baseline directions modulo 180 degrees before fitting or upright-angle snapping. Reversing the polygon's baseline edge shall not render text upside down.

The colour estimator shall continue to report observed source colours unchanged. To improve the perceived sharpness of light replacement text on dark surfaces, the renderer shall apply a bounded rendering-only lightness adjustment when the text colour's relative luminance exceeds that of an opaque background whose relative luminance is at most `0.35` by at least `0.15`. The adjustment shall preserve the estimated text colour's hue and alpha and move its HSL lightness 65% of the remaining distance toward white. It shall not make any assumed compositing-background choice for an alpha-zero background, and shall not apply to other foreground/background relationships.

Automated tests shall use synthetic images and fonts only; they shall not use sample data. Tests shall cover in-place modification, background removal, rendered text colour, fitting of both shorter and longer replacement strings, wrapping, rotation, and output bounds. The local command and HTML output shall be verified with temporary synthetic inputs; the supplied examples are for manual visual evaluation only.

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

## FR-2026-08-02-13

| Property | Value |
|----------|-------|
| Title | Generate text-replacement artifacts within OCR evaluations |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-02 |
| Related Requirements | FR-2026-08-01-03, FR-2026-08-02-02, FR-2026-08-02-06, FR-2026-08-02-08, FR-2026-08-02-10 |

### Description

For every successful OCR image evaluation, the OCR-evaluation command shall run a text-replacement artifact stage after writing the current OCR artifacts. The stage shall use the current evaluation's original image, `OcrText` items, and source language. It shall use target language `en`, estimate the colours of every text region, and apply the replacement from every registered text-replacement provider to one image copy per provider. Each provider image shall receive all of its replacements successively, allowing the in-place renderer to produce a complete updated image.

The stage shall create a new generated text-replacement artifact directory alongside the current image artifacts. It shall contain one complete updated PNG per text-replacement provider and a clipped replacement bitmap for every eligible region/provider combination. It shall retain the original padded OCR clip as the table's original-text image.

The text-replacement stage and its report shall skip each OCR text region whose confidence is less than `0.65`. Skipped regions shall remain present in the OCR-result JSON and existing OCR report, but shall not be replaced in complete provider images or appear in the text-replacement table.

The OCR artifact stage and text-replacement artifact stage shall have independent cache freshness markers. A missing or stale OCR viewer or OCR cache marker shall regenerate OCR and all dependent artifacts. A current OCR artifact set with a missing or stale text-replacement viewer or text-replacement cache marker shall retain the saved OCR JSON and OCR artifacts, then regenerate only the text-replacement artifacts and report without calling the OCR provider.

The existing provider-root static OCR viewer shall remain unchanged. Each provider root shall additionally contain a separate static text-replacement results page. For each successful image, that page shall show the original input and one selectable complete-image preview together in one non-wrapping row, each taking half of the available page width. Both images shall use the same `max-width: 100%` sizing rule without forced upscaling. The page shall then show a text-replacement table with the region number, original padded text image, and one replacement text-image column for every registered provider. The preview image shall appear above its local dropdown. The dropdown shall select the complete provider image without a page reload; it shall also offer the detected-region mask as its final option. The initial selected option and displayed image shall both be the first registered provider.

Every successful OCR-result JSON file shall include a top-level `source_language` BCP 47 string, equal to the language used in that image's OCR request. Failed JSON results shall remain status-only. The viewer shall display the resulting source-to-target language direction beside each successful OCR result, initially as `source_language→en`.

### Rationale

Running the replacement stage against the full OCR-evaluation corpus tests the renderer with realistic region geometry and demonstrates both individual region results and the complete provider-specific updated image.

### Notes

The OCR and text-replacement artifact stages shall each use independent format-version markers, so a format change invalidates only the stage it affects.

The stage shall use the committed default evaluator typeface and the existing text-region rendering and colour-estimation behaviour. It shall always use the representative background colour, including for gradient and complex classifications.

The command may continue to process confidential samples locally under FR-2026-08-01-03, but it shall not send their content, paths, metadata, OCR text, or replacement text to an external service. Until an explicit local-evaluation eligibility contract exists for text-replacement providers, the stage shall invoke only repository-default providers that execute locally.

Automated tests shall create synthetic OCR inputs, registered local test providers, and temporary output roots. They shall verify source-language JSON output, complete per-provider images, per-region clips, table columns, and provider-preview selection markup without using sample data.

---

## FR-2026-08-03-01

| Property | Value |
|----------|-------|
| Title | Package OCR and text-replacement providers in name-derived directories |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-01-02, FR-2026-08-02-06 |

### Description

The OCR-provider and text-replacement-provider factories shall discover each provider from its own direct-child Python package beneath, respectively, `pipeline/ocr_plugins/` and `pipeline/text_replacement_plugins/`. A provider package shall contain an `__init__.py` discovery entry point, the provider-specific implementation, and any provider-specific supporting code, configuration templates, documentation, or assets needed by that provider. The shared task abstractions and factory code shall remain outside provider packages.

The basename of a provider directory shall be the provider's sole factory-visible name. A provider shall not declare, configure, or otherwise supply a separate name. The factories shall use that directory name when listing, selecting, and reporting the provider.

The factories shall no longer perform duplicate provider-name detection or raise a duplicate-name error. A filesystem directory cannot have two direct children with the same name; therefore the provider-directory structure is the uniqueness mechanism.

Each provider package's `__init__.py` shall expose a zero-argument `create_provider()` function that returns its single OCR or text-replacement provider. The factory shall retain this function during discovery and call it only when that provider is requested. Discovery shall not instantiate providers. Registration functions and provider `name` attributes shall not be part of the provider-plugin contract.

Each provider's optional human-readable description shall be the trimmed, dedented docstring of its `__init__.py` discovery entry point. A missing or empty docstring shall produce no description and shall not prevent the provider from being discovered or used. Each factory shall expose the discovered descriptions as a read-only mapping from provider name to optional description.

All repository-default OCR and text-replacement providers shall be migrated to this directory-per-provider layout.

### Rationale

A self-contained provider directory prevents name collisions by construction and gives contributors a clear boundary for more substantial providers, including cloud-based OCR or translation integrations that need provider-specific code, configuration, and authentication guidance.

### Notes

This requirement supersedes the declared-name and duplicate-name-rejection clauses in FR-2026-08-01-02 and FR-2026-08-02-06. Their request/response models, provider APIs, unavailable-provider errors, provider-failure errors, contract tests, and all other requirements remain unchanged.

Provider-specific dependencies remain subject to the project's existing dependency-management and security requirements. This requirement does not authorize credentials, tokens, or confidential content to be committed, logged, or sent to an external service; separate requirements shall define credential handling and external-service eligibility before a cloud provider is used with local evaluation data.

The selected `__init__.py` and `create_provider()` convention deliberately permits moving an existing single-file plugin into a same-named directory with minimal import churn: for example, `pipeline/ocr_plugins/paddleocr.py` becomes `pipeline/ocr_plugins/paddleocr/__init__.py`. Imports of `pipeline.ocr_plugins.paddleocr` therefore remain valid. The migration shall remove each provider's `name` attribute and replace its `register_providers(factory)` function with `create_provider()`.

Factory tests shall verify that package-directory names determine provider names, that a provider without a `name` attribute is discovered, and that a package docstring supplies its description. Existing unavailable-provider and provider-failure tests shall remain.

---

## FR-2026-08-03-02

| Property | Value |
|----------|-------|
| Title | Use separate background and text passes for complete replacement images |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-02-10, FR-2026-08-02-13 |

### Description

The public text-region-rendering API shall provide separate in-place operations to wipe a text region's background and to render replacement text into a text region. Both operations shall accept and modify the caller-supplied Pillow image without requiring the caller to make an image copy. A caller shall therefore be able to wipe every region in one loop and render every replacement in a second loop.

The public API shall also provide a batch in-place operation that accepts a caller-supplied image and all region, colour-estimate, and replacement-text inputs for one image. The batch operation shall process those regions in two passes: first wipe every region with its estimated immediate background colour, including the existing two-pixel wipe outset; then render every corresponding replacement string into its region. No replacement glyph shall be rendered until the first pass has finished for every eligible region in that complete image.

The OCR-evaluation text-replacement stage shall use the batch operation for each complete provider-specific image.

### Rationale

When detected text regions are close together, the existing per-region wipe-and-render order can allow a later background wipe to cover a replacement glyph rendered for an earlier region. Separating the operations preserves replacement text from later wipes.

### Notes

This requirement supersedes the per-region successive-rendering clause in FR-2026-08-02-13 for complete provider images only. The existing single-region `replace_text_region` public API shall remain as a compatibility convenience that performs its background wipe followed by its text rendering.

The batch operation shall render a complete image through one shared Skia surface, avoiding a full-image conversion and write-back for every region. The separate public operations permit explicit caller-controlled passes but need not have the same whole-image efficiency when called repeatedly.

The ordering of background wipes and the ordering of replacement-text drawing within their respective passes remain the OCR-result item order. Overlapping OCR polygons may still cause one replacement string to draw over another; resolving that geometry conflict is out of scope unless separately specified.

Automated tests shall use synthetic adjacent OCR regions and verify both explicit separate-pass calls and the batch operation: a later background wipe cannot erase a replacement glyph rendered for an earlier region. Tests shall also retain the existing single-region API behaviour.

---

## FR-2026-08-03-03

| Property | Value |
|----------|-------|
| Title | Process a folder of documents and bitmap images for visible-text replacement |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-01-02, FR-2026-08-02-06, FR-2026-08-02-10, FR-2026-08-03-02, TR-2026-08-01-02 |

### Description

The project shall provide a main pipeline command that accepts an input folder and an output folder. It shall recursively discover the supported bitmap and document file types, process every eligible file, and write results beneath the output folder while preserving the input hierarchy. It shall ignore files whose type is not supported.

The command shall accept a text-replacement-provider name, defaulting to `character_mask`; an OCR-provider name, defaulting to `paddleocr`; a required source-language BCP 47 tag; and a target-language BCP 47 tag, defaulting to `en`. It shall replace every eligible visible text item using the selected text-replacement provider. Output filenames shall be passed to the selected text-replacement provider with `is_filename=True` before the output path is determined. Its `--help` output shall display one command-options section containing each option's concise description and default, together with separate, non-duplicative text-replacement-provider, OCR-provider, and document-text-layout reference sections. The provider sections shall list every name discovered from the default plugin directories, with its discovered plugin description when one is declared. The document-text-layout reference section shall list every accepted value; the usage and command-option entry shall use the metavar `LAYOUT` rather than repeat those values. When stdout is an interactive terminal whose `TERM` is not `dumb` and `NO_COLOR` is unset, it shall use ANSI colour without colouring descriptions: section headings shall be bold, option names bold cyan, choice names bold green, and default-value annotations yellow. It shall emit plain text when stdout is not interactive, `TERM` is `dumb`, or `NO_COLOR` is set.

For bitmap images, the command shall use the selected OCR provider, text-region colour estimator, and existing batch text-region renderer to replace detected text. It shall skip a detected text region when its normalized OCR confidence is less than `0.65`; colour-estimate confidence shall not affect eligibility. For supported document files, it shall replace both native editable text and text in every embedded raster bitmap. Native editable text is not subject to an OCR-confidence threshold.

The command shall retain each source document's file format. When a processed output path would collide with an earlier processed output path, it shall append a number to the filename to make the path unique. A failure for one eligible input file shall be reported and shall not prevent the command from processing other eligible input files.

### Rationale

The existing pipeline primitives and local evaluators need a user-facing command that produces complete, replacement-processed copies of an input folder.

### Notes

The existing requirements define supported bitmap formats as PNG, JPEG, TIFF, BMP, GIF, and WebP, and initial document extensions as PDF, DOCX, PPTX, and XLSX.

The command is `scripts/run_folder_replacement.py INPUT_FOLDER OUTPUT_FOLDER`. `--source-language` is required; `--target-language en`, `--ocr paddleocr`, and `--text-replacement character_mask` are its defaults. It exits non-zero if one or more eligible files fail, after continuing to process other files.

The Office implementation processes visible WordprocessingML, DrawingML, SpreadsheetML, and VML text nodes throughout each OOXML package, which covers document body content as well as reachable package parts such as headers, footers, tables, comments, text boxes, grouped-shape text, notes, and shared spreadsheet strings. It processes every embedded raster part under an Office `media` directory.

The PDF implementation rewrites native text-showing operations in page content and reusable Form XObjects, annotation and AcroForm text values, and form appearance streams. It replaces raster image XObjects, including images in Form XObjects. A PDF containing an inline image that cannot be safely rewritten is reported as a failed file; later files continue to be processed.

Native text replacement is applied to individual native text items. Embedded bitmap replacement uses OCR and skips regions with confidence below `0.65`; it ignores colour-estimate confidence.

Automated tests shall use synthetic input folders and files only. They shall cover supported-file discovery, ignored files, output-filename collisions, isolated file failures, confidence gating, native OOXML and PDF text replacement, embedded Office bitmap processing, and the direct-script help entry point, including its non-duplicative provider/layout sections, metavar, coloured-terminal styling, and plain-output behaviour.

No source or output content may be sent to external services. The selected providers must be locally eligible when inputs might contain confidential information.

---

## FR-2026-08-27-01

| Property | Value |
|----------|-------|
| Title | Flatten transparent raster images for OCR using the source page or slide background |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-27 |
| Related Requirements | FR-2026-08-01-02, FR-2026-08-03-03 |

### Description

Before an OCR provider that accepts opaque RGB input receives a raster image with transparency, the pipeline shall alpha-composite a temporary OCR-only copy of the image onto an opaque background and supply the resulting RGB pixels to the provider. It shall not use that flattened copy for colour estimation, replacement rendering, or output encoding; those operations shall continue to use the original source image.

For a raster image embedded in a DOCX document, the pipeline shall use the direct document background colour when it is a valid explicit RGB value. For a raster image embedded in a PPTX document, it shall use the direct slide background colour when it is a valid explicit RGB value and unambiguous for that image. It shall use opaque white when the background colour cannot be determined, including for standalone bitmap input and PDF images. It need not resolve theme colours, inherited backgrounds, or compositing through nested or overlapping images, shapes, or other visual layers.

### Rationale

Palette images can express alpha as per-palette transparency bytes. Direct conversion to RGB discards that alpha and causes Pillow to warn. Flattening an OCR-only copy before OCR removes the warning and gives OCR pixels consistent with the simple visible page or slide background without altering the source image used for replacement output.

### Notes

The scope is limited to preparing raster pixels for OCR. It does not require general document rendering or composition of arbitrary visual layers. It does not change source-image alpha handling during colour estimation or replacement rendering. Automated tests shall use synthetic transparent raster images and synthetic page or slide backgrounds only, and shall verify that the original image is retained for replacement output.

---

## FR-2026-08-03-04

| Property | Value |
|----------|-------|
| Title | Report folder-replacement progress |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-02-03, FR-2026-08-03-03 |

### Description

The folder-replacement command shall use tqdm to render terminal progress while it processes supported input files. It shall render one progress bar at a time for each input folder that contains eligible files, labelled with that folder's path relative to the input root. The bar shall show the basename of the current source file in its postfix.

The command shall print the relative path of each source file when it starts processing it. It shall render one tqdm progress bar for that source file. A bitmap file's bar shall contain one work item. A document file's bar shall contain one native-text work item and one work item for every embedded raster bitmap. A PDF's bar shall additionally contain one vector-content review work item for every page. The document's bar shall advance after each work item completes, allowing a user to see progress through its embedded-image and PDF-vector work.

### Rationale

OCR and later translation can take substantial time. Per-document progress provides visibility through long embedded-image work while retaining the command's isolated per-file failure behaviour.

### Notes

The progress bar shall show its current native-text, embedded-image, or PDF-vector work item in its postfix. Existing one-line per-file failure reporting shall remain visible without stopping later work. A failure shall close that file's bar and later files shall still be processed.

---

## FR-2026-08-03-05

| Property | Value |
|----------|-------|
| Title | Replace editable text in embedded vector graphics directly |
| Owner | KrisTC |
| Status | Implemented |
| Source | Implementation diagnosis |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-03 |

### Description

The folder-replacement pipeline shall replace editable text contained in embedded vector graphics in supported document files by directly updating the vector graphic's native text representation. It shall send each vector-text item to the selected text-replacement provider with `is_filename=False`, the command's source language, and target language.

It shall not use OCR or rasterize a vector graphic to replace its text. It shall preserve the graphic as vector output and retain non-text vector content unchanged.

When a vector graphic's visible text is represented only by paths or outlines, rather than an editable native text representation, the current implementation shall retain it unchanged and report that it was not replaced. Rasterizing it and using the existing bitmap path is deferred to a future requirement.

### Rationale

Visible text may be part of a vector graphic rather than a native document text run or a raster bitmap. Direct native-text replacement preserves the graphic's fidelity and avoids unnecessary OCR cost and recognition errors.

### Notes

The initial supported embedded vector formats are SVG, EMF, and WMF. The implementation shall identify and update their editable native text structures directly. Direct mutation is format-specific; the implementation must not treat the formats as interchangeable.

The initial direct-text implementation supports SVG `text`, `tspan`, and `textPath` content; EMF `EMR_EXTTEXTOUTA` and `EMR_EXTTEXTOUTW` records; and WMF `META_TEXTOUT` and `META_EXTTEXTOUT` records. A vector graphic with none of these editable text structures is retained unchanged and reported as unsupported. Additional vector text-record variants require a future requirement.

The current locked Python image stack has no usable EMF or WMF rasterizer. Implementing the deferred outlined-text fallback requires a separately specified, dependency-policy-compliant renderer and an output-reembedding strategy for replacing the original vector package part with its processed bitmap result.

A renderer that requires a commercial license shall not be used in evaluation mode: generated documents must not contain evaluation watermarks or other licensing artifacts. Its license file, key, or equivalent credential shall not be committed, logged, or included in generated artifacts. The licence configuration and deployment mechanism require a separate approved requirement before such a renderer is added.

---

## FR-2026-08-03-06

| Property | Value |
|----------|-------|
| Title | Comment on unsupported images in Office documents |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-03-05 |

### Description

When processing a Word, Excel, or PowerPoint document, the pipeline shall add a document-native comment for every image whose text cannot be processed. The comment shall state that the image contains text that is not supported yet.

### Rationale

Comments make unreplaced visible text reviewable without altering the source image or silently implying that its content was processed.

### Notes

Before implementation, define which conditions create a comment (for example, a vector with no editable text, OCR failure, or every skipped low-confidence OCR region); the exact comment text; comment author/identity; and the required anchor for Word, Excel, and PowerPoint comments. The implementation shall not replace the requested comment with a visible text box, speaker note, cell value, or other non-comment artifact.

---

## FR-2026-08-03-07

| Property | Value |
|----------|-------|
| Title | Select native document-text layout-preservation mode |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-02-10 |

### Description

The folder-replacement command shall provide a document-text layout mode for native editable text in PDF, DOCX, PPTX, and XLSX output. The mode shall not change the established OCR bitmap replacement path or direct editable-vector-text replacement path.

`preserve-source-formatting` shall be the default. It shall replace native text while retaining the source document's existing font and size. It shall not attempt to resize, reflow, or otherwise fit the replacement text to its original bounds.

`preserve-basic-layout` shall replace text using an appropriate Noto font distributed under the SIL Open Font License and shall adjust font size to fit the replacement text within the source text item's explicit bounding box. It shall favour fitting within the original visible region over retaining the source font or font size. It shall apply to explicitly laid-out native document text and editable vector text, including PowerPoint shapes and grouped shapes, Word text boxes and embedded diagrams, and Excel and PowerPoint drawing text.

Free-flowing Word text, including normal document paragraphs, shall retain source formatting in both modes because it has no stable explicit bounding box to fit. The mode shall not change the established OCR bitmap replacement path.

### Rationale

Source formatting may be essential to a document's design, but translated text can be substantially longer or shorter. An explicit mode lets users choose between source fidelity and a basic readability-oriented fit.

### Notes

The command-line option name and its exact accepted values remain to be defined. The current implementation's native-document replacement behaviour corresponds to `preserve-source-formatting`.

Before implementation, define the bounding-box source and fitting behaviour for each format, including PowerPoint shapes and grouped shapes, Word text boxes and embedded diagrams, Excel cells and drawing text, and PDF content/form/annotation text. Also define the target-language-to-Noto-face mapping, handling when no committed Noto face supports the target language, wrapping, and overflow behaviour when a minimum readable font size cannot fit.

The `preserve-basic-layout` implementation shall use a repository-owned,
redistributable Noto font asset. It shall not depend on operating-system fonts
or runtime font downloads. Additional Noto assets supplied by the local
bootstrap cache of FR-2026-08-27-04 are project-selected assets for this
purpose. The font selection and all fitting calculations shall be deterministic
for the same input, options, and font assets.

Automated tests shall use synthetic documents and fonts only. They shall verify the default mode retains source font settings, the fitting mode selects the specified Noto font and reduces or increases size as needed, and each supported document format's output remains valid.

---

## FR-2026-08-03-08

| Property | Value |
|----------|-------|
| Title | Preserve OOXML markup-compatibility namespace bindings |
| Owner | KrisTC |
| Status | Implemented |
| Source | Implementation diagnosis |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-03 |

### Description

When replacing native text in an OOXML package part, the pipeline shall preserve every namespace binding referenced by Markup Compatibility attributes and elements, including `mc:Choice` `Requires` values and `mc:Ignorable` values. The rewritten part shall retain valid namespace bindings for those references.

### Rationale

OOXML compatibility markup uses prefix-valued attributes whose prefixes may not otherwise appear in an element or attribute name. A generic XML serializer can discard those declarations even though the resulting package still requires them. Preserving the bindings keeps generated Word, Excel, and PowerPoint documents valid and avoids application repair prompts.

### Notes

The implementation shall use only synthetic OOXML package data in automated tests. Tests shall verify that a text-rewritten part containing a compatibility choice still declares the prefix named by its `Requires` value.

---

## FR-2026-08-03-09

| Property | Value |
|----------|-------|
| Title | Replace raster DIBs embedded in EMF graphics |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-03-05, TR-2026-08-03-01 |

### Description

When an embedded EMF graphic contains a raster DIB payload in an `EMR_STRETCHDIBITS` record, the folder-replacement pipeline shall decode that payload in memory and process it through the existing shared bitmap OCR and text-replacement path. It shall re-embed the resulting DIB in the same EMF record, retaining the EMF graphic and its other vector content.

The raster DIB path shall use the selected OCR and text-replacement providers, source and target languages, typeface, confidence threshold, colour estimation, and batch text-region rendering already used for standalone and Office-embedded bitmap images. Its replaced OCR-region count shall contribute to the document's image-region result.

### Rationale

An EMF can combine editable vector text with already-rasterized visual content. Processing DIB payloads directly covers that contained bitmap content without requiring an EMF renderer or rasterizing the whole vector graphic.

### Notes

The initial scope is `EMR_STRETCHDIBITS`. Other EMF bitmap record types and outlined or path-only vector text remain out of scope until separately specified. The DIB shall be processed only in memory and shall invoke the existing shared raster handler; no intermediate image file is permitted.

Automated tests shall use a synthetic EMF containing a DIB payload. They shall verify that the shared image processor is invoked, its result is re-embedded, and unrelated EMF records remain valid.

---

## FR-2026-08-03-10

| Property | Value |
|----------|-------|
| Title | Separate vector format handlers and support standalone vector inputs |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-03-05, TR-2026-08-03-01 |

### Description

The vector-replacement implementation shall provide separate SVG, EMF, and WMF modules, with a small extension-based dispatcher and shared result and DIB helpers. Standalone `.svg`, `.emf`, and `.wmf` input files shall be supported by the folder command and shall use the same in-memory format handler as an embedded Office vector part.

### Rationale

The vector formats have distinct binary and XML structures that need independent iteration. Sharing the one in-memory entry point prevents different behaviour for standalone and embedded graphics.

### Notes

The existing shared bitmap handler remains the sole raster text-replacement implementation. Vector handlers shall pass a decoded embedded bitmap directly to it and shall not write intermediate files.

---

## FR-2026-08-03-11

| Property | Value |
|----------|-------|
| Title | Replace self-contained SVG raster images |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-03-10, SR-2026-08-03-02 |

### Description

The SVG handler shall process a raster image referenced by an SVG `image` element only when the image is a supported bitmap encoded as a `data:` URI in that SVG. It shall decode the bitmap in memory, apply the shared bitmap OCR and text-replacement handler, and update the same `data:` URI when one or more OCR regions are replaced.

### Rationale

An SVG can combine editable text and an embedded raster image. Supporting self-contained raster data covers the image without requiring a renderer or an external resource.

### Notes

Nested SVG, video, canvas, foreign-object content, malformed data URIs, and non-supported image MIME types remain unchanged until separately specified.

---

## FR-2026-08-03-12

| Property | Value |
|----------|-------|
| Title | Replace self-contained WMF DIB bitmap records |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-03-10 |

### Description

The WMF handler shall decode and process the self-contained source DIB in `META_STRETCHDIB` records through the shared bitmap OCR and text-replacement handler, then re-embed the resulting DIB in the same record. Its replaced OCR-region count shall contribute to the folder result.

### Rationale

WMF supports raster DIB content alongside its native drawing and text records. Processing the DIB directly preserves the surrounding WMF without requiring a WMF renderer.

### Notes

The initial scope is `META_STRETCHDIB`. Other WMF bitmap records, compressed DIB payloads, and vector text represented only by outlines remain out of scope until separately specified.

---

## FR-2026-08-03-13

| Property | Value |
|----------|-------|
| Title | Evaluate native text-element layout for preserve-basic-layout |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-07, FR-2026-08-02-10 |

### Description

The project shall rename `scripts/run_text_replacement_evaluations.py` to identify it as the OCR text-replacement evaluator. The name `scripts/run_text_replacement_evaluations.py` shall be used for a separate local evaluation command for native editable PowerPoint text elements.

For its first pass, the native-text evaluator shall inspect each eligible text element in PPTX source files in the same local sample corpus used by the other evaluation commands, extract its basic text-box properties including autofit settings, and render that element to a bitmap with Skia. It shall skip a text frame with no non-whitespace run text, while retaining blank paragraphs in an otherwise nonempty text frame. It shall write the extracted properties as a JSON file beside each rendered bitmap. The generated static HTML evaluation shall contain one row per source text element and present the slide and object reference, a new-tab link to that row's JSON properties file, and the rendered bitmap. The HTML shall display each native-size preview with a thin red border that makes the text-box bounds visible without changing the raster bitmap. It may process `sample-data/confidential/` locally only under the repository's confidential-sample rule.

The extracted and reported text-box properties shall include the source location; bounding-box position and size; source and effective text rotation; all four text-frame padding values; word-wrap setting; horizontal and vertical alignment; and autofit mode, font scale, and line-spacing reduction when represented in the source. For each paragraph and run, the report shall include text content, paragraph alignment and spacing when set, direct bullet settings, and the run's font family, broad serif/sans-serif/fixed-width classification, size, bold, italic, underline, and baseline settings when set.

The evaluator shall render without applying autofit. It shall render within the explicit text box after applying the extracted padding and text rotation. It shall select a committed, redistributable Noto face matching the source element's broad serif, sans-serif, or fixed-width classification when the original font is unavailable. The first pass shall render text layout only; source text, shape, and page colours, fills, borders, and other non-layout visual styling are out of scope. The evaluator shall run independently of OCR and shall not invoke an OCR provider.

### Rationale

Native text elements have explicit bounds and may contain multiple runs with distinct formatting. Inspecting their geometry and source settings separately from OCR-region replacement provides a fast visual baseline for the later `preserve-basic-layout` fitting implementation.

### Notes

The initial input format is PPTX only. The evaluator shall use the ordinary local evaluation corpus, including locally processed confidential samples under the repository's confidential-sample rule. It shall ignore PowerPoint temporary lock files whose filename starts with `~$`. It shall recursively traverse each slide's shape tree and evaluate each shape with a text frame, including text frames within grouped shapes. Tables, charts, notes, masters, layouts, and other text not exposed as a slide-shape text frame are out of scope. The command shall accept `--input-root` and `--output-root`, defaulting to `sample-data/` and `outputs/evaluations/text-replacement/`. It shall write one HTML page for each source presentation and a sibling artifact directory named after that page; each text box shall have a PNG rendering and JSON properties file in that directory. The HTML shall display the PNG at its native pixel dimensions without a forced maximum size. Because each HTML page represents one presentation, the table shall show only a slide/object reference rather than repeating the presentation filename in each row. Reported dimensions, padding, paragraph spacing, and font sizes shall use PowerPoint's source English Metric Units (EMUs) and points where applicable.

The first renderer shall support the reported run-level typography, paragraph alignment and spacing, text-frame padding, vertical alignment, text rotation, direct bullet characters, and empty paragraphs. It shall preserve an empty paragraph's line advance, using its direct end-paragraph run font size when present, but shall not render a bullet for an empty paragraph. Underlines shall use the selected Skia typeface's underline position and thickness metrics rather than an estimated size-relative position, and an explicit false underline setting shall suppress underline rendering. It shall report direct source properties and resolve list-style defaults through the PowerPoint master, layout, text-frame, and paragraph precedence chain for the evaluator's explicit-properties artifacts. Theme resolution remains out of scope except where FR-2026-08-22-10 requires it for source-font fitting and previews. For rendering only, an absent direct font size shall use 18 points and an absent direct font-family classification shall use sans-serif. The committed Noto Sans JP, Noto Serif JP, and Noto Sans Mono assets shall be selected, respectively, for sans-serif, serif, and fixed-width classifications. Tab layout and automatic-number and picture bullets remain out of scope. Colour, shape fill, borders, and other non-layout visual styling are out of scope for this first pass.

Source symbol-font `buChar` codepoints may not render as their intended visual glyph with the committed Noto fonts. A future fallback must map a source symbol-font character to an appropriate Unicode glyph supported by the committed Noto assets; it shall not depend on an operating-system symbol font. The initial supported source symbol fonts and their mapping coverage remain to be specified.

The evaluator shall measure and reflow the complete text before drawing, then select the largest uniform scale from the source run font sizes that fits within the padded text-box bounds rather than clipping at the bottom. It shall preserve every run's relative font-size ratio and style, rewrap at each candidate scale, and retain explicit blank paragraphs and line breaks. It shall test scales down to a one-pixel font size. If content still cannot fit, the output shall record overflow rather than silently clipping. Each JSON artifact shall include the selected scale and fit status.

When an otherwise unbreakable token alone exceeds its available line width, the evaluator shall introduce character-level layout breaks for that token before reducing font size. It shall retain ordinary word wrapping when the token fits on a line.

When a paragraph has explicit point-based line spacing below the rendered glyph line height, the evaluator shall use at least the glyph line height as its drawing and fitting advance. It shall continue to report the original point-based spacing value unchanged.

For each source text box, the HTML shall show the original rendering followed by one native-size rendering column per locally discovered text-replacement provider. The evaluator shall infer the source language from the established language-code directory hierarchy used by OCR evaluation and shall request English (`en`) as the target language by default. It shall issue one replacement request for each nonempty paragraph, preserving paragraph-level layout properties, including bullets, indentation, alignment, and spacing. Each returned paragraph shall be represented by one run using that paragraph's dominant source run style: the style of the run with the greatest number of non-whitespace source characters, with the first run winning a tie. The provider-specific rendered bitmap and a sibling provider-specific explicit-properties JSON shall record that paragraph-level replacement and its independently fitted text size. The HTML may be wider than the viewport and shall retain every image at its native size for horizontal-scroll review.

Alongside the source-properties JSON, the evaluator shall write a sibling explicit-properties JSON for each rendered text box. It shall retain the same text-box definition shape while flattening the layout properties needed by a future PPTX-writing helper. In particular, it shall set the selected committed Noto font family explicitly for every run, multiply every direct or defaulted run font size by the selected fitting scale, set autofit to `none`, and retain the selected scale and fit status. The source-properties JSON shall remain an unmodified record of extracted source properties. The HTML row shall provide new-tab links to both JSON artifacts.

Automated tests shall use synthetic documents only. They shall verify property extraction, autofit extraction, Noto-face selection, one output row per eligible text element, deterministic Skia bitmap output, and that the command does not construct or invoke an OCR provider.

---

## FR-2026-08-03-14

| Property | Value |
|----------|-------|
| Title | Apply preserve-basic-layout to bounded native document text |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-03-07, FR-2026-08-03-13 |

### Description

The folder-replacement command shall expose `--document-text-layout` with values `preserve-source-formatting` (default) and `preserve-basic-layout`. The latter shall apply only to native editable text for which a format adapter can determine a finite text rectangle and write explicit text formatting back to that same container. It shall not change the OCR bitmap or editable-vector replacement paths. Free-flowing document text without a stable bounding box shall retain source formatting.

The product shall provide a shared bounded-text layout core. It shall accept styled paragraphs and runs, bounds, padding, rotation or writing direction, alignment, and list settings; obtain a replacement for each nonempty paragraph; select the dominant source run style for each returned paragraph; select an appropriate committed Noto face; wrap and fit the replacement within the box; and return explicit writable text-frame, paragraph, and run settings with autofit disabled. A token that alone exceeds line width shall be character-wrapped before font reduction. A fit that cannot meet the minimum one-pixel font size shall remain visible as overflow rather than silently clipping.

The core shall support format-specific adapters for PPTX slide and grouped-shape text frames, DOCX drawing text boxes and embedded-diagram text, XLSX drawing-shape text, XLSX worksheet cells with finite explicit grid bounds, and bounded PDF form or annotation text. Each adapter shall use the shared fitting semantics while retaining format-specific extraction, inherited-style resolution, and writing logic. A format or text container that cannot supply reliable bounds or cannot safely write the resulting explicit formatting shall retain `preserve-source-formatting`.

The fitting output shall calculate its scale with the selected Noto face and write the fitted size explicitly. Each format adapter shall embed the selected redistributable Noto face(s) when its output format supports portable font embedding, subject to the font's embedding permissions. Portable embedding shall use repository-owned static Noto faces, rather than the variable test faces used for deterministic measurement. Where a format has no safe portable-font embedding path, the adapter shall retain its resolved source font reference while applying the Noto-derived fitted size, equivalent to `preserve-basic-layout-source-font`; it shall not claim portable rendering. The initial PPTX implementation may write explicit Noto font references without embedding while compatible static font assets and a PowerPoint-compatible embedding path are specified.

### Rationale

Translated text may differ substantially in length. A shared fitting model provides a readability-first replacement path wherever the source exposes an explicit text container, while allowing each document format to retain its own safe serialization rules.

### Notes

The existing generic native-text replacement remains the implementation of `preserve-source-formatting`. The initial shared font assets are the committed Noto Sans JP, Noto Serif JP, and Noto Sans Mono faces; an adapter shall select the corresponding broad sans-serif, serif, or fixed-width face. Target-language coverage and additional Noto families require separate requirements when those faces are added.

The initial implementation order is PPTX, then DOCX drawing text, XLSX drawing text and worksheet cells, and bounded PDF text. An XLSX cell is eligible only when its column width and row height resolve to finite explicit grid bounds; a merged cell uses the complete merged grid rectangle. For a cell fit, the adapter shall convert Excel's explicit column-width character unit to its standard 96-DPI grid width and row-height points to EMUs. A cell without reliable bounds retains source formatting. A structured XLSX table body cell uses the same finite-grid-cell rule. Until FR-2026-08-04-08 is implemented, its header row and `xl/tables/*.xml` definitions are structured-reference metadata and shall remain unchanged, so formula, query, and table references remain valid. Charts, ordinary Word paragraphs, and arbitrary PDF content streams require a separate bounding-box definition before they can opt in. Ordinary EMF and WMF text records have no portable embedding path; when they have an eligible explicit clip rectangle, they shall retain the source face while applying the Noto-derived fitted size.

Automated tests shall use synthetic documents and fonts only. They shall verify mode selection, bounded-container eligibility, paragraph-level replacement, explicit no-autofit output, fitted Noto typography, stable overflow behavior, and valid output for each implemented adapter.

---

## FR-2026-08-03-15

| Property | Value |
|----------|-------|
| Title | Apply preserve-basic-layout to PPTX text frames |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-14, FR-2026-08-03-13 |

### Description

When `--document-text-layout preserve-basic-layout` is selected, the folder-replacement PPTX handler shall replace text in slide-shape text frames, including placeholders and text frames inside grouped shapes, using the shared bounded-text layout core. It shall resolve applicable PowerPoint list styles from master, layout, text frame, and paragraph sources; make resulting body, paragraph, bullet, and run settings explicit; select the chosen Noto face; disable autofit; and apply the independently fitted replacement text and font sizes to the output presentation.

The PPTX handler shall preserve existing processing of embedded bitmap and editable-vector package parts. It shall leave slide text outside a supported text frame unchanged. In `preserve-source-formatting` mode, it shall retain the existing generic OOXML native-text behavior.

### Rationale

PPTX is the evaluated bounded-text format and provides the first production integration for the fitting model.

### Notes

The implementation shall preserve the package's unrelated parts and relationships. It shall use only the repository-owned Noto assets and shall not rely on operating-system font discovery or runtime font downloads. The initial implementation shall write explicit Noto font references but shall not claim portable font embedding: the committed faces are variable fonts and a PowerPoint-compatible embedding path has not been specified. A follow-up embedding implementation shall include the regular face and any bold, italic, or bold-italic face needed by written runs, using separately specified compatible static font assets. Although fitting evaluates down to a one-pixel size, PPTX serialization shall write every DrawingML run size within OOXML's 1–4,000 point range. If fitting requires a smaller size, the written run shall use one point and retain the resulting overflow rather than emitting invalid package content.

Automated tests shall build synthetic PPTX files with ordinary, placeholder, and grouped text frames. They shall verify source-formatting mode, basic-layout paragraph replacement and fitting, explicit no-autofit and font settings, and a valid output package. Font-part tests will be added with the separately specified embedding implementation.

---

## FR-2026-08-03-16

| Property | Value |
|----------|-------|
| Title | Replace and fit PowerPoint table-cell text |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-14, FR-2026-08-03-15 |

### Description

When `--document-text-layout preserve-basic-layout` is selected, the PPTX handler shall replace text in every editable PowerPoint table cell. Where the cell exposes a finite text rectangle, including its cell bounds and text-frame padding, it shall use the shared bounded-text layout core and write explicit fitted Noto typography with autofit disabled. It shall retain the table's geometry, fill, borders, merge state, and other non-text properties.

If a table cell cannot supply a reliable finite text rectangle or cannot safely accept explicit fitted formatting, the handler shall still replace its editable text through the established source-formatting path. It shall retain the existing font, size, and text-frame behavior for that cell rather than skipping replacement.

### Rationale

Table cells usually provide the explicit bounds needed for readable translated text, while a safe source-formatting fallback ensures that unsupported cell variants do not silently retain source-language text.

### Notes

Automated tests shall use synthetic PPTX tables with ordinary cells and merged cells. They shall verify fitted replacement for bounded cells, source-formatting replacement fallback for an ineligible cell, preservation of table geometry, and valid output packages.

---

## FR-2026-08-04-01

| Property | Value |
|----------|-------|
| Title | Derive fit bounds for PowerPoint no-autofit text frames |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-04 |
| Related Requirements | FR-2026-08-03-14, FR-2026-08-03-15 |

### Description

For a PowerPoint slide-shape text frame processed with `--document-text-layout preserve-basic-layout`, the handler shall use a derived fit rectangle when the source text-frame autofit mode is explicitly `none` (PowerPoint's **Do not Autofit** setting). It shall lay out the original source paragraphs and runs at their original resolved font sizes, styles, paragraph settings, padding, writing direction, and list settings, then use the occupied source-text rectangle as the replacement fitting rectangle. The derived rectangle shall retain the source text frame's padding and shall not exceed the original shape rectangle.

The handler shall use the original shape or cell rectangle directly for every other bounded-text case, including `text-to-fit-shape`, `shape-to-fit-text`, inherited or unspecified autofit, table cells, and non-PowerPoint adapters. It shall not derive replacement bounds from original text in those cases.

Typeface selection for `preserve-basic-layout-source-font` is defined by
FR-2026-08-22-04. This requirement continues to define the no-autofit fit
rectangle independently of the selected typeface.

### Rationale

Authors can disable autofit while leaving a large editing text frame around a smaller intended block of text. Fitting replacement text to that loose frame can produce needlessly small or visually misplaced typography. The original laid-out text provides a closer approximation of the intended visual bounds.

### Notes

The source text frame's geometry remains unchanged. The derived rectangle affects only replacement fitting and is not written back as a resized shape. The implementation shall retain the existing one-point OOXML serialization minimum and overflow behavior.

Automated tests shall use synthetic PPTX text frames with explicit `noAutofit` and a larger source rectangle than the original occupied text. They shall verify that the no-autofit replacement uses the derived rectangle, while `text-to-fit-shape` and table-cell replacement continue to use their actual rectangles.

---

## FR-2026-08-04-04

| Property | Value |
|----------|-------|
| Title | Preview PowerPoint no-autofit derived fit bounds |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-04 |
| Related Requirements | FR-2026-08-03-13, FR-2026-08-04-01 |

### Description

The native PowerPoint text-layout evaluation command shall use the same derived-fit-bound rule as the production PPTX adapter for replacement previews. When the source text frame explicitly uses `noAutofit`, it shall measure the original resolved text with the shared deterministic bounded-text layout core and fit each replacement against that derived rectangle. Every other evaluated text frame shall continue to fit replacement text against its full source rectangle.

Each preview bitmap shall retain the full source shape dimensions and render replacement text at the position it would have in the unchanged source shape. For a replacement that uses derived bounds, the bitmap shall also show a distinct, thin dashed guide for the derived fit rectangle, in addition to the existing red source-shape border displayed by the HTML viewer. This guide is evaluation-only and shall not be included in an explicit-properties definition intended to represent output formatting.

Replacement explicit-properties JSON shall retain the original source shape geometry, because the production adapter does not resize the shape. It shall record the fitting rectangle and whether it was derived from the source text, so reviewers can compare the source geometry, the fit input, and the fitted result.

### Rationale

The evaluator must preview the same fit decision that the production PPTX adapter writes. Showing both the original shape and the derived fit rectangle makes it possible to identify loose `noAutofit` frames and assess whether source-text measurement produces useful replacement typography.

### Notes

The evaluator may share or delegate to the existing bounded-text layout core rather than maintain a second measurement implementation. Its existing source-property extraction and visual source rendering remain unchanged. Automated tests shall use synthetic text boxes to verify that explicit `noAutofit` replacements use a recorded smaller derived fitting rectangle while other autofit modes retain the source rectangle.

---

## FR-2026-08-04-05

| Property | Value |
|----------|-------|
| Title | Preserve PowerPoint no-autofit width and derive its natural text height |
| Owner | KrisTC |
| Status | Implemented |
| Source | User clarification |
| Date Added | 2026-08-04 |
| Related Requirements | FR-2026-08-04-01, FR-2026-08-04-04 |

### Description

This requirement supersedes the derived-rectangle dimensional rule in FR-2026-08-04-01 and FR-2026-08-04-04 for explicitly `noAutofit` PowerPoint slide-shape text frames.

For such a frame, the PPTX adapter shall retain the source text-frame width and padding. It shall lay out the original resolved paragraphs and runs at their source font sizes using that padded width, preserving wrapping. The derived fitting height shall be the source layout's natural height plus the frame's top and bottom padding. It shall not be clamped to the source shape height. The replacement shall be fitted against this source-width and natural-height rectangle.

The adapter shall retain the source shape geometry when writing the presentation. A no-autofit text frame may therefore display text below its nominal source rectangle, consistent with the source's no-autofit layout behaviour. Every other autofit mode and bounded-text adapter shall continue to fit against its original source rectangle.

The native-text evaluator shall render explicit no-autofit source text at its original scale and shall expand its evaluation canvas vertically as needed to show the natural text height. Its replacement preview shall use the same source-width/natural-height fitting rectangle and expand vertically as needed to show it. It shall show the original source-shape rectangle and the derived fitting rectangle as distinct evaluation-only guides. The replacement explicit-properties JSON shall record the derived rectangle without changing the reported source shape geometry.

### Rationale

PowerPoint's no-autofit behaviour preserves the text-frame width and wraps content downward at the selected font size. A tight occupied-width calculation or height clamp incorrectly shrinks text and hides vertical overflow, producing a preview and fitted result unlike the source presentation.

### Notes

Automated tests shall use a synthetic no-autofit text frame whose source text needs more height than its shape. They shall verify original-scale source rendering, a fitting rectangle with the source width and a natural height greater than the source shape, and a taller replacement preview. Tests shall also retain the full-source-rectangle behaviour for `text-to-fit-shape`.

---

## FR-2026-08-04-06

| Property | Value |
|----------|-------|
| Title | Preserve source typeface references during best-effort PPTX fitting |
| Owner | KrisTC |
| Status | Superseded |
| Source | User request |
| Date Added | 2026-08-04 |
| Related Requirements | FR-2026-08-22-04 |

### Description

This historical requirement introduced
`preserve-basic-layout-source-font`. Its current definition is
FR-2026-08-22-04.

---

## FR-2026-08-04-02

| Property | Value |
|----------|-------|
| Title | Select an empty OCR provider for local pipeline testing |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-04 |
| Related Requirements | FR-2026-08-01-02, FR-2026-08-01-03, FR-2026-08-03-01, FR-2026-08-03-03 |

### Description

The default OCR-provider factory shall expose a locally implemented provider named `no_ocr`. Its `recognize` operation shall return immediately with an `OcrResult` whose `text_items` collection is empty, without inspecting the supplied image, loading an OCR model, or accessing the network.

The folder-replacement command shall allow `--ocr no_ocr`. When selected, it shall retain the established native editable-text and editable-vector-text replacement behaviour, but it shall leave every raster bitmap unchanged because the empty OCR result contains no eligible text regions.

The `no_ocr` provider shall not be eligible for the synthetic OCR contract test. The OCR-evaluation command shall exclude `no_ocr` from its automatic all-provider evaluation, so selecting this test utility does not create empty results or cache roots in a normal OCR-quality evaluation.

### Rationale

Replacing text in documents with many raster images can be slow because normal OCR initializes models and recognizes every image. An explicit empty local provider makes it possible to test discovery, output paths, native-text replacement, document traversal, progress, and error isolation without paying that OCR cost.

### Notes

The provider shall be a normal directory-derived OCR-provider package under `pipeline/ocr_plugins/`, consistent with FR-2026-08-03-01. It shall not be the default OCR provider and shall not be a fallback after a real OCR-provider failure.

Automated tests shall use synthetic images and temporary folders. They shall verify the provider returns an empty result without touching image pixels, folder replacement with `--ocr no_ocr` leaves raster images unchanged while retaining native-text replacement, and OCR evaluation does not invoke or generate output for this provider.

---

## FR-2026-08-04-03

| Property | Value |
|----------|-------|
| Title | Report actionable folder-replacement command-line errors |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-04 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-03-14 |

### Description

Before processing any input, `scripts/run_folder_replacement.py` shall validate its user-supplied parameters and report anticipated validation failures through argparse's normal command-line-error mechanism. It shall print the usage summary and one concise `error:` message to standard error, exit with status 2, and shall not display a Python traceback for these failures.

The command shall report an error when the input path does not exist or is not a directory, or when an existing output path is not a directory. It shall report an error when `--ocr` does not name a discovered OCR provider, or when `--text-replacement` does not name a discovered text-replacement provider. Each unavailable-provider error shall identify the invalid value and list the available provider names for that option.

The command shall also report an error when the output folder is the input folder or is located below it.

Existing argparse validation for missing required arguments and unsupported `--document-text-layout` values shall retain the same command-line-error behaviour. Unexpected operational failures, including failures while processing eligible input files, shall retain the per-file isolation and reporting required by FR-2026-08-03-03.

### Rationale

Input paths and provider names are ordinary user choices. Clear command-line feedback lets a user correct them immediately, rather than interpreting an implementation exception or traceback.

### Notes

Validation shall happen before the command loads the replacement typeface or begins folder processing. It shall not create an output directory or modify input files when validation fails.

Automated tests shall invoke the script as a subprocess with synthetic temporary paths. They shall verify status 2, a concise error message, and no traceback for a missing input directory, a non-directory input, a non-directory output, an output directory nested below the input directory, an unknown OCR provider, and an unknown text-replacement provider. They shall verify the unavailable-provider messages contain the available names.

---

## FR-2026-08-04-07

| Property | Value |
|----------|-------|
| Title | Apply preserve-basic-layout to bounded vector, Word, and PDF text |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-04 |
| Related Requirements | FR-2026-08-03-05, FR-2026-08-03-07, FR-2026-08-03-14 |

### Description

`preserve-basic-layout` shall use the shared bounded-text layout core for every supported native text container that supplies an explicit finite rectangle and can be rewritten safely. This extends the existing PPTX and explicitly bounded XLSX-cell handling to DOCX drawing text, XLSX drawing-shape text, bounded PDF form or annotation text, and bounded editable SVG, EMF, and WMF text. All adapters shall use the same paragraph replacement, dominant-run-style selection, Noto-face selection, reflow, fit/overflow result, and explicit fitted typography semantics. The adapters shall preserve their surrounding document or vector content.

Portable formats shall embed selected repository-owned static Noto faces. For a format without a safe portable embedding path, including ordinary EMF and WMF, the adapter shall retain the resolved source face but write the Noto-derived fitted size and explicit layout settings. This is a required best-effort mode, not a reason to retain the original size when replacement text length changes substantially.

A container without an explicit finite rectangle, or for which the adapter cannot safely write an explicit fitting result, shall retain the existing `preserve-source-formatting` replacement behaviour. Free-flowing Word paragraphs, arbitrary PDF page-content text, outlined vector text, and SVG text without an explicit containing rectangle shall not opt in.

### Rationale

The readability objective applies wherever the document format supplies a true text field, annotation, or clip rectangle, not only to PowerPoint. A shared core prevents later fitting corrections from diverging between Office, PDF, and vector formats.

### Notes

The required bounding sources and safe write rules are not yet fully specified for several requested formats:

- DOCX: DrawingML text boxes can use their drawing extent; Word embedded-diagram text requires a defined mapping from the diagram's text node to its rendered shape extent.
- XLSX: Drawing-shape text can use its DrawingML transform extent. The existing finite-grid-cell path remains separate only for bounds extraction; it uses the same fitting core.
- PDF: AcroForm widgets and FreeText annotations have rectangles. Implemented PDF rules are defined by FR-2026-08-04-09; portable Unicode fallback is proposed by FR-2026-08-04-10.
- SVG: ordinary `text`/`tspan` elements do not define a rectangular text field. A qualifying explicit rectangle must be identified, such as a clipping rectangle associated with the text; `foreignObject` and arbitrary HTML layout remain out of scope unless separately added.
- EMF and WMF: text output records have an origin and may have a clipping/opaque rectangle. Only records with an explicit clipping rectangle are candidates; a record with only an origin, advances, or current font is not bounded text.

Automated tests shall use synthetic DOCX, XLSX, PDF, SVG, EMF, and WMF inputs. They shall verify exact eligibility/fallback decisions, replacement through the shared core, explicit fitted output, and that every generated file remains loadable by an appropriate format parser. PDF tests shall also verify any required appearance streams and embedded-font resources.

---

## FR-2026-08-04-08

| Property | Value |
|----------|-------|
| Title | Translate structured XLSX table headers safely |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-04 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-03-14, FR-2026-08-04-07 |

### Description

The folder-replacement pipeline shall translate a structured XLSX table's visible header-row cells only when it can atomically update the corresponding `xl/tables/*.xml` `tableColumn` names and every supported structured reference that relies on those names. The output shall remain loadable by Excel without a repair operation.

The implementation shall define a deterministic mapping from each source header to its replacement header, including duplicate or empty replacement results. It shall update worksheet formulae, table calculated-column formulae, totals-row formulae, workbook defined names, and other supported structured-reference consumers using token-aware parsing rather than unrestricted string replacement. Unsupported consumers shall be detected and reported with a safe fallback that retains the affected header unchanged.

Until this requirement is implemented, the pipeline shall treat structured XLSX table header cells and their `xl/tables/*.xml` definitions as an explicit non-replacement exception in every document-text layout mode. It shall continue to replace table body cells; finite-grid body cells remain eligible for `preserve-basic-layout` fitting.

### Rationale

Table headers are both visible labels and schema identifiers. Replacing only the visible cells breaks the agreement with table metadata; replacing the metadata without every dependent structured reference can break formulae, query bindings, and workbook semantics.

### Notes

Automated tests shall use synthetic workbooks containing tables, structured formulae, calculated columns, totals rows, and duplicate replacement candidates. They shall verify valid, repair-free output, consistent header and metadata names, correct supported-reference updates, and the unchanged-header fallback for unsupported dependencies.

---

## FR-2026-08-04-09

| Property | Value |
|----------|-------|
| Title | Safely replace currently supported PDF text |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request and implementation review |
| Date Added | 2026-08-04 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-03-07, FR-2026-08-03-14, FR-2026-08-04-07 |

### Description

This requirement defines the implemented PDF-specific eligibility, encoding, appearance, and fallback rules that the generic bounded-text requirements leave open.

For a PDF FreeText annotation or editable AcroForm text field with a finite `/Rect`, `preserve-basic-layout` shall use the shared bounded-text layout core. It shall write the replacement value, explicit fitted size, an embedded repository-owned static Noto face, and a clipped normal appearance stream that renders the replacement within that rectangle. It shall preserve the annotation or field's non-text semantics and surrounding page content. A field or annotation without a safe finite rectangle shall use `preserve-source-formatting` replacement rather than a bounded fit.

PDF page-content and Form XObject text-showing operations do not define a reliable text rectangle. They shall continue to receive native text replacement, but shall not opt into paragraph fitting, box resizing, or inferred bounding boxes. An unchanged replacement shall retain its original encoded text operand and active font selection.

When changing a page-content or Form-XObject text operand, the adapter shall decode composite Type0 text through its `/ToUnicode` CMap using the CMap's actual character-code widths. It shall not assume that `/Identity-H` implies two-byte character codes. A `/ToUnicode` map is decoding evidence only and shall not be reversed to select a CID for replacement text. If the active Type0 font, or a subsetted simple font, cannot safely encode the replacement, the adapter shall select the existing ASCII-safe fallback used for masking and redaction.

`preserve-basic-layout-source-font` is defined by FR-2026-08-27-02. Its
source-font measurement and output-font selection supersede this requirement's
historical source-font fallback rule. All other PDF-specific rules in this
requirement remain in effect.

### Rationale

PDF appearance streams, CMaps, subsetted fonts, and page-content operators have materially different safety properties from Office text containers. These rules prevent invisible or corrupt masking text while keeping the bounded-form path portable and the unbounded-content path conservative.

### Notes

The ASCII-safe page-content fallback is not sufficient for general non-ASCII replacement text; FR-2026-08-04-10 specifies that follow-up.

Automated tests shall use synthetic PDFs only. They shall cover Type0 `/ToUnicode` CMaps with one-byte and multi-byte codes, `TJ` arrays, subsetted simple fonts that lack a replacement glyph, unchanged identity operands, bounded field and FreeText appearance generation, embedded fallback resources, and parser-loadable output. Visual verification shall render synthetic outputs with an independent PDF viewer or renderer.

---

## FR-2026-08-04-10

| Property | Value |
|----------|-------|
| Title | Support complete Unicode replacement in unbounded PDF content |
| Owner | KrisTC |
| Status | Proposed |
| Source | Implementation review |
| Date Added | 2026-08-04 |
| Related Requirements | FR-2026-08-04-09 |

### Description

For changed, unbounded PDF page-content and Form-XObject text where the active source font cannot safely encode the replacement, the pipeline shall embed and select a portable static Unicode fallback that renders the complete replacement text for the requested target language. It shall not silently substitute unsupported characters with unrelated glyphs. If no safe fallback is available, it shall retain the source operand and report that item as unsupported.

### Rationale

The implemented ASCII fallback is suitable for local masking and redaction but not for general translation.

### Notes

Automated tests shall use synthetic non-ASCII replacements and verify embedded fallback resources, parser-loadable output, and visual rendering in an independent PDF viewer or renderer.

---

## FR-2026-08-24-03

| Property | Value |
|----------|-------|
| Title | Configure Windows Paddle CUDA runtime environment |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-24 |
| Related Requirements | FR-2026-08-21-01, TR-2026-08-01-01, SR-2026-08-21-01 |

### Description

The project shall provide a Windows PowerShell script that discovers the newest locally installed NVIDIA CUDA Toolkit 12.x and the newest locally installed cuDNN 9.x runtime for Windows x86_64 required by the project's pinned Windows `paddlepaddle-gpu` distribution. The script shall validate that the discovered CUDA and cuDNN DLL directories exist and contain the required runtime DLLs before updating the repository-root `.env.local` dotenv environment file.

The setup script shall manage only the `.env.local` `PATH` entry. It shall configure that entry so PaddlePaddle can load the validated NVIDIA DLL directories while preserving the invoking user's existing `PATH`. It shall preserve every user-managed `.env.local` entry, including future provider credentials or other secrets, unchanged. The file shall be ignored by Git and must not be committed. Project commands shall use it when it exists, without requiring CUDA or cuDNN directories to be added permanently to the user's global Windows environment.

The project shall provide `scripts/run.ps1` and executable `scripts/run.sh` wrapper scripts. Each wrapper shall accept a command and its arguments, run it through `uv run`, and, when the repository-root `.env.local` file exists, pass that file to uv with `--env-file`. The wrapper shall also support an explicit dotenv-file override for project-internal setup validation. The wrapper shall preserve the delegated command's exit code. Every project script that otherwise invokes `uv run` directly shall invoke the platform-appropriate `run` wrapper instead.

The setup script shall merge its candidate `PATH` entry with a temporary copy of `.env.local`, then start a fresh process through the PowerShell `run` wrapper using that temporary dotenv-file override. It shall verify that the installed PaddlePaddle distribution reports CUDA compilation support and detects at least one available CUDA device. The script shall report the detected CUDA Toolkit and cuDNN locations and the number of visible devices. It shall exit non-zero without creating `.env.local` when it did not previously exist, or modifying it when it did, if discovery, validation, dotenv loading, or Paddle CUDA-device detection fails. It shall delete the temporary candidate file in every outcome.

### Rationale

The Windows PaddlePaddle GPU wheel can be installed correctly while CUDA and cuDNN DLLs remain unavailable to its child process because their installation locations are not on `PATH`. A project-local environment file gives local development commands a repeatable way to expose those libraries and future provider settings without changing machine-wide configuration, while an end-to-end verification prevents treating a merely installed toolkit as usable GPU acceleration.

### Notes

The approved Paddle CUDA wheel registry in SR-2026-08-21-01 remains CUDA 12.6. The local runtime-discovery rule is independent of that wheel registry label: it shall select the newest valid CUDA Toolkit 12.x installation and the newest valid cuDNN 9.x Windows x86_64 runtime installation, including a standard cuDNN layout such as `C:\Program Files\NVIDIA\CUDNN\v9.<version>\bin\12.<version>\x64`. The fresh Paddle CUDA-device probe is the final compatibility check. The implementation shall identify the exact required cuDNN DLL names and compatible CUDA Toolkit locations from the pinned PaddlePaddle GPU runtime, rather than accepting an arbitrary directory that happens to contain similarly named files.

The setup script shall not download, install, update, or modify NVIDIA software, the Python environment, the uv lockfile, or the user's persistent environment variables. It may read standard Windows NVIDIA installation locations and relevant environment variables to discover candidate installations. Its diagnostics shall distinguish missing CUDA Toolkit, missing or incompatible cuDNN runtime libraries, an unavailable NVIDIA driver or GPU, and a PaddlePaddle CUDA-loading failure.

The setup script shall update the `PATH` entry atomically after the probe succeeds, so a failed run cannot leave a partially written file or overwrite user-managed settings. A malformed or duplicate managed `PATH` entry shall fail with a diagnostic rather than causing the script to rewrite unrelated content. The `PATH` entry is the setup script's only managed part of `.env.local`; users are responsible for adding, rotating, and removing any secrets. Diagnostics and automated tests shall not display secret values.

The `.env.local` file shall be added to `.gitignore` when this requirement is implemented. Automated tests shall mock installation discovery and the child-process probe; they shall not require CUDA hardware or NVIDIA software in CI. They shall verify that the setup script preserves arbitrary user-managed dotenv entries and rolls back cleanly on failure, and that each run wrapper uses `.env.local` only when it exists. The runtime probe is a required local validation on supported Windows machines, while CPU-only platforms remain valid under FR-2026-08-21-01.

---

## FR-2026-08-24-04

| Property | Value |
|----------|-------|
| Title | Translate text and filenames with Google Cloud Translation |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-24 |
| Related Requirements | FR-2026-08-02-06, FR-2026-08-03-01, FR-2026-08-03-04, FR-2026-08-24-03, SR-2026-08-24-01 |

### Description

The default text-replacement provider factory shall discover a `google_cloud_translate` provider. The provider shall use the Google Cloud Translation Advanced v3 API to translate ordinary text from the request's source BCP 47 language tag to its target BCP 47 language tag.

For filename requests, the provider shall translate the filename stem while retaining the original suffix unchanged. It shall reject an empty translated stem or a translated stem containing a path separator, NUL character, `.` or `..`, by raising `TextReplacementProviderError`. The existing folder-replacement collision and output-root safety checks shall continue to apply.

The provider shall return `TextReplacementProviderError` when required local configuration is absent, authentication fails, the requested language pair is rejected, the Google API call fails, or the API response does not contain a translation. It shall not fall back to another cloud service or to `argos_translate`.

### Rationale

Argos Translate provides an offline option, but its translation quality is insufficient for some document-replacement workloads. Google Cloud Translation provides a separately selectable managed translation service without changing the shared replacement API or requiring the local provider to be removed.

### Notes

The provider shall use the Google Cloud Translation Advanced v3 API's documented source- and target-language fields. It shall pass the request's BCP 47 tags unchanged unless the Google API requires a documented normalization. It shall configure the Google Cloud project through `GOOGLE_CLOUD_PROJECT`.

The provider shall use the global `translate.googleapis.com` endpoint and `global` location when `GOOGLE_CLOUD_TRANSLATION_LOCATION` is unset. When that setting names a Cloud Translation-supported location within continental Europe, such as `europe-west1`, the provider shall select the `translate-eu.googleapis.com` multi-regional endpoint and use that same location in its API resource names. A non-European location value shall raise `TextReplacementProviderError`; this feature does not support the US multi-regional endpoint. This feature shall use Google's pre-trained NMT model and shall not support custom AutoML models. The endpoint behavior and regional restrictions shall follow Google's [Global and multi-regional endpoints documentation](https://docs.cloud.google.com/translate/docs/advanced/endpoints).

Google Cloud credential configuration shall comply with SR-2026-08-24-01. A successful result shall use confidence `0.0`, because the API does not return a calibrated translation-confidence value for this operation. Empty input and requests whose source and target language tags are equal after case-insensitive comparison shall return the input unchanged with confidence `0.0` and shall not call the API.

The provider shall require the service-account Application Default Credentials configuration defined by SR-2026-08-24-01. Missing project or `GOOGLE_APPLICATION_CREDENTIALS` configuration, an unreadable credential file, or an API-key-only configuration shall raise `TextReplacementProviderError` before making a network request.

`google_cloud_translate` shall declare `LOCAL_EVALUATION_ELIGIBLE = False`. Automated local text-replacement evaluation and its default test suite shall not instantiate it or send evaluation text to Google. This evaluation exclusion does not prevent user-requested processing of confidential samples through the provider when it complies with SR-2026-08-24-01.

The provider shall send to Google only the replacement request's text and source and target language tags, plus the configured project and API operation parameters. It shall not send source paths, output paths, document metadata, OCR confidence, image bytes, evaluation artifacts, or credentials. It shall not persist translation text or API responses beyond the normal in-memory replacement result.

Provider-owned automated tests shall use synthetic text and filenames only. They shall mock the Google client and verify ordinary-text translation, filename safety, unchanged same-language and empty requests, global and EU endpoint configuration, configuration and API failures, API request construction, and that no confidential or credential value appears in errors or logs. Tests shall not make network calls or require Google credentials.

---

## FR-2026-08-24-05

| Property | Value |
|----------|-------|
| Title | Configure and verify Google Cloud Translation credentials |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-24 |
| Related Requirements | FR-2026-08-24-03, FR-2026-08-24-04, SR-2026-08-24-01 |

### Description

The project shall provide `scripts/configure_google_cloud_translation.py` to configure and verify the local Google Cloud Translation provider. The Python helper shall be invoked through the project's locked Python environment, for example `uv run --no-sync python scripts/configure_google_cloud_translation.py --credential-file ../credentials/credential.json`. It shall accept `--credential-file` with an absolute or relative path to a service-account credential JSON file and optional `--location`. The helper shall resolve a relative credential-file path against the invoking process's current working directory before validation, probing, and writing its absolute forward-slash form to `.env.local`. It shall derive the project ID from the credential file's `project_id` value. The optional location shall follow FR-2026-08-24-04: an unset location selects the global endpoint and a supported European location selects the EU endpoint. Its command help shall state that omission selects the global endpoint and list `europe-west1` (Belgium), `europe-west3` (Frankfurt), and `europe-west4` (Netherlands) as examples rather than an exhaustive availability list.

Before updating `.env.local`, the helper shall validate that the supplied path is an existing service-account credential JSON file, then perform one synthetic `translateText` request through the Google Cloud Translation provider using a fixed repository-owned test string. The probe shall confirm that the credentials, project, selected endpoint, and location work together. It shall not use sample data, document content, OCR output, user-provided text, or confidential data.

After a successful probe, the helper shall atomically create or update only its marked `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, and optional `GOOGLE_CLOUD_TRANSLATION_LOCATION` entries in the repository-root `.env.local` file. It shall write `GOOGLE_APPLICATION_CREDENTIALS` as a double-quoted absolute path with forward slashes, so the uv dotenv loader can parse a Windows credential-file path. It shall preserve all user-managed entries, including the CUDA `PATH` entry managed by `scripts/configure-paddle-cuda-environment.ps1`. If validation or the probe fails, it shall leave an existing `.env.local` unchanged and shall not create one that did not already exist.

### Rationale

Service-account key creation may be restricted, while an approved local credential file can be distributed for a single-machine utility. A project-owned setup command makes that credential configuration explicit, validates it before use, and avoids hand-editing provider settings into an ignored environment file.

### Notes

The helper shall print the credential file's basename, project ID, selected endpoint, selected location, and a success or concise failure category. A Google Cloud project ID is an identifier rather than a credential; it is permitted in the successful, interactive local summary but shall not be included in failure diagnostics or logs. The helper shall not print the credential file's contents, absolute credential path, private-key fields, access tokens, authorization headers, or the probe's source or translated text.

The helper shall replace its prior marked block atomically and preserve all user-managed dotenv entries. It shall recognise the previous PowerShell helper's marker during this migration, replace that block with the Python helper's marker, and shall not remove similarly named unmarked entries.

The helper shall not create a Google Cloud project, enable billing or APIs, create service accounts, create credential files, modify IAM roles, or make persistent Google Cloud configuration changes. The setup guide required by SR-2026-08-24-01 shall direct the developer to obtain the credential file from the appropriate project administrator before running the helper.

Automated tests shall use temporary synthetic credential files and a mocked Google client. They shall verify managed dotenv-entry creation and replacement, preservation of arbitrary user-managed dotenv entries, preservation of the CUDA script's managed `PATH` entry, probe failure rollback, API-key-shaped input rejection, and that diagnostics contain no credential value or probe text.

---

## FR-2026-08-04-11

| Property | Value |
|----------|-------|
| Title | Replace editable SmartArt and WordArt text in PPTX files |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request and local output diagnosis |
| Date Added | 2026-08-04 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-03-14, FR-2026-08-03-15 |

### Description

The folder-replacement PPTX handler shall replace editable text in SmartArt diagrams and WordArt shapes. The supplied diagnostic examples are SmartArt diagrams; this requirement also covers editable DrawingML WordArt text that uses text effects.

For SmartArt, the handler shall traverse the presentation's reachable diagram data parts and replace each eligible logical text value that PowerPoint uses to render the diagram. It shall update the canonical SmartArt text source rather than only a generated drawing representation, and it shall replace each logical text value at most once. The output shall retain the diagram's nodes, connections, layout, styles, colours, and non-text content, and shall open in PowerPoint without a repair prompt.

For WordArt, the handler shall replace the text in its editable DrawingML text body while preserving the shape's geometry and all text-effect, fill, outline, and transform markup. It shall not attempt to replace text that has been converted to outlines or rasterized.

Both container types shall participate in `preserve-source-formatting`. They shall participate in `preserve-basic-layout` or `preserve-basic-layout-source-font` only when the handler can identify a finite rendered text rectangle and safely write the resulting explicit text formatting; otherwise they shall use `preserve-source-formatting` replacement. The command's existing text-replacement provider, language options, per-file isolation, and result reporting shall apply.

### Rationale

SmartArt commonly stores its visible editable text in diagram-specific package parts rather than ordinary slide-shape text frames. WordArt can similarly rely on a text body whose appearance is defined by DrawingML effects. Treating both as native editable PPTX text closes a visible replacement gap without rasterizing or rebuilding the presentation's design.

### Notes

Automated tests shall use synthetic PPTX files only. They shall include a SmartArt diagram with multiple labels and an editable WordArt shape with text effects. Tests shall verify that every eligible logical text value is replaced exactly once, the output package remains loadable without repair, diagram and WordArt non-text XML is retained, and a PowerPoint-compatible renderer shows the replacements. Tests shall not use confidential presentations or derived artifacts.

---

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

## FR-2026-08-04-13

| Property | Value |
|----------|-------|
| Title | Replace PowerPoint speaker-note text |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-04 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-03-15 |

### Description

The PPTX folder-replacement handler shall replace editable text in every `ppt/notesSlides/notesSlide*.xml` part using the selected text-replacement provider and request languages.

Speaker-note text shall use direct OOXML text replacement in every document-text layout mode, including `preserve-basic-layout` and `preserve-basic-layout-source-font`. It shall not use bounded-text fitting, rewrite speaker-note geometry, or alter non-text XML, package relationships, slide content, or notes-master parts.

### Rationale

PowerPoint speaker notes are editable document text but are not exposed through the slide-shape traversal used for fitted slide text. Direct replacement ensures that the notes remain translated while avoiding unnecessary layout changes.

### Notes

Automated tests shall create a synthetic PPTX package with a speaker-note part and verify that the note text is replaced in every document-text layout mode, while slide text, relationships, and non-text note XML remain valid and unchanged where not otherwise eligible for replacement. Tests shall not use sample data or confidential presentations.

---

## FR-2026-08-04-14

| Property | Value |
|----------|-------|
| Title | Report native text-replacement evaluation progress |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-04 |
| Related Requirements | FR-2026-08-03-13 |

### Description

The native PowerPoint text-replacement evaluation command, `scripts/run_text_replacement_evaluations.py`, shall use tqdm to render terminal progress. It shall render one progress bar at a time for each discovered source-language directory containing eligible PPTX files. Each bar shall be labelled with that directory's path relative to the input root, advance once per eligible presentation after it is processed or skipped, and show the current presentation basename in its postfix.

### Rationale

Native-text evaluation may process many presentations and render every eligible text box with each replacement provider. Folder-level progress makes that work visible while preserving the command's isolated per-presentation failure handling.

### Notes

PowerPoint temporary lock files remain ineligible and shall not contribute to a progress bar's total. Existing one-line skipped-presentation reporting shall remain visible and later presentations shall continue processing.

---

## FR-2026-08-05-01

| Property | Value |
|----------|-------|
| Title | Preserve advanced PPTX text styling during fitted replacement |
| Owner | KrisTC |
| Status | Implemented |
| Source | User clarification and local output diagnosis |
| Date Added | 2026-08-05 |
| Related Requirements | FR-2026-08-03-14, FR-2026-08-03-15, FR-2026-08-04-06, FR-2026-08-04-11 |

### Description

For editable PowerPoint slide-shape text frames, WordArt shall not be a special
text-container category. An editable `p:sp` text frame with DrawingML text
effects, fills, outlines, or an `a:prstTxWarp` preset text transform shall use
the same bounded-text eligibility, extraction, replacement, fitting, and
writing path as every other editable slide-shape text frame. The presence of
one of those properties shall not cause a fallback to
`preserve-source-formatting`.

In `preserve-source-formatting`, the existing direct OOXML text replacement
shall continue to retain all source text styling. In either fitted layout mode,
the PPTX writer shall preserve the dominant source run's advanced direct
formatting when it writes the one replacement run for a non-empty paragraph.
It shall retain all compatible `a:rPr` and `a:endParaRPr` attributes and child
elements, including text fill, outline, effects, highlight, underline paint,
language, and hyperlinks, except where an explicitly fitted property replaces
the source value. It shall also retain the shape and text-body's existing
non-text styling and transform markup, including `p:spPr`, `a:bodyPr`, and
`a:prstTxWarp`.

The fitted rewrite may change the replacement text, the explicit fitted font
size, the written Latin and East-Asian typeface references, and the existing
required explicit text-frame layout settings such as disabled autofit. In
`preserve-basic-layout`, it shall write the selected Noto typeface references.
In `preserve-basic-layout-source-font`, it shall retain resolved source
typeface references where available. Typeface selection and fitting measurement
for that mode are defined by FR-2026-08-22-04.

Advanced text styling may alter the visual occupied bounds or make the fitted
output appear imperfect. This is an accepted best-effort limitation; it is not
a reason to bypass fitting. A PPTX text frame may fall back to direct
source-formatting replacement only when it has no finite reliable text
rectangle or cannot be safely rewritten while retaining package validity.

This requirement supersedes FR-2026-08-04-11 only where that requirement
treats WordArt as a separate container or permits fallback because of WordArt
styling. The SmartArt requirements remain unchanged: the handler shall
continue to replace canonical reachable diagram-data text, rather than fitting
or rewriting generated SmartArt drawing shapes.

### Rationale

Modern PowerPoint WordArt uses ordinary editable DrawingML text with presets
and styling. Treating those properties as an unsupported container excludes
many ordinary coloured or styled text boxes from the fitted modes and makes
`preserve-basic-layout` unexpectedly retain source fonts. Retaining advanced
styling while changing only the fitted typography preserves more of the
presentation design and keeps the two fitted modes distinguishable. Exact
visual metric equivalence is not required because the output remains editable.

### Notes

Automated tests shall use synthetic PPTX files only. They shall verify that
ordinary coloured text and text with `a:prstTxWarp`, fill, outline, shadow or
other effects, highlight, underline paint, language, and hyperlink markup are
fitted in both fitted modes while retaining that markup and the shape geometry.
They shall verify that basic layout writes Noto faces, source-font layout
retains the resolved source faces, and both modes produce the same replacement
text, fitting scale, and explicit autofit result. Existing SmartArt tests shall
continue to verify canonical diagram-data replacement exactly once without
rewriting generated diagram shapes. Tests must use synthetic data only.

---

## FR-2026-08-22-01

| Property | Value |
|----------|-------|
| Title | Run repeatable preset folder-replacement development scenarios |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-04-02, FR-2026-08-04-03, FR-2026-08-04-06, FR-2026-08-04-07 |

### Description

The project shall provide a separate development-only command that runs
repeatable visible-text-replacement scenarios over sample-data language
folders. It shall be a command-line wrapper around
`scripts/run_folder_replacement.py`; it shall construct and invoke that
command once for each scenario, and shall not invoke the folder-processing API
directly. It shall not change the command-line contract or generic input/output
behaviour of `scripts/run_folder_replacement.py`.

The command shall be named `scripts/run_development_folder_replacement.py`.
It shall accept one `SOURCE_FOLDER` positional argument that is relative to
`sample-data/`, is neither absolute nor escaping, and ends in a BCP 47
language-directory name. It shall derive the source-language option from that
final directory name. This permits multiple sample-data use-case hierarchies
without accepting arbitrary source or output paths. Its `--help` output shall
describe the source-selection rule and every supported option.

The command shall expose text-replacement provider, OCR provider,
document-text-layout mode, and target-language options directly; it shall not
define presets. A selected option shall accept one value or a comma-separated
collection of values. The literal value `all` shall expand to every discovered
text-replacement provider or OCR provider, and to every defined
document-text-layout mode. The target-language option shall accept exactly one
BCP 47 value and shall default to `en`; it shall not accept comma-separated
values or `all`. When one or more expandable options select multiple values,
the command shall run their Cartesian product, producing one separately
identifiable scenario for every combination.

For an input selected as `SOURCE_FOLDER` and a target language `TARGET`, the
command shall write outputs below
`outputs/evaluations/folder-replacement-development/`, preserving the parent
path of `SOURCE_FOLDER` relative to `sample-data/` and using a
`SOURCE_LANGUAGE-TARGET` directory in place of the source-language leaf. It
shall create one `vN` revision directory below that root, where `N` is the next
positive integer not already allocated there. All scenario combinations for one
invocation and one source/target-language root shall share that revision.
Every generated scenario output shall identify its effective option values in
its directory hierarchy or another immediately adjacent, human-readable
artifact, so visual review can unambiguously associate each output with its
replacement provider, OCR provider, layout mode, target language, and inferred
source language. Each scenario shall be stored below its revision directory in
a deterministic option hierarchy that identifies its text-replacement provider,
OCR provider, and document-text-layout mode, followed by the source file's path
relative to `SOURCE_FOLDER`. The revision directory shall contain a
`manifest.json` file that records the complete effective invocation, every
scenario combination, and an optional user comment. The command shall accept an
optional `--comment` value and record it in that manifest without using it in a
directory or file name.

The command shall validate the selected source folder and option values before
processing. It shall retain the main pipeline's provider validation, per-file
failure isolation, and exit-status semantics. It shall preserve the repository's
confidential-sample-data boundary:
confidential source data and derived results shall remain local evaluation
artifacts and shall not be copied into committed code, tests, fixtures,
documentation, examples, prompts, logs, issue descriptions, or commit
messages. This requirement supersedes the local-provider restriction in
FR-2026-08-03-03 only for this development command: it may invoke every
discovered provider, including a cloud-backed provider. The user is responsible
for selecting and using providers and associated accounts that are approved for
the selected documents.

Automated tests shall use synthetic temporary sample-data and output trees only.
They shall verify inferred source language, output-tree mirroring, preset
absence, comma-separated selected-value collections, per-option all-options
expansion, Cartesian-product scenario creation, non-overwriting revision
allocation, effective-configuration identification, manifest content and
optional comments, validation failures, and delegation to the established
folder-replacement command. Tests shall not use sample data.

### Rationale

Repeatedly entering long folder-replacement commands makes it difficult to run
consistent before-and-after comparisons while pipeline behaviour changes. A
bounded development runner makes the common sample-data scenarios concise,
repeatable, and easy to review across languages and option combinations while
leaving the general-purpose pipeline command unchanged.

### Notes

This is a development and manual-review tool. Its outputs are local generated
artifacts and shall remain ignored by Git. It does not alter the existing
folder-replacement command, its defaults, or its supported arbitrary-folder
workflow.

---

## FR-2026-08-22-02

| Property | Value |
|----------|-------|
| Title | Filter folder-replacement input files by glob pattern |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-22-01 |

### Description

The general folder-replacement command and development folder-replacement
command shall each accept an optional repeatable `--include PATTERN` option to
restrict processing to selected source files. Each option value shall accept a
single glob pattern or a comma-separated collection of glob patterns.

Patterns shall match source file paths relative to the command's selected input
folder. A supported file shall be processed when it matches at least one
include pattern. When no `--include` option is supplied, the commands shall
retain their current behaviour and process every supported file. Files that do
not match an include pattern shall be skipped without generating output.

If no supported source files match the include patterns, the command shall
complete successfully with zero processed files.

### Rationale

Development and diagnosis often need to focus on one document type or a small
set of files. Glob-based inclusion avoids repeatedly processing unrelated
documents while retaining the general recursive-folder workflow.

### Notes

The development command shall pass its selected include patterns to every
underlying folder-replacement scenario. Its manifest shall record the effective
include patterns. Automated tests shall use synthetic input trees and verify
single patterns, comma-separated and repeated patterns, relative-path matching,
unchanged no-filter behaviour, excluded-output absence, and successful
zero-match runs.

---

## FR-2026-08-22-03

| Property | Value |
|----------|-------|
| Title | Produce Word-repair-free DOCX output when embedding fitted fonts |
| Owner | KrisTC |
| Status | Proposed |
| Source | Word compatibility diagnosis |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-03-14, FR-2026-08-04-07 |

### Description

When `preserve-basic-layout` writes fitted text into a DOCX drawing text
container, the output shall use a conformant WordprocessingML embedded-font
package and shall open in Microsoft Word without a repair prompt attributable
to pipeline-generated font parts.

For every embedded static font part, the DOCX writer shall generate and record
a `w:fontKey`, reverse the complete 16-byte GUID sequence, and XOR that
reversed sequence against both of the font file's first two 16-byte blocks.
The stored part shall have the obfuscated-font content type, a valid
font-table relationship, and a relationship from the main document part to the
font table.

The writer shall use one `w:font` element per font family. Its regular, bold,
italic, and bold-italic embedded faces, when supplied, shall be child elements
of that family entry. It shall not introduce duplicate family entries, duplicate
relationship IDs, or duplicate content-type declarations. Existing font-table
metadata and unrelated font relationships shall be retained.

For every pipeline-created font-family entry, the writer shall add conformant
font-substitution metadata before its embedded-face elements: `w:panose1`,
`w:charset`, `w:family`, `w:pitch`, and `w:sig`. The values shall be derived
from the embedded static font's SFNT tables rather than hard-coded. The
metadata shall be placed in the `CT_Font` schema sequence and shall agree with
the family named by the embedded font. Existing metadata for a pre-existing
font-family entry shall remain unchanged.

When adding embedded-font parts, the writer shall ensure that
`word/settings.xml` contains the empty `w:embedTrueTypeFonts` setting. It
shall preserve existing settings and insert that element at its position in the
`CT_Settings` schema sequence; it shall not append the setting after later
settings. Before writing the output, the embedded-font validation shall reject
a package with pipeline-added font parts that lacks this setting or has it in
an invalid schema position.

When adding DOCX content-type declarations, the writer shall retain the
`[Content_Types].xml` `CT_Types` schema sequence: every `Default` element
shall precede every `Override` element. It shall insert a missing obfuscated
font `Default` declaration before the first `Override`, rather than appending
it after existing overrides.

Every pipeline-created WordprocessingML `w:rPr` element shall place its child
elements in the `CT_RPr` schema sequence. In particular, run-style, font,
bold, and italic properties shall precede font-size properties; underline and
later properties shall follow them. The DOCX writer shall not rely on Word to
repair or reorder generated run properties.

Before writing a DOCX output, the writer shall validate every pipeline-added
font relationship and content-type declaration, deobfuscate each added font
with its recorded key, and confirm that the result is a loadable OpenType or
TrueType font. If the writer cannot create or validate a conformant embedded
font package, processing of that source document shall fail without leaving an
invalid output file; the folder command's existing per-file failure isolation
shall continue to apply.

### Rationale

DOCX font embedding is an OOXML package feature with Word-specific binary and
relationship rules. A ZIP archive that contains a font-looking part can still
be unreadable or repairable by Word. Validating the complete package and the
recovered font prevents portability work from producing corrupt documents.

### Notes

The standard font-obfuscation algorithm reverses the whole GUID byte sequence,
not only the multi-byte UUID fields. The document's fitted font assets remain
the repository-owned static Noto faces required by FR-2026-08-03-14 and
FR-2026-08-04-07; the writer shall continue to respect their embedding
permissions.

The normative basis is ISO/IEC 29500-1 §17.8.3.8. Microsoft documents its
Word implementation in [MS-OI29500 §17.8.3.8,
`embedTrueTypeFonts`](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/8c385d06-6c29-470b-89cf-3c2bab8633e6),
which states that this setting directs the application to embed used fonts.
Microsoft's [font-part implementation
note](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/ea097c57-5794-4624-b08e-017b47051b1d)
also documents the Word obfuscated-font content type and refers to the
standard's font-embedding algorithm.

The WordprocessingML font-table overview describes both the substitution
metadata and embedded-face relationships in a `w:font` entry; see [ECMA-376
Part 4 §2.8, Fonts](https://c-rex.net/samples/ooxml/e1/Part4/OOXML_P4_DOCX_Fonts_topic_ID0E6KCU.html).

Automated tests shall use complete, synthetic OPC DOCX packages only. They
shall verify font-table merging, relationship and content-type reachability,
correct deobfuscation, and successful parsing of each recovered static font.
They shall also verify that an intentionally malformed embedded-font package is
rejected. They shall create bold, italic, and underlined fitted runs and verify
their `w:rPr` schema order. They shall verify that a font content-type default
added to a package containing overrides remains before every override. Tests
shall also start with a synthetic DOCX whose settings omit
`w:embedTrueTypeFonts`, and verify that the writer adds the setting in
`CT_Settings` order when it embeds a font and that validation rejects a
missing or misplaced setting. They shall verify that pipeline-created font
families have ordered, SFNT-derived substitution metadata before their embedded
faces. Tests shall not use confidential documents or derived artifacts.

The repository shall retain a documented Microsoft Word smoke-test procedure
for a representative generated DOCX. Where Word automation is available, it
shall open and save the synthetic output and verify that no repair log is
created. This manual or platform-specific gate supplements, rather than
replaces, deterministic automated package validation.

---

## FR-2026-08-22-04

| Property | Value |
|----------|-------|
| Title | Measure source-font fitted layout with the best verified source face |
| Owner | KrisTC |
| Status | Superseded |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-03-14, FR-2026-08-04-06, FR-2026-08-04-07 |

### Description

FR-2026-08-27-02 supersedes this requirement. It defines the current
source-font measurement, output-font selection, and fallback behaviour.

### Rationale

The new definition separates source measurement from replacement/output-font
selection, giving missing glyphs one predictable Noto fallback.

### Notes

The shared resolver remains the implementation mechanism. Its safe in-memory
embedded-font boundary and indirect-reference resolution requirements remain
applicable where they do not conflict with FR-2026-08-27-02.

---

## FR-2026-08-22-05

| Property | Value |
|----------|-------|
| Title | Use embedded DOCX source fonts for source-font layout measurement |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-22-03, FR-2026-08-22-04 |

### Description

As the first embedded-source-font implementation, the DOCX adapter shall
discover embedded WordprocessingML font faces in the input package and offer
them to the common source-font resolver for eligible DrawingML text containers
processed in `preserve-basic-layout-source-font` mode. It shall resolve a
`w:font` entry and its requested regular, bold, italic, or bold-italic
embedded-face relationship through the package font table and font-table
relationships.

The adapter shall de-obfuscate a candidate `.odttf` part with its recorded
`w:fontKey`, validate that the recovered bytes are a loadable OpenType or
TrueType face, and provide those bytes in memory only. It shall reject a
missing, malformed, unreachable, unsafe, or mismatched relationship or font
part. It shall not use a font-table declaration without a valid corresponding
embedded face as evidence that the face is available.

The adapter shall preserve pre-existing font-table entries, relationships, and
font-part bytes. It shall not write decoded source-font bytes to the output,
create a new embedding, or alter the source font's embedding permissions. The
common resolver shall determine whether a valid candidate has the requested
identity and replacement glyph coverage; failure shall follow the fallback
rules in FR-2026-08-22-04.

### Rationale

DOCX already has a well-defined embedded-font package representation, and this
pipeline already validates that representation when it embeds its own fitted
Noto faces. It is therefore the lowest-risk first format for source-font
measurement without relying on a locally installed font.

### Notes

Automated tests shall create complete synthetic DOCX packages containing an
embedded repository-owned test face and verify successful in-memory recovery
and selection. They shall also verify malformed obfuscation, missing or
incorrect relationships, requested-style absence, and missing replacement
glyphs fall back without corrupting or expanding the existing font parts.

---

## FR-2026-08-22-06

| Property | Value |
|----------|-------|
| Title | Use embedded PPTX source fonts for source-font layout measurement |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-03-15, FR-2026-08-22-04 |

### Description

The PPTX adapter shall discover presentation-embedded font faces referenced by
the input PresentationML embedded-font list and offer safely decoded candidates
to the common source-font resolver for eligible fitted text frames, including
grouped shapes and table cells, in `preserve-basic-layout-source-font` mode.
It shall associate each embedded regular, bold, italic, or bold-italic face
with its declared family and source-run style through the package's standard
relationships.

The adapter shall accept a candidate only when the relationship target is a
contained package part and its decoded bytes load as a Skia typeface. It shall
preserve all pre-existing embedded-font parts, relationships, and list entries;
it shall neither decode a source font to disk nor write, subset, replace, or
expand it. Candidate identity and replacement-glyph coverage remain the common
resolver's responsibility under FR-2026-08-22-04.

### Rationale

PowerPoint files can carry their own design fonts. Using an available original
face gives the source-font mode metrics that reflect a presentation's intended
appearance without depending on the host's Office installation.

### Notes

The implementation shall first document the exact supported PresentationML
font-part encodings and relationship forms before enabling them. Automated
tests shall use self-contained synthetic PPTX packages and repository-owned
test fonts; they shall cover each supported style, invalid or external-looking
relationships, unusable font data, and preservation of unrelated package
content.

---

## FR-2026-08-22-07

| Property | Value |
|----------|-------|
| Title | Use embedded PDF source fonts for source-font layout measurement |
| Owner | KrisTC |
| Status | Deferred |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-04-07, FR-2026-08-04-09, FR-2026-08-22-04 |

### Description

For a bounded PDF FreeText annotation or editable AcroForm field processed in
`preserve-basic-layout-source-font` mode, the PDF adapter shall offer an
embedded source font only when it can identify the active source font resource
for that container and recover a loadable embedded font program from that
resource. It shall support only contained font streams and formats that Skia
can load; it shall not fetch a font named by a PDF resource or descriptor.

The adapter shall preserve the source font object, stream, resource dictionaries,
encoding, and appearance data unless the existing text-replacement rules
otherwise require a safe update. It shall not attempt to extend a subsetted
font. The common resolver shall reject an embedded PDF candidate whose font
does not provide the requested replacement glyphs, and the adapter shall then
use the general fallback rules.

### Rationale

PDFs often embed the exact font needed to render their form or annotation
content, but those programs are frequently subsetted. Separating recovery from
glyph validation permits accurate use when possible without claiming that an
arbitrary PDF font can encode a translated replacement.

### Notes

Implementation of this requirement is intentionally deferred until broader PDF
handling has been reviewed and separately specified.

Automated tests shall use synthetic PDFs with bounded supported containers and
embedded repository-owned test fonts. They shall verify matching selection,
subset or missing-glyph fallback, malformed font-stream fallback, no network or
filesystem access, and valid output appearances.

---

## FR-2026-08-22-08

| Property | Value |
|----------|-------|
| Title | Use embedded SVG source fonts for source-font layout measurement |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-04-07, FR-2026-08-22-04 |

### Description

For an eligible bounded SVG text container processed in
`preserve-basic-layout-source-font` mode, the SVG adapter shall discover an
embedded `@font-face` only when its source is a contained `data:` URI in that
same SVG and its decoded bytes load as a Skia typeface. It shall map the
embedded face's declared family and style to the source text request before
offering it to the common source-font resolver.

The adapter shall not open or fetch any external stylesheet, URL, path, or
package-relative font reference. It shall preserve the original stylesheet and
embedded data unchanged. Unsupported data formats, malformed CSS, malformed
data URIs, style mismatches, and missing replacement glyphs shall use the
general fallback rules.

### Rationale

An inline SVG font is a self-contained source of the intended typeface, whereas
an external font reference crosses the pipeline's existing external-resource
security boundary.

### Notes

Automated tests shall use synthetic SVGs with inline repository-owned test-font
data. They shall verify matching selection and all fallback conditions, and
shall verify that external font URLs are neither opened nor reported as
available.

---

## FR-2026-08-22-09

| Property | Value |
|----------|-------|
| Title | Preview source-font fitted layout in the native-text evaluator |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-03-13, FR-2026-08-22-04, FR-2026-08-22-06 |

### Description

`scripts/run_text_replacement_evaluations.py` shall generate previews for both
fitted document-text layout modes. For each input presentation it shall retain
the existing HTML report and artifact directory for `preserve-basic-layout`,
and write a separate source-font report named `<filename>.sf.html` with a
sibling `<filename>.sf/` artifact directory. The source-font report shall not
be mixed into the existing HTML file.

For every provider-specific replacement preview in the source-font report, its
HTML row shall contain a native-size `preserve-basic-layout-source-font`
rendering and a new-tab link to its source-font explicit-properties JSON
artifact. Its original rendering shall be retained in that report as the visual
comparison baseline. The existing Noto-mode report and artifacts shall remain
unchanged.

The source-font preview shall call the common source-font resolver and bounded
layout core required by FR-2026-08-22-04. It shall use the same source bounds,
source-width/natural-height behaviour for explicit `noAutofit`, paragraph
replacement, wrapping, font-size fitting, and face-selection priority as the
folder-replacement source-font mode. For the evaluator's PPTX inputs, it shall
offer a verified embedded source face when the PPTX embedded-font support of
FR-2026-08-22-06 is available; otherwise it shall offer an exact installed
source face where available, before using the committed Noto fallback.

The source-font explicit-properties artifact shall identify the selected
measurement face, its selection diagnostic, and the resulting scale and fit
status. It shall distinguish `embedded-source-face`,
`installed-source-face`, and `noto-fallback`, including the fallback reason.
The bitmap shall render with the face selected for measurement, so it is a
review of the source-font mode's layout calculation rather than a guarantee of
how a document will render on another machine without that face.

The evaluator shall preserve the existing confidential-sample handling and
external-resource boundary. It shall not fetch a font or open a document-named
path or URL. The source-font report is allowed to be wider than the viewport
and shall retain native bitmap dimensions.

### Rationale

Source-font fitting deliberately permits host-dependent results. Side-by-side
local previews, together with an explicit record of the selected measurement
face and fallback decision, make those results reviewable before users rely on
the mode for document output.

### Notes

This requirement expands the evaluator only; it does not make
`preserve-basic-layout-source-font` available for any additional document
containers. Before PPTX embedded-font support is implemented, evaluator
previews can still exercise exact installed-font and Noto-fallback paths.

Automated tests shall use synthetic presentations and injected embedded or
host-face candidates. They shall verify a `<filename>.sf.html` report and its
separate artifact directory, one source-font preview and JSON artifact per
replacement preview, resolver priority and diagnostics in the artifact, Noto
fallback, the existing Noto report remaining unchanged, and no dependency on
fonts installed on the test host.

---

## FR-2026-08-22-10

| Property | Value |
|----------|-------|
| Title | Resolve PPTX theme typeface aliases for source-font fitting |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request and source-font evaluation diagnosis |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-03-13, FR-2026-08-03-15, FR-2026-08-22-04, FR-2026-08-22-09 |

### Description

For PPTX input processed in `preserve-basic-layout-source-font` mode, the
PPTX adapter and native-text evaluator shall resolve DrawingML theme typeface
aliases to concrete family requests before calling the common source-font
resolver. They shall resolve the text container's reachable theme part through
the package relationship chain; they shall not assume that a part named
`ppt/theme/theme1.xml` applies to every slide or text frame.

The adapter shall resolve the DrawingML major and minor aliases `+mj-lt`,
`+mj-ea`, `+mj-cs`, `+mn-lt`, `+mn-ea`, and `+mn-cs` through the corresponding
`a:fontScheme` major or minor Latin, East Asian, or complex-script slot. It
shall retain direct concrete typeface names unchanged. It shall consider
script-specific `a:font` entries in the selected theme when the applicable
major or minor slot delegates to one of those entries.

The adapter shall retain separate source typeface declarations for the Latin,
East Asian, and complex-script slots of a run. It shall choose the applicable
concrete family for each character or contiguous script segment, then provide
those segments to the shared source-font resolver and layout renderer. It shall
not treat a Latin theme alias as evidence that its resolved Latin face covers
East Asian text. When the theme, relationship, alias, script, or concrete face
cannot be resolved safely, that segment shall follow the Noto fallback rules
of FR-2026-08-22-04.

Theme resolution shall affect measurement and evaluator rendering only. The
PPTX writer shall preserve the original typeface aliases and script-specific
references in source-font output unless an existing explicit-layout rule
requires another source-preserving serialization. Evaluator source-font JSON
shall record the original alias, resolved concrete family, script or segment,
and final face-selection diagnostic.

### Rationale

Theme aliases are symbolic pointers into a presentation's design system, not
font family names. Resolving them before fitting lets the source-font mode use
the family PowerPoint intends for each script, while retaining the original
theme-driven formatting in the editable output.

### Notes

This is the first format-specific indirect-typeface implementation required by
FR-2026-08-22-04. It does not add embedded-font extraction; PPTX embedded-font
handling remains FR-2026-08-22-06. It shall not follow an external package,
filesystem path, or URL while resolving a theme.

Automated tests shall use synthetic PPTX packages with relationship-reachable
themes. They shall verify every major/minor and Latin/East Asian/complex-script
alias, direct-family preservation, script-segment selection, an unresolved
theme fallback, source-font JSON diagnostics, unchanged source aliases in
written output, and no dependency on fonts installed on the test host.

---

## FR-2026-08-22-11

| Property | Value |
|----------|-------|
| Title | Resolve DOCX theme fonts for source-font fitting |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-22-04, FR-2026-08-22-05 |

### Description

For eligible DOCX DrawingML text containers processed in
`preserve-basic-layout-source-font` mode, the DOCX adapter shall resolve
WordprocessingML run-font settings through direct run properties, applicable
character and paragraph styles, document defaults, and the document theme
before calling the common source-font resolver. It shall preserve the original
WordprocessingML references when writing source-font output.

The adapter shall resolve `w:asciiTheme`, `w:hAnsiTheme`, `w:eastAsiaTheme`,
and `w:cstheme` font references to the reachable Word theme's DrawingML
`a:fontScheme` major or minor Latin, East Asian, or complex-script slot. It
shall retain direct `w:ascii`, `w:hAnsi`, `w:eastAsia`, and `w:cs` family names
as concrete requests. It shall retain separate script-specific requests and
select the applicable face by character or contiguous script segment; it shall
not use a Latin request as proof that a face covers East Asian or complex-script
text.

Theme and style resolution shall use only parts and relationships contained in
the DOCX package. A missing, malformed, unreachable, or cyclic style/theme
reference shall produce the ordinary Noto fallback for the affected segment.
Evaluator diagnostics introduced for a future DOCX evaluator shall record the
original reference, resolved family, script segment, and final selection.

### Rationale

Word documents can inherit symbolic theme-font settings through several style
layers. Resolving those layers makes source-font measurement reflect the
document's intended typography without changing the theme-driven editable
formatting retained in output.

### Notes

This requirement does not add fitting for flowing Word paragraphs or alter
their existing source-formatting fallback. Embedded DOCX source-font recovery
remains FR-2026-08-22-05. Automated tests shall use synthetic DOCX packages
with document defaults, styles, and relationship-reachable themes; they shall
verify direct overrides, each theme font attribute, script segmentation,
fallbacks, and unchanged serialized source references.

---

## FR-2026-08-22-12

| Property | Value |
|----------|-------|
| Title | Resolve XLSX workbook theme fonts for source-font fitting |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-04-07, FR-2026-08-22-04 |

### Description

For eligible XLSX cells and DrawingML text processed in
`preserve-basic-layout-source-font` mode, the XLSX adapter shall resolve the
workbook's contained theme and font-style records before calling the common
source-font resolver. It shall preserve the original style and DrawingML font
references when writing source-font output.

For worksheet cells, the adapter shall resolve an `x:font` with an `x:scheme`
value of `major` or `minor` through the workbook theme's `a:fontScheme` major
or minor slots. A direct `x:name` remains a concrete family request unless the
format specifies that the selected scheme overrides it. For DrawingML text,
the adapter shall resolve DrawingML major/minor Latin, East Asian, and
complex-script aliases under the same rules as FR-2026-08-22-10. It shall keep
script-specific requests distinct and select concrete faces per character or
contiguous script segment.

The adapter shall use only relationship-reachable theme and style parts inside
the workbook. A missing or malformed theme, unsupported scheme value, or
unresolvable script slot shall use the common Noto fallback for that segment.
It shall not make XLSX font embedding portable or fetch an external font.

### Rationale

Excel styles can request the major or minor workbook theme fonts instead of a
literal family name, while drawing text uses DrawingML's richer script-aware
font model. Resolving both paths provides metrics consistent with a workbook's
design without altering its existing style references.

### Notes

This requirement does not change finite-cell eligibility, structured-table
handling, or XLSX's lack of an interoperable embedded-font path. Automated
tests shall use synthetic workbooks with relationship-reachable themes and
both cell and drawing text. They shall verify major/minor schemes, direct-name
precedence, DrawingML aliases, script segmentation, safe fallback, and
unchanged source style references.

---

## FR-2026-08-22-13

| Property | Value |
|----------|-------|
| Title | Resolve SVG CSS font inheritance and stacks for source-font fitting |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-22-04, FR-2026-08-22-08 |

### Description

For eligible SVG text processed in `preserve-basic-layout-source-font` mode,
the SVG adapter shall compute the applicable `font-family`, `font-weight`, and
`font-style` from the element, inherited SVG/CSS properties, and contained
`style` rules before calling the common source-font resolver. It shall preserve
the original SVG and CSS font declarations in source-font output.

The adapter shall parse a CSS `font-family` list as an ordered set of concrete
family candidates. For each character or contiguous script segment it shall
offer candidates in CSS order to the common resolver, selecting the first
exact embedded or installed face that matches the requested style and covers
the segment's glyphs. If none is usable, it shall use the common Noto fallback.
Generic CSS family names and unsupported CSS expressions shall not be mistaken
for installed family names; they shall follow an explicitly specified fallback
policy before Noto is selected.

The adapter shall process only styles and `@font-face` data contained inside
the SVG. It shall not load external stylesheets, URLs, paths, CSS imports, or
font resources. Inline embedded-font use remains subject to FR-2026-08-22-08.

### Rationale

SVG typography is usually governed by CSS inheritance and ordered fallback
stacks, rather than a single direct family attribute. Computing the effective
stack lets source-font measurement follow the author’s intended fallback order
without crossing the existing external-resource trust boundary.

### Notes

This requirement does not add general HTML/CSS layout support. The supported
selector subset is element, `.class`, `#id`, and descendant combinations of
those forms, using ordinary specificity and source-order precedence.
Custom properties and `var()` are unsupported: a declaration using `var()` is
ignored. `serif`, `monospace`, and `sans-serif` map respectively to the
committed Noto serif, mono, and sans fallback classifications; they are never
accepted as a host-family match. Text inside `foreignObject` is outside this
fitted SVG-text scope. Automated tests shall use synthetic SVGs with inline
styles and repository-owned test fonts; they shall verify inheritance, stack
order, style matching, glyph fallback, malformed-CSS fallback, and that no
external reference is opened.

---

## FR-2026-08-23-01

| Property | Value |
|----------|-------|
| Title | Fit replacement text in inferred PDF visual text regions |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following PDF layout review |
| Date Added | 2026-08-23 |
| Related Requirements | FR-2026-08-03-07, FR-2026-08-03-14, FR-2026-08-04-07, FR-2026-08-04-09, FR-2026-08-04-10 |

### Description

This requirement extends `preserve-basic-layout` to eligible native text
shown by PDF page-content streams and Form XObjects. It supersedes the
prohibition on inferred PDF bounds in FR-2026-08-04-09 only for text that
meets the eligibility rules below. Existing FreeText-annotation and AcroForm
behaviour remains unchanged.

The PDF adapter shall build visual text regions from visible text-showing
operations. It shall calculate each source glyph or run's position, baseline,
advance, and transform from the active PDF graphics state, text state, font,
and text-showing operators. It shall not treat a PDF text operand, word,
space character, individual glyph, or `BT`/`ET` text-object boundary as a
paragraph boundary.

PDF glyph advances are expressed in text space. The adapter shall transform
each advance through the active text matrix and current transformation matrix
before using it to calculate source-region geometry. It shall account for text
state that affects placement, including font size, horizontal scaling,
character spacing, word spacing, leading, text rise, and text rendering mode.
When it writes fitted text, it shall preserve an equivalent placement transform
or normalize that transform exactly once. It shall not omit or apply a source
transform twice.

For each candidate region, the adapter shall:

1. Collect placed, decoded text chunks throughout the current page-content or
   Form-XObject content scope, including chunks in separate `BT`/`ET` text
   objects. Group compatible contiguous chunks into visual runs and visual
   lines using their common baseline, orientation, proximity, and applicable
   graphics state.
2. Determine reading order from the visual layout within a region, rather than
   relying on the order of independent PDF content-stream operations.
3. Measure the source text at its original effective size and transform to
   derive a finite occupied region. The measurement shall use a verified
   source face when available; otherwise it shall use the PDF text-placement
   geometry and glyph advances. Character count alone shall not determine a
   region's bounds.
4. Classify the result as either a visual line, which retains its original
   line region and baseline, or a visual text block, whose replacement may
   wrap and reflow within the inferred block region.

A visual text block is eligible only when the adapter can deterministically
identify a finite region containing multiple compatible lines with a common
orientation, text flow, and compatible text-painting state. The adapter shall
not merge text across columns, table-like row or cell boundaries,
independently positioned labels, materially different transforms, clipping
boundaries, opacity, or colour state. If block classification is uncertain, it
shall use independent visual-line fitting rather than paragraph reflow.

For an eligible visual line or block, the adapter shall use the shared
bounded-text layout core. It shall pass the complete region text to the
selected text-replacement provider, fit the returned replacement to that
region, preserve the source orientation and alignment, and record whether the
result fitted or overflowed. `preserve-basic-layout` shall use the configured
portable target-language face and normal fitted-layout rules.

The adapter shall replace the source text painting rather than paint an opaque
background over it. It shall preserve applicable surrounding graphics state,
including clipping, colour, opacity, and the region's placement transform. It
shall not alter unrelated page content.

Eligibility requires all of the following:

- the source text is visible text rather than text used only for clipping,
  masking, or an invisible rendering mode;
- the source can be decoded reliably enough for the selected replacement
  provider;
- the adapter can derive a finite non-degenerate visual line or block region;
- the adapter can safely replace every source text-showing operation belonging
  to that region; and
- a font can render every replacement character.

An undecodable, unsupported, non-visible, or unsafe source text operation
shall be retained unchanged and act as a visual-region boundary. It shall not
make other independently eligible text in the same `BT`/`ET` text object
ineligible.

General Unicode replacement for eligible page-content and Form-XObject text
requires FR-2026-08-04-10. Until that requirement is implemented, an item for
which the active source font cannot encode the replacement shall remain
unchanged and be reported as unsupported; it shall not use an ASCII masking
fallback for translated output.

The initial scope shall support ordinary horizontal text and text rotated by a
multiple of 90 degrees, including scaled placements. It shall support text
inside reusable Form XObjects in their local coordinate system.

### Rationale

A PDF page commonly contains text positioned as fragments, words, or glyph
runs rather than as a reflowable paragraph. Reconstructing a visual line or a
well-evidenced visual block provides a bounded region comparable to a
PowerPoint text frame, allowing translated replacement text to be fitted
without treating arbitrary PDF operator boundaries as layout structure.

### Notes

This requirement does not require PDF tags or a semantic document structure.
Tags may be used as a future hint, but visual geometry remains the authority
for placement.

An identity replacement provider is a source-equivalent fitted-layout control.
It shall pass through the same region inference, measurement, bounded fitting,
target-face selection, and PDF output-drawing path as any other replacement;
it shall not bypass or retain the original source painting. Its rendered result
should preserve the original text's visual placement and size as closely as
the configured replacement face permits. Tests shall verify that replacement
drawing was emitted for both an identity replacement and a changed
replacement.

Table-like layouts, contents pages, forms, labels, and multi-column pages are
supported initially through separate visual-line fitting. They shall not be
treated as prose blocks unless a later requirement defines reliable cell or
table reconstruction.

The following remain out of scope: outlined/path-only text, image-only pages
(which use the existing OCR path), arbitrary-angle or sheared text, Type 3 or
otherwise non-standard text rendering that cannot be safely replaced, text
used as a clipping or masking path, and decorative text following a path.

Automated tests shall use synthetic PDFs only. They shall cover fragmented
`Tj` and `TJ` text, separately positioned runs forming one line, multi-line
paragraph blocks, multi-column text, table-like rows, contents-page leaders,
nested and reusable Form XObjects, 90-degree rotated text, Unicode fallback
eligibility, uncertain-block line fallback, and unsupported clipping,
outlined, and image-only cases. They shall also cover non-unit text matrices,
current-transformation-matrix scaling, horizontal text scaling, and a text
object containing both an unsupported operation and a separately eligible
operation. Tests shall verify that transformed source bounds are correct, that
the eligible operation is replaced while the unsupported operation is
unchanged, and that fitted output uses the expected replacement font size and
placement. Rendered output shall be visually verified by an independent PDF
renderer.

---

## FR-2026-08-23-02

| Property | Value |
|----------|-------|
| Title | Preserve PDF text paint state when fitting visual regions |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following native-PDF layout evaluation |
| Date Added | 2026-08-23 |
| Related Requirements | FR-2026-08-23-01, FR-2026-08-04-09 |

### Description

For eligible ordinary fill-text regions (PDF text rendering mode `0`), a
graphics-state transition later in the same `BT`/`ET` text object shall not
cause an earlier independently eligible region to remain unchanged solely
because replacement text would otherwise be emitted after `ET`.

The PDF adapter shall associate every candidate visual region with the
graphics and text paint state that applied when its source text was painted.
It shall emit the fitted replacement while that state applies. The adapter may
do this by writing replacement operations at the source location within the
existing text object and restoring the subsequent text state, or by splitting
and reconstructing equivalent text objects. It shall not nest `BT`/`ET` text
objects or change the rendering of later source operations.

The replacement shall preserve the region's applicable fill colour, colour
space, opacity, blend state, clipping, and placement transform. A transition
of any of those properties shall be a visual-region boundary: chunks on each
side shall be fitted separately unless a later requirement defines a safe
cross-state grouping rule. A later transition shall not retroactively make an
earlier region in a different paint state ineligible.

This requirement applies to page content and reusable Form XObjects. It does
not require support for stroked, fill-and-stroke, clipping, invisible, or
otherwise non-fill text rendering modes.

### Rationale

PDF generators commonly retain a long text object while changing fill colour
for a link, label, or emphasis. Emitting every replacement only after the
text object's `ET` cannot preserve the paint state of its earlier text. The
replacement must instead be anchored to the source region's state.

### Notes

Automated tests shall use synthetic PDFs only. They shall include one text
object containing multiple visible fill-text regions separated by fill-colour
and opacity changes, including a transition back to an earlier colour. Tests
shall verify that every eligible region is replaced, each replacement retains
its source paint state, later source text remains semantically and visually
unchanged apart from its own replacement, and the output renders in an
independent PDF renderer.

## FR-2026-08-23-03

| Property | Value |
|----------|-------|
| Title | Use fill-only portable replacement for fill-and-stroke PDF text |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following native-PDF layout evaluation |
| Date Added | 2026-08-23 |
| Related Requirements | FR-2026-08-23-01, FR-2026-08-23-02 |

### Description

`preserve-basic-layout` shall support eligible text painted with PDF text
rendering mode `2` (fill and stroke). It shall fit the replacement using the
same visual-region rules as ordinary fill text. The portable replacement shall
be painted in rendering mode `0` (fill-only), using the source fill colour,
colour space, opacity, blend state, clipping, and placement transform.

The replacement shall not apply the source stroke colour, stroke width, dash,
join, cap, or other stroke state. Retaining or compensating a source text
stroke for a portable target font is out of scope for this requirement and
requires a later explicit style policy.

The adapter shall calculate and retain text-position state through eligible
mode-`2` source text. A later independently eligible fill-only region in the
same `BT`/`ET` text object shall remain eligible without requiring a reset
text matrix. A change to text rendering mode, stroke colour, stroke width, or
other applicable stroke state shall be a visual-region boundary.

Stroke-only, clipping, invisible, and other non-fill text rendering modes
remain out of scope.

### Rationale

Mode `2` is visible selectable text, but a source outline stroke is not a
portable font-weight instruction. Applying it unchanged to a different target
face, particularly after fitting to a smaller size, can make replacement text
materially heavier than the source. Fill-only output is the predictable
baseline for translated and masking output.

### Notes

Automated tests shall use synthetic mode-`2` text and verify, in an
independent PDF renderer, that the source text painting is replaced by
fill-only portable output with the source fill paint state. They shall include
an ordinary fill-only operation after mode-`2` text in the same text object
and verify that both regions are replaced without a reset text matrix.

---

## FR-2026-08-23-04

| Property | Value |
|----------|-------|
| Title | Use Type0 CID width tables for PDF visual-region geometry |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following PDF measurement review |
| Date Added | 2026-08-23 |
| Related Requirements | FR-2026-08-23-01, FR-2026-08-04-09 |

### Description

When deriving an eligible Type0 PDF text run's source advance, the PDF
adapter shall use the active descendant CIDFont's per-CID `/W` width table
when a safe code-to-CID mapping is available. It shall use the descendant's
`/DW` default width only for CIDs not covered by `/W`.

The adapter shall determine source character-code boundaries using the active
PDF CMaps. It shall not assume that source character codes are two bytes, that
`/Identity-H` applies, or that a `/ToUnicode` mapping can be reversed to find
a CID. A `/ToUnicode` CMap remains decoding evidence; the active encoding CMap
is the authority for mapping a source code to a CID for width lookup.

If the adapter cannot determine a code-to-CID mapping safely, it shall retain
the existing conservative source-advance fallback. It shall not invent a CID
from Unicode text. This requirement changes source-region measurement only;
it does not change replacement font selection or encoding.

### Rationale

Type0 CIDFonts often use widths that vary by CID. Treating every decoded code
as the `/DW` default can over- or under-estimate a source visual line, causing
unnecessary shrinking, wrapping, or poor placement of a fitted replacement.

### Notes

Automated tests shall use synthetic Type0 fonts with an Identity encoding and
mixed `/W` and `/DW` coverage. They shall verify source-line advance, inferred
region width, fitted replacement size, and placement. Tests shall also cover
variable-length source codes and a non-identity encoding case; an unresolved
mapping shall take the documented fallback without emitting an invented CID.

---

## FR-2026-08-23-05

| Property | Value |
|----------|-------|
| Title | Preserve PDF text positioning across undecodable source text |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following native-PDF layout evaluation |
| Date Added | 2026-08-23 |
| Related Requirements | FR-2026-08-23-01, FR-2026-08-23-04 |

### Description

When a visible source text-showing operation cannot be decoded for the text
replacement provider, `preserve-basic-layout` shall retain that operation
unchanged and make it a visual-region boundary. If the adapter can determine
the operation's advance safely from the source font, active encoding CMap,
text-showing operator, and current text state, it shall advance its internal
text-position state by that amount.

This shall allow a later independently eligible text operation in the same
`BT`/`ET` object to be inferred and replaced without requiring an intervening
`Tm`, `Td`, `TD`, or other text-position reset. The undecodable source text
shall not be sent to the replacement provider and shall not be incorporated
into a replacement visual region.

For `Tj`, `TJ`, `'`, and `"` operations, calculated advance shall include
source glyph widths, `TJ` numeric adjustments, character spacing, word
spacing, horizontal scaling, and any operator-defined line movement. The
adapter shall use the active source encoding CMap to establish code
boundaries; it shall not infer widths from decoded Unicode text.

If complete advance cannot be determined safely, the adapter shall retain the
operation unchanged and preserve the existing conservative positioning
barrier. It shall not guess character boundaries, CIDs, glyph widths, or text
advance.

### Rationale

PDF text positioning is stateful. An undecodable glyph can be left visually
unchanged without making a later decodable run unsafe, provided its advance is
known. Treating every undecodable operation as an unknown-position barrier
unnecessarily leaves later, independently replaceable text unchanged.

### Notes

Automated tests shall use synthetic PDFs only. They shall include an
undecodable composite-font operation with a safe encoding-CMap/width-based
advance followed by a decodable ordinary-fill operation in the same text
object without a text-matrix reset. Tests shall verify that the former remains
unchanged, the latter is replaced at its original visual position, and an
unknown code-to-CID mapping retains the conservative barrier.

---

## FR-2026-08-23-06

| Property | Value |
|----------|-------|
| Title | Recover Unicode from embedded Identity CID fonts when `/ToUnicode` is incomplete |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following native-PDF text-replacement evaluation |
| Date Added | 2026-08-23 |
| Related Requirements | FR-2026-08-23-01, FR-2026-08-23-04, FR-2026-08-23-05 |

### Description

For an otherwise eligible Type0 source-text operation, the PDF adapter shall
prefer the source `/ToUnicode` CMap. When that CMap is absent or does not map
every source code in an operation, the adapter shall attempt an embedded-font
Unicode recovery path before classifying the operation as undecodable.

The initial recovery path applies only when all of the following hold:

- the active source encoding is `/Identity-H`;
- the descendant CIDFont declares `/CIDToGIDMap /Identity`;
- the descendant font descriptor contains an embedded TrueType or OpenType
  font program with a parseable Unicode `cmap`; and
- every source code can be mapped through a complete, unambiguous chain of
  source code to CID, CID to GID, and GID to exactly one Unicode text value.

For a conforming Identity-H operand, the adapter shall read source codes as
two-byte CIDs. For a single-byte source string operand, it may apply an
Identity-H compatibility mapping by zero-extending that byte to a CID only
when the resulting GID has exactly one Unicode mapping in the embedded font's
`cmap`. It shall not apply this compatibility mapping to a multi-byte operand,
split an even-length operand into one-byte CIDs, or choose between multiple
possible code segmentations or Unicode values.

When recovery succeeds, the adapter shall use the recovered Unicode text for
the selected text-replacement provider and shall retain the existing
PDF-derived glyph-width and text-position calculations for visual geometry.
Recovered text shall participate in the same visual-region inference,
replacement, paint-state preservation, and fitting path as text decoded from
`/ToUnicode`.

The adapter shall cache parsed embedded-font Unicode maps per source font for
the duration of one document. It shall not use operating-system fonts, font
name heuristics, OCR, or network resources as part of this decoding path.

If any source code, CID, GID, embedded font, or Unicode mapping is missing,
ambiguous, malformed, or unsupported, the adapter shall retain the source
operation unchanged and follow the existing safe-positioning behaviour. It
shall not guess text from glyph outlines or use a placeholder character as a
translation input.

### Rationale

Some PDFs contain visible selectable text whose `/ToUnicode` CMap is absent
or incomplete even though the embedded CID font provides an unambiguous
Unicode mapping. A PDF viewer can often use that mapping for copy and select
operations. Recovering it through a verified source-code-to-glyph chain makes
the text available to every replacement provider, including translation,
without weakening the existing conservative handling of genuinely opaque
glyph codes.

### Notes

Automated tests shall use synthetic PDFs and non-confidential font assets.
They shall cover a Type0 Identity-H font with an Identity CID-to-GID map and
embedded Unicode `cmap` where `/ToUnicode` is incomplete; a successful
two-byte recovery; a successful single-byte compatibility recovery; and
rejection of ambiguous, missing, non-Identity, and multi-byte compatibility
cases. Tests shall verify provider input, source-region placement, and that a
rejected operation remains unchanged without suppressing a later independently
eligible operation.

---

## FR-2026-08-24-01

| Property | Value |
|----------|-------|
| Title | Reliably decode Type0 PDF text when high-level decoding yields whitespace |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following native-PDF text-replacement evaluation |
| Date Added | 2026-08-24 |
| Related Requirements | FR-2026-08-23-01, FR-2026-08-23-04, FR-2026-08-23-05, FR-2026-08-23-06 |

### Description

For Type0 source text, the adapter shall not treat a structurally present
`/ToUnicode` CMap as reliable merely because it maps every source code. A
mapping that produces only whitespace or other semantically implausible output
for visible non-whitespace source glyphs shall be treated as unreliable. The
adapter shall first parse the PDF's `/ToUnicode` CMap according to its code
space and mapping rules rather than relying solely on a library's simplified
font-decoding helper. It may then use a deterministic recovery route supported
by the PDF itself, including the embedded-font recovery of FR-2026-08-23-06.

If no complete, unambiguous, in-document Unicode recovery route is available,
the adapter shall leave the source operation unchanged. It shall not infer
Unicode from glyph outlines, host fonts, OCR, or network resources. Use of an
external CID-collection mapping is out of scope unless a later requirement
defines its provenance, licensing, versioning, and validation.

### Rationale

PDF viewers can sometimes recover text from Type0 fonts through decoding paths
that differ from a library's high-level helper. Parsing the document's own
Unicode CMap before declaring text undecodable prevents a helper limitation
from silently turning meaningful visible text into whitespace while retaining
the conservative no-guessing policy for genuinely opaque fonts.

### Notes

Automated tests shall use only synthetic PDFs and non-confidential font assets.
They shall also cover a Type0 font whose direct `/ToUnicode` CMap parsing
recovers visible non-whitespace text when the existing high-level decoding
helper does not, plus a CMap or embedded font for which recovery is ambiguous
or unavailable. The former shall reach the provider and semantic replacement
path; the latter shall remain unchanged and shall not emit a placeholder or
replacement. Tests shall verify provider input and visual behavior with an
independent PDF renderer.

---

## FR-2026-08-24-02

| Property | Value |
|----------|-------|
| Title | Make fitted replacement text authoritative for PDF copy and search |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following native-PDF text-replacement evaluation |
| Date Added | 2026-08-24 |
| Related Requirements | FR-2026-08-23-01, FR-2026-08-24-01 |

### Description

For every source text-showing operation that is safely replaced by
`preserve-basic-layout`, the fitted replacement shall become the authoritative
semantic text of the output PDF. Standard PDF text extraction, selection,
copy, and search shall expose the replacement text, in its provider-returned
Unicode order, rather than the source text.

The adapter shall not retain the replaced source `Tj`, `TJ`, `'`, or `"`
operand as hidden, invisible, or otherwise non-painted selectable text. It
shall instead remove or rewrite that source text representation and preserve
the required text-position state for subsequent page content. The output must
therefore retain the visual placement of later independent content without
leaving the replaced source text discoverable through the normal PDF text
layer.

The replacement font encoding shall provide a complete, unambiguous Unicode
mapping for every emitted replacement glyph. The generated text stream and
its `/ToUnicode` mapping shall together extract as exactly the replacement
text; visible glyph placement alone is insufficient.

When the source content is inside marked content whose alternate text affects
selection, copy, or extraction, the adapter shall update that alternate text
to the replacement text or remove it if it no longer represents the replaced
content. If it cannot safely update or remove an applicable alternate-text
representation, it shall leave that source operation unchanged rather than
produce a visual and semantic mismatch.

This requirement applies only to operations that otherwise meet the safe
replacement eligibility requirements. Unsupported or undecodable source text,
and existing FreeText annotations and AcroForm field values, remain unchanged.

### Rationale

Hiding source glyph painting can preserve the page's appearance and text
positioning, but it leaves the source string in the PDF text layer. That makes
copy, selection, and search disagree with the document the user sees. A
replacement pipeline intended for translation or masking must replace both
representations.

### Notes

Automated tests shall use only synthetic PDFs and non-confidential font assets.
They shall cover a replaced `Tj` and `TJ` operation whose original source text
is no longer returned by extraction; successful search, selection, and copy
of the replacement Unicode text; a generated-font `/ToUnicode` mapping;
preservation of the following operation's visual position after the source
showing operation is removed or rewritten; and marked content with an
`/ActualText` value. Tests shall verify semantic behavior with an independent
PDF text extractor and visual behavior with an independent PDF renderer.

---

## FR-2026-08-27-02

| Property | Value |
|----------|-------|
| Title | Apply the PPTX source-font fitted-layout interpretation consistently across document formats |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following cross-format layout review |
| Date Added | 2026-08-27 |
| Related Requirements | FR-2026-08-03-14, FR-2026-08-04-07, FR-2026-08-04-09, FR-2026-08-04-10, FR-2026-08-22-04, FR-2026-08-22-05, FR-2026-08-22-07, FR-2026-08-22-08, FR-2026-08-22-11, FR-2026-08-22-12, FR-2026-08-22-13, FR-2026-08-23-01, FR-2026-08-24-02, FR-2026-08-27-05 |

### Description

`preserve-basic-layout-source-font` shall have one meaning for every supported
fitted document-text container: PPTX, DOCX drawing text, XLSX cells and
drawing text, PDF text, and SVG text.

For each eligible text container, the adapter shall resolve the effective
source font request, including any applicable theme, style, CSS, or selected
font-object indirection.  It shall first attempt to measure the source text
with that source face, so that any source-derived bounds reflect the source
document's actual typography.  An exact embedded source face is preferred,
then an exact installed source face.  If neither is available or usable, it
shall use the appropriate committed Noto face for source measurement.

The adapter shall separately select the font used for the fitted replacement
and output.  It shall use the source face only when that face is available,
can render every replacement glyph, and can be safely represented by the
output format.  Otherwise it shall use the appropriate committed Noto face.
Replacement fitting shall use the same face that the output uses.
FR-2026-08-27-05 supersedes this single-face fallback rule only for a
replacement that requires multiple portable faces; it does not change the
source-font measurement rule.

The mode shall always use the normal bounded-layout replacement, wrapping, and
font-size fitting path.  It shall not retain the original size or bypass
fitting merely because the source face is unavailable or cannot render the
replacement.  `preserve-basic-layout` remains the deterministic Noto mode.

This requirement does not widen fitted-layout eligibility.  A container that
is unbounded, cannot be safely rewritten, or cannot be decoded safely shall
continue to use its existing `preserve-source-formatting` fallback.  Source
font parts, resources, references, and relationships shall remain unchanged;
the pipeline shall not fetch, modify, expand, subset, or redistribute a source
font.

For PDF, all existing rules for visual-region inference, paint state, text
semantics, encoding, FreeText annotations, AcroForm fields, and safe fallbacks
remain unchanged.  The only change is that source-font mode shall use the
source-measurement and output-font-selection rules above instead of direct
text-operand substitution.  If a PDF source font cannot safely encode the
replacement, the existing portable Noto Unicode output path shall be used.

This requirement supersedes the source-font-mode clauses of
FR-2026-08-04-09 and FR-2026-08-22-04.  It does not supersede any other PDF
or format-specific safety rule.

### Rationale

Using the source face for source measurement gives more accurate source-derived
bounds.  Selecting the replacement/output face separately prevents missing
glyphs or a non-embeddable source font from producing unreadable output.  This
makes the mode predictable across formats without changing their existing
format-specific safety behaviour.

### Notes

The mode remains machine-dependent when it uses an installed source face.
Embedded-source-font support remains separately scoped by the related
requirements.  PDF portable Unicode output depends on FR-2026-08-04-10; the
existing ASCII masking fallback is not an acceptable source-font output.

Automated tests shall use synthetic documents and repository-owned fonts only.
For each eligible adapter, they shall verify source-font measurement, source
font output when it covers the replacement, Noto output when it does not, and
fitted output in every case.  PDF tests shall additionally retain the existing
visual, encoding, copy/search, and appearance validation.

---

## FR-2026-08-27-03

| Property | Value |
|----------|-------|
| Title | Provide portable Noto fallback coverage for fitted PDF page visual text |
| Owner | KrisTC |
| Status | Implemented |
| Source | Implementation review following Google Cloud Translation run |
| Date Added | 2026-08-27 |
| Related Requirements | FR-2026-08-03-14, FR-2026-08-04-10, FR-2026-08-27-02, FR-2026-08-27-05, FR-2026-08-27-06, FR-2026-08-27-07, FR-2026-08-27-09 |

### Description

For every eligible fitted PDF page-content visual-text region in both
`preserve-basic-layout` and `preserve-basic-layout-source-font`, a replacement
shall not be skipped solely because the initially selected portable Noto face
lacks a replacement glyph. The adapter shall select a project-selected,
static, embeddable Noto fallback that covers every non-whitespace replacement
character and shall use that same face for fitting and output.

The portable fallback shall be selected deterministically from the requested
target-language BCP 47 tag and replacement text. The project shall maintain a
small explicit mapping from supported target-language/scripts to static Noto
faces and weights. It shall identify the official Noto download source and SIL
OFL licence for each additional face. It shall also define any
script-segmentation rule if no one selected face covers a complete replacement.
The pipeline shall not download fonts during document processing or use
host-installed fonts for this portable fallback.

Initially, English (`en`), Danish (`da`), French (`fr`), Spanish (`es`), and
Japanese (`ja`) use the committed Noto Sans JP, Noto Serif JP, and Noto Sans
Mono faces by broad classification. Chinese is not initially supported by this
requirement. The optional Noto Sans Math and Noto Sans Symbols 2 faces and
their bootstrap are defined by FR-2026-08-27-07 and FR-2026-08-27-04. The PDF
adapter selects portable segments in the base-to-math-to-symbol order defined
by FR-2026-08-27-07.

For a target language outside the approved portable-coverage set, or a
replacement that no approved fallback can cover, the PDF adapter shall retain
only the affected visual text region and, in a debug run, report it once as
unsupported under FR-2026-08-27-06. It shall not warn once per region, replace
unsupported characters with unrelated glyphs, or use the ASCII masking
fallback for translation output.

This requirement completes the portable Unicode output required by
FR-2026-08-27-02 for eligible fitted PDF page visual text. The PDF eligibility,
painting, encoding, and copy/search rules remain unchanged. Unbounded PDF
page-content and Form-XObject text remain controlled by FR-2026-08-04-10.
PDF FreeText annotations and AcroForm fields, together with all non-PDF
adapters, are separately controlled by FR-2026-08-27-09.

### Rationale

The current committed static faces are Japanese/Latin-focused. Selecting an
approved portable face before fitting prevents a glyph-coverage failure from
turning an otherwise eligible PDF visual region into an unexplained omission.

### Notes

The committed Japanese/Latin base assets remain available without bootstrap,
including for synthetic tests and the existing offline path. Optional math and
symbol faces are obtained only by the local bootstrap specified in
FR-2026-08-27-04; they are not committed merely to make every possible target
script available.

Automated tests shall use synthetic replacement text. They shall verify that a
first-choice face without a glyph selects an approved covering fallback, the
fitted PDF output is renderable and parser-loadable, and no individual-region
coverage warning is emitted. Tests shall verify the debug unsupported outcome
for an unapproved target language or an uncovered character.

---

## FR-2026-08-27-04

| Property | Value |
|----------|-------|
| Title | Bootstrap optional font packs and PaddleOCR models before processing |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following runtime-asset review |
| Date Added | 2026-08-27 |
| Related Requirements | FR-2026-08-01-02, FR-2026-08-03-14, FR-2026-08-24-03, FR-2026-08-27-03 |

### Description

The project shall provide `scripts/bootstrap_runtime_assets.py`. It shall be a
simple, idempotent local setup command: it downloads every optional static Noto
font pack selected by the project's supported target-language/script mapping,
initially Noto Sans Math Regular and Noto Sans Symbols 2 Regular,
to one platform-standard, per-user font-cache directory outside a repository
checkout, then initializes PaddleOCR once for each of its currently supported
English and Japanese languages. It shall use the official Noto download source
selected by the project and PaddleOCR's normal official download mechanism. It
shall print the font-cache directory and PaddleOCR model-cache directory it
used, together with a short result, and fail clearly when a download or
PaddleOCR initialization fails.

The committed Japanese/Latin Noto faces shall remain the bootstrap-free base
font assets. They shall continue to support synthetic tests and the existing
offline Japanese/Latin layout path. Optional packs shall remain outside Git;
the project shall not acquire the entire upstream Noto collection merely
because it exists. A future mapping update shall add only the font packs needed
for its approved language/script coverage.

The exact replacement text is not known until translation, so every normal
folder-replacement invocation using either fitted layout mode for an approved
portable-coverage target language shall require every optional pack in that
mapping before it starts. Initially that means Noto Sans Math Regular and Noto
Sans Symbols 2 Regular.
The normal processing path shall use only the local font cache, select the
fallback defined by FR-2026-08-27-03, and use the selected face for both
fitting and output. It shall not fetch a font, inspect a host font, or silently
skip an eligible region during processing. If a required pack is absent, it
shall fail before processing any input document.

The folder-replacement script shall finish that preflight failure with one
concise, clearly labelled summary. It shall state that no input document was
processed, name each missing runtime asset and its shared-cache location, show
the bootstrap command that installs or initializes it, and tell the user to
rerun the folder replacement after bootstrap succeeds. It shall not emit a
per-region warning or argparse usage for this prerequisite failure. The
existing base fonts remain usable for synthetic tests and non-fitted paths;
the upfront optional-pack prerequisite is required only to guarantee the
fitted-layout behaviour of FR-2026-08-27-03.

PaddleOCR retains ownership of its normal local model cache and download
behaviour. The bootstrap exists only to pre-trigger that behaviour; it shall
not create a second model cache, lock model bytes, or alter PaddleOCR's cache
configuration. Adding a PaddleOCR language shall add one initialization step
to the bootstrap command.

The user-facing document-processing and OCR-evaluation scripts shall call one
small shared helper before starting work. The helper shall check the fitted
layout's optional packs and, when PaddleOCR is selected, whether the bootstrap
has been run successfully. It shall report all missing selected prerequisites
with a concise instruction to run the bootstrap command. `scripts/run.sh` and
`scripts/run.ps1` shall remain unchanged.

### Rationale

Downloading fonts or OCR models while a document is being processed causes
late, network-dependent failures. A small explicit setup step makes those
downloads happen at a convenient time without turning the wrappers or the
normal processing path into an asset-management system.

### Notes

The optional-font cache shall use the platform's normal per-user cache location
so multiple repository checkouts share it. Its location may be configurable by
an explicit environment variable. PaddleOCR models retain the default local
cache required by FR-2026-08-01-02, which is likewise shared independently of
the checkout. A small success marker may sit beside the optional font cache; it
shall not contain source document content, paths, text, credentials, or
translation responses.

The source and licence for each optional Noto pack shall be recorded beside the
font mapping. The project deliberately trusts the selected official Noto source
for this convenience feature; it does not require a separate artifact manifest,
download-size check, or checksum verification process.

Automated tests shall mock the downloads and PaddleOCR initialization. They
shall verify the bootstrap invokes every selected font and existing PaddleOCR
language, the fitted-layout font-cache prerequisite fails before processing,
the folder-replacement summary names the missing font and bootstrap command,
the successful marker is recognized, and the wrappers remain unchanged.

---

## FR-2026-08-27-05

| Property | Value |
|----------|-------|
| Title | Support multi-face portable fallback segments in fitted document text |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request following portable-font fallback review |
| Date Added | 2026-08-27 |
| Related Requirements | FR-2026-08-03-14, FR-2026-08-04-10, FR-2026-08-27-02, FR-2026-08-27-03, FR-2026-08-27-04, FR-2026-08-27-07, FR-2026-08-27-09 |

### Description

The shared fitted-text model shall support one replacement run being represented
by ordered output segments, each with an approved portable Noto face. This is
a core document-text-layout feature for both `preserve-basic-layout` and
`preserve-basic-layout-source-font`; it is not a PDF-only feature.

When no one approved portable face covers an entire replacement, the shared
layout path shall deterministically select covering faces for contiguous output
segments, then measure, wrap, and fit those segments together as one text box.
It shall not split a grapheme cluster, use a host-installed font, download a
font while processing, or substitute an unrelated glyph. Source-font mode
shall retain FR-2026-08-27-02's independent source-measurement rule; this
requirement changes only portable output selection and fitting.

The first implementation shall support left-to-right horizontal replacement
text only. It shall cover the approved English, Danish, French, Spanish, and
Japanese target-language set. A replacement containing a strong right-to-left
character or a bidirectional formatting control shall use the existing safe
unsupported outcome rather than approximate bidi layout. Vertical text and
full bidi layout remain later extensions. For this first implementation,
segment choice shall prefer the run's normal broad-classification base Noto
face, then Noto Sans Math, then Noto Sans Symbols 2; adjacent segments using
the same face shall be combined. If none covers a complete grapheme cluster,
the applicable safe unsupported outcome shall apply.

Every eligible format adapter shall serialize the selected segments using its
native multi-run representation and retain its existing safety rules. In PDF,
this includes switching the selected embedded font within generated text while
retaining correct painting, glyph encoding, `/ToUnicode`, copy/search, and
appearance behaviour. This requirement does not widen PDF eligibility or
change the rules for unbounded PDF page-content or Form-XObject text.

The fitted-run model refactor shall preserve the ordered segment representation
defined here. Full bidi and vertical-layout behaviour shall be specified before
those extensions are implemented.

### Rationale

PDF and the other supported native document formats can represent adjacent
runs with different fonts. Modelling this once in the shared layout pipeline
avoids inconsistent format-specific fallback decisions.

### Notes

Automated tests shall use synthetic mixed-script and symbol replacements. They
shall verify deterministic segment selection, jointly fitted wrapping, valid
output for each eligible adapter, and PDF visual and copy/search behaviour.

---

## FR-2026-08-27-06

| Property | Value |
|----------|-------|
| Title | Write a per-document folder-replacement diagnostic report when work is ignored or unsupported |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following identity-provider regression diagnosis |
| Date Added | 2026-08-27 |
| Related Requirements | FR-2026-08-03-14, FR-2026-08-27-03, FR-2026-08-27-05, FR-2026-08-27-09 |

### Description

For each source document with an unsupported file type, failed, or unsupported
work, a debug-enabled run shall write one JSON sidecar beside that document's
intended output path. `scripts/run_folder_replacement.py` shall enable this
with an explicit `--debug` flag; ordinary runs shall not create diagnostic
sidecars. `scripts/run_development_folder_replacement.py` shall always pass
`--debug` to each scenario. A file excluded by `--include` is intentional run
selection and shall be counted as ignored without producing a diagnostic
sidecar. Its name shall be the intended output filename followed by
`.diagnostics.json`; for example, `report.pdf.diagnostics.json`. This avoids
collisions between otherwise identically named source files with different
extensions. A document with no reportable issue need not have a sidecar. The
final terminal summary shall state how many diagnostic sidecars were written
and their output root.

Each sidecar shall contain the run options, per-document totals, and entries
for every reportable ignored, failed, or unsupported item in that document. Entries shall
provide a stable reason code, useful exception or fallback detail, and relevant
location and font-selection information. For an unsupported portable-font
cluster, this includes its container kind and the candidate fallback faces
considered for that cluster, and the
uncovered Unicode characters and code points. A PDF visual-text unsupported
entry shall begin with the original extracted region text and the complete
replacement text returned by the plugin, followed by the other diagnostic
fields. It shall include a page-user-space top-left anchor for the region, not
a full quadrilateral. This makes it clear whether an unsupported character was
already in the source or was introduced by the replacement, and lets a
developer find the retained region on the stated page. The diagnostic sidecar
is local output alongside the converted document and may contain the
document-specific data needed to debug that conversion. The development
scenario manifest shall list the sidecars generated for each scenario; it
shall not copy their contents into the manifest.

For fitted PDF page visual text, FR-2026-08-27-03's safe unsupported
outcome shall leave only the affected region unchanged, record one unsupported
entry, and allow the rest of that input document and the remaining folder to
continue. It shall not fail the complete PDF solely because a replacement
cluster is not covered or uses unsupported bidi or vertical layout. Other
format adapters retain their existing failure behaviour until their
format-specific safe-container handling is implemented under FR-2026-08-27-09.

### Rationale

The identity provider reveals the exact source characters, whereas masking
output may not. A companion report makes fallback and selection problems
debuggable without making a local development run depend on terminal output.

### Notes

Reports derived from confidential samples remain local evaluation artifacts and
must not be staged, committed, uploaded, or quoted. Automated tests shall use
synthetic files and verify sidecar naming and content for ignored files,
ordinary file failures, and unsupported portable-font output.

---

## FR-2026-08-27-07

| Property | Value |
|----------|-------|
| Title | Add portable Noto Math fallback for editable scientific notation |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request for scientific-document mathematical text coverage |
| Date Added | 2026-08-27 |
| Related Requirements | FR-2026-08-27-03, FR-2026-08-27-04, FR-2026-08-27-05, FR-2026-08-27-06 |

### Description

FR-2026-08-27-07 extends the approved optional portable-font mapping with
Noto Sans Math Regular from the official `notofonts/math` release, licensed
under SIL OFL 1.1. It shall be downloaded by the existing bootstrap command to
the existing shared user font cache, remain outside Git, and be required by
the same fitted-layout preflight as Noto Sans Symbols 2. The project shall not
download it on demand while processing a document.

For left-to-right horizontal editable text in either fitted layout mode, the
shared portable selection shall try the normal broad-classification base Noto
face, then Noto Sans Math, then Noto Sans Symbols 2. It shall select and fit
ordered grapheme-safe segments as defined by FR-2026-08-27-05. Noto Sans Math
shall be embedded or referenced through each eligible adapter's existing
portable multi-run output path, including PDF glyph encoding and `/ToUnicode`.
It shall not be treated as synthetic bold or italic when a matching static
math face is not supplied.

This adds coverage for editable Unicode mathematical notation, including the
Mathematical Alphanumeric Symbols block (for example `U+1D436`). It does not
recognize, edit, or reconstruct equations that are raster images, vector
outlines, or non-text equation objects; their existing OCR/vector safety rules
remain unchanged. Unsupported mathematical text still follows the existing
safe unsupported outcome and diagnostic reporting.

FR-2026-08-27-07 extends the portable-font mapping used by the related
requirements; its base-to-math-to-symbol selection order is controlling where
those requirements refer to portable fallback selection.

### Rationale

Scientific documents commonly encode mathematical letters as Unicode text
rather than ordinary Latin characters. The existing base and Symbols 2 faces
do not cover every such character, while a single explicitly approved math
face is much smaller and simpler than a generic font-discovery system.

### Notes

Automated tests shall use synthetic editable mathematical text. They shall
verify bootstrap/preflight handling, deterministic base-to-math-to-symbol
selection, the `U+1D436` regression, and valid PDF output with correct
copy/search mapping. Tests shall also verify that an unsupported mathematical
character retains its container and diagnostic behaviour.

---

## FR-2026-08-27-08

| Property | Value |
|----------|-------|
| Title | Diagnose safely retained native PDF text in debug runs |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following review of unmasked PDF text |
| Date Added | 2026-08-27 |
| Related Requirements | FR-2026-08-03-14, FR-2026-08-04-10, FR-2026-08-27-06 |

### Description

In a `--debug` folder-replacement run using either fitted layout mode, the PDF
adapter shall add a `retained` diagnostic entry whenever it safely leaves a
non-empty native PDF text showing operation or visual text region unchanged
because it is not eligible for replacement. This is distinct from an
`unsupported` entry: it records that the adapter did not attempt replacement,
rather than that portable output coverage rejected replacement text.

Each entry shall give a stable reason code and page number. When the source
text can be decoded safely, it shall begin with `source_text`; otherwise it
shall state that the source text was undecodable. It shall identify whether
the retained container is page content or a Form XObject, include the relevant
text-showing operator or visual-region eligibility detail, and include the
page-user-space top-left location when it is known. It shall not call the text
replacement provider solely to populate a retained entry, and shall not
diagnose non-text drawing operations, raster text, or vector outlines as
native PDF text.

The implementation shall report common safe-retention reasons including an
undecodable source encoding, missing or unsafe placement information,
ineligible text rendering mode, marked content with `/ActualText`, and a
visual region that cannot safely be reconstructed. Related operations shall be
reported as one retained entry where that is possible; the report shall not
emit one entry per glyph.

### Rationale

Visible source text can remain in a converted PDF for deliberate safety
reasons. A debug sidecar should make that distinction reviewable without
changing the conservative PDF-editing rules or misleading a reviewer into
thinking that the replacement provider was invoked.

### Notes

Automated tests shall use synthetic PDFs for each retained reason and verify
that normal runs remain silent, debug runs report the reason and safely decoded
source text where available, and no additional replacement-provider call is
made for retained content.

---

## FR-2026-08-27-09

| Property | Value |
|----------|-------|
| Title | Safely retain unsupported fitted text in non-page and non-PDF containers |
| Owner | KrisTC |
| Status | Proposed |
| Source | Requirement split from FR-2026-08-27-03 after PDF page-text implementation |
| Date Added | 2026-08-27 |
| Related Requirements | FR-2026-08-27-02, FR-2026-08-27-03, FR-2026-08-27-05, FR-2026-08-27-06, FR-2026-08-27-07 |

### Description

For either fitted layout mode, a portable-font coverage or supported-layout
failure for one eligible text container shall leave only that container
unchanged and allow the remainder of the document and folder run to continue.
This requirement applies to PDF FreeText annotations and AcroForm fields, and
to eligible editable text containers in the DOCX, PPTX, XLSX, SVG, EMF, and
WMF adapters. It does not widen the existing eligibility or safety rules for
those formats.

The affected adapter shall use the shared base-to-math-to-symbol portable
selection defined by FR-2026-08-27-05 and FR-2026-08-27-07. If no approved face
covers a complete replacement grapheme cluster, or the replacement requires
unsupported bidirectional or vertical layout, it shall retain that container
rather than fail the complete document, substitute an unrelated glyph, or use
the ASCII masking fallback. Existing source-font measurement and independent
source-font output rules remain unchanged.

In a debug-enabled run, the adapter shall add one `unsupported` diagnostic entry
under FR-2026-08-27-06 for each retained container. Where available, the entry
shall begin with `source_text` and `replacement_text`, then identify the
container kind and its document location (for example page, slide, sheet, part,
or object). It shall include the uncovered characters and code points and the
candidate portable faces considered. The diagnostic path shall not invoke the
replacement provider again merely to populate the report. Normal runs remain
silent except for the existing end-of-run missing-font guidance.

The adapter shall serialize successfully selected multi-face segments using its
native representation, as required by FR-2026-08-27-05, before applying this
container-level recovery. Raster images, vector outlines, and ineligible
non-text drawing operations remain governed by their current OCR and vector
safety rules; this requirement does not attempt to recognize, reconstruct, or
replace them.

### Rationale

Fitted PDF page visual text already has safe, region-level recovery. Other
editable text containers should have the same failure isolation without
claiming that all document formats already implement it.

### Notes

Automated tests shall use synthetic documents for every affected adapter. They
shall verify that one unsupported container does not fail the document, eligible
neighbouring containers are still replaced, the unchanged container remains
valid in the output, and debug diagnostics identify it without a repeated
replacement-provider call.

---

## FR-2026-08-27-10

| Property | Value |
|----------|-------|
| Title | Transparently cache OCR and text-replacement provider results beside source files |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-27 |
| Related Requirements | FR-2026-08-01-02, FR-2026-08-02-06, FR-2026-08-24-04, SR-2026-08-24-01, SR-2026-08-27-01 |

### Description

The project shall provide an opt-in, source-adjacent cache for successful OCR
and text-replacement provider calls. Caching shall be enabled only when the
process environment contains `PIPELINE_PLUGIN_CACHE=1`; an absent value or any
other value shall leave caching disabled. The existing project run wrappers
already load the manually managed, Git-ignored repository-root `.env.local`
file, so no command-line cache option or script-specific cache switch shall be
added.

When caching is enabled, the OCR and text-replacement provider factories shall
return transparent caching proxies around created providers. The proxies shall
preserve the respective provider APIs and provider metadata, and shall work for
every discovered provider without each provider implementing storage logic.
They shall cache only successful, schema-valid normalized results; a provider
failure, a malformed cached value, or an uncacheable provider-specific `extra`
value shall result in an ordinary provider call and shall not be cached as a
failure.

Every source-processing operation with an identified source file shall establish
a cache scope before invoking either provider. Within that scope, the proxies
shall use one SQLite database named `<source filename>.plugin-cache.sqlite3` in
the source file's parent directory. For example, the cache associated with
`report.pptx` shall be `report.pptx.plugin-cache.sqlite3`. The proxies shall
silently bypass caching when no source cache scope exists; the public provider
request models do not contain a source path and a factory cannot safely infer
one. This preserves transparent use by all source-aware pipeline operations
without coupling the cache to individual command-line scripts.

The cache shall use only Python's standard-library SQLite support. It shall use
transactional writes and a single-file journal mode, rather than WAL mode, so
one logical cache does not normally create `-wal` and `-shm` sidecars. Cache
sidecars and temporary journal files shall be excluded from source-file
discovery and from Git. A cache sidecar is local derived data and is not an
input document, output document, or diagnostic artifact.

An OCR cache key shall include the cache schema version, provider cache identity,
request language, OCR preparation settings, and a SHA-256 digest of the exact
prepared image pixels and dimensions supplied to the provider. It shall not
depend on a document-internal image identifier. This shall allow separately
encountered identical embedded images to reuse a result while avoiding a hit
when their actual OCR input differs.

A text-replacement cache key shall include the cache schema version, provider
cache identity, the exact input text, filename flag, source language, and target
language. Request content and configuration values used only as key material
shall be represented by a digest, not stored as separate cache-key columns.
Every cacheable provider shall supply a documented cache identity that changes
when an output-affecting provider, model, or configuration change makes prior
results unsafe to reuse. A provider without such an identity shall be invoked
normally and bypass the cache.

Cached OCR results shall preserve every normalized text item, including text,
confidence, bounding polygon, and JSON-compatible `extra` data. Cached
text-replacement results shall preserve text, confidence, and JSON-compatible
`extra` data. Cache deserialization shall validate the normalized models before
returning a hit and shall not use pickle or execute cache contents.

For the explicit opt-in cache scope defined here, this requirement supersedes
FR-2026-08-24-04's prohibition on persisting Google translation text beyond the
in-memory result. It permits persistence only of the normalized successful
translation result in the source-adjacent cache; it does not permit persistence
of Google credential material or raw Google API responses.

### Rationale

OCR and managed translation are expensive repeat operations. Factory-created
proxies keep caching provider-generic and available to every source-aware
pipeline path, while a per-source sidecar keeps derived text close to the input
whose processing produced it. Hashing prepared image content removes the need
for stable identifiers on images embedded in Office documents, PDFs, and vector
containers.

### Notes

The initial cache scope shall include standalone source bitmaps, native text,
filenames, and raster images embedded in supported documents and vector
graphics. A source-aware evaluator or future processing entrypoint shall obtain
the same behaviour by establishing the shared cache scope, rather than by
implementing its own provider cache. Calls made directly through a factory with
no source file context are deliberately not cacheable.

The cache must not contain credentials, credential paths, authorization headers,
raw remote API responses, source paths as stored data, or diagnostic logs. Its
privacy, corruption handling, and logging requirements are defined by
SR-2026-08-27-01. Automated tests shall use synthetic inputs and mocked
providers; they shall verify enabled and disabled factory behaviour, cache hits,
key separation, embedded-image reuse without an internal ID, invalidation by
provider identity, malformed-cache recovery, and the absence of cached
failures.

---

## FR-2026-08-27-11

| Property | Value |
|----------|-------|
| Title | Reuse one provider-cache SQLite connection for each source file |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request and performance diagnosis |
| Date Added | 2026-08-27 |
| Related Requirements | FR-2026-08-27-10, SR-2026-08-27-01 |

### Description

When `PIPELINE_PLUGIN_CACHE=1` is enabled, a source-cache scope shall open at
most one SQLite connection for its source file and reuse that connection for all
OCR and text-replacement cache reads and writes made while the scope is active.
The connection shall be opened lazily on the first cache operation, so an
enabled run that never invokes a cacheable provider does not create a cache
file. The scope shall commit and close the connection when processing of that
source file ends.

The cache must retain the exact key and result semantics defined by
FR-2026-08-27-10. Reusing a connection shall not widen cache matches across
source files, providers, result kinds, languages, filename status, image
content, or cache identities. An SQLite open, initialization, locking, or write
failure shall disable caching only for that source scope and let ordinary
provider processing continue without exposing cache data in diagnostics.

For PDF files, the folder-replacement progress total shall represent each page's
native-text pass, one document-level native-form pass, and each unique embedded
raster image. The PDF handler shall advance the progress bar after completing
each page's native-text and annotation processing, with a page-number label,
and after completing its form-field pass. It shall retain one progress unit per
unique embedded raster image. This progress behaviour shall apply whether or
not provider caching is enabled.

### Rationale

PDF native-text processing can make hundreds or thousands of provider calls
before it completes its first progress work item. Opening, configuring, and
committing a SQLite connection for every cache lookup and write turns a local
SSD workload into a large filesystem-transaction workload and causes prolonged
apparent `0%` progress. A source-scoped connection retains the per-source
privacy boundary while removing this avoidable overhead.

Page-level progress makes a long native-text pass observable without pretending
that the count of PDF text operands can be cheaply known in advance.

### Notes

The provider-result table uses the parameterized lookup
`WHERE result_kind = ? AND cache_key = ?` against its composite primary key.
`cache_key` is a SHA-256 digest of canonical request material, including the
provider name and cache identity, cache schema version, and all
output-affecting request fields. Thus the database does not store request text
or configuration as query columns, while an exact text replacement for one
provider cannot be returned for another provider or request kind.

Automated tests shall use synthetic providers and verify that many calls in one
source scope open one connection, that different source scopes do not share a
connection or cache file, and that a cache database failure falls back to the
underlying provider. Synthetic multi-page PDF tests shall verify the native-page,
form-pass, and embedded-image progress units and labels.

---

## FR-2026-08-28-01

| Property | Value |
|----------|-------|
| Title | Reuse Google Cloud Translation client within a provider instance |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following PDF native-text performance diagnosis |
| Date Added | 2026-08-28 |
| Related Requirements | FR-2026-08-24-04, SR-2026-08-24-01, FR-2026-08-27-10 |

### Description

`GoogleCloudTranslateProvider` shall lazily load and validate its local Google
configuration, then create one `TranslationServiceClient` for its selected
endpoint. It shall reuse that configuration and client for every subsequent
non-empty, cross-language replacement request made through the same provider
instance. Empty and case-insensitively same-language requests shall continue to
return without loading configuration or creating a client.

The provider factory's existing fresh-provider-per-`create()` contract remains
unchanged. Therefore a new factory-created provider shall reread the local
environment and credential-file configuration, while a provider already in use
shall retain the configuration selected at its first remote request. A failed
configuration validation or client construction shall not be retained: a later
request may retry initialization. A `translateText` operation failure shall
retain the initialized client and continue to raise the existing normalized
provider error; it shall not silently select another endpoint or provider.

This requirement shall not batch requests, alter individual `translateText`
request construction, persist configuration or client state, widen the remote
data boundary, or expose configuration values in errors or logs.

### Rationale

PDF native text can produce many small replacement calls. Re-reading the local
credential JSON and constructing a Google client for every one adds unnecessary
local work and connection setup around every remote operation. Reuse preserves
the existing request semantics and trust boundary while removing that repeated
per-call setup cost.

### Notes

Automated tests shall use synthetic configuration and mocked clients. They shall
verify one configuration validation and one client construction for multiple
ordinary replacement calls, no initialization for empty or same-language calls,
fresh configuration for a new provider instance, initialization retry after a
construction failure, and unchanged endpoint, error-sanitization, and request
contents behaviour.

---

## FR-2026-08-28-02

| Property | Value |
|----------|-------|
| Title | Preserve underlying provider names in cache-aware diagnostics |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-28 |
| Related Requirements | FR-2026-08-27-10, FR-2026-08-27-06 |

### Description

Folder-replacement diagnostic sidecars shall identify a caching-proxy provider
by its wrapped provider's concrete type name followed by ` (cached)`. For
example, a cached `PaddleOcrProvider` shall be recorded as
`PaddleOcrProvider (cached)`, and a cached `GoogleCloudTranslateProvider` as
`GoogleCloudTranslateProvider (cached)`. An unwrapped provider shall retain the
existing concrete type-name value.

The label shall report only the wrapper state and underlying provider type. It
shall not expose cache paths, cache keys, request text, provider configuration,
credential information, or implementation-object representations.

### Rationale

Transparent cache proxies should not obscure which OCR or replacement provider
actually processed a document. Retaining the existing name and explicitly
showing cache use makes diagnostic sidecars accurate and readable.

### Notes

The label may be supplied by a shared provider-diagnostic naming helper or a
small proxy interface; the folder processor shall not need to know individual
plugin classes. Automated tests shall use synthetic providers and verify cached
and unwrapped diagnostic labels without using a source document or provider
configuration.

---

## FR-2026-08-28-03

| Property | Value |
|----------|-------|
| Title | Record safe structured context for folder-replacement file failures |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following insufficient Word failure diagnostics |
| Date Added | 2026-08-28 |
| Related Requirements | FR-2026-08-27-06, FR-2026-08-27-09, SR-2026-08-24-01 |

### Description

For a debug-enabled folder-replacement run, a `file_processing_failed`
diagnostic entry shall retain the existing exception type and safe detail, and
shall add the last known structured failure context. The context shall identify
the processing stage, container kind, operation, and document-local location
when known. The Office handlers shall identify package parts for native XML,
embedded bitmap, and embedded vector work; their fitted-layout paths shall at
least identify the document-local part, slide, worksheet, or document-layout
phase that was active.

When the failed operation invokes OCR, the context shall record the request
language and source image width, height, and mode. When it invokes text
replacement, it shall record the source and target languages, whether the
request is for a filename, and the input character count. The sidecar shall
also retain the per-document totals accumulated before failure. It shall not
record raw replacement text, OCR text, image pixels, cache keys or paths,
provider configuration, credentials, credential paths, API responses, or a
raw traceback or chained-exception message. Exception-cause information may be
recorded as exception type names only.

The existing file-atomic behaviour remains unchanged. A failure escaping an
Office handler shall discard its temporary output and stop processing the
remainder of that document, while the folder run continues with later source
files. A malformed individual XML part that an existing adapter already
retains unchanged shall continue to be non-fatal. Per-container continuation
after other OCR, replacement, or layout failures is outside this requirement
and remains governed by the format-specific safe-container work of
FR-2026-08-27-09.

### Rationale

An exception type alone does not reveal whether a failure occurred while
selecting an output filename, replacing native document text, OCRing an
embedded image, or writing an output package. Request metadata and a
document-local location make a local sidecar actionable without copying the
document's text or weakening the Google credential and remote-data boundary.

### Notes

The new fields are additive to the existing sidecar schema so existing local
consumers can continue to read their required fields. Reports derived from
confidential samples remain local evaluation artifacts and must not be staged,
committed, uploaded, or quoted. Automated tests shall use synthetic Office
documents and failing synthetic providers. They shall verify a native-text and
an embedded-image failure entry, the expected safe request metadata and
document-local location, the absence of request text and chained exception
messages, document-level atomic failure, and continuation to the next source
file.

---

## FR-2026-08-28-04

| Property | Value |
|----------|-------|
| Title | Replace fully covered PDF text marked with alternate text |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following review of retained native PDF text |
| Date Added | 2026-08-28 |
| Related Requirements | FR-2026-08-24-02, FR-2026-08-27-08 |

### Description

For fitted PDF replacement, a `/ActualText` marked-content scope shall not by
itself make otherwise eligible source text ineligible. The adapter shall
replace the visible text and remove that scope's `/ActualText` value when all
text-showing operations in the scope are successfully replaced and the scope
contains no nested marked content or non-text content whose semantics could
depend on `/ActualText`. The generated replacement text and its existing
`/ToUnicode` mapping shall then be the authoritative text for extraction,
selection, copy, search, and accessibility.

The adapter shall remove `/ActualText` only from the particular `BDC`
invocation being replaced. It shall not mutate a shared named Properties
resource, because another marked-content invocation may use that resource and
remain unchanged.

If any text operation in the scope is unsupported, undecodable, or otherwise
not replaced, or the scope has nested marked content or other semantic content,
the adapter shall retain every text operation in that scope unchanged. A debug
run shall record the retained result using the existing marked-content
`/ActualText` reason code.

### Rationale

`/ActualText` is a hidden semantic label. Leaving it unchanged after a visible
replacement can expose the original text through copy, search, or assistive
technology. Removing it from a fully replaced, text-only scope makes the
replacement's Unicode mapping authoritative without risking an unrelated
marked-content use of the same shared property resource.

### Notes

Automated tests shall use synthetic PDFs. They shall verify replacement and
extraction of a text-only `/ActualText` scope; preservation of another
invocation that shares the original named Properties resource; and retention
of a scope with a nested marked-content operation or a source operation that
cannot be replaced.

---

## FR-2026-08-29-01

| Property | Value |
|----------|-------|
| Title | OCR-replace outlined PDF vector text without rasterizing the page |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following review of OCR-detectable outlined PDF text |
| Date Added | 2026-08-29 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-04-09, FR-2026-08-27-08 |

### Description

For a PDF page, the folder-replacement pipeline shall additionally process
visible text that is painted as vector drawing operations rather than as a
native PDF text-showing operation or an embedded raster image. It shall do so
by rendering the relevant vector-painted page content to an in-memory raster
image, passing that image through the selected existing OCR provider, and
using the resulting OCR polygons to draw background wipes and replacement text
back into the original PDF page coordinate system.

The pipeline shall retain the original PDF page's vector and raster content.
It shall not flatten or rasterize an entire output page. Each successful
replacement shall cover only its detected OCR region and write replacement
text using the existing PDF portable-font output path. The source vector
outlines have no authoritative text semantics; the inserted replacement text
shall be selectable and extractable through its existing PDF Unicode mapping.

The vector-content OCR pass shall not reprocess text that the PDF adapter has
already handled as native editable text or as an embedded raster image. A
region shall be eligible only when it is visible in the rendered vector
content, meets the existing normalized OCR-confidence threshold, can be mapped
to a finite non-degenerate page-space polygon, and has a safe estimated
background for a local wipe. It shall retain a region unchanged when these
conditions are not met or when the replacement cannot be rendered with the
existing portable-font policy.

A four-corner OCR region whose longest baseline differs from the horizontal
axis by no more than five degrees shall remain eligible. The PDF overlay shall
cover its enclosing page-space rectangle and render its replacement text
horizontally, without reproducing the small detected skew. This follows the
established raster-image OCR policy for small false rotations caused by glyph
shape. A region whose baseline exceeds that tolerance, or whose geometry is
not a finite non-degenerate quadrilateral, shall remain unchanged with the
stable orientation-retained reason code.

Before PDFium rendering or OCR, the pipeline shall inspect the filtered
vector-only content for each page. It shall skip PDFium rendering and OCR for
a page that contains no potentially visible vector-painting operation,
including inside invoked Form XObjects. The PDF progress bar shall include one
completed `vector OCR page N/total` work item for every page, whether that
inspection skips the page or the page proceeds to rendering and OCR.

The selected OCR provider, replacement provider, source and target languages,
and existing text-region colour estimation and rendering behaviour shall apply
to eligible vector-content OCR regions. The `preserve-basic-layout-source-font`
mode shall use the existing portable fallback for this path because vector
outlines do not identify a reusable source font.

In a debug-enabled run, the diagnostic sidecar shall record one safe summary
for each PDF page where the vector-content OCR pass detects a region or safely
retains a region. The summary shall give the page number and counts for OCR-detected, confidence-rejected,
replacement-written, and safely-retained regions, together with stable reason
codes for any retained categories. It shall not contain OCR text, replacement
text, image pixels, raw OCR polygons, or rendered-page artefacts.

### Rationale

Some PDF producers convert visibly clear text into drawing paths. That text is
neither a PDF text operation nor an embedded bitmap, so the current native
text and embedded-image paths cannot reach it even when the selected OCR
provider recognizes a raster rendering with high confidence. A localized
render-and-overlay path closes this gap while preserving the rest of the page
as PDF content.

### Notes

This feature needs a separately approved local PDF rendering-engine decision,
including its supported platforms, rendering resolution, dependency policy,
and security review, before implementation. It must not send rendered pages or
OCR inputs to a remote service beyond the selected provider's already approved
data boundary.

The render pass must preserve enough of the PDF graphics state to identify
visible vector content, including clipping, transforms, opacity, and overlap.
It must not use a rendered whole-page image as the output page, and it must not
apply an OCR replacement twice where native-text or embedded-bitmap processing
already owns the visible source content.

Automated tests shall use synthetic PDFs only. They shall include high-contrast
outlined text over a uniform background, nearby native editable text, and a
nearby embedded raster image. They shall verify that only the outlined text is
replaced, the page retains vector content outside replacement wipes, the
generated replacement is extractable, a low-confidence or unsafe-background
case is retained, and debug diagnostics contain only the specified safe
metadata.

---

## FR-2026-08-29-02

| Property | Value |
|----------|-------|
| Title | OCR fallback for undecodable native PDF text |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request following outlined-PDF-text implementation review |
| Date Added | 2026-08-29 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-23-05, FR-2026-08-27-02, FR-2026-08-27-08, FR-2026-08-29-01, TR-2026-08-29-02, SR-2026-08-29-01 |

### Description

When either fitted document-text layout mode, `preserve-basic-layout` or
`preserve-basic-layout-source-font`, retains a visible native-PDF
text-showing operation because its font encoding cannot be decoded safely, the
pipeline shall attempt a local-render, single-OCR-pass fallback for that
operation. It shall apply only to the stable `pdf_text_undecodable` reason
code, or to a future reason code explicitly classified as an undecodable
visible-text encoding failure. It shall not apply to
`preserve-source-formatting`.

For each page, the fallback and the outlined-vector-text OCR path of
FR-2026-08-29-01 shall share one in-memory detection render and one call to
the selected OCR provider. That render shall include vector-painted page
content, eligible undecodable native text operations, and the visual context
needed to estimate a safe local wipe. It shall exclude native text that the
adapter has already replaced and embedded raster-image text already owned by
the bitmap path.

Each finite, non-degenerate OCR result from that selective render shall become
an in-memory virtual PDF visual-text item. Its OCR text and page-space geometry
are authoritative for the item; the adapter shall not require or record a
one-to-one association with an undecodable source operation. Before invoking
the replacement provider, it shall combine virtual OCR items with normally
decoded native PDF visual-text items only where the existing visual-flow
inference can establish one compatible line or block. It shall otherwise keep
the item as an independent visual flow. Vector-derived OCR items use the same
model.

Successful replacement shall use the selected existing OCR and
text-replacement providers, source and target languages, confidence threshold,
safe-background policy, and portable PDF-font output path. A combined flow
shall remove its decoded native source operations through the normal PDF path,
leave its undecodable native source operations unchanged, wipe only its virtual
OCR regions still visible in the original page, and draw one fitted selectable
replacement overlay. The adapter shall use one local wipe for each accepted
OCR region, rather than one enlarged wipe for the combined flow. It shall
retain all other original page content and never replace the same visible
source text twice.

The fallback shall not apply to a missing position, an ineligible PDF text
rendering mode, a non-decoding replacement failure, a malformed PDF that
cannot be rendered safely, or an OCR region that fails the existing confidence,
geometry, background, or portable-font safety checks. Those cases shall retain
their current safe behaviour. The fitted output shall use the existing portable
PDF-font policy; it shall not infer or claim a source font for virtual OCR text.

In a debug-enabled run, diagnostics shall retain the stable
`pdf_text_undecodable` reason with its existing safe operation metadata and
record that the page entered the OCR-enhanced visual-flow pass. The report
shall record per-page aggregate OCR detected/replaced/retained counts, but
shall not record an operation-to-OCR mapping. It shall not record OCR text,
replacement text, decoded source bytes, image pixels, or raw OCR polygons.

### Rationale

A visible PDF text operation can have valid glyph drawing but lack a safe
Unicode mapping. Leaving it unchanged protects against inventing source text,
but a local visual OCR fallback can recover some such cases while retaining
the existing safety boundary and avoiding duplicate processing of nearby text.

### Notes

TR-2026-08-29-02 defines the approved selective-render and virtual-text design.
FR-2026-08-29-02 supersedes the retain-unchanged clauses of FR-2026-08-23-05
and FR-2026-08-27-02 only for an operation successfully replaced through this
fallback. It supersedes FR-2026-08-27-08's retained-entry shape only for these
lifecycle entries. For OCR-derived virtual flows, it supersedes
FR-2026-08-29-01's per-region replacement wording only to permit one fitted
replacement overlay for a compatible combined flow while retaining a local
wipe for every OCR-derived source region. All other PDF safety rules remain
unchanged.

Tests must use synthetic PDFs with an intentionally undecodable visible text
operation within a decoded visual flow, an isolated undecodable label, nearby
vector text, and nearby raster text. They shall verify one OCR call per
eligible page, virtual-text flow grouping and independent-flow fallback, local
wipes, no duplicate native or bitmap processing, safe aggregate diagnostics,
parser-loadable output, and independent rendering of the result.

---

## FR-2026-08-29-03

| Property | Value |
|----------|-------|
| Title | Infer multi-run PDF visual text blocks for context-aware translation |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following PDF translation-layout review |
| Date Added | 2026-08-29 |
| Related Requirements | FR-2026-08-23-01, FR-2026-08-27-02, FR-2026-08-27-03, FR-2026-08-27-05, FR-2026-08-27-06 |

### Description

For fitted PDF page-content and Form-XObject text, the adapter shall infer a
visual line from ordered, compatible text chunks even when the line contains
multiple PDF text-showing operations, `TJ` fragments, source fonts, source
sizes, weights, or ordinary positioned gaps.

A source formatting change shall not alone make a visual-line or visual-block
candidate ineligible. Chunks shall remain separate when they differ in
orientation, transform, clipping, opacity, colour or paint state, or when
their placement provides evidence of independent labels, columns, table cells,
or rows.

Before grouping chunks into visual lines, the adapter shall derive
non-crossable visual separators from transformed, visible PDF geometry and
text placement. It shall not merge chunks across:

- an axis-aligned visible vector border, rule, or filled divider that separates
  their occupied regions;
- a recurring horizontal or vertical whitespace gutter that forms aligned rows
  or columns in the local layout; or
- evidence that the chunks belong to distinct label/value, table-cell, or
  column streams.

The adapter shall evaluate intervening text placement across all compatible and
incompatible visual-state groups. A text line with a different effective paint
state that lies between two proposed prose lines and occupies their horizontal
flow corridor is a non-crossable label boundary. Matching outer text colour or
style shall not cause the adapter to skip an intervening heading or label.

A single gap on one baseline is not sufficient evidence of a table boundary.
Conversely, the absence of a drawn border is not evidence that chunks are
prose. When the adapter cannot distinguish a prose continuation from
independently positioned cells or labels, it shall retain separate visual-line
regions.

The adapter may classify adjacent visual lines as one reflowable prose block
even when each line contains multiple source chunks. Eligibility requires
deterministic evidence of a shared text flow: compatible orientation and paint
state, finite bounds, consistent line spacing, and compatible alignment or
indentation. It shall not merge across columns, repeated cell boundaries,
table-like rows, form fields, contents leaders, or independently positioned
labels.

For an eligible prose block:

- The adapter shall make one text-replacement-provider request for the
  complete visual block, in visual reading order.
- Visual source line wraps shall provide translation context but shall not
  force output line breaks. The fitted-layout stage shall reflow the translated
  result within the whole inferred block.
- The adapter shall replace all source text operations belonging to that block
  with one fitted replacement region.
- Source-font mode shall derive bounds from the placed source chunks, but shall
  use the existing deterministic dominant-style policy for translated output.
  It shall not attempt to map translated words back onto individual bold or
  size-varied source fragments.
- Output glyph coverage and serialization shall use the existing multi-face
  fitted-run model from FR-2026-08-27-05. Multiple portable output fonts may
  be selected and fitted together within the single region.

The adapter shall not retain an otherwise eligible replacement merely because
its fitted output could overlap another replacement region. Translation
coverage takes precedence over overlap avoidance. The adapter shall instead
reduce avoidable overlap by applying the visual-block grouping rules above.

### Rationale

PDF authoring tools often encode one visually coherent sentence or paragraph
as separately positioned fragments with mixed typography. Translating those
fragments independently loses linguistic context and fits each result to an
artificially small box. Reconstructing a well-evidenced visual block improves
translation quality and permits a single coherent reflow, while the explicit
table, column, and label exclusions retain the prior safety fix.

### Notes

Automated tests shall use synthetic PDFs only and cover:

- a multi-line prose block with mixed fonts, weights, sizes, and `TJ`
  fragments, producing one provider request;
- reflow of a translated prose block without preserving source soft wraps;
- bordered and borderless adjacent table cells, form labels, contents leaders,
  and multi-column text remaining separate;
- same-style title and body text remaining separate when an intervening
  differently styled heading overlaps their horizontal flow corridor;
- prose with a nearby decorative rule still grouping where that rule does not
  separate its occupied text regions;
- correct multi-font portable output within one fitted block.

---

## FR-2026-08-30-04

| Property | Value |
|----------|-------|
| Title | Reflow emphasised ordered-list item continuations as one PDF region |
| Owner | KrisTC |
| Status | Implemented |
| Source | User review of PDF translation-layout evaluation |
| Date Added | 2026-08-30 |
| Related Requirements | FR-2026-08-23-02, FR-2026-08-29-03 |

### Description

Within a verified ordered PDF list item, a fill- or stroke-paint colour change
alone shall not prevent compatible marker and continuation rows from forming
one fitted replacement region. Colour may represent inline emphasis rather
than a semantic boundary. The item shall still remain separate from every
other ordered-list item.

The adapter shall retain the existing safety boundaries for material font-size
changes, orientation, transform, clipping, opacity, vector separators,
recurring gutters, columns, tables, labels, and incompatible placement. It
shall retain separate visual regions when those signals make the continuation
ambiguous.

Because the existing fitted-output model emits one paint state for a visual
region, a cross-colour item shall use the paint state that contributes the most
source text. Ties shall use visual reading order. It shall not try to assign
translated words to the source emphasis spans.

### Rationale

Report authors often colour one sentence in a numbered item to emphasise a
finding, then continue the same item in ordinary text. Replacing those rows
independently loses context and allows a longer translation of the emphasised
row to overlap its continuation.

### Notes

Automated tests shall use synthetic PDFs only. They shall verify that a
coloured numbered-item marker row followed by aligned ordinary-colour
continuation rows creates one provider request, uses the dominant paint state,
and remains separate from adjacent list items and from a misaligned coloured
row.

---

## FR-2026-08-30-05

| Property | Value |
|----------|-------|
| Title | Conservatively widen eligible single-line PDF replacement regions, including enclosing highlight containers |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following PDF translation-layout review |
| Date Added | 2026-08-30 |
| Related Requirements | FR-2026-08-23-01, FR-2026-08-27-02, FR-2026-08-29-03 |

### Description

For eligible fitted PDF page-content and Form-XObject visual text processed in
either `preserve-basic-layout` or `preserve-basic-layout-source-font` mode,
the adapter may widen a replacement fitting region in the reading direction
when the replacement would not fit as one output line at the source line's
effective font size, provided it can retain at least 80% of that size.

This rule shall apply only to an ordinary horizontal, single visual line. The
line shall not be an inferred multi-line prose block, an ordered-list item with
continuation rows, or a vertical or rotated text region. The rule is intended
for standalone headings, labels, and simple one-line list items; it shall not
change the bounded reflow rules for larger runs of text.

The adapter shall preserve the source line's starting edge, baseline,
orientation, alignment, and height. It may widen the fitting rectangle only
from its ending edge toward the reading direction, and only as far as a finite
clear corridor permits. It shall measure the selected output font at the
source line's effective font size and determine the minimum widened width that
keeps the complete replacement on one line at that size. When that width is
available within the clear corridor, the adapter shall use it and retain the
source effective font size. Otherwise, it may use the largest one-line fitted
size that is at least 80% of the source effective font size and fits within the
same clear corridor. It shall not move or resize other page content.

A clear corridor shall be accepted only when the adapter can conservatively
establish that it lies within the page or Form-XObject bounds, has the same
safe local background as the source line, and is free of every other visible
text region and non-background visible graphic. The collision check shall
include native PDF text, raster images, vector-painted content, annotations or
form appearances, clipping boundaries, and page or Form-XObject edges. If the
adapter cannot determine this geometry or background reliably, it shall treat
the corridor as unavailable.

An active clipping path shall not by itself exclude an otherwise eligible
single-line region from widening. When the adapter can establish that every
active clip is a finite, axis-aligned rectangle in page or Form-XObject space,
it shall intersect those rectangles with the applicable content bounds and
treat the resulting rectangle as a hard expansion boundary. It may widen only
when both the source rectangle and the complete expanded output rectangle
remain within that boundary. A non-rectangular, unbounded, malformed, or
otherwise unsupported clipping path shall retain the existing conservative
fallback behaviour.

As a limited exception to the raster-graphic collision rule, an image may be
treated as a non-blocking page or Form-XObject background when it is marked as
a PDF artifact, its finite page-space rectangle covers the complete applicable
content bounds, and it is painted as that content's background. It shall not
be treated as foreground content solely because it spans the candidate
corridor. All other images, including an image with only partial or uncertain
background evidence, remain collision blockers.

Unsupported vector path syntax elsewhere in the same page or Form-XObject
shall not by itself make a candidate corridor unavailable. When the adapter
can derive a finite conservative page-space bounding rectangle for the
complete painted vector path, it shall treat that rectangle as a visible
vector-graphic collision region and compare it only with the candidate's
potential expanded-output corridor. A rectangle disjoint from that corridor
shall not prevent widening. If the adapter cannot derive such a finite bound,
or the bound intersects the corridor, it shall retain the conservative
unavailable or blocking outcome.

As a limited exception to the vector-graphic collision rule, a reliably
recognised closed, filled vector shape may be treated as an enclosing highlight
container. The source line must be within that container's interior, and the
full expanded output rectangle must remain within the same interior. The
container's own fill and border shall not block expansion within that interior,
but its boundary is a hard limit and shall never be crossed. Every other
visible text region, connector or rule, shape, image, annotation, form
appearance, clipping boundary, and page or Form-XObject edge remains a
collision blocker, including content inside the same container. If the shape,
its interior, its fill/background, or its containment relationship to the
source line cannot be determined reliably, the adapter shall use the existing
fallback behaviour.

The widening decision shall not affect replacement eligibility or coverage. If
no clear corridor is available, or if its full available width cannot contain
the replacement on one line at no less than 80% of the source effective font
size, the adapter shall retain the existing source-region fitting behaviour,
including its normal wrapping, font-size fitting, and overflow handling. It
shall not retain or omit an otherwise eligible replacement merely because
widening is unavailable or because a widened result would overlap other
replacement output.

### Rationale

Translations of short headings and list items can be materially longer than
their source text even when the surrounding page has unused space. Allowing a
verified one-sided expansion to retain the source font size and a one-line
result improves readability, while the single-line scope and fail-closed
collision check preserve the existing conservative handling of paragraphs,
tables, and graphics.

### Notes

This requirement is intentionally limited to PDF visual-text regions. It does
not change the explicit-container fitting rules for PPTX, DOCX, XLSX, SVG,
annotations, or AcroForm fields.

The implementation must define deterministic synthetic-test fixtures for a
clear uniform-background corridor, a recognised enclosing filled container,
nearby text, a connector or rule, nearby raster and vector graphics, a page
edge, an uncertain background, and a multi-line prose block. They shall verify
that a clear one-line case and a contained one-line case retain their source
effective font size and have no replacement line break; they shall also verify
a one-line result at exactly 80% of source effective font size is accepted and
a smaller result falls back. All other cases shall use the pre-existing
source-region fitting behaviour. No test or fixture may use confidential sample
data.

The vector fixtures shall additionally verify that a finite, unsupported
painted curve outside a candidate corridor permits widening, while an otherwise
equivalent curve intersecting that corridor blocks it.

The fixtures shall also verify that a source line and expanded output contained
by a page-sized rectangular clip can widen, while a non-rectangular clip cannot,
and that an artifact-marked full-page background image does not block widening.

In a debug-enabled fitted PDF replacement run, the adapter shall add one
diagnostic entry when an otherwise eligible ordinary horizontal visual line
needs a wider fitting region to retain at least 80% of its source effective
font size on a single output line, but falls back to the existing source-region
fitting behaviour. The entry shall identify the page, container kind, and
existing safe region-location metadata, together with one stable reason code:
unavailable expansion geometry, unavailable clear corridor, or clear corridor
too narrow for an 80%-minimum-sized one-line output.

Each expansion diagnostic entry shall include the source text and replacement
text, so a human can identify the line that fell back without correlating the
rounded geometry with the PDF. The entry shall not contain glyph data, raw PDF
operations, rendered pixels, or raw OCR geometry. It may contain rounded
source-region and clear-corridor widths and the source effective font size.

For an eligible candidate whose clear corridor is unavailable, the entry shall
add a stable `clear_corridor_blocker_kind` identifying the first blocking class:
text, vector graphic, raster image, container boundary, page or Form-XObject
boundary, or unknown geometry. Where finite comparable geometry exists, it may
also add rounded blocker location metadata in PDF page user space.

When the adapter has attempted fitting in the full available corridor and the
entry records a too-narrow-corridor fallback, it shall additionally include the
rounded full-corridor fit status, font scale, effective font size, and output
line count. These fields shall identify whether the fallback resulted from
line wrapping, a font-size reduction, or another bounded-layout fit result.

The adapter shall not create an expansion diagnostic for a successful
expansion, a line that already fits at source size, or a region outside this
requirement's single-line eligibility scope. In particular, multi-line prose
blocks and other non-candidate regions shall not add diagnostic noise.

As a targeted exception to that no-noise rule, the adapter shall add one
`layout_expansion_excluded` entry for a region outside the single-line
eligibility scope only when its normal fitted replacement wraps or is smaller
than 80% of its source effective font size. The entry shall include source and
replacement text, source visual-line count, normal fit status, font scale,
effective font size, output line count, and a stable exclusion reason: inferred
multi-line region, clipping, non-horizontal orientation, or unsupported source
geometry. It shall not add entries for non-candidate regions whose normal
replacement already fits on one line at 80% or more of source size.

Tests shall additionally verify one diagnostic for each fallback reason and no
diagnostic for a successful expansion, an already-fitting line, or a multi-line
prose block whose normal replacement already meets the one-line 80% threshold.
They shall verify the source and replacement text in every fallback entry, the
full-corridor diagnostic fields for a too-narrow corridor fallback, the
clear-corridor blocker kind, and a targeted exclusion entry for a wrapped or
undersized normal replacement.

---

## FR-2026-08-30-06

| Property | Value |
|----------|-------|
| Title | Retain native PDF text whose Unicode decoding cannot be verified |
| Owner | KrisTC |
| Status | Implemented |
| Source | User-reported cross-viewer PDF corruption diagnosis |
| Date Added | 2026-08-30 |
| Related Requirements | FR-2026-08-04-10, FR-2026-08-23-01, FR-2026-08-27-02, FR-2026-08-27-03, FR-2026-08-27-05, FR-2026-08-29-02 |

### Description

Before the fitted native-PDF replacement path sends text to a replacement
provider or writes it with a portable output font, it shall establish that the
source bytes' Unicode decoding is safe. A syntactically present `/ToUnicode`
map is insufficient when it cannot be verified against the source font's
encoding and embedded font program.

In particular, an embedded simple TrueType font that has no PDF `/Encoding`
and whose embedded `cmap` provides only a legacy non-Unicode mapping shall be
treated as `pdf_text_undecodable`. The adapter shall retain the affected text
unchanged and record the existing safe diagnostic; it shall not pass a guessed
Unicode value to the identity, masking, or translation provider, and shall not
render that guess through the portable Noto path. This applies to page content
and Form XObjects in both fitted-layout modes.

In a debug-enabled run, each retained operation shall use the existing
`pdf_text_undecodable` reason code, set `source_text_status` to `undecodable`,
and record `font_encoding_status` as
`unverifiable_legacy_nonunicode_embedded_truetype`. Its detail shall explain
that the source `/ToUnicode` map could not be verified against the embedded
legacy non-Unicode `cmap`. The diagnostic shall not include guessed source
text or raw font bytes.

The rule must not depend on the processing host's installed fonts. A source
font may still be used for measurement where the existing layout policy
permits it, but its host installation shall not make an otherwise
unverifiable byte-to-Unicode mapping eligible for replacement.

### Rationale

This defect is independent of Preview, Chrome, and Teams: they consistently
render the glyphs requested by the pipeline. The corruption begins earlier,
when an unverifiable source mapping is accepted as Unicode and is then
faithfully written into an embedded portable font. Retaining such text is the
only safe native-PDF outcome until the OCR fallback in FR-2026-08-29-02 can
associate and replace it.

### Notes

Automated tests shall use a synthetic simple TrueType font whose embedded
program exposes only a legacy non-Unicode `cmap`. They shall verify that every
affected native text operation remains byte-for-byte unchanged, that no
replacement-provider request is made for it, and that its diagnostic uses
`pdf_text_undecodable`. They shall cover page content and a Form XObject,
including `TJ` arrays. No test, reference image, log, or diagnostic artifact
may use confidential sample data.

---

## FR-2026-08-31-01

| Property | Value |
|----------|-------|
| Title | Detail diagnostics for unsupported vector-OCR orientation |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-31 |
| Related Requirements | FR-2026-08-29-01 |

### Description

When the vector-content OCR path retains an otherwise confidence-accepted
region with the stable reason code
`vector_ocr_polygon_orientation_unsupported`, its debug diagnostic sidecar
shall include one per-region detail record. The record shall contain the
detected OCR text and the signed baseline angle in degrees that was compared
with the five-degree upright-rendering tolerance. The angle shall use the
existing baseline normalisation range of -90 to 90 degrees and be rounded to
one decimal place. When the retained polygon has no finite, non-degenerate
four-corner baseline, the angle field shall be `null`.

This exception applies only to that reason code. The sidecar continues to omit
replacement text, image pixels, raw OCR polygons, and rendered-page artefacts.
The sidecar has the same data-exposure boundary as the source document.

### Rationale

The aggregate retained-reason count identifies the cause of retention but not
whether a greater orientation tolerance would safely cover a useful recognised
region. Detected text and a normalised angle allow an operator to assess that
decision directly.

### Notes

Tests shall use a synthetic rotated vector-OCR region and verify its detected
text and rounded signed angle in the detail record, alongside the existing
aggregate reason count.

---

## FR-2026-08-31-02

| Property | Value |
|----------|-------|
| Title | Diagnose and apply reviewed legacy bullet mappings in fitted PDF text |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following portable-font coverage diagnosis |
| Date Added | 2026-08-31 |
| Related Requirements | FR-2026-08-27-03, FR-2026-08-27-05, FR-2026-08-27-06, FR-2026-08-27-07 |

### Description

When an eligible fitted PDF page visual-text region is retained with
`portable_font_coverage_unsupported`, the debug diagnostic shall additionally
classify an uncovered cluster as a `candidate_bullet_character` when all of
the following are true:

1. the cluster is at the start of the same newline-delimited logical line in
   the extracted source region and replacement text, ignoring leading
   whitespace;
2. it is one Unicode scalar value and is the only uncovered cluster that
   caused the region to be retained; and
3. it is either in a Unicode Private Use Area or belongs to an explicit,
   conservative candidate set of non-textual bullet and list-marker
   characters maintained by the project; and
4. the source logical line contains at least two non-whitespace Unicode
   scalars after the candidate marker.

The diagnostic shall retain `portable_font_coverage_unsupported` as its
reason code and include `candidate_kind: "bullet_character"` in addition to
the existing source text, replacement text, uncovered character, code point,
candidate portable faces, page, and region anchor. It shall also include the
effective source-font resource name when that information is available. A
cluster that does not meet every condition shall retain the existing ordinary
portable-font diagnostic without `candidate_kind`.

For reviewability, a candidate entry shall write `candidate_kind` and
`source_font_resource_name`, when present, immediately after `code_points` and
before `region_location` in the JSON object.

This classification is a discovery aid, not a rendering decision or proof of
the glyph's semantic meaning. It shall not automatically replace, omit,
normalise, or preserve a candidate independently from its containing region:
the existing safe outcome continues to leave the complete region unchanged.

The project shall provide one small, repository-owned, reviewed override
registry for approved legacy bullet mappings. Each entry shall identify the
extracted source scalar, the portable Unicode output scalar or cluster, and,
where applicable, the source-font resource identity that limits the entry's
scope. Adding an entry requires visual comparison against the source document
to establish the intended marker and confirmation that the selected portable
output font covers the mapped value.

Before portable-font coverage selection and bounded-layout fitting, the PDF
adapter shall apply a matching registry entry to every matching
newline-delimited logical line in the replacement text. A match requires the
entry's source scalar to be the first non-whitespace scalar in the same
logical source line and replacement line returned by the provider, and
requires any configured source-font resource identity to match. The source
logical line shall also meet the two-following-non-whitespace-scalar threshold
for a candidate bullet. The adapter shall substitute only that leading scalar
on each matching line with the entry's portable output value, then fit and
serialize the complete resulting replacement using the normal portable-face
selection path. It shall preserve newlines and shall not send a second
replacement-provider request. A successful mapped region shall be a normal
replacement: it shall not be retained merely because the original legacy
bullet was outside portable-font coverage.

An override shall apply only when its complete matching conditions hold; it
shall not turn all Private Use Area characters, all leading symbols, or all
glyphs from a font into bullets. A missing entry, a non-matching source font,
or a replacement that does not retain the expected leading source scalar shall
leave the normal unsupported behaviour unchanged. Likewise, if the mapped
replacement still has an uncovered cluster or unsupported layout, the complete
region shall be retained and diagnosed under the existing safe outcome. An
applied mapping does not require a diagnostic sidecar in an otherwise
successful run; existing diagnostic reporting remains for retained work.

### Rationale

Legacy office fonts commonly encode visually decorative bullets as Private Use
Area characters. Unicode coverage cannot establish their meaning, and mapping
them automatically could change meaningful content. A precise diagnostic lets
an operator run the conversion over local documents, search for a bounded set
of review candidates, compare each candidate with its source rendering, and
approve only well-understood mappings.

### Notes

The portable-face coverage decision remains mechanical: the adapter tests the
actual replacement cluster against the selected base, Math, and Symbols 2 Noto
faces in their established order. Candidate classification does not infer that
Noto Sans Symbols 2 should cover a Private Use Area glyph, nor does it select
an output symbol. Tests shall use synthetic PDFs only. They shall verify a
leading unsupported Private Use Area scalar produces the additional
classification; an unsupported middle-of-text scalar, multiple uncovered
clusters, and an unsupported multi-scalar grapheme do not; and every case
retains its complete source region. Tests shall also verify that a reviewed
mapping replaces every matching logical-line-leading scalar, uses the mapped
portable value for fitting and PDF output, preserves the remaining translated
text and newlines in the same region, and does not make a second provider
request. They shall verify that a provider normalisation on one line does not
suppress a candidate on another line, and that a source-font mismatch,
provider-returned leading-character mismatch, and any remaining uncovered
cluster retain the complete region with the ordinary unsupported diagnostic.
They shall also verify that a marker with zero or one following
non-whitespace source scalar is neither classified as a candidate nor mapped,
and that it retains the existing ordinary unsupported outcome.
