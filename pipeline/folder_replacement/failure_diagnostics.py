"""Safe, local context captured for a folder-replacement file failure."""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.ocr import OcrProvider, OcrRequest, OcrResult
from pipeline.ocr.provider import LocalContractTestSkip
from pipeline.text_replacement import (
    TextReplacementProvider,
    TextReplacementRequest,
    TextReplacementResult,
)


@dataclass(slots=True)
class FailureContext:
    """Record metadata about the last document operation without retaining content."""

    stage: str = "document_setup"
    container_kind: str | None = None
    operation: str | None = None
    package_part: str | None = None
    item_index: int | None = None
    request: dict[str, object] | None = None

    def set_location(
        self,
        *,
        stage: str,
        container_kind: str,
        operation: str,
        package_part: str | None = None,
        item_index: int | None = None,
    ) -> None:
        """Set the active document operation before it can raise."""
        self.stage = stage
        self.container_kind = container_kind
        self.operation = operation
        self.package_part = package_part
        self.item_index = item_index
        self.request = None

    def record_text_replacement(self, request: TextReplacementRequest) -> None:
        """Store only replacement request metadata, never the requested text."""
        self.operation = "text_replacement"
        self.request = {
            "kind": "text_replacement",
            "source_language": request.source_language,
            "target_language": request.target_language,
            "is_filename": request.is_filename,
            "input_character_count": len(request.text),
        }

    def record_ocr(self, request: OcrRequest) -> None:
        """Store only OCR request metadata, never image pixels or recognized text."""
        self.operation = "ocr"
        self.request = {
            "kind": "ocr",
            "language": request.language,
            "image_width": request.image.width,
            "image_height": request.image.height,
            "image_mode": request.image.mode,
        }

    def as_diagnostic(self) -> dict[str, object]:
        """Return the safe, serializable context for a sidecar entry."""
        result: dict[str, object] = {"stage": self.stage}
        if self.container_kind is not None:
            result["container_kind"] = self.container_kind
        if self.operation is not None:
            result["operation"] = self.operation
        location: dict[str, object] = {}
        if self.package_part is not None:
            location["package_part"] = self.package_part
        if self.item_index is not None:
            location["item_index"] = self.item_index
        if location:
            result["location"] = location
        if self.request is not None:
            result["request"] = self.request
        return result


@dataclass(frozen=True, slots=True)
class ContextualTextReplacementProvider:
    """Pass through replacement calls while recording safe request metadata."""

    wrapped_provider: TextReplacementProvider
    context: FailureContext

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        self.context.record_text_replacement(request)
        return self.wrapped_provider.replace(request)


@dataclass(frozen=True, slots=True)
class ContextualOcrProvider:
    """Pass through OCR calls while recording safe request metadata."""

    wrapped_provider: OcrProvider
    context: FailureContext

    @property
    def supported_languages(self) -> frozenset[str]:
        return self.wrapped_provider.supported_languages

    @property
    def supports_local_contract_test(self) -> bool:
        return self.wrapped_provider.supports_local_contract_test

    @property
    def skipped_local_contract_angles(self) -> frozenset[int]:
        return self.wrapped_provider.skipped_local_contract_angles

    @property
    def skipped_local_contract_cases(self) -> frozenset[LocalContractTestSkip]:
        return self.wrapped_provider.skipped_local_contract_cases

    def recognize(self, request: OcrRequest) -> OcrResult:
        self.context.record_ocr(request)
        return self.wrapped_provider.recognize(request)


def exception_cause_types(error: BaseException) -> list[str]:
    """Return a bounded exception cause chain without exposing exception messages."""
    causes: list[str] = []
    current = error.__cause__
    while current is not None and len(causes) < 4:
        causes.append(type(current).__name__)
        current = current.__cause__
    return causes
