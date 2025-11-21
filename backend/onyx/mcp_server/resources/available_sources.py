"""Resources that expose metadata for the Onyx MCP server."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import Any

from fastmcp.server.dependencies import get_access_token

from onyx.mcp_server.api import mcp_server
from onyx.mcp_server.utils import fetch_indexed_source_types
from onyx.utils.logger import setup_logger

logger = setup_logger()


@mcp_server.resource(
    "resource://available_sources",
    name="available_sources",
    description=(
        "Enumerate document sources that currently have indexed content and can be "
        "used to filter the onyx_search_documents tool."
    ),
    mime_type="application/json",
)
async def available_sources_resource() -> dict[str, Any]:
    """Return the list of indexed source types for search filtering."""

    access_token = get_access_token()
    if not access_token:
        raise ValueError("Authentication required")

    sources = await fetch_indexed_source_types(access_token)
    if sources is None:
        raise ValueError("Failed to fetch indexed source types")

    source_values = sorted(sources)

    logger.info(
        "Onyx MCP Server: available_sources resource returning %s entries",
        len(source_values),
    )

    return {
        "sources": source_values,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
