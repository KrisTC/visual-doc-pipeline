"""Deterministic placeholder text-replacement provider."""

from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult
from pipeline.text_replacement.provider import TextReplacementProvider
from pipeline.text_replacement_plugins._masking import mask_non_whitespace_characters


class CharacterMaskProvider:
    """Mask ordinary text while retaining filenames and Unicode whitespace unchanged."""

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        """Return one hash per non-whitespace character, except for filenames."""
        replacement = (
            request.text
            if request.is_filename
            else mask_non_whitespace_characters(request.text, 1)
        )
        return TextReplacementResult(text=replacement, confidence=1.0)


def create_provider() -> TextReplacementProvider:
    """Create the character-mask provider selected by this package's directory name."""
    return CharacterMaskProvider()
