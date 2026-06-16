"""HTTP client for ``opencode serve`` — the only transport Onyx Craft
uses to drive in-sandbox agent turns. Design lives in
``docs/craft/features/opencode-serve-client.md``.

Public surface:

- :class:`OpencodeServeClient`
- :class:`ClientTimeouts`

Sandbox-event types come from :mod:`onyx.server.features.build.sandbox.event_schema`.
"""

from __future__ import annotations

import queue
import time
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import cast

import httpx

from onyx.server.features.build.configs import OPENCODE_SERVE_CONNECT_TIMEOUT
from onyx.server.features.build.configs import OPENCODE_SERVE_EVENT_READ_TIMEOUT
from onyx.server.features.build.configs import OPENCODE_SERVE_REQUEST_TIMEOUT
from onyx.server.features.build.configs import OPENCODE_SERVER_USERNAME
from onyx.server.features.build.configs import SANDBOX_TURN_TIMEOUT_SECONDS
from onyx.server.features.build.configs import SSE_KEEPALIVE_INTERVAL
from onyx.server.features.build.packets import SubagentStartedPacket
from onyx.server.features.build.sandbox.event_schema import AgentMessageChunk
from onyx.server.features.build.sandbox.event_schema import AgentThoughtChunk
from onyx.server.features.build.sandbox.event_schema import Error
from onyx.server.features.build.sandbox.event_schema import PromptResponse
from onyx.server.features.build.sandbox.event_schema import ToolCallProgress
from onyx.server.features.build.sandbox.event_schema import ToolCallStart
from onyx.server.features.build.sandbox.opencode.event_bus import _Subscription
from onyx.server.features.build.sandbox.opencode.event_bus import BUS_CLOSED_SENTINEL
from onyx.server.features.build.sandbox.opencode.event_bus import PodEventBus
from onyx.server.features.build.sandbox.sse import SSEKeepalive
from onyx.utils.logger import setup_logger

logger = setup_logger()


# Event union (kept narrow — only the types we actually translate to).
SandboxEvent = (
    AgentMessageChunk
    | AgentThoughtChunk
    | ToolCallStart
    | ToolCallProgress
    | PromptResponse
    | Error
    | SubagentStartedPacket
    | SSEKeepalive
)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ClientTimeouts:
    """HTTP timeouts for one ``OpencodeServeClient`` instance.

    Defaults pull from ``configs.py`` so deployment can tune via env without
    touching the client.
    """

    connect_timeout: float = OPENCODE_SERVE_CONNECT_TIMEOUT
    request_timeout: float = OPENCODE_SERVE_REQUEST_TIMEOUT
    event_read_timeout: float = OPENCODE_SERVE_EVENT_READ_TIMEOUT


# ---------------------------------------------------------------------------
# Per-turn state. Threaded through the reader so translation is correlation-
# aware (idempotent ToolCallStart, terminator de-dup, gap-fill accumulators).
# ---------------------------------------------------------------------------


@dataclass
class _TurnState:
    """Mutable per-turn state used by the translator.

    Lives only for the duration of one ``send_message`` call. Not exposed
    outside this module.
    """

    session_id: str
    # ToolCallStart is emitted only on the FIRST sighting of a callID.
    seen_tool_calls: set[str] = field(default_factory=set)
    # PromptResponse is yielded at most once per turn; subsequent backstop
    # signals are no-ops.
    terminator_yielded: bool = False
    # Per-text-partID accumulator: how many characters of each part we have
    # already yielded as AgentMessageChunk content. Used to gap-fill when a
    # ``message.part.updated`` for a text part reveals more text than we've
    # delivered (which happens after an ``/event`` reconnect).
    local_text: dict[str, str] = field(default_factory=dict)
    # MessageIDs of every assistant message in this turn. opencode creates
    # one assistant message per step, so a single user turn that involves
    # a tool call yields at least two: the message containing the
    # pre-tool thoughts + tool call, and a follow-up message containing
    # the post-tool synthesized answer. Text parts whose ``messageID``
    # isn't in this set are filtered (user echoes, prior-turn messages).
    assistant_message_ids: set[str] = field(default_factory=set)
    # PartID → "text" | "reasoning" | "tool" | ... (the delta routes on this).
    part_types: dict[str, str] = field(default_factory=dict)
    # MessageIDs we've ruled out as assistant (user role, malformed body,
    # or fetch failed). Kept so subsequent deltas short-circuit without
    # re-issuing the REST hydrate.
    user_message_ids: set[str] = field(default_factory=set)
    # `task` callID → claimed child session (parallel tasks get distinct children).
    task_child_by_call: dict[str, str] = field(default_factory=dict)
    # Descendant sessions share this parent turn stream but not opencode-local
    # ids. Keep each child session's message/part/tool caches isolated.
    child_states: dict[str, _TurnState] = field(default_factory=dict)
    # Last LLM finish reason seen on any assistant message.updated. Only the
    # terminator (fired from session.idle/status) consumes it — message.updated
    # itself is per-step and can't terminate the turn.
    last_finish: str | None = None


# ---------------------------------------------------------------------------
# Tool-name mapping. Mirrors the frontend's NAME_MAP / TOOL_KIND_MAP in
# ``web/src/app/craft/utils/parsePacket.ts`` so the translator emits the
# same {kind, title} the existing translator emits today.
# ---------------------------------------------------------------------------


_TOOL_KIND: dict[str, str] = {
    "bash": "execute",
    "read": "read",
    "write": "edit",
    "edit": "edit",
    "patch": "edit",
    "apply_patch": "edit",
    "applypatch": "edit",
    "glob": "search",
    "grep": "search",
    "list": "search",
    "task": "other",
    "todowrite": "other",
    "todo_write": "other",
    "webfetch": "fetch",
    "websearch": "search",
    # opencode 1.15.x additions:
    "lsp": "other",
    "skill": "other",
    "question": "other",
    "invalid": "other",
}

_TOOL_TITLE: dict[str, str] = {
    "bash": "Running command",
    "read": "Reading",
    "write": "Writing",
    "edit": "Editing",
    "patch": "Editing",
    "apply_patch": "Applying patch",
    "applypatch": "Applying patch",
    "glob": "Searching files",
    "grep": "Searching content",
    "list": "Listing",
    "task": "Running task",
    "todowrite": "Updating todos",
    "todo_write": "Updating todos",
    "webfetch": "Fetching web content",
    "websearch": "Searching web",
    # opencode 1.15.x additions:
    "lsp": "Checking code",
    "skill": "Running skill",
    "question": "Asking",
    "invalid": "Validating",
}


