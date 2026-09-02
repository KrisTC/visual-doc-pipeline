# Word Requirements

DOCX-specific fitting and font behaviour.

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

## FR-2026-08-22-05

| Property | Value |
|----------|-------|
| Title | Use embedded DOCX source fonts for source-font layout measurement |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-22-03, FR-2026-08-27-02 |

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
rules in FR-2026-08-27-02.

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

## FR-2026-08-22-11

| Property | Value |
|----------|-------|
| Title | Resolve DOCX inherited typography for fitted layout |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-27-02, FR-2026-08-22-05 |

### Description

For eligible DOCX DrawingML text containers processed in a fitted
document-text layout mode, the DOCX adapter shall resolve WordprocessingML
run-font settings and font size through direct run properties, applicable
character and paragraph styles, document defaults, and the document theme
before fitting. It shall preserve the original WordprocessingML references
when writing source-font output.

When a text-box paragraph has no explicit `w:pStyle`, the adapter shall apply
the default paragraph style declared by `w:style/@w:default="1"` in the
document's `word/styles.xml`, including its `w:basedOn` chain. The default
paragraph style's `w:sz` shall supply the effective source size when no later
paragraph, character, or direct-run property overrides it. This is the
template default used by Word; the adapter shall not substitute its generic
18-point fallback while that value is available.

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
with document defaults, a default paragraph style, styles, and
relationship-reachable themes; they shall verify direct overrides, default
paragraph-style size inheritance, each theme font attribute, script
segmentation, fallbacks, and unchanged serialized source references.

---

## FR-2026-09-02-05

| Property | Value |
|----------|-------|
| Title | Translate flowing Word paragraphs in maximal emphasis-preserving runs |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following DOCX translation-quality review |
| Date Added | 2026-09-02 |
| Related Requirements | FR-2026-08-02-06, FR-2026-08-03-03, FR-2026-08-03-14, FR-2026-08-04-07, FR-2026-09-01-01 |

### Description

For every eligible ordinary, flowing WordprocessingML `w:p` paragraph, the
DOCX adapter shall assemble its visible text in Word reading order into maximal
contiguous emphasis runs. It shall make one text-replacement request for each
non-empty maximal run, rather than independently translating adjacent `w:t`
text nodes or source formatting runs. This applies in every document-text
layout mode because flowing Word paragraphs remain outside the bounded-layout
path.

An emphasis run is delimited only by a change in its effective text colour,
superscript or subscript setting, or strikethrough setting. The adapter shall
preserve those three emphasis properties in the corresponding replacement run.
Differences in other source run formatting shall not split an emphasis run;
the replacement shall use the dominant source style within that emphasis run,
where the dominant style is the style with the greatest number of
non-whitespace visible characters and the first run wins a tie. The adapter
shall preserve paragraph properties and retain the existing source font, size,
and no-reflow behaviour for each selected dominant style.

The adapter shall concatenate returned emphasis-run replacements in source
order. Adjacent replacement runs whose touching output characters are both
Unicode Latin letters or decimal numbers and whose source boundary contains no
whitespace shall receive one U+0020 space between them. The inserted space
shall use the preceding run's emphasis formatting. It shall not insert a space
for non-Latin output, adjacent punctuation, or when either returned
replacement already supplies boundary whitespace. The adapter shall otherwise
write provider-returned text unchanged; it shall not attempt word- or
character-level correspondence between source and translated runs.

The adapter shall preserve Word's non-text paragraph structure, including
paragraph properties, bookmarks, comments, fields, hyperlinks, tabs, manual
line breaks, and tracked-content boundaries. A paragraph whose visible text
cannot be safely represented as the required sequence of emphasis-run requests
while preserving that structure shall retain the structure and translate every
eligible visible text node in its original reading order using the existing
direct text-node replacement path. It shall not leave eligible visible source
text unchanged solely because the paragraph cannot use maximal emphasis-run
replacement. This is a translation-quality fallback, not an unsupported-text
outcome. Bounded DOCX drawing text containers continue to use their existing
paragraph-level shared fitting path and are not regressed by this requirement.

