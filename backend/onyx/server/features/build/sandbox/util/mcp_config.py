"""Resolve craft-enabled MCP servers into static opencode `mcp` config.

Credentials are deliberately absent — the sandbox proxy injects them per
request, so the emitted config is identical whether or not a user has connected
a server. Chat-side per-tool curation (`Tool.enabled`) carries over as opencode
enable/disable entries.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from onyx.db.mcp import get_all_mcp_tools_for_server
from onyx.db.mcp import get_craft_enabled_mcp_servers
from onyx.db.models import MCPServer
from onyx.server.features.build.sandbox.models import CraftMCPServerConfig

_NON_IDENTIFIER = re.compile(r"[^a-z0-9]+")


def _server_key(server: MCPServer) -> str:
    """A stable, identifier-safe opencode server id. The row id suffix keeps it
    unique across servers that slugify to the same name."""
    slug = _NON_IDENTIFIER.sub("-", server.name.lower()).strip("-") or "mcp"
    return f"{slug}-{server.id}"


def resolve_craft_mcp_servers(db_session: Session) -> list[CraftMCPServerConfig]:
    """Every craft-enabled MCP server as opencode config input, with its tools
    split into enabled/disabled by the admin's chat-side curation."""
    configs: list[CraftMCPServerConfig] = []
    for server in get_craft_enabled_mcp_servers(db_session):
        tools = get_all_mcp_tools_for_server(server.id, db_session)
        configs.append(
            CraftMCPServerConfig(
                key=_server_key(server),
                url=server.server_url,
                enabled_tools=tuple(t.name for t in tools if t.enabled),
                disabled_tools=tuple(t.name for t in tools if not t.enabled),
            )
        )
    return configs
