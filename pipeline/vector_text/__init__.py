"""Direct editable-text replacement for supported vector graphic formats."""

from pipeline.vector_text.common import NestedGraphic, VectorDocument, VectorReplacementResult
from pipeline.vector_text.replacer import analyse_vector_text, replace_vector_text

__all__ = [
    "NestedGraphic",
    "VectorDocument",
    "VectorReplacementResult",
    "analyse_vector_text",
    "replace_vector_text",
]
