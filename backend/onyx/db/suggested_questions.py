from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from onyx.configs.constants import KV_SUGGESTED_QUESTIONS_USER_KEY
from onyx.db.document_access import apply_document_access_filter
from onyx.db.enums import UserFileStatus
from onyx.db.models import Document, KVStore, UserFile
from onyx.utils.special_types import JSON_ro


def _indexed_documents(exclude_ids: set[str]) -> Select:
    stmt = select(Document.id, Document.last_synced).where(
        Document.last_synced.is_not(None), Document.hidden.is_(False)
    )
    if exclude_ids:
        stmt = stmt.where(Document.id.not_in(list(exclude_ids)))
    return stmt


def _public_document_ids(db_session: Session) -> Select:
    # With no user, the access filter keeps only what everyone can see.
    return apply_document_access_filter(
        db_session, select(Document.id), user_email=None, external_group_ids=[]
    )


def _newest_ids(db_session: Session, stmt: Select, limit: int) -> list[str]:
    # The access filter joins one row per connector pair, so de-duplicate.
    stmt = stmt.distinct().order_by(Document.last_synced.desc()).limit(limit)
    return [document_id for document_id, _ in db_session.execute(stmt).tuples()]


def get_newest_public_document_ids(
    db_session: Session, limit: int, exclude_ids: set[str]
) -> list[str]:
    """Connector documents everyone in the tenant can see, newest first by when
    Onyx indexed them (`last_synced`). We do not sort by when the document was
    last edited in its source: a file last edited years ago but connected today
    would then sort last, though it is new to this tenant."""
    stmt = apply_document_access_filter(
        db_session,
        _indexed_documents(exclude_ids),
        user_email=None,
        external_group_ids=[],
    )
    return _newest_ids(db_session, stmt, limit)


def get_newest_private_document_ids(
    db_session: Session,
    user_email: str,
    external_group_ids: list[str],
    user_id: UUID,
    prior_emails: list[str],
    limit: int,
    exclude_ids: set[str],
) -> list[str]:
    """Connector documents this person can see and not everyone can, newest
    first by when Onyx indexed them. Uses the same access rules as search."""
    stmt = apply_document_access_filter(
        db_session,
        _indexed_documents(exclude_ids).where(
            Document.id.not_in(_public_document_ids(db_session))
        ),
        user_email=user_email,
        external_group_ids=external_group_ids,
        user_id=user_id,
        prior_emails=prior_emails,
    )
    return _newest_ids(db_session, stmt, limit)


def get_recent_user_file_ids(
    db_session: Session, user_id: UUID, limit: int, exclude_ids: set[str]
) -> list[str]:
    """A person's finished uploads, newest first, as their ids in the search
    index. Incognito uploads are left out: they belong to one chat."""
    stmt = (
        select(UserFile.id)
        .where(
            UserFile.user_id == user_id,
            UserFile.status == UserFileStatus.COMPLETED,
            UserFile.incognito_session_id.is_(None),
        )
        .order_by(
            UserFile.last_project_sync_at.desc().nulls_last(),
            UserFile.created_at.desc(),
        )
        .limit(limit + len(exclude_ids))
    )
    user_file_ids = [str(user_file_id) for user_file_id in db_session.scalars(stmt)]
    return [
        user_file_id
        for user_file_id in user_file_ids
        if user_file_id not in exclude_ids
    ][:limit]


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
