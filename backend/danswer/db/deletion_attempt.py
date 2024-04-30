from danswer.db.models import ConnectorCredentialPair
from danswer.db.models import IndexingStatus


def check_deletion_attempt_is_allowed(
    connector_credential_pair: ConnectorCredentialPair,
    allow_scheduled: bool = False,
) -> str | None:
    """
    To be deletable:
        (1) connector should be disabled
        (2) there should be no in-progress/planned index attempts

    Returns an error message if the deletion attempt is not allowed, otherwise None.
    """
    base_error_msg = (
        f"Connector with ID '{connector_credential_pair.connector_id}' and credential ID "
        f"'{connector_credential_pair.credential_id}' is not deletable."
    )

    if not connector_credential_pair.connector.disabled:
        return base_error_msg + " Connector must be paused."

    if connector_credential_pair.last_attempt_status == IndexingStatus.IN_PROGRESS or (
        connector_credential_pair.last_attempt_status == IndexingStatus.NOT_STARTED
        and not allow_scheduled
    ):
        return (
            base_error_msg
            + " There is an ongoing / planned indexing attempt. "
            + "The indexing attempt must be completed or cancelled before deletion."
        )

    return None
