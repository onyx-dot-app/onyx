import datetime
from uuid import UUID

from sqlalchemy import Select, and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased
from sqlalchemy.orm.attributes import flag_modified

from onyx.auth.permissions import has_global_permission
from onyx.db.constants import UNSET, UnsetType
from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPOAuthProviderMode,
    MCPServerStatus,
    MCPTransport,
    Permission,
)
from onyx.db.models import (
    GatedApp,
    MCPAuthenticationType,
    MCPConnectionConfig,
    MCPServer,
    MCPServer__User,
    MCPServer__UserGroup,
    MCPServerUserPreference,
    Tool,
    User,
    User__UserGroup,
)
from onyx.server.features.mcp.models import MCPConnectionData
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_mcp_server_user_preferences(
    server_ids: list[int], user_id: UUID, db_session: Session
) -> dict[int, MCPServerUserPreference]:
    if not server_ids:
        return {}
    return {
        preference.mcp_server_id: preference
        for preference in db_session.scalars(
            select(MCPServerUserPreference).where(
                MCPServerUserPreference.user_id == user_id,
                MCPServerUserPreference.mcp_server_id.in_(server_ids),
            )
        )
    }


# MCPServer operations


def get_mcp_server_by_id(
    server_id: int, db_session: Session, *, for_update: bool = False
) -> MCPServer:
    """Get a server, optionally locking it for an atomic configuration update."""
    stmt = select(MCPServer).where(MCPServer.id == server_id)
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    server = db_session.scalar(stmt)
    if not server:
        raise ValueError("MCP server by specified id does not exist")
    return server


def _add_mcp_server_access_filter(stmt: Select, user: User) -> Select:
    """Servers the user may add to an agent (public / direct / group). Admins bypass.
    Default Chat also uses these grants; custom-agent attachments do not.
    """
    if has_global_permission(user, Permission.FULL_ADMIN_PANEL_ACCESS):
        return stmt

    stmt = stmt.distinct()
    MCPServer__UG = aliased(MCPServer__UserGroup)
    stmt = (
        stmt.outerjoin(MCPServer__UG, MCPServer__UG.mcp_server_id == MCPServer.id)
        .outerjoin(
            User__UserGroup,
            User__UserGroup.user_group_id == MCPServer__UG.user_group_id,
        )
        .outerjoin(MCPServer__User, MCPServer__User.mcp_server_id == MCPServer.id)
    )

    where_clause = MCPServer.is_public == True  # noqa: E712
    if not user.is_anonymous:
        where_clause |= User__UserGroup.user_id == user.id
        where_clause |= MCPServer__User.user_id == user.id
        # The curator who created a private server must still see/attach it.
        where_clause |= MCPServer.owner == user.email
    return stmt.where(where_clause)


def get_mcp_servers_accessible_to_user(
    user: User, db_session: Session, *, server_ids: set[int] | None = None
) -> list[MCPServer]:
    """MCP servers the user may attach to personas (public, or shared with them)."""
    stmt = select(MCPServer).order_by(MCPServer.created_at)
    if server_ids is not None:
        stmt = stmt.where(MCPServer.id.in_(server_ids))
    return list(db_session.scalars(_add_mcp_server_access_filter(stmt, user)).all())


def user_can_access_mcp_server(user: User, server_id: int, db_session: Session) -> bool:
    """Whether the user may add this server's tools to an agent."""
    stmt = _add_mcp_server_access_filter(
        select(MCPServer.id).where(MCPServer.id == server_id), user
    )
    return db_session.scalar(stmt) is not None


def make_mcp_server_private(
    server_id: int,  # noqa: ARG001
    user_ids: list[UUID] | None,
    group_ids: list[int] | None,
    db_session: Session,  # noqa: ARG001
) -> None:
    """MIT no-op stub. The EE override reconciles the user/group access rows.
    Raises if restriction is requested, mirroring `make_doc_set_private`."""
    # May cause error if someone switches down to MIT from EE
    if user_ids or group_ids:
        raise NotImplementedError(
            "Onyx MIT does not support restricting MCP servers to users/groups"
        )


