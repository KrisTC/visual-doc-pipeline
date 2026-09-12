#!/usr/bin/env python3
"""Generate a requirements-based changelog draft for the next release."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_DIRECTORY = Path("requirements")
OUTPUT_DIRECTORY = Path("outputs/changelog-drafts")
RELEASE_TAG_PATTERN = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
REQUIREMENT_HEADER_PATTERN = re.compile(
    r"^## (?P<identifier>[A-Z]{2}-\d{4}-\d{2}-\d{2}-\d{2})\s*$",
    re.MULTILINE,
)
PROPERTY_PATTERN = re.compile(r"^\| (?P<name>[^|]+) \| (?P<value>.*) \|$")
REQUIREMENTS_ROUTE_PATTERN = re.compile(r"^\| (?P<description>.+) \| `(?P<filename>[^`]+)` \|$")
GITHUB_ORIGIN_PATTERN = re.compile(
    r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)
RequirementKey = tuple[Path, str]
GROUP_ORDER = (
    Path("requirements/security-requirements.md"),
    Path("requirements/technical-requirements.md"),
    Path("requirements/general-requirements.md"),
    Path("requirements/text-replacement-requirements.md"),
)


@dataclass(frozen=True, order=True, slots=True)
class Version:
    """A release version encoded in a supported Git tag."""

    major: int
    minor: int
    patch: int

    def next_minor(self) -> Version:
        """Return the next minor release version."""
        return Version(self.major, self.minor + 1, 0)

    def next_major(self) -> Version:
        """Return the next major release version."""
        return Version(self.major + 1, 0, 0)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True, slots=True)
class Requirement:
    """The changelog-relevant fields of one requirement revision."""

    identifier: str
    title: str
    status: str
    owner: str
    rationale: str
    source_file: Path = Path()


@dataclass(frozen=True, slots=True)
class RequirementGroup:
    """A human-readable requirements-file group derived from the requirements index."""

    title: str
    description: str


def parse_arguments() -> argparse.Namespace:
    """Parse the optional release-increment mode."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "increment",
        choices=("major",),
        nargs="?",
        help="increment the major version instead of the minor version",
    )
    return parser.parse_args()


def run_git(project_root: Path, *arguments: str) -> str:
    """Run Git in the repository and return its standard output."""
    completed_process = subprocess.run(
        ["git", *arguments],
        check=True,
        cwd=project_root,
        text=True,
        capture_output=True,
    )
    return completed_process.stdout


def release_tags(project_root: Path) -> dict[Version, str]:
    """Return supported release versions and their corresponding Git tags."""
    tags: dict[Version, str] = {}
    for tag in run_git(project_root, "tag", "--list").splitlines():
        match = RELEASE_TAG_PATTERN.fullmatch(tag)
        if match is None:
            continue
        version = Version(*(int(component) for component in match.groups()))
        tags[version] = tag
    return tags


def next_release(tags: dict[Version, str], increment: str | None) -> tuple[Version, str | None]:
    """Determine the proposed version and its optional preceding release tag."""
    if not tags:
        return Version(0, 1, 0), None
    baseline = max(tags)
    version = baseline.next_major() if increment == "major" else baseline.next_minor()
    return version, tags[baseline]


def github_compare_url(project_root: Path, baseline_tag: str, version: Version) -> str:
    """Build a GitHub comparison URL from the configured origin remote."""
    origin = run_git(project_root, "remote", "get-url", "origin").strip()
    match = GITHUB_ORIGIN_PATTERN.fullmatch(origin)
    if match is None:
        raise ValueError("origin must be a GitHub repository URL to generate a comparison link.")
    return f"https://github.com/{match.group('repository')}/compare/{baseline_tag}...v{version}"


def release_heading(version: Version, release_date: date, comparison_url: str | None) -> str:
    """Render the copy-ready release heading for the generated draft."""
    if comparison_url is None:
        return f"## {version} ({release_date.isoformat()})"
    return f"## [{version}]({comparison_url}) ({release_date.isoformat()})"


