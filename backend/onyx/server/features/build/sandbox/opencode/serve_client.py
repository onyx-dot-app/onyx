"""HTTP client for ``opencode serve``.

Replaces the per-message ``opencode acp`` subprocess clients in
``sandbox/kubernetes/internal/acp_exec_client.py`` and
``sandbox/docker/internal/acp_exec_client.py``. The plan is documented in
``docs/craft/opencode-serve-migration.md`` and the design in
``docs/craft/features/opencode-serve-client.md``.

Public surface (mirrors the existing ACP clients enough that the sandbox
managers swap in one method call):

- :class:`OpencodeServeClient`
- :class:`ClientTimeouts`

Phase 1 deliverable: the client library only — no sandbox-manager wire-up.
Gated behind ``AGENT_TRANSPORT={"acp","serve"}`` in ``configs.py``.
"""

from __future__ import annotations

import queue
import time
from collections.abc import Generator
from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import cast

import httpx
from acp.schema import AgentMessageChunk
from acp.schema import AgentThoughtChunk
from acp.schema import Error
from acp.schema import PromptResponse
from acp.schema import ToolCallProgress
from acp.schema import ToolCallStart

from onyx.server.features.build.configs import ACP_MESSAGE_TIMEOUT
from onyx.server.features.build.configs import OPENCODE_SERVE_CONNECT_TIMEOUT
from onyx.server.features.build.configs import OPENCODE_SERVE_EVENT_READ_TIMEOUT
from onyx.server.features.build.configs import OPENCODE_SERVE_REQUEST_TIMEOUT
from onyx.server.features.build.configs import OPENCODE_SERVER_USERNAME
from onyx.server.features.build.configs import SSE_KEEPALIVE_INTERVAL
from onyx.server.features.build.sandbox.base import SSEKeepalive
from onyx.server.features.build.sandbox.opencode.event_bus import _Subscription
from onyx.server.features.build.sandbox.opencode.event_bus import BUS_CLOSED_SENTINEL
from onyx.server.features.build.sandbox.opencode.event_bus import PodEventBus
from onyx.utils.logger import setup_logger

logger = setup_logger()


