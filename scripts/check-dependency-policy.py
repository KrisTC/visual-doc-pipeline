#!/usr/bin/env python3
"""Validate SR-2026-08-01-01 dependency source controls."""

from __future__ import annotations

import sys
import tomllib
from collections.abc import Iterable, Mapping
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
LOCKFILE = ROOT / "uv.lock"
ALLOWLIST = ROOT / "approved-dependency-artifact-hashes.toml"
PYPI_SIMPLE_URL = "https://pypi.org/simple"
PADDLE_CUDA_SIMPLE_URL = "https://www.paddlepaddle.org.cn/packages/stable/cu126/"
PADDLE_CUDA_WHEEL_URL_PREFIX = "https://paddle-whl.bj.bcebos.com/stable/cu126/paddlepaddle-gpu/"
PADDLE_GPU_PACKAGE = "paddlepaddle-gpu"
PADDLE_GPU_VERSION = "3.3.1"
PADDLE_GPU_REQUIREMENT = "SR-2026-08-21-01"


def load_toml(path: Path) -> dict[str, object]:
    with path.open("rb") as file:
        return tomllib.load(file)


def mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return value
    return {}


def string_list(value: object) -> Iterable[str]:
    if isinstance(value, list):
        return (item for item in value if isinstance(item, str))
    return ()


def dependency_strings(project: Mapping[str, object]) -> Iterable[str]:
    yield from string_list(project.get("dependencies"))
    for dependencies in mapping(project.get("optional-dependencies")).values():
        yield from string_list(dependencies)


def is_direct_reference(requirement: str) -> bool:
    return " @ " in requirement.split(";", maxsplit=1)[0]


def validate_pyproject(document: Mapping[str, object], errors: list[str]) -> None:
    tool = mapping(document.get("tool"))
    uv = mapping(tool.get("uv"))

    expected_settings = {
        "exclude-newer": "7 days",
        "no-build": True,
        "package": False,
    }
    for setting, expected_value in expected_settings.items():
        if uv.get(setting) != expected_value:
            errors.append(
                f"pyproject.toml: tool.uv.{setting} must be {expected_value!r}."
            )

    if uv.get("sources") != {PADDLE_GPU_PACKAGE: {"index": "paddle-cu126"}}:
        errors.append(
            "pyproject.toml: tool.uv.sources must map only paddlepaddle-gpu to paddle-cu126."
        )

    indexes = uv.get("index", [])
    if indexes != [
        {"name": "paddle-cu126", "url": PADDLE_CUDA_SIMPLE_URL, "explicit": True, "exclude-newer": False},
        {"name": "pypi", "url": PYPI_SIMPLE_URL, "default": True},
    ]:
        errors.append("pyproject.toml: indexes must be the approved explicit Paddle index and PyPI.")

    project = mapping(document.get("project"))
    dependency_groups = mapping(document.get("dependency-groups"))
    requirements = [*dependency_strings(project)]
    for dependencies in dependency_groups.values():
        requirements.extend(string_list(dependencies))

    for requirement in requirements:
        if is_direct_reference(requirement):
            errors.append(
                "pyproject.toml: direct dependency references are prohibited: "
                f"{requirement!r}."
            )

    paddle_requirements = {
        requirement
        for requirement in requirements
        if requirement.partition(";")[0].strip().startswith("paddlepaddle")
    }
    if paddle_requirements != {
        "paddlepaddle==3.3.1; sys_platform != 'win32'",
        "paddlepaddle-gpu==3.3.1; sys_platform == 'win32'",
    }:
        errors.append("pyproject.toml: PaddlePaddle dependencies must use the approved CPU and Windows GPU pins.")


def validate_lockfile(
    document: Mapping[str, object], project_name: str | None, allowed_urls: set[str], errors: list[str]
) -> None:
    for package in string_mappings(document.get("package")):
        package_name = package.get("name", "<unknown>")
        source = mapping(package.get("source"))
        if package_name == project_name and source == {"virtual": "."}:
            continue
        if package_name == PADDLE_GPU_PACKAGE:
            _validate_paddle_gpu_package(package, source, allowed_urls, errors)
        elif source != {"registry": PYPI_SIMPLE_URL}:
            errors.append(
                f"uv.lock: {package_name!r} must be sourced only from PyPI."
            )


def _validate_paddle_gpu_package(
    package: Mapping[str, object], source: Mapping[str, object], allowed_urls: set[str], errors: list[str]
) -> None:
    if package.get("version") != PADDLE_GPU_VERSION:
        errors.append("uv.lock: paddlepaddle-gpu must use the approved exact version.")
    if source != {"registry": PADDLE_CUDA_SIMPLE_URL}:
        errors.append("uv.lock: paddlepaddle-gpu must use the approved Paddle index.")
    wheels = tuple(string_mappings(package.get("wheels")))
    if not wheels:
        errors.append("uv.lock: paddlepaddle-gpu must include wheel artifacts.")
    for wheel in wheels:
        url = wheel.get("url")
        if not isinstance(url, str) or not url.startswith(PADDLE_CUDA_WHEEL_URL_PREFIX):
            errors.append("uv.lock: paddlepaddle-gpu wheel URL must use the approved artifact host.")
        elif url not in allowed_urls:
            errors.append("uv.lock: paddlepaddle-gpu wheel URL is missing from the approved artifact allowlist.")


def load_approved_urls(path: Path, errors: list[str]) -> set[str]:
    if not path.is_file():
        errors.append("approved-dependency-artifact-hashes.toml is missing.")
        return set()
    document = load_toml(path)
    artifacts = document.get("artifact")
    if not isinstance(artifacts, list):
        errors.append("approved-dependency-artifact-hashes.toml must contain an [[artifact]] array.")
        return set()
    urls: set[str] = set()
    for artifact in artifacts:
        entry = mapping(artifact)
        if (
            entry.get("requirement") != PADDLE_GPU_REQUIREMENT
            or entry.get("distribution") != PADDLE_GPU_PACKAGE
            or entry.get("version") != PADDLE_GPU_VERSION
        ):
            errors.append("approved-dependency-artifact-hashes.toml contains an unauthorized artifact record.")
            continue
        url = entry.get("url")
        digest = entry.get("sha256")
        size = entry.get("size")
        wheel_tags = entry.get("wheel_tags")
        if not isinstance(url, str) or not isinstance(digest, str) or not isinstance(size, int) or not isinstance(wheel_tags, str):
            errors.append("approved-dependency-artifact-hashes.toml contains an invalid artifact record.")
            continue
        if not url.startswith(PADDLE_CUDA_WHEEL_URL_PREFIX) or len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            errors.append("approved-dependency-artifact-hashes.toml contains an invalid Paddle artifact record.")
            continue
        urls.add(url)
    return urls


def string_mappings(value: object) -> Iterable[Mapping[str, object]]:
    if isinstance(value, list):
        return (mapping(item) for item in value)
    return ()


def main() -> int:
    errors: list[str] = []
    project_name: str | None = None
    if not PYPROJECT.is_file():
        errors.append("pyproject.toml is missing.")
    else:
        pyproject = load_toml(PYPROJECT)
        validate_pyproject(pyproject, errors)
        project_name_value = mapping(pyproject.get("project")).get("name")
        project_name = project_name_value if isinstance(project_name_value, str) else None

    if not LOCKFILE.is_file():
        errors.append("uv.lock is missing.")
    else:
        validate_lockfile(
            load_toml(LOCKFILE), project_name, load_approved_urls(ALLOWLIST, errors), errors
        )

    if errors:
        print("Dependency policy check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Dependency policy check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
