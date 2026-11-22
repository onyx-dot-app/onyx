import asyncio
import json
import os
import sys

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

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


# A held call fails after this time if the test never releases it.
HOLD_SECONDS = 60
_releases: dict[str, asyncio.Event] = {}


@mcp.tool
async def hold(key: str) -> str:
    """Answer once the test releases `key` (POST /release/{key}), for tests of
    calls that run beside a waiting one."""
    try:
        await asyncio.wait_for(
            _releases.setdefault(key, asyncio.Event()).wait(), HOLD_SECONDS
        )
    except TimeoutError as error:
        raise ToolError(f"The test did not let hold {key} answer in time") from error
    return "released"


@mcp.custom_route("/release/{key}", methods=["POST"])
async def release(request: Request) -> Response:
    _releases.setdefault(request.path_params["key"], asyncio.Event()).set()
    return PlainTextResponse("released")


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
