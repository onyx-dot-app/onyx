"""When suggested-questions runs happen.

Indexing, deletion and chat call the request functions. They never raise, so
they cannot break those paths; the task send is a normal broker publish, as
in Onyx's other request paths. The rules that
decide whether a run is worth its model calls are pure functions, checked
again by the task after it takes the pool lock.
"""

from datetime import datetime, timedelta
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
from onyx.server.features.suggested_questions.config import (
    SQ_GROWTH_DELAY_S,
    SQ_GROWTH_GAP_MIN,
    SQ_MAX_POOL_RUNS_PER_DAY,
    SQ_MIN_CANDIDATE_DOCS,
    SQ_MIN_NEW_DOCS,
    SQ_POOL_LOCK_WAIT_S,
    SQ_POOL_MAX,
    SQ_POOL_SHORT,
    SQ_QUESTION_MAX_AGE_DAYS,
    SQ_RUN_WINDOW_HOURS,
    SQ_SHORT_GAP_MIN,
    SQ_TASK_EXPIRES_S,
    SQ_TOPUP_GAP_MIN,
    SQ_TOPUPS_PER_USER_PER_DAY,
)
from onyx.server.features.suggested_questions.models import (
    QuestionPool,
    RefreshReason,
    RunDecision,
    UserRecord,
)
from onyx.server.features.suggested_questions.store import (
    get_live_document_ids,
    load_pool,
    pool_lock,
    save_pool,
)
from onyx.server.settings.models import ApplicationStatus
from onyx.server.settings.store import load_settings
from onyx.utils.logger import setup_logger
from shared_configs.configs import IS_PLAYGROUND

logger = setup_logger()

# Priority and delay of a pool run, by why it was requested.
_SCHEDULE: dict[RefreshReason, tuple[OnyxCeleryPriority, int]] = {
    # The person who just connected a source is waiting for these.
    RefreshReason.FIRST_RUN: (OnyxCeleryPriority.HIGH, 0),
    RefreshReason.POOL_SHORT: (OnyxCeleryPriority.MEDIUM, 0),
    # Nobody waits: current questions still work.
    RefreshReason.GROWTH: (OnyxCeleryPriority.LOW, SQ_GROWTH_DELAY_S),
}

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
    """Queue a pool run unless one is already queued as urgently or more."""
    try:
        if not is_enabled():
            return
        priority, countdown = _SCHEDULE[reason]
        cache = get_cache_backend(tenant_id=tenant_id)
        flag_ttl = countdown + SQ_TASK_EXPIRES_S
        token = _token(priority)
        previous: tuple[bytes, int] | None = None
        if not cache.set_if_absent(_POOL_QUEUED_KEY, token, ex=flag_ttl):
            queued = cache.get(_POOL_QUEUED_KEY)
            # A lower number is more urgent. The queued run will see the new
            # documents, so only a more urgent reason queues another; the task's
            # own checks stop a second run that is not needed.
            if queued is None or _priority_of(queued) <= priority:
                return
            remaining = cache.ttl(_POOL_QUEUED_KEY)
            # Only one of several upgrading requests wins the swap.
            if not cache.replace_if_value(_POOL_QUEUED_KEY, queued, token, ex=flag_ttl):
                return
            previous = (queued, remaining if remaining > 0 else flag_ttl)
        _send(
            cache,
            _POOL_QUEUED_KEY,
            token,
            previous,
            OnyxCeleryTask.GENERATE_SUGGESTED_QUESTIONS_POOL,
            {"tenant_id": tenant_id, "reason": reason.value},
            priority,
            countdown,
        )
        logger.info(
            "Suggested questions: requested a pool run (%s, priority %s, in %ds)",
            reason.value,
            priority.name,
            countdown,
        )
    except Exception:
        logger.exception("Suggested questions: could not request a pool run")


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
        token = _token(OnyxCeleryPriority.HIGH)
        if not cache.set_if_absent(queued_key, token, ex=SQ_TASK_EXPIRES_S):
            return
        _send(
            cache,
            queued_key,
            token,
            None,
            OnyxCeleryTask.GENERATE_SUGGESTED_QUESTIONS_FOR_USER,
            {"tenant_id": tenant_id, "user_id": str(user_id)},
            OnyxCeleryPriority.HIGH,
            0,
        )
        logger.info("Suggested questions: requested a top-up for %s", user_id)
    except Exception:
        logger.exception("Suggested questions: could not request a top-up")


