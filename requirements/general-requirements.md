# General Pipeline Requirements

Shared folder-processing, layout, diagnostics, caching, and development-workflow behaviour.

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

## FR-2026-08-22-01

| Property | Value |
|----------|-------|
| Title | Run repeatable preset folder-replacement development scenarios |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-04-02, FR-2026-08-04-03, FR-2026-08-27-02, FR-2026-08-04-07 |

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

## FR-2026-08-27-02

| Property | Value |
|----------|-------|
| Title | Apply the PPTX source-font fitted-layout interpretation consistently across document formats |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following cross-format layout review |
| Date Added | 2026-08-27 |
| Related Requirements | FR-2026-08-03-14, FR-2026-08-04-07, FR-2026-08-04-09, FR-2026-08-04-10, FR-2026-08-22-05, FR-2026-08-22-07, FR-2026-08-22-08, FR-2026-08-22-11, FR-2026-08-22-12, FR-2026-08-22-13, FR-2026-08-23-01, FR-2026-08-24-02, FR-2026-08-27-05 |

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
FR-2026-08-04-09 and the former cross-format source-font definition. It does not supersede any other PDF or format-specific safety rule.

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
