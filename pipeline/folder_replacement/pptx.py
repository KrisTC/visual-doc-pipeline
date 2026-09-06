"""PPTX-specific native text replacement."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from copy import deepcopy
from dataclasses import dataclass, replace
import os
from pathlib import Path
import posixpath
from typing import Protocol, cast
import xml.etree.ElementTree as ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.oxml import parse_xml
from pptx.oxml.ns import qn
from pptx.shapes.base import BaseShape
from pptx.shapes.graphfrm import GraphicFrame
from pptx.shapes.group import GroupShape
from pptx.table import Table, _Cell
from pptx.text.text import TextFrame, _Paragraph, _Run
from pptx.util import Emu, Length
# skia-python does not publish PEP 561 stubs; this is the native rendering boundary.
import skia  # type: ignore[import-not-found]

from pipeline.bounded_text_layout import (
    BoundedTextBox,
    BoundedTextParagraph,
    BoundedTextRun,
    DEFAULT_FONT_SIZE_POINTS,
    EMU_PER_PIXEL,
    FittedTextBox,
    SourceTypefaceReference,
    fitted_text_lines,
    noto_typefaces,
    replace_and_fit_text_box,
    source_occupied_text_box,
    trim_trailing_empty_paragraphs,
)
from pipeline.pptx_theme_fonts import PptxThemeFonts, pptx_themes_by_slide, resolve_theme_typefaces
from pipeline.ocr import OcrProvider
from pipeline.ocr.image_preparation import RgbColour
from pipeline.folder_replacement.office_xml import (
    replace_drawing_diagram_xml_text,
    replace_office_xml_text,
)
from pipeline.folder_replacement.failure_diagnostics import FailureContext
from pipeline.folder_replacement.common import NestedProgressReporter
from pipeline.text_replacement import TextReplacementProvider, TextReplacementRequest


_DRAWING_NAMESPACE = "http://schemas.openxmlformats.org/drawingml/2006/main"
_PARAGRAPH_PROPERTY_CHILD_ORDER = (
    "lnSpc",
    "spcBef",
    "spcAft",
    "buClrTx",
    "buClr",
    "buSzTx",
    "buSzPct",
    "buSzPts",
    "buFontTx",
    "buFont",
    "buNone",
    "buAutoNum",
    "buChar",
    "buBlip",
    "tabLst",
    "defRPr",
    "extLst",
)
_RUN_PROPERTY_CHILD_ORDER = (
    "noFill",
    "solidFill",
    "gradFill",
    "blipFill",
    "pattFill",
    "grpFill",
    "ln",
    "effectLst",
    "effectDag",
    "highlight",
    "uLnTx",
    "uLn",
    "uFillTx",
    "uFill",
    "latin",
    "ea",
    "cs",
    "sym",
    "hlinkClick",
    "hlinkMouseOver",
    "rtl",
    "extLst",
)
_OOXML_MINIMUM_FONT_SIZE_CENTIPOINTS = 100
_OOXML_MAXIMUM_FONT_SIZE_CENTIPOINTS = 400_000
_RELATIONSHIPS_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"
_PRESENTATION_NAMESPACE = "http://schemas.openxmlformats.org/presentationml/2006/main"


def replace_pptx_file(
    source: Path,
    destination: Path,
    ocr: OcrProvider,
    replacement: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typeface: skia.Typeface,
    completed: Callable[[str], None],
    document_text_layout: str = "preserve-source-formatting",
    failure_context: FailureContext | None = None,
    nested_progress: NestedProgressReporter | None = None,
    diagnostics: list[dict[str, object]] | None = None,
) -> tuple[int, int, int]:
    """Replace PPTX content, optionally fitting bounded slide text frames."""
    from pipeline.folder_replacement.processor import _replace_office_file

    if failure_context is not None:
        failure_context.set_location(
            stage="pptx_package_analysis",
            container_kind="pptx_document",
            operation="read",
        )
    smartart_parts, smartart_data_parts = _reachable_smartart_parts(source)
    ocr_backgrounds = _pptx_ocr_backgrounds(source)
    if document_text_layout == "preserve-source-formatting":
        native_items, image_regions, retained_vectors = _replace_office_file(
            source,
            destination,
            ocr,
            replacement,
            source_language,
            target_language,
            typeface,
            completed,
            document_text_layout=document_text_layout,
            skip_native_xml_part=smartart_parts.__contains__,
            ocr_backgrounds=ocr_backgrounds,
            failure_context=failure_context,
            nested_progress=nested_progress,
            diagnostics=diagnostics,
        )
        native_items += _replace_smartart_data_parts(
            destination,
            smartart_data_parts,
            replacement,
            source_language,
            target_language,
            failure_context,
        )
        return native_items, image_regions, retained_vectors
    if document_text_layout not in {
        "preserve-basic-layout",
        "preserve-basic-layout-source-font",
    }:
        raise ValueError(f"Unsupported document text layout mode: {document_text_layout!r}")
    preserve_source_font_family = document_text_layout == "preserve-basic-layout-source-font"
    slide_themes = pptx_themes_by_slide(source) if preserve_source_font_family else ()

    # Preserve the established embedded bitmap and vector paths before python-pptx
    # rewrites supported slide text frames.
    native_items, image_regions, retained_vectors = _replace_office_file(
        source,
        destination,
        ocr,
        replacement,
        source_language,
        target_language,
        typeface,
        completed,
        document_text_layout=document_text_layout,
        replace_native_xml=False,
        ocr_backgrounds=ocr_backgrounds,
        failure_context=failure_context,
        nested_progress=nested_progress,
        diagnostics=diagnostics,
    )
    native_items += _replace_smartart_data_parts(
        destination,
        smartart_data_parts,
        replacement,
        source_language,
        target_language,
        failure_context,
    )
    if failure_context is not None:
        failure_context.set_location(
            stage="pptx_fitted_layout_read",
            container_kind="pptx_document",
            operation="read",
        )
    presentation = Presentation(str(destination))
    layout_typefaces = noto_typefaces()
    for slide_index, slide in enumerate(presentation.slides):
        if failure_context is not None:
            failure_context.set_location(
                stage="pptx_fitted_layout",
                container_kind="pptx_slide",
                operation="text_replacement",
                package_part=f"ppt/slides/slide{slide_index + 1}.xml",
                item_index=slide_index + 1,
            )
        native_items += _replace_slide_text_frames(
            slide.shapes,
            slide.slide_layout,
            replacement,
            source_language,
            target_language,
            layout_typefaces,
            preserve_source_font_family,
            slide_themes[slide_index] if slide_index < len(slide_themes) else None,
            slide_index,
            diagnostics,
        )
    if failure_context is not None:
        failure_context.set_location(
            stage="pptx_fitted_layout_write",
            container_kind="pptx_document",
            operation="write",
        )
    presentation.save(str(destination))
    if diagnostics is not None:
        _refresh_written_table_fit_diagnostics(destination, diagnostics)
    native_items += _replace_speaker_note_parts(
        destination,
        replacement,
        source_language,
        target_language,
        failure_context,
    )
    completed("native text layout")
    return native_items, image_regions, retained_vectors


def _pptx_ocr_backgrounds(source: Path) -> dict[str, RgbColour]:
    """Return unambiguous direct solid slide backgrounds for embedded images."""
    with ZipFile(source) as archive:
        parts = frozenset(archive.namelist())
        candidates: dict[str, set[RgbColour]] = {}
        unknown_backgrounds: set[str] = set()
        for slide_part in parts:
            if not _is_slide_part(slide_part):
                continue
            image_parts = _slide_image_parts(archive, parts, slide_part)
            if not image_parts:
                continue
            background = _slide_background_colour(archive, slide_part)
            if background is None:
                unknown_backgrounds.update(image_parts)
                continue
            for image_part in image_parts:
                candidates.setdefault(image_part, set()).add(background)
    return {
        image_part: next(iter(backgrounds))
        for image_part, backgrounds in candidates.items()
        if len(backgrounds) == 1 and image_part not in unknown_backgrounds
    }


def _is_slide_part(part_name: str) -> bool:
    parent, name = posixpath.split(part_name)
    return parent == "ppt/slides" and name.startswith("slide") and name.endswith(".xml")


def _slide_image_parts(archive: ZipFile, parts: frozenset[str], slide_part: str) -> set[str]:
    relationships_part = _relationships_part_name(slide_part)
    if relationships_part not in parts:
        return set()
    try:
        relationships = ElementTree.fromstring(archive.read(relationships_part))
    except ElementTree.ParseError:
        return set()
    image_parts: set[str] = set()
    for relationship in relationships:
        if relationship.tag != f"{{{_RELATIONSHIPS_NAMESPACE}}}Relationship":
            continue
        if relationship.get("TargetMode") == "External" or not (relationship.get("Type") or "").endswith("/image"):
            continue
        target = relationship.get("Target")
        image_part = None if target is None else _relationship_target_part_name(slide_part, target)
        if image_part is not None and image_part in parts:
            image_parts.add(image_part)
    return image_parts


def _slide_background_colour(archive: ZipFile, slide_part: str) -> RgbColour | None:
    try:
        slide = ElementTree.fromstring(archive.read(slide_part))
    except ElementTree.ParseError:
        return None
    background = slide.find(
        f"{{{_PRESENTATION_NAMESPACE}}}cSld/{{{_PRESENTATION_NAMESPACE}}}bg/"
        f"{{{_PRESENTATION_NAMESPACE}}}bgPr/{{{_DRAWING_NAMESPACE}}}solidFill/"
        f"{{{_DRAWING_NAMESPACE}}}srgbClr"
    )
    if background is None:
        return None
    value = background.get("val")
    if value is None or len(value) != 6:
        return None
    try:
        red = int(value[0:2], 16)
        green = int(value[2:4], 16)
        blue = int(value[4:6], 16)
    except ValueError:
        return None
    return red, green, blue


def _reachable_smartart_parts(source: Path) -> tuple[frozenset[str], frozenset[str]]:
    """Find reachable SmartArt package parts and their canonical data parts."""
    with ZipFile(source) as archive:
        archive_parts = frozenset(archive.namelist())
        pending: list[str | None] = [None]
        visited: set[str | None] = set()
        reachable: set[str] = set()
        data_parts: set[str] = set()
        while pending:
            source_part = pending.pop()
            if source_part in visited:
                continue
            visited.add(source_part)
            relationships_part = _relationships_part_name(source_part)
            if relationships_part not in archive_parts:
                continue
            try:
                relationships = ElementTree.fromstring(archive.read(relationships_part))
            except ElementTree.ParseError:
                continue
            for relationship in relationships:
                if relationship.tag != f"{{{_RELATIONSHIPS_NAMESPACE}}}Relationship":
                    continue
                if relationship.get("TargetMode") == "External":
                    continue
                target = relationship.get("Target")
                if target is None:
                    continue
                target_part = _relationship_target_part_name(source_part, target)
                if target_part is None or target_part not in archive_parts:
                    continue
                reachable.add(target_part)
                pending.append(target_part)
                if (relationship.get("Type") or "").endswith("/diagramData"):
                    data_parts.add(target_part)

    smartart_parts = {
        part for part in reachable if part.startswith("ppt/diagrams/")
    } | data_parts
    return frozenset(smartart_parts), frozenset(data_parts)


def _relationships_part_name(source_part: str | None) -> str:
    if source_part is None:
        return "_rels/.rels"
    parent, basename = posixpath.split(source_part)
    return posixpath.join(parent, "_rels", f"{basename}.rels")


def _relationship_target_part_name(source_part: str | None, target: str) -> str | None:
    base = "" if source_part is None else posixpath.dirname(source_part)
    candidate = target.lstrip("/") if target.startswith("/") else posixpath.join(base, target)
    normalized = posixpath.normpath(candidate)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        return None
    return normalized


def _replace_smartart_data_parts(
    presentation_path: Path,
    data_parts: frozenset[str],
    replacement: TextReplacementProvider,
    source_language: str,
    target_language: str,
    failure_context: FailureContext | None = None,
) -> int:
    """Replace only canonical SmartArt labels, not generated diagram drawings."""
    if not data_parts:
        return 0
    if failure_context is not None:
        failure_context.set_location(
            stage="pptx_smartart_read",
            container_kind="pptx_document",
            operation="read",
        )
    temporary_path = presentation_path.with_name(f".{presentation_path.name}.smartart.tmp")
    replaced_items = 0
    try:
        with (
            ZipFile(presentation_path) as source_archive,
            ZipFile(temporary_path, "w", ZIP_DEFLATED) as destination_archive,
        ):
            for entry in source_archive.infolist():
                if failure_context is not None:
                    failure_context.set_location(
                        stage="pptx_smartart_read",
                        container_kind="pptx_package_part",
                        operation="read",
                        package_part=entry.filename,
                    )
                data = source_archive.read(entry.filename)
                if entry.filename in data_parts:
                    if failure_context is not None:
                        failure_context.set_location(
                            stage="pptx_smartart",
                            container_kind="pptx_smartart_data",
                            operation="text_replacement",
                            package_part=entry.filename,
                        )
                    data, replaced = replace_drawing_diagram_xml_text(
                        data,
                        replacement,
                        source_language,
                        target_language,
                    )
                    replaced_items += replaced
                if failure_context is not None:
                    failure_context.set_location(
                        stage="pptx_smartart_write",
                        container_kind="pptx_package_part",
                        operation="write",
                        package_part=entry.filename,
                    )
                destination_archive.writestr(entry, data)
        os.replace(temporary_path, presentation_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return replaced_items


def _replace_speaker_note_parts(
    presentation_path: Path,
    replacement: TextReplacementProvider,
    source_language: str,
    target_language: str,
    failure_context: FailureContext | None = None,
) -> int:
    """Directly replace editable text in PPTX speaker-note slide parts."""
    if failure_context is not None:
        failure_context.set_location(
            stage="pptx_notes_read",
            container_kind="pptx_document",
            operation="read",
        )
    with ZipFile(presentation_path) as archive:
        note_parts = frozenset(
            entry.filename for entry in archive.infolist() if _is_speaker_note_part(entry.filename)
        )
    if not note_parts:
        return 0

    temporary_path = presentation_path.with_name(f".{presentation_path.name}.notes.tmp")
    replaced_items = 0
    try:
        with (
            ZipFile(presentation_path) as source_archive,
            ZipFile(temporary_path, "w", ZIP_DEFLATED) as destination_archive,
        ):
            for entry in source_archive.infolist():
                if failure_context is not None:
                    failure_context.set_location(
                        stage="pptx_notes_read",
                        container_kind="pptx_package_part",
                        operation="read",
                        package_part=entry.filename,
                    )
                data = source_archive.read(entry.filename)
                if entry.filename in note_parts:
                    if failure_context is not None:
                        failure_context.set_location(
                            stage="pptx_speaker_notes",
                            container_kind="pptx_speaker_notes",
                            operation="text_replacement",
                            package_part=entry.filename,
                        )
                    data, replaced = replace_office_xml_text(
                        data, replacement, source_language, target_language
                    )
                    replaced_items += replaced
                if failure_context is not None:
                    failure_context.set_location(
                        stage="pptx_notes_write",
                        container_kind="pptx_package_part",
                        operation="write",
                        package_part=entry.filename,
                    )
                destination_archive.writestr(entry, data)
        os.replace(temporary_path, presentation_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return replaced_items


def _is_speaker_note_part(part_name: str) -> bool:
    """Return whether an OOXML part is a PowerPoint speaker-note slide XML part."""
    parent, name = posixpath.split(part_name)
    return parent == "ppt/notesSlides" and name.startswith("notesSlide") and name.endswith(".xml")


def _replace_slide_text_frames(
    shapes: Iterable[BaseShape],
    slide_layout: object,
    replacement: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typefaces: dict[str, skia.Typeface],
    preserve_source_font_family: bool,
    theme: PptxThemeFonts | None,
    slide_index: int,
    diagnostics: list[dict[str, object]] | None,
) -> int:
    replaced = 0
    for shape_index, shape in enumerate(shapes):
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            replaced += _replace_slide_text_frames(
                cast(GroupShape, shape).shapes,
                slide_layout,
                replacement,
                source_language,
                target_language,
                typefaces,
                preserve_source_font_family,
                theme,
                slide_index,
                diagnostics,
            )
            continue
        if shape.shape_type == MSO_SHAPE_TYPE.TABLE:
            replaced += _replace_table_cells(
                cast(GraphicFrame, shape),
                replacement,
                source_language,
                target_language,
                typefaces,
                preserve_source_font_family,
                theme,
                slide_index,
                shape_index,
                diagnostics,
            )
            continue
        if not shape.has_text_frame:
            continue
        text_shape = cast(_TextShape, shape)
        if not _has_text(text_shape):
            continue
        raw_text_box = _text_box(
            text_shape, slide_layout, theme if preserve_source_font_family else None
        )
        text_box = trim_trailing_empty_paragraphs(raw_text_box)
        _trim_trailing_empty_text_frame(text_shape.text_frame)
        fit_box = (
            source_occupied_text_box(
                text_box, typefaces, measure_source_fonts=preserve_source_font_family
            )
            if _has_explicit_no_autofit(text_shape.text_frame)
            else text_box
        )
        fitted = replace_and_fit_text_box(
            fit_box,
            replacement,
            source_language,
            target_language,
            typefaces,
            preserve_source_font_family=preserve_source_font_family,
            measure_source_fonts=preserve_source_font_family,
        )
        _write_explicit_text_frame(text_shape.text_frame, fitted.text_box)
        replaced += sum(
            1
            for paragraph in text_box.paragraphs
            if "".join(run.text for run in paragraph.runs).strip()
        )
    return replaced


@dataclass(frozen=True, slots=True)
class _TableGeometry:
    """The table dimensions that fitted replacement must retain exactly."""

    frame: tuple[int, int, int, int]
    column_widths: tuple[int, ...]
    row_heights: tuple[int, ...]
    merge_origin_count: int


@dataclass(frozen=True, slots=True)
class _TableCellFit:
    """One replacement prepared before selecting the table-wide scale."""

    cell: _Cell
    row_index: int
    column_index: int
    row_span: int
    column_span: int
    text_box: BoundedTextBox
    fitted: FittedTextBox


def _replace_table_cells(
    table_shape: GraphicFrame,
    replacement: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typefaces: dict[str, skia.Typeface],
    preserve_source_font_family: bool,
    theme: PptxThemeFonts | None,
    slide_index: int,
    shape_index: int,
    diagnostics: list[dict[str, object]] | None,
) -> int:
    """Replace one table using a shared scale calculated before cells are written."""
    table = table_shape.table
    captured_geometry = _table_geometry(table_shape, table)
    replaced = 0
    participants: list[_TableCellFit] = []
    fallback_cells: list[tuple[int, int]] = []
    for row_index, row in enumerate(table.rows):
        for column_index in range(len(table.columns)):
            cell = table.cell(row_index, column_index)
            if cell.is_spanned:
                continue
            width = _table_cell_width(table, cell, column_index)
            if width is None:
                fallback_replaced = _replace_text_frame_source_formatting(
                    cell.text_frame, replacement, source_language, target_language
                )
                replaced += fallback_replaced
                if fallback_replaced:
                    fallback_cells.append((row_index, column_index))
                continue
            text_box = _table_cell_text_box(
                cell,
                width,
                max(1, captured_geometry.frame[3]),
                theme if preserve_source_font_family else None,
            )
            if not _has_non_whitespace_text(text_box):
                continue
            fitted = replace_and_fit_text_box(
                text_box,
                replacement,
                source_language,
                target_language,
                typefaces,
                preserve_source_font_family=preserve_source_font_family,
                measure_source_fonts=preserve_source_font_family,
            )
            participants.append(
                _TableCellFit(
                    cell,
                    row_index,
                    column_index,
                    cell.span_height if cell.is_merge_origin else 1,
                    cell.span_width if cell.is_merge_origin else 1,
                    text_box,
                    fitted,
                )
            )
    common_scale, common_status, allocated_row_heights, row_allocation_strategy = _table_common_scale(
        participants,
        captured_geometry.row_heights,
        captured_geometry.frame[3],
    )
    limiting_cells = _table_limiting_cells(participants, common_scale, allocated_row_heights)
    for participant in participants:
        _write_explicit_text_frame(
            participant.cell.text_frame,
            _scale_fitted_text_box(participant.fitted.text_box, common_scale / participant.fitted.font_scale),
            write_text_frame_geometry=False,
        )
        replaced += sum(
            1
            for paragraph in participant.text_box.paragraphs
            if "".join(run.text for run in paragraph.runs).strip()
        )
    _write_table_geometry(table_shape, table, captured_geometry, allocated_row_heights)
    if diagnostics is not None:
        diagnostics.append(
            _table_fit_diagnostic(
                slide_index,
                shape_index,
                captured_geometry,
                _table_geometry(table_shape, table),
                participants,
                fallback_cells,
                common_scale,
                common_status,
                limiting_cells,
                row_allocation_strategy,
            )
        )
    return replaced


def _table_geometry(table_shape: GraphicFrame, table: Table) -> _TableGeometry:
    """Return the mutable table geometry as plain values suitable for diagnostics."""
    return _TableGeometry(
        (int(table_shape.left), int(table_shape.top), int(table_shape.width), int(table_shape.height)),
        tuple(int(table.columns[index].width) for index in range(len(table.columns))),
        tuple(int(table.rows[index].height) for index in range(len(table.rows))),
        sum(
            1
            for row_index in range(len(table.rows))
            for column_index in range(len(table.columns))
            if table.cell(row_index, column_index).is_merge_origin
        ),
    )


def _write_table_geometry(
    table_shape: GraphicFrame,
    table: Table,
    geometry: _TableGeometry,
    row_heights: tuple[int, ...],
) -> None:
    """Write the fixed frame and its selected readable row allocation."""
    for index, width in enumerate(geometry.column_widths):
        table.columns[index].width = Emu(width)
    for index, height in enumerate(row_heights):
        table.rows[index].height = Emu(height)
    left, top, width, height = geometry.frame
    table_shape.left = Emu(left)
    table_shape.top = Emu(top)
    table_shape.width = Emu(width)
    table_shape.height = Emu(height)


def _table_common_scale(
    participants: list[_TableCellFit], source_row_heights: tuple[int, ...], frame_height: int
) -> tuple[float, str, tuple[int, ...], str]:
    """Maximise the common scale while allocating rows inside the fixed frame."""
    if _source_rows_are_consistent(source_row_heights, frame_height):
        scale, status = _fixed_row_common_scale(participants, source_row_heights)
        return scale, status, source_row_heights, "source_rows"
    if not participants:
        empty_rows = [0] * len(source_row_heights)
        _distribute_height(
            empty_rows,
            tuple(range(len(empty_rows))),
            frame_height,
            source_row_heights,
        )
        return 1.0, "fit", tuple(empty_rows), "frame_allocation"
    minimum_scale = max(_minimum_writable_scale(participant.fitted) for participant in participants)
    full_size_rows = _allocate_table_rows(participants, source_row_heights, frame_height, 1.0)
    if full_size_rows is not None:
        return 1.0, "fit", full_size_rows, "frame_allocation"
    minimum_rows = _allocate_table_rows(
        participants, source_row_heights, frame_height, minimum_scale
    )
    if minimum_rows is None:
        return (
            minimum_scale,
            "overflow",
            _overflow_table_rows(participants, source_row_heights, frame_height, minimum_scale),
            "frame_allocation",
        )
    fitting_scale = minimum_scale
    non_fitting_scale = 1.0
    fitting_rows = minimum_rows
    for _ in range(16):
        candidate = (fitting_scale + non_fitting_scale) / 2.0
        candidate_rows = _allocate_table_rows(
            participants, source_row_heights, frame_height, candidate
        )
        if candidate_rows is None:
            non_fitting_scale = candidate
        else:
            fitting_scale = candidate
            fitting_rows = candidate_rows
    return fitting_scale, "fit", fitting_rows, "frame_allocation"


def _source_rows_are_consistent(source_row_heights: tuple[int, ...], frame_height: int) -> bool:
    """Recognise a well-formed table grid that PowerPoint already renders stably."""
    return (
        bool(source_row_heights)
        and all(height > 0 for height in source_row_heights)
        and abs(sum(source_row_heights) - frame_height) <= max(1, frame_height // 100)
    )


def _fixed_row_common_scale(
    participants: list[_TableCellFit], row_heights: tuple[int, ...]
) -> tuple[float, str]:
    """Fit against an already well-formed source grid without redistributing rows."""
    if not participants or _table_fits_rows(participants, row_heights, 1.0):
        return 1.0, "fit"
    minimum_scale = max(_minimum_writable_scale(participant.fitted) for participant in participants)
    if not _table_fits_rows(participants, row_heights, minimum_scale):
        return minimum_scale, "overflow"
    fitting_scale = minimum_scale
    non_fitting_scale = 1.0
    for _ in range(16):
        candidate = (fitting_scale + non_fitting_scale) / 2.0
        if _table_fits_rows(participants, row_heights, candidate):
            fitting_scale = candidate
        else:
            non_fitting_scale = candidate
    return fitting_scale, "fit"


def _table_fits_rows(
    participants: list[_TableCellFit], row_heights: tuple[int, ...], scale: float
) -> bool:
    """Return whether fixed rows provide every translated cell's natural height."""
    return all(
        _table_cell_fits_width(participant, scale)
        and _table_cell_required_height(participant, scale)
        <= sum(row_heights[participant.row_index : participant.row_index + participant.row_span])
        for participant in participants
    )


