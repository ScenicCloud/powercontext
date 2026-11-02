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

"""Create the Source lifecycle dependency graph table during startup."""

from sqlalchemy.ext.asyncio import AsyncConnection

_COLUMNS = """
    scope_id {identity} NOT NULL,
    node_id {identity} NOT NULL,
    kind VARCHAR(16) NOT NULL,
    ordinal INTEGER NOT NULL,
    reference_json {text} NOT NULL,
    parents_json {text} NOT NULL,
    policy VARCHAR(8) NOT NULL,
    available INTEGER NOT NULL,
    source_revision INTEGER,
    last_sequence INTEGER,
    last_available INTEGER,
    PRIMARY KEY (scope_id, node_id)
"""


async def ensure_source_lifecycle_schema(connection: AsyncConnection, /) -> None:
    """Create the lifecycle graph idempotently; the runtime owns its rows."""

    if connection.dialect.name == "sqlite":
        columns = _COLUMNS.format(identity="VARCHAR(255)", text="MEDIUMTEXT")
    elif connection.dialect.name == "mysql":
        identity = "VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"
        columns = _COLUMNS.format(identity=identity, text="MEDIUMTEXT")
    else:
        raise ValueError(f"unsupported Source lifecycle dialect: {connection.dialect.name}")  # noqa: TRY003
    await connection.exec_driver_sql(f"CREATE TABLE IF NOT EXISTS pc_source_lifecycle_nodes ({columns})")


__all__ = ["ensure_source_lifecycle_schema"]
