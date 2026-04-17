"""Resource exposing document sets available to the current user."""

from __future__ import annotations

from typing import Any

from onyx.mcp_server.api import mcp_server
from onyx.mcp_server.utils import get_accessible_document_sets
from onyx.mcp_server.utils import require_access_token
from onyx.utils.logger import setup_logger

logger = setup_logger()


@mcp_server.resource(
    "resource://document_sets",
    name="document_sets",
    description=(
        "Enumerate the Document Sets accessible to the current user. Use the "
        "returned `name` values with the `document_set_names` filter of the "
        "`search_indexed_documents` tool to scope searches to a specific set."
    ),
    mime_type="application/json",
)
async def document_sets_resource() -> dict[str, Any]:
    """Return the list of document sets the user can filter searches by."""

    access_token = require_access_token()

    document_sets = sorted(
        await get_accessible_document_sets(access_token), key=lambda entry: entry.name
    )

    logger.info(
        "Onyx MCP Server: document_sets resource returning %s entries",
        len(document_sets),
    )

    return {
        "document_sets": [entry.model_dump(mode="json") for entry in document_sets],
    }
