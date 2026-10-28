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

from PIL import Image

from pipeline.vector_text.emfplus import PlusRecord
from scripts import emf_preview as preview


class RectF(ctypes.Structure):
    _fields_ = [("x", ctypes.c_float), ("y", ctypes.c_float),
                ("width", ctypes.c_float), ("height", ctypes.c_float)]


def _record_metafile(
    kind: int, *, blue_fallback: bool = False, blue_plus: bool = False, draw_pen: bool = False
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

