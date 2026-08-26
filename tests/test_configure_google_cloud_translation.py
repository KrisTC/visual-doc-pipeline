#!/usr/bin/env python3
"""Tests for Google Cloud Translation dotenv configuration."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest


PROJECT_ROOT = Path(__file__).parents[1]
MANAGED_MARKER = "# Managed by scripts/configure-google-cloud-translation.ps1"


@unittest.skipUnless(os.name == "nt", "Google Cloud Translation setup script requires Windows.")
class ConfigureGoogleCloudTranslationTests(unittest.TestCase):
    """Verify setup with synthetic credentials and a mocked provider probe."""

    # Verifies FR-2026-08-24-05.
    def test_configures_a_quoted_forward_slash_credential_path_and_preserves_other_entries(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            script = _copy_setup_script(root)
            credential_file = _write_synthetic_credential(root)
            candidate_file = root / "candidate.env"
            _write_fake_run_wrapper(root, candidate_file)
            environment_file = root / ".env.local"
            environment_file.write_text(
                "CUSTOM_SETTING=preserved\nGOOGLE_CLOUD_PROJECT=old-project\n",
                encoding="utf-8",
            )

            completed_process = _run_setup(script, credential_file, {"FAKE_GOOGLE_PROBE_EXIT_CODE": "0"})

            self.assertEqual(0, completed_process.returncode, completed_process.stderr)
            content = environment_file.read_text(encoding="utf-8")
            self.assertIn("CUSTOM_SETTING=preserved\n", content)
            self.assertIn(MANAGED_MARKER, content)
            self.assertIn('GOOGLE_APPLICATION_CREDENTIALS="', content)
            self.assertIn(credential_file.as_posix(), content)
            self.assertIn("GOOGLE_CLOUD_PROJECT=synthetic-project\n", content)
            self.assertNotIn("GOOGLE_CLOUD_PROJECT=old-project", content)
            self.assertEqual(content, candidate_file.read_text(encoding="utf-8"))
            self.assertNotIn("synthetic-private-key", completed_process.stdout + completed_process.stderr)

    # Verifies FR-2026-08-24-05.
    def test_failed_probe_keeps_the_existing_environment_file_unchanged(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            script = _copy_setup_script(root)
            credential_file = _write_synthetic_credential(root)
            _write_fake_run_wrapper(root, root / "unused.env")
            environment_file = root / ".env.local"
            original_content = "CUSTOM_SETTING=preserved\n"
            environment_file.write_text(original_content, encoding="utf-8")

            completed_process = _run_setup(script, credential_file, {"FAKE_GOOGLE_PROBE_EXIT_CODE": "1"})

            self.assertNotEqual(0, completed_process.returncode)
            self.assertEqual(original_content, environment_file.read_text(encoding="utf-8"))
            self.assertEqual([], list(root.glob(".env.local.*.tmp")))
            self.assertNotIn("synthetic-private-key", completed_process.stdout + completed_process.stderr)

    # Verifies FR-2026-08-24-05.
    def test_rejects_non_service_account_json_without_creating_an_environment_file(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            script = _copy_setup_script(root)
            credential_file = root / "credential.json"
            credential_file.write_text(json.dumps({"type": "authorized_user"}), encoding="utf-8")
            _write_fake_run_wrapper(root, root / "unused.env")

            completed_process = _run_setup(script, credential_file, {"FAKE_GOOGLE_PROBE_EXIT_CODE": "0"})

            self.assertNotEqual(0, completed_process.returncode)
            self.assertFalse((root / ".env.local").exists())


def _copy_setup_script(root: Path) -> Path:
    """Copy the setup script into an isolated synthetic project root."""
    scripts_directory = root / "scripts"
    scripts_directory.mkdir()
    destination = scripts_directory / "configure-google-cloud-translation.ps1"
    shutil.copy2(PROJECT_ROOT / "scripts" / destination.name, destination)
    return destination


def _write_synthetic_credential(root: Path) -> Path:
    """Create a non-secret service-account-shaped JSON file."""
    credential_file = root / "credential.json"
    credential_file.write_text(
        json.dumps(
            {
                "type": "service_account",
                "project_id": "synthetic-project",
                "private_key": "synthetic-private-key",
            }
        ),
        encoding="utf-8",
    )
    return credential_file


def _write_fake_run_wrapper(root: Path, candidate_file: Path) -> None:
    """Write a wrapper that captures the candidate dotenv and returns a synthetic probe result."""
    wrapper = root / "scripts" / "run.ps1"
    wrapper.write_text(
        "param()\r\n"
        "$environmentFile = $args[1]\r\n"
        "[System.IO.File]::WriteAllText($env:FAKE_GOOGLE_CANDIDATE_FILE, [System.IO.File]::ReadAllText($environmentFile))\r\n"
        "if ([int]$env:FAKE_GOOGLE_PROBE_EXIT_CODE -eq 0) { Write-Output 'GOOGLE_CLOUD_TRANSLATION_PROBE=ok' }\r\n"
        "exit [int]$env:FAKE_GOOGLE_PROBE_EXIT_CODE\r\n",
        encoding="ascii",
    )
    assert candidate_file.parent == root


def _run_setup(
    script: Path, credential_file: Path, extra_environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Run one setup-script invocation with a synthetic service-account credential file."""
    candidate_file = script.parents[1] / "candidate.env"
    return subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(script), "-CredentialFile", str(credential_file)],
        check=False,
        capture_output=True,
        env={**os.environ, **extra_environment, "FAKE_GOOGLE_CANDIDATE_FILE": str(candidate_file)},
        text=True,
    )


if __name__ == "__main__":
    unittest.main()