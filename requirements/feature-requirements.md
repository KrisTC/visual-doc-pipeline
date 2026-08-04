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
| Status | Proposed |
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
| Status | Proposed |
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

The generic OCR-provider contract test shall use a repository-owned Noto Japanese font pack rather than operating-system fonts or runtime font downloads. The pack shall include multiple font faces and its upstream version, source URL, license, and file hashes shall be recorded with the assets. The fonts shall be licensed for redistribution under the SIL Open Font License.

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
| Owner | |
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
| Owner | |
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
| Owner | |
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
| Owner | |
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
| Owner | |
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
| Owner | |
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
| Owner | |
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
| Owner | |
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
| Owner | |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-01-02, FR-2026-08-02-06, FR-2026-08-02-10, FR-2026-08-03-02, TR-2026-08-01-02 |

### Description

The project shall provide a main pipeline command that accepts an input folder and an output folder. It shall recursively discover the supported bitmap and document file types, process every eligible file, and write results beneath the output folder while preserving the input hierarchy. It shall ignore files whose type is not supported.

The command shall accept a text-replacement-provider name, defaulting to `character_mask`; an OCR-provider name, defaulting to `paddleocr`; a required source-language BCP 47 tag; and a target-language BCP 47 tag, defaulting to `en`. It shall replace every eligible visible text item using the selected text-replacement provider. Output filenames shall be passed to the selected text-replacement provider with `is_filename=True` before the output path is determined.

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

Automated tests shall use synthetic input folders and files only. They shall cover supported-file discovery, ignored files, output-filename collisions, isolated file failures, confidence gating, native OOXML and PDF text replacement, embedded Office bitmap processing, and the direct-script help entry point.

No source or output content may be sent to external services. The selected providers must be locally eligible when inputs might contain confidential information.

---

## FR-2026-08-03-04

| Property | Value |
|----------|-------|
| Title | Report folder-replacement progress |
| Owner | |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-02-03, FR-2026-08-03-03 |

### Description

The folder-replacement command shall use tqdm to render terminal progress while it processes supported input files. It shall render one progress bar at a time for each input folder that contains eligible files, labelled with that folder's path relative to the input root. The bar shall show the basename of the current source file in its postfix.

The command shall print the relative path of each source file when it starts processing it. It shall render one tqdm progress bar for that source file. A bitmap file's bar shall contain one work item. A document file's bar shall contain one native-text work item and one work item for every embedded raster bitmap. The document's bar shall advance after each work item completes, allowing a user to see progress through its embedded-image work.

### Rationale

OCR and later translation can take substantial time. Per-document progress provides visibility through long embedded-image work while retaining the command's isolated per-file failure behaviour.

### Notes

The progress bar shall show its current native-text or embedded-image work item in its postfix. Existing one-line per-file failure reporting shall remain visible without stopping later work. A failure shall close that file's bar and later files shall still be processed.

---

## FR-2026-08-03-05

| Property | Value |
|----------|-------|
| Title | Replace editable text in embedded vector graphics directly |
| Owner | |
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
| Owner | |
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
| Owner | |
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

The `preserve-basic-layout` implementation shall use a repository-owned, redistributable Noto font asset. It shall not depend on operating-system fonts or runtime font downloads. The font selection and all fitting calculations shall be deterministic for the same input, options, and font assets.

Automated tests shall use synthetic documents and fonts only. They shall verify the default mode retains source font settings, the fitting mode selects the specified Noto font and reduces or increases size as needed, and each supported document format's output remains valid.

---

## FR-2026-08-03-08

| Property | Value |
|----------|-------|
| Title | Preserve OOXML markup-compatibility namespace bindings |
| Owner | |
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
| Owner | |
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
| Owner | |
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
| Owner | |
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
| Owner | |
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
| Owner | |
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

The first renderer shall support the reported run-level typography, paragraph alignment and spacing, text-frame padding, vertical alignment, text rotation, direct bullet characters, and empty paragraphs. It shall preserve an empty paragraph's line advance, using its direct end-paragraph run font size when present, but shall not render a bullet for an empty paragraph. Underlines shall use the selected Skia typeface's underline position and thickness metrics rather than an estimated size-relative position, and an explicit false underline setting shall suppress underline rendering. It shall report direct source properties and resolve list-style defaults through the PowerPoint master, layout, text-frame, and paragraph precedence chain for the evaluator's explicit-properties artifacts. Theme resolution remains out of scope. For rendering only, an absent direct font size shall use 18 points and an absent direct font-family classification shall use sans-serif. The committed Noto Sans JP, Noto Serif JP, and Noto Sans Mono assets shall be selected, respectively, for sans-serif, serif, and fixed-width classifications. Tab layout and automatic-number and picture bullets remain out of scope. Colour, shape fill, borders, and other non-layout visual styling are out of scope for this first pass.

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
| Owner | |
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
| Owner | |
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
| Owner | |
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
| Owner | |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-04 |
| Related Requirements | FR-2026-08-03-14, FR-2026-08-03-15 |

