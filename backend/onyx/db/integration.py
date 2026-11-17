from collections.abc import Collection, Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Select, and_, delete, func, select, update
from sqlalchemy.orm import InstrumentedAttribute, Session, aliased, load_only
from sqlalchemy.sql.elements import KeyedColumnElement

from onyx.db.enums import (
    ExternalAppType,
    IntegrationActionPolicyValue,
    IntegrationActionSource,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationKind,
    IntegrationOAuthProviderMode,
    MarketplaceKind,
    MCPTransport,
)
from onyx.db.external_app import delete_external_app__no_commit
from onyx.db.models import (
    ExternalApp,
    Integration,
    IntegrationAction,
    IntegrationActionPolicy,
    IntegrationConnection,
    IntegrationOAuthClient,
    Marketplace,
    MCPServer,
    Plugin,
    Plugin__Integration,
    PluginSkill,
    PluginVersion,
    Tool,
    User,
)
from onyx.db.utils import UnsetType, is_set
from onyx.integrations.connection_models import read_oauth_client
from onyx.integrations.models import IntegrationActionSpec, IntegrationPluginRow


def get_integration_by_id(
    integration_id: int, db_session: Session
) -> Integration | None:
    return db_session.get(Integration, integration_id)


def list_enabled_integrations_by_id(
    db_session: Session, integration_ids: Collection[int]
) -> list[Integration]:
    if not integration_ids:
        return []
    return list(
        db_session.scalars(
            select(Integration)
            .where(Integration.id.in_(integration_ids), Integration.enabled.is_(True))
            .order_by(Integration.id)
        ).all()
    )


def list_integrations(db_session: Session) -> list[Integration]:
    return list(db_session.scalars(select(Integration).order_by(Integration.id)).all())


def get_mcp_server_for_integration(
    integration_id: int, db_session: Session
) -> MCPServer | None:
    return db_session.scalar(
        select(MCPServer)
        .join(Integration, Integration.mcp_server_id == MCPServer.id)
        .where(Integration.id == integration_id)
    )


def get_external_app_for_integration(
    integration_id: int, db_session: Session
) -> ExternalApp | None:
    return db_session.scalar(
        select(ExternalApp)
        .join(Integration, Integration.external_app_id == ExternalApp.id)
        .where(Integration.id == integration_id)
    )


def _enabled(integration_id: int | None) -> ColumnElement[bool]:
    enabled = Integration.enabled.is_(True)
    if integration_id is None:
        return enabled
    return and_(enabled, Integration.id == integration_id)


def list_enabled_mcp_server_urls(
    db_session: Session, integration_id: int | None = None
) -> list[tuple[int, str]]:
    """``(integration_id, server_url)`` of each enabled MCP integration, or of
    only ``integration_id``."""
    return list(
        db_session.execute(
            select(Integration.id, MCPServer.server_url)
            .join(MCPServer, MCPServer.id == Integration.mcp_server_id)
            .where(_enabled(integration_id))
            .order_by(Integration.id)
        ).tuples()
    )


def list_enabled_openapi_schemas(
    db_session: Session, integration_id: int | None = None
) -> list[tuple[int, dict[str, Any] | None]]:
    """``(integration_id, openapi_schema)`` of each enabled OpenAPI integration,
    or of only ``integration_id``."""
    return list(
        db_session.execute(
            select(Integration.id, Tool.openapi_schema)
            .join(Tool, Tool.id == Integration.tool_id)
            .where(_enabled(integration_id))
            .order_by(Integration.id)
        ).tuples()
    )


def list_enabled_external_apps(
    db_session: Session, integration_id: int | None = None
) -> list[tuple[int, ExternalApp]]:
    """``(integration_id, external_app)`` of each enabled preset or custom app,
    or of only ``integration_id``."""
    return list(
        db_session.execute(
            select(Integration.id, ExternalApp)
            .join(ExternalApp, ExternalApp.id == Integration.external_app_id)
            .where(_enabled(integration_id))
            .order_by(Integration.id)
        ).tuples()
    )


def get_openapi_tool_for_integration(
    integration_id: int, db_session: Session
) -> Tool | None:
    return db_session.scalar(
        select(Tool)
        .join(Integration, Integration.tool_id == Tool.id)
        .where(
            Integration.id == integration_id,
            Tool.openapi_schema.is_not(None),
        )
    )