def requirement_files_at_revision(project_root: Path, revision: str) -> dict[Path, str]:
    """Read requirement files directly in requirements/ from a Git revision."""
    paths = run_git(project_root, "ls-tree", "-r", "--name-only", revision, "--", "requirements").splitlines()
    return {
        path: run_git(project_root, "show", f"{revision}:{path}")
        for name in paths
        if (path := Path(name)).parent == REQUIREMENTS_DIRECTORY and path.suffix == ".md"
    }


def requirement_groups(project_root: Path, revision: str) -> dict[Path, RequirementGroup]:
    """Read requirements-file group labels and scope descriptions from README.md."""
    contents = run_git(project_root, "show", f"{revision}:requirements/README.md")
    groups: dict[Path, RequirementGroup] = {}
    for line in contents.splitlines():
        match = REQUIREMENTS_ROUTE_PATTERN.fullmatch(line)
        if match is None:
            continue
        filename = match.group("filename")
        path = REQUIREMENTS_DIRECTORY / filename
        title = Path(filename).stem.replace("-", " ").title()
        groups[path] = RequirementGroup(title, f"Requirements for {match.group('description')}.")
    return groups


def parse_requirements(files: dict[Path, str]) -> dict[RequirementKey, Requirement]:
    """Extract requirements by immutable ID from requirement file contents."""
    requirements: dict[RequirementKey, Requirement] = {}
    for path, contents in files.items():
        headers = list(REQUIREMENT_HEADER_PATTERN.finditer(contents))
        for index, header in enumerate(headers):
            body_end = headers[index + 1].start() if index + 1 < len(headers) else len(contents)
            requirement = parse_requirement(header.group("identifier"), contents[header.end() : body_end], path)
            key = (path, requirement.identifier)
            if key in requirements:
                raise ValueError(f"Requirement ID {requirement.identifier} occurs more than once in {path}.")
            requirements[key] = requirement
    return requirements


def parse_requirement(identifier: str, body: str, source_file: Path) -> Requirement:
    """Parse required changelog fields from a requirement's Markdown block."""
    properties = {
        match.group("name").strip(): match.group("value").strip()
        for line in body.splitlines()
        if (match := PROPERTY_PATTERN.fullmatch(line)) is not None
    }
    missing = [name for name in ("Title", "Status", "Owner") if name not in properties]
    if missing:
        raise ValueError(f"Requirement {identifier} is missing: {', '.join(missing)}.")
    rationale_match = re.search(r"^### Rationale\s*$\n(?P<text>.*?)(?=^### |^---\s*$|\Z)", body, re.MULTILINE | re.DOTALL)
    rationale = rationale_match.group("text").strip() if rationale_match is not None else ""
    return Requirement(identifier, properties["Title"], properties["Status"], properties["Owner"], rationale, source_file)


def requirement_changes(
    previous: dict[RequirementKey, Requirement], current: dict[RequirementKey, Requirement]
) -> dict[str, list[Requirement]]:
    """Classify requirements according to their state at the release boundary."""
    return {
        "Added": [current[key] for key in sorted(current.keys() - previous.keys(), key=requirement_key_sort_key)],
        "Updated": [
            current[key]
            for key in sorted(current.keys() & previous.keys(), key=requirement_key_sort_key)
            if current[key] != previous[key]
        ],
        "Deleted": [previous[key] for key in sorted(previous.keys() - current.keys(), key=requirement_key_sort_key)],
    }


def requirement_key_sort_key(key: RequirementKey) -> tuple[str, str]:
    """Provide a stable ordering for requirements with duplicate IDs in different files."""
    return str(key[0]), key[1]


def group_sort_key(source_file: Path) -> tuple[int, str]:
    """Order foundational requirement groups before alphabetically ordered format groups."""
    try:
        return GROUP_ORDER.index(source_file), ""
    except ValueError:
        return len(GROUP_ORDER), str(source_file)


def markdown_cell(value: str) -> str:
    """Make a field safe for a single-line Markdown table cell."""
    return value.replace("|", "\\|").replace("\n", " ")


