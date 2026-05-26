"""Unit tests for :meth:`OpencodeServeClient.ensure_session`.

The persistence story for ``BuildSession.opencode_session_id`` rests on
two invariants:

1. When given a valid id, ``ensure_session`` MUST do a single ``GET
   /session/{id}`` and return the same id — no ``POST /session``.
   Otherwise every turn would mint a fresh opencode session and orphan
   conversation history.

2. When given a stale id (404 from GET), ``ensure_session`` MUST fall
   through to ``POST /session`` and return the new id. The caller
   (``_send_message_via_serve``) compares this to the input and fires the
   ``on_opencode_session_resolved`` callback so the session manager can
   rewrite the DB row.

The lower-level callback wiring (transport → session_manager →
``BuildSession.opencode_session_id``) is exercised end-to-end in
external-dependency / integration tests; these unit tests lock the
HTTP-level contract so the higher-level test surface stays small.
"""

from __future__ import annotations

from typing import Any

import httpx

from onyx.server.features.build.sandbox.opencode.serve_client import ClientTimeouts
from onyx.server.features.build.sandbox.opencode.serve_client import OpencodeServeClient

_STALE_ID = "ses_stale_old_id_001"
_FRESH_ID = "ses_fresh_new_id_002"
_CWD = "/workspace/sessions/abc-def"


class _RecordingTransport(httpx.MockTransport):
    """MockTransport that records every request so tests can assert call
    counts and ordering — same pattern as test_send_message_with_bus.py."""

    def __init__(self, handler: Any) -> None:
        self.requests: list[httpx.Request] = []

        def recorder(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        super().__init__(recorder)


def _make_client(transport: httpx.BaseTransport) -> OpencodeServeClient:
    return OpencodeServeClient(
        base_url="http://test.invalid:4096",
        password=None,
        event_bus=None,  # ensure_session is unary — no bus needed
        timeouts=ClientTimeouts(
            connect_timeout=1.0, request_timeout=5.0, event_read_timeout=300.0
        ),
        transport=transport,
    )


def test_ensure_session_reuses_valid_id_with_single_get() -> None:
    """The load-bearing happy path: persisted id is still valid → one GET,
    no POST, same id returned. This is the path that should fire on every
    turn after the first."""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == f"/session/{_STALE_ID}":
            return httpx.Response(200, json={"id": _STALE_ID})
        raise AssertionError(f"unexpected request {req.method} {req.url.path}")

    transport = _RecordingTransport(handler)
    client = _make_client(transport)

    resolved = client.ensure_session(_STALE_ID, cwd=_CWD)

    assert resolved == _STALE_ID
    assert len(transport.requests) == 1
    assert transport.requests[0].method == "GET"
    assert transport.requests[0].url.path == f"/session/{_STALE_ID}"


def test_ensure_session_creates_when_id_404s() -> None:
    """Stale id (pod restart / eviction): GET 404 → POST /session →
    return the freshly-minted id. This is the path the callback wiring
    depends on — the returned id MUST differ from the input so
    _send_message_via_serve fires ``on_opencode_session_resolved``."""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == f"/session/{_STALE_ID}":
            return httpx.Response(404, json={"error": "not found"})
        if req.method == "POST" and req.url.path == "/session":
            return httpx.Response(200, json={"id": _FRESH_ID})
        raise AssertionError(f"unexpected request {req.method} {req.url.path}")

    transport = _RecordingTransport(handler)
    client = _make_client(transport)

    resolved = client.ensure_session(_STALE_ID, cwd=_CWD, title="build-session-abc")

    assert resolved == _FRESH_ID
    assert resolved != _STALE_ID  # MUST differ → triggers callback at caller
    assert len(transport.requests) == 2
    assert transport.requests[0].method == "GET"
    assert transport.requests[0].url.path == f"/session/{_STALE_ID}"
    assert transport.requests[1].method == "POST"
    assert transport.requests[1].url.path == "/session"


def test_ensure_session_creates_when_no_id_supplied() -> None:
    """None caller-supplied id (preflight on a brand-new BuildSession):
    skip the lookup, go straight to POST."""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and req.url.path == "/session":
            return httpx.Response(200, json={"id": _FRESH_ID})
        raise AssertionError(f"unexpected request {req.method} {req.url.path}")

    transport = _RecordingTransport(handler)
    client = _make_client(transport)

    resolved = client.ensure_session(None, cwd=_CWD)

    assert resolved == _FRESH_ID
    assert len(transport.requests) == 1
    assert transport.requests[0].method == "POST"
    assert transport.requests[0].url.path == "/session"


def test_ensure_session_raises_on_5xx_lookup() -> None:
    """Non-404 errors during GET (500, network) must NOT silently fall
    through to POST — that would mask outages and create accidental
    sessions. ``_raise_for_status`` should fire."""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == f"/session/{_STALE_ID}":
            return httpx.Response(500, json={"error": "internal"})
        raise AssertionError(f"unexpected request {req.method} {req.url.path}")

    transport = _RecordingTransport(handler)
    client = _make_client(transport)

    try:
        client.ensure_session(_STALE_ID, cwd=_CWD)
    except httpx.HTTPStatusError as e:
        assert e.response.status_code == 500
        # Exactly one request: we did NOT fall through to POST.
        assert len(transport.requests) == 1
        return
    raise AssertionError("expected HTTPStatusError for 500 lookup")


def test_ensure_session_callback_contract_triggers_on_id_mismatch() -> None:
    """Simulates the ``_send_message_via_serve`` contract: caller invokes
    ensure_session, then compares input vs. result; if they differ, fires
    the persistence callback. Locks the "id mismatch → callback fires"
    invariant at the unit level so the session-manager DB write path is
    guaranteed reachable from any future caller."""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == f"/session/{_STALE_ID}":
            return httpx.Response(404)
        if req.method == "POST" and req.url.path == "/session":
            return httpx.Response(200, json={"id": _FRESH_ID})
        raise AssertionError(f"unexpected {req.method} {req.url.path}")

    transport = _RecordingTransport(handler)
    client = _make_client(transport)

    persisted_ids: list[str] = []

    def on_resolved(new_id: str) -> None:
        persisted_ids.append(new_id)

    # Mirror _send_message_via_serve's logic.
    resolved = client.ensure_session(_STALE_ID, cwd=_CWD)
    if resolved != _STALE_ID:
        on_resolved(resolved)

    assert persisted_ids == [_FRESH_ID], (
        "callback must fire exactly once with the new id when stale"
    )


def test_ensure_session_callback_does_not_fire_on_valid_id() -> None:
    """Counterpart to the above: when the persisted id is still valid,
    the callback MUST NOT fire — otherwise we'd do a redundant DB write
    on every turn after the first."""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == f"/session/{_STALE_ID}":
            return httpx.Response(200, json={"id": _STALE_ID})
        raise AssertionError(f"unexpected {req.method} {req.url.path}")

    transport = _RecordingTransport(handler)
    client = _make_client(transport)

    persisted_ids: list[str] = []

    def on_resolved(new_id: str) -> None:
        persisted_ids.append(new_id)

    resolved = client.ensure_session(_STALE_ID, cwd=_CWD)
    if resolved != _STALE_ID:
        on_resolved(resolved)

    assert persisted_ids == [], (
        "callback must NOT fire on the happy path (persisted id still valid)"
    )