def get_integration_by_kind_row(
    kind_row_id: InstrumentedAttribute[int | None], row_id: int, db_session: Session
) -> Integration | None:
    """The integration of a kind row, such as ``Integration.mcp_server_id``."""
    return db_session.scalar(select(Integration).where(kind_row_id == row_id))


def _openapi_tools_with_integration() -> Select[
    tuple[Tool, Integration, IntegrationConnection]
]:
    return (
        select(Tool, Integration, IntegrationConnection)
        .join(Integration, Integration.tool_id == Tool.id)
        .outerjoin(
            IntegrationConnection,
            (IntegrationConnection.integration_id == Integration.id)
            & IntegrationConnection.user_id.is_(None),
        )
        .where(Tool.openapi_schema.is_not(None))
    )


def list_openapi_tools_with_integration(
    db_session: Session,
) -> list[tuple[Tool, Integration, IntegrationConnection | None]]:
    """Each OpenAPI tool with its integration and organization connection."""
    return [
        (tool, integration, organization)
        for tool, integration, organization in db_session.execute(
            _openapi_tools_with_integration().order_by(Tool.id)
        ).tuples()
    ]


def get_openapi_tool_with_integration(
    tool_id: int, db_session: Session
) -> tuple[Tool, Integration, IntegrationConnection | None] | None:
    row = db_session.execute(
        _openapi_tools_with_integration().where(Tool.id == tool_id)
    ).one_or_none()
    return (row[0], row[1], row[2]) if row is not None else None


def list_integration_actions(
    integration_id: int, db_session: Session
) -> list[IntegrationAction]:
    return list(
        db_session.scalars(
            select(IntegrationAction)
            .where(IntegrationAction.integration_id == integration_id)
            .order_by(IntegrationAction.id)
        ).all()
    )


def count_integration_actions(
    integration_ids: Collection[int], db_session: Session
) -> dict[int, int]:
    counts = dict.fromkeys(integration_ids, 0)
    if not integration_ids:
        return counts
    for integration_id, count in db_session.execute(
        select(IntegrationAction.integration_id, func.count())
        .where(IntegrationAction.integration_id.in_(integration_ids))
        .group_by(IntegrationAction.integration_id)
    ).tuples():
        counts[integration_id] = count
    return counts


def list_action_summaries(
    integration_ids: Collection[int], db_session: Session
) -> dict[int, list[IntegrationAction]]:
    """The actions of each integration with only the columns a view shows,
    in action order."""
    actions: dict[int, list[IntegrationAction]] = {
        integration_id: [] for integration_id in integration_ids
    }
    if not integration_ids:
        return actions
    for action in db_session.scalars(
        select(IntegrationAction)
        .options(
            load_only(
                IntegrationAction.integration_id,
                IntegrationAction.key,
                IntegrationAction.display_name,
                IntegrationAction.description,
                IntegrationAction.read_only,
                IntegrationAction.default_policy,
            )
        )
        .where(IntegrationAction.integration_id.in_(integration_ids))
        .order_by(IntegrationAction.id)
    ):
        actions[action.integration_id].append(action)
    return actions


def list_external_app_types(
    integration_ids: Collection[int], db_session: Session
) -> dict[int, ExternalAppType]:
    """The app type of each integration that has an ``external_app`` row."""
    if not integration_ids:
        return {}
    return dict(
        db_session.execute(
            select(Integration.id, ExternalApp.app_type)
            .join(ExternalApp, ExternalApp.id == Integration.external_app_id)
            .where(Integration.id.in_(integration_ids))
        )
        .tuples()
        .all()
    )


def _apply_spec(action: IntegrationAction, spec: IntegrationActionSpec) -> None:
    action.source = spec.source
    action.display_name = spec.display_name
    action.description = spec.description
    action.read_only = spec.read_only
    action.default_policy = spec.default_policy
    action.input_schema = spec.input_schema
    action.output_schema = spec.output_schema
    action.http_method = spec.http_method
    action.path_template = spec.path_template


def lock_integration__no_commit(integration_id: int, db_session: Session) -> None:
    """Locks the integration row, then expires the session, so the reads that
    follow see what other transactions committed before the lock."""
    db_session.flush()
    db_session.execute(
        select(Integration.id).where(Integration.id == integration_id).with_for_update()
    )
    db_session.expire_all()


