"""DOCX format handler."""
from __future__ import annotations
from collections.abc import Callable
from pathlib import Path
import skia  # type: ignore[import-not-found]
from pipeline.ocr import OcrProvider
from pipeline.text_replacement import TextReplacementProvider

def replace_docx_file(source: Path, destination: Path, ocr: OcrProvider, replacement: TextReplacementProvider, source_language: str, target_language: str, typeface: skia.Typeface, completed: Callable[[str], None]) -> tuple[int, int, int]:
    from pipeline.folder_replacement.processor import _replace_office_file
    return _replace_office_file(source, destination, ocr, replacement, source_language, target_language, typeface, completed)
