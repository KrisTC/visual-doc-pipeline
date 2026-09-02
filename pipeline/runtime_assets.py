"""Small shared bootstrap support for optional fonts and PaddleOCR models."""

from __future__ import annotations

import os
from pathlib import Path
import platform
import random
import shutil
from tempfile import NamedTemporaryFile
import time
from typing import Callable, TypeVar
from urllib.request import urlopen
from zipfile import ZipFile


FONT_CACHE_ENVIRONMENT_VARIABLE = "VISUAL_DOC_PIPELINE_FONT_CACHE"
_APPLICATION_CACHE_DIRECTORY = "visual-doc-pipeline"
_SYMBOLS_ARCHIVE_URL = (
    "https://github.com/notofonts/symbols/releases/download/"
    "NotoSansSymbols2-v2.008/NotoSansSymbols2-v2.008.zip"
)
_SYMBOLS_ARCHIVE_MEMBER = "NotoSansSymbols2/googlefonts/ttf/NotoSansSymbols2-Regular.ttf"
_SYMBOLS_FILENAME = "NotoSansSymbols2-Regular.ttf"
_MATH_ARCHIVE_URL = (
    "https://github.com/notofonts/math/releases/download/"
    "NotoSansMath-v3.000/NotoSansMath-v3.000.zip"
)
_MATH_ARCHIVE_MEMBER = "NotoSansMath/googlefonts/ttf/NotoSansMath-Regular.ttf"
_MATH_FILENAME = "NotoSansMath-Regular.ttf"
_SUCCESS_MARKER_FILENAME = "bootstrap-complete"
_TEMPORARY_FILE_LOCK_RETRY_SECONDS = 30.0
_TEMPORARY_FILE_LOCK_INITIAL_DELAY_SECONDS = 0.1
_TEMPORARY_FILE_LOCK_MAX_DELAY_SECONDS = 5.0
_FITTED_LAYOUT_MODES = frozenset(
    {"preserve-basic-layout", "preserve-basic-layout-source-font"}
)
_BASE_TARGET_LANGUAGES = frozenset({"en", "da", "es", "fr", "ja"})
_OperationResult = TypeVar("_OperationResult")


class RuntimeAssetsRequiredError(RuntimeError):
    """Raised when a processing command needs the local bootstrap first."""


class RuntimeAssetTemporaryFileLockError(RuntimeError):
    """Raised when a bootstrap temporary file remains locked after retries."""

    def __init__(
        self, operation: str, path: Path, elapsed_seconds: float, error: OSError
    ) -> None:
        super().__init__(
            f"Could not {operation} temporary bootstrap file {path} after "
            f"{elapsed_seconds:.1f} seconds of retrying: {error}. Another process, "
            "such as endpoint-security software, may be holding the file open."
        )


def font_cache_directory() -> Path:
    """Return the shared per-user cache for optional static font files."""
    configured = os.environ.get(FONT_CACHE_ENVIRONMENT_VARIABLE)
    if configured:
        return Path(configured).expanduser()
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Caches" / _APPLICATION_CACHE_DIRECTORY / "fonts"
    if system == "Windows":
        local_application_data_value = os.environ.get("LOCALAPPDATA")
        local_application_data = (
            Path(local_application_data_value)
            if local_application_data_value
            else Path.home() / "AppData" / "Local"
        )
        return local_application_data / _APPLICATION_CACHE_DIRECTORY / "fonts"
    cache_home_value = os.environ.get("XDG_CACHE_HOME")
    cache_home = Path(cache_home_value) if cache_home_value else Path.home() / ".cache"
    return cache_home / _APPLICATION_CACHE_DIRECTORY / "fonts"


def symbols_font_path() -> Path:
    """Return the optional Noto Sans Symbols 2 font location."""
    return font_cache_directory() / _SYMBOLS_FILENAME


def math_font_path() -> Path:
    """Return the optional Noto Sans Math font location."""
    return font_cache_directory() / _MATH_FILENAME


def bootstrap_marker_path() -> Path:
    """Return the small marker written only after a successful bootstrap."""
    return font_cache_directory() / _SUCCESS_MARKER_FILENAME


def symbols_font_is_available() -> bool:
    """Return whether the optional symbol fallback has been bootstrapped."""
    return symbols_font_path().is_file()


def math_font_is_available() -> bool:
    """Return whether the optional math fallback has been bootstrapped."""
    return math_font_path().is_file()


def bootstrap_optional_fonts() -> tuple[Path, Path]:
    """Download the selected optional portable faces into the shared cache."""
    return bootstrap_symbols_font(), bootstrap_math_font()


def bootstrap_symbols_font() -> Path:
    """Download the selected optional Noto Sans Symbols 2 face."""
    return _bootstrap_font(
        _SYMBOLS_ARCHIVE_URL, _SYMBOLS_ARCHIVE_MEMBER, symbols_font_path()
    )