def _tool_kind(tool: str) -> str:
    return _TOOL_KIND.get(tool, "other")


def _tool_title(tool: str) -> str:
    return _TOOL_TITLE.get(tool, "Running tool")


# opencode's tool status values → ToolCallStatus literal.
# Onyx schema: "pending" | "in_progress" | "completed" | "failed"
# opencode emits: "pending", "running", "completed", "error". "running" → "in_progress".
_TOOL_STATUS_MAP: dict[str, str] = {
    "pending": "pending",
    "running": "in_progress",
    "in_progress": "in_progress",
    "completed": "completed",
    "failed": "failed",
    "error": "failed",
    "cancelled": "failed",
}


def _tool_status(opencode_status: Any) -> str:
    if not isinstance(opencode_status, str):
        return "pending"
    return _TOOL_STATUS_MAP.get(opencode_status, "pending")


# ---------------------------------------------------------------------------
# Tool-call ``content[]`` synthesis. Opencode serve does not emit a content
# array on tool parts — only ``state.{input,output,metadata}``. Onyx's
# frontend (and persistence path) reads from a content array, so we
# synthesize the shape it expects from the empirical field names locked in
# the test report.
# ---------------------------------------------------------------------------


def _synthesize_tool_content(
    tool: str, state: dict[str, Any]
) -> list[dict[str, Any]] | None:
    """Build the ``content`` array expected by the consumer for a tool call.

    Returns ``None`` for tools that don't need content synthesis (bash,
    task, etc. — their output ends up in ``raw_output`` instead).
    """
    inp = state.get("input") or {}

    # Edit tool: oldString/newString → {type: diff, oldText, newText, path}
    if tool in ("edit", "patch"):
        file_path = inp.get("filePath") or inp.get("file_path") or inp.get("path") or ""
        old = inp.get("oldString") or inp.get("oldText") or inp.get("old_string") or ""
        new = inp.get("newString") or inp.get("newText") or inp.get("new_string") or ""
        if file_path or old or new:
            return [
                {
                    "type": "diff",
                    "path": file_path,
                    "oldText": old,
                    "newText": new,
                }
            ]
        return None

    # Read tool: state.output is a string with `<file>…</file>`-ish wrapping
    # already line-numbered. Frontend's extractFileContent strips line numbers.
    if tool == "read":
        out = state.get("output")
        if isinstance(out, str):
            return [
                {
                    "type": "content",
                    "content": {"type": "text", "text": out},
                }
            ]
        return None

    return None


def _wrap_raw_output(state: dict[str, Any]) -> dict[str, Any] | None:
    """Frontend expects ``raw_output`` to be an object with an ``output``
    field. Opencode gives plain strings for most tools. Wrap consistently.

    Tools where ``state.output`` is already a dict (none observed in Phase 0
    but possible) get passed through unchanged.

    Error-state tool parts carry their message in ``state.error`` instead of
    ``state.output``.
    """
    out = state.get("output")
    if out is None:
        err = state.get("error")
        if isinstance(err, str) and err:
            out = err
        else:
            return None
    if isinstance(out, str):
        wrapped: dict[str, Any] = {"output": out}
        metadata = state.get("metadata")
        if metadata:
            wrapped["metadata"] = metadata
        return wrapped
    if isinstance(out, dict):
        return out
    return {"output": str(out)}


def _hydrate_message(
    state: _TurnState,
    msg_id: str,
    fetch_message: Callable[[str], dict[str, Any] | None] | None,
) -> str | None:
    """REST-fetch a message, populate caches, return role (or None).

    Negative results (fetch failure or unknown role) are cached in
    ``user_message_ids`` so ``_is_assistant_message`` short-circuits on
    subsequent deltas instead of re-issuing REST calls.
    """
    if fetch_message is None:
        state.user_message_ids.add(msg_id)
        return None
    body = fetch_message(msg_id)
    if not body:
        logger.warning("hydrate(%s): empty/failed fetch", msg_id)
        state.user_message_ids.add(msg_id)
        return None
    info = body.get("info") or {}
    if not isinstance(info, dict):
        logger.warning("hydrate(%s): no info object", msg_id)
        state.user_message_ids.add(msg_id)
        return None
    role = info.get("role")
    logger.info(
        "hydrate(%s): role=%s parts=%s", msg_id, role, len(body.get("parts") or [])
    )
    if role == "assistant":
        state.assistant_message_ids.add(msg_id)
    elif role == "user":
        state.user_message_ids.add(msg_id)
    else:
        state.user_message_ids.add(msg_id)
        return None
    parts = body.get("parts") or []
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, dict):
                continue
            part_id = part.get("id")
            part_type = part.get("type")
            if isinstance(part_id, str) and isinstance(part_type, str):
                state.part_types[part_id] = part_type
    return role if isinstance(role, str) else None


def _is_assistant_message(
    state: _TurnState,
    msg_id: str | None,
    fetch_message: Callable[[str], dict[str, Any] | None] | None,
) -> bool:
    """True if msg_id is a known assistant message, hydrating once if needed."""
    if not isinstance(msg_id, str):
        return False
    if msg_id in state.assistant_message_ids:
        return True
    if msg_id in state.user_message_ids:
        return False
    return _hydrate_message(state, msg_id, fetch_message) == "assistant"


