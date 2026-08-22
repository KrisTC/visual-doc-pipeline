# Document text-layout review guide

This guide reviews the two fitted document-text modes.  It is based on the
implemented requirements, principally FR-2026-08-03-14 and
FR-2026-08-04-06.

## Intended behaviour

| Concern | `preserve-basic-layout` | `preserve-basic-layout-source-font` |
|---|---|---|
| Replacement and fitting | Replace each non-empty paragraph, wrap it, and select one fitted scale for the bounded text box. | The same replacement and fitting process. |
| Measurement face | Repository-owned Noto face selected as sans-serif, serif, or fixed-width. | The same repository-owned Noto face. |
| Written font face | Explicit selected Noto face. | Resolved source face when one exists; otherwise the selected Noto face. |
| Font size and autofit | Explicit fitted run sizes; autofit disabled. | The same. |
| Goal | Deterministic, Noto-based output that prioritises fitting. | Best-effort preservation of presentation design, accepting a possible metric mismatch with Noto measurement. |

The modes are not respectively “fit” and “do not fit”.  Both fit.  The only
intentional PPTX difference is the font reference written after the fit.

`preserve-source-formatting` is the separate default mode.  It translates
native text in place without fitting, reflowing, changing font sizes, or
forcing a face.

## Central implementation path

The shared utility is [pipeline/bounded_text_layout.py](../pipeline/bounded_text_layout.py).
Adapters should extract a `BoundedTextBox` and call
`replace_and_fit_text_box`, rather than independently translating runs or
calculating a scale.

```text
adapter extracts bounded source text
        |
        v
replace_and_fit_text_box
  -> replace_paragraphs
     (one provider request per non-empty paragraph; dominant source-run style)
  -> fit_explicit_noto_text_box
     (Noto measurement, wrap/character-wrap, common fitted scale)
  -> explicit paragraphs and runs
        |
        v
adapter writes its format-specific text-frame settings
```

`fit_explicit_noto_text_box(..., preserve_source_font_family=False)` writes
the selected Noto family for every output run.  Passing `True` preserves a
non-empty resolved `run.font_family`; the Noto family remains the fallback and
the measurement face in either case.

## API and call-site review

| Area | Entry point / call site | Basic-layout font policy | Review focus |
|---|---|---|---|
| CLI | [scripts/run_folder_replacement.py](../scripts/run_folder_replacement.py) | Selects and forwards the layout value. | Ensure the command value arrives unchanged at `replace_input_folder`. |
| Folder dispatcher | [pipeline/folder_replacement/processor.py](../pipeline/folder_replacement/processor.py) | Dispatches by format. | Validate the mode once and keep unsupported containers on source-formatting fallback. |
| PPTX shapes and tables | [pipeline/folder_replacement/pptx.py](../pipeline/folder_replacement/pptx.py) | Passes `False` for basic layout and `True` for source-font mode. | Check bounds, no-autofit handling, and every supported shape reaching the shared utility. |
| DOCX DrawingML text boxes | [pipeline/folder_replacement/docx.py](../pipeline/folder_replacement/docx.py) | Basic writes Noto; source-font mode preserves source references. | Check only finite drawing bounds opt in; flowing paragraphs stay direct replacement. |
| XLSX cells and drawing text | [pipeline/folder_replacement/xlsx.py](../pipeline/folder_replacement/xlsx.py) | Retains source face in both fitted modes because XLSX has no portable embedded-font path. | This is an intentional format limitation, not the PPTX mode contract. |
| PDF bounded fields and annotations | [pipeline/folder_replacement/processor.py](../pipeline/folder_replacement/processor.py) | Basic embeds/writes static Noto; source-font mode retains the existing appearance face. | Check the written PDF appearance, not only the intermediate run family. |
| SVG with explicit clip rectangles | [pipeline/vector_text/svg.py](../pipeline/vector_text/svg.py) | Basic writes and embeds static Noto; source-font retains `font-family`. | Ensure the text has a qualifying explicit clip rectangle. |
| EMF and WMF clipped text | [pipeline/vector_text/replacer.py](../pipeline/vector_text/replacer.py) | Retains source GDI font and applies Noto-derived scale. | Intentional: these formats have no safe portable font-embedding path. |

The API contains a policy boolean because serialisation differs by format.  It
does not permit an adapter to change fitting measurement: all normal fitted
paths still use `noto_typefaces()`.

## PPTX review procedure

1. Use a synthetic text box with a resolved non-Noto face, finite dimensions,
   and a replacement that needs a size change.
2. Run once with each fitted mode.
3. Inspect the output `ppt/slides/slide*.xml` rather than relying only on a
   viewer's font menu.  For every rewritten `a:r/a:rPr`, basic layout should
   contain explicit `a:latin` and `a:ea` `typeface` values naming Noto.  The
   source-font mode should instead retain the resolved source value when one
   existed.
4. In both outputs, verify explicit `a:rPr/@sz` and `a:bodyPr/a:noAutofit`.
   The shape geometry should not be resized.
5. Repeat with a PowerPoint **Do not Autofit** frame.  It should retain the
   source width and fit against the source text's natural height; other
   autofit modes use the original shape bounds.
6. Verify a table cell, a grouped shape, an inherited placeholder style, and
   a source run without a resolvable face.  The last must use Noto in
   source-font mode.

For visual review, compare the two outputs on a machine without the source
font installed as well as one that has it.  Basic layout is deliberately the
more stable comparison; source-font mode is explicitly best effort.

## WordArt and advanced-style handling

FR-2026-08-05-01 is implemented. WordArt presets and advanced DrawingML run
styling no longer exclude a PPTX shape from fitting. The writer creates the
replacement run from the dominant source run's direct properties, retains the
paragraph's end-run properties, then changes only the fitted typography. In
particular, fill, outline, effects, highlights, underline paint, language, and
hyperlinks remain in the output. SmartArt is unchanged and remains on its
canonical diagram-data replacement path.

## Invariants for automated tests

- Basic PPTX fitting writes explicit Noto `latin` and East-Asian references,
  explicit fitted sizes, and no-autofit.
- Source-font PPTX fitting preserves a resolved non-Noto face but has the same
  paragraph text, scale, and autofit result as basic fitting.
- A coloured ordinary text box is fitted in basic layout while retaining its
  advanced run formatting.
- A WordArt preset text transform is fitted without dropping its effects or
  changing shape geometry.
- Unsupported or unbounded containers retain direct source-formatting
  replacement and are reported/documented as such.
