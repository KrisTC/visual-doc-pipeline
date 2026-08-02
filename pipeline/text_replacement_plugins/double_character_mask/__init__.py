"""Deterministic text-replacement provider with double-length hash output."""

from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult
from pipeline.text_replacement.provider import TextReplacementProvider


class DoubleCharacterMaskProvider:
    """Return two hashes for every ordinary input character."""

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        """Return double-length hash text while retaining filenames unchanged."""
        replacement = request.text if request.is_filename else "#" * (2 * len(request.text))
        return TextReplacementResult(text=replacement, confidence=1.0)


def create_provider() -> TextReplacementProvider:
    """Create the double-character-mask provider selected by this package's directory name."""
    return DoubleCharacterMaskProvider()
