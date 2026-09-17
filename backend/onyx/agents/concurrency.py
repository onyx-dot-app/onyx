"""Thread ownership and finite event delivery for an execution tree."""

import os
import threading
from collections.abc import Callable
from concurrent.futures import Future
from contextvars import copy_context
from queue import Queue

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

    @property
    def idle(self) -> bool:
        with self._lock:
            return self._count == 0

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


class EventDelivery:
    """Deliver ordered, isolated events; listeners must finish their own I/O within a timeout."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._listeners: list[Callable[[AgentEvent], None]] = []
        self._queue: Queue[tuple[AgentEvent, int]] = Queue(EVENT_QUEUE_CAPACITY)
        self._bytes = 0
        self._closing = False
        self._dispatch_thread_id: int | None = None
        self.failed = threading.Event()
        self.tracker = WorkTracker()
        self._context = copy_context()
        self._scheduled = False

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
        with self._lock:
            if self._closing or self.failed.is_set() or not self._listeners:
                return
            size = len(to_json(event.model_dump(mode="python"), bytes_mode="base64"))
            if self._queue.full() or self._bytes + size > AGENT_EVENT_BUFFER_MAX_BYTES:
                self.failed.set()
                logger.error("Agent observer backlog exceeded its bound")
                return
            self._bytes += size
            self._queue.put_nowait((event.model_copy(deep=True), size))
            self._condition.notify()
            if self._scheduled:
                return
            self._scheduled = True
            self.tracker.started()
            try:
                context = self._context.copy()
                start_thread_with_context(
                    self._deliver, name="agent-events", daemon=True, context=context
                )
            except Exception:
                self._scheduled = False
                self.tracker.finished()
                self.failed.set()
                self._discard_pending()
                logger.exception("Agent observer delivery could not start")
                return

    @property
    def is_dispatch_thread(self) -> bool:
        with self._lock:
            return self._dispatch_thread_id == threading.get_ident()

    def _send(self, event: AgentEvent) -> None:
        with self._lock:
            listeners = tuple(self._listeners)
            self._dispatch_thread_id = threading.get_ident()
        try:
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
        finally:
            with self._lock:
                self._dispatch_thread_id = None

    def _deliver(self) -> None:
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(
                        lambda: self._closing or not self._queue.empty()
                    )
                    if self._queue.empty():
                        self._scheduled = False
                        return
                    event, size = self._queue.get_nowait()
                try:
                    self._send(event)
                finally:
                    with self._lock:
                        self._bytes -= size
        finally:
            self.tracker.finished()

    def _discard_pending(self) -> None:
        while not self._queue.empty():
            _, size = self._queue.get_nowait()
            self._bytes -= size

    def close(self) -> None:
        with self._lock:
            self._closing = True
            self._condition.notify_all()
        if not self.tracker.wait_idle(CLEANUP_SECONDS):
            self.failed.set()
            logger.warning("Agent event delivery exceeded its cleanup bound")
        with self._lock:
            self._discard_pending()
            self._listeners.clear()
