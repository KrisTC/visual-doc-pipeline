"""Deterministic local colour estimation for OCR text regions."""

from __future__ import annotations

from collections import deque
from math import ceil, floor
from typing import cast

import numpy as np
import numpy.typing as npt
from PIL import Image, ImageDraw

from pipeline.ocr.models import BoundingPolygon, OcrText
from pipeline.text_region_colours.models import (
    BackgroundKind,
    RgbaColour,
    TextRegionColourEstimate,
)

_DEFAULT_PADDING = 12
_RING_WIDTH = 3
_MAX_CLUSTERS = 4
_MAX_TEXT_DISTANCE_THRESHOLD = 32.0
_MINIMUM_TRANSPARENT_BACKGROUND_SUPPORT = 0.25
_FloatArray = npt.NDArray[np.float64]
_BoolArray = npt.NDArray[np.bool_]
_IntArray = npt.NDArray[np.intp]
_UInt8Array = npt.NDArray[np.uint8]


def estimate_text_region_colours(
    image: Image.Image,
    text_region: OcrText,
    *,
    padding: int = _DEFAULT_PADDING,
) -> TextRegionColourEstimate:
    """Estimate foreground and local-background colours for ``text_region``.

    Args:
        image: Original in-memory source image. It may use any Pillow-supported
            mode; the estimator reads it as RGBA and does not modify it.
        text_region: OCR text item whose bounding polygon identifies the region to
            analyse. The item's recognized string and OCR confidence are not inputs
            to the colour calculation.
        padding: Non-negative source-image pixels to sample beyond the polygon's
            bounds on every side. The default of 12 provides local background
            evidence while remaining constrained to the image bounds.

    Returns:
        A primary text colour, immediate glyph-background colour, confidence scores,
        and background classification. Colour values are observed non-premultiplied
        eight-bit sRGB RGBA values. Confidence scores are deterministic heuristic
        reliability signals, not probabilities or OCR confidence values.

    Raises:
        ValueError: If ``padding`` is negative or the polygon has no overlap with
            the source image.
    """
    if padding < 0:
        message = "padding must not be negative."
        raise ValueError(message)

    rgba = np.array(image.convert("RGBA"), dtype=np.uint8)
    left, top, right, bottom = _padded_bounds(
        text_region.bounding_polygon, image.width, image.height, padding
    )
    crop_rgba = rgba[top:bottom, left:right]
    polygon_mask = _polygon_mask(
        text_region.bounding_polygon, crop_rgba.shape[1], crop_rgba.shape[0], left, top
    )
    if not np.any(polygon_mask):
        message = "The OCR bounding polygon does not overlap the source image."
        raise ValueError(message)

    crop_lab = _rgb_to_lab(crop_rgba[:, :, :3])
    ring_mask = _outer_ring_mask(crop_rgba.shape[1], crop_rgba.shape[0])
    ring_mask &= crop_rgba[:, :, 3] > 0
    if not np.any(ring_mask):
        ring_mask = _outer_ring_mask(crop_rgba.shape[1], crop_rgba.shape[0])

    transparent_background_mask = polygon_mask & (crop_rgba[:, :, 3] == 0)
    if _has_supported_transparent_background(transparent_background_mask, polygon_mask):
        (
            background_lab,
            background_colour,
            background_spread,
            background_mask,
            background_support,
            background_centres,
        ) = _transparent_background(
            crop_lab, crop_rgba, transparent_background_mask, polygon_mask
        )
    else:
        (
            background_lab,
            background_colour,
            background_spread,
            background_mask,
            background_support,
            background_centres,
        ) = _immediate_background(crop_lab, crop_rgba, polygon_mask, ring_mask)
    # Secondary clusters filter broad patterned background areas. They can however
    # include a glyph shade, so fall back to the dominant surface when they leave
    # too little evidence for a credible text candidate.
    background_distances = _nearest_colour_distance(crop_lab, background_centres)
    threshold = min(
        _MAX_TEXT_DISTANCE_THRESHOLD,
        max(10.0, 3.0 * background_spread + 8.0),
    )
    raw_text_mask = (
        polygon_mask
        & (crop_rgba[:, :, 3] > 0)
        & (background_distances >= threshold)
    )
    text_mask = _remove_small_components(_remove_isolated_pixels(raw_text_mask), 2)
    minimum_text_pixels = max(8, ceil(np.count_nonzero(polygon_mask) * 0.01))
    if np.count_nonzero(text_mask) < minimum_text_pixels:
        dominant_text_mask = (
            polygon_mask
            & (crop_rgba[:, :, 3] > 0)
            & (_colour_distances(crop_lab, background_lab) >= threshold)
        )
        text_mask = _remove_small_components(_remove_isolated_pixels(dominant_text_mask), 2)

    if np.any(text_mask):
        text_lab, text_colour, text_spread, geometry_score, separation_score = (
            _primary_text_colour(
                crop_lab,
                crop_rgba,
                text_mask,
                background_mask,
                polygon_mask,
                background_lab,
            )
        )
    else:
        text_lab = background_lab
        text_colour = background_colour
        text_spread = 100.0
        geometry_score = 0.0
        separation_score = 0.0

    background_kind = _classify_background(
        crop_lab,
        polygon_mask,
        text_mask,
        background_mask,
        background_lab,
        background_support,
    )
    text_confidence = _text_confidence(
        text_mask,
        text_lab,
        background_lab,
        text_spread,
        geometry_score,
        separation_score,
    )
    background_confidence = _background_confidence(background_spread, background_support)
    return TextRegionColourEstimate(
        text_colour=text_colour,
        background_colour=background_colour,
        text_colour_confidence=text_confidence,
        background_colour_confidence=background_confidence,
        background_kind=background_kind,
    )


