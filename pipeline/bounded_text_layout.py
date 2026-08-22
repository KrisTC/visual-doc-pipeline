"""Deterministic fitting for editable text with a finite bounding rectangle."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
import re
import unicodedata

# skia-python does not publish PEP 561 stubs; this is the native measurement boundary.
import skia  # type: ignore[import-not-found]

from pipeline.text_replacement import TextReplacementProvider, TextReplacementRequest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FONT_DIRECTORY = PROJECT_ROOT / "tests" / "assets" / "fonts"
FONT_PATHS = {
    "sans-serif": FONT_DIRECTORY / "NotoSansJP[wght].ttf",
    "serif": FONT_DIRECTORY / "NotoSerifJP[wght].ttf",
    "fixed-width": FONT_DIRECTORY / "NotoSansMono[wdth,wght].ttf",
}
EMU_PER_PIXEL = 9_525
PIXELS_PER_POINT = 4.0 / 3.0
DEFAULT_FONT_SIZE_POINTS = 18.0
_TOKEN_PATTERN = re.compile(r"[\n\v]|\S+\s*|\s+")


@dataclass(frozen=True, slots=True)
class BoundedTextRun:
    """Resolved typography for a source or replacement run."""

    text: str
    font_family: str | None
    font_classification: str
    font_size_points: float | None
    bold: bool | None
    italic: bool | None
    underline: str | None
    baseline: int | None
    source_typefaces: tuple["SourceTypefaceReference", ...] = ()


@dataclass(frozen=True, slots=True)
class SourceTypefaceReference:
    """One original DrawingML-like script slot and its measurement family.

    ``original_family`` remains the value to write back to the document.  A
    format adapter may fill ``resolved_family`` for a theme or other indirect
    reference; the shared layout code never resolves document packaging.
    """

    script: str
    original_family: str | None
    resolved_family: str | None = None


@dataclass(frozen=True, slots=True)
class BoundedTextParagraph:
    """Resolved paragraph settings required for a stable text layout."""

    alignment: str | None
    space_before_points: float | None
    space_after_points: float | None
    line_spacing: float | None
    line_spacing_kind: str | None
    level: int
    margin_left_emu: int | None
    indent_emu: int | None
    bullet_kind: str | None
    bullet_marker: str | None
    empty_line_font_size_points: float | None
    runs: tuple[BoundedTextRun, ...]


@dataclass(frozen=True, slots=True)
class BoundedTextBox:
    """A text frame whose dimensions allow replacement fitting."""

    width_emu: int
    height_emu: int
    margin_left_emu: int
    margin_top_emu: int
    margin_right_emu: int
    margin_bottom_emu: int
    text_direction: str | None
    paragraphs: tuple[BoundedTextParagraph, ...]


@dataclass(frozen=True, slots=True)
class FittedTextBox:
    """Explicit replacement formatting and the fit result."""

    text_box: BoundedTextBox
    font_scale: float
    fit_status: str
    font_selections: tuple["SourceFontSelection", ...] = ()


@dataclass(frozen=True, slots=True)
class SourceFontSelection:
    """The measurement face selected for one source run."""

    source: str
    requested_family: str | None
    measured_family: str
    fallback_reason: str | None
    original_reference: str | None = None
    resolved_family: str | None = None
    script: str | None = None


@dataclass(frozen=True, slots=True)
class EmbeddedTypefaceCandidate:
    """A document adapter's already-decoded, in-memory embedded face."""

    family: str
    style: skia.FontStyle
    typeface: skia.Typeface


@dataclass(frozen=True, slots=True)
class SourceFontMeasurement:
    """A run-keyed layout model and the faces selected to measure it."""

    text_box: BoundedTextBox
    typefaces: dict[str, skia.Typeface]
    selections: tuple[SourceFontSelection, ...]


@dataclass(frozen=True, slots=True)
class _Style:
    classification: str
    size_pixels: float
    bold: bool
    italic: bool


@dataclass(frozen=True, slots=True)
class _Segment:
    text: str
    style: _Style


