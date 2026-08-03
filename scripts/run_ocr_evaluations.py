#!/usr/bin/env python3
"""Generate local visual OCR evaluations for every registered provider."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import shutil
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from PIL import Image, ImageDraw
from tqdm import tqdm
# skia-python does not publish PEP 561 stubs; the evaluator passes its native Typeface through.
import skia  # type: ignore[import-not-found]

from pipeline.ocr import (
    BoundingPolygon,
    OcrProvider,
    OcrProviderFactory,
    OcrRequest,
    OcrResult,
    OcrText,
    PixelPoint,
)
from pipeline.ocr.languages import discover_language_directories
from pipeline.text_region_colours import estimate_text_region_colours
from pipeline.text_region_rendering import TextRegionReplacement, replace_text_regions
from pipeline.text_replacement import TextReplacementProviderFactory, TextReplacementRequest
from scripts.prepare_ocr_evaluation_inputs import prepare_evaluation_inputs
from scripts.run_text_replacement_evaluations import _load_default_typeface


BITMAP_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


CHECKSUM_FILENAME = ".input.sha256"
ARTIFACT_FORMAT_VERSION_FILENAME = ".artifact-format-version"
ARTIFACT_FORMAT_VERSION = "3"
TEXT_REPLACEMENT_CHECKSUM_FILENAME = ".text-replacement.input.sha256"
TEXT_REPLACEMENT_ARTIFACT_FORMAT_VERSION_FILENAME = (
    ".text-replacement-artifact-format-version"
)
TEXT_REPLACEMENT_ARTIFACT_FORMAT_VERSION = "8"
VIEWER_FILENAME = "index.html"
TEXT_REPLACEMENT_VIEWER_FILENAME = "text-replacement.html"
MAXIMUM_PROGRESS_LABEL_LENGTH = 44
TEXT_CLIP_CONTEXT_PIXELS = 20
TEXT_REPLACEMENT_MINIMUM_CONFIDENCE = 0.65


@dataclass
class EvaluationRunResult:
    """Counts produced by one OCR evaluation run."""

    failed_images: int = 0
    processed_images: int = 0
    skipped_providers: int = 0
    successful_images: int = 0


@dataclass(frozen=True)
class EvaluationImage:
    """One eligible input image and the language supplied by its parent directory."""

    language: str
    path: Path
    progress_folder: Path
    relative_path: Path


@dataclass(frozen=True)
class ViewerEntry:
    """One image evaluation rendered in a provider's static viewer."""

    image: EvaluationImage
    succeeded: bool
    confidences: tuple[float, ...]
    extracted_texts: tuple[str, ...]
    replacement_succeeded: bool


class EvaluationProgress(Protocol):
    """The small portion of tqdm used while evaluating one input folder."""

    def set_postfix_str(self, s: str, refresh: bool = ...) -> None:
        """Set the current provider and image label."""

    def update(self, n: int = ...) -> bool | None:
        """Advance the completed evaluation count."""


def discover_evaluation_images(input_root: Path) -> list[EvaluationImage]:
    """Discover supported input images below the established language directories."""
    if not input_root.is_dir():
        raise ValueError(f"Input root does not exist or is not a directory: {input_root}")

    images: list[EvaluationImage] = []
    for language_directory in discover_language_directories(input_root):
        language = language_directory.name
        for image_path in sorted(language_directory.rglob("*")):
            if image_path.is_file() and image_path.suffix.lower() in BITMAP_EXTENSIONS:
                relative_path = image_path.relative_to(input_root)
                relative_to_language = image_path.relative_to(language_directory)
                progress_folder = (
                    language_directory.relative_to(input_root)
                    if len(relative_to_language.parts) == 1
                    else language_directory.relative_to(input_root)
                    / relative_to_language.parts[0]
                )
                images.append(
                    EvaluationImage(
                        language=language,
                        path=image_path,
                        progress_folder=progress_folder,
                        relative_path=relative_path,
                    )
                )
    return images


def progress_groups(images: list[EvaluationImage]) -> dict[Path, list[EvaluationImage]]:
    """Group images by their language directory or its immediate child folder."""
    groups: defaultdict[Path, list[EvaluationImage]] = defaultdict(list)
    for image in images:
        groups[image.progress_folder].append(image)
    return dict(groups)


