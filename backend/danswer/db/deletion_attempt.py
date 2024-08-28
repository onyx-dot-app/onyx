from sqlalchemy.orm import Session

from danswer.db.embedding_model import get_current_db_embedding_model
from danswer.db.index_attempt import get_last_attempt
from danswer.db.models import ConnectorCredentialPair
from danswer.db.models import IndexingStatus


def check_deletion_attempt_is_allowed(
    connector_credential_pair: ConnectorCredentialPair,
    db_session: Session,
    allow_scheduled: bool = False,
) -> str | None:
    """
    To be deletable:
        (1) connector should be paused
        (2) there should be no in-progress/planned index attempts

    Returns an error message if the deletion attempt is not allowed, otherwise None.
    """
    base_error_msg = (
        f"Connector with ID '{connector_credential_pair.connector_id}' and credential ID "
        f"'{connector_credential_pair.credential_id}' is not deletable."
    )

    if connector_credential_pair.status.is_active():
        return base_error_msg + " Connector must be paused."

    connector_id = connector_credential_pair.connector_id
    credential_id = connector_credential_pair.credential_id
    current_embedding_model = get_current_db_embedding_model(db_session)

    last_indexing = get_last_attempt(
        connector_id=connector_id,
        credential_id=credential_id,
        embedding_model_id=current_embedding_model.id,
        db_session=db_session,
    )

    if not last_indexing:
        return None

    if last_indexing.status == IndexingStatus.IN_PROGRESS or (
        last_indexing.status == IndexingStatus.NOT_STARTED and not allow_scheduled
    ):
        return (
            base_error_msg
            + " There is an ongoing / planned indexing attempt. "
            + "The indexing attempt must be completed or cancelled before deletion."
        )

    return None
