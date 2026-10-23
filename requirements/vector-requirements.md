# Vector Graphic Requirements

SVG, EMF, WMF, and editable vector-graphic processing.

## FR-2026-08-03-05

| Property | Value |
|----------|-------|
| Title | Replace editable text in embedded vector graphics directly |
| Owner | KrisTC |
| Status | Proposed |
| Source | Implementation diagnosis |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-03 |

### Description

The folder-replacement pipeline shall replace editable text contained in embedded vector graphics in supported document files by directly updating the vector graphic's native text representation. It shall send each vector-text item to the selected text-replacement provider with `is_filename=False`, the command's source language, and target language.

It shall not use OCR or rasterize a vector graphic to replace its text. It shall preserve the graphic as vector output and retain non-text vector content unchanged.

When a vector graphic's visible text is represented only by paths or outlines, rather than an editable native text representation, the current implementation shall retain it unchanged and report that it was not replaced. Rasterizing it and using the existing bitmap path is deferred to a future requirement.

### Rationale

Visible text may be part of a vector graphic rather than a native document text run or a raster bitmap. Direct native-text replacement preserves the graphic's fidelity and avoids unnecessary OCR cost and recognition errors.

### Notes

The initial supported embedded vector formats are SVG, EMF, and WMF. The implementation shall identify and update their editable native text structures directly. Direct mutation is format-specific; the implementation must not treat the formats as interchangeable.

The initial direct-text implementation supports SVG `text`, `tspan`, and `textPath` content; EMF `EMR_EXTTEXTOUTA` and `EMR_EXTTEXTOUTW` records; and WMF `META_TEXTOUT` and `META_EXTTEXTOUT` records. A vector graphic with none of these editable text structures is retained unchanged and reported as unsupported. Additional vector text-record variants require a future requirement.

The current locked Python image stack has no usable EMF or WMF rasterizer. Implementing the deferred outlined-text fallback requires a separately specified, dependency-policy-compliant renderer and an output-reembedding strategy for replacing the original vector package part with its processed bitmap result.

A renderer that requires a commercial license shall not be used in evaluation mode: generated documents must not contain evaluation watermarks or other licensing artifacts. Its license file, key, or equivalent credential shall not be committed, logged, or included in generated artifacts. The licence configuration and deployment mechanism require a separate approved requirement before such a renderer is added.

---

## FR-2026-08-03-06

| Property | Value |
|----------|-------|
| Title | Comment on unsupported images in Office documents |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-03-05 |

### Description

When processing a Word, Excel, or PowerPoint document, the pipeline shall add a document-native comment for every image whose text cannot be processed. The comment shall state that the image contains text that is not supported yet.

### Rationale

Comments make unreplaced visible text reviewable without altering the source image or silently implying that its content was processed.

### Notes

Before implementation, define which conditions create a comment (for example, a vector with no editable text, OCR failure, or every skipped low-confidence OCR region); the exact comment text; comment author/identity; and the required anchor for Word, Excel, and PowerPoint comments. The implementation shall not replace the requested comment with a visible text box, speaker note, cell value, or other non-comment artifact.

---

## FR-2026-08-03-09

| Property | Value |
|----------|-------|
| Title | Replace raster DIBs embedded in EMF graphics |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-03-05, TR-2026-08-03-01 |

### Description

When an embedded EMF graphic contains a raster DIB payload in an `EMR_STRETCHDIBITS` record, the folder-replacement pipeline shall decode that payload in memory and process it through the existing shared bitmap OCR and text-replacement path. It shall re-embed the resulting DIB in the same EMF record, retaining the EMF graphic and its other vector content.

The raster DIB path shall use the selected OCR and text-replacement providers, source and target languages, typeface, confidence threshold, colour estimation, and batch text-region rendering already used for standalone and Office-embedded bitmap images. Its replaced OCR-region count shall contribute to the document's image-region result.

### Rationale

An EMF can combine editable vector text with already-rasterized visual content. Processing DIB payloads directly covers that contained bitmap content without requiring an EMF renderer or rasterizing the whole vector graphic.

### Notes

The initial scope is `EMR_STRETCHDIBITS`. Other EMF bitmap record types and outlined or path-only vector text remain out of scope until separately specified; FR-2026-10-22-14 specifies EMF+ image objects. The DIB shall be processed only in memory and shall invoke the existing shared raster handler; no intermediate image file is permitted.

Automated tests shall use a synthetic EMF containing a DIB payload. They shall verify that the shared image processor is invoked, its result is re-embedded, and unrelated EMF records remain valid.

---

## FR-2026-08-03-10

| Property | Value |
|----------|-------|
| Title | Separate vector format handlers and support standalone vector inputs |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-03-05, TR-2026-08-03-01 |

### Description

The vector-replacement implementation shall provide separate SVG, EMF, and WMF modules, with a small dispatcher and shared result and DIB helpers. FR-2026-10-22-09 defines how the dispatcher identifies EMF and WMF content. Standalone `.svg`, `.emf`, and `.wmf` input files shall be supported by the folder command and shall use the same in-memory format handler as an embedded Office vector part.

### Rationale

The vector formats have distinct binary and XML structures that need independent iteration. Sharing the one in-memory entry point prevents different behaviour for standalone and embedded graphics.

### Notes

The existing shared bitmap handler remains the sole raster text-replacement implementation. Vector handlers shall pass a decoded embedded bitmap directly to it and shall not write intermediate files.

---

## FR-2026-08-03-11

| Property | Value |
|----------|-------|
| Title | Replace self-contained SVG raster images |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-03-10, SR-2026-08-03-02 |

### Description

The SVG handler shall process a raster image referenced by an SVG `image` element only when the image is a supported bitmap encoded as a `data:` URI in that SVG. It shall decode the bitmap in memory, apply the shared bitmap OCR and text-replacement handler, and update the same `data:` URI when one or more OCR regions are replaced.

