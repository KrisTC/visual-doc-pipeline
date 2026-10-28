#!/usr/bin/env python3
"""Generate visual OCR evaluations for local or explicitly selected providers."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from PIL import Image
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
from pipeline.ocr.errors import OcrProviderNotFoundError
from pipeline.ocr.languages import discover_language_directories
from pipeline.folder_replacement.filters import parse_include_patterns
from pipeline.ocr_plugins.google_cloud_vision import cache_identity as vision_cache_identity
from pipeline.provider_cache import source_cache_scope
from pipeline.terminal_progress import LiveProgress
from pipeline.runtime_assets import RuntimeAssetsRequiredError, require_runtime_assets
from pipeline.text_region_colours import TextRegionColourEstimate, estimate_replacement_colours
from pipeline.text_region_rendering import TextRegionReplacement, replace_text_regions
from pipeline.text_replacement import (
    TextReplacementProvider,
    TextReplacementProviderFactory,
    replace_text,
)
from pipeline.text_replacement.errors import TextReplacementProviderNotFoundError
from scripts.prepare_ocr_evaluation_inputs import (
    PreparationProgress,
    PreparationResult,
    prepare_evaluation_inputs,
)
from scripts.ocr_text_replacement_evaluations import _load_default_typeface


BITMAP_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


CHECKSUM_FILENAME = ".input.sha256"
ARTIFACT_FORMAT_VERSION_FILENAME = ".artifact-format-version"
ARTIFACT_FORMAT_VERSION = "7"
VISION_ARTIFACT_FORMAT_VERSION = "7-vision-auto-language-v1"
TEXT_REPLACEMENT_CHECKSUM_FILENAME = ".text-replacement.input.sha256"
TEXT_REPLACEMENT_ARTIFACT_FORMAT_VERSION_FILENAME = (
    ".text-replacement-artifact-format-version"
)
TEXT_REPLACEMENT_ARTIFACT_FORMAT_VERSION = "15"
BASELINE_TEXT_REPLACEMENT_PROVIDERS = ("identity", "character_mask")
VIEWER_FILENAME = "index.html"
TEXT_REPLACEMENT_VIEWER_FILENAME = "text-replacement.html"
MAXIMUM_PROGRESS_LABEL_LENGTH = 44
TEXT_CLIP_CONTEXT_PIXELS = 20
TEXT_REPLACEMENT_MINIMUM_CONFIDENCE = 0.65
EXCLUDED_EVALUATION_PROVIDERS = frozenset({"no_ocr", "google_cloud_vision"})
DEFAULT_MAX_IMAGES = 25
PREPARE_STAGE = "Prepare inputs"
CLEANUP_STAGE = "Clean up"
OCR_STAGE = "OCR"
TEXT_REPLACEMENT_STAGE_PREFIX = "Text replacement: "


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
    """The active Rich task operations used while evaluating one input folder."""

    def set_postfix_str(self, s: str, refresh: bool = ...) -> None:
        """Set the current provider and image label."""

    def update(self, n: int = ...) -> bool | None:
        """Advance the completed evaluation count."""


def discover_evaluation_images(
    input_root: Path,
    selected_image_paths: tuple[Path, ...] | None = None,
) -> list[EvaluationImage]:
    """Discover supported input images below the established language directories."""
    if not input_root.is_dir():
        raise ValueError(f"Input root does not exist or is not a directory: {input_root}")

    images: list[EvaluationImage] = []
    for language_directory in discover_language_directories(input_root):
        language = language_directory.name
        if selected_image_paths is None:
            candidate_paths = sorted(language_directory.rglob("*"))
        else:
            candidate_paths = sorted(
                input_root / relative_path
                for relative_path in selected_image_paths
                if (input_root / relative_path).is_relative_to(language_directory)
            )
        for image_path in candidate_paths:
            if image_path.is_file() and image_path.suffix.lower() in BITMAP_EXTENSIONS:
                relative_path = image_path.relative_to(input_root)
                images.append(
                    EvaluationImage(
                        language=language,
                        path=image_path,
                        relative_path=relative_path,
                    )
                )
    return images


def limit_images(images: list[EvaluationImage], maximum: int) -> list[EvaluationImage]:
    """Keep the first images in discovery order; a maximum of 0 keeps them all."""
    return images if maximum == 0 else images[:maximum]


def input_tree_checksum(
    images: list[EvaluationImage],
    on_image: Callable[[], None] | None = None,
) -> str:
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
        if on_image is not None:
            on_image()
    return digest.hexdigest()


def text_replacement_provider_names(
    factory: TextReplacementProviderFactory, requested_name: str | None
) -> tuple[str, ...]:
    """Return the baseline providers plus the optional requested provider, in run order."""
    if requested_name is not None and requested_name not in factory.provider_names:
        raise TextReplacementProviderNotFoundError(
            f"No text-replacement provider is registered under {requested_name!r}. "
            f"Registered providers: {', '.join(factory.provider_names)}."
        )
    if requested_name is None or requested_name in BASELINE_TEXT_REPLACEMENT_PROVIDERS:
        return BASELINE_TEXT_REPLACEMENT_PROVIDERS
    return (*BASELINE_TEXT_REPLACEMENT_PROVIDERS, requested_name)


def evaluate_ocr_inputs(
    input_root: Path,
    output_root: Path,
    factory: OcrProviderFactory | None = None,
    *,
    ocr_provider_name: str | None = None,
    text_replacement_provider_name: str | None = None,
    text_replacement_factory: TextReplacementProviderFactory | None = None,
    selected_image_paths: tuple[Path, ...] | None = None,
    max_images: int = DEFAULT_MAX_IMAGES,
    display: LiveProgress | None = None,
) -> EvaluationRunResult:
    """Evaluate local providers by default or one explicitly selected provider.

    A caller that has already started the live display (with the Prepare inputs
    stage active and an indeterminate overall row) passes it; otherwise this
    function runs its own display.
    """
    replacement_factory = (
        text_replacement_factory or TextReplacementProviderFactory.discover_default_plugins()
    )
    replacement_names = text_replacement_provider_names(
        replacement_factory, text_replacement_provider_name
    )
    if display is not None:
        return _evaluate_stages(
            display, input_root, output_root, factory,
            ocr_provider_name, selected_image_paths, max_images,
            replacement_factory, replacement_names,
        )
    with LiveProgress() as own_display:
        _start_prepare_stage(own_display)
        return _evaluate_stages(
            own_display, input_root, output_root, factory,
            ocr_provider_name, selected_image_paths, max_images,
            replacement_factory, replacement_names,
        )


class _PrepareStageProgress:
    """Show the steps of the Prepare inputs stage on the live display's current row."""

    def __init__(self, display: LiveProgress) -> None:
        self._display = display

    def start_step(self, label: str, total: int | None) -> None:
        self._display.start_current(PREPARE_STAGE, total, "file")
        self._display.set_current_label(label)

    def advance(self) -> None:
        self._display.advance_current()


