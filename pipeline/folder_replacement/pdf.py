"""PDF-native visible-text replacement and fitting."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
from pathlib import Path
import re
import struct
from typing import cast
import warnings

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf._cmap import get_encoding
from pypdf.generic import (
    ArrayObject,
    ByteStringObject,
    BooleanObject,
    ContentStream,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    TextStringObject,
)
import skia  # type: ignore[import-not-found]

from pipeline.bounded_text_layout import (
    BoundedTextBox,
    BoundedTextParagraph,
    BoundedTextRun,
    PortableTextUnsupportedError,
    fitted_text_lines,
    noto_typefaces,
    replace_and_fit_text_box,
)
from pipeline.folder_replacement.bitmap import replace_image as _process_bitmap_image
from pipeline.folder_replacement.common import replace_native_text
from pipeline.ocr import OcrProvider
from pipeline.portable_fonts import static_noto_bytes, static_noto_font
from pipeline.runtime_assets import math_font_is_available, symbols_font_is_available
from pipeline.text_replacement import TextReplacementProvider


def _replace_native_text(
    text: str,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
) -> str:
    return replace_native_text(text, replacement_provider, source_language, target_language)


def _replace_image_text(
    image: Image.Image,
    ocr_provider: OcrProvider,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typeface: skia.Typeface,
) -> int:
    return _process_bitmap_image(
        image, ocr_provider, replacement_provider, source_language, target_language, typeface
    )


def pdf_work_total(source: Path) -> int:
    """Return the native-text plus embedded-raster work units in one PDF."""
    reader = PdfReader(source)
    image_references: set[int] = set()
    inline_image_count = 0
    for page in reader.pages:
        for image_file in page.images:
            reference = image_file.indirect_reference
            if reference is None:
                inline_image_count += 1
            else:
                image_references.add(reference.idnum)
    return len(reader.pages) + 1 + len(image_references) + inline_image_count


def replace_pdf_file(
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
    diagnostics: list[dict[str, object]] | None = None,
) -> tuple[int, int]:
    reader = PdfReader(source)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    native_items = 0
    seen_forms: set[int] = set()
    seen_annotations: set[int] = set()
    for page_index, page in enumerate(writer.pages, start=1):
        native_items += _replace_pdf_content_text(
            page,
            writer,
            replacement_provider,
            source_language,
            target_language,
            seen_forms,
            static_font=document_text_layout == "preserve-basic-layout",
            source_font=document_text_layout == "preserve-basic-layout-source-font",
            visual_layout=document_text_layout in {
                "preserve-basic-layout", "preserve-basic-layout-source-font"
            },
            page_index=page_index,
            diagnostics=diagnostics,
            container_kind="pdf_page_content",
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
        work_completed(f"native text page {page_index}/{len(writer.pages)}")
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
    work_completed("native form fields")
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
                measure_source_fonts=document_text_layout == "preserve-basic-layout-source-font",
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
            measure_source_fonts=document_text_layout == "preserve-basic-layout-source-font",
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
    measure_source_fonts: bool,
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
        measure_source_fonts=measure_source_fonts,
    )
    runs = fitted.text_box.paragraphs[0].runs
    run = runs[0]
    set_value(NameObject(key), TextStringObject("".join(item.text for item in runs)))
    font_size = run.font_size_points or size
    use_noto_output = embed_noto or len(runs) > 1 or not run.source_typefaces
    if use_noto_output:
        classifications = tuple(
            _pdf_portable_classification(item.font_classification)
            for item in runs
        )
        fonts = {
            classification: _pdf_embedded_noto_font(writer, classification, False)
            for classification in set(classifications)
        }
        font_name, _font_reference = fonts[classifications[0]]
        set_value(NameObject("/DA"), TextStringObject(f"/{font_name} {font_size:.4f} Tf 0 g"))
        _pdf_write_appearance_runs(dictionary, runs, fonts, bounds)
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
    """Create an Identity-H Type0 font with an explicit CID-to-glyph map."""
    family, _path = static_noto_font(classification, bold)
    resource_name = (
        "PipelineNotoMath"
        if classification == "math"
        else "PipelineNotoSymbols"
        if classification == "symbols"
        else "PipelineNotoBold" if bold else "PipelineNoto"
    )
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
    cid_to_gid = DecodedStreamObject()
    # CID zero is the required .notdef glyph.  Subsequent CIDs are allocated
    # as replacement Unicode characters are encountered.
    cid_to_gid.set_data(b"\x00\x00")
    descendant = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/CIDFontType2"),
        NameObject("/BaseFont"): NameObject(f"/{postscript_name}"),
        NameObject("/CIDSystemInfo"): DictionaryObject({NameObject("/Registry"): TextStringObject("Adobe"), NameObject("/Ordering"): TextStringObject("Identity"), NameObject("/Supplement"): NumberObject(0)}),
        NameObject("/FontDescriptor"): descriptor,
        NameObject("/CIDToGIDMap"): writer._add_object(cid_to_gid),
        NameObject("/DW"): NumberObject(1000),
    }))
    to_unicode = DecodedStreamObject()
    to_unicode.set_data(_pdf_static_tounicode_cmap({}))
    reference = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type0"),
        NameObject("/BaseFont"): NameObject(f"/{postscript_name}"), NameObject("/Encoding"): NameObject("/Identity-H"),
        NameObject("/DescendantFonts"): ArrayObject([descendant]),
        NameObject("/ToUnicode"): writer._add_object(to_unicode),
    }))
    type_zero = reference.get_object()
    setattr(type_zero, "_pipeline_static_tounicode", to_unicode)
    setattr(type_zero, "_pipeline_static_cid_by_character_glyph", {})
    setattr(type_zero, "_pipeline_static_unicode_by_cid", {})
    descendant_object = descendant.get_object()
    setattr(descendant_object, "_pipeline_static_cid_to_gid", cid_to_gid)
    setattr(descendant_object, "_pipeline_static_glyph_widths", {})
    setattr(descendant_object, "_pipeline_static_glyph_by_cid", {})
    setattr(descendant_object, "_pipeline_static_next_cid", 1)
    cached[key] = reference
    return resource_name, reference


def _pdf_portable_classification(classification: str) -> str:
    """Map shared run classifications to PDF's embeddable portable faces."""
    return classification if classification in {"math", "symbols"} else "sans-serif"


def _pdf_write_appearance(
    dictionary: object, font_name: str, font_reference: object, text: str,
    font_size: float, bounds: tuple[float, float], classification: str = "sans-serif",
) -> None:
    """Regenerate a simple clipped appearance with the embedded static face."""
    face = noto_typefaces()[classification]
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


def _pdf_write_appearance_runs(
    dictionary: object,
    runs: tuple[BoundedTextRun, ...],
    fonts: dict[str, tuple[str, object]],
    bounds: tuple[float, float],
) -> None:
    """Regenerate a simple appearance that can switch portable fonts per run."""
    width, height = bounds
    content = [
        f"q 0 0 {width:.4f} {height:.4f} re W n BT 0 g 0 {max(0.0, height - (runs[0].font_size_points or 12.0)):.4f} Td"
    ]
    resources = DictionaryObject()
    for run in runs:
        classification = _pdf_portable_classification(run.font_classification)
        font_name, font_reference = fonts[classification]
        encoded = _pdf_static_glyph_bytes(
            font_reference, run.text, classification
        ).hex().upper()
        content.append(
            f"/{font_name} {run.font_size_points or 12.0:.4f} Tf "
            f"<{encoded}> Tj"
        )
        resources[NameObject(f"/{font_name}")] = font_reference
    content.append("ET Q")
    appearance = DecodedStreamObject()
    appearance.set_data(" ".join(content).encode("ascii"))
    appearance.update({
        NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(width), NumberObject(height)]),
        NameObject("/Resources"): DictionaryObject({NameObject("/Font"): resources}),
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
    visual_layout: bool = False,
    page_index: int | None = None,
    diagnostics: list[dict[str, object]] | None = None,
    container_kind: str = "pdf_page_content",
) -> int:
    get_contents = getattr(content_owner, "get_contents", None)
    replace_contents = getattr(content_owner, "replace_contents", None)
    contents = get_contents() if callable(get_contents) else content_owner
    if contents is None:
        return 0
    content_stream = ContentStream(contents, writer)
    static_font_name: str | None = None
    static_font_reference: object | None = None
    fitted_static_fonts: dict[str, tuple[str, object]] = {}
    fallback_font_name: str | None = None
    if visual_layout:
        static_font_name, static_font_reference = _pdf_embedded_noto_font(
            writer, "sans-serif", False
        )
        fitted_static_fonts["sans-serif"] = (static_font_name, static_font_reference)
        _pdf_add_font_resource(content_owner, static_font_name, static_font_reference)
        if math_font_is_available():
            math_font_name, math_font_reference = _pdf_embedded_noto_font(
                writer, "math", False
            )
            fitted_static_fonts["math"] = (math_font_name, math_font_reference)
            _pdf_add_font_resource(content_owner, math_font_name, math_font_reference)
        if symbols_font_is_available():
            symbol_font_name, symbol_font_reference = _pdf_embedded_noto_font(
                writer, "symbols", False
            )
            fitted_static_fonts["symbols"] = (symbol_font_name, symbol_font_reference)
            _pdf_add_font_resource(content_owner, symbol_font_name, symbol_font_reference)
    elif static_font:
        static_font_name, static_font_reference = _pdf_content_fallback_font(writer)
        _pdf_add_font_resource(content_owner, static_font_name, static_font_reference)
    elif source_font:
        fallback_font_name, fallback_font_reference = _pdf_content_fallback_font(writer)
        _pdf_add_font_resource(content_owner, fallback_font_name, fallback_font_reference)
    font_resources = _pdf_font_resources(content_owner)
    properties = _pdf_property_resources(content_owner)
    if visual_layout and fitted_static_fonts:
        replaced_items = _replace_pdf_fitted_operations(
            content_stream,
            replacement_provider,
            source_language,
            target_language,
            font_resources,
            fitted_static_fonts,
            properties,
            source_font=source_font,
            page_index=page_index,
            diagnostics=diagnostics,
            container_kind=container_kind,
        )
    else:
        replaced_items = _replace_pdf_operations(
            content_stream,
            replacement_provider,
            source_language,
            target_language,
            font_resources,
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
            visual_layout=visual_layout,
            page_index=page_index,
            diagnostics=diagnostics,
            container_kind="pdf_form_xobject",
        )
    return replaced_items


@dataclass(frozen=True, slots=True)
class _PdfShownText:
    """One eligible PDF text-showing operation in page user space."""

    operation_index: int
    text_object_index: int
    text: str
    start: tuple[float, float]
    end: tuple[float, float]
    direction: tuple[float, float]
    normal: tuple[float, float]
    horizontal_stretch: float
    font_size: float
    graphics_context: int
    ctm: tuple[float, float, float, float, float, float]
    line_matrix: tuple[float, float, float, float, float, float]
    text_matrix_after: tuple[float, float, float, float, float, float]
    current_font: tuple[object, object] | None
    character_spacing: float
    word_spacing: float
    horizontal_scale: float
    text_rise: float
    text_rendering_mode: int


