"""Cancellation signals, execution scopes, and interruptible provider streaming."""

import asyncio
import os
import threading
from collections.abc import Callable, Coroutine, Generator, Iterator
from concurrent.futures import CancelledError, Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import contextmanager, suppress
from contextvars import ContextVar, copy_context
from functools import wraps
from typing import TYPE_CHECKING, ParamSpec, TypeVar

from pydantic import JsonValue

from onyx.llm.exceptions import LLMTimeoutError
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import get_background_event_loop

logger = setup_logger()

_PROVIDER_CLEANUP_TIMEOUT_SECONDS = 5.0


class AgentCancelled(BaseException):
    """Control flow, not a model/tool failure. Like asyncio.CancelledError."""


class CancellationSignal:
    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: set[Callable[[], object]] = set()
        self._operation_listeners: set[Callable[[Future[None]], None]] = set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def check(self) -> None:
        if self.cancelled:
            raise AgentCancelled()

    def cancel(self) -> None:
        with self._lock:
            if self.cancelled:
                return
            self._cancelled.set()
            callbacks = tuple(self._callbacks)
            self._callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                logger.exception("Agent cancellation callback failed")

    @contextmanager
    def on_cancel(self, callback: Callable[[], object]) -> Iterator[None]:
        with self._lock:
            cancelled = self.cancelled
            if not cancelled:
                self._callbacks.add(callback)
        try:
            if cancelled:
                callback()
            yield
        finally:
            with self._lock:
                self._callbacks.discard(callback)

    def track_operation(self, completion: Future[None]) -> None:
        with self._lock:
            listeners = tuple(self._operation_listeners)
        for listener in listeners:
            listener(completion)

    @contextmanager
    def on_operation(self, listener: Callable[[Future[None]], None]) -> Iterator[None]:
        """Observe provider work until actual cleanup finishes, including after timeout."""
        with self._lock:
            self._operation_listeners.add(listener)
        try:
            yield
        finally:
            with self._lock:
                self._operation_listeners.discard(listener)


_current_signal: ContextVar[CancellationSignal | None] = ContextVar(
    "agent_cancellation", default=None
)


def current_cancellation() -> CancellationSignal | None:
    return _current_signal.get()


def check_cancelled() -> None:
    signal = current_cancellation()
    if signal is not None:
        signal.check()


@contextmanager
def cancellation_scope(signal: CancellationSignal) -> Iterator[None]:
    token = _current_signal.set(signal)
    try:
        yield
    finally:
        _current_signal.reset(token)


if TYPE_CHECKING:
    from litellm import CustomStreamWrapper
    from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
    from litellm.types.utils import ModelResponseStream


class _NetworkLoop:
    def __init__(self) -> None:
        self.pid = os.getpid()
        self.loop = get_background_event_loop()
        self._tasks: set[asyncio.Task[None]] = set()

    def call[T](
        self,
        coroutine: Coroutine[None, None, T],
        signal: CancellationSignal | None,
        *,
        timeout: float,
        ownership_signal: CancellationSignal | None = None,
    ) -> T:
        result: Future[T] = Future()
        completion: Future[None] = Future()
        result.set_running_or_notify_cancel()
        completion.set_running_or_notify_cancel()
        cancelled = False
        entered = False
        task: asyncio.Task[None] | None = None

        async def run() -> None:
            nonlocal entered
            entered = True
            try:
                result.set_result(await coroutine)
            except asyncio.CancelledError:
                result.set_exception(CancelledError())
            except BaseException as error:
                result.set_exception(error)

        def cancel_task() -> None:
            nonlocal cancelled
            cancelled = True
            if task is not None:
                task.cancel()

        def cancel() -> None:
            self.loop.call_soon_threadsafe(cancel_task)

        def finish(done: asyncio.Task[None]) -> None:
            self._tasks.discard(done)
            if not entered:
                coroutine.close()
                result.set_exception(CancelledError())
            completion.set_result(None)

        def start() -> None:
            nonlocal task
            task = self.loop.create_task(run())
            self._tasks.add(task)
            task.add_done_callback(finish)
            if cancelled:
                task.cancel()

        owner = ownership_signal or signal
        try:
            if signal is not None:
                signal.check()
            if owner is not None:
                owner.track_operation(completion)
            self.loop.call_soon_threadsafe(start)
        except BaseException:
            coroutine.close()
            completion.set_result(None)
            raise
        try:
            if signal is None:
                return result.result(timeout=timeout)
            with signal.on_cancel(cancel):
                return result.result(timeout=timeout)
        except FutureTimeoutError as error:
            if result.done():
                raise
            cancel()
            if signal is not None:
                signal.check()
            raise LLMTimeoutError(
                "Provider I/O did not complete within its operation timeout"
            ) from error
        except CancelledError:
            if signal is not None:
                signal.check()
            raise


