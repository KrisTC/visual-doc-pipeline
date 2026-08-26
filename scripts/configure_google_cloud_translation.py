#!/usr/bin/env python3
"""Configure and verify local Google Cloud Translation credentials."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import NamedTemporaryFile
from typing import NoReturn


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT_FILE_NAME = ".env.local"
MANAGED_MARKER = "# Managed by scripts/configure_google_cloud_translation.py"
LEGACY_MANAGED_MARKER = "# Managed by scripts/configure-google-cloud-translation.ps1"
MANAGED_SETTING_NAMES = frozenset(
    {
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_TRANSLATION_LOCATION",
    }
)
PROBE_SUCCESS_MARKER = "GOOGLE_CLOUD_TRANSLATION_PROBE=ok"
EU_LOCATION_HELP = (
    "Optional European Cloud Translation location. Examples: europe-west1 (Belgium), "
    "europe-west3 (Frankfurt), europe-west4 (Netherlands). Omit for the global endpoint."
)
PROBE_CODE = "\n".join(
    (
        "from pipeline.text_replacement.models import TextReplacementRequest",
        "from pipeline.text_replacement_plugins.google_cloud_translate import GoogleCloudTranslateProvider",
        "result = GoogleCloudTranslateProvider().replace("
        'TextReplacementRequest("translation configuration probe", False, "en", "fr"))',
        "if not result.text:",
        '    raise RuntimeError("Google Cloud Translation returned empty probe text.")',
        f"print({PROBE_SUCCESS_MARKER!r})",
    )
)


class ConfigurationError(Exception):
    """A safe, concise configuration failure suitable for local display."""


def _parse_arguments(arguments: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure and verify local Google Cloud Translation credentials."
    )
    parser.add_argument(
        "--credential-file",
        required=True,
        type=Path,
        help="Service-account credential JSON file; relative paths are resolved from the current directory.",
    )
    parser.add_argument(
        "--location",
        metavar="EUROPE_LOCATION",
        help=EU_LOCATION_HELP,
    )
    return parser.parse_args(arguments)


def _read_service_account(credential_file: Path) -> tuple[Path, str]:
    credential_file = credential_file.expanduser().resolve()
    if not credential_file.is_file():
        raise ConfigurationError("The credential file does not exist.")

    try:
        credential = json.loads(credential_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ConfigurationError("The credential file is not valid JSON.") from error

    if not isinstance(credential, dict):
        raise ConfigurationError("The credential file is not a service-account credential JSON file.")
    project_id = credential.get("project_id")
    if (
        credential.get("type") != "service_account"
        or not isinstance(project_id, str)
        or not project_id.strip()
    ):
        raise ConfigurationError(
            "The credential file is not a service-account credential JSON file with a project ID."
        )
    return credential_file.resolve(), project_id.strip()


def _normalized_location(location: str | None) -> str | None:
    if location is None:
        return None
    normalized = location.strip()
    return normalized or None


def _newline_for(content: str) -> str:
    return "\r\n" if "\r\n" in content else "\n"


def _setting_name(line: str) -> str | None:
    name, separator, _ = line.partition("=")
    return name if separator and name in MANAGED_SETTING_NAMES else None


def _remove_previous_managed_blocks(content: str) -> str:
    retained_lines: list[str] = []
    lines = content.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.rstrip("\r\n") not in {MANAGED_MARKER, LEGACY_MANAGED_MARKER}:
            retained_lines.append(line)
            index += 1
            continue

        index += 1
        while index < len(lines) and _setting_name(lines[index].rstrip("\r\n")) is not None:
            index += 1
    return "".join(retained_lines)


def _candidate_environment_content(
    existing_content: str,
    credential_path: Path,
    project_id: str,
    location: str | None,
) -> str:
    newline = _newline_for(existing_content)
    retained_content = _remove_previous_managed_blocks(existing_content)
    managed_lines = [
        MANAGED_MARKER,
        f'GOOGLE_APPLICATION_CREDENTIALS="{credential_path.as_posix()}"',
        f"GOOGLE_CLOUD_PROJECT={project_id}",
    ]
    if location is not None:
        managed_lines.append(f"GOOGLE_CLOUD_TRANSLATION_LOCATION={location}")
    managed_block = newline.join(managed_lines) + newline
    if not retained_content:
        return managed_block
    separator = "" if retained_content.endswith(("\n", "\r")) else newline
    return retained_content + separator + managed_block


def _probe_environment(
    credential_path: Path, project_id: str, location: str | None, project_root: Path
) -> None:
    probe_environment = os.environ.copy()
    probe_environment["GOOGLE_APPLICATION_CREDENTIALS"] = str(credential_path)
    probe_environment["GOOGLE_CLOUD_PROJECT"] = project_id
    if location is None:
        probe_environment.pop("GOOGLE_CLOUD_TRANSLATION_LOCATION", None)
    else:
        probe_environment["GOOGLE_CLOUD_TRANSLATION_LOCATION"] = location

    completed_process = subprocess.run(
        [sys.executable, "-c", PROBE_CODE],
        check=False,
        capture_output=True,
        cwd=project_root,
        env=probe_environment,
        text=True,
    )
    if (
        completed_process.returncode != 0
        or completed_process.stdout.splitlines().count(PROBE_SUCCESS_MARKER) != 1
    ):
        raise ConfigurationError("Google Cloud Translation credential validation failed.")


def _atomically_write_environment(content: str, environment_file: Path) -> None:
    temporary_file: Path | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=environment_file.parent,
            prefix=".env.local.",
            suffix=".tmp",
            delete=False,
        ) as file_handle:
            temporary_file = Path(file_handle.name)
            file_handle.write(content)
            file_handle.flush()
            os.fsync(file_handle.fileno())
        os.replace(temporary_file, environment_file)
        temporary_file = None
    finally:
        if temporary_file is not None:
            temporary_file.unlink(missing_ok=True)


def configure(
    credential_file: Path, location: str | None, project_root: Path = PROJECT_ROOT
) -> tuple[str, str, str, str]:
    """Probe a credential and atomically update the project-root dotenv file."""
    resolved_credential_path, project_id = _read_service_account(credential_file)
    normalized_location = _normalized_location(location)
    environment_file = project_root / ENVIRONMENT_FILE_NAME
    existing_content = environment_file.read_text(encoding="utf-8") if environment_file.exists() else ""
    candidate_content = _candidate_environment_content(
        existing_content, resolved_credential_path, project_id, normalized_location
    )
    _probe_environment(resolved_credential_path, project_id, normalized_location, project_root)
    _atomically_write_environment(candidate_content, environment_file)
    endpoint = "translate.googleapis.com" if normalized_location is None else "translate-eu.googleapis.com"
    selected_location = normalized_location or "global"
    return resolved_credential_path.name, project_id, endpoint, selected_location


def _fail(message: str) -> NoReturn:
    print(f"Google Cloud Translation configuration failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def main(arguments: list[str] | None = None) -> int:
    arguments_namespace = _parse_arguments(arguments)
    try:
        credential_name, project_id, endpoint, location = configure(
            arguments_namespace.credential_file, arguments_namespace.location
        )
    except ConfigurationError as error:
        _fail(str(error))
    except (OSError, UnicodeDecodeError):
        _fail("a local file operation failed.")

    print(f"Credential file: {credential_name}")
    print(f"Project: {project_id}")
    print(f"Endpoint: {endpoint}")
    print(f"Location: {location}")
    print("Google Cloud Translation configuration succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
