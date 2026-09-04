#!/usr/bin/env python3
"""Replace visible text in every supported file below an input folder."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import os
from pathlib import Path
import re
import sys
from typing import Protocol


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# skia-python does not publish PEP 561 stubs; this is the native rendering boundary.
import skia  # type: ignore[import-not-found]

from pipeline.folder_replacement import parse_include_patterns, replace_input_folder
from pipeline.folder_replacement.xlsx import XLSX_TRANSLATION_MODE_CHOICES
from pipeline.ocr.errors import OcrProviderNotFoundError
from pipeline.ocr import OcrProvider, OcrProviderFactory
from pipeline.runtime_assets import RuntimeAssetsRequiredError, require_runtime_assets
from pipeline.text_replacement.errors import TextReplacementProviderNotFoundError
from pipeline.text_replacement import TextReplacementProvider, TextReplacementProviderFactory


DEFAULT_FONT_PATH = PROJECT_ROOT / "tests" / "assets" / "fonts" / "NotoSansJP[wght].ttf"
FONT_WEIGHT_AXIS_TAG = 0x77676874
DEFAULT_FONT_WEIGHT = 500.0
DEFAULT_TEXT_REPLACEMENT_PROVIDER = "google_cloud_translate"
DEFAULT_OCR_PROVIDER = "paddleocr"
DEFAULT_TARGET_LANGUAGE = "en"
DOCUMENT_TEXT_LAYOUT_CHOICES = (
    "preserve-source-formatting",
    "preserve-basic-layout",
    "preserve-basic-layout-source-font",
)
DEFAULT_DOCUMENT_TEXT_LAYOUT = "preserve-basic-layout-source-font"
ANSI_BOLD_CYAN = "\033[1;36m"
ANSI_BOLD_GREEN = "\033[1;32m"
ANSI_BOLD = "\033[1m"
ANSI_YELLOW = "\033[33m"
ANSI_RESET = "\033[0m"


class _HelpOutput(Protocol):
    """The write-only stream interface accepted by argparse help rendering."""

    def write(self, text: str) -> object: ...


class _HelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter
):
    """Render defaults and multi-line argument-group descriptions in CLI help."""

    def __init__(self, prog: str) -> None:
        super().__init__(prog, width=100)


class _ColourArgumentParser(argparse.ArgumentParser):
    """Render ANSI-coloured help only when the output stream supports it."""

    def print_help(self, file: _HelpOutput | None = None) -> None:
        output = file if file is not None else sys.stdout
        message = self.format_help()
        if _supports_ansi_colour(output):
            message = _colourize_help(message)
        self._print_message(message, output)


def _argument_parser() -> argparse.ArgumentParser:
    """Create the main folder-replacement command-line parser."""
    text_replacement_factory = TextReplacementProviderFactory.discover_default_plugins()
    ocr_factory = OcrProviderFactory.discover_default_plugins()
    parser = _ColourArgumentParser(
        description=__doc__, formatter_class=_HelpFormatter
    )
    parser.add_argument("input_folder", type=Path, help="Folder to process.")
    parser.add_argument("output_folder", type=Path, help="Folder for processed files.")

    command_options = parser.add_argument_group("command options")
    command_options.add_argument(
        "--source-language", required=True, help="Source-language BCP 47 tag."
    )
    command_options.add_argument(
        "--target-language",
        default=DEFAULT_TARGET_LANGUAGE,
        help="Target-language BCP 47 tag.",
    )
    command_options.add_argument(
        "--text-replacement",
        default=DEFAULT_TEXT_REPLACEMENT_PROVIDER,
        metavar="PROVIDER",
        help="Replacement provider; see below.",
    )
    command_options.add_argument(
        "--ocr",
        default=DEFAULT_OCR_PROVIDER,
        metavar="PROVIDER",
        help="OCR provider; see below.",
    )
    command_options.add_argument(
        "--document-text-layout",
        choices=DOCUMENT_TEXT_LAYOUT_CHOICES,
        metavar="LAYOUT",
        default=DEFAULT_DOCUMENT_TEXT_LAYOUT,
        help="Layout mode; see below.",
    )
    command_options.add_argument(
        "--xlsx-translation-mode",
        choices=XLSX_TRANSLATION_MODE_CHOICES,
        default="full",
        help="XLSX translation mode (default: %(default)s).",
    )
    command_options.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Include matching relative source paths; may repeat or use commas.",
    )
    command_options.add_argument(
        "--debug",
        action="store_true",
        help="Write per-document diagnostic JSON sidecars for reportable issues.",
    )

    parser.add_argument_group(
        "text-replacement providers",
        description=_provider_choices_description(
            text_replacement_factory.provider_names,
            text_replacement_factory.provider_descriptions,
        ),
    )
    parser.add_argument_group(
        "OCR providers",
        description=_provider_choices_description(
            ocr_factory.provider_names, ocr_factory.provider_descriptions
        ),
    )
    parser.add_argument_group(
        "document-text-layout modes",
        description=(
            "  preserve-source-formatting: Retain the source font and size.\n"
            "  preserve-basic-layout: Fit replacement text with a Noto font.\n"
            "  preserve-basic-layout-source-font: Fit replacement text while retaining "
            "source font references where possible."
        ),
    )
    return parser


def _provider_choices_description(
    provider_names: tuple[str, ...],
    provider_descriptions: Mapping[str, str | None],
) -> str:
    """Format one separate help entry for every discovered provider plugin."""
    return "\n".join(
        f"  {name}: {provider_descriptions[name] or 'No description available.'}"
        for name in provider_names
    )


def _supports_ansi_colour(output: object) -> bool:
    """Return whether an output stream supports the command's ANSI help styling."""
    isatty = getattr(output, "isatty", None)
    return (
        callable(isatty)
        and isatty()
        and os.environ.get("TERM") != "dumb"
        and "NO_COLOR" not in os.environ
    )


