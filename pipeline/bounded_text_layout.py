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
) -> FittedTextBox:
    """Fit a replacement and return no-autofit-ready explicit run typography.

    Noto remains the deterministic measurement face.  Callers may preserve a
    resolved source typeface reference in the written output as a best-effort
    presentation-design policy.
    """
    selected_typefaces = typefaces or noto_typefaces()
    width, height = _content_dimensions(text_box)
    if _is_vertical(text_box):
        # PowerPoint advances vertical text through the shape height, then opens a
        # new column across its width. Shape rotation itself needs no adjustment:
        # it rotates the already-laid-out text frame with the containing shape.
        width, height = height, width
    scale, status = _fit_scale(text_box.paragraphs, width, height, selected_typefaces)
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
    return FittedTextBox(replace(text_box, paragraphs=explicit_paragraphs), scale, status)


def replace_and_fit_text_box(
    text_box: BoundedTextBox,
    provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    typefaces: dict[str, skia.Typeface] | None = None,
    *,
    preserve_source_font_family: bool = False,
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
    )


def source_occupied_text_box(
    text_box: BoundedTextBox,
    typefaces: dict[str, skia.Typeface] | None = None,
) -> BoundedTextBox:
    """Return no-autofit's source-width and natural-height fitting rectangle.

    PowerPoint preserves the text frame's flow width when autofit is disabled,
    allowing laid-out text to continue below the shape.  This deliberately
    keeps that width while deriving an unclamped natural height.  Callers keep
    the source shape geometry when they write the fitted replacement.
    """
    selected_typefaces = typefaces or noto_typefaces()
    content_width, content_height = _content_dimensions(text_box)
    layout_width, layout_height = content_width, content_height
    if _is_vertical(text_box):
        layout_width, layout_height = layout_height, layout_width

    lines = _layout_lines(text_box.paragraphs, layout_width, selected_typefaces, 1.0)
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
    return run.font_classification if run.font_classification in FONT_PATHS else "sans-serif"


def _font_points(run: BoundedTextRun) -> float:
    return run.font_size_points or DEFAULT_FONT_SIZE_POINTS
