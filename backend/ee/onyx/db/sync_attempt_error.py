from sqlalchemy.orm import Session

from ee.onyx.external_permissions.models import SyncEntityFailure
from onyx.db.index_attempt import cap_failure_message
from onyx.db.models import SyncAttemptError
from onyx.db.permission_sync_attempt import lock_external_group_sync_attempt_if_owned


def create_sync_attempt_error(
    db_session: Session,
    external_group_sync_attempt_id: int,
    cc_pair_id: int,
    failure: SyncEntityFailure,
) -> None:
    """Commits at once, so the session holds no transaction while the sync
    goes back to the source. Refused once the reaper has failed the attempt,
    like the group writes, so a lost attempt files no rows."""
    lock_external_group_sync_attempt_if_owned(
        external_group_sync_attempt_id, db_session
    )
    db_session.add(
        SyncAttemptError(
            external_group_sync_attempt_id=external_group_sync_attempt_id,
            connector_credential_pair_id=cc_pair_id,
            entity_kind=failure.kind,
            entity_id=failure.id,
            entity_name=failure.name,
            failure_message=cap_failure_message(failure.message),
        )
    )
    db_session.commit()
