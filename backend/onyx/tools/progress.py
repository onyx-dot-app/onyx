"""Route synchronous domain progress through the owning Pydantic AI run."""

import asyncio
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from pydantic_ai import CustomEvent, RunContext

from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import PacketObj


# Pydantic AI requires dataclasses for registered custom events.
@dataclass(kw_only=True)
class OnyxToolProgress(CustomEvent):
    placement: Placement
    obj: PacketObj


_progress_handler: ContextVar[Callable[[OnyxToolProgress], None] | None] = ContextVar(
    "onyx_tool_progress_handler", default=None
)

_tool_run_closed: ContextVar[tuple[threading.Event, ...]] = ContextVar(
    "onyx_tool_run_closed", default=()
)


def check_tool_run_active() -> None:
    """Reject late worker results after the owning async tool was cancelled."""
    if any(closed.is_set() for closed in _tool_run_closed.get()):
        raise asyncio.CancelledError("The owning agent run has ended.")


def publish_tool_progress(placement: Placement, obj: PacketObj) -> bool:
    handler = _progress_handler.get()
    if handler is None:
        return False
    handler(OnyxToolProgress(placement=placement, obj=obj))
    return True


@contextmanager
def route_tool_progress(context: RunContext[None]) -> Iterator[None]:
    """Bind progress for a tool batch run with asyncio.to_thread.

    The worker waits until the agent accepts each event. This preserves ordering
    and prevents unbounded progress buffering when consumers slow down.
    """
    loop = asyncio.get_running_loop()
    closed = threading.Event()
    closed_scopes = (*_tool_run_closed.get(), closed)

    def is_closed() -> bool:
        return any(scope.is_set() for scope in closed_scopes)

    def publish(event: OnyxToolProgress) -> None:
        if is_closed() or loop.is_closed():
            raise asyncio.CancelledError("The owning agent run has ended.")
        future = asyncio.run_coroutine_threadsafe(context.emit(event), loop)
        while not is_closed():
            try:
                future.result(timeout=0.1)
                return
            except FutureTimeoutError:
                continue
        future.cancel()
        raise asyncio.CancelledError("The owning agent run has ended.")

    token = _progress_handler.set(publish)
    closed_token = _tool_run_closed.set(closed_scopes)
    try:
        yield
    finally:
        closed.set()
        _progress_handler.reset(token)
        _tool_run_closed.reset(closed_token)
