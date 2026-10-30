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
    return parser


def build_command(
    arguments: Sequence[str], *, available_cores: int, selected_items: int | None = None
) -> tuple[list[str], dict[str, str | None]]:
    """Return the test command and the environment changes (None removes a variable)."""
    parser = _argument_parser()
    options, forwarded = parser.parse_known_args(arguments)
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
    workers = default_worker_count(available_cores)
    if selected_items is not None:
        workers = min(workers, max(1, (selected_items + 1) // 2))
    # One worker runs in the main process; "-n 0" disables xdist rather than starting a worker.
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-n",
        str(workers if workers > 1 else 0),
        "--dist=worksteal",
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


def _has_selection(arguments: Sequence[str]) -> bool:
    return any(
        arg.startswith(("-k", "-m", "--deselect="))
        or (not arg.startswith("-") and (
            "::" in arg or arg.endswith(".py") or (PROJECT_ROOT / arg).is_dir()
        ))
        for arg in arguments
    )


def main(arguments: Sequence[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    command, environment_changes = build_command(
        arguments,
        available_cores=_available_cores(),
    )
    if "--serial" not in arguments and _has_selection(command[6:]):
        collection = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "count_test_items.py"), *command[6:]],
            check=False, cwd=PROJECT_ROOT, env=_child_environment(environment_changes),
            capture_output=True, text=True,
        )
        if collection.returncode:
            print(collection.stdout, end="")
            print(collection.stderr, end="", file=sys.stderr)
            return collection.returncode
        selected_items = int(collection.stdout.rsplit("\n", 2)[-2])
        command, environment_changes = build_command(
            arguments, available_cores=_available_cores(), selected_items=selected_items
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
