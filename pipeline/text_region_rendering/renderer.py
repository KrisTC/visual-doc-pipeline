"""Render a replacement string in an OCR region without copying the input image."""

from __future__ import annotations

from collections.abc import Callable
from colorsys import hls_to_rgb, rgb_to_hls
from dataclasses import dataclass
from math import atan2, ceil, cos, degrees, floor, hypot, radians, sin
import re

import numpy as np
from PIL import Image
# skia-python does not publish PEP 561 stubs; this is the native rendering boundary.
import skia  # type: ignore[import-not-found]

from pipeline.ocr.models import BoundingPolygon, OcrText, PixelPoint
from pipeline.text_region_colours import RgbaColour, TextRegionColourEstimate


AXIS_ALIGNMENT_TOLERANCE_DEGREES = 0.01
UPRIGHT_LAYOUT_TOLERANCE_DEGREES = 5.0
FONT_WEIGHT_AXIS_TAG = 0x77676874
SMALL_FONT_WEIGHT = 300.0
SMALL_FONT_SIZE_THRESHOLD = 14.0
BACKGROUND_WIPE_OUTSET_PIXELS = 2
DARK_BACKGROUND_MAXIMUM_LUMINANCE = 0.35
LIGHT_TEXT_MINIMUM_LUMINANCE_DIFFERENCE = 0.15
LIGHT_TEXT_LIGHTNESS_BOOST = 0.65


@dataclass(frozen=True, slots=True)
class _RegionFrame:
    """A local text coordinate system aligned with the longest polygon edge."""

    angle_degrees: float
    minimum_x: float
    maximum_x: float
    minimum_y: float
    maximum_y: float

    @property
    def width(self) -> float:
        return self.maximum_x - self.minimum_x

    @property
    def height(self) -> float:
        return self.maximum_y - self.minimum_y

    @property
    def is_axis_aligned(self) -> bool:
        """Return whether the frame maps local coordinates directly to pixel axes."""
        nearest_right_angle = round(self.angle_degrees / 90.0) * 90.0
        return abs(self.angle_degrees - nearest_right_angle) <= AXIS_ALIGNMENT_TOLERANCE_DEGREES


@dataclass(frozen=True, slots=True)
class _TextLayout:
    """Lines and Skia font metrics selected for one fitted replacement."""

    font: skia.Font
    lines: tuple[str, ...]
    line_bounds: tuple["_GlyphBounds", ...]
    line_advance: float
    content_top: float
    content_bottom: float


@dataclass(frozen=True, slots=True)
class _GlyphBounds:
    """Visible glyph extents relative to a line's drawing origin and baseline."""

    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top


@dataclass(frozen=True, slots=True)
class _RenderPlan:
    """One selected frame, layout, and local translation for a replacement."""

    frame: _RegionFrame
    layout: _TextLayout
    offset_x: float = 0.0
    offset_y: float = 0.0


def replace_text_region(
    image: Image.Image,
    text_region: OcrText,
    colour_estimate: TextRegionColourEstimate,
    replacement_text: str,
    typeface: skia.Typeface,
    target_language: str,
) -> None:
    """Replace visible text in ``text_region`` directly in ``image``.

    The function fills the OCR polygon with the estimate's representative
    background colour and then uses Skia to draw the largest whole-pixel font
    size whose wrapped replacement lines fit the region's geometry. It does not
    create or return an image copy. ``typeface`` is caller-owned and may be
    reused across calls. ``target_language`` is validated and retained at this
    API boundary; language-specific shaping is not implemented yet.
    """
    if not target_language.strip():
        message = "A text-region replacement requires a non-empty target language tag."
        raise ValueError(message)
    if image.width <= 0 or image.height <= 0:
        message = "A text-region replacement requires a non-empty image."
        raise ValueError(message)

    path = _polygon_path(text_region.bounding_polygon)
    source = np.ascontiguousarray(np.asarray(image.convert("RGBA")))
    surface = _make_surface(image.width, image.height)
    canvas = surface.getCanvas()
    canvas.drawImage(skia.Image.fromarray(source), 0, 0)

    _wipe_background(canvas, path, colour_estimate.background_colour)
    if replacement_text:
        render_plan = _select_render_plan(
            replacement_text, typeface, text_region.bounding_polygon
        )
        _draw_layout(
            canvas,
            path,
            render_plan,
            _render_text_colour(
                colour_estimate.text_colour, colour_estimate.background_colour
            ),
        )

    rendered = Image.fromarray(surface.makeImageSnapshot().toarray(), "RGBA")
    if image.mode == "RGBA":
        image.paste(rendered)
    else:
        image.paste(rendered.convert(image.mode))


