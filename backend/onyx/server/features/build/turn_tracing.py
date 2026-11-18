"""Share a Craft turn's trace identity across gateway replicas."""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from uuid import UUID, uuid4

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS
from onyx.server.features.build.sandbox.serve_transport import PromptSlot
from onyx.server.features.build.timeouts import (
    SCHEDULED_RUN_HARD_CAP_SECONDS,
    TURN_RECLAIM_SLACK_SECONDS,
)
from onyx.tracing.framework.create import trace
from onyx.tracing.setup import has_external_exporters
from onyx.utils.logger import setup_logger

logger = setup_logger()
TRACE_CACHE_TIMEOUT_SECONDS = 0.25


def _trace_key(session_id: UUID) -> str:
    return f"craft:turn_trace:{session_id}"


@contextmanager
def traced_prompt_slot(
    session_id: UUID, prompt_slot: AbstractContextManager[PromptSlot]
) -> Iterator[PromptSlot]:
    """The turn owns tracing; the sandbox owns prompt serialization."""
    tracing_enabled = has_external_exporters()
    with prompt_slot as slot:
        if not slot.has_lease or not tracing_enabled:
            yield slot
            return
        with craft_turn_trace(session_id):
            slot.extend()
            yield PromptSlot(acquired=False) if slot.lost else slot


@contextmanager
def craft_turn_trace(session_id: UUID) -> Iterator[None]:
    """Publish only while holding the session's prompt slot."""
    trace_id = uuid4().hex
    cache = get_cache_backend(operation_timeout_s=TRACE_CACHE_TIMEOUT_SECONDS)
    key = _trace_key(session_id)
    root = trace(
        "craft_turn",
        metadata={
            "craft_session_id": str(session_id),
            "distributed_trace_id": trace_id,
            "distributed_root_span_id": trace_id[:16],
        },
    )
    try:
        cache.set(
            key,
            trace_id,
            ex=SCHEDULED_RUN_HARD_CAP_SECONDS + TURN_RECLAIM_SLACK_SECONDS,
        )
    except CACHE_TRANSIENT_ERRORS:
        logger.warning("Could not publish Craft turn trace", exc_info=True)
    # Publish before processor setup, which can outlast the prompt-slot lease.
    # A subagent SSE generator can resume in another thread. Do not bind context.
    root.start()
    try:
        yield
    finally:
        try:
            cache.delete_if_value(key, trace_id.encode())
        except CACHE_TRANSIENT_ERRORS:
            logger.warning("Could not clear Craft turn trace", exc_info=True)
        finally:
            root.finish()


def get_craft_turn_trace_id(session_id: UUID) -> str | None:
    if not has_external_exporters():
        return None
    try:
        value = get_cache_backend(operation_timeout_s=TRACE_CACHE_TIMEOUT_SECONDS).get(
            _trace_key(session_id)
        )
    except CACHE_TRANSIENT_ERRORS:
        logger.warning("Could not read Craft turn trace", exc_info=True)
        return None
    return value.decode() if value is not None else None
