from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.cache.locks import cache_shared_lock
from onyx.configs.constants import (
    KV_SUGGESTED_QUESTIONS_POOL_KEY,
    KV_SUGGESTED_QUESTIONS_USER_KEY,
)
from onyx.db.document import filter_existing_document_ids
from onyx.db.enums import AccountType
from onyx.db.models import User
from onyx.db.suggested_questions import load_user_record_values
from onyx.db.user_file import filter_existing_user_file_ids_any_owner
from onyx.db.users import get_all_users
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.features.suggested_questions.config import (
    SQ_ACTIVE_DAYS,
    SQ_POOL_LOCK_HELD_S,
    SQ_PRIVATE_SHELF,
    SQ_SHARED_SHELF,
    SQ_USED_IDS_MAX,
    SQ_USER_RECORD_LOCK_TIMEOUT_S,
)
from onyx.server.features.suggested_questions.models import (
    PoolQuestion,
    QuestionPool,
    UseCase,
    UserRecord,
)
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def load_pool(refresh_cache: bool = False) -> QuestionPool | None:
    """Pass refresh_cache=True under pool_lock: an unlocked reader can refill
    the cache with an older pool after a locked writer has saved."""
    try:
        stored = get_kv_store().load(
            KV_SUGGESTED_QUESTIONS_POOL_KEY, refresh_cache=refresh_cache
        )
    except KvKeyNotFoundError:
        return None
    return QuestionPool.model_validate(stored)


def save_pool(pool: QuestionPool) -> None:
    get_kv_store().store(KV_SUGGESTED_QUESTIONS_POOL_KEY, pool.model_dump(mode="json"))


def pool_lock(wait_s: float) -> AbstractContextManager[None]:
    """The lock a pool run, a top-up and a deletion take before they change
    the company's pool. Raises CacheLockAcquisitionError after `wait_s`."""
    return cache_shared_lock(
        lock_name=f"suggested_questions_pool:{get_current_tenant_id()}",
        max_time_lock_held_s=SQ_POOL_LOCK_HELD_S,
        wait_for_lock_s=wait_s,
        logger=logger,
    )


def get_live_document_ids(db_session: Session, document_ids: list[str]) -> set[str]:
    """The ids, out of these, whose connector document or upload still exists."""
    return filter_existing_document_ids(
        db_session, document_ids
    ) | filter_existing_user_file_ids_any_owner(db_session, document_ids)


def merge_questions(
    existing: Iterable[PoolQuestion],
    new: Iterable[PoolQuestion],
    live_document_ids: set[str],
    max_size: int = SQ_SHARED_SHELF,
) -> list[PoolQuestion]:
    """Merge a run's questions into a shelf: drop questions whose document is
    gone, keep one question per document (the best search position, then the
    newest), and keep the newest `max_size`."""

    def rank(question: PoolQuestion) -> tuple[int, float]:
        return question.search_position, -question.created_at.timestamp()

    best_by_document: dict[str, PoolQuestion] = {}
    for question in [*existing, *new]:
        if question.document_id not in live_document_ids:
            continue
        current = best_by_document.get(question.document_id)
        if current is None or rank(question) < rank(current):
            best_by_document[question.document_id] = question
    newest_first = sorted(
        best_by_document.values(),
        key=lambda question: question.created_at,
        reverse=True,
    )
    return newest_first[:max_size]


def load_user_record(user_id: UUID, refresh_cache: bool = False) -> UserRecord:
    try:
        stored = get_kv_store().load(
            KV_SUGGESTED_QUESTIONS_USER_KEY.format(user_id),
            refresh_cache=refresh_cache,
        )
    except KvKeyNotFoundError:
        return UserRecord()
    return UserRecord.model_validate(stored)


