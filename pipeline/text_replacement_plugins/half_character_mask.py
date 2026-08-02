"""Deterministic text-replacement provider with half-length hash output."""

from pipeline.text_replacement.factory import TextReplacementProviderFactory
from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult


class HalfCharacterMaskProvider:
    """Return at least one hash and otherwise half as many as the ordinary input."""

    name = "half_character_mask"

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        """Return a minimum-one, half-length hash string while retaining filenames."""
        replacement = (
            request.text if request.is_filename else "#" * max(1, len(request.text) // 2)
        )
        return TextReplacementResult(text=replacement, confidence=1.0)


def register_providers(factory: TextReplacementProviderFactory) -> None:
    """Register the half-character-mask provider under its stable product name."""
    factory.register(HalfCharacterMaskProvider.name, HalfCharacterMaskProvider)
