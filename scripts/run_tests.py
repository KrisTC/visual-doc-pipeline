#!/usr/bin/env python3
"""Run the automated test suite; invoked by scripts/run-tests.sh and run-tests.ps1."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIRECTORY = PROJECT_ROOT / "tests"
FAST_TESTS_ENVIRONMENT_VARIABLE = "VISUAL_DOC_PIPELINE_FAST_TESTS"
RESERVED_CORES = 2


def default_worker_count(available_cores: int) -> int:
    """Leave cores free for the developer's other work, but always use at least one."""
    return max(1, available_cores - RESERVED_CORES)


def _available_cores() -> int:
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0))
    return os.cpu_count() or 1


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the automated tests. Arguments not listed here are passed to pytest, or to "
            "unittest with --serial."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--serial",
        action="store_true",
        help="Run in one process with unittest discovery (the reference mode) instead of pytest-xdist.",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Skip tests marked slow with tests/slow_test_support.slow_test.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        help=f"Parallel worker count (default: max(1, cores - {RESERVED_CORES})).",
    )
    return parser


def build_command(
    arguments: Sequence[str], *, available_cores: int
) -> tuple[list[str], dict[str, str | None]]:
    """Return the test command and the environment changes (None removes a variable)."""
    parser = _argument_parser()
    options, forwarded = parser.parse_known_args(arguments)
    if options.workers is not None and options.workers < 1:
        parser.error("--workers must be at least 1.")
    environment: dict[str, str | None] = {
        FAST_TESTS_ENVIRONMENT_VARIABLE: "1" if options.fast else None
    }
    if options.serial:
        command = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            str(TESTS_DIRECTORY),
            "-p",
            "test_*.py",
            *forwarded,
        ]
        return command, environment
    workers = options.workers or default_worker_count(available_cores)
    # One worker runs in the main process; "-n 0" disables xdist rather than starting a worker.
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-n",
        str(workers if workers > 1 else 0),
        *forwarded,
    ]
    return command, environment


def _child_environment(changes: Mapping[str, str | None]) -> dict[str, str]:
    environment = dict(os.environ)
    for name, value in changes.items():
        if value is None:
            environment.pop(name, None)
        else:
            environment[name] = value
    return environment


def main(arguments: Sequence[str] | None = None) -> int:
    command, environment_changes = build_command(
        sys.argv[1:] if arguments is None else arguments,
        available_cores=_available_cores(),
    )
    completed = subprocess.run(
        command,
        check=False,
        cwd=PROJECT_ROOT,
        env=_child_environment(environment_changes),
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