### Rationale

An SVG can combine editable text and an embedded raster image. Supporting self-contained raster data covers the image without requiring a renderer or an external resource.

### Notes

Nested SVG, video, canvas, foreign-object content, malformed data URIs, and non-supported image MIME types remain unchanged until separately specified.

---

## FR-2026-08-03-12

| Property | Value |
|----------|-------|
| Title | Replace self-contained WMF DIB bitmap records |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-03-10 |

### Description

The WMF handler shall decode and process the self-contained source DIB in `META_STRETCHDIB` records through the shared bitmap OCR and text-replacement handler, then re-embed the resulting DIB in the same record. Its replaced OCR-region count shall contribute to the folder result.

### Rationale

WMF supports raster DIB content alongside its native drawing and text records. Processing the DIB directly preserves the surrounding WMF without requiring a WMF renderer.

### Notes

The initial scope is `META_STRETCHDIB`. Other WMF bitmap records, compressed DIB payloads, and vector text represented only by outlines remain out of scope until separately specified.

---

## FR-2026-08-22-08

| Property | Value |
|----------|-------|
| Title | Use embedded SVG source fonts for source-font layout measurement |
| Owner | KrisTC |
| Status | Proposed |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-04-07, FR-2026-08-27-02 |

### Description

For an eligible bounded SVG text container processed in
`preserve-basic-layout-source-font` mode, the SVG adapter shall discover an
embedded `@font-face` only when its source is a contained `data:` URI in that
same SVG and its decoded bytes load as a Skia typeface. It shall map the
embedded face's declared family and style to the source text request before
offering it to the common source-font resolver.

The adapter shall not open or fetch any external stylesheet, URL, path, or
package-relative font reference. It shall preserve the original stylesheet and
embedded data unchanged. Unsupported data formats, malformed CSS, malformed
data URIs, style mismatches, and missing replacement glyphs shall use the
general fallback rules.

### Rationale

An inline SVG font is a self-contained source of the intended typeface, whereas
an external font reference crosses the pipeline's existing external-resource
security boundary.

### Notes

Automated tests shall use synthetic SVGs with inline repository-owned test-font
data. They shall verify matching selection and all fallback conditions, and
shall verify that external font URLs are neither opened nor reported as
available.

---

## FR-2026-08-22-13

| Property | Value |
|----------|-------|
| Title | Resolve SVG CSS font inheritance and stacks for source-font fitting |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-22 |
| Related Requirements | FR-2026-08-27-02, FR-2026-08-22-08 |

### Description

For eligible SVG text processed in `preserve-basic-layout-source-font` mode,
the SVG adapter shall compute the applicable `font-family`, `font-weight`, and
`font-style` from the element, inherited SVG/CSS properties, and contained
`style` rules before calling the common source-font resolver. It shall preserve
the original SVG and CSS font declarations in source-font output.

The adapter shall parse a CSS `font-family` list as an ordered set of concrete
family candidates. For each character or contiguous script segment it shall
offer candidates in CSS order to the common resolver, selecting the first
exact embedded or installed face that matches the requested style and covers
the segment's glyphs. If none is usable, it shall use the common Noto fallback.
Generic CSS family names and unsupported CSS expressions shall not be mistaken
for installed family names; they shall follow an explicitly specified fallback
policy before Noto is selected.

The adapter shall process only styles and `@font-face` data contained inside
the SVG. It shall not load external stylesheets, URLs, paths, CSS imports, or
font resources. Inline embedded-font use remains subject to FR-2026-08-22-08.

### Rationale

SVG typography is usually governed by CSS inheritance and ordered fallback
stacks, rather than a single direct family attribute. Computing the effective
stack lets source-font measurement follow the author’s intended fallback order
without crossing the existing external-resource trust boundary.

### Notes

This requirement does not add general HTML/CSS layout support. The supported
selector subset is element, `.class`, `#id`, and descendant combinations of
those forms, using ordinary specificity and source-order precedence.
Custom properties and `var()` are unsupported: a declaration using `var()` is
ignored. `serif`, `monospace`, and `sans-serif` map respectively to the
committed Noto serif, mono, and sans fallback classifications; they are never
accepted as a host-family match. Text inside `foreignObject` is outside this
fitted SVG-text scope. Automated tests shall use synthetic SVGs with inline
styles and repository-owned test fonts; they shall verify inheritance, stack
order, style matching, glyph fallback, malformed-CSS fallback, and that no
external reference is opened.

---

## FR-2026-09-04-01

| Property | Value |
|----------|-------|
| Title | Fit un-clipped horizontal EMF text to measured source geometry |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following EMF table-label diagnosis |
| Date Added | 2026-09-04 |
| Related Requirements | FR-2026-08-03-05, FR-2026-08-03-07, FR-2026-08-03-14, FR-2026-08-04-07, FR-2026-08-27-02, FR-2026-09-05-02, FR-2026-10-22-11 |

### Description

This requirement defines fitted-layout eligibility for editable EMF
`EMR_EXTTEXTOUTA` and `EMR_EXTTEXTOUTW` records that have no explicit clipping
rectangle. It does not change `preserve-source-formatting`, which shall retain
its existing direct native text replacement behaviour. FR-2026-09-05-02
supersedes this requirement's per-record fitting and expansion behaviour for
an eligible contiguous text record group.

In either fitted layout mode, the EMF adapter shall first reconstruct the
selected source GDI font and original horizontal text placement.  It shall
measure the original non-empty, single-line text at its original size to derive
its occupied source rectangle.  A record with a non-degenerate rendered bounds
rectangle shall use the measured rectangle as its source rectangle when it lies
within those bounds, and otherwise shall use the record bounds themselves. A
measurement that differs from the bounds shall not make the record ineligible.
A record without non-degenerate bounds shall use the measured rectangle
positioned from the record's origin and alignment.

