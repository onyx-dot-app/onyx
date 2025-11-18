"""Resources that expose metadata for the Onyx MCP server."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import Any

from fastmcp.server.dependencies import get_access_token

from onyx.db.connector import fetch_unique_document_sources
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.mcp_server.api import mcp_server
from onyx.mcp_server.utils import tenant_context_from_token
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
def available_sources_resource() -> dict[str, Any]:
    """Return the list of indexed source types for search filtering."""

    access_token = get_access_token()
    if not access_token or "_user" not in access_token.claims:
        raise ValueError("Authentication required")

    with tenant_context_from_token(access_token):
        with get_session_with_current_tenant() as db_session:
            sources = fetch_unique_document_sources(db_session)

    source_values = sorted(source.value for source in sources)

    logger.info(
        "Onyx MCP Server: available_sources resource returning %s entries",
        len(source_values),
    )

    return {
        "sources": source_values,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