Automated tests shall use synthetic DOCX packages only. They shall verify that
adjacent same-emphasis source runs form one maximal provider request, while
colour, superscript, subscript, and strikethrough transitions form separate
requests and retain their corresponding output emphasis. They shall verify
that independently translated adjacent Latin alphanumeric runs with no source
whitespace receive exactly one correctly formatted U+0020 joiner, and that no
joiner is added for existing whitespace, punctuation, or non-Latin output.
They shall also verify dominant-style selection, preservation of paragraph
properties and safe non-text structure, no reflow or fitted-font embedding for
flowing text, direct text-node translation with unchanged non-text structure
for a mixed-content paragraph, and unchanged bounded-text-container behaviour.
Tests and fixtures shall not use confidential documents or derived artifacts.

### Rationale

Word run boundaries record formatting and editing structure, not translation
boundaries. Translating each run independently gives a translation provider
unnecessarily small fragments. Merging all formatting that is not requested
emphasis maximises context while retaining colour, vertical-position, and
strikethrough cues. In scripts that normally omit spaces, independently
translated English emphasis runs can otherwise meet without a separator.

---

## FR-2026-09-02-06

| Property | Value |
|----------|-------|
| Title | Diagnose flowing Word paragraph structure fallbacks |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following DOCX translation-quality regression diagnosis |
| Date Added | 2026-09-02 |
| Related Requirements | FR-2026-08-27-06, FR-2026-09-02-05 |

### Description

In a debug-enabled folder-replacement run, the DOCX adapter shall add one
`fallback` entry to the existing per-document diagnostic sidecar for every
flowing Word paragraph that uses FR-2026-09-02-05's direct text-node
structure fallback. It shall not call the text-replacement provider again
merely to populate diagnostics.

Each entry shall contain the stable reason code
`docx_flowing_paragraph_structure_fallback`, container kind
`docx_flowing_paragraph`, the Word package part, the zero-based paragraph
index within that part, the paragraph's visible source text, and one or more
stable structure-reason codes. The initial structure-reason codes shall
distinguish a non-run paragraph child, a run without visible text, and each
unsupported run child by its WordprocessingML local name. The entry shall
identify the effective layout mode. It shall not contain translated text,
credentials, provider configuration, paths outside the existing sidecar
schema, or raw XML.

Ordinary runs shall remain silent. The sidecar remains a local output artifact
governed by FR-2026-08-27-06 and the confidential-sample rule; it shall not be
staged, committed, uploaded, or quoted.

Automated tests shall use synthetic DOCX packages only. They shall verify one
entry each for representative bookmark, hyperlink, and unsupported run-child
paragraphs; stable package-part and paragraph-index locations; source-text
recording; direct text-node translation while preserving the fallback
paragraph's non-text structure; no additional provider request to populate the
entry; sidecar omission when debug is disabled; and unchanged maximal-run
translation of adjacent eligible paragraphs.

### Rationale

Word paragraphs can contain harmless-looking structural markup that prevents a
safe maximal-run rewrite. A local, precise diagnostic makes the resulting
translation-quality fallback visible, rather than confusing it with a
translation-provider failure or leaving text untranslated.

---

## FR-2026-09-02-07

| Property | Value |
|----------|-------|
| Title | Preserve and translate Word caption cross-references |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following DOCX cross-reference regression diagnosis |
| Date Added | 2026-09-02 |
| Related Requirements | FR-2026-08-27-06, FR-2026-09-02-05, FR-2026-09-02-06 |

### Description

The DOCX adapter shall recognise balanced WordprocessingML complex fields made
from `w:fldChar` begin, separate, and end markers, and shall recognise their
`w:instrText` instructions without sending those instructions to the
text-replacement provider. It shall support caption source fields using `SEQ`
and live cross-reference fields using `REF` and `PAGEREF`, including a
cross-reference wrapped in a Word hyperlink.