`preserve-basic-layout` shall measure the source text with the appropriate
committed Noto face.  `preserve-basic-layout-source-font` shall first measure
with the resolved source face when it is available and usable, and otherwise
shall measure with the appropriate committed Noto face.  Replacement-face
selection and fitting shall follow FR-2026-08-27-02.  As ordinary EMF has no
safe portable font-embedding path, the output shall retain its source font
reference while applying the selected fitting scale.

For a record not selected for a group by FR-2026-09-05-02, the measured source
rectangle shall be the default replacement fitting bound. For a source record
and returned replacement that each contain one horizontal line, the adapter
may expand that bound along the baseline only into verified empty space. It
shall not expand vertically or introduce a new line. It shall stop before the
nearest intersecting source-text rectangle or a recognised vector line segment.
The complete fitted replacement glyph bounds shall remain within the resulting
rectangle and shall not intersect another source-text rectangle or recognised
vector line segment. A left-aligned record may expand rightward, a
right-aligned record may expand leftward, and a centred record may expand
symmetrically. Expansion shall also stop at the finite, non-degenerate EMF
header `rclBounds` rectangle. When that outer bound cannot be reconciled with
the record's coordinate system, the adapter shall retain the measured source
rectangle and shall not infer outer free space.

The initial eligible geometry is ordinary, axis-aligned horizontal text and
axis-aligned `EMR_MOVETOEX`/`EMR_LINETO` line segments in a safely resolved EMF
coordinate system.  The adapter shall not infer table cells, paragraph blocks,
or obstacles from arbitrary paths, fills, images, rotations, shears,
unresolved transforms, or ambiguous graphics state.  An unsupported or
ambiguous record shall retain the existing `preserve-source-formatting`
fallback rather than risk crossing a line or other text.

### Rationale

EMF drawings often encode table and heading labels as independent text records
without a clipping rectangle.  Measuring the original visual line provides a
safe default bound.  Limited expansion into evidenced empty horizontal space
preserves readable translated headings while retaining table rules and
neighbouring values as hard layout boundaries.

### Notes

The adapter may use the shared bounded-text layout core for face selection and
fitting, but it must retain one-line EMF output semantics. It must not use OCR
or rasterize the EMF graphic for this feature. FR-2026-09-05-02 defines the
limited exception that treats multiple source records as one one-line output.

Automated tests shall use synthetic EMF inputs only.  They shall verify
Noto-only source measurement in `preserve-basic-layout`; source-face
measurement and Noto fallback in `preserve-basic-layout-source-font`; fitting
to the measured source rectangle; fitting a record whose measurement is wider
than its bounds into those bounds; measuring a record without bounds from its
origin; permitted horizontal expansion; stopping at
both an adjacent text rectangle and a vertical line segment; alignment-aware
expansion; and unchanged direct replacement for multi-line, rotated,
transformed, ambiguous, or otherwise ineligible records.  Tests shall verify
that generated EMF files remain structurally valid.

---

## FR-2026-09-05-01

| Property | Value |
|----------|-------|
| Title | Fit EMF text through resolvable affine transforms |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following transformed-EMF PowerPoint diagnosis |
| Date Added | 2026-09-05 |
| Related Requirements | FR-2026-08-03-05, FR-2026-08-03-07, FR-2026-08-03-14, FR-2026-08-04-07, FR-2026-08-27-02, FR-2026-09-04-01, FR-2026-09-05-02 |

### Description

This requirement extends the EMF fitted-layout eligibility of
FR-2026-09-04-01 to editable `EMR_EXTTEXTOUTA` and `EMR_EXTTEXTOUTW` records
whose effective affine coordinate transform is finite and invertible.  It
includes translation, uniform or non-uniform scale, reflection, rotation at
any angle, shear, and compositions of those operations.  It supersedes
FR-2026-09-04-01's transformed-record fallback only for records that meet
this requirement. `preserve-source-formatting` shall retain its existing
direct native-text replacement behaviour. FR-2026-09-05-02 supersedes this
requirement's per-record fitting and expansion behaviour for an eligible
contiguous text record group.

For every eligible record, the adapter shall reconstruct the effective
logical-to-rendered coordinate transform from the EMF device-context state.
It shall process `EMR_SETWORLDTRANSFORM` and every
`EMR_MODIFYWORLDTRANSFORM` operation according to its declared composition
mode, along with `EMR_SETWINDOWORGEX`, `EMR_SETWINDOWEXTEX`,
`EMR_SETVIEWPORTORGEX`, `EMR_SETVIEWPORTEXTEX`,
`EMR_SCALEWINDOWEXTEX`, `EMR_SCALEVIEWPORTEXTEX`, and the active map and
graphics modes.  It shall preserve and restore that state through EMF
save/restore-device-context operations.  A pure translation shall not make a
record ineligible.

The adapter shall use the effective transform and the applicable GDI text
semantics to express source text rectangles, source baselines, and explicit
clip rectangles in one rendered coordinate space.  It shall then apply the
existing source measurement and replacement-face selection rules.  Existing
explicit-clip fitting shall use the transformed clip geometry.

For every eligible transform not selected for a group by FR-2026-09-05-02, the
transformed measured source rectangle shall be the replacement fitting bound.
The adapter shall apply at most a uniform downscale to the replacement and
shall retain the source text position and effective transform. The complete
transformed replacement glyph bounds shall remain inside that source bound.
This source-bound-only fitting rule applies to rotated, reflected, sheared,
and otherwise non-axis-aligned transforms. It shall not expand the bound,
infer free space, or attempt neighbour or line-obstacle avoidance for those
transforms.

