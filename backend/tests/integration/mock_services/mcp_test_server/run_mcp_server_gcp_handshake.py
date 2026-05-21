#!/usr/bin/env python3
"""GCP Logging-like MCP mock: handshake RPCs work without auth; tool calls require Bearer.

Simulates servers that return 403 on tools/call without credentials while still
exposing OAuth protected-resource metadata for proactive Onyx connect.

Requires mock_oauth_idp.py on port 8765.

Usage:
  python mock_oauth_idp.py
  python run_mcp_server_gcp_handshake.py [port]   # default 8013
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Awaitable
from collections.abc import Callable
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

import uvicorn
from dev_oauth_constants import DEV_OAUTH_ISSUER as _DEFAULT_OAUTH_ISSUER
from dev_oauth_constants import DEV_OAUTH_SCOPE
from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.responses import PlainTextResponse
from fastapi.responses import Response
from fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import Message

# Tests may override the IdP base URL when binding dynamic ports.
DEV_OAUTH_ISSUER = os.getenv("DEV_OAUTH_ISSUER", _DEFAULT_OAUTH_ISSUER)

MCP_METHODS_PUBLIC = frozenset({"initialize", "tools/list", "notifications/initialized"})


def _metadata_url_for_resource(resource_url: str) -> str:
    u = urlsplit(resource_url)
    path = u.path.lstrip("/")
    suffix = "/.well-known/oauth-protected-resource"
    if path:
        suffix += f"/{path}"
    return urlunsplit((u.scheme, u.netloc, suffix, "", ""))


def make_tools(mcp: FastMCP) -> None:
    @mcp.tool(name="echo", description="Echo input back")
    def echo(message: str) -> str:
        return f"echo: {message}"

    @mcp.tool(name="list_log_entries", description="Fake log query for GCP parity testing")
    def list_log_entries(project_id: str, filter: str = "") -> dict[str, str]:
        return {
            "project_id": project_id,
            "filter": filter,
            "summary": "mock log entries (dev server)",
        }


class GcpHandshakeAuthMiddleware(BaseHTTPMiddleware):
    """Allow initialize/tools/list without auth; require Bearer on tools/call."""

    def __init__(self, app: FastAPI, *, resource_metadata_url: str) -> None:
        super().__init__(app)
        self._resource_metadata_url = resource_metadata_url

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method != "POST" or not request.url.path.startswith("/mcp"):
            return await call_next(request)

        body = await request.body()
        method: str | None = None
        if body:
            try:
                payload = json.loads(body)
                if isinstance(payload, dict):
                    method = payload.get("method")
            except json.JSONDecodeError:
                method = None

        if method not in MCP_METHODS_PUBLIC and not request.headers.get("Authorization"):
            challenge = (
                f'Bearer resource_metadata="{self._resource_metadata_url}", '
                'error="insufficient_scope", error_description="Authentication required"'
            )
            return JSONResponse(
                status_code=403,
                content={
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32001,
                        "message": "Forbidden: Bearer token required for tool calls",
                    },
                    "id": None,
                },
                headers={"WWW-Authenticate": challenge},
            )

        async def receive() -> Message:
            return {"type": "http.request", "body": body, "more_body": False}

        replay = Request(request.scope, receive)
        return await call_next(replay)


def create_app(*, port: int, bind_host: str = "127.0.0.1") -> FastAPI:
    mcp = FastMCP("GCP-handshake MCP mock")
    make_tools(mcp)
    mcp_app = mcp.http_app()
    app = FastAPI(title="GCP-handshake MCP mock", lifespan=mcp_app.lifespan)

    resource_url = f"http://{bind_host}:{port}/mcp/"
    prm_url = _metadata_url_for_resource(resource_url)

    @app.get("/.well-known/oauth-protected-resource")
    @app.get("/.well-known/oauth-protected-resource/{_suffix:path}")
    def oauth_protected_resource(_suffix: str = "") -> JSONResponse:
        return JSONResponse(
            {
                "resource": resource_url,
                "authorization_servers": [DEV_OAUTH_ISSUER],
                "bearer_methods_supported": ["header"],
                "scopes_supported": [DEV_OAUTH_SCOPE],
            }
        )

    @app.get("/healthz")
    def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    app.add_middleware(
        GcpHandshakeAuthMiddleware,
        resource_metadata_url=prm_url,
    )
    app.mount("/", mcp_app)
    return app


def main() -> None:
    port = int(sys.argv[1] if len(sys.argv) > 1 else "8013")
    host = os.getenv("MCP_SERVER_HOST", "127.0.0.1")
    app = create_app(port=port, bind_host=host)
    print(f"GCP-handshake MCP mock on http://{host}:{port}/mcp")
    print(f"  PRM: {_metadata_url_for_resource(f'http://{host}:{port}/mcp/')}")
    print(f"  IdP: {DEV_OAUTH_ISSUER} (start mock_oauth_idp.py)")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
