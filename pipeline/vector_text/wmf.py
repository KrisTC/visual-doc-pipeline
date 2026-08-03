"""WMF format handler."""
from __future__ import annotations
from collections.abc import Callable
from PIL import Image
from pipeline.vector_text.common import VectorReplacementResult

def replace_wmf(data: bytes, replace_text: Callable[[str], str], source_language: str, replace_image: Callable[[Image.Image], int] | None) -> VectorReplacementResult:
    from pipeline.vector_text.replacer import _replace_wmf_text
    return _replace_wmf_text(data, replace_text, source_language, replace_image)
