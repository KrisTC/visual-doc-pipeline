# PowerPoint Requirements

PPTX-specific text replacement, fitting, styling, tables, shapes, and notes.

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
| Related Requirements | FR-2026-08-03-14, FR-2026-08-03-15, FR-2026-08-27-02, FR-2026-09-06-02 |

### Description

When either fitted document-text layout mode, `preserve-basic-layout` or `preserve-basic-layout-source-font`, is selected, the PPTX handler shall replace text in every editable PowerPoint table cell. Where the cell exposes a finite text rectangle, including its cell bounds and text-frame padding, it shall use the shared bounded-text layout core and write explicit fitted typography appropriate to the selected mode with autofit disabled. Typeface selection and source-font measurement for `preserve-basic-layout-source-font` are governed by FR-2026-08-27-02. It shall retain the table's fill, borders, merge state, and other non-text properties. Table-wide typography fitting, graphic-frame preservation, grid-column preservation, and row-height behaviour are governed by FR-2026-09-06-02.

If a table cell cannot supply a reliable finite text rectangle or cannot safely accept explicit fitted formatting, the handler shall still replace its editable text through the established source-formatting path. It shall retain the existing font, size, and text-frame behavior for that cell rather than skipping replacement.

### Rationale

Table cells usually provide the explicit bounds needed for readable translated text, while a safe source-formatting fallback ensures that unsupported cell variants do not silently retain source-language text.

### Notes

Automated tests shall use synthetic PPTX tables with ordinary cells and merged cells. They shall verify fitted replacement for bounded cells in both fitted layout modes, source-formatting replacement fallback for an ineligible cell, preservation of table geometry, and valid output packages.

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
FR-2026-08-27-02. This requirement continues to define the no-autofit fit
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

## FR-2026-08-05-01

| Property | Value |
|----------|-------|
| Title | Preserve advanced PPTX text styling during fitted replacement |
| Owner | KrisTC |
| Status | Implemented |
| Source | User clarification and local output diagnosis |
| Date Added | 2026-08-05 |
| Related Requirements | FR-2026-08-03-14, FR-2026-08-03-15, FR-2026-08-27-02, FR-2026-08-04-11 |

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
for that mode are defined by FR-2026-08-27-02.

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

## FR-2026-08-22-06

| Property | Value |
|----------|-------|
| Title | Use embedded PPTX source fonts for source-font layout measurement |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-03-15, FR-2026-08-27-02 |

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
resolver's responsibility under FR-2026-08-27-02.

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

## FR-2026-08-22-09

| Property | Value |
|----------|-------|
| Title | Preview source-font fitted layout in the native-text evaluator |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-03-13, FR-2026-08-27-02, FR-2026-08-22-06 |

### Description

`scripts/text_replacement_evaluations.py` shall generate previews for both
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
layout core required by FR-2026-08-27-02. It shall use the same source bounds,
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
| Related Requirements | FR-2026-08-03-13, FR-2026-08-03-15, FR-2026-08-27-02, FR-2026-08-22-09 |

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
of FR-2026-08-27-02.

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
FR-2026-08-27-02. It does not add embedded-font extraction; PPTX embedded-font
handling remains FR-2026-08-22-06. It shall not follow an external package,
filesystem path, or URL while resolving a theme.

Automated tests shall use synthetic PPTX packages with relationship-reachable
themes. They shall verify every major/minor and Latin/East Asian/complex-script
alias, direct-family preservation, script-segment selection, an unresolved
theme fallback, source-font JSON diagnostics, unchanged source aliases in
written output, and no dependency on fonts installed on the test host.

---

## FR-2026-09-06-02

| Property | Value |
|----------|-------|
| Title | Fit PowerPoint table text as a table-wide typography plan |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request and local output diagnosis |
| Date Added | 2026-09-06 |
| Related Requirements | FR-2026-08-03-16, FR-2026-08-27-02, FR-2026-08-27-06, FR-2026-08-28-03 |

### Description

In both fitted document-text layout modes, the PPTX adapter shall fit all
eligible non-empty merge-origin cells of one PowerPoint table as one table-wide
typography plan, rather than fitting cells independently.

This requirement refines FR-2026-08-03-16. That requirement remains governing
for editable-cell replacement, safe source-formatting fallback, and preservation
of table non-text properties; this requirement governs table-wide fitting and
table geometry, including row-height allocation.

