"""seekdb 数据访问层。

本模块是项目与 OceanBase seekdb 交互的唯一入口，使用高层 Python SDK
``pyseekdb`` 的嵌入式本地库（无需启动独立数据库服务），实现：

* 条目写入 / 更新（upsert）
* 向量语义检索（HNSW + 余弦距离）
* 关键词全文检索（文档包含匹配）
* 混合检索（全文支路 + 向量支路，RRF 倒数排名融合）
* 按类别 / 标签元数据过滤、列表、删除

检索语义与索引全部落在 seekdb 引擎内，业务代码只做结果整理。
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Optional

import pyseekdb
import pylibseekdb  # pyseekdb 自带底层驱动：嵌入式模式下确保 catalog 数据库存在（跨平台 wheel）
from pyseekdb import HNSWConfiguration

from .embedder import OfflineEmbedder
from .models import Note


class NoteRepository:
    """对 seekdb 集合 ``notes`` 的增删查封装。"""

    COLLECTION = "notes"

    def __init__(self, db_path: str, database: str = "knowledge", dimension: int = 256):
        self.dimension = dimension
        self.database = database
        self._ensure_database(db_path, database)
        # 嵌入式模式：数据落在本地目录；embedding 由本项目 embedder 生成，关闭 SDK 默认模型
        self.client = pyseekdb.Client(path=db_path, database=database)
        self.embedder = OfflineEmbedder(dimension=dimension)
        self.collection = self.client.get_or_create_collection(
            name=self.COLLECTION,
            configuration=HNSWConfiguration(dimension=dimension, distance="cosine"),
            embedding_function=None,
        )

    @staticmethod
    def _ensure_database(db_path: str, database: str) -> None:
        """嵌入式模式下，高层 SDK 不会自动创建 catalog 库，先用底层驱动建库。"""
        os.makedirs(db_path, exist_ok=True)
        inst = pylibseekdb.open(db_dir=db_path)
        try:
            conn = inst.connect(database="test", autocommit=True)
            cur = conn.cursor()
            cur.execute(f"CREATE DATABASE IF NOT EXISTS {database}")
            cur.close()
            conn.close()
        finally:
            inst.close()

    # ------------------------------------------------------------------ 写入
    @staticmethod
    def _doc_text(note: Note) -> str:
        """标题 + 正文一起作为可检索文档，保证关键词能命中标题。"""
        return f"{note.title}\n{note.content}"

    def upsert(self, note: Note) -> str:
        """写入或更新一条笔记，返回 note_id。"""
        if not note.note_id:
            note.note_id = uuid.uuid4().hex[:12]
        # 标题并入正文一起参与向量化，提升语义召回
        text_for_embedding = f"{note.title}。{note.content}"
        vector = self.embedder.embed(text_for_embedding)
        self.collection.upsert(
            ids=note.note_id,
            documents=self._doc_text(note),
            embeddings=vector,
            metadatas=note.to_metadata(),
        )
        return note.note_id

    def bulk_upsert(self, notes: List[Note]) -> List[str]:
        ids, docs, metas, vectors = [], [], [], []
        for note in notes:
            if not note.note_id:
                note.note_id = uuid.uuid4().hex[:12]
            ids.append(note.note_id)
            docs.append(self._doc_text(note))
            metas.append(note.to_metadata())
            vectors.append(self.embedder.embed(f"{note.title}。{note.content}"))
        self.collection.upsert(ids=ids, documents=docs, embeddings=vectors, metadatas=metas)
        return ids

    # ------------------------------------------------------------------ 读取
    @staticmethod
    def _pack(ids: List[str], docs: List[str], metas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for i, note_id in enumerate(ids):
            results.append(Note.from_result(
                doc=docs[i] if i < len(docs) else "",
                meta=metas[i] if i < len(metas) else {},
                note_id=note_id,
            ))
        return results

    def list_all(self, limit: int = 50, category: Optional[str] = None) -> List[Dict[str, Any]]:
        where = {"category": category} if category else None
        payload = self.collection.get(where=where, limit=limit)
        return self._pack(payload.get("ids", []), payload.get("documents", []), payload.get("metadatas", []))

    def count(self) -> int:
        return self.collection.count()

    # ------------------------------------------------------------------ 检索
    def search_vector(self, query: str, top_k: int = 5, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """语义向量检索：把查询向量化后走 HNSW 最近邻。

        seekdb 向量索引异步构建，刚写入时 ANN 可能召回为空；此时回退到
        全量取出已存向量、用本地余弦相似度精排兜底，保证开箱即可检索。
        """
        q_vec = self.embedder.embed(query)
        where = {"category": category} if category else None
        payload = self.collection.query(
            query_embeddings=q_vec,
            where=where,
            n_results=top_k,
            include=["documents", "metadatas"],
        )
        ids = payload.get("ids", [[]])[0]
        if ids:
            docs = payload.get("documents", [[]])[0]
            metas = payload.get("metadatas", [[]])[0]
            return self._pack(ids, docs, metas)

        # 兜底：索引尚未就绪，全量 + 余弦精排（入库向量已 L2 归一化，点积即余弦）
        allp = self.collection.get(where=where, limit=100,
                                   include=["documents", "metadatas", "embeddings"])
        all_ids = allp.get("ids", [])
        embs = allp.get("embeddings", [])
        scored = sorted(
            ((sum(a * b for a, b in zip(q_vec, e)), i) for i, e in enumerate(embs)),
            reverse=True,
        )[:top_k]
        ids = [all_ids[i] for _, i in scored]
        docs = [allp["documents"][i] for _, i in scored]
        metas = [allp["metadatas"][i] for _, i in scored]
        return self._pack(ids, docs, metas)

    def search_fulltext(self, keyword: str, top_k: int = 5, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """关键词全文检索：文档包含匹配（seekdb 全文支路）。"""
        payload = self.collection.get(
            where={"category": category} if category else None,
            where_document={"$contains": keyword},
            limit=top_k,
        )
        return self._pack(payload.get("ids", []), payload.get("documents", []), payload.get("metadatas", []))

    def search_hybrid(self, query: str, top_k: int = 5, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """混合检索：全文支路 + 向量支路，RRF 倒数排名融合后重排。"""
        q_vec = self.embedder.embed(query)
        where = {"category": category} if category else None
        payload = self.collection.hybrid_search(
            query={
                "where_document": {"$contains": query},
                "where": where,
                "n_results": top_k,
            },
            knn={
                "query_embeddings": [q_vec],
                "where": where,
                "n_results": top_k,
            },
            rank={"rrf": {}},
            n_results=top_k,
            include=["documents", "metadatas"],
        )
        ids = payload.get("ids", [[]])[0]
        docs = payload.get("documents", [[]])[0]
        metas = payload.get("metadatas", [[]])[0]
        return self._pack(ids, docs, metas)

    def search(self, query: str, mode: str = "hybrid", top_k: int = 5,
               category: Optional[str] = None) -> List[Dict[str, Any]]:
        if mode == "vector":
            return self.search_vector(query, top_k, category)
        if mode == "fulltext":
            return self.search_fulltext(query, top_k, category)
        return self.search_hybrid(query, top_k, category)

    # ------------------------------------------------------------------ 删除
    def delete(self, note_id: str) -> None:
        self.collection.delete(ids=note_id)

    def close(self) -> None:
        # pyseekdb 嵌入式 Client 无需显式关闭；保留接口便于扩展远端模式
        pass
