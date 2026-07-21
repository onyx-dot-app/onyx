"""Resolve craft-enabled MCP servers into opencode `mcp` config input."""

from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy.orm import Session

from onyx.db.mcp import get_craft_enabled_mcp_servers, get_mcp_tools_for_servers
from onyx.db.models import MCPServer, User
from onyx.server.features.build.sandbox.models import CraftMCPServerConfig

_NON_IDENTIFIER = re.compile(r"[^a-z0-9]+")


def _server_key(server: MCPServer) -> str:
    """Identifier-safe opencode server id; the id suffix keeps it unique across
    servers that slugify to the same name."""
    slug = _NON_IDENTIFIER.sub("-", server.name.lower()).strip("-") or "mcp"
    return f"{slug}-{server.id}"


def resolve_craft_mcp_servers(
    db_session: Session, user: User
) -> list[CraftMCPServerConfig]:
    """Craft-enabled MCP servers ``user`` may use, as opencode config input.
    Two queries: the servers, then a bulk fetch of their tools.

    Access (public / shared / owned) is filtered here; authentication is not —
    auth state changes mid-session (connect, token expiry) while this config is
    baked at provision, so the proxy enforces credentials per request and
    surfaces a "connect this server" detail for unauthenticated ones."""
    servers = get_craft_enabled_mcp_servers(db_session, user)
    disabled_by_server: dict[int, list[str]] = defaultdict(list)
    for tool in get_mcp_tools_for_servers([s.id for s in servers], db_session):
        if tool.mcp_server_id is not None and not tool.enabled:
            disabled_by_server[tool.mcp_server_id].append(tool.name)
    return [
        CraftMCPServerConfig(
            key=_server_key(server),
            url=server.server_url,
            disabled_tools=tuple(disabled_by_server.get(server.id, ())),
        )
        for server in servers
    ]
