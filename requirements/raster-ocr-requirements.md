# Raster Images and OCR Requirements

OCR providers, raster-image processing, replacement-image rendering, and OCR evaluation.

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
| Status | Implemented |
| Source | User request following Windows PaddleOCR runtime failure |
| Date Added | 2026-08-21 |
| Related Requirements | FR-2026-08-01-02, TR-2026-08-01-01, SR-2026-08-01-01, SR-2026-08-21-01 |

### Description

The PaddleOCR provider shall select its execution device automatically after PaddleOCR has initialized. It shall use NVIDIA GPU 0 when the installed PaddlePaddle runtime is CUDA-enabled and reports an available GPU; otherwise it shall use CPU. GPU acceleration is an opportunistic performance improvement, not a separately guaranteed CI target.

When automatic-engine initialization or inference fails, the provider shall retry the request once with an explicit CPU engine. A failure from that CPU retry shall raise `OcrProviderError` without further fallback.

On Windows and Linux CPU inference, the provider shall disable PaddleOCR's OneDNN/MKLDNN execution path and use Paddle's ordinary CPU execution mode. This workaround shall not apply to GPU inference or macOS CPU inference.

### Rationale

PaddleOCR documents NVIDIA GPU acceleration and the project now provides a Windows test runner. The pinned Windows and Linux CPU runtimes fail in OneDNN execution, while the same test input succeeds with OneDNN disabled. Automatic GPU selection preserves available performance improvements without making GPU hardware mandatory.

### Notes

The provider shall not add a device-selection command-line option in this feature. Its automatic GPU choice depends on the PaddlePaddle distribution and the locally installed NVIDIA driver and CUDA runtime. The current CPU-only environment remains valid and shall select CPU. A CUDA-enabled PaddlePaddle distribution may be adopted only when it can comply with the repository's uv lockfile, PyPI-only, no-source-build, and dependency-cooldown policies. The provider shall not import PaddlePaddle separately to probe device availability before PaddleOCR initializes.

Automated tests shall mock Paddle runtime availability and engine behavior to verify device selection, the Windows and Linux CPU OneDNN setting, preserved macOS CPU behavior, and the single GPU-to-CPU fallback without requiring CUDA hardware. GPU inference verification remains an optional local check on compatible hardware.

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

The project shall provide a command that evaluates every supported bitmap image in `outputs/evaluations/ocr/input/` with every discovered OCR-provider plugin eligible for automatic local evaluation when no path filter is supplied. The number of images evaluated per run is limited by FR-2026-10-26-04. Explicit provider selection and exclusions are governed by FR-2026-08-04-02 and FR-2026-10-24-02; path filtering is governed by FR-2026-10-24-03. The input image's enclosing language-code directory shall supply the BCP 47 language passed to the provider.

The command shall use the existing OCR-provider factory and OCR task request and response abstractions in `pipeline/ocr/`. It shall not implement, discover, or invoke provider-specific OCR logic independently.

For each provider, the command shall create a corresponding provider root in `outputs/evaluations/ocr/output/`. Beneath that root, it shall mirror the input hierarchy. For every input image, it shall write a JSON serialization of the normalized OCR response together with a status, a standalone SVG detection mask with every detected text region masked in black and linked to its viewer table row (FR-2026-10-26-02), and one clipped bitmap image for each detected text region, using that region's bounding box. When a provider does not support an image's language, or when OCR fails for an image with a supported language, the command shall continue evaluating other images and providers, write a JSON file containing only a failed status for that image, and shall not create visual OCR artifacts for that image.

Each provider root shall contain a generated static HTML viewer that lets a user browse that provider's image evaluations, including the input image, SVG detection mask, detected-region clips, and OCR result data.

### Rationale

Persisting visual artifacts alongside normalized provider output makes it practical to inspect detection coverage and compare OCR providers against the local, real-data corpus.

### Notes

Evaluation outputs are local generated artifacts and remain ignored by Git. The command may process confidential inputs locally, but it shall not send their contents, paths, metadata, or extracted text to external services or commit them to repository artifacts, except for explicitly selected Google Cloud Vision image processing under SR-2026-10-24-01 and FR-2026-10-24-02.

The static viewer may load jQuery from a CDN. The precise success-status JSON shape and generated-file naming shall be defined by the implementation.

Each provider root shall contain a checksum representing its complete evaluation input tree. The command shall skip regenerating a provider's output only when that checksum matches the current input tree and the provider root's `index.html` exists. Removing either the checksum or `index.html` shall force that provider's output to be regenerated.

---

## FR-2026-08-02-01

| Property | Value |
|----------|-------|
| Title | Report OCR-evaluation progress |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-02 |
| Related Requirements | FR-2026-08-01-03, TR-2026-08-01-01, FR-2026-09-03-01, FR-2026-10-26-03 |

### Description

FR-2026-10-26-03 supersedes the row mapping in this requirement with stage-based rows covering OCR and text replacement.

The OCR-evaluation command shall render terminal progress as defined by
FR-2026-09-03-01. Its overall bar shall contain every non-cached
provider/image evaluation in the run. Its current-task bar shall contain the
non-cached provider/image evaluations in the active folder below an input
language-code directory.

### Rationale

OCR evaluation against the local real-data corpus can take substantial time. Folder-level progress gives the user useful visibility into work completed without requiring them to infer it from model output files.

### Notes

Images directly in a language-code directory shall be represented by that
language directory's current-task bar. It shall show the current provider and
image. The command shall write a one-line skipped status for each
checksum-skipped provider.

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

The static OCR-evaluation viewer shall not render JSON result content inline. For each successful image evaluation, it shall show the detected text-region clips in a table with an image column and an extracted-text column. Each detected region shall occupy one row. It shall present the provider's original recognized text without browser or page translation. The viewer shall mark the page and extracted-text cells as not translatable and shall identify each cell's source language.

### Rationale

The table gives a compact, legible visual comparison of every detected region and its OCR result without overwhelming the manual-evaluation view with serialized data.

### Notes

The viewer shall retain the input image and the black SVG detection mask (FR-2026-10-26-02) above the table. It shall retain a JSON-result link that opens in a new browser tab, but shall not render JSON content inline.

Automated tests shall use synthetic multilingual OCR text and verify that the generated HTML preserves the source text and includes translation-prevention markup.

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

The estimator reports the observed colours of whatever image it receives. Raster text replacement applies a page colour to a transparent image before calling it, as FR-2026-10-26-01 specifies.

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

The colour estimator shall continue to report observed source colours unchanged. To improve the perceived sharpness of light replacement text on dark surfaces, the renderer shall apply a bounded rendering-only lightness adjustment when the text colour's relative luminance exceeds that of an opaque background whose relative luminance is at most `0.35` by at least `0.15`. The adjustment shall preserve the estimated text colour's hue and alpha and move its HSL lightness 65% of the remaining distance toward white. For a fully transparent background, the relationship shall be judged against the assumed page colour of FR-2026-10-26-01 instead of being skipped. The adjustment otherwise applies by the existing rules and shall not apply to other foreground/background relationships.

Automated tests shall use synthetic images and fonts only; they shall not use sample data. Tests shall cover in-place modification, background removal, rendered text colour, fitting of both shorter and longer replacement strings, wrapping, rotation, and output bounds. The local command and HTML output shall be verified with temporary synthetic inputs; the supplied examples are for manual visual evaluation only.

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

For every successful OCR image evaluation, the OCR-evaluation command shall run a text-replacement artifact stage after writing the current OCR artifacts. The stage shall use the current evaluation's original image, `OcrText` items, and source language. It shall use target language `en`, estimate the colours of every text region, and apply the replacement from each selected text-replacement provider (FR-2026-10-26-05) to one image copy per provider. Each provider image shall receive all of its replacements successively, allowing the in-place renderer to produce a complete updated image.

The stage shall create a new generated text-replacement artifact directory alongside the current image artifacts. It shall contain one complete updated PNG per text-replacement provider and a clipped replacement bitmap for every eligible region/provider combination. It shall retain the original padded OCR clip as the table's original-text image.

The text-replacement stage and its report shall skip each OCR text region whose confidence is less than `0.65`. Skipped regions shall remain present in the OCR-result JSON and existing OCR report, but shall not be replaced in complete provider images or appear in the text-replacement table.

