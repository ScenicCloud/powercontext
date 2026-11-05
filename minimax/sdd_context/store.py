"""seekdb storage and retrieval for the SDD context module.

All engineering material is persisted in seekdb (OceanBase seekdb) and every
context selection runs real SQL against it. The module uses the MySQL-compatible
wire protocol so the same code works against a local seekdb server, a Docker
instance, or OceanBase.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import pymysql
from pymysql.cursors import DictCursor

FTS_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
}


def stable_id(prefix: str, value: str, length: int = 16) -> str:
    return f"{prefix}_{hashlib.sha1(value.encode('utf-8')).hexdigest()[:length]}"


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    project: str
    kind: str
    path: str
    title: str
    locator: str
    line_start: int
    line_end: int
    status: str
    text: str

    def as_source(self) -> dict[str, Any]:
        source = {
            "path": self.path,
            "kind": self.kind,
            "title": self.title,
            "lines": [self.line_start, self.line_end],
            "text": self.text,
        }
        if self.locator:
            source["locator"] = self.locator
        if self.status:
            source["status"] = self.status
        return source


class SeekDBStore:
    """Thin, explicit seekdb gateway with a query log used as evidence."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 2883,
        user: str = "root",
        password: str = "",
        database: str = "sdd_context",
        query_log: Path | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.query_log = query_log
        self._connection: pymysql.Connection | None = None
        self.queries: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ connection
    def connect(self) -> pymysql.Connection:
        if self._connection is None:
            self._connection = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                charset="utf8mb4",
                cursorclass=DictCursor,
                autocommit=True,
            )
        return self._connection

    @classmethod
    def create_database(cls, *, host: str, port: int, user: str, password: str, database: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_]+", database):
            raise ValueError(f"invalid database name: {database!r}")
        connection = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            charset="utf8mb4",
            autocommit=True,
        )
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{database}` DEFAULT CHARACTER SET utf8mb4")
        connection.close()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if self.query_log is not None:
            self.query_log.parent.mkdir(parents=True, exist_ok=True)
            self.query_log.write_text(
                "\n".join(json.dumps(item, ensure_ascii=False, default=str) for item in self.queries) + "\n",
                encoding="utf-8",
            )

    # ------------------------------------------------------------------ schema
    def ensure_schema(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS documents (
                doc_id VARCHAR(191) PRIMARY KEY,
                project VARCHAR(128) NOT NULL,
                kind VARCHAR(32) NOT NULL,
                path VARCHAR(512) NOT NULL,
                title VARCHAR(255) NOT NULL,
                content_hash CHAR(64) NOT NULL,
                updated_at VARCHAR(40) NOT NULL,
                body LONGTEXT NOT NULL,
                FULLTEXT KEY ft_documents_body (body),
                KEY idx_documents_project (project, kind)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id VARCHAR(191) PRIMARY KEY,
                doc_id VARCHAR(191) NOT NULL,
                project VARCHAR(128) NOT NULL,
                kind VARCHAR(32) NOT NULL,
                path VARCHAR(512) NOT NULL,
                title VARCHAR(255) NOT NULL,
                locator VARCHAR(255) NOT NULL DEFAULT '',
                line_start INT NOT NULL,
                line_end INT NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT '',
                text LONGTEXT NOT NULL,
                FULLTEXT KEY ft_chunks_text (text),
                KEY idx_chunks_project (project, kind)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS ingest_runs (
                run_id VARCHAR(64) PRIMARY KEY,
                project VARCHAR(128) NOT NULL,
                started_at VARCHAR(40) NOT NULL,
                documents INT NOT NULL,
                chunks INT NOT NULL,
                note VARCHAR(255) NOT NULL DEFAULT ''
            )
            """,
        )
        for statement in statements:
            self._execute(statement, (), fetch=False)

    def reset(self) -> None:
        for table in ("chunks", "documents", "ingest_runs"):
            self._execute(f"DROP TABLE IF EXISTS {table}", (), fetch=False)  # noqa: S608 - fixed table names
        self.ensure_schema()

    # ------------------------------------------------------------------ writes
    def document_hash(self, doc_id: str) -> str | None:
        rows = self._execute("SELECT content_hash FROM documents WHERE doc_id = %s", (doc_id,))
        return rows[0]["content_hash"] if rows else None

    def replace_document(
        self,
        *,
        doc_id: str,
        project: str,
        kind: str,
        path: str,
        title: str,
        content_hash: str,
        body: str,
        chunks: Sequence[Chunk],
    ) -> bool:
        """Replace one document and its chunks atomically.

        Returns ``True`` when the document changed and was written, ``False``
        when the content hash matched and the existing rows were kept.
        """

        existing = self.document_hash(doc_id)
        if existing == content_hash and existing is not None:
            self.queries.append(
                {
                    "ts": now_utc(),
                    "sql": "SELECT content_hash FROM documents WHERE doc_id = %s",
                    "params": [doc_id],
                    "result": "unchanged",
                }
            )
            return False

        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM chunks WHERE doc_id = %s", (doc_id,))
                cursor.execute(
                    """
                    INSERT INTO documents
                        (doc_id, project, kind, path, title, content_hash, updated_at, body)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        project = VALUES(project),
                        kind = VALUES(kind),
                        path = VALUES(path),
                        title = VALUES(title),
                        content_hash = VALUES(content_hash),
                        updated_at = VALUES(updated_at),
                        body = VALUES(body)
                    """,
                    (doc_id, project, kind, path, title, content_hash, now_utc(), body),
                )
                if chunks:
                    cursor.executemany(
                        """
                        INSERT INTO chunks
                            (chunk_id, doc_id, project, kind, path, title, locator,
                             line_start, line_end, status, text)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        [
                            (
                                chunk.chunk_id,
                                chunk.doc_id,
                                chunk.project,
                                chunk.kind,
                                chunk.path,
                                chunk.title,
                                chunk.locator,
                                chunk.line_start,
                                chunk.line_end,
                                chunk.status,
                                chunk.text,
                            )
                            for chunk in chunks
                        ],
                    )
        except Exception:
            connection.rollback()
            raise
        self.queries.append(
            {
                "ts": now_utc(),
                "sql": "DELETE FROM chunks + INSERT documents/chunks (transaction)",
                "params": [doc_id, content_hash],
                "result": f"{len(chunks)} chunks",
            }
        )
        return True

    def record_run(self, *, project: str, documents: int, chunks: int, note: str) -> None:
        self._execute(
            "INSERT INTO ingest_runs (run_id, project, started_at, documents, chunks, note) VALUES (%s, %s, %s, %s, %s, %s)",
            (stable_id("run", f"{project}:{now_utc()}"), project, now_utc(), documents, chunks, note),
            fetch=False,
        )

    # ------------------------------------------------------------------ reads
    def fts(self, terms: Sequence[str], *, project: str, kind: str | None, limit: int) -> list[dict[str, Any]]:
        query = " ".join(term for term in terms if term not in FTS_STOPWORDS)
        if not query:
            return []
        if kind is None:
            rows = self._execute(
                """
                SELECT chunk_id, path, locator, line_start, line_end, status, text,
                       MATCH(text) AGAINST (%s IN NATURAL LANGUAGE MODE) AS score
                FROM chunks
                WHERE project = %s AND MATCH(text) AGAINST (%s IN NATURAL LANGUAGE MODE)
                ORDER BY score DESC, chunk_id ASC
                LIMIT %s
                """,
                (query, project, query, limit),
            )
        else:
            rows = self._execute(
                """
                SELECT chunk_id, path, locator, line_start, line_end, status, text,
                       MATCH(text) AGAINST (%s IN NATURAL LANGUAGE MODE) AS score
                FROM chunks
                WHERE project = %s AND kind = %s AND MATCH(text) AGAINST (%s IN NATURAL LANGUAGE MODE)
                ORDER BY score DESC, chunk_id ASC
                LIMIT %s
                """,
                (query, project, kind, query, limit),
            )
        self.queries.append(
            {
                "ts": now_utc(),
                "sql": "SELECT ... MATCH(text) AGAINST(%s IN NATURAL LANGUAGE MODE)",
                "params": [query, project, kind, limit],
                "result": [row["chunk_id"] for row in rows],
            }
        )
        for row in rows:
            row["score"] = float(row.get("score") or 0.0)
        return rows

    def like(
        self, terms: Sequence[str], *, project: str, kind: str | None, limit: int
    ) -> list[dict[str, Any]]:
        """Substring search used for Chinese text, where seekdb FTS has no tokens."""

        unique: list[str] = []
        for term in terms:
            if term and term not in unique:
                unique.append(term)
        if not unique:
            return []
        conditions = " OR ".join("INSTR(text, %s) > 0" for _ in unique)
        kind_clause = ""
        if kind is not None:
            kind_clause = " AND kind = %s"
        # The score expression needs the term list twice: once for hits, once for WHERE.
        rows = self._execute(
            f"""
            SELECT chunk_id, path, kind, locator, line_start, line_end, status, text,
                   ({' + '.join('INSTR(text, %s) > 0' for _ in unique)}) AS hits
            FROM chunks
            WHERE project = %s AND ({conditions}) {kind_clause}
            ORDER BY hits DESC, chunk_id ASC
            LIMIT %s
            """,  # noqa: S608 - only parameter placeholders are interpolated
            tuple(unique) + (project, *unique) + ((kind,) if kind is not None else ()) + (limit,),
        )
        self.queries.append(
            {
                "ts": now_utc(),
                "sql": "SELECT ... INSTR(text, %s) (Chinese substring candidates)",
                "params": [unique, project, kind, limit],
                "result": [row["chunk_id"] for row in rows],
            }
        )
        for row in rows:
            row["hits"] = int(row.get("hits") or 0)
        return rows

    def get_chunks(self, chunk_ids: Iterable[str]) -> list[dict[str, Any]]:
        ids = list(chunk_ids)
        if not ids:
            return []
        placeholders = ", ".join(["%s"] * len(ids))
        rows = self._execute(
            f"SELECT chunk_id, doc_id, project, kind, path, title, locator, line_start, line_end, status, text "
            f"FROM chunks WHERE chunk_id IN ({placeholders})",  # noqa: S608 - placeholders only
            tuple(ids),
        )
        by_id = {row["chunk_id"]: row for row in rows}
        return [by_id[chunk_id] for chunk_id in ids if chunk_id in by_id]

    def list_chunks(self, *, project: str, kind: str) -> list[dict[str, Any]]:
        return self._execute(
            "SELECT chunk_id, path, title, locator, line_start, line_end, status, text "
            "FROM chunks WHERE project = %s AND kind = %s ORDER BY path, line_start",
            (project, kind),
        )

    def count(self, *, project: str) -> int:
        rows = self._execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE project = %s",
            (project,),
        )
        return int(rows[0]["n"])

    def count_chunks(self, *, project: str, kind: str) -> int:
        rows = self._execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE project = %s AND kind = %s",
            (project, kind),
        )
        return int(rows[0]["n"])

    def term_document_frequencies(
        self, terms: Sequence[str], *, project: str, kind: str
    ) -> dict[str, int]:
        unique = [term for term in dict.fromkeys(terms) if term]
        if not unique:
            return {}
        expressions = ", ".join(
            f"SUM(CASE WHEN INSTR(LOWER(text), %s) > 0 THEN 1 ELSE 0 END) AS df_{index}"
            for index in range(len(unique))
        )
        rows = self._execute(
            f"SELECT {expressions} FROM chunks WHERE project = %s AND kind = %s",  # noqa: S608 - placeholders only
            tuple(term.lower() for term in unique) + (project, kind),
        )
        row = rows[0] if rows else {}
        return {
            term: int(row.get(f"df_{index}") or 0) for index, term in enumerate(unique)
        }

    # ------------------------------------------------------------------ internals
    def _execute(self, sql: str, params: tuple[Any, ...], *, fetch: bool = True) -> list[dict[str, Any]]:
        connection = self.connect()
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = list(cursor.fetchall()) if fetch and cursor.description else []
        self.queries.append(
            {
                "ts": now_utc(),
                "sql": re.sub(r"\s+", " ", sql).strip(),
                "params": list(params),
                "result": rows if len(rows) <= 20 else f"{len(rows)} rows",
            }
        )
        return rows
