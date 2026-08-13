import datetime
from collections.abc import Mapping
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, and_, delete, select
from sqlalchemy.orm import Session, aliased, selectinload
from sqlalchemy.orm.attributes import flag_modified

from onyx.db.constants import UNSET, UnsetType
from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPOAuthProviderMode,
    MCPServerStatus,
    MCPTransport,
    SandboxStatus,
)
from onyx.db.models import (
    MCPAuthenticationType,
    MCPConnectionConfig,
    MCPServer,
    MCPServer__User,
    MCPServer__UserGroup,
    Persona,
    Sandbox,
    Tool,
    User,
    User__UserGroup,
    UserRole,
)
from onyx.server.features.mcp.models import (
    DENYLISTED_MCP_HEADERS,
    MCPAuthTemplate,
    MCPConnectionData,
    MCPOAuthKeys,
    mcp_oauth_reauth_required,
    merge_mcp_headers,
)
from onyx.utils.logger import setup_logger
from onyx.utils.sensitive import SensitiveValue

logger = setup_logger()


# MCPServer operations
def get_all_mcp_servers(db_session: Session) -> list[MCPServer]:
    """Get all MCP servers"""
    return list(
        db_session.scalars(select(MCPServer).order_by(MCPServer.created_at)).all()
    )


def get_mcp_server_by_id(server_id: int, db_session: Session) -> MCPServer:
    """Get MCP server by ID"""
    server = db_session.scalar(select(MCPServer).where(MCPServer.id == server_id))
    if not server:
        raise ValueError("MCP server by specified id does not exist")
    return server


def get_mcp_servers_by_owner(owner_email: str, db_session: Session) -> list[MCPServer]:
    """Get all MCP servers owned by a specific user"""
    return list(
        db_session.scalars(
            select(MCPServer).where(MCPServer.owner == owner_email)
        ).all()
    )


def get_craft_enabled_mcp_servers(
    db_session: Session, user: User | None
) -> list[MCPServer]:
    """MCP servers an admin has made available to the Craft agent, filtered to
    those ``user`` may use (public / shared / owned). ``None`` skips the access
    filter — only for host matching before a user is known (proxy claim path).

    Eager-loads ``admin_connection_config`` so credential resolution across the
    returned set doesn't lazy-load one row per admin-managed server."""
    stmt = (
        select(MCPServer)
        .where(MCPServer.available_in_craft.is_(True))
        .options(selectinload(MCPServer.admin_connection_config))
    )
    if user is not None:
        stmt = _add_mcp_server_access_filter(stmt, user)
    return list(db_session.scalars(stmt).all())


def get_mcp_servers_for_persona(
    persona_id: int,
    db_session: Session,
    user: User,  # noqa: ARG001
) -> list[MCPServer]:
    """Servers already on a persona's tools. No attach ACL — chat users of the
    persona must see/auth these. ``user`` is for callers enforcing persona visibility.
    """
    # Get the persona and its tools
    persona = db_session.query(Persona).filter(Persona.id == persona_id).first()
    if not persona:
        return []

    # Collect unique MCP server IDs from the persona's tools
    mcp_server_ids = set()
    for tool in persona.tools:
        if tool.mcp_server_id:
            mcp_server_ids.add(tool.mcp_server_id)

    if not mcp_server_ids:
        return []

    # Fetch the MCP servers
    mcp_servers = (
        db_session.query(MCPServer).filter(MCPServer.id.in_(mcp_server_ids)).all()
    )

    return list(mcp_servers)


def _add_mcp_server_access_filter(stmt: Select, user: User) -> Select:
    """Servers the user may add to an agent (public / direct / group). Admins bypass.
    Does not control chat use of agent-attached servers.
    """
    if user.role == UserRole.ADMIN:
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
    user: User, db_session: Session
) -> list[MCPServer]:
    """MCP servers the user may attach to personas (public, or shared with them)."""
    stmt = _add_mcp_server_access_filter(
        select(MCPServer).order_by(MCPServer.created_at), user
    )
    return list(db_session.scalars(stmt).all())


def user_can_access_mcp_server(user: User, server_id: int, db_session: Session) -> bool:
    """Whether the user may add this server's tools to an agent."""
    stmt = _add_mcp_server_access_filter(
        select(MCPServer.id).where(MCPServer.id == server_id), user
    )
    return db_session.scalar(stmt) is not None


