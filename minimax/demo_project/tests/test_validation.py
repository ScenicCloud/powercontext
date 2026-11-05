"""Regression tests for argument validation that predates the change.

This file is identical in the before and after snapshots.
"""

from __future__ import annotations

import pytest

from board import TaskService


@pytest.mark.parametrize("status", ["archived", "", None, "OPEN"])
def test_invalid_status_is_rejected(status: str | None) -> None:
    if status is None:
        # ``None`` means "no filter" and is therefore valid.
        assert TaskService().list_tasks(status=status)
        return
    with pytest.raises(ValueError):
        TaskService().list_tasks(status=status)


@pytest.mark.parametrize("priority", [0, 6, -1, "3", 3.5, True])
def test_invalid_priority_is_rejected(priority: object) -> None:
    with pytest.raises(ValueError):
        TaskService().list_tasks(priority=priority)  # type: ignore[arg-type]


@pytest.mark.parametrize("limit", [0, -2, "5", 1.5, True])
def test_invalid_limit_is_rejected(limit: object) -> None:
    with pytest.raises(ValueError):
        TaskService().list_tasks(limit=limit)  # type: ignore[arg-type]
