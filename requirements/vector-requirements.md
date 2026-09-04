# Vector Graphic Requirements

SVG, EMF, WMF, and editable vector-graphic processing.

## FR-2026-08-03-05

| Property | Value |
|----------|-------|
| Title | Replace editable text in embedded vector graphics directly |
| Owner | KrisTC |
| Status | Implemented |
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
| Status | Implemented |
| Source | User request |
| Date Added | 2026-08-03 |
| Related Requirements | FR-2026-08-03-03, FR-2026-08-03-05, TR-2026-08-03-01 |

### Description

When an embedded EMF graphic contains a raster DIB payload in an `EMR_STRETCHDIBITS` record, the folder-replacement pipeline shall decode that payload in memory and process it through the existing shared bitmap OCR and text-replacement path. It shall re-embed the resulting DIB in the same EMF record, retaining the EMF graphic and its other vector content.

The raster DIB path shall use the selected OCR and text-replacement providers, source and target languages, typeface, confidence threshold, colour estimation, and batch text-region rendering already used for standalone and Office-embedded bitmap images. Its replaced OCR-region count shall contribute to the document's image-region result.

### Rationale

An EMF can combine editable vector text with already-rasterized visual content. Processing DIB payloads directly covers that contained bitmap content without requiring an EMF renderer or rasterizing the whole vector graphic.

### Notes

The initial scope is `EMR_STRETCHDIBITS`. Other EMF bitmap record types and outlined or path-only vector text remain out of scope until separately specified. The DIB shall be processed only in memory and shall invoke the existing shared raster handler; no intermediate image file is permitted.

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

The vector-replacement implementation shall provide separate SVG, EMF, and WMF modules, with a small extension-based dispatcher and shared result and DIB helpers. Standalone `.svg`, `.emf`, and `.wmf` input files shall be supported by the folder command and shall use the same in-memory format handler as an embedded Office vector part.

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
| Related Requirements | FR-2026-08-03-05, FR-2026-08-03-07, FR-2026-08-03-14, FR-2026-08-04-07, FR-2026-08-27-02 |

### Description

This requirement extends fitted-layout eligibility for editable EMF
`EMR_EXTTEXTOUTA` and `EMR_EXTTEXTOUTW` records that have no explicit clipping
rectangle.  It supersedes the EMF-specific explicit-clipping-only rule in
FR-2026-08-04-07, but only for the eligible records below.  It does not change
`preserve-source-formatting`, which shall retain its existing direct native
text replacement behaviour.

In either fitted layout mode, the EMF adapter shall first reconstruct the
selected source GDI font and original horizontal text placement.  It shall
measure the original non-empty, single-line text at its original size to derive
its occupied source rectangle.  The record's non-degenerate rendered bounds
shall be retained as independent geometry evidence and a safety limit; a
measurement that cannot be reconciled safely with those bounds is ineligible.

`preserve-basic-layout` shall measure the source text with the appropriate
committed Noto face.  `preserve-basic-layout-source-font` shall first measure
with the resolved source face when it is available and usable, and otherwise
shall measure with the appropriate committed Noto face.  Replacement-face
selection and fitting shall follow FR-2026-08-27-02.  As ordinary EMF has no
safe portable font-embedding path, the output shall retain its source font
reference while applying the selected fitting scale.

The measured source rectangle shall be the default replacement fitting bound.
For a source record and returned replacement that each contain one horizontal
line, the adapter may expand that bound along the baseline only into verified
empty space.  It shall not expand vertically or introduce a new line.  It
shall stop before the nearest intersecting source-text rectangle or a
recognised vector line segment.  The complete fitted replacement glyph bounds
shall remain within the resulting rectangle and shall not intersect another
source-text rectangle or recognised vector line segment.  A left-aligned
record may expand rightward, a right-aligned record may expand leftward, and a
centred record may expand symmetrically.

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
fitting, but it must retain one-line EMF output semantics.  It must not use OCR
or rasterize the EMF graphic for this feature.

Automated tests shall use synthetic EMF inputs only.  They shall verify
Noto-only source measurement in `preserve-basic-layout`; source-face
measurement and Noto fallback in `preserve-basic-layout-source-font`; fitting
to the measured source rectangle; permitted horizontal expansion; stopping at
both an adjacent text rectangle and a vertical line segment; alignment-aware
expansion; and unchanged direct replacement for multi-line, rotated,
transformed, ambiguous, or otherwise ineligible records.  Tests shall verify
that generated EMF files remain structurally valid.

---
