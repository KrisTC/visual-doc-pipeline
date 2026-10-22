"""Text-replacement task models, providers, and provider discovery."""

from pipeline.text_replacement.factory import TextReplacementProviderFactory
from pipeline.text_replacement.batching import BatchProgress, PlannedBatch, TextUnit, TranslationEngine
from pipeline.text_replacement.helpers import (
    batch_limits_of,
    cached_flags_of,
    check_result_length,
    notify_rate_limit_wait,
    rate_limit_wait_listener,
    replace_each,
    replace_text,
)
from pipeline.text_replacement.models import (
    BatchLimits,
    TextReplacementItem,
    TextReplacementRequest,
    TextReplacementResult,
)
from pipeline.text_replacement.provider import TextReplacementProvider

__all__ = [
    "BatchLimits",
    "BatchProgress",
    "PlannedBatch",
    "TextReplacementItem",
    "TextReplacementProvider",
    "TextReplacementProviderFactory",
    "TextReplacementRequest",
    "TextReplacementResult",
    "TextUnit",
    "TranslationEngine",
    "batch_limits_of",
    "cached_flags_of",
    "check_result_length",
    "notify_rate_limit_wait",
    "rate_limit_wait_listener",
    "replace_each",
    "replace_text",
]
