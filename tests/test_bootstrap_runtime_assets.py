"""Synthetic checks for the runtime-asset bootstrap command."""

from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
from io import StringIO
from pathlib import Path
import unittest
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "bootstrap_runtime_assets.py"
SPECIFICATION = importlib.util.spec_from_file_location("bootstrap_runtime_assets", SCRIPT_PATH)
assert SPECIFICATION is not None and SPECIFICATION.loader is not None
bootstrap = importlib.util.module_from_spec(SPECIFICATION)
SPECIFICATION.loader.exec_module(bootstrap)


class BootstrapRuntimeAssetsTests(unittest.TestCase):
    # Verifies FR-2026-08-27-04.
    def test_prints_the_shared_font_and_paddle_cache_locations(self) -> None:
        output = StringIO()
        with (
            patch.object(
                bootstrap,
                "bootstrap_optional_fonts",
                return_value=(Path("/fonts/symbols.ttf"), Path("/fonts/math.ttf")),
            ),
            patch.object(bootstrap, "bootstrap_models"),
            patch.object(bootstrap, "mark_bootstrap_complete"),
            patch.object(bootstrap, "font_cache_directory", return_value=Path("/fonts")),
            patch.object(bootstrap, "paddle_model_cache_directory", return_value=Path("/models")),
            redirect_stdout(output),
        ):
            self.assertEqual(0, bootstrap.main())

        self.assertIn("Font cache: /fonts", output.getvalue())
        self.assertIn("Noto Sans Math: /fonts/math.ttf", output.getvalue())
        self.assertIn("PaddleOCR model cache: /models", output.getvalue())
