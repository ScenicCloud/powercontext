# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Pi session branch capture with durable incremental collection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from pydantic import BaseModel, JsonValue

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.connectors import (
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
)
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PI_EVENT_SOURCE_NAME = "pi-event"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"


class PiSessionInput(BaseModel):
    """A complete Pi v3 JSONL archive and the branch leaf to capture."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event on the selected branch plus its complete input record."""

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source):
    """Captured immutable Pi event."""

    source_id: str
    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


def pi_event_source_id(session_id: str, event_id: str) -> str:
    """Build the stable identity of one event inside one session."""

    if not session_id or not event_id:
        raise ValueError("session_id and event_id must be non-empty")
    source_id = f"pi:{quote(session_id, safe='')}:{quote(event_id, safe='')}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"pi event source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters")
    return source_id


def parse_pi_session(value: PiSessionInput, /) -> tuple[PiEventInput, ...]:
    """Parse the complete ancestor branch of one selected Pi leaf."""

    records = _load_records(value.content)
    header = records[0]
    session_id = header.get("id")
    if header.get("type") != "session" or header.get("version") != 3:
        raise ValueError("Pi archive must start with a version 3 session header")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Pi session header must contain a non-empty id")

    nodes: dict[str, dict[str, JsonValue]] = {}
    parent_by_id: dict[str, str | None] = {}
    for record in records[1:]:
        event_id = record.get("id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("Pi records must contain a non-empty string id")
        if event_id in nodes:
            raise ValueError("Pi record ids must be unique")
        if "parentId" not in record:
            raise ValueError("Pi records must declare parentId")
        parent_id = record["parentId"]
        if parent_id is not None and (not isinstance(parent_id, str) or parent_id not in nodes):
            raise ValueError("Pi parentId must be null or reference an earlier record")
        nodes[event_id] = record
        parent_by_id[event_id] = parent_id

    if not nodes:
        if value.leaf_id is not None:
            raise ValueError("leaf_id does not exist in this Pi archive")
        return ()
    leaf = value.leaf_id if value.leaf_id is not None else next(reversed(nodes))
    if leaf not in nodes:
        raise ValueError("leaf_id does not exist in this Pi archive")

    chain: list[dict[str, JsonValue]] = []
    cursor: str | None = leaf
    while cursor is not None:
        chain.append(nodes[cursor])
        cursor = parent_by_id[cursor]
    chain.reverse()

    events: list[PiEventInput] = []
    for record in chain:
        event_type = record.get("type")
        if not isinstance(event_type, str) or not event_type:
            raise ValueError("Pi records must declare a non-empty type")
        visible = _visible_event(record, event_type)
        if visible is None:
            continue
        role, content = visible
        events.append(
            PiEventInput(
                session_id=session_id,
                event_id=str(record["id"]),
                parent_id=parent_by_id[str(record["id"])],
                event_type=event_type,
                role=role,
                content=f"{role}: {content}",
                record=record,
            )
        )
    return tuple(events)


def _load_records(content: bytes) -> list[dict[str, JsonValue]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Pi archive must be strict UTF-8") from error
    records: list[dict[str, JsonValue]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError("Pi archive lines must be valid JSON") from error
        if not isinstance(record, dict):
            raise ValueError("Pi archive records must be JSON objects")
        records.append(record)
    if not records:
        raise ValueError("Pi archive must contain a session header")
    return records


def _visible_event(record: dict[str, JsonValue], event_type: str) -> tuple[str, str] | None:
    if event_type == "message":
        message = record.get("message")
        if not isinstance(message, dict):
            raise ValueError("Pi message records must contain a message object")
        role = message.get("role")
        if not isinstance(role, str) or not role:
            raise ValueError("Pi message records must contain a message role")
        body = _message_body(role, message)
        return None if body is None else (role, body)
    if event_type in {"compaction", "branch_summary"}:
        summary = record.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            return None
        return event_type, summary
    if event_type == "custom_message":
        body = _content_text(record.get("content"))
        return None if body is None else ("custom", body)
    return None


def _message_body(role: str, message: dict[str, JsonValue]) -> str | None:
    if role == "toolResult":
        tool_name = message.get("toolName")
        tool_call_id = message.get("toolCallId")
        if not isinstance(tool_name, str) or not isinstance(tool_call_id, str):
            raise ValueError("Pi tool results must contain toolName and toolCallId")
        text = _content_text(message.get("content")) or ""
        return f"[tool_result {tool_name} {tool_call_id}] {text}"
    if role == "bashExecution":
        command = message.get("command")
        output = message.get("output")
        if not isinstance(command, str) or not isinstance(output, str):
            raise ValueError("Pi bash executions must contain command and output strings")
        return f"$ {command}\n{output}"
    return _content_text(message.get("content"))


def _content_text(content: object) -> str | None:
    if isinstance(content, str):
        return content if content.strip() else None
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text)
        elif block_type == "toolCall":
            name = block.get("name")
            call_id = block.get("id")
            if not isinstance(name, str) or not isinstance(call_id, str):
                raise ValueError("Pi tool calls must contain name and id strings")
            arguments = block.get("arguments")
            if arguments is None:
                arguments = {}
            parts.append(
                f"[tool_call {name} {call_id}] "
                + json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
    return "\n".join(parts) if parts else None


class PiEventAdapter:
    """Resolve and read captured Pi events."""

    input_class = PiEventInput
    name = PI_EVENT_SOURCE_NAME
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        source_id = pi_event_source_id(value.session_id, value.event_id)
        return PiEventSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


class PiEventTextEvidenceProjection:
    """Expose one event's complete text as evidence."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.source_id,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


def _event_fingerprint(event: PiEventInput) -> str:
    encoded = json.dumps(event.record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class PiSessionConnector:
    """Import the visible events of one Pi branch incrementally."""

    name = PI_SESSION_CONNECTOR_NAME
    version = "1"
    source_definitions = frozenset({PI_EVENT_SOURCE_NAME})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self._path = Path(path)
        self._leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        raw = self._path.read_bytes()
        events = parse_pi_session(PiSessionInput(content=raw, leaf_id=self._leaf_id))
        imported = _checkpoint_imports(session.checkpoint)

        updated = dict(imported)
        for event in events:
            fingerprint = _event_fingerprint(event)
            previous = imported.get(event.event_id)
            if previous is not None:
                if previous != fingerprint:
                    raise ValueError(f"imported Pi event {event.event_id!r} was rewritten")
                continue
            await session.submit(event.event_id, PI_EVENT_SOURCE_NAME, event)
            updated[event.event_id] = fingerprint
        return ConnectorRunCompletion(
            status=ConnectorRunStatus.COMPLETE,
            checkpoint={"version": 1, "imported": updated},
        )


def _checkpoint_imports(checkpoint: JsonValue) -> dict[str, str]:
    if checkpoint is None:
        return {}
    if not isinstance(checkpoint, dict) or checkpoint.get("version") != 1:
        raise ValueError("Pi connector checkpoint is invalid")
    imported = checkpoint.get("imported")
    if not isinstance(imported, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in imported.items()
    ):
        raise ValueError("Pi connector checkpoint is invalid")
    return dict(imported)


PI_EVENT_ADAPTER = PiEventAdapter()
PI_EVENT_SOURCE_DEFINITION: AdapterSourceDefinition[PiEventInput, PiEventSource, PiEventInput] = (
    AdapterSourceDefinition(
        PI_EVENT_ADAPTER,
        projections=(PiEventTextEvidenceProjection(),),
    )
)

__all__ = [
    "PI_EVENT_SOURCE_DEFINITION",
    "PI_EVENT_SOURCE_NAME",
    "PI_SESSION_CONNECTOR_NAME",
    "PiEventInput",
    "PiEventSource",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
    "pi_event_source_id",
]
