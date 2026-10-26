#!/usr/bin/env python3
"""Prepare raster-image inputs for OCR evaluation."""

from __future__ import annotations

import argparse
import hashlib
import posixpath
import shutil
import sys
import xml.etree.ElementTree as ElementTree
from collections import deque
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable, Iterator, Protocol, cast
from urllib.parse import unquote
from zipfile import BadZipFile, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from pypdf import PdfReader
from pipeline.folder_replacement.filters import is_office_owner_file, matches_include_patterns
from pipeline.ocr.languages import discover_language_directories


BITMAP_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
OFFICE_DOCUMENT_EXTENSIONS = {".docx", ".pptx", ".xlsx"}
OFFICE_DOCUMENT_RELATIONSHIP_TYPE = "/officeDocument"
@dataclass(frozen=True)
class ExtractedImage:
    data: bytes
    extension: str


@dataclass
class PreparationResult:
    copied_bitmaps: int = 0
    extracted_images: int = 0
    processed_documents: int = 0
    removed_directories: int = 0
    skipped_documents: int = 0
    selected_image_paths: tuple[Path, ...] = ()


class PreparationProgress(Protocol):
    """Receives the named steps of input preparation and their completed work items."""

    def start_step(self, label: str, total: int | None) -> None:
        """Begin a named step whose total is unknown when it is None."""

    def advance(self) -> None:
        """Record one completed work item in the active step."""