For an orientation-preserving, axis-aligned transform consisting only of
translation and positive horizontal and vertical scale, the adapter shall
also apply the existing un-clipped free-space expansion rule from
FR-2026-09-04-01 to an individual record not selected for a group by
FR-2026-09-05-02. It may expand only along the horizontal source baseline into
verified empty space, stopping before transformed source-text rectangles and
recognised `EMR_MOVETOEX`/`EMR_LINETO` line segments. The complete fitted
replacement glyph bounds shall remain within the expanded bound and shall not
intersect those obstacles or the finite, non-degenerate EMF header `rclBounds`
rectangle. When the header bounds cannot be reconciled with the record's
rendered coordinate system, the adapter shall retain the transformed measured
source rectangle and shall not infer outer free space.

The output shall retain the source text position, orientation, reflection,
and effective transform.  It may add or select a cloned GDI font only to
apply the uniform fitted scale required by the shared bounded-text layout
result.  It shall not rasterize the EMF, convert text to outlines, reorder
painting operations, alter unrelated graphics state, or replace a text record
more than once.  A replacement that cannot fit at the one-pixel minimum shall
remain visible as overflow according to the shared fitted-layout rule, rather
than silently clipping or retaining source-language text.

The adapter shall retain the direct `preserve-source-formatting` replacement
fallback for a singular or non-finite matrix, an unresolvable map or graphics
state, unsupported device-context restoration, an unsupported
text-orientation semantic.  It shall not approximate such a case
through rasterization, OCR, or a guessed transform.

### Rationale

PowerPoint commonly carries EMF graphics that use repeated coordinate
translations and scales for ordinary diagram labels.  Other sources may use
rotation, reflection, or shear.  Treating every world transform as unsafe
leaves translated labels at their source size and makes adjacent-label overlap
likely.  Fitting every resolvable transform to its original visible bound
maximizes translation coverage and visibility; limiting expansion to the
simple axis-aligned case preserves the existing obstacle-safety guarantee
without delaying rotated, mirrored, or sheared text support.

### Notes

The requirement is EMF-specific; it does not change PPTX-native text-frame
fitting or the OCR bitmap path.  "Orientation-preserving, axis-aligned" means
that the effective transform has no rotation, reflection, or shear and has
strictly positive horizontal and vertical scale.  This is deliberately
narrower than source-bound-only eligibility.

Automated tests shall use synthetic EMFs only.  They shall verify fitted
replacement for direct and composed translations, uniform and unequal scale,
reflection, arbitrary-angle rotation, and shear; `EMR_SETWORLDTRANSFORM`; each
`EMR_MODIFYWORLDTRANSFORM` composition mode; window/viewport origins and
extents; scale-window and scale-viewport records; applicable map and graphics
modes; and save/restore-device-context nesting.  They shall verify
transform-aware source measurement, explicit clips, source-bound-only fitting
for rotated, reflected, and sheared text, baseline-only expansion and text and
line obstacles for the orientation-preserving axis-aligned case, source-font
and Noto measurement modes, output orientation, and structural validity.  They
shall also verify unchanged direct replacement fallback for singular or
non-finite transforms and unsupported state restoration.

---

## FR-2026-09-05-02

| Property | Value |
|----------|-------|
| Title | Fit coherent EMF text fragments as one visual block |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following adjacent EMF-label layout review |
| Date Added | 2026-09-05 |
| Related Requirements | FR-2026-08-03-05, FR-2026-08-03-07, FR-2026-08-03-14, FR-2026-08-04-07, FR-2026-08-27-02, FR-2026-09-04-01, FR-2026-09-05-01 |

### Description

In `preserve-basic-layout` and `preserve-basic-layout-source-font`, the EMF
adapter shall identify an eligible visual text run of two or more editable
`EMR_EXTTEXTOUTA` or `EMR_EXTTEXTOUTW` records before requesting replacement
text. It shall translate and fit the run once as one horizontal visual line,
rather than independently translating and fitting each member.
`preserve-source-formatting` shall retain its existing direct per-record
replacement behaviour.

The fit region for an eligible run shall be the union of its source text
fragments' measured areas. It shall not infer or expand to a surrounding table
cell, shape, or other semantic container. The complete replacement shall be
one coherent text block within that original union region. The adapter shall
select the largest uniform output size that fits, but shall never increase
above the largest source-fragment font size. If it cannot reliably determine
that maximum size, it shall use the existing source-region fitting result
without enlargement.

The implementation shall group records only when all of the following
evidence is present:

- the records form one left-to-right visual text line in source paint order.
  They may be separated by non-painting GDI device-context records, including
  font selection, text colour, text alignment, character spacing,
  justification, coordinate transforms, device-context save/restore,
  clip-region changes, object lifecycle, and non-drawing comments. A failed
  state restoration or an unrecognised comment is ineligible. An intervening
  drawing, bitmap, or other record that paints pixels remains a hard boundary;
- every member is a non-empty, single-line record of the same EMF text-record
  encoding and supplies a finite source text area. The adapter shall derive
  that area from, in priority order, a non-degenerate explicit clip rectangle,
  a non-degenerate record bounds rectangle, or source-text measurement at the
  record's text origin. Members may freely mix those three evidence forms; in
  particular, a member without an explicit bounds or clip rectangle shall not
  prevent grouping. A clipped run's finite clip rectangles must be compatible
  when more than one is present: they must be identical or mutually overlap;
- every member has an orientation-preserving, axis-aligned effective transform
  with the same linear scale components; pure translation between members is
  permitted;
- the leftmost member, which will be the output anchor, is left-aligned;
- the rendered source baselines match within one rendered logical unit, the
  member rectangles are in strictly increasing left-to-right order, and each
  adjacent pair touches, overlaps, or has a horizontal gap no greater than four
  rendered source-line heights; and
