#!/usr/bin/env python3
"""Render Windows EMF development outputs as local PNG previews."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.terminal_progress import LiveProgress
from pipeline.vector_text.emfplus import EMFPLUS_OBJECT, PlusRecord
from pipeline.vector_text.emfplus_image import find_image_objects


DEFAULT_DPI = 400
MAX_PIXELS = 25_000_000
MAX_METAFILE_BYTES = 128 * 1024 * 1024
_SAFE_EMF_RECORDS = frozenset(range(1, 69)) | frozenset(range(70, 99)) | {
    108, 114, 115, 116, 118, 120,
}
_GDIC_BEGINGROUP = 2
_GDIC_ENDGROUP = 3
MAX_NESTED_METAFILES = 4
_SAFE_PLUS_RECORDS = frozenset(range(0x4001, 0x4038)) - {
    0x4003, 0x4005, 0x4006, 0x4007,
}


class PreviewError(Exception):
    """A graphic cannot be safely or successfully previewed."""


@dataclass(frozen=True)
class Metafile:
    data: bytes
    width: int
    height: int


def _checked_metafile(path: Path, dpi: float) -> Metafile:
    try:
        with path.open("rb") as file:
            data = file.read(MAX_METAFILE_BYTES + 1)
    except OSError as error:
        raise PreviewError("Cannot read the EMF.") from error
    if len(data) > MAX_METAFILE_BYTES:
        raise PreviewError("EMF exceeds the preview input size limit.")
    if len(data) < 88 or data[40:44] != b" EMF":
        raise PreviewError("Invalid EMF header.")
    left, top, right, bottom = struct.unpack_from("<iiii", data, 24)
    physical_width = (right - left) * dpi / 2540
    physical_height = (bottom - top) * dpi / 2540
    if not math.isfinite(physical_width) or not math.isfinite(physical_height):
        raise PreviewError("Invalid or oversized EMF preview dimensions.")
    width = round(physical_width)
    height = round(physical_height)
    if width <= 0 or height <= 0 or width * height * 2 > MAX_PIXELS:
        raise PreviewError("Invalid or oversized EMF preview dimensions.")

    _verify_records(data, 0)
    return Metafile(data, width, height)


def _verify_records(data: bytes, depth: int) -> None:
    """Check every record of an EMF, including nested EMF image objects."""
    offset = 0
    comments: list[tuple[int, list[PlusRecord]]] = []
    record_index = 0
    while offset < len(data):
        if offset + 8 > len(data):
            raise PreviewError("Malformed EMF record.")
        kind, size = struct.unpack_from("<II", data, offset)
        if kind not in _SAFE_EMF_RECORDS or size < 8 or size % 4 or offset + size > len(data):
            raise PreviewError("EMF contains an unverified or malformed record.")
        record = data[offset : offset + size]
        if kind == 70:
            if not _is_plus_comment(record):
                _check_non_plus_comment(record)
                offset += size
                record_index += 1
                continue
            records = _parse_plus_records(record)
            for plus in records:
                if plus.record_type not in _SAFE_PLUS_RECORDS:
                    raise PreviewError("EMF+ contains an unverified record.")
                if plus.record_type == EMFPLUS_OBJECT:
                    object_type = (plus.flags >> 8) & 0x7F
                    if object_type == 2:
                        _check_pen(plus)
                    elif object_type == 1:
                        if plus.flags & 0x8000 or len(plus.data) < 8:
                            raise PreviewError("EMF+ brush cannot be verified.")
                        _check_brush(plus.data)
                    elif object_type not in {3, 4, 5, 6, 7, 8, 9}:
                        raise PreviewError("EMF+ object cannot be verified.")
            comments.append((record_index, records))
        offset += size
        record_index += 1
    objects, unsupported = find_image_objects(comments)
    if unsupported:
        raise PreviewError("EMF+ image object cannot be verified as self-contained.")
    for obj in objects:
        if obj.kind == "bitmap":
            continue
        if obj.extension != ".emf" or depth >= MAX_NESTED_METAFILES:
            raise PreviewError("EMF+ image object cannot be verified as self-contained.")
        if len(obj.payload) < 88 or obj.payload[40:44] != b" EMF":
            raise PreviewError("EMF+ nested metafile has an invalid header.")
        _verify_records(obj.payload, depth + 1)


def _is_plus_comment(record: bytes) -> bool:
    return len(record) >= 16 and record[12:16] == b"EMF+"


def _check_non_plus_comment(record: bytes) -> None:
    """Accept only comments GDI never interprets as a graphic or resource.

    Classification uses the 4-byte identifier and, for public GDIC comments,
    the 4-byte type. Comment contents are not otherwise parsed.
    """
    data_size = struct.unpack_from("<I", record, 8)[0] if len(record) >= 12 else 0
    if data_size < 4 or 12 + data_size > len(record) or len(record) - 12 - data_size >= 4:
        raise PreviewError("EMF contains a malformed comment.")
    if record[12:16] != b"GDIC":
        return
    if data_size < 8:
        raise PreviewError("EMF contains a malformed comment.")
    comment_type = struct.unpack_from("<I", record, 16)[0]
    if comment_type == _GDIC_ENDGROUP:
        return
    if comment_type == _GDIC_BEGINGROUP:
        if data_size < 28 or 28 + 2 * struct.unpack_from("<I", record, 36)[0] > data_size:
            raise PreviewError("EMF contains a malformed comment.")
        return
    raise PreviewError("EMF contains an unsupported public comment type.")


def _parse_plus_records(comment: bytes) -> list[PlusRecord]:
    data_size = struct.unpack_from("<I", comment, 8)[0]
    end = 12 + data_size
    if data_size < 4 or end > len(comment):
        raise PreviewError("Malformed EMF+ comment.")
    records: list[PlusRecord] = []
    offset = 16
    while offset < end:
        if offset + 12 > end:
            raise PreviewError("Malformed EMF+ record.")
        kind, flags, size, data_length = struct.unpack_from("<HHII", comment, offset)
        if size < 12 or size % 4 or offset + size > end or data_length > size - 12:
            raise PreviewError("Malformed EMF+ record.")
        records.append(PlusRecord(
            kind, flags, comment[offset : offset + size], comment[offset + 12 : offset + 12 + data_length],
        ))
        offset += size
    return records


def _check_brush(data: bytes) -> None:
    if len(data) < 8 or struct.unpack_from("<I", data, 4)[0] not in {0, 1, 3, 4}:
        raise PreviewError("EMF+ brush cannot be verified as self-contained.")


def _check_pen(record: PlusRecord) -> None:
    data = record.data
    if record.flags & 0x8000 or len(data) < 28:
        raise PreviewError("EMF+ pen cannot be verified.")
    pen_type, flags = struct.unpack_from("<II", data, 4)
    if pen_type != 0 or flags & ~0x1FFF:
        raise PreviewError("EMF+ pen options cannot be verified.")
    brush_offset = 20 + (24 if flags & 1 else 0)
    brush_offset += 4 * sum(bool(flags & (1 << bit)) for bit in range(1, 8))
    if flags & 0x100:
        brush_offset = _skip_pen_array(data, brush_offset)
    brush_offset += 4 if flags & 0x200 else 0
    if flags & 0x400:
        brush_offset = _skip_pen_array(data, brush_offset)
    # Custom caps are size-prefixed path data and name no external resource.
    for custom_cap in (0x800, 0x1000):
        if flags & custom_cap:
            brush_offset = _skip_sized_pen_data(data, brush_offset)
    _check_brush(data[brush_offset:])


def _skip_sized_pen_data(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise PreviewError("EMF+ pen custom cap cannot be verified.")
    size: int = struct.unpack_from("<I", data, offset)[0]
    end = offset + 4 + size
    if end > len(data):
        raise PreviewError("EMF+ pen custom cap cannot be verified.")
    return end


def _skip_pen_array(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise PreviewError("EMF+ pen array cannot be verified.")
    count: int = struct.unpack_from("<I", data, offset)[0]
    end = offset + 4 + 4 * count
    if end > len(data):
        raise PreviewError("EMF+ pen array cannot be verified.")
    return end


class BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("width", wintypes.LONG),
        ("height", wintypes.LONG),
        ("planes", wintypes.WORD),
        ("bit_count", wintypes.WORD),
        ("compression", wintypes.DWORD),
        ("size_image", wintypes.DWORD),
        ("x_pixels_per_meter", wintypes.LONG),
        ("y_pixels_per_meter", wintypes.LONG),
        ("colors_used", wintypes.DWORD),
        ("colors_important", wintypes.DWORD),
    ]


class BitmapInfo(ctypes.Structure):
    _fields_ = [("header", BitmapInfoHeader), ("colors", wintypes.DWORD * 3)]


class StartupInput(ctypes.Structure):
    _fields_ = [
        ("version", wintypes.UINT),
        ("debug_callback", ctypes.c_void_p),
        ("suppress_background_thread", wintypes.BOOL),
        ("suppress_external_codecs", wintypes.BOOL),
    ]


class WindowsRenderer:
    def __init__(self) -> None:
        self.gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        self.plus = ctypes.WinDLL("gdiplus", use_last_error=True)
        self._configure()
        self.token = ctypes.c_size_t()
        startup = StartupInput(1, None, False, True)
        self._check(self.plus.GdiplusStartup(ctypes.byref(self.token), ctypes.byref(startup), None))

    def _configure(self) -> None:
        self.gdi.SetEnhMetaFileBits.argtypes = [wintypes.UINT, ctypes.c_void_p]
        self.gdi.SetEnhMetaFileBits.restype = ctypes.c_void_p
        self.gdi.DeleteEnhMetaFile.argtypes = [ctypes.c_void_p]
        self.gdi.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
        self.gdi.CreateCompatibleDC.restype = ctypes.c_void_p
        self.gdi.DeleteDC.argtypes = [ctypes.c_void_p]
        self.gdi.CreateDIBSection.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(BitmapInfo), wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, wintypes.DWORD,
        ]
        self.gdi.CreateDIBSection.restype = ctypes.c_void_p
        self.gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.gdi.SelectObject.restype = ctypes.c_void_p
        self.gdi.DeleteObject.argtypes = [ctypes.c_void_p]
        self.gdi.GdiFlush.argtypes = []
        self.gdi.PlayEnhMetaFile.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.RECT),
        ]
        self.plus.GdiplusStartup.argtypes = [
            ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(StartupInput), ctypes.c_void_p,
        ]
        self.plus.GdiplusShutdown.argtypes = [ctypes.c_size_t]
        self.plus.GdipGetMetafileHeaderFromEmf.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.plus.GdipCreateMetafileFromEmf.argtypes = [
            ctypes.c_void_p, wintypes.BOOL, ctypes.POINTER(ctypes.c_void_p),
        ]
        self.plus.GdipCreateFromHDC.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        self.plus.GdipDrawImageRectI.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ]
        self.plus.GdipDeleteGraphics.argtypes = [ctypes.c_void_p]
        self.plus.GdipDisposeImage.argtypes = [ctypes.c_void_p]

    @staticmethod
    def _check(status: int) -> None:
        if status != 0:
            raise PreviewError(f"Windows GDI+ failed with status {status}.")

    def close(self) -> None:
        self.plus.GdiplusShutdown(self.token)

    def render(self, metafile: Metafile, size: tuple[int, int], mode: str) -> Image.Image | None:
        data = ctypes.create_string_buffer(metafile.data)
        handle = self.gdi.SetEnhMetaFileBits(len(metafile.data), data)
        if not handle:
            raise PreviewError("Windows could not load the EMF.")
        try:
            header = ctypes.create_string_buffer(512)
            self._check(self.plus.GdipGetMetafileHeaderFromEmf(handle, header))
            metafile_type = struct.unpack_from("<i", header.raw)[0]
            if mode == "gdi" and metafile_type == 4:
                return None
            return self._render_handle(handle, size, (metafile.width, metafile.height), mode)
        finally:
            self.gdi.DeleteEnhMetaFile(handle)

    def _render_handle(
        self, handle: int, size: tuple[int, int], draw_size: tuple[int, int], mode: str
    ) -> Image.Image:
        width, height = size
        dc = self.gdi.CreateCompatibleDC(None)
        if not dc:
            raise PreviewError("Windows could not create a rendering context.")
        bitmap = None
        previous = None
        graphics = ctypes.c_void_p()
        image = ctypes.c_void_p()
        try:
            info = BitmapInfo()
            info.header.size = ctypes.sizeof(BitmapInfoHeader)
            info.header.width = width
            info.header.height = -height
            info.header.planes = 1
            info.header.bit_count = 32
            pixels = ctypes.c_void_p()
            bitmap = self.gdi.CreateDIBSection(dc, ctypes.byref(info), 0, ctypes.byref(pixels), None, 0)
            if not bitmap or not pixels.value:
                raise PreviewError("Windows could not allocate the preview bitmap.")
            previous = self.gdi.SelectObject(dc, bitmap)
            if not previous or previous == ctypes.c_void_p(-1).value:
                raise PreviewError("Windows could not select the preview bitmap.")
            ctypes.memset(pixels, 255, width * height * 4)
            if mode == "gdi":
                rect = wintypes.RECT(0, 0, *draw_size)
                if not self.gdi.PlayEnhMetaFile(dc, handle, ctypes.byref(rect)):
                    raise PreviewError("Windows GDI playback failed.")
            else:
                self._check(self.plus.GdipCreateMetafileFromEmf(handle, False, ctypes.byref(image)))
                self._check(self.plus.GdipCreateFromHDC(dc, ctypes.byref(graphics)))
                self._check(self.plus.GdipDrawImageRectI(graphics, image, 0, 0, *draw_size))
                self._check(self.plus.GdipDeleteGraphics(graphics))
                graphics = ctypes.c_void_p()
            if not self.gdi.GdiFlush():
                raise PreviewError("Windows could not finish rendering the preview.")
            return Image.frombytes("RGB", size, ctypes.string_at(pixels, width * height * 4), "raw", "BGRX")
        finally:
            if graphics.value:
                self.plus.GdipDeleteGraphics(graphics)
            if image.value:
                self.plus.GdipDisposeImage(image)
            if previous:
                self.gdi.SelectObject(dc, previous)
            if bitmap:
                self.gdi.DeleteObject(bitmap)
            self.gdi.DeleteDC(dc)


def _original(path: Path) -> Path | None:
    sidecar = path.with_name(path.name + ".diagnostics.json")
    if not sidecar.is_file():
        return None
    try:
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        source = metadata.get("source_absolute_path")
        if not isinstance(source, str):
            return None
        original = Path(source)
        if not original.is_absolute() or str(original).startswith("\\\\"):
            return None
        if not original.is_file() or original.resolve() == path.resolve():
            return None
        return original
    except (OSError, ValueError, AttributeError):
        return None


def _process(path: Path, dpi: float, renderer: WindowsRenderer, display: LiveProgress | None = None) -> bool:
    if display is not None:
        display.start_current(path.name, 2, "playback")
    original_path = _original(path)
    evaluation_root = (PROJECT_ROOT / "outputs" / "evaluations").resolve()
    confidential_root = (PROJECT_ROOT / "sample-data" / "confidential").resolve()
    if (
        path.resolve().is_relative_to(confidential_root)
        or (original_path is not None and original_path.resolve().is_relative_to(confidential_root))
    ) and not path.resolve().is_relative_to(evaluation_root):
        print("Warning: confidential previews must remain below outputs/evaluations.", file=sys.stderr)
        return False
    try:
        processed = _checked_metafile(path, dpi)
    except (PreviewError, MemoryError) as error:
        message = str(error) if isinstance(error, PreviewError) else "Cannot allocate the EMF preview."
        print(f"Warning: {message}", file=sys.stderr)
        if any(
            path.with_name(f"{path.name}.{kind}{mode}.png").exists()
            for mode in ("", ".gdi") for kind in ("preview", "diff")
        ):
            print("Warning: an earlier preview may be stale.", file=sys.stderr)
        return False
    original = None
    if original_path is not None:
        try:
            original = _checked_metafile(original_path, dpi)
        except (PreviewError, MemoryError) as error:
            message = str(error) if isinstance(error, PreviewError) else "Cannot allocate the original preview."
            print(f"Warning: original unavailable for comparison: {message}", file=sys.stderr)
    size = (original.width, original.height) if original else (processed.width, processed.height)
    success = True
    for mode in ("gdiplus", "gdi"):
        suffix = ".gdi" if mode == "gdi" else ""
        kind = "diff" if original else "preview"
        destination = path.with_name(f"{path.name}.{kind}{suffix}.png")
        stale = path.with_name(f"{path.name}.{'preview' if original else 'diff'}{suffix}.png")
        if stale.exists():
            print("Warning: an earlier preview may be stale.", file=sys.stderr)
        try:
            left = renderer.render(original, size, mode) if original else None
            right = renderer.render(processed, size, mode)
            if right is None or (original is not None and left is None):
                print("Warning: GDI playback is unavailable for an EMF+ Only file.", file=sys.stderr)
                if destination.exists():
                    print("Warning: an earlier preview may be stale.", file=sys.stderr)
                continue
            if left is not None:
                combined = Image.new("RGB", (size[0] * 2, size[1]), "white")
                combined.paste(left, (0, 0))
                combined.paste(right, (size[0], 0))
            else:
                combined = right
            _save_png(combined, destination, dpi)
        except (PreviewError, MemoryError) as error:
            message = str(error) if isinstance(error, PreviewError) else "Cannot allocate the preview bitmap."
            print(f"Warning: {mode} preview failed: {message}", file=sys.stderr)
            if destination.exists():
                print("Warning: an earlier preview may be stale.", file=sys.stderr)
            success = False
        finally:
            if display is not None:
                display.advance_current()
    return success


def _save_png(image: Image.Image, destination: Path, dpi: float) -> None:
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".png", delete=False) as file:
            temporary = file.name
            image.save(file, format="PNG", dpi=(dpi, dpi))
        os.replace(temporary, destination)
    except OSError as error:
        raise PreviewError("Cannot write the PNG sidecar.") from error
    finally:
        if temporary is not None and os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError as error:
                raise PreviewError("Cannot remove the temporary PNG sidecar.") from error


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Revision, scenario directory, or processed EMF.")
    parser.add_argument("--dpi", type=float, default=DEFAULT_DPI, help=f"Render resolution (default: {DEFAULT_DPI:g} DPI).")
    args = parser.parse_args(argv)
    if not math.isfinite(args.dpi) or args.dpi <= 0:
        parser.error("--dpi must be a positive finite number.")
    if sys.platform != "win32":
        parser.error("EMF preview is available only on Windows.")
    if args.path.is_file() and args.path.suffix.lower() == ".emf":
        files = [args.path]
    elif args.path.is_dir():
        files = sorted(path for path in args.path.rglob("*") if path.is_file() and path.suffix.lower() == ".emf")
    else:
        parser.error("Path must be an EMF file or a directory.")
    try:
        renderer = WindowsRenderer()
    except (OSError, PreviewError) as error:
        print(f"Warning: cannot initialize the Windows renderer: {error}", file=sys.stderr)
        return 1
    try:
        with LiveProgress() as display:
            display.start_overall(len(files), "file")
            failures = 0
            for path in files:
                if not _process(path, args.dpi, renderer, display):
                    failures += 1
                display.advance_overall()
    finally:
        renderer.close()
    if failures:
        print(f"Warning: {failures} EMF preview(s) failed.", file=sys.stderr)
    print(f"EMF preview: {len(files)} file(s), {failures} failure(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
