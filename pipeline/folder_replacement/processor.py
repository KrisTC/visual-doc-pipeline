"""Folder-oriented orchestration for local visible-text replacement."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import json
from pathlib import Path
import os
import sys
from typing import Protocol
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from PIL import Image
# skia-python does not publish PEP 561 stubs; this is the native rendering boundary.
import skia  # type: ignore[import-not-found]

from pipeline.ocr import OcrProvider
from pipeline.ocr.image_preparation import DEFAULT_OCR_BACKGROUND, RgbColour
from pipeline.folder_replacement.failure_diagnostics import (
    ContextualOcrProvider,
    ContextualTextReplacementProvider,
    FailureContext,
    exception_cause_types,
)
from pipeline.provider_cache import is_cache_sidecar, provider_diagnostic_name, source_cache_scope
from pipeline.terminal_progress import LiveProgress
from pipeline.text_replacement import TextReplacementProvider, TextReplacementRequest
from pipeline.vector_text import replace_vector_text
from pipeline.folder_replacement.office_xml import replace_office_xml_text
from pipeline.folder_replacement.docx import replace_docx_file
from pipeline.folder_replacement.pdf import pdf_work_total, replace_pdf_file
from pipeline.folder_replacement.pptx import replace_pptx_file
from pipeline.folder_replacement.xlsx import replace_xlsx_file, xlsx_native_text_request_total
from pipeline.folder_replacement.bitmap import (
    replace_bitmap_bytes as _process_bitmap_bytes,
    replace_bitmap_file as _process_bitmap_file,
    replace_image as _process_bitmap_image,
)
from pipeline.folder_replacement.filters import matches_include_patterns
from pipeline.folder_replacement.common import NestedProgressReporter
BITMAP_EXTENSIONS = frozenset({".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"})
OFFICE_DOCUMENT_EXTENSIONS = frozenset({".docx", ".pptx", ".xlsx"})
DOCUMENT_EXTENSIONS = OFFICE_DOCUMENT_EXTENSIONS | {".pdf"}
VECTOR_EXTENSIONS = frozenset({".emf", ".svg", ".wmf"})
TEXT_REPLACEMENT_MINIMUM_CONFIDENCE = 0.65


class ProgressReporter(Protocol):
    """Minimal terminal-progress operations used by the folder processor."""

    def set_postfix_str(self, text: str) -> None:
        """Show the current work item beside the progress bar."""

    def update(self, count: float | None = None) -> bool | None:
        """Advance the progress bar by ``count`` completed work items."""

    def close(self) -> None:
        """Finish terminal rendering for this bar."""


ProgressFactory = Callable[[int, str], ProgressReporter]


@dataclass(slots=True)
class FolderReplacementResult:
    """Counts and per-file failure messages from a folder-replacement run."""

    processed_files: int = 0
    ignored_files: int = 0
    failed_files: int = 0
    replaced_image_regions: int = 0
    replaced_native_text_items: int = 0
    retained_vector_graphics: int = 0
    failures: list[str] = field(default_factory=list)
    diagnostic_sidecars: list[Path] = field(default_factory=list)


def replace_input_folder(
    input_root: Path,
    output_root: Path,
    *,
    ocr_provider: OcrProvider,
    text_replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typeface: skia.Typeface,
    document_text_layout: str = "preserve-source-formatting",
    xlsx_translation_mode: str = "full",
    include_patterns: tuple[str, ...] = (),
    diagnostics_enabled: bool = False,
    show_progress: bool = True,
    progress_factory: ProgressFactory | None = None,
) -> FolderReplacementResult:
    """Replace visible text in every supported file below ``input_root``.

    The output hierarchy mirrors the input hierarchy. A filename replacement is
    requested before each destination is selected; collisions are resolved by a
    numeric suffix. One failed file is recorded and does not stop later files.
    """
    _validate_roots(input_root, output_root)
    if not source_language.strip():
        raise ValueError("A folder replacement run requires a non-empty source language.")
    if not target_language.strip():
        raise ValueError("A folder replacement run requires a non-empty target language.")
    if document_text_layout not in {
        "preserve-source-formatting",
        "preserve-basic-layout",
        "preserve-basic-layout-source-font",
    }:
        raise ValueError(
            "Document text layout must be 'preserve-source-formatting', "
            "'preserve-basic-layout', or 'preserve-basic-layout-source-font'."
        )
    if xlsx_translation_mode not in {"full", "fast"}:
        raise ValueError("XLSX translation mode must be 'full' or 'fast'.")
    if not _provider_supports_language(ocr_provider, source_language):
        raise ValueError(
            f"The selected OCR provider does not support source language {source_language!r}."
        )

    result = FolderReplacementResult()
    reserved_paths: set[Path] = set()
    source_paths = tuple(sorted(
        path for path in input_root.rglob("*") if path.is_file() and not is_cache_sidecar(path)
    ))
    eligible_source_count = sum(
        path.suffix.lower() in BITMAP_EXTENSIONS | DOCUMENT_EXTENSIONS | VECTOR_EXTENSIONS
        and matches_include_patterns(path.relative_to(input_root), include_patterns)
        for path in source_paths
    )
    display = LiveProgress() if show_progress and progress_factory is None else None
    if display is not None:
        display.__enter__()
        display.start_overall(eligible_source_count * 100, "source %")
    completed_sources = 0
    try:
      for source_path in source_paths:
        temporary_destination: Path | None = None
        destination: Path | None = None
        progress: ProgressReporter | None = None
        extension = source_path.suffix.lower()
        relative_source_path = source_path.relative_to(input_root)
        if extension not in BITMAP_EXTENSIONS | DOCUMENT_EXTENSIONS | VECTOR_EXTENSIONS:
            result.ignored_files += 1
            if diagnostics_enabled:
                _write_document_diagnostic(
                    output_root,
                    relative_source_path,
                    None,
                    _diagnostic_options(
                        source_language,
                        target_language,
                        document_text_layout,
                        include_patterns,
                        ocr_provider,
                        text_replacement_provider,
                    ),
                    _empty_document_totals(),
                    [{
                        "kind": "ignored",
                        "reason_code": "unsupported_file_type",
                        "detail": f"No folder-replacement handler supports {extension or 'files without an extension'}.",
                    }],
                    result,
                )
            continue
        if not matches_include_patterns(relative_source_path, include_patterns):
            result.ignored_files += 1
            continue
        document_diagnostics: list[dict[str, object]] = []
        counts_before = _document_totals(result)
        failure_context = FailureContext() if diagnostics_enabled else None
        processing_ocr: OcrProvider = ocr_provider
        processing_replacement: TextReplacementProvider = text_replacement_provider
        if failure_context is not None:
            processing_ocr = ContextualOcrProvider(ocr_provider, failure_context)
            processing_replacement = ContextualTextReplacementProvider(
                text_replacement_provider, failure_context
            )
        cache_scope = source_cache_scope(source_path)
        cache_scope.__enter__()
        try:
            print(f"Processing: {relative_source_path}")
            if show_progress:
                source_work_total = _source_work_total(
                    source_path,
                    document_text_layout=document_text_layout,
                    xlsx_translation_mode=xlsx_translation_mode,
                )
                if display is not None:
                    progress = display.start_current(
                        relative_source_path.name, source_work_total, "work item"
                    )
                else:
                    make_progress = progress_factory or _make_progress_bar
                    progress = make_progress(source_work_total, relative_source_path.name)

            def work_completed(label: str) -> None:
                if progress is not None:
                    progress.set_postfix_str(label)
                    progress.update()
                    if display is not None:
                        display.set_overall_from_current(completed_sources)

            if failure_context is not None:
                failure_context.set_location(
                    stage="output_filename",
                    container_kind="source_filename",
                    operation="text_replacement",
                )
            destination = _destination_path(
                input_root,
                output_root,
                source_path,
                processing_replacement,
                source_language,
                target_language,
                reserved_paths,
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary_destination = destination.with_name(f".{destination.name}.tmp")
            if extension in BITMAP_EXTENSIONS:
                if failure_context is not None:
                    failure_context.set_location(
                        stage="standalone_bitmap",
                        container_kind="bitmap_file",
                        operation="ocr",
                    )
                image_regions = _replace_bitmap_file(
                    source_path,
                    temporary_destination,
                    processing_ocr,
                    processing_replacement,
                    source_language,
                    target_language,
                    typeface,
                )
                result.replaced_image_regions += image_regions
                work_completed("bitmap")
            elif extension in VECTOR_EXTENSIONS:
                if failure_context is not None:
                    failure_context.set_location(
                        stage="standalone_vector",
                        container_kind="vector_graphic",
                        operation="text_replacement",
                    )
                vector_result = replace_vector_text(
                    source_path.read_bytes(),
                    extension,
                    lambda text: _replace_native_text(
                        text, processing_replacement, source_language, target_language
                    ),
                    source_language,
                    lambda image: _replace_image_text(
                        image,
                        processing_ocr,
                        processing_replacement,
                        source_language,
                        target_language,
                        typeface,
                    ),
                    document_text_layout=document_text_layout,
                    replacement_provider=processing_replacement,
                    target_language=target_language,
                )
                temporary_destination.write_bytes(vector_result.data)
                result.replaced_native_text_items += vector_result.replaced_text_items
                result.replaced_image_regions += vector_result.replaced_image_regions
                if not vector_result.has_editable_text and not vector_result.has_embedded_bitmaps:
                    result.retained_vector_graphics += 1
                work_completed("vector graphic")
            elif extension == ".pdf":
                if failure_context is not None:
                    failure_context.set_location(
                        stage="pdf_document",
                        container_kind="pdf_document",
                        operation="text_replacement",
                    )
                native_items, image_regions = replace_pdf_file(
                    source_path,
                    temporary_destination,
                    processing_ocr,
                    processing_replacement,
                    source_language,
                    target_language,
                    typeface,
                    work_completed,
                    document_text_layout=document_text_layout,
                    diagnostics=document_diagnostics if diagnostics_enabled else None,
                )
                result.replaced_native_text_items += native_items
                result.replaced_image_regions += image_regions
            else:
                if extension == ".docx":
                    native_items, image_regions, retained_vectors = replace_docx_file(
                        source_path, temporary_destination, processing_ocr, processing_replacement,
                        source_language, target_language, typeface, work_completed,
                        document_text_layout=document_text_layout, failure_context=failure_context,
                        diagnostics=document_diagnostics if diagnostics_enabled else None,
                        nested_progress=display,
                        xlsx_translation_mode=xlsx_translation_mode,
                    )
                elif extension == ".xlsx":
                    office_handler = replace_xlsx_file
                    native_items, image_regions, retained_vectors = office_handler(
                        source_path, temporary_destination, processing_ocr, processing_replacement,
                        source_language, target_language, typeface, work_completed,
                        document_text_layout=document_text_layout, failure_context=failure_context,
                        nested_progress=display,
                        xlsx_translation_mode=xlsx_translation_mode,
                        diagnostics=document_diagnostics if diagnostics_enabled else None,
                    )
                else:
                    native_items, image_regions, retained_vectors = replace_pptx_file(
                        source_path, temporary_destination, processing_ocr, processing_replacement,
                        source_language, target_language, typeface, work_completed,
                        document_text_layout=document_text_layout, failure_context=failure_context,
                        nested_progress=display,
                    )
                result.replaced_native_text_items += native_items
                result.replaced_image_regions += image_regions
                result.retained_vector_graphics += retained_vectors
            os.replace(temporary_destination, destination)
        except (BadZipFile, OSError, RuntimeError, ValueError) as error:
            result.failed_files += 1
            result.failures.append(f"{source_path}: {error}")
            print(f"Failed: {source_path}: {error}", file=sys.stderr)
            if temporary_destination is not None:
                temporary_destination.unlink(missing_ok=True)
            document_diagnostics.append(
                {
                    "kind": "failed",
                    "reason_code": "file_processing_failed",
                    "exception_type": type(error).__name__,
                    "detail": str(error),
                    "failure_context": (
                        failure_context.as_diagnostic()
                        if failure_context is not None
                        else {"stage": "document_setup"}
                    ),
                }
            )
            cause_types = exception_cause_types(error)
            if cause_types:
                document_diagnostics[-1]["exception_cause_types"] = cause_types
            if diagnostics_enabled:
                _write_document_diagnostic(
                    output_root,
                    relative_source_path,
                    destination,
                    _diagnostic_options(
                        source_language,
                        target_language,
                        document_text_layout,
                        include_patterns,
                        ocr_provider,
                        text_replacement_provider,
                    ),
                    _document_totals_since(counts_before, result),
                    document_diagnostics,
                    result,
                )
            continue
        else:
            reserved_paths.add(destination)
            result.processed_files += 1
            if diagnostics_enabled and document_diagnostics:
                _write_document_diagnostic(
                    output_root,
                    relative_source_path,
                    destination,
                    _diagnostic_options(
                        source_language,
                        target_language,
                        document_text_layout,
                        include_patterns,
                        ocr_provider,
                        text_replacement_provider,
                    ),
                    _document_totals_since(counts_before, result),
                    document_diagnostics,
                    result,
                )
        finally:
            cache_scope.__exit__(None, None, None)
            if display is not None:
                display.complete_overall_source(completed_sources)
                completed_sources += 1
                display.clear_current()
            elif progress is not None:
                progress.close()
    finally:
        if display is not None:
            display.__exit__(None, None, None)
    return result


def _diagnostic_options(
    source_language: str,
    target_language: str,
    document_text_layout: str,
    include_patterns: tuple[str, ...],
    ocr_provider: OcrProvider,
    text_replacement_provider: TextReplacementProvider,
) -> dict[str, object]:
    """Return the effective, document-independent options for a sidecar."""
    return {
        "source_language": source_language,
        "target_language": target_language,
        "document_text_layout": document_text_layout,
        "include_patterns": list(include_patterns),
        "ocr_provider": provider_diagnostic_name(ocr_provider),
        "text_replacement_provider": provider_diagnostic_name(text_replacement_provider),
    }


def _document_totals(result: FolderReplacementResult) -> dict[str, int]:
    """Return the counters used to calculate per-document result totals."""
    return {
        "native_text_items": result.replaced_native_text_items,
        "ocr_image_regions": result.replaced_image_regions,
        "retained_vector_graphics": result.retained_vector_graphics,
    }


def _empty_document_totals() -> dict[str, int]:
    """Return zero work totals for a source file that was never processed."""
    return {
        "native_text_items": 0,
        "ocr_image_regions": 0,
        "retained_vector_graphics": 0,
    }


def _document_totals_since(
    before: Mapping[str, int], result: FolderReplacementResult
) -> dict[str, int]:
    """Return the work counters contributed while one source file was processed."""
    after = _document_totals(result)
    return {name: after[name] - before[name] for name in after}


def _write_document_diagnostic(
    output_root: Path,
    relative_source_path: Path,
    destination: Path | None,
    options: Mapping[str, object],
    totals: Mapping[str, int],
    entries: list[dict[str, object]],
    result: FolderReplacementResult,
) -> None:
    """Write one local JSON sidecar beside a document's intended output path."""
    intended_output = destination or output_root / relative_source_path
    sidecar = intended_output.with_name(f"{intended_output.name}.diagnostics.json")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    output_path = intended_output.relative_to(output_root).as_posix()
    sidecar.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_path": relative_source_path.as_posix(),
                "output_path": output_path,
                "options": dict(options),
                "totals": dict(totals),
                "entries": entries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    result.diagnostic_sidecars.append(sidecar)


