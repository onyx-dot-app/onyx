"""Configuration for the MCP server.

Reads directly from environment variables to avoid importing heavy dependencies
from the main Onyx codebase (e.g., fastapi_users via onyx.configs.app_configs).

These values must match the definitions in onyx.configs.app_configs.
"""

import os


# API server connection settings
APP_PORT = 8080
# API_PREFIX is used to prepend a base path for all API routes
# generally used if using a reverse proxy which doesn't support stripping the `/api`
# prefix from requests directed towards the API server. In these cases, set this to `/api`
APP_API_PREFIX = os.environ.get("API_PREFIX", "")

# MCP server settings
MCP_SERVER_ENABLED = os.environ.get("MCP_SERVER_ENABLED", "").lower() == "true"
MCP_SERVER_PORT = int(os.environ.get("MCP_SERVER_PORT") or 8090)

# CORS origins for MCP clients (comma-separated)
# Local dev: "http://localhost:*"
# Production: "https://trusted-client.com,https://another-client.com"
MCP_SERVER_CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("MCP_SERVER_CORS_ORIGINS", "").split(",")
    if origin.strip()
]