def affected_user_ids_for_mcp_server(
    server: MCPServer, db_session: Session
) -> set[UUID]:
    """User IDs with a RUNNING sandbox whose Craft session should be reloaded
    after this server changes (enabled/disabled for craft, tools toggled, URL
    edited). Scoped to running sandboxes so the hot-reload push has somewhere to
    land. Access must match what ``resolve_craft_mcp_servers`` bakes into a
    session: public / group / direct / owner, plus admins (who bypass the access
    filter in ``_add_mcp_server_access_filter`` and therefore see every
    craft-enabled server)."""
    stmt = select(Sandbox.user_id).where(Sandbox.status == SandboxStatus.RUNNING)
    if server.is_public:
        return set(db_session.scalars(stmt))

    group_users = (
        select(User__UserGroup.user_id)
        .join(
            MCPServer__UserGroup,
            MCPServer__UserGroup.user_group_id == User__UserGroup.user_group_id,
        )
        .where(MCPServer__UserGroup.mcp_server_id == server.id)
    )
    direct_users = select(MCPServer__User.user_id).where(
        MCPServer__User.mcp_server_id == server.id
    )
    owner_users = select(User.id).where(  # ty: ignore[no-matching-overload]
        User.email == server.owner
    )
    # Admins see every craft-enabled server (ACL bypass), so any change to a
    # private server can be baked into an admin's session and must reload it.
    admin_users = select(User.id).where(  # ty: ignore[no-matching-overload]
        User.role == UserRole.ADMIN
    )
    stmt = stmt.where(
        Sandbox.user_id.in_(group_users)
        | Sandbox.user_id.in_(direct_users)
        | Sandbox.user_id.in_(owner_users)
        | Sandbox.user_id.in_(admin_users)
    )
    return set(db_session.scalars(stmt))


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
    admin_connection_config_id: int | None = None,
    is_public: bool = True,
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
        admin_connection_config_id=admin_connection_config_id,
        is_public=is_public,
    )
    db_session.add(new_server)
    db_session.flush()  # Get the ID without committing
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


def delete_mcp_server(server_id: int, db_session: Session) -> None:
    """Delete an MCP server and all associated tools (via CASCADE)"""
    server = get_mcp_server_by_id(server_id, db_session)

    # Count tools that will be deleted
    tools_count = db_session.query(Tool).filter(Tool.mcp_server_id == server_id).count()
    logger.info(
        "Deleting MCP server %s with %s associated tools", server_id, tools_count
    )

    db_session.delete(server)
    db_session.commit()

    logger.info("Successfully deleted MCP server %s and its tools", server_id)


def get_all_mcp_tools_for_server(server_id: int, db_session: Session) -> list[Tool]:
    """Get all MCP tools for a server"""
    return list(
        db_session.scalars(select(Tool).where(Tool.mcp_server_id == server_id)).all()
    )


def get_mcp_tools_for_servers(server_ids: list[int], db_session: Session) -> list[Tool]:
    """All MCP tools across ``server_ids`` in a single query"""
    if not server_ids:
        return []
    return list(
        db_session.scalars(select(Tool).where(Tool.mcp_server_id.in_(server_ids))).all()
    )


def add_user_to_mcp_server(server_id: int, user_id: UUID, db_session: Session) -> None:
    """Grant a user access to an MCP server"""
    server = get_mcp_server_by_id(server_id, db_session)
    user = db_session.scalar(
        select(User).where(User.id == user_id)  # ty: ignore[invalid-argument-type]
    )
    if not user:
        raise ValueError("User not found")

    if user not in server.users:
        server.users.append(user)
        db_session.commit()


def remove_user_from_mcp_server(
    server_id: int, user_id: UUID, db_session: Session
) -> None:
    """Remove a user's access to an MCP server"""
    server = get_mcp_server_by_id(server_id, db_session)
    user = db_session.scalar(
        select(User).where(User.id == user_id)  # ty: ignore[invalid-argument-type]
    )
    if not user:
        raise ValueError("User not found")

    if user in server.users:
        server.users.remove(user)
        db_session.commit()


# MCPConnectionConfig operations
def extract_connection_data(
    config: MCPConnectionConfig | None, apply_mask: bool = False
) -> MCPConnectionData:
    """Extract MCPConnectionData from a connection config, with proper typing.

    This helper encapsulates the cast from the JSON column's dict[str, Any]
    to the typed MCPConnectionData structure.
    """
    if config is None or config.config is None:
        return MCPConnectionData(headers={})
    if isinstance(config.config, SensitiveValue):
        return cast(MCPConnectionData, config.config.get_value(apply_mask=apply_mask))
    return cast(MCPConnectionData, config.config)


