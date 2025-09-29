import os
from collections.abc import Awaitable
from collections.abc import Callable
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

import uvicorn
from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.responses import PlainTextResponse
from fastapi.responses import Response
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.server import FunctionTool
from starlette.middleware.base import BaseHTTPMiddleware

# uncomment for debug logs
# logging.basicConfig(level=logging.DEBUG)

"""
Setup Okta:
1. Create an authorization Server (Admin Console → Security →
API → Authorization Servers), and get the Issuer, JWKS uri,
audience (i.e. api://mcp). Add the mcp:use scope.
Grant types should be Authorization Code and Refresh Token.
policy should allow your client (or All Clients) to grant oidc default scopes + mcp:use
WARNING: due to the order of discovery urls, you actually need to use the default authorization server
until Okta updates where their discovery urls are or the client library stops trying
to go to <base_url>/.well-known/oauth-authorization-server before trying the fallback

2. Create a client (Admin Console → Applications → Create App Integration)
Enable authorization code and store the client id and secret.
"""


def make_many_tools(mcp: FastMCP) -> list[FunctionTool]:
    def make_tool(i: int) -> FunctionTool:
        @mcp.tool(name=f"tool_{i}", description=f"Get secret value {i}")
        def tool_name(name: str) -> str:
            """Get secret value."""
            return f"Secret value {500 - i}!"

        return tool_name

    tools = []
    for i in range(100):
        tools.append(make_tool(i))

    @mcp.tool
    async def whoami() -> dict[str, Any]:
        tok = get_access_token()  # None if unauthenticated
        return {
            "client_id": tok.client_id if tok else None,
            "scopes": tok.scopes if tok else [],
            "claims": tok.claims if tok else {},
        }

    tools.append(whoami)
    return tools


# ---------- FASTAPI APP ----------


def init_app(
    app: FastAPI,
    mcp_resource_url: str,
    authorization_servers: list[str],
    scopes_supported: list[str],
) -> None:
    # 1) Protected Resource Metadata (RFC 9728) at well-known URL.
    #    We accept both with and without the trailing resource suffix to be lenient in dev.
    @app.get("/.well-known/oauth-protected-resource")
    @app.get("/.well-known/oauth-protected-resource/{_suffix:path}")
    def oauth_protected_resource(_suffix: str = "") -> JSONResponse:
        """
        Return PRM document. The 'resource' MUST equal the MCP resource identifier (the URL clients use),
        and should be validated by clients per RFC 9728 §3.3.
        """
        return JSONResponse(
            {
                "resource": mcp_resource_url,
                "authorization_servers": authorization_servers,
                "bearer_methods_supported": ["header"],
                "scopes_supported": scopes_supported,
                # (Optional extras: jwks_uri, resource_signing_alg_values_supported, etc.)
            }
        )

    # Health check (unprotected)
    @app.get("/healthz")
    def health() -> PlainTextResponse:
        return PlainTextResponse("ok")


def metadata_url_for_resource(resource_url: str) -> str:
    """
    RFC 9728: insert '/.well-known/oauth-protected-resource' between host and path.
    If the resource has a path (e.g., '/mcp'), append it after the well-known suffix.
    """
    u = urlsplit(resource_url)
    path = u.path.lstrip("/")
    suffix = "/.well-known/oauth-protected-resource"
    if path:
        suffix += f"/{path}"
    return urlunsplit((u.scheme, u.netloc, suffix, "", ""))


PRM_URL = "replace me"


# 2) Middleware that ensures 401s include a proper WWW-Authenticate challenge
#    pointing clients to our PRM URL (RFC 9728 §5.1), and includes RFC 6750 error info.
class WWWAuthenticateMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, protected_prefixes: Iterable[str]) -> None:
        super().__init__(app)
        self.protected_prefixes = tuple(protected_prefixes)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Only guard MCP endpoints (both Streamable HTTP and SSE)
        if not request.url.path.startswith(self.protected_prefixes):
            return await call_next(request)

        # Let FastMCP/verifier run first
        response = await call_next(request)

        # If unauthenticated or invalid token, attach RFC-compliant challenge header
        if response.status_code == 401:
            # RFC 9728: include resource_metadata param pointing to PRM URL.
            # RFC 6750: include error + error_description when appropriate.
            challenge = (
                f'Bearer resource_metadata="{PRM_URL}", '
                f'error="invalid_token", '
                f'error_description="Authentication required"'
            )
            # Don't clobber if already present; append or set.
            if "www-authenticate" in response.headers:
                response.headers["www-authenticate"] += ", " + challenge
            else:
                response.headers["www-authenticate"] = challenge
            # Helpful cache headers
            response.headers.setdefault("cache-control", "no-store")
            response.headers.setdefault("pragma", "no-cache")
        return response


if __name__ == "__main__":

    audience = os.getenv("MCP_OAUTH_AUDIENCE", "api://mcp")
    issuer = os.getenv(
        "MCP_OAUTH_ISSUER",
        "https://test-domain.okta.com/oauth2/default?well_known_override=https://test-domain.okta.com/oauth2/<as_id>/.well-known/oauth-authorization-server",
    )  # NOTE: the mcp client library currently tries the root discovery url before
    # falling back to the one actually used by Okta. Our client code lets you specify this well_known_override
    # for Okta and other Idps that use these discovery urls.

    # issuer = os.getenv("MCP_OAUTH_ISSUER", "https://test-domain.okta.com/.well-known/oauth-authorization-server?issuer=https://test-domain.okta.com/oauth2/<auth_server_id>")
    jwks_uri = os.getenv(
        "MCP_OAUTH_JWKS_URI", "https://test-domain.okta.com/oauth2/default/v1/keys"
    )
    required_scopes = os.getenv("MCP_OAUTH_REQUIRED_SCOPES", "mcp:use")
    print(f"Required scopes: {required_scopes}")
    print(f"Audience: {audience}")
    print(f"Issuer: {issuer}")
    print(f"JWKS URI: {jwks_uri}")

    verifier = JWTVerifier(
        issuer=issuer.split("?")[0],  # ignore auth url override if present
        audience=audience,  # exactly what you set on the AS
        jwks_uri=jwks_uri,
        required_scopes=required_scopes.split(
            ","
        ),  # must be present in the token's `scp`
    )

    mcp = FastMCP("My HTTP MCP", auth=verifier)
    make_many_tools(mcp)
    mcp_app = mcp.http_app()

    app = FastAPI(title="MCP over HTTP/SSE with OAuth", lifespan=mcp_app.lifespan)

    mcp_resource_url = "http://127.0.0.1:8004/mcp/"
    authorization_servers = [issuer]
    scopes_supported = ["mcp:use"]

    init_app(app, mcp_resource_url, authorization_servers, scopes_supported)
    PRM_URL = metadata_url_for_resource(mcp_resource_url)
    print(f"PRM URL: {PRM_URL}")
    print(f"MCP Resource URL: {mcp_resource_url}")
    print(f"Authorization Servers: {authorization_servers}")
    print(f"Scopes Supported: {scopes_supported}")

    # Apply middleware at the parent app so it wraps mounted sub-apps too
    app.add_middleware(WWWAuthenticateMiddleware, protected_prefixes=["/mcp", "/sse"])

    # 3) Mount MCP apps
    # Streamable HTTP transport (recommended for modern MCP clients)
    app.mount("/", mcp_app)
    # SSE transport (some clients still use this)
    # app.mount("/sse", mcp.sse_app()) # TODO: v2

    uvicorn.run(app, host="127.0.0.1", port=8004)
