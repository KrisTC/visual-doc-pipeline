"""Deterministic placeholder text-replacement provider."""

from pipeline.text_replacement.helpers import replace_each
from pipeline.text_replacement.models import TextReplacementItem, TextReplacementRequest, TextReplacementResult
from pipeline.text_replacement.provider import TextReplacementProvider
from pipeline.text_replacement_plugins._masking import mask_non_whitespace_characters


SHORT_NAME = "mask"


def cache_identity() -> str:
    """Return the output-compatible implementation version for result caching."""
    return "character_mask:v1"


class CharacterMaskProvider:
    """Mask ordinary text while retaining filenames and Unicode whitespace unchanged."""

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        """Return one hash per non-whitespace character of each text, except for filenames."""
        return replace_each(
            request,
            lambda text: TextReplacementItem(
                text if request.is_filename else mask_non_whitespace_characters(text, 1), 1.0
            ),
        )


def create_provider() -> TextReplacementProvider:
    """Create the character-mask provider selected by this package's directory name."""
    return CharacterMaskProvider()
