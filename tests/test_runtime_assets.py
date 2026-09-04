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

    # Verifies FR-2026-09-02-01.
    def test_temporary_file_operation_retries_a_transient_windows_lock(self) -> None:
        error = PermissionError("file is being used by another process")
        setattr(error, "winerror", 32)
        attempts = 0

        def temporarily_locked_operation() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise error
            return "complete"

        with patch("pipeline.runtime_assets.time.sleep") as sleep:
            result = runtime_assets._retry_temporary_file_operation(
                "remove", Path("temporary.zip"), temporarily_locked_operation
            )

        self.assertEqual("complete", result)
        self.assertEqual(2, attempts)
        sleep.assert_called_once()

    # Verifies FR-2026-09-02-01.
    def test_temporary_file_operation_reports_an_exhausted_windows_lock(self) -> None:
        error = PermissionError("file is being used by another process")
        setattr(error, "winerror", 32)

        def permanently_locked_operation() -> None:
            raise error

        with patch(
            "pipeline.runtime_assets.time.monotonic", side_effect=(100.0, 130.0)
        ):
            with self.assertRaisesRegex(
                runtime_assets.RuntimeAssetTemporaryFileLockError,
                "endpoint-security software",
            ) as context:
                runtime_assets._retry_temporary_file_operation(
                    "remove", Path("temporary.zip"), permanently_locked_operation
                )

        self.assertIn("temporary.zip", str(context.exception))
        self.assertIn("30.0 seconds", str(context.exception))

    # Verifies FR-2026-09-02-01.
    def test_temporary_file_operation_does_not_retry_other_filesystem_errors(self) -> None:
        error = FileNotFoundError("temporary file is missing")

        def missing_file_operation() -> None:
            raise error

        with patch("pipeline.runtime_assets.time.sleep") as sleep:
            with self.assertRaises(FileNotFoundError):
                runtime_assets._retry_temporary_file_operation(
                    "remove", Path("temporary.zip"), missing_file_operation
                )

        sleep.assert_not_called()

    # Verifies FR-2026-08-27-04.
    def test_paddle_processing_requires_the_successful_bootstrap_marker(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            with patch.dict(
                os.environ,
                {runtime_assets.FONT_CACHE_ENVIRONMENT_VARIABLE: temporary_directory},
                clear=False,
            ):
                with self.assertRaises(runtime_assets.RuntimeAssetsRequiredError) as context:
                    runtime_assets.require_runtime_assets(
                        "en", "paddleocr", "preserve-source-formatting"
                    )
                self.assertIn(runtime_assets.bootstrap_command(), str(context.exception))
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
                self.assertIn(runtime_assets.bootstrap_command(), str(context.exception))

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
