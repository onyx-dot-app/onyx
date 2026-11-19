"""The two suggested-questions runs: one for the company's pool, one for a
person who is short of questions. Both hold the pool lock for the whole run
and check again, under the lock, that the run is still worth its model calls.
"""

import time
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from celery import Task, shared_task
from celery.utils.log import get_task_logger

from onyx.cache.interface import CacheLockAcquisitionError
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import User
from onyx.db.suggested_questions import count_candidate_documents
from onyx.db.users import fetch_user_by_id
from onyx.secondary_llm_flows.suggested_questions import (
    build_triage_clients,
    build_writing_llms,
    triage_chunks,
    write_questions,
)
from onyx.server.features.suggested_questions.config import (
    SQ_LOCK_BUSY_RETRY_S,
    SQ_POOL_BUSY_RETRY_S,
    SQ_POOL_LOCK_HELD_S,
    SQ_PRIVATE_REFILL_AT,
    SQ_RUN_BUDGET_S,
    SQ_RUN_RETRIES,
    SQ_RUN_RETRY_DELAY_S,
    SQ_RUN_WINDOW_HOURS,
    SQ_SAVE_MARGIN_S,
)
from onyx.server.features.suggested_questions.models import (
    CandidateDocument,
    PoolQuestion,
    QuestionPool,
)
from onyx.server.features.suggested_questions.scheduling import (
    count_usable_questions,
    fresh_document_ids,
    is_enabled,
    release_pool_flag,
    release_topup_flag,
    topup_allowed,
    worth_running,
)
from onyx.server.features.suggested_questions.selection import (
    NothingSearchableYet,
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
    save_private_questions,
)
from onyx.server.features.suggested_questions.verification import run_search_test
from onyx.server.settings.store import load_settings

task_logger = get_task_logger(__name__)


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
    if not _start(self, lambda: release_pool_flag(tenant_id)):
        return
    try:
        with pool_lock(0):
            _run_pool(tenant_id, reason)
    except CacheLockAcquisitionError:
        # Try again later rather than drop the request: documents indexed
        # during the running run are not in it. worth_running decides then.
        _retry_later(
            self,
            SQ_POOL_BUSY_RETRY_S,
            {"tenant_id": tenant_id, "reason": reason},
            "pool still busy",
        )
    except NothingSearchableYet:
        # Not recorded as a run, so a first run stays a first run.
        _retry_later(
            self,
            SQ_RUN_RETRY_DELAY_S,
            {"tenant_id": tenant_id, "reason": reason},
            "documents not searchable yet",
        )
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
    self: Task, *, tenant_id: str, user_id: str, recorded: bool = False
) -> None:
    """`recorded` is set on a retry whose attempt already counts against the
    person's top-up limits, so the retry finishes it instead of being refused
    by the gap it just recorded."""
    if not _start(self, lambda: release_topup_flag(tenant_id, UUID(user_id))):
        return
    attempt = {"recorded": recorded}
    try:
        with pool_lock(0):
            _run_topup(tenant_id, UUID(user_id), attempt)
    except CacheLockAcquisitionError:
        # The person is waiting, so try again soon.
        _retry_later(
            self,
            SQ_LOCK_BUSY_RETRY_S,
            {"tenant_id": tenant_id, "user_id": user_id, **attempt},
            "pool still busy",
        )
    except NothingSearchableYet:
        _retry_later(
            self,
            SQ_RUN_RETRY_DELAY_S,
            {"tenant_id": tenant_id, "user_id": user_id, **attempt},
            "documents not searchable yet",
        )
    except Exception as e:
        task_logger.exception("Suggested questions: top-up failed for %s", user_id)
        raise self.retry(
            exc=e,
            countdown=SQ_RUN_RETRY_DELAY_S,
            kwargs={"tenant_id": tenant_id, "user_id": user_id, **attempt},
        )


def _retry_later(task: Task, countdown: int, kwargs: dict[str, Any], why: str) -> None:
    """Retry a run that could not start its work: the pool was locked, or its
    documents were not searchable yet. After the last retry, stop quietly:
    a later request runs it again."""
    if task.max_retries is not None and task.request.retries >= task.max_retries:
        task_logger.info("Suggested questions: %s, giving up", why)
        return
    raise task.retry(countdown=countdown, kwargs=kwargs)


def _start(task: Task, release_flag: Callable[[], None]) -> bool:
    """Free the task's queued flag, then say whether runs are on. Neither step
    may fail the task: a flag that stays set only delays the next request, and
    an unknown trial status means no run. A retry leaves the flag alone: the
    first delivery freed it, so a flag set now belongs to a newer request."""
    try:
        if not task.request.retries:
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
    clock = _RunClock()
    stored = load_pool(refresh_cache=True)
    pool = stored or QuestionPool()
    # Documents whose question expired may get a new one.
    covered = fresh_document_ids(pool.questions, started)
    with get_session_with_current_tenant() as db_session:
        decision = worth_running(
            stored, started, count_candidate_documents(db_session, covered)
        )
        if not decision.run:
            task_logger.info(
                "Suggested questions: pool run skipped (%s): %s",
                reason,
                decision.reason,
            )
            return
        people = get_recently_active_users(db_session, started)
        # Each person's private shelf skips the documents already on it.
        private_covered = {
            person.id: fresh_document_ids(
                load_user_record(person.id, refresh_cache=True).questions, started
            )
            for person in people
        }
        candidates = choose_documents(db_session, people, covered, private_covered)
        docs_now = count_candidate_documents(db_session, set())
    roles = sorted({role for person in people if (role := role_for(person))})
    added = _write_and_test(tenant_id, candidates, roles, None, clock)
    _save(
        pool.record_run(started, docs_now, timedelta(hours=SQ_RUN_WINDOW_HOURS)),
        added,
        candidates,
        started,
        clock,
    )
    private_documents = {c.document_id for c in candidates if c.owner_ids}
    private_added = sum(q.document_id in private_documents for q in added)
    task_logger.info(
        "Suggested questions: pool run (%s, %s) added %d shared and %d private questions",
        reason,
        decision.reason,
        len(added) - private_added,
        private_added,
    )