For a supported live caption cross-reference, the adapter shall resolve the
bookmark named by the reference instruction to its caption source in the same
DOCX package. It shall translate the caption's visible display text and write
a consistent translated display result into every linked cross-reference. It
shall apply the ordinary maximal emphasis-run and Latin joiner rules to text
outside the field result. It shall not translate a reference result as an
independent text-node fragment when its source bookmark resolves successfully.

The adapter shall preserve the live-reference structure: every `w:fldChar` and
`w:instrText` element, the original field instruction, bookmark name and ID,
bookmark range, hyperlink wrapper and relationship, and `SEQ` identifier shall
remain present and in their original relative order. It shall update only
visible field-result text and other eligible visible text. It shall not unlink
the field, convert it to static text, rename a bookmark, remove a `SEQ` field,
or turn a cross-reference into an ordinary non-linking run. The resulting DOCX
shall retain caption sources and their targets in Microsoft Word's
Cross-reference dialog.

A missing, malformed, unbalanced, ambiguous, cross-story, or unsupported field
or bookmark relationship shall not corrupt the document or leave eligible
visible text untranslated. The adapter shall retain the field structure and
use FR-2026-09-02-05's direct visible-text fallback for only the affected
field result. In a debug-enabled run it shall add one `fallback` diagnostic
entry identifying the field kind, package part, paragraph index, field-result
text, bookmark identity when safely available, and a stable reason code. It
shall not make an additional replacement-provider request merely for
diagnostics.

Automated tests shall use synthetic DOCX packages only. They shall verify a
caption `SEQ` field inside a named bookmark with one or more linked `REF`
fields, including a hyperlink-wrapped reference. They shall verify source and
linked results receive the same translated caption text; field instructions,
markers, bookmark names and IDs, bookmark ranges, hyperlink markup and
relationships remain valid; and a DOCX parser loads the output. They shall
also verify missing, malformed, and ambiguous references preserve their field
structure, translate their visible result through the documented fallback, and
emit the expected debug diagnostic. Tests shall use synthetic text, bookmark
names, and relationships only.

The repository shall retain a Microsoft Word smoke-test procedure for the
synthetic output. It shall confirm that the caption remains listed under its
reference type in the Cross-reference dialog and that inserting a new linked
cross-reference succeeds without repairing or unlinking the existing fields.

### Rationale

Caption text and a cross-reference's displayed result are two views of one
semantic source. Treating their serialized runs independently produces poor
translation and can invalidate the OOXML structures Word uses to discover
captions and create links. Resolving the bookmark relationship preserves both
translation consistency and the document's live-reference behaviour.

---

## FR-2026-09-02-08

| Property | Value |
|----------|-------|
| Title | Preserve field order and safe joins in flowing Word text |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following DOCX page-field ordering diagnosis |
| Date Added | 2026-09-02 |
| Related Requirements | FR-2026-09-02-05, FR-2026-09-02-07 |

### Description

This requirement applies uniformly to every flowing WordprocessingML
paragraph in every Word story, including document body, header, footer,
footnote, endnote, comment, and glossary parts. It shall not introduce
header- or footer-specific replacement behaviour.

Every balanced complex-field boundary made from `w:fldChar` begin, separate,
and end markers shall be a hard boundary for surrounding ordinary text. The
adapter shall not combine, move, or clear visible text nodes that occur on
opposite sides of a field, even when the field is otherwise unsupported or its
visible cached result uses FR-2026-09-02-05's direct visible-text fallback.
It shall preserve the source reading order of literal text, field instructions,
and field results.

The adapter shall recognise `PAGE`, `NUMPAGES`, `SECTION`, and
`SECTIONPAGES` as dynamic numeric system fields. It shall preserve their field
instructions and cached visible results unchanged and shall not submit those
cached values to the text-replacement provider. `SEQ`, `REF`, and `PAGEREF`
semantic resolution remains governed by FR-2026-09-02-07; the field-boundary
and safe-join rules in this requirement apply equally while processing those
fields. Other unsupported fields retain their existing direct visible-text
fallback without permitting ordinary text to cross their structural boundary.

