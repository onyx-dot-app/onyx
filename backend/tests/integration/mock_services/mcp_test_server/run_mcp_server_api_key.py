import sys

import uvicorn
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
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
    # Accept only these tokens (treat them like API keys) and require a scope
    if len(sys.argv) > 1:
        api_key = sys.argv[1]
    else:
        api_key = "dev-api-key-123"

    if len(sys.argv) > 2:
        port = int(sys.argv[2])
    else:
        port = 8001

    auth = StaticTokenVerifier(
        tokens={
            api_key: {"client_id": "evan", "scopes": ["mcp:use"]},
        },
        required_scopes=["mcp:use"],
    )

    # Create FastMCP instance - it will handle /mcp path internally
    mcp = FastMCP("My HTTP MCP", auth=auth)
    make_many_tools(mcp)

    # Get the MCP HTTP app (configured to serve at /mcp)
    mcp_app = mcp.http_app()

    # Create wrapper FastAPI app with the MCP app's lifespan
    app = FastAPI(title="MCP API Key Test Server", lifespan=mcp_app.lifespan)

    # Health check (unprotected)
    @app.get("/healthz")
    def health() -> PlainTextResponse:
        return PlainTextResponse("ok")

    # Mount MCP app at root - it handles /mcp internally
    app.mount("/", mcp_app)

    # Run the server
    uvicorn.run(app, host="0.0.0.0", port=port)
