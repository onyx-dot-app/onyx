from uuid import UUID, uuid4

from celery import Celery
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import (
    DANSWER_REDIS_FUNCTION_LOCK_PREFIX,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
)
from onyx.connectors.capability_checks.indexing_hold import get_first_indexing_hold
from onyx.db.connector_edit_requests import (
    create_pending_backfill_attempt__no_commit,
)
from onyx.db.enums import ConnectorCredentialPairStatus, IndexModelStatus
from onyx.db.index_attempt import (
    claim_waiting_index_attempt,
    mark_attempt_failed,
)
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.db.models import ConnectorCredentialPair, SearchSettings
from onyx.redis.tenant_redis_client import TenantRedisClient

_LOCK_TIMEOUT = 30
# Serializes attempt creation (beat or API) and the dispatch of waiting attempts.
_CREATION_LOCK_NAME = DANSWER_REDIS_FUNCTION_LOCK_PREFIX + "try_creating_indexing_task"


def _new_docfetching_task_id(
    cc_pair: ConnectorCredentialPair, search_settings: SearchSettings
) -> str:
    return f"docfetching_{cc_pair.id}_{search_settings.id}_{uuid4()}"


def _skips_indexing(
    cc_pair: ConnectorCredentialPair, search_settings: SearchSettings
) -> bool:
    if cc_pair.status == ConnectorCredentialPairStatus.DELETING:
        return True
    # Mirrors should_index: a legacy FUTURE reindex still indexes a paused pair,
    # or the model swap never completes.
    if cc_pair.status == ConnectorCredentialPairStatus.PAUSED:
        return (
            search_settings.status != IndexModelStatus.FUTURE
            or search_settings.use_port_flow
        )
    return False


def _send_docfetching_task(
    celery_app: Celery,
    *,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
    index_attempt_id: int,
    custom_task_id: str,
    tenant_id: str,
) -> None:
    # Use higher priority for first-time indexing to ensure new connectors
    # get processed before re-indexing of existing connectors
    has_successful_attempt = cc_pair.last_successful_index_time is not None
    priority = (
        OnyxCeleryPriority.MEDIUM if has_successful_attempt else OnyxCeleryPriority.HIGH
    )

    # No expires=: a docfetching task can wait in the queue for hours under
    # load, and the NOT_STARTED scan in the indexing watchdog fails an attempt
    # whose task is lost.
    result = celery_app.send_task(
        OnyxCeleryTask.CONNECTOR_DOC_FETCHING_TASK,
        kwargs={
            "index_attempt_id": index_attempt_id,
            "cc_pair_id": cc_pair.id,
            "search_settings_id": search_settings.id,
            "tenant_id": tenant_id,
        },
        queue=OnyxCeleryQueues.CONNECTOR_DOC_FETCHING,
        task_id=custom_task_id,
        priority=priority,
    )
    if not result:
        raise RuntimeError("send_task for connector_doc_fetching_task failed.")

    task_logger.info(
        f"Created docfetching task: "
        f"cc_pair={cc_pair.id} "
        f"search_settings={search_settings.id} "
        f"attempt_id={index_attempt_id} "
        f"celery_task_id={custom_task_id}"
    )


def try_creating_docfetching_task(
    celery_app: Celery,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
    reindex: bool,
    db_session: Session,
    r: TenantRedisClient,
    tenant_id: str,
) -> int | None:
    """Checks for any conditions that should block the indexing task from being
    created, then creates the task.

    Does not check for scheduling related conditions as this function
    is used to trigger indexing immediately.

    Now uses database-based coordination instead of Redis fencing.
    """
    return _try_creating_attempt(
        celery_app,
        cc_pair,
        search_settings,
        db_session,
        r,
        tenant_id,
        from_beginning=reindex,
    )


def try_creating_pending_backfill_attempt(
    celery_app: Celery,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
    request_id: UUID,
    db_session: Session,
    r: TenantRedisClient,
    tenant_id: str,
) -> int | None:
    """Creates the attempt of the pair's pending backfill ``request_id`` and
    records it on the request in one transaction, then sends its docfetching
    task. Returns None when the pair skips indexing, its first attempt is
    held for the capability checks, or the backfill must wait (see
    ``create_pending_backfill_attempt__no_commit``)."""
    lock: RedisLock = r.lock(_CREATION_LOCK_NAME, timeout=_LOCK_TIMEOUT)
    if not lock.acquire(blocking_timeout=_LOCK_TIMEOUT / 2):
        return None

    committed_attempt_id: int | None = None
    try:
        db_session.refresh(cc_pair)
        if _skips_indexing(cc_pair, search_settings):
            return None
        # A backfill never waits: until the first full run is sent, it has
        # nothing to add to.
        if get_first_indexing_hold(db_session, cc_pair) is not None:
            task_logger.info(
                f"Skipping backfill while the first attempt is held: cc_pair={cc_pair.id}"
            )
            return None

        custom_task_id = _new_docfetching_task_id(cc_pair, search_settings)
        index_attempt_id: int | None = create_pending_backfill_attempt__no_commit(
            db_session,
            cc_pair_id=cc_pair.id,
            search_settings_id=search_settings.id,
            request_id=request_id,
            celery_task_id=custom_task_id,
        )
        if index_attempt_id is None:
            db_session.rollback()
            return None
        # The task is sent only after the commit, so an edit that commits
        # first sees the attempt and stops it.
        db_session.commit()
        committed_attempt_id = index_attempt_id

        _send_docfetching_task(
            celery_app,
            cc_pair=cc_pair,
            search_settings=search_settings,
            index_attempt_id=index_attempt_id,
            custom_task_id=custom_task_id,
            tenant_id=tenant_id,
        )
        return index_attempt_id
    except Exception:
        task_logger.exception(
            f"try_creating_pending_backfill_attempt - Unexpected exception: "
            f"cc_pair={cc_pair.id} search_settings={search_settings.id}"
        )
        db_session.rollback()
        # The next beat releases the request of a failed attempt.
        if committed_attempt_id is not None:
            mark_attempt_failed(committed_attempt_id, db_session)
        return None
    finally:
        if lock.owned():
            lock.release()