def _allocate_table_rows(
    participants: list[_TableCellFit],
    source_row_heights: tuple[int, ...],
    frame_height: int,
    scale: float = 1.0,
) -> tuple[int, ...] | None:
    """Return the smallest fitting rows plus proportionally distributed spare height."""
    required_rows = [0] * len(source_row_heights)
    spanning: list[tuple[_TableCellFit, int]] = []
    for participant in participants:
        if not _table_cell_fits_width(participant, scale):
            return None
        required_height = _table_cell_required_height(participant, scale)
        if participant.row_span == 1:
            required_rows[participant.row_index] = max(
                required_rows[participant.row_index], required_height
            )
        else:
            spanning.append((participant, required_height))
    for _ in range(len(spanning) + 1):
        changed = False
        for participant, required_height in spanning:
            start = participant.row_index
            end = start + participant.row_span
            deficit = required_height - sum(required_rows[start:end])
            if deficit <= 0:
                continue
            _distribute_height(required_rows, tuple(range(start, end)), deficit)
            changed = True
        if not changed:
            break
    required_total = sum(required_rows)
    if required_total > frame_height:
        return None
    _distribute_height(
        required_rows,
        tuple(range(len(required_rows))),
        frame_height - required_total,
        source_row_heights,
    )
    return tuple(required_rows)


