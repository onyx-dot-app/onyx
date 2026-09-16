"""Bounded work and delivery for one execution tree."""

import asyncio
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from contextvars import copy_context
from queue import Empty, Queue

from pydantic_core import to_json

from onyx.agents.events import AgentEvent
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import ContextThreadPoolExecutor

logger = setup_logger()
OPERATION_TIMEOUT_SECONDS = 1800.0
CLEANUP_SECONDS = 2.0
AGENT_WORKER_THREADS = int(os.environ.get("AGENT_WORKER_THREADS", "32"))
AGENT_WORKER_PENDING = int(os.environ.get("AGENT_WORKER_PENDING", "256"))
AGENT_OBSERVER_THREADS = int(os.environ.get("AGENT_OBSERVER_THREADS", "8"))
AGENT_OBSERVER_PENDING = int(os.environ.get("AGENT_OBSERVER_PENDING", "256"))
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

    async def wait_idle(self, timeout: float) -> bool:
        if self.idle:
            return True
        loop = asyncio.get_running_loop()
        finished: asyncio.Future[None] = loop.create_future()

        def resolve() -> None:
            if not finished.done():
                finished.set_result(None)

        def notify() -> None:
            if not loop.is_closed():
                loop.call_soon_threadsafe(resolve)

        unsubscribe = self.on_idle(notify)
        try:
            done, _ = await asyncio.wait({finished}, timeout=timeout)
            return bool(done)
        finally:
            unsubscribe()
            finished.cancel()


class _SharedExecutor:
    """Bound running and queued jobs before submitting to the shared worker pool."""

    def __init__(self, workers: int, pending: int, name: str) -> None:
        self._slots = threading.BoundedSemaphore(pending)
        self._executor = ContextThreadPoolExecutor(workers, name)

    def submit[T](self, operation: Callable[[], T]) -> Future[T]:
        if not self._slots.acquire(blocking=False):
            raise RuntimeError("Agent worker backlog exceeded its bound")
        try:
            future = self._executor.submit(operation)
        except BaseException:
            self._slots.release()
            raise
        future.add_done_callback(lambda _future: self._slots.release())
        return future


_OPERATION_WORKERS = _SharedExecutor(
    AGENT_WORKER_THREADS, AGENT_WORKER_PENDING, "agent-operation"
)
_OBSERVER_WORKERS = _SharedExecutor(
    AGENT_OBSERVER_THREADS, AGENT_OBSERVER_PENDING, "agent-events"
)


class _UpdateAdmission:
    def __init__(self, capacity: int) -> None:
        self._available = capacity
        self._condition = threading.Condition()

    def acquire(self, signal: CancellationSignal, timeout: float) -> None:
        def wake() -> None:
            with self._condition:
                self._condition.notify_all()

        with signal.on_cancel(wake), self._condition:
            ready = self._condition.wait_for(
                lambda: self._available > 0 or signal.cancelled, timeout=timeout
            )
            signal.check()
            if not ready:
                raise TimeoutError("Agent update admission exceeded its bound")
            self._available -= 1

    def release(self) -> None:
        with self._condition:
            self._available += 1
            self._condition.notify()


