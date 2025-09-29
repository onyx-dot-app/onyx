from typing import cast
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from onyx.db.enums import MCPAuthenticationPerformer
from onyx.db.enums import MCPTransport
from onyx.db.models import MCPAuthenticationType
from onyx.db.models import MCPConnectionConfig
from onyx.db.models import MCPServer
from onyx.db.models import Persona
from onyx.db.models import Tool
from onyx.db.models import User
from onyx.server.features.mcp.models import MCPConnectionData
from onyx.utils.logger import setup_logger

logger = setup_logger()


# MCPServer operations
def get_all_mcp_servers(db_session: Session) -> list[MCPServer]:
    """Get all MCP servers"""
    return list(db_session.scalars(select(MCPServer)).all())


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
    persona_id: int, db_session: Session, user: User | None = None
) -> list[MCPServer]:
    """Get all MCP servers associated with a persona via its tools"""
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


def get_mcp_servers_accessible_to_user(
    user_id: UUID, db_session: Session
) -> list[MCPServer]:
    """Get all MCP servers accessible to a user (directly or through groups)"""
    user = db_session.scalar(select(User).where(User.id == user_id))  # type: ignore
    if not user:
        return []
    user = cast(User, user)
    # Get servers accessible directly to user
    user_servers = list(user.accessible_mcp_servers)

    # TODO: Add group-based access once relationships are fully implemented
    # For now, just return direct user access
    return user_servers


def create_mcp_server__no_commit(
    owner_email: str,
    name: str,
    description: str | None,
    server_url: str,
    auth_type: MCPAuthenticationType,
    transport: MCPTransport,
    auth_performer: MCPAuthenticationPerformer,
    db_session: Session,
    admin_connection_config_id: int | None = None,
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
        admin_connection_config_id=admin_connection_config_id,
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
    transport: MCPTransport | None = None,
) -> MCPServer:
    """Update an existing MCP server"""
    server = get_mcp_server_by_id(server_id, db_session)

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
    if transport is not None:
        server.transport = transport

    db_session.flush()  # Don't commit yet, let caller decide when to commit
    return server


def delete_mcp_server(server_id: int, db_session: Session) -> None:
    """Delete an MCP server and all associated tools (via CASCADE)"""
    server = get_mcp_server_by_id(server_id, db_session)

    # Count tools that will be deleted
    tools_count = db_session.query(Tool).filter(Tool.mcp_server_id == server_id).count()
    logger.info(f"Deleting MCP server {server_id} with {tools_count} associated tools")

    db_session.delete(server)
    db_session.commit()

    logger.info(f"Successfully deleted MCP server {server_id} and its tools")


def get_all_mcp_tools_for_server(server_id: int, db_session: Session) -> list[Tool]:
    """Get all MCP tools for a server"""
    return list(
        db_session.scalars(select(Tool).where(Tool.mcp_server_id == server_id)).all()
    )


def add_user_to_mcp_server(server_id: int, user_id: UUID, db_session: Session) -> None:
    """Grant a user access to an MCP server"""
    server = get_mcp_server_by_id(server_id, db_session)
    user = db_session.scalar(select(User).where(User.id == user_id))  # type: ignore
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
    user = db_session.scalar(select(User).where(User.id == user_id))  # type: ignore
    if not user:
        raise ValueError("User not found")

    if user in server.users:
        server.users.remove(user)
        db_session.commit()


# MCPConnectionConfig operations
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
        config.config = config_data
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
        existing_config.config = config_data
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