def get_mcp_tools_for_servers(server_ids: list[int], db_session: Session) -> list[Tool]:
    """All MCP tools across ``server_ids`` in a single query"""
    if not server_ids:
        return []
    return list(
        db_session.scalars(select(Tool).where(Tool.mcp_server_id.in_(server_ids))).all()
    )


# MCPConnectionConfig operations
def get_connection_config_by_id(
    config_id: int, db_session: Session, *, for_update: bool = False
) -> MCPConnectionConfig:
    """Get connection config by ID. ``for_update`` row-locks the config so a
    read-compare-write over its JSON blob is atomic against concurrent writers."""
    stmt = select(MCPConnectionConfig).where(MCPConnectionConfig.id == config_id)
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    config = db_session.scalar(stmt)
    if not config:
        raise ValueError("Connection config by specified id does not exist")
    return config


def get_user_connection_config(
    server_id: int, user_email: str, db_session: Session
) -> MCPConnectionConfig | None:
    """Get a user's connection config for a specific MCP server"""
    return db_session.scalar(
        select(MCPConnectionConfig).where(
            and_(
                MCPConnectionConfig.mcp_server_id == server_id,
                MCPConnectionConfig.user_email == user_email,
            )
        )
    )


def get_user_connection_configs(
    server_ids: list[int], user_email: str, db_session: Session
) -> dict[int, MCPConnectionConfig]:
    """`user_email`'s own connection configs for `server_ids`, keyed by server id.
    One query, for callers resolving credentials across many servers."""
    if not server_ids:
        return {}
    rows = db_session.scalars(
        select(MCPConnectionConfig).where(
            and_(
                MCPConnectionConfig.mcp_server_id.in_(server_ids),
                MCPConnectionConfig.user_email == user_email,
            )
        )
    )
    return {row.mcp_server_id: row for row in rows if row.mcp_server_id is not None}


def update_connection_config(
    config_id: int,
    db_session: Session,
    config_data: MCPConnectionData | None = None,
) -> MCPConnectionConfig:
    """Update an existing connection config"""
    config = update_connection_config__no_commit(config_id, db_session, config_data)
    db_session.commit()
    return config


def update_connection_config__no_commit(
    config_id: int,
    db_session: Session,
    config_data: MCPConnectionData | None = None,
) -> MCPConnectionConfig:
    """Update a connection config without owning the transaction."""
    config = get_connection_config_by_id(config_id, db_session)

    if config_data is not None:
        config.config = config_data  # ty: ignore[invalid-assignment]
        flag_modified(config, "config")

    db_session.flush()
    return config


def create_mcp_server__no_commit(
    owner_email: str,
    name: str,
    description: str | None,
    server_url: str,
    auth_type: MCPAuthenticationType | None,
    transport: MCPTransport | None,
    auth_performer: MCPAuthenticationPerformer | None,
    db_session: Session,
    oauth_provider_mode: MCPOAuthProviderMode = MCPOAuthProviderMode.AUTO_DISCOVERY,
    oauth_authorization_endpoint: str | None = None,
    oauth_token_endpoint: str | None = None,
    oauth_scopes_override: list[str] | None = None,
    oauth_additional_auth_params: dict[str, str] | None = None,
    oauth_cimd_enabled: bool = True,
    admin_connection_config_id: int | None = None,
    is_public: bool = True,
    available_in_craft: bool = False,
) -> MCPServer:
    """Create a new MCP server"""
    new_server = MCPServer(
        owner=owner_email,
        name=name,
        description=description,
        server_url=server_url,
        transport=transport,
        auth_type=auth_type,
        auth_performer=auth_performer,
        oauth_provider_mode=oauth_provider_mode,
        oauth_authorization_endpoint=oauth_authorization_endpoint,
        oauth_token_endpoint=oauth_token_endpoint,
        oauth_scopes_override=oauth_scopes_override,
        oauth_additional_auth_params=oauth_additional_auth_params,
        oauth_cimd_enabled=oauth_cimd_enabled,
        admin_connection_config_id=admin_connection_config_id,
        is_public=is_public,
        available_in_craft=available_in_craft,
    )
    db_session.add(new_server)
    db_session.flush()  # Get the ID without committing
    db_session.add(GatedApp(mcp_server_id=new_server.id))
    db_session.flush()
    return new_server