def _padded_bounds(
    polygon: BoundingPolygon, image_width: int, image_height: int, padding: int
) -> tuple[int, int, int, int]:
    xs = [point.x for point in polygon.vertices]
    ys = [point.y for point in polygon.vertices]
    left = max(0, floor(min(xs)) - padding)
    top = max(0, floor(min(ys)) - padding)
    right = min(image_width, ceil(max(xs)) + padding + 1)
    bottom = min(image_height, ceil(max(ys)) + padding + 1)
    if left >= right or top >= bottom:
        message = "The OCR bounding polygon has no overlapping source-image bounds."
        raise ValueError(message)
    return left, top, right, bottom


def _polygon_mask(
    polygon: BoundingPolygon, width: int, height: int, left: int, top: int) -> _BoolArray:
    mask_image = Image.new("1", (width, height), 0)
    ImageDraw.Draw(mask_image).polygon(
        [(point.x - left, point.y - top) for point in polygon.vertices], fill=1
    )
    return np.array(mask_image, dtype=bool)


def _outer_ring_mask(width: int, height: int) -> _BoolArray:
    ring_width = min(_RING_WIDTH, max(1, min(width, height) // 2))
    mask = np.zeros((height, width), dtype=bool)
    mask[:ring_width, :] = True
    mask[-ring_width:, :] = True
    mask[:, :ring_width] = True
    mask[:, -ring_width:] = True
    return mask


def _rgb_to_lab(rgb: _UInt8Array) -> _FloatArray:
    rgb_float = rgb.astype(np.float64) / 255.0
    linear_rgb = np.where(
        rgb_float <= 0.04045,
        rgb_float / 12.92,
        ((rgb_float + 0.055) / 1.055) ** 2.4,
    )
    matrix: _FloatArray = np.array(
        (
            (0.4124564, 0.3575761, 0.1804375),
            (0.2126729, 0.7151522, 0.0721750),
            (0.0193339, 0.1191920, 0.9503041),
        ),
        dtype=np.float64,
    )
    xyz = linear_rgb @ matrix.T
    normalized_xyz = xyz / np.array((0.95047, 1.0, 1.08883), dtype=np.float64)
    delta = 6.0 / 29.0
    lab_basis = np.where(
        normalized_xyz > delta**3,
        np.cbrt(normalized_xyz),
        normalized_xyz / (3.0 * delta**2) + 4.0 / 29.0,
    )
    return np.stack(
        (
            116.0 * lab_basis[:, :, 1] - 16.0,
            500.0 * (lab_basis[:, :, 0] - lab_basis[:, :, 1]),
            200.0 * (lab_basis[:, :, 1] - lab_basis[:, :, 2]),
        ),
        axis=2,
    )


def _dominant_colour(lab_values: _FloatArray, rgba_values: _UInt8Array) -> tuple[_FloatArray, RgbaColour, float]:
    if len(lab_values) == 0:
        message = "Colour estimation requires at least one pixel."
        raise ValueError(message)
    labels, centers = _cluster_colours(lab_values)
    counts = np.bincount(labels, minlength=len(centers))
    dominant_label = int(np.argmax(counts))
    selected_lab = lab_values[labels == dominant_label]
    selected_rgba = rgba_values[labels == dominant_label]
    median_lab = np.median(selected_lab, axis=0)
    median_rgba = np.rint(np.median(selected_rgba, axis=0)).astype(np.uint8)
    spread = float(np.percentile(_colour_distances(selected_lab, median_lab), 75))
    return median_lab, _to_colour(median_rgba), spread


def _cluster_colours(values: _FloatArray) -> tuple[_IntArray, _FloatArray]:
    cluster_count = min(_MAX_CLUSTERS, len(values))
    centers = np.empty((cluster_count, 3), dtype=np.float64)
    centers[0] = np.median(values, axis=0)
    nearest_distance = _colour_distances(values, centers[0])
    for index in range(1, cluster_count):
        centers[index] = values[int(np.argmax(nearest_distance))]
        nearest_distance = np.minimum(
            nearest_distance, _colour_distances(values, centers[index])
        )

    labels = np.zeros(len(values), dtype=np.intp)
    for _ in range(16):
        distances = np.linalg.norm(values[:, np.newaxis, :] - centers[np.newaxis, :, :], axis=2)
        new_labels = np.argmin(distances, axis=1).astype(np.intp)
        new_centers = centers.copy()
        for index in range(cluster_count):
            members = values[new_labels == index]
            if len(members):
                new_centers[index] = np.mean(members, axis=0)
        if np.array_equal(new_labels, labels):
            labels = new_labels
            break
        labels = new_labels
        centers = new_centers
    return labels, centers


def _colour_distances(values: _FloatArray, colour: _FloatArray) -> _FloatArray:
    squared_distances = np.sum(np.square(values - colour), axis=-1)
    # NumPy's shape-polymorphic ufunc stubs expose this array result as Any.
    return cast(_FloatArray, np.sqrt(squared_distances))


def _nearest_colour_distance(values: _FloatArray, colours: _FloatArray) -> _FloatArray:
    squared_distances = np.sum(
        np.square(values[:, :, np.newaxis, :] - colours[np.newaxis, np.newaxis, :, :]), axis=3
    )
    # NumPy's shape-polymorphic ufunc and reduction stubs expose this result as Any.
    return cast(_FloatArray, np.sqrt(squared_distances).min(axis=2))


def _immediate_background(
    lab: _FloatArray,
    rgba: _UInt8Array,
    polygon_mask: _BoolArray,
    ring_mask: _BoolArray,
) -> tuple[_FloatArray, RgbaColour, float, _BoolArray, float, _FloatArray]:
    """Find broad interior background evidence before considering outer context."""
    polygon_lab = lab[polygon_mask]
    polygon_rgba = rgba[polygon_mask]
    labels, centers = _cluster_colours(polygon_lab)
    counts = np.bincount(labels, minlength=len(centers))
    dominant_index = int(np.argmax(counts))
    broad_cluster_minimum = max(12, ceil(len(polygon_lab) * 0.12))
    broad_indices = np.flatnonzero(counts >= broad_cluster_minimum)
    if len(broad_indices) == 0:
        broad_indices = np.array((dominant_index,), dtype=np.intp)
    background_centres = centers[broad_indices]
    dominant_lab = polygon_lab[labels == dominant_index]
    dominant_rgba = polygon_rgba[labels == dominant_index]
    background_lab = np.median(dominant_lab, axis=0)
    background_spread = float(
        np.percentile(_colour_distances(dominant_lab, background_lab), 75)
    )
    nearest_background_distance = _nearest_colour_distance(lab, background_centres)
    background_mask = polygon_mask & (
        nearest_background_distance <= max(8.0, 3.0 * background_spread + 6.0)
    )
    dominant_support = counts[dominant_index] / len(polygon_lab)
    ring_lab, _, _ = _dominant_colour(lab[ring_mask], rgba[ring_mask])
    significant_internal_contrast = any(
        member_count >= max(3, ceil(len(polygon_lab) * 0.03))
        and float(_colour_distances(centers[index], background_lab)) >= 15.0
        for index, member_count in enumerate(counts)
        if index != dominant_index
    )
    prefer_outer_context = (
        len(broad_indices) == 1
        and float(_colour_distances(background_lab, ring_lab)) >= 15.0
        and not significant_internal_contrast
    )
    if np.count_nonzero(background_mask) < 3 or prefer_outer_context:
        # A near-solid glyph crop can contain too little interior surface. In that
        # case, preserve the historical outer-ring estimate as the fallback.
        background_lab, background_colour, background_spread = _dominant_colour(
            lab[ring_mask], rgba[ring_mask]
        )
        background_mask = polygon_mask & (
            _colour_distances(lab, background_lab)
            <= max(8.0, 3.0 * background_spread + 6.0)
        )
        background_centres = np.expand_dims(background_lab, axis=0)
        dominant_support = np.count_nonzero(background_mask) / np.count_nonzero(polygon_mask)
    else:
        background_colour = _to_colour(
            np.rint(np.median(dominant_rgba, axis=0)).astype(np.uint8)
        )
    return (
        background_lab,
        background_colour,
        background_spread,
        background_mask,
        float(dominant_support),
        background_centres,
    )


def _has_supported_transparent_background(
    transparent_mask: _BoolArray, polygon_mask: _BoolArray
) -> bool:
    """Return whether transparent pixels make up a credible local surface."""
    transparent_pixels = int(np.count_nonzero(transparent_mask))
    minimum_pixels = max(
        3,
        ceil(np.count_nonzero(polygon_mask) * _MINIMUM_TRANSPARENT_BACKGROUND_SUPPORT),
    )
    return transparent_pixels >= minimum_pixels


def _transparent_background(
    lab: _FloatArray,
    rgba: _UInt8Array,
    transparent_mask: _BoolArray,
    polygon_mask: _BoolArray,
) -> tuple[_FloatArray, RgbaColour, float, _BoolArray, float, _FloatArray]:
    """Use a sufficiently broad alpha-zero surface as immediate background evidence."""
    values = lab[transparent_mask]
    rgba_values = rgba[transparent_mask]
    background_lab = np.median(values, axis=0)
    median_rgba = np.rint(np.median(rgba_values, axis=0)).astype(np.uint8)
    background_spread = float(
        np.percentile(_colour_distances(values, background_lab), 75)
    )
    background_support = np.count_nonzero(transparent_mask) / np.count_nonzero(polygon_mask)
    return (
        background_lab,
        _to_colour(median_rgba),
        background_spread,
        transparent_mask,
        float(background_support),
        np.expand_dims(background_lab, axis=0),
    )


def _primary_text_colour(
    lab: _FloatArray,
    rgba: _UInt8Array,
    text_mask: _BoolArray,
    background_mask: _BoolArray,
    polygon_mask: _BoolArray,
    background_colour: _FloatArray,
) -> tuple[_FloatArray, RgbaColour, float, float, float]:
    """Select a compact, stroke-like candidate over large contrasting fills."""
    values = lab[text_mask]
    rgba_values = rgba[text_mask]
    labels, centers = _cluster_colours(values)
    label_image = np.full(text_mask.shape, -1, dtype=np.intp)
    label_image[text_mask] = labels
    background_edge = _dilate(background_mask)
    candidates: list[tuple[float, int, _FloatArray, _BoolArray, float]] = []
    minimum_members = max(8, ceil(np.count_nonzero(polygon_mask) * 0.01), len(values) // 50)
    for index, center in enumerate(centers):
        cluster_mask = label_image == index
        member_count = int(np.count_nonzero(cluster_mask))
        if member_count < minimum_members:
            continue
        contrast = min(1.0, float(_colour_distances(center, background_colour)) / 45.0)
        if contrast < 0.25:
            continue
        background_contact = np.count_nonzero(cluster_mask & background_edge) / member_count
        core_ratio = np.count_nonzero(_erode(cluster_mask)) / member_count
        area_ratio = member_count / np.count_nonzero(polygon_mask)
        stroke_score = min(1.0, 0.28 / max(area_ratio, 0.01))
        geometry_score = (
            0.55 * (1.0 - background_contact)
            + 0.25 * min(1.0, core_ratio / 0.1)
            + 0.20 * stroke_score
        )
        purity = max(0.0, 1.0 - float(np.percentile(_colour_distances(values[labels == index], center), 75)) / 25.0)
        # Thin glyphs can legitimately have no eroded core, especially when a
        # provider supplies a loose box. Contrast is therefore weighted above
        # interior thickness, while geometry still rejects broad background fills.
        score = 0.35 * geometry_score + 0.45 * contrast + 0.2 * purity
        candidates.append((score, index, center, cluster_mask, geometry_score))
    if not candidates:
        text_lab, text_colour, text_spread = _dominant_colour(lab[text_mask], rgba[text_mask])
        return text_lab, text_colour, text_spread, 0.0, 0.0

    ranked_candidates = sorted(candidates, reverse=True, key=lambda candidate: candidate[0])
    _, _, _, selected_mask, selected_geometry_score = ranked_candidates[0]
    selected_lab = lab[selected_mask]
    selected_rgba = rgba[selected_mask]
    median_lab = np.median(selected_lab, axis=0)
    median_rgba = np.rint(np.median(selected_rgba, axis=0)).astype(np.uint8)
    spread = float(np.percentile(_colour_distances(selected_lab, median_lab), 75))
    separation = (
        (ranked_candidates[0][0] - ranked_candidates[1][0]) / ranked_candidates[0][0]
        if len(ranked_candidates) > 1 and ranked_candidates[0][0] > 0.0
        else 0.5
    )
    return median_lab, _to_colour(median_rgba), spread, float(selected_geometry_score), separation


def _remove_isolated_pixels(mask: _BoolArray) -> _BoolArray:
    padded = np.pad(mask, 1, constant_values=False)
    neighbours = np.zeros(mask.shape, dtype=np.intp)
    height, width = mask.shape
    for row_offset in range(3):
        for column_offset in range(3):
            neighbours += padded[row_offset : row_offset + height, column_offset : column_offset + width]
    return mask & (neighbours >= 2)


def _remove_small_components(mask: _BoolArray, minimum_size: int) -> _BoolArray:
    height, width = mask.shape
    visited = np.zeros_like(mask)
    retained = np.zeros_like(mask)
    for row in range(height):
        for column in range(width):
            if not mask[row, column] or visited[row, column]:
                continue
            component: list[tuple[int, int]] = []
            pending: deque[tuple[int, int]] = deque([(row, column)])
            visited[row, column] = True
            while pending:
                current_row, current_column = pending.pop()
                component.append((current_row, current_column))
                for row_offset in (-1, 0, 1):
                    for column_offset in (-1, 0, 1):
                        neighbour_row = current_row + row_offset
                        neighbour_column = current_column + column_offset
                        if (
                            0 <= neighbour_row < height
                            and 0 <= neighbour_column < width
                            and mask[neighbour_row, neighbour_column]
                            and not visited[neighbour_row, neighbour_column]
                        ):
                            visited[neighbour_row, neighbour_column] = True
                            pending.append((neighbour_row, neighbour_column))
            if len(component) >= minimum_size:
                for component_row, component_column in component:
                    retained[component_row, component_column] = True
    return retained


def _erode(mask: _BoolArray) -> _BoolArray:
    padded = np.pad(mask, 1, constant_values=False)
    height, width = mask.shape
    eroded = np.ones(mask.shape, dtype=bool)
    for row_offset in range(3):
        for column_offset in range(3):
            eroded &= padded[row_offset : row_offset + height, column_offset : column_offset + width]
    return eroded


def _classify_background(
    lab: _FloatArray,
    polygon_mask: _BoolArray,
    text_mask: _BoolArray,
    background_mask: _BoolArray,
    background: _FloatArray,
    background_support: float,
) -> BackgroundKind:
    values = lab[background_mask] if background_support >= 0.65 else lab[polygon_mask & ~text_mask]
    if len(values) < 3:
        return BackgroundKind.COMPLEX
    variation = float(np.percentile(_colour_distances(values, background), 90))
    if variation <= 2.0:
        return BackgroundKind.FLAT
    return BackgroundKind.GRADIENT if variation <= 20.0 else BackgroundKind.COMPLEX


def _text_confidence(
    text_mask: _BoolArray,
    text_colour: _FloatArray,
    background_colour: _FloatArray,
    text_spread: float,
    geometry_score: float,
    separation_score: float,
) -> float:
    text_size = int(np.count_nonzero(text_mask))
    if not text_size:
        return 0.0
    contrast = min(1.0, float(_colour_distances(text_colour, background_colour)) / 45.0)
    consistency = max(0.0, 1.0 - text_spread / 25.0)
    evidence = min(1.0, text_size / 8.0)
    return min(
        1.0,
        0.3 * contrast
        + 0.25 * consistency
        + 0.25 * geometry_score
        + 0.15 * separation_score
        + 0.05 * evidence,
    )


def _background_confidence(spread: float, support: float) -> float:
    consistency = max(0.0, 1.0 - spread / 30.0)
    support_score = min(1.0, 0.35 + 0.65 * support)
    return float(support_score * consistency)


def _dilate(mask: _BoolArray) -> _BoolArray:
    padded = np.pad(mask, 1, constant_values=False)
    height, width = mask.shape
    dilated = np.zeros(mask.shape, dtype=bool)
    for row_offset in range(3):
        for column_offset in range(3):
            dilated |= padded[row_offset : row_offset + height, column_offset : column_offset + width]
    return dilated


def _to_colour(values: _UInt8Array) -> RgbaColour:
    return RgbaColour(int(values[0]), int(values[1]), int(values[2]), int(values[3]))