def get_connection_config_by_id(
    config_id: int, db_session: Session, *, for_update: bool = False
) -> MCPConnectionConfig:
    """Get connection config by ID. ``for_update`` row-locks the config so a
    read-compare-write over its JSON blob is atomic against concurrent writers."""
    stmt = select(MCPConnectionConfig).where(MCPConnectionConfig.id == config_id)
    if for_update:
        stmt = stmt.with_for_update()
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


class MCPCredentialsError(Exception):
    """Credentials for an MCP server cannot be resolved for this user."""


def get_mcp_auth_template(mcp_server: MCPServer) -> MCPAuthTemplate | None:
    """Read the canonical admin template, including legacy per-user API keys."""
    config = mcp_server.admin_connection_config
    if config is None:
        return None
    data = extract_connection_data(config, apply_mask=False)
    headers = data.get("header_template")
    if headers is None and (
        mcp_server.auth_type == MCPAuthenticationType.API_TOKEN
        and mcp_server.auth_performer == MCPAuthenticationPerformer.PER_USER
    ):
        headers = data.get("headers")
    if headers is None:
        return None
    return MCPAuthTemplate(headers=headers)


class ResolvedMCPCredentials(BaseModel):
    """Effective connection state for one MCP server and user."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    connection_config: MCPConnectionConfig | None
    user_oauth_token: str | None
    auth_type: MCPAuthenticationType | None = None
    auth_template: MCPAuthTemplate | None = None
    user_email: str = ""

    def _config_data(self) -> MCPConnectionData:
        return extract_connection_data(self.connection_config, apply_mask=False)

    def _template_substitutions(self) -> dict[str, str]:
        data = self._config_data()
        substitutions = dict(data.get("header_substitutions", {}))
        if api_token := data.get("api_token"):
            substitutions["api_key"] = api_token
        return substitutions

    def _configured_headers(self) -> dict[str, str]:
        data = self._config_data()
        template_headers: dict[str, str] = {}
        if self.auth_template is not None and self._has_required_substitutions():
            template_headers = self.auth_template.render(
                self._template_substitutions(), user_email=self.user_email
            )
        return merge_mcp_headers(data.get("headers", {}), template_headers)

    def _generated_auth_headers(self) -> dict[str, str]:
        if self.user_oauth_token:
            return {"Authorization": f"Bearer {self.user_oauth_token}"}
        if self.auth_type != MCPAuthenticationType.OAUTH:
            return {}
        tokens = self._config_data().get(MCPOAuthKeys.TOKENS.value)
        if not tokens:
            return {}
        token_type = tokens.get("token_type")
        access_token = tokens.get("access_token")
        if not token_type or not access_token:
            return {}
        return {"Authorization": f"{token_type} {access_token}"}

    def _has_required_substitutions(self) -> bool:
        if self.auth_template is None or not self.auth_template.required_fields:
            return True
        substitutions = self._template_substitutions()
        return all(
            substitutions.get(field) for field in self.auth_template.required_fields
        )

    def build_headers(self) -> dict[str, str]:
        """Build configured headers with generated authentication taking precedence."""
        stored = merge_mcp_headers(
            self._configured_headers(), self._generated_auth_headers()
        )
        headers = {
            k: v for k, v in stored.items() if k.lower() not in DENYLISTED_MCP_HEADERS
        }
        if len(headers) != len(stored):
            # Names only — header values are credentials.
            logger.warning(
                "Stored MCP credential headers contained denylisted headers "
                "that were stripped: %s",
                sorted(k for k in stored if k.lower() in DENYLISTED_MCP_HEADERS),
            )
        return headers

    def needs_reauth(self) -> bool:
        """The stored OAuth grant is dead (expired, no refresh token); only a
        user reconnect can restore it. Its bearer header still takes precedence
        in ``build_headers``, so no caller-supplied header can work around it."""
        return self.auth_type == MCPAuthenticationType.OAUTH and (
            mcp_oauth_reauth_required(self._config_data())
        )

    def is_authenticated(self) -> bool:
        if self.auth_type in (None, MCPAuthenticationType.NONE):
            return self._has_required_substitutions()
        if self.auth_type == MCPAuthenticationType.PT_OAUTH:
            return bool(self.user_oauth_token) and self._has_required_substitutions()
        if self.auth_type == MCPAuthenticationType.OAUTH:
            # A dead grant must read as unauthenticated so the UI prompts a
            # reconnect and Craft configs exclude the server.
            return (
                bool(self._generated_auth_headers())
                and not self.needs_reauth()
                and self._has_required_substitutions()
            )
        return bool(self._configured_headers()) and self._has_required_substitutions()


def resolve_mcp_credentials(
    mcp_server: MCPServer,
    user: User,
    db_session: Session,
    *,
    user_configs: Mapping[int, MCPConnectionConfig] | None = None,
) -> ResolvedMCPCredentials:
    """Combine the admin template, user substitutions, and generated auth.

    `user_configs` may preload every requested server's user row; a missing key
    means no stored user values.
    """
    auth_template = get_mcp_auth_template(mcp_server)
    user_connection_config = (
        user_configs.get(mcp_server.id)
        if user_configs is not None
        else get_user_connection_config(mcp_server.id, user.email, db_session)
    )

    if mcp_server.auth_type == MCPAuthenticationType.PT_OAUTH:
        if user.is_anonymous:
            raise MCPCredentialsError(
                f"Anonymous user cannot use PT_OAUTH MCP server {mcp_server.id}"
            )
        return ResolvedMCPCredentials(
            connection_config=user_connection_config,
            user_oauth_token=(
                user.oauth_accounts[0].access_token if user.oauth_accounts else None
            ),
            auth_type=mcp_server.auth_type,
            auth_template=auth_template,
            user_email=user.email,
        )

    if mcp_server.auth_type in (
        MCPAuthenticationType.API_TOKEN,
        MCPAuthenticationType.OAUTH,
    ):
        if mcp_server.auth_performer == MCPAuthenticationPerformer.PER_USER:
            connection_config = user_connection_config
        else:
            connection_config = mcp_server.admin_connection_config
        return ResolvedMCPCredentials(
            connection_config=connection_config,
            user_oauth_token=None,
            auth_type=mcp_server.auth_type,
            auth_template=auth_template,
            user_email=user.email,
        )

    return ResolvedMCPCredentials(
        connection_config=user_connection_config,
        user_oauth_token=None,
        auth_type=mcp_server.auth_type,
        auth_template=auth_template,
        user_email=user.email,
    )


def can_resolve_mcp_credentials(
    mcp_server: MCPServer,
    user: User,
    db_session: Session,
    *,
    user_configs: Mapping[int, MCPConnectionConfig] | None = None,
) -> bool:
    """Whether every generated credential and template value is available."""
    try:
        credentials = resolve_mcp_credentials(
            mcp_server, user, db_session, user_configs=user_configs
        )
    except MCPCredentialsError:
        return False
    return credentials.is_authenticated()


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


def get_user_connection_configs_for_server(
    server_id: int, db_session: Session
) -> list[MCPConnectionConfig]:
    """Get all user connection configs for a specific MCP server"""
    return list(
        db_session.scalars(
            select(MCPConnectionConfig).where(
                MCPConnectionConfig.mcp_server_id == server_id
            )
        ).all()
    )


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


def upsert_user_connection_config(
    server_id: int,
    user_email: str,
    config_data: MCPConnectionData,
    db_session: Session,
) -> MCPConnectionConfig:
    """Create or update a user's connection config for an MCP server"""
    existing_config = get_user_connection_config(server_id, user_email, db_session)

    if existing_config:
        existing_config.config = config_data  # ty: ignore[invalid-assignment]
        db_session.flush()  # Don't commit yet, let caller decide when to commit
        return existing_config
    else:
        return create_connection_config(
            config_data=config_data,
            mcp_server_id=server_id,
            user_email=user_email,
            db_session=db_session,
        )


def delete_connection_config(config_id: int, db_session: Session) -> None:
    """Delete a connection config"""
    config = get_connection_config_by_id(config_id, db_session)
    db_session.delete(config)
    db_session.flush()  # Don't commit yet, let caller decide when to commit


def delete_user_connection_configs_for_server(
    server_id: int, user_email: str, db_session: Session
) -> None:
    """Delete all connection configs for a user on a specific server"""
    configs = db_session.scalars(
        select(MCPConnectionConfig).where(
            and_(
                MCPConnectionConfig.mcp_server_id == server_id,
                MCPConnectionConfig.user_email == user_email,
            )
        )
    ).all()

    for config in configs:
        db_session.delete(config)

    db_session.commit()


def delete_all_user_connection_configs_for_server_no_commit(
    server_id: int, db_session: Session
) -> None:
    """Delete all user connection configs for a specific MCP server"""
    db_session.execute(
        delete(MCPConnectionConfig).where(
            and_(
                MCPConnectionConfig.mcp_server_id == server_id,
                MCPConnectionConfig.user_email != "",
            )
        )
    )
    db_session.flush()  # Don't commit yet, let caller decide when to commit
