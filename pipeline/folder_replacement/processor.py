"""Folder-oriented orchestration for local visible-text replacement."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import json
from pathlib import Path
import os
import random
import re
import sys
import time
from time import perf_counter
from typing import Protocol
from zipfile import BadZipFile, ZipFile

# skia-python does not publish PEP 561 stubs; this is the native rendering boundary.
import skia  # type: ignore[import-not-found]

from pipeline.ocr import OcrProvider
from pipeline.folder_replacement.failure_diagnostics import (
    ContextualOcrProvider,
    ContextualTextReplacementProvider,
    FailureContext,
    exception_cause_types,
)
from pipeline.folder_replacement.logo_filter import LogoFilteringOcrProvider
from pipeline.provider_cache import (
    CACHE_FILENAME_SUFFIX, CacheInspectionError, CachingOcrProvider,
    CachingTextReplacementProvider, inspect_cache, is_cache_sidecar,
    provider_diagnostic_name, source_cache_scope,
)
from pipeline.provider_metrics import MeteredOcrProvider, MeteredTextReplacementProvider, RunMetrics
from pipeline.terminal_progress import LiveProgress
from pipeline.text_replacement import TextReplacementProvider, TranslationEngine, replace_text
from pipeline.vector_text import VectorReplacementResult
from pipeline.folder_replacement.docx import DocxResult, apply_docx, docx_work_item_total, plan_docx
from pipeline.folder_replacement.pdf import apply_pdf, pdf_work_total, plan_pdf
from pipeline.folder_replacement.pptx import PptxResult, apply_pptx, plan_pptx, pptx_work_item_total
from pipeline.folder_replacement.xlsx import XlsxResult, apply_xlsx, plan_xlsx, xlsx_work_item_total
from pipeline.folder_replacement.bitmap import (
    apply_bitmap,
    plan_bitmap_file,
    save_bitmap_file,
)
from pipeline.folder_replacement.planning import PhaseProgress, plan_and_apply
from pipeline.folder_replacement.vector import (
    append_vector_diagnostics,
    apply_vector,
    plan_vector,
)
from pipeline.folder_replacement.filters import is_office_owner_file, matches_include_patterns
from pipeline.folder_replacement.common import NestedProgressReporter
BITMAP_EXTENSIONS = frozenset({".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"})
OFFICE_DOCUMENT_EXTENSIONS = frozenset({".docx", ".pptx", ".xlsx"})
DOCUMENT_EXTENSIONS = OFFICE_DOCUMENT_EXTENSIONS | {".pdf"}
VECTOR_EXTENSIONS = frozenset({".emf", ".svg", ".wmf"})
TEXT_REPLACEMENT_MINIMUM_CONFIDENCE = 0.65
PROGRESS_WRITE_RETRY_SECONDS = 5.0
PROGRESS_WRITE_INITIAL_DELAY_SECONDS = 0.05
PROGRESS_WRITE_MAX_DELAY_SECONDS = 1.0


class ProgressWriteError(OSError):
    """A progress snapshot could not be written within the retry period."""

    def __init__(self, path: Path, elapsed_seconds: float, cause: OSError) -> None:
        super().__init__(
            f"Could not write progress file {path} after {elapsed_seconds:.1f} seconds: {cause}. "
            "Another process, such as endpoint-security software, may be holding the file open."
        )
        self.path = path
        self.elapsed_seconds = elapsed_seconds


class ProgressReporter(Protocol):
    """Minimal terminal-progress operations used by the folder processor."""

    def set_postfix_str(self, text: str) -> None:
        """Show the current work item beside the progress bar."""

    def update(self, count: float | None = None) -> bool | None:
        """Advance the progress bar by ``count`` completed work items."""

    def close(self) -> None:
        """Finish terminal rendering for this bar."""


ProgressFactory = Callable[[int, str], ProgressReporter]
ProgressEntry = dict[str, str | int | float | None]
ProgressEntries = dict[str, ProgressEntry]


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
    preserve_logo_text: tuple[str, ...] = (),
    diagnostics_enabled: bool = False,
    ocr_provider_name: str | None = None,
    text_replacement_provider_name: str | None = None,
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
    preserved_logos = frozenset(value.strip(" ") for value in preserve_logo_text)
    if "" in preserved_logos:
        raise ValueError("Logo text to preserve must not be empty or spaces-only.")
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
    source_paths = tuple(sorted(path for path in input_root.rglob("*") if path.is_file()))
    eligible_source_count = sum(
        not is_cache_sidecar(path)
        and not is_office_owner_file(path)
        and path.suffix.lower() in BITMAP_EXTENSIONS | DOCUMENT_EXTENSIONS | VECTOR_EXTENSIONS
        and matches_include_patterns(path.relative_to(input_root), include_patterns)
        for path in source_paths
    )
    output_root.mkdir(parents=True, exist_ok=True)
    progress_entries: ProgressEntries = {
        path.relative_to(input_root).as_posix(): {
            "status": (
                "queued"
                if not is_cache_sidecar(path)
                and not is_office_owner_file(path)
                and path.suffix.lower()
                in BITMAP_EXTENSIONS | DOCUMENT_EXTENSIONS | VECTOR_EXTENSIONS
                and matches_include_patterns(path.relative_to(input_root), include_patterns)
                else "skipped"
            )
        }
        for path in source_paths
    }

    display = LiveProgress() if show_progress and progress_factory is None else None
    if display is not None:
        display.__enter__()
        display.start_overall(eligible_source_count * 100, "source %")
    completed_sources = 0
    overall_progress = 0
    overall_eta_seconds: float | None = None
    overall_eta_status = _eta_status(None, display is not None)

    def update_overall_state(current_file_progress: int = 0) -> None:
        """Keep the JSON Overall state aligned with the Rich Overall task."""
        nonlocal overall_progress, overall_eta_seconds, overall_eta_status
        if display is not None:
            overall_progress, overall_eta_seconds = display.overall_state()
        elif eligible_source_count:
            overall_progress = int(
                (completed_sources * 100 + current_file_progress)
                * 100
                / (eligible_source_count * 100)
            )
            overall_eta_seconds = None
        overall_eta_status = _eta_status(overall_eta_seconds, display is not None)

    progress_warning_shown = False

    def publish_progress() -> None:
        # A progress snapshot is monitoring output: a lock that outlasts the retry
        # period skips this snapshot, and the next one supersedes it.
        nonlocal progress_warning_shown
        try:
            _write_progress_file(
                output_root, overall_progress, overall_eta_seconds, progress_entries,
                eta_status=overall_eta_status,
            )
        except ProgressWriteError as error:
            if not progress_warning_shown:
                progress_warning_shown = True
                print(f"Warning: {error} Progress updates continue to be attempted.", file=sys.stderr)

    publish_progress()
    try:
      for source_path in source_paths:
        temporary_destination: Path | None = None
        destination: Path | None = None
        progress: ProgressReporter | None = None
        extension = source_path.suffix.lower()
        relative_source_path = source_path.relative_to(input_root)
        progress_entry = progress_entries[relative_source_path.as_posix()]
        if is_cache_sidecar(source_path) or is_office_owner_file(source_path):
            continue
        if extension not in BITMAP_EXTENSIONS | DOCUMENT_EXTENSIONS | VECTOR_EXTENSIONS:
            result.ignored_files += 1
            if diagnostics_enabled:
                _write_document_diagnostic(
                    output_root,
                    source_path,
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
        emf_layout_trace: list[dict[str, object]] = []
        counts_before = _document_totals(result)
        failure_context = FailureContext() if diagnostics_enabled else None
        processing_ocr: OcrProvider = ocr_provider
        processing_replacement: TextReplacementProvider = text_replacement_provider
        run_metrics = RunMetrics() if diagnostics_enabled else None
        if run_metrics is not None:
            run_metrics.__enter__()
            if not isinstance(ocr_provider, CachingOcrProvider):
                processing_ocr = MeteredOcrProvider(
                    ocr_provider, ocr_provider_name or type(ocr_provider).__name__
                )
            if not isinstance(text_replacement_provider, CachingTextReplacementProvider):
                processing_replacement = MeteredTextReplacementProvider(
                    text_replacement_provider,
                    text_replacement_provider_name or type(text_replacement_provider).__name__,
                )
        if failure_context is not None:
            processing_ocr = ContextualOcrProvider(processing_ocr, failure_context)
            processing_replacement = ContextualTextReplacementProvider(
                processing_replacement, failure_context
            )
        if preserved_logos:
            processing_ocr = LogoFilteringOcrProvider(processing_ocr, preserved_logos)
        document_started = perf_counter()
        cache_scope = source_cache_scope(source_path)
        cache_scope.__enter__()
        try:
            progress_entry["status"] = "processing"
            progress_entry["progress"] = 0
            _set_entry_eta(progress_entry, None, display is not None)
            update_overall_state()
            publish_progress()
            source_work_total = _source_work_total(
                source_path,
                document_text_layout=document_text_layout,
                xlsx_translation_mode=xlsx_translation_mode,
            )
            completed_work = 0
            reported_progress = 0
            if show_progress:
                if display is not None:
                    progress = display.start_current(
                        relative_source_path.name, source_work_total, "work item"
                    )
                else:
                    make_progress = progress_factory or _make_progress_bar
                    progress = make_progress(source_work_total, relative_source_path.name)
            _set_entry_eta(
                progress_entry,
                None if display is None else display.current_state()[1],
                display is not None,
            )
            update_overall_state()
            publish_progress()
            print(f"Processing: {relative_source_path}")

            def work_completed(label: str) -> None:
                nonlocal completed_work, reported_progress
                completed_work += 1
                file_progress = min(
                    99, int(completed_work * 100 / source_work_total)
                )
                progress_entry["progress"] = max(reported_progress, file_progress)
                progress_entry["details"] = label
                if progress is not None:
                    progress.set_postfix_str(label)
                    progress.update()
                    if display is not None:
                        display.set_overall_from_current(completed_sources)
                if display is not None:
                    file_progress, current_eta = display.current_state()
                    _set_entry_eta(progress_entry, current_eta, True)
                file_progress = max(reported_progress, min(99, file_progress))
                reported_progress = file_progress
                progress_entry["progress"] = file_progress
                update_overall_state(file_progress)
                publish_progress()

            def set_work_label(label: str) -> None:
                progress_entry["details"] = label
                if progress is not None:
                    progress.set_postfix_str(label)
                publish_progress()

            def grow_work_total(count: int) -> None:
                nonlocal source_work_total
                source_work_total += count
                set_total = getattr(progress, "set_total", None)
                if callable(set_total):
                    set_total(source_work_total)

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
                plan = plan_bitmap_file(source_path, processing_ocr, source_language)
                work_completed("Planning image 1 of 1")
                phase_progress = PhaseProgress(work_completed, set_work_label, grow_work_total)
                image_regions = plan_and_apply(
                    plan,
                    TranslationEngine(processing_replacement, source_language, target_language),
                    lambda translate: apply_bitmap(plan, translate, typeface, target_language),
                    phase_progress,
                )
                save_bitmap_file(plan, temporary_destination)
                if diagnostics_enabled:
                    document_diagnostics.extend(plan.skipped_regions)
                result.replaced_image_regions += image_regions
                work_completed("Applying image 1 of 1")
            elif extension in VECTOR_EXTENSIONS:
                if failure_context is not None:
                    failure_context.set_location(
                        stage="standalone_vector",
                        container_kind="vector_graphic",
                        operation="text_replacement",
                    )
                vector_plan = plan_vector(
                    source_path.read_bytes(),
                    extension,
                    processing_ocr,
                    source_language,
                    target_language,
                    document_text_layout=document_text_layout,
                    diagnostics=document_diagnostics if diagnostics_enabled else None,
                )
                work_completed("Planning vector graphic 1 of 1")
                phase_progress = PhaseProgress(work_completed, set_work_label, grow_work_total)
                vector_result = plan_and_apply(
                    vector_plan,
                    TranslationEngine(processing_replacement, source_language, target_language),
                    lambda translate: apply_vector(vector_plan, translate, typeface),
                    phase_progress,
                )
                temporary_destination.write_bytes(vector_result.data)
                result.replaced_native_text_items += vector_result.replaced_text_items
                result.replaced_image_regions += vector_result.replaced_image_regions
                if diagnostics_enabled:
                    append_vector_diagnostics(document_diagnostics, vector_result, None, emf_layout_trace)
                if not vector_result.has_editable_text and not vector_result.has_embedded_bitmaps:
                    result.retained_vector_graphics += 1
                work_completed("Applying vector graphic 1 of 1")
            elif extension == ".pdf":
                if failure_context is not None:
                    failure_context.set_location(
                        stage="pdf_document",
                        container_kind="pdf_document",
                        operation="text_replacement",
                    )
                phase_progress = PhaseProgress(work_completed, set_work_label, grow_work_total)
                pdf_diagnostics = document_diagnostics if diagnostics_enabled else None
                pdf_plan = plan_pdf(
                    source_path,
                    processing_ocr,
                    source_language,
                    target_language,
                    document_text_layout=document_text_layout,
                    progress=phase_progress,
                )
                native_items, image_regions = plan_and_apply(
                    pdf_plan,
                    TranslationEngine(processing_replacement, source_language, target_language),
                    lambda translate: apply_pdf(
                        pdf_plan, translate, typeface, temporary_destination,
                        progress=phase_progress, diagnostics=pdf_diagnostics,
                    ),
                    phase_progress,
                )
                result.replaced_native_text_items += native_items
                result.replaced_image_regions += image_regions
            else:
                phase_progress = PhaseProgress(work_completed, set_work_label, grow_work_total)
                engine = TranslationEngine(processing_replacement, source_language, target_language)
                office_diagnostics = document_diagnostics if diagnostics_enabled else None
                office_result: DocxResult | XlsxResult | PptxResult
                if extension == ".docx":
                    document_plan = plan_docx(
                        source_path.read_bytes(),
                        processing_ocr,
                        source_language,
                        target_language,
                        document_text_layout=document_text_layout,
                        diagnostics=office_diagnostics,
                        progress=phase_progress,
                        nested_progress=display,
                        failure_context=failure_context,
                    )
                    office_result = plan_and_apply(
                        document_plan,
                        engine,
                        lambda translate: apply_docx(
                            document_plan, translate, typeface,
                            progress=phase_progress, failure_context=failure_context,
                            diagnostics=office_diagnostics, nested_progress=display,
                        ),
                        phase_progress,
                    )
                elif extension == ".xlsx":
                    workbook_plan = plan_xlsx(
                        source_path.read_bytes(),
                        processing_ocr,
                        source_language,
                        target_language,
                        document_text_layout=document_text_layout,
                        xlsx_translation_mode=xlsx_translation_mode,
                        diagnostics=office_diagnostics,
                        progress=phase_progress,
                        nested_progress=display,
                        failure_context=failure_context,
                    )
                    office_result = plan_and_apply(
                        workbook_plan,
                        engine,
                        lambda translate: apply_xlsx(
                            workbook_plan, translate, typeface,
                            progress=phase_progress, failure_context=failure_context,
                            diagnostics=office_diagnostics,
                        ),
                        phase_progress,
                    )
                else:
                    presentation_plan = plan_pptx(
                        source_path.read_bytes(),
                        processing_ocr,
                        source_language,
                        target_language,
                        document_text_layout=document_text_layout,
                        diagnostics=office_diagnostics,
                        progress=phase_progress,
                        nested_progress=display,
                        failure_context=failure_context,
                    )
                    office_result = plan_and_apply(
                        presentation_plan,
                        engine,
                        lambda translate: apply_pptx(
                            presentation_plan, translate, typeface,
                            progress=phase_progress, failure_context=failure_context,
                            diagnostics=office_diagnostics,
                        ),
                        phase_progress,
                    )
                temporary_destination.write_bytes(office_result.data)
                native_items = office_result.native_items
                image_regions = office_result.image_regions
                retained_vectors = office_result.retained_vectors
                for media_part, media_vector in office_result.vector_results:
                    if diagnostics_enabled:
                        append_vector_diagnostics(document_diagnostics, media_vector, media_part, emf_layout_trace)
                    if not media_vector.has_editable_text and not media_vector.has_embedded_bitmaps:
                        print(f"Retained vector without editable text: {source_path}", file=sys.stderr)
                result.replaced_native_text_items += native_items
                result.replaced_image_regions += image_regions
                result.retained_vector_graphics += retained_vectors
            os.replace(temporary_destination, destination)
        except (BadZipFile, OSError, RuntimeError, ValueError) as error:
            progress_entry["status"] = "failed"
            progress_entry["details"] = str(error)
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
            continue
        else:
            progress_entry["status"] = "completed"
            progress_entry["progress"] = 100
            reserved_paths.add(destination)
            result.processed_files += 1
        finally:
            cache_scope.__exit__(None, None, None)
            document_seconds = perf_counter() - document_started
            if run_metrics is not None:
                run_metrics.__exit__(None, None, None)
                cache_path = source_path.with_name(f"{source_path.name}{CACHE_FILENAME_SUFFIX}")
                inventory: list[dict[str, object]] | None = None
                if cache_path.is_file():
                    try:
                        inventory = inspect_cache(cache_path)
                    except CacheInspectionError:
                        pass
                _write_document_diagnostic(
                    output_root, source_path, relative_source_path, destination,
                    _diagnostic_options(
                        source_language, target_language, document_text_layout,
                        include_patterns, ocr_provider, text_replacement_provider,
                    ),
                    _document_totals_since(counts_before, result), document_diagnostics, result,
                    run_activity={
                        "document_processing_seconds": document_seconds,
                        "unique_texts": run_metrics.unique_texts,
                        "plan_misses": run_metrics.plan_misses,
                        "providers": run_metrics.report(document_seconds),
                    },
                    cache_inventory=inventory,
                    emf_layout_trace=emf_layout_trace,
                )
            if display is not None:
                display.complete_overall_source(completed_sources)
                display.clear_current()
            elif progress is not None:
                progress.close()
            completed_sources += 1
            if progress_entry["status"] == "completed":
                _set_entry_eta(progress_entry, 0, False)
                progress_entry.pop("details", None)
            else:
                progress_entry.pop("eta_seconds", None)
                progress_entry.pop("eta_status", None)
            update_overall_state()
            publish_progress()
    finally:
        if display is not None:
            display.__exit__(None, None, None)
    return result


def _eta_status(eta_seconds: float | None, estimating: bool) -> str | None:
    """Label an unknown ETA, but only when a progress display is producing estimates."""
    return "Calculating" if estimating and eta_seconds is None else None


def _set_entry_eta(entry: ProgressEntry, eta_seconds: float | None, estimating: bool) -> None:
    entry["eta_seconds"] = eta_seconds
    status = _eta_status(eta_seconds, estimating)
    if status is None:
        entry.pop("eta_status", None)
    else:
        entry["eta_status"] = status


def _write_progress_file(
    output_root: Path,
    progress: int,
    eta_seconds: float | None,
    entries: ProgressEntries,
    eta_status: str | None = None,
) -> None:
    """Atomically publish a complete machine-readable folder-progress snapshot.

    Raises ``ProgressWriteError`` if the file stays unwritable for the retry period.
    """
    progress_path = output_root / "progress.json"
    temporary_path = progress_path.with_name(f".{progress_path.name}.tmp")
    document: dict[str, object] = {"progress": progress, "eta_seconds": eta_seconds}
    if eta_status is not None:
        document["eta_status"] = eta_status
    document["files"] = entries
    content = json.dumps(document, ensure_ascii=False, indent=2) + "\n"

    def publish() -> None:
        temporary_path.write_text(content, encoding="utf-8")
        os.replace(temporary_path, progress_path)

    _retry_progress_write(publish, progress_path)


def _retry_progress_write(
    action: Callable[[], None],
    path: Path,
    *,
    sleep: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] | None = None,
) -> None:
    """Retry a progress write with bounded jittered backoff while the file is locked."""
    sleep = sleep or time.sleep
    monotonic = monotonic or time.monotonic
    started_at = monotonic()
    deadline = started_at + PROGRESS_WRITE_RETRY_SECONDS
    delay_seconds = PROGRESS_WRITE_INITIAL_DELAY_SECONDS
    while True:
        try:
            action()
            return
        except OSError as error:
            current_time = monotonic()
            if current_time >= deadline:
                raise ProgressWriteError(path, current_time - started_at, error) from error
            jittered_delay_seconds = min(
                PROGRESS_WRITE_MAX_DELAY_SECONDS, delay_seconds * random.uniform(0.8, 1.2)
            )
            sleep(min(jittered_delay_seconds, deadline - current_time))
            delay_seconds = min(PROGRESS_WRITE_MAX_DELAY_SECONDS, delay_seconds * 2)


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
    source_path: Path,
    relative_source_path: Path,
    destination: Path | None,
    options: Mapping[str, object],
    totals: Mapping[str, int],
    entries: list[dict[str, object]],
    result: FolderReplacementResult,
    run_activity: dict[str, object] | None = None,
    cache_inventory: list[dict[str, object]] | None = None,
    emf_layout_trace: list[dict[str, object]] | None = None,
) -> None:
    """Write one local JSON sidecar beside a document's intended output path."""
    intended_output = destination or output_root / relative_source_path
    sidecar = intended_output.with_name(f"{intended_output.name}.diagnostics.json")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    output_path = intended_output.relative_to(output_root).as_posix()
    diagnostic: dict[str, object] = {
                "schema_version": 1,
                "source_path": relative_source_path.as_posix(),
                "source_absolute_path": source_path.resolve().as_posix(),
                "output_path": output_path,
                "options": dict(options),
                "totals": dict(totals),
                "entries": entries,
            }
    if run_activity is not None:
        diagnostic["run_activity"] = run_activity
    if cache_inventory is not None:
        diagnostic["cache_inventory"] = cache_inventory
    if emf_layout_trace:
        diagnostic["emf_layout_trace"] = emf_layout_trace
    sidecar.write_text(
        json.dumps(
            diagnostic,
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
    replacement_name = replace_text(
        replacement_provider, source_path.name, is_filename=True,
        source_language=source_language, target_language=target_language,
    ).text
    _validate_filename(replacement_name)
    if Path(replacement_name).suffix.lower() != source_path.suffix.lower():
        replacement_name = f"{replacement_name}{source_path.suffix}"
    replacement_name = _windows_safe_filename(replacement_name, source_path)
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
    if not name or name in {".", ".."} or "\x00" in name or "/" in name or "\\" in name:
        raise ValueError(f"Text-replacement provider returned an unsafe filename: {name!r}")


def _windows_safe_filename(name: str, source_path: Path) -> str:
    """Make a translated name valid on Windows, changing only the stem (FR-2026-10-27-01)."""
    suffix = Path(name).suffix
    stem = name[: len(name) - len(suffix)] if suffix else name
    stem = _INVALID_FILENAME_CHARACTERS.sub("-", stem)
    stem = _WHITESPACE_RUN.sub(" ", stem).lstrip(" ").rstrip(" .")
    if not stem:
        stem = source_path.stem
    elif stem.upper() in _RESERVED_DEVICE_NAMES:
        stem = f"_{stem}"
    return f"{stem}{suffix}"


_INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"|?*\x00-\x1f]+')
_WHITESPACE_RUN = re.compile(r"\s+")
_RESERVED_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)


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
    if extension in BITMAP_EXTENSIONS or extension in VECTOR_EXTENSIONS:
        return 2
    if extension == ".docx":
        with ZipFile(source_path) as archive:
            return 2 * docx_work_item_total(archive.namelist())
    if extension in OFFICE_DOCUMENT_EXTENSIONS:
        if extension == ".xlsx":
            with ZipFile(source_path) as archive:
                return 2 * xlsx_work_item_total(
                    archive.namelist(), document_text_layout, xlsx_translation_mode
                )
        with ZipFile(source_path) as archive:
            return 2 * pptx_work_item_total(archive.namelist())
    return pdf_work_total(source_path)


def _make_progress_bar(total: int, label: str) -> ProgressReporter:
    """Create the standard terminal bar for one source file."""
    raise RuntimeError("A Rich live display is required when no test progress factory is supplied.")


def _replace_native_text(
    text: str,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
) -> str:
    return replace_text(
        replacement_provider, text, is_filename=False,
        source_language=source_language, target_language=target_language,
    ).text
