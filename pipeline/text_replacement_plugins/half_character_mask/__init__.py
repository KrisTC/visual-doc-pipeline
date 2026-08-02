"""Deterministic text-replacement provider with half-length hash output."""

from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult
from pipeline.text_replacement.provider import TextReplacementProvider


class HalfCharacterMaskProvider:
    """Return at least one hash and otherwise half as many as the ordinary input."""

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        """Return a minimum-one, half-length hash string while retaining filenames."""
        replacement = (
            request.text if request.is_filename else "#" * max(1, len(request.text) // 2)
        )
        return TextReplacementResult(text=replacement, confidence=1.0)


def create_provider() -> TextReplacementProvider:
    """Create the half-character-mask provider selected by this package's directory name."""
    return HalfCharacterMaskProvider()