Before replacement formatting is written, the adapter shall capture the table
graphic-frame rectangle, every grid-column width, every row height, merge
state, and each cell's padded text rectangle. The graphic-frame rectangle is
the authoritative rendered table size. In particular, the adapter shall not
treat a row-height sum that differs from the frame height, or an individual
zero-height row, as the table's rendered height or as an ineligible text bound.

The adapter shall replace and resolve output typefaces for all eligible cells.
When every source row has a positive height and the stored row-height total
agrees with the captured frame height within one percent, it shall retain those
row heights unchanged and iteratively determine the largest common font-scale
factor, no greater than `1.0`, that fits within them. This preserves a
well-formed PowerPoint table grid and avoids changing its rendered footprint.

Otherwise, the adapter shall iteratively determine the largest common
font-scale factor, no greater than `1.0`, for which it can allocate row heights
within the captured table frame and fit every eligible cell. It shall derive
each candidate cell's natural height at the candidate scale using its captured
width and padding, then allocate at least that height to each row. A cell
spanning rows shall require the combined allocated height of those rows. A row
with a stored height of zero remains eligible and shall receive its required
allocated height.

The common scale factor shall apply to every resolved source run size in the
table. It shall preserve deliberate source typography differences, such as a
larger header or smaller note, while ensuring that cells with the same source
font size receive the same fitted output size. Fitting results shall not depend
on cell traversal order.

The adapter shall preserve the captured table rectangle, grid-column widths,
and merge state. It shall not resize the table or columns, or enable
content-driven table or text-frame autofit. It shall write explicit no-autofit
and fitted typography for every participating cell.

When more than one row-height allocation can fit the selected common scale, the
adapter shall preserve the source's positive row-height proportions when it
distributes the remaining table height. This is a preference only: common-font
readability takes precedence over source row-height proportions, and fixed
table-frame size takes precedence over both. If no valid common scale can fit
within the fixed frame, the adapter shall retain the fixed frame and apply the
existing common minimum-scale overflow behaviour.

If no common scale can fit every participating cell while keeping each written
run at PowerPoint's valid one-point minimum, the adapter shall write the
smallest common scale that keeps every run valid and report normal overflow
behaviour; it shall not shrink only the overflowing cell or alter table
geometry. Existing safe fallback behaviour remains applicable to a cell that
has no reliable bounds or cannot safely accept explicit fitted formatting.

In a debug-enabled run, the adapter shall add one `table_fit` entry for each
table considered by this requirement to the document diagnostic sidecar under
FR-2026-08-27-06. A document with one or more such entries shall receive a
sidecar even when it has no ignored, failed, or unsupported work.

Each `table_fit` entry shall identify the slide number and zero-based table
shape index, without recording a shape name. It shall contain the input and
written table rectangle, grid-column widths, row heights, merge-origin count,
eligible-cell count, selected common scale, common fit status, whether the
written table frame exactly matches the captured frame, whether the input
row-height sum differed from that frame height, and the selected
`row_allocation_strategy` of `source_rows` or `frame_allocation`. It shall
record the final allocated row heights and their sum. For every participating
cell, it shall record its zero-based row and column, row and column spans,
captured padded bounds, resolved source font-size values, its independent fit
scale and status for comparison, and its fit status at the selected common
scale. It shall identify every cell that prevents a larger common scale and
every cell using the established source-formatting fallback.

These entries shall contain no source text, replacement text, shape name,
provider response, source-font family name, credential, cache key, or raw
exception detail. The diagnostic path shall use the replacement and layout
results already produced for the table; it shall not invoke a provider again.

### Rationale

Independent cell fitting can make one translated body cell dramatically smaller
than neighbouring cells that were clearly intended to share a text size. A
common table scale preserves the author's typography. PowerPoint tables can
carry row-height values whose sum does not equal the rendered graphic frame;
using those values as absolute bounds shrinks both the apparent table and its
text. A fixed-frame row allocation repairs malformed grids, while retaining an
already well-formed grid avoids PowerPoint-specific visual reflow. The sidecar
makes scale selection, row allocation, and input geometry inconsistencies
visible during local iteration without disclosing table content.

### Notes