def _try_creating_attempt(
    celery_app: Celery,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
    db_session: Session,
    r: TenantRedisClient,
    tenant_id: str,
    *,
    from_beginning: bool,
) -> int | None:
    # we need to serialize any attempt to trigger indexing since it can be triggered
    # either via celery beat or manually (API call)
    lock: RedisLock = r.lock(
        _CREATION_LOCK_NAME,
        timeout=_LOCK_TIMEOUT,
    )

    acquired = lock.acquire(blocking_timeout=_LOCK_TIMEOUT / 2)
    if not acquired:
        return None

    index_attempt_id = None
    try:
        # Basic status checks
        db_session.refresh(cc_pair)
        # A pause that commits after the beat read the pair ends here.
        if _skips_indexing(cc_pair, search_settings):
            return None

        # A first attempt that waits for the capability checks is created
        # without its task; the beat sends it once the checks pass.
        held = get_first_indexing_hold(db_session, cc_pair) is not None
        custom_task_id = (
            None if held else _new_docfetching_task_id(cc_pair, search_settings)
        )

        # Try to create a new index attempt using database coordination
        # This replaces the Redis fencing mechanism
        index_attempt_id = IndexingCoordination.try_create_index_attempt(
            db_session=db_session,
            cc_pair_id=cc_pair.id,
            search_settings_id=search_settings.id,
            celery_task_id=custom_task_id,
            from_beginning=from_beginning,
        )

        if index_attempt_id is None:
            # Another indexing attempt is already running
            return None

        if custom_task_id is None:
            task_logger.info(
                f"Created index attempt that waits for capability checks: "
                f"cc_pair={cc_pair.id} "
                f"search_settings={search_settings.id} "
                f"attempt_id={index_attempt_id}"
            )
            return index_attempt_id

        _send_docfetching_task(
            celery_app,
            cc_pair=cc_pair,
            search_settings=search_settings,
            index_attempt_id=index_attempt_id,
            custom_task_id=custom_task_id,
            tenant_id=tenant_id,
        )
        return index_attempt_id

    except Exception:
        task_logger.exception(
            f"try_creating_indexing_task - Unexpected exception: cc_pair={cc_pair.id} search_settings={search_settings.id}"
        )

        # Clean up on failure
        if index_attempt_id is not None:
            mark_attempt_failed(index_attempt_id, db_session)

        return None
    finally:
        if lock.owned():
            lock.release()

    return index_attempt_id


def try_dispatching_waiting_attempt(
    celery_app: Celery,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
    index_attempt_id: int,
    db_session: Session,
    r: TenantRedisClient,
    tenant_id: str,
) -> bool:
    """Sends the docfetching task of an attempt that waits for the capability
    checks, once no hold applies. Returns True when the task was sent.

    Shares the creation lock, and the claim is conditional, so the task is
    sent at most once.
    """
    lock: RedisLock = r.lock(
        _CREATION_LOCK_NAME,
        timeout=_LOCK_TIMEOUT,
    )
    if not lock.acquire(blocking_timeout=_LOCK_TIMEOUT / 2):
        return False

    claimed = False
    try:
        db_session.refresh(cc_pair)
        if _skips_indexing(cc_pair, search_settings):
            return False
        if get_first_indexing_hold(db_session, cc_pair) is not None:
            return False

        custom_task_id = _new_docfetching_task_id(cc_pair, search_settings)
        claimed = claim_waiting_index_attempt(
            db_session, index_attempt_id, custom_task_id
        )
        if not claimed:
            return False
        _send_docfetching_task(
            celery_app,
            cc_pair=cc_pair,
            search_settings=search_settings,
            index_attempt_id=index_attempt_id,
            custom_task_id=custom_task_id,
            tenant_id=tenant_id,
        )
        return True
    except Exception:
        task_logger.exception(
            f"try_dispatching_waiting_attempt - Unexpected exception: "
            f"cc_pair={cc_pair.id} attempt_id={index_attempt_id}"
        )
        if claimed:
            mark_attempt_failed(index_attempt_id, db_session)
        return False
    finally:
        if lock.owned():
            lock.release()
