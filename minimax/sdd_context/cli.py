"""Command line entry point for the SDD context module."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ingest import ingest_markdown, ingest_project
from .minimax_client import apply_diff, call_minimax, build_prompt
from .pc_state import build_state_payload, load_state_async, run_async, save_state_async
from .select import required_sources, select_context
from .settings import TASK, Settings, module_root, records_dir, state_dir, work_dir
from .store import SeekDBStore
from .verify import run_verification

PROJECT = "minimax_demo"
BEFORE_PROJECT = "minimax_demo_before"

REQUIRED = {
    "specs": [
        "specs/service_spec.md#REQ-BOARD-006",
        "specs/service_spec.md#REQ-BOARD-007",
        "specs/service_spec.md#REQ-BOARD-010",
    ],
    "decisions": [
        "specs/decisions.md#ADR-005",
        "specs/decisions.md#ADR-006",
    ],
    "code": ["board/service.py#TaskService.list_tasks"],
    "tests": [
        "tests/test_due_before.py",
        "tests/test_filters.py",
    ],
}


def make_store(settings: Settings, *, log_name: str = "seekdb_queries.log") -> SeekDBStore:
    return SeekDBStore(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        database=settings.database,
        query_log=records_dir() / log_name,
    )


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_init(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    store = make_store(settings)
    try:
        SeekDBStore.create_database(
            host=settings.host,
            port=settings.port,
            user=settings.user,
            password=settings.password,
            database=settings.database,
        )
        store.ensure_schema()
        if args.reset:
            store.reset()
        print(f"seekdb schema ready at {settings.host}:{settings.port}/{settings.database}")
        if args.reset:
            print("all tables were recreated")
    finally:
        store.close()
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    store = make_store(settings)
    project_dir = Path(args.project_dir).resolve()
    try:
        store.ensure_schema()
        summary = ingest_project(store, project_root=project_dir, project=args.project)
    finally:
        store.close()
    payload = summary.as_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.out:
        write_json(Path(args.out), payload)
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    store = make_store(settings, log_name=args.query_log)
    try:
        context = select_context(store, project=args.project, task=args.task)
    finally:
        store.close()
    missing = required_sources(context, REQUIRED) if args.check_required else {}
    payload = {
        "context": context,
        "required": REQUIRED if args.check_required else None,
        "missing_required": missing,
    }
    if args.out:
        write_json(Path(args.out), payload)
    print(
        json.dumps(
            {
                "specs": [item["locator"] for item in context["specs"]],
                "decisions": [item["locator"] for item in context["decisions"]],
                "excluded_decisions": [item["locator"] for item in context["excluded_decisions"]],
                "code": [item["locator"] for item in context["code"]],
                "tests": [item["locator"] for item in context["tests"]],
                "missing_required": missing,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if missing else 0


def cmd_ask(args: argparse.Namespace) -> int:
    context_payload = json.loads(Path(args.context).read_text(encoding="utf-8"))
    context = context_payload.get("context", context_payload)
    project_dir = Path(args.project_dir).resolve()
    files = {
        relative: (project_dir / relative).read_text(encoding="utf-8")
        for relative in args.files
    }
    prompt = build_prompt(
        task=args.task,
        context=context,
        files=files,
        attempt=args.attempt,
        feedback=args.feedback,
    )
    result = call_minimax(
        prompt=prompt,
        record_path=Path(args.out),
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key,
    )
    if not result.diff:
        print("MiniMax response did not contain a unified diff; record saved but nothing applied")
        return 2
    if args.apply:
        code, output = apply_diff(project_dir, result.diff, records_dir())
        print(f"patch exit_code={code}\n{output}")
        return code
    print(result.diff)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    result = run_verification(
        Path(args.project_dir).resolve(),
        Path(args.out_dir).resolve(),
        phase=args.phase,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if (result["target_ok"] and result["regression_ok"]) else 1


def cmd_state_save(args: argparse.Namespace) -> int:
    payload = build_state_payload(
        task_id="TASK-BOARD-DUE-BEFORE",
        task=args.task,
        context_path=Path(args.context),
        verification_path=Path(args.verification),
        completed=args.completed,
        pending=args.pending,
    )
    result = run_async(
        lambda: save_state_async(state_dir=state_dir(), payload=payload)
    )
    result["db_path"] = str(state_dir() / "powercontext.db")
    result["payload"] = payload
    write_json(Path(args.out), result)
    print(json.dumps({key: result[key] for key in ("scope_id", "source_id", "source_position")}, indent=2))
    return 0


def cmd_state_show(args: argparse.Namespace) -> int:
    result = run_async(lambda: load_state_async(state_dir=state_dir()))
    write_json(Path(args.out), result)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:2000])
    return 0 if result.get("found") else 1


def _prepare_before_project() -> Path:
    source = module_root() / "demo_project"
    target = work_dir() / "before_project"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"),
    )
    shutil.copy2(
        module_root() / "evidence" / "before" / "board" / "service.py",
        target / "board" / "service.py",
    )
    return target


def cmd_evolution(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    store = make_store(settings, log_name="seekdb_queries_spec_evolution.log")
    spec_dir = work_dir() / "spec_evolution"
    spec_dir.mkdir(parents=True, exist_ok=True)
    spec_path = spec_dir / "notification_spec.md"
    evolution_dir = module_root() / "evidence" / "spec_evolution"
    task = "通知摘要固定包含几条通知，按什么顺序排序？"
    results: dict[str, Any] = {"task": task, "steps": []}
    try:
        store.ensure_schema()
        shutil.copy2(evolution_dir / "notification_v1.md", spec_path)
        summary_v1 = ingest_markdown(store, path=spec_path, project="spec_evolution")
        context_v1 = select_context(store, project="spec_evolution", task=task)
        results["steps"].append(
            {"version": "v1", "ingest": summary_v1.as_dict(), "context": context_v1}
        )
        shutil.copy2(evolution_dir / "notification_v2.md", spec_path)
        summary_v2 = ingest_markdown(store, path=spec_path, project="spec_evolution")
        context_v2 = select_context(store, project="spec_evolution", task=task)
        results["steps"].append(
            {"version": "v2", "ingest": summary_v2.as_dict(), "context": context_v2}
        )
    finally:
        store.close()
    v1_text = " ".join(item["text"] for item in results["steps"][0]["context"]["specs"])
    v2_text = " ".join(item["text"] for item in results["steps"][1]["context"]["specs"])
    results["v1_contains_2"] = "2 条通知" in v1_text
    results["v2_contains_3"] = "3 条通知" in v2_text
    results["updated_content_used"] = (
        results["v1_contains_2"] and results["v2_contains_3"] and v1_text != v2_text
    )
    write_json(Path(args.out), results)
    print(
        json.dumps(
            {
                "updated_content_used": results["updated_content_used"],
                "v1_specs": [item["locator"] for item in results["steps"][0]["context"]["specs"]],
                "v2_specs": [item["locator"] for item in results["steps"][1]["context"]["specs"]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if results["updated_content_used"] else 1


def cmd_demo(args: argparse.Namespace) -> int:
    records = records_dir()
    records.mkdir(parents=True, exist_ok=True)
    settings = Settings.from_env()
    summary: dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat()}

    # 1. seekdb schema + both snapshots ingested.
    store = make_store(settings)
    try:
        SeekDBStore.create_database(
            host=settings.host,
            port=settings.port,
            user=settings.user,
            password=settings.password,
            database=settings.database,
        )
        store.reset()
        demo_root = module_root() / "demo_project"
        before_root = _prepare_before_project()
        summary["ingest_current"] = ingest_project(store, project_root=demo_root, project=PROJECT).as_dict()
        summary["ingest_before"] = ingest_project(
            store, project_root=before_root, project=BEFORE_PROJECT
        ).as_dict()
    finally:
        store.close()

    # 2. Context for the MiniMax call (built from the pre-change snapshot).
    store = make_store(settings, log_name="seekdb_queries_context.log")
    try:
        context_before = select_context(store, project=BEFORE_PROJECT, task=TASK)
        missing_before = required_sources(context_before, REQUIRED)
        context_current = select_context(store, project=PROJECT, task=TASK)
    finally:
        store.close()
    write_json(records / "context_for_minimax.json", {"context": context_before, "missing_required": missing_before})
    write_json(records / "context_current.json", {"context": context_current})
    summary["context"] = {
        "missing_required": missing_before,
        "specs": [item["locator"] for item in context_before["specs"]],
        "decisions": [item["locator"] for item in context_before["decisions"]],
        "excluded_decisions": [item["locator"] for item in context_before["excluded_decisions"]],
        "code": [item["locator"] for item in context_before["code"]],
        "tests": [item["locator"] for item in context_before["tests"]],
    }

    # 3. Before-state verification: target tests must fail, regressions must pass.
    before_verification = run_verification(work_dir() / "before_project", records, phase="before")
    after_verification = run_verification(module_root() / "demo_project", records, phase="after")
    summary["verification_before"] = before_verification
    summary["verification_after"] = after_verification
    summary["must_pass"] = {
        "target_failed_before": before_verification["target"]["exit_code"] != 0,
        "regression_passed_before": before_verification["regression"]["exit_code"] == 0,
        "target_passed_after": after_verification["target"]["exit_code"] == 0,
        "regression_passed_after": after_verification["regression"]["exit_code"] == 0,
    }

    # 3b. Refresh the committed before/after snapshots and their diff.
    after_snapshot = records / ".." / "evidence" / "after" / "board" / "service.py"
    after_snapshot.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(module_root() / "demo_project" / "board" / "service.py", after_snapshot)
    diff_run = subprocess.run(
        [
            "diff",
            "-u",
            "--label",
            "a/board/service.py",
            "--label",
            "b/board/service.py",
            str((work_dir() / "before_project" / "board" / "service.py").resolve()),
            str((module_root() / "demo_project" / "board" / "service.py").resolve()),
        ],
        text=True,
        capture_output=True,
    )
    (module_root() / "evidence" / "code_change.diff").write_text(diff_run.stdout, encoding="utf-8")

    # 4. Spec update + reimport must change the retrieved context.
    evolution_result = cmd_evolution(argparse.Namespace(out=str(records / "spec_evolution.json")))
    summary["spec_evolution_updated"] = evolution_result == 0

    # 4b. Check that the recorded MiniMax patch reproduces the committed code.
    session_path = records / "minimax_dev_session.json"
    patch_path = records / "minimax_patch.diff"
    minimax_recorded = False
    patch_reproduces_after = False
    if session_path.exists() and patch_path.exists():
        session = json.loads(session_path.read_text(encoding="utf-8"))
        minimax_recorded = bool(session.get("extracted_diff")) and session.get("provider") == "MiniMax"
        check_dir = work_dir() / "patch_verify"
        if check_dir.exists():
            shutil.rmtree(check_dir)
        shutil.copytree(work_dir() / "before_project", check_dir)
        applied = subprocess.run(
            ["patch", "-p1", "-i", str(patch_path.resolve())],
            cwd=check_dir,
            text=True,
            capture_output=True,
        )
        if applied.returncode == 0:
            patched = (check_dir / "board" / "service.py").read_text(encoding="utf-8")
            committed = (module_root() / "demo_project" / "board" / "service.py").read_text(encoding="utf-8")
            patch_reproduces_after = patched == committed
    summary["minimax"] = {
        "record": str(session_path.relative_to(module_root())),
        "recorded": minimax_recorded,
        "patch_reproduces_committed_code": patch_reproduces_after,
    }

    # 5. Save state through PowerContext, then read it in a separate process.
    completed = ["从 seekdb 检索规格、决策、代码与测试来源"]
    if minimax_recorded:
        completed.append("MiniMax 根据上下文产出补丁并应用")
    completed.append("目标测试转绿，回归测试保持通过")
    save_result = run_async(
        lambda: save_state_async(
            state_dir=state_dir(),
            payload=build_state_payload(
                task_id="TASK-BOARD-DUE-BEFORE",
                task=TASK,
                context_path=records / "context_for_minimax.json",
                verification_path=records / "verification_after.json",
                completed=completed,
                pending=[],
            ),
        )
    )
    write_json(records / "powercontext_save.json", save_result)
    summary["powercontext_save"] = {
        "scope_id": save_result["scope_id"],
        "source_id": save_result["source_id"],
        "source_position": save_result["source_position"],
    }
    show = subprocess.run(
        [sys.executable, "-m", "sdd_context", "state-show", "--out", str(records / "state_after_restart.json")],
        cwd=module_root(),
        text=True,
        capture_output=True,
    )
    summary["state_after_restart"] = {
        "exit_code": show.returncode,
        "stdout": show.stdout[:800],
        "stderr": show.stderr[:400],
    }
    state_payload = json.loads((records / "state_after_restart.json").read_text(encoding="utf-8"))
    summary["must_pass"]["state_read_after_restart"] = bool(state_payload.get("found"))
    summary["must_pass"]["minimax_session_recorded"] = bool(minimax_recorded)
    summary["must_pass"]["minimax_patch_reproduces_committed_code"] = bool(patch_reproduces_after)

    write_json(records / "run_summary.json", summary)
    print(json.dumps(summary["must_pass"], ensure_ascii=False, indent=2))
    return 0 if all(summary["must_pass"].values()) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sdd_context", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="create the seekdb database and tables")
    init.add_argument("--reset", action="store_true", help="drop and recreate all tables")
    init.set_defaults(func=cmd_init)

    ingest = subparsers.add_parser("ingest", help="ingest specs, code and tests into seekdb")
    ingest.add_argument("--project-dir", required=True)
    ingest.add_argument("--project", required=True)
    ingest.add_argument("--out")
    ingest.set_defaults(func=cmd_ingest)

    context = subparsers.add_parser("context", help="select task context from seekdb")
    context.add_argument("--project", required=True)
    context.add_argument("--task", default=TASK)
    context.add_argument("--out")
    context.add_argument("--query-log", default="seekdb_queries.log")
    context.add_argument("--check-required", action="store_true")
    context.set_defaults(func=cmd_context)

    ask = subparsers.add_parser("ask", help="ask MiniMax to produce the patch")
    ask.add_argument("--project-dir", required=True)
    ask.add_argument("--context", required=True)
    ask.add_argument("--task", default=TASK)
    ask.add_argument("--files", nargs="+", required=True)
    ask.add_argument("--out", default=str(records_dir() / "minimax_dev_session.json"))
    ask.add_argument("--model")
    ask.add_argument("--base-url")
    ask.add_argument("--api-key")
    ask.add_argument("--attempt", type=int, default=1)
    ask.add_argument("--feedback", default="")
    ask.add_argument("--apply", action="store_true")
    ask.set_defaults(func=cmd_ask)

    verify = subparsers.add_parser("verify", help="run target and regression tests")
    verify.add_argument("--project-dir", required=True)
    verify.add_argument("--phase", choices=["before", "after"], default="after")
    verify.add_argument("--out-dir", default=str(records_dir()))
    verify.set_defaults(func=cmd_verify)

    state_save = subparsers.add_parser("state-save", help="persist task state in PowerContext")
    state_save.add_argument("--context", default=str(records_dir() / "context_for_minimax.json"))
    state_save.add_argument("--verification", default=str(records_dir() / "verification_after.json"))
    state_save.add_argument("--task", default=TASK)
    state_save.add_argument("--completed", nargs="*", default=[])
    state_save.add_argument("--pending", nargs="*", default=[])
    state_save.add_argument("--out", default=str(records_dir() / "powercontext_save.json"))
    state_save.set_defaults(func=cmd_state_save)

    state_show = subparsers.add_parser("state-show", help="read task state after a module restart")
    state_show.add_argument("--out", default=str(records_dir() / "state_after_restart.json"))
    state_show.set_defaults(func=cmd_state_show)

    evolution = subparsers.add_parser("evolution", help="demonstrate spec update and reimport")
    evolution.add_argument("--out", default=str(records_dir() / "spec_evolution.json"))
    evolution.set_defaults(func=cmd_evolution)

    demo = subparsers.add_parser("demo", help="run the complete deterministic evidence pipeline")
    demo.set_defaults(func=cmd_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