def _overflow_table_rows(
    participants: list[_TableCellFit],
    source_row_heights: tuple[int, ...],
    frame_height: int,
    scale: float,
) -> tuple[int, ...]:
    """Keep the fixed frame when even the valid common minimum cannot fit."""
    required_rows = [0] * len(source_row_heights)
    for participant in participants:
        required_height = _table_cell_required_height(participant, scale)
        indexes = tuple(range(participant.row_index, participant.row_index + participant.row_span))
        _distribute_height(required_rows, indexes, required_height)
    required_total = sum(required_rows)
    if required_total <= frame_height:
        _distribute_height(
            required_rows,
            tuple(range(len(required_rows))),
            frame_height - required_total,
            source_row_heights,
        )
        return tuple(required_rows)
    return _proportional_heights(required_rows, frame_height)


def _table_cell_required_height(participant: _TableCellFit, scale: float) -> int:
    """Measure the natural padded height for an already translated cell at ``scale``."""
    scaled = _scale_fitted_text_box(
        participant.fitted.text_box, scale / participant.fitted.font_scale
    )
    natural = source_occupied_text_box(scaled, participant.fitted.layout_typefaces)
    return max(1, int(natural.height_emu))


def _table_cell_fits_width(participant: _TableCellFit, scale: float) -> bool:
    """Reject a scale whose wrapped layout still exceeds the cell's fixed width."""
    scaled = _scale_fitted_text_box(
        participant.fitted.text_box, scale / participant.fitted.font_scale
    )
    fitted = replace(participant.fitted, text_box=scaled, font_scale=scale)
    content_width = (
        scaled.width_emu - scaled.margin_left_emu - scaled.margin_right_emu
    ) / EMU_PER_PIXEL
    return all(line.width_pixels <= content_width for line in fitted_text_lines(fitted))


