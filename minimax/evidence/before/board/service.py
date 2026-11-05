"""Task board service — snapshot before the SDD task was implemented.

This file is the exact pre-change copy of ``demo_project/board/service.py``.
It implements REQ-BOARD-001 through REQ-BOARD-005 and REQ-BOARD-008/009, but
it does not accept a ``due_before`` argument yet. The demo restores this file
to reproduce the failing target tests.
"""

from __future__ import annotations

from datetime import date

from .models import PRIORITY_VALUES, TASK_STATUSES, Task
from .repository import InMemoryTaskRepository

DEFAULT_LIMIT = 20


class TaskService:
    """Read operations for the task board (REQ-BOARD-001)."""

    def __init__(self, repository: InMemoryTaskRepository | None = None) -> None:
        self._repository = repository or InMemoryTaskRepository()

    def get_task(self, task_id: str) -> Task:
        """Return one task or raise ``KeyError`` (REQ-BOARD-002)."""

        return self._repository.get(task_id)

    def list_tasks(
        self,
        *,
        status: str | None = None,
        priority: int | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[Task]:
        """List tasks after applying the current filters (REQ-BOARD-003/004)."""

        normalized_status = self._validate_status(status)
        normalized_priority = self._validate_priority(priority)
        normalized_limit = self._validate_limit(limit)

        tasks = [
            task
            for task in self._repository.all()
            if self._matches(task, status=normalized_status, priority=normalized_priority)
        ]
        tasks.sort(key=self._sort_key)
        return tasks[:normalized_limit]

    @staticmethod
    def _matches(task: Task, *, status: str | None, priority: int | None) -> bool:
        if status is not None and task.status != status:
            return False
        if priority is not None and task.priority != priority:
            return False
        return True

    @staticmethod
    def _sort_key(task: Task) -> tuple[int, date, str]:
        return (-task.priority, task.due or date.max, task.id)

    @staticmethod
    def _validate_status(status: str | None) -> str | None:
        if status is None:
            return None
        if status not in TASK_STATUSES:
            raise ValueError(f"status must be one of {TASK_STATUSES}, got {status!r}")
        return status

    @staticmethod
    def _validate_priority(priority: int | None) -> int | None:
        if priority is None:
            return None
        if isinstance(priority, bool) or not isinstance(priority, int) or priority not in PRIORITY_VALUES:
            raise ValueError(f"priority must be one of {PRIORITY_VALUES}, got {priority!r}")
        return priority

    @staticmethod
    def _validate_limit(limit: int) -> int:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        return limit
