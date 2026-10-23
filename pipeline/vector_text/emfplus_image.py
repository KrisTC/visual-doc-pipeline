"""Find, decode and rewrite the Image objects of an EMF+ stream.

An EMF+ ``EmfPlusObject`` record of type Image holds a bitmap or a nested metafile. GDI+
splits an object larger than one record over consecutive object records: each chunk
carries the continuation flag and starts with the 4-byte total size of the whole object.
This module reassembles those chunks, reads the bitmap or metafile inside, and writes a
replacement object back with the same chunking. Deciding what to translate lives in
``emf.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import struct

from PIL import Image

from pipeline.vector_text.emfplus import (
    EMFPLUS_OBJECT,
    PlusRecord,
    comment_record,
    plus_record,
)

IMAGE_OBJECT_TYPE = 5
# The most data one EmfPlusObject record carries, including a chunk's 4-byte total size.
MAX_RECORD_DATA = 65_008

_CONTINUED = 0x8000
_VERSION_MASK = 0xFFFFF000
_VERSION = 0xDBC01000
_BITMAP_TYPE = 1
_METAFILE_TYPE = 2
_BITMAP_HEADER_SIZE = 28
_METAFILE_HEADER_SIZE = 16
_COMPRESSED = 1
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"
# PixelFormat -> (PIL mode, PIL raw mode, bytes per pixel).
_RAW_PIXEL_FORMATS = {
    0x00021808: ("RGB", "BGR", 3),
    0x00022009: ("RGB", "BGRX", 4),
    0x0026200A: ("RGBA", "BGRA", 4),
}
# MetafileType -> extension of the handler for the nested format.
_METAFILE_EXTENSIONS = {1: ".wmf", 2: ".wmf", 3: ".emf", 4: ".emf", 5: ".emf"}

Location = tuple[int, int]


@dataclass(slots=True)
class ImageObject:
    """One reassembled Image object and where its record chunks sit in the EMF."""

    object_id: int
    locations: list[Location]
    data: bytes
    kind: str = ""
    extension: str = ""
    payload: bytes = b""
    pixel_format: int = 0
    raw_stride: int = 0
    width: int = 0
    height: int = 0
    is_compressed: bool = True
    image: Image.Image | None = None


@dataclass(frozen=True, slots=True)
class UnsupportedImageObject:
    """An Image object that is left unchanged, with the first place it sits."""

    object_id: int
    location: Location
    reason: str


def find_image_objects(
    comments: list[tuple[int, list[PlusRecord]]],
) -> tuple[list[ImageObject], list[UnsupportedImageObject]]:
    """Reassemble every Image object and read its header.

    ``comments`` is the parsed EMF+ records of each EMF+ comment with the comment's
    index. An object that cannot be processed safely is returned as unsupported.
    """
    flat = [
        ((record_index, plus_index), plus)
        for record_index, plus_records in comments
        for plus_index, plus in enumerate(plus_records)
    ]
    objects: list[ImageObject] = []
    unsupported: list[UnsupportedImageObject] = []
    pending: _Pending | None = None

    def finish(locations: list[Location], object_id: int, data: bytes) -> None:
        parsed = _read_object(object_id, locations, data)
        if isinstance(parsed, str):
            unsupported.append(UnsupportedImageObject(object_id, locations[0], parsed))
        else:
            objects.append(parsed)

    for location, plus in flat:
        is_image = plus.record_type == EMFPLUS_OBJECT and _object_type(plus) == IMAGE_OBJECT_TYPE
        if pending is not None:
            if is_image and plus.flags & _CONTINUED and (plus.flags & 0xFF) == pending.object_id:
                if not pending.add(location, plus):
                    unsupported.append(UnsupportedImageObject(
                        pending.object_id, pending.locations[0], "emfplus_image_object_chunks_invalid"
                    ))
                    pending = None
                elif pending.is_complete:
                    finish(pending.locations, pending.object_id, bytes(pending.data))
                    pending = None
                continue
            unsupported.append(UnsupportedImageObject(
                pending.object_id, pending.locations[0], "emfplus_image_object_chunks_invalid"
            ))
            pending = None
        if not is_image:
            continue
        object_id = plus.flags & 0xFF
        if not plus.flags & _CONTINUED:
            finish([location], object_id, plus.data)
            continue
        started = _Pending(object_id)
        if not started.add(location, plus):
            unsupported.append(
                UnsupportedImageObject(object_id, location, "emfplus_image_object_chunks_invalid")
            )
        elif started.is_complete:
            finish(started.locations, object_id, bytes(started.data))
        else:
            pending = started
    if pending is not None:
        unsupported.append(UnsupportedImageObject(
            pending.object_id, pending.locations[0], "emfplus_image_object_chunks_invalid"
        ))
    return objects, unsupported


class _Pending:
    """An object whose chunks are still being collected."""

    def __init__(self, object_id: int) -> None:
        self.object_id = object_id
        self.locations: list[Location] = []
        self.data = bytearray()
        self._total: int | None = None

    def add(self, location: Location, plus: PlusRecord) -> bool:
        """Add one chunk; return False when it contradicts the object's declared size."""
        if len(plus.data) < 4:
            return False
        total: int = struct.unpack_from("<I", plus.data, 0)[0]
        if self._total is not None and total != self._total:
            return False
        self._total = total
        self.locations.append(location)
        self.data += plus.data[4:]
        return len(self.data) <= total

    @property
    def is_complete(self) -> bool:
        return self._total is not None and len(self.data) == self._total


