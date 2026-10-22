"""Shared result, DIB and single-line text-fitting helpers for vector handlers."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
import struct
from typing import Protocol
from PIL import Image
# skia-python does not publish PEP 561 stubs; this is the native measurement boundary.
import skia  # type: ignore[import-not-found]
from pipeline.bounded_text_layout import (
    BoundedTextBox,
    BoundedTextParagraph,
    BoundedTextRun,
    SourceTypefaceReference,
    fit_explicit_noto_text_box,
    fitted_text_lines,
    noto_typefaces,
    replace_and_fit_text_box,
)
from pipeline.text_replacement import TextReplacementProvider

# ExtTextOut option flags, shared by the EMF and WMF text records.
ETO_OPAQUE = 0x0002
ETO_CLIPPED = 0x0004

_EMU_PER_PIXEL = 9_525

@dataclass(frozen=True, slots=True)
class VectorReplacementResult:
    data: bytes
    replaced_text_items: int
    has_editable_text: bool
    replaced_image_regions: int = 0
    has_embedded_bitmaps: bool = False
    diagnostics: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class NestedGraphic:
    """A vector graphic embedded in another one, with where to report problems with it."""

    data: bytes
    extension: str
    location: dict[str, object]


class VectorDocument(Protocol):
    """A parsed vector graphic that lists its texts, images and nested graphics.

    ``apply`` may be called once; it rewrites the parsed graphic in place.
    """

    def texts(self) -> tuple[str, ...]:
        """Return every source text ``apply`` will ask to replace, in request order."""

    def images(self) -> list[Image.Image]:
        """Return the decoded embedded raster images, in the order ``apply`` visits them."""

    def nested(self) -> list[NestedGraphic]:
        """Return the embedded vector graphics, in the order ``apply`` visits them."""

    def apply(
        self,
        replace_text: Callable[[str], str],
        replacement_provider: TextReplacementProvider | None,
        replace_image: Callable[[int, Image.Image], int] | None,
        replace_nested: Callable[[int], VectorReplacementResult | None] | None = None,
    ) -> VectorReplacementResult:
        """Replace the texts and render the images; ``replace_image`` gets the image index.

        ``replace_nested`` gets a nested graphic's index and returns its replaced graphic,
        or None to leave it unchanged.
        """

def bitmap_file_from_dib(info: bytes, bits: bytes) -> bytes:
    offset = 14 + len(info)
    return struct.pack("<2sIHHI", b"BM", offset + len(bits), 0, 0, offset) + info + bits

def dib_from_image(image: Image.Image) -> tuple[bytes, bytes]:
    output = BytesIO()
    image.convert("RGB").save(output, format="BMP")
    data = output.getvalue()
    offset = struct.unpack_from("<I", data, 10)[0]
    return data[14:offset], data[offset:]


@dataclass(frozen=True, slots=True)
class SourceLineFont:
    """The source typography of one single-line vector text, in pixels at 96 dpi."""

    family: str | None
    size_points: float
    bold: bool
    italic: bool
    classification: str = "sans-serif"
    references: tuple[SourceTypefaceReference, ...] = ()


@dataclass(frozen=True, slots=True)
class FittedLine:
    """A translated single line and the factor to apply to its source size."""

    text: str
    scale: float
    run: BoundedTextRun


def _line_box(text: str, font: SourceLineFont, width_pixels: float, height_pixels: float) -> BoundedTextBox:
    run = BoundedTextRun(
        text, font.family, font.classification, font.size_points, font.bold, font.italic,
        "none", None, font.references or (SourceTypefaceReference("latin", font.family),),
    )
    return BoundedTextBox(
        max(1, round(width_pixels * _EMU_PER_PIXEL)), max(1, round(height_pixels * _EMU_PER_PIXEL)),
        0, 0, 0, 0, None,
        (BoundedTextParagraph("left", None, None, None, None, 0, None, None, None, None, None, (run,)),),
    )


def measure_source_line(
    text: str, font: SourceLineFont, *, measure_source_fonts: bool
) -> tuple[float, float] | None:
    """Return the width and height of the source text laid out as one line at its own size.

    Uses the resolved source face when ``measure_source_fonts`` is set and the face is
    usable, and the committed Noto face otherwise (FR-2026-08-27-02).
    """
    size_pixels = font.size_points * (4.0 / 3.0)
    box = _line_box(text, font, size_pixels * (len(text) + 2) * 2, size_pixels * 10)
    measured = fit_explicit_noto_text_box(
        box, noto_typefaces(), preserve_source_font_family=True,
        measure_source_fonts=measure_source_fonts,
    )
    lines = fitted_text_lines(measured)
    if len(lines) != 1 or measured.font_scale != 1.0:
        return None
    width, height = lines[0].width_pixels, lines[0].height_pixels
    return (width, height) if width > 0 and height > 0 else None


def translate_and_fit_line(
    source_text: str,
    font: SourceLineFont,
    width_pixels: float,
    height_pixels: float | None,
    provider: TextReplacementProvider,
    source_language: str,
    target_language: str,
    *,
    preserve_source_font_family: bool,
    measure_source_fonts: bool,
    calibration_width: float | None = None,
    calibration_text: str | None = None,
) -> FittedLine | None:
    """Translate one line and return the factor that makes it fit the given bounds.

    The replacement is never dropped for being too wide: the factor only shrinks it,
    so a text that cannot fit stays translated and overflows (FR-2026-10-22-11).
    ``calibration_width`` is the rendered width of the source text when the source
    application's metrics are known; a narrower layout face then reduces the factor.
    ``height_pixels`` is None when the height is only a measurement of the source line,
    so the width alone limits the factor.
    Returns None when the replacement is not one line in one run.
    """
    fitted = replace_and_fit_text_box(
        _line_box(
            source_text, font, width_pixels,
            font.size_points * (4.0 / 3.0) * 10 if height_pixels is None else height_pixels,
        ),
        provider, source_language, target_language, noto_typefaces(),
        preserve_source_font_family=preserve_source_font_family,
        measure_source_fonts=measure_source_fonts,
    )
    runs = fitted.text_box.paragraphs[0].runs
    replacement = "".join(run.text for run in runs)
    if len(runs) != 1 or any(character in replacement for character in "\r\n\v"):
        return None
    run = runs[0]
    layout_typefaces = fitted.layout_typefaces
    if layout_typefaces is None or run.font_classification not in layout_typefaces:
        return None
    layout_font = skia.Font(layout_typefaces[run.font_classification], font.size_points * (4.0 / 3.0))
    layout_font.setEmbolden(run.bold is True)
    if run.italic is True:
        layout_font.setSkewX(-0.2)
    text_width = float(layout_font.measureText(replacement))
    metrics = layout_font.getMetrics()
    line_height = metrics.fDescent - metrics.fAscent + metrics.fLeading
    if text_width <= 0.0 or line_height <= 0.0:
        return None
    scale = min(1.0, width_pixels / text_width)
    if height_pixels is not None:
        scale = min(scale, height_pixels / line_height)
    if calibration_width is not None and calibration_width > 0:
        source_width = float(layout_font.measureText(calibration_text or source_text))
        if source_width > 0.0:
            scale *= min(1.0, source_width / calibration_width)
    if scale <= 0.0:
        return None
    return FittedLine(replacement, scale, run)
