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

"""Deterministic context packs and prefix-reusing deltas.

The wire format is the interoperability contract: canonical UTF-8 JSON with
sorted keys, Base64 chunk arrays, SHA-256 digests over the unsigned payload, and
a ``byte_count`` that includes its own encoding.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass

PACK_SCHEMA = "powercontext.context-pack.v1"
DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
DEFAULT_CHUNK_BYTES = 512

_PACK_FIELDS = frozenset({"schema", "items", "digest", "byte_count"})
_DELTA_FIELDS = frozenset({"schema", "base_digest", "target_digest", "prefix_items", "appended"})


class ContextPackError(ValueError):
    """A pack or delta violates the wire contract or cannot be reconstructed."""


@dataclass(frozen=True, slots=True)
class ContextPack:
    """One complete, self-describing context payload."""

    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    def __post_init__(self) -> None:
        _require_items("items", self.items)
        if not isinstance(self.digest, str) or not self.digest.startswith("sha256:"):
            raise ContextPackError("digest must be a sha256:<hex> string")
        _require_count("byte_count", self.byte_count)

    @classmethod
    def build(cls, items: tuple[bytes, ...], /) -> ContextPack:
        """Construct a complete pack from exact chunks."""

        payload, size = _pack_payload(items)
        return cls(items=tuple(items), digest=str(payload["digest"]), byte_count=size)

    @classmethod
    def from_content(cls, content: str, /, *, chunk_bytes: int = DEFAULT_CHUNK_BYTES) -> ContextPack:
        """Chunk UTF-8 content deterministically without splitting a character."""

        if type(chunk_bytes) is not int or chunk_bytes < 1:
            raise ContextPackError("chunk_bytes must be a positive integer")
        if not isinstance(content, str):
            raise ContextPackError("content must be text")
        return cls.build(_chunks(content.encode("utf-8"), chunk_bytes))

    def to_bytes(self) -> bytes:
        payload, _ = _pack_payload(self.items)
        return _canonical(payload)

    @classmethod
    def from_bytes(cls, payload: bytes, /) -> ContextPack:
        decoded = _decode_object(payload, _PACK_FIELDS, "pack")
        if decoded["schema"] != PACK_SCHEMA:
            raise ContextPackError("unsupported pack schema")
        items = _decode_items("items", decoded["items"])
        digest = decoded["digest"]
        if not isinstance(digest, str) or digest != _digest(items):
            raise ContextPackError("pack digest does not match its items")
        byte_count = decoded["byte_count"]
        _require_count("byte_count", byte_count)
        canonical = _canonical({
            "schema": PACK_SCHEMA,
            "items": _encode_items(items),
            "digest": digest,
            "byte_count": byte_count,
        })
        if byte_count != len(canonical):
            raise ContextPackError("byte_count does not match the encoded pack")
        return cls(items=items, digest=digest, byte_count=byte_count)


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """A reusable base prefix plus the target suffix."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.base_digest, str) or not isinstance(self.target_digest, str):
            raise ContextPackError("digests must be strings")
        _require_count("prefix_items", self.prefix_items)
        _require_items("appended", self.appended)

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack, /) -> ContextPackDelta:
        """Reuse the longest common chunk prefix and carry the target suffix."""

        prefix = 0
        for left, right in zip(base.items, target.items, strict=False):
            if left != right:
                break
            prefix += 1
        return cls(
            base_digest=base.digest,
            target_digest=target.digest,
            prefix_items=prefix,
            appended=target.items[prefix:],
        )

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        return _canonical({
            "schema": DELTA_SCHEMA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": _encode_items(self.appended),
        })

    @classmethod
    def from_bytes(cls, payload: bytes, /) -> ContextPackDelta:
        decoded = _decode_object(payload, _DELTA_FIELDS, "delta")
        if decoded["schema"] != DELTA_SCHEMA:
            raise ContextPackError("unsupported delta schema")
        base_digest = decoded["base_digest"]
        target_digest = decoded["target_digest"]
        if not isinstance(base_digest, str) or not isinstance(target_digest, str):
            raise ContextPackError("delta digests must be strings")
        prefix = decoded["prefix_items"]
        _require_count("prefix_items", prefix)
        appended = _decode_items("appended", decoded["appended"])
        return cls(
            base_digest=base_digest,
            target_digest=target_digest,
            prefix_items=prefix,
            appended=appended,
        )


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta, /) -> ContextPack:
    """Verify one delta against its base and rebuild the target pack."""

    if not isinstance(base, ContextPack) or not isinstance(delta, ContextPackDelta):
        raise ContextPackError("base and delta must be decoded context pack values")
    if delta.base_digest != base.digest:
        raise ContextPackError("delta base digest does not match the supplied pack")
    if delta.prefix_items > len(base.items):
        raise ContextPackError("prefix_items exceeds the base chunk count")
    items = (*base.items[: delta.prefix_items], *delta.appended)
    if _digest(items) != delta.target_digest:
        raise ContextPackError("reconstructed items do not match the target digest")
    return ContextPack.build(items)


