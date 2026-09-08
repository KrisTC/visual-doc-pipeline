#!/usr/bin/env python3
"""Run folder replacement through the fixed OCI mount interface."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from pipeline.runtime_assets import bootstrap_completed
from scripts import bootstrap_runtime_assets, folder_replacement

INPUT_DIRECTORY = Path("/input")
OUTPUT_DIRECTORY = Path("/output")
GOOGLE_CREDENTIAL_PATH = Path("/run/secrets/google-application-credentials.json")


def main(arguments: Sequence[str] | None = None) -> int:
    """Bootstrap an empty runtime cache, then invoke fixed-root replacement."""
    supplied_arguments = list(sys.argv[1:] if arguments is None else arguments)
    _configure_google_credentials()
    if _help_requested(supplied_arguments):
        return folder_replacement.main(
            supplied_arguments, fixed_roots=(INPUT_DIRECTORY, OUTPUT_DIRECTORY)
        )
    if not _ensure_valid_fixed_roots():
        return 2
    if not bootstrap_completed():
        print("Initializing runtime assets in /runtime-cache before processing input.")
        result = bootstrap_runtime_assets.main()
        if result != 0:
            return result
    return folder_replacement.main(
        supplied_arguments, fixed_roots=(INPUT_DIRECTORY, OUTPUT_DIRECTORY)
    )


def _configure_google_credentials() -> None:
    """Use the fixed secret target unless the caller set an explicit override."""
    if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ and GOOGLE_CREDENTIAL_PATH.is_file():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(GOOGLE_CREDENTIAL_PATH)


def _help_requested(arguments: Sequence[str]) -> bool:
    """Avoid network bootstrap when the user asks only for command help."""
    return "--help" in arguments or "-h" in arguments


def _ensure_valid_fixed_roots() -> bool:
    """Validate fixed mounts before a first-use bootstrap can access the network."""
    if not INPUT_DIRECTORY.is_dir():
        print("Container input mount must be an existing directory.", file=sys.stderr)
        return False
    try:
        if not OUTPUT_DIRECTORY.exists():
            OUTPUT_DIRECTORY.mkdir(parents=True)
    except OSError:
        print("Container output mount could not be created.", file=sys.stderr)
        return False
    if not OUTPUT_DIRECTORY.is_dir():
        print("Container output mount must be a directory.", file=sys.stderr)
        return False
    resolved_input = INPUT_DIRECTORY.resolve()
    resolved_output = OUTPUT_DIRECTORY.resolve()
    if resolved_output == resolved_input or resolved_output.is_relative_to(resolved_input):
        print("Container output mount must be separate from the input mount.", file=sys.stderr)
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