def _validate_roots(input_root: Path, output_root: Path) -> None:
    if not input_root.is_dir():
        raise ValueError(f"Input root does not exist or is not a directory: {input_root}")
    resolved_input = input_root.resolve()
    resolved_output = output_root.resolve()
    if resolved_output == resolved_input or resolved_output.is_relative_to(resolved_input):
        raise ValueError("Output root must not be the input root or a directory below it.")


def _provider_supports_language(ocr_provider: OcrProvider, language: str) -> bool:
    primary_language = language.replace("_", "-").lower().split("-", 1)[0]
    return any(
        supported.replace("_", "-").lower().split("-", 1)[0] == primary_language
        for supported in ocr_provider.supported_languages
    )


def _destination_path(
    input_root: Path,
    output_root: Path,
    source_path: Path,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    reserved_paths: set[Path],
) -> Path:
    replacement_name = replacement_provider.replace(
        TextReplacementRequest(
            text=source_path.name,
            is_filename=True,
            source_language=source_language,
            target_language=target_language,
        )
    ).text
    _validate_filename(replacement_name)
    if Path(replacement_name).suffix.lower() != source_path.suffix.lower():
        replacement_name = f"{replacement_name}{source_path.suffix}"
    relative_parent = source_path.relative_to(input_root).parent
    candidate = output_root / relative_parent / replacement_name
    _assert_path_inside_output(output_root, candidate)
    number = 2
    while candidate in reserved_paths or candidate.exists():
        candidate = candidate.with_name(
            f"{Path(replacement_name).stem} ({number}){Path(replacement_name).suffix}"
        )
        number += 1
    return candidate


