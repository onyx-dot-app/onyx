"""When suggested-questions runs happen.

Indexing, deletion and chat call the request functions. They never raise, so
they cannot break those paths; the task send is a normal broker publish, as
in Onyx's other request paths. A request is sent only when the run rules allow
it now, so the queue never carries a task that would just return. The task
checks the same rules again under the pool lock, for requests that raced.
"""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend, CacheLockAcquisitionError
from onyx.configs.constants import (
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.suggested_questions import count_candidate_documents
from onyx.server.features.suggested_questions.config import (
    SQ_MAX_POOL_RUNS_PER_DAY,
    SQ_MIN_CANDIDATE_DOCS,
    SQ_POOL_LOCK_WAIT_S,
    SQ_POOL_RUN_GAP_MIN,
    SQ_RUN_WINDOW_HOURS,
    SQ_TASK_EXPIRES_S,
    SQ_TOPUP_GAP_MIN,
    SQ_TOPUPS_PER_USER_PER_DAY,
)
from onyx.server.features.suggested_questions.models import (
    PoolQuestion,
    QuestionPool,
    RefreshReason,
    RunDecision,
    UserRecord,
)
from onyx.server.features.suggested_questions.store import (
    get_live_document_ids,
    load_pool,
    load_private_shelves,
    pool_lock,
    save_pool,
    save_private_questions,
)
from onyx.server.settings.models import ApplicationStatus
from onyx.server.settings.store import load_settings
from onyx.utils.logger import setup_logger
from shared_configs.configs import IS_PLAYGROUND

logger = setup_logger()

# Short-lived flags in the tenant's cache: one queued run at a time.
_POOL_QUEUED_KEY = "suggested_questions_pool_queued"
_TOPUP_QUEUED_KEY = "suggested_questions_topup_queued:{}"


def is_enabled() -> bool:
    """Only on the Playground, and only while the company's trial runs. The
    read-only grace period and an expired trial stop every run."""
    if not IS_PLAYGROUND:
        return False
    # A failed read raises instead of returning defaults, which say ACTIVE.
    settings = load_settings(raise_on_error=True)
    return settings.application_status == ApplicationStatus.ACTIVE


def request_pool_refresh(tenant_id: str, reason: RefreshReason) -> None:
    """Queue a pool run when the run rules allow it now, unless one is already
    queued."""
    try:
        if not is_enabled():
            return
        pool = load_pool()
        now = datetime.now(UTC)
        with get_session_with_current_tenant() as db_session:
            candidates = count_candidate_documents(
                db_session, fresh_document_ids(pool.questions, now) if pool else set()
            )
        if not worth_running(pool, now, candidates).run:
            return
        cache = get_cache_backend(tenant_id=tenant_id)
        token = _token()
        # The queued run does the same work, so a second one is not queued.
        if not cache.set_if_absent(_POOL_QUEUED_KEY, token, ex=SQ_TASK_EXPIRES_S):
            return
        _send(
            cache,
            _POOL_QUEUED_KEY,
            token,
            OnyxCeleryTask.GENERATE_SUGGESTED_QUESTIONS_POOL,
            {"tenant_id": tenant_id, "reason": reason.value},
        )
        logger.info("Suggested questions: requested a pool run (%s)", reason.value)
    except Exception:
        logger.exception("Suggested questions: could not request a pool run")


def request_refresh_for_new_documents(tenant_id: str) -> None:
    """For the indexing hooks: new documents reached the index. Only a company
    that never had a pool run asks for one here. After that, chat opens ask for
    runs when a person is short of questions. Reads the stored pool first: this
    runs on every indexed batch."""
    try:
        if not is_enabled():
            return
        pool = load_pool()
        if pool is not None and pool.last_run_at() is not None:
            return
    except Exception:
        logger.exception("Suggested questions: could not read the pool")
        return
    request_pool_refresh(tenant_id, RefreshReason.FIRST_RUN)


def request_user_topup(
    tenant_id: str, user_id: UUID, record: UserRecord, now: datetime
) -> None:
    """Queue a run for one person who has fewer questions than they should,
    within their top-up limits."""
    try:
        if not is_enabled() or not topup_allowed(record, now):
            return
        cache = get_cache_backend(tenant_id=tenant_id)
        queued_key = _TOPUP_QUEUED_KEY.format(user_id)
        token = _token()
        if not cache.set_if_absent(queued_key, token, ex=SQ_TASK_EXPIRES_S):
            return
        _send(
            cache,
            queued_key,
            token,
            OnyxCeleryTask.GENERATE_SUGGESTED_QUESTIONS_FOR_USER,
            {"tenant_id": tenant_id, "user_id": str(user_id)},
        )
        logger.info("Suggested questions: requested a top-up for %s", user_id)
    except Exception:
        logger.exception("Suggested questions: could not request a top-up")


def release_pool_flag(tenant_id: str) -> None:
    """Called by the pool task when it starts: the queued run is now running,
    so a new request may queue the next one."""
    get_cache_backend(tenant_id=tenant_id).delete(_POOL_QUEUED_KEY)


def release_topup_flag(tenant_id: str, user_id: UUID) -> None:
    """Called by the top-up task when it starts, like release_pool_flag."""
    get_cache_backend(tenant_id=tenant_id).delete(_TOPUP_QUEUED_KEY.format(user_id))


def drop_orphaned_questions() -> None:
    """Remove questions whose document was deleted from the shared shelf and
    from every private shelf. It asks for no run: the next chat open of a
    person who is now short does. If a run holds the pool, leave it: the run's
    save step drops them too."""
    try:
        if not is_enabled():
            return
        with pool_lock(SQ_POOL_LOCK_WAIT_S):
            pool = load_pool(refresh_cache=True)
            with get_session_with_current_tenant() as db_session:
                shelves = load_private_shelves(db_session)
                ids = (pool.document_ids if pool else set()) | {
                    question.document_id
                    for questions in shelves.values()
                    for question in questions
                }
                if not ids:
                    return
                live = get_live_document_ids(db_session, list(ids))
            shared_dropped = 0
            if pool is not None:
                kept = [q for q in pool.questions if q.document_id in live]
                shared_dropped = len(pool.questions) - len(kept)
                if shared_dropped:
                    save_pool(pool.model_copy(update={"questions": kept}))
            private_dropped = 0
            now = datetime.now(UTC)
            for user_id, questions in shelves.items():
                gone = sum(q.document_id not in live for q in questions)
                if gone:
                    save_private_questions(user_id, [], live, now)
                    private_dropped += gone
        if shared_dropped or private_dropped:
            logger.info(
                "Suggested questions: dropped %d shared and %d private questions about deleted documents",
                shared_dropped,
                private_dropped,
            )
    except CacheLockAcquisitionError:
        return
    except Exception:
        logger.exception("Suggested questions: could not drop deleted questions")


def topup_allowed(record: UserRecord, now: datetime) -> bool:
    recent = [
        topup
        for topup in record.topups
        if topup >= now - timedelta(hours=SQ_RUN_WINDOW_HOURS)
    ]
    return len(recent) < SQ_TOPUPS_PER_USER_PER_DAY and (
        not recent or now - recent[-1] >= timedelta(minutes=SQ_TOPUP_GAP_MIN)
    )


def fresh_document_ids(questions: Iterable[PoolQuestion], now: datetime) -> set[str]:
    """Documents with a question young enough to show. A document whose
    question expired may get a new one."""
    return {q.document_id for q in questions if q.is_fresh(now)}


def count_usable_questions(
    questions: Iterable[PoolQuestion], live_document_ids: set[str], now: datetime
) -> int:
    """Questions whose document still exists and that are young enough to
    show."""
    return sum(
        question.document_id in live_document_ids and question.is_fresh(now)
        for question in questions
    )


def worth_running(
    pool: QuestionPool | None, now: datetime, candidate_documents: int
) -> RunDecision:
    """Whether a pool run may call the models now. Runs are requested only when
    they are needed (a first run, deleted questions, a person short of
    questions), so these rules only keep runs affordable. Checked before the
    request is sent and again by the task under the lock. `candidate_documents`
    counts documents without a question on the shared shelf."""
    if candidate_documents < SQ_MIN_CANDIDATE_DOCS:
        return RunDecision(run=False, reason="too few documents without a question")
    last_run = pool.last_run_at() if pool else None
    if pool is None or last_run is None:
        return RunDecision(run=True, reason="first run")
    if (
        pool.runs_since(now - timedelta(hours=SQ_RUN_WINDOW_HOURS))
        >= SQ_MAX_POOL_RUNS_PER_DAY
    ):
        return RunDecision(run=False, reason="daily run limit reached")
    if now - last_run < timedelta(minutes=SQ_POOL_RUN_GAP_MIN):
        return RunDecision(run=False, reason="too soon after the last run")
    return RunDecision(run=True, reason="requested")


def _token() -> bytes:
    """A queued flag's value, unique to this request, so a request only ever
    removes its own flag."""
    return uuid4().hex.encode()


def _send(
    cache: CacheBackend,
    queued_key: str,
    token: bytes,
    task_name: str,
    kwargs: dict[str, Any],
) -> None:
    """Send the task. If the send fails, remove this request's flag; another
    request's flag is left alone."""
    try:
        # Imported here, as other request paths do, so importing this module
        # does not build the Celery app.
        from onyx.background.celery.versioned_apps.client import app as client_app

        client_app.send_task(
            task_name,
            kwargs=kwargs,
            queue=OnyxCeleryQueues.SUGGESTED_QUESTIONS,
            # Every run has a person waiting for its questions.
            priority=OnyxCeleryPriority.HIGH,
            expires=SQ_TASK_EXPIRES_S,
        )
    except Exception:
        cache.delete_if_value(queued_key, token)
        raise