def _emit_text_delta(
    props: dict[str, Any],
    state: _TurnState,
    fetch_message: Callable[[str], dict[str, Any] | None] | None,
) -> Iterable[SandboxEvent]:
    field_name = props.get("field")
    delta = props.get("delta")
    part_id = props.get("partID")
    msg_id = props.get("messageID")
    if not isinstance(delta, str) or not isinstance(part_id, str):
        return
    if not delta:
        return
    # Assistant-only filter. Deltas race ~300ms ahead of message.updated;
    # _is_assistant_message hydrates via REST when the role is unknown.
    if not _is_assistant_message(state, msg_id, fetch_message):
        return
    if field_name != "text":
        # Non-text fields (e.g. tool input streaming, future extensions)
        # have no sandbox-event mapping yet. Drop silently.
        return
    # Route by the PART'S TYPE (not the delta's ``field``, which is
    # always "text" because that's the part attribute being updated).
    # opencode emits reasoning content on parts with ``type=reasoning``
    # and visible text on parts with ``type=text``. The part type is
    # recorded from prior ``message.part.updated`` events.
    part_type = state.part_types.get(part_id, "text")
    if part_type == "reasoning":
        # Track reasoning accumulator the same way as text so the
        # post-delta ``message.part.updated`` reconciliation doesn't
        # double-emit. partID is unique across types, so they share
        # ``state.local_text`` without collision.
        state.local_text[part_id] = state.local_text.get(part_id, "") + delta
        yield AgentThoughtChunk.model_validate(
            {
                "sessionUpdate": "agent_thought_chunk",
                "content": {"type": "text", "text": delta},
            }
        )
    elif part_type == "text":
        state.local_text[part_id] = state.local_text.get(part_id, "") + delta
        yield AgentMessageChunk.model_validate(
            {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": delta},
            }
        )
    # Other part types (step-start, step-finish, tool, ...) don't carry
    # user-visible text — ignore.


# ---------------------------------------------------------------------------
# translate_opencode_event — translation has no I/O of its own. Hydration of
# unknown messageIDs (the delta-before-message.updated race) is delegated to
# the optional ``fetch_message`` callable injected by the caller.
# ---------------------------------------------------------------------------


def _is_descendant_of(
    sess_id: str,
    ancestor_id: str,
    parent_resolver: Callable[[str], str | None] | None,
) -> bool:
    """True if ``sess_id`` is a descendant of ``ancestor_id`` via the
    child→parent chain. Guards against cycles and missing resolver."""
    if parent_resolver is None:
        return False
    seen: set[str] = {sess_id}
    parent = parent_resolver(sess_id)
    while parent is not None and parent not in seen:
        if parent == ancestor_id:
            return True
        seen.add(parent)
        parent = parent_resolver(parent)
    return False


def _state_for_session(state: _TurnState, session_id: str) -> _TurnState:
    if session_id == state.session_id:
        return state
    child_state = state.child_states.get(session_id)
    if child_state is None:
        child_state = _TurnState(session_id=session_id)
        state.child_states[session_id] = child_state
    return child_state


def translate_opencode_event(
    raw: dict[str, Any],
    state: _TurnState,
    fetch_message: Callable[[str], dict[str, Any] | None] | None = None,
    parent_resolver: Callable[[str], str | None] | None = None,
    children_resolver: Callable[[str], list[str]] | None = None,
    fetch_message_by_session: Callable[[str, str], dict[str, Any] | None] | None = None,
) -> Iterable[SandboxEvent]:
    """Convert one opencode ``/event`` payload into zero-or-more SandboxEvents.

    Pure function: read-only over ``raw`` (but mutates ``state``). Called from
    the reader thread; all field access defensive against unexpected shapes.

    Returns an iterable so single opencode events that imply multiple
    sandbox events (e.g. final ``message.updated`` → flush +
    ``PromptResponse``) can yield more than one.

    ``parent_resolver`` (child→parent) lets the translator recognize events
    from descendant subagent sessions; their tool events are forwarded and
    tagged with routing metadata instead of dropped. ``children_resolver``
    (parent→children) lets the parent's ``task`` tool event be tagged with the
    subagent session it spawned.
    """
    etype = raw.get("type")
    if not isinstance(etype, str):
        return

    props = raw.get("properties") or {}
    if not isinstance(props, dict):
        return

    # All events for our session must match by sessionID. Some events nest the
    # session id under properties.info.sessionID, others under
    # properties.sessionID; check both.
    sess_id = props.get("sessionID")
    if sess_id is None:
        info = props.get("info") or {}
        if isinstance(info, dict):
            sess_id = info.get("sessionID")

    if etype == "session.created":
        info = props.get("info") or {}
        if not isinstance(info, dict):
            return
        child_id = info.get("id")
        parent_id = info.get("parentID")
        if (
            isinstance(child_id, str)
            and isinstance(parent_id, str)
            and parent_id == state.session_id
        ):
            yield SubagentStartedPacket(
                subagent_session_id=child_id,
                parent_session_id=parent_id,
            )
        return

    if isinstance(sess_id, str) and sess_id != state.session_id:
        # Event from another session. Forward descendant text/thought/tool
        # events tagged so the frontend can route them to the live subagent.
        if not _is_descendant_of(sess_id, state.session_id, parent_resolver):
            return  # unrelated session — drop as before

        child_meta = {"sessionId": sess_id, "parentSessionId": state.session_id}
        child_state = _state_for_session(state, sess_id)

        if etype == "message.updated":
            info = props.get("info") or {}
            if not isinstance(info, dict):
                return
            if info.get("role") != "assistant":
                return
            msg_id = info.get("id")
            if isinstance(msg_id, str):
                child_state.assistant_message_ids.add(msg_id)
            return

        child_fetch_message = (
            (lambda mid: fetch_message_by_session(sess_id, mid))
            if fetch_message_by_session is not None
            else None
        )

        if etype == "message.part.delta":
            for event in _emit_text_delta(props, child_state, child_fetch_message):
                _merge_field_meta(event, child_meta)
                yield event
            return

        if etype != "message.part.updated":
            return

        part = props.get("part") or {}
        if not isinstance(part, dict):
            return

        part_type = part.get("type")
        part_id_for_state = part.get("id")
        if isinstance(part_id_for_state, str) and isinstance(part_type, str):
            child_state.part_types[part_id_for_state] = part_type

        if part_type == "reasoning":
            if not _is_assistant_message(
                child_state, part.get("messageID"), child_fetch_message
            ):
                return
            events = _reconcile_reasoning_part(part, child_state)
        elif part_type == "text":
            if not _is_assistant_message(
                child_state, part.get("messageID"), child_fetch_message
            ):
                return
            events = _reconcile_text_part(part, child_state)
        elif part_type == "tool":
            events = _emit_tool_events(part, child_state)
        else:
            return

        for event in events:
            _merge_field_meta(event, child_meta)
            yield event
        return

    # ── streaming text deltas ────────────────────────────────────────
    if etype == "message.part.delta":
        yield from _emit_text_delta(props, state, fetch_message)
        return

    # ── part lifecycle (tool calls + gap-fill anchors for text parts) ──
    if etype == "message.part.updated":
        part = props.get("part") or {}
        if not isinstance(part, dict):
            return
        part_type = part.get("type")

        # Record the part's type so later ``message.part.delta`` events
        # can route to the right sandbox event class (text → message chunk,
        # reasoning → thought chunk). Deltas alone don't carry the part
        # type, only the part id.
        part_id_for_state = part.get("id")
        if isinstance(part_id_for_state, str) and isinstance(part_type, str):
            state.part_types[part_id_for_state] = part_type

        if part_type == "reasoning":
            if not _is_assistant_message(state, part.get("messageID"), fetch_message):
                return
            yield from _reconcile_reasoning_part(part, state)
            return

        if part_type == "text":
            if not _is_assistant_message(state, part.get("messageID"), fetch_message):
                return
            yield from _reconcile_text_part(part, state)
            return

        if part_type == "tool":
            # Tag the parent's ``task`` tool event with the subagent session it
            # spawned so the frontend can link the call to its child stream.
            subagent_sid: str | None = None
            if part.get("tool") == "task" and children_resolver is not None:
                # Each task callID claims the most-recent not-yet-claimed child.
                call_id = part.get("callID")
                if call_id is not None and call_id in state.task_child_by_call:
                    subagent_sid = state.task_child_by_call[call_id]
                else:
                    claimed = set(state.task_child_by_call.values())
                    unclaimed = [
                        c
                        for c in children_resolver(state.session_id)
                        if c not in claimed
                    ]
                    if unclaimed:
                        subagent_sid = unclaimed[-1]
                        if call_id is not None:
                            state.task_child_by_call[call_id] = subagent_sid
            for event in _emit_tool_events(part, state):
                if subagent_sid is not None:
                    _merge_field_meta(event, {"subagentSessionId": subagent_sid})
                yield event
            return

        # Reasoning parts: streams come via message.part.delta with
        # field=reasoning; ignore the updated lifecycle for them.
        return

    # ── role caching + error termination ─────────────────────────────
    # NOT a turn terminator: opencode emits time.completed on EVERY step's
    # assistant message (tool-call step, text step, etc.). The real
    # end-of-turn signal is session.status:idle / session.idle below.
    if etype == "message.updated":
        info = props.get("info") or {}
        if not isinstance(info, dict):
            return
        if info.get("role") != "assistant":
            return
        msg_id = info.get("id")
        if isinstance(msg_id, str):
            state.assistant_message_ids.add(msg_id)
        finish = info.get("finish")
        if isinstance(finish, str):
            state.last_finish = finish
        # A message error DOES kill the turn — surface it.
        err = info.get("error")
        if err and isinstance(err, dict):
            yield from _emit_terminator(state, error=err, finish=finish)
        return

    # ── turn terminators ─────────────────────────────────────────────
    # Mirrors opencode's CLI: packages/opencode/src/cli/cmd/run.ts:728.
    # session.status.status is {type: "idle"|"busy"|..., ...} — match on
    # status.type, not the outer string.
    if etype == "session.idle":
        yield from _emit_terminator(state, finish=state.last_finish)
        return
    if etype == "session.status":
        status = props.get("status")
        if isinstance(status, dict) and status.get("type") == "idle":
            yield from _emit_terminator(state, finish=state.last_finish)
        return

    # ── error envelope ───────────────────────────────────────────────
    if etype == "session.error":
        err = props.get("error") or {}
        if isinstance(err, dict):
            yield from _emit_terminator(state, error=err)
        return

    # Everything else (server.heartbeat, session.created, session.diff,
    # session.next.{agent,model}.switched, session.updated, etc.) is
    # informational — ignored.
    return


