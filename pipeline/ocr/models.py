"""Strongly typed models shared by every OCR provider."""

from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image


@dataclass(frozen=True, slots=True)
class PixelPoint:
    """A point in source-image pixel coordinates.

    Attributes:
        x: Horizontal position from the source image's left edge.
        y: Vertical position from the source image's top edge.
    """

    x: float
    y: float


@dataclass(frozen=True, slots=True)
class BoundingPolygon:
    """A text region defined by at least three source-image pixel vertices.

    Attributes:
        vertices: Vertices around the recognized text region, in reading order. Providers
            must preserve their detected geometry rather than reducing it to an
            axis-aligned rectangle.
    """

    vertices: tuple[PixelPoint, ...]

    def __post_init__(self) -> None:
        if len(self.vertices) < 3:
            message = "A bounding polygon must contain at least three vertices."
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class OcrRequest:
    """One image and the BCP 47 language tag to recognize.

    Attributes:
        image: The in-memory source image. Callers retain ownership of the image and
            providers must not require a filesystem path.
        language: A non-empty BCP 47 language tag, such as ``en`` or ``ja``. Each
            provider maps this stable public value to its own native convention.
    """

    image: Image.Image
    language: str

    def __post_init__(self) -> None:
        if not self.language.strip():
            message = "An OCR request requires a non-empty language tag."
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class OcrText:
    """One text region recognized by an OCR provider.

    Attributes:
        text: The string recognized in this text region. It is preserved exactly as
            returned by the provider, including provider-selected whitespace.
        confidence: The provider's recognition confidence normalized to the inclusive
            range 0.0 to 1.0. Higher values indicate greater provider confidence, but
            scores from different providers are not necessarily calibrated alike.
        bounding_polygon: The source-image pixel region from which ``text`` was
            recognized. Polygon vertices preserve rotation and other non-rectangular
            geometry when supplied by a provider.
        extra: Optional provider-specific information that has no cross-provider
            meaning. Use stable, provider-namespaced keys, and do not require other
            providers to supply them. The default is an empty dictionary.
    """

    text: str
    confidence: float
    bounding_polygon: BoundingPolygon
    extra: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            message = "OCR confidence must be between 0.0 and 1.0 inclusive."
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class OcrResult:
    """The text regions recognized from one OCR request.

    Attributes:
        text_items: Text regions in the reading order supplied by the provider.
    """

    text_items: tuple[OcrText, ...]
