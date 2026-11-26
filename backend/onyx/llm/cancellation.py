"""Cancellation signals and execution scopes for model generation."""

import asyncio
import threading
from collections.abc import AsyncGenerator, Callable, Generator, Iterator
from concurrent.futures import Future
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar, copy_context
from functools import wraps
from typing import Literal, ParamSpec, TypeVar

from onyx.utils.logger import setup_logger

logger = setup_logger()


class AgentCancelled(BaseException):
    """Cancellation control flow bypasses ordinary model/tool error recovery."""


# Why work was cancelled: a caller asked for it, the work reached its deadline,
# or the user stopped it.
CancelReason = Literal["requested", "deadline", "user"]


class CancellationSignal:
    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: set[Callable[[], None]] = set()
        self._reason: CancelReason | None = None

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def reason(self) -> CancelReason | None:
        """The reason of the first cancel() call; None while not cancelled."""
        return self._reason

    def check(self) -> None:
        if self.cancelled:
            raise AgentCancelled()

    def cancel(self, reason: CancelReason = "requested") -> None:
        with self._lock:
            if self.cancelled:
                return
            self._reason = reason
            self._cancelled.set()
            callbacks = tuple(self._callbacks)
            self._callbacks.clear()
        for callback in callbacks:
            callback()

    @contextmanager
    def on_cancel(self, callback: Callable[[], None]) -> Iterator[None]:
        def notify() -> None:
            try:
                callback()
            except AgentCancelled:
                pass
            except Exception:
                logger.exception("Agent cancellation callback failed")

        with self._lock:
            cancelled = self.cancelled
            if not cancelled:
                self._callbacks.add(notify)
        try:
            if cancelled:
                notify()
            yield
        finally:
            with self._lock:
                self._callbacks.discard(notify)


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


def wait_for_future[T](
    future: Future[T], timeout_seconds: float, signal: CancellationSignal | None
) -> T:
    """The result of `future`, waited for at most `timeout_seconds` and not
    past a cancel of `signal`: then it raises AgentCancelled, or TimeoutError
    after the timeout. The work goes on without the caller."""
    done = threading.Event()
    future.add_done_callback(lambda _: done.set())
    with nullcontext() if signal is None else signal.on_cancel(done.set):
        done.wait(timeout_seconds)
    if not future.done():
        if signal is not None:
            signal.check()
        raise TimeoutError(f"the work did not end in {timeout_seconds:g} seconds")
    return future.result()


_P = ParamSpec("_P")
_T = TypeVar("_T")


def isolated_context(
    generate: Callable[_P, Generator[_T, None, None]],
) -> Callable[_P, Generator[_T, None, None]]:
    """Run a generator in its own context copy, across next and close.

    A generator shares its caller's context, so a span opened inside it would
    stay current for the caller between yields and after an early close.
    """

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


def isolated_async_context(
    generate: Callable[_P, AsyncGenerator[_T, None]],
) -> Callable[_P, AsyncGenerator[_T, None]]:
    """Async counterpart of ``isolated_context``.

    ``Context.run`` cannot drive an async generator, so each step and the close
    run as a task bound to one context copy. A span opened inside the generator
    then starts and ends in that copy, even when callers step it from different
    tasks, as Starlette's ``StreamingResponse`` does.
    """

    @wraps(generate)
    def start(*args: _P.args, **kwargs: _P.kwargs) -> AsyncGenerator[_T, None]:
        execution = copy_context()
        source = execution.run(generate, *args, **kwargs)

        async def advance() -> tuple[_T] | None:
            try:
                return (await source.__anext__(),)
            except StopAsyncIteration:
                return None

        async def close() -> None:
            await source.aclose()

        async def iterate() -> AsyncGenerator[_T, None]:
            try:
                while (
                    step := await asyncio.create_task(advance(), context=execution)
                ) is not None:
                    yield step[0]
            finally:
                # Shielded so a cancelled caller still closes the source in its
                # own context.
                await asyncio.shield(asyncio.create_task(close(), context=execution))

        return iterate()

    return start
