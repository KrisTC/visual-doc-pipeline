"""WMF format handler."""
from __future__ import annotations
from collections.abc import Callable
from PIL import Image
from pipeline.vector_text.common import VectorReplacementResult
from pipeline.text_replacement import TextReplacementProvider

def replace_wmf(data: bytes, replace_text: Callable[[str], str], source_language: str, replace_image: Callable[[Image.Image], int] | None, *, document_text_layout: str = "preserve-source-formatting", replacement_provider: TextReplacementProvider | None = None, target_language: str | None = None) -> VectorReplacementResult:
    from pipeline.vector_text.replacer import _replace_wmf_text
    return _replace_wmf_text(data, replace_text, source_language, replace_image, document_text_layout=document_text_layout, replacement_provider=replacement_provider, target_language=target_language)