def render_draft(
    version: Version,
    release_date: date,
    comparison_url: str | None,
    changes: dict[str, list[Requirement]],
    groups: dict[Path, RequirementGroup],
) -> str:
    """Render the reviewable changelog-draft Markdown document."""
    lines = [f"# Changelog draft: {version}", "", release_heading(version, release_date, comparison_url), ""]
    source_files = sorted(
        {item.source_file for requirements in changes.values() for item in requirements}, key=group_sort_key
    )
    for source_file in source_files:
        group = groups[source_file]
        lines.extend([f"### {group.title}", "", group.description, ""])
        for change_kind, requirements in changes.items():
            grouped_requirements = [item for item in requirements if item.source_file == source_file]
            if not grouped_requirements:
                continue
            lines.extend([f"#### {change_kind}", "", "| ID | Title | Status | Owner |", "|---|---|---|---|"])
            lines.extend(
                f"| {item.identifier} | {markdown_cell(item.title)} | {markdown_cell(item.status)} | {markdown_cell(item.owner)} |"
                for item in grouped_requirements
            )
            lines.append("")

    lines.extend(["### Requirement details", ""])
    for source_file in source_files:
        group = groups[source_file]
        lines.extend([f"#### {group.title}", "", group.description, ""])
        for requirements in changes.values():
            for item in requirements:
                if item.source_file != source_file:
                    continue
                lines.extend([f"##### {item.identifier} — {item.title} [{item.status}]", "", "###### Rationale", ""])
                lines.append(item.rationale or "No rationale provided.")
                lines.append("")
    return "\n".join(lines)


def requirements_diff(project_root: Path, baseline_tag: str | None, first_release: bool) -> str:
    """Return the complete requirements diff for the proposed release."""
    if first_release:
        return run_git(project_root, "diff", "--root", "HEAD", "--", "requirements")
    if baseline_tag is None:
        raise ValueError("A non-initial release requires a version baseline tag.")
    return run_git(project_root, "diff", f"{baseline_tag}..HEAD", "--", "requirements")


def changelog_is_empty(project_root: Path) -> bool:
    """Return whether CHANGELOG.md is absent or contains no meaningful text."""
    changelog = project_root / "CHANGELOG.md"
    return not changelog.exists() or not changelog.read_text(encoding="utf-8").strip()


def main() -> int:
    """Generate the next changelog draft and its source requirements diff."""
    arguments = parse_arguments()
    tags = release_tags(PROJECT_ROOT)
    version, baseline_tag = next_release(tags, arguments.increment)
    first_release = baseline_tag is None or changelog_is_empty(PROJECT_ROOT)
    if first_release:
        previous_files: dict[Path, str] = {}
    else:
        if baseline_tag is None:
            raise ValueError("A non-initial release requires a version baseline tag.")
        previous_files = requirement_files_at_revision(PROJECT_ROOT, baseline_tag)
    current = parse_requirements(requirement_files_at_revision(PROJECT_ROOT, "HEAD"))
    previous = parse_requirements(previous_files)
    changes = requirement_changes(previous, current)
    groups = requirement_groups(PROJECT_ROOT, "HEAD")
    comparison_url = None if baseline_tag is None else github_compare_url(PROJECT_ROOT, baseline_tag, version)
    output_directory = PROJECT_ROOT / OUTPUT_DIRECTORY
    output_directory.mkdir(parents=True, exist_ok=True)
    diff_path = output_directory / f"{version}.requirements.diff"
    draft_path = output_directory / f"{version}.md"
    diff_path.write_text(
        requirements_diff(PROJECT_ROOT, baseline_tag, first_release), encoding="utf-8"
    )
    draft_path.write_text(render_draft(version, date.today(), comparison_url, changes, groups), encoding="utf-8")
    print(f"Release tag: v{version}")
    print(f"Changelog draft: {draft_path.relative_to(PROJECT_ROOT)}")
    print(f"Requirements diff: {diff_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
