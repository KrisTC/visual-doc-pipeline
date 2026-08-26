#!/usr/bin/env python3
"""Tests for Google Cloud Translation dotenv configuration."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import ModuleType
from typing import Protocol, cast
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "configure_google_cloud_translation.py"


class SetupModule(Protocol):
    """Typed surface of the dynamically loaded command-line helper."""

    MANAGED_MARKER: str
    subprocess: ModuleType
    ConfigurationError: type[Exception]

    def configure(
        self, credential_file: Path, location: str | None, project_root: Path = ...
    ) -> tuple[str, str, str, str]: ...

    def _probe_environment(
        self, credential_path: Path, project_id: str, location: str | None, project_root: Path
    ) -> None: ...

    def _read_service_account(self, credential_file: Path) -> tuple[Path, str]: ...


def _load_setup_module() -> SetupModule:
    specification = importlib.util.spec_from_file_location("configure_google_cloud_translation", SCRIPT_PATH)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return cast(SetupModule, module)


class ConfigureGoogleCloudTranslationTests(unittest.TestCase):
    """Verify setup with synthetic credentials and a mocked provider probe."""

    def setUp(self) -> None:
        self.setup = _load_setup_module()

    # Verifies FR-2026-08-24-05.
    def test_configures_a_quoted_forward_slash_credential_path_and_preserves_other_entries(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            credential_file = _write_synthetic_credential(root)
            environment_file = root / ".env.local"
            environment_file.write_text(
                "CUSTOM_SETTING=preserved\n"
                "# Managed by scripts/configure-paddle-cuda-environment.ps1\n"
                'PATH="C:/CUDA/bin;${PATH}"\n'
                "GOOGLE_CLOUD_PROJECT=user-managed-project\n",
                encoding="utf-8",
            )

            with patch.object(self.setup, "_probe_environment") as probe:
                result = self.setup.configure(credential_file, None, root)

            self.assertEqual(
                (credential_file.name, "synthetic-project", "translate.googleapis.com", "global"), result
            )
            probe.assert_called_once_with(credential_file.resolve(), "synthetic-project", None, root)
            content = environment_file.read_text(encoding="utf-8")
            self.assertIn("CUSTOM_SETTING=preserved\n", content)
            self.assertIn("# Managed by scripts/configure-paddle-cuda-environment.ps1\n", content)
            self.assertIn('PATH="C:/CUDA/bin;${PATH}"\n', content)
            self.assertIn("GOOGLE_CLOUD_PROJECT=user-managed-project\n", content)
            self.assertIn(self.setup.MANAGED_MARKER, content)
            self.assertIn('GOOGLE_APPLICATION_CREDENTIALS="', content)
            self.assertIn(credential_file.as_posix(), content)
            self.assertIn("GOOGLE_CLOUD_PROJECT=synthetic-project\n", content)

    # Verifies FR-2026-08-24-05.
    def test_migrates_the_legacy_powershell_managed_block_and_writes_eu_location(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            credential_file = _write_synthetic_credential(root)
            environment_file = root / ".env.local"
            environment_file.write_text(
                "CUSTOM_SETTING=preserved\n"
                "# Managed by scripts/configure-google-cloud-translation.ps1\n"
                'GOOGLE_APPLICATION_CREDENTIALS="C:/old/credential.json"\n'
                "GOOGLE_CLOUD_PROJECT=old-project\n"
                "GOOGLE_CLOUD_TRANSLATION_LOCATION=europe-west1\n",
                encoding="utf-8",
            )

            with patch.object(self.setup, "_probe_environment") as probe:
                result = self.setup.configure(credential_file, " europe-west1 ", root)

            self.assertEqual(
                (credential_file.name, "synthetic-project", "translate-eu.googleapis.com", "europe-west1"), result
            )
            probe.assert_called_once_with(credential_file.resolve(), "synthetic-project", "europe-west1", root)
            content = environment_file.read_text(encoding="utf-8")
            self.assertNotIn("configure-google-cloud-translation.ps1", content)
            self.assertNotIn("old-project", content)
            self.assertIn("CUSTOM_SETTING=preserved\n", content)
            self.assertIn("GOOGLE_CLOUD_TRANSLATION_LOCATION=europe-west1\n", content)

    # Verifies FR-2026-08-24-05.
    def test_failed_probe_keeps_the_existing_environment_file_unchanged(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            credential_file = _write_synthetic_credential(root)
            environment_file = root / ".env.local"
            original_content = "CUSTOM_SETTING=preserved\n"
            environment_file.write_text(original_content, encoding="utf-8")

            with patch.object(
                self.setup,
                "_probe_environment",
                side_effect=self.setup.ConfigurationError("Google Cloud Translation credential validation failed."),
            ):
                with self.assertRaisesRegex(self.setup.ConfigurationError, "credential validation failed"):
                    self.setup.configure(credential_file, None, root)

            self.assertEqual(original_content, environment_file.read_text(encoding="utf-8"))
            self.assertEqual([], list(root.glob(".env.local.*.tmp")))

    # Verifies FR-2026-08-24-05.
    def test_rejects_non_service_account_json_without_creating_an_environment_file(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            credential_file = root / "credential.json"
            credential_file.write_text(json.dumps({"type": "authorized_user"}), encoding="utf-8")

            with self.assertRaises(self.setup.ConfigurationError):
                self.setup.configure(credential_file, None, root)

            self.assertFalse((root / ".env.local").exists())

    # Verifies FR-2026-08-24-05.
    def test_resolves_a_relative_credential_path_from_the_current_directory(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            credential_file = _write_synthetic_credential(root)
            original_directory = Path.cwd()
            try:
                os.chdir(root)
                resolved_path, project_id = self.setup._read_service_account(Path("credential.json"))
            finally:
                os.chdir(original_directory)

            self.assertEqual(credential_file.resolve(), resolved_path)
            self.assertEqual("synthetic-project", project_id)

    # Verifies FR-2026-08-24-05.
    def test_help_lists_global_and_european_location_examples(self) -> None:
        completed_process = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--help"], check=False, capture_output=True, text=True
        )

        self.assertEqual(0, completed_process.returncode, completed_process.stderr)
        help_text = " ".join(completed_process.stdout.split())
        self.assertIn("europe-west1 (Belgium)", help_text)
        self.assertIn("europe-west3 (Frankfurt)", help_text)
        self.assertIn("europe-west4 (Netherlands)", help_text)
        self.assertIn("Omit for the global endpoint", help_text)

    # Verifies FR-2026-08-24-05.
    def test_probe_uses_only_derived_configuration_and_hides_provider_failure_output(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            credential_file = _write_synthetic_credential(root)
            completed_process = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="synthetic-private-key"
            )

            with patch.object(self.setup.subprocess, "run", return_value=completed_process) as run:
                with self.assertRaisesRegex(self.setup.ConfigurationError, "credential validation failed") as error:
                    self.setup._probe_environment(credential_file, "synthetic-project", None, root)

            self.assertNotIn("synthetic-private-key", str(error.exception))
            arguments = run.call_args.kwargs
            self.assertEqual(str(credential_file), arguments["env"]["GOOGLE_APPLICATION_CREDENTIALS"])
            self.assertEqual("synthetic-project", arguments["env"]["GOOGLE_CLOUD_PROJECT"])
            self.assertNotIn("GOOGLE_CLOUD_TRANSLATION_LOCATION", arguments["env"])


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


if __name__ == "__main__":
    unittest.main()
