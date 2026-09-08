"""Tests for the fixed-path OCI entrypoint without starting Docker."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import container_entrypoint
from scripts import folder_replacement
import scripts.bootstrap_runtime_assets as bootstrap_runtime_assets


class ContainerEntrypointTests(unittest.TestCase):
    # Verifies FR-2026-09-07-01.
    def test_bootstraps_before_invoking_folder_replacement_with_fixed_roots(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_directory = root / "input"
            input_directory.mkdir()
            output_directory = root / "output"
            events: list[str] = []

            def bootstrap() -> int:
                events.append("bootstrap")
                return 0

            def replace(*_arguments: object, **_keywords: object) -> int:
                events.append("replace")
                return 7

            with patch.object(container_entrypoint, "INPUT_DIRECTORY", input_directory), patch.object(
                container_entrypoint, "OUTPUT_DIRECTORY", output_directory
            ), patch.object(container_entrypoint, "bootstrap_completed", return_value=False), patch.object(
                bootstrap_runtime_assets, "main", side_effect=bootstrap
            ), patch.object(folder_replacement, "main", side_effect=replace) as command:
                self.assertEqual(7, container_entrypoint.main(["--source-language", "ja"]))

            self.assertEqual(["bootstrap", "replace"], events)
            self.assertTrue(output_directory.is_dir())
            self.assertEqual(
                ((["--source-language", "ja"],), {"fixed_roots": (input_directory, output_directory)}),
                command.call_args,
            )

    # Verifies FR-2026-09-07-01.
    def test_reuses_a_populated_cache_without_bootstrap(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_directory = root / "input"
            input_directory.mkdir()
            output_directory = root / "output"
            with patch.object(container_entrypoint, "INPUT_DIRECTORY", input_directory), patch.object(
                container_entrypoint, "OUTPUT_DIRECTORY", output_directory
            ), patch.object(container_entrypoint, "bootstrap_completed", return_value=True), patch.object(
                bootstrap_runtime_assets, "main"
            ) as bootstrap, patch.object(
                folder_replacement, "main", return_value=0
            ):
                self.assertEqual(0, container_entrypoint.main(["--source-language", "ja"]))

            bootstrap.assert_not_called()

    # Verifies FR-2026-09-07-01.
    def test_rejects_invalid_fixed_roots_before_runtime_bootstrap(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_directory = root / "output"
            with patch.object(container_entrypoint, "INPUT_DIRECTORY", root / "missing"), patch.object(
                container_entrypoint, "OUTPUT_DIRECTORY", output_directory
            ), patch.object(container_entrypoint, "bootstrap_completed", return_value=False), patch.object(
                bootstrap_runtime_assets, "main"
            ) as bootstrap, patch.object(folder_replacement, "main") as command:
                self.assertEqual(2, container_entrypoint.main(["--source-language", "ja"]))

            bootstrap.assert_not_called()
            command.assert_not_called()

    # Verifies FR-2026-09-07-01 and SR-2026-09-07-01.
    def test_uses_the_fixed_google_secret_only_without_an_explicit_override(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            credential = Path(temporary_directory) / "credential.json"
            credential.write_text("{}", encoding="utf-8")
            with patch.object(container_entrypoint, "GOOGLE_CREDENTIAL_PATH", credential):
                with patch.dict(os.environ, {}, clear=True):
                    container_entrypoint._configure_google_credentials()
                    self.assertEqual(str(credential), os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
                with patch.dict(
                    os.environ, {"GOOGLE_APPLICATION_CREDENTIALS": "caller-value"}, clear=True
                ):
                    container_entrypoint._configure_google_credentials()
                    self.assertEqual("caller-value", os.environ["GOOGLE_APPLICATION_CREDENTIALS"])

    # Verifies FR-2026-09-07-01.
    def test_container_help_has_no_positional_mount_arguments(self) -> None:
        parser = folder_replacement._argument_parser((Path("/input"), Path("/output")))

        help_text = parser.format_help()
        self.assertNotIn("input_folder", help_text)
        self.assertNotIn("output_folder", help_text)
        with patch.object(folder_replacement, "main", return_value=0) as command:
            self.assertEqual(0, container_entrypoint.main(["--help"]))

        self.assertEqual(((["--help"],), {"fixed_roots": (Path("/input"), Path("/output"))}), command.call_args)
