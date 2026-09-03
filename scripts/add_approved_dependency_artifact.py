#!/usr/bin/env python3
"""Add reviewed non-default-registry wheel artifacts to the local allowlist."""

from __future__ import annotations

import argparse
import hashlib
import re
import tomllib
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.request import Request, urlopen

from pipeline.terminal_progress import LiveProgress

ROOT = Path(__file__).resolve().parents[1]
SECURITY_REQUIREMENTS = ROOT / "requirements" / "security-requirements.md"
ALLOWLIST = ROOT / "approved-dependency-artifact-hashes.toml"
CACHE_DIRECTORY = ROOT / ".dependency-artifact-cache"
PYPROJECT = ROOT / "pyproject.toml"
CHUNK_SIZE = 1024 * 1024
REQUIREMENT_ID_PATTERN = re.compile(r"SR-\d{4}-\d{2}-\d{2}-\d{2}\Z")
EXACT_PYTHON_VERSION_PATTERN = re.compile(r"==(?P<major>\d+)\.(?P<minor>\d+)\.\d+\Z")


@dataclass(frozen=True, slots=True)
class Artifact:
    """One reviewed wheel artifact permitted by a security requirement."""

    requirement: str
    distribution: str
    version: str
    url: str
    sha256: str
    size: int
    wheel_tags: str


class _LinkParser(HTMLParser):
    """Collect hyperlinks from a PEP 503 simple-index page."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for name, value in attrs:
            if name == "href" and value is not None:
                self.links.append(value)


def _normalize_distribution(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _index_url(registry: str, distribution: str) -> str:
    return urljoin(registry.rstrip("/") + "/", _normalize_distribution(distribution) + "/")


def _validate_inputs(requirement: str, registry: str, distribution: str, version: str) -> None:
    if not REQUIREMENT_ID_PATTERN.fullmatch(requirement):
        raise ValueError("--requirement must be a security requirement ID such as SR-2026-08-21-01.")
    parsed_registry = urlsplit(registry)
    if parsed_registry.scheme != "https" or not parsed_registry.netloc:
        raise ValueError("--registry must be an HTTPS PEP 503 base URL.")
    if registry.rstrip("/").endswith(".whl"):
        raise ValueError("--registry must be a registry base URL, not a direct wheel URL.")
    if not distribution or not version:
        raise ValueError("--distribution and --version must be non-empty.")
    requirement_text = SECURITY_REQUIREMENTS.read_text(encoding="utf-8")
    requirement_heading = f"## {requirement}\n"
    start = requirement_text.find(requirement_heading)
    if start < 0:
        raise ValueError(f"{requirement!r} is not defined in {SECURITY_REQUIREMENTS}.")
    end = requirement_text.find("\n---", start)
    section = requirement_text[start:] if end < 0 else requirement_text[start:end]
    if distribution not in section or version not in section or registry.rstrip("/") not in section:
        raise ValueError(
            f"{requirement!r} does not explicitly authorize {distribution}=={version} "
            f"from {registry!r}."
        )


def _supported_cpython_tags(pyproject: Path = PYPROJECT) -> frozenset[str]:
    """Return CPython wheel tags supported by the project's exact Python pin."""
    with pyproject.open("rb") as file:
        document = tomllib.load(file)
    project = document.get("project")
    requires_python = project.get("requires-python") if isinstance(project, dict) else None
    if not isinstance(requires_python, str):
        raise ValueError("pyproject.toml must declare project.requires-python.")
    match = EXACT_PYTHON_VERSION_PATTERN.fullmatch(requires_python)
    if match is None:
        raise ValueError(
            "The artifact approval workflow requires an exact ==X.Y.Z project.requires-python pin."
        )
    return frozenset({f"cp{match['major']}{match['minor']}"})


