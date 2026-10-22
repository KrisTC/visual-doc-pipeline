"""Deterministic text-replacement provider that preserves ordinary text."""

from pipeline.text_replacement.helpers import replace_each
from pipeline.text_replacement.models import TextReplacementItem, TextReplacementRequest, TextReplacementResult
from pipeline.text_replacement.provider import TextReplacementProvider


SHORT_NAME = "identity"


def cache_identity() -> str:
    """Return the output-compatible implementation version for result caching."""
    return "identity:v1"


class IdentityProvider:
    """Return the requested text unchanged for visual baseline comparisons."""

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        """Return every input text without applying a replacement."""
        return replace_each(request, lambda text: TextReplacementItem(text, 1.0))


def create_provider() -> TextReplacementProvider:
    """Create the identity provider selected by this package's directory name."""
    return IdentityProvider()