@dataclass(frozen=True, slots=True)
class _Line:
    segments: tuple[_Segment, ...]
    width: float
    height: float
    paragraph: BoundedTextParagraph


def noto_typefaces() -> dict[str, skia.Typeface]:
    """Load only committed Noto faces used by the fitting model."""
    typefaces: dict[str, skia.Typeface] = {}
    for classification, path in FONT_PATHS.items():
        if not path.is_file():
            raise RuntimeError(f"Bounded-text layout requires committed font asset {path}.")
        typeface = skia.Typeface.MakeFromFile(str(path))
        if typeface is None:
            raise RuntimeError(f"Could not load committed layout font asset {path}.")
        typefaces[classification] = typeface
    return typefaces


def source_font_measurement(
    text_box: BoundedTextBox,
    typefaces: dict[str, skia.Typeface] | None = None,
    *,
    embedded_faces: tuple[EmbeddedTypefaceCandidate, ...] = (),
    font_manager: skia.FontMgr | None = None,
) -> SourceFontMeasurement:
    """Resolve exact embedded or installed faces for measurement only.

    Document adapters pass only safely decoded in-memory embedded candidates;
    this shared boundary neither knows package formats nor opens document paths.
    """
    selected_typefaces = dict(typefaces or noto_typefaces())
    manager = font_manager or skia.FontMgr.RefDefault()
    selections: list[SourceFontSelection] = []
    paragraphs: list[BoundedTextParagraph] = []
    for paragraph_index, paragraph in enumerate(text_box.paragraphs):
        runs: list[BoundedTextRun] = []
        for run_index, run in enumerate(paragraph.runs):
            for segment_index, segment in enumerate(_source_font_segments(run)):
                typeface, selection = _source_typeface(
                    segment, selected_typefaces, embedded_faces, manager
                )
                key = f"source-face-{paragraph_index}-{run_index}-{segment_index}"
                selected_typefaces[key] = typeface
                selections.append(selection)
                runs.append(replace(segment, font_classification=key))
        paragraphs.append(replace(paragraph, runs=tuple(runs)))
    return SourceFontMeasurement(
        replace(text_box, paragraphs=tuple(paragraphs)), selected_typefaces, tuple(selections)
    )


def _source_typeface(
    run: BoundedTextRun,
    noto_faces: dict[str, skia.Typeface],
    embedded_faces: tuple[EmbeddedTypefaceCandidate, ...],
    font_manager: skia.FontMgr,
) -> tuple[skia.Typeface, SourceFontSelection]:
    fallback = noto_faces[_classification(run)]
    references = run.source_typefaces or (SourceTypefaceReference("latin", run.font_family),)
    last_selection: SourceFontSelection | None = None
    requested_style = _source_font_style(run)
    for reference in references:
        requested_family = reference.resolved_family or reference.original_family
        if not requested_family or requested_family.startswith("+"):
            last_selection = SourceFontSelection("noto-fallback", requested_family, fallback.getFamilyName(), "unresolved-source-family", reference.original_family, reference.resolved_family, reference.script)
            continue
        for candidate in embedded_faces:
            if _same_family(candidate.family, requested_family) and _same_style(candidate.style, requested_style) and _same_family(candidate.typeface.getFamilyName(), requested_family) and _glyphs_available(candidate.typeface, run.text):
                return candidate.typeface, SourceFontSelection("embedded-source-face", requested_family, candidate.typeface.getFamilyName(), None, reference.original_family, requested_family, reference.script)
        face = font_manager.matchFamilyStyle(requested_family, requested_style)
        if face is None:
            last_selection = SourceFontSelection("noto-fallback", requested_family, fallback.getFamilyName(), "source-face-unavailable", reference.original_family, requested_family, reference.script)
        elif not _same_family(face.getFamilyName(), requested_family):
            last_selection = SourceFontSelection("noto-fallback", requested_family, fallback.getFamilyName(), "source-family-mismatch", reference.original_family, requested_family, reference.script)
        elif not _same_style(face.fontStyle(), requested_style):
            last_selection = SourceFontSelection("noto-fallback", requested_family, fallback.getFamilyName(), "source-style-mismatch", reference.original_family, requested_family, reference.script)
        elif not _glyphs_available(face, run.text):
            last_selection = SourceFontSelection("noto-fallback", requested_family, fallback.getFamilyName(), "source-glyphs-unavailable", reference.original_family, requested_family, reference.script)
        else:
            return face, SourceFontSelection("installed-source-face", requested_family, face.getFamilyName(), None, reference.original_family, requested_family, reference.script)
    assert last_selection is not None
    generic_classification = {"serif": "serif", "monospace": "fixed-width", "sans-serif": "sans-serif"}.get(
        (last_selection.original_reference or "").lower()
    )
    if generic_classification:
        fallback = noto_faces[generic_classification]
        last_selection = replace(last_selection, measured_family=fallback.getFamilyName())
    return fallback, last_selection