def _start_prepare_stage(display: LiveProgress) -> None:
    display.start_overall(None, "stage")
    _PrepareStageProgress(display).start_step("Starting", None)


def _evaluate_stages(
    display: LiveProgress,
    input_root: Path,
    output_root: Path,
    factory: OcrProviderFactory | None,
    ocr_provider_name: str | None,
    selected_image_paths: tuple[Path, ...] | None,
    max_images: int,
    text_replacement_factory: TextReplacementProviderFactory,
    replacement_provider_names: tuple[str, ...],
) -> EvaluationRunResult:
    """Finish Prepare inputs, then run the cleanup, OCR, and text-replacement stages."""
    if selected_image_paths == ():
        return EvaluationRunResult()
    prepare_progress = _PrepareStageProgress(display)
    prepare_progress.start_step("Loading plugins", None)
    provider_factory = factory or OcrProviderFactory.discover_default_plugins()
    result = EvaluationRunResult()

    prepare_progress.start_step("Discovering", None)
    discovered_images = discover_evaluation_images(input_root, selected_image_paths)
    images = limit_images(discovered_images, max_images)
    prepare_progress.start_step("Checksumming", len(images))
    checksum = input_tree_checksum(images, display.advance_current)
    if len(images) < len(discovered_images):
        print(
            f"Limiting evaluation to the first {len(images)} of {len(discovered_images)} "
            "eligible images; use --max-images 0 to remove the limit or --include "
            "to narrow the selection."
        )

    if ocr_provider_name is None:
        provider_names = tuple(
            name
            for name in provider_factory.provider_names
            if name not in EXCLUDED_EVALUATION_PROVIDERS
        )
    elif ocr_provider_name in provider_factory.provider_names:
        provider_names = (ocr_provider_name,)
    else:
        raise OcrProviderNotFoundError(
            f"No OCR provider is registered under {ocr_provider_name!r}."
        )
    providers_to_run: list[tuple[str, Path]] = []
    replacement_roots: list[Path] = []
    for provider_name in provider_names:
        provider_root = _provider_output_root(output_root, provider_name)
        ocr_is_current = _provider_output_is_current(provider_root, checksum)
        if ocr_is_current:
            result.skipped_providers += 1
            print(f"Skipping {provider_name}: OCR input checksum unchanged.")
        else:
            providers_to_run.append((provider_name, provider_root))
        # Regenerating OCR output removes the provider root, and so its replacement artifacts.
        if not ocr_is_current or not _text_replacement_output_is_current(
            provider_root, checksum, replacement_provider_names
        ):
            replacement_roots.append(provider_root)

    if not replacement_roots:
        replacement_provider_names = ()
    roots_to_remove = [
        (provider_name, provider_root)
        for provider_name, provider_root in providers_to_run
        if provider_root.exists()
    ]
    display.set_overall_total(
        1
        + (1 if roots_to_remove else 0)
        + (1 if providers_to_run else 0)
        + len(replacement_provider_names)
    )
    display.advance_overall()
    display.clear_current()

    if roots_to_remove:
        _remove_provider_roots(display, roots_to_remove)
        display.advance_overall()
        display.clear_current()

    if providers_to_run:
        _run_ocr_stage(display, provider_factory, providers_to_run, images, checksum, result)
        display.advance_overall()
        display.clear_current()

    if replacement_provider_names:
        _run_text_replacement_stages(
            display,
            replacement_roots,
            images,
            text_replacement_factory,
            replacement_provider_names,
            checksum,
        )

    return result


