"""Opt-in source-adjacent caching for normalized provider results."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from contextvars import ContextVar, Token
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pipeline.ocr.models import OcrRequest, OcrResult
    from pipeline.ocr.provider import LocalContractTestSkip, OcrProvider
    from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult
    from pipeline.text_replacement.provider import TextReplacementProvider


CACHE_ENVIRONMENT_VARIABLE = "PIPELINE_PLUGIN_CACHE"
CACHE_FILENAME_SUFFIX = ".plugin-cache.sqlite3"
_CACHE_SCHEMA_VERSION = 1
_MAXIMUM_CACHE_VALUE_BYTES = 4 * 1024 * 1024
_MAXIMUM_COLLECTION_ITEMS = 10_000
_MAXIMUM_NESTING_DEPTH = 32
_SOURCE_CACHE_SESSION: ContextVar[_SourceCacheSession | None] = ContextVar(
    "source_cache_session", default=None
)


def caching_is_enabled() -> bool:
    """Return whether the explicit opt-in provider cache is enabled."""
    return os.environ.get(CACHE_ENVIRONMENT_VARIABLE) == "1"


def is_cache_sidecar(path: Path) -> bool:
    """Return whether a path is a cache database or SQLite sidecar for one."""
    name = path.name
    return name.endswith(CACHE_FILENAME_SUFFIX) or any(
        name.endswith(f"{CACHE_FILENAME_SUFFIX}{suffix}")
        for suffix in ("-journal", "-shm", "-wal")
    )


class _SourceCacheSession:
    """Own one lazily opened SQLite connection for a source-cache scope."""

    def __init__(self, cache_path: Path) -> None:
        self._cache_path = cache_path
        self._connection: sqlite3.Connection | None = None
        self._disabled = False

    def connection(self) -> sqlite3.Connection | None:
        """Return the reusable connection, or disable this scope after a DB failure."""
        if self._disabled:
            return None
        if self._connection is None:
            connection: sqlite3.Connection | None = None
            try:
                self._cache_path.parent.mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(self._cache_path, timeout=1.0)
                connection.execute("PRAGMA journal_mode=DELETE")
                connection.execute("PRAGMA busy_timeout=1000")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS provider_result_cache ("
                    "result_kind TEXT NOT NULL, cache_key TEXT NOT NULL, result_json TEXT NOT NULL, "
                    "PRIMARY KEY (result_kind, cache_key))"
                )
            except sqlite3.Error:
                if connection is not None:
                    connection.close()
                self._disabled = True
                return None
            self._connection = connection
        return self._connection

    def disable(self) -> None:
        """Stop caching for this source after an SQLite operation fails."""
        self._disabled = True
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def close(self) -> None:
        """Commit cached successes and close this source's connection."""
        if self._connection is None:
            return
        try:
            self._connection.commit()
        except sqlite3.Error:
            self._connection.rollback()
        finally:
            self._connection.close()
            self._connection = None


class _SourceCacheScope(AbstractContextManager[None]):
    """Bind one source file's cache sidecar to provider calls in this context."""

    def __init__(self, source_path: Path) -> None:
        self._source_path = source_path
        self._token: Token[_SourceCacheSession | None] | None = None
        self._session: _SourceCacheSession | None = None

    def __enter__(self) -> None:
        self._session = _SourceCacheSession(
            self._source_path.with_name(f"{self._source_path.name}{CACHE_FILENAME_SUFFIX}")
        )
        self._token = _SOURCE_CACHE_SESSION.set(self._session)
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        del exc_type, exc_value, traceback
        if self._session is not None:
            self._session.close()
        if self._token is not None:
            _SOURCE_CACHE_SESSION.reset(self._token)


def source_cache_scope(source_path: Path) -> AbstractContextManager[None]:
    """Return a context that associates provider calls with one source file."""
    return _SourceCacheScope(source_path)


class CachingOcrProvider:
    """Delegate OCR while reusing normalized results in the active source cache."""

    def __init__(self, provider: OcrProvider, cache_identity: str) -> None:
        self._provider = provider
        self._cache_identity = cache_identity

    @property
    def supported_languages(self) -> frozenset[str]:
        return self._provider.supported_languages

    @property
    def supports_local_contract_test(self) -> bool:
        return self._provider.supports_local_contract_test

    @property
    def skipped_local_contract_angles(self) -> frozenset[int]:
        return self._provider.skipped_local_contract_angles

    @property
    def skipped_local_contract_cases(self) -> frozenset[LocalContractTestSkip]:
        return self._provider.skipped_local_contract_cases

    def recognize(self, request: OcrRequest) -> OcrResult:
        """Return a cached OCR result when the active source cache has one."""
        if _active_cache_session() is None:
            return self._provider.recognize(request)
        cache_key = _ocr_cache_key(self._cache_identity, request)
        cached = _read_result("ocr", cache_key, _ocr_result_from_payload)
        if cached is not None:
            return cast("OcrResult", cached)
        result = self._provider.recognize(request)
        _write_result("ocr", cache_key, _ocr_result_payload(result))
        return result


class CachingTextReplacementProvider:
    """Delegate replacement while reusing normalized results in the active cache."""

    def __init__(self, provider: TextReplacementProvider, cache_identity: str) -> None:
        self._provider = provider
        self._cache_identity = cache_identity

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        """Return a cached text-replacement result when available."""
        if _active_cache_session() is None:
            return self._provider.replace(request)
        cache_key = _text_replacement_cache_key(self._cache_identity, request)
        cached = _read_result("text_replacement", cache_key, _text_result_from_payload)
        if cached is not None:
            return cast("TextReplacementResult", cached)
        result = self._provider.replace(request)
        _write_result("text_replacement", cache_key, _text_result_payload(result))
        return result