def _wheel_urls(registry: str, distribution: str, version: str) -> tuple[str, ...]:
    index_url = _index_url(registry, distribution)
    request = Request(index_url, headers={"Accept": "text/html"})
    with urlopen(request) as response:
        page = response.read().decode("utf-8")
    parser = _LinkParser()
    parser.feed(page)
    filename_prefix = _normalize_distribution(distribution).replace("-", "_") + f"-{version}-"
    supported_tags = _supported_cpython_tags()
    urls: set[str] = set()
    for link in parser.links:
        url, _ = urldefrag(urljoin(index_url, link))
        filename = Path(urlsplit(url).path).name
        wheel_parts = filename.removesuffix(".whl").rsplit("-", maxsplit=3)
        if (
            filename.startswith(filename_prefix)
            and filename.endswith(".whl")
            and len(wheel_parts) == 4
            and wheel_parts[1] in supported_tags
        ):
            urls.add(url)
    if not urls:
        raise ValueError(f"No wheel artifacts found for {distribution}=={version} at {index_url}.")
    return tuple(sorted(urls))


def _download_artifact(
    requirement: str, distribution: str, version: str, url: str, directory: Path,
    display: LiveProgress | None = None,
) -> Artifact:
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / _cache_filename(url)
    digest = hashlib.sha256()
    existing_size = destination.stat().st_size if destination.exists() else 0
    if existing_size:
        with destination.open("rb") as existing:
            while chunk := existing.read(CHUNK_SIZE):
                digest.update(chunk)
    request = Request(url, headers={"Range": f"bytes={existing_size}-"} if existing_size else {})
    with urlopen(request) as response:
        append = existing_size > 0 and response.status == 206
        if not append:
            existing_size = 0
            digest = hashlib.sha256()
        content_length = response.headers.get("Content-Length")
        total = existing_size + int(content_length) if content_length is not None else None
        mode = "ab" if append else "wb"
        if display is not None:
            display.start_download(Path(urlsplit(url).path).name, total, existing_size)
        with destination.open(mode) as output:
            while chunk := response.read(CHUNK_SIZE):
                digest.update(chunk)
                output.write(chunk)
                if display is not None:
                    display.advance_download(len(chunk))
    size = destination.stat().st_size
    metadata_name, metadata_version = _wheel_metadata(destination)
    if _normalize_distribution(metadata_name) != _normalize_distribution(distribution):
        raise ValueError(f"{url} metadata does not identify distribution {distribution!r}.")
    if metadata_version != version:
        raise ValueError(f"{url} metadata does not identify version {version!r}.")
    filename = destination.name.removesuffix(".whl")
    wheel_tags = filename.rsplit("-", maxsplit=3)[-3:]
    if len(wheel_tags) != 3:
        raise ValueError(f"{url} is not a valid wheel filename.")
    return Artifact(requirement, distribution, version, url, digest.hexdigest(), size, "-".join(wheel_tags))


def _cache_filename(url: str) -> str:
    """Return a collision-resistant cache filename for one artifact URL."""
    filename = Path(urlsplit(url).path).name
    return f"{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}-{filename}"


def _wheel_metadata(path: Path) -> tuple[str, str]:
    """Return the required Name and Version fields from a wheel metadata file."""
    with zipfile.ZipFile(path) as archive:
        metadata_paths = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_paths) != 1:
            raise ValueError(f"{path} must contain exactly one wheel metadata file.")
        headers = _metadata_headers(archive.read(metadata_paths[0]))
    name = headers.get("Name")
    version = headers.get("Version")
    if name is None or version is None:
        raise ValueError(f"{path} metadata must define Name and Version fields.")
    return name, version


def _metadata_headers(content: bytes) -> dict[str, str]:
    """Parse simple wheel metadata headers until the metadata body begins."""
    headers: dict[str, str] = {}
    for line in content.decode("utf-8").splitlines():
        if not line:
            break
        name, separator, value = line.partition(":")
        if separator and name and not name.startswith((" ", "\t")):
            headers[name] = value.lstrip()
    return headers


