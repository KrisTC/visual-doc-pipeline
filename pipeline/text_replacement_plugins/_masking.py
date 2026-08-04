"""Shared Unicode-whitespace-preserving masking helpers for test providers."""

from __future__ import annotations

from itertools import groupby


def mask_non_whitespace_characters(text: str, hashes_per_character: int) -> str:
    """Replace non-whitespace characters while retaining every whitespace code point."""
    return "".join(
        character if character.isspace() else "#" * hashes_per_character
        for character in text
    )


def half_mask_non_whitespace_sequences(text: str) -> str:
    """Halve non-whitespace sequences while retaining whitespace and word boundaries."""
    replacement_parts: list[str] = []
    for is_whitespace, characters in groupby(text, key=str.isspace):
        sequence = "".join(characters)
        if is_whitespace:
            replacement_parts.append(sequence)
        else:
            replacement_parts.append("#" * max(1, len(sequence) // 2))
    return "".join(replacement_parts)