def _ocr_cache_key(cache_identity: str, request: OcrRequest) -> str | None:
    try:
        image_bytes = request.image.tobytes()
        image_size = request.image.size
        image_mode = request.image.mode
    except (AttributeError, OSError, ValueError):
        return None
    return _cache_key(
        {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "provider": cache_identity,
            "language": request.language,
            "image_mode": image_mode,
            "image_size": image_size,
            "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
        }
    )


def _text_replacement_cache_key(
    cache_identity: str, request: TextReplacementRequest
) -> str:
    return _cache_key(
        {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "provider": cache_identity,
            "text": request.text,
            "is_filename": request.is_filename,
            "source_language": request.source_language,
            "target_language": request.target_language,
        }
    )


def _cache_key(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _read_result(
    result_kind: str, cache_key: str | None, decoder: Callable[[object], object]
) -> object | None:
    session = _active_cache_session()
    if session is None or cache_key is None:
        return None
    connection = session.connection()
    if connection is None:
        return None
    try:
        row = connection.execute(
            "SELECT result_json FROM provider_result_cache WHERE result_kind = ? AND cache_key = ?",
            (result_kind, cache_key),
        ).fetchone()
        if row is None or not isinstance(row[0], str) or len(row[0].encode("utf-8")) > _MAXIMUM_CACHE_VALUE_BYTES:
            return None
        try:
            result = decoder(json.loads(row[0]))
        except (TypeError, ValueError, json.JSONDecodeError, RecursionError):
            connection.execute(
                "DELETE FROM provider_result_cache WHERE result_kind = ? AND cache_key = ?",
                (result_kind, cache_key),
            )
            return None
        return result
    except sqlite3.Error:
        session.disable()
        return None


def _write_result(result_kind: str, cache_key: str | None, payload: object) -> None:
    session = _active_cache_session()
    if session is None or cache_key is None:
        return
    try:
        value = _normalized_json_value(payload)
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > _MAXIMUM_CACHE_VALUE_BYTES:
            return
        connection = session.connection()
        if connection is None:
            return
        connection.execute(
            "INSERT INTO provider_result_cache (result_kind, cache_key, result_json) VALUES (?, ?, ?) "
            "ON CONFLICT(result_kind, cache_key) DO UPDATE SET result_json = excluded.result_json",
            (result_kind, cache_key, encoded),
        )
    except (sqlite3.Error, TypeError, ValueError, RecursionError):
        session.disable()
        return


def _active_cache_session() -> _SourceCacheSession | None:
    return _SOURCE_CACHE_SESSION.get() if caching_is_enabled() else None


def _ocr_result_payload(result: OcrResult) -> object:
    return {
        "text_items": [
            {
                "text": item.text,
                "confidence": item.confidence,
                "bounding_polygon": [[point.x, point.y] for point in item.bounding_polygon.vertices],
                "extra": item.extra,
            }
            for item in result.text_items
        ]
    }


def _ocr_result_from_payload(payload: object) -> OcrResult:
    from pipeline.ocr.models import BoundingPolygon, OcrResult, OcrText, PixelPoint

    mapping = _mapping(payload)
    raw_items = _list(mapping.get("text_items"))
    if len(raw_items) > _MAXIMUM_COLLECTION_ITEMS:
        raise ValueError("Too many cached OCR text items.")
    items: list[OcrText] = []
    for raw_item in raw_items:
        item = _mapping(raw_item)
        vertices = _list(item.get("bounding_polygon"))
        if len(vertices) < 3 or len(vertices) > _MAXIMUM_COLLECTION_ITEMS:
            raise ValueError("Invalid cached OCR polygon.")
        points = tuple(
            PixelPoint(_number(_list(vertex)[0]), _number(_list(vertex)[1]))
            for vertex in vertices
            if len(_list(vertex)) == 2
        )
        if len(points) != len(vertices):
            raise ValueError("Invalid cached OCR polygon vertex.")
        items.append(
            OcrText(
                text=_string(item.get("text")),
                confidence=_number(item.get("confidence")),
                bounding_polygon=BoundingPolygon(points),
                extra=_mapping(_normalized_json_value(item.get("extra"))),
            )
        )
    return OcrResult(tuple(items))


def _text_result_payload(result: TextReplacementResult) -> object:
    return {"text": result.text, "confidence": result.confidence, "extra": result.extra}


def _text_result_from_payload(payload: object) -> TextReplacementResult:
    from pipeline.text_replacement.models import TextReplacementResult

    mapping = _mapping(payload)
    return TextReplacementResult(
        text=_string(mapping.get("text")),
        confidence=_number(mapping.get("confidence")),
        extra=_mapping(_normalized_json_value(mapping.get("extra"))),
    )


def _normalized_json_value(value: object, depth: int = 0) -> object:
    if depth > _MAXIMUM_NESTING_DEPTH:
        raise ValueError("Cached JSON is nested too deeply.")
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Cached JSON number is not finite.")
        return value
    if isinstance(value, list | tuple):
        if len(value) > _MAXIMUM_COLLECTION_ITEMS:
            raise ValueError("Cached JSON collection is too large.")
        return [_normalized_json_value(item, depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > _MAXIMUM_COLLECTION_ITEMS or not all(isinstance(key, str) for key in value):
            raise ValueError("Cached JSON object is invalid.")
        return {key: _normalized_json_value(item, depth + 1) for key, item in value.items()}
    raise TypeError("Cached JSON value is not serializable.")


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Cached value is not an object.")
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Cached value is not a list.")
    return cast(list[object], value)


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Cached value is not a string.")
    return value


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("Cached value is not a number.")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Cached value is not finite.")
    return number
