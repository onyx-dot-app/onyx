import datetime
from typing import cast
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from sqlalchemy import and_
from sqlalchemy import delete
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy.orm import aliased
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from onyx.db.constants import UNSET
from onyx.db.constants import UnsetType
from onyx.db.enums import MCPAuthenticationPerformer
from onyx.db.enums import MCPOAuthProviderMode
from onyx.db.enums import MCPServerStatus
from onyx.db.enums import MCPTransport
from onyx.db.models import MCPAuthenticationType
from onyx.db.models import MCPConnectionConfig
from onyx.db.models import MCPServer
from onyx.db.models import MCPServer__User
from onyx.db.models import MCPServer__UserGroup
from onyx.db.models import Persona
from onyx.db.models import Tool
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserRole
from onyx.server.features.mcp.models import DENYLISTED_MCP_HEADERS
from onyx.server.features.mcp.models import MCPConnectionData
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
    config_id: int, db_session: Session
) -> MCPConnectionConfig:
    """Get connection config by ID"""
    config = db_session.scalar(
        select(MCPConnectionConfig).where(MCPConnectionConfig.id == config_id)
    )
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


class ResolvedMCPCredentials(BaseModel):
    """Credential source for one (server, user) pair.

    Exactly one of the fields is populated (both are None for auth type NONE):
    `connection_config` for API_TOKEN / OAUTH servers, `user_oauth_token` for
    PT_OAUTH servers.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    connection_config: MCPConnectionConfig | None
    user_oauth_token: str | None

    def build_headers(self) -> dict[str, str]:
        """Auth headers for a request to the server: the stored
        connection-config headers, with PT_OAUTH's login token taking
        precedence. Empty when no credentials are stored.

        Denylisted headers (see DENYLISTED_MCP_HEADERS) are stripped so every
        consumer gets the security filter automatically — stored credentials
        must never source e.g. a Host header."""
        stored = extract_connection_data(self.connection_config).get("headers", {})
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
        if self.user_oauth_token:
            headers["Authorization"] = f"Bearer {self.user_oauth_token}"
        return headers


def resolve_mcp_credentials(
    mcp_server: MCPServer,
    user: User,
    db_session: Session,
) -> ResolvedMCPCredentials:
    """Resolve which stored credentials authenticate `user` against `mcp_server`.

    The single source of truth for the performer/auth-type branching, shared by
    chat's MCPTool construction and Craft's sandbox-proxy credential injection:
    - PT_OAUTH: the user's login OAuth token; no stored config row.
    - API_TOKEN / OAUTH: the user's own `mcp_connection_config` row for
      PER_USER servers, the admin config row otherwise.
    - NONE: no credentials.

    Raises MCPCredentialsError for PT_OAUTH with the anonymous user, who has no
    login OAuth token.
    """
    if mcp_server.auth_type == MCPAuthenticationType.PT_OAUTH:
        if user.is_anonymous:
            raise MCPCredentialsError(
                f"Anonymous user cannot use PT_OAUTH MCP server {mcp_server.id}"
            )
        return ResolvedMCPCredentials(
            connection_config=None,
            user_oauth_token=(
                user.oauth_accounts[0].access_token if user.oauth_accounts else None
            ),
        )

    if mcp_server.auth_type in (
        MCPAuthenticationType.API_TOKEN,
        MCPAuthenticationType.OAUTH,
    ):
        if mcp_server.auth_performer == MCPAuthenticationPerformer.PER_USER:
            connection_config = get_user_connection_config(
                mcp_server.id, user.email, db_session
            )
        else:
            connection_config = mcp_server.admin_connection_config
        return ResolvedMCPCredentials(
            connection_config=connection_config, user_oauth_token=None
        )

    return ResolvedMCPCredentials(connection_config=None, user_oauth_token=None)


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
    config = get_connection_config_by_id(config_id, db_session)

    if config_data is not None:
        config.config = config_data  # ty: ignore[invalid-assignment]
        # Force SQLAlchemy to detect the change by marking the field as modified
        flag_modified(config, "config")

    db_session.commit()
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


# TODO: do this in one db call
def get_server_auth_template(
    server_id: int, db_session: Session
) -> MCPConnectionConfig | None:
    """Get the authentication template for a server (from the admin connection config)"""
    server = get_mcp_server_by_id(server_id, db_session)
    if not server.admin_connection_config_id:
        return None

    if server.auth_performer == MCPAuthenticationPerformer.ADMIN:
        return None  # admin server implies no template
    return server.admin_connection_config


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
            MCPConnectionConfig.mcp_server_id == server_id
        )
    )
    db_session.flush()  # Don't commit yet, let caller decide when to commit
