"""Focused test: OpencodeServeClient self-heals a 401 by reloading the password."""

from __future__ import annotations

import httpx

from onyx.server.features.build.sandbox.opencode.serve_client import OpencodeServeClient


def test_request_reloads_password_on_401_and_retries() -> None:
    calls: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers.get("authorization"))
        # First call (stale password) → 401; retry (fresh password) → 200.
        if len(calls) == 1:
            return httpx.Response(401)
        return httpx.Response(200, json={"id": "ses_new"})

    reloads: list[int] = []

    def reload_password() -> str:
        reloads.append(1)
        return "fresh-pw"

    client = OpencodeServeClient(
        base_url="http://test.invalid:4096",
        password="stale-pw",
        transport=httpx.MockTransport(handler),
        reload_password=reload_password,
    )
    sid = client.ensure_session(None, directory="/workspace/sessions/x")
    assert sid == "ses_new"
    assert len(calls) == 2, calls
    assert calls[0] != calls[1], "auth header should change after reload"
    assert len(reloads) == 1
    client.close()


def test_request_does_not_retry_when_password_unchanged() -> None:
    n = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal n
        n += 1
        return httpx.Response(401)

    client = OpencodeServeClient(
        base_url="http://test.invalid:4096",
        password="same",
        transport=httpx.MockTransport(handler),
        reload_password=lambda: "same",
    )
    # 401 with unchanged password → no retry, surfaces as HTTPStatusError.
    try:
        client.ensure_session(None, directory="/workspace/sessions/x")
        assert False, "expected HTTPStatusError"
    except httpx.HTTPStatusError:
        pass
    assert n == 1, n
    client.close()
