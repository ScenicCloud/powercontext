"""命令行入口。

用法示例：
    python -m src.cli ingest                 # 导入 data/sample_notes.json 样例数据
    python -m src.cli list                   # 列出全部条目
    python -m src.cli search "范围查询"       # 混合检索（默认）
    python -m src.cli search "RAG 检索" --mode vector
    python -m src.cli search "周报" --mode fulltext --category work
    python -m src.cli add --title "标题" --content "正文" --category study --tags 数据库,复习
    python -m src.cli count
    python -m src.cli delete <note_id>

数据库路径可用环境变量 SEEKDB_PATH 覆盖（默认 ./data/seekdb.db）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

from .models import Note
from .repository import NoteRepository

DEFAULT_DB_PATH = os.environ.get("SEEKDB_PATH", "./data/seekdb.db")
SAMPLE_FILE = Path(__file__).resolve().parent.parent / "data" / "sample_notes.json"


def _repo() -> NoteRepository:
    return NoteRepository(db_path=DEFAULT_DB_PATH)


def _load_sample() -> List[Note]:
    raw = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
    notes = []
    for item in raw:
        note = Note(**item)
        # 样例条目用标题哈希作确定性 id，重复 ingest 走 upsert 更新而非翻倍
        note.note_id = hashlib.md5(note.title.encode("utf-8")).hexdigest()[:12]
        notes.append(note)
    return notes


def cmd_ingest(args: argparse.Namespace) -> None:
    repo = _repo()
    ids = repo.bulk_upsert(_load_sample())
    print(f"已导入 {len(ids)} 条笔记，当前共 {repo.count()} 条。")


def cmd_list(args: argparse.Namespace) -> None:
    repo = _repo()
    items = repo.list_all(limit=args.limit, category=args.category)
    _print_items(items)


def cmd_search(args: argparse.Namespace) -> None:
    repo = _repo()
    items = repo.search(args.query, mode=args.mode, top_k=args.top_k, category=args.category)
    print(f"模式={args.mode}，命中 {len(items)} 条：")
    _print_items(items)


def cmd_add(args: argparse.Namespace) -> None:
    repo = _repo()
    tags = [t for t in (args.tags or "").split(",") if t]
    note = Note(title=args.title, content=args.content, category=args.category,
                tags=tags, source="manual")
    note_id = repo.upsert(note)
    print(f"已写入，note_id={note_id}")


def cmd_count(_: argparse.Namespace) -> None:
    print(f"当前共 {_repo().count()} 条。")


def cmd_delete(args: argparse.Namespace) -> None:
    repo = _repo()
    repo.delete(args.note_id)
    print(f"已删除 {args.note_id}")


def _print_items(items: List[Dict[str, Any]]) -> None:
    if not items:
        print("（无命中）")
        return
    for idx, it in enumerate(items, 1):
        score = f"  score={it['score']:.3f}" if it.get("score") is not None else ""
        print(f"\n[{idx}] {it['title']}  ({it['category']}, {','.join(it['tags'])}){score}")
        print(f"    {it['content']}")
        print(f"    id={it['note_id']}  {it['created_at']}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="knowledge-base", description="基于 seekdb 的个人知识检索工具")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("ingest", help="导入样例数据").set_defaults(func=cmd_ingest)

    pl = sub.add_parser("list", help="列出条目")
    pl.add_argument("--category", choices=["general", "study", "research", "work"])
    pl.add_argument("--limit", type=int, default=50)
    pl.set_defaults(func=cmd_list)

    ps = sub.add_parser("search", help="检索：hybrid / vector / fulltext")
    ps.add_argument("query")
    ps.add_argument("--mode", choices=["hybrid", "vector", "fulltext"], default="hybrid")
    ps.add_argument("--category", choices=["general", "study", "research", "work"])
    ps.add_argument("--top-k", type=int, default=5)
    ps.set_defaults(func=cmd_search)

    pa = sub.add_parser("add", help="新增一条笔记")
    pa.add_argument("--title", required=True)
    pa.add_argument("--content", required=True)
    pa.add_argument("--category", choices=["general", "study", "research", "work"], default="general")
    pa.add_argument("--tags", default="")
    pa.set_defaults(func=cmd_add)

    sub.add_parser("count", help="统计条目数").set_defaults(func=cmd_count)

    pd = sub.add_parser("delete", help="按 id 删除")
    pd.add_argument("note_id")
    pd.set_defaults(func=cmd_delete)

    return p


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