_network: _NetworkLoop | None = None

_network_lock = threading.Lock()


def _network_loop() -> _NetworkLoop:
    global _network
    with _network_lock:
        if _network is None or _network.pid != os.getpid():
            _network = _NetworkLoop()
        return _network


@contextmanager
def cancellation_deadline(
    seconds: float, callback: Callable[[], None]
) -> Iterator[None]:
    loop = get_background_event_loop()
    handle: asyncio.TimerHandle | None = None
    expires_at = loop.time() + seconds

    def start() -> None:
        nonlocal handle
        handle = loop.call_at(expires_at, callback)

    def stop() -> None:
        if handle is not None:
            handle.cancel()

    loop.call_soon_threadsafe(start)
    try:
        yield
    finally:
        loop.call_soon_threadsafe(stop)


class CancellableStream(Iterator["ModelResponseStream"]):
    def __init__(
        self,
        kwargs: dict[str, JsonValue],
        signal: CancellationSignal,
        *,
        isolated_client: bool,
        timeout: float,
    ) -> None:
        self._network = _network_loop()
        self._signal = signal
        self._timeout = timeout
        self._response: CustomStreamWrapper | None = None
        self._client: AsyncHTTPHandler | None = None
        self._closed = False
        try:
            signal.check()
            self._network.call(
                self._open(kwargs, isolated_client),
                signal,
                timeout=timeout + _PROVIDER_CLEANUP_TIMEOUT_SECONDS,
            )
        except BaseException:
            with suppress(Exception):
                self.close()
            raise

    async def _open(self, kwargs: dict[str, JsonValue], isolated: bool) -> None:
        from litellm import CustomStreamWrapper
        from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

        from onyx.llm.litellm_singleton import litellm

        if isolated:
            self._client = AsyncHTTPHandler(timeout=self._timeout)
        try:
            response = await litellm.acompletion(**(kwargs | {"client": self._client}))
            if not isinstance(response, CustomStreamWrapper):
                raise TypeError("Expected a streaming model response")
            self._response = response
            self._signal.check()
        except BaseException:
            with suppress(Exception):
                await self._close()
            raise

    async def _next(self) -> "ModelResponseStream":
        self._signal.check()
        if self._response is None:
            raise StopAsyncIteration
        try:
            return await anext(self._response)
        except BaseException:
            with suppress(Exception):
                await self._close()
            raise

    async def _close(self) -> None:
        # Detach resources before awaiting so cancellation and iterator cleanup
        # cannot both close the same provider stream.
        response, self._response = self._response, None
        client, self._client = self._client, None
        try:
            try:
                if response is not None:
                    await asyncio.wait_for(
                        response.aclose(), _PROVIDER_CLEANUP_TIMEOUT_SECONDS
                    )
            finally:
                if client is not None:
                    await asyncio.wait_for(
                        client.close(), _PROVIDER_CLEANUP_TIMEOUT_SECONDS
                    )
        except Exception:
            logger.exception("Provider stream cleanup failed")
            raise

    def __next__(self) -> "ModelResponseStream":
        if self._closed:
            raise StopIteration
        try:
            self._signal.check()
            return self._network.call(
                self._next(),
                self._signal,
                timeout=self._timeout + _PROVIDER_CLEANUP_TIMEOUT_SECONDS,
            )
        except StopAsyncIteration:
            self.close()
            raise StopIteration from None
        except BaseException:
            with suppress(Exception):
                self.close()
            raise

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self._network.call(
                    self._close(),
                    None,
                    timeout=2 * _PROVIDER_CLEANUP_TIMEOUT_SECONDS,
                    ownership_signal=self._signal,
                )
            except LLMTimeoutError:
                logger.exception("Provider stream cleanup exceeded its wait bound")
                raise


_P = ParamSpec("_P")

_T = TypeVar("_T")


def isolated_context(
    generate: Callable[_P, Generator[_T, None, None]],
) -> Callable[_P, Generator[_T, None, None]]:
    """Keep generator context variables isolated across next and close operations."""

    @wraps(generate)
    def start(*args: _P.args, **kwargs: _P.kwargs) -> Generator[_T, None, None]:
        execution = copy_context()
        source = execution.run(generate, *args, **kwargs)

        def iterate() -> Generator[_T, None, None]:
            try:
                while True:
                    try:
                        value = execution.run(source.__next__)
                    except StopIteration:
                        return
                    yield value
            finally:
                execution.run(source.close)

        return iterate()

    return start
