# Excel Requirements

XLSX-specific structured-table and theme-font behaviour.

## FR-2026-08-04-08

| Property | Value |
|----------|-------|
| Title | Translate structured XLSX table headers safely |
| Owner | KrisTC |
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

## FR-2026-08-22-12

| Property | Value |
|----------|-------|
| Title | Resolve XLSX workbook theme fonts for source-font fitting |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-04-07, FR-2026-08-27-02 |

### Description

For eligible XLSX cells and DrawingML text processed in
`preserve-basic-layout-source-font` mode, the XLSX adapter shall resolve the
workbook's contained theme and font-style records before calling the common
source-font resolver. It shall preserve the original style and DrawingML font
references when writing source-font output.

For worksheet cells, the adapter shall resolve an `x:font` with an `x:scheme`
value of `major` or `minor` through the workbook theme's `a:fontScheme` major
or minor slots. A direct `x:name` remains a concrete family request unless the
format specifies that the selected scheme overrides it. For DrawingML text,
the adapter shall resolve DrawingML major/minor Latin, East Asian, and
complex-script aliases under the same rules as FR-2026-08-22-10. It shall keep
script-specific requests distinct and select concrete faces per character or
contiguous script segment.

The adapter shall use only relationship-reachable theme and style parts inside
the workbook. A missing or malformed theme, unsupported scheme value, or
unresolvable script slot shall use the common Noto fallback for that segment.
It shall not make XLSX font embedding portable or fetch an external font.

### Rationale

Excel styles can request the major or minor workbook theme fonts instead of a
literal family name, while drawing text uses DrawingML's richer script-aware
font model. Resolving both paths provides metrics consistent with a workbook's
design without altering its existing style references.

### Notes

This requirement does not change finite-cell eligibility, structured-table
handling, or XLSX's lack of an interoperable embedded-font path. Automated
tests shall use synthetic workbooks with relationship-reachable themes and
both cell and drawing text. They shall verify major/minor schemes, direct-name
precedence, DrawingML aliases, script segmentation, safe fallback, and
unchanged source style references.

---

## FR-2026-09-03-05

| Property | Value |
|----------|-------|
| Title | Exclude numeric-looking XLSX text from translation |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following embedded-workbook progress diagnosis |
| Date Added | 2026-09-03 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-03-14, FR-2026-09-03-01 |

### Description

The XLSX adapter shall leave numeric-looking textual cell values and DrawingML
text unchanged in every document-text layout mode. This rule applies equally
to standalone XLSX files and relationship-reachable embedded XLSX workbooks.
Skipped values shall not invoke the text-replacement provider and shall not
contribute to nested embedded-workbook replacement progress.

Numeric-looking means an entire value matching this locale-independent ASCII
grammar: an optional `+` or `-`; either decimal digits or correctly grouped
thousands using commas; an optional `.` decimal fraction; an optional `e` or
`E` exponent with an optional sign; and an optional trailing `%`. Thus `123`,
`-12.5`, `1,234.56`, `1e6`, and `25%` are skipped. Values with currency
symbols, date or time separators, fractions, surrounding whitespace, or
Unicode decimal digits remain eligible for replacement.

### Rationale

Numeric values and identifiers stored as text can inflate translation-request
counts and add remote work without providing a translation benefit. The rule
must be deterministic across platforms and preserve values whose apparent
numeric form is intentional text.

### Notes

Automated tests shall use synthetic standalone and embedded workbooks. They
shall verify the confirmed numeric-text grammar, unchanged skipped values, no
provider requests for them, correct request totals, and unchanged translation
of non-numeric text.

---

## FR-2026-09-03-06

| Property | Value |
|----------|-------|
| Title | Support full and fast XLSX translation modes |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following a large embedded chart-data workbook |
| Date Added | 2026-09-03 |
| Related Requirements | FR-2026-08-03-03, FR-2026-09-03-01, FR-2026-09-03-03, FR-2026-09-03-05 |

### Description

The XLSX adapter shall support `full` and `fast` native-text translation modes.
Folder replacement shall use `full` mode for standalone XLSX source files by
default. The folder-replacement command and the development folder-replacement
helper shall expose `--xlsx-translation-mode full|fast`, and the helper shall
forward its selected value to every folder-replacement scenario. A DOCX adapter
processing a relationship-reachable embedded chart workbook shall always invoke
XLSX `fast` mode.

