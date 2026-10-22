"""Shared plan and apply steps for every supported vector graphic (SVG, EMF, WMF).

``pipeline.vector_text`` parses a graphic into a ``VectorDocument`` that lists its source
texts and decoded embedded raster images. Planning keeps that document, plans every
embedded image as a nested bitmap plan (OCR runs here, once), and exposes the texts and
the images' texts as units. Apply writes the engine's translations into the document and
renders each image's plan into it. A nested vector graphic uses these same functions.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import skia  # type: ignore[import-not-found]
from PIL import Image

from pipeline.folder_replacement.bitmap import BitmapPlan, apply_bitmap, plan_bitmap
from pipeline.folder_replacement.planning import (
    LookupProvider,
    child_unit_id,
    enter_nested,
    plan_and_apply,
)
from pipeline.ocr import OcrProvider
from pipeline.text_replacement import (
    TextReplacementItem,
    TextReplacementProvider,
    TextUnit,
    TranslationEngine,
)
from pipeline.vector_text import VectorDocument, VectorReplacementResult, analyse_vector_text

VECTOR_UNIT_ID = "vector"


@dataclass(slots=True)
class VectorPlan:
    """The parsed graphic and the plans of its embedded raster images and nested graphics.

    ``images`` and ``nested`` are aligned with the document's images and nested graphics.
    An entry is None when the nesting depth limit or an unreadable graphic left it
    unchanged.
    """

    document: VectorDocument
    target_language: str
    texts: tuple[str, ...]
    images: list[BitmapPlan | None]
    unit_id: str = VECTOR_UNIT_ID
    nested: list[VectorPlan | None] = field(default_factory=list)

    def units(self) -> Iterator[TextUnit]:
        """Yield this graphic's own unit, then each embedded image's and nested graphic's."""
        yield TextUnit(self.unit_id, self.texts)
        for image in self.images:
            if image is not None:
                yield from image.units()
        for nested in self.nested:
            if nested is not None:
                yield from nested.units()


def plan_vector(
    data: bytes,
    extension: str,
    ocr: OcrProvider,
    source_language: str,
    target_language: str,
    *,
    document_text_layout: str = "preserve-source-formatting",
    unit_id: str = VECTOR_UNIT_ID,
    depth: int = 0,
    package_part: str = "",
    diagnostics: list[dict[str, object]] | None = None,
) -> VectorPlan:
    """List the graphic's texts and plan its embedded images and nested graphics.

    No text provider is called. ``depth`` is how many documents deep this graphic sits
    below the root file, so its images and nested graphics are left unchanged when they
    would exceed the nesting limit.
    """
    document = analyse_vector_text(
        data, extension, source_language, target_language,
        document_text_layout=document_text_layout,
    )
    images: list[BitmapPlan | None] = []
    for index, image in enumerate(document.images()):
        if enter_nested(depth, package_part, diagnostics) is None:
            images.append(None)
        else:
            image_unit_id = child_unit_id(unit_id, f"image-{index + 1}")
            images.append(plan_bitmap(image, ocr, source_language, unit_id=image_unit_id))
    nested: list[VectorPlan | None] = []
    for index, graphic in enumerate(document.nested()):
        child_depth = enter_nested(depth, package_part, diagnostics)
        if child_depth is None:
            nested.append(None)
            continue
        try:
            nested.append(plan_vector(
                graphic.data, graphic.extension, ocr, source_language, target_language,
                document_text_layout=document_text_layout,
                unit_id=child_unit_id(unit_id, f"emfplus-object-{index + 1}"),
                depth=child_depth, package_part=package_part, diagnostics=diagnostics,
            ))
        except ValueError:
            if diagnostics is not None:
                diagnostics.append({
                    "kind": "unsupported",
                    "reason_code": "nested_graphic_malformed",
                    "container_kind": "emfplus_image_object",
                    "vector_format": "emf",
                    "location": dict(graphic.location),
                })
            nested.append(None)
    return VectorPlan(document, target_language, document.texts(), images, unit_id, nested)


def apply_vector(
    plan: VectorPlan,
    translate: Callable[[str], TextReplacementItem],
    typeface: skia.Typeface,
) -> VectorReplacementResult:
    """Replace the graphic's text and render its planned images using ``translate``."""

    def apply_image(index: int, image: Image.Image) -> int:
        if index >= len(plan.images):
            message = "The vector graphic has more embedded images than its plan."
            raise RuntimeError(message)
        planned = plan.images[index]
        if planned is None:
            return 0
        if planned.image.size != image.size:
            message = "A vector graphic's embedded image differs from its plan."
            raise RuntimeError(message)
        # Render onto the image the document will re-encode.
        planned.image = image
        return apply_bitmap(planned, translate, typeface, plan.target_language)

    def apply_nested(index: int) -> VectorReplacementResult | None:
        if index >= len(plan.nested):
            message = "The vector graphic has more nested graphics than its plan."
            raise RuntimeError(message)
        planned = plan.nested[index]
        return None if planned is None else apply_vector(planned, translate, typeface)

    return plan.document.apply(
        lambda text: translate(text).text, LookupProvider(translate), apply_image, apply_nested
    )


def replace_vector_bytes(
    data: bytes,
    extension: str,
    ocr: OcrProvider,
    replacement: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typeface: skia.Typeface,
    *,
    document_text_layout: str = "preserve-source-formatting",
) -> VectorReplacementResult:
    """Replace a vector graphic through its own engine, for parents not yet converted."""
    plan = plan_vector(
        data, extension, ocr, source_language, target_language,
        document_text_layout=document_text_layout,
    )
    return plan_and_apply(
        plan,
        TranslationEngine(replacement, source_language, target_language),
        lambda translate: apply_vector(plan, translate, typeface),
    )
