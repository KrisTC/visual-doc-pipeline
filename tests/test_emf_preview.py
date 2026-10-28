"""Synthetic tests for the Windows EMF preview command."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from contextlib import redirect_stderr
from io import StringIO
import json
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops

from pipeline.text_replacement import TextReplacementItem, TextReplacementRequest, TextReplacementResult, replace_each
from pipeline.vector_text import replace_vector_text
from pipeline.vector_text.common import ETO_CLIPPED
from pipeline.vector_text.emf import analyse_emf
from pipeline.vector_text.emfplus import PlusRecord
from scripts import emf_preview as preview
from test_vector_text_replacer import _emf_text_clips, _emf_text_options


class RectF(ctypes.Structure):
    _fields_ = [("x", ctypes.c_float), ("y", ctypes.c_float),
                ("width", ctypes.c_float), ("height", ctypes.c_float)]


def _record_metafile(
    kind: int, *, blue_fallback: bool = False, blue_plus: bool = False, draw_pen: bool = False,
    gdi_text: bool = False,
) -> bytes:
    gdi = ctypes.WinDLL("gdi32")
    user = ctypes.WinDLL("user32")
    plus = ctypes.WinDLL("gdiplus")
    user.GetDC.argtypes = [ctypes.c_void_p]
    user.GetDC.restype = ctypes.c_void_p
    user.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi.GetEnhMetaFileBits.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p]
    gdi.DeleteEnhMetaFile.argtypes = [ctypes.c_void_p]
    plus.GdiplusStartup.argtypes = [
        ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(preview.StartupInput), ctypes.c_void_p,
    ]
    plus.GdiplusShutdown.argtypes = [ctypes.c_size_t]
    plus.GdipRecordMetafile.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(RectF), ctypes.c_int,
        ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p),
    ]
    plus.GdipGetImageGraphicsContext.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    plus.GdipCreateSolidFill.argtypes = [wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    plus.GdipFillRectangleI.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ]
    plus.GdipDeleteBrush.argtypes = [ctypes.c_void_p]
    plus.GdipDeleteGraphics.argtypes = [ctypes.c_void_p]
    plus.GdipCreatePen1.argtypes = [
        wintypes.DWORD, ctypes.c_float, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p),
    ]
    plus.GdipDrawLineI.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ]
    plus.GdipDeletePen.argtypes = [ctypes.c_void_p]
    plus.GdipGetDC.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    plus.GdipReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR]
    gdi.CreateFontW.restype = ctypes.c_void_p
    gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi.SelectObject.restype = ctypes.c_void_p
    gdi.TextOutW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int]
    gdi.DeleteObject.argtypes = [ctypes.c_void_p]
    plus.GdipGetHemfFromMetafile.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    plus.GdipDisposeImage.argtypes = [ctypes.c_void_p]
    token = ctypes.c_size_t()
    startup = preview.StartupInput(1, None, False, True)
    if plus.GdiplusStartup(ctypes.byref(token), ctypes.byref(startup), None):
        raise RuntimeError("Could not start GDI+.")
    dc = user.GetDC(None)
    metafile = ctypes.c_void_p()
    graphics = ctypes.c_void_p()
    brush = ctypes.c_void_p()
    handle = ctypes.c_void_p()
    try:
        rect = RectF(0, 0, 25.4, 25.4)
        def check(status: int) -> None:
            if status:
                raise RuntimeError(f"Synthetic GDI+ recording failed: {status}")

        check(plus.GdipRecordMetafile(dc, kind, ctypes.byref(rect), 6, None, ctypes.byref(metafile)))
        check(plus.GdipGetImageGraphicsContext(metafile, ctypes.byref(graphics)))
        check(plus.GdipCreateSolidFill(0xFFFF0000, ctypes.byref(brush)))
        check(plus.GdipFillRectangleI(graphics, brush, 0, 0, 80, 80))
        if draw_pen:
            pen = ctypes.c_void_p()
            check(plus.GdipCreatePen1(0xFF000000, 2.0, 2, ctypes.byref(pen)))
            check(plus.GdipDrawLineI(graphics, pen, 0, 70, 80, 70))
            check(plus.GdipDeletePen(pen))
        if gdi_text:
            text_dc = ctypes.c_void_p()
            check(plus.GdipGetDC(graphics, ctypes.byref(text_dc)))
            font = gdi.CreateFontW(-30, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, "Arial")
            if not font:
                raise RuntimeError("Could not create synthetic GDI font.")
            old_font = gdi.SelectObject(text_dc, font)
            if not old_font or not gdi.TextOutW(text_dc, 5, 5, "Old", 3):
                raise RuntimeError("Could not draw synthetic GDI text.")
            gdi.SelectObject(text_dc, old_font)
            gdi.DeleteObject(font)
            check(plus.GdipReleaseDC(graphics, text_dc))
        check(plus.GdipDeleteBrush(brush))
        check(plus.GdipDeleteGraphics(graphics))
        check(plus.GdipGetHemfFromMetafile(metafile, ctypes.byref(handle)))
        size = gdi.GetEnhMetaFileBits(handle, 0, None)
        result = ctypes.create_string_buffer(size)
        if gdi.GetEnhMetaFileBits(handle, size, result) != size:
            raise RuntimeError("Could not read synthetic metafile.")
        data = bytearray(result.raw)
        struct.pack_into("<iiii", data, 24, 0, 0, 2540, 2540)
        if blue_fallback or blue_plus:
            offset = 0
            while offset < len(data):
                record_type, size = struct.unpack_from("<II", data, offset)
                if blue_fallback and record_type == 39:
                    struct.pack_into("<I", data, offset + 16, 0x00FF0000)
                if blue_plus and record_type == 70 and data[offset + 12 : offset + 16] == b"EMF+":
                    position = offset + 16
                    while position < offset + size:
                        plus_type, flags, plus_size, _ = struct.unpack_from("<HHII", data, position)
                        if plus_type == 0x400A and flags & 0x8000:
                            struct.pack_into("<I", data, position + 12, 0xFF0000FF)
                        position += plus_size
                offset += size
        return bytes(data)
    finally:
        if handle.value:
            gdi.DeleteEnhMetaFile(handle)
        if metafile.value:
            plus.GdipDisposeImage(metafile)
        user.ReleaseDC(None, dc)
        plus.GdiplusShutdown(token)


def _record_gdi_overlap_metafile(*, rotated: bool, opaque: bool = False, angle: int = 90) -> bytes:
    class _Transform(ctypes.Structure):
        _fields_ = [(name, ctypes.c_float) for name in ("m11", "m12", "m21", "m22", "dx", "dy")]

    gdi = ctypes.WinDLL("gdi32")
    user = ctypes.WinDLL("user32")
    user.GetDC.argtypes = [ctypes.c_void_p]
    user.GetDC.restype = ctypes.c_void_p
    user.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi.CreateEnhMetaFileW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(wintypes.RECT), ctypes.c_wchar_p]
    gdi.CreateEnhMetaFileW.restype = ctypes.c_void_p
    gdi.CloseEnhMetaFile.argtypes = [ctypes.c_void_p]
    gdi.CloseEnhMetaFile.restype = ctypes.c_void_p
    gdi.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR]
    gdi.CreateFontW.restype = ctypes.c_void_p
    gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi.SelectObject.restype = ctypes.c_void_p
    gdi.GetStockObject.argtypes = [ctypes.c_int]
    gdi.GetStockObject.restype = ctypes.c_void_p
    gdi.TextOutW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int]
    gdi.ExtTextOutW.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int, wintypes.UINT, ctypes.POINTER(wintypes.RECT),
        wintypes.LPCWSTR, wintypes.UINT, ctypes.c_void_p,
    ]
    gdi.Rectangle.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    gdi.MoveToEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    gdi.SetBkMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
    gdi.SetBkColor.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    gdi.SetTextColor.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    gdi.SetGraphicsMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
    gdi.SetWorldTransform.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Transform)]
    gdi.SaveDC.argtypes = [ctypes.c_void_p]
    gdi.RestoreDC.argtypes = [ctypes.c_void_p, ctypes.c_int]
    gdi.GetEnhMetaFileBits.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p]
    gdi.DeleteEnhMetaFile.argtypes = [ctypes.c_void_p]
    gdi.DeleteObject.argtypes = [ctypes.c_void_p]
    screen = user.GetDC(None)
    frame = wintypes.RECT(0, 0, 2540, 2540)
    dc = gdi.CreateEnhMetaFileW(screen, None, ctypes.byref(frame), None)
    font = gdi.CreateFontW(-20, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, "Arial")
    if not dc or not font:
        raise RuntimeError("Could not create synthetic GDI metafile.")
    old_font = gdi.SelectObject(dc, font)
    gdi.SetBkMode(dc, 1)
    if rotated:
        gdi.SaveDC(dc)
        gdi.SetGraphicsMode(dc, 2)
        transforms = {
            90: (0, 1, -1, 0, 35, 10),
            180: (-1, 0, 0, -1, 95, 45),
            270: (0, -1, 1, 0, 15, 95),
        }
        matrix = _Transform(*transforms[angle])
        if not gdi.SetWorldTransform(dc, ctypes.byref(matrix)) or not gdi.TextOutW(dc, 0, 0, "Old", 3):
            raise RuntimeError("Could not draw rotated synthetic text.")
        gdi.RestoreDC(dc, -1)
        neighbour = {90: (15, 70), 180: (5, 20), 270: (15, 5)}[angle]
    elif opaque:
        gdi.SetBkColor(dc, 0x0000FF00)
        opaque_rect = wintypes.RECT(5, 5, 75, 50)
        if not gdi.ExtTextOutW(dc, 10, 15, 2, ctypes.byref(opaque_rect), "Old", 3, None):
            raise RuntimeError("Could not draw opaque synthetic text.")
        neighbour = (80, 15)
    else:
        old_brush = gdi.SelectObject(dc, gdi.GetStockObject(5))
        gdi.Rectangle(dc, 5, 5, 70, 50)
        gdi.SelectObject(dc, old_brush)
        if not gdi.TextOutW(dc, 10, 15, "Old", 3):
            raise RuntimeError("Could not draw synthetic text.")
        neighbour = (80, 15)
    gdi.MoveToEx(dc, -100, -100, None)
    gdi.SetTextColor(dc, 0x000000FF)
    if not gdi.TextOutW(dc, *neighbour, "Value", 5):
        raise RuntimeError("Could not draw synthetic neighbouring text.")
    gdi.SelectObject(dc, old_font)
    handle = gdi.CloseEnhMetaFile(dc)
    gdi.DeleteObject(font)
    user.ReleaseDC(None, screen)
    if not handle:
        raise RuntimeError("Could not close synthetic GDI metafile.")
    try:
        size = gdi.GetEnhMetaFileBits(handle, 0, None)
        buffer = ctypes.create_string_buffer(size)
        if gdi.GetEnhMetaFileBits(handle, size, buffer) != size:
            raise RuntimeError("Could not read synthetic GDI metafile.")
        return buffer.raw
    finally:
        gdi.DeleteEnhMetaFile(handle)


def _comment_record(identifier: bytes, body: bytes) -> bytes:
    data = identifier + body
    padded = data + b"\0" * (-len(data) % 4)
    return struct.pack("<III", 70, 12 + len(padded), len(data)) + padded


def _image_comment(metafile_type: int, payload: bytes) -> bytes:
    image = struct.pack("<IIII", 0xDBC01002, 2, metafile_type, len(payload)) + payload
    record = struct.pack("<HHII", 0x4008, (5 << 8) | 1, 12 + len(image), len(image)) + image
    return _comment_record(b"EMF+", record)


def _with_comments(metafile: bytes, comments: list[bytes]) -> bytes:
    data = bytearray(metafile)
    header_size = struct.unpack_from("<I", data, 4)[0]
    data[header_size:header_size] = b"".join(comments)
    struct.pack_into("<I", data, 48, len(data))
    struct.pack_into("<I", data, 52, struct.unpack_from("<I", data, 52)[0] + len(comments))
    return bytes(data)


@unittest.skipUnless(sys.platform == "win32", "Requires Windows GDI+.")
class EmfPreviewTests(unittest.TestCase):
    # Verifies FR-2026-10-28-05.
    def test_fitted_text_stays_inside_shape_in_both_playback_paths(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request,
                    lambda text: TextReplacementItem("Wide heading" if text == "Old" else "i", 1.0),
                )

        source = _record_gdi_overlap_metafile(rotated=False)
        result = analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(lambda text: text, _Provider())
        decisions = result.emf_layout_trace[0]["fit_decisions"]
        assert isinstance(decisions, dict)
        self.assertLessEqual(decisions["expansion_limits"]["right"], 70)
        without_text = bytearray(result.data)
        offset = 0
        while offset < len(without_text):
            record_type, size = struct.unpack_from("<II", without_text, offset)
            if record_type == 84:
                struct.pack_into("<I", without_text, offset + 44, 0)
                break
            offset += size
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.emf"
            path.write_bytes(result.data)
            metafile = preview._checked_metafile(path, 192)
            reference = preview.Metafile(bytes(without_text), metafile.width, metafile.height)
            device_width, _, millimetres_width, _ = struct.unpack_from("<iiii", source, 72)
            frame_left, _, frame_right, _ = struct.unpack_from("<iiii", source, 24)
            scale_x = metafile.width * millimetres_width * 100 / (device_width * (frame_right - frame_left))
            renderer = preview.WindowsRenderer()
            try:
                for mode in ("gdi", "gdiplus"):
                    with self.subTest(mode=mode):
                        size = (metafile.width, metafile.height)
                        fitted = renderer.render(metafile, size, mode)
                        background = renderer.render(reference, size, mode)
                        assert fitted is not None and background is not None
                        bounds = ImageChops.difference(fitted, background).getbbox()
                        self.assertIsNotNone(bounds)
                        assert bounds is not None
                        self.assertLessEqual(bounds[2], 70 * scale_x + 3)
            finally:
                renderer.close()

    # Verifies FR-2026-10-28-05.
    def test_opaque_background_survives_overlap_clip_in_both_playback_paths(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request,
                    lambda text: TextReplacementItem("W" * 500 if text == "Old" else "i", 1.0),
                )

        source = _record_gdi_overlap_metafile(rotated=False, opaque=True)
        result = analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(lambda text: text, _Provider())
        options = _emf_text_options(result.data)
        self.assertTrue(options[0] & 2)
        self.assertTrue(options[1] & ETO_CLIPPED)
        self.assertEqual((5, 5, 75, 50), _emf_text_clips(result.data)[0])
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.emf"
            path.write_bytes(result.data)
            metafile = preview._checked_metafile(path, 192)
            original = preview.Metafile(source, metafile.width, metafile.height)
            device_width, device_height, millimetres_width, millimetres_height = struct.unpack_from("<iiii", source, 72)
            sample = (
                round(7 * metafile.width * millimetres_width * 100 / (device_width * 2540)),
                round(40 * metafile.height * millimetres_height * 100 / (device_height * 2540)),
            )
            renderer = preview.WindowsRenderer()
            try:
                for mode in ("gdi", "gdiplus"):
                    with self.subTest(mode=mode):
                        size = (metafile.width, metafile.height)
                        before = renderer.render(original, size, mode)
                        after = renderer.render(metafile, size, mode)
                        assert before is not None and after is not None
                        self.assertEqual((0, 255, 0), before.getpixel(sample))
                        self.assertEqual(before.getpixel(sample), after.getpixel(sample))
            finally:
                renderer.close()

    # Verifies FR-2026-10-28-05.
    def test_overlap_clips_render_in_both_windows_playback_paths(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request,
                    lambda text: TextReplacementItem("W" * 500 if text == "Old" else "i", 1.0),
                )

        for angle in (0, 90, 180, 270):
            with self.subTest(angle=angle), TemporaryDirectory() as temporary:
                source = _record_gdi_overlap_metafile(rotated=bool(angle), angle=angle or 90)
                result = analyse_emf(
                    source, source_language="en", target_language="en",
                    document_text_layout="preserve-basic-layout", trace_layout=True,
                ).apply(lambda text: text, _Provider())
                self.assertTrue(_emf_text_options(result.data)[0] & ETO_CLIPPED)
                self.assertTrue(result.emf_layout_trace[0]["overlap_protection_clipped"])
                clip = _emf_text_clips(result.data)[0]
                if not angle:
                    decisions = result.emf_layout_trace[0]["fit_decisions"]
                    assert isinstance(decisions, dict)
                    self.assertLessEqual(decisions["expansion_limits"]["right"], 70)
                modified = bytearray(result.data)
                offset = 0
                while offset < len(modified):
                    kind, size = struct.unpack_from("<II", modified, offset)
                    if kind == 84:
                        options = struct.unpack_from("<I", modified, offset + 52)[0]
                        struct.pack_into("<I", modified, offset + 52, options & ~ETO_CLIPPED)
                        break
                    offset += size
                path = Path(temporary) / "synthetic.emf"
                path.write_bytes(result.data)
                metafile = preview._checked_metafile(path, 192)
                device_width, device_height, millimetres_width, millimetres_height = struct.unpack_from("<iiii", source, 72)
                frame_left, frame_top, frame_right, frame_bottom = struct.unpack_from("<iiii", source, 24)
                scale_x = metafile.width * millimetres_width * 100 / (device_width * (frame_right - frame_left))
                scale_y = metafile.height * millimetres_height * 100 / (device_height * (frame_bottom - frame_top))
                unclipped = preview.Metafile(bytes(modified), metafile.width, metafile.height)
                renderer = preview.WindowsRenderer()
                try:
                    for mode in ("gdi", "gdiplus"):
                        with self.subTest(mode=mode):
                            size = (metafile.width, metafile.height)
                            protected = renderer.render(metafile, size, mode)
                            overflowing = renderer.render(unclipped, size, mode)
                            assert protected is not None and overflowing is not None
                            difference = ImageChops.difference(protected, overflowing)
                            bounds = difference.getbbox()
                            self.assertIsNotNone(bounds)
                            assert bounds is not None
                            if angle == 90:
                                self.assertGreaterEqual(bounds[1], (clip[2] + 10) * scale_y - 3, (clip, bounds))
                            elif angle == 180:
                                self.assertLessEqual(bounds[2], (95 - clip[2]) * scale_x + 3, (clip, bounds))
                            elif angle == 270:
                                self.assertLessEqual(bounds[3], (95 - clip[2]) * scale_y + 3, (clip, bounds))
                            else:
                                self.assertGreaterEqual(bounds[0], clip[2] * scale_x - 3, (clip, bounds))
                finally:
                    renderer.close()

    # Verifies FR-2026-10-28-03.
    def test_fitted_gdi_font_is_used_by_both_windows_playback_paths(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(request, lambda text: TextReplacementItem("Longer", 1.0))

        source = _record_metafile(5, gdi_text=True)
        result = replace_vector_text(
            source, ".emf", lambda text: text, "en",
            document_text_layout="preserve-basic-layout",
            replacement_provider=_Provider(), target_language="en",
        )
        first_new_handle = struct.unpack_from("<H", source, 56)[0]
        modified = bytearray(result.data)
        changed = 0
        offset = 0
        while offset < len(modified):
            kind, size = struct.unpack_from("<II", modified, offset)
            if kind == 82 and struct.unpack_from("<I", modified, offset + 8)[0] >= first_new_handle:
                height = struct.unpack_from("<i", modified, offset + 12)[0]
                struct.pack_into("<i", modified, offset + 12, -1 if height < 0 else 1)
                changed += 1
            offset += size
        self.assertGreater(changed, 0)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.emf"
            path.write_bytes(result.data)
            metafile = preview._checked_metafile(path, 150)
            renderer = preview.WindowsRenderer()
            try:
                altered = preview.Metafile(bytes(modified), metafile.width, metafile.height)
                for mode in ("gdi", "gdiplus"):
                    with self.subTest(mode=mode):
                        size = (metafile.width, metafile.height)
                        normal = renderer.render(metafile, size, mode)
                        smaller = renderer.render(altered, size, mode)
                        self.assertIsNotNone(normal)
                        self.assertIsNotNone(smaller)
                        assert normal is not None and smaller is not None
                        self.assertIsNotNone(ImageChops.difference(normal, smaller).getbbox())
            finally:
                renderer.close()

    # Verifies FR-2026-10-28-02.
    def test_native_playback_of_ordinary_dual_and_plus_only(self) -> None:
        renderer = preview.WindowsRenderer()
        try:
            with TemporaryDirectory() as temporary:
                root = Path(temporary)
                for kind in (3, 4, 5):
                    with self.subTest(kind=kind):
                        path = root / f"{kind}.emf"
                        path.write_bytes(_record_metafile(kind, blue_fallback=kind == 5))
                        metafile = preview._checked_metafile(path, 150)
                        size = (metafile.width, metafile.height)
                        self.assertEqual((150, 150), size)
                        plus_image = renderer.render(metafile, size, "gdiplus")
                        self.assertIsNotNone(plus_image)
                        assert plus_image is not None
                        self.assertNotEqual((255, 255, 255), plus_image.getpixel((20, 20)))
                        gdi_image = renderer.render(metafile, size, "gdi")
                        if kind == 4:
                            self.assertIsNone(gdi_image)
                        else:
                            self.assertIsNotNone(gdi_image)
                            assert gdi_image is not None
                            self.assertNotEqual((255, 255, 255), gdi_image.getpixel((20, 20)))
                            if kind == 5:
                                self.assertNotEqual(plus_image.getpixel((20, 20)), gdi_image.getpixel((20, 20)))
        finally:
            renderer.close()

    # Verifies FR-2026-10-28-02.
    def test_manual_file_pair_and_unpaired_preview(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.emf"
            output = root / "renamed.emf"
            source.write_bytes(_record_metafile(5))
            output.write_bytes(_record_metafile(5, blue_fallback=True, blue_plus=True))
            diagnostic = output.with_name(output.name + ".diagnostics.json")
            diagnostic.write_text(
                json.dumps({"source_absolute_path": str(source)}), encoding="utf-8"
            )
            self.assertEqual(0, preview.main([str(output), "--dpi", "100"]))
            for name in ("renamed.emf.diff.png", "renamed.emf.diff.gdi.png"):
                with Image.open(root / name) as image:
                    self.assertEqual((200, 100), image.size)
                    self.assertNotEqual(image.getpixel((20, 20)), image.getpixel((120, 20)))
            (root / "renamed.emf.diff.png").write_bytes(b"old preview")
            self.assertEqual(0, preview.main([str(output), "--dpi", "100"]))
            with Image.open(root / "renamed.emf.diff.png") as image:
                self.assertEqual("PNG", image.format)
            diagnostic.unlink()
            messages = StringIO()
            with redirect_stderr(messages):
                self.assertEqual(0, preview.main([str(output)]))
            self.assertIn("stale", messages.getvalue())
            for name in ("renamed.emf.preview.png", "renamed.emf.preview.gdi.png"):
                with Image.open(root / name) as image:
                    self.assertEqual((400, 400), image.size)

    # Verifies FR-2026-10-28-02.
    def test_external_resource_record_is_rejected_before_playback(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "unsafe.emf"
            data = bytearray(_record_metafile(3))
            profile = bytearray(608)
            struct.pack_into("<III", profile, 0, 122, len(profile), 1)
            name = "C:\\synthetic-profile.icc".encode("utf-16-le")
            profile[80 : 80 + len(name)] = name
            data[108:108] = profile
            struct.pack_into("<I", data, 48, len(data))
            record_count = struct.unpack_from("<I", data, 52)[0]
            struct.pack_into("<I", data, 52, record_count + 1)
            path.write_bytes(data)
            with patch.object(preview.WindowsRenderer, "render") as render:
                self.assertEqual(1, preview.main([str(path)]))
            render.assert_not_called()

    # Verifies FR-2026-10-28-02.
    def test_group_and_private_comments_are_accepted_and_rendered(self) -> None:
        begin = struct.pack("<I4iI", 2, 0, 0, 10, 10, 2) + "ab".encode("utf-16-le")
        cases = {
            "group": [_comment_record(b"GDIC", begin), _comment_record(b"GDIC", struct.pack("<I", 3))],
            "private": [_comment_record(b"SYNT", b"opaque data!")],
        }
        for name, comments in cases.items():
            with self.subTest(name=name), TemporaryDirectory() as temporary:
                path = Path(temporary) / f"{name}.emf"
                path.write_bytes(_with_comments(_record_metafile(3), comments))
                self.assertEqual(0, preview.main([str(path)]))
                self.assertTrue((Path(temporary) / f"{name}.emf.preview.png").exists())

    # Verifies FR-2026-10-28-02.
    def test_unsupported_public_and_malformed_comments_are_rejected(self) -> None:
        cases = {
            "multiformats": (
                _comment_record(b"GDIC", struct.pack("<I", 0x40000004) + b"SECRET-PAYLOAD"),
                "unsupported public comment type",
            ),
            "windows metafile": (
                _comment_record(b"GDIC", struct.pack("<I", 0x80000001) + b"SECRET-PAYLOAD"),
                "unsupported public comment type",
            ),
            "unrecognised": (
                _comment_record(b"GDIC", struct.pack("<I", 0x1234)), "unsupported public comment type",
            ),
            "inconsistent size": (
                struct.pack("<III", 70, 16, 64) + b"SYNT", "malformed comment",
            ),
            "description overruns": (
                _comment_record(b"GDIC", struct.pack("<I4iI", 2, 0, 0, 1, 1, 500)), "malformed comment",
            ),
        }
        for name, (comment, reason) in cases.items():
            with self.subTest(name=name), TemporaryDirectory() as temporary:
                path = Path(temporary) / "comment.emf"
                path.write_bytes(_with_comments(_record_metafile(3), [comment]))
                messages = StringIO()
                with patch.object(preview.WindowsRenderer, "render") as render, redirect_stderr(messages):
                    self.assertEqual(1, preview.main([str(path)]))
                render.assert_not_called()
                self.assertIn(reason, messages.getvalue())
                self.assertNotIn("SECRET", messages.getvalue())

    # Verifies FR-2026-10-28-02.
    def test_nested_emf_image_object_is_verified_recursively(self) -> None:
        ordinary = _record_metafile(3)
        profile = bytearray(608)
        struct.pack_into("<III", profile, 0, 122, len(profile), 1)
        unsafe = _with_comments(ordinary, [bytes(profile)])
        deep = ordinary
        for _ in range(preview.MAX_NESTED_METAFILES + 1):
            deep = _with_comments(ordinary, [_image_comment(3, deep)])
        cases = {
            "nested ordinary": (_image_comment(3, ordinary), True),
            "nested unsafe record": (_image_comment(3, unsafe), False),
            "nested WMF": (_image_comment(1, ordinary), False),
            "too deep": (_image_comment(3, deep), False),
        }
        for name, (comment, accepted) in cases.items():
            with self.subTest(name=name), TemporaryDirectory() as temporary:
                path = Path(temporary) / "nested.emf"
                path.write_bytes(_with_comments(ordinary, [comment]))
                if accepted:
                    self.assertEqual((150, 150), (lambda m: (m.width, m.height))(
                        preview._checked_metafile(path, 150)))
                else:
                    with self.assertRaises(preview.PreviewError):
                        preview._checked_metafile(path, 150)

    # Verifies FR-2026-10-28-02.
    def test_pen_with_custom_cap_is_verified(self) -> None:
        brush = struct.pack("<III", 0xDBC01001, 0, 0xFF000000)

        def pen(flags: int, optional: bytes) -> PlusRecord:
            data = struct.pack("<IIIIf", 0xDBC01001, 0, flags, 2, 1.0) + optional + brush
            return PlusRecord(0x4008, 0x0200, b"", data)

        preview._check_pen(pen(0x1000, struct.pack("<I", 8) + b"\0" * 8))
        preview._check_pen(pen(0x1800, struct.pack("<I", 4) + b"\0" * 4 + struct.pack("<I", 0)))
        for name, record in {
            "cap overruns data": pen(0x1000, struct.pack("<I", 500) + b"\0" * 8),
            "missing cap": pen(0x1000, b""),
            "unknown option": pen(0x2000, b""),
        }.items():
            with self.subTest(name=name), self.assertRaises(preview.PreviewError):
                preview._check_pen(record)

    # Verifies FR-2026-10-28-02.
    def test_native_pen_and_unverified_object(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "pen.emf"
            path.write_bytes(_record_metafile(5, draw_pen=True))
            self.assertEqual(0, preview.main([str(path)]))
            data = bytearray(path.read_bytes())
            brush = struct.pack("<HHIIII", 0x4008, 0x0100, 20, 8, 0xDBC01002, 2)
            comment = struct.pack("<III", 70, 16 + len(brush), 4 + len(brush)) + b"EMF+" + brush
            data[152:152] = comment
            struct.pack_into("<I", data, 48, len(data))
            record_count = struct.unpack_from("<I", data, 52)[0]
            struct.pack_into("<I", data, 52, record_count + 1)
            path.write_bytes(data)
            with patch.object(preview.WindowsRenderer, "render") as render:
                self.assertEqual(1, preview.main([str(path)]))
            render.assert_not_called()

    # Verifies FR-2026-10-28-02.
    def test_plus_only_and_renderer_failure_isolation(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            plus_only = root / "only.emf"
            dual = root / "dual.emf"
            plus_only.write_bytes(_record_metafile(4))
            dual.write_bytes(_record_metafile(5))
            self.assertEqual(0, preview.main([str(plus_only)]))
            self.assertTrue((root / "only.emf.preview.png").is_file())
            self.assertFalse((root / "only.emf.preview.gdi.png").exists())
            real_render = preview.WindowsRenderer.render

            def failing_plus(
                renderer: preview.WindowsRenderer, meta: preview.Metafile,
                size: tuple[int, int], mode: str,
            ) -> Image.Image | None:
                if mode == "gdiplus":
                    raise preview.PreviewError("Synthetic playback failure.")
                return real_render(renderer, meta, size, mode)

            with patch.object(preview.WindowsRenderer, "render", new=failing_plus):
                self.assertEqual(1, preview.main([str(root)]))
            self.assertTrue((root / "dual.emf.preview.gdi.png").is_file())

    # Verifies FR-2026-10-28-02.
    def test_revision_and_scenario_directory_discovery(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "scenario-a"
            second = root / "scenario-b" / "nested"
            first.mkdir()
            second.mkdir(parents=True)
            (first / "a.emf").write_bytes(_record_metafile(3))
            (second / "b.EMF").write_bytes(_record_metafile(3))
            self.assertEqual(0, preview.main([str(first)]))
            self.assertTrue((first / "a.emf.preview.png").is_file())
            self.assertFalse((second / "b.EMF.preview.png").exists())
            self.assertEqual(0, preview.main([str(root)]))
            self.assertTrue((second / "b.EMF.preview.png").is_file())

    # Verifies FR-2026-10-28-02.
    def test_progress_reports_each_file_and_playback_path(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("a.emf", "b.emf"):
                (root / name).write_bytes(_record_metafile(5))
            with patch.object(preview, "LiveProgress") as live:
                display = live.return_value.__enter__.return_value
                self.assertEqual(0, preview.main([str(root), "--dpi", "50"]))
            display.start_overall.assert_called_once_with(2, "file")
            self.assertEqual(2, display.start_current.call_count)
            self.assertEqual(2, display.advance_overall.call_count)
            self.assertEqual(4, display.advance_current.call_count)

    # Verifies FR-2026-10-28-02.
    def test_invalid_original_renders_processed_file_only(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.emf"
            output = root / "output.emf"
            source.write_bytes(b"not an EMF")
            output.write_bytes(_record_metafile(5))
            output.with_name(output.name + ".diagnostics.json").write_text(
                json.dumps({"source_absolute_path": str(source)}), encoding="utf-8"
            )
            self.assertEqual(0, preview.main([str(output)]))
            self.assertTrue((root / "output.emf.preview.png").is_file())
            self.assertFalse((root / "output.emf.diff.png").exists())

    # Verifies FR-2026-10-28-02.
    def test_comparison_uses_same_physical_scale_for_both_halves(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.emf"
            output = root / "output.emf"
            source.write_bytes(_record_metafile(5))
            smaller = bytearray(_record_metafile(5))
            struct.pack_into("<iiii", smaller, 24, 0, 0, 1270, 1270)
            output.write_bytes(smaller)
            output.with_name(output.name + ".diagnostics.json").write_text(
                json.dumps({"source_absolute_path": str(source)}), encoding="utf-8"
            )
            self.assertEqual(0, preview.main([str(output), "--dpi", "100"]))
            for name in ("output.emf.diff.png", "output.emf.diff.gdi.png"):
                with Image.open(root / name) as image:
                    self.assertEqual((200, 100), image.size)
                    self.assertNotEqual((255, 255, 255), image.getpixel((20, 20)))
                    self.assertNotEqual((255, 255, 255), image.getpixel((120, 20)))
                    self.assertEqual((255, 255, 255), image.getpixel((175, 20)))

    # Verifies FR-2026-10-28-02.
    def test_invalid_dpi_and_oversized_canvas_are_reported(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "image.emf"
            path.write_bytes(_record_metafile(3))
            for dpi in ("0", "nan", "inf"):
                with self.subTest(dpi=dpi), self.assertRaises(SystemExit):
                    preview.main([str(path), "--dpi", dpi])
            self.assertEqual(1, preview.main([str(path), "--dpi", "1000000"]))
            self.assertFalse(path.with_name("image.emf.preview.png").exists())

    # Verifies FR-2026-10-28-02.
    def test_non_windows_fails_explicitly(self) -> None:
        with patch("sys.platform", "linux"), self.assertRaises(SystemExit) as result:
            preview.main(["example.emf"])
        self.assertNotEqual(0, result.exception.code)


if __name__ == "__main__":
    unittest.main()

