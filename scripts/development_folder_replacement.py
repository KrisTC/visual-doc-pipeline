#!/usr/bin/env python3
"""Run repeatable sample-data scenarios through the folder-replacement command."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import product
import json
from pathlib import Path
import re
from subprocess import run
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from pipeline.folder_replacement import parse_include_patterns
from pipeline.ocr import OcrProviderFactory
from pipeline.text_replacement import TextReplacementProviderFactory
from scripts.folder_replacement import (
    DEFAULT_DOCUMENT_TEXT_LAYOUT,
    DEFAULT_OCR_PROVIDER,
    DEFAULT_TARGET_LANGUAGE,
    DEFAULT_TEXT_REPLACEMENT_PROVIDER,
    DOCUMENT_TEXT_LAYOUT_CHOICES,
)


DEVELOPMENT_OUTPUT_ROOT = Path("outputs/evaluations/dirdev")
FOLDER_REPLACEMENT_SCRIPT = PROJECT_ROOT / "scripts" / "folder_replacement.py"
LANGUAGE_TAG_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
DOCUMENT_TEXT_LAYOUT_SHORT_NAMES = {
    "preserve-source-formatting": "psf",
    "preserve-basic-layout": "pbl",
    "preserve-basic-layout-source-font": "pblsf",
}


@dataclass(frozen=True, slots=True)
class Scenario:
    """One concrete invocation of the general folder-replacement command."""

    text_replacement: str
    ocr: str
    document_text_layout: str
    text_replacement_short_name: str
    ocr_short_name: str

    def manifest_data(self) -> dict[str, str]:
        """Return this scenario's stable manifest representation."""
        return {
            "text_replacement": self.text_replacement,
            "ocr": self.ocr,
            "document_text_layout": self.document_text_layout,
            "text_replacement_short_name": self.text_replacement_short_name,
            "ocr_short_name": self.ocr_short_name,
            "document_text_layout_short_name": DOCUMENT_TEXT_LAYOUT_SHORT_NAMES[
                self.document_text_layout
            ],
        }


def _argument_parser() -> argparse.ArgumentParser:
    """Create the development scenario command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source_folder",
        type=Path,
        help="Folder relative to sample-data whose final directory is a BCP 47 language tag.",
    )
    parser.add_argument(
        "--target-language",
        default=DEFAULT_TARGET_LANGUAGE,
        metavar="LANGUAGE",
        help="One target-language BCP 47 tag (default: %(default)s).",
    )
    parser.add_argument(
        "--text-replacement",
        default=DEFAULT_TEXT_REPLACEMENT_PROVIDER,
        metavar="PROVIDER[,PROVIDER...]|all",
        help="Replacement provider(s), or all discovered providers (default: %(default)s).",
    )
    parser.add_argument(
        "--ocr",
        default=DEFAULT_OCR_PROVIDER,
        metavar="PROVIDER[,PROVIDER...]|all",
        help="OCR provider(s), or all discovered providers (default: %(default)s).",
    )
    parser.add_argument(
        "--document-text-layout",
        default=DEFAULT_DOCUMENT_TEXT_LAYOUT,
        metavar="LAYOUT[,LAYOUT...]|all",
        help="Layout mode(s), or all modes (default: %(default)s).",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Pass include pattern to every scenario; may repeat or use commas.",
    )
    parser.add_argument(
        "--comment",
        help="Optional review comment recorded only in manifest.json.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Construct and run all requested folder-replacement scenarios."""
    parser = _argument_parser()
    arguments = parser.parse_args(argv)
    source_root, source_relative_path, source_language = _validate_source_folder(
        arguments.source_folder, parser
    )
    target_language = _validate_language_tag(
        arguments.target_language, "target language", parser
    )
    include_patterns = _parse_include_patterns(arguments.include, parser)
    scenarios = _expand_scenarios(arguments, parser)
    revision_root = _create_revision_root(source_relative_path, source_language, target_language)
    run_results: list[dict[str, object]] = []
    manifest: dict[str, object] = {
        "source_folder": source_relative_path.as_posix(),
        "source_language": source_language,
        "target_language": target_language,
        "include_patterns": list(include_patterns),
        "comment": arguments.comment,
        "scenarios": [scenario.manifest_data() for scenario in scenarios],
        "results": run_results,
    }
    manifest_path = revision_root / "manifest.json"
    _write_manifest(manifest_path, manifest)

    has_failure = False
    for scenario in scenarios:
        output_root = _scenario_output_root(revision_root, scenario)
        command = _folder_replacement_command(
            source_root,
            output_root,
            source_language,
            target_language,
            scenario,
            arguments.include,
        )
        print(f"Running scenario: {output_root.relative_to(PROJECT_ROOT)}")
        completed_process = run(command, check=False, cwd=PROJECT_ROOT)
        diagnostic_sidecars = sorted(
            path.relative_to(output_root).as_posix()
            for path in output_root.rglob("*.diagnostics.json")
        )
        run_results.append(
            {
                "scenario": scenario.manifest_data(),
                "exit_code": completed_process.returncode,
                "output_root": output_root.relative_to(PROJECT_ROOT).as_posix(),
                "diagnostic_sidecars": diagnostic_sidecars,
            }
        )
        _write_manifest(manifest_path, manifest)
        has_failure = has_failure or completed_process.returncode != 0
    return 1 if has_failure else 0


