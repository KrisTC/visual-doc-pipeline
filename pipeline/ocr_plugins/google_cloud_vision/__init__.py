"""Google Cloud Vision document-text OCR provider."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from io import BytesIO
import json
import math
import os
from pathlib import Path
from statistics import median
from typing import Protocol, cast

from PIL import Image
import numpy as np
import numpy.typing as npt

from pipeline.ocr.errors import OcrProviderError
from pipeline.ocr.image_preparation import opaque_rgb_for_ocr
from pipeline.ocr.models import BoundingPolygon, OcrRequest, OcrResult, OcrText, PixelPoint
from pipeline.ocr.provider import LocalContractTestSkip, OcrProvider
from pipeline.text_region_colours.estimator import rgb_to_lab


SHORT_NAME = "gcv"
_CREDENTIALS_ENVIRONMENT_VARIABLE = "GOOGLE_APPLICATION_CREDENTIALS"
_PROJECT_ENVIRONMENT_VARIABLE = "GOOGLE_CLOUD_PROJECT"
_LOCATION_ENVIRONMENT_VARIABLE = "GOOGLE_CLOUD_TRANSLATION_LOCATION"
_EU_ENDPOINT = "eu-vision.googleapis.com"
_DEFAULT_TRANSLATION_LOCATION = "europe-west1"
_MAXIMUM_PIXELS = 75_000_000
_MAXIMUM_IMAGE_BYTES = 20_000_000
_REQUEST_TIMEOUT_SECONDS = 120.0
# These constants shape the grouped OCR output, so cache_identity() includes them.
_LINE_GROUPING_VERSION = 3
_MINIMUM_DIRECTION_ALIGNMENT = 0.9
_BASELINE_OFFSET_RATIO = 0.5
_CHARACTER_SIZE_SPLIT_RATIO = 1.1
_WORD_GAP_RATIO = 1.5
# Words are not joined when the surfaces just above and below their facing ends differ
# by at least this CIE76 Lab distance. Calibrated on local evaluation output.
_SURFACE_DIFFERENCE_SPLIT = 40.0
_SURFACE_SAMPLE_THICKNESS = 4
_SURFACE_SPAN_RATIO = 0.3
_MINIMUM_SURFACE_SPAN = 4


def cache_identity() -> str:
    """Return the output-affecting grouping configuration for cache keys and artifacts."""
    return (
        f"google_cloud_vision:documentTextDetection:lines-v{_LINE_GROUPING_VERSION}"
        f":align{_MINIMUM_DIRECTION_ALIGNMENT}:baseline{_BASELINE_OFFSET_RATIO}"
        f":size{_CHARACTER_SIZE_SPLIT_RATIO}:gap{_WORD_GAP_RATIO}"
        f":surface{_SURFACE_DIFFERENCE_SPLIT}:{_SURFACE_SAMPLE_THICKNESS}"
        f":{_SURFACE_SPAN_RATIO}:{_MINIMUM_SURFACE_SPAN}"
    )


class _Vertex(Protocol):
    x: int
    y: int


class _Symbol(Protocol):
    text: str

    @property
    def bounding_box(self) -> _BoundingBox: ...

    @property
    def property(self) -> _TextProperty: ...


class _BreakType(Protocol):
    name: str


class _DetectedBreak(Protocol):
    type_: _BreakType
    is_prefix: bool


class _TextProperty(Protocol):
    detected_break: _DetectedBreak


class _Word(Protocol):
    confidence: float
    symbols: Sequence[_Symbol]

    @property
    def bounding_box(self) -> _BoundingBox: ...

    @property
    def property(self) -> _TextProperty: ...


class _BoundingBox(Protocol):
    vertices: Sequence[_Vertex]


class _Paragraph(Protocol):
    words: Sequence[_Word]


class _Block(Protocol):
    paragraphs: Sequence[_Paragraph]


class _Page(Protocol):
    blocks: Sequence[_Block]


class _TextAnnotation(Protocol):
    pages: Sequence[_Page]


class _ApiError(Protocol):
    code: int


class _Annotation(Protocol):
    error: _ApiError
    full_text_annotation: _TextAnnotation


class _BatchResponse(Protocol):
    responses: Sequence[_Annotation]


class _VisionClient(Protocol):
    def batch_annotate_images(
        self, *, request: Mapping[str, object], timeout: float
    ) -> _BatchResponse: ...


class _VisionClientFactory(Protocol):
    def __call__(self, *, client_options: Mapping[str, str]) -> _VisionClient: ...


@dataclass(frozen=True, slots=True)
class _Configuration:
    project_id: str


@dataclass(frozen=True, slots=True)
class _RecognizedWord:
    text: str
    confidence: float
    polygon: BoundingPolygon
    symbol_count: int
    starts_line: bool
    ends_line: bool
    symbols: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class _Decision:
    """The outcome of comparing one word with the line being built."""

    split_reason: str | None
    measurements: dict[str, float]


class GoogleCloudVisionProvider:
    """Recognize visual lines through synchronous Cloud Vision document OCR."""

    supported_languages = frozenset({"en", "ja"})
    supports_local_contract_test = False
    skipped_local_contract_angles: frozenset[int] = frozenset()
    skipped_local_contract_cases: frozenset[LocalContractTestSkip] = frozenset()

    def __init__(self) -> None:
        self._configuration: _Configuration | None = None
        self._client: _VisionClient | None = None

    def recognize(self, request: OcrRequest) -> OcrResult:
        """Send one in-memory image to the EU endpoint and normalize its lines."""
        if request.language not in self.supported_languages:
            raise OcrProviderError("Google Cloud Vision does not support the requested language.")
        configuration, client = self._initialized_client()
        image = _prepared_image(request)
        image_bytes = _encode_image(image)
        api_request: Mapping[str, object] = {
            "parent": f"projects/{configuration.project_id}/locations/eu",
            "requests": [
                {
                    "image": {"content": image_bytes},
                    "features": [{"type_": "DOCUMENT_TEXT_DETECTION"}],
                }
            ],
        }
        try:
            response = client.batch_annotate_images(
                request=api_request, timeout=_REQUEST_TIMEOUT_SECONDS
            )
        except Exception:
            raise OcrProviderError("Google Cloud Vision OCR request failed.") from None
        try:
            return _parse_response(response, image)
        except OcrProviderError:
            raise
        except Exception:
            raise OcrProviderError("Google Cloud Vision returned malformed OCR data.") from None

    def _initialized_client(self) -> tuple[_Configuration, _VisionClient]:
        if self._configuration is not None and self._client is not None:
            return self._configuration, self._client
        configuration = _load_configuration()
        try:
            module = import_module("google.cloud.vision_v1")
            client_factory = cast(_VisionClientFactory, module.ImageAnnotatorClient)
            client = client_factory(client_options={"api_endpoint": _EU_ENDPOINT})
        except Exception:
            raise OcrProviderError("Google Cloud Vision client initialization failed.") from None
        self._configuration = configuration
        self._client = client
        return configuration, client


def _load_configuration() -> _Configuration:
    credential_value = os.environ.get(_CREDENTIALS_ENVIRONMENT_VARIABLE, "").strip()
    if not credential_value:
        raise OcrProviderError("Google Cloud Vision requires service-account credentials.")
    credential_path = Path(credential_value)
    if not credential_path.is_absolute() or not credential_path.is_file():
        raise OcrProviderError("Google Cloud Vision service-account configuration is invalid.")
    try:
        credential_data = cast(Mapping[str, object], json.loads(credential_path.read_text("utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise OcrProviderError("Google Cloud Vision service-account configuration is invalid.") from None
    if not isinstance(credential_data, dict) or credential_data.get("type") != "service_account":
        raise OcrProviderError("Google Cloud Vision service-account configuration is invalid.")

    project_value = credential_data.get("project_id")
    credential_project = project_value.strip() if isinstance(project_value, str) else ""
    project_id = os.environ.get(_PROJECT_ENVIRONMENT_VARIABLE, "").strip() or credential_project
    if not project_id:
        raise OcrProviderError("Google Cloud Vision requires a Google Cloud project.")
    location = (
        os.environ.get(_LOCATION_ENVIRONMENT_VARIABLE, "").strip()
        or _DEFAULT_TRANSLATION_LOCATION
    )
    if not location.casefold().startswith("europe-"):
        raise OcrProviderError("Google Cloud Vision requires a European location setting.")
    return _Configuration(project_id)


def _prepared_image(request: OcrRequest) -> Image.Image:
    width, height = request.image.size
    if width <= 0 or height <= 0 or width * height > _MAXIMUM_PIXELS:
        raise OcrProviderError("Google Cloud Vision image dimensions exceed the OCR limit.")
    try:
        prepared = opaque_rgb_for_ocr(request.image)
        return Image.frombytes("RGB", prepared.size, prepared.tobytes())
    except Exception:
        raise OcrProviderError("Google Cloud Vision could not encode the image.") from None


def _encode_image(image: Image.Image) -> bytes:
    try:
        output = BytesIO()
        image.save(output, format="PNG")
        image_bytes = output.getvalue()
    except Exception:
        raise OcrProviderError("Google Cloud Vision could not encode the image.") from None
    if len(image_bytes) > _MAXIMUM_IMAGE_BYTES:
        raise OcrProviderError("Google Cloud Vision image exceeds the request size limit.")
    return image_bytes


def _parse_response(response: _BatchResponse, image: Image.Image | None = None) -> OcrResult:
    if len(response.responses) != 1:
        raise OcrProviderError("Google Cloud Vision returned an invalid response count.")
    annotation = response.responses[0]
    if annotation.error.code:
        raise OcrProviderError("Google Cloud Vision rejected the OCR request.")
    pixels = None if image is None else np.asarray(image.convert("RGB"), dtype=np.uint8)
    text_items: list[OcrText] = []
    for page in annotation.full_text_annotation.pages:
        for block in page.blocks:
            for paragraph in block.paragraphs:
                line: list[_RecognizedWord] = []
                # joins[i] holds the measurements that joined line[i + 1] to its predecessor.
                joins: list[dict[str, float]] = []
                started_by = _Decision("paragraph_start", {})
                for word in paragraph.words:
                    recognized = _recognized_word(word)
                    if line:
                        decision = _grouping_decision(line, recognized, pixels)
                        if decision.split_reason is not None:
                            text_items.append(_line_item(line, started_by, joins))
                            line = []
                            joins = []
                            started_by = decision
                        else:
                            joins.append(decision.measurements)
                    line.append(recognized)
                if line:
                    text_items.append(_line_item(line, started_by, joins))
    return OcrResult(tuple(text_items))


def _recognized_word(word: _Word) -> _RecognizedWord:
    if not word.symbols:
        raise OcrProviderError("Google Cloud Vision returned malformed OCR data.")
    parts: list[str] = []
    starts_line = False
    ends_line = False
    last_break_type = "UNKNOWN"
    for symbol in word.symbols:
        if not symbol.text:
            raise OcrProviderError("Google Cloud Vision returned malformed OCR data.")
        detected_break = symbol.property.detected_break
        break_type = detected_break.type_.name
        last_break_type = break_type
        if detected_break.is_prefix:
            starts_line |= _is_line_break(break_type)
            if break_type in {"SPACE", "SURE_SPACE"}:
                parts.append(" ")
        parts.append(symbol.text)
        if not detected_break.is_prefix:
            ends_line |= _is_line_break(break_type)
            if break_type in {"SPACE", "SURE_SPACE"}:
                parts.append(" ")
    if last_break_type == "UNKNOWN":
        word_break = word.property.detected_break
        break_type = word_break.type_.name
        if word_break.is_prefix:
            starts_line |= _is_line_break(break_type)
            if break_type in {"SPACE", "SURE_SPACE"}:
                parts.insert(0, " ")
        else:
            ends_line |= _is_line_break(break_type)
            if break_type in {"SPACE", "SURE_SPACE"}:
                parts.append(" ")
    confidence = float(word.confidence)
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise OcrProviderError("Google Cloud Vision returned malformed OCR data.")
    return _RecognizedWord(
        "".join(parts),
        confidence,
        _word_polygon(word),
        len(word.symbols),
        starts_line,
        ends_line,
        tuple(_symbol_details(symbol) for symbol in word.symbols),
    )


def _symbol_details(symbol: _Symbol) -> dict[str, object]:
    details: dict[str, object] = {"text": symbol.text}
    vertices = symbol.bounding_box.vertices
    if len(vertices) == 4:
        polygon = [[float(vertex.x), float(vertex.y)] for vertex in vertices]
        if all(math.isfinite(value) for point in polygon for value in point):
            details["polygon"] = polygon
    return details


def _is_line_break(break_type: str) -> bool:
    return break_type in {"EOL_SURE_SPACE", "LINE_BREAK", "HYPHEN"}


def _word_polygon(word: _Word) -> BoundingPolygon:
    vertices = word.bounding_box.vertices
    if len(vertices) != 4:
        raise OcrProviderError("Google Cloud Vision returned malformed OCR data.")
    points = tuple(PixelPoint(float(vertex.x), float(vertex.y)) for vertex in vertices)
    if not all(math.isfinite(point.x) and math.isfinite(point.y) for point in points):
        raise OcrProviderError("Google Cloud Vision returned malformed OCR data.")
    width = math.hypot(points[1].x - points[0].x, points[1].y - points[0].y)
    height = math.hypot(points[3].x - points[0].x, points[3].y - points[0].y)
    if width == 0 or height == 0:
        raise OcrProviderError("Google Cloud Vision returned malformed OCR data.")
    return BoundingPolygon(points)


def _axes(polygon: BoundingPolygon) -> tuple[tuple[float, float], tuple[float, float]]:
    first, second = polygon.vertices[:2]
    dx, dy = second.x - first.x, second.y - first.y
    length = math.hypot(dx, dy)
    along = (dx / length, dy / length)
    return along, (-along[1], along[0])


def _extent(
    polygon: BoundingPolygon, direction: tuple[float, float]
) -> tuple[float, float]:
    projections = [point.x * direction[0] + point.y * direction[1] for point in polygon.vertices]
    return min(projections), max(projections)


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator > 0 else 0.0


def _grouping_decision(
    line: list[_RecognizedWord],
    next_word: _RecognizedWord,
    pixels: npt.NDArray[np.uint8] | None = None,
) -> _Decision:
    if next_word.starts_line:
        return _Decision("word_starts_line", {})
    if line[-1].ends_line:
        return _Decision("previous_word_ends_line", {})
    # Compare positions in the first word's reading direction, including rotated text.
    along, across = _axes(line[0].polygon)
    next_along, _ = _axes(next_word.polygon)
    alignment = along[0] * next_along[0] + along[1] * next_along[1]
    measurements = {"direction_alignment": alignment}
    if alignment < _MINIMUM_DIRECTION_ALIGNMENT:
        return _Decision("direction_mismatch", measurements)
    first_across = _extent(line[0].polygon, across)
    next_across = _extent(next_word.polygon, across)
    first_center = sum(first_across) / 2
    next_center = sum(next_across) / 2
    height = max(
        first_across[1] - first_across[0],
        next_across[1] - next_across[0],
    )
    baseline_offset = abs(next_center - first_center)
    measurements["baseline_offset_ratio"] = _ratio(baseline_offset, height)
    previous_along = _extent(line[-1].polygon, along)
    next_along_extent = _extent(next_word.polygon, along)
    gap = next_along_extent[0] - previous_along[1]
    measurements["gap_ratio"] = _ratio(gap, height)
    if baseline_offset > height * _BASELINE_OFFSET_RATIO:
        return _Decision("baseline_offset", measurements)
    # Ignore short bullet and punctuation boxes when comparing character scale.
    prior_heights: list[float] = []
    for word in line:
        if any(character.isalnum() for character in word.text):
            lower, upper = _extent(word.polygon, across)
            prior_heights.append(upper - lower)
    next_height = next_across[1] - next_across[0]
    if prior_heights and any(character.isalnum() for character in next_word.text):
        typical_height = median(prior_heights)
        larger = max(typical_height, next_height)
        smaller = min(typical_height, next_height)
        measurements["character_size_ratio"] = _ratio(larger, smaller)
        if larger >= _CHARACTER_SIZE_SPLIT_RATIO * smaller:
            return _Decision("character_size", measurements)
    # A wide gap on the same baseline usually separates labels or columns.
    if gap > height * _WORD_GAP_RATIO:
        return _Decision("word_gap", measurements)
    # Last, because sampling pixels is the costliest rule and only matters for a join.
    # Overlapping boxes have no gap, so there are no distinct surfaces to compare.
    if pixels is not None and gap > 0:
        difference = _surface_difference(pixels, line[-1], next_word, along, across)
        if difference is not None:
            measurements["background_colour_difference"] = difference
            if difference >= _SURFACE_DIFFERENCE_SPLIT:
                return _Decision("background_colour", measurements)
    return _Decision(None, measurements)


def _surface_colour(
    pixels: npt.NDArray[np.uint8],
    word: _RecognizedWord,
    along: tuple[float, float],
    across: tuple[float, float],
    facing_end: bool,
) -> npt.NDArray[np.float64] | None:
    """Return the median Lab colour of thin strips just outside one end of a word box.

    The strips lie above and below the box, so they sample the surface behind the text
    rather than its glyphs. Only the end that faces the neighbouring word is sampled so a
    gradual change across a long line is not mistaken for a boundary between words.
    """
    along_low, along_high = _extent(word.polygon, along)
    across_low, across_high = _extent(word.polygon, across)
    span = max(float(_MINIMUM_SURFACE_SPAN), (along_high - along_low) * _SURFACE_SPAN_RATIO)
    start, stop = (along_high - span, along_high) if facing_end else (along_low, along_low + span)
    along_values = np.arange(start, stop, 1.0)
    thickness = float(_SURFACE_SAMPLE_THICKNESS)
    across_values = np.concatenate(
        (
            np.arange(across_low - thickness, across_low, 1.0),
            np.arange(across_high, across_high + thickness, 1.0),
        )
    )
    along_grid, across_grid = np.meshgrid(along_values, across_values)
    columns = np.floor(along_grid * along[0] + across_grid * across[0]).astype(np.int64)
    rows = np.floor(along_grid * along[1] + across_grid * across[1]).astype(np.int64)
    height, width = pixels.shape[:2]
    inside = (columns >= 0) & (columns < width) & (rows >= 0) & (rows < height)
    if not np.any(inside):
        return None
    samples = pixels[rows[inside], columns[inside]].reshape(1, -1, 3)
    return cast("npt.NDArray[np.float64]", np.median(rgb_to_lab(samples)[0], axis=0))


def _surface_difference(
    pixels: npt.NDArray[np.uint8],
    previous_word: _RecognizedWord,
    next_word: _RecognizedWord,
    along: tuple[float, float],
    across: tuple[float, float],
) -> float | None:
    previous_surface = _surface_colour(pixels, previous_word, along, across, True)
    next_surface = _surface_colour(pixels, next_word, along, across, False)
    if previous_surface is None or next_surface is None:
        return None
    return float(np.linalg.norm(previous_surface - next_surface))


def _polygon_points(polygon: BoundingPolygon) -> list[list[float]]:
    return [[point.x, point.y] for point in polygon.vertices]


def _grouping_extra(
    words: list[_RecognizedWord], started_by: _Decision, joins: list[dict[str, float]]
) -> dict[str, object]:
    """Describe the original Vision words and decisions behind one grouped region."""
    word_details: list[dict[str, object]] = []
    for index, word in enumerate(words):
        detail: dict[str, object] = {
            "text": word.text,
            "confidence": word.confidence,
            "polygon": _polygon_points(word.polygon),
            "starts_line": word.starts_line,
            "ends_line": word.ends_line,
            "symbols": list(word.symbols),
        }
        if index > 0:
            detail["joined_measurements"] = joins[index - 1]
        word_details.append(detail)
    return {
        "google_cloud_vision": {
            "grouping_version": _LINE_GROUPING_VERSION,
            "thresholds": {
                "minimum_direction_alignment": _MINIMUM_DIRECTION_ALIGNMENT,
                "baseline_offset_ratio": _BASELINE_OFFSET_RATIO,
                "character_size_split_ratio": _CHARACTER_SIZE_SPLIT_RATIO,
                "word_gap_ratio": _WORD_GAP_RATIO,
                "surface_difference_split": _SURFACE_DIFFERENCE_SPLIT,
                "surface_sample_thickness": _SURFACE_SAMPLE_THICKNESS,
                "surface_span_ratio": _SURFACE_SPAN_RATIO,
            },
            "region_started_by": {
                "reason": started_by.split_reason,
                "measurements": started_by.measurements,
            },
            "words": word_details,
        }
    }


def _line_item(
    words: list[_RecognizedWord], started_by: _Decision, joins: list[dict[str, float]]
) -> OcrText:
    text = "".join(word.text for word in words).strip()
    if not text:
        raise OcrProviderError("Google Cloud Vision returned malformed OCR data.")
    total_symbols = sum(word.symbol_count for word in words)
    confidence = sum(word.confidence * word.symbol_count for word in words) / total_symbols
    if len(words) == 1:
        polygon = words[0].polygon
    else:
        along, across = _axes(words[0].polygon)
        points = tuple(point for word in words for point in word.polygon.vertices)
        along_values = [point.x * along[0] + point.y * along[1] for point in points]
        across_values = [point.x * across[0] + point.y * across[1] for point in points]
        left, right = min(along_values), max(along_values)
        top, bottom = min(across_values), max(across_values)

        def corner(distance_along: float, distance_across: float) -> PixelPoint:
            return PixelPoint(
                distance_along * along[0] + distance_across * across[0],
                distance_along * along[1] + distance_across * across[1],
            )

        polygon = BoundingPolygon(
            (
                corner(left, top),
                corner(right, top),
                corner(right, bottom),
                corner(left, bottom),
            )
        )
    return OcrText(text, confidence, polygon, _grouping_extra(words, started_by, joins))


def create_provider() -> OcrProvider:
    """Create the provider registered under its plugin-directory name."""
    return GoogleCloudVisionProvider()
