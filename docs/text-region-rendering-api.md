# Text-region rendering API

`replace_text_region` uses Skia to remove and redraw one visible OCR text region in place.

```python
from pipeline.text_region_rendering import replace_text_region

replace_text_region(
    image,
    ocr_text,
    colour_estimate,
    replacement_text,
    typeface,
    target_language="en",
)
```

The supplied `image` is modified directly. Copy it before calling this function if its original pixels are needed later. `typeface` is a caller-loaded `skia.Typeface`, so it can be loaded once and reused for several regions.

The utility fills the OCR polygon with `background_colour`, then lays out and draws the replacement in `text_colour`. It uses the polygon's longest edge as the local text direction, clips drawing to the polygon, wraps to multiple lines when necessary, and selects the largest whole-pixel font size that fits. When that direction is within five degrees of horizontal or vertical, it prefers an upright, pixel-aligned layout only when the visible glyph bounds are contained by the polygon without reducing the fitted font size. The target-language parameter is retained in the API for future language-specific shaping and layout; the initial implementation uses simple Skia text measurement.

For `gradient` and `complex` backgrounds, the representative `background_colour` is still used. This removes visible source text but does not reconstruct the original surface.

The local evaluator loads the committed variable Noto Sans JP font at native weight `500` (bold). When a supplied variable typeface has a `wght` axis and its preliminary fitted size is below 14 px, the renderer re-fits with that typeface's `300` weight variation to retain more useful glyph width. Static typefaces retain their supplied weight.
