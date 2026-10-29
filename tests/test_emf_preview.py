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
from pipeline.vector_text.emfplus import parse_driver_string
from scripts import emf_preview as preview
from test_vector_emfplus import _font_objects, _plus_records
from test_vector_text_replacer import _emf_text_clips, _emf_text_options


class RectF(ctypes.Structure):
    _fields_ = [("x", ctypes.c_float), ("y", ctypes.c_float),
                ("width", ctypes.c_float), ("height", ctypes.c_float)]


class PointF(ctypes.Structure):
    _fields_ = [("x", ctypes.c_float), ("y", ctypes.c_float)]


def _record_metafile(
    kind: int, *, blue_fallback: bool = False, blue_plus: bool = False, draw_pen: bool = False,
    gdi_text: bool = False, plus_text: bool = False, plus_draw_text: bool = False,
    simple_plus_format: bool = False, mixed_plus_order: str = "", plus_clip: bool = False,
    vertical_separator: bool = False,
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
    plus.GdipCreateFontFamilyFromName.argtypes = [
        ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    ]
    plus.GdipCreateFont.argtypes = [
        ctypes.c_void_p, ctypes.c_float, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p),
    ]
    plus.GdipGetCellAscent.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_ushort),
    ]
    plus.GdipGetEmHeight.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_ushort),
    ]
    plus.GdipDrawDriverString.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(PointF), ctypes.c_int, ctypes.c_void_p,
    ]
    plus.GdipSetClipRect.argtypes = [
        ctypes.c_void_p, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_int,
    ]
    plus.GdipCreateStringFormat.argtypes = [
        ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p),
    ]
    plus.GdipDrawString.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p,
        ctypes.POINTER(RectF), ctypes.c_void_p, ctypes.c_void_p,
    ]
    plus.GdipDeleteStringFormat.argtypes = [ctypes.c_void_p]
    plus.GdipDeleteFont.argtypes = [ctypes.c_void_p]
    plus.GdipDeleteFontFamily.argtypes = [ctypes.c_void_p]
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
        if not plus_text and not plus_draw_text and not mixed_plus_order:
            check(plus.GdipFillRectangleI(graphics, brush, 0, 0, 80, 80))
        if plus_text or plus_draw_text or mixed_plus_order:
            if plus_clip:
                check(plus.GdipSetClipRect(graphics, 0, 0, 50, 50, 0))
            family = ctypes.c_void_p()
            font = ctypes.c_void_p()
            blue_brush = ctypes.c_void_p()
            check(plus.GdipCreateFontFamilyFromName("Arial", None, ctypes.byref(family)))
            check(plus.GdipCreateFont(family, 20, 0, 2, ctypes.byref(font)))
            check(plus.GdipCreateSolidFill(0xFF0000FF, ctypes.byref(blue_brush)))
            if plus_draw_text or mixed_plus_order:
                string_format = ctypes.c_void_p()
                check(plus.GdipCreateStringFormat(0, 0, ctypes.byref(string_format)))
                first_rect = RectF(10, 10, 20, 30)
                second_rect = RectF(30, 10, 20, 30)
                if mixed_plus_order:
                    ascent, em_height = ctypes.c_ushort(), ctypes.c_ushort()
                    check(plus.GdipGetCellAscent(family, 0, ctypes.byref(ascent)))
                    check(plus.GdipGetEmHeight(family, 0, ctypes.byref(em_height)))
                    baseline = 10 + 20 * ascent.value / em_height.value
                    if mixed_plus_order == "draw-first":
                        check(plus.GdipDrawString(graphics, "A", 1, font, ctypes.byref(first_rect), string_format, blue_brush))
                        point = PointF(30, baseline)
                        check(plus.GdipDrawDriverString(graphics, "B", 1, font, brush, ctypes.byref(point), 1, None))
                    else:
                        point = PointF(10, baseline)
                        check(plus.GdipDrawDriverString(graphics, "A", 1, font, blue_brush, ctypes.byref(point), 1, None))
                        second_rect.x = 20
                        check(plus.GdipDrawString(graphics, "B", 1, font, ctypes.byref(second_rect), string_format, brush))
                else:
                    check(plus.GdipDrawString(graphics, "A", 1, font, ctypes.byref(first_rect), string_format, blue_brush))
                    check(plus.GdipDrawString(graphics, "B", 1, font, ctypes.byref(second_rect), string_format, brush))
                check(plus.GdipDeleteStringFormat(string_format))
            else:
                first = PointF(10, 30)
                second = PointF(20, 30)
                check(plus.GdipDrawDriverString(graphics, "A", 1, font, blue_brush, ctypes.byref(first), 1, None))
                check(plus.GdipDrawDriverString(graphics, "B", 1, font, brush, ctypes.byref(second), 1, None))
            check(plus.GdipDeleteBrush(blue_brush))
            check(plus.GdipDeleteFont(font))
            check(plus.GdipDeleteFontFamily(family))
        if draw_pen or vertical_separator:
            pen = ctypes.c_void_p()
            check(plus.GdipCreatePen1(0xFF000000, 2.0, 2, ctypes.byref(pen)))
            if vertical_separator:
                check(plus.GdipDrawLineI(graphics, pen, 18, 0, 18, 50))
            else:
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
        if blue_fallback or blue_plus or simple_plus_format:
            offset = 0
            while offset < len(data):
                record_type, size = struct.unpack_from("<II", data, offset)
                if blue_fallback and record_type == 39:
                    struct.pack_into("<I", data, offset + 16, 0x00FF0000)
                if record_type == 70 and data[offset + 12 : offset + 16] == b"EMF+":
                    position = offset + 16
                    while position < offset + size:
                        plus_type, flags, plus_size, _ = struct.unpack_from("<HHII", data, position)
                        if blue_plus and plus_type == 0x400A and flags & 0x8000:
                            struct.pack_into("<I", data, position + 12, 0xFF0000FF)
                        if simple_plus_format and plus_type == 0x4008 and (flags >> 8) & 0x7F == 7:
                            struct.pack_into("<fffI", data, position + 12 + 36, 0.0, 0.0, 1.0, 0)
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