The OCR artifact stage and text-replacement artifact stage shall have independent cache freshness markers. A missing or stale OCR viewer or OCR cache marker shall regenerate OCR and all dependent artifacts. A current OCR artifact set with a missing or stale text-replacement viewer or text-replacement cache marker shall retain the saved OCR JSON and OCR artifacts, then regenerate only the text-replacement artifacts and report without calling the OCR provider.

The existing provider-root static OCR viewer shall remain unchanged, except as amended by FR-2026-10-26-02. Each provider root shall additionally contain a separate static text-replacement results page. For each successful image, that page shall show the original input and one selectable complete-image preview together in one non-wrapping row, each taking half of the available page width. Both images shall use the same `max-width: 100%` sizing rule without forced upscaling. The page shall then show a text-replacement table with the region number, original padded text image, and one replacement text-image column for every provider that ran (FR-2026-10-26-05). The preview image shall appear above its local dropdown. The dropdown shall select the complete provider image without a page reload; it shall also offer the detected-region SVG mask (FR-2026-10-26-02) as its final option. The initial selected option and displayed image shall both be the first registered provider, as amended by FR-2026-10-26-05.

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

The scope is limited to preparing raster pixels for OCR. It does not require general document rendering or composition of arbitrary visual layers. Automated tests shall use synthetic transparent raster images and synthetic page or slide backgrounds only, and shall verify that the original image is retained for replacement output.

FR-2026-10-26-01 extends this page colour to every format handler and also applies it to colour estimation; the original image remains the source for replacement output.

---

## FR-2026-09-04-02

| Property | Value |
|----------|-------|
| Title | Preserve transparent paletted PNG alpha through raster text replacement |
| Owner | KrisTC |
| Status | Implemented |
| Source | User-reported DOCX embedded-image defect |
| Date Added | 2026-09-04 |
| Related Requirements | FR-2026-08-02-10, FR-2026-08-27-01, FR-2026-08-03-03 |

### Description

When the raster text-replacement pipeline processes a PNG with palette-based
transparency, including a PNG whose Pillow mode is `P` and whose transparency
is represented by a per-palette-entry byte sequence, it shall preserve the
decoded non-premultiplied RGBA semantics of the image through replacement and
output encoding.

Before the Skia rendering result is written back, the pipeline shall use an
alpha-capable working/output representation. It shall not paste or otherwise
copy palette indices generated for a different palette into the source
image's palette. Such an operation may change the opacity or colour represented
by an unchanged source pixel and is prohibited.

For every pixel outside all replacement background-wipe outsets, the decoded
output RGBA value shall equal the decoded input RGBA value. Replacement
background wipes and glyphs shall retain the alpha values selected by the
existing colour-estimation and rendering rules. In particular, an opaque source
or replacement glyph shall not become translucent solely because the source
PNG uses palette transparency.

The pipeline shall retain the PNG file format and source dimensions. It may
encode the output as truecolour RGBA rather than indexed palette PNG when that
is necessary to preserve the required pixel semantics. This requirement does
not require preservation of the source PNG palette, palette order, ancillary
metadata, or encoded bytes.

This applies equally to standalone bitmap processing and to raster PNG parts
embedded in supported Office documents. It does not alter FR-2026-08-27-01's
temporary OCR-only flattening rule: colour estimation, replacement rendering,
and output encoding shall continue to use the transparency-preserving image.

### Rationale

An indexed PNG's pixels are palette indices, while its alpha may be stored in
a separate palette transparency table. Converting a rendered RGBA result to a
new palette and then copying those indices into the original image treats the
new indices as entries in the old palette. The resulting pixels can become
nearly transparent even when the original or rendered glyphs are opaque.

### Notes

Automated tests shall use only synthetic images and documents. They shall
create a paletted PNG with a byte-sequence transparency table containing both
fully transparent and fully opaque entries, then process it through the normal
raster replacement path using deterministic OCR and replacement doubles. They
shall verify decoded RGBA equality for representative unaffected transparent
and opaque pixels, retained source dimensions and PNG format, and replacement
glyph pixels with the expected non-zero, opaque alpha where the selected text
colour is opaque. They shall also process that PNG as a media part in a
synthetic DOCX and verify the same decoded-alpha properties after extracting
the resulting media part. Tests shall not use confidential samples or derived
artifacts.

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

The project shall provide repository-root `run.ps1` and executable `run.sh` Python launcher scripts. Each launcher shall accept one or more Python arguments, run `python` with those arguments through an exact `uv run` synchronisation selecting the root project's `gpu` optional-dependency profile, and, when the repository-root `.env.local` file exists, pass that file to uv with `--env-file`. The launcher shall also support an explicit dotenv-file override for project-internal setup validation. The launcher shall preserve the Python process's exit code. Every project script that otherwise invokes `uv run python` directly shall invoke the platform-appropriate `run` launcher instead.

The setup script shall merge its candidate `PATH` entry with a temporary copy of `.env.local`, then start a fresh process through the PowerShell `run` wrapper using that temporary dotenv-file override. It shall verify that the installed PaddlePaddle distribution reports CUDA compilation support and detects at least one available CUDA device. The script shall report the detected CUDA Toolkit and cuDNN locations and the number of visible devices. It shall exit non-zero without creating `.env.local` when it did not previously exist, or modifying it when it did, if discovery, validation, dotenv loading, or Paddle CUDA-device detection fails. It shall delete the temporary candidate file in every outcome.

### Rationale

The Windows PaddlePaddle GPU wheel can be installed correctly while CUDA and cuDNN DLLs remain unavailable to its child process because their installation locations are not on `PATH`. A project-local environment file gives local development commands a repeatable way to expose those libraries and future provider settings without changing machine-wide configuration, while an end-to-end verification prevents treating a merely installed toolkit as usable GPU acceleration.

### Notes

The approved Paddle CUDA wheel registry in SR-2026-08-21-01 remains CUDA 12.6. The local runtime-discovery rule is independent of that wheel registry label: it shall select the newest valid CUDA Toolkit 12.x installation and the newest valid cuDNN 9.x Windows x86_64 runtime installation, including a standard cuDNN layout such as `C:\Program Files\NVIDIA\CUDNN\v9.<version>\bin\12.<version>\x64`. The fresh Paddle CUDA-device probe is the final compatibility check. The implementation shall identify the exact required cuDNN DLL names and compatible CUDA Toolkit locations from the pinned PaddlePaddle GPU runtime, rather than accepting an arbitrary directory that happens to contain similarly named files.

The setup script shall not download, install, update, or modify NVIDIA software, the Python environment, the uv lockfile, or the user's persistent environment variables. It may read standard Windows NVIDIA installation locations and relevant environment variables to discover candidate installations. Its diagnostics shall distinguish missing CUDA Toolkit, missing or incompatible cuDNN runtime libraries, an unavailable NVIDIA driver or GPU, and a PaddlePaddle CUDA-loading failure.

The setup script shall update the `PATH` entry atomically after the probe succeeds, so a failed run cannot leave a partially written file or overwrite user-managed settings. A malformed or duplicate managed `PATH` entry shall fail with a diagnostic rather than causing the script to rewrite unrelated content. The `PATH` entry is the setup script's only managed part of `.env.local`; users are responsible for adding, rotating, and removing any secrets. Diagnostics and automated tests shall not display secret values.

The `.env.local` file shall be added to `.gitignore` when this requirement is implemented. Automated tests shall mock installation discovery and the child-process probe; they shall not require CUDA hardware or NVIDIA software in CI. They shall verify that the setup script preserves arbitrary user-managed dotenv entries and rolls back cleanly on failure, and that each run wrapper uses `.env.local` only when it exists. The runtime probe is a required local validation on supported Windows machines, while CPU-only platforms remain valid under FR-2026-08-21-01.

---

## FR-2026-09-07-03

| Property | Value |
|----------|-------|
| Title | Support opportunistic NVIDIA PaddleOCR acceleration in the OCI image |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-09-07 |
| Related Requirements | FR-2026-08-21-01, FR-2026-08-24-03, FR-2026-09-07-01, TR-2026-09-07-01, SR-2026-08-21-01 |

