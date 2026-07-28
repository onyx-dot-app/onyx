"""Resolve craft-enabled MCP servers into opencode `mcp` config input."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy.orm import Session

from onyx.db.mcp import (
    can_resolve_mcp_credentials,
    get_craft_enabled_mcp_servers,
    get_mcp_tools_for_servers,
    get_user_connection_configs,
)
from onyx.db.models import MCPServer, User
from onyx.server.features.build.sandbox.models import CraftMCPServerConfig
from onyx.utils.logger import setup_logger

logger = setup_logger()

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

    Filtered by access and by resolvable credentials — injection blocks an
    unauthenticated server's tool discovery, so emitting it only buys a
    permanently failed MCP client.

    Query count is flat in the number of servers: this runs per user in the
    admin restamp fan-out (``refresh_mcp_config_hashes_for_users``), which for a
    public server covers every user with a running sandbox."""
    accessible = get_craft_enabled_mcp_servers(db_session, user)
    user_configs = get_user_connection_configs(
        [s.id for s in accessible], user.email, db_session
    )
    servers: list[MCPServer] = []
    for server in accessible:
        if can_resolve_mcp_credentials(
            server, user, db_session, user_configs=user_configs
        ):
            servers.append(server)
        else:
            # Craft reads no MCP status back from opencode; this is the only
            # trace of why a server is missing from a session's config.
            logger.info(
                "craft_mcp_skip_unauthenticated server_id=%s name=%r",
                server.id,
                server.name,
            )
    disabled_by_server: dict[int, list[str]] = defaultdict(list)
    for tool in get_mcp_tools_for_servers([s.id for s in servers], db_session):
        if tool.mcp_server_id is not None and not tool.enabled:
            disabled_by_server[tool.mcp_server_id].append(tool.name)
    return [
        CraftMCPServerConfig(
            key=_server_key(server),
            url=server.server_url,
            disabled_tools=tuple(sorted(disabled_by_server.get(server.id, ()))),
            server_id=server.id,
        )
        for server in servers
    ]


def craft_mcp_fingerprint(mcp_servers: Sequence[CraftMCPServerConfig]) -> str:
    """Stable digest of everything about the craft MCP set that a running
    session must be rebuilt to pick up: the server set (id + url) and each
    server's disabled-tool set. Credential state rides in set membership, since
    ``resolve_craft_mcp_servers`` omits what it can't authenticate.
    Order-independent."""
    payload = sorted(
        [
            s.server_id,
            s.url,
            list(s.disabled_tools),
        ]
        for s in mcp_servers
    )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
