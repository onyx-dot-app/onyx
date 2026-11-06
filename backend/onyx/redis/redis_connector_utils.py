from pydantic import ValidationError
from sqlalchemy.orm import Session

from onyx.db.connector_credential_pair import get_connector_credential_pair
from onyx.db.enums import ConnectorCredentialPairStatus, TaskStatus
from onyx.db.models import TaskQueueState
from onyx.redis.redis_connector import RedisConnector
from onyx.server.documents.models import DeletionAttemptSnapshot


def _get_deletion_status(
    connector_id: int,
    credential_id: int,
    db_session: Session,
    tenant_id: str,
) -> TaskQueueState | None:
    """We no longer store TaskQueueState in the DB for a deletion attempt.
    This function populates TaskQueueState by just checking redis.
    """
    cc_pair = get_connector_credential_pair(
        connector_id=connector_id, credential_id=credential_id, db_session=db_session
    )
    if not cc_pair:
        return None

    redis_connector = RedisConnector(tenant_id, cc_pair.id)
    # One read of the fence, so the status and its start come from the same state.
    try:
        fence = redis_connector.delete.payload
        fenced = fence is not None
    except (UnicodeDecodeError, ValidationError):
        # The fence is up but unreadable: the deletion runs, its start is unknown.
        fence = None
        fenced = True
    if fenced:
        return TaskQueueState(
            task_id="",
            task_name=redis_connector.delete.fence_key,
            status=TaskStatus.STARTED,
            start_time=fence.submitted if fence is not None else None,
        )

    if cc_pair.status == ConnectorCredentialPairStatus.DELETING:
        return TaskQueueState(
            task_id="",
            task_name=redis_connector.delete.fence_key,
            status=TaskStatus.PENDING,
        )

    return None


def get_deletion_attempt_snapshot(
    connector_id: int,
    credential_id: int,
    db_session: Session,
    tenant_id: str,
) -> DeletionAttemptSnapshot | None:
    deletion_task = _get_deletion_status(
        connector_id, credential_id, db_session, tenant_id
    )
    if not deletion_task:
        return None

    return DeletionAttemptSnapshot(
        connector_id=connector_id,
        credential_id=credential_id,
        status=deletion_task.status,
        started_at=deletion_task.start_time,
    )
