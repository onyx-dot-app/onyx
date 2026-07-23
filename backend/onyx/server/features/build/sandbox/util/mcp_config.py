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
    get_craft_enabled_mcp_servers,
    get_mcp_tools_for_servers,
    get_user_authenticated_server_ids,
)
from onyx.db.models import MCPServer, User
from onyx.server.features.build.sandbox.models import CraftMCPServerConfig
from onyx.server.features.build.sandbox.util.opencode_config import (
    build_session_mcp_config,
)

if TYPE_CHECKING:
    from onyx.server.features.build.sandbox.base import SandboxManager

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

    Access is filtered here; authentication is not — auth state changes
    mid-session while this config is baked at provision, so the proxy enforces
    credentials per request."""
    servers = get_craft_enabled_mcp_servers(db_session, user)
    disabled_by_server: dict[int, list[str]] = defaultdict(list)
    for tool in get_mcp_tools_for_servers([s.id for s in servers], db_session):
        if tool.mcp_server_id is not None and not tool.enabled:
            disabled_by_server[tool.mcp_server_id].append(tool.name)
    # Per-user credential presence feeds the runtime hash so connecting/
    # disconnecting credentials hot-reloads the session (opencode re-runs tool
    # discovery, which is credential-gated).
    authed_ids = get_user_authenticated_server_ids(
        [s.id for s in servers], user.email, db_session
    )
    return [
        CraftMCPServerConfig(
            key=_server_key(server),
            url=server.server_url,
            disabled_tools=tuple(sorted(disabled_by_server.get(server.id, ()))),
            server_id=server.id,
            authenticated=server.id in authed_ids,
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
    session must be rebuilt to pick up: the server set (id + url), each server's
    disabled-tool set, and whether the user is authenticated (tool discovery is
    credential-gated). Feeds the per-session runtime hash. Order-independent."""
    payload = sorted(
        [
            s.server_id,
            s.url,
            list(s.disabled_tools),
            s.authenticated,
        ]
        for s in mcp_servers
    )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
