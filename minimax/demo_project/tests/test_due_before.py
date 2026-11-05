"""Target tests for the ``due_before`` filter (REQ-BOARD-006 / 007).

The same file is used before and after the change. Before the change every
test that passes ``due_before`` fails because the parameter does not exist;
the regression tests in this project pass in both snapshots.
"""

from __future__ import annotations

from datetime import date

import pytest

from board import TaskService


def test_due_before_keeps_only_tasks_strictly_before_the_date() -> None:
    tasks = TaskService().list_tasks(due_before=date(2026, 11, 5))
    assert [task.id for task in tasks] == ["TASK-002", "TASK-006", "TASK-001", "TASK-004"]


def test_due_before_excludes_the_boundary_date() -> None:
    tasks = TaskService().list_tasks(due_before=date(2026, 11, 5))
    assert "TASK-007" not in [task.id for task in tasks]


def test_due_before_accepts_an_iso_date_string() -> None:
    by_string = TaskService().list_tasks(due_before="2026-11-05")
    by_date = TaskService().list_tasks(due_before=date(2026, 11, 5))
    assert by_string == by_date


def test_due_before_excludes_tasks_without_a_due_date() -> None:
    tasks = TaskService().list_tasks(due_before=date(2026, 12, 31))
    assert "TASK-005" not in [task.id for task in tasks]


def test_due_before_combines_with_status_filter() -> None:
    tasks = TaskService().list_tasks(status="done", due_before=date(2026, 11, 5))
    assert [task.id for task in tasks] == ["TASK-006", "TASK-004"]


def test_due_before_respects_limit_after_ordering() -> None:
    tasks = TaskService().list_tasks(due_before="2026-11-05", limit=2)
    assert [task.id for task in tasks] == ["TASK-002", "TASK-006"]


@pytest.mark.parametrize("value", ["2026-13-40", "2026/11/05", "05-11-2026", "", 20261105])
def test_invalid_due_before_raises_value_error(value: object) -> None:
    with pytest.raises(ValueError):
        TaskService().list_tasks(due_before=value)  # type: ignore[arg-type]


def test_due_before_none_keeps_the_unfiltered_result() -> None:
    assert TaskService().list_tasks(due_before=None) == TaskService().list_tasks()