Full mode retains the established complete-workbook XLSX translation behaviour.
Fast mode shall translate only chart-relevant textual workbook cells and chart
text, plus heading rows, DrawingML text, embedded images through the normal OCR
path, and comments. A chart-relevant cell is referenced by a supported
`c:strRef` or `c:multiLvlStrRef` formula. For each referenced range, its
heading row is the first non-empty row immediately above the range; when that
row is empty or unavailable, it is the first non-empty row within the range.
Structured-table headers remain excluded under FR-2026-08-04-08. Fast mode
shall preserve unrelated worksheet cells, formulas, workbook metadata, and
numeric chart data unchanged. For chart-relevant workbook cells, it shall
update every corresponding chart string cache so the visible chart and **Edit
Data in Excel** agree without a refresh.

### Rationale

Some workbooks contain large supporting sheets unrelated to displayed charts.
Fast mode avoids sending that material for translation while retaining the
visible chart labels and adjacent user-facing content needed to understand the
workbook.

### Notes

Automated tests shall use synthetic standalone XLSX files and DOCX packages
with embedded workbooks. They shall verify full-mode default behaviour;
fast-mode selection; only selected chart labels, headings, drawings, OCR image
text, and comments invoking their respective providers; synchronized chart
caches; unchanged unrelated text-heavy cells; safe unsupported-reference
fallback; correct progress totals; and repair-free opening in Word and Excel.

---

## FR-2026-09-04-01

| Property | Value |
|----------|-------|
| Title | Expand fast XLSX selection while avoiding unrelated large worksheets |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-09-04 |
| Related Requirements | FR-2026-08-03-04, FR-2026-09-03-01, FR-2026-09-03-05, FR-2026-09-03-06 |

### Description

In XLSX `fast` mode, the adapter shall additionally select all eligible text
cells in every worksheet with no more than 1,000 rows, subject to the existing
numeric-looking-text exclusion and structured-table-header exclusion. This
selection is in addition to the chart-relevant cells and heading rows defined
by FR-2026-09-03-06. A worksheet's row count is the highest row index that
contains a stored cell in its used range; a sparse worksheet with a stored cell
in row 1,001 is therefore not a small worksheet.

The adapter shall determine whether a worksheet exceeds the 1,000-row limit
without building an in-memory XML tree for the entire worksheet; it may stop
the inspection once it finds a stored cell beyond row 1,000. A large worksheet
with no chart-relevant cells shall be copied without XML parsing or XML
serialization. A large worksheet containing chart-relevant cells shall use a
selective traversal that processes only the chart-relevant cells and required
heading cells without materializing or serializing unrelated cells.

Fast mode shall construct its output XLSX package once. It shall combine the
generic chart/comment and media changes, selected-cell changes, and chart-cache
changes in that one output construction; it shall not write intermediate whole
XLSX packages or repeatedly reserialize an unchanged large worksheet. Chart
cache synchronization shall derive worksheet values only for chart-referenced
cells rather than scan every cell in every worksheet.

For a standalone XLSX processed in `fast` mode, the folder-replacement Current
progress row shall advance once for every eligible replacement request, using
the same exact count and part-identifying labels as the embedded-workbook
progress row. It shall additionally include chart-cache synchronization and
final package output. It shall calculate that total before processing using the
same selection rules, advance an item only after the corresponding work
completes, and not report 100% while a remaining fast-mode stage is running.
The active-operation label shall identify the active worksheet or package stage
without exposing source text.

When diagnostics are enabled, the source diagnostic sidecar shall contain one
safe `xlsx_fast_mode_worksheet_skipped` entry for every large worksheet skipped
by fast mode. An entry shall identify the worksheet name and package part, but
shall not record any worksheet cell content. For an embedded workbook, these
entries shall be written to the enclosing DOCX source's diagnostic sidecar.

### Rationale

Small worksheets commonly contain user-facing labels throughout the sheet, so
translating them in fast mode is useful. Large supporting sheets should not
turn fast mode into multiple full-package rewrites or full XML traversals when
they contain no visible chart labels.

### Notes

Automated tests shall use synthetic workbooks and verify the 1,000-row
boundary; chart-derived selection; existing exclusions; unchanged large,
unreferenced worksheet XML; a single package output construction; limited
chart-cache worksheet traversal; replacement-request progress; and no early
current-task completion. They shall also verify standalone and embedded
diagnostic sidecars list skipped worksheet names without cell content.

---
