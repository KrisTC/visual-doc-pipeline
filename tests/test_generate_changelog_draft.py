"""Tests for requirements-based changelog draft generation."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import generate_changelog_draft


class GenerateChangelogDraftTests(unittest.TestCase):
    # Verifies TR-2026-09-11-03: version selection follows supported release tags.
    def test_selects_next_minor_version_from_highest_release_tag(self) -> None:
        version, tag = generate_changelog_draft.next_release(
            {
                generate_changelog_draft.Version(1, 2, 5): "v1.2.5",
                generate_changelog_draft.Version(2, 0, 0): "v2.0.0",
            },
            None,
        )

        self.assertEqual(generate_changelog_draft.Version(2, 1, 0), version)
        self.assertEqual("v2.0.0", tag)

    # Verifies TR-2026-09-11-03: major mode and no-tag initialization are supported.
    def test_selects_major_or_initial_version(self) -> None:
        major_version, tag = generate_changelog_draft.next_release(
            {generate_changelog_draft.Version(2, 4, 9): "v2.4.9"}, "major"
        )

        self.assertEqual(generate_changelog_draft.Version(3, 0, 0), major_version)
        self.assertEqual("v2.4.9", tag)
        self.assertEqual(
            (generate_changelog_draft.Version(0, 1, 0), None),
            generate_changelog_draft.next_release({}, None),
        )

    # Verifies TR-2026-09-11-03: only semantic-version release tags are eligible.
    def test_ignores_non_semantic_version_tags(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with patch.object(
                generate_changelog_draft,
                "run_git",
                return_value="v1.2.3\nv01.2.3\nv1.2\nrelease-2.0.0\n",
            ):
                tags = generate_changelog_draft.release_tags(root)

        self.assertEqual({generate_changelog_draft.Version(1, 2, 3): "v1.2.3"}, tags)

    # Verifies TR-2026-09-11-03: release headings use an origin-derived GitHub comparison link.
    def test_renders_copy_ready_linked_release_heading(self) -> None:
        version = generate_changelog_draft.Version(0, 2, 0)
        with patch.object(
            generate_changelog_draft,
            "run_git",
            return_value="git@github.com:KrisTC/visual-doc-pipeline.git\n",
        ):
            comparison_url = generate_changelog_draft.github_compare_url(Path("."), "v0.1.0", version)

        self.assertEqual(
            "## [0.2.0](https://github.com/KrisTC/visual-doc-pipeline/compare/v0.1.0...v0.2.0) (2026-09-11)",
            generate_changelog_draft.release_heading(version, date(2026, 9, 11), comparison_url),
        )
        self.assertEqual("## 0.2.0 (2026-09-11)", generate_changelog_draft.release_heading(version, date(2026, 9, 11), None))

    # Verifies TR-2026-09-11-03: an absent changelog is an empty changelog.
    def test_treats_absent_or_blank_changelog_as_empty(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.assertTrue(generate_changelog_draft.changelog_is_empty(root))
            (root / "CHANGELOG.md").write_text(" \n", encoding="utf-8")
            self.assertTrue(generate_changelog_draft.changelog_is_empty(root))
            (root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
            self.assertFalse(generate_changelog_draft.changelog_is_empty(root))

    # Verifies TR-2026-09-11-03: additions, updates, and deletions use the right revision.
    def test_classifies_requirement_changes(self) -> None:
        old = generate_changelog_draft.Requirement("TR-2026-01-01-01", "Old", "Proposed", "KrisTC", "Old rationale.")
        updated = generate_changelog_draft.Requirement("TR-2026-01-01-01", "New", "Implemented", "KrisTC", "New rationale.")
        added = generate_changelog_draft.Requirement("TR-2026-01-01-02", "Added", "Proposed", "KrisTC", "Added rationale.")

        changes = generate_changelog_draft.requirement_changes(
            {
                (Path("requirements/example.md"), old.identifier): old,
                (Path("requirements/example.md"), "TR-2026-01-01-03"): old,
            },
            {
                (Path("requirements/example.md"), updated.identifier): updated,
                (Path("requirements/example.md"), added.identifier): added,
            },
        )

        self.assertEqual([added], changes["Added"])
        self.assertEqual([updated], changes["Updated"])
        self.assertEqual([old], changes["Deleted"])

    # Verifies TR-2026-09-11-03: duplicate IDs in separate requirement files remain distinct.
    def test_parses_duplicate_ids_in_different_requirement_files(self) -> None:
        contents = """## FR-2026-01-01-01

