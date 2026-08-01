"""PaddleOCR implementation of the product OCR-provider protocol."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib import import_module
from numbers import Real
from typing import Protocol, cast

import numpy as np
import numpy.typing as npt

from pipeline.ocr.errors import OcrProviderError
from pipeline.ocr.factory import OcrProviderFactory
from pipeline.ocr.models import BoundingPolygon, OcrRequest, OcrResult, OcrText, PixelPoint
from pipeline.ocr.provider import LocalContractTestCase, LocalContractTestSkip


class PaddleOcrEngine(Protocol):
    """The portion of PaddleOCR's runtime API used by this provider."""

    def predict(
        self,
        image: npt.NDArray[np.uint8],
        *,
        use_doc_orientation_classify: bool,
        use_doc_unwarping: bool,
        use_textline_orientation: bool,
    ) -> object:
        """Recognize text from one image represented as an RGB array."""


class PaddleOcrProvider:
    """OCR provider backed by PaddleOCR's official models."""

    name = "paddleocr"
    supported_languages = frozenset({"en", "ja"})
    supports_local_contract_test = True
    skipped_local_contract_angles = frozenset({90, 135, 180, 225})
    skipped_local_contract_cases = frozenset(
        {
            LocalContractTestSkip(
                LocalContractTestCase("en", "Noto Sans JP Bold", 0, "dark"),
                "PaddleOCR does not detect this white-on-black text style reliably.",
            ),
            LocalContractTestSkip(
                LocalContractTestCase("en", "Noto Sans JP Bold", 270, "dark"),
                "PaddleOCR does not detect this white-on-black text style reliably.",
            ),
        }
    )

    def __init__(self) -> None:
        self._engines: dict[str, PaddleOcrEngine] = {}

    def recognize(self, request: OcrRequest) -> OcrResult:
        """Run PaddleOCR and normalize its output to the OCR task model."""
        native_language = _paddle_language(request.language)
        engine = self._engines.get(native_language)
        if engine is None:
            engine = _create_engine(native_language)
            self._engines[native_language] = engine

        image_array = np.asarray(request.image.convert("RGB"), dtype=np.uint8)
        try:
            raw_result = engine.predict(
                image_array,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        except Exception as error:
            message = f"PaddleOCR failed to process language {request.language!r}."
            raise OcrProviderError(message) from error
        return _parse_result(raw_result)


def register_providers(factory: OcrProviderFactory) -> None:
    """Register PaddleOCR under its stable product-provider name."""
    factory.register(PaddleOcrProvider.name, PaddleOcrProvider)


def _paddle_language(language: str) -> str:
    primary_subtag = language.strip().replace("_", "-").lower().split("-", 1)[0]
    language_names = {"en": "en", "ja": "japan"}
    try:
        return language_names[primary_subtag]
    except KeyError as error:
        message = f"PaddleOCR does not support the language tag {language!r}."
        raise OcrProviderError(message) from error


def _create_engine(language: str) -> PaddleOcrEngine:
    try:
        paddleocr_module = import_module("paddleocr")
        engine_constructor = getattr(paddleocr_module, "PaddleOCR")
        engine = engine_constructor(
            lang=language,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
    except Exception as error:
        message = f"PaddleOCR could not initialize its {language!r} model."
        raise OcrProviderError(message) from error
    # PaddleOCR has no complete static type interface; this is the scoped dynamic-library boundary.
    return cast(PaddleOcrEngine, engine)


def _parse_result(raw_result: object) -> OcrResult:
    text_items: list[OcrText] = []
    for page in _sequence(raw_result, "PaddleOCR result"):
        text_items.extend(_parse_page(page))
    return OcrResult(tuple(text_items))


def _parse_page(page: object) -> list[OcrText]:
    if not isinstance(page, Mapping):
        message = "A PaddleOCR result page must be a mapping."
        raise OcrProviderError(message)
    texts = _sequence(page.get("rec_texts"), "PaddleOCR recognized text")
    confidences = _sequence(page.get("rec_scores"), "PaddleOCR confidence scores")
    polygons = _sequence(page.get("rec_polys"), "PaddleOCR recognized polygons")
    if len(texts) != len(confidences) or len(texts) != len(polygons):
        message = "PaddleOCR result text, confidence, and polygon counts must match."
        raise OcrProviderError(message)
    text_items: list[OcrText] = []
    for text, confidence, polygon in zip(texts, confidences, polygons, strict=True):
        if not isinstance(text, str):
            message = "PaddleOCR recognized text values must be strings."
            raise OcrProviderError(message)
        text_items.append(
            OcrText(
                text=text,
                confidence=_number(confidence, "PaddleOCR confidence"),
                bounding_polygon=_parse_polygon(polygon),
            )
        )
    return text_items


def _parse_polygon(value: object) -> BoundingPolygon:
    vertices = tuple(_parse_point(point) for point in _sequence(value, "PaddleOCR polygon"))
    try:
        return BoundingPolygon(vertices)
    except ValueError as error:
        raise OcrProviderError(str(error)) from error


def _parse_point(value: object) -> PixelPoint:
    coordinates = _sequence(value, "PaddleOCR polygon vertex")
    if len(coordinates) != 2:
        message = "A PaddleOCR polygon vertex must contain x and y coordinates."
        raise OcrProviderError(message)
    return PixelPoint(
        x=_number(coordinates[0], "PaddleOCR polygon x coordinate"),
        y=_number(coordinates[1], "PaddleOCR polygon y coordinate"),
    )


def _sequence(value: object, description: str) -> Sequence[object]:
    if isinstance(value, (list, tuple)):
        return value
    if isinstance(value, np.ndarray):
        # PaddleOCR returns NumPy arrays at this dynamic third-party API boundary.
        return tuple(value.tolist())
    message = f"{description} must be a list or tuple."
    raise OcrProviderError(message)


def _number(value: object, description: str) -> float:
    if isinstance(value, Real):
        return float(value)
    message = f"{description} must be numeric."
    raise OcrProviderError(message)
