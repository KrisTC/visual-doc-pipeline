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
