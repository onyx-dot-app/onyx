"""Unit tests for :meth:`OpencodeServeClient.send_message` post-bus-refactor.

After the bus refactor, ``send_message`` is mostly orchestration: subscribe
to the per-pod :class:`PodEventBus`, POST ``prompt_async``, drain the
subscriber queue, translate events, detect terminator, unsubscribe. These
tests drive that orchestration with a fake bus + ``httpx.MockTransport``
so we never need a real opencode-serve to exercise the flow.

Coverage targets:
- Happy path: assistant text + reasoning + terminator
- Per-prompt model override threads ``providerID``/``modelID`` into the POST
- ``prompt_async`` HTTP error surfaces as the ``Error`` event
- Bus close sentinel ends the stream with an Error if no terminator seen
- Wall-clock timeout posts abort + yields Error
- ``GeneratorExit`` (browser disconnect) posts abort and re-raises
- Permission-ask events trigger out-of-band POST (auto-allow)
- ``stream_ready`` waits through transient reconnect windows before prompting
- ``stream_ready`` timeout when the bus never reconnects
"""

from __future__ import annotations

import threading
import time
from collections.abc import Generator
from typing import Any

import httpx
import pytest

from onyx.server.features.build.sandbox.event_schema import AgentMessageChunk
from onyx.server.features.build.sandbox.event_schema import AgentThoughtChunk
from onyx.server.features.build.sandbox.event_schema import Error
from onyx.server.features.build.sandbox.event_schema import PromptResponse
from onyx.server.features.build.sandbox.opencode.event_bus import PodEventBus
from onyx.server.features.build.sandbox.opencode.serve_client import ClientTimeouts
from onyx.server.features.build.sandbox.opencode.serve_client import OpencodeServeClient

