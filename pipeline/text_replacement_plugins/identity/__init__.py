"""Deterministic text-replacement provider that preserves ordinary text."""

from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult
from pipeline.text_replacement.provider import TextReplacementProvider


def cache_identity() -> str:
    """Return the output-compatible implementation version for result caching."""
    return "identity:v1"


class IdentityProvider:
    """Return the requested text unchanged for visual baseline comparisons."""

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        """Return the input without applying a replacement."""
        return TextReplacementResult(text=request.text, confidence=1.0)


def create_provider() -> TextReplacementProvider:
    """Create the identity provider selected by this package's directory name."""
    return IdentityProvider()
