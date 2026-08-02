"""BCP 47 language-directory discovery shared by local OCR tools."""

from __future__ import annotations

import re
from pathlib import Path


LANGUAGE_TAG_PATTERN = re.compile(
    r"^(?:"
    r"(?:[A-Za-z]{2,3}(?:-[A-Za-z]{3}){0,3}|[A-Za-z]{4}|[A-Za-z]{5,8})"
    r"(?:-[A-Za-z]{4})?(?:-(?:[A-Za-z]{2}|[0-9]{3}))?"
    r"(?:-(?:[A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3}))*"
    r"(?:-[0-9A-WY-Za-wy-z](?:-[A-Za-z0-9]{2,8})+)*"
    r"(?:-x(?:-[A-Za-z0-9]{1,8})+)?|"
    r"x(?:-[A-Za-z0-9]{1,8})+"
    r")$"
)


def is_language_tag(directory_name: str) -> bool:
    """Return whether a directory name has BCP 47 language-tag syntax."""
    return LANGUAGE_TAG_PATTERN.fullmatch(directory_name) is not None


def discover_language_directories(source_root: Path) -> list[Path]:
    """Find language-tag directories one or two levels below ``source_root``."""
    language_directories: list[Path] = []
    for first_level_directory in sorted(
        path for path in source_root.iterdir() if path.is_dir()
    ):
        if is_language_tag(first_level_directory.name):
            language_directories.append(first_level_directory)
            continue
        language_directories.extend(
            sorted(
                path
                for path in first_level_directory.iterdir()
                if path.is_dir() and is_language_tag(path.name)
            )
        )
    return language_directories
