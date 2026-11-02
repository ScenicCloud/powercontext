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

"""One native candidate statement for seekdb/OceanBase hybrid Memory search.

The FULLTEXT and vector projections are separate relations, but a single
statement can rank both channels: each channel is a top-k subquery over its
native index, and ``UNION ALL`` returns the two ordered candidate lists. The
frozen two-query path produced exactly these lists; keeping the same
predicates, ordering and per-channel limit preserves fusion quality bit for
bit while halving the candidate round trips.
"""

from __future__ import annotations

from pyobvector import VECTOR
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import (
    CapabilityNotSupportedError,
    EmbeddingProfile,
    MemoryCapabilities,
    MemoryProjection,
    MemorySearchChannels,
    MemorySearchRequest,
)
from powercontext.builtin.persistence.memory_index import memory_channel_hits
from powercontext.builtin.persistence.oceanbase.memory_index import (
    OceanBaseMemoryFTSIndex,
    OceanBaseMemoryVectorIndex,
)
from powercontext.builtin.persistence.tags import memory_tag_parameters, memory_tag_sql

_HYBRID_SEARCH_SQL = """
SELECT channel, memory_artifact_id, head_revision, entry_id, entry_version_id, text, score
FROM (
    SELECT 'fts' AS channel,
           f.memory_artifact_id,
           f.head_revision,
           f.entry_id,
           f.entry_version_id,
           v.text,
           MATCH(f.searchable_text) AGAINST (:analyzed_query) AS score
    FROM pc_memory_entry_heads AS f
    JOIN pc_memory_entry_versions AS v
      ON v.scope_id = f.scope_id
     AND v.memory_artifact_id = f.memory_artifact_id
     AND v.entry_version_id = f.entry_version_id
    WHERE f.scope_id = :scope_id
      AND f.memory_artifact_id IN :memory_artifact_ids
      AND MATCH(f.searchable_text) AGAINST (:analyzed_query)
    ORDER BY score DESC, f.memory_artifact_id, f.entry_id, f.entry_version_id
    LIMIT :candidate_limit
) AS fts_ranked
UNION ALL
SELECT channel, memory_artifact_id, head_revision, entry_id, entry_version_id, text, score
FROM (
    SELECT 'vector' AS channel,
           m.memory_artifact_id,
           m.head_revision,
           m.entry_id,
           m.entry_version_id,
           v.text,
           l2_distance(m.embedding, :query_vector) AS score
    FROM pc_memory_vector_entries AS m
    JOIN pc_memory_entry_versions AS v
      ON v.scope_id = m.scope_id
     AND v.memory_artifact_id = m.memory_artifact_id
     AND v.entry_version_id = m.entry_version_id
    WHERE m.scope_id = :scope_id
      AND m.memory_artifact_id IN :memory_artifact_ids
    ORDER BY l2_distance(m.embedding, :query_vector) APPROXIMATE
    LIMIT :candidate_limit
) AS vector_ranked
"""

# Tagged candidates must be filtered before each channel's LIMIT. OceanBase
# does not use the approximate vector path when a correlated pre-filter is
# present, matching the frozen vector-index behaviour.
_TAGGED_HYBRID_SEARCH_SQL = (
    _HYBRID_SEARCH_SQL.replace("ORDER BY score DESC", memory_tag_sql("f") + "ORDER BY score DESC", 1)
    .replace("ORDER BY l2_distance", memory_tag_sql("m") + "ORDER BY l2_distance", 1)
    .replace(" APPROXIMATE", "")
)


class OceanBaseHybridMemoryIndex:
    """Expose one candidate statement for hybrid mode and delegate single channels."""

    def __init__(self, profile: EmbeddingProfile) -> None:
        self.profile = profile
        self.fts = OceanBaseMemoryFTSIndex()
        self.vector = OceanBaseMemoryVectorIndex(profile)
        self.capabilities = MemoryCapabilities(
            fts=True,
            vector=True,
            hybrid=True,
            tag_filter=True,
            embedding_profile=profile,
        )
        self.tables = self.fts.tables + self.vector.tables
        self._search_sql = text(_HYBRID_SEARCH_SQL).bindparams(
            bindparam("memory_artifact_ids", expanding=True),
            bindparam("query_vector", type_=VECTOR(profile.dimension)),
        )
        self._tagged_search_sql = text(_TAGGED_HYBRID_SEARCH_SQL).bindparams(
            bindparam("memory_artifact_ids", expanding=True),
            bindparam("tag_keys", expanding=True),
            bindparam("tag_hashes", expanding=True),
            bindparam("query_vector", type_=VECTOR(profile.dimension)),
        )

    async def initialize(self, connection: AsyncConnection, /) -> None:
        await self.fts.initialize(connection)
        await self.vector.initialize(connection)

    async def replace(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memory_ref: ArtifactRef,
        projections: tuple[MemoryProjection, ...],
        /,
    ) -> None:
        await self.fts.replace(connection, scope_id, memory_ref, projections)
        await self.vector.replace(connection, scope_id, memory_ref, projections)

    async def delete(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memory_ref: ArtifactRef,
        entry_ids: tuple[str, ...],
        /,
    ) -> None:
        await self.fts.delete(connection, scope_id, memory_ref, entry_ids)
        await self.vector.delete(connection, scope_id, memory_ref, entry_ids)

    async def upsert(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memory_ref: ArtifactRef,
        projections: tuple[MemoryProjection, ...],
        /,
    ) -> None:
        await self.fts.upsert(connection, scope_id, memory_ref, projections)
        await self.vector.upsert(connection, scope_id, memory_ref, projections)

    async def search(
        self,
        connection: AsyncConnection,
        scope_id: str,
        request: MemorySearchRequest,
        /,
    ) -> MemorySearchChannels:
        if request.mode == "fts":
            return await self.fts.search(connection, scope_id, request)
        if request.mode == "vector":
            return await self.vector.search(connection, scope_id, request)
        if request.mode != "hybrid":
            return MemorySearchChannels()
        if request.embedding_profile != self.profile or request.query_vector is None:
            raise CapabilityNotSupportedError("embedding-profile")
        if not await self.vector.vector_complete(connection, scope_id, request.memories, self.profile):
            raise CapabilityNotSupportedError("vector")
        rows = (
            (
                await connection.execute(
                    self._search_sql if request.tag_filter is None else self._tagged_search_sql,
                    {
                        "scope_id": scope_id,
                        "memory_artifact_ids": tuple(memory.artifact_id for memory in request.memories),
                        "analyzed_query": request.analyzed_query,
                        "query_vector": request.query_vector,
                        "candidate_limit": request.candidate_limit,
                        **memory_tag_parameters(request.tag_filter),
                    },
                )
            )
            .mappings()
            .all()
        )
        return MemorySearchChannels(
            fts=memory_channel_hits(
                tuple(row for row in rows if str(row["channel"]) == "fts"),
                request.memories,
            ),
            vector=memory_channel_hits(
                tuple({**row, "distance": row["score"]} for row in rows if str(row["channel"]) == "vector"),
                request.memories,
            ),
        )

    async def vector_complete(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memories: tuple[ArtifactRef, ...],
        profile: EmbeddingProfile,
        /,
    ) -> bool:
        return await self.vector.vector_complete(connection, scope_id, memories, profile)

    async def hydrate(
        self,
        connection: AsyncConnection,
        scope_id: str,
        projections: tuple[MemoryProjection, ...],
        /,
    ) -> tuple[MemoryProjection, ...]:
        return await self.vector.hydrate(connection, scope_id, projections)


__all__ = ["OceanBaseHybridMemoryIndex"]