# Acp event union (kept narrow — only the types we actually translate to).
ACPEvent = (
    AgentMessageChunk
    | AgentThoughtChunk
    | ToolCallStart
    | ToolCallProgress
    | PromptResponse
    | Error
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
    # PartID → part type ("text", "reasoning", "tool", "step-start",
    # "step-finish", ...). Populated from ``message.part.updated`` events.
    # Read by the delta handler to decide whether a delta is a text chunk
    # (AgentMessageChunk) or a reasoning chunk (AgentThoughtChunk) —
    # opencode emits BOTH on ``field=text`` deltas (the field refers to
    # the part's text attribute, not whether the content is reasoning).
    part_types: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tool-name mapping. Mirrors the frontend's NAME_MAP / TOOL_KIND_MAP in
# ``web/src/app/craft/utils/parsePacket.ts`` so the translator emits the
# same {kind, title} the existing ACP code path emits today.
# ---------------------------------------------------------------------------


_TOOL_KIND: dict[str, str] = {
    "bash": "execute",
    "read": "read",
    "write": "edit",
    "edit": "edit",
    "patch": "edit",
    "glob": "search",
    "grep": "search",
    "list": "search",
    "task": "other",
    "todowrite": "other",
    "todo_write": "other",
    "webfetch": "fetch",
    "websearch": "search",
}

_TOOL_TITLE: dict[str, str] = {
    "bash": "Running command",
    "read": "Reading",
    "write": "Writing",
    "edit": "Editing",
    "patch": "Editing",
    "glob": "Searching files",
    "grep": "Searching content",
    "list": "Listing",
    "task": "Running task",
    "todowrite": "Updating todos",
    "todo_write": "Updating todos",
    "webfetch": "Fetching web content",
    "websearch": "Searching web",
}


def _tool_kind(tool: str) -> str:
    return _TOOL_KIND.get(tool, "other")


def _tool_title(tool: str) -> str:
    return _TOOL_TITLE.get(tool, "Running tool")


# opencode's tool status values → ACP's ToolCallStatus literal.
# ACP: "pending" | "in_progress" | "completed" | "failed"
# opencode emits: "pending", "running", "completed". "running" → "in_progress".
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
    """
    out = state.get("output")
    if out is None:
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


# ---------------------------------------------------------------------------
# translate_opencode_event — pure function (no I/O, no self).
# ---------------------------------------------------------------------------


def translate_opencode_event(
    raw: dict[str, Any], state: _TurnState
) -> Iterable[ACPEvent]:
    """Convert one opencode ``/event`` payload into zero-or-more ACPEvents.

    Pure function: read-only over ``raw`` (but mutates ``state``). Called from
    the reader thread; all field access defensive against unexpected shapes.

    Returns an iterable so single opencode events that imply multiple ACP
    events (e.g. final ``message.updated`` → flush + ``PromptResponse``) can
    yield more than one.
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
    if sess_id is not None and sess_id != state.session_id:
        return  # event for another session (e.g. subagent child)

    # ── streaming text deltas ────────────────────────────────────────
    if etype == "message.part.delta":
        field_name = props.get("field")
        delta = props.get("delta")
        part_id = props.get("partID")
        msg_id = props.get("messageID")
        if not isinstance(delta, str) or not isinstance(part_id, str):
            return
        # Filter out parts belonging to the user message — only assistant
        # text should reach the consumer as AgentMessageChunk. In opencode's
        # event ordering, ``message.updated`` for the assistant message
        # always fires BEFORE any deltas on its parts, so we can require
        # ``assistant_message_id`` to be known and to match.
        if not state.assistant_message_ids:
            return
        if isinstance(msg_id, str) and msg_id not in state.assistant_message_ids:
            return
        if field_name != "text":
            # Non-text fields (e.g. tool input streaming, future extensions)
            # have no ACP-event mapping yet. Drop silently.
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
        # Other part types (step-start, step-finish, tool, ...) don't
        # carry user-visible text — ignore.
        return

    # ── part lifecycle (tool calls + gap-fill anchors for text parts) ──
    if etype == "message.part.updated":
        part = props.get("part") or {}
        if not isinstance(part, dict):
            return
        part_type = part.get("type")

        # Record the part's type so later ``message.part.delta`` events
        # can route to the right ACP event class (text → message chunk,
        # reasoning → thought chunk). Deltas alone don't carry the part
        # type, only the part id.
        part_id_for_state = part.get("id")
        if isinstance(part_id_for_state, str) and isinstance(part_type, str):
            state.part_types[part_id_for_state] = part_type

        if part_type == "reasoning":
            # Final reasoning text — gap-fill so dropped deltas are
            # recovered the same way they are for visible text.
            msg_id = part.get("messageID")
            if not state.assistant_message_ids:
                return
            if isinstance(msg_id, str) and msg_id not in state.assistant_message_ids:
                return
            yield from _reconcile_reasoning_part(part, state)
            return

        if part_type == "text":
            # Same role filter as message.part.delta — assistant parts only.
            msg_id = part.get("messageID")
            if not state.assistant_message_ids:
                return
            if isinstance(msg_id, str) and msg_id not in state.assistant_message_ids:
                return
            # Reconcile against our local accumulator.
            yield from _reconcile_text_part(part, state)
            return

        if part_type == "tool":
            yield from _emit_tool_events(part, state)
            return

        # Reasoning parts: streams come via message.part.delta with
        # field=reasoning; ignore the updated lifecycle for them.
        return

    # ── primary terminator ───────────────────────────────────────────
    if etype == "message.updated":
        info = props.get("info") or {}
        if not isinstance(info, dict):
            return
        if info.get("role") != "assistant":
            return
        # Record every assistant message id so subsequent text/reasoning
        # parts and deltas can be filtered against the full set. opencode
        # creates one assistant message per step within a turn, so we'll
        # see multiple (initial reasoning+tool-call message, post-tool
        # answer message, etc.).
        msg_id = info.get("id")
        if isinstance(msg_id, str):
            state.assistant_message_ids.add(msg_id)
        completed = (info.get("time") or {}).get("completed")
        if not completed:
            return
        # Distinguish clean termination vs error termination.
        err = info.get("error")
        if err and isinstance(err, dict):
            yield from _emit_terminator(state, error=err, finish=info.get("finish"))
        else:
            yield from _emit_terminator(state, finish=info.get("finish"))
        return

    # ── backstop terminators ─────────────────────────────────────────
    if etype == "session.idle":
        yield from _emit_terminator(state)
        return
    if etype == "session.status":
        if props.get("status") == "idle":
            yield from _emit_terminator(state)
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


def _reconcile_text_part(part: dict[str, Any], state: _TurnState) -> Iterable[ACPEvent]:
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
) -> Iterable[ACPEvent]:
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
) -> Iterable[ACPEvent]:
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


