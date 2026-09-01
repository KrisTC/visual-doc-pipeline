#!/usr/bin/env python3
"""Regression tests for direct script execution."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image

from pipeline.ocr import OcrProviderFactory
from pipeline.text_replacement import TextReplacementProviderFactory
from scripts import run_folder_replacement
from scripts.run_folder_replacement import _argument_parser, _load_default_typeface

PROJECT_ROOT = Path(__file__).parents[1]


class _TtyStringIo(io.StringIO):
    """In-memory text stream that behaves as an interactive terminal for testing."""

    def isatty(self) -> bool:
        return True


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

    # Verifies FR-2026-08-22-01.
    def test_development_folder_replacement_help_runs_as_a_direct_script(self) -> None:
        self._assert_help_succeeds("run_development_folder_replacement.py")

    # Verifies FR-2026-08-03-03.
    def test_folder_replacement_help_lists_plugin_choices_and_defaults(self) -> None:
        completed_process = self._run_help("run_folder_replacement.py")

        self.assertEqual(0, completed_process.returncode, completed_process.stderr)
        help_output = completed_process.stdout
        normalized_help_output = " ".join(help_output.split())
        text_replacement_factory = TextReplacementProviderFactory.discover_default_plugins()
        ocr_factory = OcrProviderFactory.discover_default_plugins()
        self.assertIn("command options:", help_output)
        self.assertIn("text-replacement providers:", help_output)
        self.assertIn("OCR providers:", help_output)
        self.assertIn("document-text-layout modes:", help_output)
        self.assertNotIn("Select with", help_output)
        self.assertIn("--document-text-layout LAYOUT", help_output)
        self.assertNotIn("--document-text-layout {", help_output)
        for factory in (text_replacement_factory, ocr_factory):
            for name in factory.provider_names:
                description = factory.provider_descriptions[name] or "No description available."
                with self.subTest(provider=name):
                    self.assertIn(
                        f"{name}: {description}", normalized_help_output
                    )
        for default in (
            "character_mask",
            "paddleocr",
            "en",
            "preserve-source-formatting",
        ):
            with self.subTest(default=default):
                self.assertIn(f"(default: {default})", normalized_help_output)

    # Verifies FR-2026-08-03-03.
    def test_folder_replacement_help_lists_document_text_layout_choices_separately(self) -> None:
        completed_process = self._run_help("run_folder_replacement.py")

        self.assertEqual(0, completed_process.returncode, completed_process.stderr)
        help_output = completed_process.stdout
        self.assertIn("document-text-layout modes:", help_output)
        for choice in (
            "preserve-source-formatting",
            "preserve-basic-layout",
            "preserve-basic-layout-source-font",
        ):
            with self.subTest(choice=choice):
                self.assertIn(choice, help_output)

    # Verifies FR-2026-08-03-03.
    def test_folder_replacement_help_colours_options_for_a_supported_terminal(self) -> None:
        output = _TtyStringIo()
        with patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
            _argument_parser().print_help(file=output)

        help_output = output.getvalue()
        self.assertIn("\033[1mcommand options:\033[0m", help_output)
        self.assertIn("\033[1;36m--text-replacement PROVIDER\033[0m", help_output)
        self.assertIn("\033[1;32mcharacter_mask:\033[0m", help_output)
        self.assertIn("\033[33m(default: character_mask)\033[0m", help_output)
        self.assertIn("Deterministic placeholder text-replacement provider.", help_output)
        self.assertIn(
            "Target-language BCP 47 tag. \033[33m(default: en)\033[0m",
            help_output,
        )

    # Verifies FR-2026-08-03-03.
    def test_folder_replacement_help_remains_plain_when_colour_is_disabled(self) -> None:
        cases = (
            ("redirected", io.StringIO(), {"TERM": "xterm-256color"}),
            ("dumb terminal", _TtyStringIo(), {"TERM": "dumb"}),
            ("NO_COLOR", _TtyStringIo(), {"TERM": "xterm-256color", "NO_COLOR": "1"}),
        )
        for reason, output, environment in cases:
            with self.subTest(reason=reason):
                with patch.dict(os.environ, environment, clear=True):
                    _argument_parser().print_help(file=output)

                self.assertNotIn("\033[", output.getvalue())

    # Verifies FR-2026-08-03-03.
    def test_folder_replacement_loads_its_default_typeface(self) -> None:
        self.assertIsNotNone(_load_default_typeface())

    # Verifies FR-2026-08-27-04.
    def test_folder_replacement_reports_missing_fitted_layout_font_without_usage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_folder = root / "input"
            input_folder.mkdir()
            error_output = io.StringIO()
            with patch.dict(
                os.environ,
                {"VISUAL_DOC_PIPELINE_FONT_CACHE": str(root / "font-cache")},
                clear=False,
            ), patch.object(
                sys,
                "argv",
                [
                    "run_folder_replacement.py",
                    str(input_folder),
                    str(root / "output"),
                    "--source-language",
                    "en",
                    "--ocr",
                    "no_ocr",
                    "--document-text-layout",
                    "preserve-basic-layout",
                ],
            ), patch("sys.stderr", error_output):
                self.assertEqual(2, run_folder_replacement.main())

            message = error_output.getvalue()
            self.assertIn("Folder replacement did not start", message)
            self.assertIn("No input document was processed", message)
            self.assertIn("Noto Sans Symbols 2", message)
            self.assertIn("./run.sh scripts/bootstrap_runtime_assets.py", message)
            self.assertNotIn("usage:", message)

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

    # Verifies FR-2026-08-22-02.
    def test_folder_replacement_include_option_filters_source_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_folder = root / "input"
            output_folder = root / "output"
            input_folder.mkdir()
            Image.new("RGB", (4, 3), "red").save(input_folder / "source.png")
            (input_folder / "skip.docx").write_bytes(b"not selected")

            completed_process = self._run_folder_replacement(
                input_folder,
                output_folder,
                "--ocr",
                "no_ocr",
                "--include",
                "*.png",
            )

            self.assertEqual(0, completed_process.returncode, completed_process.stderr)
            self.assertTrue((output_folder / "source.png").is_file())
            self.assertFalse((output_folder / "skip.docx").exists())
            self.assertIn("1 processed, 1 ignored, 0 failed", completed_process.stdout)

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
        completed_process = self._run_help(script_name)
        self.assertEqual(0, completed_process.returncode, completed_process.stderr)
        self.assertIn("usage:", completed_process.stdout)

    def _run_help(self, script_name: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / script_name), "--help"],
            check=False,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()