def _source_font_segments(run: BoundedTextRun) -> tuple[BoundedTextRun, ...]:
    """Split runs only when the adapter supplied script-specific references."""
    if not run.source_typefaces or not run.text:
        return (run,)
    segments: list[BoundedTextRun] = []
    current_script: str | None = None
    current_text = ""
    for character in run.text:
        script = _script_for_character(character)
        if current_text and script != current_script:
            segments.append(_source_font_segment(run, current_text, current_script))
            current_text = ""
        current_script = script
        current_text += character
    if current_text:
        segments.append(_source_font_segment(run, current_text, current_script))
    return tuple(segments)


def _source_font_segment(
    run: BoundedTextRun, text: str, script: str | None
) -> BoundedTextRun:
    references = tuple(item for item in run.source_typefaces if item.script == script)
    if not references:
        references = tuple(item for item in run.source_typefaces if item.script == "latin")
    if not references:
        return replace(run, text=text, source_typefaces=())
    return replace(run, text=text, font_family=references[0].original_family, source_typefaces=references)


def _script_for_character(character: str) -> str:
    codepoint = ord(character)
    if (
        0x3000 <= codepoint <= 0x30FF
        or 0x3400 <= codepoint <= 0x9FFF
        or 0xAC00 <= codepoint <= 0xD7AF
        or 0xF900 <= codepoint <= 0xFAFF
    ):
        return "eastAsian"
    name = unicodedata.name(character, "")
    if any(marker in name for marker in (
        "ARABIC", "HEBREW", "DEVANAGARI", "BENGALI", "GURMUKHI", "GUJARATI",
        "ORIYA", "TAMIL", "TELUGU", "KANNADA", "MALAYALAM", "THAI", "LAO",
        "TIBETAN", "MYANMAR", "GEORGIAN", "ETHIOPIC", "SYRIAC",
    )):
        return "complex"
    return "latin"


def _source_font_style(run: BoundedTextRun) -> skia.FontStyle:
    if run.bold is True and run.italic is True:
        return skia.FontStyle.BoldItalic()
    if run.bold is True:
        return skia.FontStyle.Bold()
    if run.italic is True:
        return skia.FontStyle.Italic()
    return skia.FontStyle.Normal()


def _same_style(left: skia.FontStyle, right: skia.FontStyle) -> bool:
    return bool(
        left.weight() == right.weight()
        and left.width() == right.width()
        and left.slant() == right.slant()
    )


def _same_family(left: str, right: str) -> bool:
    return " ".join(unicodedata.normalize("NFKC", left).casefold().split()) == " ".join(
        unicodedata.normalize("NFKC", right).casefold().split()
    )


def _glyphs_available(typeface: skia.Typeface, text: str) -> bool:
    font = skia.Font(typeface)
    for character in text:
        if character in {"\n", "\r", "\v"}:
            continue
        glyphs = font.textToGlyphs(character)
        if not glyphs or int(glyphs[0]) == 0:
            return False
    return True


def replace_paragraphs(
    text_box: BoundedTextBox,
    provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
) -> BoundedTextBox:
    """Replace populated paragraphs while retaining their layout settings."""
    return replace(
        text_box,
        paragraphs=tuple(
            _replace_paragraph(paragraph, provider, source_language, target_language)
            for paragraph in text_box.paragraphs
        ),
    )


