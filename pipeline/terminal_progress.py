"""Bounded Rich progress displays shared by command-line workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from math import ceil
from time import monotonic

from rich.progress import (
    BarColumn,
    Progress,
    ProgressColumn,
    Task,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Column
from rich.text import Text


class EtaColumn(ProgressColumn):
    """Render a compact, explicit unknown ETA instead of Rich's placeholder."""

    def render(self, task: Task) -> Text:
        remaining = task.time_remaining
        if remaining is None:
            return Text("—")
        return Text(str(timedelta(seconds=ceil(remaining))))


class CompletionColumn(ProgressColumn):
    """Render no percentage for a task whose total is not known."""

    def render(self, task: Task) -> Text:
        if task.total is None:
            return Text("—")
        return Text(f"{task.percentage:>3.0f}%")


@dataclass(slots=True)
class CurrentProgress:
    """Compatibility adapter for work that advances the active task."""

    display: "LiveProgress"

    def set_postfix_str(self, text: str, refresh: bool = True) -> None:
        """Show the active work-item label."""
        self.display.set_current_label(text)

    def update(self, count: float | None = None) -> None:
        """Advance the active task."""
        self.display.advance_current(1 if count is None else count)

    def close(self) -> None:
        """The shared live display owns row lifetime."""
        return None


class LiveProgress:
    """One Rich live display with overall, current, and nested rows."""

    def __init__(self) -> None:
        self._progress = Progress(
            TextColumn(
                "[bold]{task.description}",
                table_column=Column(max_width=40, overflow="ellipsis"),
            ),
            BarColumn(),
            CompletionColumn(),
            TimeElapsedColumn(),
            TextColumn("ETA"),
            EtaColumn(),
            TextColumn("{task.fields[detail]}"),
            transient=True,
            redirect_stdout=True,
            redirect_stderr=True,
        )
        self._overall: TaskID | None = None
        self._current: TaskID | None = None
        self._nested: TaskID | None = None
        self._download_started: float | None = None
        self._download_initial = 0

    def __enter__(self) -> "LiveProgress":
        self._progress.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._progress.stop()

    @property
    def current(self) -> CurrentProgress:
        """Return an adapter for legacy single-task reporting boundaries."""
        return CurrentProgress(self)

    def start_overall(self, total: int, unit: str = "task") -> None:
        """Show the complete invocation's task count."""
        self._overall = self._progress.add_task(
            "Overall", total=total, detail=unit, visible=True
        )

    def advance_overall(self, count: int = 1) -> None:
        if self._overall is not None:
            self._progress.advance(self._overall, count)

    def set_overall_from_current(self, completed_sources: int) -> None:
        """Map active-task completion into its source's 100-unit overall share."""
        if self._overall is None or self._current is None:
            return
        task = self._progress.tasks[self._current]
        if task.total is None or task.total == 0:
            return
        completed = completed_sources * 100 + int(task.completed * 100 / task.total)
        self._progress.update(self._overall, completed=completed)

    def complete_overall_source(self, completed_sources: int) -> None:
        """Finish one source share after either success or isolated failure."""
        if self._overall is not None:
            self._progress.update(self._overall, completed=(completed_sources + 1) * 100)

    def start_current(self, name: str, total: int | None, unit: str) -> CurrentProgress:
        """Reset and show the active root task."""
        self._current = self._reset_task(self._current, name, total, unit)
        return self.current

    def set_current_label(self, label: str) -> None:
        if self._current is not None:
            self._progress.update(
                self._current,
                detail=label,
            )

    def advance_current(self, count: float = 1) -> None:
        if self._current is not None:
            self._progress.advance(self._current, count)

    def clear_current(self) -> None:
        if self._current is not None:
            self._progress.update(self._current, visible=False)
        self.clear_nested()

    def start_nested(self, name: str, total: int | None = 3, unit: str = "stage") -> None:
        """Show one bounded nested-object operation inside a document."""
        self._nested = self._reset_task(self._nested, f"{name}", total, unit)

    def advance_nested(self, label: str) -> None:
        if self._nested is not None:
            self._progress.update(self._nested, description=f"{label}")
            self._progress.advance(self._nested)

    def clear_nested(self) -> None:
        if self._nested is not None:
            self._progress.update(self._nested, visible=False)

    def start_download(self, filename: str, total: int | None, initial: int = 0) -> CurrentProgress:
        """Show byte-based progress for the active artifact."""
        self._download_started = monotonic()
        self._download_initial = initial
        current = self.start_current(filename, total, "bytes")
        if initial:
            self.advance_current(initial)
        return current

    def advance_download(self, count: int) -> None:
        """Advance a byte download and display its measured transfer rate."""
        if self._current is None:
            return
        elapsed = max(monotonic() - (self._download_started or monotonic()), 0.001)
        completed = self._progress.tasks[self._current].completed
        rate = max(completed - self._download_initial, 0) / elapsed
        self._progress.update(self._current, detail=f"{rate / 1024 / 1024:.1f} MiB/s")
        self._progress.advance(self._current, count)

    def _reset_task(
        self,
        task_id: TaskID | None,
        description: str,
        total: int | None,
        detail: str,
    ) -> TaskID:
        if task_id is None:
            return self._progress.add_task(description, total=total, detail=detail, visible=True)
        self._progress.reset(
            task_id,
            total=total,
            completed=0,
            visible=True,
            description=description,
            detail=detail,
        )
        return task_id
