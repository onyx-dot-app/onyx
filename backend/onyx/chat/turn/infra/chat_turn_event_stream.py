import asyncio
import logging
import queue
import threading
from collections.abc import Iterator
from queue import Queue
from typing import Optional
from typing import Self

from agents import Agent
from agents import Runner
from agents import RunResultStreaming
from agents import TContext
from agents import TResponseInputItem

from onyx.server.query_and_chat.streaming_models import Packet
from onyx.utils.threadpool_concurrency import run_async_sync
from onyx.utils.threadpool_concurrency import run_in_background
from onyx.utils.threadpool_concurrency import TimeoutThread


logger = logging.getLogger(__name__)


class OnyxRunner:
    """
    Spins up an asyncio loop in a background thread, starts Runner.run_streamed there,
    consumes its async event stream, and exposes a blocking .events() iterator.
    """

    def __init__(self) -> None:
        self._q: "queue.Queue[object]" = queue.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._streamed: Optional[RunResultStreaming] = None
        self.SENTINEL = object()

    def run_streamed_in_background(
        self,
        agent: Agent,
        input: str | list[TResponseInputItem],
        context: TContext | None = None,
        max_turns: int = 100,
    ) -> tuple[Self, TimeoutThread[None]]:
        def worker() -> None:
            async def run_and_consume():
                self._streamed = Runner.run_streamed(
                    agent,
                    input,
                    context=context,
                    max_turns=max_turns,
                )
                try:
                    async for ev in self._streamed.stream_events():
                        self._q.put(ev)
                finally:
                    self._q.put(self.SENTINEL)

            run_async_sync(run_and_consume())

        return self, run_in_background(worker)

    def events(self) -> Iterator[object]:
        while True:
            ev = self._q.get()
            if ev is self.SENTINEL:
                break
            yield ev

    def cancel(self) -> None:
        # Post a cancellation to the loop thread safely
        if self._loop and self._streamed:

            def _do_cancel() -> None:
                try:
                    self._streamed.cancel()
                except Exception:
                    pass

            self._loop.call_soon_threadsafe(_do_cancel)


class Emitter:
    """Use this inside tools to emit arbitrary UI progress."""

    def __init__(self, bus: Queue):
        self.bus = bus
        self.packet_history: list[Packet] = []

    def emit(self, packet: Packet) -> None:
        self.bus.put(packet)
        self.packet_history.append(packet)
