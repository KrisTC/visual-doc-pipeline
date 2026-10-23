"""Provider protocol for the text-replacement task."""

from typing import Protocol

from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult


class TextReplacementProvider(Protocol):
    """An implementation selected by its text-replacement plugin-package name."""

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        """Replace every request text, returning one item per text in request order.

        A provider may also expose an optional ``batch_limits`` attribute holding
        ``BatchLimits``. A failure raises and never returns a partial result.
        """
