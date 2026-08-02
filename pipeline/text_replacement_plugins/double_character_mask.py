"""Deterministic text-replacement provider with double-length hash output."""

from pipeline.text_replacement.factory import TextReplacementProviderFactory
from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult


class DoubleCharacterMaskProvider:
    """Return two hashes for every ordinary input character."""

    name = "double_character_mask"

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        """Return double-length hash text while retaining filenames unchanged."""
        replacement = request.text if request.is_filename else "#" * (2 * len(request.text))
        return TextReplacementResult(text=replacement, confidence=1.0)


def register_providers(factory: TextReplacementProviderFactory) -> None:
    """Register the double-character-mask provider under its stable product name."""
    factory.register(DoubleCharacterMaskProvider.name, DoubleCharacterMaskProvider)
