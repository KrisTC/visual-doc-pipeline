#!/usr/bin/env python3
"""Download optional fonts and pre-trigger PaddleOCR's normal model cache."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from pipeline.ocr_plugins.paddleocr import bootstrap_model_language
from pipeline.runtime_assets import (
    bootstrap_math_font,
    bootstrap_symbols_font,
    font_cache_directory,
    mark_bootstrap_complete,
    paddle_model_cache_directory,
)
from pipeline.terminal_progress import LiveProgress


def main() -> int:
    """Bootstrap the small shared optional-font and PaddleOCR caches."""
    try:
        with LiveProgress() as display:
            display.start_overall(4, "asset")
            progress = display.start_current("Runtime assets", 4, "asset")
            progress.set_postfix_str("Noto Sans Symbols 2")
            symbols_font = bootstrap_symbols_font()
            progress.update()
            display.advance_overall()
            progress.set_postfix_str("Noto Sans Math")
            math_font = bootstrap_math_font()
            progress.update()
            display.advance_overall()
            progress.set_postfix_str("PaddleOCR English")
            bootstrap_model_language("en")
            progress.update()
            display.advance_overall()
            progress.set_postfix_str("PaddleOCR Japanese")
            bootstrap_model_language("ja")
            progress.update()
            display.advance_overall()
        mark_bootstrap_complete()
    except Exception as error:
        print(f"Runtime-asset bootstrap failed: {error}", file=sys.stderr)
        return 1
    print(f"Font cache: {font_cache_directory()}")
    print(f"Noto Sans Symbols 2: {symbols_font}")
    print(f"Noto Sans Math: {math_font}")
    print(f"PaddleOCR model cache: {paddle_model_cache_directory()}")
    print("Runtime-asset bootstrap complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
