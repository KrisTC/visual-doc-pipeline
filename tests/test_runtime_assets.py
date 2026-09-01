"""Synthetic checks for the small runtime-asset bootstrap."""

from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from pipeline import runtime_assets


def _optional_fonts_archive(member: str, contents: bytes) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(member, contents)
    return output.getvalue()


class RuntimeAssetsTests(unittest.TestCase):
    # Verifies FR-2026-08-27-04.
    def test_bootstrap_optional_fonts_reuses_the_shared_user_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            with patch.dict(
                os.environ,
                {runtime_assets.FONT_CACHE_ENVIRONMENT_VARIABLE: temporary_directory},
                clear=False,
            ), patch(
                "pipeline.runtime_assets.urlopen",
                side_effect=(
                    BytesIO(
                        _optional_fonts_archive(
                            runtime_assets._SYMBOLS_ARCHIVE_MEMBER, b"synthetic-symbol-font"
                        )
                    ),
                    BytesIO(
                        _optional_fonts_archive(
                            runtime_assets._MATH_ARCHIVE_MEMBER, b"synthetic-math-font"
                        )
                    ),
                ),
            ) as download:
                first = runtime_assets.bootstrap_optional_fonts()
                second = runtime_assets.bootstrap_optional_fonts()
                self.assertEqual(
                    (
                        Path(temporary_directory) / "NotoSansSymbols2-Regular.ttf",
                        Path(temporary_directory) / "NotoSansMath-Regular.ttf",
                    ),
                    first,
                )
                self.assertEqual(first, second)
                self.assertEqual(b"synthetic-symbol-font", first[0].read_bytes())
                self.assertEqual(b"synthetic-math-font", first[1].read_bytes())
                self.assertEqual(
                    [
                        ((runtime_assets._SYMBOLS_ARCHIVE_URL,), {}),
                        ((runtime_assets._MATH_ARCHIVE_URL,), {}),
                    ],
                    download.call_args_list,
                )

    # Verifies FR-2026-08-27-04.
    def test_paddle_processing_requires_the_successful_bootstrap_marker(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            with patch.dict(
                os.environ,
                {runtime_assets.FONT_CACHE_ENVIRONMENT_VARIABLE: temporary_directory},
                clear=False,
            ):
                with self.assertRaisesRegex(
                    runtime_assets.RuntimeAssetsRequiredError, "Run ./run.sh scripts"
                ):
                    runtime_assets.require_runtime_assets(
                        "en", "paddleocr", "preserve-source-formatting"
                    )
                runtime_assets.mark_bootstrap_complete()
                runtime_assets.require_runtime_assets("en", "paddleocr", "preserve-source-formatting")

    # Verifies FR-2026-08-27-03 and FR-2026-08-27-04.
    def test_fitted_layout_requires_the_bootstrapped_symbol_font_before_processing(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            with patch.dict(
                os.environ,
                {runtime_assets.FONT_CACHE_ENVIRONMENT_VARIABLE: temporary_directory},
                clear=False,
            ):
                with self.assertRaisesRegex(
                    runtime_assets.RuntimeAssetsRequiredError,
                    "Noto Sans Math is missing from the shared font cache",
                ) as context:
                    runtime_assets.require_runtime_assets("en", "no_ocr", "preserve-basic-layout")
                self.assertIn(str(runtime_assets.symbols_font_path()), str(context.exception))
                self.assertIn(str(runtime_assets.math_font_path()), str(context.exception))
                self.assertIn("Run ./run.sh scripts", str(context.exception))

                runtime_assets.symbols_font_path().parent.mkdir(parents=True, exist_ok=True)
                runtime_assets.symbols_font_path().write_bytes(b"synthetic-symbol-font")
                runtime_assets.math_font_path().write_bytes(b"synthetic-math-font")
                runtime_assets.require_runtime_assets("en", "no_ocr", "preserve-basic-layout")

    # Verifies FR-2026-08-27-03 and FR-2026-08-27-04.
    def test_unconfigured_fitted_target_language_fails_before_processing(self) -> None:
        with self.assertRaisesRegex(
            runtime_assets.RuntimeAssetsRequiredError, "no configured portable Noto fallback"
        ):
            runtime_assets.require_runtime_assets("zh", "no_ocr", "preserve-basic-layout")
