import asyncio
import queue
import threading
from collections.abc import Iterator
from typing import Generic
from typing import Optional
from typing import TypeVar

from agents import Agent
from agents import RunResultStreaming
from agents import TContext
from agents.run import Runner

from onyx.utils.threadpool_concurrency import run_in_background

T = TypeVar("T")


class SyncAgentStream(Generic[T]):
    """
    Convert an async streamed run into a sync iterator with cooperative cancellation.
    Runs the Agent in a background thread.

    Usage:
        adapter = SyncStreamAdapter(
            agent=agent,
            input=input,
            context=context,
            max_turns=100,
            queue_maxsize=0,         # optional backpressure
        )
        for ev in adapter:          # sync iteration
            ...
        # or cancel from elsewhere:
        adapter.cancel()
    """

    _SENTINEL = object()

    def __init__(
        self,
        *,
        agent: Agent,
        input: list[dict],
        context: TContext | None = None,
        max_turns: int = 100,
        queue_maxsize: int = 0,
    ) -> None:
        self._agent = agent
        self._input = input
        self._context = context
        self._max_turns = max_turns

        self._q: "queue.Queue[object]" = queue.Queue(maxsize=queue_maxsize)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self.streamed: RunResultStreaming | None = None
        self._exc: Optional[BaseException] = None
        self._cancel_requested = threading.Event()
        self._started = threading.Event()
        self._done = threading.Event()

        self._start_thread()

    # ---------- public sync API ----------

    def __iter__(self) -> Iterator[T]:
        try:
            while True:
                item = self._q.get()
                if item is self._SENTINEL:
                    # If the consumer thread raised, surface it now
                    if self._exc is not None:
                        raise self._exc
                    # Normal completion
                    return
                yield item  # type: ignore[misc,return-value]
        finally:
            # Ensure we fully clean up whether we exited due to exception,
            # StopIteration, or external cancel.
            self.close()

    def cancel(self) -> bool:
        """
        Cooperatively cancel the underlying streamed run and shut down.
        Safe to call multiple times and from any thread.
        """
        self._cancel_requested.set()
        loop = self._loop
        streamed = self.streamed
        if loop is not None and streamed is not None and not self._done.is_set():
            loop.call_soon_threadsafe(streamed.cancel)
            return True
        return False

    def close(self, *, wait: bool = True) -> None:
        """Idempotent shutdown."""
        self.cancel()
        # ask the loop to stop if it's still running
        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
        # join the thread
        if wait and self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    # ---------- internals ----------

    def _start_thread(self) -> None:
        t = run_in_background(self._thread_main)
        self._thread = t
        # Optionally wait until the loop/worker is started so .cancel() is safe soon after init
        self._started.wait(timeout=1.0)

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)

        async def worker() -> None:
            try:
                # Start the streamed run inside the loop thread
                self.streamed = Runner.run_streamed(
                    self._agent,
                    self._input,  # type: ignore[arg-type]
                    context=self._context,
                    max_turns=self._max_turns,
                )

                # If cancel was requested before we created _streamed, honor it now
                if self._cancel_requested.is_set():
                    await self.streamed.cancel()  # type: ignore[func-returns-value]

                # Consume async events and forward into the thread-safe queue
                async for ev in self.streamed.stream_events():
                    # Early exit if a late cancel arrives
                    if self._cancel_requested.is_set():
                        # Try to cancel gracefully; don't break until cancel takes effect
                        try:
                            await self.streamed.cancel()  # type: ignore[func-returns-value]
                        except Exception:
                            pass
                        break
                    # This put() may block if queue_maxsize > 0 (backpressure)
                    self._q.put(ev)

            except BaseException as e:
                # Save exception to surface on the sync iterator side
                self._exc = e
            finally:
                # Signal end-of-stream
                self._q.put(self._SENTINEL)
                self._done.set()

        # Mark started and run the worker to completion
        self._started.set()
        try:
            loop.run_until_complete(worker())
        finally:
            try:
                # Drain pending tasks/callbacks safely
                pending = asyncio.all_tasks(loop=loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            finally:
                loop.close()
                self._loop = None