def input_tree_checksum(images: list[EvaluationImage]) -> str:
    """Return a deterministic SHA-256 checksum for the eligible input image tree."""
    digest = hashlib.sha256()
    for image in images:
        digest.update(image.relative_path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(image.language.encode("utf-8"))
        digest.update(b"\0")
        with image.path.open("rb") as input_file:
            for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def evaluate_ocr_inputs(
    input_root: Path,
    output_root: Path,
    factory: OcrProviderFactory | None = None,
) -> EvaluationRunResult:
    """Evaluate every eligible input image with every discovered OCR provider."""
    images = discover_evaluation_images(input_root)
    checksum = input_tree_checksum(images)
    provider_factory = factory or OcrProviderFactory.discover_default_plugins()
    text_replacement_factory = TextReplacementProviderFactory.discover_default_plugins()
    result = EvaluationRunResult()
    providers_to_run: list[tuple[str, Path]] = []

    for provider_name in provider_factory.provider_names:
        provider_root = _provider_output_root(output_root, provider_name)
        if _provider_output_is_current(provider_root, checksum):
            result.skipped_providers += 1
            print(f"Skipping {provider_name}: OCR input checksum unchanged.")
            continue

        providers_to_run.append((provider_name, provider_root))

    providers: list[tuple[str, Path, OcrProvider]] = []
    entries_by_provider: dict[str, list[ViewerEntry]] = {}
    for provider_name, provider_root in providers_to_run:
        if provider_root.exists():
            if not provider_root.is_dir():
                raise ValueError(f"Provider output path is not a directory: {provider_root}")
            shutil.rmtree(provider_root)
        provider_root.mkdir(parents=True)
        providers.append((provider_name, provider_root, provider_factory.create(provider_name)))
        entries_by_provider[provider_name] = []

    if providers:
        for folder, folder_images in progress_groups(images).items():
            with tqdm(
                total=len(folder_images) * len(providers),
                desc=_progress_label(folder.as_posix()),
                dynamic_ncols=True,
                leave=True,
                unit="evaluation",
            ) as progress:
                for provider_name, provider_root, provider in providers:
                    entries_by_provider[provider_name].extend(
                        _evaluate_provider(
                            provider_name,
                            provider,
                            folder_images,
                            provider_root,
                            result,
                            progress,
                        )
                    )

    for provider_name, provider_root, _ in providers:
        _write_viewer(provider_root, entries_by_provider[provider_name])
        (provider_root / CHECKSUM_FILENAME).write_text(f"{checksum}\n", encoding="ascii")
        (provider_root / ARTIFACT_FORMAT_VERSION_FILENAME).write_text(
            f"{ARTIFACT_FORMAT_VERSION}\n", encoding="ascii"
        )

    replacement_typeface: skia.Typeface | None = None
    for provider_name in provider_factory.provider_names:
        provider_root = _provider_output_root(output_root, provider_name)
        if _text_replacement_output_is_current(provider_root, checksum):
            continue
        if replacement_typeface is None:
            replacement_typeface = _load_default_typeface()
        replacement_entries = _regenerate_text_replacement_artifacts(
            provider_root,
            images,
            text_replacement_factory,
            replacement_typeface,
        )
        _write_text_replacement_viewer(
            provider_root, replacement_entries, text_replacement_factory.provider_names
        )
        (provider_root / TEXT_REPLACEMENT_CHECKSUM_FILENAME).write_text(
            f"{checksum}\n", encoding="ascii"
        )
        (provider_root / TEXT_REPLACEMENT_ARTIFACT_FORMAT_VERSION_FILENAME).write_text(
            f"{TEXT_REPLACEMENT_ARTIFACT_FORMAT_VERSION}\n", encoding="ascii"
        )

    return result


def prepare_and_evaluate_ocr_inputs(
    input_root: Path,
    output_root: Path,
    factory: OcrProviderFactory | None = None,
    prepare_inputs: Callable[[Path, Path], object] = prepare_evaluation_inputs,
) -> EvaluationRunResult:
    """Prepare the standard sample corpus, then evaluate the resulting input images."""
    prepare_inputs(Path("sample-data"), input_root)
    return evaluate_ocr_inputs(input_root, output_root, factory)


def _progress_label(value: str) -> str:
    """Keep long local folder and filename labels readable in a terminal bar."""
    if len(value) <= MAXIMUM_PROGRESS_LABEL_LENGTH:
        return value
    return f"{value[: MAXIMUM_PROGRESS_LABEL_LENGTH - 1]}…"


def _provider_output_root(output_root: Path, provider_name: str) -> Path:
    provider_root = output_root / provider_name
    if not provider_root.resolve().is_relative_to(output_root.resolve()):
        raise ValueError(f"Provider name escapes output root: {provider_name!r}")
    return provider_root


def _provider_output_is_current(provider_root: Path, checksum: str) -> bool:
    checksum_path = provider_root / CHECKSUM_FILENAME
    return (
        provider_root.is_dir()
        and (provider_root / VIEWER_FILENAME).is_file()
        and checksum_path.is_file()
        and checksum_path.read_text(encoding="ascii").strip() == checksum
        and (provider_root / ARTIFACT_FORMAT_VERSION_FILENAME).is_file()
        and (provider_root / ARTIFACT_FORMAT_VERSION_FILENAME).read_text(
            encoding="ascii"
        ).strip()
        == ARTIFACT_FORMAT_VERSION
    )


def _text_replacement_output_is_current(provider_root: Path, checksum: str) -> bool:
    """Return whether the independent text-replacement artifact stage is current."""
    checksum_path = provider_root / TEXT_REPLACEMENT_CHECKSUM_FILENAME
    version_path = provider_root / TEXT_REPLACEMENT_ARTIFACT_FORMAT_VERSION_FILENAME
    return (
        provider_root.is_dir()
        and (provider_root / TEXT_REPLACEMENT_VIEWER_FILENAME).is_file()
        and checksum_path.is_file()
        and checksum_path.read_text(encoding="ascii").strip() == checksum
        and version_path.is_file()
        and version_path.read_text(encoding="ascii").strip()
        == TEXT_REPLACEMENT_ARTIFACT_FORMAT_VERSION
    )


def _evaluate_provider(
    provider_name: str,
    provider: OcrProvider,
    images: list[EvaluationImage],
    provider_root: Path,
    result: EvaluationRunResult,
    progress: EvaluationProgress,
) -> list[ViewerEntry]:
    entries: list[ViewerEntry] = []
    for image in images:
        progress.set_postfix_str(
            f"{provider_name}: {_progress_label(image.path.name)}",
            refresh=True,
        )
        try:
            if image.language not in provider.supported_languages:
                payload: dict[str, object] = {"status": "failed"}
                _write_json(_result_json_path(provider_root, image), payload)
                result.failed_images += 1
                entries.append(ViewerEntry(image, False, (), (), False))
                continue

            try:
                with Image.open(image.path) as opened_image:
                    source_image = opened_image.copy()
                ocr_result = provider.recognize(OcrRequest(source_image, image.language))
                payload = _successful_payload(
                    ocr_result, source_image, provider_root, image
                )
                _write_json(_result_json_path(provider_root, image), payload)
                _write_visual_artifacts(provider_root, image, source_image, ocr_result)
            except Exception:
                # A local real-data evaluation should retain the other provider/image results.
                payload = {"status": "failed"}
                _write_json(_result_json_path(provider_root, image), payload)
                result.failed_images += 1
                entries.append(ViewerEntry(image, False, (), (), False))
                continue

            result.processed_images += 1
            result.successful_images += 1
            entries.append(
                ViewerEntry(
                    image,
                    True,
                    tuple(text_item.confidence for text_item in ocr_result.text_items),
                    tuple(text_item.text for text_item in ocr_result.text_items),
                    True,
                )
            )
        finally:
            progress.update(1)
    return entries


def _successful_payload(
    result: OcrResult,
    source_image: Image.Image,
    provider_root: Path,
    evaluation_image: EvaluationImage,
) -> dict[str, object]:
    return {
        "status": "succeeded",
        "source_language": evaluation_image.language,
        "text_items": [
            {
                "text": text_item.text,
                "confidence": text_item.confidence,
                "bounding_polygon": _polygon_payload(text_item.bounding_polygon.vertices),
                "padded_bounding_polygon": _translated_polygon_payload(
                    text_item.bounding_polygon.vertices,
                    _padded_clipped_bounds(
                        source_image, text_item.bounding_polygon.vertices
                    ),
                ),
                "padded_image_path": _relative_url(
                    _text_clip_path(provider_root, evaluation_image, index),
                    _result_json_path(provider_root, evaluation_image).parent,
                ),
                "extra": text_item.extra,
            }
            for index, text_item in enumerate(result.text_items, start=1)
        ],
    }


def _write_visual_artifacts(
    provider_root: Path,
    evaluation_image: EvaluationImage,
    source_image: Image.Image,
    result: OcrResult,
) -> None:
    masked_image = source_image.convert("RGBA")
    drawing = ImageDraw.Draw(masked_image)
    for text_item in result.text_items:
        drawing.polygon(
            [(point.x, point.y) for point in text_item.bounding_polygon.vertices],
            fill="black",
        )
    _masked_image_path(provider_root, evaluation_image).parent.mkdir(
        parents=True, exist_ok=True
    )
    masked_image.save(_masked_image_path(provider_root, evaluation_image), format="PNG")

    for index, text_item in enumerate(result.text_items, start=1):
        bounds = _padded_clipped_bounds(
            source_image, text_item.bounding_polygon.vertices
        )
        source_image.crop(bounds).save(
            _text_clip_path(provider_root, evaluation_image, index), format="PNG"
        )


def _write_text_replacement_artifacts(
    provider_root: Path,
    evaluation_image: EvaluationImage,
    source_image: Image.Image,
    result: OcrResult,
    text_replacement_factory: TextReplacementProviderFactory,
    replacement_typeface: skia.Typeface,
) -> None:
    """Write complete and region-clipped local replacements for every default provider."""
    eligible_text_items = tuple(
        (region_index, text_item)
        for region_index, text_item in enumerate(result.text_items, start=1)
        if text_item.confidence >= TEXT_REPLACEMENT_MINIMUM_CONFIDENCE
    )
    estimates = tuple(
        estimate_text_region_colours(source_image, text_item)
        for _, text_item in eligible_text_items
    )
    artifact_directory = _replacement_artifact_directory(provider_root, evaluation_image)
    artifact_directory.mkdir(parents=True, exist_ok=True)
    for provider_index, provider_name in enumerate(text_replacement_factory.provider_names, start=1):
        provider = text_replacement_factory.create(provider_name)
        updated_image = source_image.copy()
        replacements: list[TextRegionReplacement] = []
        for (_, text_item), estimate in zip(eligible_text_items, estimates, strict=True):
            replacement = provider.replace(
                TextReplacementRequest(
                    text=text_item.text,
                    is_filename=False,
                    source_language=evaluation_image.language,
                    target_language="en",
                )
            )
            replacements.append(
                TextRegionReplacement(
                    text_region=text_item,
                    colour_estimate=estimate,
                    replacement_text=replacement.text,
                )
            )
        replace_text_regions(
            updated_image, replacements, replacement_typeface, target_language="en"
        )
        updated_image.save(
            _replacement_complete_image_path(provider_root, evaluation_image, provider_index),
            format="PNG",
        )
        for region_index, text_item in eligible_text_items:
            bounds = _padded_clipped_bounds(source_image, text_item.bounding_polygon.vertices)
            updated_image.crop(bounds).save(
                _replacement_text_clip_path(
                    provider_root, evaluation_image, region_index, provider_index
                ),
                format="PNG",
            )


def _regenerate_text_replacement_artifacts(
    provider_root: Path,
    images: list[EvaluationImage],
    text_replacement_factory: TextReplacementProviderFactory,
    replacement_typeface: skia.Typeface,
) -> list[ViewerEntry]:
    """Rebuild replacement artifacts from cached OCR JSON without calling OCR."""
    entries: list[ViewerEntry] = []
    for image in images:
        payload = json.loads(_result_json_path(provider_root, image).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("status") != "succeeded":
            entries.append(ViewerEntry(image, False, (), (), False))
            continue

        try:
            ocr_result = _ocr_result_from_cached_payload(payload)
            with Image.open(image.path) as opened_image:
                source_image = opened_image.copy()
            artifact_directory = _replacement_artifact_directory(provider_root, image)
            if artifact_directory.exists():
                shutil.rmtree(artifact_directory)
            _write_text_replacement_artifacts(
                provider_root,
                image,
                source_image,
                ocr_result,
                text_replacement_factory,
                replacement_typeface,
            )
        except (KeyError, OSError, TypeError, ValueError):
            replacement_succeeded = False
        else:
            replacement_succeeded = True

        entries.append(
            ViewerEntry(
                image,
                True,
                tuple(text_item.confidence for text_item in ocr_result.text_items)
                if replacement_succeeded
                else (),
                tuple(text_item.text for text_item in ocr_result.text_items)
                if replacement_succeeded
                else (),
                replacement_succeeded,
            )
        )
    return entries


def _ocr_result_from_cached_payload(payload: dict[object, object]) -> OcrResult:
    """Deserialize the renderer-relevant OCR fields from a successful result JSON."""
    raw_text_items = payload["text_items"]
    if not isinstance(raw_text_items, list):
        raise ValueError("A successful cached OCR result must contain text_items.")
    return OcrResult(tuple(_ocr_text_from_cached_payload(item) for item in raw_text_items))


def _ocr_text_from_cached_payload(payload: object) -> OcrText:
    """Deserialize one OCR text item required by the text-replacement stage."""
    if not isinstance(payload, dict):
        raise ValueError("A cached OCR text item must be an object.")
    text = payload.get("text")
    confidence = payload.get("confidence")
    raw_polygon = payload.get("bounding_polygon")
    if not isinstance(text, str) or not isinstance(confidence, (int, float)):
        raise ValueError("A cached OCR text item has invalid text or confidence.")
    if not isinstance(raw_polygon, list):
        raise ValueError("A cached OCR text item has no bounding polygon.")
    vertices: list[PixelPoint] = []
    for raw_point in raw_polygon:
        if not isinstance(raw_point, dict):
            raise ValueError("A cached OCR polygon point must be an object.")
        x = raw_point.get("x")
        y = raw_point.get("y")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            raise ValueError("A cached OCR polygon point has invalid coordinates.")
        vertices.append(PixelPoint(x, y))
    return OcrText(text, float(confidence), BoundingPolygon(tuple(vertices)))


def _clipped_bounds(
    source_image: Image.Image, vertices: tuple[PixelPoint, ...]
) -> tuple[int, int, int, int]:
    coordinates = [(vertex.x, vertex.y) for vertex in vertices]
    left = max(0, math.floor(min(x for x, _ in coordinates)))
    top = max(0, math.floor(min(y for _, y in coordinates)))
    right = min(source_image.width, math.ceil(max(x for x, _ in coordinates)))
    bottom = min(source_image.height, math.ceil(max(y for _, y in coordinates)))
    if left >= right or top >= bottom:
        raise ValueError("A detected text region has no area within the source image.")
    return (left, top, right, bottom)


def _padded_clipped_bounds(
    source_image: Image.Image, vertices: tuple[PixelPoint, ...]
) -> tuple[int, int, int, int]:
    """Return the text bounds plus the configured source-image context."""
    left, top, right, bottom = _clipped_bounds(source_image, vertices)
    return (
        max(0, left - TEXT_CLIP_CONTEXT_PIXELS),
        max(0, top - TEXT_CLIP_CONTEXT_PIXELS),
        min(source_image.width, right + TEXT_CLIP_CONTEXT_PIXELS),
        min(source_image.height, bottom + TEXT_CLIP_CONTEXT_PIXELS),
    )


def _polygon_payload(vertices: tuple[PixelPoint, ...]) -> list[dict[str, float]]:
    return [{"x": point.x, "y": point.y} for point in vertices]


def _translated_polygon_payload(
    vertices: tuple[PixelPoint, ...], bounds: tuple[int, int, int, int]
) -> list[dict[str, float]]:
    """Serialize a source-image polygon relative to the crop's top-left origin."""
    left, top, _, _ = bounds
    return [{"x": point.x - left, "y": point.y - top} for point in vertices]


def _result_json_path(provider_root: Path, image: EvaluationImage) -> Path:
    return provider_root / image.relative_path.parent / f"{image.relative_path.name}.json"


def _masked_image_path(provider_root: Path, image: EvaluationImage) -> Path:
    return provider_root / image.relative_path.parent / f"{image.relative_path.name}.masked.png"


def _text_clip_path(provider_root: Path, image: EvaluationImage, index: int) -> Path:
    return (
        provider_root
        / image.relative_path.parent
        / f"{image.relative_path.name}.text-{index:04d}.png"
    )


def _replacement_artifact_directory(provider_root: Path, image: EvaluationImage) -> Path:
    """Return the image-local directory for generated text-replacement artifacts."""
    return (
        provider_root
        / image.relative_path.parent
        / f"{image.relative_path.name}.text-replacements"
    )


def _replacement_complete_image_path(
    provider_root: Path, image: EvaluationImage, provider_index: int
) -> Path:
    return _replacement_artifact_directory(provider_root, image) / f"provider-{provider_index:04d}.png"


def _replacement_text_clip_path(
    provider_root: Path, image: EvaluationImage, region_index: int, provider_index: int
) -> Path:
    return _replacement_artifact_directory(provider_root, image) / (
        f"region-{region_index:04d}.provider-{provider_index:04d}.png"
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output_file:
        json.dump(payload, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")


def _write_viewer(provider_root: Path, entries: list[ViewerEntry]) -> None:
    rendered_entries = "\n".join(
        _viewer_entry_html(provider_root, entry) for entry in entries
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OCR evaluation</title>
  <style>
    body {{ background: #f6f7f9; color: #1f2937; font-family: system-ui, sans-serif; margin: 0; }}
    main {{ margin: 0 auto; max-width: 1100px; padding: 2rem; }}
    article {{ background: white; border: 1px solid #d9dee7; border-radius: 8px; margin: 1rem 0; padding: 1rem; }}
    h1, h2 {{ margin-top: 0; }} .failed {{ border-left: 5px solid #b91c1c; }}
    .images {{ display: flex; flex-wrap: wrap; gap: 1rem; }} figure {{ margin: 0; max-width: 46%; }}
    img {{ border: 1px solid #cbd5e1; height: auto; max-width: 100%; }} figcaption {{ font-size: .9rem; }}
    table {{ border-collapse: collapse; margin-top: 1rem; width: 100%; }} th, td {{ border: 1px solid #cbd5e1; padding: .5rem; text-align: left; vertical-align: top; }}
    th {{ background: #f1f5f9; }} td img {{ max-height: 120px; }}
    .confidence {{ text-align: right; white-space: nowrap; width: 7ch; }}
  </style>
</head>
<body>
  <main>
    <h1>OCR evaluation</h1>
    <p>{len(entries)} image evaluation(s).</p>
    {rendered_entries}
  </main>
</body>
</html>
"""
    (provider_root / VIEWER_FILENAME).write_text(document, encoding="utf-8")


def _write_text_replacement_viewer(
    provider_root: Path,
    entries: list[ViewerEntry],
    replacement_provider_names: tuple[str, ...],
) -> None:
    """Write the additional full-image and region-level text-replacement viewer."""
    rendered_entries = "\n".join(
        _replacement_viewer_entry_html(
            provider_root, entry, replacement_provider_names, entry_index
        )
        for entry_index, entry in enumerate(entries, start=1)
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OCR text-replacement evaluation</title>
  <style>
    body {{ background: #f6f7f9; color: #1f2937; font-family: system-ui, sans-serif; margin: 0; }}
    main {{ margin: 0 auto; max-width: 1500px; padding: 2rem; }}
    article {{ background: white; border: 1px solid #d9dee7; border-radius: 8px; margin: 1rem 0; padding: 1rem; }}
    h1, h2 {{ margin-top: 0; }} .failed {{ border-left: 5px solid #b91c1c; }}
    .top-previews {{ display: flex; flex-wrap: nowrap; gap: 1rem; }}
    .top-preview {{ box-sizing: border-box; flex: 0 0 calc(50% - .5rem); margin: 0; min-width: 0; }}
    img {{ border: 1px solid #cbd5e1; height: auto; max-width: 100%; }} figcaption {{ font-size: .9rem; }}
    .top-preview img {{ display: block; max-width: 100%; }}
    table {{ border-collapse: collapse; margin-top: 1rem; width: auto; }} th, td {{ border: 1px solid #cbd5e1; padding: .5rem; text-align: left; vertical-align: top; }}
    th {{ background: #f1f5f9; }} td img {{ max-height: 120px; }}
  </style>
</head>
<body>
  <main>
    <h1>OCR text-replacement evaluation</h1>
    <p>{len(entries)} image evaluation(s).</p>
    {rendered_entries}
  </main>
  <script>
    document.querySelectorAll("select[data-replacement-preview]").forEach((select) => {{
      select.addEventListener("change", () => {{
        document.getElementById(select.dataset.replacementPreview).src = select.value;
      }});
    }});
  </script>
</body>
</html>
"""
    (provider_root / TEXT_REPLACEMENT_VIEWER_FILENAME).write_text(document, encoding="utf-8")


def _replacement_viewer_entry_html(
    provider_root: Path,
    entry: ViewerEntry,
    replacement_provider_names: tuple[str, ...],
    entry_index: int,
) -> str:
    title = html.escape(entry.image.relative_path.as_posix())
    if not entry.succeeded:
        return f"""<article class="failed">
  <h2>{title}</h2><p>Language: {html.escape(entry.image.language)}. Status: failed.</p>
</article>"""

    image_path = _relative_url(entry.image.path, provider_root)
    masked_path = _relative_url(_masked_image_path(provider_root, entry.image), provider_root)
    preview_identifier = f"replacement-preview-{entry_index}"
    preview_sources = tuple(
        _relative_url(
            _replacement_complete_image_path(provider_root, entry.image, provider_index), provider_root
        )
        for provider_index in range(1, len(replacement_provider_names) + 1)
    )
    provider_options = "".join(
        f'<option value="{html.escape(source, quote=True)}">{html.escape(provider_name)}</option>'
        for provider_name, source in zip(replacement_provider_names, preview_sources, strict=True)
    )
    options = (
        f"{provider_options}"
        f'<option value="{html.escape(masked_path, quote=True)}">Detected regions masked</option>'
    )
    rows = "".join(
        _replacement_text_region_row(
            provider_root, entry.image, region_index, replacement_provider_names
        )
        for region_index, confidence in enumerate(entry.confidences, start=1)
        if confidence >= TEXT_REPLACEMENT_MINIMUM_CONFIDENCE
    )
    table = (
        f"<p>No text regions met the {TEXT_REPLACEMENT_MINIMUM_CONFIDENCE:.2f} confidence threshold.</p>"
        if not rows
        else f"""<table>
  <thead><tr><th>Region</th><th>Original text image</th>{''.join(f'<th>{html.escape(name)}</th>' for name in replacement_provider_names)}</tr></thead>
  <tbody>{rows}</tbody>
</table>"""
    )
    first_preview = preview_sources[0] if preview_sources else ""
    return f"""<article>
  <h2>{title}</h2><p>Language: {html.escape(entry.image.language)}→en. Status: succeeded.</p>
  <div class="top-previews">
    <figure class="top-preview"><img alt="Original input" src="{html.escape(image_path, quote=True)}"><figcaption>Input</figcaption></figure>
    <div class="complete-preview top-preview">
      <img id="{preview_identifier}" alt="Complete text-replacement preview" src="{html.escape(first_preview, quote=True)}">
      <label for="replacement-select-{entry_index}">Complete replacement preview</label>
      <select id="replacement-select-{entry_index}" data-replacement-preview="{preview_identifier}">{options}</select>
    </div>
  </div>
  {table}
</article>"""


def _replacement_text_region_row(
    provider_root: Path,
    image: EvaluationImage,
    region_index: int,
    replacement_provider_names: tuple[str, ...],
) -> str:
    original_path = _relative_url(_text_clip_path(provider_root, image, region_index), provider_root)
    replacement_cells = "".join(
        _replacement_image_cell(
            _relative_url(
                _replacement_text_clip_path(
                    provider_root, image, region_index, provider_index
                ),
                provider_root,
            ),
            f"Replacement from {provider_name} for region {region_index}",
        )
        for provider_index, provider_name in enumerate(replacement_provider_names, start=1)
    )
    return (
        f"<tr><td>{region_index}</td>"
        f"{_replacement_image_cell(original_path, f'Original text region {region_index}') }"
        f"{replacement_cells}</tr>"
    )


def _replacement_image_cell(url: str, alternative_text: str) -> str:
    return (
        '<td><img '
        f'alt="{html.escape(alternative_text, quote=True)}" '
        f'src="{html.escape(url, quote=True)}"></td>'
    )


def _viewer_entry_html(provider_root: Path, entry: ViewerEntry) -> str:
    image_path = _relative_url(entry.image.path, provider_root)
    result_path = _relative_url(_result_json_path(provider_root, entry.image), provider_root)
    title = html.escape(entry.image.relative_path.as_posix())
    if not entry.succeeded:
        return f"""<article class="failed">
  <h2>{title}</h2><p>Language: {html.escape(entry.image.language)}. Status: failed.</p>
  <p><a href="{html.escape(result_path, quote=True)}" target="_blank" rel="noopener">JSON result</a></p>
</article>"""
    if not entry.replacement_succeeded:
        return f"""<article class="failed">
  <h2>{title}</h2><p>Language: {html.escape(entry.image.language)}→en. OCR succeeded; text-replacement artifacts failed.</p>
</article>"""

    masked_path = _relative_url(_masked_image_path(provider_root, entry.image), provider_root)
    text_rows = "".join(
        _text_region_row(provider_root, entry.image, index, text, confidence)
        for index, (text, confidence) in enumerate(
            zip(entry.extracted_texts, entry.confidences, strict=True), start=1
        )
    )
    text_table = (
        "<p>No text detected.</p>"
        if not text_rows
        else f"""<table>
  <thead><tr><th>Detected region</th><th>Extracted text</th><th class="confidence">Confidence</th></tr></thead>
  <tbody>{text_rows}</tbody>
</table>"""
    )
    return f"""<article>
  <h2>{title}</h2><p>Language: {html.escape(entry.image.language)}. Status: succeeded. <a href="{html.escape(result_path, quote=True)}" target="_blank" rel="noopener">JSON result</a></p>
  <div class="images">
    <figure><img alt="Original input" src="{html.escape(image_path, quote=True)}"><figcaption>Input</figcaption></figure>
    <figure><img alt="Detected text masked in black" src="{html.escape(masked_path, quote=True)}"><figcaption>Detected regions masked</figcaption></figure>
  </div>
  {text_table}
</article>"""


def _text_region_row(
    provider_root: Path, image: EvaluationImage, index: int, text: str, confidence: float
) -> str:
    clip_path = _relative_url(_text_clip_path(provider_root, image, index), provider_root)
    escaped_clip_path = html.escape(clip_path, quote=True)
    return f"""<tr>
  <td><a href="{escaped_clip_path}" target="_blank" rel="noopener"><img alt="Detected text {index}" src="{escaped_clip_path}"></a></td>
  <td>{html.escape(text)}</td>
  <td class="confidence">{confidence:.2%}</td>
</tr>"""


def _relative_url(path: Path, from_directory: Path) -> str:
    return Path(os.path.relpath(path, from_directory)).as_posix()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-root", type=Path, default=Path("outputs/evaluations/ocr/input")
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("outputs/evaluations/ocr/output")
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    result = prepare_and_evaluate_ocr_inputs(arguments.input_root, arguments.output_root)
    print(
        "OCR evaluation complete: "
        f"{result.successful_images} successful image(s), "
        f"{result.failed_images} failed image(s), "
        f"{result.skipped_providers} unchanged provider(s) skipped."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
