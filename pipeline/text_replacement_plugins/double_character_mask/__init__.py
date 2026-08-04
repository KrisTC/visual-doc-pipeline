"""Deterministic text-replacement provider with double-length hash output."""

from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult
from pipeline.text_replacement.provider import TextReplacementProvider
from pipeline.text_replacement_plugins._masking import mask_non_whitespace_characters


class DoubleCharacterMaskProvider:
    """Return two hashes per ordinary non-whitespace character."""

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        """Return double masks while retaining filenames and whitespace unchanged."""
        replacement = (
            request.text
            if request.is_filename
            else mask_non_whitespace_characters(request.text, 2)
        )
        return TextReplacementResult(text=replacement, confidence=1.0)


def create_provider() -> TextReplacementProvider:
    """Create the double-character-mask provider selected by this package's directory name."""
    return DoubleCharacterMaskProvider()
