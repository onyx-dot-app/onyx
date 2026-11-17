"""Rows for tests of integrations: an integration with its kind row, an
optional OAuth client and actions, a plugin that holds it, an agent link, and
policy rows."""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.db.enums import (
    ExternalAppType,
    IntegrationActionPolicyValue,
    IntegrationActionSource,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationKind,
    MCPTransport,
    PluginInstallationPolicy,
)
from onyx.db.integration import replace_integration_actions__no_commit
from onyx.db.models import (
    ExternalApp,
    Integration,
    IntegrationActionPolicy,
    IntegrationOAuthClient,
    MCPServer,
    Persona__Plugin,
    Plugin,
    Plugin__Integration,
    Tool,
)
from onyx.integrations.kinds.mcp_server import mcp_action_default_policy
from onyx.integrations.models import IntegrationActionSpec
from onyx.integrations.sync import sync_integration_actions__no_commit
from tests.external_dependency_unit.craft.db_helpers import make_skillless_plugin

DEFAULT_INPUT_SCHEMA: dict[str, JsonValue] = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
}


def _add_integration(
    db_session: Session,
    *,
    kind: IntegrationKind,
    name: str | None,
    auth_mode: IntegrationAuthMode,
    auth_method: IntegrationAuthMethod | None,
    header_template: dict[str, str] | None,
    oauth_client: IntegrationOAuthClient | None = None,
    users_can_save_always_allow: bool = True,
    mcp_server_id: int | None = None,
    external_app_id: int | None = None,
    tool_id: int | None = None,
) -> Integration:
    integration = Integration(
        kind=kind,
        name=name or f"integration-{uuid4().hex[:8]}",
        auth_mode=auth_mode,
        auth_method=auth_method,
        header_template=header_template,
        users_can_save_always_allow=users_can_save_always_allow,
        mcp_server_id=mcp_server_id,
        external_app_id=external_app_id,
        tool_id=tool_id,
    )
    db_session.add(integration)
    db_session.flush()
    if oauth_client is not None:
        oauth_client.integration_id = integration.id
        db_session.add(oauth_client)
        db_session.flush()
    return integration


def make_mcp_integration(
    db_session: Session,
    *,
    server_url: str = "https://mcp.example.test/mcp",
    name: str | None = None,
    tools: Sequence[str] = ("hello",),
    read_only: Mapping[str, bool] | None = None,
    input_schema: dict[str, JsonValue] | None = None,
    output_schema: dict[str, JsonValue] | None = None,
    description: str | None = None,
    auth_mode: IntegrationAuthMode = IntegrationAuthMode.NONE,
    auth_method: IntegrationAuthMethod | None = None,
    header_template: dict[str, str] | None = None,
    users_can_save_always_allow: bool = True,
    oauth_client: IntegrationOAuthClient | None = None,
) -> tuple[Integration, MCPServer]:
    """An MCP server integration whose actions are ``tools``.
    ``oauth_client`` is an unsaved row; this function links and saves it."""
    integration_name = name or f"mcp-{uuid4().hex[:8]}"
    server = MCPServer(
        owner="admin@example.com",
        name=f"{integration_name}-{uuid4().hex[:6]}",
        server_url=server_url,
        transport=MCPTransport.STREAMABLE_HTTP,
    )
    db_session.add(server)
    db_session.flush()
    integration = _add_integration(
        db_session,
        kind=IntegrationKind.MCP,
        name=integration_name,
        auth_mode=auth_mode,
        auth_method=auth_method,
        header_template=header_template,
        oauth_client=oauth_client,
        users_can_save_always_allow=users_can_save_always_allow,
        mcp_server_id=server.id,
    )
    replace_integration_actions__no_commit(
        integration.id,
        IntegrationActionSource.MCP,
        [
            IntegrationActionSpec(
                key=tool,
                source=IntegrationActionSource.MCP,
                display_name=tool.title(),
                description=description or f"The {tool} tool.",
                read_only=(read_only or {}).get(tool),
                default_policy=mcp_action_default_policy((read_only or {}).get(tool)),
                input_schema=(
                    input_schema if input_schema is not None else DEFAULT_INPUT_SCHEMA
                ),
                output_schema=output_schema,
            )
            for tool in tools
        ],
        db_session,
    )
    db_session.commit()
    return integration, server