@dataclass(slots=True)
class _PdfActualTextScope:
    """One marked-content scope whose alternate text must be kept coherent."""

    begin_operation_index: int
    text_operation_indexes: set[int]
    source_text_by_operation: dict[int, str]
    location_by_operation: dict[int, dict[str, object]]
    has_ambiguous_content: bool = False


@dataclass(frozen=True, slots=True)
class _PdfVisualRegion:
    """A safely replaceable visual line or paragraph-like block."""

    operation_indexes: tuple[int, ...]
    text: str
    direction: tuple[float, float]
    normal: tuple[float, float]
    base_start: float
    top: float
    width: float
    height: float
    horizontal_stretch: float
    font_size: float
    alignment: str
    insertion_index: int
    ctm: tuple[float, float, float, float, float, float]
    anchor: _PdfShownText


_PDF_ACTUAL_TEXT_TEXT_ONLY_OPERATORS = frozenset({
    b"BT", b"ET", b"Tf", b"Tm", b"Td", b"TD", b"T*", b"TL", b"Tc", b"Tw",
    b"Tz", b"Ts", b"Tr", b"Tj", b"TJ", b"'", b'"', b"q", b"Q", b"cm", b"gs",
    b"w", b"J", b"j", b"M", b"d", b"ri", b"i", b"g", b"G", b"rg", b"RG",
    b"k", b"K", b"cs", b"CS", b"sc", b"SC", b"scn", b"SCN", b"BMC", b"BDC", b"EMC",
})


def _replace_pdf_fitted_operations(
    content_stream: ContentStream,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    font_resources: dict[str, object],
    static_fonts: dict[str, tuple[str, object]],
    properties: dict[str, object],
    *,
    source_font: bool,
    page_index: int | None = None,
    diagnostics: list[dict[str, object]] | None = None,
    container_kind: str = "pdf_page_content",
) -> int:
    """Replace eligible page text as visual lines or paragraph-like blocks.

    PDF content streams have drawing commands rather than text containers.  We
    therefore only fit regions which can be reconstructed from a complete,
    visible text object and leave everything else untouched.  The generated
    text stays inside that object's graphics state, preserving its colour,
    opacity, clipping, and surrounding painting operations.
    """
    operations = content_stream.operations
    text_object_ends: set[int] = set()
    inside_text = False
    text_object_index = -1
    current_font: tuple[object, object] | None = None
    line_matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    text_matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    leading = 0.0
    character_spacing = 0.0
    word_spacing = 0.0
    horizontal_scale = 1.0
    text_rise = 0.0
    text_rendering_mode = 0
    position_known = True
    shown: list[_PdfShownText] = []
    ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    graphics_stack: list[tuple[float, float, float, float, float, float]] = []
    graphics_context = 0
    barrier = 0
    marked_content_actual_text: list[int | None] = []
    actual_text_scopes: dict[int, _PdfActualTextScope] = {}

    for index, (operands, operator) in enumerate(operations):
        active_actual_text_scopes = tuple(
            scope_index for scope_index in marked_content_actual_text
            if scope_index is not None
        )
        if (
            active_actual_text_scopes
            and operator not in _PDF_ACTUAL_TEXT_TEXT_ONLY_OPERATORS
        ):
            for scope_index in active_actual_text_scopes:
                actual_text_scopes[scope_index].has_ambiguous_content = True
        if operator == b"BMC":
            for scope_index in active_actual_text_scopes:
                actual_text_scopes[scope_index].has_ambiguous_content = True
            marked_content_actual_text.append(None)
            continue
        if operator == b"BDC":
            for scope_index in active_actual_text_scopes:
                actual_text_scopes[scope_index].has_ambiguous_content = True
            marked_scope_index: int | None = None
            if _pdf_marked_content_has_actual_text(operands, properties):
                marked_scope_index = index
                actual_text_scopes[marked_scope_index] = _PdfActualTextScope(
                    index, set(), {}, {}
                )
            marked_content_actual_text.append(marked_scope_index)
            graphics_context += 1
            continue
        if operator == b"EMC":
            if not marked_content_actual_text:
                barrier += 1
            else:
                marked_content_actual_text.pop()
            graphics_context += 1
            continue
        if operator == b"q":
            graphics_stack.append(ctm)
            graphics_context += 1
            continue
        if operator == b"Q":
            if not graphics_stack:
                barrier += 1
                continue
            ctm = graphics_stack.pop()
            graphics_context += 1
            continue
        if operator == b"cm":
            if len(operands) < 6:
                barrier += 1
            else:
                ctm = _pdf_concat_matrices(ctm, _pdf_matrix(operands))
                graphics_context += 1
            continue
        if operator in _PDF_GRAPHICS_STATE_BOUNDARY_OPERATORS:
            graphics_context += 1
            continue
        if operator == b"BT":
            inside_text = True
            text_object_index = index
            line_matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
            text_matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
            position_known = True
            continue
        if operator == b"ET":
            if inside_text:
                text_object_ends.add(text_object_index)
            inside_text = False
            continue
        if not inside_text:
            # A non-text painting or path operation between text objects is a
            # conservative visual-region boundary.  Plain BT/ET separation is
            # deliberately handled above and remains eligible for grouping.
            graphics_context += 1
            continue
        if operator == b"Tf" and len(operands) >= 2:
            current_font = (operands[0], operands[1])
            continue
        if operator == b"Tm" and len(operands) >= 6:
            line_matrix = _pdf_matrix(operands)
            text_matrix = line_matrix
            position_known = True
            continue
        if operator == b"Td" and len(operands) >= 2:
            line_matrix = _pdf_translate_matrix(line_matrix, float(operands[0]), float(operands[1]))
            text_matrix = line_matrix
            # Text showing changes only the text matrix.  ``Td`` starts the
            # next source run from the independently tracked line matrix, so
            # it re-establishes a position after an earlier unknown advance.
            position_known = True
            continue
        if operator == b"TD" and len(operands) >= 2:
            leading = -float(operands[1])
            line_matrix = _pdf_translate_matrix(line_matrix, float(operands[0]), float(operands[1]))
            text_matrix = line_matrix
            position_known = True
            continue
        if operator == b"T*":
            line_matrix = _pdf_translate_matrix(line_matrix, 0.0, -leading)
            text_matrix = line_matrix
            position_known = True
            continue
        if operator == b"TL" and operands:
            leading = float(operands[0])
            continue
        if operator == b"Tc" and operands:
            character_spacing = float(operands[0])
            continue
        if operator == b"Tw" and operands:
            word_spacing = float(operands[0])
            continue
        if operator == b"Tz" and operands:
            horizontal_scale = float(operands[0]) / 100.0
            continue
        if operator == b"Ts" and operands:
            text_rise = float(operands[0])
            continue
        if operator == b"Tr" and operands:
            next_text_rendering_mode = int(float(operands[0]))
            if next_text_rendering_mode != text_rendering_mode:
                # Fill-only and fill-and-stroke text cannot share a fitted
                # output region, even when every other graphics-state value
                # is the same.
                graphics_context += 1
            text_rendering_mode = next_text_rendering_mode
            continue

        if operator == b"'":
            line_matrix = _pdf_translate_matrix(line_matrix, 0.0, -leading)
            text_matrix = line_matrix
            position_known = True
            values = (operands[0],) if operands else ()
        elif operator == b'"':
            if len(operands) < 3:
                barrier += 1
                position_known = False
                continue
            word_spacing = float(operands[0])
            character_spacing = float(operands[1])
            line_matrix = _pdf_translate_matrix(line_matrix, 0.0, -leading)
            text_matrix = line_matrix
            position_known = True
            values = (operands[2],)
        elif operator == b"Tj":
            values = (operands[0],) if operands else ()
        elif operator == b"TJ" and operands and isinstance(operands[0], ArrayObject):
            values = tuple(value for value in operands[0] if not isinstance(value, (int, float, NumberObject, FloatObject)))
        else:
            continue

        for scope_index in active_actual_text_scopes:
            actual_text_scopes[scope_index].text_operation_indexes.add(index)

        if text_rendering_mode not in {0, 2}:
            _record_pdf_retained_diagnostic(
                diagnostics,
                page_index,
                container_kind,
                "pdf_text_rendering_mode_ineligible",
                operator,
                _pdf_diagnostic_source_text(
                    values, operands, operator, current_font, font_resources,
                    character_spacing, word_spacing, horizontal_scale,
                ),
                _pdf_diagnostic_text_location(
                    text_matrix, ctm, current_font, horizontal_scale, text_rise
                )
                if position_known
                else None,
                f"PDF text rendering mode {text_rendering_mode} is not safely replaceable.",
            )
            barrier += 1
            position_known = False
            continue
        if not position_known:
            _record_pdf_retained_diagnostic(
                diagnostics,
                page_index,
                container_kind,
                "pdf_text_position_unknown",
                operator,
                _pdf_diagnostic_source_text(
                    values, operands, operator, current_font, font_resources,
                    character_spacing, word_spacing, horizontal_scale,
                ),
                None,
                "The source text position cannot be restored safely.",
            )
            barrier += 1
            position_known = False
            continue

        chunks, advance, valid = _pdf_shown_text_chunks(
            values,
            operands[0] if operator == b"TJ" and operands else None,
            current_font,
            font_resources,
            character_spacing,
            word_spacing,
            horizontal_scale,
        )
        if not valid:
            _record_pdf_retained_diagnostic(
                diagnostics,
                page_index,
                container_kind,
                "pdf_text_undecodable",
                operator,
                None,
                _pdf_diagnostic_text_location(
                    text_matrix, ctm, current_font, horizontal_scale, text_rise
                ),
                "The source font encoding could not be decoded safely.",
            )
            undecodable_advance = _pdf_undecodable_text_advance(
                values,
                operands[0] if operator == b"TJ" and operands else None,
                current_font,
                font_resources,
                character_spacing,
                word_spacing,
                horizontal_scale,
            )
            if undecodable_advance is not None:
                # Keep the source operation untouched, but preserve the text
                # position when its source CMap and widths establish a safe
                # advance.  The barrier prevents grouping across it.
                barrier += 1
                text_matrix = _pdf_translate_matrix(text_matrix, undecodable_advance, 0.0)
                continue
            barrier += 1
            position_known = False
            continue
        placement = _pdf_text_placement(text_matrix, ctm, current_font, horizontal_scale)
        if placement is None:
            _record_pdf_retained_diagnostic(
                diagnostics,
                page_index,
                container_kind,
                "pdf_text_placement_unsupported",
                operator,
                "".join(text for text, _start, _end in chunks),
                None,
                "The source text transform cannot be safely reconstructed.",
            )
            barrier += 1
            position_known = False
            continue
        direction, normal, effective_size, horizontal_stretch = placement
        text_matrix_after = _pdf_translate_matrix(text_matrix, advance, 0.0)
        source_text = "".join(text for text, _start, _end in chunks)
        location = _pdf_diagnostic_text_location(
            text_matrix, ctm, current_font, horizontal_scale, text_rise
        )
        for scope_index in active_actual_text_scopes:
            scope = actual_text_scopes[scope_index]
            scope.source_text_by_operation[index] = source_text
            if location is not None:
                scope.location_by_operation[index] = location
        for text, start_advance, end_advance in chunks:
            start = _pdf_transform_point(
                ctm, _pdf_transform_point(text_matrix, (start_advance, text_rise))
            )
            end = _pdf_transform_point(
                ctm, _pdf_transform_point(text_matrix, (end_advance, text_rise))
            )
            shown.append(_PdfShownText(
                index, text_object_index, text, start, end, direction, normal,
                horizontal_stretch, effective_size, graphics_context + barrier, ctm, line_matrix,
                text_matrix_after, current_font, character_spacing, word_spacing,
                horizontal_scale, text_rise, text_rendering_mode,
            ))
        # PDF advances are in text space.  The text matrix applies the
        # placement transform exactly once when deriving the next position.
        text_matrix = text_matrix_after

    candidate_regions = _pdf_visual_regions(shown, text_object_ends)

    def record_retained_actual_text_scope(scope: _PdfActualTextScope) -> None:
        first_operation_index = min(scope.text_operation_indexes)
        _record_pdf_retained_diagnostic(
            diagnostics,
            page_index,
            container_kind,
            "pdf_text_marked_content_actual_text",
            operations[first_operation_index][1],
            "".join(scope.source_text_by_operation.get(index, "") for index in sorted(scope.text_operation_indexes)) or None,
            scope.location_by_operation.get(first_operation_index),
            "Marked content supplies /ActualText and cannot be safely updated as a complete text-only scope.",
        )

    if not candidate_regions:
        for scope in actual_text_scopes.values():
            if scope.text_operation_indexes:
                record_retained_actual_text_scope(scope)
        return 0

    prepared_replacements: list[tuple[_PdfVisualRegion, list[tuple[list[object], bytes]]]] = []
    for region in candidate_regions:
        try:
            replacement = _pdf_fitted_region_operations(
                region,
                replacement_provider,
                source_language,
                target_language,
                static_fonts,
                font_resources,
                source_font,
            )
        except PortableTextUnsupportedError as error:
            if diagnostics is not None:
                diagnostics.append(
                    {
                        "source_text": region.text,
                        "replacement_text": error.replacement_text,
                        "kind": "unsupported",
                        "reason_code": error.reason_code,
                        "container_kind": "pdf_visual_text",
                        "page": page_index,
                        "candidate_faces": list(error.selected_faces),
                        "characters": error.characters,
                        "code_points": [f"U+{ord(character):04X}" for character in error.characters],
                        "region_location": _pdf_diagnostic_region_location(region),
                    }
                )
            continue
        except _PdfReplacementSerializationError as error:
            if diagnostics is not None:
                diagnostics.append(
                    {
                        "source_text": region.text,
                        "replacement_text": error.replacement_text,
                        "kind": "unsupported",
                        "reason_code": error.reason_code,
                        "container_kind": "pdf_visual_text",
                        "page": page_index,
                        "detail": error.detail,
                        "region_location": _pdf_diagnostic_region_location(region),
                    }
                )
            continue
        if replacement is None:
            _record_pdf_retained_diagnostic(
                diagnostics,
                page_index,
                container_kind,
                "pdf_visual_region_not_reconstructable",
                None,
                region.text,
                _pdf_diagnostic_region_location(region),
                "The visual text region cannot be safely reconstructed for replacement.",
            )
            continue
        prepared_replacements.append((region, replacement))

    if not prepared_replacements:
        for scope in actual_text_scopes.values():
            if scope.text_operation_indexes:
                record_retained_actual_text_scope(scope)
        return 0

    actual_text_scopes_by_operation: dict[int, set[int]] = {}
    for scope_index, scope in actual_text_scopes.items():
        for operation_index in scope.text_operation_indexes:
            actual_text_scopes_by_operation.setdefault(operation_index, set()).add(scope_index)

    def scopes_for_region(region: _PdfVisualRegion) -> set[int]:
        return set().union(
            *(actual_text_scopes_by_operation.get(index, set()) for index in region.operation_indexes)
        )

    def safely_rewritable_scope_indexes(
        permitted_operations: set[int],
    ) -> set[int]:
        return {
            scope_index
            for scope_index, scope in actual_text_scopes.items()
            if (
                scope.text_operation_indexes
                and not scope.has_ambiguous_content
                and scope.text_operation_indexes <= permitted_operations
                and _pdf_without_actual_text(operations[scope.begin_operation_index][0], properties)
                is not None
            )
        }

    successful_operations = {
        operation_index
        for region, _replacement in prepared_replacements
        for operation_index in region.operation_indexes
    }
    safe_actual_text_scopes = safely_rewritable_scope_indexes(successful_operations)
    while True:
        permitted_replacements = [
            (region, replacement)
            for region, replacement in prepared_replacements
            if scopes_for_region(region) <= safe_actual_text_scopes
        ]
        permitted_operations = {
            operation_index
            for region, _replacement in permitted_replacements
            for operation_index in region.operation_indexes
        }
        next_safe_actual_text_scopes = safely_rewritable_scope_indexes(permitted_operations)
        if next_safe_actual_text_scopes == safe_actual_text_scopes:
            break
        safe_actual_text_scopes = next_safe_actual_text_scopes

    for scope_index, scope in actual_text_scopes.items():
        if scope_index in safe_actual_text_scopes or not scope.text_operation_indexes:
            continue
        record_retained_actual_text_scope(scope)

    source_removals: set[int] = set()
    replacements_by_anchor: dict[int, list[list[tuple[list[object], bytes]]]] = {}
    for region, replacement in permitted_replacements:
        for operation_index in region.operation_indexes:
            # The fitted output restores the source text position with a
            # numeric TJ adjustment after it is painted.  Dropping the source
            # show operation therefore removes its selectable/source text
            # without changing subsequent page-content placement.
            source_removals.add(operation_index)
        replacements_by_anchor.setdefault(region.insertion_index, []).append(replacement)

    if not replacements_by_anchor:
        return 0

    updated: list[tuple[list[object], bytes]] = []
    replaced_items = 0
    for index, operation in enumerate(operations):
        operands, operator = operation
        if index in safe_actual_text_scopes:
            rewritten_operands = _pdf_without_actual_text(operands, properties)
            if rewritten_operands is None:
                raise ValueError("A validated PDF /ActualText property could not be rewritten.")
            updated.append((rewritten_operands, operator))
        elif index not in source_removals:
            updated.append(operation)
        for replacement in replacements_by_anchor.get(index, ()):
            updated.extend(replacement)
            replaced_items += 1
    content_stream.operations = updated
    return replaced_items


