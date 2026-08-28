"""PaddleOCR implementation of the product OCR-provider protocol."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from numbers import Real
import sys
from typing import Protocol, cast

import numpy as np
import numpy.typing as npt

from pipeline.ocr.errors import OcrProviderError
from pipeline.ocr.image_preparation import opaque_rgb_for_ocr
from pipeline.ocr.models import BoundingPolygon, OcrRequest, OcrResult, OcrText, PixelPoint
from pipeline.ocr.provider import LocalContractTestCase, LocalContractTestSkip, OcrProvider


def cache_identity() -> str:
    """Return the output-compatible PaddleOCR implementation version for caching."""
    return "paddleocr:3.7.0:paddlepaddle:3.3.1:v1"


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


class PaddleCudaDevice(Protocol):
    """The Paddle CUDA capability operation used for automatic selection."""

    def device_count(self) -> int:
        """Return the number of available CUDA devices."""


class PaddleDeviceModule(Protocol):
    """The Paddle device namespace used for automatic selection."""

    cuda: PaddleCudaDevice


class PaddleRuntime(Protocol):
    """The initialized Paddle runtime capability operations used by this provider."""

    device: PaddleDeviceModule

    def is_compiled_with_cuda(self) -> bool:
        """Return whether the installed Paddle runtime has CUDA support."""


@dataclass(frozen=True, slots=True)
class _EngineRecord:
    """One cached PaddleOCR engine and the device that created it."""

    engine: PaddleOcrEngine
    device: str


CPU_DEVICE = "cpu"
AUTO_DEVICE = "auto"
GPU_DEVICE = "gpu:0"


class PaddleOcrProvider:
    """OCR provider backed by PaddleOCR's official models."""

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
        self._engines: dict[str, _EngineRecord] = {}

    def recognize(self, request: OcrRequest) -> OcrResult:
        """Run PaddleOCR and normalize its output to the OCR task model."""
        native_language = _paddle_language(request.language)
        engine_record = self._engines.get(native_language)
        if engine_record is None:
            try:
                engine_record = _create_engine(native_language, AUTO_DEVICE)
            except OcrProviderError as error:
                engine_record = self._create_cpu_engine(native_language, request.language, error)
            self._engines[native_language] = engine_record

        image_array = np.asarray(opaque_rgb_for_ocr(request.image), dtype=np.uint8)
        try:
            raw_result = _predict(engine_record.engine, image_array)
        except Exception as error:
            raw_result = self._retry_with_cpu(native_language, image_array, request.language, error)
        return _parse_result(raw_result)

    def _create_cpu_engine(
        self, native_language: str, requested_language: str, automatic_error: OcrProviderError
    ) -> _EngineRecord:
        """Create a CPU engine after automatic PaddleOCR initialization fails."""
        try:
            return _create_engine(native_language, CPU_DEVICE)
        except OcrProviderError as error:
            message = (
                f"PaddleOCR could not initialize language {requested_language!r} "
                "with automatic selection or CPU fallback."
            )
            raise OcrProviderError(message) from error

    def _retry_with_cpu(
        self,
        native_language: str,
        image_array: npt.NDArray[np.uint8],
        requested_language: str,
        gpu_error: Exception,
    ) -> object:
        """Retry a failed GPU request once using a cached CPU engine."""
        try:
            cpu_record = _create_engine(native_language, CPU_DEVICE)
            self._engines[native_language] = cpu_record
            return _predict(cpu_record.engine, image_array)
        except Exception as error:
            message = (
                f"PaddleOCR failed to process language {requested_language!r} "
                "on GPU and CPU fallback."
            )
            raise OcrProviderError(message) from error


def create_provider() -> OcrProvider:
    """Create the PaddleOCR provider selected by this package's directory name."""
    return PaddleOcrProvider()


def bootstrap_models() -> None:
    """Initialize every supported language so PaddleOCR populates its own cache."""
    for language in sorted(PaddleOcrProvider.supported_languages):
        native_language = _paddle_language(language)
        try:
            _create_engine(native_language, AUTO_DEVICE)
        except OcrProviderError:
            _create_engine(native_language, CPU_DEVICE)


def _paddle_language(language: str) -> str:
    primary_subtag = language.strip().replace("_", "-").lower().split("-", 1)[0]
    language_names = {"en": "en", "ja": "japan"}
    try:
        return language_names[primary_subtag]
    except KeyError as error:
        message = f"PaddleOCR does not support the language tag {language!r}."
        raise OcrProviderError(message) from error


def _create_engine(language: str, device: str) -> _EngineRecord:
    try:
        paddleocr_module = import_module("paddleocr")
        engine_constructor = getattr(paddleocr_module, "PaddleOCR")
        selected_device = _select_device(device)
        engine_kwargs: dict[str, str | bool] = {
            "lang": language,
            "enable_mkldnn": not (
                selected_device == CPU_DEVICE and sys.platform == "win32"
            ),
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
        }
        engine_kwargs["device"] = selected_device
        engine = engine_constructor(**engine_kwargs)
    except Exception as error:
        message = f"PaddleOCR could not initialize its {language!r} model."
        raise OcrProviderError(message) from error
    # PaddleOCR has no complete static type interface; this is the scoped dynamic-library boundary.
    return _EngineRecord(cast(PaddleOcrEngine, engine), selected_device)


def _select_device(requested_device: str) -> str:
    """Resolve automatic selection only after PaddleOCR has completed its imports."""
    if requested_device != AUTO_DEVICE:
        return requested_device
    try:
        runtime = cast(PaddleRuntime, import_module("paddle"))
        if runtime.is_compiled_with_cuda() and runtime.device.cuda.device_count() > 0:
            return GPU_DEVICE
    except Exception:
        pass
    return CPU_DEVICE


def _predict(engine: PaddleOcrEngine, image: npt.NDArray[np.uint8]) -> object:
    """Run the fixed PaddleOCR prediction configuration for one image."""
    return engine.predict(
        image,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


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
