#!/usr/bin/env python3
"""Replace visible text in every supported file below an input folder."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# skia-python does not publish PEP 561 stubs; this is the native rendering boundary.
import skia  # type: ignore[import-not-found]

from pipeline.folder_replacement import replace_input_folder
from pipeline.ocr import OcrProviderFactory
from pipeline.text_replacement import TextReplacementProviderFactory


DEFAULT_FONT_PATH = PROJECT_ROOT / "tests" / "assets" / "fonts" / "NotoSansJP[wght].ttf"
FONT_WEIGHT_AXIS_TAG = 0x77676874
DEFAULT_FONT_WEIGHT = 500.0


def parse_arguments() -> argparse.Namespace:
    """Parse the main folder-replacement command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_folder", type=Path)
    parser.add_argument("output_folder", type=Path)
    parser.add_argument("--text-replacement", default="character_mask")
    parser.add_argument("--ocr", default="paddleocr")
    parser.add_argument("--source-language", required=True)
    parser.add_argument("--target-language", default="en")
    return parser.parse_args()


def _load_default_typeface() -> skia.Typeface:
    if not DEFAULT_FONT_PATH.is_file():
        raise RuntimeError(f"Replacement typeface is missing: {DEFAULT_FONT_PATH}")
    typeface = skia.Typeface.MakeFromFile(str(DEFAULT_FONT_PATH))
    if typeface is None:
        raise RuntimeError(f"Could not load replacement typeface: {DEFAULT_FONT_PATH}")
    arguments = skia.FontArguments()
    coordinates = skia.FontArguments.VariationPosition.Coordinates(
        [
            skia.FontArguments.VariationPosition.Coordinate(
                FONT_WEIGHT_AXIS_TAG, DEFAULT_FONT_WEIGHT
            )
        ]
    )
    arguments.setVariationDesignPosition(skia.FontArguments.VariationPosition(coordinates))
    weighted_typeface = typeface.makeClone(arguments)
    if weighted_typeface is None:
        raise RuntimeError(
            f"Could not select wght={DEFAULT_FONT_WEIGHT:g} for {DEFAULT_FONT_PATH}"
        )
    return weighted_typeface


def main() -> int:
    """Run the configured folder replacement and report its outcome."""
    arguments = parse_arguments()
    ocr_provider = OcrProviderFactory.discover_default_plugins().create(arguments.ocr)
    replacement_provider = TextReplacementProviderFactory.discover_default_plugins().create(
        arguments.text_replacement
    )
    result = replace_input_folder(
        arguments.input_folder,
        arguments.output_folder,
        ocr_provider=ocr_provider,
        text_replacement_provider=replacement_provider,
        source_language=arguments.source_language,
        target_language=arguments.target_language,
        typeface=_load_default_typeface(),
    )
    print(
        "Folder replacement complete: "
        f"{result.processed_files} processed, {result.ignored_files} ignored, "
        f"{result.failed_files} failed, {result.replaced_native_text_items} native text item(s), "
        f"{result.replaced_image_regions} OCR image region(s), "
        f"{result.retained_vector_graphics} vector graphic(s) retained."
    )
    return 1 if result.failed_files else 0


if __name__ == "__main__":
    sys.exit(main())
