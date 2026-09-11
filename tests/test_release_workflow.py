"""Static checks for the version-tagged GHCR release workflow."""

from __future__ import annotations

from pathlib import Path
import unittest

from scripts import release_notes


ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


class ReleaseWorkflowTests(unittest.TestCase):
    """Verify the release workflow's required publication controls."""

    # Verifies TR-2026-09-10-02.
    def test_publishes_versioned_cpu_and_gpu_images_from_main_tip_tags(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("tags:\n      - \"v*\"", workflow)
        self.assertIn("contents: write", workflow)
        self.assertIn("packages: write", workflow)
        self.assertIn("git/ref/heads/main", workflow)
        self.assertIn("Release tag must resolve to the current main tip.", workflow)
        self.assertIn("ghcr.io/%s/visual-doc-pipeline-cpu", workflow)
        self.assertIn("ghcr.io/%s/visual-doc-pipeline-gpu", workflow)
        self.assertIn("--target cpu", workflow)
        self.assertIn("--target gpu", workflow)
        self.assertIn("--tag \"$IMAGE:$VERSION\" --tag \"$IMAGE:latest\" --push", workflow)
        self.assertIn("gh release create", workflow)
        self.assertIn("--verify-tag", workflow)
        self.assertIn("persist-credentials: false", workflow)

    # Verifies TR-2026-09-11-01.
    def test_published_images_have_release_oci_annotations(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn('source_url="https://github.com/$GITHUB_REPOSITORY"', workflow)
        self.assertIn('printf \'revision=%s\\n\' "$tag_commit"', workflow)
        self.assertIn('printf \'source_url=%s\\n\' "$source_url"', workflow)

        shared_labels = (
            '--label org.opencontainers.image.title="visual-doc-pipeline"',
            '--label org.opencontainers.image.description="Configurable pipeline '
            'for visible-text replacement in documents and images."',
            '--label org.opencontainers.image.source="$SOURCE_URL"',
            '--label org.opencontainers.image.url="$SOURCE_URL"',
            '--label org.opencontainers.image.licenses="Apache-2.0"',
            '--label org.opencontainers.image.version="$VERSION"',
            '--label org.opencontainers.image.revision="$REVISION"',
        )
        for label in shared_labels:
            self.assertEqual(workflow.count(label), 2)

        self.assertEqual(
            workflow.count('--label org.opencontainers.image.variant="cpu"'), 1
        )
        self.assertEqual(
            workflow.count('--label org.opencontainers.image.variant="gpu"'), 1
        )

    # Verifies TR-2026-09-11-02 and TR-2026-09-12-01.
    def test_release_notes_reference_versioned_cpu_and_gpu_images(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("Validate and extract the matching changelog entry", workflow)
        self.assertLess(
            workflow.index("Validate and extract the matching changelog entry"),
            workflow.index("Log in to GitHub Container Registry"),
        )
        self.assertIn("Generate release notes from the changelog and image references", workflow)
        self.assertIn("scripts/release_notes.py extract", workflow)
        self.assertIn("scripts/release_notes.py compose", workflow)
        self.assertIn('gh release edit "$VERSION" --repo "$GITHUB_REPOSITORY" --notes-file "$NOTES_FILE"', workflow)
        self.assertIn('gh release create "$VERSION" --repo "$GITHUB_REPOSITORY" --verify-tag --title "$VERSION" --notes-file "$NOTES_FILE"', workflow)

    # Verifies TR-2026-09-12-01: literal entries include nested headings until the next release.
    def test_extracts_literal_changelog_entry_until_next_release(self) -> None:
        changelog = """# Changelog

## 1.2.3 (2026-09-12)

Summary.

### Added

#### Detail

## [1.2.2](https://github.com/example/repository/compare/v1.2.1...v1.2.2) (2026-09-11)

Previous release.
"""

        self.assertEqual(
            "## 1.2.3 (2026-09-12)\n\nSummary.\n\n### Added\n\n#### Detail\n",
            release_notes.extract_changelog_entry(changelog, "v1.2.3"),
        )

    # Verifies TR-2026-09-12-01: linked headings and end-of-file entries are supported.
    def test_extracts_linked_changelog_entry_through_end_of_file(self) -> None:
        changelog = """# Changelog

## [1.2.3](https://github.com/example/repository/compare/v1.2.2...v1.2.3) (2026-09-12)

### Changed

Linked release entry.
"""

        self.assertEqual(
            "## [1.2.3](https://github.com/example/repository/compare/v1.2.2...v1.2.3) (2026-09-12)\n\n### Changed\n\nLinked release entry.\n",
            release_notes.extract_changelog_entry(changelog, "v1.2.3"),
        )

    # Verifies TR-2026-09-12-01: invalid or absent release entries fail before publication.
    def test_rejects_invalid_tags_and_missing_changelog_entries(self) -> None:
        with self.assertRaisesRegex(ValueError, "v<major>"):
            release_notes.extract_changelog_entry("# Changelog\n", "vlatest")
        with self.assertRaisesRegex(ValueError, "no release entry for 1.2.3"):
            release_notes.extract_changelog_entry("# Changelog\n", "v1.2.3")

    # Verifies TR-2026-09-12-01: reruns replace only workflow-managed content.
    def test_composes_idempotent_release_notes(self) -> None:
        changelog_entry = "## 1.2.3 (2026-09-12)\n\n### Added\n\nFeature.\n"
        first_notes = release_notes.compose_release_notes(
            "Maintainer notes.\n\n## Container images\n\n- CPU: `old`\n- GPU: `old`\n",
            changelog_entry,
            "ghcr.io/example/visual-doc-pipeline-cpu",
            "ghcr.io/example/visual-doc-pipeline-gpu",
            "v1.2.3",
        )
        rerun_notes = release_notes.compose_release_notes(
            first_notes,
            changelog_entry,
            "ghcr.io/example/visual-doc-pipeline-cpu",
            "ghcr.io/example/visual-doc-pipeline-gpu",
            "v1.2.3",
        )

        self.assertEqual(first_notes, rerun_notes)
        self.assertIn("Maintainer notes.", rerun_notes)
        self.assertNotIn("`old`", rerun_notes)
        self.assertEqual(1, rerun_notes.count("## 1.2.3 (2026-09-12)"))
        self.assertEqual(1, rerun_notes.count("## Container images"))
