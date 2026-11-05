"""Run the demo project's target and regression tests and capture evidence."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TARGET = "tests/test_due_before.py"
REGRESSION = ("tests/test_filters.py", "tests/test_validation.py")


def _parse_counts(output: str) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "error": 0}
    for key, pattern in (
        ("passed", r"(\d+) passed"),
        ("failed", r"(\d+) failed"),
        ("error", r"(\d+) error"),
    ):
        match = re.search(pattern, output)
        if match:
            counts[key] = int(match.group(1))
    return counts


def run_pytest(project_root: Path, targets: tuple[str, ...], *, log_path: Path) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(project_root)
    command = [sys.executable, "-m", "pytest", *targets, "-q", "--tb=short"]
    completed = subprocess.run(command, cwd=project_root, text=True, capture_output=True, env=env)
    output = completed.stdout + completed.stderr
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        f"$ {' '.join(command)}\n[exit_code={completed.returncode}]\n\n{output}",
        encoding="utf-8",
    )
    counts = _parse_counts(output)
    return {
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "counts": counts,
        "log": str(log_path),
    }


def run_verification(project_root: Path, output_dir: Path, *, phase: str) -> dict[str, Any]:
    suffix = phase
    target = run_pytest(project_root, (TARGET,), log_path=output_dir / f"tests_target_{suffix}.log")
    regression = run_pytest(project_root, REGRESSION, log_path=output_dir / f"tests_regression_{suffix}.log")
    result = {
        "phase": phase,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project": str(project_root),
        "target": target,
        "regression": regression,
        "exit_code": target["exit_code"] or regression["exit_code"],
        "target_ok": target["exit_code"] == 0,
        "regression_ok": regression["exit_code"] == 0,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"verification_{suffix}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
