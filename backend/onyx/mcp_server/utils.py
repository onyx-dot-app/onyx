"""Utility helpers for the Onyx MCP server."""

from __future__ import annotations

import httpx
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.dependencies import get_access_token
from pydantic import BaseModel
from pydantic import TypeAdapter

from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import build_api_server_url_for_http_requests


class DocumentSetEntry(BaseModel):
    """Minimal document-set shape surfaced to MCP clients.

    Projected from the backend's DocumentSetSummary to avoid coupling MCP to
    admin-only fields (cc-pair summaries, federated connectors, etc.).
    """

    name: str
    description: str | None = None


logger = setup_logger()

# Shared HTTP client reused across requests
_http_client: httpx.AsyncClient | None = None


def require_access_token() -> AccessToken:
    """
    Get and validate the access token from the current request.

    Raises:
        ValueError: If no access token is present in the request.

    Returns:
        AccessToken: The validated access token.
    """
    access_token = get_access_token()
    if not access_token:
        raise ValueError(
            "MCP Server requires an Onyx access token to authenticate your request"
        )
    return access_token


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


async def get_indexed_sources(
    access_token: AccessToken,
) -> list[str]:
    """
    Fetch indexed document sources for the current user/tenant.

    Returns:
        List of indexed source strings. Empty list if no sources are indexed.
    """
    headers = {"Authorization": f"Bearer {access_token.token}"}
    try:
        response = await get_http_client().get(
            f"{build_api_server_url_for_http_requests(respect_env_override_if_set=True)}/manage/indexed-sources",
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
        sources = payload.get("sources", [])
        if not isinstance(sources, list):
            raise ValueError("Unexpected response shape for indexed sources")
        return [str(source) for source in sources]
    except (httpx.HTTPStatusError, httpx.RequestError, ValueError):
        # Re-raise known exception types (httpx errors and validation errors)
        logger.error(
            "Onyx MCP Server: Failed to fetch indexed sources",
            exc_info=True,
        )
        raise
    except Exception as exc:
        # Wrap unexpected exceptions
        logger.error(
            "Onyx MCP Server: Unexpected error fetching indexed sources",
            exc_info=True,
        )
        raise RuntimeError(f"Failed to fetch indexed sources: {exc}") from exc


_DOCUMENT_SET_ENTRIES_ADAPTER = TypeAdapter(list[DocumentSetEntry])


async def get_accessible_document_sets(
    access_token: AccessToken,
) -> list[DocumentSetEntry]:
    """Fetch document sets accessible to the current user."""
    headers = {"Authorization": f"Bearer {access_token.token}"}
    try:
        response = await get_http_client().get(
            f"{build_api_server_url_for_http_requests(respect_env_override_if_set=True)}/manage/document-set",
            headers=headers,
        )
        response.raise_for_status()
        return _DOCUMENT_SET_ENTRIES_ADAPTER.validate_json(response.content)
    except (httpx.HTTPStatusError, httpx.RequestError, ValueError):
        logger.error(
            "Onyx MCP Server: Failed to fetch document sets",
            exc_info=True,
        )
        raise
    except Exception as exc:
        logger.error(
            "Onyx MCP Server: Unexpected error fetching document sets",
            exc_info=True,
        )
        raise RuntimeError(f"Failed to fetch document sets: {exc}") from exc
