"""MiniMax client used to produce the code change.

The module talks to MiniMax's OpenAI-compatible chat completions endpoint and
stores the full request/response pair as evidence. It never fabricates a
response: when ``MINIMAX_API_KEY`` is missing the command fails with a clear
message instead of writing a placeholder record.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.minimax.cn/v1"
DEFAULT_MODEL = "MiniMax-M3.1-Flash"


@dataclass
class MiniMaxResult:
    record: dict[str, Any]
    content: str
    diff: str | None


SYSTEM_PROMPT = """你是资深 Python 工程师。你只输出一个 unified diff，用 ```diff 代码块包裹。
不要输出任何解释、不要输出 <think> 思考块、不要复述需求、不要修改测试文件。
diff 的路径是相对于项目根目录的路径（例如 board/service.py）。
如果需要多文件修改，一个 diff 代码块里依次列出多个文件的 diff。"""


def build_prompt(
    *,
    task: str,
    context: dict[str, Any],
    files: dict[str, str],
    attempt: int = 1,
    feedback: str = "",
) -> str:
    payload = {
        "task": task,
        "context": {
            "specs": context.get("specs", []),
            "decisions": context.get("decisions", []),
            "excluded_decisions": context.get("excluded_decisions", []),
            "code": context.get("code", []),
            "tests": context.get("tests", []),
        },
        "files": files,
    }
    prompt = (
        f"第 {attempt} 轮实现。\n\n"
        "以下是任务与上下文（JSON）：\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n\n请输出 unified diff。"
    )
    if feedback:
        prompt += f"\n\n上一轮补丁验证失败，反馈如下，请修正后重新输出 diff：\n{feedback}"
    return prompt


def extract_diff(content: str) -> str | None:
    """Extract and repair a single unified diff."""

    cleaned = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    cleaned = re.sub(r"^[*]{3}\s*End Patch\s*$", "", cleaned, flags=re.MULTILINE).strip()
    code_blocks = re.findall(r"```(?:diff|patch)?\s*\n(.*?)```", cleaned, re.DOTALL)
    if code_blocks:
        candidate = code_blocks[0].strip()
    elif cleaned.lstrip().startswith(("diff --git", "--- ")):
        candidate = cleaned.strip()
    else:
        return None
    first_diff_markers = [m.start() for m in re.finditer(r"(?m)^diff --git ", candidate)]
    if len(first_diff_markers) >= 2:
        candidate = candidate[: first_diff_markers[1]].rstrip()
    first_hunks = [m.start() for m in re.finditer(r"(?m)^--- a/", candidate)]
    if len(first_hunks) >= 2 and not candidate.startswith("diff --git"):
        candidate = candidate[: first_hunks[1]].rstrip()
    candidate = _repair_unified_diff(candidate)
    return candidate.rstrip() + "\n"


def _repair_unified_diff(diff: str) -> str:
    """Insert missing blank lines between hunks; add ``diff --git`` if needed."""

    lines = diff.splitlines()
    if not lines:
        return diff
    out: list[str] = []
    if not lines[0].startswith("diff --git ") and lines[0].startswith("--- "):
        path = lines[0][4:].strip()  # strip "--- "
        target_path = path
        if path.startswith("a/"):
            target_path = "b/" + path[2:]
        elif path.startswith("b/"):
            target_path = "a/" + path[2:]
        else:
            target_path = path
        out.append(f"diff --git a/{path if path.startswith('a/') else path} b/{target_path}")
    previous_was_hunk = False
    for line in lines:
        is_hunk = line.startswith("@@")
        if is_hunk and previous_was_hunk:
            out.append("")
        out.append(line)
        previous_was_hunk = is_hunk
    return "\n".join(out)


def call_minimax(
    *,
    prompt: str,
    record_path: Path,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 16384,
) -> MiniMaxResult:
    api_key = api_key or os.getenv("MINIMAX_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "MINIMAX_API_KEY is not set. Export the key from your MiniMax token plan before running 'sdd_context ask'."
        )
    base_url = (base_url or os.getenv("MINIMAX_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
    model = model or os.getenv("MINIMAX_MODEL", DEFAULT_MODEL)

    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "enable_reasoning": False,
    }
    started = time.monotonic()
    response = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=request_body,
        timeout=180,
    )
    elapsed = time.monotonic() - started
    response.raise_for_status()
    data = response.json()
    try:
        message = data["choices"][0]["message"]
        content = message.get("content") or ""
        # M3.1-Flash / M3 可能有 reasoning_content，真正输出在 content。
        if not content and message.get("reasoning_content"):
            content = message["reasoning_content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError(f"unexpected MiniMax response: {json.dumps(data, ensure_ascii=False)[:800]}") from error
    diff = extract_diff(content)
    record = {
        "provider": "MiniMax",
        "endpoint": f"{base_url}/chat/completions",
        "model": model,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "latency_seconds": round(elapsed, 3),
        "request": request_body,
        "response": data,
        "extracted_diff": diff,
        "usage": data.get("usage"),
        "api_key_source": "MINIMAX_API_KEY environment variable (value redacted)",
    }
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return MiniMaxResult(record=record, content=content, diff=diff)


def apply_diff(project_root: Path, diff: str, records_root: Path) -> tuple[int, str]:
    """Apply a unified diff with ``patch``; return exit code and combined output."""

    import subprocess

    patch_file = records_root / "minimax_patch.diff"
    patch_file.parent.mkdir(parents=True, exist_ok=True)
    patch_file.write_text(diff, encoding="utf-8")
    check = subprocess.run(
        ["patch", "-p1", "--dry-run", "-i", str(patch_file)],
        cwd=project_root,
        text=True,
        capture_output=True,
    )
    if check.returncode != 0:
        return check.returncode, (check.stdout + check.stderr)
    applied = subprocess.run(
        ["patch", "-p1", "-i", str(patch_file)],
        cwd=project_root,
        text=True,
        capture_output=True,
    )
    return applied.returncode, (applied.stdout + applied.stderr)
