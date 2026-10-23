"""Choose the SVG, EMF or WMF handler for a vector graphic.

Format-specific parsing and rewriting lives in ``svg.py``, ``emf.py`` and ``wmf.py``;
this module only identifies the format and dispatches.
"""

from __future__ import annotations

from collections.abc import Callable

from PIL import Image

from pipeline.text_replacement import TextReplacementProvider
from pipeline.vector_text.common import VectorDocument, VectorReplacementResult
from pipeline.vector_text.emf import analyse_emf, is_emf, replace_emf
from pipeline.vector_text.wmf import analyse_wmf, is_wmf, replace_wmf


def replace_vector_text(
    data: bytes,
    extension: str,
    replace_text: Callable[[str], str],
    source_language: str,
    replace_image: Callable[[Image.Image], int] | None = None,
    *,
    document_text_layout: str = "preserve-source-formatting",
    replacement_provider: TextReplacementProvider | None = None,
    target_language: str | None = None,
) -> VectorReplacementResult:
    """Replace editable vector text for ``extension`` without OCR or rasterization."""
    normalised_extension = vector_format(data, extension)
    if normalised_extension == ".svg":
        from pipeline.vector_text.svg import replace_svg
        return replace_svg(
            data,
            replace_text,
            replace_image,
            document_text_layout=document_text_layout,
            replacement_provider=replacement_provider,
            source_language=source_language,
            target_language=target_language,
        )
    if normalised_extension == ".emf":
        return replace_emf(
            data, replace_text, replace_image,
            document_text_layout=document_text_layout,
            replacement_provider=replacement_provider,
            source_language=source_language, target_language=target_language,
        )
    if normalised_extension == ".wmf":
        return replace_wmf(
            data, replace_text, source_language, replace_image,
            document_text_layout=document_text_layout,
            replacement_provider=replacement_provider, target_language=target_language,
        )
    raise ValueError(f"Unsupported vector graphic extension: {extension}")


def vector_format(data: bytes, extension: str) -> str:
    """Return the vector format (``.svg``, ``.emf`` or ``.wmf``) of ``data``.

    EMF and WMF are told apart by content, because a file's extension does not always
    match its format (an EMF is sometimes saved as ``.wmf``). Any other content keeps
    the format its extension names.
    """
    normalised = extension.lower()
    if normalised not in {".emf", ".wmf"}:
        return normalised
    if is_emf(data):
        return ".emf"
    if is_wmf(data):
        return ".wmf"
    return normalised


def analyse_vector_text(
    data: bytes,
    extension: str,
    source_language: str,
    target_language: str,
    *,
    document_text_layout: str = "preserve-source-formatting",
) -> VectorDocument:
    """Parse a vector graphic and list its texts and images; replace nothing yet."""
    extension = vector_format(data, extension)
    if extension == ".svg":
        from pipeline.vector_text.svg import analyse_svg
        return analyse_svg(
            data,
            document_text_layout=document_text_layout,
            fit_text=document_text_layout
            in {"preserve-basic-layout", "preserve-basic-layout-source-font"},
            source_language=source_language, target_language=target_language,
        )
    if extension == ".wmf":
        return analyse_wmf(
            data, source_language=source_language,
            document_text_layout=document_text_layout, target_language=target_language,
        )
    if extension == ".emf":
        return analyse_emf(
            data, source_language=source_language,
            document_text_layout=document_text_layout, target_language=target_language,
        )
    raise ValueError(f"Unsupported vector graphic extension: {extension}")
