"""Queries for integration credentials: ``integration_connection`` (one
credential for a user or the organization) and ``integration_oauth_client``.
The logic lives in ``onyx.integrations.connections``."""

import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.db.enums import IntegrationConnectionStatus
from onyx.db.models import (
    ExternalApp,
    ExternalAppUserCredential,
    IntegrationConnection,
    IntegrationOAuthClient,
    MCPConnectionConfig,
    MCPServer,
    OAuthConfig,
    OAuthUserToken,
    Plugin__Integration,
    Tool,
    User,
)
from onyx.db.plugin_access import visible_plugin_ids


def user_can_see_integration(
    db_session: Session, integration_id: int, user_id: UUID
) -> bool:
    """True when a plugin the user can see holds the integration."""
    return (
        db_session.scalar(
            select(Plugin__Integration.integration_id)
            .where(
                Plugin__Integration.integration_id == integration_id,
                Plugin__Integration.plugin_id.in_(visible_plugin_ids(user_id)),
            )
            .limit(1)
        )
        is not None
    )


def get_connection(
    db_session: Session,
    integration_id: int,
    user_id: UUID | None,
    *,
    for_update: bool = False,
) -> IntegrationConnection | None:
    """The user's connection, or the organization connection for ``None``."""
    stmt = select(IntegrationConnection).where(
        IntegrationConnection.integration_id == integration_id,
        (
            IntegrationConnection.user_id.is_(None)
            if user_id is None
            else IntegrationConnection.user_id == user_id
        ),
    )
    if for_update:
        stmt = stmt.with_for_update()
    return db_session.scalars(stmt).one_or_none()


def get_connection_by_id(
    db_session: Session, connection_id: int, *, for_update: bool = False
) -> IntegrationConnection | None:
    stmt = select(IntegrationConnection).where(
        IntegrationConnection.id == connection_id
    )
    if for_update:
        stmt = stmt.with_for_update()
    return db_session.scalars(stmt).one_or_none()


def list_connections_for_integration(
    db_session: Session, integration_id: int
) -> list[IntegrationConnection]:
    return list(
        db_session.scalars(
            select(IntegrationConnection)
            .where(IntegrationConnection.integration_id == integration_id)
            .order_by(IntegrationConnection.id)
        )
    )


def _insert_connection_stmt(
    integration_id: int,
    user_id: UUID | None,
    secret: dict[str, Any],
    expires_at: datetime.datetime | None,
    granted_scopes: list[str] | None,
    status: IntegrationConnectionStatus,
    status_reason: str | None,
) -> Any:
    return insert(IntegrationConnection).values(
        integration_id=integration_id,
        user_id=user_id,
        secret=secret,
        expires_at=expires_at,
        granted_scopes=granted_scopes,
        status=status,
        status_reason=status_reason,
    )


def _conflict_target(user_id: UUID | None) -> dict[str, Any]:
    if user_id is None:
        return {
            "index_elements": [IntegrationConnection.integration_id],
            "index_where": IntegrationConnection.user_id.is_(None),
        }
    return {
        "index_elements": [
            IntegrationConnection.user_id,
            IntegrationConnection.integration_id,
        ],
        "index_where": IntegrationConnection.user_id.is_not(None),
    }


def upsert_connection__no_commit(
    db_session: Session,
    *,
    integration_id: int,
    user_id: UUID | None,
    secret: dict[str, Any],
    expires_at: datetime.datetime | None,
    granted_scopes: list[str] | None,
) -> IntegrationConnection:
    """Write a new credential as connected. Replaces an existing row."""
    stmt = _insert_connection_stmt(
        integration_id,
        user_id,
        secret,
        expires_at,
        granted_scopes,
        IntegrationConnectionStatus.CONNECTED,
        None,
    )
    stmt = stmt.on_conflict_do_update(
        **_conflict_target(user_id),
        set_={
            "secret": stmt.excluded.secret,
            "expires_at": stmt.excluded.expires_at,
            "granted_scopes": stmt.excluded.granted_scopes,
            "status": stmt.excluded.status,
            "status_reason": None,
            "updated_at": func.now(),
        },
    ).returning(IntegrationConnection.id)
    connection_id = db_session.execute(stmt).scalar_one()
    db_session.flush()
    connection = db_session.get(IntegrationConnection, connection_id)
    if connection is None:
        raise RuntimeError("Upserted integration connection is missing")
    db_session.refresh(connection)
    return connection


def insert_connection_if_absent__no_commit(
    db_session: Session,
    *,
    integration_id: int,
    user_id: UUID | None,
    secret: dict[str, Any],
    expires_at: datetime.datetime | None,
    granted_scopes: list[str] | None,
    status: IntegrationConnectionStatus,
    status_reason: str | None,
) -> bool:
    """Insert a row only when none exists. Returns whether it inserted."""
    stmt = (
        _insert_connection_stmt(
            integration_id,
            user_id,
            secret,
            expires_at,
            granted_scopes,
            status,
            status_reason,
        )
        .on_conflict_do_nothing(**_conflict_target(user_id))
        .returning(IntegrationConnection.id)
    )
    return db_session.execute(stmt).scalar_one_or_none() is not None


def update_connection_secret__no_commit(
    db_session: Session,
    connection: IntegrationConnection,
    *,
    secret: dict[str, Any],
    expires_at: datetime.datetime | None,
) -> None:
    connection.secret = secret  # ty: ignore[invalid-assignment]
    connection.expires_at = expires_at
    connection.status = IntegrationConnectionStatus.CONNECTED
    connection.status_reason = None
    db_session.flush()


