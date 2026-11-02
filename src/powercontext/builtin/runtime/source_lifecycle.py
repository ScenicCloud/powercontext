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

"""Propagate withdrawn Source support through Memory and Topic Memory."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator
from sqlalchemy import text

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.persistence.database import AsyncDatabase
from powercontext.builtin.runtime.models import GetMemoryEntryRequest
from powercontext.builtin.sources import validate_scope_id
from powercontext.sources import SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.artifacts.memory import MemoryService
    from powercontext.builtin.runtime.application import BuiltinRuntime

Policy = Literal["all", "any"]
Purpose = Literal["generation", "audit"]
NodeKind = Literal["source", "memory", "topic"]

_TABLE = "pc_source_lifecycle_nodes"
_MEMORY_REASON = "source lifecycle"

_NODE_COLUMNS = (
    "node_id, kind, reference_json, parents_json, policy, available, ordinal, "
    "source_revision, last_sequence, last_available"
)
_SELECT_BY_SCOPE = f"SELECT {_NODE_COLUMNS} FROM {_TABLE} WHERE scope_id = :scope_id ORDER BY ordinal"  # noqa: S608
_SELECT_BY_NODE = f"SELECT {_NODE_COLUMNS} FROM {_TABLE} WHERE scope_id = :scope_id AND node_id = :node_id"  # noqa: S608
_SELECT_NEXT_ORDINAL = f"SELECT COALESCE(MAX(ordinal), -1) + 1 FROM {_TABLE} WHERE scope_id = :scope_id"  # noqa: S608
_INSERT_NODE = (
    f"INSERT INTO {_TABLE} (scope_id, node_id, kind, ordinal, reference_json, parents_json, "  # noqa: S608
    "policy, available, source_revision, last_sequence, last_available) VALUES (:scope_id, :node_id, :kind, "
    ":ordinal, :reference_json, :parents_json, :policy, :available, :source_revision, :last_sequence, "
    ":last_available)"
)
_UPDATE_AVAILABLE = (
    f"UPDATE {_TABLE} SET available = :available "  # noqa: S608
    "WHERE scope_id = :scope_id AND node_id = :node_id"
)
_UPDATE_SOURCE_EVENT = (
    f"UPDATE {_TABLE} SET last_sequence = :sequence, last_available = :available "  # noqa: S608
    "WHERE scope_id = :scope_id AND node_id = :node_id"
)
_SELECT_INACTIVE_TOPICS = (
    f"SELECT reference_json FROM {_TABLE} "  # noqa: S608
    "WHERE scope_id = :scope_id AND kind = 'topic' AND available = 0"
)


class SourceLifecycleError(ValueError):
    """Reject a lifecycle binding, event, or resolution request."""


class SourceLifecycleEvent(BaseModel):
    """One source availability transition with an exact lifecycle revision."""

    model_config = ConfigDict(extra="forbid")

    node_id: str
    revision: StrictInt = Field(gt=0)
    sequence: StrictInt = Field(gt=0)
    available: StrictBool
    reason: str

    @field_validator("node_id", "reason")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-blank string")
        return value


@dataclass(frozen=True)
class _LifecycleNode:
    node_id: str
    kind: NodeKind
    reference: dict[str, Any]
    parents: tuple[str, ...]
    policy: Policy
    available: bool
    ordinal: int
    source_revision: int | None
    last_sequence: int | None
    last_available: bool | None

    def reference_model(self) -> SourceRef | MemoryCitation | ArtifactRef:
        if self.kind == "source":
            return SourceRef.model_validate(self.reference)
        if self.kind == "memory":
            return MemoryCitation.model_validate(self.reference)
        return ArtifactRef.model_validate(self.reference)


class SourceLifecycleStore:
    """Persist the per-scope dependency graph and its last observed state."""

    def __init__(self, database: AsyncDatabase) -> None:
        self._database = database

    async def load(self, scope_id: str, /) -> tuple[_LifecycleNode, ...]:
        async with self._database.transaction() as connection:
            rows = (await connection.execute(text(_SELECT_BY_SCOPE), {"scope_id": scope_id})).mappings()
            return tuple(_node_from_row(row) for row in rows)

    async def get(self, scope_id: str, node_id: str, /) -> _LifecycleNode | None:
        async with self._database.transaction() as connection:
            row = (
                (
                    await connection.execute(
                        text(_SELECT_BY_NODE),
                        {"scope_id": scope_id, "node_id": node_id},
                    )
                )
                .mappings()
                .first()
            )
            return None if row is None else _node_from_row(row)

    async def register(self, scope_id: str, candidate: _LifecycleNode, /) -> None:
        """Insert one binding unless an identical binding already exists."""

        async with self._database.transaction() as connection:
            row = (
                (
                    await connection.execute(
                        text(_SELECT_BY_NODE),
                        {"scope_id": scope_id, "node_id": candidate.node_id},
                    )
                )
                .mappings()
                .first()
            )
            if row is not None:
                existing = _node_from_row(row)
                if _same_binding(existing, candidate):
                    return
                raise SourceLifecycleError("node-conflict")
            ordinal = await connection.scalar(
                text(_SELECT_NEXT_ORDINAL),
                {"scope_id": scope_id},
            )
            await connection.execute(
                text(_INSERT_NODE),
                {
                    "scope_id": scope_id,
                    "node_id": candidate.node_id,
                    "kind": candidate.kind,
                    "ordinal": int(ordinal or 0),
                    "reference_json": _dump(candidate.reference),
                    "parents_json": _dump(list(candidate.parents)),
                    "policy": candidate.policy,
                    "available": int(candidate.available),
                    "source_revision": candidate.source_revision,
                    "last_sequence": candidate.last_sequence,
                    "last_available": _optional_int(candidate.last_available),
                },
            )

    async def save(
        self,
        scope_id: str,
        desired: Mapping[str, bool],
        /,
        *,
        source_node_id: str,
        sequence: int,
        available: bool,
    ) -> None:
        """Commit recomputed availability only after native propagation succeeded."""

        async with self._database.transaction() as connection:
            for node_id, node_available in desired.items():
                await connection.execute(
                    text(_UPDATE_AVAILABLE),
                    {"available": int(node_available), "scope_id": scope_id, "node_id": node_id},
                )
            await connection.execute(
                text(_UPDATE_SOURCE_EVENT),
                {
                    "sequence": sequence,
                    "available": int(available),
                    "scope_id": scope_id,
                    "node_id": source_node_id,
                },
            )

    async def inactive_topic_ids(self, scope_id: str, /) -> frozenset[str]:
        async with self._database.transaction() as connection:
            rows = (await connection.execute(text(_SELECT_INACTIVE_TOPICS), {"scope_id": scope_id})).scalars()
            identifiers: set[str] = set()
            for payload in rows:
                try:
                    reference = json.loads(payload)
                except (TypeError, ValueError):
                    continue
                artifact_id = reference.get("artifact_id") if isinstance(reference, dict) else None
                if isinstance(artifact_id, str):
                    identifiers.add(artifact_id)
            return frozenset(identifiers)


class LifecycleApplication:
    """Select the lifecycle service bound to one scope."""

    def __init__(self, runtime: BuiltinRuntime, store: SourceLifecycleStore | None) -> None:
        self._runtime = runtime
        self._store = store

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycleApplication:
        return ScopedSourceLifecycleApplication(self._runtime, self._store, scope_id)


class ScopedSourceLifecycleApplication:
    """Register a dependency graph and propagate Source lifecycle events."""

    def __init__(
        self,
        runtime: BuiltinRuntime,
        store: SourceLifecycleStore | None,
        scope_id: str,
    ) -> None:
        self._runtime = runtime
        self._store = store
        self.scope_id = validate_scope_id(scope_id)

    async def register_source(
        self,
        node_id: str,
        source_ref: SourceRef,
        /,
        *,
        revision: int = 1,
    ) -> None:
        _require_node_id(node_id)
        if not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("source-reference")
        _require_positive_int(revision, "revision")
        await self._require_source(source_ref)
        candidate = _LifecycleNode(
            node_id=node_id,
            kind="source",
            reference=source_ref.model_dump(mode="json"),
            parents=(),
            policy="all",
            available=True,
            ordinal=0,
            source_revision=revision,
            last_sequence=None,
            last_available=None,
        )
        await self._store_or_raise().register(self.scope_id, candidate)

    async def register_memory(
        self,
        node_id: str,
        citation: MemoryCitation,
        /,
        *,
        parents: Sequence[str] = (),
        policy: Policy = "all",
    ) -> None:
        _require_node_id(node_id)
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("memory-citation")
        parent_ids = _require_parents(node_id, parents, policy)
        await self._require_memory(citation)
        nodes = await self._store_or_raise().load(self.scope_id)
        available = self._derived_availability(nodes, node_id, parent_ids, policy)
        candidate = _LifecycleNode(
            node_id=node_id,
            kind="memory",
            reference=citation.model_dump(mode="json"),
            parents=parent_ids,
            policy=policy,
            available=available,
            ordinal=0,
            source_revision=None,
            last_sequence=None,
            last_available=None,
        )
        if not available:
            await self._deactivate_new_memory(citation)
        await self._store_or_raise().register(self.scope_id, candidate)

    async def register_topic(
        self,
        node_id: str,
        artifact_ref: ArtifactRef,
        /,
        *,
        parents: Sequence[str] = (),
        policy: Policy = "all",
    ) -> None:
        _require_node_id(node_id)
        if not isinstance(artifact_ref, ArtifactRef):
            raise SourceLifecycleError("topic-reference")
        if artifact_ref.family != "topic-memory":
            raise SourceLifecycleError("topic-family")
        parent_ids = _require_parents(node_id, parents, policy)
        await self._require_topic(artifact_ref)
        nodes = await self._store_or_raise().load(self.scope_id)
        available = self._derived_availability(nodes, node_id, parent_ids, policy)
        candidate = _LifecycleNode(
            node_id=node_id,
            kind="topic",
            reference=artifact_ref.model_dump(mode="json"),
            parents=parent_ids,
            policy=policy,
            available=available,
            ordinal=0,
            source_revision=None,
            last_sequence=None,
            last_available=None,
        )
        await self._store_or_raise().register(self.scope_id, candidate)

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("event")
        async with self._runtime._context(self.scope_id) as context, self._runtime._locked(self.scope_id):
            nodes = await self._store_or_raise().load(self.scope_id)
            source = next((node for node in nodes if node.node_id == event.node_id), None)
            if source is None or source.kind != "source":
                raise SourceLifecycleError("unknown-source")
            if source.source_revision != event.revision:
                raise SourceLifecycleError("revision-mismatch")
            if source.last_sequence is not None:
                if event.sequence < source.last_sequence:
                    raise SourceLifecycleError("sequence-regressed")
                if event.sequence == source.last_sequence:
                    if event.available != source.last_available:
                        raise SourceLifecycleError("sequence-conflict")
                    return sorted(node.node_id for node in nodes if node.available)
            desired = _recompute(nodes, {event.node_id: event.available})
            changed: dict[str, bool] = {}
            for node in nodes:
                if node.kind != "memory" or desired[node.node_id] == node.available:
                    continue
                entry_id = node.reference.get("entry_id")
                if not isinstance(entry_id, str):
                    raise SourceLifecycleError("stored-node")
                changed[entry_id] = desired[node.node_id]
            if changed:
                await self._sync_memory(context.artifacts.memory, context.artifacts.memory_artifact_id, changed)
            await self._store_or_raise().save(
                self.scope_id,
                desired,
                source_node_id=event.node_id,
                sequence=event.sequence,
                available=event.available,
            )
            return sorted(node_id for node_id, available in desired.items() if available)

    async def resolve(
        self,
        node_id: str,
        /,
        *,
        purpose: Purpose = "generation",
    ) -> SourceRef | MemoryCitation | ArtifactRef:
        if purpose not in ("generation", "audit"):
            raise SourceLifecycleError("purpose")
        async with self._runtime._scope_operation(self.scope_id):
            node = await self._store_or_raise().get(self.scope_id, node_id)
        if node is None:
            raise SourceLifecycleError("unknown-node")
        if purpose == "generation" and not node.available:
            raise SourceLifecycleError("node-unavailable")
        return node.reference_model()

    def _store_or_raise(self) -> SourceLifecycleStore:
        if self._store is None:
            raise SourceLifecycleError("lifecycle-unavailable")
        return self._store

    def _derived_availability(
        self,
        nodes: Sequence[_LifecycleNode],
        node_id: str,
        parents: tuple[str, ...],
        policy: Policy,
    ) -> bool:
        registered = {node.node_id: node for node in nodes}
        if node_id in registered:
            raise SourceLifecycleError("node-conflict")
        missing = [parent for parent in parents if parent not in registered]
        if missing:
            raise SourceLifecycleError("unknown-parent")
        return _policy_available(policy, (registered[parent].available for parent in parents))

    async def _require_source(self, source_ref: SourceRef) -> None:
        try:
            await self._runtime.records.for_scope(self.scope_id).get_source(
                source_ref.source_type, source_ref.source_id
            )
        except Exception as error:
            raise SourceLifecycleError("source-unreadable") from error

    async def _require_memory(self, citation: MemoryCitation) -> None:
        try:
            await self._runtime.memory.for_scope(self.scope_id).get(GetMemoryEntryRequest(citation=citation))
        except Exception as error:
            raise SourceLifecycleError("memory-unreadable") from error

    async def _require_topic(self, artifact_ref: ArtifactRef) -> None:
        try:
            await self._runtime.records.for_scope(self.scope_id).get_artifact_revision(
                artifact_ref.family, artifact_ref.artifact_id, artifact_ref.revision
            )
        except Exception as error:
            raise SourceLifecycleError("topic-unreadable") from error

    async def _deactivate_new_memory(self, citation: MemoryCitation) -> None:
        async with self._runtime._context(self.scope_id) as context, self._runtime._locked(self.scope_id):
            await self._sync_memory(
                context.artifacts.memory, context.artifacts.memory_artifact_id, {citation.entry_id: False}
            )

    async def _sync_memory(
        self,
        service: MemoryService,
        artifact_id: str,
        desired: Mapping[str, bool],
    ) -> None:
        """Apply entry state changes through the authoritative Memory service."""

        current = await service.head(artifact_id)
        entries = {entry.entry_id: entry for entry in await service.entries(current)}
        states = {entry.entry_id: entry.state for entry in current.content.manifest.entries}
        to_forget = tuple(
            entries[entry_id]
            for entry_id, active in desired.items()
            if not active and entry_id in entries and states.get(entry_id) == "active"
        )
        to_reactivate = tuple(
            entries[entry_id]
            for entry_id, active in desired.items()
            if active and entry_id in entries and states.get(entry_id) == "inactive"
        )
        if to_forget:
            current = await service.forget(current, entries=to_forget, reason=_MEMORY_REASON)
        if to_reactivate:
            current = await service.reactivate(current, entries=to_reactivate, reason=_MEMORY_REASON)


def _node_from_row(row: Mapping[str, Any]) -> _LifecycleNode:
    try:
        reference = json.loads(row["reference_json"])
        parents = tuple(json.loads(row["parents_json"]))
    except (TypeError, ValueError, KeyError) as error:
        raise SourceLifecycleError("stored-node") from error
    kind = str(row["kind"])
    if kind not in ("source", "memory", "topic"):
        raise SourceLifecycleError("stored-kind")
    policy = str(row["policy"])
    if policy not in ("all", "any"):
        raise SourceLifecycleError("stored-policy")
    return _LifecycleNode(
        node_id=str(row["node_id"]),
        kind=kind,
        reference=reference,
        parents=parents,
        policy=policy,
        available=bool(row["available"]),
        ordinal=int(row["ordinal"]),
        source_revision=None if row["source_revision"] is None else int(row["source_revision"]),
        last_sequence=None if row["last_sequence"] is None else int(row["last_sequence"]),
        last_available=None if row["last_available"] is None else bool(row["last_available"]),
    )


def _same_binding(left: _LifecycleNode, right: _LifecycleNode) -> bool:
    return (
        left.kind == right.kind
        and left.reference == right.reference
        and left.parents == right.parents
        and left.policy == right.policy
        and left.source_revision == right.source_revision
    )


def _recompute(nodes: Sequence[_LifecycleNode], override: Mapping[str, bool]) -> dict[str, bool]:
    desired: dict[str, bool] = {}
    for node in nodes:
        if node.kind == "source":
            desired[node.node_id] = override.get(node.node_id, node.available)
            continue
        missing = [parent for parent in node.parents if parent not in desired]
        if missing:
            raise SourceLifecycleError("stored-parent")
        desired[node.node_id] = _policy_available(node.policy, (desired[parent] for parent in node.parents))
    return desired


def _policy_available(policy: Policy, supports: Sequence[bool]) -> bool:
    return all(supports) if policy == "all" else any(supports)


def _require_node_id(node_id: object) -> None:
    if not isinstance(node_id, str) or not node_id.strip():
        raise SourceLifecycleError("node-id")


def _require_positive_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SourceLifecycleError(name)


def _require_parents(node_id: str, parents: Sequence[str], policy: str) -> tuple[str, ...]:
    if policy not in ("all", "any"):
        raise SourceLifecycleError("policy")
    if not parents:
        raise SourceLifecycleError("parents")
    if len(set(parents)) != len(parents):
        raise SourceLifecycleError("duplicate-parent")
    if node_id in parents:
        raise SourceLifecycleError("self-parent")
    if any(not isinstance(parent, str) or not parent.strip() for parent in parents):
        raise SourceLifecycleError("parent")
    return tuple(parents)


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _optional_int(value: bool | None) -> int | None:
    return None if value is None else int(value)


__all__ = [
    "LifecycleApplication",
    "ScopedSourceLifecycleApplication",
    "SourceLifecycleError",
    "SourceLifecycleEvent",
    "SourceLifecycleStore",
]