def update_mcp_server__no_commit(
    server_id: int,
    db_session: Session,
    name: str | None = None,
    description: str | None = None,
    server_url: str | None = None,
    auth_type: MCPAuthenticationType | None = None,
    admin_connection_config_id: int | None = None,
    auth_performer: MCPAuthenticationPerformer | None = None,
    oauth_provider_mode: MCPOAuthProviderMode | None = None,
    oauth_authorization_endpoint: str | None | UnsetType = UNSET,
    oauth_token_endpoint: str | None | UnsetType = UNSET,
    oauth_scopes_override: list[str] | None | UnsetType = UNSET,
    oauth_additional_auth_params: dict[str, str] | None | UnsetType = UNSET,
    oauth_cimd_enabled: bool | None = None,
    transport: MCPTransport | None = None,
    status: MCPServerStatus | None = None,
    last_refreshed_at: datetime.datetime | None = None,
    is_public: bool | None = None,
    available_in_craft: bool | None = None,
) -> MCPServer:
    """Update an existing MCP server"""
    server = get_mcp_server_by_id(server_id, db_session)

    if is_public is not None:
        server.is_public = is_public
    if name is not None:
        server.name = name
    if description is not None:
        server.description = description
    if server_url is not None:
        server.server_url = server_url
    if auth_type is not None:
        server.auth_type = auth_type
    if admin_connection_config_id is not None:
        server.admin_connection_config_id = admin_connection_config_id
    if auth_performer is not None:
        server.auth_performer = auth_performer
    if oauth_provider_mode is not None:
        server.oauth_provider_mode = oauth_provider_mode
    if not isinstance(oauth_authorization_endpoint, UnsetType):
        server.oauth_authorization_endpoint = oauth_authorization_endpoint
    if not isinstance(oauth_token_endpoint, UnsetType):
        server.oauth_token_endpoint = oauth_token_endpoint
    if not isinstance(oauth_scopes_override, UnsetType):
        server.oauth_scopes_override = oauth_scopes_override
    if not isinstance(oauth_additional_auth_params, UnsetType):
        server.oauth_additional_auth_params = oauth_additional_auth_params
    if oauth_cimd_enabled is not None:
        server.oauth_cimd_enabled = oauth_cimd_enabled
    if transport is not None:
        server.transport = transport
    if status is not None:
        server.status = status
    if last_refreshed_at is not None:
        server.last_refreshed_at = last_refreshed_at
    if available_in_craft is not None:
        server.available_in_craft = available_in_craft

    db_session.flush()  # Don't commit yet, let caller decide when to commit
    return server


def create_connection_config(
    config_data: MCPConnectionData,
    db_session: Session,
    mcp_server_id: int | None = None,
    user_email: str = "",
) -> MCPConnectionConfig:
    """Create a new connection config"""
    new_config = MCPConnectionConfig(
        mcp_server_id=mcp_server_id,
        user_email=user_email,
        config=config_data,
    )
    db_session.add(new_config)
    db_session.flush()  # Don't commit yet, let caller decide when to commit
    return new_config


def upsert_mcp_server_user_preferences__no_commit(
    server_id: int,
    user_id: UUID,
    db_session: Session,
    *,
    enabled_in_chat: bool | None = None,
    enabled_in_craft: bool | None = None,
) -> MCPServerUserPreference:
    values: dict[str, bool] = {}
    if enabled_in_chat is not None:
        values["enabled_in_chat"] = enabled_in_chat
    if enabled_in_craft is not None:
        values["enabled_in_craft"] = enabled_in_craft
    if not values:
        raise ValueError("At least one preference is required")
    stmt = insert(MCPServerUserPreference).values(
        user_id=user_id, mcp_server_id=server_id, **values
    )
    return db_session.scalars(
        stmt.on_conflict_do_update(
            index_elements=[
                MCPServerUserPreference.user_id,
                MCPServerUserPreference.mcp_server_id,
            ],
            set_=values,
        ).returning(MCPServerUserPreference),
        execution_options={"populate_existing": True},
    ).one()