def _record_gdi_overlap_metafile(
    *, rotated: bool, opaque: bool = False, angle: int = 90, grouped_colours: bool = False,
    meta_clip: bool = False, temporary_paint_state: bool = False, translated_group: bool = False,
) -> bytes:
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
    gdi.IntersectClipRect.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    gdi.SetMetaRgn.argtypes = [ctypes.c_void_p]
    gdi.SelectClipRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
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
    if meta_clip:
        if not gdi.IntersectClipRect(dc, 0, 0, 48, 50) or not gdi.SetMetaRgn(dc) or not gdi.SelectClipRgn(dc, None):
            raise RuntimeError("Could not set a synthetic GDI metaregion.")
    if grouped_colours:
        if translated_group:
            matrix = _Transform(1, 0, 0, 1, 12, 0)
            if not gdi.SetGraphicsMode(dc, 2) or not gdi.SetWorldTransform(dc, ctypes.byref(matrix)):
                raise RuntimeError("Could not transform synthetic GDI text.")
        gdi.SetTextColor(dc, 0x00FF0000)
        if not gdi.TextOutW(dc, 10, 15, "A", 1):
            raise RuntimeError("Could not draw synthetic first colour span.")
        if temporary_paint_state:
            if not gdi.SaveDC(dc) or not gdi.SetBkMode(dc, 2) or not gdi.RestoreDC(dc, -1):
                raise RuntimeError("Could not restore synthetic GDI paint state.")
        if translated_group:
            matrix = _Transform(1, 0, 0, 1, 22, 0)
            if not gdi.SetWorldTransform(dc, ctypes.byref(matrix)):
                raise RuntimeError("Could not reposition synthetic GDI text.")
        neighbour = (10 if translated_group else 20, 15)
    elif rotated:
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
    if not grouped_colours:
        gdi.MoveToEx(dc, -100, -100, None)
    gdi.SetTextColor(dc, 0x000000FF)
    if not gdi.TextOutW(
        dc, *neighbour, "B" if grouped_colours else "Value", 1 if grouped_colours else 5
    ):
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