def _count_files(root: Path) -> int:
    return sum(len(file_names) for _, _, file_names in os.walk(root))


def _remove_tree(root: Path, on_file_removed: Callable[[], None]) -> None:
    """Remove a directory tree, reporting each removed file."""
    for directory, directory_names, file_names in os.walk(root, topdown=False):
        for file_name in file_names:
            os.unlink(os.path.join(directory, file_name))
            on_file_removed()
        for directory_name in directory_names:
            path = os.path.join(directory, directory_name)
            if not os.path.islink(path):
                os.rmdir(path)
            elif os.name == "nt":
                os.rmdir(path)  # Windows directory links are removed as directories
            else:
                os.unlink(path)
    os.rmdir(root)


def _remove_provider_roots(
    display: LiveProgress, roots_to_remove: list[tuple[str, Path]]
) -> None:
    """Remove superseded provider output with per-file progress."""
    display.start_current(CLEANUP_STAGE, None, "file")
    display.set_current_label("Scanning")
    for _, provider_root in roots_to_remove:
        if not provider_root.is_dir():
            raise ValueError(f"Provider output path is not a directory: {provider_root}")
    total = sum(_count_files(provider_root) for _, provider_root in roots_to_remove)
    display.start_current(CLEANUP_STAGE, total, "file")
    for provider_name, provider_root in roots_to_remove:
        display.set_current_label(provider_name)
        _remove_tree(provider_root, display.advance_current)


def _run_ocr_stage(
    display: LiveProgress,
    provider_factory: OcrProviderFactory,
    providers_to_run: list[tuple[str, Path]],
    images: list[EvaluationImage],
    checksum: str,
    result: EvaluationRunResult,
) -> None:
    """Run every selected OCR provider over every kept image."""
    progress = display.start_current(OCR_STAGE, len(images) * len(providers_to_run), "evaluation")
    providers: list[tuple[str, Path, OcrProvider]] = []
    for provider_name, provider_root in providers_to_run:
        display.set_current_label(f"Loading {provider_name}")
        provider_root.mkdir(parents=True)
        providers.append((provider_name, provider_root, provider_factory.create(provider_name)))

    entries_by_provider: dict[str, list[ViewerEntry]] = {}
    for provider_name, provider_root, provider in providers:
        entries_by_provider[provider_name] = _evaluate_provider(
            provider_name, provider, images, provider_root, result, progress
        )

    for provider_name, provider_root, _ in providers:
        display.set_current_label(f"Writing viewer: {provider_name}")
        _write_viewer(provider_root, entries_by_provider[provider_name])
        (provider_root / CHECKSUM_FILENAME).write_text(f"{checksum}\n", encoding="ascii")
        (provider_root / ARTIFACT_FORMAT_VERSION_FILENAME).write_text(
            f"{_artifact_format_version(provider_name)}\n", encoding="ascii"
        )


def prepare_and_evaluate_ocr_inputs(
    input_root: Path,
    output_root: Path,
    factory: OcrProviderFactory | None = None,
    prepare_inputs: Callable[
        [Path, Path, tuple[str, ...], PreparationProgress], PreparationResult
    ] = prepare_evaluation_inputs,
    *,
    ocr_provider_name: str | None = None,
    text_replacement_provider_name: str | None = None,
    text_replacement_factory: TextReplacementProviderFactory | None = None,
    include_patterns: tuple[str, ...] = (),
    max_images: int = DEFAULT_MAX_IMAGES,
) -> EvaluationRunResult:
    """Prepare the standard sample corpus, then evaluate the resulting input images."""
    # Reject an unknown text-replacement provider before any preparation work starts.
    replacement_factory = (
        text_replacement_factory or TextReplacementProviderFactory.discover_default_plugins()
    )
    text_replacement_provider_names(replacement_factory, text_replacement_provider_name)
    with LiveProgress() as display:
        _start_prepare_stage(display)
        preparation = prepare_inputs(
            Path("sample-data"), input_root, include_patterns, _PrepareStageProgress(display)
        )
        selected_image_paths = preparation.selected_image_paths if include_patterns else None
        return evaluate_ocr_inputs(
            input_root,
            output_root,
            factory,
            ocr_provider_name=ocr_provider_name,
            text_replacement_provider_name=text_replacement_provider_name,
            text_replacement_factory=replacement_factory,
            selected_image_paths=selected_image_paths,
            max_images=max_images,
            display=display,
        )


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
        == _artifact_format_version(provider_root.name)
    )


