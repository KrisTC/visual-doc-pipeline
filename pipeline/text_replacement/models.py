"""Strongly typed models shared by every text-replacement provider."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TextReplacementRequest:
    """A batch of texts to replace and the context needed to replace them.

    Language values are stable BCP 47 tags. Providers may map them to their own
    native conventions. One request has one language pair and one filename flag,
    so a provider never needs to group texts. A single text is a batch of one.
    """

    texts: tuple[str, ...]
    is_filename: bool
    source_language: str
    target_language: str

    def __post_init__(self) -> None:
        if not isinstance(self.texts, tuple) or not self.texts:
            message = "A text-replacement request requires a non-empty tuple of texts."
            raise ValueError(message)
        if not all(isinstance(text, str) for text in self.texts):
            message = "Every text in a text-replacement request must be a string."
            raise ValueError(message)
        if not self.source_language.strip():
            message = "A text-replacement request requires a non-empty source language tag."
            raise ValueError(message)
        if not self.target_language.strip():
            message = "A text-replacement request requires a non-empty target language tag."
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class TextReplacementItem:
    """The replacement selected for one text of a request.

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


@dataclass(frozen=True, slots=True)
class TextReplacementResult:
    """One replacement item per request text, in the same order and of the same length."""

    items: tuple[TextReplacementItem, ...]


@dataclass(frozen=True, slots=True)
class BatchLimits:
    """Optional per-request size limits that a provider may state.

    An unset limit means the provider has no limit of that kind. The target
    character count is soft: a single text larger than it is sent alone.
    """

    max_items: int | None = None
    target_characters: int | None = None
    max_characters: int | None = None
