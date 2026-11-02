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

"""Cross-call coalescing and bounded caching for document embeddings."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from collections.abc import Iterable, Mapping

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel


class _Batch:
    """One dispatched provider request shared by every waiter it serves."""

    __slots__ = ("usage",)

    def __init__(self) -> None:
        self.usage = InferenceUsage(requests=0)


class _Waiter:
    """One distinct text and the batch that will eventually produce its vector."""

    __slots__ = ("batch", "future")

    def __init__(self, future: asyncio.Future[EmbeddingVector]) -> None:
        self.future = future
        self.batch: _Batch | None = None


def _retrieve_outcome(future: asyncio.Future[EmbeddingVector]) -> None:
    # Waiters may be abandoned when a caller is cancelled; keep the loop quiet.
    if not future.cancelled():
        future.exception()


class CoalescingEmbeddingModel:
    """Share in-flight work for identical texts and cache successful vectors.

    Concurrent callers join one provider batch per distinct text set. Each caller
    still receives vectors in its own order and only pays for batches it awaited.
    """

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if max_batch_size < 1:
            raise ValueError("max_batch_size must be positive")  # noqa: TRY003
        self.profile = model.profile
        self._model = model
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = max(coalesce_ms, 0.0) / 1000.0
        self._cache_size = max(cache_size, 0)
        self._cache: OrderedDict[str, EmbeddingVector] | None = None if cache_size <= 0 else OrderedDict()
        self._pending: dict[str, _Waiter] = {}
        self._queue: deque[str] = deque()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wakeup = asyncio.Event()
        self._dispatcher: asyncio.Task[None] | None = None

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        """Return one vector per input text, in input order, with awaited-batch usage."""

        if not texts:
            return EmbeddingResult(vectors=())

        loop = asyncio.get_running_loop()
        resolved: dict[str, EmbeddingVector] = {}
        waiting: list[tuple[str, _Waiter]] = []
        for text in dict.fromkeys(texts):
            cached = self._cached(text)
            if cached is not None:
                resolved[text] = cached
                continue
            waiter = self._pending.get(text)
            if waiter is None:
                waiter = _Waiter(loop.create_future())
                waiter.future.add_done_callback(_retrieve_outcome)
                self._pending[text] = waiter
                self._queue.append(text)
            waiting.append((text, waiter))

        if waiting:
            self._ensure_dispatcher(loop)
            # Shield each shared future so cancelling one caller leaves the batch intact.
            vectors = await asyncio.gather(*(asyncio.shield(waiter.future) for _, waiter in waiting))
            for (text, _), vector in zip(waiting, vectors, strict=True):
                resolved[text] = vector

        batches: dict[int, _Batch] = {}
        for _, waiter in waiting:
            if waiter.batch is not None:
                batches[id(waiter.batch)] = waiter.batch
        return EmbeddingResult(
            vectors=tuple(resolved[text] for text in texts),
            usage=_aggregate_usage(tuple(batches.values())),
        )

    def _cached(self, text: str) -> EmbeddingVector | None:
        cache = self._cache
        if cache is None:
            return None
        vector = cache.get(text)
        if vector is not None:
            cache.move_to_end(text)
        return vector

    def _store(self, vectors: Mapping[str, EmbeddingVector]) -> None:
        cache = self._cache
        if cache is None:
            return
        for text, vector in vectors.items():
            cache[text] = vector
            cache.move_to_end(text)
        while len(cache) > self._cache_size:
            cache.popitem(last=False)

    def _ensure_dispatcher(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._loop is loop and self._dispatcher is not None and not self._dispatcher.done():
            self._wakeup.set()
            return
        self._loop = loop
        self._wakeup = asyncio.Event()
        self._wakeup.set()
        self._dispatcher = loop.create_task(self._dispatch_loop(self._wakeup))

    async def _dispatch_loop(self, wakeup: asyncio.Event) -> None:
        while True:
            await wakeup.wait()
            wakeup.clear()
            if not self._queue:
                continue
            if self._coalesce_seconds:
                # Give near-simultaneous callers a chance to join the same batch.
                await asyncio.sleep(self._coalesce_seconds)
            tasks = [asyncio.create_task(self._run_batch(texts)) for texts in self._next_batches()]
            if tasks:
                await asyncio.gather(*tasks)

    def _next_batches(self) -> list[tuple[str, ...]]:
        batches: list[tuple[str, ...]] = []
        while self._queue:
            size = min(self._max_batch_size, len(self._queue))
            batches.append(tuple(self._queue.popleft() for _ in range(size)))
        return batches

    async def _run_batch(self, texts: tuple[str, ...]) -> None:
        waiters = {text: self._pending[text] for text in texts}
        batch = _Batch()
        for waiter in waiters.values():
            waiter.batch = batch
        try:
            result = await self._model.embed(texts)
        except asyncio.CancelledError:
            self._release(texts, waiters, cancel=True)
            raise
        except Exception as error:
            self._release(texts, waiters, error=error)
            return
        if len(result.vectors) != len(texts):
            error = ValueError("provider returned the wrong vector count")
            self._release(texts, waiters, error=error)
            return
        vectors = dict(zip(texts, result.vectors, strict=True))
        batch.usage = result.usage
        self._store(vectors)
        for text in texts:
            self._pending.pop(text, None)
        for text, waiter in waiters.items():
            if not waiter.future.done():
                waiter.future.set_result(vectors[text])

    def _release(
        self,
        texts: tuple[str, ...],
        waiters: Mapping[str, _Waiter],
        *,
        error: Exception | None = None,
        cancel: bool = False,
    ) -> None:
        for text in texts:
            self._pending.pop(text, None)
        for waiter in waiters.values():
            if waiter.future.done():
                continue
            if cancel:
                waiter.future.cancel()
            elif error is not None:
                waiter.future.set_exception(error)


def _aggregate_usage(batches: tuple[_Batch, ...]) -> InferenceUsage:
    if not batches:
        return InferenceUsage(requests=0)
    return InferenceUsage(
        requests=sum(batch.usage.requests for batch in batches),
        input_tokens=_sum_tokens(batch.usage.input_tokens for batch in batches),
        output_tokens=_sum_tokens(batch.usage.output_tokens for batch in batches),
    )


def _sum_tokens(values: Iterable[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None


__all__ = ["CoalescingEmbeddingModel"]
