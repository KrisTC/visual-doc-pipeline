"""Shared plan and apply steps for every supported raster bitmap.

``plan_bitmap`` runs OCR once and decides which regions need text. ``apply_bitmap``
renders the replacements it is handed. Neither step calls a text-replacement
provider: the texts travel through a translation engine in between.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import skia  # type: ignore[import-not-found]
from PIL import Image

from pipeline.folder_replacement.common import TEXT_REPLACEMENT_MINIMUM_CONFIDENCE
from pipeline.ocr import OcrProvider, OcrRequest
from pipeline.ocr.image_preparation import DEFAULT_OCR_BACKGROUND, RgbColour, opaque_rgb_for_ocr
from pipeline.ocr.models import OcrText
from pipeline.text_region_colours import estimate_replacement_colours
from pipeline.text_region_colours.models import TextRegionColourEstimate
from pipeline.text_region_rendering import TextRegionReplacement, replace_text_regions
from pipeline.text_replacement import (
    TextReplacementItem,
    TextReplacementProvider,
    TextUnit,
    TranslationEngine,
)

BITMAP_UNIT_ID = "image"


@dataclass(slots=True)
class BitmapPlan:
    """The OCR regions of one image that need replacement text.

    ``image`` is modified in place by ``apply_bitmap``. ``page_colour`` is what shows
    through the image's transparent pixels.
    """

    image: Image.Image
    format_name: str | None
    regions: list[tuple[OcrText, TextRegionColourEstimate]]
    unit_id: str = BITMAP_UNIT_ID
    page_colour: RgbColour = DEFAULT_OCR_BACKGROUND

    def units(self) -> Iterator[TextUnit]:
        """Yield this image's single unit with one text per region, in OCR order."""
        yield TextUnit(self.unit_id, tuple(region.text for region, _ in self.regions))


def plan_bitmap(
    image: Image.Image,
    ocr: OcrProvider,
    source_language: str,
    *,
    format_name: str | None = None,
    unit_id: str = BITMAP_UNIT_ID,
    ocr_background: RgbColour = DEFAULT_OCR_BACKGROUND,
    nested_completed: Callable[[str], None] | None = None,
) -> BitmapPlan:
    """Run OCR once and keep the confident regions with their estimated colours."""
    ocr_image = opaque_rgb_for_ocr(image, ocr_background)
    detected = ocr.recognize(OcrRequest(ocr_image, source_language)).text_items
    if nested_completed is not None:
        nested_completed("OCR recognition")
    confident = [
        item for item in detected if item.confidence >= TEXT_REPLACEMENT_MINIMUM_CONFIDENCE
    ]
    regions = list(
        zip(
            confident,
            estimate_replacement_colours(image, confident, ocr_background),
            strict=True,
        )
    )
    if nested_completed is not None:
        nested_completed("process OCR results")
    return BitmapPlan(image, format_name, regions, unit_id, ocr_background)


def apply_bitmap(
    plan: BitmapPlan,
    translate: Callable[[str], TextReplacementItem],
    typeface: skia.Typeface,
    target_language: str,
    *,
    nested_completed: Callable[[str], None] | None = None,
) -> int:
    """Render the translated regions into the planned image and return the region count."""
    prepared = [
        TextRegionReplacement(region, colours, translate(region.text).text)
        for region, colours in plan.regions
    ]
    replace_text_regions(plan.image, prepared, typeface, target_language, plan.page_colour)
    if nested_completed is not None:
        nested_completed("render replacement image")
    return len(prepared)


def plan_bitmap_file(
    source: Path, ocr: OcrProvider, source_language: str, *, unit_id: str = BITMAP_UNIT_ID
) -> BitmapPlan:
    """Plan a bitmap file, remembering its format so it can be saved back."""
    with Image.open(source) as opened:
        image, format_name = _replacement_image(opened.copy()), opened.format
    if format_name is None:
        raise ValueError(f"Could not determine bitmap format: {source}")
    return plan_bitmap(image, ocr, source_language, format_name=format_name, unit_id=unit_id)


