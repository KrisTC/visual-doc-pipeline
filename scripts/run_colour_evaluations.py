#!/usr/bin/env python3
"""Generate local HTML evaluations for OCR text-region colour estimates."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import html
import json
import os
from pathlib import Path
import sys
from typing import cast


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from PIL import Image

from pipeline.ocr.models import BoundingPolygon, OcrText, PixelPoint
from pipeline.text_region_colours import (
    RgbaColour,
    TextRegionColourEstimate,
    estimate_text_region_colours,
)


SUCCEEDED_STATUS = "succeeded"


@dataclass
class ColourEvaluationRunResult:
    """Counts produced by one local colour-evaluation run."""

    processed_json_files: int = 0
    skipped_json_files: int = 0
    written_pages: int = 0


@dataclass(frozen=True)
class EvaluationTextItem:
    """One parsed OCR item and its existing padded text-region bitmap."""

    ocr_text: OcrText
    padded_image_path: Path


def evaluate_colour_examples(input_root: Path, output_root: Path) -> ColourEvaluationRunResult:
    """Write one HTML evaluation page for each eligible OCR-result JSON file.

    The input file's adjacent source image is found by removing the ``.json``
    suffix. Invalid, failed, or unpaired results are reported and skipped so they
    cannot prevent other local examples from being evaluated.
    """
    if not input_root.is_dir():
        message = f"Input root does not exist or is not a directory: {input_root}"
        raise ValueError(message)

    result = ColourEvaluationRunResult()
    for result_path in sorted(input_root.rglob("*.json")):
        result.processed_json_files += 1
        source_image_path = result_path.with_suffix("")
        if not source_image_path.is_file():
            _skip(result, result_path, "paired source image is missing")
            continue
        try:
            text_items = _read_successful_text_items(result_path, input_root)
            if text_items is None:
                _skip(result, result_path, "OCR result status is not succeeded")
                continue
            with Image.open(source_image_path) as image:
                estimates = tuple(
                    estimate_text_region_colours(image, text_item.ocr_text)
                    for text_item in text_items
                )
        except (OSError, ValueError) as error:
            _skip(result, result_path, str(error))
            continue

        output_path = (output_root / result_path.relative_to(input_root)).with_suffix(".html")
        _write_html_page(
            output_path,
            result_path.relative_to(input_root),
            text_items,
            estimates,
        )
        result.written_pages += 1
    return result


def _read_successful_text_items(
    result_path: Path, input_root: Path
) -> tuple[EvaluationTextItem, ...] | None:
    document = _json_mapping(_load_json(result_path), result_path)
    status = _required_string(document, "status", result_path)
    if status != SUCCEEDED_STATUS:
        return None
    raw_items = _required_list(document, "text_items", result_path)
    return tuple(
        _parse_text_item(item, result_path, input_root, index)
        for index, item in enumerate(raw_items, 1)
    )


def _load_json(path: Path) -> object:
    # json.loads exposes untyped JSON data; retain it as object until validated below.
    return cast(object, json.loads(path.read_text(encoding="utf-8")))


def _parse_text_item(
    value: object, path: Path, input_root: Path, index: int
) -> EvaluationTextItem:
    item = _json_mapping(value, path, f"text_items[{index}]")
    text = _required_string(item, "text", path)
    confidence = _required_number(item, "confidence", path)
    raw_vertices = _required_list(item, "bounding_polygon", path)
    padded_image_value = _required_string(item, "padded_image_path", path)
    vertices = tuple(
        _parse_point(vertex, path, index, point_index)
        for point_index, vertex in enumerate(raw_vertices, 1)
    )
    padded_image_path = _resolve_padded_image_path(path, input_root, padded_image_value)
    if not padded_image_path.is_file():
        message = f"{path}: padded text-region bitmap is missing: {padded_image_value}"
        raise ValueError(message)
    return EvaluationTextItem(
        ocr_text=OcrText(text=text, confidence=confidence, bounding_polygon=BoundingPolygon(vertices)),
        padded_image_path=padded_image_path,
    )


def _resolve_padded_image_path(result_path: Path, input_root: Path, value: str) -> Path:
    relative_path = Path(value)
    if relative_path.is_absolute():
        message = f"{result_path}: padded_image_path must be relative."
        raise ValueError(message)
    candidate = (result_path.parent / relative_path).resolve()
    try:
        candidate.relative_to(input_root.resolve())
    except ValueError as error:
        message = f"{result_path}: padded_image_path escapes the input root."
        raise ValueError(message) from error
    return candidate


def _parse_point(value: object, path: Path, item_index: int, point_index: int) -> PixelPoint:
    point = _json_mapping(value, path, f"text_items[{item_index}].bounding_polygon[{point_index}]")
    return PixelPoint(
        x=_required_number(point, "x", path),
        y=_required_number(point, "y", path),
    )


def _json_mapping(value: object, path: Path, context: str = "document") -> dict[str, object]:
    if not isinstance(value, dict):
        message = f"{path}: {context} must be an object."
        raise ValueError(message)
    mapping: dict[str, object] = {}
    for key, child_value in value.items():
        if not isinstance(key, str):
            message = f"{path}: {context} contains a non-string key."
            raise ValueError(message)
        mapping[key] = child_value
    return mapping


def _required_string(mapping: dict[str, object], key: str, path: Path) -> str:
    value = mapping.get(key)
    if not isinstance(value, str):
        message = f"{path}: {key} must be a string."
        raise ValueError(message)
    return value


def _required_number(mapping: dict[str, object], key: str, path: Path) -> float:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        message = f"{path}: {key} must be a number."
        raise ValueError(message)
    return float(value)


def _required_list(mapping: dict[str, object], key: str, path: Path) -> list[object]:
    value = mapping.get(key)
    if not isinstance(value, list):
        message = f"{path}: {key} must be an array."
        raise ValueError(message)
    return list(value)


def _write_html_page(
    output_path: Path,
    result_path: Path,
    text_items: tuple[EvaluationTextItem, ...],
    estimates: tuple[TextRegionColourEstimate, ...],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    padded_image_urls = tuple(
        Path(os.path.relpath(text_item.padded_image_path, output_path.parent.resolve())).as_posix()
        for text_item in text_items
    )
    output_path.write_text(
        _page_html(result_path, text_items, estimates, padded_image_urls), encoding="utf-8"
    )


def _page_html(
    result_path: Path,
    text_items: tuple[EvaluationTextItem, ...],
    estimates: tuple[TextRegionColourEstimate, ...],
    padded_image_urls: tuple[str, ...],
) -> str:
    title = html.escape(result_path.as_posix())
    if text_items:
        rows = "\n".join(
            _estimate_row(index, text_item, estimate, padded_image_url)
            for index, (text_item, estimate, padded_image_url) in enumerate(
                zip(text_items, estimates, padded_image_urls, strict=True), 1
            )
        )
    else:
        rows = '<tr><td colspan="5">No OCR text regions.</td></tr>'
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Colour-estimation evaluation: {title}</title>
  <style>
    body {{ background: #f6f7f9; color: #1f2937; font-family: system-ui, sans-serif; margin: 0; }}
    main {{ margin: 0 auto; max-width: 1500px; padding: 2rem; }}
    table {{ background: white; border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #cbd5e1; padding: .55rem; text-align: left; vertical-align: top; }}
    th {{ background: #e9eef5; white-space: nowrap; }}
    .text-image {{ min-width: 120px; text-align: right; }} .text-image img {{ display: block; height: auto; margin-left: auto; max-height: 120px; max-width: 260px; }}
    .text {{ max-width: 24rem; white-space: pre-wrap; }} .confidence {{ text-align: right; white-space: nowrap; }}
    .colour {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; min-width: 15ch; }}
  </style>
</head>
<body>
  <main>
    <h1>Colour-estimation evaluation</h1>
    <p>OCR result: <code>{title}</code></p>
    <table>
      <thead><tr><th>Region</th><th>Text image</th><th>Recognized text</th><th>Background</th><th>Foreground</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </main>
</body>
</html>
"""


