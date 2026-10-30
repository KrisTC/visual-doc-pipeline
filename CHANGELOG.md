# Changelog

## [0.4.0](https://github.com/KrisTC/visual-doc-pipeline/compare/v0.3.0...v0.4.0) (2026-10-30)

### Enhanced EMF translation

Translation of Enhanced Metafile (EMF) graphics now fits compatible text
fragments together as visual lines, including EMF+ playback. This reduces
uneven text sizes and gaps, while retaining colour emphasis and handling
moderate differences in font size. Fitted GDI fonts are also made available
during EMF+ playback. Windows development runs can produce side-by-side
previews for GDI and GDI+ review. See [format support](docs/folder-replacer-format-support.md)
and [Windows EMF previews](docs/development.md#windows-emf-previews).

### Preserve OCR-detected logos

Use `--preserve-logo-text` to keep specified OCR-detected logo text in its
original image, preserving distinctive lettering instead of replacing it.
Matching is case-sensitive and applies to complete OCR results after trimming
surrounding spaces; repeat the option for different names or case variants.
OCR errors and overlapping replacement regions can still affect a logo. See
[container usage](docs/container-usage.md#preserve-logo-text) and
[development configuration](docs/development.md).

### Bug fix: GPU container certificate authorities

The GPU image now includes public certificate authority trust, fixing HTTPS
failures during first-use font downloads. Both CPU and GPU images include the
public CA certificates. See the [container guide](docs/container-usage.md#build-images)
for the trust and font-download smoke check.

### Security Requirements

Requirements for Dependency, credential, remote-data, or local-persistence security.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| SR-2026-10-28-01 | Support operator-provided trust for TLS interception | Proposed | KrisTC |

### Technical Requirements

Requirements for Tools, dependencies, test runners, typing, or shared implementation structure.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| TR-2026-10-28-01 | Provide public CA trust in CPU and GPU container images | Implemented | KrisTC |
| TR-2026-10-30-01 | Automatic worker count for selected tests | Implemented | KrisTC |
| TR-2026-10-30-02 | Distribute OCR provider contract tests | Implemented | KrisTC |

### General Requirements

Requirements for Shared pipeline, CLI, layout, cache, diagnostics, or development scenarios.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-10-28-02 | Generate Windows EMF comparison previews for development scenarios | Implemented | KrisTC |
| FR-2026-10-29-04 | Preserve specified logo text detected by OCR | Implemented | KrisTC |
| FR-2026-10-29-05 | Configure preserved OCR logo text for development scenarios | Implemented | KrisTC |

### Vector Requirements

Requirements for SVG, EMF, WMF, or other vector graphics.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-10-28-03 | Make fitted GDI fonts available during EMF+ playback | Implemented | KrisTC |
| FR-2026-10-28-04 | Trace EMF fitted-layout decisions in debug sidecars | Implemented | KrisTC |
| FR-2026-10-28-05 | Bound EMF text expansion by visible shapes | Proposed | KrisTC |
| FR-2026-10-29-01 | Fit same-font and same-size EMF and EMF+ fragments as visual lines | Implemented | KrisTC |
| FR-2026-10-29-02 | Preserve colour-emphasis spans in fitted EMF visual lines | Implemented | KrisTC |
| FR-2026-10-29-03 | Join EMF visual-line fragments whose font sizes differ moderately | Implemented | KrisTC |

### Requirement details

#### Security Requirements

Requirements for Dependency, credential, remote-data, or local-persistence security.

##### SR-2026-10-28-01 — Support operator-provided trust for TLS interception [Proposed]

###### Rationale

An intercepting proxy presents certificates issued by an organisation's CA,
which is not necessarily in a public trust store. Trusting that CA permits the
proxy to inspect traffic within the selected scope; if translation traffic is
included, this can include document text. The operator must understand and
authorize that trust boundary.

#### Technical Requirements

Requirements for Tools, dependencies, test runners, typing, or shared implementation structure.

##### TR-2026-10-28-01 — Provide public CA trust in CPU and GPU container images [Implemented]

###### Rationale

The GPU image's Python runtime was observed to have no usable default CA
trust store, causing first-use font downloads to fail before processing.
Supplying public trust roots to both variants makes the documented bootstrap
usable without an operator-provided CA on ordinary public-CA networks.

##### TR-2026-10-30-01 — Automatic worker count for selected tests [Implemented]

###### Rationale

Focused runs benefit from avoiding worker startup when only a few test items are selected, while the existing full-suite default remains appropriate for larger runs.

##### TR-2026-10-30-02 — Distribute OCR provider contract tests [Implemented]

###### Rationale

One top-level test currently runs the entire OCR matrix on a single worker. Grouping it allows parallel scheduling while keeping individual case reporting and automatic plugin discovery. Concurrent workers may load multiple OCR models and increase memory or GPU use; the benefit and resource cost should be measured before adopting the change.

#### General Requirements

Requirements for Shared pipeline, CLI, layout, cache, diagnostics, or development scenarios.

##### FR-2026-10-28-02 — Generate Windows EMF comparison previews for development scenarios [Implemented]

###### Rationale

EMF viewing and comparison are slow and vary across applications. A
side-by-side preview next to each development output makes it quicker to
inspect the replacement, while separate GDI and GDI+ playback exposes
differences between a dual metafile's viewing paths. A separate command also
allows existing development outputs to be reviewed without rerunning
replacement.

##### FR-2026-10-29-04 — Preserve specified logo text detected by OCR [Implemented]

###### Rationale

Text-based company logos can use distinctive fonts that would be lost if detected text were replaced and rendered in a substitute font.

##### FR-2026-10-29-05 — Configure preserved OCR logo text for development scenarios [Implemented]

###### Rationale

The development command is intended for rapid iteration with a consistent configuration across scenarios.

#### Vector Requirements

Requirements for SVG, EMF, WMF, or other vector graphics.

##### FR-2026-10-28-03 — Make fitted GDI fonts available during EMF+ playback [Implemented]

###### Rationale

An EMF+ viewer can play GDI records only inside selected device-context
intervals. A font created outside such an interval can be unavailable when a
later text record selects it, leaving the replacement at an unintended size.

##### FR-2026-10-28-04 — Trace EMF fitted-layout decisions in debug sidecars [Implemented]

###### Rationale

Successful fit decisions are not issue entries, so an otherwise empty sidecar
cannot explain how bounds, grouping, font selection, and nested playback
affected a visible result. A local trace makes those decisions inspectable in
subsequent reviews without a separate investigation script.

##### FR-2026-10-28-05 — Bound EMF text expansion by visible shapes [Proposed]

###### Rationale

A text record's occupied bounds can be narrower than the available area.
Expansion improves readability, but a corridor limited only by other text
and selected line records can cross a visible enclosing shape or another
graphic. Shape-aware limits retain useful expansion without assuming that
unresolved geometry is empty.

##### FR-2026-10-29-01 — Fit same-font and same-size EMF and EMF+ fragments as visual lines [Implemented]

###### Rationale

Independently fitting fragments of one visual line gives translated fragments
different sizes and leaves gaps from the original placement. Fitting the
whole line shares the original line's available width. EMF+ playback matters
independently of the GDI stream because viewers may display only that stream.

##### FR-2026-10-29-02 — Preserve colour-emphasis spans in fitted EMF visual lines [Implemented]

###### Rationale

Colour often emphasises a phrase rather than marking an independent label.
Translating colour spans separately follows the PDF policy and preserves their
colour without guessing which translated words correspond to source words.
Fitting the combined result avoids fragment-by-fragment size changes and
excessive gaps.

##### FR-2026-10-29-03 — Join EMF visual-line fragments whose font sizes differ moderately [Implemented]

###### Rationale

Presentation text often sets bracketed or annotated phrases slightly smaller
on the same baseline. Splitting those lines leaves the translated fragments
fitted independently, with uneven sizes and large gaps. A 70% bound joins the
common three-to-four size relationship while keeping clearly separate
captions and labels apart.

## [0.3.0](https://github.com/KrisTC/visual-doc-pipeline/compare/v0.2.0...v0.3.0) (2026-10-28)

### Google Cloud Vision OCR

This release adds `google_cloud_vision` as an OCR provider for extracting text
from images. Vision detects languages in the image and groups words into text
regions suitable for replacement, with grouping decisions available in OCR
result data. The existing `paddleocr` provider remains the default.

Select `--ocr google_cloud_vision` in folder processing or OCR evaluation to use
it. This sends image content to Google Cloud Vision's EU endpoint; automatic OCR
evaluations do not select Vision. See [Google Cloud setup](docs/google-cloud-setup.md).

### Supporting development and improvements

The work supporting Vision OCR also improved evaluation, review, and reliability:

- OCR evaluation pages now show image overviews, interactive region masks and
  synchronized replacement previews. Runs can be narrowed with `--include`,
  default to 25 images, and support `--max-images 0` for no limit. They run the
  `identity` and `character_mask` replacement providers by default and accept
  an additional provider through `--text-replacement`. Explicitly selecting
  Google Cloud Translation sends recognised text to Google Cloud Translation.
- Raster replacement accounts for the page behind transparent images. Regions
  whose replacement text cannot fit retain their original pixels instead of
  failing the document.
- A Windows review tool opens translated PowerPoint, Word and Excel files beside
  their sources. Folder processing skips Office temporary owner files and makes
  translated output filenames valid on Windows.
- The test runner supports parallel execution, forwarded arguments and a fast
  subset. Serial execution remains available. See the
  [development documentation](docs/development.md).

### Known issue

EMF images are not yet processed as well as intended. This is particularly
noticeable in PowerPoint presentations containing embedded EMF images. Improving
EMF processing is targeted for the next release.

### Security Requirements

Requirements for Dependency, credential, remote-data, or local-persistence security.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| SR-2026-10-24-01 | Google Cloud Vision credentials and remote-image boundary | Implemented | KrisTC |

### Technical Requirements

Requirements for Tools, dependencies, test runners, typing, or shared implementation structure.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| TR-2026-10-27-01 | Command-line argument tests run in process | Implemented | KrisTC |
| TR-2026-10-27-02 | Parallel test execution by default | Implemented | KrisTC |
| TR-2026-10-27-03 | Test runners forward arguments and support a fast subset | Implemented | KrisTC |

### General Requirements

Requirements for Shared pipeline, CLI, layout, cache, diagnostics, or development scenarios.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-10-26-02 | Skip Office temporary owner files in folder replacement and OCR evaluation input preparation | Implemented | KrisTC |
| FR-2026-10-27-01 | Make translated output filenames valid on the output filesystem | Implemented | KrisTC |
| FR-2026-10-27-05 | Review translated PowerPoint output against its source | Implemented | KrisTC |
| FR-2026-10-27-06 | Review translated Word and Excel output against its source | Implemented | KrisTC |

### Raster Ocr Requirements

Requirements for Raster images, OCR providers, OCR evaluation, or replacement-image rendering.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-10-24-01 | Add Google Cloud Vision OCR provider | Implemented | KrisTC |
| FR-2026-10-24-02 | Manually evaluate Google Cloud Vision OCR | Implemented | KrisTC |
| FR-2026-10-24-03 | Targeted OCR evaluation and Vision text grouping | Implemented | KrisTC |
| FR-2026-10-26-01 | Estimate and render raster replacement text against an assumed page colour | Implemented | KrisTC |
| FR-2026-10-26-02 | Replace the masked bitmap with a linked SVG detection mask | Implemented | KrisTC |
| FR-2026-10-26-03 | Report every stage of OCR evaluation in its progress display | Implemented | KrisTC |
| FR-2026-10-26-04 | Limit the number of images in an OCR-evaluation run | Implemented | KrisTC |
| FR-2026-10-26-05 | Select the text-replacement provider run by OCR evaluation | Implemented | KrisTC |
| FR-2026-10-27-02 | Skip a raster replacement whose text cannot fit its OCR region instead of failing the document | Implemented | KrisTC |
| FR-2026-10-27-03 | Record the original Vision words and grouping decisions in OCR extra data | Implemented | KrisTC |
| FR-2026-10-27-04 | Do not join Vision words that sit on clearly different backgrounds | Implemented | KrisTC |
| FR-2026-10-27-05 | Show an interactive image overview in OCR evaluation viewers | Implemented | KrisTC |
| FR-2026-10-27-06 | Synchronize text-replacement preview selections | Implemented | KrisTC |
| FR-2026-10-28-01 | Navigate from a detection mask to the current viewer's region | Implemented | KrisTC |

### Requirement details

#### Security Requirements

Requirements for Dependency, credential, remote-data, or local-persistence security.

##### SR-2026-10-24-01 — Google Cloud Vision credentials and remote-image boundary [Implemented]

###### Rationale

Cloud OCR introduces an external image-processing boundary. Reusing the established Google credential configuration and requiring the EU endpoint makes the data flow and regional processing choice explicit while limiting what the provider sends and records.

#### Technical Requirements

Requirements for Tools, dependencies, test runners, typing, or shared implementation structure.

##### TR-2026-10-27-01 — Command-line argument tests run in process [Implemented]

###### Rationale

Each subprocess re-imports the full folder-replacement pipeline (about 1.8 s per start, measured on the development machine), so one test with several argument-error cases cost over 13 s. Argument handling is Python logic that does not need a new interpreter; only the direct-script launch path does.

##### TR-2026-10-27-02 — Parallel test execution by default [Implemented]

###### Rationale

The test suite is dominated by independent, CPU-bound document and image processing. Parallel execution by default reduces wall time on multi-core machines without changing the tests, which is the purpose of a fast edit-test loop. A serial mode remains available so that a failure can be reproduced without concurrency as a factor.

##### TR-2026-10-27-03 — Test runners forward arguments and support a fast subset [Implemented]

###### Rationale

The runners currently cannot pass `--durations`, `-k`, or similar options, so a developer must call the wrapper by hand to profile or filter. A deliberately skip-visible fast subset shortens the edit-test loop without silently reducing what the suite verifies for a merge.

#### General Requirements

Requirements for Shared pipeline, CLI, layout, cache, diagnostics, or development scenarios.

##### FR-2026-10-26-02 — Skip Office temporary owner files in folder replacement and OCR evaluation input preparation [Implemented]

###### Rationale

An owner file has a document extension but holds only a short user and machine name, not an OOXML package, so processing it always fails. In folder replacement it makes a run exit non-zero, and in OCR evaluation input preparation it aborts the whole run. Such files appear whenever a source folder is copied while a document is open.

##### FR-2026-10-27-01 — Make translated output filenames valid on the output filesystem [Implemented]

###### Rationale

The output name is the translation of the input file's name (FR-2026-08-03-03). The input name is always valid on the source filesystem, but the translated name is new text that nothing has validated against Windows rules. A translator may introduce a forbidden character that the source name did not contain: it may turn Japanese brackets or other punctuation into an English phrase with a colon, add a question mark or quotation marks, render a full-width punctuation mark as its ASCII form, or end a name with a full stop. Full-width forms such as `：` and `？` are legal in a Windows filename, but their ASCII equivalents are not. In a failed run the source name held no ASCII colon, and the translated name did.

A single such name currently fails the whole document after all of its translation work has been done, because the error appears only at the final rename. The failure depends on the provider's wording, so it is not predictable from the input and can appear for any provider.

##### FR-2026-10-27-05 — Review translated PowerPoint output against its source [Implemented]

###### Rationale

Reviewing a development run requires opening each translated deck next to its source. Listing the revision's decks and printing the review command removes manual path entry between runs.

##### FR-2026-10-27-06 — Review translated Word and Excel output against its source [Implemented]

###### Rationale

Translated Word and Excel output is reviewed the same way as PowerPoint output. Using the same workflow keeps the review step consistent across the document types the pipeline produces.

#### Raster Ocr Requirements

Requirements for Raster images, OCR providers, OCR evaluation, or replacement-image rendering.

##### FR-2026-10-24-01 — Add Google Cloud Vision OCR provider [Implemented]

###### Rationale

Cloud Vision provides dense document OCR through a selectable managed provider while retaining the pipeline's normalized OCR result model and PaddleOCR default.
Google Vision OCR provider may be more useful when a GPU is not available as the CPU version of PaddleOCR can be very slow.

##### FR-2026-10-24-02 — Manually evaluate Google Cloud Vision OCR [Implemented]

###### Rationale

An opt-in evaluator run lets the developer compare Cloud Vision OCR against the local visual corpus while preventing a default evaluation from transmitting images.

##### FR-2026-10-24-03 — Targeted OCR evaluation and Vision text grouping [Implemented]

###### Rationale

The evaluation corpus is large, and an explicit source-path selection lets the developer assess a document or small group without running OCR on unrelated images. Matching source paths lets preparation skip unrelated document extraction as well as provider calls. Word regions are too small for useful translation, while Vision paragraph regions can combine text from visually separate lines and lose bullet or indentation structure. Text with a distinct visual size on the same line may be a separate label and needs its own replacement bounds.

##### FR-2026-10-26-01 — Estimate and render raster replacement text against an assumed page colour [Implemented]

###### Rationale

A transparent PNG in a document can look correct on the page while its stored pixels mislead colour estimation. Antialiasing pixels with low alpha and unrelated hidden RGB can form the apparent text colour, and replacement text drawn with that colour is nearly invisible on any page. The page colour supplies the missing context in one place, keeps the source's transparency in the output, and guarantees legible opaque text.

##### FR-2026-10-26-02 — Replace the masked bitmap with a linked SVG detection mask [Implemented]

###### Rationale

A vector mask keeps the original bitmap pixels unmodified, avoids a second raster copy, and gives every detection a hyperlink target. A reviewer can click a masked region and land on its OCR table row instead of matching a position by eye.

##### FR-2026-10-26-03 — Report every stage of OCR evaluation in its progress display [Implemented]

###### Rationale

Text replacement is repeated for every text-replacement provider and can take as long as OCR on a large corpus. A language-folder progress row says nothing about which of these stages is active. Showing one overall unit per stage and a per-file current row for that stage lets a reviewer see which condition is running and how far through the corpus it is.

Removing a large provider output tree before regeneration can take about a minute, and with no output the command appeared to hang. Input preparation, discovery, and checksumming can be equally slow on a large corpus. Naming these phases lets a reviewer tell that the command is busy rather than stuck.

##### FR-2026-10-26-04 — Limit the number of images in an OCR-evaluation run [Implemented]

###### Rationale

The evaluation was written for a small corpus. A real corpus of tens of documents, each containing many images, makes the default all-images run too slow for the quick manual review the command exists to support. A modest default limit keeps a bare run quick and bounded, while an explicit option and `--include` allow a larger or narrower run.

##### FR-2026-10-26-05 — Select the text-replacement provider run by OCR evaluation [Implemented]

###### Rationale

The set of providers shown in the evaluation was growing, and the slowest, `argos_translate`, was run and shown first on every evaluation. `identity` and `character_mask` are cheap, local and deterministic, so they make a fast, useful baseline. A translation provider can then be chosen deliberately for the run, in the same way as an OCR provider is chosen with `--ocr`.

##### FR-2026-10-27-02 — Skip a raster replacement whose text cannot fit its OCR region instead of failing the document [Implemented]

###### Rationale

One tiny or degenerate OCR region, such as an icon or a speck read as text, can fail an entire document and discard all of its other translated content, even though every other region was handled. The same happens to a legitimate region whose translation is much longer than its source: a single Japanese character or a short label commonly becomes a whole English word or phrase, which cannot fit the region that held the single character, however small the font. The project's approach to rendering is best effort: a region that cannot be rendered legibly is left as it was and reported for diagnosis, rather than drawn illegibly or allowed to stop the document.

##### FR-2026-10-27-03 — Record the original Vision words and grouping decisions in OCR extra data [Implemented]

###### Rationale

The grouped region deliberately hides the Vision words it came from, which makes a wrong merge or split hard to diagnose. `OcrText.extra` was provided for provider-specific information with no cross-provider meaning, and the evaluator already writes it. Capturing the contributing words and the measured ratios allows the owner to tune the grouping thresholds from real evaluation output instead of by trial and error.

##### FR-2026-10-27-04 — Do not join Vision words that sit on clearly different backgrounds [Implemented]

###### Rationale

The word boxes and symbol boxes that Vision returns are normalised to the line height, so the character-size rule cannot see that two neighbouring words are drawn at different sizes. Such words are usually also visually separate objects, for example a label inside a shape beside text on the artwork behind it. The image shows that difference even though the OCR geometry does not.

##### FR-2026-10-27-05 — Show an interactive image overview in OCR evaluation viewers [Implemented]

###### Rationale

Showing the interactive previews together lets reviewers quickly inspect all processed images before examining individual region tables.

##### FR-2026-10-27-06 — Synchronize text-replacement preview selections [Implemented]

###### Rationale

A shared selection makes it easier to compare all images under the same replacement provider or mask.

##### FR-2026-10-28-01 — Navigate from a detection mask to the current viewer's region [Implemented]

###### Rationale

A mask click should take a reviewer to the relevant detail in the viewer they are using.

## [0.2.0](https://github.com/KrisTC/visual-doc-pipeline/compare/v0.1.0...v0.2.0) (2026-10-23)

**Headline: massively faster translation.** Previously, every string in a document
was translated in its own Google Cloud Translation request. A large document
therefore made thousands of sequential calls, each costing about 0.1 s of
round-trip latency however short the text was, so translation dominated the
processing time. Each file is now processed in three steps: plan, translate, and
apply. The plan step collects every text that needs translating, including text
in embedded documents. The translate step removes duplicates, packs the texts
into batches of about 5,000 characters, and sends each batch as a single request.
The apply step then fits and writes the results exactly as before. In a benchmark
against the real service with 1,000 synthetic strings, batched requests
**translated 90 to 320 times faster** than single-text calls, and translating a
large document drops from about 15 minutes to  ~5 seconds. OCR becomes the main 
remaining cost, and it is still performed once per image.  

What this means in practice:

- **Same results, same caches.** Cache entries remain per text, so existing
  caches stay valid and a partly cached document sends only its new texts. Texts
  translated in a batch can occasionally be worded slightly differently from the
  same text translated alone (8 of 100 in the benchmark, with the same meaning);
  each cached text stays stable.
- **Safe batching.** Batches stay within Google's limits. An embedded document's
  texts are never mixed into its parent's batches. A failed batch is split to
  isolate the offending text, so one bad string does not fail a document.
- **Quota-aware.** Reaching Google's per-minute quota now slows a run down
  with exponential backoff instead of failing it, and the request deadline rises
  from 10 s to 300 s because large requests need longer. A daily-quota error still
  fails immediately. Batch size, deadline and backoff can be tuned with
  `GOOGLE_CLOUD_TRANSLATION_*` environment variables, and
  `GOOGLE_CLOUD_TRANSLATION_BATCH_MAX_ITEMS=1` reproduces one-text requests.
- **Visible progress.** Progress shows the plan, translate, and apply steps for
  each source, and `progress.json` now reports the current step, the failure
  reason, and an ETA status. Cache metrics report per-provider run and request
  counts, so they reflect real batch requests.
- **Breaking change for provider plugin authors.** The text-replacement provider
  contract now has a single `replace` method that takes a batch of texts and
  returns a batch of results. A provider that handles one text at a time can use
  `replace_each`. Built-in providers are already migrated. See
  [Text-replacement provider API](docs/text-replacement-provider-api.md).

Also in this release: PowerPoint text in layouts, masters, charts, and comments
is translated in every fitted layout mode. EMF and WMF graphics are identified by
content rather than file extension. EMF+ text and image objects (embedded bitmaps
and nested metafiles) are translated. SVG and WMF text without a clip rectangle
is fitted to its measured source extent. A tab in fitted replacement text no
longer fails a file. Design and measurements are in the
[batch text replacement plan](docs/batch-text-replacement-plan.md).

### Security Requirements

Requirements for Dependency, credential, remote-data, or local-persistence security.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| SR-2026-10-21-01 | Permit explicit read-only aggregate inspection of local provider caches | Implemented | KrisTC |
| SR-2026-10-22-01 | Keep batched translation within the existing remote-data boundary | Implemented | KrisTC |

### Technical Requirements

Requirements for Tools, dependencies, test runners, typing, or shared implementation structure.

#### Updated

| ID | Title | Status | Owner |
|---|---|---|---|
| TR-2026-09-10-01 | Validate pull requests with GitHub Actions continuous integration | Implemented | KrisTC |

### General Requirements

Requirements for Shared pipeline, CLI, layout, cache, diagnostics, or development scenarios.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-10-21-01 | Report per-provider OCR and text-replacement cache and run metrics | Implemented | KrisTC |
| FR-2026-10-22-04 | Process each source as plan, translate, and apply steps with a shared translation engine | Implemented | KrisTC |
| FR-2026-10-22-05 | Process nested documents recursively with the same plan and apply functions | Implemented | KrisTC |
| FR-2026-10-22-06 | Cache batched text-replacement results per text and report request metrics | Implemented | KrisTC |
| FR-2026-10-22-07 | Report plan, translate, and apply progress for each source | Implemented | KrisTC |
| FR-2026-10-22-11 | Fit text to its known bounds, otherwise to its measured source extent, and always translate | Implemented | KrisTC |
| FR-2026-10-23-01 | Treat a tab in fitted replacement text as whitespace | Implemented | KrisTC |
| FR-2026-10-23-02 | Report the current step, failure reason and ETA state in folder-replacement progress.json | Implemented | KrisTC |

#### Updated

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-08-27-04 | Bootstrap optional font packs and PaddleOCR models before processing | Implemented | KrisTC |

### Text Replacement Requirements

Requirements for Text-replacement provider contract or deterministic replacement-provider test support.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-10-22-01 | Replace a batch of texts with one provider call | Implemented | KrisTC |

### Google Cloud Translation Requirements

Requirements for Google Cloud Translation provider or its local configuration.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-10-22-02 | Translate a batch of texts in one Google Cloud Translation request | Implemented | KrisTC |
| FR-2026-10-22-03 | Use a long request deadline and back off on Google Cloud Translation quota limits | Implemented | KrisTC |

### Pdf Requirements

Requirements for PDF.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-10-23-02 | Plan PDF form-field appearance-stream text to avoid a plan miss | Deferred | KrisTC |

### Powerpoint Requirements

Requirements for PowerPoint / PPTX.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-10-22-08 | Translate all PowerPoint text parts in every document-text layout mode | Implemented | KrisTC |

### Vector Requirements

Requirements for SVG, EMF, WMF, or other vector graphics.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-10-22-09 | Identify EMF and WMF graphics by content, not file extension | Implemented | KrisTC |
| FR-2026-10-22-10 | Translate EMF+ text and keep the EMF+ stream valid | Implemented | KrisTC |
| FR-2026-10-22-12 | Fit SVG text that has no clip rectangle to its measured source extent | Implemented | KrisTC |
| FR-2026-10-22-13 | Fit WMF text that has no clip rectangle to its measured source extent | Implemented | KrisTC |
| FR-2026-10-22-14 | Translate EMF+ image objects: embedded bitmaps and nested metafiles | Implemented | KrisTC |

### Requirement details

#### Security Requirements

Requirements for Dependency, credential, remote-data, or local-persistence security.

##### SR-2026-10-21-01 — Permit explicit read-only aggregate inspection of local provider caches [Implemented]

###### Rationale

Reading existing metrics is distinct from enabling provider-result caching.

##### SR-2026-10-22-01 — Keep batched translation within the existing remote-data boundary [Implemented]

###### Rationale

Batching changes how many texts travel in one request, not which data may leave the machine. The synchronous operation avoids a Cloud Storage dependency that would store source text in an additional remote location, and content-free diagnostics keep the added request, retry and progress detail from leaking document content.

#### Technical Requirements

Requirements for Tools, dependencies, test runners, typing, or shared implementation structure.

##### TR-2026-09-10-01 — Validate pull requests with GitHub Actions continuous integration [Implemented]

###### Rationale

Pull-request CI gives contributors and reviewers repeatable evidence that a
change preserves the dependency controls, Python quality gates, test suite,
and both distributable container definitions before it is merged.  Keeping
untrusted pull-request code in a read-only, secret-free workflow limits the
effect of contributions from forks.  Downloading the verified optional fonts
before the tests keeps the fitted-layout fallback path under test; without them
the fallback is silently skipped on the runner and tests pass without exercising it.

#### General Requirements

Requirements for Shared pipeline, CLI, layout, cache, diagnostics, or development scenarios.

##### FR-2026-10-21-01 — Report per-provider OCR and text-replacement cache and run metrics [Implemented]

###### Rationale

Per-provider metrics make expensive provider work visible without exposing
cached content. Timing highlights whether translation or OCR dominates a
document's processing time and whether a batch translation interface merits
investigation. Backfilling on cache hits lets existing sidecars gradually
gain useful attribution without invalidating or recomputing cached results;
historical provider latency cannot be reconstructed from a cache hit.

##### FR-2026-10-22-04 — Process each source as plan, translate, and apply steps with a shared translation engine [Implemented]

###### Rationale

Translating each string as it is reached makes one remote request per string, because fitting, bullet mapping and rendering need the translated text. Measured documents needed about 6,900 requests (Word), 3,400 (PDF), 1,800 (PowerPoint) and 220 (Excel), about 0.11 to 0.15 seconds each. Repeating a handler with unchanged text to collect its strings would also repeat OCR, fitting and rendering, and unchanged text does not skip that work. Splitting each handler into a source-only plan step and a translation-dependent apply step lets one engine batch every unit's texts, about 31 requests and an estimated 5 seconds instead of about 14 minutes for the largest measured document, without repeating expensive work or changing output.

##### FR-2026-10-22-05 — Process nested documents recursively with the same plan and apply functions [Implemented]

###### Rationale

Embedded documents come from untrusted input, so recursion needs a bound: 6 levels covers realistic nesting such as a Word document containing a workbook that contains images. One implementation per type keeps behaviour, fallbacks and diagnostics identical between a root file and the same type nested in another document, and keeps each format's logic in one place. Treating each nested document as its own unit lets a 75,000-row embedded workbook be batched on its own instead of being mixed into its parent's batches.

##### FR-2026-10-22-06 — Cache batched text-replacement results per text and report request metrics [Implemented]

###### Rationale

Per-text keys mean a partly cached document sends only its new texts, existing caches stay valid, and batch composition never changes a result. Cached results are read in one transaction instead of thousands of round trips. Recording `batch_items` and the request count lets cache metrics report real request counts: the measured per-string durations (0.11 to 0.15 seconds on average) are shares of batched requests and would otherwise be misread as the latency of separate calls.

##### FR-2026-10-22-07 — Report plan, translate, and apply progress for each source [Implemented]

###### Rationale

Once strings are translated in batches, the number of requests is unknown until planning finishes, so a request count can no longer be the unit of progress. Planning is also long-running work: OCR alone took 33 to 73 seconds in measured Word, PDF and PowerPoint documents. Showing each step keeps OCR, translation and rendering visible, and clamping avoids a bar that moves backwards when the batch total becomes known.

##### FR-2026-10-22-11 — Fit text to its known bounds, otherwise to its measured source extent, and always translate [Implemented]

###### Rationale

Readers are better served by a text that is shrunk to fit and may overflow a little than by one that is not fitted or not translated. A measurement of the source estimates what the source application already knows; when the source face is not installed the Noto face is usually wider, so a measurement must not veto a fit.

##### FR-2026-10-23-01 — Treat a tab in fitted replacement text as whitespace [Implemented]

###### Rationale

A tab is whitespace that translators and the `character_mask` provider both return unchanged, but the approved Noto faces have no glyph for it. Without this rule, a PowerPoint slide whose text contains a tab failed its whole file with "No approved portable replacement font covers the text" even though every visible character was covered. Two of the 34 files in a local evaluation set failed this way.

##### FR-2026-10-23-02 — Report the current step, failure reason and ETA state in folder-replacement progress.json [Implemented]

###### Rationale

A consumer of `progress.json` could previously see only a rough status for a file, so a long planning, translation or apply step looked stalled, and a failed file gave no reason. In a measured Word document, planning alone took 33 to 73 seconds. Publishing the active step and the failure reason lets a monitor show what each file is doing and why it failed without reading the terminal. A `null` ETA is displayed by consumers as "None", which reads as an error. A separate `eta_status` property gives them a natural label while `eta_seconds` keeps its numeric type, so existing consumers continue to work.

##### FR-2026-08-27-04 — Bootstrap optional font packs and PaddleOCR models before processing [Implemented]

###### Rationale

Downloading fonts or OCR models while a document is being processed causes
late, network-dependent failures. A small explicit setup step makes those
downloads happen at a convenient time without turning the wrappers or the
normal processing path into an asset-management system. Pinning each archive's
digest keeps the font bytes that fitted layout measures and embeds identical
across machines and CI.

#### Text Replacement Requirements

Requirements for Text-replacement provider contract or deterministic replacement-provider test support.

##### FR-2026-10-22-01 — Replace a batch of texts with one provider call [Implemented]

###### Rationale

Translating a large document string by string takes thousands of sequential remote requests: measured Word, PDF, PowerPoint and Excel documents needed about 6,900, 3,400, 1,800 and 220 requests, at roughly 0.11 to 0.15 seconds each, for strings averaging 11 to 26 characters. A batch `replace` lets a remote provider send many texts per request: measured against the real service, batches of 100 to 1,000 texts translated 90 to 320 times faster than single-text calls. It is the only provider method, so a new provider implements one function, and a provider that handles one text at a time uses `replace_each`. This is a breaking change to the provider API.

#### Google Cloud Translation Requirements

Requirements for Google Cloud Translation provider or its local configuration.

##### FR-2026-10-22-02 — Translate a batch of texts in one Google Cloud Translation request [Implemented]

###### Rationale

Measured Word, PDF, PowerPoint and Excel documents made about 6,900, 3,400, 1,800 and 220 sequential `translateText` calls (about 151,000, 88,000, 20,000 and 6,000 characters), taking about 770, 390, 210 and 32 seconds, or 0.11 to 0.15 seconds per call whatever the length. Latency per call, not payload size, dominated. A benchmark with the real service on 1,000 synthetic Japanese strings (about 19 characters each) confirmed this: a request costs about 0.12 seconds plus about 11 milliseconds per 1,000 characters, and batches of 100 to 1,000 texts translated 90 to 320 times faster than single-text calls. At the default of about 5,000 characters per request, the estimated time for the largest measured document falls from about 14 minutes to about 5 seconds (about 31 requests). Larger requests gain little more (about 1 second at 10,000 characters) while a failed request repeats more text, so the defaults follow Google's recommendation of about 5,000 code points within its 1,024-item and 30,000-code-point limits. Per-character billing and per-text cache keys are unchanged. Hard-coded defaults with environment overrides allow tuning without a code change.

In the same benchmark a text's translation did not depend on its batch neighbours or position, but 8 of 100 texts were worded slightly differently from their single-text translation (same meaning). Existing cache entries stay valid and each cached text stays stable.

##### FR-2026-10-22-03 — Use a long request deadline and back off on Google Cloud Translation quota limits [Implemented]

###### Rationale

The 10-second deadline was a fixed value that suited single-text requests but would fail a large batch. The time went into the number of requests, not the length of any one, so a longer deadline lets a request pass instead of failing early. The pipeline may run inside a larger service with several users translating at once, so reaching a shared quota slows a run down rather than failing it. Google's quota documentation defines the daily and per-minute quota errors but prescribes no retry policy or maximum wait, so the backoff schedule and the 30-minute cap are project choices.

#### Pdf Requirements

Requirements for PDF.

##### FR-2026-10-23-02 — Plan PDF form-field appearance-stream text to avoid a plan miss [Deferred]

###### Rationale

The pre-existing apply route translates a form field's appearance stream after
replacing its `/V`, and the plan step does not list that text. Each affected field
therefore costs one plan miss and one extra single-text provider request. The
output is correct and the plan-miss fallback keeps it so. No sample PDF has
produced a plan miss, so the rare extra request does not justify changing the
PDF handler.

#### Powerpoint Requirements

Requirements for PowerPoint / PPTX.

##### FR-2026-10-22-08 — Translate all PowerPoint text parts in every document-text layout mode [Implemented]

###### Rationale

Layout, master, chart and comment text left in the source language produces a partly translated presentation. Every fitted mode translates all text in the package, as it does for SmartArt, WordArt and speaker notes. These parts add translation requests (a measured presentation needed about 1,800 in total), which batching makes inexpensive.

#### Vector Requirements

Requirements for SVG, EMF, WMF, or other vector graphics.

##### FR-2026-10-22-09 — Identify EMF and WMF graphics by content, not file extension [Implemented]

###### Rationale

Real documents contain EMF graphics saved with a `.wmf` extension. The WMF parser rejected them with "Invalid WMF header size." and no translated output was produced. Identifying the format from the content processes these files and leaves correctly named files unchanged.

##### FR-2026-10-22-10 — Translate EMF+ text and keep the EMF+ stream valid [Implemented]

###### Rationale

GDI+ viewers, including Office, play the EMF+ stream of a dual EMF and skip the duplicate GDI records. Translating only the GDI records left the source text visible there. Removing the EMF+ stream would lose the anti-aliased, more accurate GDI+ rendering, so both streams are translated.

The fitted source-font layout inserted its scaled GDI font records before the EMF+ header comment. A viewer expects the EMF+ header to follow the `EMR_HEADER` directly, so it treated the file as GDI-only. Placing the records after the header comment keeps the EMF+ stream recognised.

##### FR-2026-10-22-12 — Fit SVG text that has no clip rectangle to its measured source extent [Implemented]

###### Rationale

Most SVG text is not clipped. Leaving it at the source size lets longer translations run into neighbouring shapes, although the original extent is known from the source text and face.

##### FR-2026-10-22-13 — Fit WMF text that has no clip rectangle to its measured source extent [Implemented]

###### Rationale

Most WMF text is not clipped, so it was never fitted, and longer translations overlap neighbouring drawing. The original extent is known from the source text, face and font height.

##### FR-2026-10-22-14 — Translate EMF+ image objects: embedded bitmaps and nested metafiles [Implemented]

###### Rationale

Real EMF graphics can be saved as a dual EMF whose EMF+ stream draws image objects, including chunked bitmaps and nested metafiles, instead of text records. The GDI text and DIB records that the handler already translates are skipped by GDI+ viewers such as Office, so the output looked untranslated there. Re-using the shared bitmap handler and the nested-document recursion adds no second raster or vector implementation.

## 0.1.0 (2026-09-11)

First release of the visual document replacement pipeline. The folder-replacement
command recursively processes supported raster images, PDFs, Word, PowerPoint,
Excel, and vector graphics while preserving the source folder structure and file
formats. It combines pluggable OCR and text-replacement providers with native
editable-text replacement, embedded-image traversal, colour-aware bitmap
rendering, and configurable layout-preservation modes. The recommended Docker
workflow provides CPU and NVIDIA GPU images with PaddleOCR and Google Cloud
Translation as the defaults; Argos Translate can be selected instead through
the command-line options for local translation.

### Security Requirements

Requirements for Dependency, credential, remote-data, or local-persistence security.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| SR-2026-08-01-01 | Dependency cooldown and source-build prevention | Implemented | KrisTC |
| SR-2026-08-03-02 | Do not dereference external resources from vector graphics | Proposed | KrisTC |
| SR-2026-08-21-01 | Official Paddle CUDA wheel registry exception | Implemented | KrisTC |
| SR-2026-08-21-02 | Approved registry exceptions and artifact verification | Implemented | KrisTC |
| SR-2026-08-24-01 | Google Cloud Translation credentials and remote-data boundary | Implemented | KrisTC |
| SR-2026-08-27-01 | Secure local persistence of opt-in provider-result caches | Implemented | KrisTC |
| SR-2026-08-29-01 | Constrain local PDFium rendering of untrusted PDFs | Implemented | KrisTC |
| SR-2026-09-07-01 | Constrain OCI container mounts, credentials, and plugin trust boundaries | Implemented | KrisTC |
| SR-2026-09-08-01 | Official PyTorch CPU wheel registry exception | Implemented | KrisTC |

### Technical Requirements

Requirements for Tools, dependencies, test runners, typing, or shared implementation structure.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| TR-2026-08-01-01 | Python dependency management uses uv | Implemented | KrisTC |
| TR-2026-08-01-02 | Python libraries for document-file processing | Implemented | KrisTC |
| TR-2026-08-01-03 | Centralised test suite and runner | Implemented | KrisTC |
| TR-2026-08-01-04 | Strict Python type checking | Implemented | KrisTC |
| TR-2026-08-03-01 | Isolate folder-processor format handlers and shared helpers | Proposed | KrisTC |
| TR-2026-08-26-01 | Dependency policy validation remains dependency-agnostic | Implemented | KrisTC |
| TR-2026-08-29-01 | Local PDFium renderer for outlined-PDF-text OCR | Implemented | KrisTC |
| TR-2026-08-29-02 | One-pass PDFium virtual-text detection for undecodable native PDF text | Proposed | KrisTC |
| TR-2026-09-07-01 | Build reproducible Linux CPU and GPU OCI images | Implemented | KrisTC |
| TR-2026-09-10-01 | Validate pull requests with GitHub Actions continuous integration | Implemented | KrisTC |
| TR-2026-09-10-02 | Publish version-tagged CPU and GPU OCI images to GitHub Container Registry | Implemented | KrisTC |

### General Requirements

Requirements for Shared pipeline, CLI, layout, cache, diagnostics, or development scenarios.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-08-03-03 | Process a folder of documents and bitmap images for visible-text replacement | Implemented | KrisTC |
| FR-2026-08-03-04 | Report folder-replacement progress | Implemented | KrisTC |
| FR-2026-08-03-07 | Select native document-text layout-preservation mode | Implemented | KrisTC |
| FR-2026-08-03-08 | Preserve OOXML markup-compatibility namespace bindings | Implemented | KrisTC |
| FR-2026-08-03-13 | Evaluate native text-element layout for preserve-basic-layout | Implemented | KrisTC |
| FR-2026-08-03-14 | Apply preserve-basic-layout to bounded native document text | Implemented | KrisTC |
| FR-2026-08-04-03 | Report actionable folder-replacement command-line errors | Implemented | KrisTC |
| FR-2026-08-04-07 | Apply preserve-basic-layout to bounded vector, Word, and PDF text | Implemented | KrisTC |
| FR-2026-08-04-14 | Report native text-replacement evaluation progress | Proposed | KrisTC |
| FR-2026-08-22-01 | Run repeatable preset folder-replacement development scenarios | Implemented | KrisTC |
| FR-2026-08-22-02 | Filter folder-replacement input files by glob pattern | Implemented | KrisTC |
| FR-2026-08-27-02 | Apply the PPTX source-font fitted-layout interpretation consistently across document formats | Implemented | KrisTC |
| FR-2026-08-27-04 | Bootstrap optional font packs and PaddleOCR models before processing | Implemented | KrisTC |
| FR-2026-08-27-05 | Support multi-face portable fallback segments in fitted document text | Proposed | KrisTC |
| FR-2026-08-27-06 | Write a per-document folder-replacement diagnostic report when work is ignored or unsupported | Implemented | KrisTC |
| FR-2026-08-27-09 | Safely retain unsupported fitted text in non-page and non-PDF containers | Proposed | KrisTC |
| FR-2026-08-27-10 | Transparently cache OCR and text-replacement provider results beside source files | Implemented | KrisTC |
| FR-2026-08-27-11 | Reuse one provider-cache SQLite connection for each source file | Implemented | KrisTC |
| FR-2026-08-28-02 | Preserve underlying provider names in cache-aware diagnostics | Implemented | KrisTC |
| FR-2026-08-28-03 | Record safe structured context for folder-replacement file failures | Implemented | KrisTC |
| FR-2026-09-02-01 | Tolerate transient local file locks during runtime-asset bootstrap | Implemented | KrisTC |
| FR-2026-09-02-02 | Report runtime-asset bootstrap progress | Proposed | KrisTC |
| FR-2026-09-02-03 | Warn when Windows long paths are disabled | Implemented | KrisTC |
| FR-2026-09-02-04 | Use compact development folder-replacement scenario paths | Implemented | KrisTC |
| FR-2026-09-03-01 | Render bounded, nested Rich terminal progress | Proposed | KrisTC |
| FR-2026-09-07-01 | Run folder replacement through fixed-path CPU and GPU OCI container interfaces | Implemented | KrisTC |
| FR-2026-09-07-02 | Discover trusted provider plugins from the fixed container plugin mount | Implemented | KrisTC |
| FR-2026-09-07-04 | Use an optional mounted font catalog for container source-font measurement | Implemented | KrisTC |

### Text Replacement Requirements

Requirements for Text-replacement provider contract or deterministic replacement-provider test support.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-08-02-06 | Pluggable text-replacement API | Implemented | KrisTC |
| FR-2026-08-02-11 | Add deterministic text-replacement test providers | Implemented | KrisTC |

### Argos Translate Requirements

Requirements for Argos Translate provider.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-08-04-12 | Translate text and filenames with Argos Translate | Implemented | KrisTC |

### Excel Requirements

Requirements for Excel / XLSX.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-08-04-08 | Translate structured XLSX table headers safely | Proposed | KrisTC |
| FR-2026-08-22-12 | Resolve XLSX workbook theme fonts for source-font fitting | Implemented | KrisTC |
| FR-2026-09-03-05 | Exclude numeric-looking XLSX text from translation | Implemented | KrisTC |
| FR-2026-09-03-06 | Support full and fast XLSX translation modes | Implemented | KrisTC |
| FR-2026-09-04-01 | Expand fast XLSX selection while avoiding unrelated large worksheets | Implemented | KrisTC |

### Google Cloud Translation Requirements

Requirements for Google Cloud Translation provider or its local configuration.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-08-24-04 | Translate text and filenames with Google Cloud Translation | Implemented | KrisTC |
| FR-2026-08-24-05 | Configure and verify Google Cloud Translation credentials | Implemented | KrisTC |
| FR-2026-08-28-01 | Reuse Google Cloud Translation client within a provider instance | Implemented | KrisTC |
| FR-2026-09-03-04 | Bound and diagnose transient Google Cloud Translation request waits | Implemented | KrisTC |

### Pdf Requirements

Requirements for PDF.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-08-04-09 | Safely replace currently supported PDF text | Implemented | KrisTC |
| FR-2026-08-04-10 | Support complete Unicode replacement in unbounded PDF content | Implemented | KrisTC |
| FR-2026-08-22-07 | Use embedded PDF source fonts for source-font layout measurement | Deferred | KrisTC |
| FR-2026-08-23-01 | Fit replacement text in inferred PDF visual text regions | Implemented | KrisTC |
| FR-2026-08-23-02 | Preserve PDF text paint state when fitting visual regions | Implemented | KrisTC |
| FR-2026-08-23-03 | Use fill-only portable replacement for fill-and-stroke PDF text | Implemented | KrisTC |
| FR-2026-08-23-04 | Use Type0 CID width tables for PDF visual-region geometry | Implemented | KrisTC |
| FR-2026-08-23-05 | Preserve PDF text positioning across undecodable source text | Implemented | KrisTC |
| FR-2026-08-23-06 | Recover Unicode from embedded Identity CID fonts when `/ToUnicode` is incomplete | Implemented | KrisTC |
| FR-2026-08-24-01 | Reliably decode Type0 PDF text when high-level decoding yields whitespace | Implemented | KrisTC |
| FR-2026-08-24-02 | Make fitted replacement text authoritative for PDF copy and search | Implemented | KrisTC |
| FR-2026-08-27-03 | Provide portable Noto fallback coverage for fitted PDF page visual text | Implemented | KrisTC |
| FR-2026-08-27-07 | Add portable Noto Math fallback for editable scientific notation | Implemented | KrisTC |
| FR-2026-08-27-08 | Diagnose safely retained native PDF text in debug runs | Implemented | KrisTC |
| FR-2026-08-28-04 | Replace fully covered PDF text marked with alternate text | Implemented | KrisTC |
| FR-2026-08-29-01 | OCR-replace outlined PDF vector text without rasterizing the page | Implemented | KrisTC |
| FR-2026-08-29-02 | OCR fallback for undecodable native PDF text | Proposed | KrisTC |
| FR-2026-08-29-03 | Infer multi-run PDF visual text blocks for context-aware translation | Implemented | KrisTC |
| FR-2026-08-30-05 | Conservatively widen eligible single-line PDF replacement regions, including enclosing highlight containers | Implemented | KrisTC |
| FR-2026-08-30-06 | Retain native PDF text whose Unicode decoding cannot be verified | Implemented | KrisTC |
| FR-2026-08-31-01 | Detail diagnostics for unsupported vector-OCR orientation | Implemented | KrisTC |
| FR-2026-08-31-02 | Diagnose and apply reviewed legacy bullet mappings in fitted PDF text | Implemented | KrisTC |
| FR-2026-09-01-01 | Reflow compatible PDF colour-emphasis spans as one fitted region | Implemented | KrisTC |
| FR-2026-09-09-01 | Serialize fitted PDF line feeds as layout boundaries | Proposed | KrisTC |

### Powerpoint Requirements

Requirements for PowerPoint / PPTX.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-08-03-15 | Apply preserve-basic-layout to PPTX text frames | Implemented | KrisTC |
| FR-2026-08-03-16 | Replace and fit PowerPoint table-cell text | Implemented | KrisTC |
| FR-2026-08-04-01 | Derive fit bounds for PowerPoint no-autofit text frames | Implemented | KrisTC |
| FR-2026-08-04-04 | Preview PowerPoint no-autofit derived fit bounds | Implemented | KrisTC |
| FR-2026-08-04-05 | Preserve PowerPoint no-autofit width and derive its natural text height | Implemented | KrisTC |
| FR-2026-08-04-11 | Replace editable SmartArt and WordArt text in PPTX files | Implemented | KrisTC |
| FR-2026-08-04-13 | Replace PowerPoint speaker-note text | Implemented | KrisTC |
| FR-2026-08-05-01 | Preserve advanced PPTX text styling during fitted replacement | Implemented | KrisTC |
| FR-2026-08-22-06 | Use embedded PPTX source fonts for source-font layout measurement | Proposed | KrisTC |
| FR-2026-08-22-09 | Preview source-font fitted layout in the native-text evaluator | Implemented | KrisTC |
| FR-2026-08-22-10 | Resolve PPTX theme typeface aliases for source-font fitting | Implemented | KrisTC |
| FR-2026-09-06-02 | Fit PowerPoint table text as a table-wide typography plan | Implemented | KrisTC |
| FR-2026-09-06-03 | Normalize trailing empty paragraphs in PowerPoint text frames | Implemented | KrisTC |
| FR-2026-09-06-04 | Apply first-line indentation to PowerPoint fitted-text layout | Implemented | KrisTC |
| FR-2026-09-06-05 | Reserve a no-autofit source-height fitting margin | Implemented | KrisTC |
| FR-2026-09-06-06 | Preserve inferred word separators across SmartArt formatting runs | Implemented | KrisTC |

### Raster Ocr Requirements

Requirements for Raster images, OCR providers, OCR evaluation, or replacement-image rendering.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-08-01-01 | Prepare OCR-evaluation image inputs | Implemented | KrisTC |
| FR-2026-08-01-02 | Pluggable OCR-provider API | Implemented | KrisTC |
| FR-2026-08-01-03 | Generate manual OCR-evaluation results and viewer | Proposed | KrisTC |
| FR-2026-08-02-01 | Report OCR-evaluation progress | Proposed | KrisTC |
| FR-2026-08-02-02 | Present OCR text regions in the evaluation viewer | Implemented | KrisTC |
| FR-2026-08-02-04 | Show OCR confidence in the evaluation viewer | Implemented | KrisTC |
| FR-2026-08-02-05 | Prepare OCR-evaluation inputs before evaluation | Implemented | KrisTC |
| FR-2026-08-02-07 | Include context and clip-local coordinates in OCR-evaluation text clips | Implemented | KrisTC |
| FR-2026-08-02-08 | Handle cached OCR-evaluation artifacts after output-format changes | Implemented | KrisTC |
| FR-2026-08-02-09 | Estimate, document, and evaluate OCR text-region colours | Implemented | KrisTC |
| FR-2026-08-02-10 | Render replacement text into OCR regions with Skia | Implemented | KrisTC |
| FR-2026-08-02-13 | Generate text-replacement artifacts within OCR evaluations | Implemented | KrisTC |
| FR-2026-08-03-01 | Package OCR and text-replacement providers in name-derived directories | Implemented | KrisTC |
| FR-2026-08-03-02 | Use separate background and text passes for complete replacement images | Implemented | KrisTC |
| FR-2026-08-04-02 | Select an empty OCR provider for local pipeline testing | Implemented | KrisTC |
| FR-2026-08-21-01 | PaddleOCR Windows and accelerator runtime support | Implemented | KrisTC |
| FR-2026-08-24-03 | Configure Windows Paddle CUDA runtime environment | Implemented | KrisTC |
| FR-2026-08-27-01 | Flatten transparent raster images for OCR using the source page or slide background | Implemented | KrisTC |
| FR-2026-09-04-02 | Preserve transparent paletted PNG alpha through raster text replacement | Implemented | KrisTC |
| FR-2026-09-07-03 | Support opportunistic NVIDIA PaddleOCR acceleration in the OCI image | Implemented | KrisTC |

### Vector Requirements

Requirements for SVG, EMF, WMF, or other vector graphics.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-08-03-05 | Replace editable text in embedded vector graphics directly | Proposed | KrisTC |
| FR-2026-08-03-06 | Comment on unsupported images in Office documents | Proposed | KrisTC |
| FR-2026-08-03-09 | Replace raster DIBs embedded in EMF graphics | Proposed | KrisTC |
| FR-2026-08-03-10 | Separate vector format handlers and support standalone vector inputs | Proposed | KrisTC |
| FR-2026-08-03-11 | Replace self-contained SVG raster images | Proposed | KrisTC |
| FR-2026-08-03-12 | Replace self-contained WMF DIB bitmap records | Proposed | KrisTC |
| FR-2026-08-22-08 | Use embedded SVG source fonts for source-font layout measurement | Proposed | KrisTC |
| FR-2026-08-22-13 | Resolve SVG CSS font inheritance and stacks for source-font fitting | Implemented | KrisTC |
| FR-2026-09-04-01 | Fit un-clipped horizontal EMF text to measured source geometry | Implemented | KrisTC |
| FR-2026-09-05-01 | Fit EMF text through resolvable affine transforms | Implemented | KrisTC |
| FR-2026-09-05-02 | Fit coherent EMF text fragments as one visual block | Implemented | KrisTC |
| FR-2026-09-06-01 | Record vector fitted-layout fallbacks in output diagnostic sidecars | Implemented | KrisTC |

### Word Requirements

Requirements for Word / DOCX.

#### Added

| ID | Title | Status | Owner |
|---|---|---|---|
| FR-2026-08-22-03 | Produce Word-repair-free DOCX output when embedding fitted fonts | Proposed | KrisTC |
| FR-2026-08-22-05 | Use embedded DOCX source fonts for source-font layout measurement | Proposed | KrisTC |
| FR-2026-08-22-11 | Resolve DOCX inherited typography for fitted layout | Implemented | KrisTC |
| FR-2026-09-02-05 | Translate flowing Word paragraphs in maximal emphasis-preserving runs | Implemented | KrisTC |
| FR-2026-09-02-06 | Diagnose flowing Word paragraph structure fallbacks | Implemented | KrisTC |
| FR-2026-09-02-07 | Preserve and translate Word caption cross-references | Implemented | KrisTC |
| FR-2026-09-02-08 | Preserve field order and safe joins in flowing Word text | Implemented | KrisTC |
| FR-2026-09-02-09 | Preserve Table of Contents field layout during DOCX translation | Implemented | KrisTC |
| FR-2026-09-03-02 | Report post-native-pass DOCX layout progress | Implemented | KrisTC |
| FR-2026-09-03-03 | Translate native DOCX chart text and embedded chart workbooks | Implemented | KrisTC |

### Requirement details

#### Security Requirements

Requirements for Dependency, credential, remote-data, or local-persistence security.

##### SR-2026-08-01-01 — Dependency cooldown and source-build prevention [Implemented]

###### Rationale

A dependency cooldown gives the wider community time to detect and respond to a newly published malicious package or release. Preventing source-distribution builds prevents dependency build backends from running during installation.

##### SR-2026-08-03-02 — Do not dereference external resources from vector graphics [Proposed]

###### Rationale

External resource references create network and filesystem disclosure paths, non-deterministic output, and server-side request forgery risk when graphics are processed automatically.

##### SR-2026-08-21-01 — Official Paddle CUDA wheel registry exception [Implemented]

###### Rationale

PaddleOCR can use an NVIDIA GPU for local inference, but PaddlePaddle publishes its Windows CUDA wheels through its official CUDA-specific package index rather than PyPI. The repository requires a CUDA-enabled PaddlePaddle wheel for automatic GPU selection while retaining reproducible dependency resolution and the existing restrictive dependency policy.

##### SR-2026-08-21-02 — Approved registry exceptions and artifact verification [Implemented]

###### Rationale

Some platform-specific dependencies are not published on PyPI or do not publish compatible artifact hashes. A narrow exception and locally reviewed artifact digest maintain the default dependency restrictions while providing a reusable integrity control for explicitly approved cases.

##### SR-2026-08-24-01 — Google Cloud Translation credentials and remote-data boundary [Implemented]

###### Rationale

Cloud translation requires an external trust boundary and credentials. Restricting configuration to the established local environment mechanism prevents accidental version control of secrets. Google's documented API data-use controls permit the provider to process user-authorized text, including confidential samples when the user requests that processing.

##### SR-2026-08-27-01 — Secure local persistence of opt-in provider-result caches [Implemented]

###### Rationale

Source-adjacent caching makes expensive OCR and translation reruns practical,
but it deliberately retains text that may be sensitive. Explicit activation,
safe data-only decoding, conservative error handling, and exclusion from source
processing prevent that local optimization from becoming a new disclosure or
code-execution path.

##### SR-2026-08-29-01 — Constrain local PDFium rendering of untrusted PDFs [Implemented]

###### Rationale

PDF rendering introduces a native-code parser and potentially large bitmap
allocations for untrusted input. Keeping rendering local, action-free, bounded,
and in memory limits disclosure and resource-exhaustion risk while permitting
OCR of vector-outlined text.

##### SR-2026-09-07-01 — Constrain OCI container mounts, credentials, and plugin trust boundaries [Implemented]

###### Rationale

Container mounts make host data and executable extensions available to the pipeline. Explicit read/write boundaries, non-root execution, and clear credential precedence reduce accidental disclosure while retaining normal provider configuration and model bootstrapping.

##### SR-2026-09-08-01 — Official PyTorch CPU wheel registry exception [Implemented]

###### Rationale

Argos Translate requires PyTorch through its normal dependency graph. The Linux
PyPI wheel currently includes CUDA packages, while PyTorch's official CPU wheel
preserves Argos support in the CPU OCI image without adding CUDA, cuDNN, or an
NVIDIA driver.

#### Technical Requirements

Requirements for Tools, dependencies, test runners, typing, or shared implementation structure.

##### TR-2026-08-01-01 — Python dependency management uses uv [Implemented]

###### Rationale

Provides a single, defined dependency-management tool for Python development.

##### TR-2026-08-01-02 — Python libraries for document-file processing [Implemented]

###### Rationale

The pipeline requires programmatic support for these document formats.

##### TR-2026-08-01-03 — Centralised test suite and runner [Implemented]

###### Rationale

A single test location and equivalent per-platform test commands make regression checks easy to find and run consistently on macOS, Linux, and Windows.

##### TR-2026-08-01-04 — Strict Python type checking [Implemented]

###### Rationale

Strong static typing detects integration errors before runtime and keeps the pipeline interfaces reliable as provider plugins are added.

##### TR-2026-08-03-01 — Isolate folder-processor format handlers and shared helpers [Proposed]

###### Rationale

Format-specific replacement behaviour will need iterative development. Separate handlers make that work focused, while shared in-memory processing prevents duplicated behaviour and unnecessary disk I/O for embedded content.

##### TR-2026-08-26-01 — Dependency policy validation remains dependency-agnostic [Implemented]

###### Rationale

Dependency-specific validation causes routine publisher hosting changes to require code changes and makes registry-exception controls difficult to reuse.

##### TR-2026-08-29-01 — Local PDFium renderer for outlined-PDF-text OCR [Implemented]

###### Rationale

PDFium provides a local, deterministic renderer for vector outlines that pypdf
does not rasterize. An isolated render input prevents the new pass from
detecting and replacing the same visible text that native-PDF or embedded-image
processing already handles.

##### TR-2026-08-29-02 — One-pass PDFium virtual-text detection for undecodable native PDF text [Proposed]

###### Rationale

Combining detection avoids an expensive second OCR request. Virtual text
recovers translation context without relying on undecodable PDF operands as
text or requiring a brittle per-operation OCR match.

##### TR-2026-09-07-01 — Build reproducible Linux CPU and GPU OCI images [Implemented]

###### Rationale

The container must be repeatable enough to debug document-processing output, while GPU runtime compatibility requires explicit version selection. A narrow runtime image and non-root execution reduce the operational surface exposed to untrusted document inputs.

##### TR-2026-09-10-01 — Validate pull requests with GitHub Actions continuous integration [Implemented]

###### Rationale

Pull-request CI gives contributors and reviewers repeatable evidence that a
change preserves the dependency controls, Python quality gates, test suite,
and both distributable container definitions before it is merged.  Keeping
untrusted pull-request code in a read-only, secret-free workflow limits the
effect of contributions from forks.

##### TR-2026-09-10-02 — Publish version-tagged CPU and GPU OCI images to GitHub Container Registry [Implemented]

###### Rationale

No rationale provided.

#### General Requirements

Requirements for Shared pipeline, CLI, layout, cache, diagnostics, or development scenarios.

##### FR-2026-08-03-03 — Process a folder of documents and bitmap images for visible-text replacement [Implemented]

###### Rationale

The existing pipeline primitives and local evaluators need a user-facing command that produces complete, replacement-processed copies of an input folder.

##### FR-2026-08-03-04 — Report folder-replacement progress [Implemented]

###### Rationale

OCR and later translation can take substantial time. Per-document progress provides visibility through long embedded-image work while retaining the command's isolated per-file failure behaviour.

##### FR-2026-08-03-07 — Select native document-text layout-preservation mode [Implemented]

###### Rationale

Source formatting may be essential to a document's design, but translated text can be substantially longer or shorter. An explicit mode lets users choose between source fidelity and a basic readability-oriented fit.

##### FR-2026-08-03-08 — Preserve OOXML markup-compatibility namespace bindings [Implemented]

###### Rationale

OOXML compatibility markup uses prefix-valued attributes whose prefixes may not otherwise appear in an element or attribute name. A generic XML serializer can discard those declarations even though the resulting package still requires them. Preserving the bindings keeps generated Word, Excel, and PowerPoint documents valid and avoids application repair prompts.

##### FR-2026-08-03-13 — Evaluate native text-element layout for preserve-basic-layout [Implemented]

###### Rationale

Native text elements have explicit bounds and may contain multiple runs with distinct formatting. Inspecting their geometry and source settings separately from OCR-region replacement provides a fast visual baseline for the later `preserve-basic-layout` fitting implementation.

##### FR-2026-08-03-14 — Apply preserve-basic-layout to bounded native document text [Implemented]

###### Rationale

Translated text may differ substantially in length. A shared fitting model provides a readability-first replacement path wherever the source exposes an explicit text container, while allowing each document format to retain its own safe serialization rules.

##### FR-2026-08-04-03 — Report actionable folder-replacement command-line errors [Implemented]

###### Rationale

Input paths and provider names are ordinary user choices. Clear command-line feedback lets a user correct them immediately, rather than interpreting an implementation exception or traceback.

##### FR-2026-08-04-07 — Apply preserve-basic-layout to bounded vector, Word, and PDF text [Implemented]

###### Rationale

The readability objective applies wherever the document format supplies a true text field, annotation, or clip rectangle, not only to PowerPoint. A shared core prevents later fitting corrections from diverging between Office, PDF, and vector formats.

##### FR-2026-08-04-14 — Report native text-replacement evaluation progress [Proposed]

###### Rationale

Native-text evaluation may process many presentations and render every eligible text box with each replacement provider. Folder-level progress makes that work visible while preserving the command's isolated per-presentation failure handling.

##### FR-2026-08-22-01 — Run repeatable preset folder-replacement development scenarios [Implemented]

###### Rationale

Repeatedly entering long folder-replacement commands makes it difficult to run
consistent before-and-after comparisons while pipeline behaviour changes. A
bounded development runner makes the common sample-data scenarios concise,
repeatable, and easy to review across languages and option combinations while
leaving the general-purpose pipeline command unchanged.

##### FR-2026-08-22-02 — Filter folder-replacement input files by glob pattern [Implemented]

###### Rationale

Development and diagnosis often need to focus on one document type or a small
set of files. Glob-based inclusion avoids repeatedly processing unrelated
documents while retaining the general recursive-folder workflow.

##### FR-2026-08-27-02 — Apply the PPTX source-font fitted-layout interpretation consistently across document formats [Implemented]

###### Rationale

Using the source face for source measurement gives more accurate source-derived
bounds.  Selecting the replacement/output face separately prevents missing
glyphs or a non-embeddable source font from producing unreadable output.  This
makes the mode predictable across formats without changing their existing
format-specific safety behaviour.

##### FR-2026-08-27-04 — Bootstrap optional font packs and PaddleOCR models before processing [Implemented]

###### Rationale

Downloading fonts or OCR models while a document is being processed causes
late, network-dependent failures. A small explicit setup step makes those
downloads happen at a convenient time without turning the wrappers or the
normal processing path into an asset-management system.

##### FR-2026-08-27-05 — Support multi-face portable fallback segments in fitted document text [Proposed]

###### Rationale

PDF and the other supported native document formats can represent adjacent
runs with different fonts. Modelling this once in the shared layout pipeline
avoids inconsistent format-specific fallback decisions.

##### FR-2026-08-27-06 — Write a per-document folder-replacement diagnostic report when work is ignored or unsupported [Implemented]

###### Rationale

The identity provider reveals the exact source characters, whereas masking
output may not. A companion report makes fallback and selection problems
debuggable without making a local development run depend on terminal output.

##### FR-2026-08-27-09 — Safely retain unsupported fitted text in non-page and non-PDF containers [Proposed]

###### Rationale

Fitted PDF page visual text already has safe, region-level recovery. Other
editable text containers should have the same failure isolation without
claiming that all document formats already implement it.

##### FR-2026-08-27-10 — Transparently cache OCR and text-replacement provider results beside source files [Implemented]

###### Rationale

OCR and managed translation are expensive repeat operations. Factory-created
proxies keep caching provider-generic and available to every source-aware
pipeline path, while a per-source sidecar keeps derived text close to the input
whose processing produced it. Hashing prepared image content removes the need
for stable identifiers on images embedded in Office documents, PDFs, and vector
containers.

##### FR-2026-08-27-11 — Reuse one provider-cache SQLite connection for each source file [Implemented]

###### Rationale

PDF native-text processing can make hundreds or thousands of provider calls
before it completes its first progress work item. Opening, configuring, and
committing a SQLite connection for every cache lookup and write turns a local
SSD workload into a large filesystem-transaction workload and causes prolonged
apparent `0%` progress. A source-scoped connection retains the per-source
privacy boundary while removing this avoidable overhead.

Page-level progress makes a long native-text pass observable without pretending
that the count of PDF text operands can be cheaply known in advance.

##### FR-2026-08-28-02 — Preserve underlying provider names in cache-aware diagnostics [Implemented]

###### Rationale

Transparent cache proxies should not obscure which OCR or replacement provider
actually processed a document. Retaining the existing name and explicitly
showing cache use makes diagnostic sidecars accurate and readable.

##### FR-2026-08-28-03 — Record safe structured context for folder-replacement file failures [Implemented]

###### Rationale

An exception type alone does not reveal whether a failure occurred while
selecting an output filename, replacing native document text, OCRing an
embedded image, or writing an output package. Request metadata and a
document-local location make a local sidecar actionable without copying the
document's text or weakening the Google credential and remote-data boundary.

##### FR-2026-09-02-01 — Tolerate transient local file locks during runtime-asset bootstrap [Implemented]

###### Rationale

On Windows, antivirus scanning may briefly lock a downloaded temporary archive
while the bootstrap command cleans it up.

##### FR-2026-09-02-02 — Report runtime-asset bootstrap progress [Proposed]

###### Rationale

Font-pack downloads and first-time PaddleOCR model initialization can take long
enough that the explicit local setup command should show which bootstrap step
is active.

##### FR-2026-09-02-03 — Warn when Windows long paths are disabled [Implemented]

###### Rationale

The development scenario hierarchy and translated filenames can exceed the
legacy Windows path limit. Early guidance lets a developer correct the host
configuration before a processing run fails with an unhelpful file-not-found
error.

##### FR-2026-09-02-04 — Use compact development folder-replacement scenario paths [Implemented]

###### Rationale

The former descriptive hierarchy repeatedly stored long option keys, provider
names, and layout values. Plugin-declared, collision-checked short names avoid
unsafe derived acronyms while reducing Windows path-length failures that can
prevent generated Office files from being opened.

##### FR-2026-09-03-01 — Render bounded, nested Rich terminal progress [Proposed]

###### Rationale

A single live Rich display provides the Docker Compose-like view of overall,
current, and nested work while keeping output readable during long OCR and
document-processing runs. Retaining measurement and ETA information prevents
the improved layout from reducing the operational feedback currently provided
by tqdm.

##### FR-2026-09-07-01 — Run folder replacement through fixed-path CPU and GPU OCI container interfaces [Implemented]

###### Rationale

Fixed in-container paths make the container interface a thin packaging of the established command, rather than a second configuration layer. A durable cache avoids repeated model and font downloads, while automatic first-use setup keeps the single-command workflow usable.

##### FR-2026-09-07-02 — Discover trusted provider plugins from the fixed container plugin mount [Implemented]

###### Rationale

The fixed mount supports user-managed extensions without requiring users to rebuild the main image for ordinary plugin-code changes. Failing closed on name collisions keeps provider selection predictable.

##### FR-2026-09-07-04 — Use an optional mounted font catalog for container source-font measurement [Implemented]

###### Rationale

Documents often name fonts that are not distributed with the application.
Making a selected font directory visible lets source-font mode obtain more
accurate source metrics while preserving the existing portable Noto output and
fallback guarantees.

#### Text Replacement Requirements

Requirements for Text-replacement provider contract or deterministic replacement-provider test support.

##### FR-2026-08-02-06 — Pluggable text-replacement API [Implemented]

###### Rationale

The pipeline needs a stable, interchangeable boundary for translation and other visible-text replacement tasks before replacement is integrated with document processing.

##### FR-2026-08-02-11 — Add deterministic text-replacement test providers [Implemented]

###### Rationale

Deterministic same-length, longer, and shorter outputs make the local visual evaluator exercise the text-region renderer's fitting behaviour without depending on a translation service.

#### Argos Translate Requirements

Requirements for Argos Translate provider.

##### FR-2026-08-04-12 — Translate text and filenames with Argos Translate [Implemented]

###### Rationale

An offline translation provider enables the existing visible-text and folder-replacement pipeline to produce translated text and translated output filenames without using a remote translation service.

#### Excel Requirements

Requirements for Excel / XLSX.

##### FR-2026-08-04-08 — Translate structured XLSX table headers safely [Proposed]

###### Rationale

Table headers are both visible labels and schema identifiers. Replacing only the visible cells breaks the agreement with table metadata; replacing the metadata without every dependent structured reference can break formulae, query bindings, and workbook semantics.

##### FR-2026-08-22-12 — Resolve XLSX workbook theme fonts for source-font fitting [Implemented]

###### Rationale

Excel styles can request the major or minor workbook theme fonts instead of a
literal family name, while drawing text uses DrawingML's richer script-aware
font model. Resolving both paths provides metrics consistent with a workbook's
design without altering its existing style references.

##### FR-2026-09-03-05 — Exclude numeric-looking XLSX text from translation [Implemented]

###### Rationale

Numeric values and identifiers stored as text can inflate translation-request
counts and add remote work without providing a translation benefit. The rule
must be deterministic across platforms and preserve values whose apparent
numeric form is intentional text.

##### FR-2026-09-03-06 — Support full and fast XLSX translation modes [Implemented]

###### Rationale

Some workbooks contain large supporting sheets unrelated to displayed charts.
Fast mode avoids sending that material for translation while retaining the
visible chart labels and adjacent user-facing content needed to understand the
workbook.

##### FR-2026-09-04-01 — Expand fast XLSX selection while avoiding unrelated large worksheets [Implemented]

###### Rationale

Small worksheets commonly contain user-facing labels throughout the sheet, so
translating them in fast mode is useful. Large supporting sheets should not
turn fast mode into multiple full-package rewrites or full XML traversals when
they contain no visible chart labels.

#### Google Cloud Translation Requirements

Requirements for Google Cloud Translation provider or its local configuration.

##### FR-2026-08-24-04 — Translate text and filenames with Google Cloud Translation [Implemented]

###### Rationale

Argos Translate provides an offline option, but its translation quality is insufficient for some document-replacement workloads. Google Cloud Translation provides a separately selectable managed translation service without changing the shared replacement API or requiring the local provider to be removed.

##### FR-2026-08-24-05 — Configure and verify Google Cloud Translation credentials [Implemented]

###### Rationale

Service-account key creation may be restricted, while an approved local credential file can be distributed for a single-machine utility. A project-owned setup command makes that credential configuration explicit, validates it before use, and avoids hand-editing provider settings into an ignored environment file.

##### FR-2026-08-28-01 — Reuse Google Cloud Translation client within a provider instance [Implemented]

###### Rationale

PDF native text can produce many small replacement calls. Re-reading the local
credential JSON and constructing a Google client for every one adds unnecessary
local work and connection setup around every remote operation. Reuse preserves
the existing request semantics and trust boundary while removing that repeated
per-call setup cost.

##### FR-2026-09-03-04 — Bound and diagnose transient Google Cloud Translation request waits [Implemented]

###### Rationale

An RPC without a deadline can block a document pipeline indefinitely. A small,
bounded retry window tolerates transient transport failures while ensuring a
single replacement request cannot silently stall an entire source document.

#### Pdf Requirements

Requirements for PDF.

##### FR-2026-08-04-09 — Safely replace currently supported PDF text [Implemented]

###### Rationale

PDF appearance streams, CMaps, subsetted fonts, and page-content operators have materially different safety properties from Office text containers. These rules prevent invisible or corrupt masking text while keeping the bounded-form path portable and the unbounded-content path conservative.

##### FR-2026-08-04-10 — Support complete Unicode replacement in unbounded PDF content [Implemented]

###### Rationale

The implemented ASCII fallback is suitable for local masking and redaction but not for general translation.

##### FR-2026-08-22-07 — Use embedded PDF source fonts for source-font layout measurement [Deferred]

###### Rationale

PDFs often embed the exact font needed to render their form or annotation
content, but those programs are frequently subsetted. Separating recovery from
glyph validation permits accurate use when possible without claiming that an
arbitrary PDF font can encode a translated replacement.

##### FR-2026-08-23-01 — Fit replacement text in inferred PDF visual text regions [Implemented]

###### Rationale

A PDF page commonly contains text positioned as fragments, words, or glyph
runs rather than as a reflowable paragraph. Reconstructing a visual line or a
well-evidenced visual block provides a bounded region comparable to a
PowerPoint text frame, allowing translated replacement text to be fitted
without treating arbitrary PDF operator boundaries as layout structure.

##### FR-2026-08-23-02 — Preserve PDF text paint state when fitting visual regions [Implemented]

###### Rationale

PDF generators commonly retain a long text object while changing fill colour
for a link, label, or emphasis. Emitting every replacement only after the
text object's `ET` cannot preserve the paint state of its earlier text. The
replacement must instead be anchored to the source region's state.

##### FR-2026-08-23-03 — Use fill-only portable replacement for fill-and-stroke PDF text [Implemented]

###### Rationale

Mode `2` is visible selectable text, but a source outline stroke is not a
portable font-weight instruction. Applying it unchanged to a different target
face, particularly after fitting to a smaller size, can make replacement text
materially heavier than the source. Fill-only output is the predictable
baseline for translated and masking output.

##### FR-2026-08-23-04 — Use Type0 CID width tables for PDF visual-region geometry [Implemented]

###### Rationale

Type0 CIDFonts often use widths that vary by CID. Treating every decoded code
as the `/DW` default can over- or under-estimate a source visual line, causing
unnecessary shrinking, wrapping, or poor placement of a fitted replacement.

##### FR-2026-08-23-05 — Preserve PDF text positioning across undecodable source text [Implemented]

###### Rationale

PDF text positioning is stateful. An undecodable glyph can be left visually
unchanged without making a later decodable run unsafe, provided its advance is
known. Treating every undecodable operation as an unknown-position barrier
unnecessarily leaves later, independently replaceable text unchanged.

##### FR-2026-08-23-06 — Recover Unicode from embedded Identity CID fonts when `/ToUnicode` is incomplete [Implemented]

###### Rationale

Some PDFs contain visible selectable text whose `/ToUnicode` CMap is absent
or incomplete even though the embedded CID font provides an unambiguous
Unicode mapping. A PDF viewer can often use that mapping for copy and select
operations. Recovering it through a verified source-code-to-glyph chain makes
the text available to every replacement provider, including translation,
without weakening the existing conservative handling of genuinely opaque
glyph codes.

##### FR-2026-08-24-01 — Reliably decode Type0 PDF text when high-level decoding yields whitespace [Implemented]

###### Rationale

PDF viewers can sometimes recover text from Type0 fonts through decoding paths
that differ from a library's high-level helper. Parsing the document's own
Unicode CMap before declaring text undecodable prevents a helper limitation
from silently turning meaningful visible text into whitespace while retaining
the conservative no-guessing policy for genuinely opaque fonts.

##### FR-2026-08-24-02 — Make fitted replacement text authoritative for PDF copy and search [Implemented]

###### Rationale

Hiding source glyph painting can preserve the page's appearance and text
positioning, but it leaves the source string in the PDF text layer. That makes
copy, selection, and search disagree with the document the user sees. A
replacement pipeline intended for translation or masking must replace both
representations.

##### FR-2026-08-27-03 — Provide portable Noto fallback coverage for fitted PDF page visual text [Implemented]

###### Rationale

The current committed static faces are Japanese/Latin-focused. Selecting an
approved portable face before fitting prevents a glyph-coverage failure from
turning an otherwise eligible PDF visual region into an unexplained omission.

##### FR-2026-08-27-07 — Add portable Noto Math fallback for editable scientific notation [Implemented]

###### Rationale

Scientific documents commonly encode mathematical letters as Unicode text
rather than ordinary Latin characters. The existing base and Symbols 2 faces
do not cover every such character, while a single explicitly approved math
face is much smaller and simpler than a generic font-discovery system.

##### FR-2026-08-27-08 — Diagnose safely retained native PDF text in debug runs [Implemented]

###### Rationale

Visible source text can remain in a converted PDF for deliberate safety
reasons. A debug sidecar should make that distinction reviewable without
changing the conservative PDF-editing rules or misleading a reviewer into
thinking that the replacement provider was invoked.

##### FR-2026-08-28-04 — Replace fully covered PDF text marked with alternate text [Implemented]

###### Rationale

`/ActualText` is a hidden semantic label. Leaving it unchanged after a visible
replacement can expose the original text through copy, search, or assistive
technology. Removing it from a fully replaced, text-only scope makes the
replacement's Unicode mapping authoritative without risking an unrelated
marked-content use of the same shared property resource.

##### FR-2026-08-29-01 — OCR-replace outlined PDF vector text without rasterizing the page [Implemented]

###### Rationale

Some PDF producers convert visibly clear text into drawing paths. That text is
neither a PDF text operation nor an embedded bitmap, so the current native
text and embedded-image paths cannot reach it even when the selected OCR
provider recognizes a raster rendering with high confidence. A localized
render-and-overlay path closes this gap while preserving the rest of the page
as PDF content.

##### FR-2026-08-29-02 — OCR fallback for undecodable native PDF text [Proposed]

###### Rationale

A visible PDF text operation can have valid glyph drawing but lack a safe
Unicode mapping. Leaving it unchanged protects against inventing source text,
but a local visual OCR fallback can recover some such cases while retaining
the existing safety boundary and avoiding duplicate processing of nearby text.

##### FR-2026-08-29-03 — Infer multi-run PDF visual text blocks for context-aware translation [Implemented]

###### Rationale

PDF authoring tools often encode one visually coherent sentence or paragraph
as separately positioned fragments with mixed typography. Translating those
fragments independently loses linguistic context and fits each result to an
artificially small box. Reconstructing a well-evidenced visual block improves
translation quality and permits a single coherent reflow, while the explicit
table, column, and label exclusions retain the prior safety fix.

##### FR-2026-08-30-05 — Conservatively widen eligible single-line PDF replacement regions, including enclosing highlight containers [Implemented]

###### Rationale

Translations of short headings and list items can be materially longer than
their source text even when the surrounding page has unused space. Allowing a
verified one-sided expansion to retain the source font size and a one-line
result improves readability, while the single-line scope and fail-closed
collision check preserve the existing conservative handling of paragraphs,
tables, and graphics.

##### FR-2026-08-30-06 — Retain native PDF text whose Unicode decoding cannot be verified [Implemented]

###### Rationale

This defect is independent of Preview, Chrome, and Teams: they consistently
render the glyphs requested by the pipeline. The corruption begins earlier,
when an unverifiable source mapping is accepted as Unicode and is then
faithfully written into an embedded portable font. Retaining such text is the
only safe native-PDF outcome until the OCR fallback in FR-2026-08-29-02 can
associate and replace it.

##### FR-2026-08-31-01 — Detail diagnostics for unsupported vector-OCR orientation [Implemented]

###### Rationale

The aggregate retained-reason count identifies the cause of retention but not
whether a greater orientation tolerance would safely cover a useful recognised
region. Detected text and a normalised angle allow an operator to assess that
decision directly.

##### FR-2026-08-31-02 — Diagnose and apply reviewed legacy bullet mappings in fitted PDF text [Implemented]

###### Rationale

Legacy office fonts commonly encode visually decorative bullets as Private Use
Area characters. Unicode coverage cannot establish their meaning, and mapping
them automatically could change meaningful content. A precise diagnostic lets
an operator run the conversion over local documents, search for a bounded set
of review candidates, compare each candidate with its source rendering, and
approve only well-understood mappings.

##### FR-2026-09-01-01 — Reflow compatible PDF colour-emphasis spans as one fitted region [Implemented]

###### Rationale

Colour is commonly used to emphasise a word, phrase, or sentence without
changing the intended text flow. Treating each colour as an independent
fitting region loses the shared available width and makes longer replacements
wrap, shrink, or collide unnecessarily. Independently translating each
colour-emphasis span retains the existing provider contract and gives the same
translation context as the current independent-region behaviour, while a
single styled layout restores the intended shared reflow and uniform size.

##### FR-2026-09-09-01 — Serialize fitted PDF line feeds as layout boundaries [Proposed]

###### Rationale

Linux Skia returns glyph ID zero for a line feed while another supported
platform may return a nonzero placeholder. Treating a layout control as a
portable-font glyph therefore makes otherwise valid PDF replacement dependent
on the processing platform.

#### Powerpoint Requirements

Requirements for PowerPoint / PPTX.

##### FR-2026-08-03-15 — Apply preserve-basic-layout to PPTX text frames [Implemented]

###### Rationale

PPTX is the evaluated bounded-text format and provides the first production integration for the fitting model.

##### FR-2026-08-03-16 — Replace and fit PowerPoint table-cell text [Implemented]

###### Rationale

Table cells usually provide the explicit bounds needed for readable translated text, while a safe source-formatting fallback ensures that unsupported cell variants do not silently retain source-language text.

##### FR-2026-08-04-01 — Derive fit bounds for PowerPoint no-autofit text frames [Implemented]

###### Rationale

Authors can disable autofit while leaving a large editing text frame around a smaller intended block of text. Fitting replacement text to that loose frame can produce needlessly small or visually misplaced typography. The original laid-out text provides a closer approximation of the intended visual bounds.

##### FR-2026-08-04-04 — Preview PowerPoint no-autofit derived fit bounds [Implemented]

###### Rationale

The evaluator must preview the same fit decision that the production PPTX adapter writes. Showing both the original shape and the derived fit rectangle makes it possible to identify loose `noAutofit` frames and assess whether source-text measurement produces useful replacement typography.

##### FR-2026-08-04-05 — Preserve PowerPoint no-autofit width and derive its natural text height [Implemented]

###### Rationale

PowerPoint's no-autofit behaviour preserves the text-frame width and wraps content downward at the selected font size. A tight occupied-width calculation or height clamp incorrectly shrinks text and hides vertical overflow, producing a preview and fitted result unlike the source presentation.

##### FR-2026-08-04-11 — Replace editable SmartArt and WordArt text in PPTX files [Implemented]

###### Rationale

SmartArt commonly stores its visible editable text in diagram-specific package parts rather than ordinary slide-shape text frames. WordArt can similarly rely on a text body whose appearance is defined by DrawingML effects. Treating both as native editable PPTX text closes a visible replacement gap without rasterizing or rebuilding the presentation's design.

##### FR-2026-08-04-13 — Replace PowerPoint speaker-note text [Implemented]

###### Rationale

PowerPoint speaker notes are editable document text but are not exposed through the slide-shape traversal used for fitted slide text. Direct replacement ensures that the notes remain translated while avoiding unnecessary layout changes.

##### FR-2026-08-05-01 — Preserve advanced PPTX text styling during fitted replacement [Implemented]

###### Rationale

Modern PowerPoint WordArt uses ordinary editable DrawingML text with presets
and styling. Treating those properties as an unsupported container excludes
many ordinary coloured or styled text boxes from the fitted modes and makes
`preserve-basic-layout` unexpectedly retain source fonts. Retaining advanced
styling while changing only the fitted typography preserves more of the
presentation design and keeps the two fitted modes distinguishable. Exact
visual metric equivalence is not required because the output remains editable.

##### FR-2026-08-22-06 — Use embedded PPTX source fonts for source-font layout measurement [Proposed]

###### Rationale

PowerPoint files can carry their own design fonts. Using an available original
face gives the source-font mode metrics that reflect a presentation's intended
appearance without depending on the host's Office installation.

##### FR-2026-08-22-09 — Preview source-font fitted layout in the native-text evaluator [Implemented]

###### Rationale

Source-font fitting deliberately permits host-dependent results. Side-by-side
local previews, together with an explicit record of the selected measurement
face and fallback decision, make those results reviewable before users rely on
the mode for document output.

##### FR-2026-08-22-10 — Resolve PPTX theme typeface aliases for source-font fitting [Implemented]

###### Rationale

Theme aliases are symbolic pointers into a presentation's design system, not
font family names. Resolving them before fitting lets the source-font mode use
the family PowerPoint intends for each script, while retaining the original
theme-driven formatting in the editable output.

##### FR-2026-09-06-02 — Fit PowerPoint table text as a table-wide typography plan [Implemented]

###### Rationale

Independent cell fitting can make one translated body cell dramatically smaller
than neighbouring cells that were clearly intended to share a text size. A
common table scale preserves the author's typography. PowerPoint tables can
carry row-height values whose sum does not equal the rendered graphic frame;
using those values as absolute bounds shrinks both the apparent table and its
text. A fixed-frame row allocation repairs malformed grids, while retaining an
already well-formed grid avoids PowerPoint-specific visual reflow. The sidecar
makes scale selection, row allocation, and input geometry inconsistencies
visible during local iteration without disclosing table content.

##### FR-2026-09-06-03 — Normalize trailing empty paragraphs in PowerPoint text frames [Implemented]

###### Rationale

Trailing empty paragraphs are editing artefacts rather than visible text
content. Normalizing them away makes the PPTX input, fitted result, and
PowerPoint-visible layout agree. Empty paragraphs within or before visible
content can express deliberate spacing and therefore remain part of the layout.

##### FR-2026-09-06-04 — Apply first-line indentation to PowerPoint fitted-text layout [Implemented]

###### Rationale

Paragraph indentation changes the width available to text and can therefore
change wrapping, natural height, and the selected fitted font size. Treating
every line as though it began at the left margin can slightly overestimate or
underestimate the available width, particularly for translated text close to a
wrapping threshold.

##### FR-2026-09-06-05 — Reserve a no-autofit source-height fitting margin [Implemented]

###### Rationale

The measured source height is an approximation of PowerPoint's rendered
layout. Reserving a small, deterministic portion of the source content height
gives translated text a little additional reduction when it is close to a
wrapping threshold, reducing the likelihood that it expands into nearby slide
content while preserving the source frame's intended width and margins.

##### FR-2026-09-06-06 — Preserve inferred word separators across SmartArt formatting runs [Implemented]

###### Rationale

SmartArt commonly splits a logical label into adjacent DrawingML runs to
express formatting changes. Languages such as Japanese may have no source
space at that boundary, while independently translated English fragments
require one to remain readable. The existing per-node replacement path writes
the fragments directly adjacent, causing visible word collisions. The bounded
output-only rule extends the established flowing-Word and PDF colour-emphasis
joiner rules with the conservative punctuation cases needed by English prose.
Limiting it to an English target avoids inventing spacing for CJK text or other
target-language layouts.

#### Raster Ocr Requirements

Requirements for Raster images, OCR providers, OCR evaluation, or replacement-image rendering.

##### FR-2026-08-01-01 — Prepare OCR-evaluation image inputs [Implemented]

###### Rationale

Preparing a stable, image-only corpus enables a consistent comparison of OCR libraries across standalone images and images embedded in documents, while avoiding repeated extraction of unchanged documents.

##### FR-2026-08-01-02 — Pluggable OCR-provider API [Implemented]

###### Rationale

A provider abstraction permits the pipeline to use a consistent OCR result model while allowing OCR implementations to be selected by name.

##### FR-2026-08-01-03 — Generate manual OCR-evaluation results and viewer [Proposed]

###### Rationale

Persisting visual artifacts alongside normalized provider output makes it practical to inspect detection coverage and compare OCR providers against the local, real-data corpus.

##### FR-2026-08-02-01 — Report OCR-evaluation progress [Proposed]

###### Rationale

OCR evaluation against the local real-data corpus can take substantial time. Folder-level progress gives the user useful visibility into work completed without requiring them to infer it from model output files.

##### FR-2026-08-02-02 — Present OCR text regions in the evaluation viewer [Implemented]

###### Rationale

The table gives a compact, legible visual comparison of every detected region and its OCR result without overwhelming the manual-evaluation view with serialized data.

##### FR-2026-08-02-04 — Show OCR confidence in the evaluation viewer [Implemented]

###### Rationale

Displaying normalized confidence beside each detected region helps manual reviewers judge whether recognition quality corresponds with the provider's confidence.

##### FR-2026-08-02-05 — Prepare OCR-evaluation inputs before evaluation [Implemented]

###### Rationale

Preparing inputs first ensures the evaluation corpus reflects the current eligible sample-data tree without requiring a separate manual command.

##### FR-2026-08-02-07 — Include context and clip-local coordinates in OCR-evaluation text clips [Implemented]

###### Rationale

Small amounts of surrounding source-image context make text-region bitmaps more useful as test inputs. Clip-local coordinates allow downstream processing to select the detected text within those padded bitmaps without recalculating the crop offset.

##### FR-2026-08-02-08 — Handle cached OCR-evaluation artifacts after output-format changes [Implemented]

###### Rationale

The current cache is based only on input files. Without defined invalidation behaviour, an unchanged input tree causes the command to retain artifacts generated by an older evaluator format, including clips and JSON that lack newly required data.

##### FR-2026-08-02-09 — Estimate, document, and evaluate OCR text-region colours [Implemented]

###### Rationale

Reliable colour estimates are an enabling capability for later visual-text masking and replacement. Identifying the immediate glyph background, rather than merely the surrounding image context, is necessary for label panels and other strong local surfaces. Clear API documentation and static local pages let developers correctly interpret these estimates and compare them against complex examples without introducing a new rendering or image-processing step.

##### FR-2026-08-02-10 — Render replacement text into OCR regions with Skia [Implemented]

###### Rationale

The replacement-provider API, OCR geometry, and colour estimates provide the inputs needed to make translated or substituted text visibly fit the source image while avoiding a full-image copy for every individual region.

##### FR-2026-08-02-13 — Generate text-replacement artifacts within OCR evaluations [Implemented]

###### Rationale

Running the replacement stage against the full OCR-evaluation corpus tests the renderer with realistic region geometry and demonstrates both individual region results and the complete provider-specific updated image.

##### FR-2026-08-03-01 — Package OCR and text-replacement providers in name-derived directories [Implemented]

###### Rationale

A self-contained provider directory prevents name collisions by construction and gives contributors a clear boundary for more substantial providers, including cloud-based OCR or translation integrations that need provider-specific code, configuration, and authentication guidance.

##### FR-2026-08-03-02 — Use separate background and text passes for complete replacement images [Implemented]

###### Rationale

When detected text regions are close together, the existing per-region wipe-and-render order can allow a later background wipe to cover a replacement glyph rendered for an earlier region. Separating the operations preserves replacement text from later wipes.

##### FR-2026-08-04-02 — Select an empty OCR provider for local pipeline testing [Implemented]

###### Rationale

Replacing text in documents with many raster images can be slow because normal OCR initializes models and recognizes every image. An explicit empty local provider makes it possible to test discovery, output paths, native-text replacement, document traversal, progress, and error isolation without paying that OCR cost.

##### FR-2026-08-21-01 — PaddleOCR Windows and accelerator runtime support [Implemented]

###### Rationale

PaddleOCR documents NVIDIA GPU acceleration and the project now provides a Windows test runner. The pinned Windows and Linux CPU runtimes fail in OneDNN execution, while the same test input succeeds with OneDNN disabled. Automatic GPU selection preserves available performance improvements without making GPU hardware mandatory.

##### FR-2026-08-24-03 — Configure Windows Paddle CUDA runtime environment [Implemented]

###### Rationale

The Windows PaddlePaddle GPU wheel can be installed correctly while CUDA and cuDNN DLLs remain unavailable to its child process because their installation locations are not on `PATH`. A project-local environment file gives local development commands a repeatable way to expose those libraries and future provider settings without changing machine-wide configuration, while an end-to-end verification prevents treating a merely installed toolkit as usable GPU acceleration.

##### FR-2026-08-27-01 — Flatten transparent raster images for OCR using the source page or slide background [Implemented]

###### Rationale

Palette images can express alpha as per-palette transparency bytes. Direct conversion to RGB discards that alpha and causes Pillow to warn. Flattening an OCR-only copy before OCR removes the warning and gives OCR pixels consistent with the simple visible page or slide background without altering the source image used for replacement output.

##### FR-2026-09-04-02 — Preserve transparent paletted PNG alpha through raster text replacement [Implemented]

###### Rationale

An indexed PNG's pixels are palette indices, while its alpha may be stored in
a separate palette transparency table. Converting a rendered RGBA result to a
new palette and then copying those indices into the original image treats the
new indices as entries in the old palette. The resulting pixels can become
nearly transparent even when the original or rendered glyphs are opaque.

##### FR-2026-09-07-03 — Support opportunistic NVIDIA PaddleOCR acceleration in the OCI image [Implemented]

###### Rationale

The image must include the user-space components compatible with its pinned Paddle runtime, while the host remains responsible for exposing its driver and GPU through the normal container runtime. A separate CPU image avoids a CUDA wheel's early driver-library load preventing deterministic CPU execution.

#### Vector Requirements

Requirements for SVG, EMF, WMF, or other vector graphics.

##### FR-2026-08-03-05 — Replace editable text in embedded vector graphics directly [Proposed]

###### Rationale

Visible text may be part of a vector graphic rather than a native document text run or a raster bitmap. Direct native-text replacement preserves the graphic's fidelity and avoids unnecessary OCR cost and recognition errors.

##### FR-2026-08-03-06 — Comment on unsupported images in Office documents [Proposed]

###### Rationale

Comments make unreplaced visible text reviewable without altering the source image or silently implying that its content was processed.

##### FR-2026-08-03-09 — Replace raster DIBs embedded in EMF graphics [Proposed]

###### Rationale

An EMF can combine editable vector text with already-rasterized visual content. Processing DIB payloads directly covers that contained bitmap content without requiring an EMF renderer or rasterizing the whole vector graphic.

##### FR-2026-08-03-10 — Separate vector format handlers and support standalone vector inputs [Proposed]

###### Rationale

The vector formats have distinct binary and XML structures that need independent iteration. Sharing the one in-memory entry point prevents different behaviour for standalone and embedded graphics.

##### FR-2026-08-03-11 — Replace self-contained SVG raster images [Proposed]

###### Rationale

An SVG can combine editable text and an embedded raster image. Supporting self-contained raster data covers the image without requiring a renderer or an external resource.

##### FR-2026-08-03-12 — Replace self-contained WMF DIB bitmap records [Proposed]

###### Rationale

WMF supports raster DIB content alongside its native drawing and text records. Processing the DIB directly preserves the surrounding WMF without requiring a WMF renderer.

##### FR-2026-08-22-08 — Use embedded SVG source fonts for source-font layout measurement [Proposed]

###### Rationale

An inline SVG font is a self-contained source of the intended typeface, whereas
an external font reference crosses the pipeline's existing external-resource
security boundary.

##### FR-2026-08-22-13 — Resolve SVG CSS font inheritance and stacks for source-font fitting [Implemented]

###### Rationale

SVG typography is usually governed by CSS inheritance and ordered fallback
stacks, rather than a single direct family attribute. Computing the effective
stack lets source-font measurement follow the author’s intended fallback order
without crossing the existing external-resource trust boundary.

##### FR-2026-09-04-01 — Fit un-clipped horizontal EMF text to measured source geometry [Implemented]

###### Rationale

EMF drawings often encode table and heading labels as independent text records
without a clipping rectangle.  Measuring the original visual line provides a
safe default bound.  Limited expansion into evidenced empty horizontal space
preserves readable translated headings while retaining table rules and
neighbouring values as hard layout boundaries.

##### FR-2026-09-05-01 — Fit EMF text through resolvable affine transforms [Implemented]

###### Rationale

PowerPoint commonly carries EMF graphics that use repeated coordinate
translations and scales for ordinary diagram labels.  Other sources may use
rotation, reflection, or shear.  Treating every world transform as unsafe
leaves translated labels at their source size and makes adjacent-label overlap
likely.  Fitting every resolvable transform to its original visible bound
maximizes translation coverage and visibility; limiting expansion to the
simple axis-aligned case preserves the existing obstacle-safety guarantee
without delaying rotated, mirrored, or sheared text support.

##### FR-2026-09-05-02 — Fit coherent EMF text fragments as one visual block [Implemented]

###### Rationale

Some PowerPoint EMFs encode one visually continuous label as several GDI text
records separated by non-painting state changes, even when the displayed text
has one apparent size. Independent replacement gives each fragment a separate
translation scope and fitting scale, causing visible overlap or inconsistent
typography. Shared container, baseline, ordering, and obstacle evidence allows
a coherent replacement without treating nearby diagram labels as a paragraph.

##### FR-2026-09-06-01 — Record vector fitted-layout fallbacks in output diagnostic sidecars [Implemented]

###### Rationale

PowerPoint frequently embeds EMFs whose GDI coordinate state makes a fitted
replacement unsafe. Recording the local EMF record and exact fallback status
makes this visible without modifying the presentation or requiring manual
package inspection.

#### Word Requirements

Requirements for Word / DOCX.

##### FR-2026-08-22-03 — Produce Word-repair-free DOCX output when embedding fitted fonts [Proposed]

###### Rationale

DOCX font embedding is an OOXML package feature with Word-specific binary and
relationship rules. A ZIP archive that contains a font-looking part can still
be unreadable or repairable by Word. Validating the complete package and the
recovered font prevents portability work from producing corrupt documents.

##### FR-2026-08-22-05 — Use embedded DOCX source fonts for source-font layout measurement [Proposed]

###### Rationale

DOCX already has a well-defined embedded-font package representation, and this
pipeline already validates that representation when it embeds its own fitted
Noto faces. It is therefore the lowest-risk first format for source-font
measurement without relying on a locally installed font.

##### FR-2026-08-22-11 — Resolve DOCX inherited typography for fitted layout [Implemented]

###### Rationale

Word documents can inherit symbolic theme-font settings through several style
layers. Resolving those layers makes source-font measurement reflect the
document's intended typography without changing the theme-driven editable
formatting retained in output.

##### FR-2026-09-02-05 — Translate flowing Word paragraphs in maximal emphasis-preserving runs [Implemented]

###### Rationale

Word run boundaries record formatting and editing structure, not translation
boundaries. Translating each run independently gives a translation provider
unnecessarily small fragments. Merging all formatting that is not requested
emphasis maximises context while retaining colour, vertical-position, and
strikethrough cues. In scripts that normally omit spaces, independently
translated English emphasis runs can otherwise meet without a separator.

##### FR-2026-09-02-06 — Diagnose flowing Word paragraph structure fallbacks [Implemented]

###### Rationale

Word paragraphs can contain harmless-looking structural markup that prevents a
safe maximal-run rewrite. A local, precise diagnostic makes the resulting
translation-quality fallback visible, rather than confusing it with a
translation-provider failure or leaving text untranslated.

##### FR-2026-09-02-07 — Preserve and translate Word caption cross-references [Implemented]

###### Rationale

Caption text and a cross-reference's displayed result are two views of one
semantic source. Treating their serialized runs independently produces poor
translation and can invalidate the OOXML structures Word uses to discover
captions and create links. Resolving the bookmark relationship preserves both
translation consistency and the document's live-reference behaviour.

##### FR-2026-09-02-08 — Preserve field order and safe joins in flowing Word text [Implemented]

###### Rationale

Field markers define both live Word behaviour and visible-text boundaries.
Ignoring an unsupported field while rebuilding neighbouring text can shift a
separator across the field, making a page reference appear reordered even
though its field instructions remain in sequence. Dynamic counters are not
translation content, while translated prose immediately after a field can
still need the same safe Latin separator already required for emphasis runs.

##### FR-2026-09-02-09 — Preserve Table of Contents field layout during DOCX translation [Implemented]

###### Rationale

Word lays out a Table of Contents as a compact field result whose tabs and
leaders position page numbers. A generally safe prose separator consumes part
of that fixed layout and can wrap page values onto another line. Captions have
ordinary prose after their sequence number, so they need the normal joiner;
TOC entries instead require their existing tab-driven layout.

##### FR-2026-09-03-02 — Report post-native-pass DOCX layout progress [Implemented]

###### Rationale

DOCX processing performs a separate layout-aware XML and package rewrite after
the initial native-text and embedded-media pass. Leaving that rewrite outside
the work total makes the terminal report completion while substantial work is
still running.

##### FR-2026-09-03-03 — Translate native DOCX chart text and embedded chart workbooks [Implemented]

###### Rationale

A native Word chart has two representations of its editable label text: chart
XML used for immediate display and, when present, an embedded workbook used by
Excel's editing interface. Replacing only one makes the document internally
inconsistent. Delegating the workbook as a whole keeps spreadsheet semantics in
the XLSX adapter, while the DOCX adapter owns the chart-specific cache update
needed for Word to display the resulting workbook labels immediately.
