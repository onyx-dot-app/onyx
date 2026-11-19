from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.constants import KV_SUGGESTED_QUESTIONS_USER_KEY
from onyx.db.models import KVStore
from onyx.utils.special_types import JSON_ro


def load_user_record_values(
    db_session: Session, user_ids: list[UUID]
) -> dict[UUID, JSON_ro]:
    """Read many people's suggested-questions records in one query, straight
    from Postgres. People without a stored record are absent from the result."""
    if not user_ids:
        return {}
    user_id_by_key = {
        KV_SUGGESTED_QUESTIONS_USER_KEY.format(user_id): user_id for user_id in user_ids
    }
    rows = (
        db_session.execute(
            select(KVStore.key, KVStore.value).where(
                KVStore.key.in_(list(user_id_by_key))
            )
        )
        .tuples()
        .all()
    )
    return {user_id_by_key[key]: value for key, value in rows}