def replace_integration_actions__no_commit(
    integration_id: int,
    source: IntegrationActionSource,
    specs: Sequence[IntegrationActionSpec],
    db_session: Session,
) -> None:
    """Locks the integration row, so two syncs of one integration run one at a
    time. If two specs have the same key, the first one wins."""
    db_session.execute(
        select(Integration.id).where(Integration.id == integration_id).with_for_update()
    )
    existing_by_key = {
        action.key: action
        for action in list_integration_actions(integration_id, db_session)
    }

    kept_keys: set[str] = set()
    for spec in specs:
        if spec.key in kept_keys:
            continue
        kept_keys.add(spec.key)
        existing = existing_by_key.get(spec.key)
        if existing is not None:
            _apply_spec(existing, spec)
            continue
        db_session.add(
            IntegrationAction(
                integration_id=integration_id,
                key=spec.key,
                source=spec.source,
                display_name=spec.display_name,
                description=spec.description,
                read_only=spec.read_only,
                default_policy=spec.default_policy,
                input_schema=spec.input_schema,
                output_schema=spec.output_schema,
                http_method=spec.http_method,
                path_template=spec.path_template,
            )
        )

    stale_ids = [
        action.id
        for key, action in existing_by_key.items()
        if action.source == source and key not in kept_keys
    ]
    if stale_ids:
        db_session.execute(
            delete(IntegrationAction)
            .where(IntegrationAction.id.in_(stale_ids))
            .execution_options(synchronize_session="fetch")
        )
    db_session.flush()


def list_integration_plugin_rows(
    integration_ids: Collection[int], db_session: Session
) -> dict[int, list[IntegrationPluginRow]]:
    """The plugins that hold each integration, in plugin name order. The
    install setting falls back to the marketplace default."""
    rows: dict[int, list[IntegrationPluginRow]] = {
        integration_id: [] for integration_id in integration_ids
    }
    if not integration_ids:
        return rows
    owner_email: KeyedColumnElement[str] = User.__table__.c.email
    for (
        integration_id,
        plugin_id,
        name,
        description,
        kind,
        author_user_id,
        email,
        policy,
        default_policy,
    ) in db_session.execute(
        select(
            Plugin__Integration.integration_id,
            Plugin.id,
            Plugin.name,
            Plugin.description,
            Marketplace.kind,
            Plugin.author_user_id,
            owner_email,
            Plugin.installation_policy,
            Marketplace.default_installation_policy,
        )
        .join(Plugin, Plugin.id == Plugin__Integration.plugin_id)
        .join(Marketplace, Marketplace.id == Plugin.marketplace_id)
        .outerjoin(User, User.__table__.c.id == Plugin.author_user_id)
        .where(Plugin__Integration.integration_id.in_(integration_ids))
        .order_by(Plugin.name, Plugin.id)
    ).tuples():
        in_library = kind == MarketplaceKind.ORGANIZATION_LIBRARY
        rows[integration_id].append(
            IntegrationPluginRow(
                integration_id=integration_id,
                plugin_id=plugin_id,
                plugin_name=name,
                plugin_description=description,
                in_organization_library=in_library,
                author_user_id=author_user_id,
                owner_email=None if in_library else email,
                installation_policy=policy or default_policy,
            )
        )
    return rows


def list_integrations_by_ids(
    integration_ids: Collection[int], db_session: Session
) -> list[Integration]:
    if not integration_ids:
        return []
    return list(
        db_session.scalars(
            select(Integration)
            .where(Integration.id.in_(integration_ids))
            .order_by(Integration.id)
        ).all()
    )


def list_integration_ids_held_by_plugins(
    plugin_ids: Select[tuple[UUID]] | Collection[UUID], db_session: Session
) -> list[int]:
    return list(
        db_session.scalars(
            select(Plugin__Integration.integration_id)
            .where(Plugin__Integration.plugin_id.in_(plugin_ids))
            .distinct()
            .order_by(Plugin__Integration.integration_id)
        ).all()
    )


def plugin_holds_integration(plugin_id: UUID, db_session: Session) -> bool:
    return (
        db_session.scalar(
            select(Plugin__Integration.integration_id)
            .where(Plugin__Integration.plugin_id == plugin_id)
            .limit(1)
        )
        is not None
    )


