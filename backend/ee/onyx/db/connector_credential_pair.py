from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_cc_pairs_by_source(
    db_session: Session,
    source_type: DocumentSource,
    access_type: AccessType | None = None,
    status: ConnectorCredentialPairStatus | None = None,
) -> list[ConnectorCredentialPair]:
    """
    Get all cc_pairs for a given source type with optional filtering by access_type and status
    result is sorted by cc_pair id
    """
    query = (
        db_session.query(ConnectorCredentialPair)
        .join(ConnectorCredentialPair.connector)
        .filter(Connector.source == source_type)
        .order_by(ConnectorCredentialPair.id)
    )

    if access_type is not None:
        query = query.filter(ConnectorCredentialPair.access_type == access_type)

    if status is not None:
        query = query.filter(ConnectorCredentialPair.status == status)

    cc_pairs = query.all()
    return cc_pairs


def get_all_auto_sync_cc_pairs(
    db_session: Session,
) -> list[ConnectorCredentialPair]:
    return (
        db_session.query(ConnectorCredentialPair)
        .where(
            ConnectorCredentialPair.access_type == AccessType.SYNC,
        )
        .all()
    )
