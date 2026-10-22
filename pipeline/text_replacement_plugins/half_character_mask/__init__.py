"""Deterministic text-replacement provider with half-length hash output."""

from pipeline.text_replacement.helpers import replace_each
from pipeline.text_replacement.models import TextReplacementItem, TextReplacementRequest, TextReplacementResult
from pipeline.text_replacement.provider import TextReplacementProvider
from pipeline.text_replacement_plugins._masking import half_mask_non_whitespace_sequences


SHORT_NAME = "half-mask"


def cache_identity() -> str:
    """Return the output-compatible implementation version for result caching."""
    return "half_character_mask:v1"


class HalfCharacterMaskProvider:
    """Halve ordinary non-whitespace sequences while retaining whitespace unchanged."""

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        """Return half masks while retaining filenames and whitespace unchanged."""
        return replace_each(
            request,
            lambda text: TextReplacementItem(
                text if request.is_filename else half_mask_non_whitespace_sequences(text), 1.0
            ),
        )


def create_provider() -> TextReplacementProvider:
    """Create the half-character-mask provider selected by this package's directory name."""
    return HalfCharacterMaskProvider()