def _make_surface(width: int, height: int) -> skia.Surface:
    image_info = skia.ImageInfo.Make(
        width,
        height,
        skia.ColorType.kRGBA_8888_ColorType,
        skia.AlphaType.kUnpremul_AlphaType,
    )
    surface = skia.Surface.MakeRaster(image_info)
    if surface is None:
        message = f"Skia could not create a {width}x{height} raster surface."
        raise RuntimeError(message)
    return surface


def _wipe_background(canvas: skia.Canvas, path: skia.Path, colour: RgbaColour) -> None:
    """Fill the OCR polygon and its two-pixel perimeter with background colour."""
    paint = _paint_for_colour(colour)
    paint.setBlendMode(skia.BlendMode.kSrc)
    paint.setAntiAlias(False)
    # Skia's lower and right fill boundaries are exclusive at integral coordinates.
    # The extra positive translation therefore provides the same two full pixels
    # of wipe coverage on every edge.
    for offset_y in range(
        -BACKGROUND_WIPE_OUTSET_PIXELS, BACKGROUND_WIPE_OUTSET_PIXELS + 2
    ):
        for offset_x in range(
            -BACKGROUND_WIPE_OUTSET_PIXELS, BACKGROUND_WIPE_OUTSET_PIXELS + 2
        ):
            canvas.save()
            canvas.translate(offset_x, offset_y)
            canvas.drawPath(path, paint)
            canvas.restore()


def _render_text_colour(text_colour: RgbaColour, background_colour: RgbaColour) -> RgbaColour:
    """Return a bounded lightness boost for light text rendered on dark surfaces."""
    background_luminance = _relative_luminance(background_colour)
    text_luminance = _relative_luminance(text_colour)
    if (
        background_colour.alpha == 0
        or
        background_luminance > DARK_BACKGROUND_MAXIMUM_LUMINANCE
        or text_luminance - background_luminance < LIGHT_TEXT_MINIMUM_LUMINANCE_DIFFERENCE
    ):
        return text_colour

    hue, lightness, saturation = rgb_to_hls(
        text_colour.red / 255.0,
        text_colour.green / 255.0,
        text_colour.blue / 255.0,
    )
    boosted_red, boosted_green, boosted_blue = hls_to_rgb(
        hue,
        lightness + ((1.0 - lightness) * LIGHT_TEXT_LIGHTNESS_BOOST),
        saturation,
    )
    return RgbaColour(
        round(boosted_red * 255.0),
        round(boosted_green * 255.0),
        round(boosted_blue * 255.0),
        text_colour.alpha,
    )


def _relative_luminance(colour: RgbaColour) -> float:
    """Return WCAG relative luminance for an opaque or translucent sRGB value."""
    channels = (colour.red / 255.0, colour.green / 255.0, colour.blue / 255.0)
    linear_channels = tuple(
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    )
    return (
        (0.2126 * linear_channels[0])
        + (0.7152 * linear_channels[1])
        + (0.0722 * linear_channels[2])
    )


