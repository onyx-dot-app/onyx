import sys

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
from fastmcp.server.server import FunctionTool


def make_many_tools(mcp: FastMCP) -> list[FunctionTool]:
    def make_tool(i: int) -> FunctionTool:
        @mcp.tool(name=f"tool_{i}", description=f"Get secret value {i}")
        def tool_name(name: str) -> str:
            """Get secret value."""
            return f"Secret value {200 - i}!"

        return tool_name

    tools = []
    for i in range(100):
        tools.append(make_tool(i))
    return tools


if __name__ == "__main__":
    # Streamable HTTP transport (recommended)
    # Accept only these tokens (treat them like API keys) and require a scope
    if len(sys.argv) > 1:
        api_key = sys.argv[1]
    else:
        api_key = "dev-api-key-123"
    auth = StaticTokenVerifier(
        tokens={
            api_key: {"client_id": "evan", "scopes": ["mcp:use"]},
        },
        required_scopes=["mcp:use"],
    )

    mcp = FastMCP("My HTTP MCP", auth=auth)
    make_many_tools(mcp)
    mcp.run(transport="http", host="127.0.0.1", port=8001, path="/mcp")
