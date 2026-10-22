"""Shared helpers for text-replacement providers and their wrappers."""

from __future__ import annotations

from collections.abc import Callable

from pipeline.text_replacement.errors import TextReplacementProviderError
from pipeline.text_replacement.models import (
    BatchLimits,
    TextReplacementItem,
    TextReplacementRequest,
    TextReplacementResult,
)
from pipeline.text_replacement.provider import TextReplacementProvider


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


def replace_text(
    provider: TextReplacementProvider,
    text: str,
    *,
    is_filename: bool,
    source_language: str,
    target_language: str,
) -> TextReplacementItem:
    """Replace one text as a batch of one.

    This is a temporary convenience for handlers that are not yet converted to
    plan and apply steps. It is not part of the provider API.
    """
    request = TextReplacementRequest((text,), is_filename, source_language, target_language)
    return check_result_length(1, provider.replace(request)).items[0]
