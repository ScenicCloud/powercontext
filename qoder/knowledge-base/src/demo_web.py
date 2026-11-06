"""可选：本地 FastAPI 演示服务（非交付必需）。

真正对外发布的项目网站走 Qoder Sites（静态站，见 site/index.html）；
本服务只用于在本地连真实 seekdb 做接口演示：

    uvicorn src.demo_web:app --reload --port 8000

接口：
    GET /api/health                 健康检查
    GET /api/notes?category=work   笔记列表（可按类别过滤）
    GET /api/search?q=...&mode=hybrid&category=&top_k=5
    POST /api/memory               写入一条玩家恶作剧记忆
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from .models import Note
from .repository import NoteRepository

DB_PATH = os.environ.get("SEEKDB_PATH", "./data/seekdb.db")
SAMPLE_FILE = Path(__file__).resolve().parent.parent / "data" / "sample_notes.json"

app = FastAPI(title="知库 · seekdb 演示 API", version="1.0.0")
_repo: NoteRepository | None = None


class MemoryPayload(BaseModel):
    title: str = Field(default="玩家恶作剧", min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=10000)
    category: str = Field(default="general", min_length=1, max_length=50)
    tags: list[str] = Field(default_factory=lambda: ["npc", "player-memory"], max_length=20)
    note_id: str | None = Field(default=None, max_length=100)

    @field_validator("title", "content", "category")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空白")
        return value

    @field_validator("tags")
    @classmethod
    def strip_tags(cls, value: list[str]) -> list[str]:
        return [tag.strip() for tag in value if tag.strip()]


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
def search(
    q: str = Query(..., min_length=1, max_length=1000),
    mode: Literal["hybrid", "vector", "fulltext"] = Query(default="hybrid"),
    category: str | None = Query(default=None, max_length=50),
    top_k: int = Query(default=5, ge=1, le=50),
) -> dict:
    q = q.strip()
    if not q:
        raise HTTPException(status_code=422, detail="q must not be blank")
    try:
        items = get_repo().search(q, mode=mode, top_k=top_k, category=category)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"记忆检索失败: {exc}") from exc
    return {"query": q, "mode": mode, "items": items, "total": len(items)}


@app.post("/api/memory")
def remember(payload: MemoryPayload) -> dict:
    note = Note(
        note_id=payload.note_id or "",
        title=payload.title,
        content=payload.content,
        category=payload.category,
        tags=payload.tags,
    )
    try:
        note_id = get_repo().upsert(note)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"记忆写入失败: {exc}") from exc
    return {"ok": True, "note_id": note_id, "engine": "seekdb"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.demo_web:app", host="127.0.0.1", port=8000, reload=False)
