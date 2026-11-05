"""Select the context required for a task from seekdb candidates."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .store import SeekDBStore

CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
STOP_BIGRAMS = {
    "一个",
    "一些",
    "以及",
    "进行",
    "可以",
    "需要",
    "必须",
    "当前",
    "这个",
    "那个",
    "什么",
    "如何",
    "并且",
    "或者",
    "不是",
    "没有",
}


def split_identifier(value: str) -> list[str]:
    parts = re.split(r"[_\W]+", value)
    camel = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", value)
    return [part.lower() for part in parts + camel if len(part) >= 3]


def query_terms(task: str) -> dict[str, list[str]]:
    identifiers = []
    for token in IDENTIFIER.findall(task):
        if len(token) < 3 or token.islower() and len(token) < 4:
            continue
        identifiers.append(token)
        identifiers.extend(split_identifier(token))
    english: list[str] = []
    for token in identifiers:
        lowered = token.lower()
        if lowered not in english:
            english.append(lowered)

    chinese: list[str] = []
    for run in CJK_RUN.findall(task):
        for size in (2, 3):
            for index in range(len(run) - size + 1):
                gram = run[index : index + size]
                if size == 2 and gram in STOP_BIGRAMS:
                    continue
                if gram not in chinese:
                    chinese.append(gram)
    return {"english": english, "chinese": chinese}


@dataclass
class Candidate:
    chunk_id: str
    kind: str
    path: str
    locator: str
    line_start: int
    line_end: int
    status: str
    text: str
    score: float
    matched: set[str] = field(default_factory=set)

    def as_source(self) -> dict[str, Any]:
        source = {
            "path": self.path,
            "locator": self.locator,
            "lines": [self.line_start, self.line_end],
            "score": round(self.score, 3),
            "matched": sorted(self.matched),
            "text": self.text,
        }
        if self.kind == "decision":
            source["status"] = self.status
        return source


def _merge(
    fts_rows: Iterable[dict[str, Any]],
    like_rows: Iterable[dict[str, Any]],
    *,
    english: Sequence[str],
    chinese: Sequence[str],
    idf: dict[str, float],
) -> list[Candidate]:
    merged: dict[str, Candidate] = {}

    def add(row: dict[str, Any], matched: set[str], weight: float, raw_score: float = 0.0) -> None:
        chunk_id = row["chunk_id"]
        candidate = merged.get(chunk_id)
        if candidate is None:
            candidate = Candidate(
                chunk_id=chunk_id,
                kind="",
                path=row["path"],
                locator=row.get("locator", ""),
                line_start=int(row["line_start"]),
                line_end=int(row["line_end"]),
                status=row.get("status", ""),
                text=row["text"],
                score=0.0,
            )
            merged[chunk_id] = candidate
        candidate.score += weight + raw_score + sum(idf.get(term, 0.0) for term in matched)
        candidate.matched |= matched

    fts_rows = list(fts_rows)
    max_fts = max((float(row.get("score") or 0.0) for row in fts_rows), default=1.0) or 1.0
    for row in fts_rows:
        matched = {term for term in english if term and term.lower() in row["text"].lower()}
        add(row, matched, weight=4.0, raw_score=3.0 * float(row.get("score") or 0.0) / max_fts)
    for row in like_rows:
        matched = {term for term in chinese if term and term in row["text"]}
        add(row, matched, weight=1.0, raw_score=min(float(row.get("hits") or 0.0), 6.0))
    return sorted(merged.values(), key=lambda item: (-item.score, item.path, item.line_start))


def _excluded_chunks(
    store: SeekDBStore, *, project: str, kind: str, keep_ids: set[str]
) -> list[dict[str, Any]]:
    rows = store.list_chunks(project=project, kind=kind)
    return [
        {
            "path": row["path"],
            "locator": row["locator"],
            "lines": [row["line_start"], row["line_end"]],
            "status": row["status"],
            "reason": "inactive decision",
        }
        for row in rows
        if row["chunk_id"] not in keep_ids and row["status"] and row["status"] != "active"
    ]


def select_context(
    store: SeekDBStore,
    *,
    project: str,
    task: str,
    limits: dict[str, int] | None = None,
) -> dict[str, Any]:
    limits = limits or {"spec": 9, "decision": 4, "code": 6, "test": 8}
    terms = query_terms(task)
    english = terms["english"]
    chinese = terms["chinese"]
    trace: dict[str, Any] = {
        "task": task,
        "terms": terms,
        "candidate_counts": {},
        "limits": limits,
    }

    store.ensure_schema()
    selections: dict[str, list[Candidate]] = {}
    for kind in ("spec", "decision", "code", "test"):
        fts_rows = store.fts(english, project=project, kind=kind, limit=40)
        like_rows = store.like(chinese, project=project, kind=kind, limit=40)
        total = max(store.count_chunks(project=project, kind=kind), 1)
        frequencies = store.term_document_frequencies(
            list(dict.fromkeys(english + chinese)), project=project, kind=kind
        )
        idf = {
            term: round(math.log(1 + total / (1 + df)), 4)
            for term, df in frequencies.items()
        }
        merged = _merge(
            fts_rows, like_rows, english=english, chinese=chinese, idf=idf
        )
        for candidate in merged:
            candidate.kind = kind
        trace["candidate_counts"][kind] = {
            "fts": len(fts_rows),
            "substring": len(like_rows),
            "idf_terms": len(idf),
        }
        selections[kind] = merged

    # Inactive decisions are never used as implementation guidance.
    active_decisions = [item for item in selections["decision"] if item.status == "active"]
    kept_decision_ids = {item.chunk_id for item in active_decisions[: limits["decision"]]}
    excluded_decisions = _excluded_chunks(
        store, project=project, kind="decision", keep_ids=kept_decision_ids
    )

    # Keep the selected spec chunks requirement-first; the API contract is useful
    # but a single table section is enough to avoid crowding out requirement IDs.
    primary_specs = [item for item in selections["spec"] if item.locator.startswith("REQ-")]
    contract_specs = [item for item in selections["spec"] if not item.locator.startswith("REQ-")][:1]
    spec_selection = primary_specs[: max(limits["spec"] - len(contract_specs), 1)] + contract_specs

    result: dict[str, Any] = {
        "task": task,
        "specs": [item.as_source() for item in spec_selection],
        "decisions": [item.as_source() for item in active_decisions[: limits["decision"]]],
        "excluded_decisions": excluded_decisions,
        "code": [item.as_source() for item in selections["code"][: limits["code"]]],
        "tests": [item.as_source() for item in selections["test"][: limits["test"]]],
        "selection_trace": trace,
    }
    return result


def required_sources(context: dict[str, Any], required: dict[str, list[str]]) -> dict[str, list[str]]:
    """Check that every required path/locator pair appears in the selection."""

    missing: dict[str, list[str]] = {}
    for section, expected in required.items():
        selected = context.get(section, [])
        selected_paths = {source.get("path", "") for source in selected}
        selected_pairs = {
            (source.get("path", ""), source.get("locator", "")) for source in selected
        }
        absent: list[str] = []
        for item in expected:
            if "#" in item:
                path, locator = item.split("#", 1)
                if (path, locator) not in selected_pairs:
                    absent.append(item)
            elif item not in selected_paths:
                absent.append(item)
        if absent:
            missing[section] = absent
    return missing
