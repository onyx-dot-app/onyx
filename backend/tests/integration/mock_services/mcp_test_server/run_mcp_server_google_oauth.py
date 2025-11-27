"""
MCP Test Server for Google OAuth Pass-Through Authentication

This server validates Google OAuth access tokens that are passed through from
Onyx. When users log into Onyx with Google OAuth, their access token is stored
and can be passed to MCP servers that require authentication.

This server validates those tokens by calling Google's tokeninfo endpoint.

Usage:
    python run_mcp_server_google_oauth.py [port]

Environment Variables:
    MCP_SERVER_HOST: Host to bind to (default: 127.0.0.1)
    MCP_SERVER_PUBLIC_HOST: Public hostname for the server
    MCP_SERVER_PUBLIC_URL: Public URL for the server (e.g., for proxied setups)
"""

import os
import sys
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth import TokenVerifier
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.server import FunctionTool

# Google's tokeninfo endpoint for validating access tokens
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"


class GoogleOAuthTokenVerifier(TokenVerifier):
    """
    Token verifier that validates Google OAuth access tokens.

    Google access tokens are opaque tokens (not JWTs), so they need to be
    validated by calling Google's tokeninfo endpoint. This verifier makes
    an HTTP request to Google to validate the token and extract user info.

    This is useful for testing pass-through OAuth scenarios where Onyx
    forwards the user's Google OAuth token to an MCP server.
    """

    def __init__(
        self,
        required_scopes: list[str] | None = None,
        resource_server_url: str | None = None,
    ):
        """
        Initialize the Google OAuth token verifier.

        Args:
            required_scopes: Optional list of scopes that must be present in the token.
                            Google tokens have scopes like 'openid', 'email', 'profile'.
            resource_server_url: URL of this resource server (for RFC 8707)
        """
        super().__init__(
            resource_server_url=resource_server_url,
            required_scopes=required_scopes,
        )
        self._http_client: httpx.AsyncClient | None = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client for token validation."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=10.0)
        return self._http_client

    async def verify_token(self, token: str) -> AccessToken | None:
        """
        Verify a Google OAuth access token by calling Google's tokeninfo endpoint.

        Args:
            token: The Google OAuth access token to validate

        Returns:
            AccessToken object if valid, None if invalid or expired
        """
        try:
            client = await self._get_http_client()

            # Call Google's tokeninfo endpoint
            response = await client.get(
                GOOGLE_TOKENINFO_URL,
                params={"access_token": token},
            )

            if response.status_code != 200:
                # Token is invalid or expired
                return None

            token_info = response.json()

            # Check if token has an error (Google returns 200 with error field sometimes)
            if "error" in token_info:
                return None

            # Extract scopes from the token
            scopes_str = token_info.get("scope", "")
            scopes = scopes_str.split() if scopes_str else []

            # Check required scopes if configured
            if self.required_scopes:
                token_scopes = set(scopes)
                required = set(self.required_scopes)
                if not required.issubset(token_scopes):
                    return None

            # Extract client/user ID - prefer email for user identification
            client_id = (
                token_info.get("email")
                or token_info.get("sub")
                or token_info.get("user_id")
                or "unknown"
            )

            # Extract expiration time
            expires_in = token_info.get("expires_in")
            expires_at = None
            if expires_in:
                import time

                expires_at = int(time.time()) + int(expires_in)

            return AccessToken(
                token=token,
                client_id=client_id,
                scopes=scopes,
                expires_at=expires_at,
                claims=token_info,
            )

        except httpx.HTTPError:
            # Network error or timeout
            return None
        except Exception:
            # Any other error during validation
            return None

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()


def make_tools(mcp: FastMCP) -> list[FunctionTool]:
    """Create test tools for the MCP server."""
    tools: list[FunctionTool] = []

    @mcp.tool(name="echo", description="Echo back the input message")
    def echo(message: str) -> str:
        """Echo the message back to the caller."""
        return f"You said: {message}"

    tools.append(echo)

    @mcp.tool(name="get_secret", description="Get a secret value (requires auth)")
    def get_secret(secret_name: str) -> str:
        """Get a secret value. This proves the token was validated."""
        return f"Secret value for '{secret_name}': super-secret-value-12345"

    tools.append(get_secret)

    @mcp.tool(name="whoami", description="Get information about the authenticated user")
    async def whoami() -> dict[str, Any]:
        """Get information about the authenticated user from their Google token."""
        tok = get_access_token()
        if not tok:
            return {"error": "Not authenticated"}

        return {
            "client_id": tok.client_id,
            "scopes": tok.scopes,
            "email": tok.claims.get("email"),
            "email_verified": tok.claims.get("email_verified"),
            "expires_in": tok.claims.get("expires_in"),
            "access_type": tok.claims.get("access_type"),
        }

    tools.append(whoami)

    # Add some numbered tools for testing tool discovery
    for i in range(5):

        @mcp.tool(name=f"oauth_tool_{i}", description=f"Test tool number {i}")
        def numbered_tool(name: str, _i: int = i) -> str:
            """A numbered test tool."""
            return f"Tool {_i} says hello to {name}!"

        tools.append(numbered_tool)

    return tools


if __name__ == "__main__":
    port = int(sys.argv[1] if len(sys.argv) > 1 else "8006")

    # Get configuration from environment
    bind_host = os.getenv("MCP_SERVER_HOST", "127.0.0.1")
    public_host = os.getenv("MCP_SERVER_PUBLIC_HOST", bind_host)
    public_url = os.getenv("MCP_SERVER_PUBLIC_URL")

    # Optional: require specific scopes (Google tokens have scopes like 'email', 'profile')
    # Leave empty to accept any valid Google token
    required_scopes_str = os.getenv("MCP_GOOGLE_REQUIRED_SCOPES", "")
    required_scopes = (
        required_scopes_str.split(",") if required_scopes_str.strip() else None
    )

    print(f"Starting Google OAuth MCP Test Server on port {port}")
    print(f"Bind host: {bind_host}")
    print(f"Public host: {public_host}")
    if public_url:
        print(f"Public URL: {public_url}")
    if required_scopes:
        print(f"Required scopes: {required_scopes}")
    else:
        print("No specific scopes required - any valid Google token accepted")

    # Create the auth verifier
    auth = GoogleOAuthTokenVerifier(required_scopes=required_scopes)

    # Create FastMCP instance with auth
    mcp = FastMCP("Google OAuth Test MCP Server", auth=auth)
    make_tools(mcp)

    # Get the MCP HTTP app
    mcp_app = mcp.http_app()

    # Create wrapper FastAPI app
    app = FastAPI(
        title="MCP Google OAuth Test Server",
        description="MCP server that authenticates using Google OAuth tokens passed through from Onyx",
        lifespan=mcp_app.lifespan,
    )

    # Health check (unprotected)
    @app.get("/healthz")
    def health() -> PlainTextResponse:
        return PlainTextResponse("ok")

    # Info endpoint (unprotected) - useful for debugging
    @app.get("/info")
    def info() -> dict[str, Any]:
        return {
            "server": "Google OAuth MCP Test Server",
            "auth_type": "google_oauth_pass_through",
            "description": "Validates Google OAuth tokens passed from Onyx",
            "tokeninfo_endpoint": GOOGLE_TOKENINFO_URL,
            "required_scopes": required_scopes,
        }

    # Mount MCP app at root
    app.mount("/", mcp_app)

    # Run the server
    uvicorn.run(app, host=bind_host, port=port)
