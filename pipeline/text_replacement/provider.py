"""Provider protocol for the text-replacement task."""

from typing import Protocol

from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult


class TextReplacementProvider(Protocol):
    """An implementation selected by its text-replacement plugin-package name."""

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        """Replace the request text."""