def plan_bitmap_bytes(
    data: bytes,
    ocr: OcrProvider,
    source_language: str,
    *,
    unit_id: str = BITMAP_UNIT_ID,
    ocr_background: RgbColour = DEFAULT_OCR_BACKGROUND,
    nested_completed: Callable[[str], None] | None = None,
) -> BitmapPlan:
    """Plan embedded bitmap bytes, remembering their format so they can be re-encoded."""
    with Image.open(BytesIO(data)) as opened:
        image, format_name = _replacement_image(opened.copy()), opened.format
    if format_name is None:
        raise ValueError("Could not determine embedded bitmap format.")
    return plan_bitmap(
        image, ocr, source_language, format_name=format_name, unit_id=unit_id,
        ocr_background=ocr_background, nested_completed=nested_completed,
    )


def save_bitmap_file(plan: BitmapPlan, destination: Path) -> None:
    """Write the applied image in its source format."""
    plan.image.save(destination, format=plan.format_name)


def bitmap_plan_bytes(plan: BitmapPlan) -> bytes:
    """Return the applied image encoded in its source format."""
    output = BytesIO()
    plan.image.save(output, format=plan.format_name)
    return output.getvalue()


def replace_bitmap_file(
    source: Path,
    destination: Path,
    ocr: OcrProvider,
    replacement: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typeface: skia.Typeface,
) -> int:
    """Replace one bitmap file through its own one-image engine."""
    plan = plan_bitmap_file(source, ocr, source_language)
    count = _apply_with_own_engine(plan, replacement, source_language, target_language, typeface)
    save_bitmap_file(plan, destination)
    return count


def replace_bitmap_bytes(
    data: bytes,
    ocr: OcrProvider,
    replacement: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typeface: skia.Typeface,
    ocr_background: RgbColour = DEFAULT_OCR_BACKGROUND,
    nested_completed: Callable[[str], None] | None = None,
) -> tuple[bytes, int]:
    """Replace embedded bitmap bytes through their own one-image engine."""
    plan = plan_bitmap_bytes(
        data, ocr, source_language, ocr_background=ocr_background, nested_completed=nested_completed
    )
    count = _apply_with_own_engine(
        plan, replacement, source_language, target_language, typeface, nested_completed
    )
    return bitmap_plan_bytes(plan), count


def replace_image(
    image: Image.Image,
    ocr: OcrProvider,
    replacement: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typeface: skia.Typeface,
    ocr_background: RgbColour = DEFAULT_OCR_BACKGROUND,
    nested_completed: Callable[[str], None] | None = None,
) -> int:
    """Replace the text in an in-memory image through its own one-image engine."""
    plan = plan_bitmap(
        image, ocr, source_language, ocr_background=ocr_background, nested_completed=nested_completed
    )
    return _apply_with_own_engine(
        plan, replacement, source_language, target_language, typeface, nested_completed
    )


def _apply_with_own_engine(
    plan: BitmapPlan,
    replacement: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typeface: skia.Typeface,
    nested_completed: Callable[[str], None] | None = None,
) -> int:
    """Resolve one image's texts together, then apply them.

    Callers that have not yet moved to a per-source engine use this, so a bitmap
    still sends one request per batch rather than one per region.
    """
    engine = TranslationEngine(replacement, source_language, target_language)
    for unit in plan.units():
        engine.add_unit(unit.unit_id, unit.texts)
    engine.resolve()
    return apply_bitmap(plan, engine.lookup, typeface, target_language, nested_completed=nested_completed)


def _replacement_image(image: Image.Image) -> Image.Image:
    """Return an alpha-capable image for a transparent indexed-PNG replacement."""
    if image.mode == "P" and "transparency" in image.info:
        return image.convert("RGBA")
    return image
