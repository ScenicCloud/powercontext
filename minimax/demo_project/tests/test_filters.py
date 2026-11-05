"""Regression tests: behavior that must keep working after the change.

This file is identical in the before and after snapshots.
"""

from __future__ import annotations

from board import TaskService


def test_list_tasks_returns_all_tasks_by_default() -> None:
    tasks = TaskService().list_tasks()
    assert len(tasks) == 8


def test_status_filter_keeps_existing_behavior() -> None:
    tasks = TaskService().list_tasks(status="open")
    assert [task.id for task in tasks] == ["TASK-002", "TASK-005", "TASK-003", "TASK-001", "TASK-007"]


def test_priority_filter_keeps_existing_behavior() -> None:
    tasks = TaskService().list_tasks(priority=5)
    assert [task.id for task in tasks] == ["TASK-002", "TASK-005"]


def test_status_and_priority_filters_combine() -> None:
    tasks = TaskService().list_tasks(status="done", priority=3)
    assert [task.id for task in tasks] == ["TASK-006"]


def test_sorting_prefers_priority_then_due_date_then_id() -> None:
    tasks = TaskService().list_tasks()
    assert [task.id for task in tasks] == [
        "TASK-002",
        "TASK-005",
        "TASK-003",
        "TASK-008",
        "TASK-006",
        "TASK-001",
        "TASK-004",
        "TASK-007",
    ]


def test_limit_applies_after_ordering() -> None:
    tasks = TaskService().list_tasks(limit=3)
    assert [task.id for task in tasks] == ["TASK-002", "TASK-005", "TASK-003"]


def test_get_task_returns_the_requested_task() -> None:
    task = TaskService().get_task("TASK-007")
    assert task.title == "复盘线上告警"


def test_get_unknown_task_raises_key_error() -> None:
    try:
        TaskService().get_task("TASK-999")
    except KeyError as error:
        assert error.args == ("TASK-999",)
    else:  # pragma: no cover - explicit failure message
        raise AssertionError("KeyError was not raised")
