"""Repository-owned static Noto faces for portable document output.

The variable faces in :mod:`pipeline.bounded_text_layout` are intentionally
used for deterministic fitting only.  These files are the static counterparts
which adapters may embed when their container has a standard embedding path.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


_FONT_DIRECTORY = Path(__file__).resolve().parents[1] / "tests" / "assets" / "fonts"
_FONTS = {
    ("sans-serif", False): ("Noto Sans JP", _FONT_DIRECTORY / "NotoSansJP-Regular.ttf"),
    ("sans-serif", True): ("Noto Sans JP", _FONT_DIRECTORY / "NotoSansJP-Bold.ttf"),
    ("serif", False): ("Noto Serif JP", _FONT_DIRECTORY / "NotoSerifJP-Regular.ttf"),
    ("serif", True): ("Noto Serif JP", _FONT_DIRECTORY / "NotoSerifJP-Bold.ttf"),
    ("fixed-width", False): ("Noto Sans Mono", _FONT_DIRECTORY / "NotoSansMono-Regular.ttf"),
    ("fixed-width", True): ("Noto Sans Mono", _FONT_DIRECTORY / "NotoSansMono-Bold.ttf"),
}


def static_noto_font(classification: str, bold: bool | None) -> tuple[str, Path]:
    """Return the static portable Noto family and file for a fitted run."""
    return _FONTS.get((classification, bool(bold)), _FONTS[("sans-serif", bool(bold))])


@lru_cache(maxsize=None)
def static_noto_bytes(classification: str, bold: bool | None) -> bytes:
    """Load a committed static face once; no system font is consulted."""
    _family, path = static_noto_font(classification, bold)
    if not path.is_file():
        raise RuntimeError(f"Portable layout output requires committed static font {path}.")
    return path.read_bytes()