def _reconcile_text_part(
    part: dict[str, Any], state: _TurnState
) -> Iterable[SandboxEvent]:
    """Gap-fill reconciliation for visible-text parts. See module
    docstring + the ``message.part.delta`` handler for the full
    invariants. Emits a synthesized AgentMessageChunk for any text in
    ``part.text`` that we haven't already yielded as deltas."""
    yield from _reconcile_part_text(
        part,
        state,
        emit_class=AgentMessageChunk,
        session_update="agent_message_chunk",
    )


def _reconcile_reasoning_part(
    part: dict[str, Any], state: _TurnState
) -> Iterable[SandboxEvent]:
    """Same gap-fill as :func:`_reconcile_text_part` but for ``type=reasoning``
    parts — yields AgentThoughtChunk instead of AgentMessageChunk."""
    yield from _reconcile_part_text(
        part,
        state,
        emit_class=AgentThoughtChunk,
        session_update="agent_thought_chunk",
    )


def _reconcile_part_text(
    part: dict[str, Any],
    state: _TurnState,
    *,
    emit_class: type[AgentMessageChunk] | type[AgentThoughtChunk],
    session_update: str,
) -> Iterable[SandboxEvent]:
    """Shared gap-fill logic for any part type whose ``text`` field
    accumulates over deltas. ``state.local_text`` is keyed by partID so
    text-part and reasoning-part accumulators don't collide."""
    part_id = part.get("id")
    if not isinstance(part_id, str):
        return
    expected = part.get("text")
    if not isinstance(expected, str):
        return
    local = state.local_text.get(part_id, "")
    if len(expected) > len(local):
        tail = expected[len(local) :]
        state.local_text[part_id] = expected
        if tail:
            yield emit_class.model_validate(
                {
                    "sessionUpdate": session_update,
                    "content": {"type": "text", "text": tail},
                }
            )
    elif len(expected) < len(local):
        # Server-side rewind — shouldn't happen. Log and trust the longer
        # local accumulator (we've already streamed it).
        logger.warning(
            "opencode-serve: %s part %s rewound (expected %d < local %d); "
            "keeping local",
            session_update,
            part_id,
            len(expected),
            len(local),
        )


def _merge_field_meta(event: SandboxEvent, extra: dict[str, Any]) -> None:
    """Merge routing metadata into an event's ACP ``_meta`` field in place.

    ``field_meta`` (aliased ``_meta``) already carries ``toolName`` for tool
    events; merge rather than overwrite so both survive ``model_dump``."""
    existing = getattr(event, "field_meta", None)
    merged: dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
    merged.update(extra)
    setattr(event, "field_meta", merged)