def _run_topup(tenant_id: str, user_id: UUID, attempt: dict[str, bool]) -> None:
    started = datetime.now(UTC)
    clock = _RunClock()
    record = load_user_record(user_id, refresh_cache=True)
    # Checked again under the lock, unless this retry's attempt already counts.
    if not attempt["recorded"] and not topup_allowed(record, started):
        return
    with get_session_with_current_tenant() as db_session:
        user = fetch_user_by_id(db_session, user_id)
        if user is None or not user.is_active:
            return
        unused = [q for q in record.questions if q.id not in record.used]
        live = get_live_document_ids(db_session, [q.document_id for q in unused])
        if count_usable_questions(unused, live, started) > SQ_PRIVATE_REFILL_AT:
            task_logger.info("Suggested questions: %s has enough questions", user_id)
            return
        # The person's own documents only: pool runs fill the shared shelf.
        candidates = choose_documents(
            db_session,
            [user],
            set(),
            {user.id: fresh_document_ids(record.questions, started)},
            include_shared=False,
        )
    if not candidates:
        task_logger.info("Suggested questions: nothing new for %s", user_id)
        return
    if not attempt["recorded"]:
        record_topup(user_id, started, timedelta(hours=SQ_RUN_WINDOW_HOURS))
        attempt["recorded"] = True
    role = role_for(user)
    added = _write_and_test(tenant_id, candidates, [role] if role else [], user, clock)
    _save(None, added, candidates, started, clock)
    task_logger.info(
        "Suggested questions: top-up for %s added %d questions", user_id, len(added)
    )


def _write_and_test(
    tenant_id: str,
    candidates: list[CandidateDocument],
    roles: list[str],
    user: User | None,
    clock: "_RunClock",
) -> list[PoolQuestion]:
    """The model steps: triage, the writing call, and the search test. A pool
    run passes no user; a top-up passes the person."""
    with get_session_with_current_tenant() as db_session:
        chunks = fetch_chunks(db_session, candidates, tenant_id)
    passages = best_chunks_per_document(triage_chunks(chunks, build_triage_clients()))
    # Keep the candidates' order (a top-up's private documents first), so the
    # writing call's passage limit drops the least wanted ones.
    rank = {c.document_id: i for i, c in enumerate(candidates)}
    passages.sort(key=lambda p: rank.get(p.chunk.document_id, len(rank)))
    clock.check()
    drafts = write_questions(
        passages, build_writing_llms(), load_settings().company_name, roles
    )
    clock.check()
    return run_search_test(drafts, user=user, timeout_s=clock.remaining())


def _save(
    pool: QuestionPool | None,
    added: list[PoolQuestion],
    candidates: list[CandidateDocument],
    now: datetime,
    clock: "_RunClock",
) -> None:
    """Put each new question on its shelf: the shared shelf in the pool, or the
    private shelf of each person whose bucket chose its document. Questions
    whose document is gone and those too old to show leave the shelves. A
    top-up passes no pool. Refuses to save when the pool lock may have expired,
    so a late run cannot overwrite newer shelves."""
    owners = {c.document_id: c.owner_ids for c in candidates}
    shared_added = [q for q in added if not owners.get(q.document_id)]
    private_added: dict[UUID, list[PoolQuestion]] = defaultdict(list)
    for question in added:
        for owner_id in owners.get(question.document_id, []):
            private_added[owner_id].append(question)
    kept = [q for q in pool.questions if q.is_fresh(now)] if pool else []
    shelves = [
        load_user_record(owner_id, refresh_cache=True).questions
        for owner_id in private_added
    ]
    ids = {q.document_id for q in [*kept, *added]} | {
        q.document_id for shelf in shelves for q in shelf
    }
    with get_session_with_current_tenant() as db_session:
        live = get_live_document_ids(db_session, list(ids))
    clock.check_lock()
    if pool is not None:
        save_pool(
            pool.model_copy(
                update={"questions": merge_questions(kept, shared_added, live)}
            )
        )
    for owner_id, questions in private_added.items():
        save_private_questions(owner_id, questions, live, now)


class _RunClock:
    """The run's own time limits: Celery time limits do not apply in thread
    pools."""

    def __init__(self) -> None:
        self._started = time.monotonic()

    def remaining(self) -> float:
        return max(0.0, self._started + SQ_RUN_BUDGET_S - time.monotonic())

    def check(self) -> None:
        if self.remaining() == 0.0:
            raise RunOutOfTime("Suggested-questions run used its time budget")

    def check_lock(self) -> None:
        # The Redis lease expires SQ_POOL_LOCK_HELD_S after the lock was taken.
        if time.monotonic() - self._started > SQ_POOL_LOCK_HELD_S - SQ_SAVE_MARGIN_S:
            raise RunOutOfTime("The pool lock may have expired; not saving")
