"""Queries for integration credentials: ``integration_connection`` (one
credential for a user or the organization) and ``integration_oauth_client``.
The logic lives in ``onyx.integrations.connections``."""

import datetime
from collections.abc import Collection
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.db.enums import IntegrationConnectionStatus
from onyx.db.models import IntegrationConnection, IntegrationOAuthClient


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
        # The locked read replaces what the session holds for the row.
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return db_session.scalars(stmt).one_or_none()


def get_connection_with_organization(
    db_session: Session, integration_id: int, user_id: UUID | None
) -> tuple[IntegrationConnection | None, IntegrationConnection | None]:
    """The organization connection and the user's connection, in one query.
    With no user, the second item is None."""
    rows = db_session.scalars(
        select(IntegrationConnection).where(
            IntegrationConnection.integration_id == integration_id,
            (
                IntegrationConnection.user_id.is_(None)
                if user_id is None
                else or_(
                    IntegrationConnection.user_id.is_(None),
                    IntegrationConnection.user_id == user_id,
                )
            ),
        )
    ).all()
    organization = next((row for row in rows if row.user_id is None), None)
    user = next((row for row in rows if row.user_id is not None), None)
    return organization, user


def list_connections(
    db_session: Session, integration_ids: Collection[int], user_id: UUID | None
) -> dict[tuple[int, UUID | None], IntegrationConnection]:
    """The organization connections of the integrations and, for a user, the
    user's connections, by ``(integration_id, user_id)``."""
    if not integration_ids:
        return {}
    owner = IntegrationConnection.user_id.is_(None)
    if user_id is not None:
        owner = owner | (IntegrationConnection.user_id == user_id)
    return {
        (connection.integration_id, connection.user_id): connection
        for connection in db_session.scalars(
            select(IntegrationConnection).where(
                IntegrationConnection.integration_id.in_(integration_ids), owner
            )
        )
    }


def get_connection_by_id(
    db_session: Session, connection_id: int, *, for_update: bool = False
) -> IntegrationConnection | None:
    stmt = select(IntegrationConnection).where(
        IntegrationConnection.id == connection_id
    )
    if for_update:
        # The locked read replaces what the session holds for the row.
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return db_session.scalars(stmt).one_or_none()


def reload_connection(db_session: Session, connection: IntegrationConnection) -> bool:
    """Re-read the row: another caller may have written it. False when
    another caller deleted it."""
    stmt = (
        select(IntegrationConnection)
        .where(IntegrationConnection.id == connection.id)
        .execution_options(populate_existing=True)
    )
    return db_session.scalars(stmt).one_or_none() is not None


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
    """Write a new credential as connected, in the new format. Replaces an
    existing row."""
    stmt = insert(IntegrationConnection).values(
        integration_id=integration_id,
        user_id=user_id,
        secret=secret,
        expires_at=expires_at,
        granted_scopes=granted_scopes,
        status=IntegrationConnectionStatus.CONNECTED,
        status_reason=None,
        legacy_format=None,
    )
    stmt = stmt.on_conflict_do_update(
        **_conflict_target(user_id),
        set_={
            "secret": stmt.excluded.secret,
            "expires_at": stmt.excluded.expires_at,
            "granted_scopes": stmt.excluded.granted_scopes,
            "status": stmt.excluded.status,
            "status_reason": None,
            "legacy_format": None,
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


def update_connection_secret__no_commit(
    db_session: Session,
    connection: IntegrationConnection,
    *,
    secret: dict[str, Any],
    expires_at: datetime.datetime | None,
    granted_scopes: list[str] | None,
) -> None:
    """Write the secret in the new format, as connected."""
    connection.secret = secret  # ty: ignore[invalid-assignment]
    connection.expires_at = expires_at
    connection.granted_scopes = granted_scopes
    connection.status = IntegrationConnectionStatus.CONNECTED
    connection.status_reason = None
    connection.legacy_format = None
    db_session.flush()


def mark_connection_needs_reconnect__no_commit(
    db_session: Session, connection: IntegrationConnection, reason: str
) -> None:
    connection.status = IntegrationConnectionStatus.NEEDS_RECONNECT
    connection.status_reason = reason
    db_session.flush()


def mark_integration_connections_needs_reconnect__no_commit(
    db_session: Session, integration_id: int, reason: str
) -> None:
    db_session.execute(
        update(IntegrationConnection)
        .where(IntegrationConnection.integration_id == integration_id)
        .values(
            status=IntegrationConnectionStatus.NEEDS_RECONNECT,
            status_reason=reason,
            updated_at=func.now(),
        )
        .execution_options(synchronize_session="fetch")
    )


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


def delete_connections_for_user__no_commit(db_session: Session, user_id: UUID) -> None:
    db_session.execute(
        delete(IntegrationConnection)
        .where(IntegrationConnection.user_id == user_id)
        .execution_options(synchronize_session="fetch")
    )


def get_oauth_client(
    db_session: Session, integration_id: int, *, for_update: bool = False
) -> IntegrationOAuthClient | None:
    stmt = select(IntegrationOAuthClient).where(
        IntegrationOAuthClient.integration_id == integration_id
    )
    if for_update:
        # The locked read replaces what the session holds for the row.
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return db_session.scalars(stmt).one_or_none()


def get_oauth_clients(
    db_session: Session, integration_ids: Collection[int]
) -> dict[int, IntegrationOAuthClient]:
    if not integration_ids:
        return {}
    return {
        oauth_client.integration_id: oauth_client
        for oauth_client in db_session.scalars(
            select(IntegrationOAuthClient).where(
                IntegrationOAuthClient.integration_id.in_(integration_ids)
            )
        )
    }


def set_oauth_client_credentials__no_commit(
    db_session: Session,
    oauth_client: IntegrationOAuthClient,
    *,
    client_id: str | None,
    client_secret: str | None,
    registration: dict[str, Any] | None,
) -> None:
    """Write the client in the new format."""
    oauth_client.client_id = client_id  # ty: ignore[invalid-assignment]
    oauth_client.client_secret = client_secret  # ty: ignore[invalid-assignment]
    oauth_client.registration = registration  # ty: ignore[invalid-assignment]
    oauth_client.legacy_format = None
    db_session.flush()
