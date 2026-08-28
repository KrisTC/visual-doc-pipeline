#!/usr/bin/env python3
"""Generate local OCR-region source-language-to-English replacement evaluations."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import html
import json
from math import ceil, floor
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from PIL import Image
# skia-python does not publish PEP 561 stubs; this is the native rendering boundary.
import skia  # type: ignore[import-not-found]

from pipeline.text_region_colours import estimate_text_region_colours
from pipeline.text_region_rendering import replace_text_region
from pipeline.text_replacement import TextReplacementProviderFactory, TextReplacementRequest
from pipeline.provider_cache import source_cache_scope
from scripts.run_colour_evaluations import EvaluationTextItem, _read_successful_text_items


DEFAULT_FONT_PATH = PROJECT_ROOT / "tests" / "assets" / "fonts" / "NotoSansJP[wght].ttf"
FONT_WEIGHT_AXIS_TAG = 0x77676874
DEFAULT_FONT_WEIGHT = 500.0
CONFIDENTIAL_SAMPLE_ROOT = PROJECT_ROOT / "sample-data" / "confidential"
TEXT_CLIP_PADDING = 20


@dataclass
class TextReplacementEvaluationRunResult:
    """Counts produced by one local text-replacement evaluation run."""

    processed_json_files: int = 0
    skipped_json_files: int = 0
    written_pages: int = 0


@dataclass(frozen=True)
class _ProviderOutput:
    """One provider's rendered bitmap for a text region."""

    provider_name: str
    image_path: Path


def evaluate_text_replacement_examples(
    input_root: Path, output_root: Path
) -> TextReplacementEvaluationRunResult:
    """Write one source-language-to-English replacement page per eligible JSON result."""
    if not input_root.is_dir():
        message = f"Input root does not exist or is not a directory: {input_root}"
        raise ValueError(message)
    typeface = _load_default_typeface()
    factory = TextReplacementProviderFactory.discover_default_plugins()
    provider_names = factory.local_evaluation_provider_names
    result = TextReplacementEvaluationRunResult()
    for result_path in sorted(input_root.rglob("*.json")):
        result.processed_json_files += 1
        if _is_confidential_sample_path(result_path):
            _skip(result, result_path, "confidential sample data is excluded")
            continue
        source_image_path = result_path.with_suffix("")
        if not source_image_path.is_file():
            _skip(result, result_path, "paired source image is missing")
            continue
        try:
            text_items = _read_successful_text_items(result_path, input_root)
            if text_items is None:
                _skip(result, result_path, "OCR result status is not succeeded")
                continue
            source_language = _read_source_language(result_path)
            with Image.open(source_image_path) as source:
                source_image = source.copy()
            output_path = (output_root / result_path.relative_to(input_root)).with_suffix(".html")
            with source_cache_scope(source_image_path):
                rows = _render_rows(
                    source_image,
                    text_items,
                    factory,
                    provider_names,
                    typeface,
                    output_path,
                    source_language,
                )
        except (OSError, RuntimeError, ValueError) as error:
            _skip(result, result_path, str(error))
            continue

        _write_html_page(
            output_path,
            result_path.relative_to(input_root),
            text_items,
            rows,
            provider_names,
            source_language,
        )
        result.written_pages += 1
    return result


def _is_confidential_sample_path(path: Path) -> bool:
    """Return whether ``path`` is inside the repository's excluded sample subtree."""
    try:
        path.resolve().relative_to(CONFIDENTIAL_SAMPLE_ROOT.resolve())
    except ValueError:
        return False
    return True


def _load_default_typeface() -> skia.Typeface:
    if not DEFAULT_FONT_PATH.is_file():
        message = f"The replacement evaluator requires {DEFAULT_FONT_PATH}."
        raise RuntimeError(message)
    typeface = skia.Typeface.MakeFromFile(str(DEFAULT_FONT_PATH))
    if typeface is None:
        message = f"Skia could not load the evaluator typeface {DEFAULT_FONT_PATH}."
        raise RuntimeError(message)
    arguments = skia.FontArguments()
    coordinates = skia.FontArguments.VariationPosition.Coordinates(
        [
            skia.FontArguments.VariationPosition.Coordinate(
                FONT_WEIGHT_AXIS_TAG, DEFAULT_FONT_WEIGHT
            )
        ]
    )
    arguments.setVariationDesignPosition(skia.FontArguments.VariationPosition(coordinates))
    bold_typeface = typeface.makeClone(arguments)
    if bold_typeface is None:
        message = f"Skia could not select wght={DEFAULT_FONT_WEIGHT:g} for {DEFAULT_FONT_PATH}."
        raise RuntimeError(message)
    return bold_typeface


