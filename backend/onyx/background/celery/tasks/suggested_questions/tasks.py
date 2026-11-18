"""The two suggested-questions runs: one for the company's pool, one for a
person who is short of questions. Both hold the pool lock for the whole run
and check again, under the lock, that the run is still worth its model calls.
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from celery import Task, shared_task
from celery.utils.log import get_task_logger

from onyx.background.celery.tasks.suggested_questions.scheduling import (
    count_usable_questions,
    is_enabled,
    release_pool_flag,
    release_topup_flag,
    topup_allowed,
    worth_running,
)
from onyx.cache.interface import CacheLockAcquisitionError
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import User
from onyx.db.suggested_questions import (
    count_candidate_documents,
    count_new_documents_since,
)
from onyx.db.users import fetch_user_by_id
from onyx.secondary_llm_flows.suggested_questions import (
    build_triage_clients,
    build_writing_llms,
    triage_chunks,
    write_questions,
)
from onyx.server.features.suggested_questions.config import (
    SQ_LOCK_BUSY_RETRY_S,
    SQ_RUN_BUDGET_S,
    SQ_RUN_RETRIES,
    SQ_RUN_RETRY_DELAY_S,
    SQ_RUN_WINDOW_HOURS,
)
from onyx.server.features.suggested_questions.models import (
    CandidateDocument,
    PoolQuestion,
    QuestionPool,
)
from onyx.server.features.suggested_questions.selection import (
    best_chunks_per_document,
    choose_documents,
    fetch_chunks,
)
from onyx.server.features.suggested_questions.store import (
    get_live_document_ids,
    get_recently_active_users,
    load_pool,
    load_user_record,
    merge_questions,
    pool_lock,
    record_topup,
    role_for,
    save_pool,
)
from onyx.server.features.suggested_questions.verification import run_search_test
from onyx.server.settings.store import load_settings

task_logger = get_task_logger(__name__)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class RunOutOfTime(Exception):
    """The run used its time budget before its next model call."""


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.GENERATE_SUGGESTED_QUESTIONS_POOL,
    bind=True,
    ignore_result=True,
    max_retries=SQ_RUN_RETRIES,
)
def generate_suggested_questions_pool(
    self: Task, *, tenant_id: str, reason: str
) -> None:
    if not _start(lambda: release_pool_flag(tenant_id)):
        return
    try:
        # Without waiting: a run that holds the pool covers this request.
        with pool_lock(0):
            _run_pool(tenant_id, reason)
    except CacheLockAcquisitionError:
        task_logger.info("Suggested questions: a run holds the pool, skipping")
    except Exception as e:
        task_logger.exception("Suggested questions: pool run failed (%s)", reason)
        raise self.retry(exc=e, countdown=SQ_RUN_RETRY_DELAY_S)


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.GENERATE_SUGGESTED_QUESTIONS_FOR_USER,
    bind=True,
    ignore_result=True,
    max_retries=SQ_RUN_RETRIES,
)
def generate_suggested_questions_for_user(
    self: Task, *, tenant_id: str, user_id: str
) -> None:
    if not _start(lambda: release_topup_flag(tenant_id, UUID(user_id))):
        return
    try:
        with pool_lock(0):
            _run_topup(tenant_id, UUID(user_id))
    except CacheLockAcquisitionError:
        # The person is waiting, so try again soon rather than skip.
        raise self.retry(countdown=SQ_LOCK_BUSY_RETRY_S)
    except Exception as e:
        task_logger.exception("Suggested questions: top-up failed for %s", user_id)
        raise self.retry(exc=e, countdown=SQ_RUN_RETRY_DELAY_S)


def _start(release_flag: Callable[[], None]) -> bool:
    """Free the task's queued flag, then say whether runs are on. Neither step
    may fail the task: a flag that stays set only delays the next request, and
    an unknown trial status means no run."""
    try:
        release_flag()
    except Exception:
        task_logger.warning(
            "Suggested questions: could not free the queued flag", exc_info=True
        )
    try:
        return is_enabled()
    except Exception:
        task_logger.warning(
            "Suggested questions: trial status unknown, skipping", exc_info=True
        )
        return False


def _run_pool(tenant_id: str, reason: str) -> None:
    started = datetime.now(UTC)
    deadline = time.monotonic() + SQ_RUN_BUDGET_S
    stored = load_pool(refresh_cache=True)
    pool = stored or QuestionPool()
    with get_session_with_current_tenant() as db_session:
        live = get_live_document_ids(db_session, list(pool.document_ids))
        decision = worth_running(
            stored,
            started,
            new_documents=count_new_documents_since(
                db_session, pool.last_run_at() or _EPOCH
            ),
            candidate_documents=count_candidate_documents(
                db_session, pool.document_ids
            ),
            usable_questions=count_usable_questions(pool, live, started),
        )
        if not decision.run:
            task_logger.info(
                "Suggested questions: pool run skipped (%s): %s",
                reason,
                decision.reason,
            )
            return
        people = get_recently_active_users(db_session, started)
        candidates = choose_documents(db_session, people, pool.document_ids)
        docs_now = count_candidate_documents(db_session, set())
    roles = sorted({role for person in people if (role := role_for(person))})
    added = _write_and_test(tenant_id, candidates, roles, None, deadline)
    _save(
        pool.record_run(started, docs_now, timedelta(hours=SQ_RUN_WINDOW_HOURS)),
        added,
    )
    task_logger.info(
        "Suggested questions: pool run (%s, %s) added %d questions",
        reason,
        decision.reason,
        len(added),
    )


def _run_topup(tenant_id: str, user_id: UUID) -> None:
    started = datetime.now(UTC)
    deadline = time.monotonic() + SQ_RUN_BUDGET_S
    # Checked again under the lock: a retry may come after the limits filled.
    if not topup_allowed(load_user_record(user_id, refresh_cache=True), started):
        return
    pool = load_pool(refresh_cache=True) or QuestionPool()
    with get_session_with_current_tenant() as db_session:
        user = fetch_user_by_id(db_session, user_id)
        if user is None or not user.is_active:
            return
        candidates = choose_documents(
            db_session, [user], pool.document_ids, prefer_private=True
        )
    # TODO(ENG-4487): also stop when the person already has enough questions,
    # once the per-person pick (the API PR of this stack) can count them.
    if not candidates:
        task_logger.info("Suggested questions: nothing new for %s", user_id)
        return
    record_topup(user_id, started, timedelta(hours=SQ_RUN_WINDOW_HOURS))
    role = role_for(user)
    added = _write_and_test(
        tenant_id, candidates, [role] if role else [], user, deadline
    )
    _save(pool, added)
    task_logger.info(
        "Suggested questions: top-up for %s added %d questions", user_id, len(added)
    )


def _write_and_test(
    tenant_id: str,
    candidates: list[CandidateDocument],
    roles: list[str],
    user: User | None,
    deadline: float,
) -> list[PoolQuestion]:
    """The model steps: triage, the writing call, and the search test. A pool
    run passes no user; a top-up passes the person."""
    with get_session_with_current_tenant() as db_session:
        chunks = fetch_chunks(db_session, candidates, tenant_id)
    passages = best_chunks_per_document(triage_chunks(chunks, build_triage_clients()))
    _check_deadline(deadline)
    drafts = write_questions(
        passages, build_writing_llms(), load_settings().company_name, roles
    )
    _check_deadline(deadline)
    return run_search_test(drafts, user=user)


def _save(pool: QuestionPool, added: list[PoolQuestion]) -> None:
    """Merge the new questions into the pool, dropping those whose document
    is gone, and store it."""
    ids = list({q.document_id for q in [*pool.questions, *added]})
    with get_session_with_current_tenant() as db_session:
        live = get_live_document_ids(db_session, ids)
    save_pool(
        pool.model_copy(
            update={"questions": merge_questions(pool.questions, added, live)}
        )
    )


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise RunOutOfTime("Suggested-questions run used its time budget")
