"""Deterministic placeholder text-replacement provider."""

from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult
from pipeline.text_replacement.provider import TextReplacementProvider


class CharacterMaskProvider:
    """Masks ordinary text while retaining filenames unchanged."""

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        """Return one hash per input character, except for filenames."""
        replacement = request.text if request.is_filename else "#" * len(request.text)
        return TextReplacementResult(text=replacement, confidence=1.0)


def create_provider() -> TextReplacementProvider:
    """Create the character-mask provider selected by this package's directory name."""
    return CharacterMaskProvider()
