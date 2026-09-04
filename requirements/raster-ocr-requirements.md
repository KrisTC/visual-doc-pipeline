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
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-02 |
| Related Requirements | FR-2026-08-01-03, TR-2026-08-01-01, FR-2026-09-03-01 |

### Description

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

The static OCR-evaluation viewer shall not render JSON result content inline. For each successful image evaluation, it shall show the detected text-region clips in a table with an image column and an extracted-text column. Each detected region shall occupy one row.

### Rationale

The table gives a compact, legible visual comparison of every detected region and its OCR result without overwhelming the manual-evaluation view with serialized data.

### Notes

The viewer shall retain the input and black-masked comparison images above the table. It shall retain a JSON-result link that opens in a new browser tab, but shall not render JSON content inline.

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

The project shall provide repository-root `run.ps1` and executable `run.sh` Python launcher scripts. Each launcher shall accept one or more Python arguments, run `python` with those arguments through `uv run`, and, when the repository-root `.env.local` file exists, pass that file to uv with `--env-file`. The launcher shall also support an explicit dotenv-file override for project-internal setup validation. The launcher shall preserve the Python process's exit code. Every project script that otherwise invokes `uv run python` directly shall invoke the platform-appropriate `run` launcher instead.

The setup script shall merge its candidate `PATH` entry with a temporary copy of `.env.local`, then start a fresh process through the PowerShell `run` wrapper using that temporary dotenv-file override. It shall verify that the installed PaddlePaddle distribution reports CUDA compilation support and detects at least one available CUDA device. The script shall report the detected CUDA Toolkit and cuDNN locations and the number of visible devices. It shall exit non-zero without creating `.env.local` when it did not previously exist, or modifying it when it did, if discovery, validation, dotenv loading, or Paddle CUDA-device detection fails. It shall delete the temporary candidate file in every outcome.

### Rationale

The Windows PaddlePaddle GPU wheel can be installed correctly while CUDA and cuDNN DLLs remain unavailable to its child process because their installation locations are not on `PATH`. A project-local environment file gives local development commands a repeatable way to expose those libraries and future provider settings without changing machine-wide configuration, while an end-to-end verification prevents treating a merely installed toolkit as usable GPU acceleration.

### Notes

The approved Paddle CUDA wheel registry in SR-2026-08-21-01 remains CUDA 12.6. The local runtime-discovery rule is independent of that wheel registry label: it shall select the newest valid CUDA Toolkit 12.x installation and the newest valid cuDNN 9.x Windows x86_64 runtime installation, including a standard cuDNN layout such as `C:\Program Files\NVIDIA\CUDNN\v9.<version>\bin\12.<version>\x64`. The fresh Paddle CUDA-device probe is the final compatibility check. The implementation shall identify the exact required cuDNN DLL names and compatible CUDA Toolkit locations from the pinned PaddlePaddle GPU runtime, rather than accepting an arbitrary directory that happens to contain similarly named files.

The setup script shall not download, install, update, or modify NVIDIA software, the Python environment, the uv lockfile, or the user's persistent environment variables. It may read standard Windows NVIDIA installation locations and relevant environment variables to discover candidate installations. Its diagnostics shall distinguish missing CUDA Toolkit, missing or incompatible cuDNN runtime libraries, an unavailable NVIDIA driver or GPU, and a PaddlePaddle CUDA-loading failure.

The setup script shall update the `PATH` entry atomically after the probe succeeds, so a failed run cannot leave a partially written file or overwrite user-managed settings. A malformed or duplicate managed `PATH` entry shall fail with a diagnostic rather than causing the script to rewrite unrelated content. The `PATH` entry is the setup script's only managed part of `.env.local`; users are responsible for adding, rotating, and removing any secrets. Diagnostics and automated tests shall not display secret values.

The `.env.local` file shall be added to `.gitignore` when this requirement is implemented. Automated tests shall mock installation discovery and the child-process probe; they shall not require CUDA hardware or NVIDIA software in CI. They shall verify that the setup script preserves arbitrary user-managed dotenv entries and rolls back cleanly on failure, and that each run wrapper uses `.env.local` only when it exists. The runtime probe is a required local validation on supported Windows machines, while CPU-only platforms remain valid under FR-2026-08-21-01.

---