def bootstrap_math_font() -> Path:
    """Download the selected optional Noto Sans Math face."""
    return _bootstrap_font(_MATH_ARCHIVE_URL, _MATH_ARCHIVE_MEMBER, math_font_path())


def _bootstrap_font(archive_url: str, archive_member: str, destination: Path) -> Path:
    """Download one pinned Noto archive member unless it is already cached."""
    if destination.is_file():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    font_path: Path | None = None
    with NamedTemporaryFile(dir=destination.parent, suffix=".zip", delete=False) as archive_file:
        archive_path = Path(archive_file.name)
        with urlopen(archive_url) as response:
            shutil.copyfileobj(response, archive_file)
        archive_file.flush()
    try:
        with ZipFile(archive_path) as archive:
            with archive.open(archive_member) as source:
                with NamedTemporaryFile(
                    dir=destination.parent, suffix=".ttf", delete=False
                ) as font_file:
                    font_path = Path(font_file.name)
                    shutil.copyfileobj(source, font_file)
        _retry_temporary_file_operation(
            "replace", font_path, lambda: font_path.replace(destination)
        )
    finally:
        _retry_temporary_file_operation(
            "remove", archive_path, lambda: archive_path.unlink(missing_ok=True)
        )
        if font_path is not None:
            _retry_temporary_file_operation(
                "remove", font_path, lambda: font_path.unlink(missing_ok=True)
            )
    return destination


def _retry_temporary_file_operation(
    operation: str, path: Path, action: Callable[[], _OperationResult]
) -> _OperationResult:
    """Retry a temporary-file operation if Windows briefly reports a file lock."""
    started_at = time.monotonic()
    deadline = started_at + _TEMPORARY_FILE_LOCK_RETRY_SECONDS
    delay_seconds = _TEMPORARY_FILE_LOCK_INITIAL_DELAY_SECONDS
    while True:
        try:
            return action()
        except OSError as error:
            if not _is_transient_file_lock(error):
                raise
            current_time = time.monotonic()
            if current_time >= deadline:
                raise RuntimeAssetTemporaryFileLockError(
                    operation, path, current_time - started_at, error
                ) from error
            jittered_delay_seconds = min(
                _TEMPORARY_FILE_LOCK_MAX_DELAY_SECONDS,
                delay_seconds * random.uniform(0.8, 1.2),
            )
            time.sleep(min(jittered_delay_seconds, deadline - current_time))
            delay_seconds = min(
                _TEMPORARY_FILE_LOCK_MAX_DELAY_SECONDS, delay_seconds * 2
            )


def _is_transient_file_lock(error: OSError) -> bool:
    """Return whether an OS error is a Windows sharing or locking conflict."""
    return getattr(error, "winerror", None) in {32, 33}


def paddle_model_cache_directory() -> Path:
    """Return PaddleOCR's own cache location without configuring it."""
    try:
        from paddlex.utils.cache import CACHE_DIR  # type: ignore[import-untyped]
    except ImportError:
        return Path.home() / ".paddlex"
    return Path(str(CACHE_DIR))


def mark_bootstrap_complete() -> None:
    """Record a successful local bootstrap beside the optional font cache."""
    marker = bootstrap_marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("complete\n", encoding="ascii")


def bootstrap_completed() -> bool:
    """Return whether the local setup command finished successfully."""
    return bootstrap_marker_path().is_file()


def bootstrap_command() -> str:
    """Return the platform-appropriate explicit runtime-asset setup command."""
    return (
        ".\\run.ps1 scripts/bootstrap_runtime_assets.py"
        if os.name == "nt"
        else "./run.sh scripts/bootstrap_runtime_assets.py"
    )


def require_runtime_assets(
    target_language: str, ocr_provider_name: str, document_text_layout: str
) -> None:
    """Fail before processing when the selected command needs bootstrap setup."""
    primary_language = target_language.strip().replace("_", "-").lower().split("-", 1)[0]
    if document_text_layout in _FITTED_LAYOUT_MODES and primary_language not in _BASE_TARGET_LANGUAGES:
        raise RuntimeAssetsRequiredError(
            f"Target language {target_language!r} has no configured portable Noto fallback."
        )
    missing_assets: list[str] = []
    if document_text_layout in _FITTED_LAYOUT_MODES:
        if not math_font_is_available():
            missing_assets.append(
                "Noto Sans Math is missing from the shared font cache: "
                f"{math_font_path()}"
            )
        if not symbols_font_is_available():
            missing_assets.append(
                "Noto Sans Symbols 2 is missing from the shared font cache: "
                f"{symbols_font_path()}"
            )
    if ocr_provider_name == "paddleocr" and not bootstrap_completed():
        missing_assets.append(
            "PaddleOCR models have not been bootstrapped "
            f"(completion marker: {bootstrap_marker_path()})"
        )
    if missing_assets:
        raise RuntimeAssetsRequiredError(
            "Required runtime assets are missing:\n- "
            + "\n- ".join(missing_assets)
            + f"\nRun {bootstrap_command()} first."
        )
