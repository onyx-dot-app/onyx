"""The webapp proxy must strip Set-Cookie from upstream responses and
browser-context headers (Origin, sec-fetch-*) from forwarded requests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import httpx
from starlette.requests import Request
from starlette.responses import Response

from onyx.server.features.build import webapp_proxy


def _make_request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "query_string": b"",
            "headers": headers or [],
        }
    )


async def _no_bytes(chunk_size: int = 8192) -> AsyncGenerator[bytes, None]:  # noqa: ARG001
    return
    yield b""  # pragma: no cover


def _make_upstream() -> MagicMock:
    upstream = MagicMock(spec=httpx.Response)
    upstream.status_code = 200
    upstream.headers = httpx.Headers({"content-type": "text/html"})
    upstream.aiter_bytes = _no_bytes
    upstream.aclose = AsyncMock()
    return upstream


def _run_proxy_request(request: Request, client: MagicMock) -> Response:
    with (
        patch.object(
            webapp_proxy,
            "_get_sandbox_url",
            AsyncMock(return_value="http://sandbox-x:3000"),
        ),
        patch.object(webapp_proxy, "_get_proxy_client", return_value=client),
    ):
        return asyncio.run(webapp_proxy._proxy_request("", request, uuid4()))


def test_proxy_strips_set_cookie_keeps_other_headers() -> None:
    upstream = _make_upstream()
    upstream.headers = httpx.Headers(
        {
            "content-type": "text/html",
            "set-cookie": "sid=leak; Path=/",
            "x-upstream": "kept",
        }
    )

    client = MagicMock()
    client.build_request = MagicMock()
    client.send = AsyncMock(return_value=upstream)

    response = _run_proxy_request(_make_request(), client)

    header_names = {name.lower() for name in response.headers}
    assert "set-cookie" not in header_names
    assert response.headers.get("x-upstream") == "kept"


def test_proxy_strips_browser_context_request_headers() -> None:
    """Origin/sec-fetch-* must not reach the sandbox dev server — Next dev
    blocks /_next/* requests whose Origin isn't allowlisted."""
    client = MagicMock()
    client.build_request = MagicMock()
    client.send = AsyncMock(return_value=_make_upstream())

    request = _make_request(
        headers=[
            (b"origin", b"https://cloud.onyx.app"),
            (b"sec-fetch-mode", b"cors"),
            (b"sec-fetch-site", b"same-origin"),
            (b"sec-fetch-dest", b"empty"),
            (b"cookie", b"fastapiusersauth=secret"),
            (b"accept", b"text/html"),
            (b"user-agent", b"test-agent"),
        ]
    )
    _run_proxy_request(request, client)

    forwarded = client.build_request.call_args.kwargs["headers"]
    forwarded_names = {name.lower() for name in forwarded}
    assert "origin" not in forwarded_names
    assert not any(name.startswith("sec-fetch-") for name in forwarded_names)
    assert "cookie" not in forwarded_names
    assert forwarded_names >= {"accept", "user-agent"}