def _region_frame(polygon: BoundingPolygon) -> _RegionFrame:
    vertices = polygon.vertices
    edge_start, edge_end = max(
        zip(vertices, vertices[1:] + vertices[:1], strict=True),
        key=lambda edge: _distance(edge[0], edge[1]),
    )
    edge_length = _distance(edge_start, edge_end)
    if edge_length == 0.0:
        message = "A text-region polygon must contain a non-zero-length edge."
        raise ValueError(message)
    detected_angle = degrees(atan2(edge_end.y - edge_start.y, edge_end.x - edge_start.x))
    return _region_frame_at_angle(polygon, _readable_baseline_angle(detected_angle))


def _readable_baseline_angle(angle_degrees: float) -> float:
    """Normalize equivalent OCR baseline directions to the readable half-turn."""
    return ((angle_degrees + 90.0) % 180.0) - 90.0


def _region_frame_at_angle(polygon: BoundingPolygon, angle_degrees: float) -> _RegionFrame:
    """Return the OCR polygon's local extents when drawn at ``angle_degrees``."""
    angle_radians = radians(angle_degrees)
    unit_x = cos(angle_radians)
    unit_y = sin(angle_radians)
    normal_x = -unit_y
    normal_y = unit_x
    vertices = polygon.vertices
    projected_x = tuple(point.x * unit_x + point.y * unit_y for point in vertices)
    projected_y = tuple(point.x * normal_x + point.y * normal_y for point in vertices)
    frame = _RegionFrame(
        angle_degrees=angle_degrees,
        minimum_x=min(projected_x),
        maximum_x=max(projected_x),
        minimum_y=min(projected_y),
        maximum_y=max(projected_y),
    )
    if frame.width <= 0.0 or frame.height <= 0.0:
        message = "A text-region polygon must enclose a non-zero area."
        raise ValueError(message)
    return frame


def _distance(first: PixelPoint, second: PixelPoint) -> float:
    return hypot(second.x - first.x, second.y - first.y)


def _polygon_path(polygon: BoundingPolygon) -> skia.Path:
    first, *remaining = polygon.vertices
    path = skia.Path()
    path.moveTo(first.x, first.y)
    for point in remaining:
        path.lineTo(point.x, point.y)
    path.close()
    return path


def _paint_for_colour(colour: RgbaColour) -> skia.Paint:
    paint = skia.Paint(AntiAlias=True)
    paint.setColor4f(
        skia.Color4f(
            colour.red / 255.0,
            colour.green / 255.0,
            colour.blue / 255.0,
            colour.alpha / 255.0,
        )
    )
    return paint


def _fit_text(
    text: str,
    typeface: skia.Typeface,
    width: float,
    height: float,
    is_axis_aligned: bool = False,
    accepts_layout: Callable[[_TextLayout], bool] | None = None,
) -> _TextLayout:
    largest_size = max(1, ceil(min(width, height)))
    for size in range(largest_size, 0, -1):
        font = skia.Font(typeface, float(size))
        if is_axis_aligned:
            _configure_axis_aligned_font(font)
        metrics = font.getMetrics()
        line_advance = metrics.fDescent - metrics.fAscent + metrics.fLeading
        lines = _wrap_text(text, font, width)
        line_bounds = tuple(_glyph_bounds(font, line) for line in lines)
        content_top, content_bottom = _content_vertical_bounds(line_bounds, line_advance)
        if _lines_fit(line_bounds, width, height, content_top, content_bottom):
            layout = _TextLayout(
                font=font,
                lines=lines,
                line_bounds=line_bounds,
                line_advance=line_advance,
                content_top=content_top,
                content_bottom=content_bottom,
            )
            if accepts_layout is None or accepts_layout(layout):
                return layout
    message = "Replacement text could not fit the OCR region at a one-pixel font size."
    raise ValueError(message)


def _select_render_plan(
    text: str, typeface: skia.Typeface, polygon: BoundingPolygon
) -> _RenderPlan:
    """Prefer a fully contained upright layout for small OCR-box skew."""
    render_plan = _select_render_plan_for_typeface(text, typeface, polygon)
    if render_plan.layout.font.getSize() >= SMALL_FONT_SIZE_THRESHOLD:
        return render_plan
    medium_typeface = _typeface_with_weight(typeface, SMALL_FONT_WEIGHT)
    if medium_typeface is None:
        return render_plan
    return _select_render_plan_for_typeface(text, medium_typeface, polygon)


