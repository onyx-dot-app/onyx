"""Cancellation signals and execution scopes for model generation."""

import threading
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from functools import wraps
from typing import ParamSpec, TypeVar

from onyx.utils.logger import setup_logger

logger = setup_logger()


class AgentCancelled(BaseException):
    """Cancellation control flow bypasses ordinary model/tool error recovery."""


class CancellationSignal:
    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: set[Callable[[], None]] = set()

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
    def on_cancel(self, callback: Callable[[], None]) -> Iterator[None]:
        def notify() -> None:
            return callback()

        with self._lock:
            cancelled = self.cancelled
            if not cancelled:
                self._callbacks.add(notify)
        try:
            if cancelled:
                callback()
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
