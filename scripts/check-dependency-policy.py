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
PYPI_SIMPLE_URL = "https://pypi.org/simple"


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


def validate_lockfile(
    document: Mapping[str, object], project_name: str | None, errors: list[str]
) -> None:
    for package in string_mappings(document.get("package")):
        package_name = package.get("name", "<unknown>")
        source = mapping(package.get("source"))
        if package_name == project_name and source == {"virtual": "."}:
            continue
        if source != {"registry": PYPI_SIMPLE_URL}:
            errors.append(
                f"uv.lock: {package_name!r} must be sourced only from PyPI."
            )


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
