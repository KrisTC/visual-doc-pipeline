"""Folder-oriented orchestration for local visible-text replacement."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
import os
import sys
from typing import Protocol, cast
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from PIL import Image
# pypdf publishes no PEP 561 metadata for its generic object model.
from pypdf import PdfReader, PdfWriter
# pypdf's CMap helper is the library's own decoder for composite PDF fonts.
from pypdf._cmap import get_encoding
# These pypdf values cross a dynamic PDF-object boundary.
from pypdf.generic import (
    ArrayObject,
    ByteStringObject,
    BooleanObject,
    ContentStream,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)
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
from pipeline.bounded_text_layout import (
    BoundedTextBox,
    BoundedTextParagraph,
    BoundedTextRun,
    noto_typefaces,
    replace_and_fit_text_box,
)
from pipeline.portable_fonts import static_noto_bytes, static_noto_font


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
    document_text_layout: str = "preserve-source-formatting",
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
                    document_text_layout=document_text_layout,
                    replacement_provider=text_replacement_provider,
                    target_language=target_language,
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
                    document_text_layout=document_text_layout,
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
                    document_text_layout=document_text_layout,
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
    *,
    replace_native_xml: bool = True,
    skip_native_xml_part: Callable[[str], bool] | None = None,
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
            elif (
                replace_native_xml
                and entry.filename.endswith(".xml")
                and not (skip_native_xml_part and skip_native_xml_part(entry.filename))
            ):
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
    *,
    document_text_layout: str = "preserve-source-formatting",
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
            static_font=document_text_layout == "preserve-basic-layout",
            source_font=document_text_layout == "preserve-basic-layout-source-font",
        )
        native_items += _replace_pdf_annotations(
            page,
            writer,
            replacement_provider,
            source_language,
            target_language,
            seen_forms,
            seen_annotations,
            document_text_layout,
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
            document_text_layout,
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
    document_text_layout: str,
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
        if document_text_layout != "preserve-source-formatting" and annotation.get("/Subtype") == "/FreeText" and _pdf_rect(annotation) is not None:
            replaced_items += _replace_pdf_bounded_dictionary_text(
                annotation, "/Contents", replacement_provider, source_language, target_language, writer,
                embed_noto=document_text_layout == "preserve-basic-layout",
            )
            continue
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
    document_text_layout: str,
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
    if document_text_layout != "preserve-source-formatting" and _pdf_rect(dictionary) is not None and isinstance(dictionary.get("/V"), TextStringObject):
        replaced_items = _replace_pdf_bounded_dictionary_text(
            dictionary, "/V", replacement_provider, source_language, target_language, writer,
            embed_noto=document_text_layout == "preserve-basic-layout",
        )
    else:
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
                document_text_layout,
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


def _pdf_rect(dictionary: object) -> tuple[float, float] | None:
    """Return the finite width/height of a widget or FreeText rectangle."""
    get_value = getattr(dictionary, "get", None)
    rectangle = get_value("/Rect") if callable(get_value) else None
    if not isinstance(rectangle, ArrayObject) or len(rectangle) != 4:
        return None
    try:
        left, bottom, right, top = (float(value) for value in rectangle)
    except (TypeError, ValueError):
        return None
    width, height = abs(right - left), abs(top - bottom)
    return (width, height) if width > 0 and height > 0 else None


def _replace_pdf_bounded_dictionary_text(
    dictionary: object,
    key: str,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    writer: PdfWriter,
    *,
    embed_noto: bool,
) -> int:
    """Fit a form/FreeText value and make its portable-size setting explicit.

    Page-content text is intentionally excluded: its drawing operators do not
    identify a stable text rectangle.  Widget viewers use ``/DA`` to generate
    an appearance when an existing appearance is stale, so we retain its
    selected source face while supplying the Noto-measured size.
    """
    get_value = getattr(dictionary, "get", None)
    set_value = getattr(dictionary, "__setitem__", None)
    if not callable(get_value) or not callable(set_value):
        return 0
    source_text = get_value(key)
    bounds = _pdf_rect(dictionary)
    if not isinstance(source_text, TextStringObject) or bounds is None or not str(source_text).strip():
        return 0
    size, face = _pdf_default_appearance(get_value("/DA"))
    box = BoundedTextBox(
        round(bounds[0] * 12_700), round(bounds[1] * 12_700), 0, 0, 0, 0, None,
        (BoundedTextParagraph("left", None, None, None, None, 0, None, None, None, None,
                              None, (BoundedTextRun(str(source_text), face, "sans-serif", size,
                                                    False, False, "none", None),)),),
    )
    fitted = replace_and_fit_text_box(
        box, replacement_provider, source_language, target_language, noto_typefaces(),
        preserve_source_font_family=True,
    )
    run = fitted.text_box.paragraphs[0].runs[0]
    set_value(NameObject(key), TextStringObject(run.text))
    font_size = run.font_size_points or size
    if embed_noto:
        font_name, font_reference = _pdf_embedded_noto_font(writer, "sans-serif", bool(run.bold))
        set_value(NameObject("/DA"), TextStringObject(f"/{font_name} {font_size:.4f} Tf 0 g"))
        _pdf_write_appearance(dictionary, font_name, font_reference, run.text, font_size, bounds)
    else:
        set_value(NameObject("/DA"), TextStringObject(f"/{face} {font_size:.4f} Tf 0 g"))
        set_value(NameObject("/AP"), DictionaryObject())
        set_value(NameObject("/NeedAppearances"), BooleanObject(True))
    return 1


def _pdf_default_appearance(value: object) -> tuple[float, str]:
    tokens = str(value or "/Helv 12 Tf").split()
    for index, token in enumerate(tokens):
        if token == "Tf" and index >= 2:
            try:
                return max(0.75, float(tokens[index - 1])), tokens[index - 2].lstrip("/")
            except ValueError:
                break
    return 12.0, "Helv"


def _pdf_embedded_noto_font(
    writer: PdfWriter, classification: str, bold: bool
) -> tuple[str, object]:
    """Create an Identity-H Type0 font whose CIDs are static-font glyph IDs."""
    family, _path = static_noto_font(classification, bold)
    resource_name = "PipelineNotoBold" if bold else "PipelineNoto"
    postscript_name = "NotoSansJP-Thin" if classification == "sans-serif" else family.replace(" ", "")
    cached = getattr(writer, "_pipeline_layout_fonts", None)
    if cached is None:
        cached = {}
        setattr(writer, "_pipeline_layout_fonts", cached)
    key = (classification, bold)
    if key in cached:
        return resource_name, cached[key]
    font_stream = DecodedStreamObject()
    font_data = static_noto_bytes(classification, bold)
    font_stream.set_data(font_data)
    font_stream.update({NameObject("/Length1"): NumberObject(len(font_data))})
    descriptor = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/FontDescriptor"),
        NameObject("/FontName"): NameObject(f"/{postscript_name}"),
        NameObject("/Flags"): NumberObject(4),
        NameObject("/FontBBox"): ArrayObject([NumberObject(-1000), NumberObject(-1000), NumberObject(3000), NumberObject(3000)]),
        NameObject("/ItalicAngle"): NumberObject(0), NameObject("/Ascent"): NumberObject(1000),
        NameObject("/Descent"): NumberObject(-300), NameObject("/CapHeight"): NumberObject(700),
        NameObject("/StemV"): NumberObject(80), NameObject("/FontFile2"): writer._add_object(font_stream),
    }))
    descendant = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/CIDFontType2"),
        NameObject("/BaseFont"): NameObject(f"/{postscript_name}"),
        NameObject("/CIDSystemInfo"): DictionaryObject({NameObject("/Registry"): TextStringObject("Adobe"), NameObject("/Ordering"): TextStringObject("Identity"), NameObject("/Supplement"): NumberObject(0)}),
        NameObject("/FontDescriptor"): descriptor, NameObject("/CIDToGIDMap"): NameObject("/Identity"),
        NameObject("/DW"): NumberObject(1000),
    }))
    reference = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type0"),
        NameObject("/BaseFont"): NameObject(f"/{postscript_name}"), NameObject("/Encoding"): NameObject("/Identity-H"),
        NameObject("/DescendantFonts"): ArrayObject([descendant]),
    }))
    cached[key] = reference
    return resource_name, reference


def _pdf_write_appearance(
    dictionary: object, font_name: str, font_reference: object, text: str,
    font_size: float, bounds: tuple[float, float],
) -> None:
    """Regenerate a simple clipped appearance with the embedded static face."""
    face = noto_typefaces()["sans-serif"]
    glyphs = skia.Font(face).textToGlyphs(text)
    encoded = "".join(f"{glyph:04X}" for glyph in glyphs)
    width, height = bounds
    appearance = DecodedStreamObject()
    appearance.set_data(
        f"q 0 0 {width:.4f} {height:.4f} re W n BT /{font_name} {font_size:.4f} Tf 0 g 0 {max(0.0, height - font_size):.4f} Td <{encoded}> Tj ET Q".encode("ascii")
    )
    appearance.update({
        NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(width), NumberObject(height)]),
        NameObject("/Resources"): DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject(f"/{font_name}"): font_reference})}),
    })
    set_value = getattr(dictionary, "__setitem__", None)
    if callable(set_value):
        set_value(NameObject("/AP"), DictionaryObject({NameObject("/N"): appearance}))


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
    *,
    static_font: bool = False,
    source_font: bool = False,
) -> int:
    get_contents = getattr(content_owner, "get_contents", None)
    replace_contents = getattr(content_owner, "replace_contents", None)
    contents = get_contents() if callable(get_contents) else content_owner
    if contents is None:
        return 0
    content_stream = ContentStream(contents, writer)
    static_font_name: str | None = None
    fallback_font_name: str | None = None
    if static_font:
        static_font_name, static_font_reference = _pdf_content_fallback_font(writer)
        _pdf_add_font_resource(content_owner, static_font_name, static_font_reference)
    elif source_font:
        fallback_font_name, fallback_font_reference = _pdf_content_fallback_font(writer)
        _pdf_add_font_resource(content_owner, fallback_font_name, fallback_font_reference)
    replaced_items = _replace_pdf_operations(
        content_stream,
        replacement_provider,
        source_language,
        target_language,
        _pdf_font_resources(content_owner),
        static_font_name=static_font_name,
        fallback_font_name=fallback_font_name,
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
            static_font=static_font,
            source_font=source_font,
        )
    return replaced_items


def _replace_pdf_operations(
    content_stream: ContentStream,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    font_resources: dict[str, object],
    *,
    static_font_name: str | None = None,
    fallback_font_name: str | None = None,
) -> int:
    replaced_items = 0
    current_font: tuple[object, object] | None = None
    operations: list[tuple[list[object], bytes]] = []
    for operands, operator in content_stream.operations:
        if operator == b"Tf" and len(operands) >= 2:
            current_font = (operands[0], operands[1])
            operations.append((operands, operator))
            continue
        replacement_text: str | None = None
        string_indexes: tuple[int, ...]
        if operator == b"Tj" or operator == b"'":
            string_indexes = (0,)
        elif operator == b'"':
            string_indexes = (2,)
        elif operator == b"TJ":
            if operands and isinstance(operands[0], ArrayObject):
                replaced_operation = False
                used_fallback = False
                replacements: list[tuple[int, str]] = []
                for index, value in enumerate(operands[0]):
                    text = _pdf_text_operand_value(value, current_font, font_resources)
                    if text is not None:
                        replacement = _replace_native_text(text, replacement_provider, source_language, target_language)
                        if replacement == text:
                            continue
                        operand, needs_fallback = _pdf_replacement_text_operand(
                            replacement,
                            value,
                            current_font,
                            font_resources,
                            static_font_name,
                            fallback_font_name,
                        )
                        operands[0][index] = operand
                        replaced_items += 1
                        replaced_operation = True
                        used_fallback = used_fallback or needs_fallback
                        replacements.append((index, replacement))
                if used_fallback and fallback_font_name is not None and static_font_name is None:
                    for index, replacement in replacements:
                        operands[0][index] = _pdf_text_operand(replacement, fallback_font_name)
                replacement_text = "" if replaced_operation else None
            operation_font = static_font_name or (fallback_font_name if used_fallback else None)
            if replacement_text is not None and operation_font is not None:
                font_size = current_font[1] if current_font is not None else NumberObject(12)
                operations.append(([NameObject(f"/{operation_font}"), font_size], b"Tf"))
                operations.append((operands, operator))
                if current_font is not None:
                    operations.append(([current_font[0], current_font[1]], b"Tf"))
            else:
                operations.append((operands, operator))
            continue
        else:
            operations.append((operands, operator))
            continue
        used_fallback = False
        for index in string_indexes:
            if index >= len(operands):
                continue
            text = _pdf_text_operand_value(operands[index], current_font, font_resources)
            if text is not None:
                replacement = _replace_native_text(text, replacement_provider, source_language, target_language)
                if replacement == text:
                    continue
                operand, needs_fallback = _pdf_replacement_text_operand(
                    replacement,
                    operands[index],
                    current_font,
                    font_resources,
                    static_font_name,
                    fallback_font_name,
                )
                operands[index] = operand
                replaced_items += 1
                replacement_text = replacement
                used_fallback = used_fallback or needs_fallback
        operation_font = static_font_name or (fallback_font_name if replacement_text is not None and used_fallback else None)
        if replacement_text is not None and operation_font is not None:
            font_size = current_font[1] if current_font is not None else NumberObject(12)
            operations.append(([NameObject(f"/{operation_font}"), font_size], b"Tf"))
            operations.append((operands, operator))
            if current_font is not None:
                operations.append(([current_font[0], current_font[1]], b"Tf"))
        else:
            operations.append((operands, operator))
    content_stream.operations = operations
    return replaced_items


def _pdf_font_resources(content_owner: object) -> dict[str, object]:
    """Resolve the font resources usable by one page or Form XObject."""
    get_value = getattr(content_owner, "get", None)
    if not callable(get_value):
        return {}
    resources = get_value("/Resources")
    if resources is None:
        return {}
    fonts = resources.get_object().get("/Font")
    if fonts is None:
        return {}
    return {
        str(name): font.get_object()
        for name, font in fonts.get_object().items()
    }


def _pdf_text_operand_value(
    value: object,
    current_font: tuple[object, object] | None,
    font_resources: dict[str, object],
) -> str | None:
    """Decode a text-show operand, including Type0 glyph bytes with ToUnicode."""
    if not isinstance(value, (TextStringObject, ByteStringObject)):
        return None
    font = _pdf_composite_font(current_font, font_resources)
    if font is None:
        return str(value) if isinstance(value, TextStringObject) else None
    raw = _pdf_operand_bytes(value)
    if raw is None:
        return str(value) if isinstance(value, TextStringObject) else None
    try:
        return _pdf_decode_composite_bytes(raw, font)
    except (LookupError, UnicodeDecodeError, ValueError):
        return None


def _pdf_decode_composite_bytes(raw: bytes, font: DictionaryObject) -> str | None:
    """Decode one Type0 string using its actual ToUnicode code lengths."""
    cached = getattr(font, "_pipeline_tounicode_bytes", None)
    if cached is None:
        _encoding, character_map = get_encoding(font)
        codes: dict[bytes, str] = {}
        for character_code, unicode_text in character_map.items():
            for codec in ("latin-1", "utf-16-be"):
                try:
                    encoded = character_code.encode(codec, "surrogatepass")
                except UnicodeEncodeError:
                    continue
                if encoded:
                    codes.setdefault(encoded, unicode_text)
        cached = tuple(sorted(codes.items(), key=lambda item: len(item[0]), reverse=True))
        setattr(font, "_pipeline_tounicode_bytes", cached)
    result: list[str] = []
    cursor = 0
    while cursor < len(raw):
        match = next(
            ((code, value) for code, value in cached if raw.startswith(code, cursor)),
            None,
        )
        if match is None:
            return None
        code, value = match
        result.append(value)
        cursor += len(code)
    return "".join(result)


def _pdf_replacement_text_operand(
    text: str,
    source_value: object,
    current_font: tuple[object, object] | None,
    font_resources: dict[str, object],
    static_font_name: str | None,
    fallback_font_name: str | None,
) -> tuple[TextStringObject | ByteStringObject, bool]:
    """Encode a replacement for its source font, or select the safe fallback."""
    if static_font_name is not None:
        return _pdf_text_operand(text, static_font_name), False
    if (
        isinstance(source_value, TextStringObject)
        and _pdf_source_font_supports_text(text, current_font, font_resources)
    ):
        # pypdf already serializes ordinary PDF text strings in the source
        # content syntax. Retain the source face only when its ToUnicode map
        # confirms that the replacement characters have glyphs in the subset.
        return _pdf_text_operand(text, None), False
    if fallback_font_name is not None:
        # A Type0 font's ToUnicode map is a decoding aid, not a dependable
        # unicode-to-CID encoder.  Reversing it can select a blank glyph.
        return _pdf_text_operand(text, fallback_font_name), True
    return _pdf_text_operand(text, None), False


def _pdf_composite_font(
    current_font: tuple[object, object] | None,
    font_resources: dict[str, object],
) -> DictionaryObject | None:
    if current_font is None:
        return None
    font = font_resources.get(str(current_font[0]))
    if not isinstance(font, DictionaryObject) or font.get("/Subtype") != "/Type0":
        return None
    return font


def _pdf_source_font_supports_text(
    text: str,
    current_font: tuple[object, object] | None,
    font_resources: dict[str, object],
) -> bool:
    """Return whether an active simple font can safely show ``text``.

    A subsetted simple font can declare WinAnsi while omitting a glyph such as
    ``#``. Its ToUnicode map is the available evidence of the subset's glyphs.
    Composite Type0 fonts have no dependable Unicode-to-CID encoder here.
    """
    if current_font is None:
        return True
    font = font_resources.get(str(current_font[0]))
    if not isinstance(font, DictionaryObject):
        return True
    if font.get("/Subtype") == "/Type0":
        return False
    if font.get("/ToUnicode") is None:
        return True
    try:
        _encoding, character_map = get_encoding(font)
    except (LookupError, ValueError):
        return False
    supported_characters = {
        character
        for mapped_text in character_map.values()
        if isinstance(mapped_text, str)
        for character in mapped_text
    }
    return all(character in supported_characters for character in text)


def _pdf_operand_bytes(value: TextStringObject | ByteStringObject) -> bytes | None:
    if isinstance(value, ByteStringObject):
        return bytes(value)
    original_bytes = getattr(value, "original_bytes", None)
    return bytes(original_bytes) if isinstance(original_bytes, bytes) else None


def _pdf_text_operand(text: str, static_font_name: str | None) -> TextStringObject | ByteStringObject:
    if static_font_name is None:
        return TextStringObject(text)
    if static_font_name == "PipelineFallback":
        return ByteStringObject(text.encode("latin-1", "replace"))
    return ByteStringObject(_pdf_static_glyph_bytes(text))


def _pdf_static_glyph_bytes(text: str) -> bytes:
    _family, path = static_noto_font("sans-serif", False)
    typeface = skia.Typeface.MakeFromFile(str(path))
    if typeface is None:
        raise RuntimeError("Could not load the committed static Noto Sans face for PDF output.")
    return b"".join(glyph.to_bytes(2, "big") for glyph in skia.Font(typeface).textToGlyphs(text))


def _pdf_add_font_resource(content_owner: object, font_name: str, font_reference: object) -> None:
    get_value = getattr(content_owner, "get", None)
    if not callable(get_value):
        return
    resources = get_value("/Resources")
    if resources is None:
        resources_dictionary = DictionaryObject()
        set_value = getattr(content_owner, "__setitem__", None)
        if not callable(set_value):
            return
        set_value(NameObject("/Resources"), resources_dictionary)
    else:
        resources_dictionary = resources.get_object()
    fonts = resources_dictionary.get("/Font")
    if fonts is None:
        fonts = DictionaryObject()
        resources_dictionary[NameObject("/Font")] = fonts
    font_dictionary = fonts.get_object()
    if isinstance(font_dictionary, DictionaryObject):
        font_dictionary[NameObject(f"/{font_name}")] = font_reference


def _pdf_content_fallback_font(writer: PdfWriter) -> tuple[str, object]:
    """Return PDF's guaranteed ASCII face for arbitrary unbounded text runs.

    Page-content text has no reliably extractable rectangle or font encoding.
    The fallback is deliberately limited to the ASCII-safe replacement path
    (masking and redaction); bounded PDF containers continue to embed Noto.
    """
    name = "PipelineFallback"
    cached = getattr(writer, "_pipeline_content_fallback_font", None)
    if cached is None:
        cached = writer._add_object(DictionaryObject({
            NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Courier"), NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        }))
        setattr(writer, "_pipeline_content_fallback_font", cached)
    return name, cached