def make_app_integration(
    db_session: Session,
    *,
    name: str | None = None,
    app_type: ExternalAppType = ExternalAppType.CUSTOM,
    upstream_url_patterns: list[str] | None = None,
    auth_template: dict[str, Any] | None = None,
    organization_credentials: dict[str, Any] | None = None,
    auth_mode: IntegrationAuthMode = IntegrationAuthMode.NONE,
    auth_method: IntegrationAuthMethod | None = None,
    header_template: dict[str, str] | None = None,
    oauth_client: IntegrationOAuthClient | None = None,
) -> tuple[Integration, ExternalApp]:
    """An external app integration: a preset (``app_type``) or a CUSTOM app,
    with the actions that its kind finds. ``oauth_client`` is an unsaved row;
    this function links and saves it."""
    app_name = name or f"app-{uuid4().hex[:8]}"
    app = ExternalApp(
        name=app_name,
        app_type=app_type,
        enabled=True,
        upstream_url_patterns=upstream_url_patterns or [],
        auth_template=auth_template or {},
        organization_credentials=organization_credentials or {},
    )
    db_session.add(app)
    db_session.flush()
    integration = _add_integration(
        db_session,
        kind=IntegrationKind.API,
        name=app_name,
        auth_mode=auth_mode,
        auth_method=auth_method,
        header_template=header_template,
        oauth_client=oauth_client,
        external_app_id=app.id,
    )
    sync_integration_actions__no_commit(integration, db_session)
    db_session.commit()
    return integration, app


def make_openapi_integration(
    db_session: Session,
    *,
    openapi_schema: dict[str, Any],
    name: str | None = None,
    auth_mode: IntegrationAuthMode = IntegrationAuthMode.NONE,
    auth_method: IntegrationAuthMethod | None = None,
    header_template: dict[str, str] | None = None,
) -> tuple[Integration, Tool]:
    tool = Tool(
        name=f"openapi-{uuid4().hex[:8]}",
        description="OpenAPI tool",
        openapi_schema=openapi_schema,
        enabled=True,
        passthrough_auth=False,
    )
    db_session.add(tool)
    db_session.flush()
    integration = _add_integration(
        db_session,
        kind=IntegrationKind.API,
        name=name,
        auth_mode=auth_mode,
        auth_method=auth_method,
        header_template=header_template,
        tool_id=tool.id,
    )
    sync_integration_actions__no_commit(integration, db_session)
    db_session.commit()
    return integration, tool


def hold_in_plugin(
    db_session: Session,
    integrations: Sequence[Integration],
    *,
    published: bool = True,
    installation_policy: PluginInstallationPolicy | None = None,
    author_user_id: UUID | None = None,
) -> Plugin:
    """A plugin with no skills that holds the integrations."""
    plugin = make_skillless_plugin(
        db_session,
        author_user_id=author_user_id,
        published=published,
        installation_policy=installation_policy,
    )
    db_session.add_all(
        [
            Plugin__Integration(plugin_id=plugin.id, integration_id=integration.id)
            for integration in integrations
        ]
    )
    db_session.commit()
    return plugin


def link_persona(
    db_session: Session,
    persona_id: int,
    plugin_id: UUID,
    action_settings: dict[str, Any] | None = None,
) -> None:
    db_session.add(
        Persona__Plugin(
            persona_id=persona_id,
            plugin_id=plugin_id,
            action_settings=action_settings or {},
        )
    )
    db_session.commit()


def set_policy(
    db_session: Session,
    integration_id: int,
    action: str,
    policy: IntegrationActionPolicyValue,
    *,
    user_id: UUID | None = None,
) -> None:
    """An admin row (no user) or a user's row. The empty action is the
    default row."""
    db_session.add(
        IntegrationActionPolicy(
            integration_id=integration_id,
            action=action,
            user_id=user_id,
            policy=policy,
        )
    )
    db_session.commit()


def delete_integrations(db_session: Session, integration_ids: Sequence[int]) -> None:
    """Delete the integrations with their kind rows and plugins. The other
    rows of an integration go by cascade."""
    db_session.rollback()
    if not integration_ids:
        return
    plugin_ids = list(
        db_session.scalars(
            select(Plugin__Integration.plugin_id).where(
                Plugin__Integration.integration_id.in_(integration_ids)
            )
        )
    )
    integrations = db_session.scalars(
        select(Integration).where(Integration.id.in_(integration_ids))
    ).all()
    server_ids = [i.mcp_server_id for i in integrations if i.mcp_server_id]
    app_ids = [i.external_app_id for i in integrations if i.external_app_id]
    tool_ids = [i.tool_id for i in integrations if i.tool_id]
    db_session.execute(delete(Integration).where(Integration.id.in_(integration_ids)))
    db_session.execute(delete(Tool).where(Tool.id.in_(tool_ids)))
    db_session.execute(delete(MCPServer).where(MCPServer.id.in_(server_ids)))
    db_session.execute(delete(ExternalApp).where(ExternalApp.id.in_(app_ids)))
    if plugin_ids:
        db_session.execute(delete(Plugin).where(Plugin.id.in_(plugin_ids)))
    db_session.commit()
