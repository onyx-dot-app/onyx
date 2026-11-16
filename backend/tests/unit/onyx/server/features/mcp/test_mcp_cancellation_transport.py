"""Cancellation closes real MCP sessions and both supported HTTP transports."""

import asyncio
import threading
import time

import httpx
import pytest
import uvicorn
from fastmcp import FastMCP
from mcp.shared._httpx_utils import create_mcp_http_client

from onyx.db.enums import MCPTransport
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.server.features.mcp import client


@pytest.mark.parametrize("transport", [MCPTransport.SSE, MCPTransport.STREAMABLE_HTTP])
def test_cancellation_closes_real_transport(transport: MCPTransport) -> None:
    mcp = FastMCP("cancellation-test")
    started = threading.Event()
    release = threading.Event()
    cancellation = CancellationSignal()
    clients: list[httpx.AsyncClient] = []

    @mcp.tool
    async def slow_call() -> str:
        """Wait until the test releases the remote operation."""
        started.set()
        await asyncio.to_thread(release.wait, 10)
        return "finished"

    app = mcp.http_app(transport="sse" if transport == MCPTransport.SSE else "http")
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_config=None)
    )
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    def make_client(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        # Only this local test bypasses the production SSRF transport.
        connection = create_mcp_http_client(headers, timeout, auth)
        clients.append(connection)
        return connection

    def stop_running_request() -> None:
        if started.wait(10):
            cancellation.cancel()

    stopper = threading.Thread(target=stop_running_request, daemon=True)
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            assert time.monotonic() < deadline, "MCP server did not start"
            time.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        path = "/sse" if transport == MCPTransport.SSE else "/mcp"
        stopper.start()
        call_started = time.monotonic()
        with pytest.raises(AgentCancelled):
            client._call_mcp_client_function_sync(
                client._call_mcp_tool("slow_call", {}),
                f"http://127.0.0.1:{port}{path}",
                transport=transport,
                cancellation=cancellation,
                httpx_client_factory=make_client,
            )
        assert time.monotonic() - call_started < 5
        assert started.is_set()
        assert clients and all(connection.is_closed for connection in clients)
        assert not cancellation._callbacks
    finally:
        release.set()
        cancellation.cancel()
        if stopper.ident is not None:
            stopper.join(10)
        server.should_exit = True
        server_thread.join(10)
        assert not server_thread.is_alive()