def _emit_tool_events(part: dict[str, Any], state: _TurnState) -> Iterable[ACPEvent]:
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
    raw_input = part_state.get("input") or None
    raw_output = _wrap_raw_output(part_state)
    content = _synthesize_tool_content(tool, part_state)

    common: dict[str, Any] = {
        "toolCallId": call_id,
        "title": _tool_title(tool),
        "kind": _tool_kind(tool),
        "status": status,
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
) -> Iterable[ACPEvent]:
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
        # opencode uses "stop" where ACP uses "end_turn".
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
    ) -> None:
        """``event_bus`` is required for :meth:`send_message`; unary
        methods (ensure_session, list_messages, abort) work without one
        — tests can omit it when exercising the unary surface only."""
        self._base_url = base_url.rstrip("/")
        self._password = password
        self._client_info = client_info or {
            "name": "onyx-opencode-serve-client",
            "version": "1.0.0",
        }
        self._timeouts = timeouts or ClientTimeouts()
        self._auth: httpx.BasicAuth | None = (
            httpx.BasicAuth(OPENCODE_SERVER_USERNAME, password) if password else None
        )
        self._event_bus = event_bus
        # transport is for tests (httpx.MockTransport). Unary only —
        # SSE subscription is owned by the bus.
        self._http = httpx.Client(
            base_url=self._base_url,
            auth=self._auth,
            transport=transport,
            timeout=httpx.Timeout(
                connect=self._timeouts.connect_timeout,
                read=self._timeouts.request_timeout,
                write=self._timeouts.request_timeout,
                pool=self._timeouts.connect_timeout,
            ),
        )

    # ----- session lifecycle ----------------------------------------

    def health_check(self) -> bool:
        try:
            r = self._http.get("/doc", timeout=self._timeouts.connect_timeout)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    # Cold-pod retry tunables — short window, total worst-case ~1.5s.
    _COLD_POD_RETRIES = 3
    _COLD_POD_BASE_DELAY = 0.25

    def _http_with_cold_pod_retry(
        self, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        """``self._http.request`` with bounded retries for transient
        connection errors that fire when the sandbox pod is K8s-Ready but
        opencode-serve hasn't bound :4096 yet.

        Retries on ``ConnectError`` and ``RemoteProtocolError`` only — never
        on HTTP error responses, which are application-level signals the
        caller must handle.
        """
        last_exc: Exception | None = None
        for attempt in range(self._COLD_POD_RETRIES + 1):
            try:
                return self._http.request(method, path, **kwargs)
            except (httpx.ConnectError, httpx.RemoteProtocolError) as e:
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

    def ensure_session(
        self,
        opencode_session_id: str | None,
        *,
        cwd: str,
        title: str | None = None,
    ) -> str:
        """Return a valid opencode session id. Idempotent across replicas.

        Tolerates a brief cold-pod window where the sandbox is K8s-Ready
        but opencode-serve hasn't bound :4096 yet — both connect failures
        and RemoteProtocolError ("server disconnected before sending a
        response") are retried with short backoff before bubbling up.
        """
        if opencode_session_id:
            r = self._http_with_cold_pod_retry("GET", f"/session/{opencode_session_id}")
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
                    "(persisted id stale; will create new)",
                    opencode_session_id,
                )
            else:
                _raise_for_status(r, "session lookup")
            # Fall through and create.
        else:
            logger.info(
                "[SESSION-LIFECYCLE] ensure_session: no caller-supplied id; creating"
            )

        body: dict[str, Any] = {"directory": cwd}
        if title:
            body["title"] = title
        r = self._http_with_cold_pod_retry("POST", "/session", json=body)
        _raise_for_status(r, "session create")
        data = r.json()
        new_id = data.get("id")
        if not isinstance(new_id, str):
            raise RuntimeError("opencode /session returned no id")
        logger.info(
            "[SESSION-LIFECYCLE] ensure_session: POST /session -> id=%s (cwd=%s)",
            new_id,
            cwd,
        )
        return new_id

    def delete_session(self, opencode_session_id: str) -> None:
        try:
            r = self._http.delete(f"/session/{opencode_session_id}")
            if r.status_code not in (200, 204, 404):
                logger.warning(
                    "opencode-serve: delete_session(%s) → HTTP %s",
                    opencode_session_id,
                    r.status_code,
                )
        except httpx.HTTPError as e:
            logger.warning(
                "opencode-serve: delete_session(%s) failed: %s",
                opencode_session_id,
                e,
            )

    def list_messages(self, opencode_session_id: str) -> list[dict[str, Any]]:
        """Snapshot the assistant message accumulator. Returns the parsed
        JSON list directly — callers introspect via dict access.

        Empirically (test report §Gap-fill): ``part.text`` is empty during
        streaming and only populated post-terminator. Use this only for
        the post-terminator fallback in the reconnect path.
        """
        r = self._http.get(f"/session/{opencode_session_id}/message")
        _raise_for_status(r, "session messages")
        data = r.json()
        if isinstance(data, list):
            return cast(list[dict[str, Any]], data)
        return []

    def abort(self, opencode_session_id: str) -> None:
        try:
            self._http.post(f"/session/{opencode_session_id}/abort", json={})
        except httpx.HTTPError as e:
            logger.warning(
                "opencode-serve: abort(%s) failed: %s",
                opencode_session_id,
                e,
            )

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
        model_provider: str | None = None,
        model_id: str | None = None,
        timeout: float = ACP_MESSAGE_TIMEOUT,
    ) -> Generator[ACPEvent, None, None]:
        """Stream one turn of ACPEvents via the shared per-pod bus.

        ``GeneratorExit`` (browser disconnect) → POST ``/abort``.
        Wall-clock timeout → POST ``/abort`` and yield :class:`Error`.
        """
        if self._event_bus is None:
            raise RuntimeError(
                "OpencodeServeClient.send_message requires event_bus; "
                "construct the client with event_bus=PodEventBus(...)"
            )

        state = _TurnState(session_id=opencode_session_id)
        sub = self._event_bus.subscribe(opencode_session_id)
        try:
            # Block until the bus reader has the stream open, else we'd
            # POST prompt_async and miss the first events of the turn.
            if not self._event_bus.stream_ready.wait(
                timeout=self._timeouts.connect_timeout
            ):
                yield Error.model_validate(
                    {
                        "code": -3,
                        "message": "opencode /event stream did not become ready",
                    }
                )
                return

            try:
                self._post_prompt_async(
                    opencode_session_id, message, model_provider, model_id
                )
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

            yield from self._consume_from_bus(sub, timeout, opencode_session_id, state)

        except GeneratorExit:
            self.abort(opencode_session_id)
            raise
        finally:
            self._event_bus.unsubscribe(sub)

    def _consume_from_bus(
        self,
        sub: _Subscription,
        timeout: float,
        opencode_session_id: str,
        state: _TurnState,
    ) -> Generator[ACPEvent, None, None]:
        """Drain the bus queue, translate, yield until a
        :class:`PromptResponse` is emitted. permission.asked → auto-allow."""
        terminated_locally = False
        start = time.monotonic()
        last_event = start
        while True:
            remaining = timeout - (time.monotonic() - start)
            if remaining <= 0:
                self.abort(opencode_session_id)
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

            for acp_event in translate_opencode_event(raw, state):
                if isinstance(acp_event, PromptResponse):
                    terminated_locally = True
                yield acp_event

            if raw.get("type") == "permission.asked":
                self._handle_permission_ask(raw, state.session_id)

            if terminated_locally:
                return

    # ----- private: HTTP helpers ------------------------------------

    def _post_prompt_async(
        self,
        opencode_session_id: str,
        message: str,
        model_provider: str | None,
        model_id: str | None,
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
        r = self._http.post(f"/session/{opencode_session_id}/prompt_async", json=body)
        _raise_for_status(r, "prompt_async")

    def _handle_permission_ask(self, evt: dict[str, Any], session_id: str) -> None:
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