def fit_explicit_noto_text_box(
    text_box: BoundedTextBox,
    typefaces: dict[str, skia.Typeface] | None = None,
    *,
    preserve_source_font_family: bool = False,
    measure_source_fonts: bool = False,
    embedded_faces: tuple[EmbeddedTypefaceCandidate, ...] = (),
    font_manager: skia.FontMgr | None = None,
) -> FittedTextBox:
    """Fit a replacement and return no-autofit-ready explicit run typography.

    Noto remains the deterministic default. Source-font mode can instead use
    verified embedded or installed faces while retaining source references in
    written output.
    """
    selected_typefaces = typefaces or noto_typefaces()
    measurement = (
        source_font_measurement(
            text_box,
            selected_typefaces,
            embedded_faces=embedded_faces,
            font_manager=font_manager,
        )
        if measure_source_fonts
        else None
    )
    measurement_box = text_box if measurement is None else measurement.text_box
    measurement_typefaces = selected_typefaces if measurement is None else measurement.typefaces
    width, height = _content_dimensions(text_box)
    if _is_vertical(text_box):
        # PowerPoint advances vertical text through the shape height, then opens a
        # new column across its width. Shape rotation itself needs no adjustment:
        # it rotates the already-laid-out text frame with the containing shape.
        width, height = height, width
    scale, status = _fit_scale(
        measurement_box.paragraphs, width, height, measurement_typefaces
    )
    explicit_paragraphs = tuple(
        replace(
            paragraph,
            runs=tuple(
                replace(
                    run,
                    font_family=(
                        run.font_family
                        if preserve_source_font_family and run.font_family
                        else selected_typefaces[_classification(run)].getFamilyName()
                    ),
                    font_size_points=_font_points(run) * scale,
                    source_typefaces=run.source_typefaces if preserve_source_font_family else (),
                )
                for run in paragraph.runs
            ),
            empty_line_font_size_points=(
                paragraph.empty_line_font_size_points or DEFAULT_FONT_SIZE_POINTS
            )
            * scale,
        )
        for paragraph in text_box.paragraphs
    )
    return FittedTextBox(
        replace(text_box, paragraphs=explicit_paragraphs),
        scale,
        status,
        () if measurement is None else measurement.selections,
    )


def replace_and_fit_text_box(
    text_box: BoundedTextBox,
    provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typefaces: dict[str, skia.Typeface] | None = None,
    *,
    preserve_source_font_family: bool = False,
    measure_source_fonts: bool = False,
    embedded_faces: tuple[EmbeddedTypefaceCandidate, ...] = (),
    font_manager: skia.FontMgr | None = None,
) -> FittedTextBox:
    """Apply the standard paragraph replacement and explicit fitting policy.

    Format adapters own only extraction and serialization.  Keeping this
    sequence here prevents a format-specific adapter from accidentally fitting
    source text, replacing individual runs, or using a divergent font policy.
    """
    return fit_explicit_noto_text_box(
        replace_paragraphs(text_box, provider, source_language, target_language),
        typefaces,
        preserve_source_font_family=preserve_source_font_family,
        measure_source_fonts=measure_source_fonts,
        embedded_faces=embedded_faces,
        font_manager=font_manager,
    )