def _emit_tool_events(
    part: dict[str, Any], state: _TurnState
) -> Iterable[SandboxEvent]:
    """Emit ToolCallStart (first sighting) and/or ToolCallProgress for a
    tool part update."""
    call_id = part.get("callID")
    tool = part.get("tool") or ""
    if not isinstance(call_id, str) or not isinstance(tool, str):
        return

    part_state = part.get("state") or {}
    if not isinstance(part_state, dict):
        return

    raw_status = part_state.get("status", "pending")
    status = _tool_status(raw_status)
    if status == "completed":
        metadata = part_state.get("metadata")
        exit_code = metadata.get("exit") if isinstance(metadata, dict) else None
        if isinstance(exit_code, int) and exit_code != 0:
            status = "failed"
    raw_input = part_state.get("input") or None
    raw_output = _wrap_raw_output(part_state)
    content = _synthesize_tool_content(tool, part_state)

    common: dict[str, Any] = {
        "toolCallId": call_id,
        "title": _tool_title(tool),
        "kind": _tool_kind(tool),
        "status": status,
        # _meta is an ACP-reserved extensibility field. We use it to carry
        # the raw opencode tool name so the frontend can resolve a precise
        # title (otherwise tools with kind="other" — todowrite, task, lsp,
        # skill, … — all fall through to "Running tool").
        "_meta": {"toolName": tool},
    }
    if raw_input is not None:
        common["rawInput"] = raw_input
    if raw_output is not None:
        common["rawOutput"] = raw_output
    if content is not None:
        common["content"] = content

    if call_id not in state.seen_tool_calls:
        state.seen_tool_calls.add(call_id)
        yield ToolCallStart.model_validate({"sessionUpdate": "tool_call", **common})
        # When the first sighting also carries non-pending state (it can,
        # depending on how fast opencode publishes), follow up with a
        # progress event so the consumer sees both lifecycle stages.
        if raw_status != "pending":
            yield ToolCallProgress.model_validate(
                {"sessionUpdate": "tool_call_update", **common}
            )
    else:
        yield ToolCallProgress.model_validate(
            {"sessionUpdate": "tool_call_update", **common}
        )


def _emit_terminator(
    state: _TurnState,
    *,
    error: dict[str, Any] | None = None,
    finish: Any = None,
) -> Iterable[SandboxEvent]:
    """Yield ``PromptResponse`` (or ``Error``) exactly once per turn.

    Subsequent calls within the same turn are no-ops — opencode emits
    several backstop signals (``session.idle``, ``session.status``,
    plus the primary ``message.updated``) that may race.
    """
    if state.terminator_yielded:
        return
    state.terminator_yielded = True

    if error:
        msg = ""
        data = error.get("data")
        if isinstance(data, dict):
            msg = str(data.get("message") or "")
        if not msg:
            msg = str(error.get("name") or "session error")
        yield Error.model_validate({"code": -1, "message": msg})
        return

    stop_reason = "end_turn"
    if isinstance(finish, str) and finish in (
        "end_turn",
        "max_tokens",
        "max_turn_requests",
        "refusal",
        "cancelled",
    ):
        stop_reason = finish
    elif finish == "stop":
        # opencode uses "stop" where the schema uses "end_turn".
        stop_reason = "end_turn"

    yield PromptResponse.model_validate({"stopReason": stop_reason})


# ---------------------------------------------------------------------------
# OpencodeServeClient — public class.
# ---------------------------------------------------------------------------