def _record_gdi_mixed_size_metafile() -> bytes:
    """Record a red 20-pixel span followed by a blue 15-pixel span on one baseline."""
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
    gdi.TextOutW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int]
    gdi.SetBkMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
    gdi.SetTextAlign.argtypes = [ctypes.c_void_p, wintypes.UINT]
    gdi.SetTextColor.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    gdi.GetEnhMetaFileBits.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p]
    gdi.DeleteEnhMetaFile.argtypes = [ctypes.c_void_p]
    gdi.DeleteObject.argtypes = [ctypes.c_void_p]
    screen = user.GetDC(None)
    frame = wintypes.RECT(0, 0, 2540, 2540)
    dc = gdi.CreateEnhMetaFileW(screen, None, ctypes.byref(frame), None)
    large = gdi.CreateFontW(-20, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, "Arial")
    small = gdi.CreateFontW(-15, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, "Arial")
    if not dc or not large or not small:
        raise RuntimeError("Could not create synthetic GDI metafile.")
    old_font = gdi.SelectObject(dc, large)
    gdi.SetBkMode(dc, 1)
    gdi.SetTextAlign(dc, 24)
    gdi.SetTextColor(dc, 0x000000FF)
    if not gdi.TextOutW(dc, 5, 40, "A", 1):
        raise RuntimeError("Could not draw synthetic large span.")
    gdi.SelectObject(dc, small)
    gdi.SetTextColor(dc, 0x00FF0000)
    if not gdi.TextOutW(dc, 22, 40, "B", 1):
        raise RuntimeError("Could not draw synthetic small span.")
    gdi.SelectObject(dc, old_font)
    handle = gdi.CloseEnhMetaFile(dc)
    gdi.DeleteObject(large)
    gdi.DeleteObject(small)
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
    # Verifies FR-2026-10-29-01 for a natively drawn column separator.
    def test_native_emfplus_separator_splits_text_lines(self) -> None:
        source = _record_metafile(4, plus_text=True, vertical_separator=True)
        document = analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout",
        )
        self.assertEqual(("A", "B"), document.texts())
        self.assertTrue(any(kind == 0x400D for kind, _, _ in _plus_records(source)))

    # Verifies FR-2026-10-29-01 and -02 with a natively recorded rectangular clip.
    def test_grouped_emfplus_line_retains_native_clip(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request, lambda text: TextReplacementItem({"A": "Blue", "B": "Red"}[text], 1.0)
                )

        source = _record_metafile(4, plus_text=True, plus_clip=True)
        document = analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout",
        )
        self.assertEqual(("A", "B", "A", "B"), document.texts())
        result = document.apply(lambda text: text, _Provider())
        self.assertEqual(
            [record for record in _plus_records(source) if record[0] == 0x4032],
            [record for record in _plus_records(result.data) if record[0] == 0x4032],
        )
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.emf"
            path.write_bytes(result.data)
            metafile = preview._checked_metafile(path, 192)
            renderer = preview.WindowsRenderer()
            try:
                image = renderer.render(metafile, (metafile.width, metafile.height), "gdiplus")
                assert image is not None
                raw = image.convert("RGB").tobytes()
                pixels = list(zip(raw[0::3], raw[1::3], raw[2::3], strict=True))
                self.assertTrue(any(r > g + 40 and r > b + 40 for r, g, b in pixels))
                self.assertTrue(any(b > g + 40 and b > r + 40 for r, g, b in pixels))
                self.assertFalse(any(
                    (r > g + 40 and r > b + 40) or (b > g + 40 and b > r + 40)
                    for i, (r, g, b) in enumerate(pixels) if i % image.width > 68
                ))
            finally:
                renderer.close()

    # Verifies FR-2026-10-29-01 and -02 for mixed natively recorded EMF+ text.
    def test_mixed_emfplus_records_render_as_one_line(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request, lambda text: TextReplacementItem({"A": "Blue", "B": "Red"}[text], 1.0)
                )

        for order in ("draw-first", "driver-first"):
            with self.subTest(order=order):
                source = _record_metafile(4, mixed_plus_order=order)
                document = analyse_emf(
                    source, source_language="en", target_language="en",
                    document_text_layout="preserve-basic-layout",
                )
                self.assertEqual(("A", "B", "A", "B"), document.texts())
                result = document.apply(lambda text: text, _Provider())
                records = _plus_records(result.data)
                draws = [(flags, body) for kind, flags, body in records if kind == 0x401C]
                self.assertEqual(2, len(draws))
                self.assertEqual(draws[0][0] & 0xFF, draws[1][0] & 0xFF)
                self.assertFalse(any(kind == 0x4036 for kind, _, _ in records))
                with TemporaryDirectory() as temporary:
                    original_path = Path(temporary) / "original.emf"
                    original_path.write_bytes(source)
                    path = Path(temporary) / "synthetic.emf"
                    path.write_bytes(result.data)
                    original = preview._checked_metafile(original_path, 192)
                    metafile = preview._checked_metafile(path, 192)
                    renderer = preview.WindowsRenderer()
                    try:
                        before = renderer.render(original, (original.width, original.height), "gdiplus")
                        image = renderer.render(metafile, (metafile.width, metafile.height), "gdiplus")
                        assert before is not None and image is not None
                        raw = image.convert("RGB").tobytes()
                        pixels = list(zip(raw[0::3], raw[1::3], raw[2::3], strict=True))
                        blue = [(i % image.width, i // image.width) for i, (r, g, b) in enumerate(pixels)
                                if b > g + 40 and b > r + 40]
                        red = [(i % image.width, i // image.width) for i, (r, g, b) in enumerate(pixels)
                               if r > g + 40 and r > b + 40]
                        self.assertTrue(blue)
                        self.assertTrue(red)
                        self.assertLess(max(x for x, _ in blue), min(x for x, _ in red))
                        self.assertLessEqual(abs(max(y for _, y in blue) - max(y for _, y in red)), 2)
                        original_raw = before.convert("RGB").tobytes()
                        original_pixels = zip(original_raw[0::3], original_raw[1::3], original_raw[2::3], strict=True)
                        source_bottom = max(
                            i // before.width for i, (r, g, b) in enumerate(original_pixels)
                            if b > g + 40 and b > r + 40
                        )
                        self.assertLessEqual(abs(source_bottom - max(y for _, y in blue)), 2)
                    finally:
                        renderer.close()

    # Verifies FR-2026-10-29-01 and FR-2026-10-22-11 in native overflow playback.
    def test_grouped_emfplus_minimum_size_overflow_respects_active_clip(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request, lambda text: TextReplacementItem({"A": "M" * 60, "B": "M" * 8}[text], 1.0)
                )

        for clipped in (False, True):
            with self.subTest(clipped=clipped):
                source = _record_metafile(4, plus_draw_text=True, plus_clip=clipped)
                document = analyse_emf(
                    source, source_language="en", target_language="en",
                    document_text_layout="preserve-basic-layout",
                )
                result = document.apply(lambda text: text, _Provider())
                draws = [(flags, body) for kind, flags, body in _plus_records(result.data) if kind == 0x401C]
                self.assertEqual(2, len(draws))
                self.assertAlmostEqual(1.0, _font_objects(result.data)[draws[0][0] & 0xFF][0], places=5)
                self.assertFalse(any(item["reason_code"] == "emfplus_group_fit_unsuccessful"
                                     for item in result.diagnostics))
                with TemporaryDirectory() as temporary:
                    path = Path(temporary) / "synthetic.emf"
                    path.write_bytes(result.data)
                    metafile = preview._checked_metafile(path, 192)
                    renderer = preview.WindowsRenderer()
                    try:
                        image = renderer.render(metafile, (384, 384), "gdiplus")
                        assert image is not None
                        raw = image.convert("RGB").tobytes()
                        pixels = list(zip(raw[0::3], raw[1::3], raw[2::3], strict=True))
                        blue = [i % image.width for i, (r, g, b) in enumerate(pixels)
                                if b > g + 40 and b > r + 40]
                        red = [i % image.width for i, (r, g, b) in enumerate(pixels)
                               if r > g + 40 and r > b + 40]
                        self.assertTrue(blue)
                        if clipped:
                            self.assertFalse(red)
                        else:
                            self.assertTrue(red)
                            self.assertLess(max(blue), min(red))
                            self.assertGreater(struct.unpack_from("<f", draws[1][1], 12)[0], 50.0)
                    finally:
                        renderer.close()

    # Verifies FR-2026-10-29-02 with natively recorded DrawString records.
    def test_grouped_emfplus_draw_string_colours_in_native_playback(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request, lambda text: TextReplacementItem({"A": "Blue", "B": "Red"}[text], 1.0)
                )

        source = _record_metafile(4, plus_draw_text=True, simple_plus_format=True)
        document = analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout",
        )
        self.assertEqual(("A", "B", "A", "B"), document.texts())
        result = document.apply(lambda text: text, _Provider())
        draws = [(flags, body) for kind, flags, body in _plus_records(result.data) if kind == 0x401C]
        self.assertEqual(2, len(draws))
        self.assertEqual(draws[0][0] & 0xFF, draws[1][0] & 0xFF)
        fitted_size = _font_objects(result.data)[draws[0][0] & 0xFF][0]
        self.assertGreater(fitted_size, 6.0)
        self.assertLessEqual(fitted_size, 20.0)
        self.assertLess(struct.unpack_from("<f", draws[0][1], 12)[0], struct.unpack_from("<f", draws[1][1], 12)[0])
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.emf"
            path.write_bytes(result.data)
            metafile = preview._checked_metafile(path, 192)
            renderer = preview.WindowsRenderer()
            try:
                image = renderer.render(metafile, (metafile.width, metafile.height), "gdiplus")
                assert image is not None
                raw = image.convert("RGB").tobytes()
                pixels = list(zip(raw[0::3], raw[1::3], raw[2::3], strict=True))
                self.assertTrue(any(r > g + 40 and r > b + 40 for r, g, b in pixels))
                self.assertTrue(any(b > g + 40 and b > r + 40 for r, g, b in pixels))
                blue = [(i % image.width, i // image.width) for i, (r, g, b) in enumerate(pixels)
                        if b > g + 40 and b > r + 40]
                red = [(i % image.width, i // image.width) for i, (r, g, b) in enumerate(pixels)
                       if r > g + 40 and r > b + 40]
                self.assertLess(max(x for x, _ in blue), min(x for x, _ in red))
                self.assertLessEqual(abs(max(y for _, y in blue) - max(y for _, y in red)), 2)
            finally:
                renderer.close()

    # Verifies FR-2026-10-29-01 and -02 with the native default margins and tracking.
    def test_native_default_draw_string_format_is_grouped(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request, lambda text: TextReplacementItem({"A": "Blue", "B": "Red"}[text], 1.0)
                )

        source = _record_metafile(4, plus_draw_text=True)
        document = analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout",
        )
        self.assertEqual(("A", "B", "A", "B"), document.texts())
        result = document.apply(lambda text: text, _Provider())
        draws = [(flags, body) for kind, flags, body in _plus_records(result.data) if kind == 0x401C]
        self.assertEqual(2, len(draws))
        self.assertEqual(draws[0][0] & 0xFF, draws[1][0] & 0xFF)
        fitted_size = _font_objects(result.data)[draws[0][0] & 0xFF][0]
        self.assertGreater(fitted_size, 6.0)
        self.assertLessEqual(fitted_size, 20.0)
        with TemporaryDirectory() as temporary:
            original_path = Path(temporary) / "original.emf"
            original_path.write_bytes(source)
            path = Path(temporary) / "synthetic.emf"
            path.write_bytes(result.data)
            original = preview._checked_metafile(original_path, 192)
            metafile = preview._checked_metafile(path, 192)
            renderer = preview.WindowsRenderer()
            try:
                before = renderer.render(original, (original.width, original.height), "gdiplus")
                image = renderer.render(metafile, (metafile.width, metafile.height), "gdiplus")
                assert before is not None and image is not None
                raw = image.convert("RGB").tobytes()
                pixels = list(zip(raw[0::3], raw[1::3], raw[2::3], strict=True))
                self.assertTrue(any(r > g + 40 and r > b + 40 for r, g, b in pixels))
                self.assertTrue(any(b > g + 40 and b > r + 40 for r, g, b in pixels))
                blue = [(i % image.width, i // image.width) for i, (r, g, b) in enumerate(pixels)
                        if b > g + 40 and b > r + 40]
                red = [(i % image.width, i // image.width) for i, (r, g, b) in enumerate(pixels)
                       if r > g + 40 and r > b + 40]
                self.assertLess(max(x for x, _ in blue), min(x for x, _ in red))
                self.assertLessEqual(abs(max(y for _, y in blue) - max(y for _, y in red)), 2)
                original_raw = before.convert("RGB").tobytes()
                original_pixels = zip(original_raw[0::3], original_raw[1::3], original_raw[2::3], strict=True)
                source_blue_bottom = max(
                    i // before.width for i, (r, g, b) in enumerate(original_pixels)
                    if b > g + 40 and b > r + 40
                )
                self.assertLessEqual(abs(source_blue_bottom - max(y for _, y in blue)), 2)
            finally:
                renderer.close()

    # Verifies FR-2026-10-29-02 using a natively recorded EMF+ driver string.
    def test_grouped_emfplus_colours_are_visible_in_native_playback(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request, lambda text: TextReplacementItem({"A": "Blue", "B": "Red"}[text], 1.0)
                )

        source = _record_metafile(4, plus_text=True)
        source_driver = next(body for kind, _flags, body in _plus_records(source) if kind == 0x4036)
        parsed_driver = parse_driver_string(source_driver)
        assert parsed_driver is not None
        self.assertEqual(((10.0, 30.0),), parsed_driver.positions)
        document = analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout",
        )
        self.assertEqual(("A", "B", "A", "B"), document.texts())
        result = document.apply(lambda text: text, _Provider())
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.emf"
            path.write_bytes(result.data)
            metafile = preview._checked_metafile(path, 192)
            renderer = preview.WindowsRenderer()
            try:
                image = renderer.render(metafile, (metafile.width, metafile.height), "gdiplus")
                assert image is not None
                raw = image.convert("RGB").tobytes()
                pixels = list(zip(raw[0::3], raw[1::3], raw[2::3], strict=True))
                self.assertTrue(any(r > g + 40 and r > b + 40 for r, g, b in pixels))
                self.assertTrue(any(b > g + 40 and b > r + 40 for r, g, b in pixels))
            finally:
                renderer.close()

    # Verifies FR-2026-10-29-02 using normal Windows GDI and GDI+ playback.
    def test_grouped_gdi_colours_are_visible_in_both_playback_paths(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request, lambda text: TextReplacementItem({"A": "Blue", "B": "Red"}[text], 1.0)
                )

        source = _record_gdi_overlap_metafile(rotated=False, grouped_colours=True)
        document = analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        )
        self.assertIn("A", document.texts())
        self.assertIn("B", document.texts())
        result = document.apply(lambda text: text, _Provider())
        self.assertEqual("group_anchor", result.emf_layout_trace[0]["outcome"])
        self.assertEqual("suppressed_group_member", result.emf_layout_trace[1]["outcome"])
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.emf"
            path.write_bytes(result.data)
            metafile = preview._checked_metafile(path, 192)
            renderer = preview.WindowsRenderer()
            try:
                for mode in ("gdi", "gdiplus"):
                    with self.subTest(mode=mode):
                        image = renderer.render(metafile, (metafile.width, metafile.height), mode)
                        assert image is not None
                        raw = image.convert("RGB").tobytes()
                        pixels = list(zip(raw[0::3], raw[1::3], raw[2::3], strict=True))
                        self.assertTrue(any(r > g + 40 and r > b + 40 for r, g, b in pixels))
                        self.assertTrue(any(b > g + 40 and b > r + 40 for r, g, b in pixels))
            finally:
                renderer.close()

    # Verifies FR-2026-09-05-02 and FR-2026-10-29-02 through native playback.
    def test_grouped_gdi_restored_paint_state_in_native_playback(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request, lambda text: TextReplacementItem({"A": "Blue", "B": "Red"}[text], 1.0)
                )

        source = _record_gdi_overlap_metafile(
            rotated=False, grouped_colours=True, temporary_paint_state=True,
        )
        result = analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(lambda text: text, _Provider())
        first, second = result.emf_layout_trace
        self.assertEqual("group_anchor", first["outcome"])
        self.assertEqual("suppressed_group_member", second["outcome"])
        grouping = second["grouping"]
        assert isinstance(grouping, dict)
        self.assertTrue(grouping["text_paint_state_matches_previous"])
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.emf"
            path.write_bytes(result.data)
            metafile = preview._checked_metafile(path, 192)
            renderer = preview.WindowsRenderer()
            try:
                for mode in ("gdi", "gdiplus"):
                    with self.subTest(mode=mode):
                        image = renderer.render(metafile, (metafile.width, metafile.height), mode)
                        assert image is not None
                        raw = image.convert("RGB").tobytes()
                        pixels = list(zip(raw[0::3], raw[1::3], raw[2::3], strict=True))
                        self.assertTrue(any(r > g + 40 and r > b + 40 for r, g, b in pixels))
                        self.assertTrue(any(b > g + 40 and b > r + 40 for r, g, b in pixels))
            finally:
                renderer.close()

    # Verifies FR-2026-09-05-01 and FR-2026-10-29-02 through native playback.
    def test_grouped_translated_gdi_text_in_native_playback(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(
                    request, lambda text: TextReplacementItem(
                        "Blue" if text.strip() == "A" else "Red", 1.0,
                    ),
                )

        source = _record_gdi_overlap_metafile(
            rotated=False, grouped_colours=True, translated_group=True,
        )
        result = analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(lambda text: text, _Provider())
        first, second = result.emf_layout_trace
        self.assertEqual("group_anchor", first["outcome"])
        self.assertEqual("suppressed_group_member", second["outcome"])
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.emf"
            path.write_bytes(result.data)
            metafile = preview._checked_metafile(path, 192)
            renderer = preview.WindowsRenderer()
            try:
                for mode in ("gdi", "gdiplus"):
                    with self.subTest(mode=mode):
                        image = renderer.render(metafile, (metafile.width, metafile.height), mode)
                        assert image is not None
                        raw = image.convert("RGB").tobytes()
                        pixels = list(zip(raw[0::3], raw[1::3], raw[2::3], strict=True))
                        self.assertTrue(any(r > g + 40 and r > b + 40 for r, g, b in pixels))
                        self.assertTrue(any(b > g + 40 and b > r + 40 for r, g, b in pixels))
            finally:
                renderer.close()

    # Verifies FR-2026-10-29-03 through native playback: mixed-size spans stay on one
    # baseline, with the smaller span still visibly smaller.
    def test_mixed_size_gdi_spans_in_native_playback(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(request, lambda text: TextReplacementItem("HH", 1.0))

        source = _record_gdi_mixed_size_metafile()
        result = analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        ).apply(lambda text: text, _Provider())
        first, second = result.emf_layout_trace
        self.assertEqual("group_anchor", first["outcome"])
        self.assertEqual("suppressed_group_member", second["outcome"])
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.emf"
            path.write_bytes(result.data)
            metafile = preview._checked_metafile(path, 192)
            renderer = preview.WindowsRenderer()
            try:
                for mode in ("gdi", "gdiplus"):
                    with self.subTest(mode=mode):
                        image = renderer.render(metafile, (metafile.width, metafile.height), mode)
                        assert image is not None
                        raw = image.convert("RGB").tobytes()
                        pixels = list(zip(raw[0::3], raw[1::3], raw[2::3], strict=True))
                        red = [i // image.width for i, (r, g, b) in enumerate(pixels)
                               if r > g + 40 and r > b + 40]
                        blue = [i // image.width for i, (r, g, b) in enumerate(pixels)
                                if b > g + 40 and b > r + 40]
                        self.assertTrue(red)
                        self.assertTrue(blue)
                        self.assertLess(max(blue) - min(blue), max(red) - min(red))
                        self.assertLessEqual(abs(max(blue) - max(red)), 2)
            finally:
                renderer.close()

    # Verifies FR-2026-09-05-02 and FR-2026-10-28-05 with a native GDI metaregion.
    def test_grouped_gdi_metaregion_is_preserved_in_native_playback(self) -> None:
        class _Provider:
            def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
                return replace_each(request, lambda text: TextReplacementItem({"A": "Blue", "B": "Red"}[text], 1.0))

        source = _record_gdi_overlap_metafile(rotated=False, grouped_colours=True, meta_clip=True)
        document = analyse_emf(
            source, source_language="en", target_language="en",
            document_text_layout="preserve-basic-layout", trace_layout=True,
        )
        result = document.apply(lambda text: text, _Provider())
        first, second = result.emf_layout_trace
        self.assertEqual("group_anchor", first["outcome"])
        self.assertEqual("suppressed_group_member", second["outcome"])
        grouping = first["grouping"]
        assert isinstance(grouping, dict)
        self.assertTrue(grouping["meta_clip_known"])
        self.assertEqual([0, 0, 48, 50], grouping["meta_clip_bounds"])
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.emf"
            path.write_bytes(result.data)
            metafile = preview._checked_metafile(path, 192)
            device_width, _, millimetres_width, _ = struct.unpack_from("<iiii", source, 72)
            frame_left, _, frame_right, _ = struct.unpack_from("<iiii", source, 24)
            clip_x = metafile.width * millimetres_width * 100 * 48 / (device_width * (frame_right - frame_left))
            renderer = preview.WindowsRenderer()
            try:
                for mode in ("gdi", "gdiplus"):
                    with self.subTest(mode=mode):
                        image = renderer.render(metafile, (metafile.width, metafile.height), mode)
                        assert image is not None
                        raw = image.convert("RGB").tobytes()
                        pixels = list(zip(raw[0::3], raw[1::3], raw[2::3], strict=True))
                        blue = [i % image.width for i, (r, g, b) in enumerate(pixels)
                                if b > g + 40 and b > r + 40]
                        red = [i % image.width for i, (r, g, b) in enumerate(pixels)
                               if r > g + 40 and r > b + 40]
                        self.assertTrue(blue)
                        self.assertTrue(red)
                        self.assertLessEqual(max(blue + red), clip_x + 1)
            finally:
                renderer.close()

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

    # Verifies FR-2026-10-28-05: opaque text keeps its background and gains no overlap clip.
    def test_opaque_background_is_preserved_in_both_playback_paths(self) -> None:
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
        self.assertFalse(options[0] & ETO_CLIPPED)
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
