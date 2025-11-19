from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.configs.constants import FederatedConnectorSource
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import DocumentSet
from onyx.db.models import FederatedConnector
from onyx.db.models import FederatedConnector__DocumentSet
from onyx.db.models import FederatedConnectorOAuthToken
from onyx.federated_connectors.factory import get_federated_connector
from onyx.utils.logger import setup_logger

logger = setup_logger()


def fetch_federated_connector_by_id(
    federated_connector_id: int, db_session: Session
) -> FederatedConnector | None:
    """Fetch a federated connector by its ID."""
    stmt = select(FederatedConnector).where(
        FederatedConnector.id == federated_connector_id
    )
    result = db_session.execute(stmt)
    return result.scalar_one_or_none()


def fetch_all_federated_connectors(db_session: Session) -> list[FederatedConnector]:
    """Fetch all federated connectors with their OAuth tokens and document sets."""
    stmt = select(FederatedConnector).options(
        selectinload(FederatedConnector.oauth_tokens),
        selectinload(FederatedConnector.document_sets),
    )
    result = db_session.execute(stmt)
    return list(result.scalars().all())


def fetch_all_federated_connectors_parallel() -> list[FederatedConnector]:
    with get_session_with_current_tenant() as db_session:
        return fetch_all_federated_connectors(db_session)


def validate_federated_connector_credentials(
    source: FederatedConnectorSource,
    credentials: dict[str, Any],
) -> bool:
    """Validate credentials for a federated connector using the connector's validation logic."""
    try:
        # the initialization will fail if the credentials are invalid
        get_federated_connector(source, credentials)
        return True
    except Exception as e:
        logger.error(f"Error validating credentials for source {source}: {e}")
        return False


def create_federated_connector(
    db_session: Session,
    source: FederatedConnectorSource,
    credentials: dict[str, Any],
) -> FederatedConnector:
    """Create a new federated connector with credential validation."""
    # Validate credentials before creating
    if not validate_federated_connector_credentials(source, credentials):
        raise ValueError(
            f"Invalid credentials for federated connector source: {source}"
        )

    federated_connector = FederatedConnector(
        source=source,
        credentials=credentials,
    )
    db_session.add(federated_connector)
    db_session.commit()
    return federated_connector


def update_federated_connector_oauth_token(
    db_session: Session,
    federated_connector_id: int,
    user_id: UUID,
    token: str,
    expires_at: datetime | None = None,
) -> FederatedConnectorOAuthToken:
    """Update or create OAuth token for a federated connector and user."""
    # First, try to find existing token for this user and connector
    stmt = select(FederatedConnectorOAuthToken).where(
        FederatedConnectorOAuthToken.federated_connector_id == federated_connector_id,
        FederatedConnectorOAuthToken.user_id == user_id,
    )
    existing_token = db_session.execute(stmt).scalar_one_or_none()

    if existing_token:
        # Update existing token
        existing_token.token = token
        existing_token.expires_at = expires_at
        db_session.commit()
        return existing_token
    else:
        # Create new token
        oauth_token = FederatedConnectorOAuthToken(
            federated_connector_id=federated_connector_id,
            user_id=user_id,
            token=token,
            expires_at=expires_at,
        )
        db_session.add(oauth_token)
        db_session.commit()
        return oauth_token


def get_federated_connector_oauth_token(
    db_session: Session,
    federated_connector_id: int,
    user_id: UUID,
) -> FederatedConnectorOAuthToken | None:
    """Get OAuth token for a federated connector and user."""
    stmt = select(FederatedConnectorOAuthToken).where(
        FederatedConnectorOAuthToken.federated_connector_id == federated_connector_id,
        FederatedConnectorOAuthToken.user_id == user_id,
    )
    result = db_session.execute(stmt)
    return result.scalar_one_or_none()


def list_federated_connector_oauth_tokens(
    db_session: Session,
    user_id: UUID,
) -> list[FederatedConnectorOAuthToken]:
    """List all OAuth tokens for all federated connectors."""
    stmt = (
        select(FederatedConnectorOAuthToken)
        .where(
            FederatedConnectorOAuthToken.user_id == user_id,
        )
        .options(
            joinedload(FederatedConnectorOAuthToken.federated_connector),
        )
    )
    result = db_session.scalars(stmt)
    return list(result)


