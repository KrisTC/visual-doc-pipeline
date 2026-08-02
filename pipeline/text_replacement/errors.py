"""Exceptions raised by the text-replacement task and provider factory."""


class TextReplacementError(RuntimeError):
    """Base exception for text-replacement task failures."""


class DuplicateTextReplacementProviderError(TextReplacementError):
    """Raised when two plugins declare the same provider name."""


class TextReplacementProviderError(TextReplacementError):
    """Raised when a text-replacement provider cannot process a request."""


class TextReplacementProviderNotFoundError(TextReplacementError):
    """Raised when no provider is registered under a requested name."""
