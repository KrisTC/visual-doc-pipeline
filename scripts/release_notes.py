#!/usr/bin/env python3
"""Extract changelog entries and compose GitHub Release notes."""

from __future__ import annotations

import argparse
from pathlib import Path
import re


RELEASE_TAG_PATTERN = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
RELEASE_HEADING_PATTERN = re.compile(
    r"^##\s+(?:(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?=$|\s)|"
    r"\[(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\]\([^\n)]*\)(?=$|\s))",
    re.MULTILINE,
)


def version_from_tag(tag: str) -> str:
    """Return the semantic version encoded in a supported release tag."""
    match = RELEASE_TAG_PATTERN.fullmatch(tag)
    if match is None:
        raise ValueError(f"Release tag must be v<major>.<minor>.<patch>, got {tag!r}.")
    return tag[1:]


def release_heading_pattern(version: str) -> re.Pattern[str]:
    """Match an H2 changelog heading for exactly one release version."""
    escaped_version = re.escape(version)
    return re.compile(
        rf"^##\s+(?:{escaped_version}(?=$|\s)|"
        rf"\[{escaped_version}\]\([^\n)]*\)(?=$|\s))",
        re.MULTILINE,
    )


def extract_changelog_entry(changelog: str, tag: str) -> str:
    """Extract the complete changelog entry corresponding to *tag*."""
    version = version_from_tag(tag)
    entry_match = release_heading_pattern(version).search(changelog)
    if entry_match is None:
        raise ValueError(f"CHANGELOG.md has no release entry for {version}.")

    next_entry_match = RELEASE_HEADING_PATTERN.search(changelog, entry_match.end())
    entry_end = next_entry_match.start() if next_entry_match is not None else len(changelog)
    return changelog[entry_match.start() : entry_end].rstrip() + "\n"


def managed_block(name: str, content: str) -> str:
    """Return a bounded, workflow-managed release-notes block."""
    return (
        f"<!-- visual-doc-pipeline:{name}:start -->\n"
        f"{content.rstrip()}\n"
        f"<!-- visual-doc-pipeline:{name}:end -->"
    )


def remove_managed_block(body: str, name: str) -> str:
    """Remove one prior workflow-managed release-notes block."""
    escaped_name = re.escape(name)
    pattern = re.compile(
        rf"(?ms)^[ \t]*<!-- visual-doc-pipeline:{escaped_name}:start -->\n"
        rf".*?^[ \t]*<!-- visual-doc-pipeline:{escaped_name}:end -->[ \t]*\n?"
    )
    return pattern.sub("", body)


def compose_release_notes(
    existing_body: str, changelog_entry: str, cpu_image: str, gpu_image: str, version: str
) -> str:
    """Replace workflow-managed notes while retaining other release-note content."""
    body = remove_managed_block(existing_body, "changelog")
    body = remove_managed_block(body, "container-images")
    body = re.sub(
        r"(?ms)^## Container images\s*$.*?(?=^##\s|\Z)",
        "",
        body,
    ).strip()
    images = (
        "## Container images\n\n"
        f"- CPU: `{cpu_image}:{version}`\n"
        f"- GPU: `{gpu_image}:{version}`\n"
    )
    parts = [
        body,
        managed_block("container-images", images),
        managed_block("changelog", changelog_entry),
    ]
    return "\n\n".join(part for part in parts if part) + "\n"


def parse_arguments() -> argparse.Namespace:
    """Parse the release-notes helper command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract_parser = subparsers.add_parser("extract")
    extract_parser.add_argument("--changelog", required=True, type=Path)
    extract_parser.add_argument("--tag", required=True)
    extract_parser.add_argument("--output", required=True, type=Path)

    compose_parser = subparsers.add_parser("compose")
    compose_parser.add_argument("--existing", required=True, type=Path)
    compose_parser.add_argument("--changelog-entry", required=True, type=Path)
    compose_parser.add_argument("--cpu-image", required=True)
    compose_parser.add_argument("--gpu-image", required=True)
    compose_parser.add_argument("--version", required=True)
    compose_parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    """Run the requested extraction or release-notes composition command."""
    arguments = parse_arguments()
    if arguments.command == "extract":
        changelog = arguments.changelog.read_text(encoding="utf-8")
        arguments.output.write_text(
            extract_changelog_entry(changelog, arguments.tag), encoding="utf-8"
        )
        return

    existing_body = arguments.existing.read_text(encoding="utf-8")
    changelog_entry = arguments.changelog_entry.read_text(encoding="utf-8")
    arguments.output.write_text(
        compose_release_notes(
            existing_body,
            changelog_entry,
            arguments.cpu_image,
            arguments.gpu_image,
            arguments.version,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
