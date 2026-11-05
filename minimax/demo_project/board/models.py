"""Domain model for the MiniTask board demo project."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

TASK_STATUSES = ("open", "done")
PRIORITY_VALUES = (1, 2, 3, 4, 5)


@dataclass(frozen=True)
class Task:
    """A single board task.

    ``due`` is optional. Sorting and filtering must stay stable when a task
    has no due date.
    """

    id: str
    title: str
    status: str
    priority: int
    due: date | None = None
