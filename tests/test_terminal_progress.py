"""Tests for non-misleading terminal progress rendering."""

from __future__ import annotations

import unittest

from rich.progress import Progress

from pipeline.terminal_progress import CompletionColumn


class CompletionColumnTests(unittest.TestCase):
    # Verifies FR-2026-09-03-01.
    def test_indeterminate_nested_task_has_no_completion_percentage(self) -> None:
        progress = Progress()
        task_id = progress.add_task("embedded workbook", total=None)
        progress.advance(task_id, 27_895)

        rendered = CompletionColumn().render(progress.tasks[task_id])

        self.assertEqual("—", rendered.plain)


if __name__ == "__main__":
    unittest.main()
