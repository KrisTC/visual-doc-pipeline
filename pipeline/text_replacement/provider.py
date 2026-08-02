"""Provider protocol for the text-replacement task."""

from typing import Protocol

from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult


class TextReplacementProvider(Protocol):
    """A named implementation of the text-replacement task."""

    @property
    def name(self) -> str:
        """Return the unique name under which this provider is registered."""

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        """Replace the request text."""