### Description

The GPU OCI image variant defined by FR-2026-09-07-01 shall support Linux `x86_64` hosts with an NVIDIA GPU. It shall contain an exact, CUDA-enabled Linux `paddlepaddle-gpu` wheel and the compatible CUDA and cuDNN user-space runtime libraries selected during image construction. The image shall not contain or attempt to install an NVIDIA kernel driver.

When the host exposes one or more NVIDIA devices through a configured container runtime, the existing PaddleOCR provider shall retain its automatic device selection and use GPU 0. The image shall not add an OCR device CLI option or require a project-specific GPU environment variable. The GPU image shall fail with a concise runtime diagnostic when no compatible device is exposed; FR-2026-09-07-01's CPU image is the deterministic CPU path.

The project shall provide a GPU validation command that starts the published image with a requested GPU and verifies, without processing a source document, that PaddlePaddle is CUDA-enabled and reports at least one visible CUDA device. It shall fail non-zero with a concise diagnostic when the host driver, NVIDIA container runtime, requested device, or image runtime is unavailable. GPU validation is a documented optional hardware check, not a mandatory CI test.

### Rationale

The image must include the user-space components compatible with its pinned Paddle runtime, while the host remains responsible for exposing its driver and GPU through the normal container runtime. A separate CPU image avoids a CUDA wheel's early driver-library load preventing deterministic CPU execution.

### Notes

This requirement adds Linux-container support; it does not alter the Windows CUDA discovery and dotenv configuration of FR-2026-08-24-03. It makes no GPU claim for macOS, non-NVIDIA accelerators, or a host that does not expose a device to the container.

Decision recorded 2026-09-08: publish separate CPU and GPU images. The exact
Linux `paddlepaddle-gpu` wheel imports `libcuda.so.1` before provider device
selection, and the NVIDIA container runtime supplies that driver library only
when a device is requested. The GPU image therefore does not claim CPU fallback;
the CPU image supplies it using the normal CPU Paddle wheel.

Automated tests shall mock Paddle's CUDA capability boundary and verify image configuration metadata and the validation command's success and failure reporting. A manually run validation on a compatible NVIDIA Linux host shall verify the actual GPU path before a release is published.

---

## FR-2026-10-24-01

| Property | Value |
|----------|-------|
| Title | Add Google Cloud Vision OCR provider |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-10-24 |
| Related Requirements | FR-2026-08-01-02, FR-2026-10-24-03, SR-2026-10-24-01, TR-2026-08-01-01 |

### Description

The default OCR-provider factory shall discover a `google_cloud_vision` provider. The provider shall implement the existing OCR request and response contract and shall be selectable by name without changing the default `paddleocr` provider.

For each supported bitmap-image request, the provider shall use Cloud Vision's synchronous `images:annotate` operation with the `DOCUMENT_TEXT_DETECTION` feature. It shall omit `languageHints` so Vision automatically detects languages, including images that mix Japanese and Latin text. The request's BCP 47 language tag shall still be used for supported-language validation and downstream result context. It shall not use asynchronous annotation or Cloud Storage input or output.

The provider shall encode the input image in a format supported by Cloud Vision, preserve its dimensions and visible pixels under the existing OCR transparency-compositing policy, and check the applicable synchronous API image, pixel-dimension, and request-size limits before transmission. It shall raise `OcrProviderError` when the image cannot be sent within those limits. It shall not resize the image or move it to Cloud Storage to bypass a limit.

The provider shall normalize the API's structured OCR response into the existing text-item contract. FR-2026-10-24-03 defines the intended grouping for translation and replacement. Bounding polygons shall use source-image pixel coordinates and preserve the API's vertex order when reporting an API-supplied polygon. Confidence shall remain normalized to the 0.0-to-1.0 range required by FR-2026-08-01-02. Provider-specific response details may be included in the optional extra-data field when useful to preserve document structure.

The provider shall declare the BCP 47 languages it supports and shall declare itself ineligible for the default local OCR-provider contract test. The provider shall raise `OcrProviderError` for invalid configuration, authentication or authorization failures, API failures, and malformed response structures. A valid response with no detected text shall return an empty OCR result.

### Rationale

Cloud Vision provides dense document OCR through a selectable managed provider while retaining the pipeline's normalized OCR result model and PaddleOCR default.
Google Vision OCR provider may be more useful when a GPU is not available as the CPU version of PaddleOCR can be very slow.

### Verification

Automated tests shall use synthetic images and a mocked Google client. They shall verify request construction, language-hint omission, normalized response text and order, confidence, source-image polygon conversion, local rejection of an over-limit image, provider failures, and that no network request or credential is required by the default test suite.

---

## FR-2026-10-24-02

| Property | Value |
|----------|-------|
| Title | Manually evaluate Google Cloud Vision OCR |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-10-24 |
| Related Requirements | FR-2026-08-01-03, FR-2026-10-24-01, SR-2026-10-24-01 |

### Description

`scripts/ocr_evaluations.py` shall exclude `google_cloud_vision` from its automatic all-provider run. It shall accept `--ocr PROVIDER` to evaluate only the named registered OCR provider, including `google_cloud_vision` when explicitly selected. The command shall continue to prepare the normal evaluation input corpus and write results through its existing provider-specific artifacts and viewer.

An explicit `--ocr google_cloud_vision` run shall process every eligible image selected for the run, including confidential samples when selected, through the Cloud Vision provider under SR-2026-10-24-01. The command help and developer documentation shall state that this selection sends image content to Google. The evaluator shall send no source paths, filenames, metadata, evaluation artifacts, or extracted text to Cloud Vision.

The automatic run shall not instantiate `google_cloud_vision` or make a Vision API call. The explicit run shall not evaluate other OCR providers. The post-OCR text-replacement stage uses the providers selected under FR-2026-10-26-05.

### Rationale

An opt-in evaluator run lets the developer compare Cloud Vision OCR against the local visual corpus while preventing a default evaluation from transmitting images.

### Notes

The OCR-result JSON and primary OCR viewer use the provider's recognized text. The separate text-replacement viewer continues to translate to English under FR-2026-08-02-13.

### Verification

Automated tests shall use synthetic images and a fake OCR provider. They shall verify default exclusion, explicit selection, no unrelated provider calls, provider-root artifacts, and that the command help identifies the remote-image boundary. Tests shall not contact Google or read confidential samples.

---

## FR-2026-10-24-03

| Property | Value |
|----------|-------|
| Title | Targeted OCR evaluation and Vision text grouping |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-10-24 |
| Related Requirements | FR-2026-08-01-01, FR-2026-08-01-02, FR-2026-08-01-03, FR-2026-08-02-05, FR-2026-10-24-01, FR-2026-10-24-02 |

### Description

`scripts/ocr_evaluations.py` shall accept an optional repeatable `--include PATTERN` option using the same comma-separated glob syntax as the folder-replacement command. Patterns shall match supported source-file paths relative to `sample-data/`. A selected document shall select all bitmap images extracted from that document; a selected standalone bitmap shall select that image. With no include pattern, existing all-source behavior shall remain.

For a filtered run, input preparation shall copy or extract only selected source files, and OCR evaluation shall process only images originating from those files, even when prepared images from earlier runs remain under the input root. The filter shall be applied before OCR requests, checksums, and progress totals are calculated. Filtered preparation shall not delete previously prepared files solely because they are outside the current selection. A filter matching no supported source files shall complete successfully without invoking an OCR provider or replacing an existing provider output root.

Provider-specific viewers and generated results from a filtered run shall describe only the selected images. Existing provider-root checksum behavior shall account for the selected image set so that a different selection cannot be mistaken for a current evaluation.

The `google_cloud_vision` provider shall supply one text region per visual line to every caller, including folder replacement and OCR evaluation. It shall combine words and punctuation belonging to one visual line while keeping distinct lines, bullets, and indented entries separate. Text on the same baseline with a gap larger than ordinary word spacing shall form separate regions, including neighboring table cells. Adjacent substantive text at a clearly different visual character size shall also form a separate region; a small bullet or punctuation mark shall not by itself trigger this split. A region's text, confidence, and source-image polygon shall correspond to the same grouped content. Detected spaces shall be retained within a line; detected line breaks shall terminate a region. Grouping shall also use OCR word geometry when break markers alone do not separate visually distinct lines. This grouping shall be derived locally from the existing `DOCUMENT_TEXT_DETECTION` response without another external service. It shall not split a visual line into sentences or join text across visual lines.