def _select_render_plan_for_typeface(
    text: str, typeface: skia.Typeface, polygon: BoundingPolygon
) -> _RenderPlan:
    """Select the best geometric layout for one specific Skia typeface."""
    detected_frame = _region_frame(polygon)
    detected_layout = _fit_text(
        text,
        typeface,
        detected_frame.width,
        detected_frame.height,
        detected_frame.is_axis_aligned,
    )
    upright_plan = _upright_render_plan(
        text,
        typeface,
        polygon,
        detected_frame,
        minimum_font_size=detected_layout.font.getSize(),
    )
    if upright_plan is not None:
        return upright_plan
    return _RenderPlan(frame=detected_frame, layout=detected_layout)


def _typeface_with_weight(typeface: skia.Typeface, weight: float) -> skia.Typeface | None:
    """Clone a variable typeface at ``weight`` or retain no override for static fonts."""
    if not any(axis.tag == FONT_WEIGHT_AXIS_TAG for axis in typeface.getVariationDesignParameters()):
        return None
    arguments = skia.FontArguments()
    coordinates = skia.FontArguments.VariationPosition.Coordinates(
        [
            skia.FontArguments.VariationPosition.Coordinate(
                FONT_WEIGHT_AXIS_TAG, weight
            )
        ]
    )
    arguments.setVariationDesignPosition(skia.FontArguments.VariationPosition(coordinates))
    return typeface.makeClone(arguments)


def _upright_render_plan(
    text: str,
    typeface: skia.Typeface,
    polygon: BoundingPolygon,
    detected_frame: _RegionFrame,
    minimum_font_size: float,
) -> _RenderPlan | None:
    nearest_right_angle = round(detected_frame.angle_degrees / 90.0) * 90.0
    if (
        detected_frame.is_axis_aligned
        or abs(detected_frame.angle_degrees - nearest_right_angle)
        > UPRIGHT_LAYOUT_TOLERANCE_DEGREES
        or not _is_convex_polygon(polygon, nearest_right_angle)
    ):
        return None
    upright_frame = _region_frame_at_angle(polygon, nearest_right_angle)
    try:
        layout = _fit_text(
            text,
            typeface,
            upright_frame.width,
            upright_frame.height,
            is_axis_aligned=True,
            accepts_layout=lambda candidate: _contained_upright_offset(
                polygon, upright_frame, candidate
            )
            is not None,
        )
    except ValueError:
        return None
    if layout.font.getSize() < minimum_font_size:
        return None
    offset = _contained_upright_offset(polygon, upright_frame, layout)
    if offset is None:
        return None
    return _RenderPlan(frame=upright_frame, layout=layout, offset_x=offset[0], offset_y=offset[1])


def _configure_axis_aligned_font(font: skia.Font) -> None:
    """Configure a pixel-oriented font whose metrics are used for fitting and drawing."""
    font.setSubpixel(False)
    font.setHinting(skia.FontHinting.kFull)
    font.setForceAutoHinting(True)
    font.setEmbolden(True)


def _glyph_bounds(font: skia.Font, text: str) -> _GlyphBounds:
    """Return Skia's visible pixel bounds for one line at its drawing baseline."""
    bounds = skia.Rect.MakeEmpty()
    font.measureText(text, bounds=bounds)
    return _GlyphBounds(
        left=bounds.left(),
        top=bounds.top(),
        right=bounds.right(),
        bottom=bounds.bottom(),
    )