def lock_integration(integration_id: int, db_session: Session) -> Integration | None:
    return db_session.scalars(
        select(Integration).where(Integration.id == integration_id).with_for_update()
    ).one_or_none()


def insert_integration__no_commit(
    *,
    name: str,
    description: str | None,
    created_by_user_id: UUID | None,
    auth_mode: IntegrationAuthMode,
    auth_method: IntegrationAuthMethod | None,
    credential_fields: list[dict[str, Any]] | None,
    header_template: dict[str, str] | None,
    mcp_server_id: int | None = None,
    external_app_id: int | None = None,
    tool_id: int | None = None,
    db_session: Session,
) -> Integration:
    """Insert the integration of a kind row. Exactly one kind row id is set."""
    integration = Integration(
        kind=IntegrationKind.MCP if mcp_server_id is not None else IntegrationKind.API,
        mcp_server_id=mcp_server_id,
        external_app_id=external_app_id,
        tool_id=tool_id,
        name=name,
        description=description,
        created_by_user_id=created_by_user_id,
        auth_mode=auth_mode,
        auth_method=auth_method,
        credential_fields=credential_fields,
        header_template=header_template,
    )
    db_session.add(integration)
    db_session.flush()
    return integration


def rename_kind_row__no_commit(
    integration: Integration, name: str, db_session: Session
) -> None:
    """The kind rows keep a copy of the name, which the Craft prompt shows."""
    if integration.mcp_server_id is not None:
        db_session.execute(
            update(MCPServer)
            .where(MCPServer.id == integration.mcp_server_id)
            .values(name=name)
        )
    if integration.tool_id is not None:
        db_session.execute(
            update(Tool)
            .where(Tool.id == integration.tool_id)
            .values(name=name, display_name=name)
        )
    if integration.external_app_id is not None:
        db_session.execute(
            update(ExternalApp)
            .where(ExternalApp.id == integration.external_app_id)
            .values(name=name)
        )


def create_mcp_server_row__no_commit(
    *,
    name: str,
    description: str | None,
    owner_email: str,
    server_url: str,
    transport: MCPTransport,
    db_session: Session,
) -> MCPServer:
    """The kind row of an MCP integration. ``owner`` and ``name`` are old
    copies that the table requires."""
    server = MCPServer(
        owner=owner_email,
        name=name,
        description=description,
        server_url=server_url,
        transport=transport,
    )
    db_session.add(server)
    db_session.flush()
    return server


def create_openapi_tool_row__no_commit(
    *,
    name: str,
    description: str | None,
    user_id: UUID | None,
    openapi_spec: dict[str, Any],
    db_session: Session,
) -> Tool:
    tool = Tool(
        name=name,
        description=description,
        display_name=name,
        in_code_tool_id=None,
        openapi_schema=openapi_spec,
        custom_headers=[],
        user_id=user_id,
        passthrough_auth=False,
        enabled=True,
    )
    db_session.add(tool)
    db_session.flush()
    return tool


def create_external_app_row__no_commit(
    *,
    name: str,
    app_type: ExternalAppType,
    upstream_url_patterns: list[str],
    auth_template: dict[str, str],
    db_session: Session,
) -> ExternalApp:
    """The kind row of a preset or custom app. Its URL patterns are the kind
    setting. The OAuth client holds the client and the host settings of a
    preset."""
    app = ExternalApp(
        name=name,
        app_type=app_type,
        upstream_url_patterns=upstream_url_patterns,
        auth_template=auth_template,
    )
    db_session.add(app)
    db_session.flush()
    return app


