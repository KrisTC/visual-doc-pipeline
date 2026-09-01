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
| Title | Resolve DOCX theme fonts for source-font fitting |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-27-02, FR-2026-08-22-05 |

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
