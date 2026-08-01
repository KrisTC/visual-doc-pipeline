#!/usr/bin/env python3
"""Run the project's complete Python static type check."""

from __future__ import annotations

from pathlib import Path
from subprocess import run
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Run mypy with the project's configured Python source directories."""
    completed_process = run(
        [sys.executable, "-m", "mypy", "pipeline", "scripts", "tests"],
        check=False,
        cwd=PROJECT_ROOT,
    )
    return completed_process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
