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

    port = int(sys.argv[1] if len(sys.argv) > 1 else "8000")
    # Streamable HTTP transport (recommended)
    make_many_tools()
    host = os.getenv("MCP_SERVER_BIND_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_SERVER_PORT", port))
    path = os.getenv("MCP_SERVER_PATH", "/mcp")
    mcp.run(transport="http", host=host, port=port, path=path)