def mark_connection_needs_reconnect__no_commit(
    db_session: Session, connection: IntegrationConnection, reason: str
) -> None:
    connection.status = IntegrationConnectionStatus.NEEDS_RECONNECT
    connection.status_reason = reason
    db_session.flush()


def mark_integration_connections_needs_reconnect__no_commit(
    db_session: Session, integration_id: int, reason: str
) -> int:
    result = db_session.execute(
        update(IntegrationConnection)
        .where(IntegrationConnection.integration_id == integration_id)
        .values(
            status=IntegrationConnectionStatus.NEEDS_RECONNECT,
            status_reason=reason,
            updated_at=func.now(),
        )
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount  # ty: ignore[unresolved-attribute]


def delete_connection__no_commit(
    db_session: Session, integration_id: int, user_id: UUID | None
) -> bool:
    result = db_session.execute(
        delete(IntegrationConnection)
        .where(
            IntegrationConnection.integration_id == integration_id,
            (
                IntegrationConnection.user_id.is_(None)
                if user_id is None
                else IntegrationConnection.user_id == user_id
            ),
        )
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount > 0  # ty: ignore[unresolved-attribute]


def delete_connections_for_user__no_commit(db_session: Session, user_id: UUID) -> int:
    result = db_session.execute(
        delete(IntegrationConnection)
        .where(IntegrationConnection.user_id == user_id)
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount  # ty: ignore[unresolved-attribute]


def get_oauth_client(
    db_session: Session, integration_id: int, *, for_update: bool = False
) -> IntegrationOAuthClient | None:
    stmt = select(IntegrationOAuthClient).where(
        IntegrationOAuthClient.integration_id == integration_id
    )
    if for_update:
        stmt = stmt.with_for_update()
    return db_session.scalars(stmt).one_or_none()


def set_oauth_client_credentials__no_commit(
    db_session: Session,
    oauth_client: IntegrationOAuthClient,
    *,
    client_id: str | None,
    client_secret: str | None,
    registration: dict[str, Any] | None,
) -> None:
    oauth_client.client_id = client_id  # ty: ignore[invalid-assignment]
    oauth_client.client_secret = client_secret  # ty: ignore[invalid-assignment]
    oauth_client.registration = registration  # ty: ignore[invalid-assignment]
    db_session.flush()


def get_single_active_user_id_by_email(db_session: Session, email: str) -> UUID | None:
    """The id of the one active user with this email, else None (zero or
    more than one match)."""
    user_ids = list(
        db_session.scalars(
            select(User.__table__.c.id)
            .where(
                func.lower(User.email) == email.strip().lower(),
                User.__table__.c.is_active.is_(True),
            )
            .limit(2)
        )
    )
    return user_ids[0] if len(user_ids) == 1 else None


def get_active_user_ids(db_session: Session, user_ids: list[UUID]) -> set[UUID]:
    if not user_ids:
        return set()
    return set(
        db_session.scalars(
            select(User.__table__.c.id).where(
                User.__table__.c.id.in_(user_ids), User.__table__.c.is_active.is_(True)
            )
        )
    )


# Reads of the old credential tables, for the one-time import only.


def list_mcp_servers_with_integration(db_session: Session) -> list[MCPServer]:
    return list(
        db_session.scalars(
            select(MCPServer)
            .where(MCPServer.integration_id.is_not(None))
            .order_by(MCPServer.id)
        )
    )


def list_mcp_user_connection_configs(
    db_session: Session, mcp_server_id: int
) -> list[MCPConnectionConfig]:
    """The per-user configs of a server. The admin config has no email."""
    return list(
        db_session.scalars(
            select(MCPConnectionConfig)
            .where(
                MCPConnectionConfig.mcp_server_id == mcp_server_id,
                MCPConnectionConfig.user_email != "",
            )
            .order_by(MCPConnectionConfig.id)
        )
    )


def list_openapi_tools_with_integration(db_session: Session) -> list[Tool]:
    return list(
        db_session.scalars(
            select(Tool)
            .where(Tool.integration_id.is_not(None), Tool.mcp_server_id.is_(None))
            .order_by(Tool.id)
        )
    )


def get_oauth_config_by_id(
    db_session: Session, oauth_config_id: int
) -> OAuthConfig | None:
    return db_session.get(OAuthConfig, oauth_config_id)


def list_oauth_user_tokens(
    db_session: Session, oauth_config_id: int
) -> list[OAuthUserToken]:
    return list(
        db_session.scalars(
            select(OAuthUserToken)
            .where(OAuthUserToken.oauth_config_id == oauth_config_id)
            .order_by(OAuthUserToken.id)
        )
    )


def list_external_apps_with_integration(db_session: Session) -> list[ExternalApp]:
    return list(
        db_session.scalars(
            select(ExternalApp)
            .where(ExternalApp.integration_id.is_not(None))
            .order_by(ExternalApp.id)
        )
    )


def list_external_app_user_credentials(
    db_session: Session, external_app_id: int
) -> list[ExternalAppUserCredential]:
    return list(
        db_session.scalars(
            select(ExternalAppUserCredential)
            .where(ExternalAppUserCredential.external_app_id == external_app_id)
            .order_by(ExternalAppUserCredential.id)
        )
    )