def _validate_filename(name: str) -> None:
    if not name or name in {".", ".."} or "\x00" in name or Path(name).name != name:
        raise ValueError(f"Text-replacement provider returned an unsafe filename: {name!r}")


def _assert_path_inside_output(output_root: Path, path: Path) -> None:
    if not path.resolve().is_relative_to(output_root.resolve()):
        raise ValueError(f"Output path escapes output root: {path}")


def _source_work_total(
    source_path: Path,
    *,
    document_text_layout: str = "preserve-source-formatting",
    xlsx_translation_mode: str = "full",
) -> int:
    """Return the native-text plus embedded-raster work units for one source file."""
    extension = source_path.suffix.lower()
    if extension in BITMAP_EXTENSIONS:
        return 1
    if extension in VECTOR_EXTENSIONS:
        return 1
    if extension == ".docx":
        with ZipFile(source_path) as archive:
            return 4 + sum(
                _is_office_bitmap_part(name) or _is_office_vector_part(name)
                for name in archive.namelist()
            )
    if extension in OFFICE_DOCUMENT_EXTENSIONS:
        if extension == ".xlsx" and xlsx_translation_mode == "fast":
            return xlsx_native_text_request_total(
                source_path.read_bytes(), document_text_layout, xlsx_translation_mode
            ) + 2
        with ZipFile(source_path) as archive:
            return 1 + sum(
                _is_office_bitmap_part(name) or _is_office_vector_part(name)
                for name in archive.namelist()
            )
    return pdf_work_total(source_path)


