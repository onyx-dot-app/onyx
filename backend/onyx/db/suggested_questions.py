from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, String, cast, func, or_, select
from sqlalchemy.orm import Session

from onyx.configs.constants import KV_SUGGESTED_QUESTIONS_USER_KEY, DocumentSource
from onyx.db.document_access import apply_document_access_filter
from onyx.db.enums import AccessType, UserFileStatus
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Document,
    KVStore,
    User,
    UserFile,
)
from onyx.utils.special_types import JSON_ro


def _indexed_documents(exclude_ids: set[str]) -> Select[tuple[str, datetime | None]]:
    stmt = select(Document.id, Document.last_synced).where(
        Document.last_synced.is_not(None), Document.hidden.is_(False)
    )
    if exclude_ids:
        stmt = stmt.where(Document.id.not_in(list(exclude_ids)))
    return stmt


def _public_document_ids(db_session: Session) -> Select[tuple[str]]:
    # With no user, the access filter keeps only what everyone can see.
    return apply_document_access_filter(
        db_session, select(Document.id), user_email=None, external_group_ids=[]
    )


def _skip_read_time_access(
    stmt: Select, censored_sources: set[DocumentSource]
) -> Select:
    """Leave out documents whose access is decided per person at read time
    (EE censoring, for example Salesforce records), unless a public pair holds
    them, as search would. Their question could reveal what the person may not
    read. Call after apply_document_access_filter, which joins the pairs."""
    if not censored_sources:
        return stmt
    return stmt.join(
        Connector, Connector.id == ConnectorCredentialPair.connector_id
    ).where(
        or_(
            ConnectorCredentialPair.access_type == AccessType.PUBLIC,
            Connector.source.not_in(list(censored_sources)),
        )
    )


def _newest_ids(
    db_session: Session, stmt: Select[tuple[str, datetime | None]], limit: int
) -> list[str]:
    # The access filter joins one row per connector pair, so de-duplicate.
    stmt = stmt.distinct().order_by(Document.last_synced.desc()).limit(limit)
    return [document_id for document_id, _ in db_session.execute(stmt).tuples()]


def get_newest_public_document_ids(
    db_session: Session,
    limit: int,
    exclude_ids: set[str],
    censored_sources: set[DocumentSource],
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
    return _newest_ids(
        db_session, _skip_read_time_access(stmt, censored_sources), limit
    )


def get_newest_private_document_ids(
    db_session: Session,
    user_email: str,
    external_group_ids: list[str],
    user_id: UUID,
    prior_emails: list[str],
    limit: int,
    exclude_ids: set[str],
    censored_sources: set[DocumentSource],
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
    return _newest_ids(
        db_session, _skip_read_time_access(stmt, censored_sources), limit
    )


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
            UserFile.incognito.is_(False),
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


def count_candidate_documents(db_session: Session, exclude_ids: set[str]) -> int:
    """Indexed documents and finished uploads that are not in `exclude_ids`,
    the documents that already have a question."""
    excluded = list(exclude_ids)
    documents = db_session.scalar(
        select(func.count())
        .select_from(Document)
        .where(
            Document.last_synced.is_not(None),
            Document.hidden.is_(False),
            Document.id.not_in(excluded),
        )
    )
    uploads = db_session.scalar(
        select(func.count())
        .select_from(UserFile)
        .where(
            UserFile.status == UserFileStatus.COMPLETED,
            UserFile.incognito.is_(False),
            cast(UserFile.id, String).not_in(excluded),
        )
    )
    return (documents or 0) + (uploads or 0)


def get_visible_document_ids(
    db_session: Session,
    user: User,
    external_group_ids: list[str],
    document_ids: list[str],
    censored_sources: set[DocumentSource],
) -> set[str]:
    """The ids, out of these, this person may open right now: indexed connector
    documents they can see (the same rules as search, which also skip pairs
    being deleted, and no document search would censor) and their own
    finished uploads."""
    if not document_ids:
        return set()
    connector_stmt = _skip_read_time_access(
        apply_document_access_filter(
            db_session,
            _indexed_documents(set()).where(Document.id.in_(document_ids)),
            user_email=user.email,
            external_group_ids=external_group_ids,
            user_id=user.id,
            prior_emails=user.prior_emails,
        ),
        censored_sources,
    )
    visible = {document_id for document_id, _ in db_session.execute(connector_stmt)}
    uploads = select(UserFile.id).where(
        cast(UserFile.id, String).in_(document_ids),
        UserFile.user_id == user.id,
        UserFile.status == UserFileStatus.COMPLETED,
        UserFile.incognito.is_(False),
    )
    return visible | {str(user_file_id) for user_file_id in db_session.scalars(uploads)}


def has_visible_documents(
    db_session: Session, user: User, external_group_ids: list[str]
) -> bool:
    """Whether this person can open any indexed document or finished upload."""
    connector_stmt = apply_document_access_filter(
        db_session,
        _indexed_documents(set()),
        user_email=user.email,
        external_group_ids=external_group_ids,
        user_id=user.id,
        prior_emails=user.prior_emails,
    ).limit(1)
    if db_session.execute(connector_stmt).first() is not None:
        return True
    uploads = (
        select(UserFile.id)
        .where(
            UserFile.user_id == user.id,
            UserFile.status == UserFileStatus.COMPLETED,
            UserFile.incognito.is_(False),
        )
        .limit(1)
    )
    return db_session.execute(uploads).first() is not None


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
