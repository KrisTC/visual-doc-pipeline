#!/usr/bin/env python3
"""Regression tests for direct script execution."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from scripts.run_folder_replacement import _load_default_typeface

PROJECT_ROOT = Path(__file__).parents[1]


class CliEntryPointTests(unittest.TestCase):
    # Verifies FR-2026-08-01-01.
    def test_prepare_inputs_help_runs_as_a_direct_script(self) -> None:
        self._assert_help_succeeds("prepare_ocr_evaluation_inputs.py")

    # Verifies FR-2026-08-01-03.
    def test_evaluation_help_runs_as_a_direct_script(self) -> None:
        self._assert_help_succeeds("run_ocr_evaluations.py")

    # Verifies FR-2026-08-03-03.
    def test_folder_replacement_help_runs_as_a_direct_script(self) -> None:
        self._assert_help_succeeds("run_folder_replacement.py")

    # Verifies FR-2026-08-03-03.
    def test_folder_replacement_loads_its_default_typeface(self) -> None:
        self.assertIsNotNone(_load_default_typeface())

    def _assert_help_succeeds(self, script_name: str) -> None:
        completed_process = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / script_name), "--help"],
            check=False,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed_process.returncode, completed_process.stderr)
        self.assertIn("usage:", completed_process.stdout)


if __name__ == "__main__":
    unittest.main()