def _make_progress_bar(total: int, label: str) -> ProgressReporter:
    """Create the standard terminal bar for one source file."""
    raise RuntimeError("A Rich live display is required when no test progress factory is supplied.")


def _replace_bitmap_file(
    source: Path,
    destination: Path,
    ocr_provider: OcrProvider,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typeface: skia.Typeface,
) -> int:
    return _process_bitmap_file(source, destination, ocr_provider, replacement_provider, source_language, target_language, typeface)


def _replace_image_text(
    image: Image.Image,
    ocr_provider: OcrProvider,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typeface: skia.Typeface,
) -> int:
    return _process_bitmap_image(image, ocr_provider, replacement_provider, source_language, target_language, typeface)


def _replace_office_file(
    source: Path,
    destination: Path,
    ocr_provider: OcrProvider,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typeface: skia.Typeface,
    work_completed: Callable[[str], None],
    *,
    document_text_layout: str = "preserve-source-formatting",
    replace_native_xml: bool = True,
    skip_native_xml_part: Callable[[str], bool] | None = None,
    ocr_backgrounds: Mapping[str, RgbColour] | None = None,
    failure_context: FailureContext | None = None,
    nested_progress: NestedProgressReporter | None = None,
) -> tuple[int, int, int]:
    native_items = 0
    image_regions = 0
    embedded_image_index = 0
    vector_graphic_index = 0
    retained_vectors = 0
    with ZipFile(source) as source_archive, ZipFile(destination, "w", ZIP_DEFLATED) as destination_archive:
        for entry in source_archive.infolist():
            if failure_context is not None:
                failure_context.set_location(
                    stage="office_package_read",
                    container_kind="office_package_part",
                    operation="read",
                    package_part=entry.filename,
                )
            data = source_archive.read(entry.filename)
            if _is_office_bitmap_part(entry.filename):
                embedded_image_index += 1
                if failure_context is not None:
                    failure_context.set_location(
                        stage="embedded_bitmap",
                        container_kind="embedded_bitmap",
                        operation="ocr",
                        package_part=entry.filename,
                        item_index=embedded_image_index,
                    )
                if nested_progress is not None:
                    nested_progress.start_nested(entry.filename, 3, "stage")
                try:
                    data, replaced = _replace_bitmap_bytes(
                        data,
                        ocr_provider,
                        replacement_provider,
                        source_language,
                        target_language,
                        typeface,
                        DEFAULT_OCR_BACKGROUND
                        if ocr_backgrounds is None
                        else ocr_backgrounds.get(entry.filename, DEFAULT_OCR_BACKGROUND),
                        None if nested_progress is None else nested_progress.advance_nested,
                    )
                finally:
                    if nested_progress is not None:
                        nested_progress.clear_nested()
                image_regions += replaced
                work_completed(f"embedded image {embedded_image_index}")
            elif _is_office_vector_part(entry.filename):
                vector_graphic_index += 1
                if failure_context is not None:
                    failure_context.set_location(
                        stage="embedded_vector",
                        container_kind="embedded_vector",
                        operation="text_replacement",
                        package_part=entry.filename,
                        item_index=vector_graphic_index,
                    )
                vector_result = replace_vector_text(
                    data,
                    Path(entry.filename).suffix,
                    lambda text: _replace_native_text(
                        text, replacement_provider, source_language, target_language
                    ),
                    source_language,
                    lambda image: _replace_image_text(
                        image,
                        ocr_provider,
                        replacement_provider,
                        source_language,
                        target_language,
                        typeface,
                    ),
                    document_text_layout=document_text_layout,
                    replacement_provider=replacement_provider,
                    target_language=target_language,
                )
                data = vector_result.data
                native_items += vector_result.replaced_text_items
                image_regions += vector_result.replaced_image_regions
                if not vector_result.has_editable_text and not vector_result.has_embedded_bitmaps:
                    retained_vectors += 1
                    print(f"Retained vector without editable text: {source}", file=sys.stderr)
                work_completed(f"vector graphic {vector_graphic_index}")
            elif (
                replace_native_xml
                and entry.filename.endswith(".xml")
                and not (skip_native_xml_part and skip_native_xml_part(entry.filename))
            ):
                if failure_context is not None:
                    failure_context.set_location(
                        stage="native_xml",
                        container_kind="office_xml",
                        operation="text_replacement",
                        package_part=entry.filename,
                    )
                data, replaced = replace_office_xml_text(
                    data, replacement_provider, source_language, target_language
                )
                native_items += replaced
            if failure_context is not None:
                failure_context.set_location(
                    stage="office_package_write",
                    container_kind="office_package_part",
                    operation="write",
                    package_part=entry.filename,
                )
            destination_archive.writestr(entry, data)
    work_completed("native text")
    return native_items, image_regions, retained_vectors


def _is_office_bitmap_part(part_name: str) -> bool:
    return "/media/" in part_name and Path(part_name).suffix.lower() in BITMAP_EXTENSIONS


def _is_office_vector_part(part_name: str) -> bool:
    return "/media/" in part_name and Path(part_name).suffix.lower() in VECTOR_EXTENSIONS


def _replace_bitmap_bytes(
    data: bytes,
    ocr_provider: OcrProvider,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typeface: skia.Typeface,
    ocr_background: RgbColour = DEFAULT_OCR_BACKGROUND,
    nested_completed: Callable[[str], None] | None = None,
) -> tuple[bytes, int]:
    return _process_bitmap_bytes(
        data,
        ocr_provider,
        replacement_provider,
        source_language,
        target_language,
        typeface,
        ocr_background,
        nested_completed,
    )


def _replace_native_text(
    text: str,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
) -> str:
    return replacement_provider.replace(
        TextReplacementRequest(
            text=text,
            is_filename=False,
            source_language=source_language,
            target_language=target_language,
        )
    ).text
