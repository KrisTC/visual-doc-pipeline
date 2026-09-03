"""Synthetic checks for the runtime-asset bootstrap command."""

from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
from io import StringIO
from pathlib import Path
import unittest
from unittest.mock import MagicMock, call, patch


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "bootstrap_runtime_assets.py"
SPECIFICATION = importlib.util.spec_from_file_location("bootstrap_runtime_assets", SCRIPT_PATH)
assert SPECIFICATION is not None and SPECIFICATION.loader is not None
bootstrap = importlib.util.module_from_spec(SPECIFICATION)
SPECIFICATION.loader.exec_module(bootstrap)


class BootstrapRuntimeAssetsTests(unittest.TestCase):
    # Verifies FR-2026-08-27-04 and FR-2026-09-02-02.
    def test_prints_the_shared_font_and_paddle_cache_locations(self) -> None:
        output = StringIO()
        progress = MagicMock()
        display = MagicMock()
        display.__enter__.return_value = display
        display.start_current.return_value = progress
        with (
            patch.object(
                bootstrap,
                "bootstrap_symbols_font",
                return_value=Path("/fonts/symbols.ttf"),
            ),
            patch.object(
                bootstrap, "bootstrap_math_font", return_value=Path("/fonts/math.ttf")
            ),
            patch.object(bootstrap, "bootstrap_model_language") as bootstrap_language,
            patch.object(bootstrap, "mark_bootstrap_complete"),
            patch.object(bootstrap, "font_cache_directory", return_value=Path("/fonts")),
            patch.object(bootstrap, "paddle_model_cache_directory", return_value=Path("/models")),
            patch.object(bootstrap, "LiveProgress", return_value=display) as progress_factory,
            redirect_stdout(output),
        ):
            self.assertEqual(0, bootstrap.main())

        self.assertIn(f"Font cache: {Path('/fonts')}", output.getvalue())
        self.assertIn(f"Noto Sans Math: {Path('/fonts/math.ttf')}", output.getvalue())
        self.assertIn(f"PaddleOCR model cache: {Path('/models')}", output.getvalue())
        progress_factory.assert_called_once_with()
        display.start_overall.assert_called_once_with(4, "asset")
        display.start_current.assert_called_once_with("Runtime assets", 4, "asset")
        self.assertEqual(
            [
                call("Noto Sans Symbols 2"),
                call("Noto Sans Math"),
                call("PaddleOCR English"),
                call("PaddleOCR Japanese"),
            ],
            progress.set_postfix_str.call_args_list,
        )
        self.assertEqual([call(), call(), call(), call()], progress.update.call_args_list)
        self.assertEqual([call(), call(), call(), call()], display.advance_overall.call_args_list)
        self.assertEqual([call("en"), call("ja")], bootstrap_language.call_args_list)
        display.__exit__.assert_called_once()
