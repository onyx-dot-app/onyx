import os
import sys

from fastmcp import FastMCP
from fastmcp.server.server import FunctionTool

mcp = FastMCP("My HTTP MCP")


@mcp.tool
def hello(name: str) -> str:
    """Say hi."""
    return f"Hello, {name}!"


def make_many_tools() -> list[FunctionTool]:
    def make_tool(i: int) -> FunctionTool:
        @mcp.tool(name=f"tool_{i}", description=f"Get secret value {i}")
        def tool_name(name: str) -> str:
            """Get secret value."""
            return f"Secret value {100 - i}!"

        return tool_name

    tools = []
    for i in range(100):
        tools.append(make_tool(i))
    return tools


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