### Description

For a PowerPoint slide-shape text frame processed with `--document-text-layout preserve-basic-layout`, the handler shall use a derived fit rectangle when the source text-frame autofit mode is explicitly `none` (PowerPoint's **Do not Autofit** setting). It shall lay out the original source paragraphs and runs at their original resolved font sizes, styles, paragraph settings, padding, writing direction, and list settings, then use the occupied source-text rectangle as the replacement fitting rectangle. The derived rectangle shall retain the source text frame's padding and shall not exceed the original shape rectangle.

The handler shall use the original shape or cell rectangle directly for every other bounded-text case, including `text-to-fit-shape`, `shape-to-fit-text`, inherited or unspecified autofit, table cells, and non-PowerPoint adapters. It shall not derive replacement bounds from original text in those cases.

The measurement shall remain deterministic and use the same committed Noto face selected for the source run's broad family classification when the source font itself is unavailable. It shall not use operating-system font discovery.

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
| Owner | |
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
| Owner | |
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
| Owner | |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-04 |
| Related Requirements | FR-2026-08-03-14, FR-2026-08-03-15, FR-2026-08-04-05 |

### Description

The folder-replacement command shall provide a PPTX layout mode named `preserve-basic-layout-source-font`. It shall perform the same source-bound selection, source-width/natural-height handling for explicit `noAutofit`, paragraph formatting, fitted font-size calculation, and explicit autofit disabling as `preserve-basic-layout`.

For every replacement run with a resolved source typeface reference, this mode shall retain that reference in the output PPTX while applying the fitted size and other explicit run properties. It shall not replace that reference with Noto merely because fitting is enabled. A run without a resolved source typeface reference shall use the existing Noto fallback.

Fitting measurement shall remain deterministic: it shall use the committed Noto face chosen by the source run's broad family classification to calculate the scale. The mode does not guarantee metric identity with a source font that is unavailable on the viewing machine. It shall neither discover operating-system fonts nor embed fonts in this initial implementation.

The existing `preserve-basic-layout` mode shall retain its current explicit-Noto output behaviour, so users can compare deterministic-Noto and source-font best-effort output without changing existing commands.

### Rationale

Preserving a presentation's source typeface can retain important visual design even when font metrics are only approximately known. A separate mode makes this trade-off explicit and preserves the current deterministic Noto result as a fallback and comparison point.

### Notes

Automated tests shall use synthetic runs with a resolved non-Noto source typeface reference and with no source reference. They shall verify the new mode writes the source reference for the former, uses Noto for the latter, and retains the existing fitting and autofit behaviour.

---

## FR-2026-08-04-02

| Property | Value |
|----------|-------|
| Title | Select an empty OCR provider for local pipeline testing |
| Owner | |
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
| Owner | |
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
| Owner | |
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
| Owner | |
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
| Owner | |
| Status | Implemented |
| Source | User request and implementation review |
| Date Added | 2026-08-04 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-03-07, FR-2026-08-03-14, FR-2026-08-04-07 |

### Description

This requirement defines the implemented PDF-specific eligibility, encoding, appearance, and fallback rules that the generic bounded-text requirements leave open.

For a PDF FreeText annotation or editable AcroForm text field with a finite `/Rect`, `preserve-basic-layout` shall use the shared bounded-text layout core. It shall write the replacement value, explicit fitted size, an embedded repository-owned static Noto face, and a clipped normal appearance stream that renders the replacement within that rectangle. It shall preserve the annotation or field's non-text semantics and surrounding page content. A field or annotation without a safe finite rectangle shall use `preserve-source-formatting` replacement rather than a bounded fit.

PDF page-content and Form XObject text-showing operations do not define a reliable text rectangle. They shall continue to receive native text replacement, but shall not opt into paragraph fitting, box resizing, or inferred bounding boxes. An unchanged replacement shall retain its original encoded text operand and active font selection.

When changing a page-content or Form-XObject text operand, the adapter shall decode composite Type0 text through its `/ToUnicode` CMap using the CMap's actual character-code widths. It shall not assume that `/Identity-H` implies two-byte character codes. A `/ToUnicode` map is decoding evidence only and shall not be reversed to select a CID for replacement text. If the active Type0 font, or a subsetted simple font, cannot safely encode the replacement, the adapter shall select the existing ASCII-safe fallback used for masking and redaction.

When a simple source font has an available character map, `preserve-basic-layout-source-font` may retain it only when that map demonstrates support for every replacement character. A map that lacks a replacement character shall select the ASCII-safe fallback. This mode remains best effort for unbounded PDF page content; it does not promise source-font metric equivalence or layout fitting.

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
| Owner | |
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

## FR-2026-08-04-11

| Property | Value |
|----------|-------|
| Title | Replace editable SmartArt and WordArt text in PPTX files |
| Owner | |
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
