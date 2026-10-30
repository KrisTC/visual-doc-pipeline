"""Filter explicitly preserved text from folder-replacement OCR results."""

from dataclasses import dataclass

from pipeline.ocr import OcrProvider, OcrRequest, OcrResult
from pipeline.ocr.provider import LocalContractTestSkip


@dataclass(frozen=True, slots=True)
class LogoFilteringOcrProvider:
    """Filter after provider caching so the cache retains unfiltered results."""

    wrapped_provider: OcrProvider
    preserved_text: frozenset[str]

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
        result = self.wrapped_provider.recognize(request)
        return OcrResult(tuple(
            item for item in result.text_items if item.text.strip(" ") not in self.preserved_text
        ))
