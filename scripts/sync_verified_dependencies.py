#!/usr/bin/env python3
"""Synchronize locked dependencies and install non-default artifacts after verification."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import sysconfig
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from tqdm import tqdm


ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "approved-dependency-artifact-hashes.toml"
LOCKFILE = ROOT / "uv.lock"
POLICY_CHECK = ROOT / "scripts" / "check-dependency-policy.py"
PYPI_SIMPLE_URL = "https://pypi.org/simple"
CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class ApprovedArtifact:
    """A locally reviewed wheel selected for one non-default package."""

    distribution: str
    version: str
    url: str
    sha256: str
    wheel_tags: str


def _load_toml(path: Path) -> dict[str, object]:
    with path.open("rb") as file:
        return tomllib.load(file)


def _approved_artifacts(path: Path) -> tuple[ApprovedArtifact, ...]:
    values = _load_toml(path).get("artifact")
    if not isinstance(values, list):
        raise ValueError(f"{path} must contain an [[artifact]] array.")
    artifacts: list[ApprovedArtifact] = []
    for value in values:
        if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
            raise ValueError(f"{path} contains an invalid artifact entry.")
        distribution = value.get("distribution")
        version = value.get("version")
        url = value.get("url")
        sha256 = value.get("sha256")
        wheel_tags = value.get("wheel_tags")
        if (
            not isinstance(distribution, str)
            or not isinstance(version, str)
            or not isinstance(url, str)
            or not isinstance(sha256, str)
            or not isinstance(wheel_tags, str)
        ):
            raise ValueError(f"{path} contains an invalid artifact entry.")
        artifacts.append(ApprovedArtifact(distribution, version, url, sha256, wheel_tags))
    return tuple(artifacts)


def _non_default_packages(lockfile: Path) -> tuple[tuple[str, str], ...]:
    packages = _load_toml(lockfile).get("package")
    if not isinstance(packages, list):
        raise ValueError(f"{lockfile} must contain package records.")
    result: list[tuple[str, str]] = []
    for package in packages:
        if not isinstance(package, dict):
            continue
        source = package.get("source")
        name = package.get("name")
        version = package.get("version")
        if not isinstance(source, dict) or not isinstance(name, str) or not isinstance(version, str):
            continue
        registry = source.get("registry")
        if isinstance(registry, str) and registry != PYPI_SIMPLE_URL:
            result.append((name, version))
    return tuple(result)


def _current_platform_tag() -> str:
    return sysconfig.get_platform().replace("-", "_").replace(".", "_")


def _select_artifact(artifacts: tuple[ApprovedArtifact, ...], distribution: str, version: str) -> ApprovedArtifact:
    expected_python_tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    expected_platform_tag = _current_platform_tag()
    matches = [
        artifact
        for artifact in artifacts
        if artifact.distribution == distribution
        and artifact.version == version
        and expected_python_tag in artifact.wheel_tags.split("-")
        and expected_platform_tag in artifact.wheel_tags.split("-")
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one approved {distribution}=={version} wheel for "
            f"{expected_python_tag}/{expected_platform_tag}, found {len(matches)}."
        )
    return matches[0]


def _download_verified(artifact: ApprovedArtifact, directory: Path) -> Path:
    destination = directory / Path(artifact.url).name
    digest = hashlib.sha256()
    with urlopen(Request(artifact.url)) as response, destination.open("wb") as output:
        content_length = response.headers.get("Content-Length")
        total = int(content_length) if content_length is not None else None
        with tqdm(total=total, unit="B", unit_scale=True, desc=destination.name) as progress:
            while chunk := response.read(CHUNK_SIZE):
                digest.update(chunk)
                output.write(chunk)
                progress.update(len(chunk))
    if digest.hexdigest() != artifact.sha256:
        destination.unlink(missing_ok=True)
        raise ValueError(f"SHA-256 verification failed for {artifact.url}.")
    return destination


def sync_dependencies() -> None:
    """Install normal locked dependencies, then verified non-default wheels."""
    subprocess.run([sys.executable, str(POLICY_CHECK)], check=True, cwd=ROOT)
    non_default_packages = _non_default_packages(LOCKFILE)
    sync_command = ["uv", "sync", "--locked"]
    for distribution, _ in non_default_packages:
        sync_command.extend(("--no-install-package", distribution))
    subprocess.run(sync_command, check=True, cwd=ROOT)
    artifacts = _approved_artifacts(ALLOWLIST)
    with tempfile.TemporaryDirectory(prefix="verified-dependency-") as temporary_directory:
        directory = Path(temporary_directory)
        for distribution, version in non_default_packages:
            artifact = _select_artifact(artifacts, distribution, version)
            wheel = _download_verified(artifact, directory)
            subprocess.run(
                ["uv", "pip", "install", "--offline", "--no-deps", str(wheel)],
                check=True,
                cwd=ROOT,
            )


def main() -> int:
    sync_dependencies()
    print("Verified dependency synchronization completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())