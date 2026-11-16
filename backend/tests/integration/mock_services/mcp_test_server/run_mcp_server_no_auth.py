import asyncio
import json
import os
import sys

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers

mcp = FastMCP("My HTTP MCP")


@mcp.tool
def hello(name: str) -> str:
    """Say hi."""
    return f"Hello, {name}!"


@mcp.tool
def get_ticket(ticket_id: int) -> str:
    """Get a ticket. Returns JSON text, as many MCP servers do."""
    return json.dumps(
        {"id": ticket_id, "title": 'Fix the "widget" parser', "labels": ["bug"]}
    )


@mcp.tool
def echo_header(header: str) -> str:
    """Return the value of a request header, for tests of pass-through headers."""
    return f"{header}={get_http_headers().get(header.lower(), '')}"


@mcp.tool
async def slow(seconds: float) -> str:
    """Answer after a delay, for tests of calls that run beside a waiting one."""
    await asyncio.sleep(seconds)
    return "slept"


def make_many_tools() -> None:
    def make_tool(i: int) -> None:
        @mcp.tool(name=f"tool_{i}", description=f"Get secret value {i}")
        def tool_name(name: str) -> str:  # noqa: ARG001
            """Get secret value."""
            return f"Secret value {100 - i}!"

    for i in range(100):
        make_tool(i)


if __name__ == "__main__":
    # Get port from command-line argument first (passed by test)
    port_from_arg = int(sys.argv[1]) if len(sys.argv) > 1 else None
    # Streamable HTTP transport (recommended)
    make_many_tools()
    host = os.getenv("MCP_SERVER_BIND_HOST", "0.0.0.0")
    # Use MOCK_MCP_SERVER_PORT to avoid conflicts with the real Onyx MCP server port (8090)
    # Priority: command-line arg > MOCK_MCP_SERVER_PORT > MCP_SERVER_PORT > default 8000
    if port_from_arg is not None:
        port = port_from_arg
    else:
        port = int(
            os.getenv("MOCK_MCP_SERVER_PORT") or os.getenv("MCP_SERVER_PORT") or "8000"
        )
    path = os.getenv("MCP_SERVER_PATH", "/mcp")
    mcp.run(transport="http", host=host, port=port, path=path)
