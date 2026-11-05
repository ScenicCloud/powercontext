"""可选：本地 FastAPI 演示服务（非交付必需）。

真正对外发布的项目网站走 Qoder Sites（静态站，见 site/index.html）；
本服务只用于在本地连真实 seekdb 做接口演示：

    uvicorn src.demo_web:app --reload --port 8000

接口：
    GET /api/health                 健康检查
    GET /api/notes?category=work   笔记列表（可按类别过滤）
    GET /api/search?q=...&mode=hybrid&category=&top_k=5
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

from .models import Note
from .repository import NoteRepository

DB_PATH = os.environ.get("SEEKDB_PATH", "./data/seekdb.db")
SAMPLE_FILE = Path(__file__).resolve().parent.parent / "data" / "sample_notes.json"

app = FastAPI(title="知库 · seekdb 演示 API", version="1.0.0")
_repo: NoteRepository | None = None


def get_repo() -> NoteRepository:
    global _repo
    if _repo is None:
        _repo = NoteRepository(db_path=DB_PATH)
        if _repo.count() == 0:
            sample = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
            _repo.bulk_upsert([Note(**item) for item in sample])
    return _repo


@app.get("/api/health")
def health() -> dict:
    try:
        repo = get_repo()
        return {"status": "healthy", "notes": repo.count(), "engine": "seekdb"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"数据库连接失败: {exc}")


@app.get("/api/notes")
def list_notes(category: str | None = Query(default=None), limit: int = 50) -> dict:
    items = get_repo().list_all(limit=limit, category=category)
    return {"items": items, "total": len(items)}


@app.get("/api/search")
def search(q: str = Query(...), mode: str = "hybrid",
          category: str | None = None, top_k: int = 5) -> dict:
    items = get_repo().search(q, mode=mode, top_k=top_k, category=category)
    return {"query": q, "mode": mode, "items": items, "total": len(items)}


@app.post("/api/memory")
def remember(payload: dict) -> dict:
    """Persist one player action so a later Dify turn can recall it."""
    title = str(payload.get("title", "玩家恶作剧"))
    content = str(payload.get("content", "")).strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    note = Note(
        note_id=str(payload.get("note_id", "")) or None,
        title=title,
        content=content,
        category=str(payload.get("category", "general")),
        tags=payload.get("tags", ["npc", "player-memory"]),
    )
    note_id = get_repo().upsert(note)
    return {"ok": True, "note_id": note_id, "engine": "seekdb"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.demo_web:app", host="127.0.0.1", port=8000, reload=False)
