from sqlalchemy import delete
from sqlalchemy.orm import Session

from danswer.configs.constants import DocumentSource
from danswer.db.connector_credential_pair import get_connector_credential_pair
from danswer.db.enums import AccessType
from danswer.db.models import Connector
from danswer.db.models import ConnectorCredentialPair
from danswer.db.models import UserGroup__ConnectorCredentialPair
from danswer.utils.logger import setup_logger

logger = setup_logger()


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
            f"ConnectorCredentialPair with connector_id: {connector_id} "
            f"and credential_id: {credential_id} not found"
        )

    stmt = delete(UserGroup__ConnectorCredentialPair).where(
        UserGroup__ConnectorCredentialPair.cc_pair_id == cc_pair.id,
    )
    db_session.execute(stmt)


def get_cc_pairs_by_source(
    db_session: Session,
    source_type: DocumentSource,
    only_sync: bool,
) -> list[ConnectorCredentialPair]:
    query = (
        db_session.query(ConnectorCredentialPair)
        .join(ConnectorCredentialPair.connector)
        .filter(Connector.source == source_type)
    )

    if only_sync:
        query = query.filter(ConnectorCredentialPair.access_type == AccessType.SYNC)

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
