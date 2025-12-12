from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import SubscriptionRegistration
from onyx.db.models import SubscriptionResult


def get_subscription_registration(
    db_session: Session, user_id: str
) -> SubscriptionRegistration:
    return (
        db_session.query(SubscriptionRegistration)
        .filter(SubscriptionRegistration.user_id == user_id)
        .first()
    )


def get_subscription_result(db_session: Session, user_id: UUID) -> SubscriptionResult:
    return (
        db_session.query(SubscriptionResult)
        .filter(SubscriptionResult.user_id == user_id)
        .order_by(SubscriptionResult.created_at.desc())
        .first()
    )


def save_subscription_result(
    db_session: Session, subscription_result: SubscriptionResult
) -> None:
    db_session.add(subscription_result)
    db_session.commit()


def get_document_ids_by_cc_pair_name(
    db_session: Session,
    cc_pair_name: str,
    date_threshold: datetime | None = None,
) -> list[tuple[str, str | None]]:
    """
    Get all document IDs and links associated with a connector credential pair by its name,
    optionally filtered by documents updated after a date threshold.

    Args:
        db_session: Database session
        cc_pair_name: Name of the connector credential pair
        date_threshold: Optional datetime to filter documents updated after this date

    Returns:
        List of tuples containing (document_id, document_link)
    """
    # First, get the connector_id and credential_id from the ConnectorCredentialPair by name
    cc_pair = (
        db_session.query(ConnectorCredentialPair)
        .filter(ConnectorCredentialPair.name == cc_pair_name)
        .first()
    )

    if not cc_pair:
        return []

    # Build query to get document IDs and links associated with this connector/credential pair
    stmt = (
        select(DocumentByConnectorCredentialPair.id, Document.link)
        .join(
            Document,
            DocumentByConnectorCredentialPair.id == Document.id,
        )
        .where(
            DocumentByConnectorCredentialPair.connector_id == cc_pair.connector_id,
            DocumentByConnectorCredentialPair.credential_id == cc_pair.credential_id,
        )
    )

    # Add date threshold filter if provided
    if date_threshold is not None:
        stmt = stmt.where(Document.doc_updated_at >= date_threshold)

    results = db_session.execute(stmt).all()
    return [(doc_id, link) for doc_id, link in results]