| Property | Value |
|----------|-------|
| Title | Example |
| Owner | KrisTC |
| Status | Proposed |

### Rationale

Example rationale.
"""

        requirements = generate_changelog_draft.parse_requirements(
            {
                Path("requirements/one.md"): contents,
                Path("requirements/two.md"): contents.replace("Example", "Different example", 1),
            }
        )

        self.assertEqual(2, len(requirements))

    # Verifies TR-2026-09-11-03: groups use titles and scope descriptions from requirements/README.md.
    def test_reads_requirement_group_labels_from_requirements_index(self) -> None:
        with patch.object(
            generate_changelog_draft,
            "run_git",
            return_value="| Shared pipeline | `general-requirements.md` |\n",
        ):
            groups = generate_changelog_draft.requirement_groups(Path("."), "HEAD")

        self.assertEqual(
            generate_changelog_draft.RequirementGroup("General Requirements", "Requirements for Shared pipeline."),
            groups[Path("requirements/general-requirements.md")],
        )

    # Verifies TR-2026-09-11-03: foundational groups precede other requirement files.
    def test_orders_foundational_groups_before_other_requirement_files(self) -> None:
        source_files = [
            Path("requirements/word-requirements.md"),
            Path("requirements/general-requirements.md"),
            Path("requirements/security-requirements.md"),
            Path("requirements/excel-requirements.md"),
            Path("requirements/text-replacement-requirements.md"),
            Path("requirements/technical-requirements.md"),
        ]

        self.assertEqual(
            [
                Path("requirements/security-requirements.md"),
                Path("requirements/technical-requirements.md"),
                Path("requirements/general-requirements.md"),
                Path("requirements/text-replacement-requirements.md"),
                Path("requirements/excel-requirements.md"),
                Path("requirements/word-requirements.md"),
            ],
            sorted(source_files, key=generate_changelog_draft.group_sort_key),
        )

    # Verifies TR-2026-09-11-03: tables and detailed entries expose only required fields.
    def test_renders_required_summary_and_rationale(self) -> None:
        requirement = generate_changelog_draft.Requirement(
            "TR-2026-01-01-01", "Draft generator", "Proposed", "KrisTC", "Supports review.", Path("requirements/technical-requirements.md")
        )
        second_requirement = generate_changelog_draft.Requirement(
            "FR-2026-01-01-01", "General behavior", "Implemented", "KrisTC", "General rationale.", Path("requirements/general-requirements.md")
        )
        groups = {
            Path("requirements/general-requirements.md"): generate_changelog_draft.RequirementGroup("General Requirements", "Requirements for shared behavior."),
            Path("requirements/technical-requirements.md"): generate_changelog_draft.RequirementGroup("Technical Requirements", "Requirements for technical behavior."),
        }

        draft = generate_changelog_draft.render_draft(
            generate_changelog_draft.Version(0, 1, 0),
            date(2026, 9, 11),
            None,
            {"Added": [requirement, second_requirement], "Updated": [], "Deleted": []},
            groups,
        )

        self.assertIn("## 0.1.0 (2026-09-11)", draft)
        self.assertIn("| ID | Title | Status | Owner |", draft)
        self.assertIn("|---|---|---|---|", draft)
        self.assertIn("### General Requirements", draft)
        self.assertIn("Requirements for shared behavior.", draft)
        self.assertIn("### Technical Requirements", draft)
        self.assertIn("#### General Requirements", draft)
        self.assertIn("#### Technical Requirements", draft)
        self.assertEqual(2, draft.count("Requirements for shared behavior."))
        self.assertIn("##### TR-2026-01-01-01 — Draft generator [Proposed]", draft)
        self.assertIn("###### Rationale\n\nSupports review.", draft)
        self.assertNotIn("Status: Proposed", draft)
        self.assertNotIn("Source", draft)