Automated tests shall use synthetic PPTX tables only. They shall verify that two
body cells with equal source font sizes and materially different replacement
lengths receive equal output font sizes; deliberate header/body size differences
retain their proportional relationship; and the table frame, grid-column widths,
and merges are unchanged in the output package and rendered output. Tests shall
cover a stored row-height total that differs from the table frame, a zero-height
row with text, a merged participating cell, and a table that reaches the common
one-point overflow result.

Debug tests shall verify one `table_fit` sidecar entry per considered table,
including a successful table-only document; stable slide, shape, cell, scale,
and geometry fields; correct limiting-cell and fallback reporting; no repeated
provider calls; and the absence of source and replacement text, shape names,
provider responses, font-family names, credentials, cache keys, and raw
exception details. Tests and fixtures shall use synthetic data only.

---

## FR-2026-09-06-03

| Property | Value |
|----------|-------|
| Title | Normalize trailing empty paragraphs in PowerPoint text frames |
| Owner | KrisTC |
| Status | Implemented |
| Source | User clarification following local output diagnosis |
| Date Added | 2026-09-06 |
| Related Requirements | FR-2026-08-03-14, FR-2026-08-03-15, FR-2026-08-03-13, FR-2026-08-04-05 |

### Description

For a PPTX slide-shape text frame processed in either fitted
document-text-layout mode, the PPTX adapter shall remove the maximal trailing
sequence of empty paragraphs from the source text frame before replacement,
fitting, and output serialization. An empty paragraph is a paragraph with no
non-whitespace run text. This applies to source-derived fitting measurements,
including an explicit `noAutofit` natural-height measurement.

The adapter shall retain all non-trailing empty paragraphs. In particular,
leading empty paragraphs and empty paragraphs between paragraphs containing
non-whitespace text shall remain in the source, output, and fitting layout.
This requirement applies to placeholders and text frames in group shapes as
defined by FR-2026-08-03-15. PowerPoint table cells remain governed by
FR-2026-09-06-02.

The native PowerPoint text-layout evaluator shall apply the same normalization
before source and replacement rendering, fitting, and property reporting.

This requirement is a PPTX-specific exception to the shared core's ordinary
empty-paragraph retention behaviour. It does not change handling of trailing
line-break characters inside a nonempty paragraph, or measurement and
serialization rules for DOCX, XLSX, PDF, and vector adapters.

### Rationale

Trailing empty paragraphs are editing artefacts rather than visible text
content. Normalizing them away makes the PPTX input, fitted result, and
PowerPoint-visible layout agree. Empty paragraphs within or before visible
content can express deliberate spacing and therefore remain part of the layout.

### Notes

Automated tests shall use synthetic PPTX files only. They shall verify that a
text frame with trailing empty paragraphs receives the same fitted font scale
as an otherwise identical frame without them, and that the written output and
evaluator artifacts contain no trailing empty paragraphs. They shall verify the
same result for an explicit `noAutofit` text frame's derived fitting height and
evaluator preview. They shall also verify that an empty paragraph between
visible paragraphs, and one before visible content, continues to contribute its
line advance and can change the selected fitted scale. Tests shall cover
ordinary, placeholder, and grouped text frames; they shall not use confidential
presentations or derived artifacts.

---

## FR-2026-09-06-04

| Property | Value |
|----------|-------|
| Title | Apply first-line indentation to PowerPoint fitted-text layout |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following PPTX layout review |
| Date Added | 2026-09-06 |
| Related Requirements | FR-2026-08-03-13, FR-2026-08-03-14, FR-2026-08-03-15, FR-2026-08-27-02 |

### Description

For PowerPoint text frames, the shared bounded-text layout core shall
distinguish a paragraph's first-line text width from its continuation-line text
width when the PPTX adapter supplies a resolved left margin and first-line
indent.

For a horizontal, non-bulleted paragraph, the first-line text origin shall be
the padded text-frame origin plus the resolved left margin and first-line
indent. Continuation lines shall begin at the resolved left margin. The core
shall use those respective origins to calculate each line's available width
when wrapping, character-wrapping an otherwise unbreakable token, checking
horizontal fit, and selecting the uniform fitted font scale. A negative indent
may make the first line wider than continuation lines; a positive indent may
make it narrower. A line following an explicit line-break character is a
continuation line for this purpose.