def _pdf_marked_content_has_actual_text(operands: list[object], properties: dict[str, object]) -> bool:
    """Return whether a BDC property supplies semantic alternate text."""
    if len(operands) < 2:
        return False
    property_value = operands[1]
    if isinstance(property_value, NameObject):
        property_value = properties.get(str(property_value))
    get_object = getattr(property_value, "get_object", None)
    dictionary = get_object() if callable(get_object) else property_value
    return isinstance(dictionary, DictionaryObject) and dictionary.get("/ActualText") is not None


def _pdf_without_actual_text(
    operands: list[object], properties: dict[str, object]
) -> list[object] | None:
    """Return one BDC operand list with its local alternate-text value removed.

    A named Properties entry may be shared by several BDC invocations.  Emit a
    direct copy instead of mutating that shared dictionary, so only the scope
    whose source text is replaced loses its stale semantic text.
    """
    if len(operands) < 2:
        return None
    property_value = operands[1]
    if isinstance(property_value, NameObject):
        property_value = properties.get(str(property_value))
    get_object = getattr(property_value, "get_object", None)
    dictionary = get_object() if callable(get_object) else property_value
    if not isinstance(dictionary, DictionaryObject) or dictionary.get("/ActualText") is None:
        return None
    rewritten_property = DictionaryObject({
        NameObject(str(key)): value
        for key, value in dictionary.items()
        if str(key) != "/ActualText"
    })
    return [*operands[:1], rewritten_property, *operands[2:]]


def _pdf_diagnostic_source_text(
    values: tuple[object, ...],
    operands: list[object],
    operator: bytes,
    current_font: tuple[object, object] | None,
    font_resources: dict[str, object],
    character_spacing: float,
    word_spacing: float,
    horizontal_scale: float,
) -> str | None:
    """Decode source text for a debug-only retained entry without replacement."""
    chunks, _advance, valid = _pdf_shown_text_chunks(
        values,
        operands[0] if operator == b"TJ" and operands else None,
        current_font,
        font_resources,
        character_spacing,
        word_spacing,
        horizontal_scale,
    )
    if not valid:
        return None
    text = "".join(item[0] for item in chunks)
    return text or None


def _pdf_diagnostic_text_location(
    text_matrix: tuple[float, float, float, float, float, float],
    ctm: tuple[float, float, float, float, float, float],
    current_font: tuple[object, object] | None,
    horizontal_scale: float,
    text_rise: float,
) -> dict[str, object] | None:
    """Return one known source-text anchor in PDF page user-space coordinates."""
    placement = _pdf_text_placement(text_matrix, ctm, current_font, horizontal_scale)
    if placement is None:
        return None
    _direction, normal, font_size, _stretch = placement
    x, y = _pdf_transform_point(ctm, _pdf_transform_point(text_matrix, (0.0, text_rise)))
    return {
        "coordinate_space": "pdf_page_user_space",
        "top_left": {
            "x": round(x + normal[0] * font_size * 0.8, 3),
            "y": round(y + normal[1] * font_size * 0.8, 3),
        },
    }


def _record_pdf_retained_diagnostic(
    diagnostics: list[dict[str, object]] | None,
    page_index: int | None,
    container_kind: str,
    reason_code: str,
    operator: bytes | None,
    source_text: str | None,
    location: dict[str, object] | None,
    detail: str,
) -> None:
    """Append one debug-only native-text safety decision without replacement."""
    if diagnostics is None:
        return
    entry: dict[str, object] = {
        "source_text": source_text,
        "kind": "retained",
        "reason_code": reason_code,
        "container_kind": container_kind,
        "page": page_index,
        "detail": detail,
    }
    if source_text is None:
        entry["source_text_status"] = "undecodable"
    if operator is not None:
        entry["operator"] = operator.decode("ascii")
    if location is not None:
        entry["region_location"] = location
    diagnostics.append(entry)


def _pdf_matrix(operands: list[object]) -> tuple[float, float, float, float, float, float]:
    return tuple(_pdf_float(operands[index]) for index in range(6))  # type: ignore[return-value]


def _pdf_float(value: object) -> float:
    """Read a numeric PDF operand without treating arbitrary objects as numbers."""
    if not isinstance(value, (int, float, NumberObject, FloatObject)):
        raise ValueError("Expected a numeric PDF content-stream operand.")
    return float(value)


def _pdf_translate_matrix(
    matrix: tuple[float, float, float, float, float, float], tx: float, ty: float
) -> tuple[float, float, float, float, float, float]:
    a, b, c, d, e, f = matrix
    return a, b, c, d, e + tx * a + ty * c, f + tx * b + ty * d