def upsert_oauth_client__no_commit(
    *,
    integration_id: int,
    provider_mode: IntegrationOAuthProviderMode,
    authorization_url: str | None,
    token_url: str | None,
    scopes: list[str] | None,
    additional_params: dict[str, str] | None,
    pkce: bool | None,
    client_id: str | None,
    client_secret: str | None | UnsetType,
    db_session: Session,
) -> IntegrationOAuthClient:
    """Write the OAuth client in the new format. An unset ``client_secret``
    keeps the stored one. A new client id drops the registration of the old
    one. A row in an old format keeps its client and registration."""
    oauth_client = db_session.get(IntegrationOAuthClient, integration_id)
    if oauth_client is None:
        oauth_client = IntegrationOAuthClient(
            integration_id=integration_id, provider_mode=provider_mode
        )
        db_session.add(oauth_client)
    stored = read_oauth_client(oauth_client)
    legacy = oauth_client.legacy_format is not None
    oauth_client.provider_mode = provider_mode
    oauth_client.authorization_url = authorization_url
    oauth_client.token_url = token_url
    oauth_client.scopes = scopes
    oauth_client.additional_params = additional_params
    oauth_client.pkce = pkce
    if client_id != stored.client_id:
        oauth_client.client_id = client_id  # ty: ignore[invalid-assignment]
        oauth_client.registration = None
    elif legacy:
        oauth_client.client_id = client_id  # ty: ignore[invalid-assignment]
        oauth_client.registration = stored.registration or None  # ty: ignore[invalid-assignment]
    if is_set(client_secret):
        oauth_client.client_secret = client_secret  # ty: ignore[invalid-assignment]
    elif legacy:
        oauth_client.client_secret = stored.client_secret  # ty: ignore[invalid-assignment]
    oauth_client.legacy_format = None
    db_session.flush()
    return oauth_client


def delete_oauth_client__no_commit(integration_id: int, db_session: Session) -> None:
    db_session.execute(
        delete(IntegrationOAuthClient)
        .where(IntegrationOAuthClient.integration_id == integration_id)
        .execution_options(synchronize_session="fetch")
    )


def delete_integration__no_commit(
    integration: Integration, db_session: Session
) -> None:
    """Delete the integration and then its kind row. The connections,
    actions, policies, OAuth client and plugin links go by cascade. A plugin
    that held only this integration and no skill goes too."""
    other_link = aliased(Plugin__Integration)
    other_integration = (
        select(other_link.integration_id)
        .where(
            other_link.plugin_id == Plugin.id,
            other_link.integration_id != integration.id,
        )
        .exists()
    )
    any_skill = (
        select(PluginSkill.id)
        .join(PluginVersion, PluginVersion.id == PluginSkill.plugin_version_id)
        .where(PluginVersion.plugin_id == Plugin.id)
        .exists()
    )
    emptied_plugin_ids = list(
        db_session.scalars(
            select(Plugin.id)
            .join(Plugin__Integration, Plugin__Integration.plugin_id == Plugin.id)
            .where(
                Plugin__Integration.integration_id == integration.id,
                ~other_integration,
                ~any_skill,
            )
        ).all()
    )
    mcp_server_id = integration.mcp_server_id
    tool_id = integration.tool_id
    external_app_id = integration.external_app_id
    db_session.delete(integration)
    db_session.flush()
    server = db_session.get(MCPServer, mcp_server_id) if mcp_server_id else None
    if server is not None:
        db_session.delete(server)
    tool = db_session.get(Tool, tool_id) if tool_id else None
    if tool is not None:
        db_session.delete(tool)
    if external_app_id is not None:
        delete_external_app__no_commit(db_session, external_app_id)
    db_session.flush()
    if emptied_plugin_ids:
        db_session.execute(
            delete(Plugin)
            .where(Plugin.id.in_(emptied_plugin_ids))
            .execution_options(synchronize_session="fetch")
        )
        db_session.flush()


def set_policy_rows__no_commit(
    *,
    integration_id: int,
    user_id: UUID | None,
    values: Mapping[str, IntegrationActionPolicyValue | None],
    db_session: Session,
) -> None:
    """Write the admin rows (``user_id`` None) or the rows of one user, by
    action key. None deletes the row. The empty key is the default row."""
    owner = (
        IntegrationActionPolicy.user_id.is_(None)
        if user_id is None
        else IntegrationActionPolicy.user_id == user_id
    )
    stored = {
        row.action: row
        for row in db_session.scalars(
            select(IntegrationActionPolicy).where(
                IntegrationActionPolicy.integration_id == integration_id, owner
            )
        ).all()
    }
    for action, value in values.items():
        row = stored.get(action)
        if value is None:
            if row is not None:
                db_session.delete(row)
        elif row is None:
            db_session.add(
                IntegrationActionPolicy(
                    integration_id=integration_id,
                    action=action,
                    user_id=user_id,
                    policy=value,
                )
            )
        elif row.policy != value:
            row.policy = value
    db_session.flush()