def drop_orphaned_questions(tenant_id: str) -> None:
    """Remove questions whose document was deleted, then ask for a refill. If
    a run holds the pool, leave it: the run's save step drops them too."""
    try:
        if not is_enabled():
            return
        with pool_lock(SQ_POOL_LOCK_WAIT_S):
            pool = load_pool(refresh_cache=True)
            if pool is None or not pool.questions:
                return
            with get_session_with_current_tenant() as db_session:
                live = get_live_document_ids(db_session, list(pool.document_ids))
            kept = [q for q in pool.questions if q.document_id in live]
            if len(kept) == len(pool.questions):
                return
            save_pool(pool.model_copy(update={"questions": kept}))
        logger.info(
            "Suggested questions: dropped %d questions about deleted documents",
            len(pool.questions) - len(kept),
        )
        request_pool_refresh(tenant_id, RefreshReason.POOL_SHORT)
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


def count_usable_questions(
    pool: QuestionPool, live_document_ids: set[str], now: datetime
) -> int:
    """Questions whose document still exists and that are young enough to
    show."""
    max_age = timedelta(days=SQ_QUESTION_MAX_AGE_DAYS)
    return sum(
        question.document_id in live_document_ids
        and now - question.created_at < max_age
        for question in pool.questions
    )


def worth_running(
    pool: QuestionPool | None,
    now: datetime,
    new_documents: int,
    candidate_documents: int,
    usable_questions: int,
) -> RunDecision:
    """Whether a pool run is useful and not too soon. Checked before any model
    call. `new_documents` counts documents indexed since the last run started;
    `candidate_documents` counts those without a question yet."""
    if candidate_documents < SQ_MIN_CANDIDATE_DOCS:
        return RunDecision(run=False, reason="too few documents without a question")
    last_run = pool.last_run_at() if pool else None
    if pool is None or last_run is None:
        return RunDecision(run=True, reason="first run")
    window_start = now - timedelta(hours=SQ_RUN_WINDOW_HOURS)
    if pool.runs_since(window_start) >= SQ_MAX_POOL_RUNS_PER_DAY:
        return RunDecision(run=False, reason="daily run limit reached")
    since_last_run = now - last_run
    if usable_questions < SQ_POOL_SHORT:
        if since_last_run < timedelta(minutes=SQ_SHORT_GAP_MIN):
            return RunDecision(run=False, reason="running low, but too soon")
        return RunDecision(run=True, reason="running low")
    if new_documents >= SQ_MIN_NEW_DOCS and len(pool.questions) < SQ_POOL_MAX:
        if since_last_run < timedelta(minutes=SQ_GROWTH_GAP_MIN):
            return RunDecision(run=False, reason="new material, but too soon")
        return RunDecision(run=True, reason="new material")
    return RunDecision(run=False, reason="enough questions and no new material")


def _token(priority: OnyxCeleryPriority) -> bytes:
    """A queued flag's value: the run's priority and a value unique to this
    request, so a request only ever removes its own flag."""
    return f"{int(priority)}:{uuid4().hex}".encode()


def _priority_of(token: bytes) -> int:
    return int(token.split(b":", 1)[0])


def _send(
    cache: CacheBackend,
    queued_key: str,
    token: bytes,
    previous: tuple[bytes, int] | None,
    task_name: str,
    kwargs: dict[str, Any],
    priority: OnyxCeleryPriority,
    countdown: int,
) -> None:
    """Send the task. If the send fails, undo this request's flag: put back
    the flag it replaced, with that flag's remaining lifetime, or remove it.
    Another request's flag is left alone."""
    try:
        # Imported here, as other request paths do, so importing this module
        # does not build the Celery app.
        from onyx.background.celery.versioned_apps.client import app as client_app

        client_app.send_task(
            task_name,
            kwargs=kwargs,
            queue=OnyxCeleryQueues.SUGGESTED_QUESTIONS,
            priority=priority,
            countdown=countdown,
            expires=countdown + SQ_TASK_EXPIRES_S,
        )
    except Exception:
        if previous is None:
            cache.delete_if_value(queued_key, token)
        else:
            cache.replace_if_value(queued_key, token, previous[0], ex=previous[1])
        raise