def _content_vertical_bounds(
    line_bounds: tuple[_GlyphBounds, ...], line_advance: float
) -> tuple[float, float]:
    """Return visible top and bottom bounds after applying baseline spacing."""
    if not any(bounds.height > 0.0 for bounds in line_bounds):
        return (0.0, 0.0)
    top = min(
        bounds.top + (line_index * line_advance)
        for line_index, bounds in enumerate(line_bounds)
        if bounds.height > 0.0
    )
    bottom = max(
        bounds.bottom + (line_index * line_advance)
        for line_index, bounds in enumerate(line_bounds)
        if bounds.height > 0.0
    )
    return (top, bottom)


def _wrap_text(text: str, font: skia.Font, width: float) -> tuple[str, ...]:
    lines: list[str] = []
    paragraphs = text.split("\n")
    for paragraph in paragraphs:
        lines.extend(_wrap_paragraph(paragraph, font, width))
    return tuple(lines)


def _wrap_paragraph(paragraph: str, font: skia.Font, width: float) -> list[str]:
    if not paragraph:
        return [""]
    words = re.findall(r"\S+", paragraph)
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        proposed = word if not current else f"{current} {word}"
        if font.measureText(proposed) <= width:
            current = proposed
            continue
        if current:
            lines.append(current)
        lines.extend(_wrap_word(word, font, width))
        current = lines.pop()
    if current:
        lines.append(current)
    return lines


def _wrap_word(word: str, font: skia.Font, width: float) -> list[str]:
    if font.measureText(word) <= width:
        return [word]
    pieces: list[str] = []
    current = ""
    for character in word:
        proposed = f"{current}{character}"
        if current and font.measureText(proposed) > width:
            pieces.append(current)
            current = character
        else:
            current = proposed
    if current:
        pieces.append(current)
    return pieces


def _lines_fit(
    line_bounds: tuple[_GlyphBounds, ...],
    width: float,
    height: float,
    content_top: float,
    content_bottom: float,
) -> bool:
    return (
        bool(line_bounds)
        and max(bounds.width for bounds in line_bounds) <= width
        and content_bottom - content_top <= height
    )


def _contained_upright_offset(
    polygon: BoundingPolygon, frame: _RegionFrame, layout: _TextLayout
) -> tuple[float, float] | None:
    """Return the nearest integer shift that keeps every visible line box in the polygon."""
    positions = _line_positions(frame, layout)
    rectangles = tuple(
        (
            x + bounds.left,
            baseline + bounds.top,
            x + bounds.right,
            baseline + bounds.bottom,
        )
        for (x, baseline), bounds in zip(positions, layout.line_bounds, strict=True)
    )
    if not rectangles:
        return (0.0, 0.0)
    visible_left = min(rectangle[0] for rectangle in rectangles)
    visible_top = min(rectangle[1] for rectangle in rectangles)
    visible_right = max(rectangle[2] for rectangle in rectangles)
    visible_bottom = max(rectangle[3] for rectangle in rectangles)
    minimum_x = ceil(frame.minimum_x - visible_left)
    maximum_x = floor(frame.maximum_x - visible_right)
    minimum_y = ceil(frame.minimum_y - visible_top)
    maximum_y = floor(frame.maximum_y - visible_bottom)
    if minimum_x > maximum_x or minimum_y > maximum_y:
        return None
    local_vertices = _local_vertices(polygon, frame.angle_degrees)
    for offset_y in _closest_integer_offsets(minimum_y, maximum_y):
        for offset_x in _closest_integer_offsets(minimum_x, maximum_x):
            if all(
                _rectangle_inside_convex_polygon(
                    rectangle, local_vertices, float(offset_x), float(offset_y)
                )
                for rectangle in rectangles
            ):
                return (float(offset_x), float(offset_y))
    return None


def _closest_integer_offsets(minimum: int, maximum: int) -> tuple[int, ...]:
    """Return candidate integral shifts in centre-first order."""
    return tuple(sorted(range(minimum, maximum + 1), key=lambda value: (abs(value), value)))


