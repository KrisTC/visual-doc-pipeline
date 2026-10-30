#!/usr/bin/env python3
"""Synthetic tests for the development folder-replacement scenario wrapper."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pipeline.text_replacement import TextReplacementProviderFactory
from scripts import development_folder_replacement as development


class DevelopmentFolderReplacementTests(unittest.TestCase):
    # Verifies FR-2026-10-29-05.
    def test_logo_environment_is_forwarded_to_all_scenarios_and_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample-data" / "case" / "en").mkdir(parents=True)
            with (
                patch.dict(os.environ, {"PRESERVE_LOGO_TEXT": " NovaCorp ,NOVACORP"}),
                patch.object(development, "PROJECT_ROOT", root),
                patch.object(development, "run", return_value=SimpleNamespace(returncode=0)) as run_mock,
                patch("sys.platform", "linux"),
            ):
                self.assertEqual(0, development.main([
                    "case/en", "--text-replacement", "identity,character_mask", "--ocr", "no_ocr"
                ]))
            manifest = json.loads((root / "outputs/evaluations/dirdev/case/en-en/v1/manifest.json").read_text())
            self.assertEqual(["NovaCorp", "NOVACORP"], manifest["preserve_logo_text"])
            self.assertEqual(2, run_mock.call_count)
            for call in run_mock.call_args_list:
                command = call.args[0]
                self.assertIn("--preserve-logo-text=NovaCorp", command)
                self.assertIn("--preserve-logo-text=NOVACORP", command)

    # Verifies FR-2026-10-29-05.
    def test_unset_empty_and_invalid_logo_environment(self) -> None:
        for value in (None, "", " ", "NovaCorp,", ",NovaCorp"):
            with self.subTest(value=value), TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "sample-data" / "case" / "en").mkdir(parents=True)
                environment = dict(os.environ)
                environment.pop("PRESERVE_LOGO_TEXT", None)
                if value is not None:
                    environment["PRESERVE_LOGO_TEXT"] = value
                with (
                    patch.dict(os.environ, environment, clear=True),
                    patch.object(development, "PROJECT_ROOT", root),
                    patch.object(development, "run", return_value=SimpleNamespace(returncode=0)) as run_mock,
                    patch("sys.platform", "linux"),
                ):
                    if value in (None, ""):
                        self.assertEqual(0, development.main(["case/en", "--ocr", "no_ocr"]))
                        manifest = json.loads((root / "outputs/evaluations/dirdev/case/en-en/v1/manifest.json").read_text())
                        self.assertEqual([], manifest["preserve_logo_text"])
                        self.assertFalse(any(arg.startswith("--preserve-logo-text") for arg in run_mock.call_args.args[0]))
                    else:
                        with self.assertRaises(SystemExit) as error:
                            development.main(["case/en", "--ocr", "no_ocr"])
                        self.assertEqual(2, error.exception.code)
                        run_mock.assert_not_called()
                        self.assertFalse((root / "outputs").exists())

    # Verifies FR-2026-08-22-01, FR-2026-08-22-02, and FR-2026-09-02-04.
    def test_creates_one_revision_manifest_and_command_per_scenario(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_folder = root / "sample-data" / "case" / "en"
            source_folder.mkdir(parents=True)
            recorded_commands: list[list[str]] = []

            def record_command(command: list[str], **_: object) -> SimpleNamespace:
                recorded_commands.append(command)
                return SimpleNamespace(returncode=0)

            with (
                patch.object(development, "PROJECT_ROOT", root),
                patch.object(development, "run", side_effect=record_command),
            ):
                result = development.main(
                    [
                        "case/en",
                        "--text-replacement",
                        "character_mask,identity",
                        "--ocr",
                        "no_ocr",
                        "--document-text-layout",
                        "preserve-source-formatting,preserve-basic-layout",
                        "--xlsx-translation-mode",
                        "fast",
                        "--include",
                        "*.pptx,*.pdf",
                        "--include",
                        "slides/*.pptx",
                        "--comment",
                        "compare layout changes",
                    ]
                )

            self.assertEqual(0, result)
            scenario_commands = [
                command for command in recorded_commands
                if command[1] == str(development.FOLDER_REPLACEMENT_SCRIPT)
            ]
            self.assertEqual(4, len(scenario_commands))
            revision_root = (
                root
                / "outputs/evaluations/dirdev/case/en-en/v1"
            )
            manifest = json.loads((revision_root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("case/en", manifest["source_folder"])
            self.assertEqual("compare layout changes", manifest["comment"])
            self.assertEqual(["*.pptx", "*.pdf", "slides/*.pptx"], manifest["include_patterns"])
            self.assertEqual(4, len(manifest["scenarios"]))
            self.assertTrue(all(result["exit_code"] == 0 for result in manifest["results"]))
            self.assertTrue(all(result["diagnostic_sidecars"] == [] for result in manifest["results"]))
            self.assertEqual(
                {
                    ("character_mask", "mask"),
                    ("identity", "identity"),
                },
                {
                    (scenario["text_replacement"], scenario["text_replacement_short_name"])
                    for scenario in manifest["scenarios"]
                },
            )
            self.assertEqual(
                {
                    Path(result["output_root"]).name for result in manifest["results"]
                },
                {
                    "mask-no_ocr-psf",
                    "mask-no_ocr-pbl",
                    "identity-no_ocr-psf",
                    "identity-no_ocr-pbl",
                },
            )
            self.assertTrue(
                all(
                    Path(result["output_root"]).parent == revision_root.relative_to(root)
                    for result in manifest["results"]
                )
            )
            for command in scenario_commands:
                with self.subTest(command=command):
                    self.assertEqual(
                        str(development.FOLDER_REPLACEMENT_SCRIPT), command[1]
                    )
                    self.assertEqual(str(source_folder), command[2])
                    self.assertIn("--include", command)
                    self.assertIn("--debug", command)
                    self.assertEqual("fast", command[command.index("--xlsx-translation-mode") + 1])
                    self.assertIn("*.pptx,*.pdf", command)
                    self.assertIn("slides/*.pptx", command)

    # Verifies FR-2026-08-22-01.
    def test_all_expands_discovered_providers_and_allocates_next_revision(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "sample-data" / "case" / "en").mkdir(parents=True)
            completed_process = SimpleNamespace(returncode=0)
            provider_count = len(
                TextReplacementProviderFactory.discover_default_plugins().provider_names
            )

            with (
                patch.object(development, "PROJECT_ROOT", root),
                patch.object(development, "run", return_value=completed_process) as run_mock,
            ):
                self.assertEqual(
                    0,
                    development.main(
                        [
                            "case/en",
                            "--text-replacement",
                            "all",
                            "--ocr",
                            "no_ocr",
                        ]
                    ),
                )
                self.assertEqual(
                    0,
                    development.main(
                        [
                            "case/en",
                            "--text-replacement",
                            "identity",
                            "--ocr",
                            "no_ocr",
                        ]
                    ),
                )

            preview_calls = 2 if sys.platform == "win32" else 0
            self.assertEqual(provider_count + 1 + preview_calls, run_mock.call_count)
            output_root = root / "outputs/evaluations/dirdev/case/en-en"
            self.assertTrue((output_root / "v1" / "manifest.json").is_file())
            self.assertTrue((output_root / "v2" / "manifest.json").is_file())

    # Verifies FR-2026-09-02-04.
    def test_rejects_scenarios_that_share_a_combined_output_name(self) -> None:
        first = development.Scenario(
            "first",
            "ocr_first",
            "preserve-source-formatting",
            "full",
            "first-ocr",
            "second",
        )
        second = development.Scenario(
            "second",
            "ocr_second",
            "preserve-source-formatting",
            "full",
            "first",
            "ocr-second",
        )

        with self.assertRaisesRegex(ValueError, "first-ocr-second-psf"):
            development._validate_unique_scenario_output_names((first, second))

    # Verifies FR-2026-10-28-02.
    def test_preview_runs_once_on_windows_without_changing_replacement_status(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "sample-data" / "case" / "en").mkdir(parents=True)
            commands: list[list[str]] = []

            def invoke(command: list[str], **_: object) -> SimpleNamespace:
                commands.append(command)
                return SimpleNamespace(
                    returncode=1 if command[1] == str(development.EMF_PREVIEW_SCRIPT) else 0
                )

            with (
                patch.object(development, "PROJECT_ROOT", root),
                patch("sys.platform", "win32"),
                patch.object(development, "run", side_effect=invoke),
            ):
                result = development.main([
                    "case/en", "--text-replacement", "identity", "--ocr", "no_ocr",
                ])
            self.assertEqual(0, result)
            self.assertEqual(2, len(commands))
            self.assertEqual(str(development.EMF_PREVIEW_SCRIPT), commands[-1][1])
            self.assertEqual(root / "outputs/evaluations/dirdev/case/en-en/v1", Path(commands[-1][2]))

    # Verifies FR-2026-10-28-02.
    def test_preview_is_not_invoked_on_non_windows(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "sample-data" / "case" / "en").mkdir(parents=True)
            with (
                patch.object(development, "PROJECT_ROOT", root),
                patch("sys.platform", "linux"),
                patch.object(development, "run", return_value=SimpleNamespace(returncode=0)) as invoke,
            ):
                result = development.main([
                    "case/en", "--text-replacement", "identity", "--ocr", "no_ocr",
                ])
            self.assertEqual(0, result)
            self.assertEqual(1, invoke.call_count)


if __name__ == "__main__":
    unittest.main()
