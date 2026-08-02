"""Deterministic placeholder text-replacement provider."""

from pipeline.text_replacement.factory import TextReplacementProviderFactory
from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult


class CharacterMaskProvider:
    """Masks ordinary text while retaining filenames unchanged."""

    name = "character_mask"

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        """Return one hash per input character, except for filenames."""
        replacement = request.text if request.is_filename else "#" * len(request.text)
        return TextReplacementResult(text=replacement, confidence=1.0)


def register_providers(factory: TextReplacementProviderFactory) -> None:
    """Register the character-mask provider under its stable product name."""
    factory.register(CharacterMaskProvider.name, CharacterMaskProvider)