_SESSION = "ses_test_123"
_DIRECTORY = "/workspace/sessions/test-session"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _RecordingTransport(httpx.MockTransport):
    """MockTransport that also records every request for later assertions."""

    def __init__(self, handler: Any) -> None:
        self.requests: list[httpx.Request] = []

        def recorder(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        super().__init__(recorder)


@pytest.fixture
def bus(monkeypatch: pytest.MonkeyPatch) -> Generator[PodEventBus, None, None]:
    """Bus with no real reader — tests push events directly into subscriber
    queues via ``bus._dispatch`` after ``stream_ready`` is forced set."""
    b = PodEventBus(base_url="http://test.invalid:4096", auth=None)
    monkeypatch.setattr(b, "_ensure_reader_started", lambda: None)
    # The bus would normally set stream_ready inside its reader after
    # connecting. Force-set it here so send_message doesn't time out
    # waiting for a connection that's never going to happen in unit tests.
    b.stream_ready.set()
    try:
        yield b
    finally:
        b.close()


def _make_client(
    bus: PodEventBus,
    transport: httpx.BaseTransport,
    *,
    connect_timeout: float = 1.0,
) -> OpencodeServeClient:
    return OpencodeServeClient(
        base_url="http://test.invalid:4096",
        password=None,
        event_bus=bus,
        timeouts=ClientTimeouts(
            connect_timeout=connect_timeout,
            request_timeout=5.0,
            event_read_timeout=300.0,
        ),
        transport=transport,
    )


def _ok_response(_: httpx.Request) -> httpx.Response:
    """Default handler: every POST returns 204."""
    return httpx.Response(204)


# ---------------------------------------------------------------------------
# Helper: drive send_message in a thread, push events from the main thread
# ---------------------------------------------------------------------------


def _run_send_message(
    client: OpencodeServeClient,
    *,
    model_provider: str | None = None,
    model_id: str | None = None,
    timeout: float = 5.0,
) -> tuple[list[Any], threading.Thread]:
    """Start ``send_message`` on a background thread, returning the
    collected events list (populated as the generator yields)."""
    events: list[Any] = []

    def runner() -> None:
        for evt in client.send_message(
            _SESSION,
            "hello",
            directory=_DIRECTORY,
            model_provider=model_provider,
            model_id=model_id,
            timeout=timeout,
        ):
            events.append(evt)

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    return events, t


def _wait_for(predicate: Any, *, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _prompt_async_posted(transport: _RecordingTransport) -> bool:
    return any(
        request.url.path.endswith("/prompt_async") for request in transport.requests
    )


def _dispatch_session_idle(bus: PodEventBus, *, scoped: bool = True) -> None:
    properties = {"sessionID": _SESSION} if scoped else {}
    bus._dispatch({"type": "session.idle", "properties": properties})


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_send_message_yields_text_and_terminator(bus: PodEventBus) -> None:
    transport = _RecordingTransport(_ok_response)
    client = _make_client(bus, transport)
    events, t = _run_send_message(client)
    try:
        assert _wait_for(lambda: _prompt_async_posted(transport))
        # Set up: an assistant message arrives, then a text part with a delta,
        # then completion.
        bus._dispatch(
            {
                "type": "message.updated",
                "properties": {
                    "sessionID": _SESSION,
                    "info": {
                        "id": "msg1",
                        "sessionID": _SESSION,
                        "role": "assistant",
                        "time": {"completed": None},
                    },
                },
            }
        )
        bus._dispatch(
            {
                "type": "message.part.updated",
                "properties": {
                    "sessionID": _SESSION,
                    "part": {
                        "id": "p1",
                        "messageID": "msg1",
                        "sessionID": _SESSION,
                        "type": "text",
                        "text": "",
                        "state": {"status": "active"},
                    },
                },
            }
        )
        bus._dispatch(
            {
                "type": "message.part.delta",
                "properties": {
                    "sessionID": _SESSION,
                    "messageID": "msg1",
                    "partID": "p1",
                    "field": "text",
                    "delta": "hello",
                },
            }
        )
        bus._dispatch(
            {
                "type": "message.updated",
                "properties": {
                    "sessionID": _SESSION,
                    "info": {
                        "id": "msg1",
                        "sessionID": _SESSION,
                        "role": "assistant",
                        "time": {"completed": 1234567890},
                    },
                },
            }
        )
        _dispatch_session_idle(bus)
        assert _wait_for(lambda: any(isinstance(e, PromptResponse) for e in events))
    finally:
        t.join(timeout=3.0)

    # Yielded: AgentMessageChunk("hello"), PromptResponse
    chunks = [e for e in events if isinstance(e, AgentMessageChunk)]
    assert chunks, "expected at least one AgentMessageChunk"
    assert any(c.content.text == "hello" for c in chunks)
    assert any(isinstance(e, PromptResponse) for e in events)


def test_send_message_routes_reasoning_to_thought_chunks(bus: PodEventBus) -> None:
    transport = _RecordingTransport(_ok_response)
    client = _make_client(bus, transport)
    events, t = _run_send_message(client)
    try:
        assert _wait_for(lambda: _prompt_async_posted(transport))
        # Reasoning part arrives first to register its type, then a delta on
        # the same partID — translator emits AgentThoughtChunk for reasoning.
        bus._dispatch(
            {
                "type": "message.updated",
                "properties": {
                    "sessionID": _SESSION,
                    "info": {
                        "id": "msg1",
                        "sessionID": _SESSION,
                        "role": "assistant",
                        "time": {"completed": None},
                    },
                },
            }
        )
        bus._dispatch(
            {
                "type": "message.part.updated",
                "properties": {
                    "sessionID": _SESSION,
                    "part": {
                        "id": "p1",
                        "messageID": "msg1",
                        "sessionID": _SESSION,
                        "type": "reasoning",
                        "text": "",
                        "state": {"status": "active"},
                    },
                },
            }
        )
        bus._dispatch(
            {
                "type": "message.part.delta",
                "properties": {
                    "sessionID": _SESSION,
                    "messageID": "msg1",
                    "partID": "p1",
                    "field": "text",
                    "delta": "thinking…",
                },
            }
        )
        # Completion metadata arrives before the session-level terminator.
        bus._dispatch(
            {
                "type": "message.updated",
                "properties": {
                    "sessionID": _SESSION,
                    "info": {
                        "id": "msg1",
                        "sessionID": _SESSION,
                        "role": "assistant",
                        "time": {"completed": 1},
                    },
                },
            }
        )
        _dispatch_session_idle(bus)
        assert _wait_for(lambda: any(isinstance(e, PromptResponse) for e in events))
    finally:
        t.join(timeout=3.0)

    thoughts = [e for e in events if isinstance(e, AgentThoughtChunk)]
    assert thoughts, "reasoning delta must produce an AgentThoughtChunk"
    assert any(c.content.text == "thinking…" for c in thoughts)


# ---------------------------------------------------------------------------
# Per-prompt model override
# ---------------------------------------------------------------------------


def test_send_message_threads_model_override_into_prompt_async(
    bus: PodEventBus,
) -> None:
    """When ``model_provider`` and ``model_id`` are passed, they must end up
    in the ``POST /session/{id}/prompt_async`` body so opencode targets the
    right model. This is the fix for the ``opencode/big-pickle`` default
    bug — without this plumbing, opencode falls back to its built-in."""
    posted_bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/prompt_async"):
            posted_bodies.append(httpx.Response(200, content=request.content).json())
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    client = _make_client(bus, transport)
    events, t = _run_send_message(
        client, model_provider="anthropic", model_id="claude-opus-4-7"
    )
    try:
        assert _wait_for(lambda: len(posted_bodies) == 1)
        # Completion metadata arrives before the session-level terminator.
        bus._dispatch(
            {
                "type": "message.updated",
                "properties": {
                    "sessionID": _SESSION,
                    "info": {
                        "id": "msg1",
                        "sessionID": _SESSION,
                        "role": "assistant",
                        "time": {"completed": 1},
                    },
                },
            }
        )
        _dispatch_session_idle(bus)
        assert _wait_for(lambda: any(isinstance(e, PromptResponse) for e in events))
    finally:
        t.join(timeout=3.0)

    assert len(posted_bodies) == 1
    assert posted_bodies[0]["model"] == {
        "providerID": "anthropic",
        "modelID": "claude-opus-4-7",
    }
    assert posted_bodies[0]["parts"] == [{"type": "text", "text": "hello"}]


def test_send_message_omits_model_when_override_missing(bus: PodEventBus) -> None:
    """No model override → no ``model`` key in the body. opencode-serve
    falls back to its loaded config's default. This preserves the
    "session default from opencode.json" path for pre-migration sessions."""
    posted_bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/prompt_async"):
            posted_bodies.append(httpx.Response(200, content=request.content).json())
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    client = _make_client(bus, transport)
    events, t = _run_send_message(client)
    try:
        assert _wait_for(lambda: len(posted_bodies) == 1)
        bus._dispatch(
            {
                "type": "message.updated",
                "properties": {
                    "sessionID": _SESSION,
                    "info": {
                        "id": "msg1",
                        "sessionID": _SESSION,
                        "role": "assistant",
                        "time": {"completed": 1},
                    },
                },
            }
        )
        _dispatch_session_idle(bus)
        assert _wait_for(lambda: any(isinstance(e, PromptResponse) for e in events))
    finally:
        t.join(timeout=3.0)

    assert len(posted_bodies) == 1
    assert "model" not in posted_bodies[0]


def test_send_message_omits_model_when_only_one_arg_supplied(
    bus: PodEventBus,
) -> None:
    """Both ``model_provider`` and ``model_id`` must be present; either
    alone is dropped (defensive against partial wiring)."""
    posted_bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/prompt_async"):
            posted_bodies.append(httpx.Response(200, content=request.content).json())
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    client = _make_client(bus, transport)
    events, t = _run_send_message(client, model_provider="anthropic", model_id=None)
    try:
        assert _wait_for(lambda: len(posted_bodies) == 1)
        bus._dispatch(
            {
                "type": "message.updated",
                "properties": {
                    "sessionID": _SESSION,
                    "info": {
                        "id": "msg1",
                        "sessionID": _SESSION,
                        "role": "assistant",
                        "time": {"completed": 1},
                    },
                },
            }
        )
        _dispatch_session_idle(bus)
        assert _wait_for(lambda: any(isinstance(e, PromptResponse) for e in events))
    finally:
        t.join(timeout=3.0)

    assert "model" not in posted_bodies[0]


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_send_message_yields_error_on_prompt_async_http_error(
    bus: PodEventBus,
) -> None:
    """A 5xx from opencode on prompt_async must produce a single sandbox-event Error
    and clean shutdown — not a hang waiting for events that won't come."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/prompt_async"):
            return httpx.Response(500, content=b"opencode exploded")
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    client = _make_client(bus, transport)
    events: list[Any] = list(
        client.send_message(_SESSION, "hello", directory=_DIRECTORY, timeout=2.0)
    )
    assert len(events) == 1
    assert isinstance(events[0], Error)
    assert events[0].code == 500


def test_send_message_yields_error_on_prompt_async_connection_error(
    bus: PodEventBus,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    transport = httpx.MockTransport(handler)
    client = _make_client(bus, transport)
    events: list[Any] = list(
        client.send_message(_SESSION, "hi", directory=_DIRECTORY, timeout=2.0)
    )
    assert len(events) == 1
    assert isinstance(events[0], Error)
    assert events[0].code == -3
    assert "prompt_async failed" in events[0].message


def test_send_message_waits_for_event_bus_reconnect_before_prompt_async(
    bus: PodEventBus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the shared /event stream is reconnecting, the turn should wait
    instead of posting prompt_async and missing the first packets."""
    monkeypatch.setattr(bus, "_ensure_reader_started", lambda: None)
    bus.stream_ready.clear()

    transport = _RecordingTransport(_ok_response)
    client = _make_client(bus, transport, connect_timeout=0.05)
    events, t = _run_send_message(client, timeout=3.0)
    try:
        time.sleep(0.1)
        assert not any(
            request.url.path.endswith("/prompt_async") for request in transport.requests
        )

        bus.stream_ready.set()
        assert _wait_for(lambda: _prompt_async_posted(transport))

        _dispatch_session_idle(bus)
        assert _wait_for(lambda: any(isinstance(e, PromptResponse) for e in events))
    finally:
        t.join(timeout=3.0)


def test_send_message_errors_when_stream_ready_never_set(
    bus: PodEventBus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the bus never connects (stream_ready stays cleared), send_message
    surfaces an Error after the turn budget rather than blocking indefinitely
    on prompt_async."""
    monkeypatch.setattr(bus, "_ensure_reader_started", lambda: None)
    bus.stream_ready.clear()
    transport = _RecordingTransport(_ok_response)
    client = _make_client(bus, transport, connect_timeout=0.01)
    events = list(
        client.send_message(_SESSION, "hi", directory=_DIRECTORY, timeout=0.2)
    )
    assert len(events) == 1
    assert isinstance(events[0], Error)
    assert events[0].code == -3
    assert "did not become ready" in events[0].message
    assert not any(
        request.url.path.endswith("/prompt_async") for request in transport.requests
    )


def test_send_message_errors_when_bus_closes_before_terminator(
    bus: PodEventBus,
) -> None:
    """If the bus shuts down mid-turn (sandbox terminated), the subscriber
    receives a sentinel — send_message must surface that as an Error so
    the SSE consumer doesn't hang."""
    transport = httpx.MockTransport(_ok_response)
    client = _make_client(bus, transport)
    events, t = _run_send_message(client, timeout=3.0)
    try:
        # Close the bus while send_message is mid-drain.
        time.sleep(0.1)
        bus.close()
        assert _wait_for(lambda: any(isinstance(e, Error) for e in events))
    finally:
        t.join(timeout=3.0)
    errs = [e for e in events if isinstance(e, Error)]
    assert errs
    assert "event bus closed" in errs[0].message


def test_send_message_surfaces_unscoped_session_error_as_terminal(
    bus: PodEventBus,
) -> None:
    """Unscoped opencode session.error must end the turn immediately.

    Without bus fanout this event is dropped. Without treating Error as a
    local terminator, the Error is yielded but the generator keeps waiting for
    timeout and the UI sees keepalives after the real failure.
    """
    transport = httpx.MockTransport(_ok_response)
    client = _make_client(bus, transport)
    events, t = _run_send_message(client, timeout=5.0)
    try:
        bus._dispatch(
            {
                "type": "session.error",
                "properties": {
                    "error": {"data": {"message": "upstream connection reset"}}
                },
            }
        )
        assert _wait_for(lambda: not t.is_alive(), timeout=1.0)
    finally:
        t.join(timeout=3.0)

    errs = [e for e in events if isinstance(e, Error)]
    assert len(errs) == 1
    assert "upstream connection reset" in errs[0].message
    assert not any(isinstance(e, PromptResponse) for e in events)


def test_send_message_ends_on_unscoped_session_idle(bus: PodEventBus) -> None:
    """Unscoped session.idle is still a valid directory-scoped turn terminator."""
    transport = httpx.MockTransport(_ok_response)
    client = _make_client(bus, transport)
    events, t = _run_send_message(client, timeout=5.0)
    try:
        _dispatch_session_idle(bus, scoped=False)
        assert _wait_for(lambda: not t.is_alive(), timeout=1.0)
    finally:
        t.join(timeout=3.0)

    assert any(isinstance(e, PromptResponse) for e in events)
    assert not any(isinstance(e, Error) for e in events)


def test_send_message_wall_clock_timeout_aborts(bus: PodEventBus) -> None:
    """When the configured per-call timeout elapses with no terminator,
    the client posts ``/abort`` and yields a final Error."""
    aborts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/abort"):
            aborts.append(request.url.path)
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    client = _make_client(bus, transport)
    # Don't push any events — let the timeout elapse.
    events = list(
        client.send_message(_SESSION, "hi", directory=_DIRECTORY, timeout=0.3)
    )
    assert any(isinstance(e, Error) and e.code == -1 for e in events)
    assert any("/abort" in p for p in aborts)


def test_send_message_aborts_on_generator_exit(bus: PodEventBus) -> None:
    """Browser closes the SSE connection mid-turn → consumer GeneratorExits
    the generator → client posts ``/abort`` and re-raises.

    Drive the generator from the main thread only: dispatch an event so
    the first yield resolves, then ``gen.close()`` to trigger
    GeneratorExit. Mixing threads here trips Python's
    "generator already executing" guard.
    """
    aborts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/abort"):
            aborts.append(request.url.path)
        return httpx.Response(204)

    transport = _RecordingTransport(handler)
    client = _make_client(bus, transport)

    gen = client.send_message(_SESSION, "hi", directory=_DIRECTORY, timeout=5.0)

    def dispatch_first_chunk() -> None:
        assert _wait_for(lambda: _prompt_async_posted(transport))
        bus._dispatch(
            {
                "type": "message.updated",
                "properties": {
                    "sessionID": _SESSION,
                    "info": {
                        "id": "msg1",
                        "sessionID": _SESSION,
                        "role": "assistant",
                        "time": {"completed": None},
                    },
                },
            }
        )
        bus._dispatch(
            {
                "type": "message.part.updated",
                "properties": {
                    "sessionID": _SESSION,
                    "part": {
                        "id": "p1",
                        "messageID": "msg1",
                        "sessionID": _SESSION,
                        "type": "text",
                        "text": "partial",
                        "state": {"status": "active"},
                    },
                },
            }
        )

    threading.Thread(target=dispatch_first_chunk, daemon=True).start()
    assert isinstance(next(gen), AgentMessageChunk)
    # Close mid-stream: this raises GeneratorExit inside send_message's
    # try/except, which posts /abort and re-raises.
    gen.close()

    assert any("/abort" in p for p in aborts), "GeneratorExit must POST /abort"


# ---------------------------------------------------------------------------
# Permission auto-allow
# ---------------------------------------------------------------------------


def test_send_message_auto_allows_permission_asks(bus: PodEventBus) -> None:
    """Unexpected permission.asked events trigger an out-of-band POST to
    opencode's ``/permissions/{id}`` endpoint with ``{"response": "once"}``.
    This keeps the turn moving when opencode adds a new permission category
    we haven't pre-configured in opencode.json."""
    permission_posts: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "/permissions/" in request.url.path:
            permission_posts.append(
                {
                    "path": request.url.path,
                    "body": httpx.Response(200, content=request.content).json(),
                }
            )
        return httpx.Response(204)

    transport = _RecordingTransport(handler)
    client = _make_client(bus, transport)
    events, t = _run_send_message(client, timeout=3.0)
    try:
        assert _wait_for(lambda: _prompt_async_posted(transport))
        bus._dispatch(
            {
                "type": "permission.asked",
                "properties": {
                    "sessionID": _SESSION,
                    "id": "perm_42",
                    "permission": "bash",
                    "patterns": ["rm *"],
                },
            }
        )
        bus._dispatch(
            {
                "type": "message.updated",
                "properties": {
                    "sessionID": _SESSION,
                    "info": {
                        "id": "msg1",
                        "sessionID": _SESSION,
                        "role": "assistant",
                        "time": {"completed": 1},
                    },
                },
            }
        )
        _dispatch_session_idle(bus)
        assert _wait_for(lambda: any(isinstance(e, PromptResponse) for e in events))
    finally:
        t.join(timeout=3.0)

    assert len(permission_posts) == 1
    assert permission_posts[0]["path"].endswith(f"/{_SESSION}/permissions/perm_42")
    assert permission_posts[0]["body"] == {"response": "once"}


# ---------------------------------------------------------------------------
# Subscription discipline
# ---------------------------------------------------------------------------


def test_send_message_unsubscribes_on_clean_exit(bus: PodEventBus) -> None:
    """After send_message completes (terminator yielded), the subscriber
    queue must be removed from the bus — otherwise long-running pods leak
    a queue per session per call."""
    transport = httpx.MockTransport(_ok_response)
    client = _make_client(bus, transport)
    assert _SESSION not in bus._subscribers
    list(
        _gen_to_completion(
            client,
            terminator=lambda: _dispatch_session_idle(bus),
        )
    )
    # After clean exit, no subscription should remain.
    assert _SESSION not in bus._subscribers


def test_send_message_unsubscribes_on_http_error(bus: PodEventBus) -> None:
    """Subscription must be released even when send_message bails out
    early on prompt_async failure."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/prompt_async"):
            return httpx.Response(500)
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    client = _make_client(bus, transport)
    list(client.send_message(_SESSION, "hi", directory=_DIRECTORY, timeout=2.0))
    assert _SESSION not in bus._subscribers


def test_send_message_requires_event_bus() -> None:
    """Calling send_message without a bus raises immediately — guards
    against future refactors that forget to wire one up."""
    transport = httpx.MockTransport(_ok_response)
    client = OpencodeServeClient(
        base_url="http://test.invalid:4096",
        password=None,
        event_bus=None,
        transport=transport,
    )
    with pytest.raises(RuntimeError, match="requires event_bus"):
        list(client.send_message(_SESSION, "hi", directory=_DIRECTORY))


# ---------------------------------------------------------------------------
# Helper: drive send_message to terminator
# ---------------------------------------------------------------------------


def _gen_to_completion(
    client: OpencodeServeClient,
    terminator: Any,
    timeout: float = 3.0,
) -> Generator[Any, None, None]:
    """Run send_message, scheduling ``terminator()`` on a background thread
    after the generator starts so the test can yield + collect events."""
    started = threading.Event()

    def fire() -> None:
        started.wait(timeout)
        time.sleep(0.05)
        terminator()

    threading.Thread(target=fire, daemon=True).start()
    started.set()
    yield from client.send_message(
        _SESSION, "hi", directory=_DIRECTORY, timeout=timeout
    )
