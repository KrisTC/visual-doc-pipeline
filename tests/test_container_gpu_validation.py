"""Tests for the in-image Paddle CUDA validation command."""

from __future__ import annotations

from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

from scripts import validate_container_gpu


class ContainerGpuValidationTests(unittest.TestCase):
    # Verifies FR-2026-09-07-03.
    def test_reports_success_for_a_cuda_enabled_visible_device(self) -> None:
        paddle = SimpleNamespace(
            is_compiled_with_cuda=lambda: True,
            device=SimpleNamespace(cuda=SimpleNamespace(device_count=lambda: 1)),
        )
        with patch.dict(sys.modules, {"paddle": paddle}):
            self.assertEqual(0, validate_container_gpu.main())

    # Verifies FR-2026-09-07-03.
    def test_fails_when_paddle_is_not_cuda_enabled(self) -> None:
        paddle = SimpleNamespace(
            is_compiled_with_cuda=lambda: False,
            device=SimpleNamespace(cuda=SimpleNamespace(device_count=lambda: 0)),
        )
        with patch.dict(sys.modules, {"paddle": paddle}):
            self.assertEqual(1, validate_container_gpu.main())
