"""Repository-owned static Noto faces for portable document output.

The variable faces in :mod:`pipeline.bounded_text_layout` are intentionally
used for deterministic fitting only.  These files are the static counterparts
which adapters may embed when their container has a standard embedding path.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import skia  # type: ignore[import-not-found]

from pipeline.runtime_assets import (
    math_font_is_available,
    math_font_path,
    symbols_font_is_available,
    symbols_font_path,
)


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
    if classification == "symbols":
        path = symbols_font_path()
        if not path.is_file():
            raise RuntimeError(
                "Noto Sans Symbols 2 has not been bootstrapped. Run "
                "scripts/run.sh python scripts/bootstrap_runtime_assets.py first."
            )
        return "Noto Sans Symbols 2", path
    if classification == "math":
        path = math_font_path()
        if not path.is_file():
            raise RuntimeError(
                "Noto Sans Math has not been bootstrapped. Run "
                "scripts/run.sh python scripts/bootstrap_runtime_assets.py first."
            )
        return "Noto Sans Math", path
    return _FONTS.get((classification, bool(bold)), _FONTS[("sans-serif", bool(bold))])


@lru_cache(maxsize=None)
def static_noto_bytes(classification: str, bold: bool | None) -> bytes:
    """Load a committed static face once; no system font is consulted."""
    _family, path = static_noto_font(classification, bold)
    if not path.is_file():
        raise RuntimeError(f"Portable layout output requires committed static font {path}.")
    return path.read_bytes()


@lru_cache(maxsize=None)
def _optional_typeface(path: str, modification_time_ns: int) -> skia.Typeface:
    """Load one version of an optional face once per process."""
    del modification_time_ns
    typeface = skia.Typeface.MakeFromFile(path)
    if typeface is None:
        raise RuntimeError("Could not load a bootstrapped portable Noto font.")
    return typeface


def optional_static_typefaces() -> dict[str, skia.Typeface]:
    """Return cached optional faces supplied by the local bootstrap."""
    result: dict[str, skia.Typeface] = {}
    if math_font_is_available():
        path = math_font_path()
        result["math"] = _optional_typeface(str(path), path.stat().st_mtime_ns)
    if symbols_font_is_available():
        path = symbols_font_path()
        result["symbols"] = _optional_typeface(str(path), path.stat().st_mtime_ns)
    return result
