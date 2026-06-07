"""Turn-streaming pipeline.

Hosts the per-turn state container (``BuildStreamingState``), the
event-persistence dispatcher (``persist_sandbox_event`` / ``finalize_persist``),
the opencode-session-id management, and the two SSE entry points
(``stream_cli_agent_turn`` for parent turns, ``stream_subagent_turn`` for
subagent follow-ups). Pure cut from ``manager.py``; SessionManager's
streaming methods now delegate here.

The headless scheduled-tasks executor reaches into ``yield_sandbox_events``
/ ``persist_sandbox_event`` / ``finalize_persist`` directly (through
``SessionManager`` shims) so its transcripts are byte-identical to
interactive runs.
"""

import contextlib
import json
import queue as queue_lib
import threading
import time
from collections.abc import Callable
from collections.abc import Generator
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
from onyx.server.features.build.api.packets import ApprovalRequestedPacket
from onyx.server.features.build.api.packets import BuildPacket
from onyx.server.features.build.api.packets import ErrorPacket
from onyx.server.features.build.db.build_session import create_message
from onyx.server.features.build.db.build_session import get_build_session
from onyx.server.features.build.db.build_session import update_session_activity
from onyx.server.features.build.db.build_session import upsert_agent_plan
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


class BuildStreamingState:
    """Container for accumulating state during sandbox-event streaming.

    Similar to ChatStateContainer but adapted for sandbox event packet types.
    Accumulates chunks and tracks pending tool calls until completion.

    Usage:
        state = BuildStreamingState(turn_index=0)

        # During streaming:
        for packet in stream:
            if packet.type == "agent_message_chunk":
                state.add_message_chunk(packet.content.text)
            elif packet.type == "tool_call_progress" and packet.status == "completed":
                state.add_completed_tool_call(packet_data)
            # etc.

        # At end of streaming, call finalize methods and save
    """

    def __init__(self, turn_index: int) -> None:
        """Initialize streaming state for a turn.

        Args:
            turn_index: The 0-indexed user message number this turn belongs to
        """
        self.turn_index = turn_index

        # Accumulated text chunks (similar to answer_tokens in ChatStateContainer)
        self.message_chunks: list[str] = []
        self.thought_chunks: list[str] = []

        # For upserting agent_plan_update - track ID so we can update in place
        self.plan_message_id: UUID | None = None

        # Track what type of chunk we were last receiving
        self._last_chunk_type: str | None = None

    def add_message_chunk(self, text: str) -> None:
        """Accumulate message text."""
        self.message_chunks.append(text)
        self._last_chunk_type = "message"

    def add_thought_chunk(self, text: str) -> None:
        """Accumulate thought text."""
        self.thought_chunks.append(text)
        self._last_chunk_type = "thought"

    def finalize_message_chunks(
        self, routing_meta: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Build a synthetic packet with accumulated message text.

        ``routing_meta`` (when set) is merged into the packet's ACP ``_meta``
        field so a persisted subagent follow-up reloads under its subagent.

        Returns:
            A synthetic agent_message packet or None if no chunks accumulated
        """
        if not self.message_chunks:
            return None

        full_text = "".join(self.message_chunks)
        result: dict[str, Any] = {
            "type": "agent_message",
            "content": {"type": "text", "text": full_text},
            "sessionUpdate": "agent_message",
        }
        if routing_meta:
            result["_meta"] = dict(routing_meta)
        self.message_chunks.clear()
        return result

    def finalize_thought_chunks(
        self, routing_meta: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Build a synthetic packet with accumulated thought text.

        ``routing_meta`` (when set) is merged into the packet's ACP ``_meta``
        field.

        Returns:
            A synthetic agent_thought packet or None if no chunks accumulated
        """
        if not self.thought_chunks:
            return None

        full_text = "".join(self.thought_chunks)
        result: dict[str, Any] = {
            "type": "agent_thought",
            "content": {"type": "text", "text": full_text},
            "sessionUpdate": "agent_thought",
        }
        if routing_meta:
            result["_meta"] = dict(routing_meta)
        self.thought_chunks.clear()
        return result

    def should_finalize_chunks(self, new_packet_type: str) -> bool:
        """Check if we should finalize pending chunks before processing new packet.

        We finalize when the packet type changes from message/thought chunks
        to something else (or to a different chunk type).
        """
        if self._last_chunk_type is None:
            return False

        # If we were receiving message chunks and now get something else
        if (
            self._last_chunk_type == "message"
            and new_packet_type != "agent_message_chunk"
        ):
            return True

        # If we were receiving thought chunks and now get something else
        if (
            self._last_chunk_type == "thought"
            and new_packet_type != "agent_thought_chunk"
        ):
            return True

        return False

    def clear_last_chunk_type(self) -> None:
        """Clear the last chunk type tracking after finalization."""
        self._last_chunk_type = None


def _extract_text_from_content(content: Any) -> str:
    """Extract text from event content structure."""
    if content is None:
        return ""
    if hasattr(content, "type") and content.type == "text":
        return getattr(content, "text", "") or ""
    if isinstance(content, list):
        texts = []
        for block in content:
            if hasattr(block, "type") and block.type == "text":
                texts.append(getattr(block, "text", "") or "")
        return "".join(texts)
    return ""


# SSE comment line (leading `:` => ignored by EventSource and our custom
# processSSEStream parser). Pushes bytes periodically so idle-timeout killers
# (nginx, load balancers, browsers) don't tear down a long-lived stream while
# the agent emits nothing. The trailing blank line terminates the SSE record.
SSE_KEEPALIVE = ": keepalive\n\n"


def _serialize_sandbox_event(event: Any, event_type: str) -> str:
    """Serialize a sandbox event to SSE format, preserving all fields."""
    if hasattr(event, "model_dump"):
        data = event.model_dump(mode="json", by_alias=True, exclude_none=False)
    else:
        data = {"raw": str(event)}

    data["type"] = event_type
    data["timestamp"] = datetime.now(tz=timezone.utc).isoformat()

    return f"event: message\ndata: {json.dumps(data)}\n\n"


def event_to_sse(event: Any) -> str:
    """Translate a raw sandbox event to its SSE wire form.

    Keepalive markers become an SSE comment; every other event is serialized as
    a typed ``event: message`` record. The single seam shared by the interactive
    turn streams and the scheduled-run subscribe path so both emit identical
    wire bytes.
    """
    if isinstance(event, SSEKeepalive):
        return SSE_KEEPALIVE
    return _serialize_sandbox_event(event, _get_event_type(event))


def _format_packet_event(packet: BuildPacket) -> str:
    """Format a BuildPacket as SSE."""
    return f"event: message\ndata: {packet.model_dump_json(by_alias=True)}\n\n"


def _merge_events_with_announces(
    event_iter: Generator[Any, None, None],
    session_id: UUID,
    tenant_id: str,
) -> Generator[Any, None, None]:
    """Merge sandbox events and approval announces into one stream.

    Two producer threads feed a shared queue: the sandbox-event iterator, and a
    BLPOP poller that emits `ApprovalRequestedPacket` when the proxy
    signals a new approval. Announce latency is bounded by the 1s BLPOP.
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

    events_thread = threading.Thread(
        target=drive_events, name=f"events-pump-{session_id}", daemon=True
    )
    announce_thread = threading.Thread(
        target=drive_announces,
        name=f"announce-pump-{session_id}",
        daemon=True,
    )
    events_thread.start()
    announce_thread.start()
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


def _save_pending_chunks(
    db_session: DBSession,
    session_id: UUID,
    state: BuildStreamingState,
    routing_meta: dict[str, Any] | None = None,
) -> None:
    """Flush any pending accumulated message/thought chunks to the DB.

    Called when the next sandbox event is of a different type than the chunks
    currently being accumulated, and once more at end of stream.

    ``routing_meta`` tags the persisted packets' ACP ``_meta`` so subagent
    follow-up turns reload under their subagent (None for the parent path).
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


def load_turn_session(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    sandbox_id: UUID,
    session_id: UUID,
) -> BuildSession | None:
    """Headless preflight: fetch the BuildSession row and mint its
    opencode session on first turn. ``None`` if the row is gone.

    The interactive path resolves these off the session row it already
    holds; headless callers (scheduled-tasks executor) use this so they
    can pass fully-resolved values into :func:`yield_sandbox_events`.
    """
    build_session = (
        db_session.query(BuildSession).filter(BuildSession.id == session_id).first()
    )
    if build_session is None:
        logger.warning(
            "[SESSION-LIFECYCLE] preflight: BuildSession %s not found", session_id
        )
        return None
    _ensure_opencode_session_id(db_session, sandbox_manager, sandbox_id, build_session)
    return build_session


def yield_sandbox_events(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    sandbox_id: UUID,
    session_id: UUID,
    user_message_content: str,
    *,
    opencode_session_id: str | None,
    agent_provider: str | None,
    agent_model: str | None,
    should_interrupt: Callable[[], bool] | None = None,
) -> Generator[Any, None, None]:
    """Drive the agent to completion, yielding raw sandbox events.

    Thin pass-through to ``sandbox_manager.send_message`` — no DB reads,
    no SSE formatting. Callers resolve the turn inputs first
    (interactive path off the session row it holds; headless via
    :func:`load_turn_session`), then compose the events with
    `persist_sandbox_event` and, in the SSE case, an SSE serializer.

    The events include `SSEKeepalive` markers from the sandbox client;
    callers should pass them through (interactive) or drop them
    (headless).
    """

    def _persist_resolved_id(new_id: str) -> None:
        # Pod restart / eviction / 404 → the persisted opencode_session_id
        # was stale and the transport minted a new one; write it back so
        # the next turn doesn't 404 the stale id and orphan another
        # opencode session (dropping conversation history).
        _persist_opencode_session_id(db_session, session_id, new_id)

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


def _ensure_opencode_session_id(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    sandbox_id: UUID,
    build_session: BuildSession,
) -> str | None:
    """Return the row's ``opencode_session_id``, minting + persisting one
    on first turn."""
    if build_session.opencode_session_id:
        return build_session.opencode_session_id

    logger.info(
        "[SESSION-LIFECYCLE] preflight: BuildSession %s has no opencode_session_id; "
        "calling sandbox_manager.ensure_opencode_session",
        build_session.id,
    )
    new_id = sandbox_manager.ensure_opencode_session(sandbox_id, build_session.id)
    if new_id is None:
        logger.warning(
            "[SESSION-LIFECYCLE] preflight: ensure_opencode_session returned None "
            "for build_session=%s",
            build_session.id,
        )
        return None
    build_session.opencode_session_id = new_id
    db_session.commit()
    logger.info(
        "[SESSION-LIFECYCLE] preflight: persisted new opencode_session_id=%s "
        "for build_session=%s (first-turn create)",
        new_id,
        build_session.id,
    )
    return new_id


def _persist_opencode_session_id(
    db_session: DBSession, session_id: UUID, new_id: str
) -> None:
    """Write a freshly-resolved opencode_session_id back to the
    BuildSession row. Called from the transport's
    ``on_opencode_session_resolved`` callback when the persisted id
    was stale (404) or absent."""
    build_session = (
        db_session.query(BuildSession).filter(BuildSession.id == session_id).first()
    )
    if build_session is None:
        logger.warning(
            "[SESSION-LIFECYCLE] callback: BuildSession %s vanished before "
            "we could persist new opencode_session_id=%s",
            session_id,
            new_id,
        )
        return
    if build_session.opencode_session_id == new_id:
        logger.info(
            "[SESSION-LIFECYCLE] callback: opencode_session_id=%s already "
            "matches DB for build_session=%s; no-op",
            new_id,
            session_id,
        )
        return
    old_id = build_session.opencode_session_id
    build_session.opencode_session_id = new_id
    db_session.commit()
    logger.warning(
        "[SESSION-LIFECYCLE] callback: rewrote opencode_session_id %s -> %s "
        "for build_session=%s (stale id replaced)",
        old_id,
        new_id,
        session_id,
    )


def persist_sandbox_event(
    db_session: DBSession,
    session_id: UUID,
    state: BuildStreamingState,
    sandbox_event: Any,
    routing_meta: dict[str, Any] | None = None,
) -> None:
    """Apply persistence side effects for a single sandbox event.

    This is the persistence half of the old `_stream_cli_agent_response`
    method. It is intentionally synchronous and free of SSE / logging
    concerns so the headless scheduled-tasks executor can reuse it byte-
    for-byte against the same `BuildStreamingState` the interactive path
    uses.

    Behavior matches the pre-refactor interactive path exactly:
    - SSEKeepalive: no-op (handled by callers).
    - agent_message_chunk / agent_thought_chunk: accumulated; flushed
      when a non-chunk event arrives or at end of stream.
    - tool_call_start: no-op (only completed tool calls persist).
    - tool_call_progress: TodoWrite saves every progress update; other
      tools save only on `status == "completed"`. Completed Task
      sub-agent calls also emit a synthetic agent_message containing
      the task output.
    - agent_plan_update: upserted (only the latest plan per turn).
    - current_mode_update / prompt_response / error / unrecognized: not
      persisted by the interactive path; preserved here for parity.
    """
    if isinstance(sandbox_event, SSEKeepalive):
        return

    # Flush any pending chunks if the event type changed.
    event_type = _get_event_type(sandbox_event)
    if state.should_finalize_chunks(event_type):
        _save_pending_chunks(db_session, session_id, state, routing_meta)

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
        # Stream-only; persistence happens on `completed` progress.
        return

    if isinstance(sandbox_event, ToolCallProgress):
        event_data = sandbox_event.model_dump(
            mode="json", by_alias=True, exclude_none=False
        )
        event_data["type"] = "tool_call_progress"
        event_data["timestamp"] = datetime.now(tz=timezone.utc).isoformat()

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
            if task_output and isinstance(task_output, str):
                metadata_idx = task_output.find("<task_metadata>")
                if metadata_idx >= 0:
                    task_output = task_output[:metadata_idx].strip()

                if task_output:
                    task_output_packet = {
                        "type": "agent_message",
                        "content": {"type": "text", "text": task_output},
                        "source": "task_output",
                        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                    }
                    create_message(
                        session_id=session_id,
                        message_type=MessageType.ASSISTANT,
                        turn_index=state.turn_index,
                        message_metadata=task_output_packet,
                        db_session=db_session,
                    )
        return

    if isinstance(sandbox_event, AgentPlanUpdate):
        event_data = sandbox_event.model_dump(
            mode="json", by_alias=True, exclude_none=False
        )
        event_data["type"] = "agent_plan_update"
        event_data["timestamp"] = datetime.now(tz=timezone.utc).isoformat()
        plan_msg = upsert_agent_plan(
            session_id=session_id,
            turn_index=state.turn_index,
            plan_metadata=event_data,
            db_session=db_session,
            existing_plan_id=state.plan_message_id,
        )
        state.plan_message_id = plan_msg.id
        return

    # CurrentModeUpdate, PromptResponse, SandboxError, and unrecognized
    # packets are not persisted (parity with prior behavior).
    return


def finalize_persist(
    db_session: DBSession,
    session_id: UUID,
    state: BuildStreamingState,
    routing_meta: dict[str, Any] | None = None,
) -> None:
    """End-of-stream persistence hook. Flushes any pending chunks."""
    _save_pending_chunks(db_session, session_id, state, routing_meta)


def stream_cli_agent_turn(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    session_id: UUID,
    user_message_content: str,
    user_id: UUID,
) -> Generator[str, None, None]:
    """
    Stream the CLI agent's response using SSE format.

    Executes the agent via SandboxManager and streams events back to the client.
    Uses BuildStreamingState to accumulate chunks and track tool calls.
    At the end of streaming, saves accumulated state to the database.

    Storage behavior:
    - User message: Saved immediately at start
    - agent_message_chunk: Accumulated, saved as one synthetic packet at end/type change
    - agent_thought_chunk: Accumulated, saved as one synthetic packet at end/type change
    - tool_call_start: Streamed to frontend only, not saved
    - tool_call_progress: Only saved when status="completed"
    - agent_plan_update: Upserted (only latest plan kept per turn)
    """

    # Initialize packet logging
    packet_logger = get_packet_logger()

    # The log file auto-rotates to keep only the last N lines (default 5000).
    # Add a prominent separator for visual identification of new message streams.
    log_separator(
        f"NEW MESSAGE STREAM - Session: {str(session_id)[:8]} - User: {str(user_id)[:8]}"
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

    events_emitted = 0
    state: BuildStreamingState | None = None
    # Set inside the SERVE-transport block below; released in finally.
    prompt_slot_cm: contextlib.AbstractContextManager[bool] | None = None

    try:
        # Verify session exists and belongs to user
        session = get_build_session(session_id, user_id, db_session)
        if session is None:
            error_packet = ErrorPacket(message="Session not found")
            packet_logger.log("error", error_packet.model_dump())
            yield _format_packet_event(error_packet)
            return

        # Get the user's sandbox (now user-owned, not session-owned)
        sandbox = get_sandbox_by_user_id(db_session, user_id)

        # Check if sandbox is running
        if not sandbox or sandbox.status != SandboxStatus.RUNNING:
            error_packet = ErrorPacket(
                message="Sandbox is not running. Please wait for it to start."
            )
            packet_logger.log("error", error_packet.model_dump())
            yield _format_packet_event(error_packet)
            return

        # Update last activity timestamp
        update_session_activity(session_id, db_session)

        # Acquire a per-build-session lock BEFORE we touch the opencode
        # session id (preflight + persist + transport). Keying on
        # build_session_id (not opencode_session_id) is deliberate:
        # the opencode id can rotate mid-turn via the
        # on_opencode_session_resolved callback, so a key based on it
        # would let a concurrent request acquire a DIFFERENT lock and
        # bypass serialization on exactly the recovery path. It also
        # blocks first-turn races where two simultaneous prompts on a
        # fresh build session would each mint their own opencode
        # session. See SandboxManager.prompt_slot for the full
        # rationale.
        #
        # The slot is released in the matching `finally` at the
        # bottom of this try/except block.
        candidate_cm = sandbox_manager.prompt_slot(sandbox.id, session_id)
        if not candidate_cm.__enter__():
            # Release the no-op exit so the context manager's
            # contract is respected, then surface a clean error
            # without persisting any user_message or contacting
            # opencode.
            candidate_cm.__exit__(None, None, None)
            error_packet = ErrorPacket(
                message=(
                    "This session is busy with a previous turn. "
                    "Please wait for it to finish before sending "
                    "another message."
                )
            )
            packet_logger.log("error", error_packet.model_dump())
            yield _format_packet_event(error_packet)
            return
        # Slot acquired — hand off ownership to the outer finally,
        # which releases on every exit path.
        prompt_slot_cm = candidate_cm

        # NB: we deliberately do NOT clear the fence here. The finally clears
        # it before releasing the slot, so a prior turn's fence can never
        # leak to this one. Clearing at turn start instead would wipe an
        # interrupt that landed while we were blocked acquiring the slot —
        # losing the very first-turn interrupt this feature must honor.
        cache = get_cache_backend()

        def interrupt_requested() -> bool:
            # A cache blip must never fail a healthy turn — fail open.
            try:
                return is_interrupt_requested(session_id, cache)
            except CACHE_TRANSIENT_ERRORS:
                logger.warning(
                    "[SANDBOX-SERVE] interrupt fence check failed for "
                    "session %s; treating as not-interrupted",
                    session_id,
                    exc_info=True,
                )
                return False

        # Calculate turn_index BEFORE saving user message
        # turn_index = count of existing USER messages (this will be the Nth user message)

        # Get count of user messages to determine turn index
        existing_user_count = (
            db_session.query(BuildMessage)
            .filter(
                BuildMessage.session_id == session_id,
                BuildMessage.type == MessageType.USER,
            )
            .count()
        )
        turn_index = existing_user_count  # This user message is the Nth (0-indexed)

        # Save user message to database
        user_message_metadata = {
            "type": "user_message",
            "content": {"type": "text", "text": user_message_content},
        }
        create_message(
            session_id=session_id,
            message_type=MessageType.USER,
            turn_index=turn_index,
            message_metadata=user_message_metadata,
            db_session=db_session,
        )

        # Initialize streaming state for this turn
        state = BuildStreamingState(turn_index=turn_index)

        sandbox_id = sandbox.id

        packet_logger.log_raw(
            "STREAM-BEGIN-AGENT-LOOP",
            {
                "session_id": str(session_id),
                "sandbox_id": str(sandbox_id),
                "turn_index": turn_index,
            },
        )

        # Resolving here (before the interrupt-fence check) means an
        # interrupt that landed during the slow first-turn opencode mint
        # still stops us before we drive the agent.
        opencode_session_id = _ensure_opencode_session_id(
            db_session, sandbox_manager, sandbox_id, session
        )
        if interrupt_requested():
            clear_interrupt(session_id, cache)
            logger.info(
                "[SANDBOX-SERVE] turn interrupted before start: session=%s",
                session_id,
            )
            yield _serialize_sandbox_event(
                PromptResponse.model_validate({"stopReason": "cancelled"}),
                "prompt_response",
            )
            return

        # Drive the agent. sandbox events are merged with proxy approval
        # announces onto one SSE stream. `persist_sandbox_event` applies
        # persistence; SSE formatting + packet-logger book-keeping happen here.
        # `should_interrupt` lets the consume loop self-terminate on the
        # fence (abort + its own PromptResponse) within ~1s, even on an
        # event-less turn — so an interrupt never depends on opencode
        # emitting session.idle, which can leave the turn (and its slot)
        # hung until the wall-clock timeout.
        merged_events = _merge_events_with_announces(
            yield_sandbox_events(
                db_session,
                sandbox_manager,
                sandbox_id,
                session_id,
                user_message_content,
                opencode_session_id=opencode_session_id,
                agent_provider=session.agent_provider,
                agent_model=session.agent_model,
                should_interrupt=interrupt_requested,
            ),
            session_id=session_id,
            tenant_id=get_current_tenant_id(),
        )
        for sandbox_event in merged_events:
            if isinstance(sandbox_event, ApprovalRequestedPacket):
                packet_logger.log(
                    "approval_requested",
                    sandbox_event.model_dump(mode="json"),
                )
                packet_logger.log_sse_emit("approval_requested", session_id)
                yield _format_packet_event(sandbox_event)
                continue

            # Handle SSE keepalive - send comment to keep connection alive.
            if isinstance(sandbox_event, SSEKeepalive):
                # SSE comments start with : and are ignored by EventSource
                # but keep the HTTP connection alive.
                packet_logger.log_sse_emit("keepalive", session_id)
                yield SSE_KEEPALIVE
                continue

            # Persistence first so DB writes precede the SSE emit (matches
            # the prior in-loop ordering, which interleaved them).
            persist_sandbox_event(db_session, session_id, state, sandbox_event)
            events_emitted += 1

            # SSE-only branches: log + serialize for the HTTP client.
            if isinstance(sandbox_event, AgentMessageChunk):
                event_data = sandbox_event.model_dump(
                    mode="json", by_alias=True, exclude_none=False
                )
                event_data["type"] = "agent_message_chunk"
                packet_logger.log("agent_message_chunk", event_data)
                packet_logger.log_sse_emit("agent_message_chunk", session_id)
                yield _serialize_sandbox_event(sandbox_event, "agent_message_chunk")

            elif isinstance(sandbox_event, AgentThoughtChunk):
                packet_logger.log(
                    "agent_thought_chunk",
                    sandbox_event.model_dump(mode="json", by_alias=True),
                )
                packet_logger.log_sse_emit("agent_thought_chunk", session_id)
                yield _serialize_sandbox_event(sandbox_event, "agent_thought_chunk")

            elif isinstance(sandbox_event, ToolCallStart):
                packet_logger.log(
                    "tool_call_start",
                    sandbox_event.model_dump(mode="json", by_alias=True),
                )
                packet_logger.log_sse_emit("tool_call_start", session_id)
                yield _serialize_sandbox_event(sandbox_event, "tool_call_start")

            elif isinstance(sandbox_event, ToolCallProgress):
                event_data = sandbox_event.model_dump(
                    mode="json", by_alias=True, exclude_none=False
                )
                event_data["type"] = "tool_call_progress"
                event_data["timestamp"] = datetime.now(tz=timezone.utc).isoformat()
                packet_logger.log("tool_call_progress", event_data)
                packet_logger.log_sse_emit("tool_call_progress", session_id)
                yield _serialize_sandbox_event(sandbox_event, "tool_call_progress")

            elif isinstance(sandbox_event, AgentPlanUpdate):
                event_data = sandbox_event.model_dump(
                    mode="json", by_alias=True, exclude_none=False
                )
                event_data["type"] = "agent_plan_update"
                event_data["timestamp"] = datetime.now(tz=timezone.utc).isoformat()
                packet_logger.log("agent_plan_update", event_data)
                packet_logger.log_sse_emit("agent_plan_update", session_id)
                yield _serialize_sandbox_event(sandbox_event, "agent_plan_update")

            elif isinstance(sandbox_event, CurrentModeUpdate):
                event_data = sandbox_event.model_dump(
                    mode="json", by_alias=True, exclude_none=False
                )
                event_data["type"] = "current_mode_update"
                packet_logger.log("current_mode_update", event_data)
                packet_logger.log_sse_emit("current_mode_update", session_id)
                yield _serialize_sandbox_event(sandbox_event, "current_mode_update")

            elif isinstance(sandbox_event, PromptResponse):
                event_data = sandbox_event.model_dump(
                    mode="json", by_alias=True, exclude_none=False
                )
                event_data["type"] = "prompt_response"
                packet_logger.log("prompt_response", event_data)
                packet_logger.log_sse_emit("prompt_response", session_id)
                yield _serialize_sandbox_event(sandbox_event, "prompt_response")

            elif isinstance(sandbox_event, SandboxError):
                event_data = sandbox_event.model_dump(
                    mode="json", by_alias=True, exclude_none=False
                )
                event_data["type"] = "error"
                packet_logger.log("error", event_data)
                packet_logger.log_sse_emit("error", session_id)
                yield _serialize_sandbox_event(sandbox_event, "error")

            else:
                # Unrecognized packet type - log it but don't stream to frontend.
                event_type_name = type(sandbox_event).__name__
                event_data = sandbox_event.model_dump(
                    mode="json", by_alias=True, exclude_none=False
                )
                event_data["type"] = f"unrecognized_{event_type_name.lower()}"
                packet_logger.log(f"unrecognized_{event_type_name.lower()}", event_data)

        # Flush any pending accumulated chunks at end of stream.
        finalize_persist(db_session, session_id, state)

        # Log streaming completion
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

        # Update heartbeat after successful message exchange
        update_sandbox_heartbeat(db_session, sandbox_id)

    except GeneratorExit:
        logger.warning(
            "Stream generator closed for session %s after %d events "
            "(client disconnected mid-stream)",
            session_id,
            events_emitted,
        )
        if state is not None:
            finalize_persist(db_session, session_id, state)
        return
    except ValueError as e:
        error_packet = ErrorPacket(message=str(e))
        packet_logger.log("error", error_packet.model_dump())
        packet_logger.log_raw(
            "STREAM-ERROR",
            {
                "session_id": str(session_id),
                "error_type": "ValueError",
                "error": str(e),
            },
        )
        logger.exception("ValueError in build message streaming")
        yield _format_packet_event(error_packet)
    except RuntimeError as e:
        error_packet = ErrorPacket(message=str(e))
        packet_logger.log("error", error_packet.model_dump())
        packet_logger.log_raw(
            "STREAM-ERROR",
            {
                "session_id": str(session_id),
                "error_type": "RuntimeError",
                "error": str(e),
            },
        )
        logger.exception("RuntimeError in build message streaming: %s", e)
        yield _format_packet_event(error_packet)
    except Exception as e:
        error_packet = ErrorPacket(message=str(e))
        packet_logger.log("error", error_packet.model_dump())
        packet_logger.log_raw(
            "STREAM-ERROR",
            {
                "session_id": str(session_id),
                "error_type": type(e).__name__,
                "error": str(e),
            },
        )
        logger.exception("Unexpected error in build message streaming")
        yield _format_packet_event(error_packet)
    finally:
        # Release the per-opencode-session lock acquired above (if any).
        # Runs on every exit path including bare returns, GeneratorExit,
        # and exception flow — without this a long-running turn would
        # leak the lock and permanently block follow-up turns on the
        # same session.
        # Clear the fence BEFORE releasing the slot: while we still hold it
        # no next turn can start, so we can't clobber a fence legitimately
        # set for that turn. Don't let a fence outlive its turn either.
        # Guard the cache call — a raise here would skip the slot release
        # below and leak the lock for the rest of the process's life.
        try:
            clear_interrupt(session_id, get_cache_backend())
        except CACHE_TRANSIENT_ERRORS:
            logger.warning(
                "[SANDBOX-SERVE] failed to clear interrupt fence for "
                "session %s; releasing slot anyway",
                session_id,
                exc_info=True,
            )
        if prompt_slot_cm is not None:
            prompt_slot_cm.__exit__(None, None, None)


def stream_subagent_turn(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    session_id: UUID,
    subagent_opencode_session_id: str,
    content: str,
    user_id: UUID,
) -> Generator[str, None, None]:
    """SSE stream of a follow-up turn against a subagent child session.

    Focused parallel of :func:`stream_cli_agent_turn`: it reuses the same
    persistence (`persist_sandbox_event`) and SSE serialization
    (`_serialize_sandbox_event`) helpers, but drives the child session via
    ``sandbox_manager.send_subagent_message`` and tags routing ``_meta``.
    It does not re-run the parent's first-turn opencode-session preflight
    or model selection (the child session already exists with its own
    default model).
    """
    packet_logger = get_packet_logger()
    events_emitted = 0
    state: BuildStreamingState | None = None
    prompt_slot_cm: contextlib.AbstractContextManager[bool] | None = None
    # parentSessionId is filled in once we resolve the build session.
    routing_meta: dict[str, Any] = {"sessionId": subagent_opencode_session_id}

    try:
        session = get_build_session(session_id, user_id, db_session)
        if session is None:
            error_packet = ErrorPacket(message="Session not found")
            yield _format_packet_event(error_packet)
            return

        parent_opencode_session_id = session.opencode_session_id
        if not parent_opencode_session_id:
            error_packet = ErrorPacket(
                message="Parent session has no opencode session yet."
            )
            yield _format_packet_event(error_packet)
            return

        sandbox = get_sandbox_by_user_id(db_session, user_id)
        if not sandbox or sandbox.status != SandboxStatus.RUNNING:
            error_packet = ErrorPacket(
                message="Sandbox is not running. Please wait for it to start."
            )
            yield _format_packet_event(error_packet)
            return

        sandbox_id = sandbox.id
        update_session_activity(session_id, db_session)

        # Serialize against concurrent turns on the same build session
        # (the parent turn and a subagent follow-up share the same pod
        # directory + event bus).
        candidate_cm = sandbox_manager.prompt_slot(sandbox_id, session_id)
        if not candidate_cm.__enter__():
            candidate_cm.__exit__(None, None, None)
            error_packet = ErrorPacket(
                message=(
                    "This session is busy with a previous turn. "
                    "Please wait for it to finish before sending "
                    "another message."
                )
            )
            yield _format_packet_event(error_packet)
            return
        prompt_slot_cm = candidate_cm

        # Routing metadata merged into every forwarded subagent event and
        # the persisted assistant message.
        routing_meta["parentSessionId"] = parent_opencode_session_id

        state = BuildStreamingState(turn_index=0)

        # Subagent runs on the parent session's model, not the child's default.
        for sandbox_event in sandbox_manager.send_subagent_message(
            sandbox_id,
            session_id,
            subagent_opencode_session_id,
            content,
            agent_provider=session.agent_provider,
            agent_model=session.agent_model,
        ):
            # Keepalives + terminators pass through untagged.
            if isinstance(sandbox_event, SSEKeepalive):
                yield SSE_KEEPALIVE
                continue

            # Tag tool + agent-message events with routing _meta BEFORE
            # persistence so model_dump(by_alias=True) lands _meta in the
            # persisted row and the SSE frame.
            if isinstance(
                sandbox_event,
                (
                    ToolCallStart,
                    ToolCallProgress,
                    AgentMessageChunk,
                    AgentThoughtChunk,
                ),
            ):
                _merge_field_meta(sandbox_event, routing_meta)

            persist_sandbox_event(
                db_session, session_id, state, sandbox_event, routing_meta
            )
            events_emitted += 1

            if isinstance(sandbox_event, AgentMessageChunk):
                yield _serialize_sandbox_event(sandbox_event, "agent_message_chunk")
            elif isinstance(sandbox_event, AgentThoughtChunk):
                yield _serialize_sandbox_event(sandbox_event, "agent_thought_chunk")
            elif isinstance(sandbox_event, ToolCallStart):
                yield _serialize_sandbox_event(sandbox_event, "tool_call_start")
            elif isinstance(sandbox_event, ToolCallProgress):
                yield _serialize_sandbox_event(sandbox_event, "tool_call_progress")
            elif isinstance(sandbox_event, AgentPlanUpdate):
                yield _serialize_sandbox_event(sandbox_event, "agent_plan_update")
            elif isinstance(sandbox_event, CurrentModeUpdate):
                yield _serialize_sandbox_event(sandbox_event, "current_mode_update")
            elif isinstance(sandbox_event, PromptResponse):
                yield _serialize_sandbox_event(sandbox_event, "prompt_response")
            elif isinstance(sandbox_event, SandboxError):
                yield _serialize_sandbox_event(sandbox_event, "error")

        # Flush the accumulated assistant message tagged with routing _meta.
        finalize_persist(db_session, session_id, state, routing_meta)
        update_sandbox_heartbeat(db_session, sandbox_id)

    except GeneratorExit:
        logger.warning(
            "Subagent stream closed for session %s after %d events "
            "(client disconnected mid-stream)",
            session_id,
            events_emitted,
        )
        if state is not None:
            finalize_persist(db_session, session_id, state, routing_meta)
        return
    except Exception as e:
        error_packet = ErrorPacket(message=str(e))
        packet_logger.log("error", error_packet.model_dump())
        logger.exception("Error in subagent message streaming")
        yield _format_packet_event(error_packet)
    finally:
        if prompt_slot_cm is not None:
            prompt_slot_cm.__exit__(None, None, None)


def _get_event_type(sandbox_event: Any) -> str:
    """SSE ``type`` string for a sandbox event. Sandbox-event schema classes
    don't expose ``.type`` directly, so callers go through here."""
    if isinstance(sandbox_event, AgentMessageChunk):
        return "agent_message_chunk"
    elif isinstance(sandbox_event, AgentThoughtChunk):
        return "agent_thought_chunk"
    elif isinstance(sandbox_event, ToolCallStart):
        return "tool_call_start"
    elif isinstance(sandbox_event, ToolCallProgress):
        return "tool_call_progress"
    elif isinstance(sandbox_event, AgentPlanUpdate):
        return "agent_plan_update"
    elif isinstance(sandbox_event, CurrentModeUpdate):
        return "current_mode_update"
    elif isinstance(sandbox_event, PromptResponse):
        return "prompt_response"
    elif isinstance(sandbox_event, SandboxError):
        return "error"
    return "unknown"
