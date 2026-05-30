"""Tests for the cold-pod retry in :meth:`OpencodeServeClient.ensure_session`.

Empirical finding from E2E chaos testing (2026-05-23): freshly recreated
sandbox pods can be K8s-Ready (2/2) for a few hundred ms before
opencode-serve has actually bound to :4096. The first HTTP request hits a
half-open TCP connection and raises ``httpx.RemoteProtocolError`` ("server
disconnected without sending a response") or ``httpx.ConnectError``
(connection refused). The previous implementation only handled 404 →
mint; transient connection errors propagated up and broke the turn,
forcing a manual ``/restore`` to recover.

These tests lock the new bounded-retry behavior: 3 retries with linear
backoff, only on connection-level errors, never on HTTP error responses.
"""

from __future__ import annotations

from typing import Any

import httpx

from onyx.server.features.build.sandbox.opencode.serve_client import ClientTimeouts
from onyx.server.features.build.sandbox.opencode.serve_client import OpencodeServeClient

_STALE_ID = "ses_stale_001"
_FRESH_ID = "ses_fresh_002"
_CWD = "/workspace/sessions/abc"


class _RecordingTransport(httpx.MockTransport):
    def __init__(self, handler: Any) -> None:
        self.requests: list[httpx.Request] = []

        def recorder(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        super().__init__(recorder)


def _make_client(
    transport: httpx.BaseTransport, *, retries: int = 3, base_delay: float = 0.0
) -> OpencodeServeClient:
    client = OpencodeServeClient(
        base_url="http://test.invalid:4096",
        password=None,
        event_bus=None,
        timeouts=ClientTimeouts(
            connect_timeout=1.0, request_timeout=5.0, event_read_timeout=300.0
        ),
        transport=transport,
    )
    # Shrink the retry delay to 0 in tests — we're not testing the sleep,
    # we're testing the retry count.
    client._COLD_POD_RETRIES = retries  # type: ignore[misc]
    client._COLD_POD_BASE_DELAY = base_delay  # type: ignore[misc]
    return client


def test_ensure_session_retries_remoteprotocol_then_succeeds() -> None:
    """Cold-pod path: first GET raises RemoteProtocolError, second
    succeeds. ensure_session returns the original id and records exactly
    two requests."""
    call_count = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.RemoteProtocolError("Server disconnected", request=req)
        return httpx.Response(200, json={"id": _STALE_ID})

    transport = _RecordingTransport(handler)
    client = _make_client(transport)

    resolved = client.ensure_session(_STALE_ID, directory=_CWD)
    assert resolved == _STALE_ID
    assert call_count["n"] == 2


def test_ensure_session_retries_connecterror() -> None:
    """ConnectError (TCP-level connect refused) should also be retried —
    the half-open-port window can fail at either layer depending on what
    state the pod is in."""
    call_count = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.ConnectError("Connection refused", request=req)
        return httpx.Response(200, json={"id": _STALE_ID})

    transport = _RecordingTransport(handler)
    client = _make_client(transport)

    resolved = client.ensure_session(_STALE_ID, directory=_CWD)
    assert resolved == _STALE_ID
    assert call_count["n"] == 2


def test_ensure_session_exhausts_retries_and_raises() -> None:
    """If the connection error persists past the retry budget, the
    original exception must bubble up — we MUST NOT silently fall through
    to POST /session and mint a duplicate."""
    call_count = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        raise httpx.RemoteProtocolError("Server disconnected", request=req)

    transport = _RecordingTransport(handler)
    client = _make_client(transport, retries=2)  # 2 retries → 3 total attempts

    try:
        client.ensure_session(_STALE_ID, directory=_CWD)
    except httpx.RemoteProtocolError:
        assert call_count["n"] == 3  # initial + 2 retries
        # Crucially: no POST /session ever fired.
        assert all(req.method != "POST" for req in transport.requests) or (
            len(transport.requests) == 3
        )
        return
    raise AssertionError("expected RemoteProtocolError to propagate")


def test_ensure_session_does_not_retry_on_http_error() -> None:
    """HTTP error responses (4xx/5xx) are application signals — they must
    NOT trigger the cold-pod retry, which is reserved for connection-
    level transients."""
    call_count = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(500, json={"error": "internal"})

    transport = _RecordingTransport(handler)
    client = _make_client(transport)

    try:
        client.ensure_session(_STALE_ID, directory=_CWD)
    except httpx.HTTPStatusError as e:
        assert e.response.status_code == 500
        assert call_count["n"] == 1  # NO retries on 5xx
        return
    raise AssertionError("expected HTTPStatusError")


def test_ensure_session_retries_post_on_connecterror() -> None:
    """When the caller passes opencode_session_id=None, the create POST
    is retryable on ConnectError specifically — TCP-refused proves the
    server never saw the request, so retrying it cannot create duplicate
    state."""
    call_count = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if req.method == "POST" and req.url.path == "/session":
            if call_count["n"] == 1:
                raise httpx.ConnectError("Connection refused", request=req)
            return httpx.Response(200, json={"id": _FRESH_ID})
        raise AssertionError(f"unexpected {req.method} {req.url.path}")

    transport = _RecordingTransport(handler)
    client = _make_client(transport)

    resolved = client.ensure_session(None, directory=_CWD)
    assert resolved == _FRESH_ID
    assert call_count["n"] == 2


def test_ensure_session_does_not_retry_post_on_remoteprotocolerror() -> None:
    """POST /session is non-idempotent. RemoteProtocolError means the
    server may have processed the request before the connection died —
    retrying would create a duplicate opencode session and orphan the
    first. The exception MUST propagate so the caller can surface the
    failure rather than silently leaking sessions."""
    call_count = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if req.method == "POST" and req.url.path == "/session":
            raise httpx.RemoteProtocolError("Server disconnected", request=req)
        raise AssertionError(f"unexpected {req.method} {req.url.path}")

    transport = _RecordingTransport(handler)
    client = _make_client(transport)

    try:
        client.ensure_session(None, directory=_CWD)
    except httpx.RemoteProtocolError:
        assert call_count["n"] == 1, (
            "POST /session must NOT retry on RemoteProtocolError"
        )
        return
    raise AssertionError("expected RemoteProtocolError to propagate, not retry")