def _object_type(plus: PlusRecord) -> int:
    return (plus.flags >> 8) & 0x7F


def _read_object(object_id: int, locations: list[Location], data: bytes) -> ImageObject | str:
    """Read the header of an Image object, or return the reason it is unsupported."""
    if len(data) < 8 or struct.unpack_from("<I", data, 0)[0] & _VERSION_MASK != _VERSION:
        return "emfplus_image_object_malformed"
    image_type = struct.unpack_from("<I", data, 4)[0]
    if image_type == _BITMAP_TYPE:
        return _read_bitmap(object_id, locations, data)
    if image_type == _METAFILE_TYPE:
        return _read_metafile(object_id, locations, data)
    return "emfplus_image_object_type_unsupported"


def _read_bitmap(object_id: int, locations: list[Location], data: bytes) -> ImageObject | str:
    if len(data) < _BITMAP_HEADER_SIZE:
        return "emfplus_image_object_malformed"
    width, height, stride, pixel_format, bitmap_type = struct.unpack_from("<iiiII", data, 8)
    obj = ImageObject(
        object_id, locations, data, kind="bitmap", width=width, height=height,
        pixel_format=pixel_format, raw_stride=stride,
    )
    pixels = data[_BITMAP_HEADER_SIZE:]
    if bitmap_type == _COMPRESSED:
        if not (pixels.startswith(_PNG_SIGNATURE) or pixels.startswith(_JPEG_SIGNATURE)):
            return "emfplus_image_object_format_unsupported"
        obj.payload = pixels
        return obj
    if bitmap_type != 0 or pixel_format not in _RAW_PIXEL_FORMATS:
        return "emfplus_image_object_format_unsupported"
    bytes_per_pixel = _RAW_PIXEL_FORMATS[pixel_format][2]
    if (
        width <= 0 or height <= 0 or stride < width * bytes_per_pixel
        or len(pixels) < stride * height
    ):
        return "emfplus_image_object_malformed"
    obj.is_compressed = False
    obj.payload = pixels
    return obj


def _read_metafile(object_id: int, locations: list[Location], data: bytes) -> ImageObject | str:
    if len(data) < _METAFILE_HEADER_SIZE:
        return "emfplus_image_object_malformed"
    metafile_type, size = struct.unpack_from("<II", data, 8)
    extension = _METAFILE_EXTENSIONS.get(metafile_type)
    if extension is None:
        return "emfplus_image_object_format_unsupported"
    if size == 0 or _METAFILE_HEADER_SIZE + size > len(data):
        return "emfplus_image_object_malformed"
    return ImageObject(
        object_id, locations, data, kind="metafile", extension=extension,
        payload=data[_METAFILE_HEADER_SIZE : _METAFILE_HEADER_SIZE + size],
    )


def decode_bitmap(obj: ImageObject) -> Image.Image:
    """Decode a bitmap object to an RGB or RGBA image of the source pixel size."""
    if not obj.is_compressed:
        mode, raw_mode, _bytes = _RAW_PIXEL_FORMATS[obj.pixel_format]
        return Image.frombuffer(
            mode, (obj.width, obj.height), obj.payload, "raw", raw_mode, obj.raw_stride, 1
        ).copy()
    with Image.open(BytesIO(obj.payload)) as opened:
        image = opened.copy()
    has_alpha = "A" in image.getbands() or "transparency" in image.info
    return image.convert("RGBA" if has_alpha else "RGB")


def bitmap_object_data(obj: ImageObject, image: Image.Image) -> bytes:
    """Return the bitmap object's data with ``image`` as a compressed PNG bitmap."""
    output = BytesIO()
    image.save(output, format="PNG")
    # The size, stride and pixel format fields are ignored for a compressed bitmap.
    return obj.data[:24] + struct.pack("<I", _COMPRESSED) + output.getvalue()


def metafile_object_data(obj: ImageObject, metafile: bytes) -> bytes:
    """Return the metafile object's data with ``metafile`` and its new data size."""
    metafile_type = struct.unpack_from("<I", obj.data, 8)[0]
    return obj.data[:8] + struct.pack("<II", metafile_type, len(metafile)) + metafile


def image_object_comments(object_id: int, data: bytes) -> list[bytes]:
    """Return the ``EMR_COMMENT`` records that carry an Image object, chunked as GDI+ does."""
    padded = data + b"\0" * (-len(data) % 4)
    flags = (IMAGE_OBJECT_TYPE << 8) | object_id
    if len(padded) <= MAX_RECORD_DATA:
        return [comment_record(plus_record(EMFPLUS_OBJECT, flags, padded))]
    piece = MAX_RECORD_DATA - 4
    total = struct.pack("<I", len(padded))
    return [
        comment_record(plus_record(EMFPLUS_OBJECT, flags | _CONTINUED, total + padded[start : start + piece]))
        for start in range(0, len(padded), piece)
    ]
