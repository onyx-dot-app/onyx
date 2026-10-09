"""Timeout behavior of the MCP server's HTTP calls to the API server.

Long-running tool calls (document search) must use the configurable
MCP_SERVER_API_REQUEST_TIMEOUT_SECONDS, while auth/metadata calls on the
shared client keep the short 60s default.
"""

import asyncio
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastmcp.server.auth.auth import AccessToken
from pydantic import BaseModel

import onyx.mcp_server.tools.search as search_module
from onyx.mcp_server.tools.search import _post_model
from onyx.mcp_server.utils import get_http_client, shutdown_http_client

_RESPONSE_DELAY_S = 2.0


class _EmptyBody(BaseModel):
    pass


async def _slow_handler(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    await reader.read(1024)
    await asyncio.sleep(_RESPONSE_DELAY_S)
    writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
    await writer.drain()
    writer.close()


@pytest_asyncio.fixture
async def slow_server_url() -> AsyncGenerator[str, None]:
    server = await asyncio.start_server(_slow_handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}/search"
    server.close()
    await server.wait_closed()


@pytest_asyncio.fixture
async def fresh_client() -> AsyncGenerator[None, None]:
    await shutdown_http_client()
    yield
    await shutdown_http_client()


_TOKEN = AccessToken(token="test-token", client_id="test", scopes=[])


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_client")
async def test_tool_call_times_out_at_configured_value(
    slow_server_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(search_module, "MCP_SERVER_API_REQUEST_TIMEOUT_SECONDS", 1)
    with pytest.raises(httpx.ReadTimeout):
        await _post_model(slow_server_url, _EmptyBody(), _TOKEN)


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_client")
async def test_tool_call_succeeds_within_configured_value(
    slow_server_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(search_module, "MCP_SERVER_API_REQUEST_TIMEOUT_SECONDS", 10)
    response = await _post_model(slow_server_url, _EmptyBody(), _TOKEN)
    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_client")
async def test_shared_client_keeps_short_default_for_non_tool_calls() -> None:
    assert get_http_client().timeout == httpx.Timeout(60.0)
