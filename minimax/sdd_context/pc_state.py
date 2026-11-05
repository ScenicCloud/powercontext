"""PowerContext-backed task state.

Each CLI invocation starts a fresh PowerContext server process bound to a
SQLite file under ``minimax/.state``. Saving state in one invocation and
loading it in a later invocation therefore proves that the state survives a
module restart, because nothing is kept in memory between invocations.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import uvicorn
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime.config import (
    ExternalSkillsConfig,
    InferenceConfig,
    RuntimeConfig,
)
from powercontext.client import PowerContextClient
from powercontext.http import (
    CreateScopeRequest,
    CreateSourceRequest,
    ListSourcesRequest,
    RememberMemoryRequest,
    SearchMemoryRequest,
)
from powercontext.server.factory import create_server_app
from powercontext.server.settings import (
    AccessControlConfig,
    BearerAuthConfig,
    HttpConfig,
    McpConfig,
    MetricsConfig,
    ServerSettings,
    TracingConfig,
)

SCOPE_IDEMPOTENCY_KEY = "sdd-task-board-due-before"
TASK_ID = "TASK-BOARD-DUE-BEFORE"


@dataclass
class PowerContextHandle:
    url: str
    server: uvicorn.Server
    thread: threading.Thread
    listener: socket.socket

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)
        try:
            self.listener.close()
        except OSError:
            pass


def start_powercontext(state_dir: Path, *, timeout: float = 30.0) -> PowerContextHandle:
    state_dir.mkdir(parents=True, exist_ok=True)
    workspace = state_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    database_path = state_dir / "powercontext.db"

    settings = ServerSettings(
        workspace=workspace,
        database=SQLiteConfig(url=f"sqlite+aiosqlite:///{database_path}"),
        http=HttpConfig(host="127.0.0.1"),
        auth=BearerAuthConfig(enabled=False),
        access=AccessControlConfig(mode="disabled"),
        inference=InferenceConfig(),
        runtime=RuntimeConfig(schedule_seconds=None, experience_schedule_seconds=None),
        external_skills=ExternalSkillsConfig(),
        mcp=McpConfig(enabled=False),
        metrics=MetricsConfig(enabled=False),
        tracing=TracingConfig(enabled=False),
    )
    app = create_server_app(settings=settings, scheduler_path=state_dir / "scheduler.db")

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="critical", access_log=False, lifespan="on")
    )
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True, name="powercontext"
    )
    thread.start()
    deadline = time.monotonic() + timeout
    while thread.is_alive() and not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        listener.close()
        raise RuntimeError("PowerContext server failed to start within the timeout")
    return PowerContextHandle(url=f"http://127.0.0.1:{port}", server=server, thread=thread, listener=listener)


async def save_state_async(
    *,
    state_dir: Path,
    payload: dict[str, Any],
    source_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    handle = start_powercontext(state_dir)
    try:
        async with PowerContextClient(handle.url, timeout=60) as client:
            capabilities = await client.get_capabilities()
            scope = await client.create_scope(
                CreateScopeRequest(
                    title="SDD due_before task",
                    summary="Task progress and verification state for the MiniMax SDD demo.",
                    idempotency_key=SCOPE_IDEMPOTENCY_KEY,
                )
            )
            source = await client.create_source(
                scope.scope_id, CreateSourceRequest(content=payload)
            )
            memories = []
            for kind, text in (
                ("progress", payload.get("completed_text", "")),
                ("constraint", payload.get("pending_text", "")),
                ("fact", payload.get("verification_text", "")),
            ):
                if not text:
                    continue
                response = await client.remember_memory(
                    RememberMemoryRequest(
                        scope_id=scope.scope_id,
                        kind=kind,
                        text=text,
                        reason="sdd_context state round-trip",
                    )
                )
                memories.append({"kind": kind, "text": text, "response": str(response)})
            if source_callback:
                source_callback(scope.scope_id)
            return {
                "backend": "powercontext",
                "server_url": handle.url,
                "capabilities": str(capabilities)[:400],
                "scope_id": scope.scope_id,
                "source_id": source.source_id,
                "source_position": source.position,
                "memories": memories,
            }
    finally:
        handle.stop()


async def load_state_async(
    *, state_dir: Path, task_id: str = TASK_ID, query: str = "due_before"
) -> dict[str, Any]:
    handle = start_powercontext(state_dir)
    try:
        async with PowerContextClient(handle.url, timeout=60) as client:
            scopes = await client.list_scopes()
            scope = next(
                (item for item in scopes.items if item.title == "SDD due_before task"),
                None,
            )
            if scope is None:
                return {"backend": "powercontext", "found": False, "reason": "scope not found"}
            page = await client.list_sources(scope.scope_id, ListSourcesRequest(limit=100))
            matches = [
                source
                for source in page.items
                if isinstance(source.content, dict) and source.content.get("task_id") == task_id
            ]
            latest = max(matches, key=lambda item: item.position) if matches else None
            search = await client.search_memory(
                SearchMemoryRequest(scope_id=scope.scope_id, query=query, limit=10, mode="auto")
            )
            return {
                "backend": "powercontext",
                "server_url": handle.url,
                "scope_id": scope.scope_id,
                "found": latest is not None,
                "source_id": latest.source_id if latest else None,
                "source_position": latest.position if latest else None,
                "state": latest.content if latest else None,
                "memory_hits": [
                    {"score": hit.score, "text": hit.text}
                    for hit in search.hits
                ],
            }
    finally:
        handle.stop()


def run_async(factory: Callable[[], Any]) -> Any:
    import asyncio

    return asyncio.run(factory())


def build_state_payload(
    *,
    task_id: str,
    task: str,
    context_path: Path,
    verification_path: Path,
    completed: list[str],
    pending: list[str],
) -> dict[str, Any]:
    context = json.loads(context_path.read_text(encoding="utf-8"))
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    digest_source = json.dumps(context, ensure_ascii=False, sort_keys=True)
    import hashlib

    context_digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
    payload = {
        "task_id": task_id,
        "task": task,
        "completed": completed,
        "pending": pending,
        "verification": verification,
        "context_digest": context_digest,
        "context_summary": {
            "specs": [source.get("locator") for source in context.get("specs", [])],
            "decisions": [source.get("locator") for source in context.get("decisions", [])],
            "code": [source.get("locator") for source in context.get("code", [])],
            "tests": [source.get("locator") for source in context.get("tests", [])],
        },
        "completed_text": "; ".join(f"COMPLETED: {item}" for item in completed),
        "pending_text": "; ".join(f"PENDING: {item}" for item in pending),
        "verification_text": (
            f"VERIFIED: target={verification.get('target', {}).get('passed', 0)} passed, "
            f"regression={verification.get('regression', {}).get('passed', 0)} passed, "
            f"exit_code={verification.get('exit_code')}"
        ),
    }
    return payload