For a paragraph with an explicit character bullet, the text origin for every
line shall remain the resolved left margin. Its bullet marker shall be placed
at the first-line position, calculated from the left margin plus the resolved
indent. The marker shall not be considered replacement text or consume an
additional inferred text width. This preserves PowerPoint's separate bullet
and text positions for hanging bullet paragraphs.

The PPTX adapter shall resolve the margin and indent through its master, layout,
text-frame, paragraph, and list-level precedence chain before source
measurement and replacement fitting. Both fitted document-text-layout modes
shall apply the same first-line and continuation-line widths to source
measurement and replacement fitting.

The native PowerPoint text-layout evaluator shall use the same widths and
origins for source and replacement rendering. Its explicit-properties
artifacts shall continue to report the resolved margin and indent values.
Paragraphs with no resolved margin or indent shall retain their existing
layout result. This requirement does not change line spacing, paragraph
spacing, bullet selection, tab layout, automatic-number bullets, picture
bullets, or vertical-writing layout.

### Rationale

Paragraph indentation changes the width available to text and can therefore
change wrapping, natural height, and the selected fitted font size. Treating
every line as though it began at the left margin can slightly overestimate or
underestimate the available width, particularly for translated text close to a
wrapping threshold.

### Verification

Automated tests shall use synthetic PPTX documents and repository-owned fonts
only. They shall verify a non-bulleted paragraph with a positive indent whose
first line wraps at a narrower width than its continuation lines, and a
negative indent whose first line has the corresponding wider width. They shall
verify that an explicit character-bullet paragraph keeps text at its left
margin while placing the marker at its first-line position without reducing the
measured text width a second time. Tests shall verify inherited list-level
indentation, identical fitted scales in production output and evaluator
preview, and unchanged wrapping and scale for paragraphs with no indent.

---

## FR-2026-09-06-05

| Property | Value |
|----------|-------|
| Title | Reserve a no-autofit source-height fitting margin |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following PPTX layout review |
| Date Added | 2026-09-06 |
| Related Requirements | FR-2026-08-04-01, FR-2026-08-04-04, FR-2026-08-04-05, FR-2026-09-06-04 |

### Description

For an explicit `noAutofit` PowerPoint slide-shape text frame processed in
either fitted document-text-layout mode, the replacement fitting height shall
reserve a ten-percent source-layout safety margin only when the selected
replacement output uses a committed Noto face.

The adapter shall first measure the source text's natural content height using
the existing resolved source typography, padded width, paragraph settings, and
list settings. It shall multiply that content height by `0.90`, round to the
nearest EMU, and then add the unchanged top and bottom text-frame margins. The
result is the replacement fitting height. It shall not reduce the text-frame
margins, source shape geometry, or source fitting width, and it shall not clamp
the resulting fitting height to the source shape height. An empty source layout
shall retain the existing margin-only height.

In `preserve-basic-layout`, the selected output is Noto and the margin shall
therefore apply. In `preserve-basic-layout-source-font`, the adapter shall
apply the margin when any replacement run falls back to a committed Noto face;
it shall retain the unreduced natural source height when every replacement run
uses a selected embedded or installed source face. The selection shall use the
existing source-font output selection rules; this requirement shall not change
which face is selected.

The margin applies only to the derived replacement fitting height for explicit
`noAutofit` slide-shape text frames. It does not change source rendering,
`text-to-fit-shape`, `shape-to-fit-text`, inherited or unspecified autofit,
PowerPoint table cells, or any non-PPTX adapter. Existing one-point minimum and
visible-overflow behaviour remain unchanged.

The native PowerPoint text-layout evaluator shall render the source at its
unreduced natural height, but shall fit each replacement against the reduced
height. Its replacement preview guide and explicit-properties artifact shall
record the raw natural content height, the `0.90` safety factor, and the
effective fitting rectangle.

This requirement supersedes only the replacement-fitting-height rule in
FR-2026-08-04-05. Its source-width preservation, unclamped geometry, and
source-preview behaviour remain in force except where this requirement
expressly differs.

### Rationale

The measured source height is an approximation of PowerPoint's rendered
layout. Reserving a small, deterministic portion of the source content height
gives translated text a little additional reduction when it is close to a
wrapping threshold, reducing the likelihood that it expands into nearby slide
content while preserving the source frame's intended width and margins.