def source_occupied_text_box(
    text_box: BoundedTextBox,
    typefaces: dict[str, skia.Typeface] | None = None,
    *,
    measure_source_fonts: bool = False,
    embedded_faces: tuple[EmbeddedTypefaceCandidate, ...] = (),
    font_manager: skia.FontMgr | None = None,
) -> BoundedTextBox:
    """Return no-autofit's source-width and natural-height fitting rectangle.

    PowerPoint preserves the text frame's flow width when autofit is disabled,
    allowing laid-out text to continue below the shape.  This deliberately
    keeps that width while deriving an unclamped natural height.  Callers keep
    the source shape geometry when they write the fitted replacement.
    """
    selected_typefaces = typefaces or noto_typefaces()
    measurement = (
        source_font_measurement(
            text_box,
            selected_typefaces,
            embedded_faces=embedded_faces,
            font_manager=font_manager,
        )
        if measure_source_fonts
        else None
    )
    measurement_box = text_box if measurement is None else measurement.text_box
    measurement_typefaces = selected_typefaces if measurement is None else measurement.typefaces
    content_width, content_height = _content_dimensions(text_box)
    layout_width, layout_height = content_width, content_height
    if _is_vertical(text_box):
        layout_width, layout_height = layout_height, layout_width

    lines = _layout_lines(measurement_box.paragraphs, layout_width, measurement_typefaces, 1.0)
    if _is_vertical(text_box):
        width_emu = _natural_dimension_emu(
            _layout_height(lines), text_box.margin_left_emu, text_box.margin_right_emu
        )
        height_emu = text_box.height_emu
    else:
        width_emu = text_box.width_emu
        height_emu = _natural_dimension_emu(
            _layout_height(lines), text_box.margin_top_emu, text_box.margin_bottom_emu
        )

    return replace(
        text_box,
        width_emu=width_emu,
        height_emu=height_emu,
    )


def _replace_paragraph(
    paragraph: BoundedTextParagraph,
    provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
) -> BoundedTextParagraph:
    source_text = "".join(run.text for run in paragraph.runs)
    if not source_text.strip():
        return paragraph
    replacement = provider.replace(
        TextReplacementRequest(source_text, False, source_language, target_language)
    )
    dominant_run = max(
        paragraph.runs,
        key=lambda run: sum(not character.isspace() for character in run.text),
    )
    return replace(paragraph, runs=(replace(dominant_run, text=replacement.text),))


def _fit_scale(
    paragraphs: tuple[BoundedTextParagraph, ...],
    width: float,
    height: float,
    typefaces: dict[str, skia.Typeface],
) -> tuple[float, str]:
    if _fits(_layout_lines(paragraphs, width, typefaces, 1.0), width, height):
        return 1.0, "fit"
    maximum_font_pixels = max(
        [
            _font_points(run) * PIXELS_PER_POINT
            for paragraph in paragraphs
            for run in paragraph.runs
        ]
        + [
            (paragraph.empty_line_font_size_points or DEFAULT_FONT_SIZE_POINTS)
            * PIXELS_PER_POINT
            for paragraph in paragraphs
            if not paragraph.runs
        ]
        + [DEFAULT_FONT_SIZE_POINTS * PIXELS_PER_POINT]
    )
    minimum_scale = 1.0 / maximum_font_pixels
    if not _fits(_layout_lines(paragraphs, width, typefaces, minimum_scale), width, height):
        return minimum_scale, "overflow"
    fitting_scale = minimum_scale
    non_fitting_scale = 1.0
    for _ in range(16):
        candidate = (fitting_scale + non_fitting_scale) / 2.0
        if _fits(_layout_lines(paragraphs, width, typefaces, candidate), width, height):
            fitting_scale = candidate
        else:
            non_fitting_scale = candidate
    return fitting_scale, "fit"


def _content_dimensions(text_box: BoundedTextBox) -> tuple[float, float]:
    return (
        max(
            0.0,
            (text_box.width_emu - text_box.margin_left_emu - text_box.margin_right_emu)
            / EMU_PER_PIXEL,
        ),
        max(
            0.0,
            (text_box.height_emu - text_box.margin_top_emu - text_box.margin_bottom_emu)
            / EMU_PER_PIXEL,
        ),
    )


def _is_vertical(text_box: BoundedTextBox) -> bool:
    return text_box.text_direction in {
        "vert",
        "vert270",
        "eaVert",
        "wordArtVert",
        "wordArtVertRtl",
    }


def _natural_dimension_emu(
    occupied_pixels: float,
    leading_padding_emu: int,
    trailing_padding_emu: int,
) -> int:
    return max(
        leading_padding_emu + trailing_padding_emu,
        round(occupied_pixels * EMU_PER_PIXEL) + leading_padding_emu + trailing_padding_emu,
    )