def _validate_source_folder(
    source_folder: Path, parser: argparse.ArgumentParser
) -> tuple[Path, Path, str]:
    """Validate and resolve one sample-data-relative language folder."""
    if source_folder.is_absolute() or ".." in source_folder.parts:
        parser.error("SOURCE_FOLDER must be a relative path below sample-data.")
    source_relative_path = Path(*(part for part in source_folder.parts if part != "."))
    if not source_relative_path.parts:
        parser.error("SOURCE_FOLDER must name a language directory below sample-data.")
    source_language = _validate_language_tag(
        source_relative_path.name, "SOURCE_FOLDER final directory", parser
    )
    sample_data_root = PROJECT_ROOT / "sample-data"
    source_root = sample_data_root / source_relative_path
    if not source_root.is_dir():
        parser.error(f"SOURCE_FOLDER is not an existing directory: {source_relative_path}")
    if not source_root.resolve().is_relative_to(sample_data_root.resolve()):
        parser.error("SOURCE_FOLDER must resolve below sample-data.")
    return source_root, source_relative_path, source_language


def _validate_language_tag(value: str, option_name: str, parser: argparse.ArgumentParser) -> str:
    """Validate a bounded BCP 47 tag accepted by this development command."""
    if not LANGUAGE_TAG_PATTERN.fullmatch(value):
        parser.error(f"{option_name} must be a BCP 47 language tag: {value!r}")
    return value


def _parse_include_patterns(
    option_values: list[str], parser: argparse.ArgumentParser
) -> tuple[str, ...]:
    """Validate include patterns before any scenario output is allocated."""
    try:
        return parse_include_patterns(option_values)
    except ValueError as error:
        parser.error(str(error))
        raise AssertionError("argparse.error exits the process")


def _expand_scenarios(arguments: argparse.Namespace, parser: argparse.ArgumentParser) -> tuple[Scenario, ...]:
    """Expand option collections and all-values selectors into scenarios."""
    text_replacement_factory = TextReplacementProviderFactory.discover_default_plugins()
    ocr_factory = OcrProviderFactory.discover_default_plugins()
    text_replacement_names = text_replacement_factory.provider_names
    ocr_names = ocr_factory.provider_names
    replacement_values = _expand_values(
        arguments.text_replacement, text_replacement_names, "--text-replacement", parser
    )
    ocr_values = _expand_values(arguments.ocr, ocr_names, "--ocr", parser)
    layout_values = _expand_values(
        arguments.document_text_layout,
        DOCUMENT_TEXT_LAYOUT_CHOICES,
        "--document-text-layout",
        parser,
    )
    return tuple(
        Scenario(
            text_replacement,
            ocr,
            layout,
            text_replacement_factory.provider_short_names[text_replacement],
            ocr_factory.provider_short_names[ocr],
        )
        for text_replacement, ocr, layout in product(
            replacement_values, ocr_values, layout_values
        )
    )


def _expand_values(
    option_value: str,
    available_values: tuple[str, ...],
    option_name: str,
    parser: argparse.ArgumentParser,
) -> tuple[str, ...]:
    """Expand one comma-separated option value against its finite domain."""
    values = _split_option_values(option_value, option_name, parser)
    if "all" in values:
        if len(values) != 1:
            parser.error(f"{option_name} value 'all' cannot be combined with other values.")
        return available_values
    unknown_values = tuple(value for value in values if value not in available_values)
    if unknown_values:
        parser.error(
            f"Unknown {option_name} value(s): {', '.join(unknown_values)}. "
            f"Available values: {', '.join(available_values)}."
        )
    return tuple(dict.fromkeys(values))


def _split_option_values(
    option_value: str, option_name: str, parser: argparse.ArgumentParser
) -> tuple[str, ...]:
    """Split one comma-separated option value while rejecting empty entries."""
    values = tuple(part.strip() for part in option_value.split(","))
    if not values or any(not value for value in values):
        parser.error(f"{option_name} values must not be empty.")
    return values


def _create_revision_root(
    source_relative_path: Path, source_language: str, target_language: str
) -> Path:
    """Allocate the next monotonic revision below one source/target root."""
    output_root = (
        PROJECT_ROOT
        / DEVELOPMENT_OUTPUT_ROOT
        / source_relative_path.parent
        / f"{source_language}-{target_language}"
    )
    output_root.mkdir(parents=True, exist_ok=True)
    revision_number = 1
    while True:
        revision_root = output_root / f"v{revision_number}"
        try:
            revision_root.mkdir()
        except FileExistsError:
            revision_number += 1
        else:
            return revision_root


def _scenario_output_root(revision_root: Path, scenario: Scenario) -> Path:
    """Return the deterministic output root for one effective scenario."""
    return (
        revision_root
        / scenario.text_replacement_short_name
        / scenario.ocr_short_name
        / DOCUMENT_TEXT_LAYOUT_SHORT_NAMES[scenario.document_text_layout]
    )


def _folder_replacement_command(
    source_root: Path,
    output_root: Path,
    source_language: str,
    target_language: str,
    scenario: Scenario,
    include_option_values: list[str],
) -> list[str]:
    """Build one direct-script command without processing files in this wrapper."""
    command = [
        sys.executable,
        str(FOLDER_REPLACEMENT_SCRIPT),
        str(source_root),
        str(output_root),
        "--source-language",
        source_language,
        "--target-language",
        target_language,
        "--text-replacement",
        scenario.text_replacement,
        "--ocr",
        scenario.ocr,
        "--document-text-layout",
        scenario.document_text_layout,
        "--debug",
    ]
    for include_option_value in include_option_values:
        command.extend(("--include", include_option_value))
    return command


def _write_manifest(path: Path, manifest: dict[str, object]) -> None:
    """Write the current local-only review manifest deterministically."""
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(main())