def _colourize_help(help_text: str) -> str:
    """Apply styling to help headings, option names, and separate choice entries."""
    return "\n".join(_colourize_help_line(line) for line in help_text.splitlines()) + "\n"


def _colourize_help_line(line: str) -> str:
    """Style one pre-formatted argparse help line without changing its layout."""
    if line and not line.startswith(" ") and line.endswith(":"):
        return f"{ANSI_BOLD}{line}{ANSI_RESET}"
    if line.startswith("  ") and not line.startswith("   "):
        option_and_description = line[2:]
        if option_and_description.startswith("-"):
            option, separator, description = option_and_description.partition("  ")
            if separator:
                line = f"  {ANSI_BOLD_CYAN}{option}{ANSI_RESET}{separator}{description}"
            else:
                line = f"  {ANSI_BOLD_CYAN}{option}{ANSI_RESET}"
    if line.startswith("    ") and not line.startswith("     ") and ":" in line:
        choice, description = line[4:].split(":", maxsplit=1)
        line = f"    {ANSI_BOLD_GREEN}{choice}:{ANSI_RESET}{description}"
    return re.sub(
        r"\(default: [^)]+\)",
        lambda match: f"{ANSI_YELLOW}{match.group(0)}{ANSI_RESET}",
        line,
    )


def parse_arguments() -> argparse.Namespace:
    """Parse the main folder-replacement command line."""
    return _argument_parser().parse_args()


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
    parser = _argument_parser()
    arguments = parser.parse_args()
    _validate_roots(arguments, parser)
    include_patterns = _parse_include_patterns(arguments.include, parser)
    ocr_provider = _create_ocr_provider(arguments.ocr, parser)
    replacement_provider = _create_text_replacement_provider(arguments.text_replacement, parser)
    try:
        require_runtime_assets(
            arguments.target_language, arguments.ocr, arguments.document_text_layout
        )
    except RuntimeAssetsRequiredError as error:
        print("Folder replacement did not start: runtime prerequisites are not met.", file=sys.stderr)
        print(str(error), file=sys.stderr)
        print("No input document was processed. Resolve the prerequisite, then rerun.", file=sys.stderr)
        return 2
    result = replace_input_folder(
        arguments.input_folder,
        arguments.output_folder,
        ocr_provider=ocr_provider,
        text_replacement_provider=replacement_provider,
        source_language=arguments.source_language,
        target_language=arguments.target_language,
        typeface=_load_default_typeface(),
        document_text_layout=arguments.document_text_layout,
        xlsx_translation_mode=arguments.xlsx_translation_mode,
        include_patterns=include_patterns,
        diagnostics_enabled=arguments.debug,
    )
    print(
        "Folder replacement complete: "
        f"{result.processed_files} processed, {result.ignored_files} ignored, "
        f"{result.failed_files} failed, {result.replaced_native_text_items} native text item(s), "
        f"{result.replaced_image_regions} OCR image region(s), "
        f"{result.retained_vector_graphics} vector graphic(s) retained."
    )
    if result.diagnostic_sidecars:
        print(
            "Folder replacement diagnostics: "
            f"{len(result.diagnostic_sidecars)} sidecar(s) written under {arguments.output_folder}."
        )
    return 1 if result.failed_files else 0


def _validate_roots(arguments: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Report invalid command roots as ordinary command-line errors."""
    input_folder = arguments.input_folder
    output_folder = arguments.output_folder
    if not input_folder.exists():
        parser.error(f"Input folder does not exist: {input_folder}")
    if not input_folder.is_dir():
        parser.error(f"Input folder is not a directory: {input_folder}")
    if output_folder.exists() and not output_folder.is_dir():
        parser.error(f"Output folder is not a directory: {output_folder}")
    resolved_input = input_folder.resolve()
    resolved_output = output_folder.resolve()
    if resolved_output == resolved_input or resolved_output.is_relative_to(resolved_input):
        parser.error("Output folder must not be the input folder or a directory below it.")


def _parse_include_patterns(
    option_values: list[str], parser: argparse.ArgumentParser
) -> tuple[str, ...]:
    """Parse and validate repeated command-line include-pattern values."""
    try:
        return parse_include_patterns(option_values)
    except ValueError as error:
        parser.error(str(error))
        raise AssertionError("argparse.error exits the process")


def _create_ocr_provider(name: str, parser: argparse.ArgumentParser) -> OcrProvider:
    """Create a selected OCR provider or report an available-name hint."""
    factory = OcrProviderFactory.discover_default_plugins()
    try:
        return factory.create(name)
    except OcrProviderNotFoundError:
        parser.error(
            f"Unknown OCR provider {name!r}. Available OCR providers: "
            f"{', '.join(factory.provider_names)}."
        )
        raise AssertionError("argparse.error exits the process")


def _create_text_replacement_provider(
    name: str, parser: argparse.ArgumentParser
) -> TextReplacementProvider:
    """Create a selected text-replacement provider or report an available-name hint."""
    factory = TextReplacementProviderFactory.discover_default_plugins()
    try:
        return factory.create(name)
    except TextReplacementProviderNotFoundError:
        parser.error(
            f"Unknown text-replacement provider {name!r}. "
            f"Available text-replacement providers: {', '.join(factory.provider_names)}."
        )
        raise AssertionError("argparse.error exits the process")


if __name__ == "__main__":
    sys.exit(main())
