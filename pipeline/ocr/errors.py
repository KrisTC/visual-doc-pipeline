"""Exceptions raised by the OCR task and provider factory."""


class OcrError(RuntimeError):
    """Base exception for OCR task failures."""


class DuplicateOcrProviderError(OcrError):
    """Raised when two plugins declare the same provider name."""


class OcrProviderError(OcrError):
    """Raised when an OCR provider cannot process a request."""


class OcrProviderNotFoundError(OcrError):
    """Raised when no provider is registered under a requested name."""
