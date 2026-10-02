from uuid import UUID

from sqlalchemy import and_, delete, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from onyx.configs.constants import DocumentSource
from onyx.db.connector_credential_pair import get_connector_credential_pair
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    User__UserGroup,
    UserGroup__CCPairDataAccess,
    UserGroup__ConnectorCredentialPair,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _build_user_group_cc_pair_access_clause(user_id: UUID) -> ColumnElement[bool]:
    """True for pairs where the user is in a data-access group. The same rows
    give the group: ACL entries of PRIVATE pairs
    (fetch_user_groups_for_documents).

    NOTE: is imported in onyx.db.connector_credential_pair by
    `fetch_versioned_implementation`. DO NOT REMOVE."""
    return (
        select(1)
        .select_from(User__UserGroup)
        .join(
            UserGroup__CCPairDataAccess,
            and_(
                UserGroup__CCPairDataAccess.user_group_id
                == User__UserGroup.user_group_id,
                UserGroup__CCPairDataAccess.cc_pair_id == ConnectorCredentialPair.id,
            ),
        )
        .where(User__UserGroup.user_id == user_id)
        .correlate(ConnectorCredentialPair)
        .exists()
    )


def _delete_connector_credential_pair_user_groups_relationship__no_commit(
    db_session: Session, connector_id: int, credential_id: int
) -> None:
    cc_pair = get_connector_credential_pair(
        db_session=db_session,
        connector_id=connector_id,
        credential_id=credential_id,
    )
    if cc_pair is None:
        raise ValueError(
            f"ConnectorCredentialPair with connector_id: {connector_id} and credential_id: {credential_id} not found"
        )

    stmt = delete(UserGroup__ConnectorCredentialPair).where(
        UserGroup__ConnectorCredentialPair.cc_pair_id == cc_pair.id,
    )
    db_session.execute(stmt)


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
