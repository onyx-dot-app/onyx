"""Utility helpers for the Onyx MCP server."""

from __future__ import annotations

import os

import httpx
from fastmcp.server.auth.auth import AccessToken

from onyx.configs.app_configs import APP_API_PREFIX
from onyx.configs.app_configs import APP_PORT
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Shared HTTP client reused across requests
_http_client: httpx.AsyncClient | None = None


def get_api_server_url() -> str:
    """Construct the API server base URL for internal or external requests."""
    override = os.getenv("API_SERVER_BASE_URL") or os.getenv("ONYX_URL")
    if override:
        return override.rstrip("/")

    protocol = os.getenv("API_SERVER_PROTOCOL", "http")
    host = os.getenv("API_SERVER_HOST", "127.0.0.1")
    port = os.getenv("API_SERVER_PORT", str(APP_PORT))
    prefix = (APP_API_PREFIX or "").strip("/")

    base = f"{protocol}://{host}:{port}"
    return f"{base}/{prefix}" if prefix else base


def get_http_client() -> httpx.AsyncClient:
    """Return a shared async HTTP client."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=60.0)
    return _http_client


async def shutdown_http_client() -> None:
    """Close the shared HTTP client when the server shuts down."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


async def fetch_indexed_source_types(
    access_token: AccessToken,
) -> list[str] | None:
    """Fetch indexed document source types for the current user/tenant."""
    headers = {"Authorization": f"Bearer {access_token.token}"}
    try:
        response = await get_http_client().get(
            f"{get_api_server_url()}/manage/indexed-source-types",
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
        source_types = payload.get("source_types", [])
        if not isinstance(source_types, list):
            logger.error(
                "Onyx MCP Server: Unexpected response shape for indexed source types"
            )
            return None
        return [str(source_type) for source_type in source_types]
    except Exception as exc:
        logger.error(
            "Onyx MCP Server: Failed to fetch indexed source types: %s",
            exc,
            exc_info=True,
        )
        return None
