"""Configuration for the SDD context module."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

TASK = (
    "为 TaskService.list_tasks 增加 due_before 过滤：只返回截止日期严格早于给定日期的任务，"
    "同时保持 status 与 priority 过滤、默认排序和 limit 行为。"
    "非法 due_before 必须抛出 ValueError，并继续通过既有回归测试。"
)


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 2883
    user: str = "root"
    password: str = ""
    database: str = "sdd_context"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.getenv("SEEKDB_HOST", "127.0.0.1"),
            port=int(os.getenv("SEEKDB_PORT", "2883")),
            user=os.getenv("SEEKDB_USER", "root"),
            password=os.getenv("SEEKDB_PASSWORD", ""),
            database=os.getenv("SEEKDB_DATABASE", "sdd_context"),
        )


def module_root() -> Path:
    """Return the ``minimax`` directory that owns this package."""

    return Path(__file__).resolve().parent.parent


def records_dir() -> Path:
    return module_root() / "records"


def state_dir() -> Path:
    return module_root() / ".state"


def work_dir() -> Path:
    return module_root() / ".demo_work"
