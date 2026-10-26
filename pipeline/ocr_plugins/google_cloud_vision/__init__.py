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

from pipeline.ocr.errors import OcrProviderError
from pipeline.ocr.image_preparation import opaque_rgb_for_ocr
from pipeline.ocr.models import BoundingPolygon, OcrRequest, OcrResult, OcrText, PixelPoint
from pipeline.ocr.provider import LocalContractTestSkip, OcrProvider


SHORT_NAME = "gcv"
_CREDENTIALS_ENVIRONMENT_VARIABLE = "GOOGLE_APPLICATION_CREDENTIALS"
_PROJECT_ENVIRONMENT_VARIABLE = "GOOGLE_CLOUD_PROJECT"
_LOCATION_ENVIRONMENT_VARIABLE = "GOOGLE_CLOUD_TRANSLATION_LOCATION"
_EU_ENDPOINT = "eu-vision.googleapis.com"
_DEFAULT_TRANSLATION_LOCATION = "europe-west1"
_MAXIMUM_PIXELS = 75_000_000
_MAXIMUM_IMAGE_BYTES = 20_000_000
_REQUEST_TIMEOUT_SECONDS = 120.0


class _Vertex(Protocol):
    x: int
    y: int


class _Symbol(Protocol):
    text: str

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
        image_bytes = _encode_image(request)
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
            return _parse_response(response)
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


def _encode_image(request: OcrRequest) -> bytes:
    width, height = request.image.size
    if width <= 0 or height <= 0 or width * height > _MAXIMUM_PIXELS:
        raise OcrProviderError("Google Cloud Vision image dimensions exceed the OCR limit.")
    try:
        prepared = opaque_rgb_for_ocr(request.image)
        image = Image.frombytes("RGB", prepared.size, prepared.tobytes())
        output = BytesIO()
        image.save(output, format="PNG")
        image_bytes = output.getvalue()
    except Exception:
        raise OcrProviderError("Google Cloud Vision could not encode the image.") from None
    if len(image_bytes) > _MAXIMUM_IMAGE_BYTES:
        raise OcrProviderError("Google Cloud Vision image exceeds the request size limit.")
    return image_bytes


def _parse_response(response: _BatchResponse) -> OcrResult:
    if len(response.responses) != 1:
        raise OcrProviderError("Google Cloud Vision returned an invalid response count.")
    annotation = response.responses[0]
    if annotation.error.code:
        raise OcrProviderError("Google Cloud Vision rejected the OCR request.")
    text_items: list[OcrText] = []
    for page in annotation.full_text_annotation.pages:
        for block in page.blocks:
            for paragraph in block.paragraphs:
                line: list[_RecognizedWord] = []
                for word in paragraph.words:
                    recognized = _recognized_word(word)
                    if line and (
                        recognized.starts_line
                        or line[-1].ends_line
                        or not _same_visual_line(line, recognized)
                    ):
                        text_items.append(_line_item(line))
                        line = []
                    line.append(recognized)
                if line:
                    text_items.append(_line_item(line))
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
    )


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


def _same_visual_line(line: list[_RecognizedWord], next_word: _RecognizedWord) -> bool:
    # Compare positions in the first word's reading direction, including rotated text.
    along, across = _axes(line[0].polygon)
    next_along, _ = _axes(next_word.polygon)
    if along[0] * next_along[0] + along[1] * next_along[1] < 0.9:
        return False
    first_across = _extent(line[0].polygon, across)
    next_across = _extent(next_word.polygon, across)
    first_center = sum(first_across) / 2
    next_center = sum(next_across) / 2
    height = max(
        first_across[1] - first_across[0],
        next_across[1] - next_across[0],
    )
    if abs(next_center - first_center) > height * 0.5:
        return False
    # Ignore short bullet and punctuation boxes when comparing character scale.
    prior_heights: list[float] = []
    for word in line:
        if any(character.isalnum() for character in word.text):
            lower, upper = _extent(word.polygon, across)
            prior_heights.append(upper - lower)
    next_height = next_across[1] - next_across[0]
    if prior_heights and any(character.isalnum() for character in next_word.text):
        typical_height = median(prior_heights)
        if max(typical_height, next_height) >= 1.35 * min(typical_height, next_height):
            return False
    # A wide gap on the same baseline usually separates labels or columns.
    previous_along = _extent(line[-1].polygon, along)
    next_along_extent = _extent(next_word.polygon, along)
    return next_along_extent[0] - previous_along[1] <= height * 1.5


def _line_item(words: list[_RecognizedWord]) -> OcrText:
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
    return OcrText(text, confidence, polygon)


def create_provider() -> OcrProvider:
    """Create the provider registered under its plugin-directory name."""
    return GoogleCloudVisionProvider()
