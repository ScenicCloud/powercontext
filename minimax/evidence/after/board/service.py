"""Task board service.

The implementation follows the current specification in ``specs/service_spec.md``
and the public contract in ``specs/api_contract.md``.
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
        due_before: date | str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[Task]:
        """List tasks after applying the filters of REQ-BOARD-006.

        REQ-BOARD-006: ``due_before`` keeps only tasks whose due date is
        strictly earlier than the supplied date. Tasks without a due date are
        excluded when the filter is active.
        REQ-BOARD-007: invalid arguments raise ``ValueError`` before any task
        is returned.
        REQ-BOARD-008: results are ordered by priority descending, then due
        date ascending (tasks without a due date last), then task id ascending.
        REQ-BOARD-009: ``limit`` is applied after filtering and ordering.
        """

        normalized_status = self._validate_status(status)
        normalized_priority = self._validate_priority(priority)
        normalized_due_before = self._parse_due_before(due_before)
        normalized_limit = self._validate_limit(limit)

        tasks = [
            task
            for task in self._repository.all()
            if self._matches(
                task,
                status=normalized_status,
                priority=normalized_priority,
                due_before=normalized_due_before,
            )
        ]
        tasks.sort(key=self._sort_key)
        return tasks[:normalized_limit]

    @staticmethod
    def _matches(
        task: Task,
        *,
        status: str | None,
        priority: int | None,
        due_before: date | None,
    ) -> bool:
        if status is not None and task.status != status:
            return False
        if priority is not None and task.priority != priority:
            return False
        if due_before is not None:
            if task.due is None or task.due >= due_before:
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
    def _parse_due_before(due_before: date | str | None) -> date | None:
        if due_before is None:
            return None
        if isinstance(due_before, date):
            return due_before
        if isinstance(due_before, str):
            try:
                return date.fromisoformat(due_before)
            except ValueError as error:
                raise ValueError("due_before must be an ISO date (YYYY-MM-DD)") from error
        raise ValueError("due_before must be a date or an ISO date string (YYYY-MM-DD)")

    @staticmethod
    def _validate_limit(limit: int) -> int:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        return limit
