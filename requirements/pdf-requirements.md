# PDF Requirements

PDF text, rendering, fitting, OCR fallback, portability, and PDF diagnostics.

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

## FR-2026-08-22-07

| Property | Value |
|----------|-------|
| Title | Use embedded PDF source fonts for source-font layout measurement |
| Owner | KrisTC |
| Status | Deferred |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-04-07, FR-2026-08-04-09, FR-2026-08-27-02 |

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
boundaries, opacity, or incompatible paint state. FR-2026-09-01-01 defines
the limited exception for otherwise compatible colour-emphasis spans. If block
classification is uncertain, it shall use independent visual-line fitting
rather than paragraph reflow.

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
cross-state grouping rule. FR-2026-09-01-01 defines that exception for an
otherwise compatible fill- or stroke-colour transition. A later transition
shall not retroactively make an earlier region in a different paint state
ineligible.

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
orientation, transform, clipping, opacity, or incompatible paint state, or
when their placement provides evidence of independent labels, columns, table
cells, or rows. FR-2026-09-01-01 defines the limited exception for otherwise
compatible fill- or stroke-colour transitions.

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
incompatible visual-state groups. A text line with an incompatible effective
paint state that lies between two proposed prose lines and occupies their
horizontal flow corridor is a non-crossable label boundary. A colour-only
paint-state difference shall be assessed under FR-2026-09-01-01. Matching
outer text colour or style shall not cause the adapter to skip an intervening
heading or label.

A single gap on one baseline is not sufficient evidence of a table boundary.
Conversely, the absence of a drawn border is not evidence that chunks are
prose. When the adapter cannot distinguish a prose continuation from
independently positioned cells or labels, it shall retain separate visual-line
regions.

The adapter may classify adjacent visual lines as one reflowable prose block
even when each line contains multiple source chunks. Eligibility requires
deterministic evidence of a shared text flow: compatible orientation and paint
state, finite bounds, consistent line spacing, and compatible alignment or
indentation. FR-2026-09-01-01 defines when a colour-only paint-state
difference remains compatible. It shall not merge across columns, repeated
cell boundaries, table-like rows, form fields, contents leaders, or
independently positioned labels.

For an eligible prose block:

- Except where FR-2026-09-01-01 applies, the adapter shall make one
  text-replacement-provider request for the complete visual block, in visual
  reading order.
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

---

## FR-2026-09-01-01

| Property | Value |
|----------|-------|
| Title | Reflow compatible PDF colour-emphasis spans as one fitted region |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following PDF translation-layout review |
| Date Added | 2026-09-01 |
| Related Requirements | FR-2026-08-23-01, FR-2026-08-23-02, FR-2026-08-23-03, FR-2026-08-29-03 |

### Description

For fitted native PDF page-content and Form-XObject text, a change only to
the effective fill or stroke paint colour shall not by itself prevent
otherwise compatible adjacent text from forming one visual line or reflowable
visual text block. Colour may be inline emphasis rather than a label or
paragraph boundary.

This requirement supersedes the colour-state boundary in
FR-2026-08-23-01 and FR-2026-08-29-03 only for such compatible
colour-emphasis spans. Every existing non-colour eligibility and safety rule
remains decisive. In particular, the adapter shall retain separate regions
when orientation, transform, clipping, opacity, rendering mode, placement,
or the existing evidence of a vector separator, recurring gutter, column,
table cell, label, or independent flow makes grouping unsafe or ambiguous.
A colour transition shall not bypass any existing treatment of source font,
size, weight, or other typography differences.

The adapter shall assemble the source text and inferred inter-chunk
boundaries for the combined visual flow exactly as it would for the same
geometry with one paint state. A paint-colour transition shall neither remove
a source whitespace boundary nor a source line-break boundary. When the
target language's primary subtag is `en`, independently translated adjacent
paint spans whose touching output characters are both letters or numbers and
whose boundary contains no whitespace shall receive one U+0020 space between
them. The inserted space shall use the preceding span's fill paint. No space
shall be inserted for another target language or adjacent punctuation.

Within an accepted combined region, the adapter shall divide the assembled
source sequence into maximal contiguous paint spans in visual reading order.
It shall send each non-empty paint span independently to the selected
text-replacement provider using the existing source and target language
settings. It shall concatenate the returned strings in that same span order,
retaining each returned string's source effective fill paint. It shall not
need to infer a word- or character-level correspondence between independently
translated strings.

The adapter shall fit and wrap the complete concatenated, paint-styled
replacement sequence as one bounded layout. It shall select one uniform fitted
font scale for the complete region and use the normal portable target-face,
wrapping, alignment, and overflow rules. A paint span may wrap across output
lines; every resulting output segment shall retain that span's source
effective fill paint. For source fill-and-stroke text, output remains
fill-only as required by FR-2026-08-23-03, using that span's source fill
paint. The adapter shall replace every source operation in the accepted region
with the one fitted, multi-colour replacement layout.

For an accepted cross-colour ordered-list item, the adapter shall use the same
independently translated, per-span paint-preserving layout defined here.
It does not change the requirement that separate ordered-list items remain
separate.

### Rationale

Colour is commonly used to emphasise a word, phrase, or sentence without
changing the intended text flow. Treating each colour as an independent
fitting region loses the shared available width and makes longer replacements
wrap, shrink, or collide unnecessarily. Independently translating each
colour-emphasis span retains the existing provider contract and gives the same
translation context as the current independent-region behaviour, while a
single styled layout restores the intended shared reflow and uniform size.

### Notes

Automated tests shall use synthetic PDFs only. They shall verify that adjacent
ordinary prose with compatible non-colour state and multiple paint colours:

- creates one fitted visual region while making one provider request per
  non-empty maximal paint span;
- preserves the established inferred whitespace and source-boundary handling
  across paint transitions;
- uses one uniform fitted font scale and reflows the concatenated replacement
  across the complete region, including a coloured span that wraps between
  output lines;
- emits each fitted output span in its corresponding source fill colour; and
- remains separate when the existing separator, table, label, column,
  clipping, opacity, transform, orientation, rendering-mode, or placement
  rules reject grouping.

Tests shall also verify the updated per-span output for a compatible
cross-colour ordered-list item and that distinct ordered-list items remain
separate. They shall use only repository-owned synthetic text, fonts, colours,
and PDFs.
