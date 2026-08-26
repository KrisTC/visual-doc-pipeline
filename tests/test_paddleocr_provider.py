"""Unit tests for PaddleOCR runtime selection and recovery."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
import unittest
from unittest.mock import patch
import warnings

import numpy as np
from PIL import Image

from pipeline.ocr.models import OcrRequest
from pipeline.ocr_plugins.paddleocr import (
    AUTO_DEVICE,
    CPU_DEVICE,
    GPU_DEVICE,
    PaddleOcrEngine,
    PaddleOcrProvider,
    _EngineRecord,
    _create_engine,
)


class _Engine:
    def __init__(self, result: object | Exception) -> None:
        self._result = result

    def predict(
        self,
        image: np.ndarray[tuple[int, ...], np.dtype[np.uint8]],
        *,
        use_doc_orientation_classify: bool,
        use_doc_unwarping: bool,
        use_textline_orientation: bool,
    ) -> object:
        del image, use_doc_orientation_classify, use_doc_unwarping, use_textline_orientation
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _empty_result() -> list[dict[str, object]]:
    return [{"rec_texts": [], "rec_scores": [], "rec_polys": []}]


class PaddleOcrProviderTests(unittest.TestCase):
    # Verifies FR-2026-08-27-01.
    def test_palette_byte_transparency_is_flattened_without_a_pillow_warning(self) -> None:
        provider = PaddleOcrProvider()
        automatic_record = _EngineRecord(cast(PaddleOcrEngine, _Engine(_empty_result())), AUTO_DEVICE)
        image = Image.new("P", (1, 1))
        image.putpalette([255, 0, 0] + [0] * 765)
        image.info["transparency"] = bytes([128])

        with (
            patch("pipeline.ocr_plugins.paddleocr._create_engine", return_value=automatic_record),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter("always")
            result = provider.recognize(OcrRequest(image, "en"))

        self.assertEqual((), result.text_items)
        self.assertEqual([], [warning for warning in caught if issubclass(warning.category, UserWarning)])

    # Verifies FR-2026-08-21-01.
    def test_automatic_selection_creates_an_automatic_engine(self) -> None:
        provider = PaddleOcrProvider()
        automatic_record = _EngineRecord(cast(PaddleOcrEngine, _Engine(_empty_result())), AUTO_DEVICE)

        with patch(
            "pipeline.ocr_plugins.paddleocr._create_engine", return_value=automatic_record
        ) as create_engine:
            result = provider.recognize(OcrRequest(Image.new("RGB", (1, 1)), "en"))

        self.assertEqual((), result.text_items)
        create_engine.assert_called_once_with("en", AUTO_DEVICE)

    # Verifies FR-2026-08-21-01.
    def test_automatic_failure_retries_once_with_a_cpu_engine(self) -> None:
        provider = PaddleOcrProvider()
        automatic_record = _EngineRecord(cast(PaddleOcrEngine, _Engine(RuntimeError("automatic failed"))), AUTO_DEVICE)
        cpu_record = _EngineRecord(cast(PaddleOcrEngine, _Engine(_empty_result())), CPU_DEVICE)

        with patch(
            "pipeline.ocr_plugins.paddleocr._create_engine",
            side_effect=(automatic_record, cpu_record),
        ) as create_engine:
            result = provider.recognize(OcrRequest(Image.new("RGB", (1, 1)), "en"))

        self.assertEqual((), result.text_items)
        self.assertEqual(
            [("en", AUTO_DEVICE), ("en", CPU_DEVICE)],
            [call.args for call in create_engine.call_args_list],
        )

    # Verifies FR-2026-08-21-01.
    def test_windows_cpu_engine_disables_mkldnn(self) -> None:
        created: list[dict[str, object]] = []

        def create_engine(**kwargs: object) -> _Engine:
            created.append(kwargs)
            return _Engine(_empty_result())

        paddleocr_module = SimpleNamespace(PaddleOCR=create_engine)
        with (
            patch("pipeline.ocr_plugins.paddleocr.import_module", return_value=paddleocr_module),
            patch("pipeline.ocr_plugins.paddleocr.sys.platform", "win32"),
        ):
            _create_engine("en", CPU_DEVICE)

        self.assertEqual(False, created[0]["enable_mkldnn"])
        self.assertEqual(CPU_DEVICE, created[0]["device"])

    # Verifies FR-2026-08-21-01.
    def test_automatic_engine_uses_gpu_when_initialized_paddle_reports_one(self) -> None:
        created: list[dict[str, object]] = []

        def create_engine(**kwargs: object) -> _Engine:
            created.append(kwargs)
            return _Engine(_empty_result())

        paddleocr_module = SimpleNamespace(PaddleOCR=create_engine)
        paddle_module = SimpleNamespace(
            is_compiled_with_cuda=lambda: True,
            device=SimpleNamespace(cuda=SimpleNamespace(device_count=lambda: 1)),
        )
        with patch(
            "pipeline.ocr_plugins.paddleocr.import_module",
            side_effect=(paddleocr_module, paddle_module),
        ):
            _create_engine("en", AUTO_DEVICE)

        self.assertEqual(GPU_DEVICE, created[0]["device"])
