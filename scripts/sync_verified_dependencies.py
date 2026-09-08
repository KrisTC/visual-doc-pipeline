#!/usr/bin/env python3
"""Synchronize locked dependencies and install non-default artifacts after verification."""

from __future__ import annotations

import argparse
import ast
import hashlib
import os
import platform
import re
import subprocess
import sys
import sysconfig
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from pipeline.terminal_progress import LiveProgress

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "approved-dependency-artifact-hashes.toml"
LOCKFILE = ROOT / "uv.lock"
POLICY_CHECK = ROOT / "scripts" / "check-dependency-policy.py"
PYPI_SIMPLE_URL = "https://pypi.org/simple"
CHUNK_SIZE = 1024 * 1024
ARTIFACT_USER_AGENT = "visual-doc-pipeline-artifact-verifier/1.0"
EXPORTED_REQUIREMENT = re.compile(
    r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^]]*])?\s*==\s*([^\s;\\]+)"
    r"(?:\s*;\s*(.*?))?\s*$"
)


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


def _normalized_distribution_name(name: str) -> str:
    """Return the PEP 503 comparison form of a distribution name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _marker_environment(extra: str) -> dict[str, str]:
    """Return the standard PEP 508 values for this Python process."""
    return {
        "extra": extra,
        "implementation_name": sys.implementation.name,
        "implementation_version": platform.python_version(),
        "os_name": os.name,
        "platform_machine": platform.machine(),
        "platform_python_implementation": platform.python_implementation(),
        "platform_release": platform.release(),
        "platform_system": platform.system(),
        "platform_version": platform.version(),
        "python_full_version": platform.python_version(),
        "python_version": ".".join(platform.python_version_tuple()[:2]),
        "sys_platform": sys.platform,
    }


def _marker_operand(node: ast.expr, environment: dict[str, str]) -> str:
    if isinstance(node, ast.Name) and node.id in environment:
        return environment[node.id]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    raise ValueError("uv export produced an unsupported requirement marker.")


def _marker_comparison(operator: ast.cmpop, left: str, right: str) -> bool:
    if isinstance(operator, ast.Eq):
        return left == right
    if isinstance(operator, ast.NotEq):
        return left != right
    if isinstance(operator, ast.In):
        return left in right
    if isinstance(operator, ast.NotIn):
        return left not in right
    if isinstance(operator, ast.Lt):
        return left < right
    if isinstance(operator, ast.LtE):
        return left <= right
    if isinstance(operator, ast.Gt):
        return left > right
    if isinstance(operator, ast.GtE):
        return left >= right
    raise ValueError("uv export produced an unsupported requirement marker comparison.")


def _marker_applies(marker: str, extra: str) -> bool:
    """Safely evaluate the PEP 508 marker emitted by uv for the current platform."""
    environment = _marker_environment(extra)
    expression = ast.parse(marker.rstrip("\\ "), mode="eval").body

    def evaluate(node: ast.expr) -> bool:
        if isinstance(node, ast.BoolOp):
            values = (evaluate(value) for value in node.values)
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
        if isinstance(node, ast.Compare):
            left = _marker_operand(node.left, environment)
            for operator, comparator in zip(node.ops, node.comparators, strict=True):
                right = _marker_operand(comparator, environment)
                if not _marker_comparison(operator, left, right):
                    return False
                left = right
            return True
        raise ValueError("uv export produced an unsupported requirement marker.")

    return evaluate(expression)


def _selected_locked_packages(
    *,
    extra: str,
    include_development_dependencies: bool,
    project_root: Path,
) -> frozenset[tuple[str, str]]:
    """Return package versions uv exports for one selected optional profile."""
    command = [
        "uv",
        "export",
        "--locked",
        "--format",
        "requirements-txt",
        "--no-emit-project",
        "--extra",
        extra,
    ]
    if not include_development_dependencies:
        command.append("--no-dev")
    completed_process = subprocess.run(
        command,
        check=True,
        capture_output=True,
        cwd=project_root,
        text=True,
    )
    selected: set[tuple[str, str]] = set()
    for line in completed_process.stdout.splitlines():
        match = EXPORTED_REQUIREMENT.match(line)
        if match is None:
            continue
        name, version, marker = match.groups()
        if marker is not None and not _marker_applies(marker, extra):
            continue
        selected.add((_normalized_distribution_name(name), unquote(version)))
    return frozenset(selected)


def _selected_non_default_packages(
    lockfile: Path,
    *,
    extra: str,
    include_development_dependencies: bool,
    project_root: Path,
) -> tuple[tuple[str, str], ...]:
    """Limit verified artifacts to the selected extra's current-platform closure."""
    selected = _selected_locked_packages(
        extra=extra,
        include_development_dependencies=include_development_dependencies,
        project_root=project_root,
    )
    return tuple(
        (distribution, version)
        for distribution, version in _non_default_packages(lockfile)
        if (_normalized_distribution_name(distribution), version) in selected
    )


def _current_platform_tag() -> str:
    return sysconfig.get_platform().replace("-", "_").replace(".", "_")


