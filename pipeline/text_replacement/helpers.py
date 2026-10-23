"""Shared helpers for text-replacement providers and their wrappers."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from pipeline.text_replacement.errors import TextReplacementProviderError
from pipeline.text_replacement.models import (
    BatchLimits,
    TextReplacementItem,
    TextReplacementRequest,
    TextReplacementResult,
)
from pipeline.text_replacement.provider import TextReplacementProvider

_RATE_LIMIT_WAIT_LISTENER: ContextVar[Callable[[float], None] | None] = ContextVar(
    "text_replacement_rate_limit_wait_listener", default=None
)


@contextmanager
def rate_limit_wait_listener(listener: Callable[[float], None]) -> Iterator[None]:
    """Call ``listener(seconds)`` whenever a provider starts a rate-limit wait."""
    token = _RATE_LIMIT_WAIT_LISTENER.set(listener)
    try:
        yield
    finally:
        _RATE_LIMIT_WAIT_LISTENER.reset(token)


def notify_rate_limit_wait(seconds: float) -> None:
    """Tell the active listener, if any, that a rate-limit wait is starting."""
    listener = _RATE_LIMIT_WAIT_LISTENER.get()
    if listener is not None:
        listener(seconds)


def replace_each(
    request: TextReplacementRequest, function: Callable[[str], TextReplacementItem]
) -> TextReplacementResult:
    """Build a batch result by applying a per-text function to each text in order.

    A provider that handles one text at a time needs no batch code beyond this.
    """
    return TextReplacementResult(tuple(function(text) for text in request.texts))


def check_result_length(request_text_count: int, result: TextReplacementResult) -> TextReplacementResult:
    """Return the result, or raise a text-free provider error for a wrong item count."""
    if len(result.items) != request_text_count:
        message = (
            "A text-replacement provider returned "
            f"{len(result.items)} items for {request_text_count} texts."
        )
        raise TextReplacementProviderError(message)
    return result


def batch_limits_of(provider: object) -> BatchLimits | None:
    """Return a provider's optional batch limits."""
    limits = getattr(provider, "batch_limits", None)
    return limits if isinstance(limits, BatchLimits) else None


def cached_flags_of(provider: object, request: TextReplacementRequest) -> tuple[bool, ...] | None:
    """Return which request texts a provider already holds, or None when it cannot say."""
    probe = getattr(provider, "cached_flags", None)
    if not callable(probe):
        return None
    flags = probe(request)
    if isinstance(flags, tuple) and len(flags) == len(request.texts):
        return flags
    return None


def replace_text(
    provider: TextReplacementProvider,
    text: str,
    *,
    is_filename: bool,
    source_language: str,
    target_language: str,
) -> TextReplacementItem:
    """Replace one text as a batch of one.

    Use this for a text that is inherently alone (a filename, or an apply-step
    lookup that the plan missed). Handlers list their texts in the plan step and
    reach the provider through the translation engine. It is not part of the
    provider API.
    """
    request = TextReplacementRequest((text,), is_filename, source_language, target_language)
    return check_result_length(1, provider.replace(request)).items[0]