The evaluation JSON and viewer shall make detected line breaks visible so the reviewer can distinguish missing OCR breaks from display-only whitespace collapse. When the Vision grouping changes, the evaluator shall regenerate its existing Vision artifacts even when image inputs are unchanged. The `google_cloud_vision` provider shall supply a cache identity, so its normalized grouped results can use the opt-in provider-result cache of FR-2026-08-27-10, that includes a grouping version and every numeric grouping threshold (including the character-size split ratio). Changing any of them shall invalidate cached Vision results and the evaluator's Vision artifacts without a separate manual version bump. Only normalized results are cached, never the submitted image or the raw API response (SR-2026-10-24-01).

### Rationale

The evaluation corpus is large, and an explicit source-path selection lets the developer assess a document or small group without running OCR on unrelated images. Matching source paths lets preparation skip unrelated document extraction as well as provider calls. Word regions are too small for useful translation, while Vision paragraph regions can combine text from visually separate lines and lose bullet or indentation structure. Text with a distinct visual size on the same line may be a separate label and needs its own replacement bounds.

### Notes

The filter selects source files. It cannot target one extracted image within a selected document. A separate `--output-root` can retain results from different selections.

A sentence wrapped across two visual lines is returned as two regions so that each region keeps the geometry of its source line. Sentence-aware grouping may be considered separately after manual review.

### Verification

Automated tests shall use synthetic source trees and fake providers. They shall cover single, repeated, and comma-separated patterns; standalone images and documents; previously prepared excluded images; zero matches; unchanged no-filter behavior; selected-set progress and cache checks; and no provider call for an excluded image.

Synthetic Vision responses shall be used to evaluate line breaks, wrapped text, punctuation, Japanese text, bullets, indentation, multi-column layouts, adjacent table cells with a wider gap than words within a cell, distinct and mildly varying character sizes, confidence, polygon geometry, and reading order. Tests shall verify that line grouping is the same through folder processing and OCR evaluation, that the viewer exposes detected breaks, and that older Vision artifacts are invalidated. Tests shall not contact Google or use confidential samples.

---

## FR-2026-10-26-01

| Property | Value |
|----------|-------|
| Title | Estimate and render raster replacement text against an assumed page colour |
| Owner | KrisTC |
| Status | Implemented |
| Source | User-reported DOCX embedded-image defect |
| Date Added | 2026-10-26 |
| Related Requirements | FR-2026-08-02-09, FR-2026-08-02-10, FR-2026-08-02-13, FR-2026-08-27-01, FR-2026-09-04-02 |

### Description

Every raster text-replacement operation shall receive an assumed page colour: an opaque sRGB value that stands for whatever shows through the image's transparent pixels. The DOCX and PPTX handlers shall supply the colour that FR-2026-08-27-01 selects. Standalone bitmap, XLSX, and PDF handlers shall supply opaque white, including for PDF vector-content OCR rasters, until a separate requirement defines direct page-colour determination for that format. A handler that cannot determine a colour shall supply opaque white. The same page colour shall be used for OCR flattening under FR-2026-08-27-01 and for the colour estimation in this requirement.

When the source image has any pixel with alpha below 255, colour estimation shall analyse a temporary copy alpha-composited onto the page colour. Hidden RGB values of fully transparent pixels and partially transparent antialiasing pixels shall therefore contribute only the colour they would visibly produce. The source image shall be retained, unmodified, for background wipes, glyph rendering, and output encoding, and FR-2026-09-04-02 shall continue to apply to it. The text-region colour estimator's public contract is unchanged: it reports the observed colours of the image it is given, and the caller is responsible for supplying the composited copy.

The replacement text colour shall always have alpha 255. A region whose immediate background in the source image is fully transparent shall retain a fully transparent wipe colour, so a transparent cell stays transparent in the output and shows the document background. A background that is not fully transparent shall continue to be wiped with its observed stored colour.

When the estimated text-colour confidence is below 0.60 and the region's background shows the page colour (a fully transparent source background, or an opaque background equal to the page colour), the replacement text colour shall be the higher-contrast of opaque black and opaque white against the page colour, using WCAG relative luminance. This fallback shall be selected before the rendering-only lightness adjustment in FR-2026-08-02-10, which shall then apply by its existing rules. Estimated text colours with low confidence on any other background shall be unchanged by this requirement.

The text-replacement artifact stage in FR-2026-08-02-13 shall use the same page-colour behaviour, with opaque white as its page colour.

### Rationale

A transparent PNG in a document can look correct on the page while its stored pixels mislead colour estimation. Antialiasing pixels with low alpha and unrelated hidden RGB can form the apparent text colour, and replacement text drawn with that colour is nearly invisible on any page. The page colour supplies the missing context in one place, keeps the source's transparency in the output, and guarantees legible opaque text.

### Notes

This requirement amends the alpha-handling exclusion in FR-2026-08-27-01 and extends the page-colour source to every format. It does not change estimator output for an image the caller supplies or the alpha-zero background rules in FR-2026-08-02-09. It amends FR-2026-08-02-10 only so that its rendering-only lightness adjustment judges a fully transparent background against the page colour.

The 0.60 threshold is a starting value to be reviewed against the text-colour confidence of correct and incorrect estimates in representative evaluations. Evaluation of a dark-mode page background is out of scope: a transparent cell shows the actual document background, which may be dark.

PDF and XLSX page-colour determination from direct source properties, text-colour fallback on backgrounds other than the page colour, and theme or inherited colour resolution are deferred.

### Verification

Automated tests shall use synthetic images and synthetic page colours only. They shall cover:

- dark glyphs with antialiasing on a fully transparent background, verifying that the chosen text colour is the glyph colour rather than the antialiasing colour and that its alpha is 255;
- a row of transparent cells beside an opaque-filled row, verifying that the transparent wipe stays alpha 0 and the opaque wipe keeps its colour;
- a non-white page colour, verifying composited estimation and the original image retained for output;
- text-colour confidence on both sides of the threshold on a page-colour background, and low-confidence text on a non-page-colour background remaining unchanged;
- white and black fallback selection against a light and a dark page colour, and the lightness adjustment applying to light text on a transparent background over a dark page colour but not over a light one;
- default white for standalone bitmap, XLSX, and PDF inputs;
- identical behaviour through the folder-replacement and OCR-evaluation paths; and
- the same behaviour for a paletted PNG with per-palette alpha embedded in a synthetic DOCX.

Tests shall not use confidential samples or derived artifacts.

---

## FR-2026-10-26-02

| Property | Value |
|----------|-------|
| Title | Replace the masked bitmap with a linked SVG detection mask |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-10-26 |
| Related Requirements | FR-2026-08-01-03, FR-2026-08-02-02, FR-2026-08-02-13 |

### Description

For every successful OCR image evaluation, the OCR-evaluation command shall write a standalone SVG detection mask in place of the black-masked PNG. The command shall no longer write the masked PNG. The SVG shall be named `<image file name>.masked.svg`, beside the image's other artifacts, and shall not be written for an image whose evaluation failed or whose language is unsupported.

The SVG shall have a `viewBox` and intrinsic size equal to the source bitmap's pixel dimensions. It shall contain, in order, one `<image>` element that references the original input bitmap by relative URL, and one filled black `<polygon>` for each detected text region, using the region's `bounding_polygon` vertices in source-pixel coordinates. The result shall mask the same area as the retired PNG. The SVG shall not embed the bitmap data and shall not contain script.

Each polygon shall be wrapped in an `<a>` element when the OCR viewer has a table row for that region. Its `href` shall be a relative URL to that row in the provider root's OCR viewer (`index.html`), and its `target` shall be `_top`, so that activating the polygon from inside an embedded SVG scrolls or navigates the whole page to the row. A polygon whose region has no table row shall have no link and no `<a>` wrapper. Every polygon shall have a `<title>` containing the region's extracted text, shown by the browser as a tooltip. Region numbers shall match the table and the `text-NNNN` clip numbering. The SVG shall include every detected region, whatever its confidence.