def _update_user_record(
    user_id: UUID, update: Callable[[UserRecord], UserRecord]
) -> UserRecord:
    """Read, change and store one person's record under a lock, so two chat tabs
    cannot drop each other's changes."""
    with cache_shared_lock(
        lock_name=f"suggested_questions_user:{get_current_tenant_id()}:{user_id}",
        max_time_lock_held_s=SQ_USER_RECORD_LOCK_TIMEOUT_S,
        wait_for_lock_s=SQ_USER_RECORD_LOCK_TIMEOUT_S,
        logger=logger,
    ):
        # Read Postgres, not the cache: an unlocked reader can refill the
        # cache with an older value after a locked writer has saved.
        record = update(load_user_record(user_id, refresh_cache=True))
        get_kv_store().store(
            KV_SUGGESTED_QUESTIONS_USER_KEY.format(user_id),
            record.model_dump(mode="json"),
        )
        return record


def record_seen(user_id: UUID, now: datetime) -> UserRecord:
    def mark(record: UserRecord) -> UserRecord:
        # Two tabs can take the lock out of order; never move the time back.
        if record.last_seen_at is not None and record.last_seen_at >= now:
            return record
        return record.model_copy(update={"last_seen_at": now})

    return _update_user_record(user_id, mark)


def mark_used(user_id: UUID, question_id: str) -> UserRecord:
    def add(record: UserRecord) -> UserRecord:
        if question_id in record.used:
            return record
        return record.model_copy(
            update={"used": [*record.used, question_id][-SQ_USED_IDS_MAX:]}
        )

    return _update_user_record(user_id, add)


def record_topup(user_id: UUID, now: datetime, window: timedelta) -> UserRecord:
    return _update_user_record(user_id, lambda record: record.record_topup(now, window))


def save_private_questions(
    user_id: UUID,
    added: list[PoolQuestion],
    live_document_ids: set[str],
    now: datetime,
) -> None:
    """Merge a run's questions into one person's private shelf. Questions the
    person used, questions too old to show and questions whose document is gone
    leave it; the newest SQ_PRIVATE_SHELF stay, one per document. Saved under
    the person's record lock, so a click saved at the same moment is not lost.
    Callers hold the pool lock, so no other run changes the shelf meanwhile."""

    def merge(record: UserRecord) -> UserRecord:
        kept = [
            question
            for question in record.questions
            if question.id not in record.used and question.is_fresh(now)
        ]
        return record.model_copy(
            update={
                "questions": merge_questions(
                    kept, added, live_document_ids, SQ_PRIVATE_SHELF
                )
            }
        )

    _update_user_record(user_id, merge)


def load_private_shelves(db_session: Session) -> dict[UUID, list[PoolQuestion]]:
    """Every person's private shelf that holds questions, in one query."""
    users = get_all_users(db_session, include_api_key_users=False)
    stored = load_user_record_values(db_session, [user.id for user in users])
    shelves: dict[UUID, list[PoolQuestion]] = {}
    for user_id, value in stored.items():
        questions = UserRecord.model_validate(value).questions
        if questions:
            shelves[user_id] = questions
    return shelves


def get_recently_active_users(db_session: Session, now: datetime) -> list[User]:
    """People the pool should cover: those who opened the chat in the last
    SQ_ACTIVE_DAYS days, and those who have never opened it, who are most
    likely new. Only people who came and then stayed away are left out."""
    people = [
        user
        for user in get_all_users(db_session, include_api_key_users=False)
        if user.is_active and user.account_type == AccountType.STANDARD
    ]
    stored = load_user_record_values(db_session, [user.id for user in people])
    since = now - timedelta(days=SQ_ACTIVE_DAYS)
    active = []
    for user in people:
        record_value = stored.get(user.id)
        last_seen_at = (
            UserRecord.model_validate(record_value).last_seen_at
            if record_value is not None
            else None
        )
        if last_seen_at is None or last_seen_at >= since:
            active.append(user)
    return active


def role_for(user: User) -> str | None:
    # TODO(ENG-4481): onboarding will fill personal_role for every person.
    return user.personal_role


def use_case_for(user: User) -> UseCase:  # noqa: ARG001
    # TODO(ENG-4481): return the company use case the first admin picks in
    # onboarding. Until it is stored, every person gets OTHER, so ranking by
    # use case changes nothing.
    return UseCase.OTHER