def _chunks(data: bytes, limit: int) -> tuple[bytes, ...]:
    if not data:
        return ()
    chunks: list[bytes] = []
    start = 0
    while start < len(data):
        end = min(start + limit, len(data))
        if end < len(data):
            # Step back to the start of the character straddling the limit.
            while end > start and data[end] & 0xC0 == 0x80:
                end -= 1
            if end == start:
                raise ContextPackError("chunk_bytes is smaller than one UTF-8 character")
        chunks.append(data[start:end])
        start = end
    return tuple(chunks)


def _pack_payload(items: tuple[bytes, ...]) -> tuple[dict[str, object], int]:
    encoded = _encode_items(items)
    digest = _digest(items)
    # byte_count includes its own digits; iterate to the fixed point.
    count = 0
    while True:
        payload: dict[str, object] = {
            "schema": PACK_SCHEMA,
            "items": list(encoded),
            "digest": digest,
            "byte_count": count,
        }
        size = len(_canonical(payload))
        if size == count:
            return payload, size
        count = size


def _digest(items: tuple[bytes, ...]) -> str:
    unsigned = {"schema": PACK_SCHEMA, "items": list(_encode_items(items))}
    return "sha256:" + hashlib.sha256(_canonical(unsigned)).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _encode_items(items: tuple[bytes, ...]) -> tuple[str, ...]:
    return tuple(base64.b64encode(item).decode("ascii") for item in items)


def _decode_items(field: str, value: object) -> tuple[bytes, ...]:
    if not isinstance(value, list):
        raise ContextPackError(f"{field} must be an array of Base64 strings")
    decoded: list[bytes] = []
    for entry in value:
        if not isinstance(entry, str):
            raise ContextPackError(f"{field} must be an array of Base64 strings")
        try:
            decoded.append(base64.b64decode(entry, validate=True))
        except (binascii.Error, ValueError) as error:
            raise ContextPackError(f"{field} contains invalid Base64") from error
    return tuple(decoded)


def _decode_object(payload: bytes, fields: frozenset[str], name: str) -> dict[str, object]:
    if not isinstance(payload, bytes):
        raise ContextPackError(f"{name} payload must be bytes")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContextPackError(f"{name} is not canonical UTF-8 JSON") from error
    if not isinstance(value, dict) or set(value) != fields:
        raise ContextPackError(f"{name} must contain exactly {', '.join(sorted(fields))}")
    return value


def _require_count(field: str, value: object) -> None:
    if type(value) is not int or value < 0:
        raise ContextPackError(f"{field} must be a non-negative integer")


def _require_items(field: str, value: object) -> None:
    if not isinstance(value, tuple) or any(not isinstance(item, bytes) for item in value):
        raise ContextPackError(f"{field} must be a tuple of bytes")


__all__ = [
    "ContextPack",
    "ContextPackDelta",
    "ContextPackError",
    "apply_context_pack_delta",
]
