from uuid import UUID

from sqlalchemy import and_, delete, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from onyx.configs.constants import DocumentSource
from onyx.db.connector_credential_pair import get_connector_credential_pair
from onyx.db.document import build_cc_pair_has_unsynced_documents_clause
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
    access_types: list[AccessType] | None = None,
    status: ConnectorCredentialPairStatus | None = None,
) -> list[ConnectorCredentialPair]:
    """
    Get all cc_pairs for a given source type with optional filtering by access_types and status
    result is sorted by cc_pair id
    """
    query = (
        db_session.query(ConnectorCredentialPair)
        .join(ConnectorCredentialPair.connector)
        .filter(Connector.source == source_type)
        .order_by(ConnectorCredentialPair.id)
    )

    if access_types is not None:
        query = query.filter(ConnectorCredentialPair.access_type.in_(access_types))

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
            ConnectorCredentialPair.access_type.in_(AccessType.perm_synced_types()),
        )
        .all()
    )


def get_perm_sync_pending_cc_pair_sources(
    db_session: Session,
) -> dict[int, DocumentSource]:
    """The pairs awaiting their first permission sync, with their sources."""
    return dict(
        db_session.execute(
            select(ConnectorCredentialPair.id, Connector.source)
            .join(ConnectorCredentialPair.connector)
            .where(ConnectorCredentialPair.perm_sync_pending_since.is_not(None))
        )
        .tuples()
        .all()
    )


def clear_perm_sync_pending__no_commit(
    db_session: Session, cc_pair_id: int, needs_group_sync: bool
) -> bool:
    """Clears the pair's perm_sync_pending_since once its permissions are in
    the document index: a doc permission sync that started after the mark
    succeeded, an external group sync after the mark succeeded when
    needs_group_sync, and no indexed document of the pair waits for metadata
    sync. Returns True if it cleared the mark."""
    pending_since = ConnectorCredentialPair.perm_sync_pending_since
    conditions = [
        ConnectorCredentialPair.id == cc_pair_id,
        pending_since.is_not(None),
        # Set to the start time of the last successful doc permission sync.
        ConnectorCredentialPair.last_time_perm_sync >= pending_since,
        ~build_cc_pair_has_unsynced_documents_clause(),
    ]
    if needs_group_sync:
        conditions.append(
            ConnectorCredentialPair.last_time_external_group_sync >= pending_since
        )
    cleared_id = db_session.execute(
        update(ConnectorCredentialPair)
        .where(*conditions)
        .values(perm_sync_pending_since=None)
        .returning(ConnectorCredentialPair.id)
    ).scalar_one_or_none()
    return cleared_id is not None
