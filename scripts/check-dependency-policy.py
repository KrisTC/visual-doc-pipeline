#!/usr/bin/env python3
"""Validate SR-2026-08-01-01 dependency source controls."""

from __future__ import annotations

import sys
import tomllib
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
LOCKFILE = ROOT / "uv.lock"
PYPI_SIMPLE_URL = "https://pypi.org/simple"


def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        return tomllib.load(file)


def dependency_strings(project: Mapping[str, Any]) -> Iterable[str]:
    yield from project.get("dependencies", [])
    for dependencies in project.get("optional-dependencies", {}).values():
        yield from dependencies


def is_direct_reference(requirement: str) -> bool:
    return " @ " in requirement.split(";", maxsplit=1)[0]


def validate_pyproject(document: Mapping[str, Any], errors: list[str]) -> None:
    tool = document.get("tool", {})
    uv = tool.get("uv", {}) if isinstance(tool, Mapping) else {}

    expected_settings = {
        "exclude-newer": "7 days",
        "no-build": True,
        "no-sources": True,
        "package": False,
    }
    for setting, expected_value in expected_settings.items():
        if uv.get(setting) != expected_value:
            errors.append(
                f"pyproject.toml: tool.uv.{setting} must be {expected_value!r}."
            )

    if uv.get("sources"):
        errors.append("pyproject.toml: tool.uv.sources must be empty or absent.")

    indexes = uv.get("index", [])
    if indexes != [
        {"name": "pypi", "url": PYPI_SIMPLE_URL, "default": True}
    ]:
        errors.append("pyproject.toml: only the PyPI simple index is permitted.")

    project = document.get("project", {})
    dependency_groups = document.get("dependency-groups", {})
    requirements = [*dependency_strings(project)]
    for dependencies in dependency_groups.values():
        requirements.extend(dependencies)

    for requirement in requirements:
        if is_direct_reference(requirement):
            errors.append(
                "pyproject.toml: direct dependency references are prohibited: "
                f"{requirement!r}."
            )


def validate_lockfile(
    document: Mapping[str, Any], project_name: str | None, errors: list[str]
) -> None:
    for package in document.get("package", []):
        package_name = package.get("name", "<unknown>")
        source = package.get("source", {})
        if package_name == project_name and source == {"virtual": "."}:
            continue
        if source != {"registry": PYPI_SIMPLE_URL}:
            errors.append(
                f"uv.lock: {package_name!r} must be sourced only from PyPI."
            )


def main() -> int:
    errors: list[str] = []
    project_name: str | None = None
    if not PYPROJECT.is_file():
        errors.append("pyproject.toml is missing.")
    else:
        pyproject = load_toml(PYPROJECT)
        validate_pyproject(pyproject, errors)
        project_name = pyproject.get("project", {}).get("name")

    if not LOCKFILE.is_file():
        errors.append("uv.lock is missing.")
    else:
        validate_lockfile(load_toml(LOCKFILE), project_name, errors)

    if errors:
        print("Dependency policy check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Dependency policy check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