def _estimate_row(
    index: int,
    text_item: EvaluationTextItem,
    estimate: TextRegionColourEstimate,
    padded_image_url: str,
) -> str:
    escaped_url = html.escape(padded_image_url, quote=True)
    return f"""<tr>
  <td>{index}</td>
  <td class="text-image"><img alt="Padded text region {index}" src="{escaped_url}"></td>
  {_recognised_text_cell(text_item.ocr_text.text, estimate.background_colour, estimate.text_colour)}
  {_primary_colour_cell(
        estimate.background_colour,
        estimate.background_colour_confidence,
        estimate.background_kind.value,
    )}
  {_primary_colour_cell(estimate.text_colour, estimate.text_colour_confidence)}
</tr>"""


def _primary_colour_cell(
    colour: RgbaColour, confidence: float, background_kind: str | None = None
) -> str:
    lines = [_colour_code(colour), f"{confidence:.2%}"]
    if background_kind is not None:
        lines.append(html.escape(background_kind))
    return _colour_swatch_cell(colour, "<br>".join(lines))


def _recognised_text_cell(text: str, background_colour: RgbaColour, text_colour: RgbaColour) -> str:
    style = (
        f"background-color: {_css_rgba(background_colour)}; "
        f"color: {_css_rgba(text_colour)};"
    )
    return f'<td class="text" style="{style}">{html.escape(text)}</td>'


def _colour_swatch_cell(colour: RgbaColour, label: str) -> str:
    alpha = colour.alpha / 255.0
    luminance = (
        (0.2126 * colour.red + 0.7152 * colour.green + 0.0722 * colour.blue) * alpha
        + 255.0 * (1.0 - alpha)
    )
    foreground = "#000000" if luminance >= 140.0 else "#ffffff"
    style = (
        f"background-color: {_css_rgba(colour)}; "
        f"color: {foreground};"
    )
    return f'<td class="colour" style="{style}"><code>{label}</code></td>'


def _colour_code(colour: RgbaColour) -> str:
    """Return the compact HTML hexadecimal representation without losing alpha."""
    rgb_code = f"#{colour.red:02X}{colour.green:02X}{colour.blue:02X}"
    return rgb_code if colour.alpha == 255 else f"{rgb_code}{colour.alpha:02X}"


def _css_rgba(colour: RgbaColour) -> str:
    """Return a CSS RGBA colour with the model's eight-bit alpha normalized."""
    return f"rgba({colour.red}, {colour.green}, {colour.blue}, {colour.alpha / 255.0:.3f})"


def _skip(result: ColourEvaluationRunResult, path: Path, reason: str) -> None:
    result.skipped_json_files += 1
    print(f"Skipping {path}: {reason}.")


def parse_arguments() -> argparse.Namespace:
    """Return command-line arguments for the local colour evaluator."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-root", type=Path, default=Path("sample-data/color-detection-examples")
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("outputs/evaluations/color-detection-examples")
    )
    return parser.parse_args()


def main() -> int:
    """Run the local colour evaluator from the command line."""
    arguments = parse_arguments()
    result = evaluate_colour_examples(arguments.input_root, arguments.output_root)
    print(
        "Colour evaluation complete: "
        f"{result.written_pages} page(s) written, {result.skipped_json_files} JSON file(s) skipped."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
