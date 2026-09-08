#!/usr/bin/env python3
"""Verify that a running OCI image can use an exposed NVIDIA CUDA device."""

from __future__ import annotations

import sys
from importlib import import_module
from typing import Protocol, cast


class _PaddleCudaDevice(Protocol):
    """The CUDA device-count boundary needed by this validation command."""

    def device_count(self) -> int: ...


class _PaddleRuntime(Protocol):
    """The narrow Paddle runtime surface used by this validation command."""

    device: object

    def is_compiled_with_cuda(self) -> bool: ...


def main() -> int:
    """Return success only for CUDA-enabled PaddlePaddle with a visible device."""
    try:
        paddle = cast(_PaddleRuntime, import_module("paddle"))
        if not paddle.is_compiled_with_cuda():
            print("GPU validation failed: PaddlePaddle is not CUDA-enabled.", file=sys.stderr)
            return 1
        cuda_device = cast(_PaddleCudaDevice, getattr(paddle.device, "cuda"))
        device_count = cuda_device.device_count()
    except Exception:
        print(
            "GPU validation failed: CUDA device access is unavailable.", file=sys.stderr
        )
        return 1
    if device_count < 1:
        print("GPU validation failed: no CUDA device is visible.", file=sys.stderr)
        return 1
    print(f"GPU validation passed: {device_count} CUDA device(s) visible.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
