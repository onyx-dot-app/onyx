"""Turn-streaming pipeline.

Drives a single agent turn end-to-end:

    user prompt
        │
        ▼
    turn lock (per build_session) ──────────────────────────────┐
        │                                                       │
        ▼                                                       │
    ensure opencode session id (preflight; writes through)      │
        │                                                       │
        ▼                                                       │
    yield_sandbox_events  ←  (drives sandbox_manager.send_message)
        │                                                       │
        ▼                                                       │
    merge_events_with_announces  (parent turns only)            │
        │                                                       │
        ▼                                                       │
    for event in stream:                                        │
        persist_sandbox_event(...)   ──► DB writes              │
        dispatch_to_sse(...)          ──► yields SSE frames     │
        │                                                       │
        ▼                                                       │
    finalize_persist (flush trailing chunks)                    │
        │                                                       │
    ────┴───────────────────────────────────────────────────────┘
    fence cleared, slot released

Two callable entry points share the same persistence + serialization
helpers:

- :func:`stream_cli_agent_turn` — parent-turn SSE stream; includes
  approval-announce merging, the interrupt fence, and packet logging.
- :func:`stream_subagent_turn` — follow-up against an existing subagent
  child session; tags every persisted event + SSE frame with routing
  ``_meta`` so the frontend re-routes them to the subagent.

The headless scheduled-tasks executor calls :func:`yield_sandbox_events`,
:func:`persist_sandbox_event`, and :func:`finalize_persist` directly
(through ``SessionManager`` shims) so its transcripts are byte-identical
to interactive runs.
"""

from __future__ import annotations

import contextlib
import json
import queue as queue_lib
import threading
import time
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterable
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS
from onyx.configs.constants import MessageType
from onyx.db.enums import SandboxStatus
from onyx.db.models import BuildMessage
from onyx.db.models import BuildSession
from onyx.sandbox_proxy import approval_cache
from onyx.server.features.build.api.packet_logger import get_packet_logger
from onyx.server.features.build.api.packet_logger import log_separator
from onyx.server.features.build.api.packet_logger import PacketLogger
from onyx.server.features.build.api.packets import ApprovalRequestedPacket
from onyx.server.features.build.api.packets import BuildPacket
from onyx.server.features.build.api.packets import ErrorPacket
from onyx.server.features.build.db.build_session import create_message
from onyx.server.features.build.db.build_session import get_build_session
from onyx.server.features.build.db.build_session import update_session_activity
from onyx.server.features.build.db.build_session import upsert_agent_plan
from onyx.server.features.build.db.sandbox import get_sandbox_by_session_id
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.db.sandbox import update_sandbox_heartbeat
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.event_schema import AgentMessageChunk
from onyx.server.features.build.sandbox.event_schema import AgentPlanUpdate
from onyx.server.features.build.sandbox.event_schema import AgentThoughtChunk
from onyx.server.features.build.sandbox.event_schema import CurrentModeUpdate
from onyx.server.features.build.sandbox.event_schema import Error as SandboxError
from onyx.server.features.build.sandbox.event_schema import PromptResponse
from onyx.server.features.build.sandbox.event_schema import ToolCallProgress
from onyx.server.features.build.sandbox.event_schema import ToolCallStart
from onyx.server.features.build.sandbox.opencode.serve_client import _merge_field_meta
from onyx.server.features.build.sandbox.sse import SSEKeepalive
from onyx.server.features.build.session.interrupt_signal import clear_interrupt
from onyx.server.features.build.session.interrupt_signal import is_interrupt_requested
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


# =============================================================================
# Per-turn state (accumulator for streaming chunks)
# =============================================================================


