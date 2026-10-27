"""Shared plan and apply steps for the media inside an Office package.

A DOCX, PPTX or XLSX package holds bitmaps and vector graphics under ``media/``. Each is
planned as a nested unit of its parent document by the same functions that process it
as a root file. Planning runs OCR once and lists the texts; applying renders the
engine's translations and returns the re-encoded part.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import skia  # type: ignore[import-not-found]

from pipeline.folder_replacement.bitmap import (
    BitmapPlan,
    apply_bitmap,
    bitmap_plan_bytes,
    plan_bitmap_bytes,
)
from pipeline.folder_replacement.common import (
    NestedProgressReporter,
    is_office_bitmap_part,
    is_office_vector_part,
)
from pipeline.folder_replacement.failure_diagnostics import FailureContext
from pipeline.folder_replacement.planning import child_unit_id, enter_nested
from pipeline.folder_replacement.vector import VectorPlan, apply_vector, plan_vector
from pipeline.ocr import OcrProvider
from pipeline.ocr.image_preparation import DEFAULT_OCR_BACKGROUND, RgbColour
from pipeline.text_replacement import TextReplacementItem, TextUnit
from pipeline.vector_text import VectorReplacementResult

_BITMAP_PLAN_STAGES = 2


@dataclass(slots=True)
class OfficeMediaPlan:
    """The plan of one bitmap or vector part of an Office package."""

    part: str
    bitmap: BitmapPlan | None = None
    vector: VectorPlan | None = None

    def units(self) -> Iterator[TextUnit]:
        """Yield the media part's units, nested ones included."""
        if self.bitmap is not None:
            yield from self.bitmap.units()
        if self.vector is not None:
            yield from self.vector.units()


@dataclass(slots=True)
class OfficeMediaResult:
    """The re-encoded media part and what was replaced in it."""

    data: bytes
    native_items: int = 0
    image_regions: int = 0
    vector_result: VectorReplacementResult | None = None
    diagnostics: tuple[dict[str, object], ...] = ()


def is_office_media_part(name: str, *, include_vectors: bool = True) -> bool:
    """Return whether a package part is a bitmap, or a vector graphic when included."""
    return is_office_bitmap_part(name) or (include_vectors and is_office_vector_part(name))


def plan_office_media(
    part: str,
    data: bytes,
    ocr: OcrProvider,
    source_language: str,
    target_language: str,
    *,
    parent_unit_id: str,
    media_number: int,
    depth: int,
    diagnostics: list[dict[str, object]] | None = None,
    document_text_layout: str = "preserve-source-formatting",
    nested_progress: NestedProgressReporter | None = None,
    failure_context: FailureContext | None = None,
    ocr_background: RgbColour = DEFAULT_OCR_BACKGROUND,
) -> OfficeMediaPlan | None:
    """Plan one media part as a nested unit, or None when it is too deep to process.

    ``depth`` is the parent document's depth below the root file. ``media_number`` counts
    bitmaps and vector graphics separately, from 1, so unit ids stay stable.
    ``ocr_background`` is the colour a bitmap is read against, such as a Word page colour.
    """
    child_depth = enter_nested(depth, part, diagnostics)
    if child_depth is None:
        return None
    if is_office_bitmap_part(part):
        if failure_context is not None:
            failure_context.set_location(
                stage="embedded_bitmap",
                container_kind="embedded_bitmap",
                operation="ocr",
                package_part=part,
                item_index=media_number,
            )
        if nested_progress is not None:
            nested_progress.start_nested(part, _BITMAP_PLAN_STAGES, "stage")
        try:
            bitmap = plan_bitmap_bytes(
                data,
                ocr,
                source_language,
                unit_id=child_unit_id(parent_unit_id, f"image-{media_number}"),
                ocr_background=ocr_background,
                nested_completed=None if nested_progress is None else nested_progress.advance_nested,
            )
        finally:
            if nested_progress is not None:
                nested_progress.clear_nested()
        return OfficeMediaPlan(part, bitmap=bitmap)
    if failure_context is not None:
        failure_context.set_location(
            stage="embedded_vector",
            container_kind="embedded_vector",
            operation="text_replacement",
            package_part=part,
            item_index=media_number,
        )
    vector = plan_vector(
        data,
        Path(part).suffix,
        ocr,
        source_language,
        target_language,
        document_text_layout=document_text_layout,
        unit_id=child_unit_id(parent_unit_id, f"vector-{media_number}"),
        depth=child_depth,
        package_part=part,
        diagnostics=diagnostics,
    )
    return OfficeMediaPlan(part, vector=vector)


def apply_office_media(
    plan: OfficeMediaPlan,
    translate: Callable[[str], TextReplacementItem],
    typeface: skia.Typeface,
    target_language: str,
) -> OfficeMediaResult:
    """Render the planned translations into the media part and re-encode it."""
    if plan.bitmap is not None:
        regions = apply_bitmap(plan.bitmap, translate, typeface, target_language)
        return OfficeMediaResult(
            bitmap_plan_bytes(plan.bitmap),
            image_regions=regions,
            diagnostics=tuple(plan.bitmap.skipped_regions),
        )
    if plan.vector is None:
        message = "An Office media plan holds neither a bitmap nor a vector graphic."
        raise RuntimeError(message)
    result = apply_vector(plan.vector, translate, typeface)
    return OfficeMediaResult(
        result.data,
        native_items=result.replaced_text_items,
        image_regions=result.replaced_image_regions,
        vector_result=result,
    )
