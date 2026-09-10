"""Static checks for the version-tagged GHCR release workflow."""

from __future__ import annotations

from pathlib import Path
import unittest


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
