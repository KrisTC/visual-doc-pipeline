"""Content-free provider-call metrics for a document processing run."""

from __future__ import annotations

from contextlib import AbstractContextManager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.ocr.models import OcrRequest, OcrResult
    from pipeline.ocr.provider import LocalContractTestSkip, OcrProvider
    from pipeline.text_replacement.models import BatchLimits, TextReplacementRequest, TextReplacementResult
    from pipeline.text_replacement.provider import TextReplacementProvider


_RUN_METRICS: ContextVar[RunMetrics | None] = ContextVar("provider_run_metrics", default=None)


@dataclass
class _CallTotals:
    calls: int = 0
    texts: int = 0
    input_characters: int = 0
    duration_count: int = 0
    duration_total: float = 0.0
    duration_min: float | None = None
    duration_max: float | None = None
    rate_limit_waits: int = 0
    rate_limit_wait_seconds: float = 0.0


class RunMetrics(AbstractContextManager["RunMetrics"]):
    """Collect content-free successful calls for one source document."""

    def __init__(self) -> None:
        self._totals: dict[tuple[str, str], _CallTotals] = {}
        self._token: Token[RunMetrics | None] | None = None

    def __enter__(self) -> RunMetrics:
        self._token = _RUN_METRICS.set(self)
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if self._token is not None:
            _RUN_METRICS.reset(self._token)

    def record(
        self, kind: str, name: str, characters: int | None, seconds: float | None, texts: int = 1
    ) -> None:
        totals = self._totals.setdefault((kind, name), _CallTotals())
        totals.calls += 1
        totals.texts += texts
        totals.input_characters += characters or 0
        if seconds is not None:
            totals.duration_count += 1
            totals.duration_total += seconds
            totals.duration_min = seconds if totals.duration_min is None else min(totals.duration_min, seconds)
            totals.duration_max = seconds if totals.duration_max is None else max(totals.duration_max, seconds)

    def record_rate_limit_wait(self, kind: str, name: str, seconds: float) -> None:
        totals = self._totals.setdefault((kind, name), _CallTotals())
        totals.rate_limit_waits += 1
        totals.rate_limit_wait_seconds += seconds

    def report(self, document_seconds: float) -> list[dict[str, object]]:
        return [
            {
                "result_kind": kind,
                "provider_name": name,
                "successful_calls": totals.calls,
                "requested_texts": totals.texts if kind == "text_replacement" else None,
                "input_characters": totals.input_characters if kind == "text_replacement" else None,
                "duration_count": totals.duration_count,
                "duration_total_seconds": totals.duration_total,
                "duration_min_seconds": totals.duration_min,
                "duration_max_seconds": totals.duration_max,
                "duration_average_seconds": (
                    totals.duration_total / totals.duration_count if totals.duration_count else None
                ),
                "document_time_share_percent": (
                    totals.duration_total / document_seconds * 100
                    if document_seconds > 0 and totals.duration_count else None
                ),
                "rate_limit_waits": totals.rate_limit_waits,
                "rate_limit_wait_seconds": totals.rate_limit_wait_seconds,
            }
            for (kind, name), totals in sorted(self._totals.items())
        ]


def record_run_call(
    kind: str, name: str, characters: int | None, seconds: float | None, texts: int = 1
) -> None:
    metrics = _RUN_METRICS.get()
    if metrics is not None:
        metrics.record(kind, name, characters, seconds, texts)


def record_run_rate_limit_wait(kind: str, name: str, seconds: float) -> None:
    """Record one provider rate-limit wait without any request content."""
    metrics = _RUN_METRICS.get()
    if metrics is not None:
        metrics.record_rate_limit_wait(kind, name, seconds)


class MeteredOcrProvider:
    """Measure successful OCR calls independently of provider caching."""

    def __init__(self, provider: OcrProvider, name: str) -> None:
        self.wrapped_provider = provider
        self.name = name

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
        started = perf_counter()
        result = self.wrapped_provider.recognize(request)
        record_run_call("ocr", self.name, None, perf_counter() - started)
        return result


class MeteredTextReplacementProvider:
    """Measure successful text-replacement calls independently of provider caching."""

    def __init__(self, provider: TextReplacementProvider, name: str) -> None:
        self.wrapped_provider = provider
        self.name = name

    @property
    def batch_limits(self) -> BatchLimits | None:
        """Forward the wrapped provider's optional batch limits."""
        from pipeline.text_replacement.helpers import batch_limits_of

        return batch_limits_of(self.wrapped_provider)

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        started = perf_counter()
        result = self.wrapped_provider.replace(request)
        record_run_call(
            "text_replacement", self.name, sum(len(text) for text in request.texts),
            perf_counter() - started, texts=len(request.texts),
        )
        return result