In the OCR viewer, every region table row shall have an `id` that is unique within the page, is derived from the image's relative path and the region number, and is stable across regenerations. The viewer shall show the SVG mask through an `<object type="image/svg+xml">` element in place of the previous `<img>`, so that its links remain active, with `max-width: 100%` and the same sizing as the input image beside it. The row that is the current URL fragment target shall be visually highlighted using the CSS `:target` selector. No script shall be required for the links or highlighting.

The text-replacement results page shall use the same SVG for its "Detected regions masked" dropdown option. Because browsers do not allow an SVG shown through an `<img>` to load its referenced bitmap or follow links, the page's existing selection script shall display the SVG in an `<object>` element while that option is selected, and the complete-provider-image `<img>` otherwise, without a page reload. Activating a polygon from that page shall open the corresponding row in the OCR viewer, which is the only page that lists every detected region. The first-registered-provider initial selection in FR-2026-08-02-13 is unchanged.

All values written to the SVG and viewer markup, including URLs, region identifiers, and extracted text, shall be XML- or HTML-escaped as appropriate, and extracted text shall remain unmodified and marked not translatable where it appears in viewer markup.

The OCR artifact format version and the text-replacement artifact format version shall both change, so that a provider root generated with the retired masked PNG is regenerated. This requirement amends the masked-image wording in FR-2026-08-01-03, FR-2026-08-02-02, and FR-2026-08-02-13 to refer to the SVG detection mask.

### Rationale

A vector mask keeps the original bitmap pixels unmodified, avoids a second raster copy, and gives every detection a hyperlink target. A reviewer can click a masked region and land on its OCR table row instead of matching a position by eye.

### Notes

The SVG remains a standalone file that can be opened directly in a browser. Its links then target the OCR viewer by relative URL, and its bitmap reference resolves only while the input tree stays at its relative location. Browsers also treat a file-loaded SVG as a separate origin, so the design avoids script that reads the SVG's contents; that is why the viewers use `<object>`, which needs no script, rather than inlining the SVG by fetching it.

### Verification

Automated tests shall use synthetic images, synthetic OCR results, and temporary output roots only. They shall verify:

- an SVG is written for a successful image and no masked PNG is written, including no artifact for failed and unsupported-language images;
- the SVG dimensions, relative bitmap reference, polygon coordinates, link targets, tooltip text, and escaping of markup-significant characters in synthetic text;
- every table row has the unique `id` that its polygon link references, including images with the same file name in different folders;
- the OCR viewer embeds the SVG through `<object>` with the `:target` highlight style;
- the replacement page's mask option uses the SVG and the script swaps between `<object>` and `<img>`; and
- a provider root with the previous format version is regenerated.

Tests shall not use confidential samples or derived artifacts.

---

## FR-2026-10-26-03

| Property | Value |
|----------|-------|
| Title | Report every stage of OCR evaluation in its progress display |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-10-26 |
| Related Requirements | FR-2026-08-01-03, FR-2026-08-02-01, FR-2026-08-02-13, FR-2026-09-03-01 |

### Description

The OCR-evaluation command prepares its inputs, removes superseded provider output, runs an OCR stage, and then runs the text-replacement artifact stage of FR-2026-08-02-13. Its terminal progress shall cover every one of these through the Rich display of FR-2026-09-03-01, so that no phase that can take noticeable time runs without a visible, named progress row. It shall replace the progress-row mapping of FR-2026-08-02-01 as follows. The nested row is not used.

The live display shall start before input preparation begins, rather than after cleanup, and shall close before the command's final summary or error.

**Overall row.** Its units are the stages that have work in this run, in execution order:

1. One **Prepare inputs** stage, always present. It covers OCR-evaluation input preparation (FR-2026-08-02-05), input discovery, and the input-tree checksum.
2. One **Clean up** stage, present only when at least one existing provider root is to be removed before regeneration.
3. One **OCR** stage, present only when at least one OCR provider's OCR artifacts are not current.
4. One **text-replacement** stage for each text-replacement provider that FR-2026-08-02-13 invokes, present only when at least one OCR provider root needs its text-replacement artifacts regenerated. This includes a root whose OCR artifacts are current but whose text-replacement artifacts are missing or stale.

A stage shall advance the overall row once, after it completes. A stage absent for the reasons above shall not contribute a unit. Which later stages exist is known only after the Prepare inputs stage finishes, so the overall row shall be indeterminate until then and shall then show its final total. It shall not show a percentage or ETA before that point.

**Current row.** While a stage is active, the current row shall count that stage's files and shall describe the stage, not a folder:

- For the Prepare inputs stage, a unit is one source file that preparation copies or extracts, or one image that discovery or checksumming reads. Where the total is not known in advance, the row shall be indeterminate and show the count completed so far and a detail label naming the active step (`Preparing`, `Discovering`, or `Checksumming`), never leaving the row without a label.
- For the Clean up stage, a unit is one file removed from an existing provider root. The command shall first count the files to be removed, showing an indeterminate row labelled `Scanning` while it does so, and then show a determinate row. Its detail label shall show the provider whose root is being removed. A file that cannot be removed shall still propagate its error exactly as the command does today, after the live display closes.
- For the OCR stage, a unit is one non-cached OCR-provider/image evaluation, across every OCR provider being run. This is the unit count that FR-2026-08-02-01 used for its overall row.
- For a text-replacement stage, a unit is one successful OCR-result image in an OCR provider root that needs text-replacement regeneration, processed with that stage's text-replacement provider. An image whose OCR status is failed or unsupported has no replacement artifacts and shall not be counted.

The current row's description shall name the stage: `Prepare inputs`, `Clean up`, `OCR`, or `Text replacement: <provider name>`. It shall be reset when the stage completes. For the OCR and text-replacement stages, its detail label shall show the OCR provider and the image's file name, using the label-length handling that FR-2026-09-03-01 defines. Each unit shall advance the current row once, whether the file succeeds, fails, or is skipped within its stage.

When the OCR or a text-replacement stage has finished its files and is writing provider viewers and cache markers, its current row shall remain visible with a detail label `Writing viewer: <provider name>`. This label adds no units.

**Scheduling.** The current row's per-file counts for one text-replacement stage require that stage to finish its images before the next text-replacement provider starts. The command may reorder or restructure its replacement work to achieve this. Every artifact it generates, its content, the format-version and cache-freshness markers, the viewers, and the continue-on-failure behaviour of FR-2026-08-01-03 and FR-2026-08-02-13 shall be unchanged by progress reporting.

The existing one-line skipped-provider status of FR-2026-08-02-01 shall remain, shall be written through the live display's console, and the command shall report any skipped text-replacement stage in the same way. When Prepare inputs is the only stage, the display shall close as soon as it completes.

### Rationale

Text replacement is repeated for every text-replacement provider and can take as long as OCR on a large corpus. A language-folder progress row says nothing about which of these stages is active. Showing one overall unit per stage and a per-file current row for that stage lets a reviewer see which condition is running and how far through the corpus it is.

Removing a large provider output tree before regeneration can take about a minute, and with no output the command appeared to hang. Input preparation, discovery, and checksumming can be equally slow on a large corpus. Naming these phases lets a reviewer tell that the command is busy rather than stuck.

### Notes

This requirement replaces the folder-based current-row mapping in FR-2026-08-02-01 and the OCR-evaluation bullet of FR-2026-09-03-01 for this command. The language-folder grouping is no longer a progress concept. Other behaviour of those requirements, including the Overall, Current, and ETA rendering and the non-interactive plain-text fallback, remains in force.

The OCR stage's current row spans every OCR provider, so a run with two OCR providers has one OCR unit on the overall row and `images x 2` units on the current row.

### Verification

Automated tests shall use synthetic input trees, fake OCR providers, registered local test text-replacement providers, and mocked rendering boundaries. They shall verify:

- the overall total and advancement for a full run: Prepare inputs, Clean up, OCR, and one unit for each text-replacement provider, with the overall row indeterminate until preparation finishes;
- current-row totals and descriptions for every stage, with the per-stage reset between stages, including the indeterminate `Scanning` row followed by a determinate Clean up row when a synthetic provider root with known files is removed;
- that the live display is already active during Prepare inputs and Clean up, using mocked preparation and file-removal boundaries, so a slow removal is visible;
- a run whose OCR artifacts are current but whose text-replacement artifacts are stale, which shows only the Prepare inputs and text-replacement stages and no Clean up or OCR stage;
- a run in which every provider output is current, which shows only the Prepare inputs stage and writes the skipped-provider lines above the display;
- the `Writing viewer` detail label without an extra unit;
- that a removal failure closes the display before the error propagates;
- that failed and unsupported-language images are excluded from text-replacement totals, and that a failure within a stage still advances the current row once;
- that a text-replacement stage completes all its images before the next provider begins; and
- generated artifacts unchanged from those produced before this requirement.

Tests shall not use confidential samples or derived artifacts.

---

## FR-2026-10-26-04

| Property | Value |
|----------|-------|
| Title | Limit the number of images in an OCR-evaluation run |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-10-26 |
| Related Requirements | FR-2026-08-01-03, FR-2026-08-02-05, FR-2026-10-24-02, FR-2026-10-24-03, FR-2026-10-26-03 |

### Description

`scripts/ocr_evaluations.py` shall accept an optional `--max-images N` option, where `N` is a non-negative integer. When the option is absent, `N` shall be 25. A value of 0 shall mean no limit. A negative or non-integer value shall be rejected as a command-line error that names the option, before any preparation or OCR work begins.

The limit shall apply to the number of bitmap images evaluated in one run. It shall be applied to the images that remain after the `--include` selection of FR-2026-10-24-03, whether or not `--include` is given. When more than `N` images remain, the command shall keep the first `N` in the command's existing deterministic discovery order, which is language directory and then sorted path, and shall drop the rest. The kept images shall be used for the input-tree checksum, OCR requests, text-replacement artifacts, viewers, and progress totals (FR-2026-10-26-03), so a dropped image shall not be OCR'd, replaced, listed in a viewer, or counted.

The limit shall apply equally to every selected OCR provider, including an explicitly selected `google_cloud_vision` under FR-2026-10-24-02, so the default run sends at most 25 images to that provider.

When the limit drops any image, the command shall write one line through the live display's console before the OCR stage starts. The line shall state the number kept, the number eligible, and that `--max-images 0` removes the limit and `--include` narrows the selection. The command shall write no such line when nothing is dropped. The command help shall document the option, its default, and the meaning of 0.

Because the checksum covers the kept image set (FR-2026-10-24-03), a provider output root generated with a different limit or selection shall be treated as out of date and regenerated.

### Rationale

The evaluation was written for a small corpus. A real corpus of tens of documents, each containing many images, makes the default all-images run too slow for the quick manual review the command exists to support. A modest default limit keeps a bare run quick and bounded, while an explicit option and `--include` allow a larger or narrower run.

### Notes

The limit takes the first `N` images in sorted order and does not sample across languages or documents. A bare run can therefore cover only the first language directory or document whose images fill the limit, and a reviewer who wants other languages should use `--include`. A different selection strategy may be considered separately.

Input preparation (FR-2026-08-02-05) is unchanged and still copies or extracts every selected source file. The limit reduces evaluation work, not preparation work. The new option is an evaluation-command option; FR-2026-08-02-05 still forbids preparation-specific options.

Changing the limit changes the evaluated image set and so regenerates provider output (see Description). It shall not delete files in the input root.

### Verification

Automated tests shall use synthetic source trees and fake OCR providers. They shall verify:

- the default of 25, an explicit limit, and 0 for no limit, with a synthetic tree larger than 25 images;
- rejection of negative and non-integer values before any preparation or provider call;
- that the first `N` images are kept in language-directory then sorted-path order, and that the rest are not passed to a provider, replaced, listed in a viewer, or counted in progress totals;
- the limit applied after `--include`, and with no filter;
- the dropped-image notice, including its counts, and its absence when nothing is dropped;
- that a change of limit regenerates a previously generated provider root; and
- that the limit applies to an explicitly selected `google_cloud_vision` fake provider.

Tests shall not use confidential samples or derived artifacts.

---

## FR-2026-10-26-05

| Property | Value |
|----------|-------|
| Title | Select the text-replacement provider run by OCR evaluation |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-10-26 |
| Related Requirements | FR-2026-08-02-13, FR-2026-10-24-02, FR-2026-10-26-03, SR-2026-08-24-01 |

### Description

`scripts/ocr_evaluations.py` shall no longer run every locally eligible text-replacement provider. Its text-replacement artifact stage (FR-2026-08-02-13) shall always run the `identity` and `character_mask` providers, in that order, and shall run no other provider unless one is requested.

The command shall accept an optional `--text-replacement PROVIDER` option that names one further registered text-replacement provider. The option shall accept any registered provider other than `identity` and `character_mask`, including `argos_translate`, `double_character_mask`, `half_character_mask`, and `google_cloud_translate`. The `google_cloud_translate` provider shall be selectable by this option even though it declares `LOCAL_EVALUATION_ELIGIBLE = False`, because the option is an explicit user selection. The option may be given at most once. Naming `identity` or `character_mask` shall not be an error and shall not run that provider twice. An unregistered name shall be rejected as a command-line error that names the option and lists the registered provider names, before any preparation, OCR, or provider call begins.

When the option is absent, the command shall run exactly `identity` and `character_mask`. When it is present, the command shall run `identity`, `character_mask`, and the named provider, in that order. The `LOCAL_EVALUATION_ELIGIBLE` flag shall no longer decide which providers the evaluator runs.

The text-replacement viewer, its dropdown, and its table (FR-2026-08-02-13) shall list exactly the providers that ran, in run order, with the detected-region mask option last. The initially selected option and displayed image shall be the provider named by `--text-replacement` when it is neither baseline provider, and `identity` otherwise. This amends the "first registered provider" initial selection in FR-2026-08-02-13.

The text-replacement stages of the progress display (FR-2026-10-26-03) shall be one stage per provider that runs, so the number of such stages shall be two or three.

An explicit `--text-replacement google_cloud_translate` run shall send the recognised text of the selected images, including confidential samples when selected, to Google Cloud Translation under SR-2026-08-24-01 and the provider's own data boundary. It shall send no source paths, filenames, metadata, or evaluation artifacts. The command help and developer documentation shall state that this selection sends recognised text to Google. A run that does not name `google_cloud_translate` shall not instantiate it or make a Translation API call.

The text-replacement freshness marker (FR-2026-08-02-13) shall record the ordered provider names that produced the artifacts, in addition to the input checksum. A provider root whose OCR artifacts are current but whose recorded provider set differs from the requested provider set shall be treated as having stale text-replacement artifacts. The command shall regenerate only the text-replacement artifacts for that root, reusing the saved OCR JSON, and shall not call the OCR provider. Changing or removing `--text-replacement` shall therefore never leave a viewer that lists providers which did not run. The text-replacement artifact format version shall change accordingly.

### Rationale

The set of providers shown in the evaluation was growing, and the slowest, `argos_translate`, was run and shown first on every evaluation. `identity` and `character_mask` are cheap, local and deterministic, so they make a fast, useful baseline. A translation provider can then be chosen deliberately for the run, in the same way as an OCR provider is chosen with `--ocr`.

### Notes

`google_cloud_translate` is reachable only through an explicit selection, which matches the opt-in treatment of `google_cloud_vision` in FR-2026-10-24-02. Its EU endpoint restriction and credential rules are unchanged (see `google-cloud-translation-requirements.md` and SR-2026-08-24-01).

`double_character_mask` and `half_character_mask` remain registered providers and remain available through this option, but they no longer run by default. The `LOCAL_EVALUATION_ELIGIBLE` flag stays on the plugins. It remains a plugin property read by other consumers, but this command no longer reads it.

Only one provider can be added per run. Comparing more than one additional provider needs separate runs, which regenerate the text-replacement artifacts each time and reuse the saved OCR output.

### Verification

Automated tests shall use synthetic images, a fake OCR provider, and fake text-replacement providers or the local deterministic providers. They shall verify:

- that no option runs exactly `identity` and `character_mask`, in that order, and no other registered provider is instantiated or called;
- that `--text-replacement` with a registered provider runs that provider after the two baselines, and that this includes a fake provider that declares `LOCAL_EVALUATION_ELIGIBLE = False`;
- that naming `identity` or `character_mask` runs it once;
- that an unregistered name is rejected before preparation or any provider call, with the option and the registered names in the message;
- that the viewer lists exactly the providers that ran, with the additional provider initially selected, and `identity` initially selected when none or a baseline provider was requested;
- that the progress display has one text-replacement stage per provider that ran;
- that changing the requested provider with unchanged input and a current OCR cache regenerates the text-replacement artifacts without calling the OCR provider, and that an unchanged provider set skips that regeneration;
- that `google_cloud_translate` is not instantiated unless named; and
- that the command help identifies the remote-text boundary.

Tests shall not contact Google, require credentials, or use confidential samples or derived artifacts.

---


## FR-2026-10-27-02

| Property | Value |
|----------|-------|
| Title | Skip a raster replacement whose text cannot fit its OCR region instead of failing the document |
| Owner | KrisTC |
| Status | Implemented |
| Source | User-reported failure: documents failed with "Replacement text could not fit the OCR region at a one-pixel font size" |
| Date Added | 2026-10-27 |
| Related Requirements | FR-2026-08-02-10, FR-2026-08-03-03, FR-2026-08-28-03, FR-2026-08-02-09 |

### Description

The renderer of FR-2026-08-02-10 shall keep its rule that text is rendered only at a font size that fits the OCR region, down to a minimum of one pixel. A one-pixel font is too small to read in a bitmap, so the renderer shall not draw text below that fit, clipped or otherwise.

When no font size from the largest fitting size down to one pixel lets the replacement text fit a region (for example a long translation in a very small detected region), the renderer shall skip that region's replacement instead of raising an error. A skipped region shall keep its original pixels: neither its background wipe nor any replacement text is drawn for it. The other regions of the same image shall be rendered as usual, and the image shall remain part of the output.

Skipping is best effort and is not a failure. The folder-replacement command shall not count the document as failed, shall not print a failure or warning message, and shall not change the exit status because of a skipped region. A skipped region shall not count towards the replaced OCR image-region total.

When debug output is enabled (`--debug`), the document's diagnostic sidecar (FR-2026-08-28-03) shall record one entry for each skipped region, with `kind` `skipped` and `reason_code` `bitmap_replacement_text_does_not_fit`. The entry shall carry the document-local location of the image when known, the region's index in the image's OCR order, the region's frame width and height in source-image pixels, and the replacement text's character count. It shall not record the replacement text, the OCR text, image pixels, or any other content, under the same restrictions as FR-2026-08-28-03. When debug output is disabled, nothing is recorded.

The same rule applies when `scripts/ocr_evaluations.py` and the other OCR evaluation scripts render regions: they shall skip the region and continue, with no diagnostic sidecar. Rendering that succeeds is unchanged, including the upright-layout preference for small skew.

### Rationale

One tiny or degenerate OCR region, such as an icon or a speck read as text, can fail an entire document and discard all of its other translated content, even though every other region was handled. The same happens to a legitimate region whose translation is much longer than its source: a single Japanese character or a short label commonly becomes a whole English word or phrase, which cannot fit the region that held the single character, however small the font. The project's approach to rendering is best effort: a region that cannot be rendered legibly is left as it was and reported for diagnosis, rather than drawn illegibly or allowed to stop the document.

### Notes

A skipped region leaves the source text in the image untranslated. This is accepted, because the text did not fit even at one pixel, so it was not legible when replaced. The diagnostic entry lets the owner see how often it happens and where.

Skipping includes the background wipe so that the original text is not erased with nothing to replace it. The two-pass rendering order (wipe every region, then draw every replacement) therefore needs the skip decision made before the wipe pass.

### Verification

Automated tests shall use synthetic images, polygons and text only. They shall verify that a long replacement in a tiny polygon no longer raises; that every pixel of an image whose only region is skipped is unchanged, including the wipe area; that a skipped region leaves another region in the same image rendered exactly as it would be alone; that a region which fits is rendered exactly as before; and that a synthetic folder-replacement document containing both a fitting and an unfittable region completes with an output file, no failure, zero failed files and a zero exit status. With `--debug`, they shall verify the sidecar entry, its fields, and that it contains no replacement or OCR text; without `--debug`, they shall verify that no sidecar is written.

---

## FR-2026-10-27-03

| Property | Value |
|----------|-------|
| Title | Record the original Vision words and grouping decisions in OCR extra data |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-10-27 |
| Related Requirements | FR-2026-08-01-02, FR-2026-08-27-10, FR-2026-10-24-03, SR-2026-10-24-01 |

### Description

The `google_cloud_vision` provider shall populate the optional `extra` dictionary of every `OcrText` it returns with the information needed to understand how that region was grouped from the original Vision words. The data shall be stored under the single provider-namespaced key `google_cloud_vision`, and shall be JSON-compatible so that it survives the provider-result cache (FR-2026-08-27-10) and is written unchanged into the `extra` field of the `scripts/ocr_evaluations.py` JSON artifacts.

For each region the data shall include:

- the grouping version and the numeric thresholds in effect (the same values that make up the provider's cache identity);
- `region_started_by`: the reason this region began and the measurements behind that decision. The reason shall be one of `paragraph_start`, `word_starts_line`, `previous_word_ends_line`, `direction_mismatch`, `baseline_offset`, `character_size`, `word_gap` or `background_colour` (FR-2026-10-27-04);
- `words`: the original Vision words that were combined, in reading order, each with its text exactly as normalized before joining (including detected spaces), confidence, four-point source-image polygon, and whether it started or ended a line;
- for each word, `symbols`: the word's Vision symbols in order, each with its text and, when Vision supplies a four-point box, that source-image polygon. This lets the owner compare glyph sizes that a word box, which Vision may normalise to the line height, hides;
- for every word after the first, `joined_measurements`: the measurements that caused it to be joined to the previous word, so a wrongly merged region can be compared with the thresholds.

Measurements shall be finite numbers: `direction_alignment` (cosine of the angle between reading directions), `baseline_offset_ratio` and `gap_ratio` (each relative to the larger of the two word-box heights), and `character_size_ratio` (the larger over the smaller of the line's typical word height and the next word's height). A measurement that was not evaluated for a decision (for example `character_size_ratio` when either side has no alphanumeric text, or any geometry when a break marker decided the split) shall be omitted rather than guessed.

Recording this data shall not change the grouping, the region text, confidence or polygon, and shall not add another external call. The data shall hold only normalized values derived from the existing response; it shall not include the submitted image, credentials, the raw API response, or any other data excluded by SR-2026-10-24-01. Other OCR providers need not supply it.

### Rationale

The grouped region deliberately hides the Vision words it came from, which makes a wrong merge or split hard to diagnose. `OcrText.extra` was provided for provider-specific information with no cross-provider meaning, and the evaluator already writes it. Capturing the contributing words and the measured ratios allows the owner to tune the grouping thresholds from real evaluation output instead of by trial and error.

### Notes

The extra data holds the same OCR text as the region and the words' text, so it carries the same sensitivity. It remains in the local evaluation output and, when the opt-in cache is enabled, the local source-adjacent cache. It increases JSON and cache size in proportion to the number of words.

### Verification

Automated tests shall use synthetic Vision responses and shall not contact Google or use confidential samples. They shall verify that a merged region records each original word, polygon and join measurements; that a split region records the reason and measurements for each region's start, including a character-size split; that the extra data is JSON-serializable and round-trips through the provider-result cache; and that region text, confidence and polygons are unchanged by recording it.

---

## FR-2026-10-27-04

| Property | Value |
|----------|-------|
| Title | Do not join Vision words that sit on clearly different backgrounds |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request, from OCR evaluation of a label whose two adjacent words are on different surfaces |
| Date Added | 2026-10-27 |
| Related Requirements | FR-2026-10-24-03, FR-2026-10-27-03, FR-2026-08-27-10, SR-2026-10-24-01 |

### Description

The `google_cloud_vision` grouping of FR-2026-10-24-03 shall gain one further join rule based on the source image. A word shall not be joined to the line being built when the surface behind it is clearly different from the surface behind the line's last word, even when every existing rule would join them. This is a join rule: it shall be evaluated in the same pass as the existing join rules and shall never be applied by splitting a region that was already joined.

The rule shall compare the surfaces just outside the facing ends of the two words, not the words' glyphs. For each of the previous word and the next word, it shall sample thin strips of the prepared image (named thickness) immediately above and below the word's box, restricted to a named fraction of the word's extent along the reading direction nearest the other word (a minimum span applies to very narrow boxes), measured in the line's reading-direction frame so that rotated text is handled. It shall take the median CIE Lab colour of each word's strips and compare the two as a CIE76 distance. The words shall not be joined when that distance reaches a named threshold. The rule shall be skipped, and the words judged by the existing rules alone, when no image is available, when no strip pixel lies inside the image, or when the two boxes touch or overlap along the reading direction (there is then no gap with distinct surfaces on either side). The text-region-colour estimator was evaluated for this purpose and rejected: its background confidence did not separate the reported label from legitimate joins in local evaluation output.

The rule shall run last, only for a word that the existing rules would otherwise join, so it adds no image sampling for words that are already separated. It shall not change the existing rules, the order in which they are evaluated, or the text, confidence and polygon of a region. It shall use only the image already prepared for the Vision request and no further external service, and it shall not persist or transmit the image or colour data beyond the normalized `extra` data of FR-2026-10-27-03.

When the rule is evaluated, the join measurements of FR-2026-10-27-03 shall include `background_colour_difference`. A region that begins because of this rule shall record the reason `background_colour`. The rule's threshold, strip thickness and extent fraction shall be part of the thresholds recorded in `extra`, and of the provider cache identity and evaluator artifact version, so changing any of them invalidates cached results and artifacts, and `_LINE_GROUPING_VERSION` shall be raised.

### Rationale

The word boxes and symbol boxes that Vision returns are normalised to the line height, so the character-size rule cannot see that two neighbouring words are drawn at different sizes. Such words are usually also visually separate objects, for example a label inside a shape beside text on the artwork behind it. The image shows that difference even though the OCR geometry does not.

### Notes

Initial values, calibrated against local evaluation output (four files, several hundred joins): colour-difference threshold 40.0, strip thickness 4 pixels, extent fraction 0.3 with a 4 pixel minimum span. With these values the reported label scored about 49 and every other join with a positive gap scored below about 27. The calibration margin is modest: shifting the word boxes by under one pixel moved the reported label between about 38 and 52, and a gradient background elsewhere reached about 34. If a legitimate join is split, or the label rejoins, use `background_colour_difference` in `extra` to retune the threshold.

- The rule compares only the surface behind each word, not the text colour. Two words on the same surface in different colours are still joined.
- Words whose boxes touch or overlap are not compared, so such pairs are never split by this rule.
- A word on a photograph or gradient may give an unstable surface comparison. Sampling only the facing ends limits the effect of a gradient along a long line, but it is not eliminated.

### Verification

Automated tests shall use synthetic images and synthetic Vision responses only, and shall not contact Google or use confidential samples. They shall verify that adjacent words on clearly different flat backgrounds are not joined and that the second region records the `background_colour` reason, the measurement and the threshold; that adjacent words on the same background are joined as before and record the measurement; that glyph pixels inside the boxes do not affect the comparison; that no image leaves the existing behaviour unchanged; that the rule is not evaluated for a word the earlier rules separate; that the provider passes its prepared image to the rule; and that changing the rule's threshold changes the cache identity.

---

---

## FR-2026-10-27-05

| Property | Value |
|----------|-------|
| Title | Show an interactive image overview in OCR evaluation viewers |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-10-27 |
| Related Requirements | FR-2026-08-01-03, FR-2026-08-02-02, FR-2026-08-02-08, FR-2026-08-02-13, FR-2026-10-26-02, FR-2026-10-26-05 |

### Description

Each provider's OCR evaluation viewer and text-replacement results page shall show an overview of the successful image evaluations together near the top of the page, before the individual image breakdowns. The overview shall show each successful image in its own row, with the original input beside the interactive output preview, the image identity and language, and a link to its OCR JSON result. It shall not include the text-detail tables. The existing image previews and tables in the individual breakdowns shall remain.

The OCR overview previews shall retain the detection-mask interactions specified by FR-2026-10-26-02, including region tooltips and links to the corresponding OCR table rows. The text-replacement overview previews shall retain the provider and detection-mask selection behaviour specified by FR-2026-08-02-13, FR-2026-10-26-02, and FR-2026-10-26-05, including the mask's region tooltips and links. These interactions shall also continue to work in the individual breakdowns.

The OCR and text-replacement artifact format versions shall change so existing cached viewers are regenerated with the overview, subject to the existing stage-specific freshness rules.

### Rationale

Showing the interactive previews together lets reviewers quickly inspect all processed images before examining individual region tables.

### Verification

Automated tests shall use synthetic inputs and verify that both pages show one input-and-output row and a JSON link for each successful image before the breakdowns, with no detail tables in the overview, retain the existing breakdown previews and tables, and preserve the applicable selection and mask-link behaviour in both locations. Tests shall also verify that stale viewer artifacts are regenerated under the existing cache rules.

---

## FR-2026-10-27-06

| Property | Value |
|----------|-------|
| Title | Synchronize text-replacement preview selections |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-10-27 |
| Related Requirements | FR-2026-08-02-13, FR-2026-10-26-02, FR-2026-10-26-05, FR-2026-10-27-05 |

### Description

On a provider's text-replacement results page, changing any complete-image preview dropdown shall select the same text-replacement provider or detected-region mask in every preview dropdown on that page, including those in the overview and the individual breakdowns. Every preview shall immediately show the corresponding output for its own image, without reloading the page. The dropdowns shall all reflect the shared selection.

The existing initial selection, provider ordering, and detection-mask interactions remain governed by FR-2026-10-26-02 and FR-2026-10-26-05. The text-replacement artifact format version shall change so cached replacement viewers are regenerated under the existing stage-specific freshness rules.

### Rationale

A shared selection makes it easier to compare all images under the same replacement provider or mask.

### Verification

Automated tests shall use synthetic images and verify that changing a dropdown in either the overview or a breakdown updates every dropdown and its own image's preview for each provider and the detection mask, without a page reload. Tests shall verify that mask links remain usable and that a stale text-replacement viewer is regenerated without rerunning current OCR.

---

## FR-2026-10-28-01

| Property | Value |
|----------|-------|
| Title | Navigate from a detection mask to the current viewer's region |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-10-28 |
| Related Requirements | FR-2026-08-02-13, FR-2026-10-26-02, FR-2026-10-27-05, FR-2026-10-27-06 |

### Description

When a reviewer activates a detected-region polygon in an OCR viewer mask, the viewer shall navigate to and highlight that region's OCR table row on the same page. When a reviewer activates a detected-region polygon in a text-replacement viewer mask and that region has a replacement table row, the viewer shall navigate to and highlight that row on the text-replacement page. This behaviour shall work from both overview and individual breakdown previews, including locally opened generated pages.

Replacement table rows shall have stable, page-unique region identifiers corresponding to their OCR regions. Existing mask tooltips, the synchronized preview selection, and standalone mask behaviour shall remain available. This requirement amends FR-2026-10-26-02's rule that a mask activated from the text-replacement page navigates to the OCR viewer. The OCR and text-replacement artifact freshness rules shall regenerate any artifacts made stale by the change.

The mask shall continue to show regions below confidence `0.65`, which FR-2026-08-02-13 excludes from the replacement table. Activating such a region on the text-replacement page shall do nothing; its tooltip shall remain available.

### Rationale

A mask click should take a reviewer to the relevant detail in the viewer they are using.

### Verification

Use synthetic images and OCR results to verify navigation and row highlighting from both preview locations in both viewers, including local file access, matching identifiers across images with the same filename, and retained tooltips and standalone mask behaviour. Verify that low-confidence regions remain visible with tooltips but do not navigate from the replacement page, and verify cache invalidation.
