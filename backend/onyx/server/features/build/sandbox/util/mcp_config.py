"""Resolve craft-enabled MCP servers into opencode `mcp` config input."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.mcp import (
    can_resolve_mcp_credentials,
    get_craft_enabled_mcp_servers,
    get_mcp_tools_for_servers,
)
from onyx.db.models import MCPServer, User
from onyx.server.features.build.sandbox.models import CraftMCPServerConfig
from onyx.server.features.build.sandbox.util.opencode_config import (
    build_session_mcp_config,
)
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    from onyx.server.features.build.sandbox.base import SandboxManager

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
    permanently failed MCP client."""
    servers: list[MCPServer] = []
    for server in get_craft_enabled_mcp_servers(db_session, user):
        if can_resolve_mcp_credentials(server, user, db_session):
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


def write_session_mcp_config(
    sandbox_manager: SandboxManager,
    db_session: Session,
    user: User,
    sandbox_id: UUID,
    session_id: UUID,
) -> None:
    """Render ``session_id``'s craft MCP config and write it to the session's
    project ``opencode.json`` (``sessions/<id>/opencode.json``). opencode merges
    it with the pod-global config and re-reads it when the session's instance is
    disposed, so writing this then ``dispose_opencode_instance`` hot-reloads the
    MCP set without a pod re-provision. Done on cold session setup and every
    skills/MCP reload."""
    servers = resolve_craft_mcp_servers(db_session, user)
    config_json = json.dumps(build_session_mcp_config(servers, str(session_id)))
    sandbox_manager.write_sandbox_file(
        sandbox_id, f"sessions/{session_id}/opencode.json", config_json
    )


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
