"""Per-source batching engine for text replacement.

Handlers plan the texts they need as units, the engine packs them into provider
requests and resolves them once, and handlers then look the results up while they
apply them. See ``docs/batch-text-replacement-plan.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pipeline.provider_metrics import record_run_plan_miss, record_run_unique_texts
from pipeline.text_replacement.errors import TextReplacementProviderError
from pipeline.text_replacement.helpers import (
    batch_limits_of,
    cached_flags_of,
    check_result_length,
    replace_text,
)
from pipeline.text_replacement.models import TextReplacementItem, TextReplacementRequest
from pipeline.text_replacement.provider import TextReplacementProvider


@dataclass(frozen=True, slots=True)
class TextUnit:
    """The ordered texts one document or image needs, under a path-style identifier."""

    unit_id: str
    texts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlannedBatch:
    """One provider request's texts, which always come from a single unit."""

    unit_id: str
    texts: tuple[str, ...]


class BatchProgress(Protocol):
    """Receives translate-phase progress; batches already held by the cache are not reported."""

    def batches_known(self, remote_batches: int) -> None:
        """Report, once, how many batches need a provider request."""

    def batch_started(self, number: int, total: int) -> None:
        """Report that the numbered remote batch is about to be requested."""

    def batch_finished(self, number: int, total: int) -> None:
        """Report that the numbered remote batch completed."""


class TranslationEngine:
    """Pack planned units into provider requests, resolve them, and serve lookups.

    One engine serves one top-level source file and owns that file's language pair.
    """

    def __init__(
        self, provider: TextReplacementProvider, source_language: str, target_language: str
    ) -> None:
        self._provider = provider
        self._source_language = source_language
        self._target_language = target_language
        self._units: list[TextUnit] = []
        self._unit_ids: set[str] = set()
        self._results: dict[str, TextReplacementItem] = {}
        self._resolved = False
        self.plan_misses = 0

    @property
    def unique_texts(self) -> int:
        """Return how many distinct texts the units asked for."""
        return len({text for unit in self._units for text in unit.texts})

    def add_unit(self, unit_id: str, texts: tuple[str, ...]) -> None:
        """Register one unit's ordered texts before ``resolve``."""
        if self._resolved:
            message = "Units must be added before the engine is resolved."
            raise RuntimeError(message)
        if unit_id in self._unit_ids:
            message = f"Duplicate translation unit identifier: {unit_id}"
            raise ValueError(message)
        self._unit_ids.add(unit_id)
        self._units.append(TextUnit(unit_id, tuple(texts)))

    def plan_batches(self) -> tuple[PlannedBatch, ...]:
        """Pack the registered units into batches without calling the provider."""
        limits = batch_limits_of(self._provider)
        max_items = limits.max_items if limits else None
        target = limits.target_characters if limits else None
        hard_maximum = limits.max_characters if limits else None
        seen: set[str] = set()
        batches: list[PlannedBatch] = []
        for unit in self._units:
            current: list[str] = []
            characters = 0
            for text in unit.texts:
                if text in seen:
                    continue
                seen.add(text)
                if hard_maximum is not None and len(text) > hard_maximum:
                    message = (
                        f"A text of {len(text)} characters exceeds the provider maximum "
                        f"of {hard_maximum} characters."
                    )
                    raise TextReplacementProviderError(message)
                over_items = max_items is not None and len(current) >= max_items
                over_target = target is not None and characters + len(text) > target
                if current and (over_items or over_target):
                    batches.append(PlannedBatch(unit.unit_id, tuple(current)))
                    current, characters = [], 0
                current.append(text)
                characters += len(text)
            if current:
                batches.append(PlannedBatch(unit.unit_id, tuple(current)))
        return tuple(batches)

    def resolve(self, progress: BatchProgress | None = None) -> None:
        """Send every batch once and keep the results in memory for ``lookup``."""
        if self._resolved:
            message = "The engine has already been resolved."
            raise RuntimeError(message)
        batches = self.plan_batches()
        record_run_unique_texts(self.unique_texts)
        requests = [
            TextReplacementRequest(batch.texts, False, self._source_language, self._target_language)
            for batch in batches
        ]
        needs_remote = []
        for request in requests:
            flags = cached_flags_of(self._provider, request)
            needs_remote.append(flags is None or not all(flags))
        total = sum(needs_remote)
        if progress is not None:
            progress.batches_known(total)
        number = 0
        for request, remote in zip(requests, needs_remote, strict=True):
            if remote:
                number += 1
                if progress is not None:
                    progress.batch_started(number, total)
            result = check_result_length(len(request.texts), self._provider.replace(request))
            for text, item in zip(request.texts, result.items, strict=True):
                self._results[text] = item
            if remote and progress is not None:
                progress.batch_finished(number, total)
        self._resolved = True

    def lookup(self, text: str) -> TextReplacementItem:
        """Return the planned replacement for a text, or fall back to a single-text call."""
        if not self._resolved:
            message = "The engine must be resolved before texts are looked up."
            raise RuntimeError(message)
        item = self._results.get(text)
        if item is None:
            self.plan_misses += 1
            record_run_plan_miss()
            item = replace_text(
                self._provider,
                text,
                is_filename=False,
                source_language=self._source_language,
                target_language=self._target_language,
            )
            self._results[text] = item
        return item
