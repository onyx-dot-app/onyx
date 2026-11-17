from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.cache.locks import cache_shared_lock
from onyx.configs.constants import (
    KV_SUGGESTED_QUESTIONS_POOL_KEY,
    KV_SUGGESTED_QUESTIONS_USER_KEY,
)
from onyx.db.enums import AccountType
from onyx.db.models import User
from onyx.db.suggested_questions import load_user_record_values
from onyx.db.users import get_all_users
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.features.suggested_questions.config import (
    SQ_ACTIVE_DAYS,
    SQ_POOL_MAX,
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


def load_pool() -> QuestionPool | None:
    try:
        stored = get_kv_store().load(KV_SUGGESTED_QUESTIONS_POOL_KEY)
    except KvKeyNotFoundError:
        return None
    return QuestionPool.model_validate(stored)


def save_pool(pool: QuestionPool) -> None:
    get_kv_store().store(KV_SUGGESTED_QUESTIONS_POOL_KEY, pool.model_dump(mode="json"))


def merge_questions(
    existing: Iterable[PoolQuestion],
    new: Iterable[PoolQuestion],
    live_document_ids: set[str],
    max_size: int = SQ_POOL_MAX,
) -> list[PoolQuestion]:
    """Merge a run's questions into the pool: drop questions whose document is
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
    return _update_user_record(
        user_id, lambda record: record.model_copy(update={"last_seen_at": now})
    )


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
