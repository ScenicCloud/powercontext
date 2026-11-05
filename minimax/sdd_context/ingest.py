"""Parse engineering material into seekdb documents and chunks."""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from .store import Chunk, SeekDBStore, stable_id

MARKDOWN_KINDS = {
    "service_spec": "spec",
    "api_contract": "spec",
    "decisions": "decision",
}


@dataclass
class DocumentPlan:
    doc_id: str
    kind: str
    path: str
    title: str
    body: str
    content_hash: str
    chunks: list[Chunk] = field(default_factory=list)


@dataclass
class IngestSummary:
    project: str
    documents: int
    chunks: int
    changed: list[str]
    unchanged: list[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "project": self.project,
            "documents": self.documents,
            "chunks": self.chunks,
            "changed": self.changed,
            "unchanged": self.unchanged,
        }


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _line_range(text: str, start: int, end: int) -> list[int]:
    return [start, end + 1]


def _markdown_chunks(plan: DocumentPlan) -> list[Chunk]:
    lines = plan.body.splitlines()
    headings = [index for index, line in enumerate(lines) if line.startswith("##")]
    chunks: list[Chunk] = []
    for ordinal, start in enumerate(headings):
        end = headings[ordinal + 1] - 1 if ordinal + 1 < len(headings) else len(lines) - 1
        block_lines = lines[start : end + 1]
        text = "\n".join(block_lines).strip()
        if not text:
            continue
        heading = block_lines[0].lstrip("#").strip()
        locator = heading.split()[0] if heading.split() else f"block-{ordinal + 1}"
        status = ""
        for block_line in block_lines:
            match = re.match(r"Status:\s*(.*)", block_line.strip(), re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                status = "active" if value.lower() == "active" else value
                break
        chunks.append(
            Chunk(
                chunk_id=stable_id("chk", f"{plan.doc_id}:{locator}:{ordinal}"),
                doc_id=plan.doc_id,
                project="",
                kind=plan.kind,
                path=plan.path,
                title=heading,
                locator=locator,
                line_start=start + 1,
                line_end=end + 1,
                status=status,
                text=text,
            )
        )
    return chunks


def _python_chunks(plan: DocumentPlan, *, kind: str) -> list[Chunk]:
    try:
        tree = ast.parse(plan.body)
    except SyntaxError:
        return []
    _attach_parents(tree)
    chunks: list[Chunk] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if kind == "test" and not node.name.startswith("test"):
            continue
        parent = getattr(node, "parent", None)
        qualified = f"{parent.name}.{node.name}" if isinstance(parent, ast.ClassDef) else node.name
        segment = ast.get_source_segment(plan.body, node) or ""
        if not segment:
            continue
        start = node.lineno
        end = node.end_lineno or node.lineno
        chunks.append(
            Chunk(
                chunk_id=stable_id("chk", f"{plan.doc_id}:{qualified}:{start}"),
                doc_id=plan.doc_id,
                project="",
                kind=kind,
                path=plan.path,
                title=node.name,
                locator=qualified,
                line_start=start,
                line_end=end,
                status="",
                text=segment,
            )
        )
    return chunks


def _attach_parents(tree: ast.AST) -> None:
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child.parent = parent  # type: ignore[attr-defined]


def plan_document(project_root: Path, file_path: Path, project: str) -> DocumentPlan | None:
    relative = file_path.relative_to(project_root).as_posix()
    try:
        body = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    if file_path.suffix == ".md":
        name = file_path.stem
        kind = MARKDOWN_KINDS.get(name, "spec")
    elif file_path.suffix == ".py":
        if relative.startswith("tests/"):
            kind = "test"
        else:
            kind = "code"
        _attach_parents(ast.parse(body))
    else:
        return None
    title = file_path.stem.replace("_", " ")
    plan = DocumentPlan(
        doc_id=stable_id("doc", f"{project}:{relative}"),
        kind=kind,
        path=relative,
        title=title,
        body=body,
        content_hash=hash_text(body),
    )
    if kind in ("spec", "decision"):
        plan.chunks = _markdown_chunks(plan)
    else:
        plan.chunks = _python_chunks(plan, kind=kind)
    for chunk in plan.chunks:
        chunk.project = project
    return plan


def collect_files(project_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(project_root.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or ".venv" in path.parts:
            continue
        if path.suffix in (".py", ".md"):
            files.append(path)
    return files


def ingest_project(store: SeekDBStore, *, project_root: Path, project: str) -> IngestSummary:
    documents = 0
    chunks = 0
    changed: list[str] = []
    unchanged: list[str] = []
    for file_path in collect_files(project_root):
        plan = plan_document(project_root, file_path, project)
        if plan is None:
            continue
        documents += 1
        written = store.replace_document(
            doc_id=plan.doc_id,
            project=project,
            kind=plan.kind,
            path=plan.path,
            title=plan.title,
            content_hash=plan.content_hash,
            body=plan.body,
            chunks=plan.chunks,
        )
        chunks += len(plan.chunks)
        (changed if written else unchanged).append(plan.path)
    store.record_run(project=project, documents=documents, chunks=chunks, note=f"{len(changed)} changed")
    return IngestSummary(
        project=project,
        documents=documents,
        chunks=chunks,
        changed=changed,
        unchanged=unchanged,
    )


def ingest_markdown(store: SeekDBStore, *, path: Path, project: str, kind: str = "spec") -> IngestSummary:
    """Ingest a single markdown file as a standalone evolution fixture."""

    body = path.read_text(encoding="utf-8")
    doc_id = stable_id("doc", f"{project}:{path.name}")
    plan = DocumentPlan(
        doc_id=doc_id,
        kind=kind,
        path=path.name,
        title=path.stem.replace("_", " "),
        body=body,
        content_hash=hash_text(body),
    )
    plan.chunks = _markdown_chunks(plan)
    for chunk in plan.chunks:
        chunk.project = project
    written = store.replace_document(
        doc_id=doc_id,
        project=project,
        kind=kind,
        path=plan.path,
        title=plan.title,
        content_hash=plan.content_hash,
        body=plan.body,
        chunks=plan.chunks,
    )
    return IngestSummary(
        project=project,
        documents=1,
        chunks=len(plan.chunks),
        changed=[plan.path] if written else [],
        unchanged=[] if written else [plan.path],
    )
