"""Provider protocol for the OCR task."""

from dataclasses import dataclass
from typing import Protocol

from pipeline.ocr.models import OcrRequest, OcrResult


@dataclass(frozen=True, slots=True)
class LocalContractTestCase:
    """One synthetic OCR contract-test input, identified independently of a provider."""

    language: str
    font_name: str
    angle: int
    color_combination: str


@dataclass(frozen=True, slots=True)
class LocalContractTestSkip:
    """A provider-declared, temporary exception to the local OCR contract test."""

    case: LocalContractTestCase
    reason: str


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

    @property
    def skipped_local_contract_angles(self) -> frozenset[int]:
        """Return rotations temporarily excluded from the local contract test."""

    @property
    def skipped_local_contract_cases(self) -> frozenset[LocalContractTestSkip]:
        """Return exact local contract-test cases temporarily excluded by the provider."""

    def recognize(self, request: OcrRequest) -> OcrResult:
        """Recognize text in one image."""
