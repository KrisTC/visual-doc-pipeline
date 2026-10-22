"""The plan and apply convention shared by every document handler.

A handler offers ``plan_x(...)`` returning a plan with ``units()``, and
``apply_x(plan, translate, ...)`` that looks texts up through ``translate``. A nested
document is planned and applied by the same functions as a root file; a parent changes
a child's behaviour only through keyword-only options. The driver below sequences the
steps for one source file: plan, resolve every text once, then apply.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import nullcontext
from typing import Protocol, TypeVar

from pipeline.text_replacement import (
    TextReplacementItem,
    TextReplacementRequest,
    TextReplacementResult,
    TextUnit,
    TranslationEngine,
    rate_limit_wait_listener,
)

NESTED_DOCUMENT_MAX_DEPTH = 6

QUOTA_WAIT_LABEL = "Waiting for translation quota"

_Result = TypeVar("_Result")


class TextPlan(Protocol):
    """A plan lists its own unit first, then its children's units depth-first."""

    def units(self) -> Iterator[TextUnit]:
        """Yield every unit of this plan and of the documents nested inside it."""


def child_unit_id(parent_unit_id: str, child_name: str) -> str:
    """Return the path-style identifier of a nested unit, such as ``docx/xlsx/image-1``."""
    return f"{parent_unit_id}/{child_name}"


class LookupProvider:
    """A provider that answers from the engine's lookup, so apply sends nothing itself."""

    def __init__(self, translate: Callable[[str], TextReplacementItem]) -> None:
        self._translate = translate

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        if request.is_filename:
            message = "Filenames are translated outside the batching engine."
            raise ValueError(message)
        return TextReplacementResult(tuple(self._translate(text) for text in request.texts))


def enter_nested(
    depth: int, package_part: str, diagnostics: list[dict[str, object]] | None
) -> int | None:
    """Return the depth for a nested document, or None when it is too deep to process.

    The parent leaves a too-deep document unchanged. A sidecar entry is written only
    when diagnostics are enabled and carries the package part name and depth, never
    content.
    """
    child_depth = depth + 1
    if child_depth <= NESTED_DOCUMENT_MAX_DEPTH:
        return child_depth
    if diagnostics is not None:
        diagnostics.append(
            {
                "kind": "skipped",
                "reason_code": "nested_document_depth_limit_exceeded",
                "location": {"package_part": package_part},
                "depth": child_depth,
            }
        )
    return None


class PhaseProgress:
    """Turn plan, translate and apply events into labelled, bounded progress.

    ``advance`` moves the source's work counter and sets a label, ``set_label`` only
    sets a label, and ``grow_total`` adds the translate step to the source's total once
    the number of remote batches is known.
    """

    def __init__(
        self,
        advance: Callable[[str], None],
        set_label: Callable[[str], None],
        grow_total: Callable[[int], None],
    ) -> None:
        self._advance = advance
        self._set_label = set_label
        self._grow_total = grow_total

    def plan_item(self, position: int, total: int, noun: str) -> None:
        self._advance(f"Planning {noun} {position} of {total}")

    def apply_item(self, position: int, total: int, noun: str) -> None:
        self._advance(f"Applying {noun} {position} of {total}")

    def batches_known(self, remote_batches: int) -> None:
        if remote_batches:
            self._grow_total(remote_batches)

    def batch_started(self, number: int, total: int) -> None:
        self._set_label(f"Translating batch {number} of {total}")

    def batch_finished(self, number: int, total: int) -> None:
        self._advance(f"Translating batch {number} of {total}")

    def quota_wait(self, seconds: float) -> None:
        self._set_label(QUOTA_WAIT_LABEL)


def resolve_plan(plan: TextPlan, engine: TranslationEngine, progress: PhaseProgress | None = None) -> None:
    """Register every unit of a plan with the engine and resolve all texts once."""
    listener = nullcontext() if progress is None else rate_limit_wait_listener(progress.quota_wait)
    with listener:
        for unit in plan.units():
            engine.add_unit(unit.unit_id, unit.texts)
        engine.resolve(progress)


def plan_and_apply(
    plan: TextPlan,
    engine: TranslationEngine,
    apply: Callable[[Callable[[str], TextReplacementItem]], _Result],
    progress: PhaseProgress | None = None,
) -> _Result:
    """Resolve a finished plan, then apply it with the engine's lookup."""
    resolve_plan(plan, engine, progress)
    return apply(engine.lookup)
