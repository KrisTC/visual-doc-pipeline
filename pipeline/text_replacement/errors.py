"""Exceptions raised by the text-replacement task and provider factory."""


class TextReplacementError(RuntimeError):
    """Base exception for text-replacement task failures."""


class TextReplacementProviderError(TextReplacementError):
    """Raised when a text-replacement provider cannot process a request."""


class TextReplacementProviderRequestError(TextReplacementProviderError):
    """A provider failure with safe, content-free request diagnostics."""

    def __init__(self, message: str, diagnostic: dict[str, object]) -> None:
        super().__init__(message)
        self.diagnostic = diagnostic


class TextReplacementProviderNotFoundError(TextReplacementError):
    """Raised when no provider is registered under a requested name."""
