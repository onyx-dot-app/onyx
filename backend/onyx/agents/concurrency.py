"""Thread ownership and finite event delivery for an execution tree."""

import os
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future
from contextvars import copy_context

from pydantic_core import to_json

from onyx.agents.events import AgentEvent
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import (
    start_thread_future,
    start_thread_with_context,
)

logger = setup_logger()
OPERATION_TIMEOUT_SECONDS = 1800.0
CLEANUP_SECONDS = 2.0
EVENT_QUEUE_CAPACITY = 1024
EVENT_FLUSH_INTERVAL_SECONDS = 0.05
AGENT_EVENT_BUFFER_MAX_BYTES = int(
    os.environ.get("AGENT_EVENT_BUFFER_MAX_BYTES", 4 * 1024 * 1024)
)


class WorkTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._count = 0
        self._listeners: set[Callable[[], None]] = set()

    def started(self) -> None:
        with self._lock:
            self._count += 1

    def finished(self) -> None:
        with self._lock:
            self._count -= 1
            listeners = tuple(self._listeners) if self._count == 0 else ()
            if listeners:
                self._listeners.clear()
        for listener in listeners:
            try:
                listener()
            except Exception:
                logger.exception("Agent idle callback failed")

    def on_idle(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Notify once when current work drains; callers must stop admitting new work."""
        with self._lock:
            idle = self._count == 0
            if not idle:
                self._listeners.add(listener)
        if idle:
            listener()

        def unsubscribe() -> None:
            with self._lock:
                self._listeners.discard(listener)

        return unsubscribe

    def follow(self, other: "WorkTracker") -> None:
        """Include existing work after its owner stops admitting new operations."""
        self.started()
        other.on_idle(self.finished)

    def wait_idle(self, timeout: float) -> bool:
        finished = threading.Event()
        unsubscribe = self.on_idle(finished.set)
        try:
            return finished.wait(timeout)
        finally:
            unsubscribe()


def wait_operation[T](
    future: Future[T],
    signal: CancellationSignal,
    timeout: float = OPERATION_TIMEOUT_SECONDS,
) -> T:
    finished = threading.Event()
    future.add_done_callback(lambda _future: finished.set())
    with signal.on_cancel(finished.set):
        signal.check()
        if not finished.wait(timeout):
            raise TimeoutError("Agent operation exceeded its bound")
        signal.check()
        return future.result()


def _report_abandoned_worker[T](future: Future[T]) -> None:
    if future.cancelled():
        return
    error = future.exception()
    if error is not None and not isinstance(error, AgentCancelled):
        logger.error(
            "Agent worker failed after its caller stopped waiting",
            exc_info=(type(error), error, error.__traceback__),
        )


class ExecutionWork:
    """Track a run's jobs independently of its terminal result."""

    def __init__(self) -> None:
        self.tracker = WorkTracker()

    def start[T](self, operation: Callable[[], T]) -> Future[T]:
        self.tracker.started()
        try:
            future = start_thread_future(operation, name="agent-operation")
        except BaseException:
            self.tracker.finished()
            raise
        future.add_done_callback(lambda _future: self.tracker.finished())
        return future

    def blocking[T](
        self,
        operation: Callable[[], T],
        signal: CancellationSignal,
        *,
        timeout: float = OPERATION_TIMEOUT_SECONDS,
    ) -> T:
        signal.check()

        def execute() -> T:
            signal.check()
            with signal.on_operation(self.track_operation):
                return operation()

        future = self.start(execute)
        try:
            return wait_operation(future, signal, timeout)
        except BaseException as error:
            if future.done() and not future.cancelled() and future.exception() is error:
                raise
            self.tracker.started()

            def report(completed: Future[T]) -> None:
                try:
                    _report_abandoned_worker(completed)
                finally:
                    self.tracker.finished()

            future.add_done_callback(report)
            raise

    def track_operation(self, future: Future[None]) -> None:
        self.tracker.started()

        def finished(_future: Future[None]) -> None:
            self.tracker.finished()

        future.add_done_callback(finished)


class EventDispatcher:
    """Deliver queued agent events to listeners on one shared worker.

    The optional flush callback batches listener output on that same worker. It
    receives True after close drains all accepted events, for final output cleanup.
    """

    def __init__(
        self,
        *,
        flush: Callable[[bool], None] | None = None,
    ) -> None:
        self._flush = flush
        self._context = copy_context()
        self._condition = threading.Condition()
        self._queue: deque[tuple[tuple[EventDelivery, ...], AgentEvent, int]] = deque()
        self._bytes = 0
        self._closed = False
        self._release_when_idle = False
        self._worker: threading.Thread | None = None

    def publish(self, delivery: "EventDelivery", event: AgentEvent) -> None:
        channels: list[EventDelivery] = []
        try:
            with self._condition:
                has_listeners = False
                current: EventDelivery | None = delivery
                while current is not None:
                    with current._lock:
                        if not current._closing and not current.failed.is_set():
                            current.tracker.started()
                            channels.append(current)
                            has_listeners |= bool(current._listeners)
                        current = current._parent
                if not has_listeners:
                    return
                size = len(
                    to_json(event.model_dump(mode="python"), bytes_mode="base64")
                )
                if self._closed:
                    raise RuntimeError("Agent event dispatcher is closed")
                if (
                    len(self._queue) >= EVENT_QUEUE_CAPACITY
                    or self._bytes + size > AGENT_EVENT_BUFFER_MAX_BYTES
                ):
                    raise RuntimeError("Agent observer backlog exceeded its bound")
                owned_event = event.model_copy(deep=True)
                self.start()
                self._bytes += size
                self._queue.append((tuple(channels), owned_event, size))
                self._condition.notify()
                channels = []
        except Exception:
            for channel in channels:
                channel.failed.set()
            logger.exception("Agent event delivery could not queue an event")
        finally:
            for channel in channels:
                channel.tracker.finished()

    def start(self) -> None:
        with self._condition:
            if self._worker is None and not self._closed:
                self._worker = start_thread_with_context(
                    self._deliver, name="agent-events", daemon=True
                )

    def _deliver(self) -> None:
        last_flush = time.monotonic()
        while True:
            with self._condition:
                self._condition.wait_for(
                    lambda: self._closed or self._release_when_idle or self._queue,
                    EVENT_FLUSH_INTERVAL_SECONDS
                    if self._flush is not None
                    else OPERATION_TIMEOUT_SECONDS,
                )
                item = self._queue.popleft() if self._queue else None
                exiting = item is None and (
                    self._closed or self._release_when_idle or self._flush is None
                )
                final_flush = exiting and self._closed
            if item is not None:
                channels, event, size = item
                try:
                    for index, channel in enumerate(channels):
                        channel._context.run(
                            channel._send,
                            event
                            if index == len(channels) - 1
                            else event.model_copy(deep=True),
                        )
                finally:
                    with self._condition:
                        self._bytes -= size
                    for channel in channels:
                        channel._context.run(channel.tracker.finished)
            if self._flush is not None and (
                exiting or time.monotonic() - last_flush >= EVENT_FLUSH_INTERVAL_SECONDS
            ):
                try:
                    self._context.run(self._flush, final_flush)
                except Exception:
                    logger.exception("Agent event sink flush failed")
                last_flush = time.monotonic()
            if exiting:
                with self._condition:
                    if self._queue or (
                        self._flush is not None and self._closed and not final_flush
                    ):
                        continue
                    self._worker = None
                    return

    @property
    def is_dispatch_thread(self) -> bool:
        with self._condition:
            return (
                self._worker is not None and self._worker.ident == threading.get_ident()
            )

    def pause(self) -> None:
        """Release the worker when accepted events drain."""
        with self._condition:
            self._release_when_idle = True
            self._condition.notify_all()

    def resume(self) -> None:
        with self._condition:
            self._release_when_idle = False

    def close(self) -> None:
        """Reject new events and drain accepted events within the cleanup bound."""
        with self._condition:
            if self._flush is not None:
                self.start()
            self._closed = True
            self._condition.notify_all()
            worker = self._worker
        if worker is not None and worker.ident != threading.get_ident():
            worker.join(timeout=CLEANUP_SECONDS)
            if worker.is_alive():
                logger.warning("Agent event dispatcher exceeded its cleanup bound")


class EventDelivery:
    """Deliver run events and route foreground child events to ancestor listeners."""

    def __init__(
        self,
        dispatcher: EventDispatcher | None = None,
        *,
        parent: "EventDelivery | None" = None,
    ) -> None:
        if parent is not None:
            if dispatcher is not None and dispatcher is not parent.dispatcher:
                raise ValueError("Related event deliveries must share a dispatcher")
            dispatcher = parent.dispatcher
        self._parent = parent
        self._lock = threading.Lock()
        self._listeners: list[Callable[[AgentEvent], None]] = []
        self._closing = False
        self.failed = threading.Event()
        self.tracker = WorkTracker()
        self._context = copy_context()
        self._owns_dispatcher = dispatcher is None
        self.dispatcher = dispatcher if dispatcher is not None else EventDispatcher()

    def subscribe(self, listener: Callable[[AgentEvent], None]) -> Callable[[], None]:
        with self._lock:
            if not self._closing:
                self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def publish(self, event: AgentEvent) -> None:
        self.dispatcher.publish(self, event)

    @property
    def is_dispatch_thread(self) -> bool:
        return self.dispatcher.is_dispatch_thread

    def _send(self, event: AgentEvent) -> None:
        with self._lock:
            listeners = tuple(self._listeners)
        for index, listener in enumerate(listeners):
            with self._lock:
                if listener not in self._listeners:
                    continue
            try:
                # The queue owns this copy; its last listener can consume it directly.
                listener(
                    event
                    if index == len(listeners) - 1
                    else event.model_copy(deep=True)
                )
            except AgentCancelled:
                self.failed.set()
                logger.debug("Agent observer cancelled")
            except Exception:
                self.failed.set()
                logger.exception("Agent observer failed")

    def resume(self) -> None:
        if self._owns_dispatcher:
            self.dispatcher.resume()

    def pause(self) -> None:
        """Drain accepted events while retaining subscriptions for resumed execution."""
        if self._owns_dispatcher:
            self.dispatcher.pause()

    def close(self) -> None:
        with self._lock:
            self._closing = True
        if not self.tracker.wait_idle(CLEANUP_SECONDS):
            self.failed.set()
            logger.warning("Agent event delivery exceeded its cleanup bound")
        with self._lock:
            self._listeners.clear()
        if self._owns_dispatcher:
            self.dispatcher.close()