_PDF_GRAPHICS_STATE_BOUNDARY_OPERATORS = frozenset({
    b"g", b"G", b"rg", b"RG", b"k", b"K", b"cs", b"CS", b"sc", b"SC",
    b"scn", b"SCN", b"gs", b"w", b"J", b"j", b"M", b"d", b"W", b"W*", b"n",
})

# A PDF ``TJ`` array may place neighbouring table cells only a fraction of a
# font-size apart.  A half-size gap keeps ordinary kerning and word fragments
# together while preserving the separate fitted regions required for adjacent
# cells.
_PDF_VISUAL_CHUNK_GAP_FACTOR = 0.5


def _pdf_concat_matrices(
    outer: tuple[float, float, float, float, float, float],
    inner: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float, float, float]:
    """Return the matrix that applies ``inner`` then ``outer``."""
    oa, ob, oc, od, oe, of = outer
    ia, ib, ic, id, ie, if_ = inner
    return (
        oa * ia + oc * ib,
        ob * ia + od * ib,
        oa * ic + oc * id,
        ob * ic + od * id,
        oa * ie + oc * if_ + oe,
        ob * ie + od * if_ + of,
    )


def _pdf_transform_point(
    matrix: tuple[float, float, float, float, float, float], point: tuple[float, float]
) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    x, y = point
    return a * x + c * y + e, b * x + d * y + f


def _pdf_inverse_transform_point(
    matrix: tuple[float, float, float, float, float, float], point: tuple[float, float]
) -> tuple[float, float] | None:
    a, b, c, d, e, f = matrix
    determinant = a * d - b * c
    if abs(determinant) <= 1e-9:
        return None
    x, y = point
    return ((d * (x - e) - c * (y - f)) / determinant,
            (-b * (x - e) + a * (y - f)) / determinant)


def _pdf_text_placement(
    matrix: tuple[float, float, float, float, float, float],
    ctm: tuple[float, float, float, float, float, float],
    current_font: tuple[object, object] | None,
    horizontal_scale: float = 1.0,
) -> tuple[tuple[float, float], tuple[float, float], float, float] | None:
    """Return the placed axes, cross-axis size, and horizontal stretch.

    A PDF may apply independent horizontal and vertical scale factors through
    its text matrix and CTM. When the resulting axes are orthogonal, fitted
    output can retain that aspect ratio without accepting sheared text.
    """
    a, b = _pdf_transform_vector(ctm, (matrix[0], matrix[1]))
    c, d = _pdf_transform_vector(ctm, (matrix[2], matrix[3]))
    scale = math.hypot(a, b)
    normal_scale = math.hypot(c, d)
    if (
        not math.isfinite(scale)
        or not math.isfinite(normal_scale)
        or scale <= 1e-6
        or normal_scale <= 1e-6
        or not math.isfinite(horizontal_scale)
        or horizontal_scale <= 1e-6
    ):
        return None
    if abs(a * c + b * d) > scale * normal_scale * 0.01:
        return None
    font_size = _pdf_float(current_font[1]) if current_font is not None else 12.0
    if font_size <= 0.0:
        return None
    direction = (a / scale, b / scale)
    normal = (c / normal_scale, d / normal_scale)
    horizontal_stretch = scale * horizontal_scale / normal_scale
    if not math.isfinite(horizontal_stretch) or horizontal_stretch <= 1e-6:
        return None
    return direction, normal, font_size * normal_scale, horizontal_stretch


def _pdf_transform_vector(
    matrix: tuple[float, float, float, float, float, float], vector: tuple[float, float]
) -> tuple[float, float]:
    a, b, c, d, _e, _f = matrix
    x, y = vector
    return a * x + c * y, b * x + d * y


def _pdf_shown_text_chunks(
    values: tuple[object, ...],
    tj_array: object,
    current_font: tuple[object, object] | None,
    font_resources: dict[str, object],
    character_spacing: float,
    word_spacing: float,
    horizontal_scale: float,
) -> tuple[tuple[tuple[str, float, float], ...], float, bool]:
    """Decode a text-show operation into individually positioned text chunks.

    ``TJ`` arrays use numeric adjustments to position text fragments.  Those
    adjustments can represent ordinary kerning, but may also place separate
    table cells in one text-show operation.  Retaining each fragment's start
    and end advance lets visual-region grouping use the actual gap instead of
    flattening every fragment into one replacement string.
    """
    font_size = _pdf_float(current_font[1]) if current_font is not None else 12.0
    chunks: list[tuple[str, float, float]] = []
    advance = 0.0
    array_values = tuple(tj_array) if isinstance(tj_array, ArrayObject) else values
    for value in array_values:
        if isinstance(value, (int, float, NumberObject, FloatObject)):
            advance -= float(value) / 1000.0 * font_size * horizontal_scale
            continue
        # A TJ array may use an individually encoded whitespace glyph between
        # otherwise visible fragments.  It is safe to retain that glyph here:
        # it participates in the same known text advance and the replacement
        # provider preserves Unicode whitespace.  Treating it as undecodable
        # would leave the entire (selectable) TJ operation unchanged.
        decoded = _pdf_text_operand_value(
            value, current_font, font_resources, allow_whitespace=True
        )
        if decoded is None:
            return (), 0.0, False
        chunk_start = advance
        advance += _pdf_text_advance(
            value, decoded, current_font, font_resources, font_size, character_spacing,
            word_spacing, horizontal_scale,
        )
        if decoded:
            chunks.append((decoded, chunk_start, advance))
    return tuple(chunks), advance, True


def _pdf_array_object(value: object) -> ArrayObject | None:
    """Resolve a direct or indirect PDF array without changing its contents."""
    get_object = getattr(value, "get_object", None)
    resolved = get_object() if callable(get_object) else value
    return resolved if isinstance(resolved, ArrayObject) else None


def _pdf_text_advance(
    value: object,
    text: str,
    current_font: tuple[object, object] | None,
    font_resources: dict[str, object],
    font_size: float,
    character_spacing: float,
    word_spacing: float,
    horizontal_scale: float,
) -> float:
    raw = _pdf_operand_bytes(value) if isinstance(value, (TextStringObject, ByteStringObject)) else None
    font = font_resources.get(str(current_font[0])) if current_font is not None else None
    widths: list[float] = []
    if isinstance(font, DictionaryObject) and raw is not None and font.get("/Subtype") != "/Type0":
        first_character = int(font.get("/FirstChar", 0))
        declared_widths = font.get("/Widths")
        if isinstance(declared_widths, ArrayObject):
            widths = [
                float(declared_widths[code - first_character])
                if 0 <= code - first_character < len(declared_widths) else 500.0
                for code in raw
            ]
    elif isinstance(font, DictionaryObject) and raw is not None and font.get("/Subtype") == "/Type0":
        descendants = _pdf_array_object(font.get("/DescendantFonts"))
        if descendants:
            descendant = descendants[0].get_object()
            default_width = float(descendant.get("/DW", 1000))
            codes = _pdf_composite_codes(raw, font)
            cids = _pdf_type0_cids(codes, font) if codes else None
            if cids is None:
                cids = _pdf_embedded_identity_cids(raw, font)
            if cids is not None:
                widths = [_pdf_cid_width(descendant, cid, default_width) for cid in cids]
            else:
                # The source-code boundaries are known from ToUnicode, but an
                # unknown encoding CMap cannot safely be reversed into CIDs.
                # Retain the established /DW fallback rather than inventing
                # CIDs from decoded Unicode text.
                widths = [default_width] * len(codes)
    if not widths:
        face = noto_typefaces()["sans-serif"]
        widths = [
            skia.Font(face, font_size * 4.0 / 3.0).measureText(character) * 1000.0
            / max(1e-9, font_size * 4.0 / 3.0)
            for character in text
        ]
    spacing = character_spacing * max(0, len(text)) + word_spacing * text.count(" ")
    return (sum(widths) / 1000.0 * font_size + spacing) * horizontal_scale


def _pdf_undecodable_text_advance(
    values: tuple[object, ...],
    tj_array: object,
    current_font: tuple[object, object] | None,
    font_resources: dict[str, object],
    character_spacing: float,
    word_spacing: float,
    horizontal_scale: float,
) -> float | None:
    """Calculate an undecodable source operation's advance without guessing.

    This is intentionally separate from ``_pdf_text_advance``: no Unicode
    text is available, so a portable fallback face would make the subsequent
    source position speculative.
    """
    if current_font is None:
        return None
    font_size = _pdf_float(current_font[1])
    font = font_resources.get(str(current_font[0]))
    if font_size <= 0.0 or not isinstance(font, DictionaryObject):
        return None
    advance = 0.0
    array_values = tuple(tj_array) if isinstance(tj_array, ArrayObject) else values
    for value in array_values:
        if isinstance(value, (int, float, NumberObject, FloatObject)):
            advance -= float(value) / 1000.0 * font_size * horizontal_scale
            continue
        if not isinstance(value, (TextStringObject, ByteStringObject)):
            return None
        glyph_advance = _pdf_raw_text_advance(
            value,
            font,
            font_size,
            character_spacing,
            word_spacing,
            horizontal_scale,
        )
        if glyph_advance is None:
            return None
        advance += glyph_advance
    return advance


def _pdf_raw_text_advance(
    value: TextStringObject | ByteStringObject,
    font: DictionaryObject,
    font_size: float,
    character_spacing: float,
    word_spacing: float,
    horizontal_scale: float,
) -> float | None:
    """Return an advance directly from source codes and widths, if complete."""
    raw = _pdf_operand_bytes(value)
    if raw is None:
        return None
    if font.get("/Subtype") != "/Type0":
        first_character = int(font.get("/FirstChar", 0))
        declared_widths = font.get("/Widths")
        if not isinstance(declared_widths, ArrayObject):
            return None
        widths: list[float] = []
        for code in raw:
            width_index = code - first_character
            if not 0 <= width_index < len(declared_widths):
                return None
            width = declared_widths[width_index]
            if not isinstance(width, (int, float, NumberObject, FloatObject)):
                return None
            widths.append(float(width))
        code_values = tuple(raw)
    else:
        descendants = _pdf_array_object(font.get("/DescendantFonts"))
        if not descendants:
            return None
        descendant = descendants[0].get_object()
        if not isinstance(descendant, DictionaryObject):
            return None
        code_cids = _pdf_raw_type0_cids(raw, font)
        if code_cids is None:
            return None
        default_width = float(descendant.get("/DW", 1000))
        widths = [_pdf_cid_width(descendant, cid, default_width) for _code, cid in code_cids]
        code_values = tuple(int.from_bytes(code, "big") for code, _cid in code_cids)
    spacing = character_spacing * len(widths) + word_spacing * sum(
        code == 32 for code in code_values
    )
    return (sum(widths) / 1000.0 * font_size + spacing) * horizontal_scale