def _artifact_format_version(provider_name: str) -> str:
    if provider_name == "google_cloud_vision":
        return f"{VISION_ARTIFACT_FORMAT_VERSION}:{vision_cache_identity()}"
    return ARTIFACT_FORMAT_VERSION


def _text_replacement_marker(checksum: str, provider_names: tuple[str, ...]) -> str:
    """Identify the input and the ordered providers that produced replacement artifacts."""
    return f"{checksum} {','.join(provider_names)}"


def _text_replacement_output_is_current(
    provider_root: Path, checksum: str, provider_names: tuple[str, ...]
) -> bool:
    """Return whether the independent text-replacement artifact stage is current."""
    checksum_path = provider_root / TEXT_REPLACEMENT_CHECKSUM_FILENAME
    version_path = provider_root / TEXT_REPLACEMENT_ARTIFACT_FORMAT_VERSION_FILENAME
    return (
        provider_root.is_dir()
        and (provider_root / TEXT_REPLACEMENT_VIEWER_FILENAME).is_file()
        and checksum_path.is_file()
        and checksum_path.read_text(encoding="ascii").strip()
        == _text_replacement_marker(checksum, provider_names)
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
                with source_cache_scope(image.path):
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
    masked_path = _masked_image_path(provider_root, evaluation_image)
    masked_path.parent.mkdir(parents=True, exist_ok=True)
    masked_path.write_text(
        _masked_svg(provider_root, evaluation_image, source_image.size, result),
        encoding="utf-8",
    )

    for index, text_item in enumerate(result.text_items, start=1):
        bounds = _padded_clipped_bounds(
            source_image, text_item.bounding_polygon.vertices
        )
        source_image.crop(bounds).save(
            _text_clip_path(provider_root, evaluation_image, index), format="PNG"
        )


@dataclass
class _PendingReplacement:
    """One successful OCR image awaiting each text-replacement provider's artifacts."""

    image: EvaluationImage
    ocr_result: OcrResult | None
    failed: bool
    eligible_text_items: tuple[tuple[int, OcrText], ...] = ()
    estimates: tuple[TextRegionColourEstimate, ...] | None = None


def _write_text_replacement_artifacts(
    provider_root: Path,
    item: _PendingReplacement,
    source_image: Image.Image,
    replacement_provider: TextReplacementProvider,
    provider_index: int,
    replacement_typeface: skia.Typeface,
) -> None:
    """Write the complete and region-clipped replacement artifacts for one provider."""
    evaluation_image = item.image
    assert item.ocr_result is not None
    artifact_directory = _replacement_artifact_directory(provider_root, evaluation_image)
    if provider_index == 1:
        if artifact_directory.exists():
            shutil.rmtree(artifact_directory)
        artifact_directory.mkdir(parents=True, exist_ok=True)
        item.eligible_text_items = tuple(
            (region_index, text_item)
            for region_index, text_item in enumerate(item.ocr_result.text_items, start=1)
            if text_item.confidence >= TEXT_REPLACEMENT_MINIMUM_CONFIDENCE
        )
        item.estimates = tuple(
            estimate_replacement_colours(
                source_image, [text_item for _, text_item in item.eligible_text_items]
            )
        )
    assert item.estimates is not None
    with source_cache_scope(evaluation_image.path):
        updated_image = source_image.copy()
        replacements: list[TextRegionReplacement] = []
        for (_, text_item), estimate in zip(
            item.eligible_text_items, item.estimates, strict=True
        ):
            replacement = replace_text(
                replacement_provider, text_item.text, is_filename=False,
                source_language=evaluation_image.language, target_language="en",
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
    for region_index, text_item in item.eligible_text_items:
        bounds = _padded_clipped_bounds(source_image, text_item.bounding_polygon.vertices)
        updated_image.crop(bounds).save(
            _replacement_text_clip_path(
                provider_root, evaluation_image, region_index, provider_index
            ),
            format="PNG",
        )


def _plan_text_replacement(
    provider_root: Path, images: list[EvaluationImage]
) -> tuple[list[_PendingReplacement], dict[Path, ViewerEntry]]:
    """Read cached OCR JSON without calling OCR, separating usable results from failures."""
    pending: list[_PendingReplacement] = []
    failed_entries: dict[Path, ViewerEntry] = {}
    for image in images:
        payload = json.loads(_result_json_path(provider_root, image).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("status") != "succeeded":
            failed_entries[image.relative_path] = ViewerEntry(image, False, (), (), False)
            continue
        try:
            ocr_result: OcrResult | None = _ocr_result_from_cached_payload(payload)
        except (KeyError, OSError, TypeError, ValueError):
            ocr_result = None
        pending.append(_PendingReplacement(image, ocr_result, failed=ocr_result is None))
    return pending, failed_entries


def _run_text_replacement_stages(
    display: LiveProgress,
    provider_roots: list[Path],
    images: list[EvaluationImage],
    text_replacement_factory: TextReplacementProviderFactory,
    replacement_provider_names: tuple[str, ...],
    checksum: str,
) -> None:
    """Run one stage per text-replacement provider across every root needing replacement."""
    plans = [(root, *_plan_text_replacement(root, images)) for root in provider_roots]
    total = sum(len(pending) for _, pending, _ in plans)
    replacement_typeface: skia.Typeface | None = None

    for provider_index, replacement_name in enumerate(replacement_provider_names, start=1):
        display.start_current(
            f"{TEXT_REPLACEMENT_STAGE_PREFIX}{replacement_name}", total, "image"
        )
        if replacement_typeface is None:
            display.set_current_label("Loading typeface")
            replacement_typeface = _load_default_typeface()
        display.set_current_label(f"Loading {replacement_name}")
        replacement_provider = text_replacement_factory.create(replacement_name)
        for provider_root, pending, _ in plans:
            for item in pending:
                display.set_current_label(
                    f"{provider_root.name}: {_progress_label(item.image.path.name)}"
                )
                try:
                    if not item.failed:
                        with Image.open(item.image.path) as opened_image:
                            source_image = opened_image.copy()
                        _write_text_replacement_artifacts(
                            provider_root, item, source_image, replacement_provider,
                            provider_index, replacement_typeface,
                        )
                except (KeyError, OSError, TypeError, ValueError):
                    item.failed = True
                finally:
                    display.advance_current()

        if provider_index == len(replacement_provider_names):
            for provider_root, pending, failed_entries in plans:
                display.set_current_label(f"Writing viewer: {provider_root.name}")
                _write_text_replacement_report(
                    provider_root, images, pending, failed_entries,
                    replacement_provider_names, checksum,
                )
        display.advance_overall()
        display.clear_current()


def _write_text_replacement_report(
    provider_root: Path,
    images: list[EvaluationImage],
    pending: list[_PendingReplacement],
    failed_entries: dict[Path, ViewerEntry],
    replacement_provider_names: tuple[str, ...],
    checksum: str,
) -> None:
    """Write one provider root's replacement viewer and freshness markers."""
    pending_by_path = {item.image.relative_path: item for item in pending}
    entries: list[ViewerEntry] = []
    for image in images:
        item = pending_by_path.get(image.relative_path)
        if item is None:
            entries.append(failed_entries[image.relative_path])
            continue
        succeeded = not item.failed
        ocr_result = item.ocr_result
        if succeeded and ocr_result is not None:
            _replacement_mask_path(provider_root, image).write_text(
                _masked_svg(provider_root, image, _image_size(image.path), ocr_result, replacement=True),
                encoding="utf-8",
            )
        entries.append(
            ViewerEntry(
                image,
                True,
                tuple(text_item.confidence for text_item in ocr_result.text_items)
                if succeeded and ocr_result is not None
                else (),
                tuple(text_item.text for text_item in ocr_result.text_items)
                if succeeded and ocr_result is not None
                else (),
                succeeded,
            )
        )
    _write_text_replacement_viewer(provider_root, entries, replacement_provider_names)
    (provider_root / TEXT_REPLACEMENT_CHECKSUM_FILENAME).write_text(
        f"{_text_replacement_marker(checksum, replacement_provider_names)}\n", encoding="ascii"
    )
    (provider_root / TEXT_REPLACEMENT_ARTIFACT_FORMAT_VERSION_FILENAME).write_text(
        f"{TEXT_REPLACEMENT_ARTIFACT_FORMAT_VERSION}\n", encoding="ascii"
    )


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
    return provider_root / image.relative_path.parent / f"{image.relative_path.name}.masked.svg"


def _replacement_mask_path(provider_root: Path, image: EvaluationImage) -> Path:
    return provider_root / image.relative_path.parent / f"{image.relative_path.name}.replacement-masked.svg"


# Characters that XML 1.0 forbids, which provider text can contain.
_INVALID_XML_CHARACTERS = re.compile("[^\u0009\u000a\u000d\u0020-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


def _region_element_id(image: EvaluationImage, region_index: int) -> str:
    """Return the viewer table-row id that an SVG detection link targets."""
    path_digest = hashlib.sha256(image.relative_path.as_posix().encode("utf-8")).hexdigest()
    return f"region-{path_digest[:12]}-{region_index}"


def _masked_svg(
    provider_root: Path,
    image: EvaluationImage,
    image_size: tuple[int, int],
    result: OcrResult,
    *,
    replacement: bool = False,
) -> str:
    """Build a standalone SVG with links to rows in the selected viewer."""
    svg_directory = _masked_image_path(provider_root, image).parent
    source_url = html.escape(_relative_url(image.path, svg_directory), quote=True)
    viewer_name = TEXT_REPLACEMENT_VIEWER_FILENAME if replacement else VIEWER_FILENAME
    viewer_url = _relative_url(provider_root / viewer_name, svg_directory)
    width, height = image_size
    regions: list[str] = []
    for region_index, text_item in enumerate(result.text_items, start=1):
        points = " ".join(
            f"{format(point.x, '.15g')},{format(point.y, '.15g')}"
            for point in text_item.bounding_polygon.vertices
        )
        title = html.escape(_INVALID_XML_CHARACTERS.sub("", text_item.text), quote=False)
        polygon = f'<polygon points="{points}" fill="black"><title>{title}</title></polygon>'
        if replacement and text_item.confidence < TEXT_REPLACEMENT_MINIMUM_CONFIDENCE:
            regions.append(polygon)
        else:
            target = html.escape(f"{viewer_url}#{_region_element_id(image, region_index)}", quote=True)
            regions.append(f'<a href="{target}" target="_top">{polygon}</a>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">\n'
        f'<image href="{source_url}" x="0" y="0" width="{width}" height="{height}"/>\n'
        + "\n".join(regions)
        + "\n</svg>\n"
    )


def _image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def _mask_object_html(
    url: str | None, image_size: tuple[int, int], element_id: str = "", hidden: bool = False
) -> str:
    """Embed the SVG mask through <object>, which keeps its links active and loads its bitmap."""
    width, height = image_size
    attributes = [
        'type="image/svg+xml"',
        f'style="aspect-ratio: {width} / {height}; height: auto; max-width: 100%; width: {width}px"',
    ]
    if element_id:
        attributes.append(f'id="{html.escape(element_id, quote=True)}"')
    if url is not None:
        attributes.append(f'data="{html.escape(url, quote=True)}"')
    if hidden:
        attributes.append("hidden")
    return f'<object {" ".join(attributes)}>Detected regions masked</object>'


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
    overview = "\n".join(
        f'<article class="overview-item">{_overview_header_html(provider_root, entry)}'
        f'{_ocr_preview_html(provider_root, entry)}</article>'
        for entry in entries if entry.succeeded
    )
    document = f"""<!doctype html>
<html lang="en" translate="no">
<head>
  <meta charset="utf-8">
  <meta name="google" content="notranslate">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OCR evaluation</title>
  <style>
    body {{ background: #f6f7f9; color: #1f2937; font-family: system-ui, sans-serif; margin: 0; }}
    main {{ margin: 0 auto; max-width: 1100px; padding: 2rem; }}
    article {{ background: white; border: 1px solid #d9dee7; border-radius: 8px; margin: 1rem 0; padding: 1rem; }}
    h1, h2 {{ margin-top: 0; }} .failed {{ border-left: 5px solid #b91c1c; }}
    .images {{ display: flex; flex-wrap: nowrap; gap: 1rem; }}
    .images figure {{ box-sizing: border-box; flex: 0 0 calc(50% - .5rem); margin: 0; min-width: 0; }}
    img {{ border: 1px solid #cbd5e1; height: auto; max-width: 100%; }} figcaption {{ font-size: .9rem; }}
    table {{ border-collapse: collapse; margin-top: 1rem; width: 100%; }} th, td {{ border: 1px solid #cbd5e1; padding: .5rem; text-align: left; vertical-align: top; }}
    th {{ background: #f1f5f9; }} td img {{ max-height: 120px; }}
    object {{ background: white; border: 1px solid #cbd5e1; display: block; }}
    tr:target td {{ background: #fef9c3; }}
    .extracted-text {{ white-space: pre-wrap; }}
    .confidence {{ text-align: right; white-space: nowrap; width: 7ch; }}
  </style>
</head>
<body>
  <main>
    <h1>OCR evaluation</h1>
    <p>{len(entries)} image evaluation(s).</p>
    <section><h2>Image overview</h2><div class="overview">{overview}</div></section>
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
    overview = "\n".join(
        f'<article class="overview-item">{_overview_header_html(provider_root, entry)}'
        f'{_replacement_preview_html(provider_root, entry, replacement_provider_names, f"overview-{entry_index}")}</article>'
        for entry_index, entry in enumerate(entries, start=1)
        if entry.succeeded and entry.replacement_succeeded
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
    object {{ background: white; border: 1px solid #cbd5e1; display: block; }}
    [hidden] {{ display: none !important; }}
    tr:target td {{ background: #fef9c3; }}
    table {{ border-collapse: collapse; margin-top: 1rem; width: auto; }} th, td {{ border: 1px solid #cbd5e1; padding: .5rem; text-align: left; vertical-align: top; }}
    th {{ background: #f1f5f9; }} td img {{ max-height: 120px; }}
  </style>
</head>
<body>
  <main>
    <h1>OCR text-replacement evaluation</h1>
    <p>{len(entries)} image evaluation(s).</p>
    <section><h2>Image overview</h2><div class="overview">{overview}</div></section>
    {rendered_entries}
  </main>
  <script>
    const selects = document.querySelectorAll("select[data-replacement-preview]");
    selects.forEach((select) => {{
      select.addEventListener("change", () => {{
        // All dropdowns have the same option order, but image-specific URLs.
        const selectedIndex = select.selectedIndex;
        selects.forEach((target) => {{
          target.selectedIndex = selectedIndex;
          const preview = document.getElementById(target.dataset.replacementPreview);
          const mask = document.getElementById(target.dataset.replacementMask);
          const showMask = target.value.endsWith(".svg");
          if (showMask) {{
            if (mask.getAttribute("data") !== target.value) mask.setAttribute("data", target.value);
          }} else {{
            preview.src = target.value;
          }}
          preview.hidden = showMask;
          mask.hidden = !showMask;
        }});
      }});
    }});
  </script>
</body>
</html>
"""
    (provider_root / TEXT_REPLACEMENT_VIEWER_FILENAME).write_text(document, encoding="utf-8")


def _overview_header_html(provider_root: Path, entry: ViewerEntry) -> str:
    title = html.escape(entry.image.relative_path.as_posix())
    language = html.escape(entry.image.language)
    result_path = html.escape(_relative_url(_result_json_path(provider_root, entry.image), provider_root), quote=True)
    return (
        f'<h3>{title}</h3><p>Language: {language}. '
        f'<a href="{result_path}" target="_blank" rel="noopener">JSON result</a></p>'
    )


def _ocr_preview_html(provider_root: Path, entry: ViewerEntry) -> str:
    image_path = html.escape(_relative_url(entry.image.path, provider_root), quote=True)
    masked_path = _relative_url(_masked_image_path(provider_root, entry.image), provider_root)
    return f"""<div class="images">
    <figure><img alt="Original input" src="{image_path}"><figcaption>Input</figcaption></figure>
    <figure>{_mask_object_html(masked_path, _image_size(entry.image.path))}<figcaption>Detected regions masked</figcaption></figure>
  </div>"""


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

    if not entry.replacement_succeeded:
        return f"""<article class="failed">
  <h2>{title}</h2><p>Language: {html.escape(entry.image.language)}→en. OCR succeeded; text-replacement artifacts failed.</p>
</article>"""

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
    return f"""<article>
  <h2>{title}</h2><p>Language: {html.escape(entry.image.language)}→en. Status: succeeded.</p>
  {_replacement_preview_html(provider_root, entry, replacement_provider_names, str(entry_index))}
  {table}
</article>"""


def _replacement_preview_html(
    provider_root: Path,
    entry: ViewerEntry,
    replacement_provider_names: tuple[str, ...],
    identifier_suffix: str,
) -> str:
    """Render a selectable preview for an overview or breakdown."""
    image_path = _relative_url(entry.image.path, provider_root)
    masked_path = _relative_url(_replacement_mask_path(provider_root, entry.image), provider_root)
    preview_identifier = f"replacement-preview-{identifier_suffix}"
    preview_sources = tuple(
        _relative_url(
            _replacement_complete_image_path(provider_root, entry.image, provider_index), provider_root
        )
        for provider_index in range(1, len(replacement_provider_names) + 1)
    )
    initial_index = len(preview_sources) - 1 if len(preview_sources) > len(
        BASELINE_TEXT_REPLACEMENT_PROVIDERS
    ) else 0
    provider_options = "".join(
        f'<option value="{html.escape(source, quote=True)}"'
        f'{" selected" if index == initial_index else ""}>{html.escape(provider_name)}</option>'
        for index, (provider_name, source) in enumerate(
            zip(replacement_provider_names, preview_sources, strict=True)
        )
    )
    options = (
        f"{provider_options}"
        f'<option value="{html.escape(masked_path, quote=True)}">Detected regions masked</option>'
    )
    first_preview = preview_sources[initial_index] if preview_sources else ""
    return f"""<div class="top-previews">
    <figure class="top-preview"><img alt="Original input" src="{html.escape(image_path, quote=True)}"><figcaption>Input</figcaption></figure>
    <div class="complete-preview top-preview">
      <img id="{preview_identifier}" alt="Complete text-replacement preview" src="{html.escape(first_preview, quote=True)}">
      {_mask_object_html(None, _image_size(entry.image.path), f"{preview_identifier}-mask", hidden=True)}
      <label for="replacement-select-{identifier_suffix}">Complete replacement preview</label>
      <select id="replacement-select-{identifier_suffix}" data-replacement-preview="{preview_identifier}" data-replacement-mask="{preview_identifier}-mask">{options}</select>
    </div>
  </div>"""


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
        f'<tr id="{html.escape(_region_element_id(image, region_index), quote=True)}"><td>{region_index}</td>'
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
    result_path = _relative_url(_result_json_path(provider_root, entry.image), provider_root)
    title = html.escape(entry.image.relative_path.as_posix())
    if not entry.succeeded:
        return f"""<article class="failed">
  <h2>{title}</h2><p>Language: {html.escape(entry.image.language)}. Status: failed.</p>
  <p><a href="{html.escape(result_path, quote=True)}" target="_blank" rel="noopener">JSON result</a></p>
</article>"""
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
  {_ocr_preview_html(provider_root, entry)}
  {text_table}
</article>"""


def _text_region_row(
    provider_root: Path, image: EvaluationImage, index: int, text: str, confidence: float
) -> str:
    clip_path = _relative_url(_text_clip_path(provider_root, image, index), provider_root)
    escaped_clip_path = html.escape(clip_path, quote=True)
    return f"""<tr id="{html.escape(_region_element_id(image, index), quote=True)}">
  <td><a href="{escaped_clip_path}" target="_blank" rel="noopener"><img alt="Detected text {index}" src="{escaped_clip_path}"></a></td>
  <td class="extracted-text notranslate" lang="{html.escape(image.language, quote=True)}" translate="no">{html.escape(text)}</td>
  <td class="confidence">{confidence:.2%}</td>
</tr>"""


def _relative_url(path: Path, from_directory: Path) -> str:
    try:
        return Path(os.path.relpath(path, from_directory)).as_posix()
    except ValueError:
        # Windows has no relative path between different drives.
        return path.resolve().as_uri()


def _non_negative_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer") from None
    if number < 0:
        raise argparse.ArgumentTypeError("must be 0 or greater")
    return number


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ocr",
        metavar="PROVIDER",
        help=(
            "Evaluate only this OCR provider. Selecting google_cloud_vision "
            "sends input image content to Google."
        ),
    )
    parser.add_argument(
        "--text-replacement",
        metavar="PROVIDER",
        help=(
            "Also run this text-replacement provider after the always-run identity and "
            "character_mask providers. Selecting google_cloud_translate sends recognised "
            "text to Google."
        ),
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Include matching source paths relative to sample-data; may repeat or use commas.",
    )
    parser.add_argument(
        "--max-images",
        type=_non_negative_integer,
        default=DEFAULT_MAX_IMAGES,
        metavar="N",
        help=(
            "Evaluate at most N images, taking the first N in language-directory and "
            f"sorted-path order after --include (default: {DEFAULT_MAX_IMAGES}; 0 means no limit)."
        ),
    )
    parser.add_argument(
        "--input-root", type=Path, default=Path("outputs/evaluations/ocr/input")
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("outputs/evaluations/ocr/output")
    )
    arguments = parser.parse_args()
    try:
        arguments.include_patterns = parse_include_patterns(arguments.include)
    except ValueError as error:
        parser.error(str(error))
    try:
        text_replacement_provider_names(
            TextReplacementProviderFactory.discover_default_plugins(), arguments.text_replacement
        )
    except TextReplacementProviderNotFoundError as error:
        parser.error(f"argument --text-replacement: {error}")
    return arguments


def main() -> int:
    arguments = parse_arguments()
    try:
        require_runtime_assets("en", arguments.ocr or "paddleocr", "preserve-source-formatting")
    except RuntimeAssetsRequiredError as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        result = prepare_and_evaluate_ocr_inputs(
            arguments.input_root,
            arguments.output_root,
            ocr_provider_name=arguments.ocr,
            text_replacement_provider_name=arguments.text_replacement,
            include_patterns=arguments.include_patterns,
            max_images=arguments.max_images,
        )
    except (OcrProviderNotFoundError, TextReplacementProviderNotFoundError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(
        "OCR evaluation complete: "
        f"{result.successful_images} successful image(s), "
        f"{result.failed_images} failed image(s), "
        f"{result.skipped_providers} unchanged provider(s) skipped."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