def create_federated_connector_document_set_mapping(
    db_session: Session,
    federated_connector_id: int,
    document_set_id: int,
    entities: dict[str, Any],
) -> FederatedConnector__DocumentSet:
    """Create a mapping between federated connector and document set with entities."""
    mapping = FederatedConnector__DocumentSet(
        federated_connector_id=federated_connector_id,
        document_set_id=document_set_id,
        entities=entities,
    )
    db_session.add(mapping)
    db_session.commit()
    return mapping


def update_federated_connector_document_set_entities(
    db_session: Session,
    federated_connector_id: int,
    document_set_id: int,
    entities: dict[str, Any],
) -> FederatedConnector__DocumentSet | None:
    """Update entities for a federated connector document set mapping."""
    stmt = select(FederatedConnector__DocumentSet).where(
        FederatedConnector__DocumentSet.federated_connector_id
        == federated_connector_id,
        FederatedConnector__DocumentSet.document_set_id == document_set_id,
    )
    mapping = db_session.execute(stmt).scalar_one_or_none()

    if mapping:
        mapping.entities = entities
        db_session.commit()
        return mapping

    return None


def get_federated_connector_document_set_mappings(
    db_session: Session,
    federated_connector_id: int,
) -> list[FederatedConnector__DocumentSet]:
    """Get all document set mappings for a federated connector."""
    stmt = select(FederatedConnector__DocumentSet).where(
        FederatedConnector__DocumentSet.federated_connector_id == federated_connector_id
    )
    result = db_session.execute(stmt)
    return list(result.scalars().all())


def delete_federated_connector_document_set_mapping(
    db_session: Session,
    federated_connector_id: int,
    document_set_id: int,
) -> bool:
    """Delete a federated connector document set mapping."""
    stmt = select(FederatedConnector__DocumentSet).where(
        FederatedConnector__DocumentSet.federated_connector_id
        == federated_connector_id,
        FederatedConnector__DocumentSet.document_set_id == document_set_id,
    )
    mapping = db_session.execute(stmt).scalar_one_or_none()

    if mapping:
        db_session.delete(mapping)
        db_session.commit()
        return True

    return False


def get_federated_connector_document_set_mappings_by_document_set_names(
    db_session: Session,
    document_set_names: list[str],
) -> list[FederatedConnector__DocumentSet]:
    """Get all document set mappings for a federated connector by document set names."""
    stmt = (
        select(FederatedConnector__DocumentSet)
        .join(
            DocumentSet,
            FederatedConnector__DocumentSet.document_set_id == DocumentSet.id,
        )
        .where(DocumentSet.name.in_(document_set_names))
    )
    result = db_session.scalars(stmt)
    return list(result)


def update_federated_connector(
    db_session: Session,
    federated_connector_id: int,
    credentials: dict[str, Any] | None = None,
) -> FederatedConnector | None:
    """Update a federated connector with credential validation."""
    federated_connector = fetch_federated_connector_by_id(
        federated_connector_id, db_session
    )
    if not federated_connector:
        return None

    if credentials is not None:
        # Validate credentials before updating
        if not validate_federated_connector_credentials(
            federated_connector.source, credentials
        ):
            raise ValueError(
                f"Invalid credentials for federated connector source: {federated_connector.source}"
            )
        federated_connector.credentials = credentials

    db_session.commit()
    return federated_connector


def delete_federated_connector(
    db_session: Session,
    federated_connector_id: int,
) -> bool:
    """Delete a federated connector and all its related data."""
    federated_connector = fetch_federated_connector_by_id(
        federated_connector_id, db_session
    )
    if not federated_connector:
        return False

    # Delete related OAuth tokens (cascade should handle this)
    # Delete related document set mappings (cascade should handle this)
    db_session.delete(federated_connector)
    db_session.commit()
    return True