def _load_allowlist(path: Path) -> list[Artifact]:
    if not path.exists():
        return []
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    artifacts_value = document.get("artifact")
    if not isinstance(artifacts_value, list):
        raise ValueError(f"{path} must contain an [[artifact]] array.")
    artifacts: list[Artifact] = []
    for item in artifacts_value:
        if not isinstance(item, dict) or not all(isinstance(key, str) for key in item):
            raise ValueError(f"{path} artifact entries must be tables.")
        requirement = item.get("requirement")
        distribution = item.get("distribution")
        version = item.get("version")
        url = item.get("url")
        sha256 = item.get("sha256")
        size = item.get("size")
        wheel_tags = item.get("wheel_tags")
        if (
            not isinstance(requirement, str)
            or not isinstance(distribution, str)
            or not isinstance(version, str)
            or not isinstance(url, str)
            or not isinstance(sha256, str)
            or not isinstance(size, int)
            or not isinstance(wheel_tags, str)
        ):
            raise ValueError(f"{path} artifact entries have an invalid shape.")
        artifacts.append(Artifact(requirement, distribution, version, url, sha256, size, wheel_tags))
    return artifacts


def _write_allowlist(path: Path, artifacts: list[Artifact]) -> None:
    lines = ["# Locally reviewed non-default-registry wheel artifacts.", ""]
    for artifact in sorted(artifacts, key=lambda item: (item.distribution, item.version, item.url)):
        lines.extend(
            [
                "[[artifact]]",
                f'requirement = "{artifact.requirement}"',
                f'distribution = "{artifact.distribution}"',
                f'version = "{artifact.version}"',
                f'url = "{artifact.url}"',
                f'sha256 = "{artifact.sha256}"',
                f"size = {artifact.size}",
                f'wheel_tags = "{artifact.wheel_tags}"',
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def add_artifacts(
    requirement: str,
    registry: str,
    distribution: str,
    version: str,
    allowlist: Path = ALLOWLIST,
    *,
    replace: bool = False,
) -> tuple[Artifact, ...]:
    """Discover, verify, and record every wheel sibling for one approved version."""
    _validate_inputs(requirement, registry, distribution, version)
    existing = _load_allowlist(allowlist)
    matching = [
        artifact
        for artifact in existing
        if (artifact.requirement, artifact.distribution, artifact.version)
        == (requirement, distribution, version)
    ]
    urls = _wheel_urls(registry, distribution, version)
    approved = [artifact for artifact in matching if artifact.url in urls]
    matching_urls = {artifact.url for artifact in approved}
    if matching_urls == set(urls) and not replace:
        if len(approved) != len(matching):
            retained = [artifact for artifact in existing if artifact not in matching]
            _write_allowlist(allowlist, [*retained, *approved])
            return tuple(approved)
        raise ValueError("The allowlist already contains this requirement, distribution, and version; use --replace to update it.")
    retained = [artifact for artifact in existing if artifact not in matching]
    approved = approved if not replace else []
    matching_urls = {artifact.url for artifact in approved}
    pending_urls = tuple(url for url in urls if url not in matching_urls or replace)
    with LiveProgress() as display:
        display.start_overall(len(pending_urls), "artifact")
        for url in pending_urls:
            artifact = _download_artifact(
                requirement, distribution, version, url, CACHE_DIRECTORY, display
            )
            approved.append(artifact)
            _write_allowlist(allowlist, [*retained, *approved])
            display.advance_overall()
            display.clear_current()
    return tuple(approved)


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirement", required=True, help="Authorizing security requirement ID.")
    parser.add_argument("--registry", required=True, help="Authorizing HTTPS PEP 503 registry base URL.")
    parser.add_argument("--distribution", required=True, help="Distribution name to approve.")
    parser.add_argument("--version", required=True, help="Exact distribution version to approve.")
    parser.add_argument("--replace", action="store_true", help="Replace existing records for this requirement, distribution, and version.")
    return parser


def main() -> int:
    arguments = _argument_parser().parse_args()
    artifacts = add_artifacts(
        arguments.requirement,
        arguments.registry,
        arguments.distribution,
        arguments.version,
        replace=arguments.replace,
    )
    for artifact in artifacts:
        print(f"{artifact.wheel_tags} {artifact.size} bytes sha256:{artifact.sha256} {artifact.url}")
    print(f"Wrote {len(artifacts)} reviewed artifact record(s) to {ALLOWLIST}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