def _local_vertices(polygon: BoundingPolygon, angle_degrees: float) -> tuple[PixelPoint, ...]:
    """Rotate source vertices into the text frame without translating their origin."""
    angle_radians = radians(angle_degrees)
    unit_x = cos(angle_radians)
    unit_y = sin(angle_radians)
    return tuple(
        PixelPoint(
            x=(point.x * unit_x) + (point.y * unit_y),
            y=(-point.x * unit_y) + (point.y * unit_x),
        )
        for point in polygon.vertices
    )


def _is_convex_polygon(polygon: BoundingPolygon, angle_degrees: float) -> bool:
    """Return whether the candidate's local polygon supports corner-only containment."""
    vertices = _local_vertices(polygon, angle_degrees)
    signs: list[float] = []
    for first, second, third in zip(
        vertices, vertices[1:] + vertices[:1], vertices[2:] + vertices[:2], strict=True
    ):
        cross_product = (
            (second.x - first.x) * (third.y - second.y)
            - (second.y - first.y) * (third.x - second.x)
        )
        if abs(cross_product) > 1e-6:
            signs.append(cross_product)
    return bool(signs) and (
        all(sign > 0.0 for sign in signs) or all(sign < 0.0 for sign in signs)
    )


def _rectangle_inside_convex_polygon(
    rectangle: tuple[float, float, float, float],
    vertices: tuple[PixelPoint, ...],
    offset_x: float,
    offset_y: float,
) -> bool:
    """Return whether every rectangle corner is inside one convex local polygon."""
    left, top, right, bottom = rectangle
    return all(
        _point_inside_convex_polygon(PixelPoint(x + offset_x, y + offset_y), vertices)
        for x, y in ((left, top), (right, top), (right, bottom), (left, bottom))
    )


def _point_inside_convex_polygon(point: PixelPoint, vertices: tuple[PixelPoint, ...]) -> bool:
    """Treat an edge point as inside and otherwise require a consistent cross-product sign."""
    signs: list[float] = []
    for first, second in zip(vertices, vertices[1:] + vertices[:1], strict=True):
        cross_product = (
            (second.x - first.x) * (point.y - first.y)
            - (second.y - first.y) * (point.x - first.x)
        )
        if abs(cross_product) > 1e-6:
            signs.append(cross_product)
    return not signs or all(sign > 0.0 for sign in signs) or all(sign < 0.0 for sign in signs)


def _draw_layout(
    canvas: skia.Canvas,
    path: skia.Path,
    render_plan: _RenderPlan,
    text_colour: RgbaColour,
) -> None:
    frame = render_plan.frame
    layout = render_plan.layout
    content_height = layout.content_bottom - layout.content_top
    paint = _paint_for_colour(text_colour)
    canvas.save()
    canvas.clipPath(path, skia.ClipOp.kIntersect, True)
    canvas.rotate(frame.angle_degrees)
    for line, (x, baseline) in zip(
        layout.lines,
        _line_positions(frame, layout, render_plan.offset_x, render_plan.offset_y),
        strict=True,
    ):
        canvas.drawString(line, x, baseline, layout.font, paint)
    canvas.restore()


def _line_positions(
    frame: _RegionFrame,
    layout: _TextLayout,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> tuple[tuple[float, float], ...]:
    """Return each line's drawing origin and baseline in the local text frame."""
    content_height = layout.content_bottom - layout.content_top
    first_baseline = frame.minimum_y + ((frame.height - content_height) / 2.0) - layout.content_top
    return tuple(
        (
            _placement_coordinate(
                frame.minimum_x + ((frame.width - bounds.width) / 2.0) - bounds.left + offset_x,
                frame.is_axis_aligned,
            ),
            _placement_coordinate(
                first_baseline + (line_index * layout.line_advance) + offset_y,
                frame.is_axis_aligned,
            ),
        )
        for line_index, bounds in enumerate(layout.line_bounds)
    )


def _placement_coordinate(coordinate: float, is_axis_aligned: bool) -> float:
    """Snap only text that remains aligned with source-image pixel axes."""
    return float(round(coordinate)) if is_axis_aligned else coordinate