class BuildStreamingState:
    """Container for chunks and bookkeeping over a single turn.

    The agent stream emits text in chunks (``agent_message_chunk`` /
    ``agent_thought_chunk``) interleaved with tool calls. We buffer chunks
    until we see a non-chunk event of the same family, then flush them as
    a single synthesized ``agent_message`` / ``agent_thought`` row. The
    plan also gets upserted (only the latest plan per turn is kept).

    NOTE: This class is part of the public surface (``from
    ...session.manager import BuildStreamingState``). Tests construct it
    directly and the scheduled-tasks executor passes one to
    ``persist_sandbox_event`` / ``finalize_persist``. Keep the method
    names stable.
    """

    def __init__(self, turn_index: int) -> None:
        self.turn_index = turn_index
        self.message_chunks: list[str] = []
        self.thought_chunks: list[str] = []
        # Plan rows are upserted in place — remember the id once minted.
        self.plan_message_id: UUID | None = None
        # Used to decide when to flush.
        self._last_chunk_type: str | None = None

    def add_message_chunk(self, text: str) -> None:
        self.message_chunks.append(text)
        self._last_chunk_type = "message"

    def add_thought_chunk(self, text: str) -> None:
        self.thought_chunks.append(text)
        self._last_chunk_type = "thought"

    def finalize_message_chunks(
        self, routing_meta: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Synthesize one ``agent_message`` packet from the accumulated
        text and clear the buffer. ``None`` if there was nothing buffered."""
        if not self.message_chunks:
            return None
        packet: dict[str, Any] = {
            "type": "agent_message",
            "content": {"type": "text", "text": "".join(self.message_chunks)},
            "sessionUpdate": "agent_message",
        }
        if routing_meta:
            packet["_meta"] = dict(routing_meta)
        self.message_chunks.clear()
        return packet

    def finalize_thought_chunks(
        self, routing_meta: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        if not self.thought_chunks:
            return None
        packet: dict[str, Any] = {
            "type": "agent_thought",
            "content": {"type": "text", "text": "".join(self.thought_chunks)},
            "sessionUpdate": "agent_thought",
        }
        if routing_meta:
            packet["_meta"] = dict(routing_meta)
        self.thought_chunks.clear()
        return packet

    def should_finalize_chunks(self, new_packet_type: str) -> bool:
        """True when the incoming event would break the current chunk run
        (e.g. a tool call arriving mid-``agent_message_chunk`` stream)."""
        if self._last_chunk_type == "message":
            return new_packet_type != "agent_message_chunk"
        if self._last_chunk_type == "thought":
            return new_packet_type != "agent_thought_chunk"
        return False

    def clear_last_chunk_type(self) -> None:
        self._last_chunk_type = None


# =============================================================================
# Event type registry + serializers
# =============================================================================


@dataclass(frozen=True)
class _EventDescriptor:
    """Mapping from a sandbox event class to its SSE type name."""

    cls: type
    sse_type: str


_EVENT_DESCRIPTORS: tuple[_EventDescriptor, ...] = (
    _EventDescriptor(AgentMessageChunk, "agent_message_chunk"),
    _EventDescriptor(AgentThoughtChunk, "agent_thought_chunk"),
    _EventDescriptor(ToolCallStart, "tool_call_start"),
    _EventDescriptor(ToolCallProgress, "tool_call_progress"),
    _EventDescriptor(AgentPlanUpdate, "agent_plan_update"),
    _EventDescriptor(CurrentModeUpdate, "current_mode_update"),
    _EventDescriptor(PromptResponse, "prompt_response"),
    _EventDescriptor(SandboxError, "error"),
)


# Tag events the frontend should re-route under a subagent with these.
_ROUTABLE_EVENT_TYPES: tuple[type, ...] = (
    ToolCallStart,
    ToolCallProgress,
    AgentMessageChunk,
    AgentThoughtChunk,
)


def _sse_type_for(sandbox_event: Any) -> str:
    """SSE ``type`` string for a sandbox event. Returns ``"unknown"`` for
    types not in the registry."""
    for descriptor in _EVENT_DESCRIPTORS:
        if isinstance(sandbox_event, descriptor.cls):
            return descriptor.sse_type
    return "unknown"


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def serialize_sandbox_event(event: Any, event_type: str) -> str:
    """Serialize a sandbox event as an SSE ``message`` frame, preserving
    all fields and injecting ``type`` + ``timestamp``."""
    if hasattr(event, "model_dump"):
        data = event.model_dump(mode="json", by_alias=True, exclude_none=False)
    else:
        data = {"raw": str(event)}
    data["type"] = event_type
    data["timestamp"] = _utc_now_iso()
    return f"event: message\ndata: {json.dumps(data)}\n\n"


def format_packet_event(packet: BuildPacket) -> str:
    """Format a ``BuildPacket`` (e.g. ``ErrorPacket``,
    ``ApprovalRequestedPacket``) as an SSE ``message`` frame."""
    return f"event: message\ndata: {packet.model_dump_json(by_alias=True)}\n\n"


def _extract_text_from_content(content: Any) -> str:
    """Pull the user-visible text out of a chunk's ``content`` field."""
    if content is None:
        return ""
    if hasattr(content, "type") and content.type == "text":
        return getattr(content, "text", "") or ""
    if isinstance(content, list):
        texts: list[str] = []
        for block in content:
            if hasattr(block, "type") and block.type == "text":
                texts.append(getattr(block, "text", "") or "")
        return "".join(texts)
    return ""


# =============================================================================
# Persistence
# =============================================================================


def save_pending_chunks(
    db_session: DBSession,
    session_id: UUID,
    state: BuildStreamingState,
    routing_meta: dict[str, Any] | None = None,
) -> None:
    """Flush any buffered message/thought chunks to ``BuildMessage`` rows.

    Called whenever the incoming event would break the chunk run, and once
    at end-of-stream. ``routing_meta`` is merged into the persisted ACP
    ``_meta`` so subagent follow-ups reload under their subagent.
    """
    message_packet = state.finalize_message_chunks(routing_meta)
    if message_packet:
        create_message(
            session_id=session_id,
            message_type=MessageType.ASSISTANT,
            turn_index=state.turn_index,
            message_metadata=message_packet,
            db_session=db_session,
        )

    thought_packet = state.finalize_thought_chunks(routing_meta)
    if thought_packet:
        create_message(
            session_id=session_id,
            message_type=MessageType.ASSISTANT,
            turn_index=state.turn_index,
            message_metadata=thought_packet,
            db_session=db_session,
        )

    state.clear_last_chunk_type()


def _persist_tool_call_progress(
    db_session: DBSession,
    session_id: UUID,
    state: BuildStreamingState,
    sandbox_event: ToolCallProgress,
) -> None:
    """Tool calls persist on ``completed`` (or every update for TodoWrite,
    which streams its plan via progress packets). Completed Task tools
    also emit a synthetic ``agent_message`` containing the subagent's
    output so it appears inline in the transcript."""
    event_data = sandbox_event.model_dump(
        mode="json", by_alias=True, exclude_none=False
    )
    event_data["type"] = "tool_call_progress"
    event_data["timestamp"] = _utc_now_iso()

    tool_name = (event_data.get("title") or "").lower()
    is_todo_write = tool_name in ("todowrite", "todo_write")
    raw_input = event_data.get("rawInput") or {}
    is_task_tool = (
        tool_name == "task"
        or raw_input.get("subagent_type") is not None
        or raw_input.get("subagentType") is not None
    )

    if is_todo_write or sandbox_event.status == "completed":
        create_message(
            session_id=session_id,
            message_type=MessageType.ASSISTANT,
            turn_index=state.turn_index,
            message_metadata=event_data,
            db_session=db_session,
        )

    if is_task_tool and sandbox_event.status == "completed":
        raw_output = event_data.get("rawOutput") or {}
        task_output = raw_output.get("output")
        if isinstance(task_output, str):
            # The opencode runtime appends a ``<task_metadata>...`` block;
            # strip it so the displayed message is clean prose.
            metadata_idx = task_output.find("<task_metadata>")
            if metadata_idx >= 0:
                task_output = task_output[:metadata_idx].strip()
            if task_output:
                create_message(
                    session_id=session_id,
                    message_type=MessageType.ASSISTANT,
                    turn_index=state.turn_index,
                    message_metadata={
                        "type": "agent_message",
                        "content": {"type": "text", "text": task_output},
                        "source": "task_output",
                        "timestamp": _utc_now_iso(),
                    },
                    db_session=db_session,
                )


def _persist_agent_plan(
    db_session: DBSession,
    session_id: UUID,
    state: BuildStreamingState,
    sandbox_event: AgentPlanUpdate,
) -> None:
    """Plan rows are upserted: only the latest plan per turn is kept."""
    event_data = sandbox_event.model_dump(
        mode="json", by_alias=True, exclude_none=False
    )
    event_data["type"] = "agent_plan_update"
    event_data["timestamp"] = _utc_now_iso()
    plan_msg = upsert_agent_plan(
        session_id=session_id,
        turn_index=state.turn_index,
        plan_metadata=event_data,
        db_session=db_session,
        existing_plan_id=state.plan_message_id,
    )
    state.plan_message_id = plan_msg.id


def persist_sandbox_event(
    db_session: DBSession,
    session_id: UUID,
    state: BuildStreamingState,
    sandbox_event: Any,
    routing_meta: dict[str, Any] | None = None,
) -> None:
    """Apply DB-write side effects for a single sandbox event.

    Dispatch:
    - ``SSEKeepalive`` / ``CurrentModeUpdate`` / ``PromptResponse`` /
      ``SandboxError`` / unrecognized: not persisted (parity with the
      original interactive path).
    - ``AgentMessageChunk`` / ``AgentThoughtChunk``: accumulated into
      ``state``; flushed by :func:`save_pending_chunks` when a non-chunk
      event arrives or at end of stream.
    - ``ToolCallStart``: not persisted; only completed progress writes.
    - ``ToolCallProgress``: writes on ``completed`` (every update for
      TodoWrite). Completed Task tools also write a synthetic
      ``agent_message`` containing the subagent's output.
    - ``AgentPlanUpdate``: upserted; latest plan wins per turn.

    Intentionally synchronous, free of SSE / logging concerns, so the
    headless scheduled-tasks executor can drive the same persistence as
    the interactive path with a different SSE wrapper.
    """
    if isinstance(sandbox_event, SSEKeepalive):
        return

    # Flush pending chunks if this event breaks the chunk run.
    if state.should_finalize_chunks(_sse_type_for(sandbox_event)):
        save_pending_chunks(db_session, session_id, state, routing_meta)

    if isinstance(sandbox_event, AgentMessageChunk):
        text = _extract_text_from_content(sandbox_event.content)
        if text:
            state.add_message_chunk(text)
        return

    if isinstance(sandbox_event, AgentThoughtChunk):
        text = _extract_text_from_content(sandbox_event.content)
        if text:
            state.add_thought_chunk(text)
        return

    if isinstance(sandbox_event, ToolCallStart):
        return

    if isinstance(sandbox_event, ToolCallProgress):
        _persist_tool_call_progress(db_session, session_id, state, sandbox_event)
        return

    if isinstance(sandbox_event, AgentPlanUpdate):
        _persist_agent_plan(db_session, session_id, state, sandbox_event)
        return


def finalize_persist(
    db_session: DBSession,
    session_id: UUID,
    state: BuildStreamingState,
    routing_meta: dict[str, Any] | None = None,
) -> None:
    """End-of-stream hook: flush trailing chunks."""
    save_pending_chunks(db_session, session_id, state, routing_meta)


# =============================================================================
# Opencode session id management
# =============================================================================

# Both helpers commit immediately. The opencode session id is a write-
# ahead durable handle — losing it to a crash before the next persist
# would orphan the opencode session and drop the conversation history.


def ensure_opencode_session_id(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    sandbox_id: UUID,
    session_id: UUID,
) -> str | None:
    """Return the opencode session id for ``session_id``, minting one
    (lazily, on first turn) if needed. Commits immediately so the id
    survives a mid-stream crash."""
    build_session = (
        db_session.query(BuildSession).filter(BuildSession.id == session_id).first()
    )
    if build_session is None:
        logger.warning(
            "[SESSION-LIFECYCLE] preflight: BuildSession %s not found", session_id
        )
        return None
    if build_session.opencode_session_id:
        logger.info(
            "[SESSION-LIFECYCLE] preflight: reusing persisted "
            "opencode_session_id=%s for build_session=%s (no DB write, no "
            "/session call)",
            build_session.opencode_session_id,
            session_id,
        )
        return build_session.opencode_session_id

    logger.info(
        "[SESSION-LIFECYCLE] preflight: BuildSession %s has no "
        "opencode_session_id; calling sandbox_manager.ensure_opencode_session",
        session_id,
    )
    new_id = sandbox_manager.ensure_opencode_session(sandbox_id, session_id)
    if new_id is None:
        logger.warning(
            "[SESSION-LIFECYCLE] preflight: ensure_opencode_session returned None "
            "for build_session=%s",
            session_id,
        )
        return None
    build_session.opencode_session_id = new_id
    db_session.commit()
    logger.info(
        "[SESSION-LIFECYCLE] preflight: minted opencode_session_id=%s for "
        "build_session=%s",
        new_id,
        session_id,
    )
    return new_id


def persist_opencode_session_id(
    db_session: DBSession, session_id: UUID, new_id: str
) -> None:
    """Write a freshly-resolved opencode session id back to the row.

    Called from the transport's ``on_opencode_session_resolved`` callback
    when the persisted id was stale (e.g. pod restart returned 404 and the
    transport had to mint a new one). Without this rewrite the next turn
    would 404 on the same stale id and orphan another opencode session.
    """
    build_session = (
        db_session.query(BuildSession).filter(BuildSession.id == session_id).first()
    )
    if build_session is None:
        logger.warning(
            "[SESSION-LIFECYCLE] callback: BuildSession %s vanished before we "
            "could persist new opencode_session_id=%s",
            session_id,
            new_id,
        )
        return
    if build_session.opencode_session_id == new_id:
        return
    old_id = build_session.opencode_session_id
    build_session.opencode_session_id = new_id
    db_session.commit()
    logger.warning(
        "[SESSION-LIFECYCLE] callback: rewrote opencode_session_id %s -> %s for "
        "build_session=%s (stale id replaced)",
        old_id,
        new_id,
        session_id,
    )


# =============================================================================
# Sandbox event generator
# =============================================================================


def _get_session_agent_selection(
    db_session: DBSession, session_id: UUID
) -> tuple[str | None, str | None]:
    """``(agent_provider, agent_model)`` from the BuildSession row, or
    ``(None, None)`` for pre-migration rows."""
    row = db_session.query(BuildSession).filter(BuildSession.id == session_id).first()
    if row is None:
        return None, None
    return row.agent_provider, row.agent_model


def yield_sandbox_events(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    sandbox_id: UUID,
    session_id: UUID,
    user_message_content: str,
    opencode_session_id: str | None = None,
    should_interrupt: Callable[[], bool] | None = None,
) -> Generator[Any, None, None]:
    """Drain the CLI agent to completion, yielding raw sandbox events.

    Pure event source — no SSE formatting, no DB writes beyond the
    first-turn preflight that mints + persists the opencode session id.
    Callers compose this with :func:`persist_sandbox_event` (DB) and an
    SSE serializer to build a complete stream.

    Events include ``SSEKeepalive`` markers from the sandbox transport;
    callers should pass them through (interactive) or drop them
    (headless).
    """
    if opencode_session_id is None:
        opencode_session_id = ensure_opencode_session_id(
            db_session, sandbox_manager, sandbox_id, session_id
        )
    agent_provider, agent_model = _get_session_agent_selection(db_session, session_id)

    def _persist_resolved_id(new_id: str) -> None:
        persist_opencode_session_id(db_session, session_id, new_id)

    yield from sandbox_manager.send_message(
        sandbox_id,
        session_id,
        user_message_content,
        opencode_session_id=opencode_session_id,
        agent_provider=agent_provider,
        agent_model=agent_model,
        on_opencode_session_resolved=_persist_resolved_id,
        should_interrupt=should_interrupt,
    )


# =============================================================================
# Approval-announce merging
# =============================================================================


def merge_events_with_announces(
    event_iter: Iterable[Any],
    session_id: UUID,
    tenant_id: str,
) -> Generator[Any, None, None]:
    """Merge sandbox events and approval-announce packets into one stream.

    Two daemon threads feed a shared queue: one drains the sandbox event
    iterator, the other BLPOPs the approval cache and emits
    ``ApprovalRequestedPacket`` whenever the proxy signals a new approval.
    Announce latency is bounded by the 1s BLPOP.
    """
    output: queue_lib.Queue[Any] = queue_lib.Queue()
    stop = threading.Event()
    done_sentinel = object()

    def drive_events() -> None:
        try:
            for evt in event_iter:
                output.put(evt)
        except Exception as e:
            output.put(e)
        finally:
            output.put(done_sentinel)

    def drive_announces() -> None:
        cache = get_cache_backend(tenant_id=tenant_id)
        while not stop.is_set():
            try:
                approval_id = approval_cache.pop_announcement(
                    session_id, timeout_s=1, cache=cache
                )
            except Exception:
                logger.exception(
                    "approval.announce_poll_failed session_id=%s", session_id
                )
                time.sleep(1)
                continue
            if approval_id is None:
                continue
            output.put(
                ApprovalRequestedPacket(approval_id=approval_id, session_id=session_id)
            )

    threading.Thread(
        target=drive_events, name=f"events-pump-{session_id}", daemon=True
    ).start()
    threading.Thread(
        target=drive_announces, name=f"announce-pump-{session_id}", daemon=True
    ).start()
    try:
        while True:
            item = output.get()
            if item is done_sentinel:
                return
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        stop.set()


# =============================================================================
# Turn lock + interrupt fence
# =============================================================================


@contextlib.contextmanager
def acquire_turn_slot(
    sandbox_manager: SandboxManager,
    sandbox_id: UUID,
    session_id: UUID,
) -> Iterator[bool]:
    """Try to acquire the per-build-session turn lock.

    Yields:
        ``True`` if the slot was acquired and the caller may proceed.
        ``False`` if another turn is already in flight; the caller should
        emit a busy error and return without touching the agent.

    The underlying ``sandbox_manager.prompt_slot`` returns a context
    manager whose ``__enter__`` returns the acquired-bool. This wrapper
    lets callers use ordinary ``with`` syntax without juggling
    ``__enter__`` / ``__exit__`` manually.
    """
    inner = sandbox_manager.prompt_slot(sandbox_id, session_id)
    acquired = inner.__enter__()
    if not acquired:
        inner.__exit__(None, None, None)
        yield False
        return
    try:
        yield True
    finally:
        inner.__exit__(None, None, None)


def _safe_clear_interrupt(session_id: UUID) -> None:
    """Clear the interrupt fence, swallowing transient cache errors.

    A raise here would skip slot release in the caller's ``finally`` and
    leak the lock for the rest of the process's life.
    """
    try:
        clear_interrupt(session_id, get_cache_backend())
    except CACHE_TRANSIENT_ERRORS:
        logger.warning(
            "[SANDBOX-SERVE] failed to clear interrupt fence for session %s; "
            "releasing slot anyway",
            session_id,
            exc_info=True,
        )


def _interrupt_check(session_id: UUID) -> Callable[[], bool]:
    """A polling callable used by the transport. Fails open on cache
    blips so a degraded cache can never silently terminate a healthy turn."""
    cache = get_cache_backend()

    def _check() -> bool:
        try:
            return is_interrupt_requested(session_id, cache)
        except CACHE_TRANSIENT_ERRORS:
            logger.warning(
                "[SANDBOX-SERVE] interrupt fence check failed for session %s; "
                "treating as not-interrupted",
                session_id,
                exc_info=True,
            )
            return False

    return _check


# =============================================================================
# SSE dispatch (per-event-type emission)
# =============================================================================


def _ensure_routing_meta(sandbox_event: Any, routing_meta: dict[str, Any]) -> None:
    """Tag tool + agent-message events with routing ``_meta`` so the
    persisted row and the SSE frame both carry it. Must run BEFORE
    persistence so ``model_dump(by_alias=True)`` lands ``_meta``."""
    if isinstance(sandbox_event, _ROUTABLE_EVENT_TYPES):
        _merge_field_meta(sandbox_event, routing_meta)


def _dispatch_event_to_sse(
    sandbox_event: Any,
    packet_logger: PacketLogger | None,
    session_id: UUID,
) -> str | None:
    """Format ``sandbox_event`` as an SSE frame, logging to the packet
    logger on the way out. ``None`` for unrecognized events (the SSE
    stream skips them; persistence ignored them too).

    Pass ``packet_logger=None`` to skip packet logging (subagent path).
    """
    for descriptor in _EVENT_DESCRIPTORS:
        if isinstance(sandbox_event, descriptor.cls):
            if packet_logger is not None:
                event_data = sandbox_event.model_dump(
                    mode="json", by_alias=True, exclude_none=False
                )
                event_data["type"] = descriptor.sse_type
                event_data["timestamp"] = _utc_now_iso()
                packet_logger.log(descriptor.sse_type, event_data)
                packet_logger.log_sse_emit(descriptor.sse_type, session_id)
            return serialize_sandbox_event(sandbox_event, descriptor.sse_type)

    # Unrecognized: log to the diagnostic file but don't emit.
    if packet_logger is not None:
        event_type_name = type(sandbox_event).__name__
        event_data = sandbox_event.model_dump(
            mode="json", by_alias=True, exclude_none=False
        )
        event_data["type"] = f"unrecognized_{event_type_name.lower()}"
        packet_logger.log(f"unrecognized_{event_type_name.lower()}", event_data)
    return None


# =============================================================================
# Public stream entrypoints
# =============================================================================


def _emit_error(
    packet_logger: PacketLogger | None,
    message: str,
) -> Generator[str, None, None]:
    """Emit a single ``ErrorPacket`` SSE frame."""
    error_packet = ErrorPacket(message=message)
    if packet_logger is not None:
        packet_logger.log("error", error_packet.model_dump())
    yield format_packet_event(error_packet)


def _calculate_turn_index(db_session: DBSession, session_id: UUID) -> int:
    """The turn index is the 0-based count of existing USER messages: the
    new user message we're about to persist is the Nth turn."""
    return (
        db_session.query(BuildMessage)
        .filter(
            BuildMessage.session_id == session_id,
            BuildMessage.type == MessageType.USER,
        )
        .count()
    )


def _persist_user_message(
    db_session: DBSession,
    session_id: UUID,
    turn_index: int,
    content: str,
) -> None:
    create_message(
        session_id=session_id,
        message_type=MessageType.USER,
        turn_index=turn_index,
        message_metadata={
            "type": "user_message",
            "content": {"type": "text", "text": content},
        },
        db_session=db_session,
    )


def stream_cli_agent_turn(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    session_id: UUID,
    user_id: UUID,
    user_message_content: str,
) -> Generator[str, None, None]:
    """Drive a parent agent turn end-to-end and yield SSE frames.

    Storage behavior:
    - User message: persisted immediately at start.
    - ``agent_message_chunk`` / ``agent_thought_chunk``: accumulated;
      flushed as one synthetic row at end / on chunk-type change.
    - ``tool_call_start``: streamed only; not persisted.
    - ``tool_call_progress``: persisted on ``completed`` (every update
      for TodoWrite); completed Task tools also emit a synthetic
      ``agent_message`` row.
    - ``agent_plan_update``: upserted; latest plan wins.
    """
    packet_logger = get_packet_logger()
    log_separator(
        f"NEW MESSAGE STREAM - Session: {str(session_id)[:8]} - "
        f"User: {str(user_id)[:8]}"
    )
    packet_logger.log_raw(
        "STREAM-START",
        {
            "session_id": str(session_id),
            "user_id": str(user_id),
            "message_preview": user_message_content[:200]
            + ("..." if len(user_message_content) > 200 else ""),
        },
    )

    state = BuildStreamingState(turn_index=0)

    try:
        # --- Preflight ---------------------------------------------------
        session = get_build_session(session_id, user_id, db_session)
        if session is None:
            yield from _emit_error(packet_logger, "Session not found")
            return

        sandbox = get_sandbox_by_user_id(db_session, user_id)
        if not sandbox or sandbox.status != SandboxStatus.RUNNING:
            yield from _emit_error(
                packet_logger,
                "Sandbox is not running. Please wait for it to start.",
            )
            return

        update_session_activity(session_id, db_session)

        # --- Turn lock + interrupt fence ---------------------------------
        # Acquire the per-build_session lock BEFORE touching the opencode
        # session id (preflight + persist + transport). Keying on
        # build_session_id (not opencode_session_id) is deliberate: the
        # opencode id can rotate mid-turn via the
        # on_opencode_session_resolved callback, so a key based on it
        # would let a concurrent request take a DIFFERENT lock and bypass
        # serialization on exactly the recovery path. It also blocks
        # first-turn races where two simultaneous prompts on a fresh build
        # session would each mint their own opencode session.
        with acquire_turn_slot(sandbox_manager, sandbox.id, session_id) as acquired:
            if not acquired:
                yield from _emit_error(
                    packet_logger,
                    "This session is busy with a previous turn. Please wait "
                    "for it to finish before sending another message.",
                )
                return

            # NB: we deliberately do NOT clear the fence here. The finally
            # clears it before releasing the slot, so a prior turn's fence
            # can never leak. Clearing at turn start would instead wipe an
            # interrupt that landed while we were blocked acquiring the
            # slot — losing the very first-turn interrupt this feature
            # must honor.
            interrupt_requested = _interrupt_check(session_id)
            try:
                yield from _run_cli_turn(
                    db_session=db_session,
                    sandbox_manager=sandbox_manager,
                    packet_logger=packet_logger,
                    session_id=session_id,
                    sandbox_id=sandbox.id,
                    user_message_content=user_message_content,
                    state=state,
                    interrupt_requested=interrupt_requested,
                )
            finally:
                # Clear the fence BEFORE releasing the slot: while we hold
                # the slot no next turn can start, so we can't clobber a
                # fence legitimately set for that turn — and we don't let
                # this turn's fence outlive it either.
                _safe_clear_interrupt(session_id)

    except GeneratorExit:
        logger.warning(
            "Stream generator closed for session %s (client disconnected mid-stream)",
            session_id,
        )
        finalize_persist(db_session, session_id, state)
        return
    except ValueError as e:
        packet_logger.log_raw(
            "STREAM-ERROR",
            {
                "session_id": str(session_id),
                "error_type": "ValueError",
                "error": str(e),
            },
        )
        logger.exception("ValueError in build message streaming")
        yield from _emit_error(packet_logger, str(e))
    except RuntimeError as e:
        packet_logger.log_raw(
            "STREAM-ERROR",
            {
                "session_id": str(session_id),
                "error_type": "RuntimeError",
                "error": str(e),
            },
        )
        logger.exception("RuntimeError in build message streaming: %s", e)
        yield from _emit_error(packet_logger, str(e))
    except Exception as e:
        packet_logger.log_raw(
            "STREAM-ERROR",
            {
                "session_id": str(session_id),
                "error_type": type(e).__name__,
                "error": str(e),
            },
        )
        logger.exception("Unexpected error in build message streaming")
        yield from _emit_error(packet_logger, str(e))


def _run_cli_turn(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    packet_logger: PacketLogger,
    session_id: UUID,
    sandbox_id: UUID,
    user_message_content: str,
    state: BuildStreamingState,
    interrupt_requested: Callable[[], bool],
) -> Generator[str, None, None]:
    """Inner loop: lock has been acquired, sandbox is RUNNING. Persists
    the user message, drives the agent, and yields SSE frames."""
    turn_index = _calculate_turn_index(db_session, session_id)
    _persist_user_message(db_session, session_id, turn_index, user_message_content)
    state.turn_index = turn_index

    # Defensive re-check: the sandbox could have been deleted between
    # preflight and lock acquisition (the lock serializes turns, not
    # sandbox deletion). Surface a clean "Sandbox not found" rather than
    # failing inside the transport.
    if get_sandbox_by_session_id(db_session, session_id) is None:
        yield from _emit_error(packet_logger, "Sandbox not found")
        return

    packet_logger.log_raw(
        "STREAM-BEGIN-AGENT-LOOP",
        {
            "session_id": str(session_id),
            "sandbox_id": str(sandbox_id),
            "turn_index": turn_index,
        },
    )

    # Resolve the opencode session id BEFORE the interrupt fence check so
    # an interrupt that landed during the (slow) first-turn create stops
    # us before we drive the agent — closing the first-turn race a direct
    # abort can't.
    opencode_session_id = ensure_opencode_session_id(
        db_session, sandbox_manager, sandbox_id, session_id
    )
    if interrupt_requested():
        clear_interrupt(session_id, get_cache_backend())
        logger.info(
            "[SANDBOX-SERVE] turn interrupted before start: session=%s", session_id
        )
        yield serialize_sandbox_event(
            PromptResponse.model_validate({"stopReason": "cancelled"}),
            "prompt_response",
        )
        return

    events_emitted = 0
    merged_events = merge_events_with_announces(
        yield_sandbox_events(
            db_session,
            sandbox_manager,
            sandbox_id,
            session_id,
            user_message_content,
            opencode_session_id=opencode_session_id,
            should_interrupt=interrupt_requested,
        ),
        session_id=session_id,
        tenant_id=get_current_tenant_id(),
    )

    try:
        for sandbox_event in merged_events:
            # Approval announces are out-of-band packets, not sandbox
            # events: format and yield them directly.
            if isinstance(sandbox_event, ApprovalRequestedPacket):
                packet_logger.log(
                    "approval_requested", sandbox_event.model_dump(mode="json")
                )
                packet_logger.log_sse_emit("approval_requested", session_id)
                yield format_packet_event(sandbox_event)
                continue

            # Keepalives pass through as SSE comments (ignored by
            # EventSource but keep the TCP connection alive).
            if isinstance(sandbox_event, SSEKeepalive):
                packet_logger.log_sse_emit("keepalive", session_id)
                yield ": keepalive\n\n"
                continue

            # Persistence first so DB writes precede the SSE emit.
            persist_sandbox_event(db_session, session_id, state, sandbox_event)
            events_emitted += 1
            sse_frame = _dispatch_event_to_sse(sandbox_event, packet_logger, session_id)
            if sse_frame is not None:
                yield sse_frame

        finalize_persist(db_session, session_id, state)

        packet_logger.log_raw(
            "STREAM-COMPLETE",
            {
                "session_id": str(session_id),
                "sandbox_id": str(sandbox_id),
                "turn_index": turn_index,
                "events_emitted": events_emitted,
                "message_chunks_accumulated": len(state.message_chunks),
                "thought_chunks_accumulated": len(state.thought_chunks),
            },
        )

        update_sandbox_heartbeat(db_session, sandbox_id)
    except GeneratorExit:
        finalize_persist(db_session, session_id, state)
        raise


def stream_subagent_turn(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    session_id: UUID,
    user_id: UUID,
    subagent_opencode_session_id: str,
    user_message_content: str,
) -> Generator[str, None, None]:
    """Send a follow-up to a subagent's child opencode session and stream
    the response as SSE frames.

    Mirrors :func:`stream_cli_agent_turn` but:
    - targets an existing child opencode session (the subagent),
    - tags every tool / agent-message event + persisted row with routing
      ``_meta`` ``{"sessionId": <child>, "parentSessionId": <parent>}``
      so the frontend re-routes them under the subagent on reload,
    - skips approval-announce merging, packet logging, the first-turn
      opencode preflight, and the interrupt fence (none apply to a
      follow-up against an already-minted child session).
    """
    state = BuildStreamingState(turn_index=0)
    routing_meta: dict[str, Any] = {"sessionId": subagent_opencode_session_id}
    events_emitted = 0

    try:
        # --- Preflight ---------------------------------------------------
        session = get_build_session(session_id, user_id, db_session)
        if session is None:
            yield format_packet_event(ErrorPacket(message="Session not found"))
            return

        parent_opencode_session_id = session.opencode_session_id
        if not parent_opencode_session_id:
            yield format_packet_event(
                ErrorPacket(message="Parent session has no opencode session yet.")
            )
            return

        sandbox = get_sandbox_by_user_id(db_session, user_id)
        if not sandbox or sandbox.status != SandboxStatus.RUNNING:
            yield format_packet_event(
                ErrorPacket(
                    message="Sandbox is not running. Please wait for it to start."
                )
            )
            return

        update_session_activity(session_id, db_session)

        # --- Turn lock ---------------------------------------------------
        # Acquire the per-build-session lock: the parent turn and the
        # subagent follow-up share the pod directory + event bus, so a
        # concurrent parent turn would corrupt this stream.
        with acquire_turn_slot(sandbox_manager, sandbox.id, session_id) as acquired:
            if not acquired:
                yield format_packet_event(
                    ErrorPacket(
                        message=(
                            "This session is busy with a previous turn. "
                            "Please wait for it to finish before sending "
                            "another message."
                        )
                    )
                )
                return

            routing_meta["parentSessionId"] = parent_opencode_session_id

            # Use the parent session's model so the follow-up runs on the
            # same model as the parent (not the child session's default).
            agent_provider, agent_model = _get_session_agent_selection(
                db_session, session_id
            )

            event_iter = sandbox_manager.send_subagent_message(
                sandbox.id,
                session_id,
                subagent_opencode_session_id,
                user_message_content,
                agent_provider=agent_provider,
                agent_model=agent_model,
            )

            for sandbox_event in event_iter:
                if isinstance(sandbox_event, SSEKeepalive):
                    yield ": keepalive\n\n"
                    continue

                _ensure_routing_meta(sandbox_event, routing_meta)
                persist_sandbox_event(
                    db_session, session_id, state, sandbox_event, routing_meta
                )
                events_emitted += 1
                sse_frame = _dispatch_event_to_sse(
                    sandbox_event, packet_logger=None, session_id=session_id
                )
                if sse_frame is not None:
                    yield sse_frame

            finalize_persist(db_session, session_id, state, routing_meta)
            update_sandbox_heartbeat(db_session, sandbox.id)
    except GeneratorExit:
        logger.warning(
            "Subagent stream closed for session %s after %d events "
            "(client disconnected mid-stream)",
            session_id,
            events_emitted,
        )
        finalize_persist(db_session, session_id, state, routing_meta)
        return
    except Exception as e:
        logger.exception("Error in subagent message streaming")
        yield format_packet_event(ErrorPacket(message=str(e)))