class PngSavable(Protocol):
    """An image object that can encode itself to PNG."""

    def save(self, output: BytesIO, format: str) -> None:
        """Encode the image to the requested output format."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalise_extension(name: str) -> str:
    return Path(name).suffix.lower()


def convert_to_png(image: PngSavable) -> ExtractedImage:
    """Convert a PDF image that uses an unsupported bitmap encoding to PNG."""
    output = BytesIO()
    image.save(output, format="PNG")
    return ExtractedImage(output.getvalue(), ".png")


def extract_pdf_images(source: Path) -> Iterator[ExtractedImage]:
    """Extract unique raster images, including nested Form XObjects and inline images."""
    seen_images: set[str] = set()
    reader = PdfReader(source)
    for page in reader.pages:
        for image in page.images:
            extension = normalise_extension(image.name)
            extracted = (
                ExtractedImage(image.data, extension)
                if extension in BITMAP_EXTENSIONS
                # pypdf's image wrapper does not publish a precise image type.
                else convert_to_png(cast(PngSavable, image.image))
            )
            image_key = hashlib.sha256(extracted.data).hexdigest()
            if image_key in seen_images:
                continue
            seen_images.add(image_key)
            yield extracted


def relationship_part_name(source_part: str | None) -> str:
    if source_part is None:
        return "_rels/.rels"
    directory, filename = posixpath.split(source_part)
    return posixpath.join(directory, "_rels", f"{filename}.rels")


def resolve_relationship_target(source_part: str | None, target: str) -> str | None:
    target = unquote(target)
    if target.startswith("/"):
        resolved = target.lstrip("/")
    else:
        base_directory = "" if source_part is None else posixpath.dirname(source_part)
        resolved = posixpath.normpath(posixpath.join(base_directory, target))
    if resolved in {"", ".", ".."} or resolved.startswith("../"):
        return None
    return resolved


def related_parts(archive: ZipFile, source_part: str | None) -> list[str]:
    relationships_path = relationship_part_name(source_part)
    if relationships_path not in archive.namelist():
        return []

    relationships = ElementTree.fromstring(archive.read(relationships_path))
    targets = []
    for relationship in relationships:
        if source_part is None and not relationship.attrib.get("Type", "").endswith(
            OFFICE_DOCUMENT_RELATIONSHIP_TYPE
        ):
            continue
        if relationship.attrib.get("TargetMode") == "External":
            continue
        target = relationship.attrib.get("Target")
        if target is None:
            continue
        resolved = resolve_relationship_target(source_part, target)
        if resolved is not None and resolved in archive.namelist():
            targets.append(resolved)
    return sorted(set(targets))


def extract_office_images(source: Path) -> Iterator[ExtractedImage]:
    """Extract raster parts reachable through an OOXML package relationship graph."""
    try:
        with ZipFile(source) as archive:
            queue: deque[str | None] = deque([None])
            visited_parts: set[str | None] = set()
            yielded_parts: set[str] = set()

            while queue:
                source_part = queue.popleft()
                if source_part in visited_parts:
                    continue
                visited_parts.add(source_part)

                for target_part in related_parts(archive, source_part):
                    extension = normalise_extension(target_part)
                    if extension in BITMAP_EXTENSIONS:
                        if target_part not in yielded_parts:
                            yielded_parts.add(target_part)
                            yield ExtractedImage(archive.read(target_part), extension)
                    elif target_part not in visited_parts:
                        queue.append(target_part)
    except BadZipFile as error:
        raise ValueError(f"Unsupported or invalid Office document: {source}") from error


def extract_document_images(source: Path) -> Iterable[ExtractedImage]:
    if source.suffix.lower() == ".pdf":
        return extract_pdf_images(source)
    return extract_office_images(source)


def document_output_directory(output_root: Path, relative_source_path: Path) -> Path:
    output_directory = output_root / relative_source_path
    resolved_root = output_root.resolve()
    if not output_directory.resolve().is_relative_to(resolved_root):
        raise ValueError(f"Document output path escapes output root: {relative_source_path}")
    return output_directory


def is_unchanged(output_directory: Path, source_checksum: str) -> bool:
    checksum_path = output_directory / ".source.sha256"
    return checksum_path.is_file() and checksum_path.read_text(encoding="ascii").strip() == source_checksum


def expected_output_directories(
    source_root: Path, language_directories: Iterable[Path]
) -> set[Path]:
    """Return output directories that have an eligible source counterpart."""
    expected_directories: set[Path] = set()
    for language_directory in language_directories:
        expected_directories.add(language_directory.relative_to(source_root))
        for source_path in language_directory.rglob("*"):
            relative_source_path = source_path.relative_to(source_root)
            if source_path.is_dir() or (
                source_path.suffix.lower() in (OFFICE_DOCUMENT_EXTENSIONS | {".pdf"})
                and not is_office_owner_file(source_path)
            ):
                expected_directories.add(relative_source_path)
    return expected_directories


def remove_stale_output_directories(
    source_root: Path,
    output_root: Path,
    language_directories: Iterable[Path],
    progress: PreparationProgress | None = None,
) -> int:
    """Remove stale generated directories while retaining unmatched files in live ones."""
    if not output_root.is_dir():
        return 0

    if progress is not None:
        progress.start_step("Scanning stale output", None)
    expected_directories = expected_output_directories(source_root, language_directories)
    removed_directories = 0

    stale_directories = sorted(
        (
            path
            for path in output_root.rglob("*")
            if path.is_dir()
            and not _is_expected_or_ancestor(
                path.relative_to(output_root), expected_directories
            )
        ),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    if progress is not None:
        progress.start_step("Removing stale output", len(stale_directories))
    for stale_directory in stale_directories:
        if stale_directory.is_dir():
            shutil.rmtree(stale_directory)
            removed_directories += 1
        if progress is not None:
            progress.advance()

    return removed_directories


def _is_expected_or_ancestor(path: Path, expected_directories: set[Path]) -> bool:
    return path in expected_directories or any(
        expected_directory.is_relative_to(path)
        for expected_directory in expected_directories
    )


def prepare_evaluation_inputs(
    source_root: Path,
    output_root: Path,
    include_patterns: tuple[str, ...] = (),
    progress: PreparationProgress | None = None,
) -> PreparationResult:
    """Copy raster samples and extract embedded raster images from supported documents."""
    if not source_root.is_dir():
        raise ValueError(f"Source root does not exist or is not a directory: {source_root}")

    result = PreparationResult()
    selected_image_paths: list[Path] = []
    language_directories = discover_language_directories(source_root)
    if progress is not None:
        progress.start_step("Scanning sources", None)
    eligible_sources = [
        source
        for language_directory in language_directories
        for source in sorted(path for path in language_directory.rglob("*") if path.is_file())
        if source.suffix.lower() in BITMAP_EXTENSIONS | OFFICE_DOCUMENT_EXTENSIONS | {".pdf"}
        and not is_office_owner_file(source)
        and matches_include_patterns(source.relative_to(source_root), include_patterns)
    ]
    if progress is not None:
        progress.start_step("Preparing", len(eligible_sources))
    for source in eligible_sources:
        try:
            relative_source_path = source.relative_to(source_root)
            extension = source.suffix.lower()

            if extension in BITMAP_EXTENSIONS:
                destination = output_root / relative_source_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                result.copied_bitmaps += 1
                if include_patterns:
                    selected_image_paths.append(relative_source_path)
                continue

            output_directory = document_output_directory(output_root, relative_source_path)
            source_checksum = sha256_file(source)
            if is_unchanged(output_directory, source_checksum):
                result.skipped_documents += 1
                if include_patterns:
                    selected_image_paths.extend(
                        path.relative_to(output_root)
                        for path in sorted(output_directory.iterdir())
                        if path.is_file() and path.suffix.lower() in BITMAP_EXTENSIONS
                    )
                continue

            if output_directory.exists():
                if not output_directory.is_dir():
                    raise ValueError(
                        f"Document output path is not a directory: {output_directory}"
                    )
                shutil.rmtree(output_directory)
            output_directory.mkdir(parents=True)

            extracted_images = list(extract_document_images(source))
            for index, image in enumerate(extracted_images, start=1):
                destination = output_directory / f"image-{index:04d}{image.extension}"
                destination.write_bytes(image.data)
                if include_patterns:
                    selected_image_paths.append(destination.relative_to(output_root))
            (output_directory / ".source.sha256").write_text(
                f"{source_checksum}\n", encoding="ascii"
            )
            result.extracted_images += len(extracted_images)
            result.processed_documents += 1
        finally:
            if progress is not None:
                progress.advance()

    if not include_patterns:
        result.removed_directories = remove_stale_output_directories(
            source_root, output_root, language_directories, progress
        )
    result.selected_image_paths = tuple(selected_image_paths)

    return result


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path("sample-data"))
    parser.add_argument(
        "--output-root", type=Path, default=Path("outputs/evaluations/ocr/input")
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    result = prepare_evaluation_inputs(arguments.source_root, arguments.output_root)
    print(
        "OCR evaluation input preparation complete: "
        f"{result.copied_bitmaps} bitmap(s) copied, "
        f"{result.extracted_images} embedded image(s) extracted, "
        f"{result.processed_documents} document(s) processed, "
        f"{result.removed_directories} stale directory(s) removed, "
        f"{result.skipped_documents} unchanged document(s) skipped."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
