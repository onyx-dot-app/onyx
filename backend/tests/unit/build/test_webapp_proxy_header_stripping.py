"""The webapp proxy must strip Set-Cookie from upstream responses."""

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


def _make_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "query_string": b"",
            "headers": [],
        }
    )


async def _no_bytes(chunk_size: int = 8192) -> AsyncGenerator[bytes, None]:  # noqa: ARG001
    return
    yield b""  # pragma: no cover


def test_proxy_strips_set_cookie_keeps_other_headers() -> None:
    upstream = MagicMock(spec=httpx.Response)
    upstream.status_code = 200
    upstream.headers = httpx.Headers(
        {
            "content-type": "text/html",
            "set-cookie": "sid=leak; Path=/",
            "x-upstream": "kept",
        }
    )
    upstream.aiter_bytes = _no_bytes
    upstream.aclose = AsyncMock()

    client = MagicMock()
    client.build_request = MagicMock()
    client.send = AsyncMock(return_value=upstream)

    with (
        patch.object(
            webapp_proxy,
            "_get_sandbox_url",
            AsyncMock(return_value="http://sandbox-x:3000"),
        ),
        patch.object(webapp_proxy, "_get_proxy_client", return_value=client),
    ):
        response: Response = asyncio.run(
            webapp_proxy._proxy_request("", _make_request(), uuid4())
        )

    header_names = {name.lower() for name in response.headers}
    assert "set-cookie" not in header_names
    assert response.headers.get("x-upstream") == "kept"
