"""Shared result and DIB helpers for vector handlers."""
from __future__ import annotations
from dataclasses import dataclass
from io import BytesIO
import struct
from PIL import Image

@dataclass(frozen=True, slots=True)
class VectorReplacementResult:
    data: bytes
    replaced_text_items: int
    has_editable_text: bool
    replaced_image_regions: int = 0
    has_embedded_bitmaps: bool = False

def bitmap_file_from_dib(info: bytes, bits: bytes) -> bytes:
    offset = 14 + len(info)
    return struct.pack("<2sIHHI", b"BM", offset + len(bits), 0, 0, offset) + info + bits

def dib_from_image(image: Image.Image) -> tuple[bytes, bytes]:
    output = BytesIO()
    image.convert("RGB").save(output, format="BMP")
    data = output.getvalue()
    offset = struct.unpack_from("<I", data, 10)[0]
    return data[14:offset], data[offset:]