class OpencodeServeClient:
    """Thin Python client over a single in-pod ``opencode serve`` instance.

    Constructor and lifecycle responsibilities are deliberately small:
    sourcing the per-pod password, resolving the pod IP, and choosing the
    LLM model live in the sandbox manager. This client just speaks HTTP.

    See ``docs/craft/features/opencode-serve-client.md`` for the full
    design.
    """

    def __init__(
        self,
        base_url: str,
        password: str | None,
        *,
        event_bus: PodEventBus | None = None,
        client_info: dict[str, Any] | None = None,
        timeouts: ClientTimeouts | None = None,
        transport: httpx.BaseTransport | None = None,
        reload_password: Callable[[], str | None] | None = None,
    ) -> None:
        """``event_bus`` is required for :meth:`send_message`; unary
        methods (ensure_session, list_messages, abort) work without one
        — tests can omit it when exercising the unary surface only.

        ``reload_password`` re-fetches the password from its source of truth,
        invoked on a 401 to self-heal a peer-pod password rotation. ``None``
        disables the self-heal (e.g. health probes)."""
        self._base_url = base_url.rstrip("/")
        self._password = password
        self._client_info = client_info or {
            "name": "onyx-opencode-serve-client",
            "version": "1.0.0",
        }
        self._timeouts = timeouts or ClientTimeouts()
        self._reload_password = reload_password
        self._event_bus = event_bus
        # transport is for tests (httpx.MockTransport); stored so
        # _apply_password can rebuild the client without losing it.
        self._transport = transport
        self._auth = self._basic_auth(password)
        self._http = self._make_http_client()

    @staticmethod
    def _basic_auth(password: str | None) -> httpx.BasicAuth | None:
        return httpx.BasicAuth(OPENCODE_SERVER_USERNAME, password) if password else None

    def _make_http_client(self) -> httpx.Client:
        """Build a client bound to the current ``self._auth``. Pure — callers
        set ``self._auth`` first."""
        return httpx.Client(
            base_url=self._base_url,
            auth=self._auth,
            transport=self._transport,
            timeout=httpx.Timeout(
                connect=self._timeouts.connect_timeout,
                read=self._timeouts.request_timeout,
                write=self._timeouts.request_timeout,
                pool=self._timeouts.connect_timeout,
            ),
        )

    def _apply_password(self, password: str | None) -> None:
        """Rebuild the http client with a fresh password (auth is bound at
        construction); close the old one to avoid a pool leak."""
        old = self._http
        self._password = password
        self._auth = self._basic_auth(password)
        self._http = self._make_http_client()
        old.close()

    # ----- session lifecycle ----------------------------------------

    def health_check_status(self) -> int | None:
        """HTTP status from ``GET /doc``, or ``None`` on transport error — lets
        the readiness probe tell a 401 (stale password) from a not-yet-listening
        pod (transport error)."""
        try:
            r = self._http.get("/doc", timeout=self._timeouts.connect_timeout)
            return r.status_code
        except httpx.HTTPError:
            return None

    def health_check(self) -> bool:
        return self.health_check_status() == 200

    # Cold-pod retry tunables — short window, total worst-case ~1.5s.
    _COLD_POD_RETRIES = 3
    _COLD_POD_BASE_DELAY = 0.25

    def _http_with_cold_pod_retry(
        self,
        method: str,
        path: str,
        *,
        idempotent: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        """``self._http.request`` with bounded retries for transient
        connection errors that fire when the sandbox pod is K8s-Ready but
        opencode-serve hasn't bound :4096 yet.

        ``ConnectError`` is always retryable — a TCP connection refused
        proves the server never saw the request, so a retry can never
        produce duplicate side effects.

        ``RemoteProtocolError`` ("server disconnected without sending a
        response") is only retryable when the caller passes
        ``idempotent=True``. The server MAY have processed the request
        before the connection died, so retrying a non-idempotent POST
        (e.g. ``POST /session``) can create duplicate state — exactly the
        orphan-session bug this transport was designed to avoid.

        Never retries HTTP error responses — those are application-level
        signals the caller must handle.
        """
        retryable: tuple[type[BaseException], ...] = (
            (httpx.ConnectError, httpx.RemoteProtocolError)
            if idempotent
            else (httpx.ConnectError,)
        )
        last_exc: BaseException | None = None
        for attempt in range(self._COLD_POD_RETRIES + 1):
            try:
                return self._http.request(method, path, **kwargs)
            except retryable as e:
                last_exc = e
                if attempt == self._COLD_POD_RETRIES:
                    break
                delay = self._COLD_POD_BASE_DELAY * (attempt + 1)
                logger.info(
                    "[SESSION-LIFECYCLE] cold-pod retry %d/%d for %s %s after %s: %s",
                    attempt + 1,
                    self._COLD_POD_RETRIES,
                    method,
                    path,
                    type(e).__name__,
                    e,
                )
                time.sleep(delay)
        assert last_exc is not None
        raise last_exc

    def _request(
        self,
        method: str,
        path: str,
        *,
        idempotent: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        """Unary request with cold-pod retry plus a one-shot password reload
        on 401 (a peer pod rotated the password, staling our cache). Retrying
        is safe even for a non-idempotent POST: a 401 is rejected before
        processing, so the server never saw the body. An unchanged reload is a
        genuine auth failure — return it for the caller to surface."""
        r = self._http_with_cold_pod_retry(
            method, path, idempotent=idempotent, **kwargs
        )
        if r.status_code != 401 or self._reload_password is None:
            return r
        new_password = self._reload_password()
        if new_password == self._password:
            return r
        logger.info(
            "[SESSION-LIFECYCLE] 401 on %s %s; reloaded opencode password and "
            "retrying (peer pod likely rotated it)",
            method,
            path,
        )
        self._apply_password(new_password)
        return self._http_with_cold_pod_retry(
            method, path, idempotent=idempotent, **kwargs
        )

    def ensure_session(
        self,
        opencode_session_id: str | None,
        *,
        directory: str,
        title: str | None = None,
    ) -> str:
        """Return a valid opencode session id. Idempotent across replicas.

        A missing caller-supplied id is treated optimistically: the restored
        history snapshot may not contain that opencode session yet, so we mint a
        replacement id and let the caller persist it. Non-404 lookup failures
        still raise instead of masking runtime outages.

        ``directory`` anchors the opencode Instance for this session.
        Opencode-serve scopes its session store per-directory via the
        ``?directory=`` query parameter on every route (the
        ``Instance.provide`` middleware in ``server.ts``); the body field
        is silently ignored. Without it, the session is created in the
        server's launch cwd (``/workspace``) and every subsequent op must
        also omit ``?directory=`` to find it — which silently breaks
        per-session filesystem isolation.

        Tolerates a brief cold-pod window where the sandbox is K8s-Ready
        but opencode-serve hasn't bound :4096 yet — both connect failures
        and RemoteProtocolError ("server disconnected before sending a
        response") are retried with short backoff before bubbling up.
        """
        directory_params = {"directory": directory}
        if opencode_session_id:
            # GET is idempotent — safe to retry on either ConnectError or
            # RemoteProtocolError.
            r = self._request(
                "GET",
                f"/session/{opencode_session_id}",
                params=directory_params,
                idempotent=True,
            )
            if r.status_code == 200:
                logger.info(
                    "[SESSION-LIFECYCLE] ensure_session: GET /session/%s -> 200 "
                    "(reusing existing opencode session, no create)",
                    opencode_session_id,
                )
                return opencode_session_id
            if r.status_code == 404:
                logger.warning(
                    "[SESSION-LIFECYCLE] ensure_session: GET /session/%s -> 404 "
                    "(persisted id missing from opencode store; will create new)",
                    opencode_session_id,
                )
            else:
                _raise_for_status(r, "session lookup")
            # Fall through and create.
        else:
            logger.info(
                "[SESSION-LIFECYCLE] ensure_session: no caller-supplied id; creating"
            )

        body: dict[str, Any] = {}
        if title:
            body["title"] = title
        # POST /session is NOT idempotent — opencode mints a new session
        # id on every request. Retrying only on ConnectError (TCP refused
        # = server never saw it) keeps the call safe; a
        # RemoteProtocolError after a half-handled POST could leak an
        # orphan opencode session.
        r = self._request(
            "POST",
            "/session",
            params=directory_params,
            json=body,
            idempotent=False,
        )
        _raise_for_status(r, "session create")
        data = r.json()
        new_id = data.get("id")
        if not isinstance(new_id, str):
            raise RuntimeError("opencode /session returned no id")
        logger.info(
            "[SESSION-LIFECYCLE] ensure_session: POST /session -> id=%s (directory=%s)",
            new_id,
            directory,
        )
        return new_id

    def delete_session(self, opencode_session_id: str, *, directory: str) -> bool:
        """Best-effort delete of an opencode session from the live serve process.

        Product deletion is owned by Onyx's BuildSession row. This cleanup is
        opportunistic: failure should not block deleting the Onyx session.
        """
        try:
            r = self._request(
                "DELETE",
                f"/session/{opencode_session_id}",
                params={"directory": directory},
                idempotent=True,
            )
        except httpx.HTTPError as e:
            logger.warning(
                "opencode-serve: delete_session(%s) failed: %s",
                opencode_session_id,
                e,
            )
            return False

        if r.status_code in (200, 204, 404):
            return True
        logger.warning(
            "opencode-serve: delete_session(%s) -> HTTP %s",
            opencode_session_id,
            r.status_code,
        )
        return False

    def list_messages(
        self, opencode_session_id: str, *, directory: str
    ) -> list[dict[str, Any]]:
        """Snapshot the assistant message accumulator. Returns the parsed
        JSON list directly — callers introspect via dict access.

        Empirically (test report §Gap-fill): ``part.text`` is empty during
        streaming and only populated post-terminator. Use this only for
        the post-terminator fallback in the reconnect path.
        """
        r = self._request(
            "GET",
            f"/session/{opencode_session_id}/message",
            params={"directory": directory},
            idempotent=True,
        )
        _raise_for_status(r, "session messages")
        data = r.json()
        if isinstance(data, list):
            return cast(list[dict[str, Any]], data)
        return []

    def abort(self, opencode_session_id: str, *, directory: str) -> None:
        try:
            self._http.post(
                f"/session/{opencode_session_id}/abort",
                params={"directory": directory},
                json={},
            )
        except httpx.HTTPError as e:
            logger.warning(
                "opencode-serve: abort(%s) failed: %s",
                opencode_session_id,
                e,
            )

    def get_message(
        self, opencode_session_id: str, message_id: str, *, directory: str
    ) -> dict[str, Any] | None:
        """GET /session/{id}/message/{id}. None on any failure (never raises)."""
        try:
            r = self._request(
                "GET",
                f"/session/{opencode_session_id}/message/{message_id}",
                params={"directory": directory},
                idempotent=True,
            )
        except httpx.HTTPError as e:
            logger.warning("get_message(%s) network error: %s", message_id, e)
            return None
        if r.status_code != 200:
            logger.warning("get_message(%s) -> HTTP %s", message_id, r.status_code)
            return None
        try:
            body = r.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> OpencodeServeClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ----- the load-bearing method ----------------------------------

    def send_message(
        self,
        opencode_session_id: str,
        message: str,
        *,
        directory: str,
        model_provider: str | None = None,
        model_id: str | None = None,
        timeout: float = SANDBOX_TURN_TIMEOUT_SECONDS,
        should_interrupt: Callable[[], bool] | None = None,
    ) -> Generator[SandboxEvent, None, None]:
        """Stream one turn of SandboxEvents via the shared per-pod bus.

        ``directory`` must match the one passed to :meth:`ensure_session`
        — opencode-serve scopes its Instance (and therefore the session
        store) per ``?directory=`` query param; calling with a different
        directory will 404 the session.

        ``GeneratorExit`` (browser disconnect) → POST ``/abort``.
        Wall-clock timeout → POST ``/abort`` and yield :class:`Error`.
        """
        if self._event_bus is None:
            raise RuntimeError(
                "OpencodeServeClient.send_message requires event_bus; "
                "construct the client with event_bus=PodEventBus(...)"
            )

        state = _TurnState(session_id=opencode_session_id)
        turn_started_at = time.monotonic()
        prompt_posted = False

        def fetch_message(mid: str) -> dict[str, Any] | None:
            return self.get_message(opencode_session_id, mid, directory=directory)

        sub = self._event_bus.subscribe(opencode_session_id)
        try:
            # Wait until the bus reader has the /event stream open, else we'd
            # POST prompt_async and miss the first events of the turn. The bus
            # may be in a reconnect window after a transient disconnect, so do
            # not fail on the short HTTP connect timeout; wait within the turn's
            # wall-clock budget while emitting keepalives.
            ready = yield from self._wait_for_event_stream_ready(
                sub,
                timeout,
                turn_started_at,
                should_interrupt=should_interrupt,
            )
            if not ready:
                return

            try:
                self._post_prompt_async(
                    opencode_session_id,
                    message,
                    model_provider,
                    model_id,
                    directory=directory,
                )
                prompt_posted = True
            except httpx.HTTPStatusError as e:
                yield Error.model_validate(
                    {
                        "code": e.response.status_code,
                        "message": _short_body(e.response),
                    }
                )
                return
            except httpx.HTTPError as e:
                yield Error.model_validate(
                    {"code": -3, "message": f"prompt_async failed: {e}"}
                )
                return

            remaining_timeout = max(0.0, timeout - (time.monotonic() - turn_started_at))
            yield from self._consume_from_bus(
                sub,
                remaining_timeout,
                opencode_session_id,
                state,
                fetch_message,
                directory=directory,
                parent_resolver=self._event_bus.parent_of,
                children_resolver=self._event_bus.list_children,
                should_interrupt=should_interrupt,
            )

        except GeneratorExit:
            if prompt_posted:
                self.abort(opencode_session_id, directory=directory)
            raise
        finally:
            self._event_bus.unsubscribe(sub)

    def _wait_for_event_stream_ready(
        self,
        sub: _Subscription,
        timeout: float,
        turn_started_at: float,
        *,
        should_interrupt: Callable[[], bool] | None = None,
    ) -> Generator[SandboxEvent, None, bool]:
        """Wait for the shared /event reader to be connected before prompting.

        This absorbs short reconnect windows without dropping the turn. It still
        respects the caller's turn budget and exits promptly if the bus gives up
        and self-closes.
        """
        last_keepalive = time.monotonic()
        last_interrupt_check = last_keepalive

        while True:
            if self._event_bus is None:
                yield Error.model_validate(
                    {
                        "code": -3,
                        "message": "opencode /event bus is unavailable",
                    }
                )
                return False

            if self._event_bus.closed:
                yield Error.model_validate(
                    {
                        "code": -3,
                        "message": "event bus closed before /event stream became ready",
                    }
                )
                return False

            if self._event_bus.stream_ready.is_set():
                return True

            now = time.monotonic()
            if should_interrupt is not None and now - last_interrupt_check >= 1.0:
                last_interrupt_check = now
                if should_interrupt():
                    yield PromptResponse.model_validate({"stopReason": "cancelled"})
                    return False

            remaining = timeout - (now - turn_started_at)
            if remaining <= 0:
                yield Error.model_validate(
                    {
                        "code": -3,
                        "message": "opencode /event stream did not become ready",
                    }
                )
                return False

            wait_for = min(remaining, 1.0)
            if self._event_bus.stream_ready.wait(timeout=wait_for):
                return True

            try:
                raw = sub.queue.get_nowait()
            except queue.Empty:
                if time.monotonic() - last_keepalive >= SSE_KEEPALIVE_INTERVAL:
                    yield SSEKeepalive()
                    last_keepalive = time.monotonic()
                continue

            if raw is BUS_CLOSED_SENTINEL:
                yield Error.model_validate(
                    {
                        "code": -3,
                        "message": "event bus closed before /event stream became ready",
                    }
                )
                return False

            # Do not translate pre-prompt events; they belong to prior activity
            # on this opencode session. Loop back to re-check stream readiness,
            # timeout, and bus closure.

    def _consume_from_bus(
        self,
        sub: _Subscription,
        timeout: float,
        opencode_session_id: str,
        state: _TurnState,
        fetch_message: Callable[[str], dict[str, Any] | None],
        *,
        directory: str,
        parent_resolver: Callable[[str], str | None] | None = None,
        children_resolver: Callable[[str], list[str]] | None = None,
        should_interrupt: Callable[[], bool] | None = None,
    ) -> Generator[SandboxEvent, None, None]:
        """Drain the bus queue, translate, yield until a
        :class:`PromptResponse` is emitted. permission.asked → auto-allow.

        ``should_interrupt`` (polled ~1/s) lets the caller end the turn
        deterministically: we abort opencode and emit our own terminating
        ``PromptResponse`` rather than waiting on a ``session.idle`` that may
        never arrive after an abort — otherwise an interrupted, event-less turn
        would pin its slot until ``timeout``."""
        terminated_locally = False
        start = time.monotonic()
        last_event = start
        last_interrupt_check = start
        while True:
            now = time.monotonic()
            if should_interrupt is not None and now - last_interrupt_check >= 1.0:
                last_interrupt_check = now
                if should_interrupt():
                    self.abort(opencode_session_id, directory=directory)
                    yield PromptResponse.model_validate({"stopReason": "cancelled"})
                    return

            remaining = timeout - (time.monotonic() - start)
            if remaining <= 0:
                self.abort(opencode_session_id, directory=directory)
                yield Error.model_validate(
                    {"code": -1, "message": "Timeout waiting for response"}
                )
                return

            try:
                raw = sub.queue.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                idle = time.monotonic() - last_event
                if idle >= SSE_KEEPALIVE_INTERVAL:
                    yield SSEKeepalive()
                    last_event = time.monotonic()
                continue

            last_event = time.monotonic()

            if raw is BUS_CLOSED_SENTINEL:
                if not terminated_locally:
                    yield Error.model_validate(
                        {
                            "code": -3,
                            "message": "event bus closed before terminator",
                        }
                    )
                return

            # server.connected is a bus-internal readiness marker.
            if raw.get("type") == "server.connected":
                continue

            for sandbox_event in translate_opencode_event(
                raw,
                state,
                fetch_message,
                parent_resolver=parent_resolver,
                children_resolver=children_resolver,
                fetch_message_by_session=lambda session_id,
                message_id: self.get_message(
                    session_id, message_id, directory=directory
                ),
            ):
                if isinstance(sandbox_event, (Error, PromptResponse)):
                    terminated_locally = True
                yield sandbox_event

            if raw.get("type") == "permission.asked":
                self._handle_permission_ask(raw, state.session_id, directory=directory)

            if terminated_locally:
                return

    # ----- private: HTTP helpers ------------------------------------

    def _post_prompt_async(
        self,
        opencode_session_id: str,
        message: str,
        model_provider: str | None,
        model_id: str | None,
        *,
        directory: str,
    ) -> None:
        """POST /session/.../prompt_async.

        If ``model_provider`` and ``model_id`` are both provided, override
        opencode.json's default for this turn. Otherwise the body omits
        ``model`` and opencode falls back to the session's default
        (written by ``setup_session_workspace`` into ``opencode.json``).
        """
        body: dict[str, Any] = {"parts": [{"type": "text", "text": message}]}
        if model_provider and model_id:
            body["model"] = {"providerID": model_provider, "modelID": model_id}
        # idempotent=False: only the 401 reload retries this POST.
        r = self._request(
            "POST",
            f"/session/{opencode_session_id}/prompt_async",
            params={"directory": directory},
            json=body,
            idempotent=False,
        )
        _raise_for_status(r, "prompt_async")

    def _handle_permission_ask(
        self, evt: dict[str, Any], session_id: str, *, directory: str
    ) -> None:
        """Auto-allow + telemetry per §Decisions #1.

        Production ``opencode.json`` should already cover every permission
        category we use. Reaching this path means opencode added a new
        category we haven't configured — auto-allow keeps the turn moving
        and the WARN log lets us notice.
        """
        props = evt.get("properties") or {}
        perm_id = props.get("id")
        perm_type = props.get("permission")
        patterns = props.get("patterns")
        if not isinstance(perm_id, str):
            logger.warning(
                "opencode-serve: permission.asked without id; cannot respond"
            )
            return
        logger.warning(
            "opencode-serve: auto-allowing unexpected permission.asked "
            "(type=%s patterns=%s session=%s id=%s) — update opencode.json",
            perm_type,
            patterns,
            session_id,
            perm_id,
        )
        try:
            self._http.post(
                f"/session/{session_id}/permissions/{perm_id}",
                params={"directory": directory},
                json={"response": "once"},
            )
        except httpx.HTTPError as e:
            logger.warning(
                "opencode-serve: permission auto-allow failed for %s: %s",
                perm_id,
                e,
            )


# ---------------------------------------------------------------------------
# Module-private helpers.
# ---------------------------------------------------------------------------


def _short_body(r: httpx.Response) -> str:
    try:
        text = r.text or ""
    except Exception:  # noqa: BLE001
        return f"<unreadable body, HTTP {r.status_code}>"
    return text[:200]


def _raise_for_status(r: httpx.Response, op: str) -> None:
    if r.status_code >= 400:
        raise httpx.HTTPStatusError(
            f"{op} failed with HTTP {r.status_code}: {_short_body(r)}",
            request=r.request,
            response=r,
        )
