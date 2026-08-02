"""Deterministic text-replacement provider that preserves ordinary text."""

from pipeline.text_replacement.factory import TextReplacementProviderFactory
from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult


class IdentityProvider:
    """Return the requested text unchanged for visual baseline comparisons."""

    name = "identity"

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        """Return the input without applying a replacement."""
        return TextReplacementResult(text=request.text, confidence=1.0)


def register_providers(factory: TextReplacementProviderFactory) -> None:
    """Register the identity provider under its stable product name."""
    factory.register(IdentityProvider.name, IdentityProvider)
