"""Strongly typed models shared by every text-replacement provider."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TextReplacementRequest:
    """Text to replace and the context needed to replace it.

    Language values are stable BCP 47 tags. Providers may map them to their own
    native conventions.
    """

    text: str
    is_filename: bool
    source_language: str
    target_language: str

    def __post_init__(self) -> None:
        if not self.source_language.strip():
            message = "A text-replacement request requires a non-empty source language tag."
            raise ValueError(message)
        if not self.target_language.strip():
            message = "A text-replacement request requires a non-empty target language tag."
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class TextReplacementResult:
    """The replacement selected by a text-replacement provider.

    ``extra`` holds optional provider-specific information and has no shared
    meaning across providers.
    """

    text: str
    confidence: float
    extra: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            message = "Text-replacement confidence must be between 0.0 and 1.0 inclusive."
            raise ValueError(message)
