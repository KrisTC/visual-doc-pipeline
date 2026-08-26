#!/usr/bin/env python3
"""Validate SR-2026-08-01-01 dependency source controls."""

from __future__ import annotations

import sys
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
LOCKFILE = ROOT / "uv.lock"
ALLOWLIST = ROOT / "approved-dependency-artifact-hashes.toml"


@dataclass(frozen=True, slots=True)
class IndexConfiguration:
    """Configured default and explicitly opted-in package registries."""

    default_registry: str | None
    explicit_indexes: Mapping[str, str]
    package_sources: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ApprovedArtifacts:
    """Validated non-default-registry artifact metadata."""

    package_versions: set[tuple[str, str]]
    record_count: int


@dataclass(frozen=True, slots=True)
class LockfileValidation:
    """Counts collected while validating locked package sources."""

    registry_package_count: int
    non_default_package_count: int


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


def validate_pyproject(document: Mapping[str, object], errors: list[str]) -> IndexConfiguration:
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

    index_configuration = _index_configuration(uv, errors)

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

    return index_configuration


def _index_configuration(uv: Mapping[str, object], errors: list[str]) -> IndexConfiguration:
    default_registry: str | None = None
    explicit_indexes: dict[str, str] = {}
    for index in string_mappings(uv.get("index")):
        name = index.get("name")
        url = index.get("url")
        is_default = index.get("default", False)
        is_explicit = index.get("explicit", False)
        if not isinstance(name, str) or not isinstance(url, str):
            errors.append("pyproject.toml: every tool.uv.index entry must define string name and url values.")
            continue
        if not isinstance(is_default, bool) or not isinstance(is_explicit, bool):
            errors.append("pyproject.toml: index default and explicit values must be booleans.")
            continue
        if is_default and is_explicit:
            errors.append(f"pyproject.toml: index {name!r} cannot be both default and explicit.")
            continue
        if is_default:
            if default_registry is not None:
                errors.append("pyproject.toml: tool.uv.index must define exactly one default registry.")
            default_registry = url
        elif is_explicit:
            if name in explicit_indexes:
                errors.append(f"pyproject.toml: explicit index name {name!r} is duplicated.")
            explicit_indexes[name] = url

    if default_registry is None:
        errors.append("pyproject.toml: tool.uv.index must define one default registry.")

    package_sources: dict[str, str] = {}
    for package_name, source in mapping(uv.get("sources")).items():
        source_mapping = mapping(source)
        index_name = source_mapping.get("index")
        if (
            set(source_mapping) != {"index"}
            or not isinstance(index_name, str)
            or index_name not in explicit_indexes
        ):
            errors.append(
                f"pyproject.toml: source for {package_name!r} must select a configured explicit index."
            )
            continue
        package_sources[package_name] = index_name

    return IndexConfiguration(default_registry, explicit_indexes, package_sources)


def validate_lockfile(
    document: Mapping[str, object],
    project_name: str | None,
    index_configuration: IndexConfiguration,
    approved_packages: set[tuple[str, str]],
    errors: list[str],
) -> LockfileValidation:
    registry_package_count = 0
    non_default_package_count = 0
    for package in string_mappings(document.get("package")):
        package_name = package.get("name", "<unknown>")
        source = mapping(package.get("source"))
        if package_name == project_name and source == {"virtual": "."}:
            continue
        version = package.get("version")
        registry = source.get("registry")
        if not isinstance(package_name, str) or not isinstance(version, str) or set(source) != {"registry"} or not isinstance(registry, str):
            errors.append(
                f"uv.lock: {package_name!r} must be sourced from a configured registry."
            )
            continue
        registry_package_count += 1
        if registry == index_configuration.default_registry:
            continue
        non_default_package_count += 1
        matching_indexes = [
            index_name
            for index_name, index_url in index_configuration.explicit_indexes.items()
            if index_url == registry
        ]
        if len(matching_indexes) != 1:
            errors.append(f"uv.lock: {package_name!r} uses an unconfigured non-default registry.")
            continue
        if index_configuration.package_sources.get(package_name) != matching_indexes[0]:
            errors.append(
                f"uv.lock: {package_name!r} must be explicitly assigned to its non-default registry."
            )
        if (package_name, version) not in approved_packages:
            errors.append(
                f"uv.lock: {package_name}=={version} has no approved verified artifact."
            )
    return LockfileValidation(registry_package_count, non_default_package_count)