async def _wait_operation[T](
    future: asyncio.Future[T], signal: CancellationSignal, timeout: float
) -> T:
    loop = asyncio.get_running_loop()
    cancelled: asyncio.Future[None] = loop.create_future()

    def resolve_cancel() -> None:
        if not cancelled.done():
            cancelled.set_result(None)

    def notify_cancel() -> None:
        loop.call_soon_threadsafe(resolve_cancel)

    try:
        with signal.on_cancel(notify_cancel):
            signal.check()
            done, _ = await asyncio.wait(
                {future, cancelled},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            signal.check()
            if not done:
                raise TimeoutError("Agent operation exceeded its bound")
            return future.result()
    finally:
        cancelled.cancel()


def _report_abandoned_worker[T](completion: asyncio.Future[T]) -> None:
    if completion.cancelled():
        return
    error = completion.exception()
    if error is not None and not isinstance(error, AgentCancelled):
        logger.error(
            "Agent worker failed after its caller stopped waiting",
            exc_info=(type(error), error, error.__traceback__),
        )


class ExecutionServices:
    """Share worker admission and concurrency limits across a root run and its children."""

    def __init__(self, capacity: int) -> None:
        self.loop = asyncio.get_running_loop()
        self.parallelism = capacity
        self.capacity = asyncio.Semaphore(capacity)
        self.update_capacity = _UpdateAdmission(capacity)
        self.tracker = WorkTracker()
        self._closed = False

    async def blocking[T](
        self,
        operation: Callable[[], T],
        signal: CancellationSignal,
        *,
        tracker: WorkTracker | None = None,
    ) -> T:
        if self._closed:
            raise RuntimeError("Agent execution services are closed")
        deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
        admission = asyncio.create_task(self.capacity.acquire())
        try:
            await _wait_operation(admission, signal, OPERATION_TIMEOUT_SECONDS)
        except BaseException:
            admission.cancel()
            if admission.done() and not admission.cancelled() and admission.result():
                self.capacity.release()
            raise
        self.tracker.started()
        if tracker is not None:
            tracker.started()

        def finished(_future: Future[T]) -> None:
            self.tracker.finished()
            if tracker is not None:
                tracker.finished()
            if not self.loop.is_closed():
                self.loop.call_soon_threadsafe(self.capacity.release)

        def track_provider(completion: Future[None]) -> None:
            self.tracker.started()
            if tracker is not None:
                tracker.started()

            def provider_finished(_future: Future[None]) -> None:
                self.tracker.finished()
                if tracker is not None:
                    tracker.finished()

            completion.add_done_callback(provider_finished)

        def execute() -> T:
            signal.check()
            with signal.on_operation(track_provider):
                return operation()

        try:
            signal.check()
            future = _OPERATION_WORKERS.submit(execute)
        except BaseException:
            self.capacity.release()
            self.tracker.finished()
            if tracker is not None:
                tracker.finished()
            raise
        future.add_done_callback(finished)
        completion = asyncio.wrap_future(future)
        try:
            return await _wait_operation(
                completion, signal, max(0, deadline - time.monotonic())
            )
        except BaseException as error:
            if (
                completion.done()
                and not completion.cancelled()
                and completion.exception() is error
            ):
                raise
            completion.add_done_callback(_report_abandoned_worker)
            raise

    def close(self) -> None:
        self._closed = True


class ExecutionWork:
    """Track one run's unfinished work and accept updates on its owning event loop."""

    def __init__(self, services: ExecutionServices) -> None:
        self.services = services
        self.tracker = WorkTracker()
        self.loop = services.loop
        self.loop_thread = threading.get_ident()

    async def blocking[T](
        self, operation: Callable[[], T], signal: CancellationSignal
    ) -> T:
        return await self.services.blocking(operation, signal, tracker=self.tracker)

    def track_task[T](self, task: asyncio.Task[T]) -> None:
        self.tracker.started()
        task.add_done_callback(lambda _task: self.tracker.finished())

    def accept[T](self, operation: Callable[[], T], signal: CancellationSignal) -> T:
        if threading.get_ident() == self.loop_thread:
            return operation()
        deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
        self.services.update_capacity.acquire(signal, OPERATION_TIMEOUT_SECONDS)
        self.tracker.started()
        accepted: Future[T] = Future()
        completed = threading.Event()
        accepted.add_done_callback(lambda _future: completed.set())

        def apply() -> None:
            try:
                if not accepted.set_running_or_notify_cancel():
                    return
                try:
                    accepted.set_result(operation())
                except BaseException as error:
                    accepted.set_exception(error)
            finally:
                self.services.update_capacity.release()
                self.tracker.finished()

        try:
            signal.check()
            self.loop.call_soon_threadsafe(apply)
        except BaseException:
            self.services.update_capacity.release()
            self.tracker.finished()
            raise
        try:
            with signal.on_cancel(completed.set):
                if not completed.wait(timeout=max(0, deadline - time.monotonic())):
                    raise TimeoutError("Agent update acceptance exceeded its bound")
                signal.check()
                return accepted.result()
        except BaseException:
            accepted.cancel()
            raise


class EventDelivery:
    """Deliver ordered, isolated events; listeners must finish their own I/O within a timeout."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
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
            if self._scheduled:
                return
            self._scheduled = True
            self.tracker.started()
            try:
                context = self._context.copy()
                drain = _OBSERVER_WORKERS.submit(lambda: context.run(self._deliver))
            except Exception:
                self._scheduled = False
                self.tracker.finished()
                self.failed.set()
                self._discard_pending()
                logger.exception("Agent observer delivery could not start")
                return
            drain.add_done_callback(lambda _future: self.tracker.finished())

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
                except (AgentCancelled, asyncio.CancelledError):
                    self.failed.set()
                    logger.debug("Agent observer cancelled")
                except Exception:
                    self.failed.set()
                    logger.exception("Agent observer failed")
        finally:
            with self._lock:
                self._dispatch_thread_id = None

    def _deliver(self) -> None:
        while True:
            with self._lock:
                try:
                    event, size = self._queue.get_nowait()
                except Empty:
                    self._scheduled = False
                    return
            try:
                self._send(event)
            finally:
                with self._lock:
                    self._bytes -= size

    def _discard_pending(self) -> None:
        while not self._queue.empty():
            _, size = self._queue.get_nowait()
            self._bytes -= size

    async def close(self) -> None:
        with self._lock:
            self._closing = True
        if not await self.tracker.wait_idle(CLEANUP_SECONDS):
            self.failed.set()
            logger.warning("Agent event delivery exceeded its cleanup bound")
        with self._lock:
            self._discard_pending()
            self._listeners.clear()