def _distribute_height(
    heights: list[int], indexes: tuple[int, ...], amount: int, weights: tuple[int, ...] | None = None
) -> None:
    """Distribute whole EMUs deterministically, favouring source row proportions."""
    if amount <= 0 or not indexes:
        return
    selected_weights = (
        tuple(max(0, weights[index]) for index in indexes)
        if weights is not None
        else tuple(1 for _ in indexes)
    )
    if not any(selected_weights):
        selected_weights = tuple(1 for _ in indexes)
    total_weight = sum(selected_weights)
    additions = [amount * weight // total_weight for weight in selected_weights]
    for index, addition in zip(indexes, additions, strict=True):
        heights[index] += addition
    remainder = amount - sum(additions)
    for index in indexes[:remainder]:
        heights[index] += 1


def _proportional_heights(heights: list[int], total: int) -> tuple[int, ...]:
    """Compress required rows to the fixed frame for a known overflow outcome."""
    source_total = sum(heights)
    if source_total <= 0:
        return tuple(0 for _ in heights)
    result = [total * height // source_total for height in heights]
    for index in range(total - sum(result)):
        result[index % len(result)] += 1
    return tuple(result)


def _table_limiting_cells(
    participants: list[_TableCellFit], common_scale: float, row_heights: tuple[int, ...]
) -> list[tuple[int, int]]:
    """Identify cells whose allocated row span leaves no height for a larger scale."""
    limiting: list[tuple[int, int]] = []
    for participant in participants:
        allocated = sum(
            row_heights[participant.row_index : participant.row_index + participant.row_span]
        )
        required = _table_cell_required_height(participant, common_scale)
        if allocated <= required + 1:
            limiting.append((participant.row_index, participant.column_index))
    return limiting


def _minimum_writable_scale(fitted: FittedTextBox) -> float:
    """Keep every explicitly written run at or above DrawingML's one-point minimum."""
    if fitted.font_scale <= 0.0:
        return 1.0
    unscaled_sizes = [
        (run.font_size_points or DEFAULT_FONT_SIZE_POINTS) / fitted.font_scale
        for paragraph in fitted.text_box.paragraphs
        for run in paragraph.runs
    ]
    unscaled_sizes.extend(
        (paragraph.empty_line_font_size_points or DEFAULT_FONT_SIZE_POINTS) / fitted.font_scale
        for paragraph in fitted.text_box.paragraphs
        if not paragraph.runs
    )
    return max((1.0 / size for size in unscaled_sizes if size > 0.0), default=1.0)


def _table_cell_fit_status(fitted: FittedTextBox, common_scale: float) -> str:
    """Classify a cell at the selected common scale using its monotonic fit result."""
    return (
        "fit"
        if fitted.fit_status == "fit" and common_scale <= fitted.font_scale
        else "overflow"
    )


def _is_table_limiting_cell(fitted: FittedTextBox, common_scale: float) -> bool:
    """Return whether this cell fixes the maximum common scale or overflows it."""
    return (
        fitted.fit_status == "overflow"
        or fitted.font_scale <= common_scale + 1e-9
    )


def _scale_fitted_text_box(text_box: BoundedTextBox, factor: float) -> BoundedTextBox:
    """Rescale already-selected output faces without replacing or resolving text again."""
    return replace(
        text_box,
        paragraphs=tuple(
            replace(
                paragraph,
                runs=tuple(
                    replace(
                        run,
                        font_size_points=(run.font_size_points or DEFAULT_FONT_SIZE_POINTS) * factor,
                    )
                    for run in paragraph.runs
                ),
                empty_line_font_size_points=(
                    (paragraph.empty_line_font_size_points or DEFAULT_FONT_SIZE_POINTS) * factor
                ),
            )
            for paragraph in text_box.paragraphs
        ),
    )


def _table_fit_diagnostic(
    slide_index: int,
    shape_index: int,
    captured_geometry: _TableGeometry,
    written_geometry: _TableGeometry,
    participants: list[_TableCellFit],
    fallback_cells: list[tuple[int, int]],
    common_scale: float,
    common_status: str,
    limiting_cells: list[tuple[int, int]],
    row_allocation_strategy: str,
) -> dict[str, object]:
    """Build a text-free local diagnostic for one table-wide fitting decision."""
    return {
        "kind": "table_fit",
        "slide_index": slide_index,
        "shape_index": shape_index,
        "input_geometry": _table_geometry_diagnostic(captured_geometry),
        "written_geometry": _table_geometry_diagnostic(written_geometry),
        "geometry_preserved": captured_geometry == written_geometry,
        "table_frame_preserved": captured_geometry.frame == written_geometry.frame,
        "row_height_frame_mismatch": sum(captured_geometry.row_heights)
        != captured_geometry.frame[3],
        "row_allocation_strategy": row_allocation_strategy,
        "allocated_row_heights": list(written_geometry.row_heights),
        "allocated_row_height_total": sum(written_geometry.row_heights),
        "merge_origin_count": captured_geometry.merge_origin_count,
        "eligible_cell_count": len(participants),
        "common_scale": common_scale,
        "fit_status": common_status,
        "limiting_cells": [_table_cell_location(row, column) for row, column in limiting_cells],
        "fallback_cells": [_table_cell_location(row, column) for row, column in fallback_cells],
        "cells": [
            {
                **_table_cell_location(participant.row_index, participant.column_index),
                "row_span": participant.row_span,
                "column_span": participant.column_span,
                "padded_bounds": {
                    "width": participant.text_box.width_emu,
                    "height": sum(
                        written_geometry.row_heights[
                            participant.row_index : participant.row_index + participant.row_span
                        ]
                    ),
                    "margin_left": participant.text_box.margin_left_emu,
                    "margin_top": participant.text_box.margin_top_emu,
                    "margin_right": participant.text_box.margin_right_emu,
                    "margin_bottom": participant.text_box.margin_bottom_emu,
                },
                "source_font_sizes": _source_font_sizes(participant.text_box),
                "independent_fit_scale": participant.fitted.font_scale,
                "independent_fit_status": participant.fitted.fit_status,
                "fit_status": _table_cell_fit_status(participant.fitted, common_scale),
            }
            for participant in participants
        ],
    }


def _refresh_written_table_fit_diagnostics(
    presentation_path: Path, diagnostics: list[dict[str, object]]
) -> None:
    """Read written table dimensions back from the saved package for debug output."""
    presentation = Presentation(str(presentation_path))
    for diagnostic in diagnostics:
        if diagnostic.get("kind") != "table_fit":
            continue
        slide_index = diagnostic.get("slide_index")
        shape_index = diagnostic.get("shape_index")
        if not isinstance(slide_index, int) or not isinstance(shape_index, int):
            continue
        if slide_index < 0 or slide_index >= len(presentation.slides):
            continue
        shapes = presentation.slides[slide_index].shapes
        if shape_index < 0 or shape_index >= len(shapes):
            continue
        shape = shapes[shape_index]
        if not shape.has_table:
            continue
        written_geometry = _table_geometry(cast(GraphicFrame, shape), cast(GraphicFrame, shape).table)
        written_geometry_diagnostic = _table_geometry_diagnostic(written_geometry)
        diagnostic["written_geometry"] = written_geometry_diagnostic
        diagnostic["geometry_preserved"] = diagnostic.get("input_geometry") == written_geometry_diagnostic
        input_geometry = diagnostic.get("input_geometry")
        if isinstance(input_geometry, dict):
            frame = input_geometry.get("frame")
            diagnostic["table_frame_preserved"] = frame == written_geometry_diagnostic["frame"]
        diagnostic["allocated_row_heights"] = list(written_geometry.row_heights)
        diagnostic["allocated_row_height_total"] = sum(written_geometry.row_heights)


def _table_geometry_diagnostic(geometry: _TableGeometry) -> dict[str, object]:
    left, top, width, height = geometry.frame
    return {
        "frame": {"left": left, "top": top, "width": width, "height": height},
        "column_widths": list(geometry.column_widths),
        "row_heights": list(geometry.row_heights),
    }


def _table_cell_location(row_index: int, column_index: int) -> dict[str, int]:
    return {"row_index": row_index, "column_index": column_index}


def _source_font_sizes(text_box: BoundedTextBox) -> list[float]:
    """Return sorted resolved sizes without including document text or font names."""
    return sorted(
        {
            run.font_size_points or DEFAULT_FONT_SIZE_POINTS
            for paragraph in text_box.paragraphs
            for run in paragraph.runs
        }
    )


def _table_cell_width(table: Table, cell: _Cell, column_index: int) -> int | None:
    """Return the merge-origin cell's finite width; row height comes from the frame plan."""
    span_width = cell.span_width if cell.is_merge_origin else 1
    columns = tuple(
        table.columns[index] for index in range(column_index, column_index + span_width)
    )
    if len(columns) != span_width:
        return None
    width = sum(int(column.width) for column in columns)
    return width if width > 0 else None


def _table_cell_text_box(
    cell: _Cell, width: int, height: int, theme: PptxThemeFonts | None
) -> BoundedTextBox:
    """Build a bounded layout model using the table cell's own margins."""
    text_frame = cell.text_frame
    return BoundedTextBox(
        width_emu=width,
        height_emu=height,
        margin_left_emu=int(cell.margin_left),
        margin_top_emu=int(cell.margin_top),
        margin_right_emu=int(cell.margin_right),
        margin_bottom_emu=int(cell.margin_bottom),
        text_direction=text_frame._element.bodyPr.get("vert"),
        paragraphs=tuple(
            _effective_table_cell_paragraph(paragraph, theme) for paragraph in text_frame.paragraphs
        ),
    )


def _effective_table_cell_paragraph(
    paragraph: _Paragraph, theme: PptxThemeFonts | None
) -> BoundedTextParagraph:
    direct = _paragraph_properties(paragraph)
    style_properties = (paragraph._p.pPr,) if paragraph._p.pPr is not None else ()
    defaults = _run_defaults(style_properties)
    bullet_kind, bullet_marker = _effective_bullet(style_properties)
    return replace(
        direct,
        alignment=direct.alignment or _inherited_alignment(style_properties) or "left",
        margin_left_emu=(
            direct.margin_left_emu
            if direct.margin_left_emu is not None
            else _inherited_integer(style_properties, "marL")
        ),
        indent_emu=(
            direct.indent_emu
            if direct.indent_emu is not None
            else _inherited_integer(style_properties, "indent")
        ),
        bullet_kind=bullet_kind,
        bullet_marker=bullet_marker,
        empty_line_font_size_points=direct.empty_line_font_size_points
        or defaults.font_size_points,
        runs=tuple(_effective_run(run, defaults, theme) for run in direct.runs),
    )


def _has_non_whitespace_text(text_box: BoundedTextBox) -> bool:
    return any(run.text.strip() for paragraph in text_box.paragraphs for run in paragraph.runs)


def _replace_text_frame_source_formatting(
    text_frame: TextFrame,
    replacement: TextReplacementProvider,
    source_language: str,
    target_language: str,
) -> int:
    """Replace a cell while retaining its original runs and text-frame settings."""
    replaced = 0
    for paragraph in text_frame.paragraphs:
        for run in paragraph.runs:
            if not run.text:
                continue
            run.text = replacement.replace(
                TextReplacementRequest(run.text, False, source_language, target_language)
            ).text
            replaced += 1
    return replaced


def _has_text(shape: "_TextShape") -> bool:
    return any(
        run.text.strip()
        for paragraph in shape.text_frame.paragraphs
        for run in paragraph.runs
    )


def _trim_trailing_empty_text_frame(text_frame: TextFrame) -> None:
    """Apply PPTX trailing-paragraph normalization to the source XML."""
    paragraphs = list(text_frame.paragraphs)
    while len(paragraphs) > 1 and not any(
        run.text.strip() for run in paragraphs[-1].runs
    ):
        paragraph = paragraphs.pop()
        text_frame._element.remove(paragraph._p)


def _has_explicit_no_autofit(text_frame: TextFrame) -> bool:
    """Whether the source, rather than our output, explicitly disables autofit."""
    return text_frame._element.bodyPr.find(qn("a:noAutofit")) is not None


def _text_box(
    shape: "_TextShape", slide_layout: object, theme: PptxThemeFonts | None
) -> BoundedTextBox:
    text_frame = shape.text_frame
    paragraphs = tuple(
        _effective_paragraph(paragraph, shape, slide_layout, theme)
        for paragraph in text_frame.paragraphs
    )
    return BoundedTextBox(
        width_emu=int(shape.width),
        height_emu=int(shape.height),
        margin_left_emu=int(text_frame.margin_left),
        margin_top_emu=int(text_frame.margin_top),
        margin_right_emu=int(text_frame.margin_right),
        margin_bottom_emu=int(text_frame.margin_bottom),
        text_direction=text_frame._element.bodyPr.get("vert"),
        paragraphs=paragraphs,
    )


def _effective_paragraph(
    paragraph: _Paragraph, shape: "_TextShape", slide_layout: object, theme: PptxThemeFonts | None
) -> BoundedTextParagraph:
    direct = _paragraph_properties(paragraph)
    style_properties = _paragraph_style_properties(
        shape, slide_layout, direct.level, paragraph._p.pPr
    )
    defaults = _run_defaults(style_properties)
    bullet_kind, bullet_marker = _effective_bullet(style_properties)
    return replace(
        direct,
        alignment=direct.alignment or _inherited_alignment(style_properties) or "left",
        margin_left_emu=(
            direct.margin_left_emu
            if direct.margin_left_emu is not None
            else _inherited_integer(style_properties, "marL")
        ),
        indent_emu=(
            direct.indent_emu
            if direct.indent_emu is not None
            else _inherited_integer(style_properties, "indent")
        ),
        bullet_kind=bullet_kind,
        bullet_marker=bullet_marker,
        empty_line_font_size_points=direct.empty_line_font_size_points
        or defaults.font_size_points,
        runs=tuple(_effective_run(run, defaults, theme) for run in direct.runs),
    )


def _paragraph_properties(paragraph: _Paragraph) -> BoundedTextParagraph:
    line_spacing = paragraph.line_spacing
    if isinstance(line_spacing, Length):
        line_spacing_value, line_spacing_kind = float(line_spacing.pt), "points"
    elif isinstance(line_spacing, (int, float)):
        line_spacing_value, line_spacing_kind = float(line_spacing), "multiple"
    else:
        line_spacing_value, line_spacing_kind = None, None
    paragraph_properties = paragraph._p.pPr
    bullet_kind, bullet_marker = _paragraph_bullet(paragraph_properties)
    return BoundedTextParagraph(
        alignment=_enum_name(paragraph.alignment),
        space_before_points=_length_points(paragraph.space_before),
        space_after_points=_length_points(paragraph.space_after),
        line_spacing=line_spacing_value,
        line_spacing_kind=line_spacing_kind,
        level=paragraph.level,
        margin_left_emu=_xml_integer(paragraph_properties, "marL"),
        indent_emu=_xml_integer(paragraph_properties, "indent"),
        bullet_kind=bullet_kind,
        bullet_marker=bullet_marker,
        empty_line_font_size_points=_end_paragraph_font_size_points(paragraph),
        runs=tuple(_run_properties(run) for run in paragraph.runs),
    )


def _run_properties(run: _Run) -> BoundedTextRun:
    source_typefaces = _source_typefaces_from_properties(run.font._element)
    return BoundedTextRun(
        text=run.text,
        font_family=run.font.name,
        font_classification=_font_classification(run.font.name),
        font_size_points=_length_points(run.font.size),
        bold=run.font.bold,
        italic=run.font.italic,
        underline=_enum_name(run.font.underline),
        baseline=_xml_integer(run.font._element, "baseline"),
        source_typefaces=source_typefaces,
    )


@dataclass(frozen=True, slots=True)
class _RunDefaults:
    font_family: str | None = None
    font_size_points: float | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: str | None = None
    baseline: int | None = None
    source_typefaces: tuple[SourceTypefaceReference, ...] = ()


def _paragraph_style_properties(
    shape: "_TextShape", slide_layout: object, level: int, direct: object | None
) -> tuple[object, ...]:
    properties: list[object] = []
    layout = cast("_SlideLayout", slide_layout)
    master_level = _list_level_properties(_master_text_style(shape, layout), level)
    if master_level is not None:
        properties.append(master_level)
    layout_level = _list_level_properties(_layout_list_style(shape, layout), level)
    if layout_level is not None:
        properties.append(layout_level)
    text_frame_level = _list_level_properties(shape.text_frame._element.find(qn("a:lstStyle")), level)
    if text_frame_level is not None:
        properties.append(text_frame_level)
    if direct is not None:
        properties.append(direct)
    return tuple(properties)


def _master_text_style(shape: "_TextShape", layout: "_SlideLayout") -> object | None:
    if not shape.is_placeholder:
        return None
    placeholder_type = str(shape.placeholder_format.type)
    style_name = (
        "titleStyle"
        if "TITLE" in placeholder_type
        else "bodyStyle"
        if "BODY" in placeholder_type
        else "otherStyle"
    )
    styles = cast("_XmlElement", layout.slide_master._element).find(qn("p:txStyles"))
    return None if styles is None else styles.find(qn(f"p:{style_name}"))


def _layout_list_style(shape: "_TextShape", layout: "_SlideLayout") -> object | None:
    if not shape.is_placeholder:
        return None
    placeholder_index = shape.placeholder_format.idx
    for layout_shape in layout.shapes:
        if layout_shape.is_placeholder:
            candidate = cast(_TextShape, layout_shape)
            if candidate.placeholder_format.idx == placeholder_index:
                return cast(object, candidate.text_frame._element.find(qn("a:lstStyle")))
    return None


def _list_level_properties(list_style: object | None, level: int) -> object | None:
    if list_style is None:
        return None
    return cast("_XmlElement", list_style).find(qn(f"a:lvl{level + 1}pPr"))


def _run_defaults(properties: tuple[object, ...]) -> _RunDefaults:
    defaults = _RunDefaults()
    for paragraph_properties in properties:
        run_properties = cast("_XmlElement", paragraph_properties).find(qn("a:defRPr"))
        if run_properties is None:
            continue
        size = run_properties.get("sz")
        defaults = _RunDefaults(
            font_family=_font_from_properties(run_properties) or defaults.font_family,
            font_size_points=float(size) / 100.0 if size is not None else defaults.font_size_points,
            bold=_xml_boolean(run_properties.get("b"))
            if run_properties.get("b") is not None
            else defaults.bold,
            italic=_xml_boolean(run_properties.get("i"))
            if run_properties.get("i") is not None
            else defaults.italic,
            underline=run_properties.get("u") or defaults.underline,
            baseline=_xml_integer(run_properties, "baseline") or defaults.baseline,
            source_typefaces=_merge_source_typefaces(
                defaults.source_typefaces, _source_typefaces_from_properties(run_properties)
            ),
        )
    return defaults


def _effective_run(
    run: BoundedTextRun, defaults: _RunDefaults, theme: PptxThemeFonts | None
) -> BoundedTextRun:
    source_typefaces = _merge_source_typefaces(defaults.source_typefaces, run.source_typefaces)
    source_typefaces = resolve_theme_typefaces(source_typefaces, theme, run.text)
    family = run.font_family or defaults.font_family or _primary_source_family(source_typefaces)
    return replace(
        run,
        font_family=family,
        font_classification=_font_classification(family),
        font_size_points=run.font_size_points or defaults.font_size_points,
        bold=run.bold if run.bold is not None else defaults.bold,
        italic=run.italic if run.italic is not None else defaults.italic,
        underline=run.underline if run.underline is not None else defaults.underline,
        baseline=run.baseline if run.baseline is not None else defaults.baseline,
        source_typefaces=source_typefaces,
    )


def _effective_bullet(properties: tuple[object, ...]) -> tuple[str | None, str | None]:
    kind: str | None = None
    marker: str | None = None
    for paragraph_properties in properties:
        candidate_kind, candidate_marker = _paragraph_bullet(paragraph_properties)
        if candidate_kind is not None:
            kind, marker = candidate_kind, candidate_marker
    return kind, marker


def _paragraph_bullet(properties: object | None) -> tuple[str | None, str | None]:
    if properties is None:
        return None, None
    element = cast("_XmlElement", properties)
    if element.find(qn("a:buNone")) is not None:
        return "none", None
    character = element.find(qn("a:buChar"))
    if character is not None:
        return "character", character.get("char")
    if element.find(qn("a:buAutoNum")) is not None:
        return "automatic-number", None
    if element.find(qn("a:buBlip")) is not None:
        return "picture", None
    return None, None


def _write_explicit_text_frame(
    text_frame: TextFrame,
    text_box: BoundedTextBox,
    *,
    write_text_frame_geometry: bool = True,
) -> None:
    body_properties = text_frame._element.bodyPr
    if write_text_frame_geometry:
        body_properties.set("lIns", str(int(text_frame.margin_left)))
        body_properties.set("tIns", str(int(text_frame.margin_top)))
        body_properties.set("rIns", str(int(text_frame.margin_right)))
        body_properties.set("bIns", str(int(text_frame.margin_bottom)))
        body_properties.set("wrap", "square" if text_frame.word_wrap is not False else "none")
    body_properties.autofit = MSO_AUTO_SIZE.NONE
    for paragraph, explicit in zip(text_frame.paragraphs, text_box.paragraphs, strict=True):
        _write_paragraph(paragraph, explicit)


def _write_paragraph(paragraph: _Paragraph, explicit: BoundedTextParagraph) -> None:
    source_run_properties = _dominant_source_run_properties(paragraph)
    source_end_properties = cast(
        _XmlElement | None, paragraph._p.find(qn("a:endParaRPr"))
    )
    paragraph_properties = paragraph._p.get_or_add_pPr()
    paragraph_properties.set("lvl", str(explicit.level))
    paragraph_properties.set("algn", _drawing_alignment(explicit.alignment))
    _set_optional_integer(paragraph_properties, "marL", explicit.margin_left_emu)
    _set_optional_integer(paragraph_properties, "indent", explicit.indent_emu)
    _write_spacing(paragraph_properties, "a:spcBef", explicit.space_before_points, "points")
    _write_spacing(paragraph_properties, "a:spcAft", explicit.space_after_points, "points")
    _write_spacing(
        paragraph_properties,
        "a:lnSpc",
        explicit.line_spacing,
        explicit.line_spacing_kind,
    )
    _write_bullet(paragraph_properties, explicit)
    for child in tuple(paragraph._p):
        if child.tag != qn("a:pPr"):
            paragraph._p.remove(child)
    for run in explicit.runs:
        destination_run = paragraph.add_run()
        destination_run.text = run.text
        destination_properties = destination_run._r.get_or_add_rPr()
        _copy_xml_properties(destination_properties, source_run_properties)
        _write_run_properties(destination_properties, run)
    end_properties = paragraph._p.get_or_add_endParaRPr()
    empty_style = explicit.runs[0] if explicit.runs else BoundedTextRun(
        "", "Noto Sans JP", "sans-serif", explicit.empty_line_font_size_points, False, False, "none", 0
    )
    _copy_xml_properties(end_properties, source_end_properties)
    _write_run_properties(end_properties, empty_style)
    _reorder_children(paragraph_properties, _PARAGRAPH_PROPERTY_CHILD_ORDER)


def _dominant_source_run_properties(paragraph: _Paragraph) -> _XmlElement | None:
    """Return the direct properties of the run selected by the shared core.

    ``replace_and_fit_text_box`` emits one replacement run for a populated
    paragraph, using its dominant source run. The PPTX writer mirrors that
    selection so it can retain advanced DrawingML formatting outside the
    shared metric model.
    """
    source_runs = tuple(paragraph.runs)
    if not source_runs:
        return None
    dominant_run = max(
        source_runs,
        key=lambda run: sum(not character.isspace() for character in run.text),
    )
    return cast(_XmlElement | None, dominant_run._r.find(qn("a:rPr")))


def _copy_xml_properties(destination: object, source: _XmlElement | None) -> None:
    """Clone direct DrawingML properties without retaining source text nodes."""
    destination_element = cast(_XmlElement, destination)
    for name in tuple(destination_element.attrib):
        destination_element.attrib.pop(name)
    for child in tuple(destination_element):
        destination_element.remove(child)
    if source is None:
        return
    for name, value in source.attrib.items():
        destination_element.set(name, value)
    for child in source:
        destination_element.append(deepcopy(child))


def _write_spacing(
    paragraph_properties: object,
    container_tag: str,
    value: float | None,
    kind: str | None,
) -> None:
    element = cast("_XmlElement", paragraph_properties)
    existing = element.find(qn(container_tag))
    if existing is not None:
        element.remove(existing)
    if value is None:
        return
    container = _new_element(container_tag)
    child = _new_element("a:spcPts" if kind == "points" else "a:spcPct")
    child.set("val", str(round(value * (100.0 if kind == "points" else 100_000.0))))
    container.append(child)
    element.append(container)


def _write_bullet(properties: object, paragraph: BoundedTextParagraph) -> None:
    element = cast("_XmlElement", properties)
    for tag in ("a:buNone", "a:buChar"):
        existing = element.find(qn(tag))
        if existing is not None:
            element.remove(existing)
    if paragraph.bullet_kind == "none":
        element.append(_new_element("a:buNone"))
    elif paragraph.bullet_kind == "character":
        bullet = _new_element("a:buChar")
        bullet.set("char", paragraph.bullet_marker or "•")
        element.append(bullet)


def _write_run_properties(properties: object, run: BoundedTextRun) -> None:
    element = cast("_XmlElement", properties)
    element.set("sz", str(_ooxml_font_size_centipoints(run.font_size_points or 18.0)))
    references = (
        (
            {"latin": "a:latin", "eastAsian": "a:ea", "complex": "a:cs"}[item.script],
            item.original_family,
        )
        for item in run.source_typefaces
    ) if run.source_typefaces else ((tag, run.font_family or "Noto Sans JP") for tag in ("a:latin", "a:ea"))
    for tag, family in references:
        if not family:
            continue
        child = element.find(qn(tag))
        if child is None:
            child = _new_element(tag)
            element.append(child)
        child.set("typeface", family)
    _reorder_children(element, _RUN_PROPERTY_CHILD_ORDER)


def _ooxml_font_size_centipoints(size_points: float) -> int:
    """Return a valid DrawingML ``sz`` value for an explicitly fitted run."""
    return min(
        _OOXML_MAXIMUM_FONT_SIZE_CENTIPOINTS,
        max(_OOXML_MINIMUM_FONT_SIZE_CENTIPOINTS, round(size_points * 100.0)),
    )


def _new_element(tag: str) -> "_XmlElement":
    """Create a DrawingML element through python-pptx's lxml element factory."""
    return cast(
        _XmlElement,
        parse_xml(
            f'<a:{tag.partition(":")[2]} xmlns:a="{_DRAWING_NAMESPACE}"/>'
        ),
    )


def _reorder_children(element: object, order: tuple[str, ...]) -> None:
    """Restore the schema-required order after writing DrawingML properties."""
    xml_element = cast(_XmlElement, element)
    ranks = {name: index for index, name in enumerate(order)}
    children = list(xml_element)
    children.sort(key=lambda child: ranks.get(child.tag.rsplit("}", 1)[-1], len(ranks)))
    for child in children:
        xml_element.remove(child)
    for child in children:
        xml_element.append(child)


def _drawing_alignment(value: str | None) -> str:
    return {"left": "l", "center": "ctr", "right": "r", "justify": "just"}.get(value or "left", "l")


def _set_optional_integer(element: object, name: str, value: int | None) -> None:
    xml_element = cast("_XmlElement", element)
    if value is None:
        xml_element.attrib.pop(name, None)
    else:
        xml_element.set(name, str(value))


def _inherited_integer(properties: tuple[object, ...], name: str) -> int | None:
    value: int | None = None
    for paragraph_properties in properties:
        candidate = _xml_integer(paragraph_properties, name)
        if candidate is not None:
            value = candidate
    return value


def _inherited_alignment(properties: tuple[object, ...]) -> str | None:
    value: str | None = None
    for paragraph_properties in properties:
        raw = cast("_XmlElement", paragraph_properties).get("algn")
        if raw is not None:
            value = {"l": "left", "ctr": "center", "r": "right", "just": "justify"}.get(raw, raw)
    return value


def _font_from_properties(properties: object) -> str | None:
    element = cast("_XmlElement", properties)
    for tag in ("a:latin", "a:ea"):
        candidate = element.find(qn(tag))
        if candidate is not None and candidate.get("typeface"):
            return candidate.get("typeface")
    return None


def _source_typefaces_from_properties(
    properties: object,
) -> tuple[SourceTypefaceReference, ...]:
    element = cast("_XmlElement", properties)
    references: list[SourceTypefaceReference] = []
    for script, tag in (("latin", "a:latin"), ("eastAsian", "a:ea"), ("complex", "a:cs")):
        candidate = element.find(qn(tag))
        if candidate is not None and candidate.get("typeface"):
            references.append(SourceTypefaceReference(script, candidate.get("typeface")))
    return tuple(references)


def _merge_source_typefaces(
    defaults: tuple[SourceTypefaceReference, ...], direct: tuple[SourceTypefaceReference, ...]
) -> tuple[SourceTypefaceReference, ...]:
    by_script = {item.script: item for item in defaults}
    by_script.update({item.script: item for item in direct})
    return tuple(by_script[script] for script in ("latin", "eastAsian", "complex") if script in by_script)


def _primary_source_family(references: tuple[SourceTypefaceReference, ...]) -> str | None:
    return next((item.original_family for item in references if item.script == "latin"), None) or next(
        (item.original_family for item in references), None
    )


def _xml_integer(element: object | None, name: str) -> int | None:
    if element is None:
        return None
    value = cast("_XmlElement", element).get(name)
    return int(value) if value is not None else None


def _xml_boolean(value: str | None) -> bool | None:
    return None if value is None else value not in {"0", "false", "False"}


def _end_paragraph_font_size_points(paragraph: _Paragraph) -> float | None:
    size = _xml_integer(paragraph._p.endParaRPr, "sz")
    return None if size is None else size / 100.0


def _length_points(value: Length | None) -> float | None:
    return None if value is None else float(value.pt)


def _enum_name(value: object) -> str | None:
    if value is None:
        return None
    return str(value).split(" ", 1)[0].lower().replace("_", "-")


def _font_classification(family: str | None) -> str:
    normalized = (family or "").lower()
    if any(marker in normalized for marker in ("mono", "courier", "console", "code")):
        return "fixed-width"
    if any(marker in normalized for marker in ("serif", "roman", "times", "georgia")):
        return "serif"
    return "sans-serif"


class _XmlElement(Protocol, Iterable["_XmlElement"]):
    attrib: dict[str, str]
    tag: str

    def append(self, element: object) -> None: ...
    def remove(self, element: object) -> None: ...
    def find(self, path: str) -> "_XmlElement | None": ...
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def iter(self) -> Iterator["_XmlElement"]: ...
    def __iter__(self) -> Iterator["_XmlElement"]:
        raise NotImplementedError


class _TextShape(Protocol):
    width: int
    height: int
    is_placeholder: bool
    text_frame: TextFrame
    placeholder_format: "_PlaceholderFormat"


class _PlaceholderFormat(Protocol):
    idx: int
    type: object


class _SlideLayout:
    shapes: Iterable[BaseShape]
    slide_master: "_SlideMaster"


class _SlideMaster:
    _element: object
