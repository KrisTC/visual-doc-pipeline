# Changelog

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
