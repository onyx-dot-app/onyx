"""Shared dev credentials for local MCP OAuth mocks.

Use these values when registering the MCP server in Onyx Admin and when
configuring the OAuth client on the local mock IdP (fixed in mock_oauth_idp.py).
"""

from __future__ import annotations

# Local mock authorization server (mock_oauth_idp.py)
DEV_OAUTH_ISSUER = "http://127.0.0.1:8765"
DEV_OAUTH_JWKS_URI = f"{DEV_OAUTH_ISSUER}/jwks"
DEV_OAUTH_AUDIENCE = "api://mcp"
DEV_OAUTH_SCOPE = "mcp:use"

DEV_OAUTH_CLIENT_ID = "onyx-mcp-dev"
DEV_OAUTH_CLIENT_SECRET = "onyx-mcp-dev-secret"
DEV_OAUTH_REDIRECT_URI = "http://localhost:3000/mcp/oauth/callback"

# MCP mock servers (see README.md)
MCP_NO_AUTH_URL = "http://127.0.0.1:8010/mcp"
MCP_API_KEY_URL = "http://127.0.0.1:8001/mcp"
MCP_LOCAL_OAUTH_URL = "http://127.0.0.1:8012/mcp"
MCP_HANDSHAKE_OAUTH_URL = "http://127.0.0.1:8013/mcp"

DEV_API_KEY = "dev-api-key-123"