def _pdf_raw_type0_cids(raw: bytes, font: DictionaryObject) -> tuple[tuple[bytes, int], ...] | None:
    """Map every raw Type0 source code to a CID from its active encoding CMap."""
    encoding = font.get("/Encoding")
    encoding_object = encoding.get_object() if encoding is not None else None
    if str(encoding_object) in {"/Identity-H", "/Identity-V"}:
        recovered_cids = _pdf_embedded_identity_cids(raw, font)
        if recovered_cids is not None:
            if len(raw) == 1:
                return ((raw, recovered_cids[0]),)
            return tuple(
                (raw[index:index + 2], recovered_cids[index // 2])
                for index in range(0, len(raw), 2)
            )
        if len(raw) % 2:
            return None
        return tuple(
            (raw[index:index + 2], int.from_bytes(raw[index:index + 2], "big"))
            for index in range(0, len(raw), 2)
        )
    mappings = _pdf_cid_encoding_mappings(encoding_object)
    if mappings is None:
        return None
    result: list[tuple[bytes, int]] = []
    cursor = 0
    while cursor < len(raw):
        matches = [(code, cid) for code, cid in mappings.items() if raw.startswith(code, cursor)]
        if len(matches) != 1:
            return None
        code, cid = matches[0]
        result.append((code, cid))
        cursor += len(code)
    return tuple(result)


def _pdf_composite_codes(raw: bytes, font: DictionaryObject) -> tuple[bytes, ...]:
    cached = _pdf_tounicode_codes(font)
    codes: list[bytes] = []
    cursor = 0
    while cursor < len(raw):
        match = next((code for code, _value in cached if raw.startswith(code, cursor)), None)
        if match is None:
            return ()
        codes.append(match)
        cursor += len(match)
    return tuple(codes)


def _pdf_tounicode_codes(font: DictionaryObject) -> tuple[tuple[bytes, str], ...]:
    """Return the source-code boundaries established by the ToUnicode CMap."""
    cached = getattr(font, "_pipeline_tounicode_bytes", None)
    if cached is None:
        direct = _pdf_direct_tounicode_cmap(font)
        if direct is not None:
            cached = direct.mappings
        else:
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
    return cast(tuple[tuple[bytes, str], ...], cached)


def _pdf_type0_cids(codes: tuple[bytes, ...], font: DictionaryObject) -> tuple[int, ...] | None:
    """Map source character codes to CIDs without deriving CIDs from Unicode."""
    encoding = font.get("/Encoding")
    encoding_object = encoding.get_object() if encoding is not None else None
    if str(encoding_object) in {"/Identity-H", "/Identity-V"}:
        return tuple(int.from_bytes(code, "big") for code in codes)
    mappings = _pdf_cid_encoding_mappings(encoding_object)
    if mappings is None:
        return None
    result: list[int] = []
    for code in codes:
        cid = mappings.get(code)
        if cid is None:
            return None
        result.append(cid)
    return tuple(result)


def _pdf_cid_encoding_mappings(encoding: object) -> dict[bytes, int] | None:
    """Read explicit ``begincidchar`` and ``begincidrange`` mappings only."""
    get_data = getattr(encoding, "get_data", None)
    if not callable(get_data):
        return None
    try:
        data = bytes(get_data())
    except (TypeError, ValueError):
        return None
    mappings: dict[bytes, int] = {}
    for body in re.findall(rb"\bbegincidchar\b(.*?)\bendcidchar\b", data, re.DOTALL):
        for code, cid in re.findall(rb"<([0-9A-Fa-f]+)>\s+([0-9]+)", body):
            try:
                mappings[bytes.fromhex(code.decode("ascii"))] = int(cid)
            except ValueError:
                return None
    for body in re.findall(rb"\bbegincidrange\b(.*?)\bendcidrange\b", data, re.DOTALL):
        for first, last, base in re.findall(
            rb"<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>\s+([0-9]+)", body
        ):
            try:
                first_code = bytes.fromhex(first.decode("ascii"))
                last_code = bytes.fromhex(last.decode("ascii"))
                if len(first_code) != len(last_code):
                    return None
                first_value = int.from_bytes(first_code, "big")
                last_value = int.from_bytes(last_code, "big")
                if last_value < first_value or last_value - first_value > 65_535:
                    return None
                for value in range(first_value, last_value + 1):
                    mappings[value.to_bytes(len(first_code), "big")] = int(base) + value - first_value
            except ValueError:
                return None
    return mappings or None


def _pdf_cid_width(descendant: DictionaryObject, cid: int, default_width: float) -> float:
    """Resolve one CID's width from the PDF ``/W`` syntax."""
    declared_widths = _pdf_array_object(descendant.get("/W"))
    if declared_widths is None:
        return default_width
    index = 0
    while index < len(declared_widths):
        if not isinstance(declared_widths[index], (int, NumberObject)):
            return default_width
        first = int(declared_widths[index])
        index += 1
        if index >= len(declared_widths):
            return default_width
        second = declared_widths[index]
        index += 1
        if isinstance(second, ArrayObject):
            offset = cid - first
            if 0 <= offset < len(second) and isinstance(second[offset], (int, float, NumberObject, FloatObject)):
                return float(second[offset])
            continue
        if not isinstance(second, (int, NumberObject)) or index >= len(declared_widths):
            return default_width
        last = int(second)
        width = declared_widths[index]
        index += 1
        if first <= cid <= last and isinstance(width, (int, float, NumberObject, FloatObject)):
            return float(width)
    return default_width


def _pdf_visual_regions(
    shown: list[_PdfShownText], text_object_ends: set[int]
) -> tuple[_PdfVisualRegion, ...]:
    """Infer only geometry-compatible visual lines and paragraph blocks.

    Text objects are deliberately not grouping boundaries.  Paint-state
    changes and undecodable operations remain visual-region boundaries.
    """
    eligible = [item for item in shown if item.text_object_index in text_object_ends]
    by_context: dict[tuple[int, tuple[float, float, float, float, float, float]], list[_PdfShownText]] = {}
    for item in eligible:
        by_context.setdefault((item.graphics_context, item.ctm), []).append(item)

    regions: list[_PdfVisualRegion] = []
    for items in by_context.values():
        regions.extend(_pdf_regions_in_context(items, text_object_ends))
    return tuple(regions)


def _pdf_regions_in_context(
    shown: list[_PdfShownText], text_object_ends: set[int]
) -> tuple[_PdfVisualRegion, ...]:
    if not shown:
        return ()
    direction, normal = shown[0].direction, shown[0].normal
    if any(
        abs(item.direction[0] - direction[0]) > 0.01
        or abs(item.direction[1] - direction[1]) > 0.01
        for item in shown
    ):
        # Separate compatible orientations rather than allowing one unusual
        # item to suppress independently safe neighbours.
        direction_regions: list[_PdfVisualRegion] = []
        by_direction: dict[tuple[int, int], list[_PdfShownText]] = {}
        for item in shown:
            by_direction.setdefault((round(item.direction[0] * 100), round(item.direction[1] * 100)), []).append(item)
        for items in by_direction.values():
            direction_regions.extend(_pdf_regions_in_context(items, text_object_ends))
        return tuple(direction_regions)
    horizontal_stretch = shown[0].horizontal_stretch
    if any(
        abs(item.horizontal_stretch - horizontal_stretch)
        > max(item.horizontal_stretch, horizontal_stretch) * 0.01
        for item in shown
    ):
        by_stretch: list[list[_PdfShownText]] = []
        for item in shown:
            stretch_group = next(
                (candidate for candidate in by_stretch if abs(
                    item.horizontal_stretch - candidate[0].horizontal_stretch
                ) <= max(item.horizontal_stretch, candidate[0].horizontal_stretch) * 0.01),
                None,
            )
            if stretch_group is None:
                by_stretch.append([item])
            else:
                stretch_group.append(item)
        stretch_regions: list[_PdfVisualRegion] = []
        for items in by_stretch:
            stretch_regions.extend(_pdf_regions_in_context(items, text_object_ends))
        return tuple(stretch_regions)
    lines: list[list[_PdfShownText]] = []
    for item in sorted(shown, key=lambda value: (-_pdf_dot(value.start, normal), _pdf_dot(value.start, direction))):
        baseline = _pdf_dot(item.start, normal)
        line = next(
            (
                candidate for candidate in lines
                if abs(_pdf_dot(candidate[0].start, normal) - baseline)
                <= max(candidate[0].font_size, item.font_size) * 0.45
            ),
            None,
        )
        if line is None:
            lines.append([item])
        else:
            line.append(item)
    line_groups: list[list[_PdfShownText]] = []
    for line in lines:
        ordered = sorted(line, key=lambda value: _pdf_dot(value.start, direction))
        group: list[_PdfShownText] = []
        for item in ordered:
            if group:
                gap = _pdf_dot(item.start, direction) - _pdf_dot(group[-1].end, direction)
                if gap > max(group[-1].font_size, item.font_size) * _PDF_VISUAL_CHUNK_GAP_FACTOR:
                    line_groups.append(group)
                    group = []
            group.append(item)
        if group:
            line_groups.append(group)
    ordered_groups = sorted(line_groups, key=lambda group: (-_pdf_dot(group[0].start, normal), _pdf_dot(group[0].start, direction)))
    if _pdf_is_paragraph_like(ordered_groups, direction, normal):
        return (_pdf_make_visual_region(ordered_groups, direction, normal, True, text_object_ends),)
    return tuple(
        _pdf_make_visual_region((group,), direction, normal, False, text_object_ends)
        for group in ordered_groups
    )


def _pdf_is_paragraph_like(
    groups: list[list[_PdfShownText]], direction: tuple[float, float], normal: tuple[float, float]
) -> bool:
    if len(groups) < 2 or any(len(group) != 1 for group in groups):
        return False
    starts = [_pdf_dot(group[0].start, direction) for group in groups]
    sizes = [group[0].font_size for group in groups]
    if max(starts) - min(starts) > max(sizes):
        return False
    baselines = [_pdf_dot(group[0].start, normal) for group in groups]
    return all(
        0.4 * max(sizes[index - 1], sizes[index])
        <= baselines[index - 1] - baselines[index]
        <= 2.2 * max(sizes[index - 1], sizes[index])
        for index in range(1, len(baselines))
    )


def _pdf_make_visual_region(
    groups: tuple[list[_PdfShownText], ...] | list[list[_PdfShownText]],
    direction: tuple[float, float],
    normal: tuple[float, float],
    block: bool,
    text_object_ends: set[int],
) -> _PdfVisualRegion:
    ordered_groups = list(groups)
    items = [item for group in ordered_groups for item in group]
    starts = [_pdf_dot(item.start, direction) for item in items]
    ends = [_pdf_dot(item.end, direction) for item in items]
    baselines = [_pdf_dot(group[0].start, normal) for group in ordered_groups]
    size = max(item.font_size for item in items)
    text = "\n".join("".join(item.text for item in group) for group in ordered_groups)
    top = max(baselines) + size * 0.8
    bottom = min(baselines) - size * 0.4
    alignment = "left"
    if block:
        group_ends = [_pdf_dot(group[-1].end, direction) for group in ordered_groups]
        centres = [(start + end) / 2.0 for start, end in zip(
            [_pdf_dot(group[0].start, direction) for group in ordered_groups], group_ends
        )]
        if max(group_ends) - min(group_ends) <= size:
            alignment = "right"
        elif max(centres) - min(centres) <= size:
            alignment = "center"
    anchor = max(items, key=lambda item: item.operation_index)
    return _PdfVisualRegion(
        tuple(item.operation_index for item in items), text, direction, normal,
        min(starts), top, max(1.0, max(ends) - min(starts)), max(size * 1.2, top - bottom),
        items[0].horizontal_stretch,
        size, alignment,
        anchor.operation_index, anchor.ctm, anchor,
    )


def _pdf_dot(point: tuple[float, float], vector: tuple[float, float]) -> float:
    return point[0] * vector[0] + point[1] * vector[1]


def _pdf_diagnostic_region_location(region: _PdfVisualRegion) -> dict[str, object]:
    """Describe one retained region by its top-left PDF page user-space anchor."""
    return {
        "coordinate_space": "pdf_page_user_space",
        "top_left": {
            "x": round(
                region.direction[0] * region.base_start + region.normal[0] * region.top,
                3,
            ),
            "y": round(
                region.direction[1] * region.base_start + region.normal[1] * region.top,
                3,
            ),
        },
    }


def _pdf_fitted_region_operations(
    region: _PdfVisualRegion,
    replacement_provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    static_fonts: dict[str, tuple[str, object]],
    font_resources: dict[str, object],
    source_font: bool,
) -> list[tuple[list[object], bytes]] | None:
    restore_operations = _pdf_restore_source_text_state(region.anchor)
    if restore_operations is None:
        return None
    box = BoundedTextBox(
        round(region.width / region.horizontal_stretch * 12_700), round(region.height * 12_700), 0, 0, 0, 0, None,
        (BoundedTextParagraph(
            region.alignment, None, None, None, None, 0, None, None, None, None, None,
            (BoundedTextRun(
                region.text,
                _pdf_source_font_family(region.anchor.current_font, font_resources),
                "sans-serif",
                region.font_size,
                False,
                False,
                "none",
                None,
            ),),
        ),),
    )
    fitted = replace_and_fit_text_box(
        box,
        replacement_provider,
        source_language,
        target_language,
        noto_typefaces(),
        preserve_source_font_family=source_font,
        measure_source_fonts=source_font,
    )
    replacement_text = "".join(
        run.text for paragraph in fitted.text_box.paragraphs for run in paragraph.runs
    )
    output_runs = fitted.text_box.paragraphs[0].runs
    output_run = output_runs[0]
    source_output = (
        source_font
        and len(output_runs) == 1
        and bool(output_run.source_typefaces)
        and _pdf_source_font_supports_text(
            replacement_text, region.anchor.current_font, font_resources
        )
    )
    static_classifications = tuple(
        _pdf_portable_classification(run.font_classification)
        for run in output_runs
    )
    if not source_output and any(
        static_fonts.get(classification) is None
        or not _pdf_static_font_supports_text(run.text, classification)
        for run, classification in zip(output_runs, static_classifications, strict=True)
    ):
        unsupported_text = "".join(
            run.text
            for run, classification in zip(output_runs, static_classifications, strict=True)
            if (
                static_fonts.get(classification) is None
                or not _pdf_static_font_supports_text(run.text, classification)
            )
        )
        selected_faces = tuple(
            dict.fromkeys(
                "Noto Sans Math" if classification == "math"
                else "Noto Sans Symbols 2" if classification == "symbols"
                else "Noto Sans"
                for classification in static_classifications
            )
        )
        raise PortableTextUnsupportedError(
            "portable_font_coverage_unsupported",
            unsupported_text,
            selected_faces,
            replacement_text=replacement_text,
        )
    if fitted.fit_status == "overflow":
        warnings.warn(
            "A PDF visual text region overflowed at the minimum readable font size.",
            RuntimeWarning,
            stacklevel=2,
        )
    font_size = output_run.font_size_points or region.font_size
    cursor = region.top - font_size * 0.8
    result: list[tuple[list[object], bytes]] = []
    result.extend((
        ([NumberObject(0)], b"Tc"),
        ([NumberObject(0)], b"Tw"),
        ([NumberObject(100)], b"Tz"),
        ([NumberObject(0)], b"Ts"),
        # A source fill-and-stroke outline is not portable font-weight
        # information.  The replacement retains its fill paint state but uses
        # the predictable fill-only presentation required by FR-2026-08-23-03.
        ([NumberObject(0)], b"Tr"),
    ))
    if source_output and region.anchor.current_font is not None:
        result.append(
            ([region.anchor.current_font[0], FloatObject(font_size)], b"Tf")
        )
        active_static_font: tuple[str, float] | None = None
    elif static_classifications:
        initial_font = static_fonts.get(static_classifications[0])
        if initial_font is None:
            return None
        result.append(
            ([NameObject(f"/{initial_font[0]}"), FloatObject(font_size)], b"Tf")
        )
        active_static_font = (initial_font[0], font_size)
    else:
        active_static_font = None
    for line in fitted_text_lines(fitted):
        if not line.text:
            cursor -= line.height_pixels * 0.75
            continue
        width = line.width_pixels * 0.75 * region.horizontal_stretch
        offset = 0.0
        if region.alignment == "right":
            offset = max(0.0, region.width - width)
        elif region.alignment == "center":
            offset = max(0.0, (region.width - width) / 2.0)
        x = region.direction[0] * (region.base_start + offset) + region.normal[0] * cursor
        y = region.direction[1] * (region.base_start + offset) + region.normal[1] * cursor
        local_origin = _pdf_inverse_transform_point(region.ctm, (x, y))
        local_direction_end = _pdf_inverse_transform_point(
            region.ctm, (x + region.direction[0], y + region.direction[1])
        )
        local_normal_end = _pdf_inverse_transform_point(
            region.ctm, (x + region.normal[0], y + region.normal[1])
        )
        if local_origin is None or local_direction_end is None or local_normal_end is None:
            return None
        local_direction = (
            local_direction_end[0] - local_origin[0],
            local_direction_end[1] - local_origin[1],
        )
        local_normal = (
            local_normal_end[0] - local_origin[0],
            local_normal_end[1] - local_origin[1],
        )
        local_direction = (
            local_direction[0] * region.horizontal_stretch,
            local_direction[1] * region.horizontal_stretch,
        )
        result.append(
            ([FloatObject(local_direction[0]), FloatObject(local_direction[1]),
              FloatObject(local_normal[0]), FloatObject(local_normal[1]),
              FloatObject(local_origin[0]), FloatObject(local_origin[1])], b"Tm")
        )
        if source_output:
            result.append(([_pdf_text_operand(line.text, None, "sans-serif")], b"Tj"))
        else:
            for segment in line.segments:
                classification = (
                    _pdf_portable_classification(segment.font_classification)
                )
                static_font = static_fonts.get(classification)
                if static_font is None:
                    return None
                font_name, font_reference = static_font
                encoded_text = _pdf_static_glyph_bytes(
                    font_reference, segment.text, classification
                )
                selected_font = (font_name, segment.font_size_points)
                if selected_font != active_static_font:
                    result.append(
                        ([NameObject(f"/{font_name}"), FloatObject(segment.font_size_points)], b"Tf")
                    )
                    active_static_font = selected_font
                result.append(([ByteStringObject(encoded_text)], b"Tj"))
        cursor -= line.height_pixels * 0.75
    result.extend(restore_operations)
    return result


def _pdf_restore_source_text_state(
    anchor: _PdfShownText,
) -> list[tuple[list[object], bytes]] | None:
    """Restore the source text state without changing its text-line matrix.

    A generated ``Tm`` changes both PDF text matrices.  Restoring only the
    post-source text matrix would therefore break a later ``T*``.  Set the
    original line matrix, then invisibly replay its horizontal advance with
    ``TJ`` so the source text matrix and text-line matrix both match their
    original values.
    """
    if anchor.current_font is None or abs(anchor.horizontal_scale) <= 1e-9:
        return None
    font_size = _pdf_float(anchor.current_font[1])
    if font_size <= 0.0:
        return None
    text_advance = _pdf_matrix_translation_delta(anchor.line_matrix, anchor.text_matrix_after)
    if text_advance is None or abs(text_advance[1]) > 1e-6:
        return None
    tj_adjustment = -text_advance[0] * 1000.0 / (font_size * anchor.horizontal_scale)
    return [
        ([anchor.current_font[0], anchor.current_font[1]], b"Tf"),
        ([FloatObject(anchor.character_spacing)], b"Tc"),
        ([FloatObject(anchor.word_spacing)], b"Tw"),
        ([FloatObject(anchor.horizontal_scale * 100.0)], b"Tz"),
        ([FloatObject(anchor.text_rise)], b"Ts"),
        ([FloatObject(value) for value in anchor.line_matrix], b"Tm"),
        ([NumberObject(3)], b"Tr"),
        ([ArrayObject([FloatObject(tj_adjustment)])], b"TJ"),
        ([NumberObject(anchor.text_rendering_mode)], b"Tr"),
    ]


def _pdf_matrix_translation_delta(
    matrix: tuple[float, float, float, float, float, float],
    translated: tuple[float, float, float, float, float, float],
) -> tuple[float, float] | None:
    """Return the text-space translation from ``matrix`` to ``translated``."""
    a, b, c, d, e, f = matrix
    determinant = a * d - b * c
    if abs(determinant) <= 1e-9:
        return None
    delta_x = translated[4] - e
    delta_y = translated[5] - f
    return (
        (d * delta_x - c * delta_y) / determinant,
        (-b * delta_x + a * delta_y) / determinant,
    )


class _PdfReplacementSerializationError(ValueError):
    """A portable PDF replacement cannot be encoded without semantic loss."""

    def __init__(self, reason_code: str, detail: str, replacement_text: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail
        self.replacement_text = replacement_text


def _pdf_static_glyph_bytes(
    font_reference: object, text: str, classification: str = "sans-serif"
) -> bytes:
    """Encode text with unique CIDs even where font glyphs are shared.

    A font may draw two Unicode whitespace characters with one glyph.  CIDs
    must nevertheless remain distinct so the generated `/ToUnicode` map can
    make copy, search, and extraction return the provider's exact text.
    """
    get_object = getattr(font_reference, "get_object", None)
    type_zero = get_object() if callable(get_object) else font_reference
    descendants = type_zero.get("/DescendantFonts") if isinstance(type_zero, DictionaryObject) else None
    if not isinstance(descendants, ArrayObject) or not descendants:
        raise _PdfReplacementSerializationError(
            "pdf_replacement_font_encoding_invalid",
            "The embedded PDF replacement font has no CID descendant.",
            text,
        )
    descendant = descendants[0].get_object()
    if not isinstance(descendant, DictionaryObject):
        raise _PdfReplacementSerializationError(
            "pdf_replacement_font_encoding_invalid",
            "The embedded PDF replacement font has an invalid CID descendant.",
            text,
        )
    cid_by_character_glyph = getattr(type_zero, "_pipeline_static_cid_by_character_glyph", None)
    unicode_by_cid = getattr(type_zero, "_pipeline_static_unicode_by_cid", None)
    widths = getattr(descendant, "_pipeline_static_glyph_widths", None)
    glyph_by_cid = getattr(descendant, "_pipeline_static_glyph_by_cid", None)
    cid_to_gid = getattr(descendant, "_pipeline_static_cid_to_gid", None)
    next_cid = getattr(descendant, "_pipeline_static_next_cid", None)
    if not all(isinstance(value, dict) for value in (
        cid_by_character_glyph, unicode_by_cid, widths, glyph_by_cid
    )) or not isinstance(cid_to_gid, DecodedStreamObject) or not isinstance(next_cid, int):
        raise _PdfReplacementSerializationError(
            "pdf_replacement_font_encoding_invalid",
            "The embedded PDF replacement font has no writable CID mapping.",
            text,
        )
    cid_by_character_glyph = cast(dict[tuple[str, int], int], cid_by_character_glyph)
    unicode_by_cid = cast(dict[int, str], unicode_by_cid)
    widths = cast(dict[int, int], widths)
    glyph_by_cid = cast(dict[int, int], glyph_by_cid)
    # The shared layout face cache also prevents each PDF region from reopening
    # the optional Symbols 2 file while constructing CID metadata.
    font = skia.Font(noto_typefaces()[classification], 1000.0)
    glyphs = font.textToGlyphs(text)
    if len(glyphs) != len(text):
        raise _PdfReplacementSerializationError(
            "pdf_replacement_font_glyph_encoding_unavailable",
            "The portable replacement font did not produce one glyph per replacement character.",
            text,
        )
    encoded = bytearray()
    for character, glyph, width in zip(text, glyphs, font.getWidths(glyphs)):
        glyph_id = int(glyph)
        if glyph_id == 0:
            raise _PdfReplacementSerializationError(
                "pdf_replacement_font_glyph_encoding_unavailable",
                "The portable replacement font does not contain a replacement glyph.",
                text,
            )
        key = (character, glyph_id)
        cid = cid_by_character_glyph.get(key)
        if cid is None:
            if next_cid > 0xFFFF:
                raise _PdfReplacementSerializationError(
                    "pdf_replacement_font_cid_capacity_exceeded",
                    "The portable replacement font exhausted its 16-bit CID space.",
                    text,
                )
            cid = next_cid
            next_cid += 1
            cid_by_character_glyph[key] = cid
            unicode_by_cid[cid] = character
            glyph_by_cid[cid] = glyph_id
            widths[cid] = round(float(width))
        encoded.extend(cid.to_bytes(2, "big"))
    setattr(descendant, "_pipeline_static_next_cid", next_cid)
    encoded_widths = ArrayObject()
    for cid, width in sorted(widths.items()):
        encoded_widths.append(NumberObject(cid))
        encoded_widths.append(ArrayObject([NumberObject(width)]))
    descendant[NameObject("/W")] = encoded_widths
    cid_to_gid.set_data(
        b"".join(
            glyph_by_cid.get(cid, 0).to_bytes(2, "big")
            for cid in range(max(glyph_by_cid, default=0) + 1)
        )
    )
    to_unicode = getattr(type_zero, "_pipeline_static_tounicode", None)
    if not isinstance(to_unicode, DecodedStreamObject):
        raise _PdfReplacementSerializationError(
            "pdf_replacement_font_encoding_invalid",
            "The embedded PDF replacement font has no ToUnicode stream.",
            text,
        )
    to_unicode.set_data(_pdf_static_tounicode_cmap(unicode_by_cid))
    return bytes(encoded)


def _pdf_static_tounicode_cmap(unicode_by_cid: dict[int, str]) -> bytes:
    """Encode an Adobe-Identity ToUnicode CMap for the generated static font."""
    entries = [
        f"<{cid:04X}> <{text.encode('utf-16-be').hex().upper()}>"
        for cid, text in sorted(unicode_by_cid.items())
    ]
    chunks = [entries[index:index + 100] for index in range(0, len(entries), 100)]
    body = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /Adobe-Identity-UCS def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        "<0000> <FFFF>",
        "endcodespacerange",
    ]
    for chunk in chunks:
        body.append(f"{len(chunk)} beginbfchar")
        body.extend(chunk)
        body.append("endbfchar")
    body.extend((
        "endcmap",
        "CMapName currentdict /CMap defineresource pop",
        "end",
        "end",
    ))
    return ("\n".join(body) + "\n").encode("ascii")


def _pdf_static_font_supports_text(text: str, classification: str = "sans-serif") -> bool:
    _family, path = static_noto_font(classification, False)
    typeface = skia.Typeface.MakeFromFile(str(path))
    if typeface is None:
        raise RuntimeError("Could not load the committed static Noto Sans face for PDF output.")
    font = skia.Font(typeface)
    for character in text:
        if character.isspace():
            continue
        glyphs = font.textToGlyphs(character)
        if not glyphs or int(glyphs[0]) == 0:
            return False
    return True


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


def _pdf_source_font_family(
    current_font: tuple[object, object] | None, font_resources: dict[str, object]
) -> str | None:
    """Return a concrete source-family request without trusting a PDF subset tag."""
    if current_font is None:
        return None
    font = font_resources.get(str(current_font[0]))
    if not isinstance(font, DictionaryObject):
        return None
    base_font = font.get("/BaseFont")
    if not isinstance(base_font, NameObject):
        return None
    family = str(base_font).lstrip("/")
    subset, separator, remainder = family.partition("+")
    if separator and len(subset) == 6 and subset.isupper():
        family = remainder
    return family or None


def _pdf_property_resources(content_owner: object) -> dict[str, object]:
    """Resolve named marked-content property dictionaries for one content scope."""
    get_value = getattr(content_owner, "get", None)
    if not callable(get_value):
        return {}
    resources = get_value("/Resources")
    if resources is None:
        return {}
    properties = resources.get_object().get("/Properties")
    if properties is None:
        return {}
    return {
        str(name): value.get_object()
        for name, value in properties.get_object().items()
    }


def _pdf_text_operand_value(
    value: object,
    current_font: tuple[object, object] | None,
    font_resources: dict[str, object],
    *,
    allow_whitespace: bool = False,
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
        return _pdf_decode_composite_bytes(raw, font, allow_whitespace=allow_whitespace)
    except (LookupError, UnicodeDecodeError, ValueError):
        return None


def _pdf_decode_composite_bytes(
    raw: bytes, font: DictionaryObject, *, allow_whitespace: bool = False
) -> str | None:
    """Decode one Type0 string without accepting a whitespace-only false map."""
    decoded = _pdf_decode_direct_tounicode_bytes(raw, font)
    if decoded is None:
        decoded = _pdf_decode_tounicode_bytes(raw, font)
    if decoded is not None and (allow_whitespace or not decoded.isspace()):
        return decoded
    recovered = _pdf_decode_embedded_identity_bytes(raw, font)
    if recovered is not None:
        return recovered
    # A visible string whose only available mapping is whitespace is unsafe as
    # replacement input.  Leave it unchanged rather than emit invisible text.
    return None


@dataclass(frozen=True, slots=True)
class _PdfToUnicodeCMap:
    code_spaces: tuple[tuple[bytes, bytes], ...]
    mappings: tuple[tuple[bytes, str], ...]


_PDF_CMAP_TOKEN = re.compile(r"<[0-9A-Fa-f\s]+>|\[|\]|[^\s\[\]<>]+")


def _pdf_direct_tounicode_cmap(font: DictionaryObject) -> _PdfToUnicodeCMap | None:
    """Parse the document's ToUnicode CMap without pypdf's font helper."""
    cache_attribute = "_pipeline_direct_tounicode_cmap"
    cached = getattr(font, cache_attribute, None)
    if cached is not None:
        return cast(_PdfToUnicodeCMap | None, cached)
    reference = font.get("/ToUnicode")
    stream = reference.get_object() if reference is not None else None
    get_data = getattr(stream, "get_data", None)
    if not callable(get_data):
        setattr(font, cache_attribute, None)
        return None
    try:
        tokens = _PDF_CMAP_TOKEN.findall(bytes(get_data()).decode("latin-1"))
        code_spaces, mappings = _pdf_parse_tounicode_cmap(tokens)
    except (TypeError, UnicodeDecodeError, ValueError):
        setattr(font, cache_attribute, None)
        return None
    if not mappings:
        setattr(font, cache_attribute, None)
        return None
    result = _PdfToUnicodeCMap(
        tuple(code_spaces),
        tuple(sorted(mappings.items(), key=lambda item: len(item[0]), reverse=True)),
    )
    setattr(font, cache_attribute, result)
    return result


def _pdf_parse_tounicode_cmap(
    tokens: list[str],
) -> tuple[list[tuple[bytes, bytes]], dict[bytes, str]]:
    """Parse the supported codespace, bfchar, and bfrange CMap constructs."""
    code_spaces: list[tuple[bytes, bytes]] = []
    mappings: dict[bytes, str] = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "begincodespacerange":
            index = _pdf_parse_codespace_range(tokens, index + 1, code_spaces)
        elif token == "beginbfchar":
            index = _pdf_parse_bfchar(tokens, index + 1, mappings)
        elif token == "beginbfrange":
            index = _pdf_parse_bfrange(tokens, index + 1, mappings)
        else:
            index += 1
    if code_spaces:
        for code in mappings:
            if not any(
                len(code) == len(start) and start <= code <= end
                for start, end in code_spaces
            ):
                raise ValueError("A ToUnicode mapping lies outside its codespace range.")
    return code_spaces, mappings


def _pdf_parse_codespace_range(
    tokens: list[str], index: int, code_spaces: list[tuple[bytes, bytes]]
) -> int:
    while index < len(tokens) and tokens[index] != "endcodespacerange":
        if index + 1 >= len(tokens):
            raise ValueError("An incomplete ToUnicode codespace range was encountered.")
        start = _pdf_cmap_hex_bytes(tokens[index])
        end = _pdf_cmap_hex_bytes(tokens[index + 1])
        if len(start) != len(end) or start > end:
            raise ValueError("An invalid ToUnicode codespace range was encountered.")
        code_spaces.append((start, end))
        index += 2
    return index + 1


def _pdf_parse_bfchar(tokens: list[str], index: int, mappings: dict[bytes, str]) -> int:
    while index < len(tokens) and tokens[index] != "endbfchar":
        if index + 1 >= len(tokens):
            raise ValueError("An incomplete ToUnicode bfchar entry was encountered.")
        _pdf_add_tounicode_mapping(
            mappings, _pdf_cmap_hex_bytes(tokens[index]), _pdf_cmap_unicode(tokens[index + 1])
        )
        index += 2
    return index + 1


def _pdf_parse_bfrange(tokens: list[str], index: int, mappings: dict[bytes, str]) -> int:
    while index < len(tokens) and tokens[index] != "endbfrange":
        if index + 2 >= len(tokens):
            raise ValueError("An incomplete ToUnicode bfrange entry was encountered.")
        start = _pdf_cmap_hex_bytes(tokens[index])
        end = _pdf_cmap_hex_bytes(tokens[index + 1])
        if len(start) != len(end) or start > end:
            raise ValueError("An invalid ToUnicode bfrange was encountered.")
        index += 2
        if tokens[index] == "[":
            index += 1
            source = int.from_bytes(start, "big")
            final = int.from_bytes(end, "big")
            while source <= final:
                if index >= len(tokens) or tokens[index] == "]":
                    raise ValueError("A ToUnicode bfrange array is too short.")
                _pdf_add_tounicode_mapping(
                    mappings, source.to_bytes(len(start), "big"), _pdf_cmap_unicode(tokens[index])
                )
                source += 1
                index += 1
            if index >= len(tokens) or tokens[index] != "]":
                raise ValueError("A ToUnicode bfrange array is malformed.")
            index += 1
            continue
        destination = _pdf_cmap_hex_bytes(tokens[index])
        if len(destination) % 2 or not destination:
            raise ValueError("A ToUnicode bfrange destination is invalid.")
        for source in range(int.from_bytes(start, "big"), int.from_bytes(end, "big") + 1):
            value = int.from_bytes(destination, "big") + source - int.from_bytes(start, "big")
            mapped = value.to_bytes(len(destination), "big")
            _pdf_add_tounicode_mapping(
                mappings, source.to_bytes(len(start), "big"), _pdf_cmap_unicode_bytes(mapped)
            )
        index += 1
    return index + 1


def _pdf_cmap_hex_bytes(token: str) -> bytes:
    if not token.startswith("<") or not token.endswith(">"):
        raise ValueError("Expected a hexadecimal CMap token.")
    hex_text = "".join(token[1:-1].split())
    if not hex_text or len(hex_text) % 2:
        raise ValueError("An invalid hexadecimal CMap token was encountered.")
    return bytes.fromhex(hex_text)


def _pdf_cmap_unicode(token: str) -> str:
    return _pdf_cmap_unicode_bytes(_pdf_cmap_hex_bytes(token))


def _pdf_cmap_unicode_bytes(value: bytes) -> str:
    if len(value) % 2:
        raise ValueError("A ToUnicode destination must use UTF-16BE code units.")
    text = value.decode("utf-16-be")
    return text.removeprefix("\ufeff")


def _pdf_add_tounicode_mapping(mappings: dict[bytes, str], code: bytes, text: str) -> None:
    existing = mappings.get(code)
    if existing is not None and existing != text:
        raise ValueError("A ToUnicode CMap maps one source code ambiguously.")
    mappings[code] = text


def _pdf_decode_direct_tounicode_bytes(raw: bytes, font: DictionaryObject) -> str | None:
    cmap = _pdf_direct_tounicode_cmap(font)
    if cmap is None:
        return None
    result: list[str] = []
    cursor = 0
    while cursor < len(raw):
        matches = [
            (code, value)
            for code, value in cmap.mappings
            if raw.startswith(code, cursor)
            and (not cmap.code_spaces or any(
                len(code) == len(start) and start <= code <= end
                for start, end in cmap.code_spaces
            ))
        ]
        if not matches:
            return None
        code, value = matches[0]
        if len(matches) > 1 and len(matches[1][0]) == len(code):
            return None
        result.append(value)
        cursor += len(code)
    return "".join(result)


def _pdf_decode_tounicode_bytes(raw: bytes, font: DictionaryObject) -> str | None:
    """Decode source bytes only when the source ``/ToUnicode`` CMap is complete."""
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


def _pdf_decode_embedded_identity_bytes(raw: bytes, font: DictionaryObject) -> str | None:
    """Recover Unicode through an unambiguous embedded Identity CID font."""
    unicode_by_gid = _pdf_embedded_identity_unicode_map(font)
    if unicode_by_gid is None:
        return None
    cids = _pdf_embedded_identity_cids(raw, font, unicode_by_gid)
    if cids is None:
        return None
    return "".join(unicode_by_gid[cid] for cid in cids)


def _pdf_embedded_identity_cids(
    raw: bytes,
    font: DictionaryObject,
    unicode_by_gid: dict[int, str] | None = None,
) -> tuple[int, ...] | None:
    """Return verified Identity-H CIDs, including the one-byte compatibility case."""
    encoding = font.get("/Encoding")
    encoding_object = encoding.get_object() if encoding is not None else None
    if str(encoding_object) != "/Identity-H":
        return None
    glyphs = unicode_by_gid if unicode_by_gid is not None else _pdf_embedded_identity_unicode_map(font)
    if glyphs is None:
        return None
    cids: tuple[int, ...]
    if len(raw) == 1:
        cids = (raw[0],)
    elif raw and len(raw) % 2 == 0:
        cids = tuple(int.from_bytes(raw[index:index + 2], "big") for index in range(0, len(raw), 2))
    else:
        return None
    return cids if all(cid in glyphs for cid in cids) else None


def _pdf_embedded_identity_unicode_map(font: DictionaryObject) -> dict[int, str] | None:
    """Return unambiguous CID/GID Unicode values from an embedded source font."""
    cache_attribute = "_pipeline_embedded_identity_unicode_map"
    cached = getattr(font, cache_attribute, None)
    if cached is not None:
        return cast(dict[int, str] | None, cached)
    descendants = _pdf_array_object(font.get("/DescendantFonts"))
    descendant = descendants[0].get_object() if descendants else None
    if (
        not isinstance(descendant, DictionaryObject)
        or str(descendant.get("/CIDToGIDMap")) != "/Identity"
    ):
        setattr(font, cache_attribute, None)
        return None
    descriptor_reference = descendant.get("/FontDescriptor")
    descriptor = descriptor_reference.get_object() if descriptor_reference is not None else None
    if not isinstance(descriptor, DictionaryObject):
        setattr(font, cache_attribute, None)
        return None
    font_program_reference = descriptor.get("/FontFile2")
    if font_program_reference is None:
        font_program_reference = descriptor.get("/FontFile3")
    get_object = getattr(font_program_reference, "get_object", None)
    font_program = get_object() if callable(get_object) else font_program_reference
    get_data = getattr(font_program, "get_data", None)
    if not callable(get_data):
        setattr(font, cache_attribute, None)
        return None
    try:
        glyph_unicode_values = _pdf_embedded_font_gid_unicode_values(bytes(get_data()))
    except (struct.error, TypeError, ValueError):
        glyph_unicode_values = None
    if glyph_unicode_values is None:
        setattr(font, cache_attribute, None)
        return None
    result = {
        glyph: next(iter(values))
        for glyph, values in glyph_unicode_values.items()
        if len(values) == 1
    }
    setattr(font, cache_attribute, result or None)
    return result or None


def _pdf_embedded_font_gid_unicode_values(data: bytes) -> dict[int, set[str]] | None:
    """Read Unicode ``cmap`` subtables from an embedded TrueType/OpenType font."""
    if len(data) < 12:
        return None
    table_count = struct.unpack_from(">H", data, 4)[0]
    directory_end = 12 + table_count * 16
    if directory_end > len(data):
        return None
    cmap_offset = next(
        (
            struct.unpack_from(">I", data, offset + 8)[0]
            for offset in range(12, directory_end, 16)
            if data[offset:offset + 4] == b"cmap"
        ),
        None,
    )
    if cmap_offset is None or cmap_offset + 4 > len(data):
        return None
    cmap_count = struct.unpack_from(">H", data, cmap_offset + 2)[0]
    records_end = cmap_offset + 4 + cmap_count * 8
    if records_end > len(data):
        return None
    records: list[tuple[int, int, int]] = []
    for offset in range(cmap_offset + 4, records_end, 8):
        platform, encoding, relative_offset = struct.unpack_from(">HHI", data, offset)
        if platform == 0 or (platform == 3 and encoding in {1, 10}):
            records.append((platform, encoding, cmap_offset + relative_offset))
    if not records:
        return None
    values: dict[int, set[str]] = {}
    for _platform, _encoding, offset in records:
        if offset + 2 > len(data):
            return None
        format_number = struct.unpack_from(">H", data, offset)[0]
        if format_number == 4:
            entries = _pdf_embedded_cmap_format4_entries(data, offset)
        elif format_number == 12:
            entries = _pdf_embedded_cmap_format12_entries(data, offset)
        else:
            continue
        if entries is None:
            return None
        for glyph, codepoint in entries:
            if glyph and 0 <= codepoint <= 0x10FFFF and not 0xD800 <= codepoint <= 0xDFFF:
                values.setdefault(glyph, set()).add(chr(codepoint))
    return values or None


def _pdf_embedded_cmap_format4_entries(data: bytes, offset: int) -> tuple[tuple[int, int], ...] | None:
    if offset + 16 > len(data):
        return None
    length = struct.unpack_from(">H", data, offset + 2)[0]
    end = offset + length
    segment_count = struct.unpack_from(">H", data, offset + 6)[0] // 2
    if length < 16 or segment_count == 0 or end > len(data):
        return None
    end_codes_offset = offset + 14
    start_codes_offset = end_codes_offset + segment_count * 2 + 2
    deltas_offset = start_codes_offset + segment_count * 2
    ranges_offset = deltas_offset + segment_count * 2
    if ranges_offset + segment_count * 2 > end:
        return None
    entries: list[tuple[int, int]] = []
    for index in range(segment_count):
        end_code = struct.unpack_from(">H", data, end_codes_offset + index * 2)[0]
        start_code = struct.unpack_from(">H", data, start_codes_offset + index * 2)[0]
        delta = struct.unpack_from(">h", data, deltas_offset + index * 2)[0]
        range_offset = struct.unpack_from(">H", data, ranges_offset + index * 2)[0]
        if start_code > end_code:
            return None
        for codepoint in range(start_code, end_code + 1):
            if range_offset == 0:
                glyph = (codepoint + delta) & 0xFFFF
            else:
                glyph_offset = ranges_offset + index * 2 + range_offset + (codepoint - start_code) * 2
                if glyph_offset + 2 > end:
                    return None
                glyph = struct.unpack_from(">H", data, glyph_offset)[0]
                if glyph:
                    glyph = (glyph + delta) & 0xFFFF
            entries.append((glyph, codepoint))
    return tuple(entries)


def _pdf_embedded_cmap_format12_entries(data: bytes, offset: int) -> tuple[tuple[int, int], ...] | None:
    if offset + 16 > len(data):
        return None
    length = struct.unpack_from(">I", data, offset + 4)[0]
    group_count = struct.unpack_from(">I", data, offset + 12)[0]
    end = offset + length
    if length < 16 or end > len(data) or offset + 16 + group_count * 12 > end:
        return None
    entries: list[tuple[int, int]] = []
    for group_offset in range(offset + 16, offset + 16 + group_count * 12, 12):
        first, last, glyph = struct.unpack_from(">III", data, group_offset)
        if first > last or last > 0x10FFFF or last - first > 65_535:
            return None
        entries.extend((glyph + codepoint - first, codepoint) for codepoint in range(first, last + 1))
    return tuple(entries)


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


def _pdf_text_operand(
    text: str, static_font_name: str | None, classification: str = "sans-serif"
) -> TextStringObject | ByteStringObject:
    if static_font_name is None:
        return TextStringObject(text)
    if static_font_name == "PipelineFallback":
        return ByteStringObject(text.encode("latin-1", "replace"))
    raise ValueError(
        "Portable Noto text requires its font reference to allocate CID mappings."
    )


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
