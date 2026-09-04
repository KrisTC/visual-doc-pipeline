"""Shared types, constants, and provider helpers for format handlers."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from pipeline.ocr import OcrProvider
from pipeline.text_replacement import TextReplacementProvider, TextReplacementRequest

BITMAP_EXTENSIONS = frozenset({".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"})
OFFICE_DOCUMENT_EXTENSIONS = frozenset({".docx", ".pptx", ".xlsx"})
DOCUMENT_EXTENSIONS = OFFICE_DOCUMENT_EXTENSIONS | {".pdf"}
VECTOR_EXTENSIONS = frozenset({".emf", ".svg", ".wmf"})
TEXT_REPLACEMENT_MINIMUM_CONFIDENCE = 0.65

class ProgressReporter(Protocol):
    def set_postfix_str(self, text: str) -> None: ...
    def update(self, count: float | None = None) -> bool | None: ...
    def close(self) -> None: ...


class NestedProgressReporter(Protocol):
    """The bounded nested-operation row used by interactive folder progress."""

    def start_nested(self, name: str, total: int | None, unit: str = ...) -> None: ...
    def advance_nested(self, label: str) -> None: ...
    def clear_nested(self) -> None: ...

ProgressFactory = Callable[[int, str], ProgressReporter]

@dataclass(slots=True)
class FolderReplacementResult:
    processed_files: int = 0
    ignored_files: int = 0
    failed_files: int = 0
    replaced_image_regions: int = 0
    replaced_native_text_items: int = 0
    retained_vector_graphics: int = 0
    failures: list[str] = field(default_factory=list)

def provider_supports_language(provider: OcrProvider, language: str) -> bool:
    primary = language.replace("_", "-").lower().split("-", 1)[0]
    return any(item.replace("_", "-").lower().split("-", 1)[0] == primary for item in provider.supported_languages)

def replace_native_text(text: str, provider: TextReplacementProvider, source_language: str, target_language: str) -> str:
    return provider.replace(TextReplacementRequest(text, False, source_language, target_language)).text

def is_office_bitmap_part(name: str) -> bool:
    return "/media/" in name and Path(name).suffix.lower() in BITMAP_EXTENSIONS

def is_office_vector_part(name: str) -> bool:
    return "/media/" in name and Path(name).suffix.lower() in VECTOR_EXTENSIONS
