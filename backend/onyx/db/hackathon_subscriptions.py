from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import SubscriptionRegistration
from onyx.db.models import SubscriptionResult


def get_subscription_registration(
    db_session: Session, user_id: UUID
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
        .first()
    )


def save_subscription_result(
    db_session: Session, subscription_result: SubscriptionResult
) -> None:
    db_session.add(subscription_result)
    db_session.commit()


def get_document_ids_by_cc_pair_name(
    db_session: Session, cc_pair_name: str
) -> list[str]:
    """
    Get all document IDs associated with a connector credential pair by its name.

    Args:
        db_session: Database session
        cc_pair_name: Name of the connector credential pair

    Returns:
        List of document IDs
    """
    # First, get the connector_id and credential_id from the ConnectorCredentialPair by name
    cc_pair = (
        db_session.query(ConnectorCredentialPair)
        .filter(ConnectorCredentialPair.name == cc_pair_name)
        .first()
    )

    if not cc_pair:
        return []

    # Then get all document IDs associated with this connector/credential pair
    stmt = select(DocumentByConnectorCredentialPair.id).where(
        DocumentByConnectorCredentialPair.connector_id == cc_pair.connector_id,
        DocumentByConnectorCredentialPair.credential_id == cc_pair.credential_id,
    )

    document_ids = db_session.execute(stmt).scalars().all()
    return list(document_ids)
