"""Resolve the MCP integrations of a user into opencode `mcp` config input."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.enums import IntegrationKind
from onyx.db.integration import (
    get_mcp_server_for_integration,
    list_integration_actions,
)
from onyx.db.models import Integration, User
from onyx.integrations.connection_models import ConnectionState
from onyx.integrations.connections import integration_status
from onyx.integrations.craft import (
    TaskPlugins,
    list_runnable_integrations,
    load_task_plugins,
    resolve_craft_action_policies,
)
from onyx.integrations.models import EffectivePolicy
from onyx.server.features.build.sandbox.models import CraftMCPServerConfig
from onyx.utils.logger import setup_logger

logger = setup_logger()

_NON_IDENTIFIER = re.compile(r"[^a-z0-9]+")


def _server_key(integration: Integration) -> str:
    """Identifier-safe opencode server id; the id suffix keeps it unique across
    integrations that slugify to the same name."""
    slug = _NON_IDENTIFIER.sub("-", integration.name.lower()).strip("-") or "mcp"
    return f"{slug}-{integration.id}"


def _blocked_actions(
    db_session: Session, integration: Integration, user: User, task: TaskPlugins | None
) -> tuple[str, ...]:
    keys = [
        action.key for action in list_integration_actions(integration.id, db_session)
    ]
    policies = resolve_craft_action_policies(
        db_session,
        integration=integration,
        action_keys=keys,
        user_id=user.id,
        task=task,
    )
    return tuple(
        sorted(
            key for key, policy in policies.items() if policy is EffectivePolicy.BLOCKED
        )
    )


def resolve_craft_mcp_servers(
    db_session: Session, user: User, task_id: UUID | None = None
) -> list[CraftMCPServerConfig]:
    """The MCP integrations of the plugins ``user`` runs, as opencode config
    input. A session of a scheduled run (``task_id``) gets only the task
    plugins that the owner can see, also one the owner turned off, and the
    task settings decide its disabled tools, as in the proxy. Only a connected integration (or one with
    no sign-in) is listed: injection blocks the tool discovery of an
    unauthenticated server, so emitting it only buys a permanently failed MCP
    client. A Blocked action is a disabled tool."""
    task = (
        load_task_plugins(db_session, task_id, user.id) if task_id is not None else None
    )
    integrations = (
        list_runnable_integrations(db_session, user.id)
        if task is None
        else task.integrations()
    )
    configs: list[CraftMCPServerConfig] = []
    for integration in integrations:
        if integration.kind is not IntegrationKind.MCP:
            continue
        server = get_mcp_server_for_integration(integration.id, db_session)
        if server is None:
            continue
        status = integration_status(integration, user, db_session)
        if status.state is not ConnectionState.CONNECTED:
            # Craft reads no MCP status back from opencode; this is the only
            # trace of why a server is missing from a session's config.
            logger.info(
                "craft_mcp_skip_unauthenticated integration_id=%s name=%r",
                integration.id,
                integration.name,
            )
            continue
        configs.append(
            CraftMCPServerConfig(
                key=_server_key(integration),
                url=server.server_url,
                disabled_tools=_blocked_actions(db_session, integration, user, task),
                integration_id=integration.id,
            )
        )
    return configs


def craft_mcp_fingerprint(mcp_servers: Sequence[CraftMCPServerConfig]) -> str:
    """Stable digest of everything about the craft MCP set that a running
    session must be rebuilt to pick up: the server set (id + url) and each
    server's disabled-tool set. Credential state rides in set membership, since
    ``resolve_craft_mcp_servers`` omits what it can't authenticate.
    Order-independent."""
    payload = sorted(
        [
            s.integration_id,
            s.url,
            list(s.disabled_tools),
        ]
        for s in mcp_servers
    )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