- the source rectangle of every member can be derived as FR-2026-09-04-01 and
  FR-2026-09-05-01 define. Source-glyph measurement is
  required only when the record has neither an explicit clip nor a
  non-degenerate bounds rectangle.

The adapter shall not require members to use the same declared GDI face, font
size, weight, italic state, colour, character spacing, or text alignment after
the anchor. Instead, it shall determine the run's dominant typography from the member with
the greatest number of non-whitespace source characters, resolving ties to the
leftmost member. The translated run shall use that dominant typography and one
uniform fitted scale. This intentionally replaces source inline emphasis with
one coherent output style.

The adapter shall concatenate the member source strings in visual order for
the one provider request. It shall preserve a touching or overlapping boundary
without an inserted character, and represent a positive source gap with one
space. A replacement containing a line break, a bidi control, or an unsupported
portable-font segment shall make the entire candidate group ineligible. The
adapter shall then use the existing safe per-record behaviour for its members.

The fitting bound shall begin as the union of the run's measured source areas,
including areas derived for members without an explicit bounds or clip
rectangle. It shall then apply the existing horizontal verified-empty-space
expansion rule as one whole line, stopping at external text, recognised line
segments, the EMF header bounds, or an active rectangular EMF device-context
clip region. It shall not infer a semantic container.
Before selecting the uniform output size for a left-aligned group, the adapter
shall reserve a renderer-safety margin at the right edge of that expanded
bound. The margin shall be the greater of two rendered EMF logical units and
three percent of the bound width, rounded up, while retaining at least one
logical unit of usable width. It shall use the reduced width for fitting but
retain the full expanded bound as the rewritten record bounds and all obstacle
and clip caps. This margin accounts for a retained or substituted GDI font
rendering wider in PowerPoint than the deterministic layout measurement.
The adapter shall select the leftmost member as the anchor, write the complete
one-line replacement to that record, and make every later member non-painting
by replacing its text with an empty string. It shall retain source record order,
the anchor's position and effective transform, and all non-text EMF records.
The source union and any expanded bound are fitting and measurement bounds, not
a new rendering clip. The adapter shall remove `ETO_CLIPPED` from the rewritten
anchor, including when the source anchor was clipped, and write the resulting
bound as the anchor record bounds. A later clipped fragment that is made
non-painting need not retain its former clip rectangle.
It may add and select one cloned GDI font based on the dominant typography only
to apply the run's one uniform fitted scale. It shall clear any explicit
character-advance array on each
rewritten member, since it no longer describes that member's replacement text.
It shall not reflow, reposition, or resize individual group members
independently.

Run members shall not be obstacles to one another. The complete replacement
glyph bounds shall remain within the expanded fitting bound and shall not
intersect an external text rectangle, recognised line segment, or the finite,
non-degenerate EMF header `rclBounds` rectangle. The adapter shall track a
rectangular `EMR_EXTSELECTCLIPRGN` clip through device-context save/restore
and use the intersection of compatible active member clips as an additional
hard cap. An unsupported, degenerate, empty, or unreconcilable active clip
shall retain the source union without free-space expansion. The run shall not expand
vertically, cross another group or text record, infer cells or paragraph
blocks, or group a rotated, reflected, sheared, incompatible-clipped, or
ambiguous record.

FR-2026-09-04-01 and FR-2026-09-05-01 remain the applicable fitting and
expansion rules for every record that is not selected into a group by this
requirement. A group that cannot be safely formed, translated, measured,
encoded, or fitted shall use those existing individual-record rules; it shall
not rasterize the EMF, use OCR, or guess semantic boundaries.

### Rationale

Some PowerPoint EMFs encode one visually continuous label as several GDI text
records separated by non-painting state changes, even when the displayed text
has one apparent size. Independent replacement gives each fragment a separate
translation scope and fitting scale, causing visible overlap or inconsistent
typography. Shared container, baseline, ordering, and obstacle evidence allows
a coherent replacement without treating nearby diagram labels as a paragraph.

### Notes

Automated tests shall use synthetic EMFs only. They shall verify one provider
request, dominant-typography selection, and one uniform fitted scale for an
eligible two- and three-record run; mixed explicit-bound, explicit-clip, and
measurement-derived source areas; union-bound fitting without enlargement;
the maximum-source-font-size cap; anchor output and non-painting successor
records; and stopping at an external text rectangle and a vertical line
segment. They shall verify grouping across non-painting text-state changes,
including differing source faces, sizes, weights, colours, alignment, character
spacing, and justification. They shall verify that each remaining grouping
precondition independently rejects a candidate and retains the existing
individual-record behaviour, including intervening drawing, bitmap, clipping
path, save/restore, encoding, baseline, transform, gap, incompatible clip,
rotation, reflection, or shear differences. They shall verify that explicit
character-advance arrays are cleared on rewritten run members; compatible
mixed-clip run anchor bounds and clip rewriting; and fallback for degenerate or
unreconcilable clips. Tests shall verify the fixed and percentage renderer-safety
margin used for group fitting while retaining the full rewritten render bound.
Tests shall verify active rectangular device-context clip
tracking, save/restore, and expansion caps. Tests shall verify that individual and
run expansion stop at valid EMF header bounds and do not expand when those
bounds are invalid or unreconcilable. Tests shall verify valid generated EMFs and unchanged
`preserve-source-formatting` output.

When an otherwise eligible member selects a stock or otherwise unresolved GDI
font rather than a directly-created `LOGFONTW` record, both fitted modes shall
derive a normal, non-italic Noto Sans JP fallback font from that member's
source-line height. They shall use the fallback for source measurement,
dominant-typography selection, and output. The adapter shall emit a directly
created fallback `LOGFONTW` only for the fitted output record and select it
for that record, retaining the unresolved source selection before and after
the record. This intentionally does not preserve an unresolved stock face, but
lets an eligible run use one explicit output font and uniform scale.

