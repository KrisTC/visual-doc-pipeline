"""Folder-oriented orchestration for local visible-text replacement."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
import os
import sys
from typing import Protocol
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from PIL import Image
# pypdf publishes no PEP 561 metadata for its generic object model.
from pypdf import PdfReader, PdfWriter
# These pypdf values cross a dynamic PDF-object boundary.
from pypdf.generic import ArrayObject, ContentStream, TextStringObject
# skia-python does not publish PEP 561 stubs; this is the native rendering boundary.
import skia  # type: ignore[import-not-found]
from tqdm import tqdm

from pipeline.ocr import OcrProvider, OcrRequest
from pipeline.text_region_colours import estimate_text_region_colours
from pipeline.text_region_rendering import TextRegionReplacement, replace_text_regions
from pipeline.text_replacement import TextReplacementProvider, TextReplacementRequest
from pipeline.vector_text import replace_vector_text
from pipeline.folder_replacement.office_xml import replace_office_xml_text
from pipeline.folder_replacement.docx import replace_docx_file
from pipeline.folder_replacement.pdf import replace_pdf_file
from pipeline.folder_replacement.pptx import replace_pptx_file
from pipeline.folder_replacement.xlsx import replace_xlsx_file
from pipeline.folder_replacement.bitmap import (
    replace_bitmap_bytes as _process_bitmap_bytes,
    replace_bitmap_file as _process_bitmap_file,
    replace_image as _process_bitmap_image,
)


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


def replace_input_folder(
    input_root: Path,
    output_root: Path,
    *,
    ocr_provider: OcrProvider,
    text_replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typeface: skia.Typeface,
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
    if not _provider_supports_language(ocr_provider, source_language):
        raise ValueError(
            f"The selected OCR provider does not support source language {source_language!r}."
        )

    result = FolderReplacementResult()
    reserved_paths: set[Path] = set()
    for source_path in sorted(path for path in input_root.rglob("*") if path.is_file()):
        temporary_destination: Path | None = None
        progress = None
        extension = source_path.suffix.lower()
        if extension not in BITMAP_EXTENSIONS | DOCUMENT_EXTENSIONS | VECTOR_EXTENSIONS:
            result.ignored_files += 1
            continue
        try:
            relative_source_path = source_path.relative_to(input_root)
            print(f"Processing: {relative_source_path}")
            if show_progress:
                make_progress = progress_factory or _make_progress_bar
                progress = make_progress(_source_work_total(source_path), relative_source_path.name)

            def work_completed(label: str) -> None:
                if progress is not None:
                    progress.set_postfix_str(label)
                    progress.update()

            destination = _destination_path(
                input_root,
                output_root,
                source_path,
                text_replacement_provider,
                source_language,
                target_language,
                reserved_paths,
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary_destination = destination.with_name(f".{destination.name}.tmp")
            if extension in BITMAP_EXTENSIONS:
                image_regions = _replace_bitmap_file(
                    source_path,
                    temporary_destination,
                    ocr_provider,
                    text_replacement_provider,
                    source_language,
                    target_language,
                    typeface,
                )
                result.replaced_image_regions += image_regions
                work_completed("bitmap")
            elif extension in VECTOR_EXTENSIONS:
                vector_result = replace_vector_text(
                    source_path.read_bytes(),
                    extension,
                    lambda text: _replace_native_text(
                        text, text_replacement_provider, source_language, target_language
                    ),
                    source_language,
                    lambda image: _replace_image_text(
                        image,
                        ocr_provider,
                        text_replacement_provider,
                        source_language,
                        target_language,
                        typeface,
                    ),
                )
                temporary_destination.write_bytes(vector_result.data)
                result.replaced_native_text_items += vector_result.replaced_text_items
                result.replaced_image_regions += vector_result.replaced_image_regions
                if not vector_result.has_editable_text and not vector_result.has_embedded_bitmaps:
                    result.retained_vector_graphics += 1
                work_completed("vector graphic")
            elif extension == ".pdf":
                native_items, image_regions = replace_pdf_file(
                    source_path,
                    temporary_destination,
                    ocr_provider,
                    text_replacement_provider,
                    source_language,
                    target_language,
                    typeface,
                    work_completed,
                )
                result.replaced_native_text_items += native_items
                result.replaced_image_regions += image_regions
            else:
                office_handler = {
                    ".docx": replace_docx_file,
                    ".pptx": replace_pptx_file,
                    ".xlsx": replace_xlsx_file,
                }[extension]
                native_items, image_regions, retained_vectors = office_handler(
                    source_path,
                    temporary_destination,
                    ocr_provider,
                    text_replacement_provider,
                    source_language,
                    target_language,
                    typeface,
                    work_completed,
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
            continue
        else:
            reserved_paths.add(destination)
            result.processed_files += 1
        finally:
            if progress is not None:
                progress.close()
    return result


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


def _source_work_total(source_path: Path) -> int:
    """Return the native-text plus embedded-raster work units for one source file."""
    extension = source_path.suffix.lower()
    if extension in BITMAP_EXTENSIONS:
        return 1
    if extension in VECTOR_EXTENSIONS:
        return 1
    if extension in OFFICE_DOCUMENT_EXTENSIONS:
        with ZipFile(source_path) as archive:
            return 1 + sum(
                _is_office_bitmap_part(name) or _is_office_vector_part(name)
                for name in archive.namelist()
            )
    reader = PdfReader(source_path)
    image_references: set[int] = set()
    inline_image_count = 0
    for page in reader.pages:
        for image_file in page.images:
            reference = image_file.indirect_reference
            if reference is None:
                inline_image_count += 1
            else:
                image_references.add(reference.idnum)
    return 1 + len(image_references) + inline_image_count


def _make_progress_bar(total: int, label: str) -> ProgressReporter:
    """Create the standard terminal bar for one source file."""
    return tqdm(
        total=total,
        desc=label,
        dynamic_ncols=True,
        leave=True,
        unit="work item",
    )


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
) -> tuple[int, int, int]:
    native_items = 0
    image_regions = 0
    embedded_image_index = 0
    vector_graphic_index = 0
    retained_vectors = 0
    with ZipFile(source) as source_archive, ZipFile(destination, "w", ZIP_DEFLATED) as destination_archive:
        for entry in source_archive.infolist():
            data = source_archive.read(entry.filename)
            if _is_office_bitmap_part(entry.filename):
                embedded_image_index += 1
                data, replaced = _replace_bitmap_bytes(
                    data,
                    ocr_provider,
                    replacement_provider,
                    source_language,
                    target_language,
                    typeface,
                )
                image_regions += replaced
                work_completed(f"embedded image {embedded_image_index}")
            elif _is_office_vector_part(entry.filename):
                vector_graphic_index += 1
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
                )
                data = vector_result.data
                native_items += vector_result.replaced_text_items
                image_regions += vector_result.replaced_image_regions
                if not vector_result.has_editable_text and not vector_result.has_embedded_bitmaps:
                    retained_vectors += 1
                    print(f"Retained vector without editable text: {source}", file=sys.stderr)
                work_completed(f"vector graphic {vector_graphic_index}")
            elif entry.filename.endswith(".xml"):
                data, replaced = replace_office_xml_text(
                    data, replacement_provider, source_language, target_language
                )
                native_items += replaced
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
) -> tuple[bytes, int]:
    return _process_bitmap_bytes(data, ocr_provider, replacement_provider, source_language, target_language, typeface)


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


def _replace_pdf_file(
    source: Path,
    destination: Path,
    ocr_provider: OcrProvider,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typeface: skia.Typeface,
    work_completed: Callable[[str], None],
) -> tuple[int, int]:
    reader = PdfReader(source)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    native_items = 0
    seen_forms: set[int] = set()
    seen_annotations: set[int] = set()
    for page in writer.pages:
        native_items += _replace_pdf_content_text(
            page,
            writer,
            replacement_provider,
            source_language,
            target_language,
            seen_forms,
        )
        native_items += _replace_pdf_annotations(
            page,
            writer,
            replacement_provider,
            source_language,
            target_language,
            seen_forms,
            seen_annotations,
        )
    acro_form = writer._root_object.get("/AcroForm")
    if acro_form is not None:
        native_items += _replace_pdf_form_fields(
            acro_form.get_object(),
            writer,
            replacement_provider,
            source_language,
            target_language,
            seen_forms,
            seen_annotations,
        )
    work_completed("native text")
    image_regions = 0
    seen_images: set[int] = set()
    embedded_image_index = 0
    for page in writer.pages:
        for image_file in page.images:
            reference = image_file.indirect_reference
            if reference is None:
                raise ValueError("A PDF contains an inline image that cannot be replaced safely.")
            if reference.idnum in seen_images:
                continue
            seen_images.add(reference.idnum)
            if image_file.image is None:
                raise ValueError("Could not decode an embedded PDF image.")
            replacement_image = image_file.image.copy()
            image_regions += _replace_image_text(
                replacement_image,
                ocr_provider,
                replacement_provider,
                source_language,
                target_language,
                typeface,
            )
            image_file.replace(replacement_image)
            embedded_image_index += 1
            work_completed(f"embedded image {embedded_image_index}")
    with destination.open("wb") as output_file:
        writer.write(output_file)
    return native_items, image_regions


def _replace_pdf_annotations(
    page: object,
    writer: PdfWriter,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    seen_forms: set[int],
    seen_annotations: set[int],
) -> int:
    annotations = getattr(page, "get", lambda _key, _default=None: None)("/Annots")
    if annotations is None:
        return 0
    replaced_items = 0
    for annotation_reference in annotations.get_object():
        annotation = annotation_reference.get_object()
        if annotation.indirect_reference is not None:
            identifier = annotation.indirect_reference.idnum
            if identifier in seen_annotations:
                continue
            seen_annotations.add(identifier)
        replaced_items += _replace_pdf_dictionary_text(
            annotation, replacement_provider, source_language, target_language
        )
        appearance = annotation.get("/AP")
        if appearance is not None:
            replaced_items += _replace_pdf_appearance_streams(
                appearance.get_object(),
                writer,
                replacement_provider,
                source_language,
                target_language,
                seen_forms,
            )
    return replaced_items


def _replace_pdf_form_fields(
    field: object,
    writer: PdfWriter,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    seen_forms: set[int],
    seen_annotations: set[int],
) -> int:
    get_object = getattr(field, "get_object", None)
    dictionary = get_object() if callable(get_object) else field
    if not hasattr(dictionary, "get"):
        return 0
    reference = getattr(dictionary, "indirect_reference", None)
    identifier = getattr(reference, "idnum", None)
    if isinstance(identifier, int):
        if identifier in seen_annotations:
            return 0
        seen_annotations.add(identifier)
    replaced_items = _replace_pdf_dictionary_text(
        dictionary, replacement_provider, source_language, target_language
    )
    appearance = dictionary.get("/AP")
    if appearance is not None:
        replaced_items += _replace_pdf_appearance_streams(
            appearance.get_object(),
            writer,
            replacement_provider,
            source_language,
            target_language,
            seen_forms,
        )
    children = dictionary.get("/Kids")
    if children is None:
        children = dictionary.get("/Fields")
    if children is not None:
        for child in children.get_object():
            replaced_items += _replace_pdf_form_fields(
                child,
                writer,
                replacement_provider,
                source_language,
                target_language,
                seen_forms,
                seen_annotations,
            )
    return replaced_items


def _replace_pdf_dictionary_text(
    dictionary: object,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
) -> int:
    get_value = getattr(dictionary, "get", None)
    if not callable(get_value):
        return 0
    replaced_items = 0
    for key in ("/Contents", "/V", "/DV", "/T"):
        value = get_value(key)
        if not isinstance(value, TextStringObject):
            continue
        set_value = getattr(dictionary, "__setitem__", None)
        if not callable(set_value):
            continue
        set_value(
            key,
            TextStringObject(
                _replace_native_text(
                    str(value), replacement_provider, source_language, target_language
                )
            ),
        )
        replaced_items += 1
    return replaced_items


def _replace_pdf_appearance_streams(
    appearance: object,
    writer: PdfWriter,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    seen_forms: set[int],
) -> int:
    values = getattr(appearance, "values", None)
    if not callable(values):
        return 0
    replaced_items = 0
    for value in values():
        appearance_entry = value.get_object()
        get_value = getattr(appearance_entry, "get", None)
        if callable(get_value) and get_value("/Subtype") == "/Form":
            replaced_items += _replace_pdf_content_text(
                appearance_entry,
                writer,
                replacement_provider,
                source_language,
                target_language,
                seen_forms,
            )
        elif hasattr(appearance_entry, "values"):
            replaced_items += _replace_pdf_appearance_streams(
                appearance_entry,
                writer,
                replacement_provider,
                source_language,
                target_language,
                seen_forms,
            )
    return replaced_items


def _replace_pdf_content_text(
    content_owner: object,
    writer: PdfWriter,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    seen_forms: set[int],
) -> int:
    get_contents = getattr(content_owner, "get_contents", None)
    replace_contents = getattr(content_owner, "replace_contents", None)
    contents = get_contents() if callable(get_contents) else content_owner
    if contents is None:
        return 0
    content_stream = ContentStream(contents, writer)
    replaced_items = _replace_pdf_operations(
        content_stream,
        replacement_provider,
        source_language,
        target_language,
    )
    if replaced_items:
        if callable(replace_contents):
            replace_contents(content_stream)
        else:
            set_data = getattr(content_owner, "set_data", None)
            if not callable(set_data):
                raise ValueError("A PDF Form XObject has no writable content stream.")
            set_data(content_stream.get_data())
    resources = getattr(content_owner, "get", lambda _key, _default=None: None)("/Resources")
    xobjects = (
        resources.get_object().get("/XObject")
        if resources is not None and resources.get_object().get("/XObject") is not None
        else None
    )
    if xobjects is None:
        return replaced_items
    for xobject in xobjects.get_object().values():
        form = xobject.get_object()
        if form.get("/Subtype") != "/Form" or form.indirect_reference is None:
            continue
        identifier = form.indirect_reference.idnum
        if identifier in seen_forms:
            continue
        seen_forms.add(identifier)
        replaced_items += _replace_pdf_content_text(
            form,
            writer,
            replacement_provider,
            source_language,
            target_language,
            seen_forms,
        )
    return replaced_items


def _replace_pdf_operations(
    content_stream: ContentStream,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
) -> int:
    replaced_items = 0
    for operands, operator in content_stream.operations:
        string_indexes: tuple[int, ...]
        if operator == b"Tj" or operator == b"'":
            string_indexes = (0,)
        elif operator == b'"':
            string_indexes = (2,)
        elif operator == b"TJ":
            if operands and isinstance(operands[0], ArrayObject):
                for index, value in enumerate(operands[0]):
                    if isinstance(value, TextStringObject):
                        operands[0][index] = TextStringObject(
                            _replace_native_text(
                                str(value), replacement_provider, source_language, target_language
                            )
                        )
                        replaced_items += 1
            continue
        else:
            continue
        for index in string_indexes:
            if index < len(operands) and isinstance(operands[index], TextStringObject):
                operands[index] = TextStringObject(
                    _replace_native_text(
                        str(operands[index]), replacement_provider, source_language, target_language
                    )
                )
                replaced_items += 1
    return replaced_items
