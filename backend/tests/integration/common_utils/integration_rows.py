"""Integration rows for integration tests, written to the stack's database.

An MCP server made through the admin MCP routes has no integration, and chat
offers no action of it. These helpers make the integration of such a server,
its actions, a plugin in the Organization library that holds it, agent links
and policy rows."""

from collections.abc import Mapping, Sequence
from uuid import UUID, uuid4

from sqlalchemy import delete, select

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    IntegrationActionPolicyValue,
    IntegrationAuthMode,
    IntegrationKind,
    PluginInstallationPolicy,
)
from onyx.db.models import (
    Integration,
    IntegrationActionPolicy,
    Persona__Plugin,
    Plugin,
    Plugin__Integration,
    PluginVersion,
)
from onyx.db.plugin import get_or_create_organization_library__no_commit
from onyx.integrations.sync import sync_integration_actions__no_commit


def add_mcp_integration(mcp_server_id: int, name: str) -> tuple[int, UUID]:
    """An integration with no sign-in for the server, held by a published
    plugin that each user gets by default. Returns the integration id and
    the plugin id."""
    with get_session_with_current_tenant() as db_session:
        integration = Integration(
            kind=IntegrationKind.MCP,
            name=name,
            auth_mode=IntegrationAuthMode.NONE,
            mcp_server_id=mcp_server_id,
        )
        db_session.add(integration)
        db_session.flush()
        sync_integration_actions__no_commit(integration, db_session)
        plugin_id, version_id = uuid4(), uuid4()
        db_session.add(
            Plugin(
                id=plugin_id,
                name=f"integration-{plugin_id.hex[:8]}",
                description="",
                marketplace_id=get_or_create_organization_library__no_commit(
                    db_session
                ),
                installation_policy=PluginInstallationPolicy.DEFAULT,
                current_version_id=version_id,
                published_version_id=version_id,
            )
        )
        db_session.flush()
        db_session.add(
            PluginVersion(id=version_id, plugin_id=plugin_id, version_number=1)
        )
        db_session.add(
            Plugin__Integration(plugin_id=plugin_id, integration_id=integration.id)
        )
        db_session.commit()
        return integration.id, plugin_id


def delete_integration(integration_id: int, plugin_id: UUID) -> None:
    with get_session_with_current_tenant() as db_session:
        db_session.execute(delete(Plugin).where(Plugin.id == plugin_id))
        db_session.execute(delete(Integration).where(Integration.id == integration_id))
        db_session.commit()


def link_persona(
    persona_id: int, plugin_id: UUID, action_settings: Mapping[str, object]
) -> None:
    """Set the agent's link to the plugin, as the agent editor saves it."""
    with get_session_with_current_tenant() as db_session:
        link = db_session.scalar(
            select(Persona__Plugin).where(
                Persona__Plugin.persona_id == persona_id,
                Persona__Plugin.plugin_id == plugin_id,
            )
        )
        if link is None:
            db_session.add(
                Persona__Plugin(
                    persona_id=persona_id,
                    plugin_id=plugin_id,
                    action_settings=dict(action_settings),
                )
            )
        else:
            link.action_settings = dict(action_settings)
        db_session.commit()


def only_actions(actions: Sequence[str]) -> dict[str, object]:
    """The settings the migration writes for an agent with these MCP tools:
    each other action is blocked."""
    return {"default": "blocked", "actions": dict.fromkeys(actions, "inherit")}


def set_admin_policies(
    integration_id: int,
    policies: Mapping[str, IntegrationActionPolicyValue] | None = None,
    *,
    users_can_save_always_allow: bool | None = None,
) -> None:
    """Replace the admin rows of these actions, as the admin Actions tab
    saves them."""
    with get_session_with_current_tenant() as db_session:
        for action, policy in (policies or {}).items():
            db_session.execute(
                delete(IntegrationActionPolicy).where(
                    IntegrationActionPolicy.integration_id == integration_id,
                    IntegrationActionPolicy.action == action,
                    IntegrationActionPolicy.user_id.is_(None),
                )
            )
            db_session.add(
                IntegrationActionPolicy(
                    integration_id=integration_id, action=action, policy=policy
                )
            )
        if users_can_save_always_allow is not None:
            db_session.get_one(
                Integration, integration_id
            ).users_can_save_always_allow = users_can_save_always_allow
        db_session.commit()


def save_always_allow(integration_id: int, user_id: UUID, action: str) -> None:
    """The user's saved Always allow for one action."""
    with get_session_with_current_tenant() as db_session:
        db_session.add(
            IntegrationActionPolicy(
                integration_id=integration_id,
                action=action,
                user_id=user_id,
                policy=IntegrationActionPolicyValue.ALLOW,
            )
        )
        db_session.commit()
