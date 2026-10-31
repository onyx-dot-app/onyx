"""Resource exposing the agents available to the current user."""

from __future__ import annotations

import json

from onyx.mcp_server.api import mcp_server
from onyx.mcp_server.utils import get_accessible_agents, require_access_token
from onyx.utils.logger import setup_logger

logger = setup_logger()


@mcp_server.resource(
    "resource://agents",
    name="agents",
    description=(
        "Enumerate the Onyx agents accessible to the current user. Use a "
        "returned `name` value with the `agent` filter of the "
        "`search_indexed_documents` tool to run a search with that agent's "
        "knowledge scope and model."
    ),
    mime_type="application/json",
)
async def agents_resource() -> str:
    """Return the agents the user can scope a search to."""

    access_token = require_access_token()

    agents = sorted(
        await get_accessible_agents(access_token), key=lambda entry: entry.name
    )

    logger.info(
        "Onyx MCP Server: agents resource returning %s entries",
        len(agents),
    )

    # FastMCP 3.2+ requires str/bytes/list[ResourceContent] — it no longer
    # auto-serializes; serialize to JSON ourselves.
    return json.dumps([entry.model_dump(mode="json") for entry in agents])
