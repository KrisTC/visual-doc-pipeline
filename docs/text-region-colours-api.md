# Text-region-colour API

`estimate_text_region_colours(image, text_region)` analyses one OCR `OcrText` region in the original Pillow image. It returns `TextRegionColourEstimate`; it does not modify the image, mask text, or reconstruct a background.

For the rationale, stages, scoring, and limitations of the current implementation,
see [the algorithm design note](text-region-colours-algorithm.md).

```python
from pipeline.text_region_colours import estimate_text_region_colours

estimate = estimate_text_region_colours(image, ocr_text)
```

## Colour values

Every `RgbaColour` is an observed, non-premultiplied eight-bit sRGB value:

| Property | Range | Meaning |
|---|---:|---|
| `red`, `green`, `blue` | `0`–`255` | sRGB channel values |
| `alpha` | `0`–`255` | Opacity: `0` transparent, `255` opaque |

The values describe pixels stored in the source image. They do not infer a hidden source-layer colour before alpha compositing.

## Estimate fields

| Field | Meaning |
|---|---|
| `text_colour` | Estimated primary text fill. |
| `background_colour` | Estimated immediate surface behind glyphs, such as a label panel. It is not a reconstruction fill for a gradient or complex image. |
| `text_colour_confidence` | A `0.0`–`1.0` heuristic reliability score based on text-like geometry, candidate separation, foreground/background Lab contrast, and selected text-colour consistency. |
| `background_colour_confidence` | A `0.0`–`1.0` heuristic reliability score based on immediate-background support and consistency. |
| `background_kind` | Advisory `flat`, `gradient`, or `complex` local-background classification. |

Confidence is neither a probability nor OCR confidence. `0.0` means the estimator found no usable supporting evidence; `1.0` means the strongest evidence available to this heuristic, not a correctness guarantee. Compare scores only from the same estimator version. Review low-confidence estimates or apply a caller-selected fallback.

## Colours for replacing text

`estimate_replacement_colours(image, text_regions, page_colour=(255, 255, 255))` returns one `TextRegionColourEstimate` per region, ready for the rendering API. Use it instead of `estimate_text_region_colours` when replacing text, particularly in images with transparency.

- `page_colour` is the opaque RGB colour that shows through transparent pixels, such as the document background. It defaults to white.
- `background_colour` is still the observed background, so a transparent cell stays transparent when it is wiped.
- `text_colour` is estimated from a copy composited onto `page_colour`, so antialiasing pixels with hidden RGB values are not mistaken for text. It is always opaque.
- When `text_colour_confidence` is below `0.60` and the background shows the page colour (transparent, or opaque and equal to it), `text_colour` is opaque black or white, whichever contrasts more with `page_colour`.

## Local example evaluator

Generate local static pages for the supplied examples with:

```sh
./run.sh scripts/colour_evaluations.py
```

Pages are written below `outputs/evaluations/color-detection-examples/`. Each result row references its existing padded text-region bitmap through a relative path and is a local generated artifact; do not add the pages to Git.
