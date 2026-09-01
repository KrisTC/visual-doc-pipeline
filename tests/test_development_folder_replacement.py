#!/usr/bin/env python3
"""Synthetic tests for the development folder-replacement scenario wrapper."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pipeline.text_replacement import TextReplacementProviderFactory
from scripts import development_folder_replacement as development


class DevelopmentFolderReplacementTests(unittest.TestCase):
    # Verifies FR-2026-08-22-01 and FR-2026-08-22-02.
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
                        "--include",
                        "*.pptx,*.pdf",
                        "--include",
                        "slides/*.pptx",
                        "--comment",
                        "compare layout changes",
                    ]
                )

            self.assertEqual(0, result)
            self.assertEqual(4, len(recorded_commands))
            revision_root = (
                root
                / "outputs/evaluations/folder-replacement-development/case/en-en/v1"
            )
            manifest = json.loads((revision_root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("case/en", manifest["source_folder"])
            self.assertEqual("compare layout changes", manifest["comment"])
            self.assertEqual(["*.pptx", "*.pdf", "slides/*.pptx"], manifest["include_patterns"])
            self.assertEqual(4, len(manifest["scenarios"]))
            self.assertTrue(all(result["exit_code"] == 0 for result in manifest["results"]))
            self.assertTrue(all(result["diagnostic_sidecars"] == [] for result in manifest["results"]))
            for command in recorded_commands:
                with self.subTest(command=command):
                    self.assertEqual(
                        str(development.FOLDER_REPLACEMENT_SCRIPT), command[1]
                    )
                    self.assertEqual(str(source_folder), command[2])
                    self.assertIn("--include", command)
                    self.assertIn("--debug", command)
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

            self.assertEqual(provider_count + 1, run_mock.call_count)
            output_root = root / "outputs/evaluations/folder-replacement-development/case/en-en"
            self.assertTrue((output_root / "v1" / "manifest.json").is_file())
            self.assertTrue((output_root / "v2" / "manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