def _platform_matches(wheel_platform_tag: str, expected_platform_tag: str) -> bool:
    """Return whether an approved wheel tag can run on the current platform."""
    if expected_platform_tag in wheel_platform_tag:
        return True
    return expected_platform_tag == "linux_x86_64" and (
        wheel_platform_tag.startswith("manylinux") or wheel_platform_tag.startswith("linux")
    ) and wheel_platform_tag.endswith("x86_64")


def _select_artifact(artifacts: tuple[ApprovedArtifact, ...], distribution: str, version: str) -> ApprovedArtifact:
    expected_python_tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    expected_platform_tag = _current_platform_tag()
    matches = [
        artifact
        for artifact in artifacts
        if artifact.distribution == distribution
        and artifact.version == version
        and expected_python_tag in artifact.wheel_tags.split("-")
        and _platform_matches(artifact.wheel_tags.split("-")[-1], expected_platform_tag)
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one approved {distribution}=={version} wheel for "
            f"{expected_python_tag}/{expected_platform_tag}, found {len(matches)}."
        )
    return matches[0]


def _download_verified(
    artifact: ApprovedArtifact, directory: Path, display: LiveProgress | None = None
) -> Path:
    destination = directory / unquote(Path(artifact.url).name)
    digest = hashlib.sha256()
    with urlopen(Request(artifact.url, headers={"User-Agent": ARTIFACT_USER_AGENT})) as response, destination.open("wb") as output:
        content_length = response.headers.get("Content-Length")
        total = int(content_length) if content_length is not None else None
        if display is not None:
            display.start_download(destination.name, total)
        while chunk := response.read(CHUNK_SIZE):
            digest.update(chunk)
            output.write(chunk)
            if display is not None:
                display.advance_download(len(chunk))
    if digest.hexdigest() != artifact.sha256:
        destination.unlink(missing_ok=True)
        raise ValueError(f"SHA-256 verification failed for {artifact.url}.")
    return destination


def sync_dependencies(
    *,
    extra: str,
    include_development_dependencies: bool = True,
    project_root: Path = ROOT,
) -> None:
    """Install one locked profile, then its verified non-default wheels."""
    project_root = project_root.resolve()
    pyproject = project_root / "pyproject.toml"
    lockfile = project_root / "uv.lock"
    subprocess.run(
        [sys.executable, str(POLICY_CHECK), "--pyproject", str(pyproject), "--lockfile", str(lockfile)],
        check=True,
        cwd=ROOT,
    )
    non_default_packages = _selected_non_default_packages(
        lockfile,
        extra=extra,
        include_development_dependencies=include_development_dependencies,
        project_root=project_root,
    )
    sync_command = ["uv", "sync", "--locked", "--extra", extra]
    if not include_development_dependencies:
        sync_command.append("--no-dev")
    for distribution, _ in non_default_packages:
        sync_command.extend(("--no-install-package", distribution))
    subprocess.run(sync_command, check=True, cwd=project_root)
    artifacts = _approved_artifacts(ALLOWLIST)
    with tempfile.TemporaryDirectory(prefix="verified-dependency-") as temporary_directory:
        directory = Path(temporary_directory)
        _install_verified_artifacts(non_default_packages, artifacts, directory, project_root)


def _install_verified_artifacts(
    non_default_packages: tuple[tuple[str, str], ...],
    artifacts: tuple[ApprovedArtifact, ...],
    directory: Path,
    project_root: Path,
) -> None:
    """Install verified wheels, using progress only when this interpreter has Rich."""
    try:
        from pipeline.terminal_progress import LiveProgress
    except ImportError:
        for distribution, version in non_default_packages:
            _install_verified_artifact(_select_artifact(artifacts, distribution, version), directory, project_root)
        return
    with LiveProgress() as display:
        display.start_overall(len(non_default_packages), "artifact")
        for distribution, version in non_default_packages:
            artifact = _select_artifact(artifacts, distribution, version)
            _install_verified_artifact(artifact, directory, project_root, display)
            display.advance_overall()
            display.clear_current()


def _install_verified_artifact(
    artifact: ApprovedArtifact,
    directory: Path,
    project_root: Path,
    display: LiveProgress | None = None,
) -> None:
    """Download one reviewed wheel and install exactly those verified bytes."""
    wheel = _download_verified(artifact, directory, display)
    subprocess.run(
        ["uv", "pip", "install", "--offline", "--no-deps", str(wheel)],
        check=True,
        cwd=project_root,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-dev",
        action="store_true",
        help="Install only runtime dependencies from the committed lockfile.",
    )
    parser.add_argument(
        "--extra",
        required=True,
        help="Mutually exclusive optional-dependency profile to synchronise.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=ROOT,
        help="Project directory containing the locked dependency environment (default: repository root).",
    )
    arguments = parser.parse_args()
    sync_dependencies(
        extra=arguments.extra,
        include_development_dependencies=not arguments.no_dev,
        project_root=arguments.project_root,
    )
    print("Verified dependency synchronization completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
