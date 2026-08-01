"""Provider protocol for the OCR task."""

from typing import Protocol

from pipeline.ocr.models import OcrRequest, OcrResult


class OcrProvider(Protocol):
    """A named implementation of the OCR task."""

    @property
    def name(self) -> str:
        """Return the unique name under which this provider is registered."""

    @property
    def supported_languages(self) -> frozenset[str]:
        """Return the BCP 47 language tags this provider can recognize."""

    @property
    def supports_local_contract_test(self) -> bool:
        """Return whether this provider can run without remote access or credentials."""

    def recognize(self, request: OcrRequest) -> OcrResult:
        """Recognize text in one image."""
