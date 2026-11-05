"""Deterministic in-memory fixture data used by the demo project and its tests."""

from __future__ import annotations

from datetime import date

from .models import Task

SEED_TASKS: tuple[Task, ...] = (
    Task("TASK-001", "整理季度发布说明", "open", 3, date(2026, 11, 3)),
    Task("TASK-002", "修复登录页超时", "open", 5, date(2026, 11, 2)),
    Task("TASK-003", "补充导入器单测", "open", 4, date(2026, 11, 8)),
    Task("TASK-004", "归档旧版帮助中心", "done", 2, date(2026, 10, 30)),
    Task("TASK-005", "评审 API 契约", "open", 5, None),
    Task("TASK-006", "更新部署手册", "done", 3, date(2026, 11, 1)),
    Task("TASK-007", "复盘线上告警", "open", 1, date(2026, 11, 5)),
    Task("TASK-008", "清理无用依赖", "done", 4, date(2026, 11, 12)),
)


class InMemoryTaskRepository:
    """Read-only repository; the demo keeps persistence intentionally simple."""

    def __init__(self, tasks: tuple[Task, ...] = SEED_TASKS) -> None:
        self._tasks = tuple(tasks)

    def all(self) -> tuple[Task, ...]:
        return self._tasks

    def get(self, task_id: str) -> Task:
        for task in self._tasks:
            if task.id == task_id:
                return task
        raise KeyError(task_id)