Automated tests shall verify grouping and uniformly fitted output for eligible
stock-font records without a directly-created source font.

---

## FR-2026-09-06-01

| Property | Value |
|----------|-------|
| Title | Record vector fitted-layout fallbacks in output diagnostic sidecars |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following PowerPoint EMF diagnosis |
| Date Added | 2026-09-06 |
| Related Requirements | FR-2026-08-03-05, FR-2026-08-03-10, FR-2026-08-27-06, FR-2026-09-04-01, FR-2026-09-05-01, FR-2026-09-05-02 |

### Description

When a fitted-layout mode is requested and an editable EMF text record is
replaced through the existing direct source-formatting path because fitted
layout cannot be used, the output sidecar shall add one `layout_fallback`
entry. It shall identify `vector_format` as `emf`, `container_kind` as
`emf_text_record`, the EMF text-record index and byte offset, and the
embedded package part when applicable. It shall contain a stable reason code
that distinguishes an unresolved coordinate state, an invalid transform,
unavailable source geometry, an unsuccessful bounded fit, and an unavailable
rotated or sheared transform. A successful fitted replacement and an ordinary
`preserve-source-formatting` replacement shall not add a fallback entry.
When available, the entry shall begin with the record's `source_text` and the
`replacement_text` returned by the selected provider so a reviewer can compare
the direct fallback with its source.

The vector adapter shall return structured diagnostic decisions to the folder
processor without writing sidecars itself. The folder processor remains solely
responsible for writing the source document's sidecar beside its output.

### Rationale

PowerPoint frequently embeds EMFs whose GDI coordinate state makes a fitted
replacement unsafe. Recording the local EMF record and exact fallback status
makes this visible without modifying the presentation or requiring manual
package inspection.

### Notes

Automated tests shall use synthetic standalone and PPTX-embedded vector data.
They shall verify an embedded EMF fitted-layout fallback with source and
replacement text, package-part and record location, including the distinct
rotated and sheared transform statuses. They shall verify sidecar omission
when debug is disabled, when fitted EMF replacement succeeds, and for a vector
retained solely because it has no editable text.

---

## FR-2026-10-22-09

| Property | Value |
|----------|-------|
| Title | Identify EMF and WMF graphics by content, not file extension |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-10-22 |
| Related Requirements | FR-2026-08-03-10, FR-2026-10-22-04 |

### Description

The vector-replacement dispatcher shall identify an EMF or WMF graphic from its content. A graphic is an EMF when its first record is the EMF header record with the ` EMF` signature. It is a WMF when it starts with the placeable-metafile key or with a standard WMF header. A `.emf` or `.wmf` file whose content is the other format shall be processed by the handler for the format its content shows. When the content shows neither format, the file extension shall decide, so a damaged graphic reports the same format-specific error as before. A `.svg` file is not content-sniffed.

The output keeps the source file's name and extension. Planning and applying a graphic shall use the format the dispatcher identified.

### Rationale

Real documents contain EMF graphics saved with a `.wmf` extension. The WMF parser rejected them with "Invalid WMF header size." and no translated output was produced. Identifying the format from the content processes these files and leaves correctly named files unchanged.

### Verification

Automated tests shall use synthetic graphics only. They shall verify that an EMF with a `.wmf` extension and a WMF with an `.emf` extension are each processed by the handler for their content, that a placeable WMF is recognised, and that content showing neither format keeps its extension's handler and error.

---

## FR-2026-10-22-10

| Property | Value |
|----------|-------|
| Title | Translate EMF+ text and keep the EMF+ stream valid |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request |
| Date Added | 2026-10-22 |
| Related Requirements | FR-2026-08-03-05, FR-2026-08-03-10, FR-2026-10-22-04, FR-2026-10-22-09 |

### Description

An EMF can carry a second drawing stream in EMF+ records, stored inside `EMR_COMMENT` records that begin with the identifier `EMF+`. A dual EMF holds the same drawing twice, as GDI records and as EMF+ records. Viewers that play EMF+ draw the EMF+ stream and skip the GDI records that duplicate it.

The EMF handler shall translate text in both streams, so either kind of viewer shows the translated text:

- `EmfPlusDrawString` records, when the font object they name is defined earlier in the file.
- `EmfPlusDrawDriverString` records whose glyphs are characters (`CmapLookup` set) and whose text runs horizontally.

EMF+ text is planned and applied like any other vector text. Both streams request the same source text, so the batch, the cache and the request count see it once. The EMF handler shall analyse the EMF once and list its texts and embedded images through the `VectorDocument` protocol, as the SVG and WMF handlers do.

When a fitted layout is selected, the handler shall shrink the font of a replaced EMF+ text to fit its source extent: the layout rectangle for `EmfPlusDrawString`, and the span of the source glyph positions for `EmfPlusDrawDriverString`. It shall do this by emitting a new font object under an object identifier the file never uses, never by changing the source font object, and it shall reuse one new font object for repeated sizes. When the source-font layout is selected, the source face is measured as for other EMF text.

When an `EmfPlusDrawDriverString` text is replaced, the handler shall write one position for each replacement character, advanced by the measured width of the preceding characters. A source that gives only the first glyph position (`RealizedAdvance` set) keeps that single position.

The handler shall keep the output a valid EMF: the EMF+ record sizes, the `EMR_COMMENT` size and data size, the `EMR_HEADER` byte and record counts shall match the rewritten records, and the EMF+ header shall stay the first record after the `EMR_HEADER`.

The handler shall not insert any record before the EMF+ header comment. The fitted source-font layout inserts its scaled GDI font records immediately after that comment. An EMF without an EMF+ stream shall produce the same output as before this requirement.