def _read_source_language(result_path: Path) -> str:
    """Read the required source language from a successful OCR result JSON."""
    document = json.loads(result_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{result_path}: OCR result must be an object.")
    source_language = document.get("source_language")
    if not isinstance(source_language, str) or not source_language.strip():
        raise ValueError(f"{result_path}: source_language must be a non-empty string.")
    return source_language


def _render_rows(
    source_image: Image.Image,
    text_items: tuple[EvaluationTextItem, ...],
    factory: TextReplacementProviderFactory,
    provider_names: tuple[str, ...],
    typeface: skia.Typeface,
    output_path: Path,
    source_language: str,
) -> tuple[tuple[_ProviderOutput, ...], ...]:
    rows: list[tuple[_ProviderOutput, ...]] = []
    image_directory = output_path.with_name(f"{output_path.stem}.replacement-images")
    for region_index, text_item in enumerate(text_items, 1):
        estimate = estimate_text_region_colours(source_image, text_item.ocr_text)
        outputs: list[_ProviderOutput] = []
        for provider_index, provider_name in enumerate(provider_names, 1):
            provider = factory.create(provider_name)
            replacement = provider.replace(
                TextReplacementRequest(
                    text=text_item.ocr_text.text,
                    is_filename=False,
                    source_language=source_language,
                    target_language="en",
                )
            )
            rendered_image = source_image.copy()
            replace_text_region(
                rendered_image,
                text_item.ocr_text,
                estimate,
                replacement.text,
                typeface,
                target_language="en",
            )
            image_path = image_directory / f"region-{region_index:04d}.provider-{provider_index:04d}.png"
            image_path.parent.mkdir(parents=True, exist_ok=True)
            _text_clip(rendered_image, text_item).save(image_path, format="PNG")
            outputs.append(_ProviderOutput(provider_name=provider_name, image_path=image_path))
        rows.append(tuple(outputs))
    return tuple(rows)


def _text_clip(image: Image.Image, text_item: EvaluationTextItem) -> Image.Image:
    vertices = text_item.ocr_text.bounding_polygon.vertices
    left = max(0, floor(min(point.x for point in vertices)) - TEXT_CLIP_PADDING)
    top = max(0, floor(min(point.y for point in vertices)) - TEXT_CLIP_PADDING)
    right = min(image.width, ceil(max(point.x for point in vertices)) + TEXT_CLIP_PADDING)
    bottom = min(image.height, ceil(max(point.y for point in vertices)) + TEXT_CLIP_PADDING)
    return image.crop((left, top, right, bottom))


def _write_html_page(
    output_path: Path,
    result_path: Path,
    text_items: tuple[EvaluationTextItem, ...],
    rows: tuple[tuple[_ProviderOutput, ...], ...],
    provider_names: tuple[str, ...],
    source_language: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    padded_image_urls = tuple(
        Path(os.path.relpath(item.padded_image_path, output_path.parent.resolve())).as_posix()
        for item in text_items
    )
    output_path.write_text(
        _page_html(result_path, padded_image_urls, rows, provider_names, source_language),
        encoding="utf-8",
    )


def _page_html(
    result_path: Path,
    padded_image_urls: tuple[str, ...],
    rows: tuple[tuple[_ProviderOutput, ...], ...],
    provider_names: tuple[str, ...],
    source_language: str,
) -> str:
    title = html.escape(result_path.as_posix())
    headers = "".join(f"<th>{html.escape(name)}</th>" for name in provider_names)
    if rows:
        body_rows = "\n".join(
            _html_row(index, padded_image_url, outputs)
            for index, (padded_image_url, outputs) in enumerate(
                zip(padded_image_urls, rows, strict=True), 1
            )
        )
    else:
        body_rows = f'<tr><td colspan="{2 + len(provider_names)}">No OCR text regions.</td></tr>'
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Text-replacement evaluation: {title}</title>
  <style>
    body {{ background: #f6f7f9; color: #1f2937; font-family: system-ui, sans-serif; margin: 0; }}
    main {{ margin: 0 auto; max-width: 1500px; padding: 2rem; }}
    table {{ background: white; border-collapse: collapse; width: auto; }}
    th, td {{ border: 1px solid #cbd5e1; padding: .55rem; text-align: left; vertical-align: top; }}
    th {{ background: #e9eef5; white-space: nowrap; }}
    .text-image {{ min-width: 120px; text-align: right; }}
    .text-image img {{ display: block; height: auto; margin-left: auto; max-height: 160px; max-width: 300px; }}
  </style>
</head>
<body>
  <main>
    <h1>Text-replacement evaluation</h1>
    <p>OCR result: <code>{title}</code> <span>{html.escape(source_language)}→en</span></p>
    <table>
      <thead><tr><th>Region</th><th>Original text image</th>{headers}</tr></thead>
      <tbody>{body_rows}</tbody>
    </table>
  </main>
</body>
</html>
"""


def _html_row(index: int, padded_image_url: str, outputs: tuple[_ProviderOutput, ...]) -> str:
    provider_cells = "".join(
        _image_cell(
            Path(os.path.relpath(output.image_path, output.image_path.parents[1])).as_posix(),
            f"Replacement from {output.provider_name} for region {index}",
        )
        for output in outputs
    )
    return (
        f"<tr><td>{index}</td>"
        f'{_image_cell(padded_image_url, f"Original text region {index}")}'
        f"{provider_cells}</tr>"
    )


def _image_cell(url: str, alternative_text: str) -> str:
    return (
        '<td class="text-image"><img '
        f'alt="{html.escape(alternative_text, quote=True)}" '
        f'src="{html.escape(url, quote=True)}"></td>'
    )


def _skip(result: TextReplacementEvaluationRunResult, path: Path, reason: str) -> None:
    result.skipped_json_files += 1
    print(f"Skipping {path}: {reason}.")


def parse_arguments() -> argparse.Namespace:
    """Return command-line arguments for the local text-replacement evaluator."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-root", type=Path, default=Path("sample-data/color-detection-examples")
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("outputs/evaluations/text-replacement-examples")
    )
    return parser.parse_args()


def main() -> int:
    """Run the local text-replacement evaluator from the command line."""
    arguments = parse_arguments()
    result = evaluate_text_replacement_examples(arguments.input_root, arguments.output_root)
    print(
        "OCR text-replacement evaluation complete: "
        f"{result.written_pages} page(s) written, {result.skipped_json_files} JSON file(s) skipped."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
