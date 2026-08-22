"""Selection helpers for folder-replacement source files."""

from __future__ import annotations

from collections.abc import Iterable
from fnmatch import fnmatchcase
from pathlib import Path


def parse_include_patterns(option_values: Iterable[str]) -> tuple[str, ...]:
    """Split repeated comma-separated include-option values into patterns."""
    values = tuple(option_values)
    patterns = tuple(
        pattern
        for option_value in values
        for pattern in (part.strip() for part in option_value.split(","))
        if pattern
    )
    if any(
        not pattern.strip()
        for option_value in values
        for pattern in option_value.split(",")
    ):
        raise ValueError("Include patterns must not be empty.")
    return patterns


def matches_include_patterns(
    relative_source_path: Path, include_patterns: tuple[str, ...]
) -> bool:
    """Return whether a relative source path matches any configured glob pattern."""
    return not include_patterns or any(
        fnmatchcase(relative_source_path.as_posix(), pattern)
        for pattern in include_patterns
    )