The handler shall leave an EMF+ text record unchanged, and shall add an `unsupported` entry to the output sidecar, when it cannot be replaced safely: the glyphs are glyph indices, the text is vertical, the record is malformed, the replacement needs characters outside the Basic Multilingual Plane, or the record needs regenerated positions but its font object is missing, is continued, or has a size unit that is not world or pixel. A malformed EMF+ comment is also left unchanged and reported as `unsupported`. When a fitted layout cannot be applied to a replaced EMF+ text because its font object is missing, its font size unit is not world or pixel, its extent is empty, no object identifier is free, or the bounded fit fails, the text shall be replaced at its source size and the output sidecar shall add one `layout_fallback` entry with `vector_format` `emf`, `container_kind` `emfplus_text_record`, and the source and replacement text. Neither entry is added when `--debug` is off, as for other vector diagnostics.

### Rationale

GDI+ viewers, including Office, play the EMF+ stream of a dual EMF and skip the duplicate GDI records. Translating only the GDI records left the source text visible there. Removing the EMF+ stream would lose the anti-aliased, more accurate GDI+ rendering, so both streams are translated.

The fitted source-font layout inserted its scaled GDI font records before the EMF+ header comment. A viewer expects the EMF+ header to follow the `EMR_HEADER` directly, so it treated the file as GDI-only. Placing the records after the header comment keeps the EMF+ stream recognised.

### Verification

Automated tests shall use synthetic EMFs only. They shall verify that `EmfPlusDrawString` and character-glyph `EmfPlusDrawDriverString` text is replaced alongside GDI text records in a dual EMF; that the EMF+ record, comment and header sizes and the record count are consistent; that the EMF+ header stays the first record after the `EMR_HEADER` in all layout modes, including when scaled GDI font records are inserted; and that an EMF without EMF+ records produces unchanged output. They shall verify fitted font-object emission with an unused identifier, reuse of that object for repeated sizes, and the unmodified source font object; regenerated and first-position-only driver-string positions; each unsupported and fallback case and its sidecar entry; and that planning requests every text the apply step requests, so a planned run makes no further provider request.

---

## FR-2026-10-22-12

| Property | Value |
|----------|-------|
| Title | Fit SVG text that has no clip rectangle to its measured source extent |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following an EMF diagnosis |
| Date Added | 2026-10-22 |
| Related Requirements | FR-2026-08-04-07, FR-2026-08-22-08, FR-2026-08-22-13, FR-2026-08-27-02, FR-2026-10-22-11 |

### Description

An SVG `text` or `tspan` element has no text field. Text that has an explicit clip rectangle keeps its existing fit to that rectangle. In both fitted layouts, other text shall follow the unknown-bounds rule of FR-2026-10-22-11: the SVG handler shall measure the source text at its resolved `font-size` with the source face, or the committed Noto face when the source face is unavailable, and shall fit a longer replacement to that measured width by reducing the size. A replacement no longer than the source keeps the source size.

The handler shall fit an element only when it has its own text and no child elements, is not inside a `foreignObject`, is not a `textPath`, uses horizontal writing, and has no rotation or skew from its own or an ancestor's `transform` or from a `rotate` attribute. The source size is its resolved `font-size`, or the CSS default size when none is set; a `font-size` that cannot be resolved to a length is not placed safely. A reduced size shall be written to the element's inline style, which takes precedence over style sheets. The handler shall not expand the measured extent into neighbouring space.

An element that cannot be fitted safely shall be replaced at its source size, as `preserve-source-formatting` does, and shall still be translated. `preserve-source-formatting` is unchanged.

### Rationale

Most SVG text is not clipped. Leaving it at the source size lets longer translations run into neighbouring shapes, although the original extent is known from the source text and face.

### Verification

Automated tests shall use synthetic SVGs only. They shall verify the size reduction of un-clipped text with a resolved and with an unavailable source face; that a replacement no longer than the source keeps its size; that text with a clip rectangle is unchanged from before; that rotated, skewed, `textPath`, `foreignObject` and child-element text is replaced at its source size; that the replacement is translated when it cannot fit at the minimum size; and that the output remains valid SVG.

---

## FR-2026-10-22-13

| Property | Value |
|----------|-------|
| Title | Fit WMF text that has no clip rectangle to its measured source extent |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following an EMF diagnosis |
| Date Added | 2026-10-22 |
| Related Requirements | FR-2026-08-04-07, FR-2026-08-27-02, FR-2026-10-22-09, FR-2026-10-22-11 |

### Description

A WMF `META_TEXTOUT` or `META_EXTTEXTOUT` record has an origin and may have a clip rectangle. A record with a clip rectangle keeps its existing fit to that rectangle. In both fitted layouts, other records shall follow the unknown-bounds rule of FR-2026-10-22-11: the WMF handler shall measure the source text at the height of the selected font with the source face, or the committed Noto face when the source face is unavailable, and shall fit a longer replacement to that measured width by reducing the size. A replacement no longer than the source keeps the source size.

The handler shall fit a record only when a created font is selected, that font has a non-zero height and no escapement, and the text is a single line. A reduced size shall be written as a scaled clone of the selected font that is used by that record only. The handler shall not expand the measured extent into neighbouring space.

A record that cannot be fitted safely shall be replaced at its source size, as `preserve-source-formatting` does, and shall still be translated. `preserve-source-formatting` is unchanged.

### Rationale

Most WMF text is not clipped, so it was never fitted, and longer translations overlap neighbouring drawing. The original extent is known from the source text, face and font height.

### Verification

Automated tests shall use synthetic WMFs only. They shall verify the size reduction of `META_TEXTOUT` and un-clipped `META_EXTTEXTOUT` records with a resolved and with an unavailable source face; that a replacement no longer than the source keeps its size; that clipped records are unchanged from before; that a record with no selected font, a zero-height font, an escapement or multiple lines is replaced at its source size; that the replacement is translated when it cannot fit at the minimum size; that other records keep the original font; and that the generated WMF remains structurally valid.

