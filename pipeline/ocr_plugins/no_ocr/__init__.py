"""Immediate empty-result OCR provider for local pipeline testing."""

from __future__ import annotations

from pipeline.ocr.models import OcrRequest, OcrResult
from pipeline.ocr.provider import LocalContractTestSkip, OcrProvider


SHORT_NAME = "no_ocr"


def cache_identity() -> str:
    """Return the output-compatible implementation version for result caching."""
    return "no_ocr:v1"


class NoOcrProvider:
    """Return no recognized text without reading the image or loading an OCR engine."""

    supported_languages = frozenset({"en", "ja"})
    supports_local_contract_test = False
    skipped_local_contract_angles: frozenset[int] = frozenset()
    skipped_local_contract_cases: frozenset[LocalContractTestSkip] = frozenset()

    def recognize(self, request: OcrRequest) -> OcrResult:
        """Return an empty result immediately for the supplied request."""
        del request
        return OcrResult(())


def create_provider() -> OcrProvider:
    """Create the no_ocr provider selected by this package's directory name."""
    return NoOcrProvider()