def load_approved_artifacts(path: Path, errors: list[str]) -> ApprovedArtifacts:
    if not path.is_file():
        errors.append("approved-dependency-artifact-hashes.toml is missing.")
        return ApprovedArtifacts(set(), 0)
    document = load_toml(path)
    artifacts = document.get("artifact")
    if not isinstance(artifacts, list):
        errors.append("approved-dependency-artifact-hashes.toml must contain an [[artifact]] array.")
        return ApprovedArtifacts(set(), 0)
    packages: set[tuple[str, str]] = set()
    record_count = 0
    for artifact in artifacts:
        entry = mapping(artifact)
        requirement = entry.get("requirement")
        distribution = entry.get("distribution")
        version = entry.get("version")
        url = entry.get("url")
        digest = entry.get("sha256")
        size = entry.get("size")
        wheel_tags = entry.get("wheel_tags")
        if (
            not isinstance(requirement, str)
            or not isinstance(distribution, str)
            or not isinstance(version, str)
            or not isinstance(url, str)
            or not isinstance(digest, str)
            or not isinstance(size, int)
            or not isinstance(wheel_tags, str)
        ):
            errors.append("approved-dependency-artifact-hashes.toml contains an invalid artifact record.")
            continue
        parsed_url = urlsplit(url)
        if (
            not requirement
            or not distribution
            or not version
            or parsed_url.scheme != "https"
            or not parsed_url.netloc
            or not parsed_url.path.endswith(".whl")
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or size <= 0
            or len(wheel_tags.split("-")) != 3
        ):
            errors.append("approved-dependency-artifact-hashes.toml contains an invalid artifact record.")
            continue
        packages.add((distribution, version))
        record_count += 1
    return ApprovedArtifacts(packages, record_count)


def string_mappings(value: object) -> Iterable[Mapping[str, object]]:
    if isinstance(value, list):
        return (mapping(item) for item in value)
    return ()


def success_message(
    index_configuration: IndexConfiguration,
    lockfile_validation: LockfileValidation,
    approved_artifacts: ApprovedArtifacts,
) -> str:
    """Summarize the dependency-policy controls verified during this run."""
    return "\n".join(
        (
            "Dependency policy check passed.",
            "- Source controls: exclude-newer=7 days, no-build=True, package=False.",
            f"- Registries: 1 default and {len(index_configuration.explicit_indexes)} explicit configured.",
            (
                f"- Lockfile: {lockfile_validation.registry_package_count} registry packages checked, "
                f"including {lockfile_validation.non_default_package_count} from explicit registries."
            ),
            (
                f"- Approved artifacts: {approved_artifacts.record_count} wheel records cover "
                f"{len(approved_artifacts.package_versions)} non-default package versions."
            ),
        )
    )


def main() -> int:
    errors: list[str] = []
    project_name: str | None = None
    approved_artifacts = ApprovedArtifacts(set(), 0)
    if not PYPROJECT.is_file():
        errors.append("pyproject.toml is missing.")
        index_configuration = IndexConfiguration(None, {}, {})
    else:
        pyproject = load_toml(PYPROJECT)
        index_configuration = validate_pyproject(pyproject, errors)
        project_name_value = mapping(pyproject.get("project")).get("name")
        project_name = project_name_value if isinstance(project_name_value, str) else None

    if not LOCKFILE.is_file():
        errors.append("uv.lock is missing.")
        lockfile_validation = LockfileValidation(0, 0)
    else:
        approved_artifacts = load_approved_artifacts(ALLOWLIST, errors)
        lockfile_validation = validate_lockfile(
            load_toml(LOCKFILE),
            project_name,
            index_configuration,
            approved_artifacts.package_versions,
            errors,
        )

    if errors:
        print("Dependency policy check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(success_message(index_configuration, lockfile_validation, approved_artifacts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
