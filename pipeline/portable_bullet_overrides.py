"""Reviewed mappings for legacy PDF bullet glyphs.

Private-Use-Area values in a PDF's ToUnicode map do not identify a portable
Unicode glyph. This registry remains deliberately small: entries are added
only after visual review of the source document.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LegacyBulletOverride:
    """One reviewed leading-marker mapping for fitted PDF visual text."""

    source_scalar: str
    portable_replacement: str
    source_font_resource_name: str | None = None


# Add reviewed mappings here.  The optional resource name is the PDF resource
# name (for example, ``/F1``) reported by the debug diagnostic; omit it only
# when review establishes that the extracted scalar has the same meaning across
# the intended source-font scope.
LEGACY_BULLET_OVERRIDES: tuple[LegacyBulletOverride, ...] = (
    LegacyBulletOverride("\uF0D8", "➢"),
    LegacyBulletOverride("\uF06C", "➢", "/F2"),
    LegacyBulletOverride("\uF06C", "➢", "/F3"),
    LegacyBulletOverride("\uF097", "➢", "/F9")
)


# These visible characters are candidates only when an otherwise eligible
# replacement cannot be covered.  They are not automatic mappings.
_NON_TEXTUAL_LIST_MARKER_CANDIDATES = frozenset({
    "•", "◦", "▪", "▫", "○", "●", "►", "▸", "▹", "➢", "➤",
})


def candidate_bullet_character(text: str) -> bool:
    """Return whether a one-scalar uncovered cluster merits human review."""
    if len(text) != 1:
        return False
    code_point = ord(text)
    return (
        0xE000 <= code_point <= 0xF8FF
        or 0xF0000 <= code_point <= 0xFFFFD
        or 0x100000 <= code_point <= 0x10FFFD
        or text in _NON_TEXTUAL_LIST_MARKER_CANDIDATES
    )


def apply_legacy_bullet_override(
    source_text: str,
    replacement_text: str,
    source_font_resource_name: str | None,
    overrides: tuple[LegacyBulletOverride, ...] | None = None,
) -> str:
    """Map reviewed leading markers on corresponding provider-output lines."""
    selected_overrides = LEGACY_BULLET_OVERRIDES if overrides is None else overrides
    source_lines = source_text.split("\n")
    replacement_lines = replacement_text.split("\n")
    for index, (source_line, replacement_line) in enumerate(
        zip(source_lines, replacement_lines, strict=False)
    ):
        source_leading = _first_non_whitespace_scalar(source_line)
        replacement_leading = _first_non_whitespace_scalar(replacement_line)
        if (
            source_leading is None
            or replacement_leading is None
            or not _has_meaningful_following_source_text(source_line, source_leading[0])
        ):
            continue
        _source_index, source_scalar = source_leading
        replacement_index, replacement_scalar = replacement_leading
        if source_scalar != replacement_scalar:
            continue
        override = next(
            (
                candidate
                for candidate in selected_overrides
                if (
                    candidate.source_scalar == source_scalar
                    and (
                        candidate.source_font_resource_name is None
                        or candidate.source_font_resource_name == source_font_resource_name
                    )
                )
            ),
            None,
        )
        if override is not None:
            replacement_lines[index] = (
                replacement_line[:replacement_index]
                + override.portable_replacement
                + replacement_line[replacement_index + 1:]
            )
    return "\n".join(replacement_lines)


def leading_scalar_matches(text: str, scalar: str) -> bool:
    """Return whether ``scalar`` is the first non-whitespace scalar in text."""
    leading = _first_non_whitespace_scalar(text)
    return leading is not None and leading[1] == scalar


def corresponding_line_leading_scalar_matches(
    source_text: str, replacement_text: str, scalar: str
) -> bool:
    """Return whether ``scalar`` begins a corresponding source/output line."""
    for source_line, replacement_line in zip(
        source_text.split("\n"), replacement_text.split("\n"), strict=False
    ):
        source_leading = _first_non_whitespace_scalar(source_line)
        if (
            source_leading is not None
            and source_leading[1] == scalar
            and leading_scalar_matches(replacement_line, scalar)
            and _has_meaningful_following_source_text(source_line, source_leading[0])
        ):
            return True
    return False


def _first_non_whitespace_scalar(text: str) -> tuple[int, str] | None:
    for index, character in enumerate(text):
        if not character.isspace():
            return index, character
    return None


def _has_meaningful_following_source_text(text: str, marker_index: int) -> bool:
    """Require at least two visible source scalars after a potential marker."""
    return sum(not character.isspace() for character in text[marker_index + 1:]) >= 2