The existing Latin/digit joiner rule shall also apply between a field display
and adjacent eligible ordinary replacement text. When the touching returned
characters are both Unicode Latin letters or decimal numbers, neither source
side supplies boundary whitespace, and neither touching output character is
punctuation, the adapter shall add exactly one U+0020 space after the preceding
field display in a separate run using its preceding formatting; it shall not
alter the field's cached result to add that space. It shall not add a space
before or after punctuation, including a slash, nor where either side already
has boundary whitespace. It shall not attempt unconditional field spacing
because that would corrupt page-number, abbreviation, code, and punctuation
layouts. For a `SEQ` field followed by its ordinary caption title, the adapter
shall apply the same returned-Latin-or-digit and punctuation checks even when
the source boundary has whitespace, because a translation provider may consume
that source delimiter. It shall still not add a second space when either
returned boundary already has whitespace.

Automated tests shall use synthetic DOCX packages only. They shall verify a
flowing `P. { PAGE } / { NUMPAGES }` paragraph in a non-body Word story,
confirm that its literal separators and field order remain unchanged, confirm
that the provider receives neither numeric cached result, and confirm that the
output package parses successfully. They shall also verify an equivalent body
paragraph to demonstrate that story type does not affect the behaviour, an
unsupported-field fallback does not merge text across that field, and the
field-to-ordinary-text joiner adds a space only under the specified
language-safe conditions. Tests and fixtures shall not use confidential
documents or derived artifacts.

### Rationale

Field markers define both live Word behaviour and visible-text boundaries.
Ignoring an unsupported field while rebuilding neighbouring text can shift a
separator across the field, making a page reference appear reordered even
though its field instructions remain in sequence. Dynamic counters are not
translation content, while translated prose immediately after a field can
still need the same safe Latin separator already required for emphasis runs.

---

## FR-2026-09-02-09

| Property | Value |
|----------|-------|
| Title | Preserve Table of Contents field layout during DOCX translation |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following DOCX Table of Contents layout review |
| Date Added | 2026-09-02 |
| Related Requirements | FR-2026-09-02-05, FR-2026-09-02-07, FR-2026-09-02-08 |

### Description

The DOCX adapter shall recognise the visible result of a complex `TOC` field,
including a `TOC` field that spans multiple Word paragraphs and contains
nested hyperlinks and `PAGEREF` fields. This is a field-context rule, not a
header, footer, or story-type special case.

Within a `TOC` field result, the adapter shall translate eligible visible TOC
entry text but shall not insert any pipeline-generated U+0020 joiner between
field results, ordinary runs, hyperlinks, tabs, dot leaders, or page-number
results. It shall preserve the source order and placement of tabs, leader
settings, hyperlinks, and page-number field markup. A nested TOC `PAGEREF`
field's cached page-number result shall remain unchanged and shall not be sent
to the text-replacement provider.

Outside the `TOC` field result, FR-2026-09-02-05, FR-2026-09-02-07, and
FR-2026-09-02-08 continue to apply unchanged. In particular, this requirement
does not suppress the required safe joiner between a caption `SEQ` field and
its following caption title.

Automated tests shall use a synthetic DOCX package containing a multi-paragraph
`TOC` result with hyperlink-wrapped entry text, tab stops with dot leaders, and
nested `PAGEREF` page fields. They shall verify translated entry text, unchanged
page-number cached results, no provider request for those page numbers, no
pipeline-inserted whitespace in the TOC result, unchanged field and hyperlink
structure, preserved tabs and leader settings, and successful DOCX parsing.
Tests and fixtures shall not use confidential documents or derived artifacts.

### Rationale

Word lays out a Table of Contents as a compact field result whose tabs and
leaders position page numbers. A generally safe prose separator consumes part
of that fixed layout and can wrap page values onto another line. Captions have
ordinary prose after their sequence number, so they need the normal joiner;
TOC entries instead require their existing tab-driven layout.

---