---

## FR-2026-10-22-14

| Property | Value |
|----------|-------|
| Title | Translate EMF+ image objects: embedded bitmaps and nested metafiles |
| Owner | KrisTC |
| Status | Implemented |
| Source | User request following an EMF diagnosis |
| Date Added | 2026-10-22 |
| Related Requirements | FR-2026-08-03-09, FR-2026-08-03-10, FR-2026-10-22-04, FR-2026-10-22-05, FR-2026-10-22-09, FR-2026-10-22-10, SR-2026-08-03-02 |

### Description

FR-2026-10-22-10 translates the text records of an EMF+ stream. An EMF+ stream can also draw images defined in `EmfPlusObject` records with object type Image. An Image object holds either a bitmap or a nested metafile. A GDI+ viewer, such as Office, plays the EMF+ stream of a dual EMF and skips the duplicate GDI records, so text inside these images stays visible unless the images are processed. A viewer that plays only the GDI records, such as Inkscape, already shows the translated GDI text and is unaffected.

The EMF handler shall list every Image object of the EMF+ stream through the `VectorDocument` protocol, whether or not a draw record uses it, and shall process each one in memory:

- **Bitmap.** The handler shall decode the bitmap, process it through the shared bitmap OCR and text-replacement path as FR-2026-08-03-09 does for a GDI DIB, and re-embed the result in the same Image object under the same object identifier. The decoded bitmap is a compressed image (PNG or JPEG) or an uncompressed 24-bit RGB, 32-bit RGB or 32-bit ARGB pixel buffer. The replaced bitmap shall keep the source pixel dimensions, because draw records address it in source pixels, and shall keep its alpha. It shall be written as a compressed PNG bitmap. Its replaced OCR-region count shall contribute to the document's image-region result.
- **Nested metafile.** The handler shall treat the metafile as a nested document under FR-2026-10-22-05: it shall plan and apply it through the public plan and apply entry points of the handler for the nested format, retain its plan, list its units after the parent's, and embed the returned bytes. The nested format is identified as FR-2026-10-22-09 identifies a graphic, so an EMF, EMF+-only or EMF-plus-dual metafile is handled by the EMF handler, and a WMF or placeable WMF by the WMF handler. The EMF handler shall not branch on being nested. The nested document is its own unit with a path-style identifier below its parent's, and the depth limit and `nested_document_depth_limit_exceeded` diagnostic of FR-2026-10-22-05 apply to it.

The handler shall write Image objects with the chunking GDI+ uses: an object too large for one `EmfPlusObject` record, whose data holds at most 65,008 bytes, is split over consecutive records with the continuation flag set, and every chunk starts with the 4-byte total size of the whole object. It shall reassemble a chunked object before processing it and shall write the replacement as the same kind of chunked object.

The handler shall keep the output a valid EMF as FR-2026-10-22-10 requires. The EMF+ record sizes, the `EMR_COMMENT` sizes and data sizes, the object's total size and, for a metafile, its metafile data size, and the `EMR_HEADER` byte and record counts shall match the rewritten records. The EMF+ header shall stay the first record after the `EMR_HEADER`. No Image object that is left unchanged shall change by a byte, and no object other than an Image object shall change.

The handler shall leave an Image object unchanged, and shall add an `unsupported` entry to the output sidecar, when it cannot be processed safely: its chunks are not consecutive or do not add up to the declared total size, it is malformed, its bitmap is in a format or pixel format not listed above, or its metafile data is malformed or in an unrecognised format. A failure inside a nested metafile shall be reported through the nested handler's own entries and shall not change the other objects. The `unsupported` entry shall have `vector_format` `emf` and `container_kind` `emfplus_image_object`, and shall identify the object only by its identifier and never by its content. The entry is added only when `--debug` is set, as for other vector diagnostics.

EMF+ image objects are self-contained, and nothing shall be fetched or opened for them, as SR-2026-08-03-02 requires.

### Rationale

Real EMF graphics can be saved as a dual EMF whose EMF+ stream draws image objects, including chunked bitmaps and nested metafiles, instead of text records. The GDI text and DIB records that the handler already translates are skipped by GDI+ viewers such as Office, so the output looked untranslated there. Re-using the shared bitmap handler and the nested-document recursion adds no second raster or vector implementation.

### Notes

Text that exists only as outlines or paths, such as `EmfPlusFillPath` and `EmfPlusDrawPath` records, remains out of scope as in FR-2026-08-03-09. Other EMF+ image types, such as indexed or high-bit-depth bitmaps, are reported as unsupported until separately specified.

A dual EMF carries the same picture in the GDI stream and the EMF+ stream. Bitmaps in the two streams are processed as separate images, so a bitmap that is drawn in both costs one OCR pass for each encoding.

### Verification

Automated tests shall use synthetic EMFs only. They shall verify that a PNG bitmap object, a JPEG bitmap object and each listed uncompressed pixel format are processed through the shared bitmap handler and re-embedded under the same object identifier with the source pixel dimensions and alpha; that a chunked bitmap object is reassembled and written back with a valid total size in every chunk and valid chunk sizes; that a nested EMF+-only metafile and a nested WMF have their text and bitmaps translated by their own handlers and embedded with a valid metafile data size; that nested units are listed after the parent's with path-style identifiers and share the one resolution with the parent's texts; that a nested metafile at a depth beyond the limit is left unchanged and, only with `--debug`, reported without content; that the EMF+ header stays the first record after the `EMR_HEADER` and that the EMF+ record, comment and header sizes and counts are consistent; that objects left unchanged are byte-identical; that each unsupported case is left unchanged and reported only with `--debug`; and that planning requests every text and image the apply step requests, so a planned run makes no further provider request.

---