def _fits(lines: tuple[_Line, ...], width: float, height: float) -> bool:
    return _layout_height(lines) <= height and all(
        line.width <= max(0.0, width - _paragraph_margin_pixels(line.paragraph)) for line in lines
    )


def _layout_lines(
    paragraphs: tuple[BoundedTextParagraph, ...],
    width: float,
    typefaces: dict[str, skia.Typeface],
    scale: float,
) -> tuple[_Line, ...]:
    lines: list[_Line] = []
    for paragraph in paragraphs:
        segments: list[_Segment] = []
        current_width = 0.0
        paragraph_width = max(0.0, width - _paragraph_margin_pixels(paragraph))
        for run in paragraph.runs:
            style = _style(run, scale)
            for token in _tokens(run.text):
                if token in {"\n", "\v"}:
                    lines.append(_line(segments, current_width, paragraph, scale))
                    segments, current_width = [], 0.0
                    continue
                for piece in _emergency_wrap(token, style, paragraph_width, typefaces):
                    piece_width = _measure(piece, style, typefaces)
                    if segments and paragraph_width > 0 and current_width + piece_width > paragraph_width:
                        lines.append(_line(segments, current_width, paragraph, scale))
                        segments, current_width = [], 0.0
                    segments.append(_Segment(piece, style))
                    current_width += piece_width
        lines.append(_line(segments, current_width, paragraph, scale))
    return tuple(lines)


def _tokens(text: str) -> Iterable[str]:
    for token in _TOKEN_PATTERN.findall(text):
        if token in {"\n", "\v"} or not _wide_character(token):
            yield token
        else:
            yield from token


def _wide_character(text: str) -> bool:
    return any(unicodedata.east_asian_width(character) in {"W", "F"} for character in text)


def _emergency_wrap(
    token: str,
    style: _Style,
    width: float,
    typefaces: dict[str, skia.Typeface],
) -> tuple[str, ...]:
    if width <= 0 or _measure(token, style, typefaces) <= width:
        return (token,)
    return tuple(token)


def _line(
    segments: list[_Segment], width: float, paragraph: BoundedTextParagraph, scale: float
) -> _Line:
    fallback = (
        paragraph.empty_line_font_size_points or DEFAULT_FONT_SIZE_POINTS
    ) * PIXELS_PER_POINT * 1.2 * scale
    height = max((segment.style.size_pixels * 1.2 for segment in segments), default=fallback)
    return _Line(tuple(segments), width, height, paragraph)


def _layout_height(lines: tuple[_Line, ...]) -> float:
    return sum(
        (line.paragraph.space_before_points or 0.0) * PIXELS_PER_POINT
        + _line_advance(line)
        + (line.paragraph.space_after_points or 0.0) * PIXELS_PER_POINT
        for line in lines
    )


def _line_advance(line: _Line) -> float:
    paragraph = line.paragraph
    if paragraph.line_spacing_kind == "multiple" and paragraph.line_spacing is not None:
        return line.height * paragraph.line_spacing
    if paragraph.line_spacing_kind == "points" and paragraph.line_spacing is not None:
        return max(line.height, paragraph.line_spacing * PIXELS_PER_POINT)
    return line.height


def _paragraph_margin_pixels(paragraph: BoundedTextParagraph) -> float:
    return (paragraph.margin_left_emu or 0) / EMU_PER_PIXEL


def _style(run: BoundedTextRun, scale: float) -> _Style:
    return _Style(
        _classification(run),
        _font_points(run) * PIXELS_PER_POINT * scale,
        run.bold is True,
        run.italic is True,
    )


def _measure(text: str, style: _Style, typefaces: dict[str, skia.Typeface]) -> float:
    font = skia.Font(typefaces[style.classification], style.size_pixels)
    font.setEmbolden(style.bold)
    if style.italic:
        font.setSkewX(-0.2)
    return float(font.measureText(text))


def _classification(run: BoundedTextRun) -> str:
    return run.font_classification


def _font_points(run: BoundedTextRun) -> float:
    return run.font_size_points or DEFAULT_FONT_SIZE_POINTS
