#!/usr/bin/env python3
"""Regression tests for direct script execution."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image

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

    # Verifies FR-2026-08-04-02.
    def test_folder_replacement_selects_no_ocr_and_leaves_a_bitmap_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_folder = root / "input"
            output_folder = root / "output"
            input_folder.mkdir()
            source = input_folder / "source.png"
            Image.new("RGB", (4, 3), "red").save(source)
            document = input_folder / "document.docx"
            with ZipFile(document, "w", ZIP_DEFLATED) as archive:
                archive.writestr(
                    "word/document.xml",
                    """<?xml version=\"1.0\"?><w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:body><w:p><w:r><w:t>Word</w:t></w:r></w:p></w:body></w:document>""",
                )

            completed_process = self._run_folder_replacement(
                input_folder,
                output_folder,
                "--ocr",
                "no_ocr",
            )

            self.assertEqual(0, completed_process.returncode, completed_process.stderr)
            with Image.open(source) as source_image, Image.open(output_folder / "source.png") as output_image:
                self.assertEqual(source_image.tobytes(), output_image.tobytes())
            with ZipFile(output_folder / "document.docx") as archive:
                document_xml = archive.read("word/document.xml").decode("utf-8")
            self.assertIn("####", document_xml)
            self.assertIn("0 OCR image region(s)", completed_process.stdout)

    # Verifies FR-2026-08-04-03.
    def test_folder_replacement_reports_anticipated_argument_errors_without_tracebacks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_folder = root / "input"
            input_folder.mkdir()
            input_file = root / "input-file"
            input_file.write_text("not a folder", encoding="utf-8")
            output_file = root / "output-file"
            output_file.write_text("not a folder", encoding="utf-8")

            cases = (
                (
                    root / "missing",
                    root / "output",
                    (),
                    "Input folder does not exist:",
                ),
                (input_file, root / "output", (), "Input folder is not a directory:"),
                (input_folder, output_file, (), "Output folder is not a directory:"),
                (
                    input_folder,
                    input_folder / "output",
                    (),
                    "Output folder must not be the input folder",
                ),
                (
                    input_folder,
                    root / "output",
                    ("--ocr", "missing"),
                    "Unknown OCR provider 'missing'. Available OCR providers: no_ocr, paddleocr.",
                ),
                (
                    input_folder,
                    root / "output",
                    ("--text-replacement", "missing"),
                    "Unknown text-replacement provider 'missing'. Available text-replacement providers:",
                ),
            )
            for source, destination, options, message in cases:
                with self.subTest(message=message):
                    completed_process = self._run_folder_replacement(
                        source, destination, *options
                    )

                    self.assertEqual(2, completed_process.returncode)
                    self.assertIn("usage:", completed_process.stderr)
                    self.assertIn(f"error: {message}", completed_process.stderr)
                    self.assertNotIn("Traceback", completed_process.stderr)

    def _run_folder_replacement(
        self, input_folder: Path, output_folder: Path, *options: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "run_folder_replacement.py"),
                str(input_folder),
                str(output_folder),
                "--source-language",
                "en",
                *options,
            ],
            check=False,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )

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
