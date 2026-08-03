# core/modules/assistant/stream_bridge.py
#
# Drives a blocking sync generator from a worker thread and surfaces its
# items to the event loop.
#
# Same job as agent.py's _aiter_in_thread, deliberately reimplemented here
# instead of imported: that one lives in a route module that imports
# modules/agent at module level, and modules/agent is stripped from the
# free image. The assistant ships in BOTH editions, so it cannot reach into
# a paid module to borrow a helper — the import would fail at startup, not
# at call time.
#
# The model lock is acquired here, around the whole generation, exactly as
# the agent path does: a token stream that released the lock between chunks
# would let a concurrent request interleave into the same llama context.
# It is taken lazily so this module stays importable on the free image.

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from typing import AsyncIterator, Callable, Iterator


def _model_lock():
    """The backend's generation lock, or a no-op when there is no backend."""
    try:
        from modules.agent.llm_backend import _LLAMA_LOCK

        return _LLAMA_LOCK
    except ImportError:
        return nullcontext()


async def aiter_in_thread(
    make_iter: Callable[[], Iterator[str]],
) -> AsyncIterator[str]:
    """Yield items from a blocking generator without starving the loop.

    ``make_iter`` is a zero-argument factory so the generator is created
    *inside* the worker thread. Items and any terminal exception travel
    back through a queue, so every chunk hands control to the event loop —
    which is what keeps /health answering while a long generation runs.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    def _producer() -> None:
        try:
            with _model_lock():
                for item in make_iter():
                    loop.call_soon_threadsafe(queue.put_nowait, item)
        except Exception as exc:  # surface to the consumer, never kill the thread
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, sentinel)

    future = loop.run_in_executor(None, _producer)
    try:
        while True:
            item = await queue.get()
            if item is sentinel:
                break
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        await future