### Verification

Automated tests shall use synthetic PPTX files only. They shall verify that an
explicit `noAutofit` text frame whose selected output is Noto has a replacement
fitting height equal to its source top and bottom margins plus 90 percent of
its measured natural content height, and that its selected scale is smaller
than the same fixture without the safety margin. They shall verify that a
source-font-mode replacement whose every run selects an embedded or installed
source face retains the unreduced natural height, while a replacement that
falls back to Noto receives the safety margin. They shall verify unchanged
source shape geometry, width, margins, and source preview height; matching
production and evaluator fitting rectangles and scales; recorded raw height,
factor, and effective rectangle; and unchanged fitting for every excluded
autofit and table case.

---

## FR-2026-09-06-06

| Property | Value |
|----------|-------|
| Title | Preserve inferred word separators across SmartArt formatting runs |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request and local confidential-output diagnosis |
| Date Added | 2026-09-06 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-04-11, FR-2026-09-01-01, FR-2026-09-02-05 |

### Description

For each canonical SmartArt `dgm:t` paragraph, the PPTX handler shall retain
the existing one-request-per-eligible-`a:t` replacement behaviour and its
source-run formatting. After replacement, it shall inspect each pair of
consecutive eligible text nodes in reading order that has no intervening
visible non-text content.

When the target language's primary subtag is `en`, the source boundary contains
no Unicode whitespace, neither returned replacement supplies boundary
whitespace, and the touching returned fragments form one of the following safe
English joins, the handler shall append one U+0020 space to the preceding
replacement text node:

- both touching characters are Unicode Latin letters or decimal numbers;
- the preceding character is `,`, `.`, `;`, `:`, `!`, or `?`, except when it
  separates two decimal digits, and the following character is not a closing
  delimiter;
- the preceding character is a closing bracket or parenthesis (`)`, `]`, or
  `}`), and the following character is not a delimiter; or
- the following character is an opening bracket or parenthesis (`(`, `[`, or
  `{`) and the preceding character is a word character or one of the safe
  punctuation characters above.

The inserted space shall retain the preceding node's existing run formatting
and shall be serialized with XML whitespace preservation when it is at the
edge of an `a:t` value (equivalent to an XML `&#x20;` joiner). It shall not
insert a space for another target language; when the source or either
replacement already supplies boundary whitespace; inside a delimiter pair;
around unsupported punctuation such as `/` or `-`; or when a visible non-text
element separates the nodes. It shall otherwise preserve the provider-returned
text and SmartArt XML unchanged, and shall not attempt word- or character-level
correspondence between independently translated text nodes.

This behaviour shall apply in every `--document-text-layout` mode because
SmartArt remains on its canonical diagram-data source-formatting path. It
shall not rewrite generated SmartArt drawing shapes, alter the diagram nodes,
connections, layout, styles, colours, or non-text content, or change text
replacement behaviour for WordArt or ordinary PowerPoint text frames.

### Rationale

SmartArt commonly splits a logical label into adjacent DrawingML runs to
express formatting changes. Languages such as Japanese may have no source
space at that boundary, while independently translated English fragments
require one to remain readable. The existing per-node replacement path writes
the fragments directly adjacent, causing visible word collisions. The bounded
output-only rule extends the established flowing-Word and PDF colour-emphasis
joiner rules with the conservative punctuation cases needed by English prose.
Limiting it to an English target avoids inventing spacing for CJK text or other
target-language layouts.

### Verification

Automated tests shall use synthetic PPTX SmartArt diagram-data parts only.
They shall verify in every document-text-layout mode that adjacent,
differently formatted source runs with no source whitespace receive exactly
one XML-preserved U+0020 separator for Latin words, comma/period/colon
boundaries, and opening or closing brackets; both source run-property elements
remain unchanged; and the data part remains PowerPoint-loadable. They shall
also verify decimal punctuation, delimiter-internal text, slash and hyphen
punctuation, existing source or returned whitespace, a non-`en` target, a
non-Latin output, and a visible non-text element do not receive an inferred
space. Tests shall retain the existing one request per eligible SmartArt text
node, replace-each-logical-value-once behaviour, generated-diagram-shape
exclusion, and synthetic-data-only constraint.
