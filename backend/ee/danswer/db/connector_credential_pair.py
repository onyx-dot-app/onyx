from sqlalchemy import delete
from sqlalchemy.orm import Session

from danswer.configs.constants import DocumentSource
from danswer.db.connector_credential_pair import get_connector_credential_pair
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
    source_type: DocumentSource,
    db_session: Session,
) -> list[ConnectorCredentialPair]:
    cc_pairs = (
        db_session.query(ConnectorCredentialPair)
        .join(ConnectorCredentialPair.connector)
        .filter(Connector.source == source_type)
        .all()
    )

    return cc_pairs
