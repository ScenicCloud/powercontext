"""笔记条目的数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any


@dataclass
class Note:
    """一条可被检索的知识条目（课程笔记 / 文献摘要 / 工作任务 / 会议纪要等）。"""

    title: str
    content: str
    category: str = "general"          # general | study | research | work
    tags: List[str] = field(default_factory=list)
    source: str = "manual"             # manual | import | meeting
    created_at: str = ""               # ISO 日期字符串，可空
    note_id: str = ""                  # 主键；为空时由仓库层生成

    def to_metadata(self) -> Dict[str, Any]:
        """转换为 seekdb metadata（metadata 仅支持标量，tags 用逗号拼接）。"""
        return {
            "title": self.title,
            "category": self.category,
            "tags": ",".join(self.tags),
            "source": self.source,
            "created_at": self.created_at,
        }

    @staticmethod
    def from_result(doc: str, meta: Dict[str, Any], note_id: str, score: float | None = None) -> Dict[str, Any]:
        """把 seekdb 召回结果还原成前端/CLI 易读的字典。

        入库文档首行是标题；这里若首行与 metadata.title 一致则剥离，避免正文重复标题。
        """
        meta = meta or {}
        title = meta.get("title", "")
        content = doc or ""
        if title and content.startswith(title):
            content = content[len(title):].lstrip("\n")
        tags_raw = meta.get("tags", "")
        return {
            "note_id": note_id,
            "title": title,
            "content": content,
            "category": meta.get("category", "general"),
            "tags": [t for t in str(tags_raw).split(",") if t],
            "source": meta.get("source", "manual"),
            "created_at": meta.get("created_at", ""),
            "score": score,
        }

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)
