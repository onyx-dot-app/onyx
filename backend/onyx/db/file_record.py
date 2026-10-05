from datetime import timedelta

from sqlalchemy import ColumnElement, String, and_, case, cast, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.background.task_utils import QUERY_REPORT_NAME_PREFIX
from onyx.configs.constants import FileOrigin, FileType
from onyx.db.enums import IndexingStatus
from onyx.db.models import FileRecord, IndexAttempt
from onyx.file_store.constants import (
    CONTENT_SHA256_METADATA_KEY,
    INCOGNITO_SESSION_METADATA_KEY,
    STAGED_FOR_CC_PAIR_METADATA_KEY,
)
from onyx.file_store.models import StoredFileFacts
from shared_configs.contextvars import CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR


def get_query_history_export_files(
    db_session: Session,
) -> list[FileRecord]:
    return list(
        db_session.scalars(
            select(FileRecord).where(
                and_(
                    FileRecord.file_id.like(f"{QUERY_REPORT_NAME_PREFIX}-%"),
                    FileRecord.file_type == FileType.CSV,
                    FileRecord.file_origin == FileOrigin.QUERY_HISTORY_CSV,
                )
            )
        )
    )


def get_filerecord_by_file_id_optional(
    file_id: str,
    db_session: Session,
) -> FileRecord | None:
    return db_session.query(FileRecord).filter_by(file_id=file_id).first()


class FileRecordNotFoundError(RuntimeError):
    """Raised when a file record does not exist (e.g. the file was deleted).

    Subclasses RuntimeError so existing `except RuntimeError` call sites keep
    working; callers that need to distinguish "file is gone" from transient
    infrastructure failures can catch this type specifically.
    """


def get_filerecord_by_file_id(
    file_id: str,
    db_session: Session,
) -> FileRecord:
    filestore = db_session.query(FileRecord).filter_by(file_id=file_id).first()

    if not filestore:
        raise FileRecordNotFoundError(
            f"File by id {file_id} does not exist or was deleted"
        )

    return filestore


def get_filerecords_by_file_ids(
    file_ids: list[str],
    db_session: Session,
) -> list[FileRecord]:
    """Fetch all matching file records in a single query. Missing IDs are
    simply absent from the result."""
    if not file_ids:
        return []
    return list(
        db_session.scalars(select(FileRecord).where(FileRecord.file_id.in_(file_ids)))
    )


def get_stored_file_facts(
    db_session: Session, file_ids: list[str]
) -> dict[str, StoredFileFacts]:
    """The facts of each given file that has a record, by file id."""
    facts: dict[str, StoredFileFacts] = {}
    for record in get_filerecords_by_file_ids(file_ids, db_session):
        metadata = (
            record.file_metadata if isinstance(record.file_metadata, dict) else {}
        )
        content_sha256 = metadata.get(CONTENT_SHA256_METADATA_KEY)
        facts[record.file_id] = StoredFileFacts(
            display_name=record.display_name or record.file_id,
            file_type=record.file_type,
            content_sha256=content_sha256 if isinstance(content_sha256, str) else None,
        )
    return facts


def get_object_keys_with_records(
    bucket_name: str, object_keys: list[str], db_session: Session
) -> set[str]:
    """The given keys that a file record in this bucket points at."""
    if not object_keys:
        return set()
    return set(
        db_session.scalars(
            select(FileRecord.object_key).where(
                FileRecord.bucket_name == bucket_name,
                FileRecord.object_key.in_(object_keys),
            )
        )
    )


def update_filerecord_file_sizes(
    file_sizes: dict[str, int],
    db_session: Session,
) -> None:
    """Persist lazily-discovered sizes for records written before the
    file_size column existed. Caller commits."""
    if not file_sizes:
        return
    db_session.execute(
        update(FileRecord)
        .where(FileRecord.file_id.in_(file_sizes.keys()))
        # Only fill still-empty sizes: a concurrent overwrite may have
        # persisted a fresh size after this listing's lookup started.
        .where(FileRecord.file_size.is_(None))
        .values(file_size=case(file_sizes, value=FileRecord.file_id))
    )


def get_filerecord_by_prefix(
    prefix: str,
    db_session: Session,
) -> list[FileRecord]:
    if not prefix:
        return db_session.query(FileRecord).all()
    return (
        db_session.query(FileRecord).filter(FileRecord.file_id.like(f"{prefix}%")).all()
    )


def delete_filerecord_by_file_id(
    file_id: str,
    db_session: Session,
) -> None:
    db_session.query(FileRecord).filter_by(file_id=file_id).delete()


def update_filerecord_origin(
    file_id: str,
    from_origin: FileOrigin,
    to_origin: FileOrigin,
    db_session: Session,
) -> None:
    """Change a file_record's `file_origin`, filtered on the current origin
    so the update is idempotent. Caller owns the commit.
    """
    db_session.query(FileRecord).filter(
        FileRecord.file_id == file_id,
        FileRecord.file_origin == from_origin,
    ).update({FileRecord.file_origin: to_origin})


def get_staged_file_ids_by_index_attempt_id(
    index_attempt_id: int,
    db_session: Session,
) -> list[str]:
    """Return every `INDEXING_STAGING` file_id tagged with this attempt."""
    return list(
        db_session.scalars(
            select(FileRecord.file_id)
            .where(FileRecord.file_origin == FileOrigin.INDEXING_STAGING)
            .where(
                FileRecord.file_metadata["index_attempt_id"].as_string()
                == str(index_attempt_id)
            )
        ).all()
    )


def get_staged_file_ids_for_cc_pair_excluding_attempt(
    cc_pair_id: int,
    tenant_id: str,
    excluding_attempt_id: int,
    db_session: Session,
) -> list[str]:
    """Return `INDEXING_STAGING` file_ids for this cc_pair eligible for
    the start-of-run orphan sweep — anything tagged with a different
    `index_attempt_id` whose owning attempt is NOT still running.

    Files belonging to a non-terminal attempt (e.g. a concurrent
    targeted reindex on the same cc_pair) are kept; their binaries are
    still being consumed and must not be wiped. Files whose owning
    attempt no longer exists in the DB at all (deleted by retention,
    test fixtures with synthetic IDs, etc.) are still reaped, since
    nothing is going to consume them.
    """
    non_terminal_statuses = [s for s in IndexingStatus if not s.is_terminal()]
    non_terminal_cc_pair_attempt_ids_subq = select(cast(IndexAttempt.id, String)).where(
        IndexAttempt.connector_credential_pair_id == cc_pair_id,
        IndexAttempt.status.in_(non_terminal_statuses),
    )
    return list(
        db_session.scalars(
            select(FileRecord.file_id)
            .where(FileRecord.file_origin == FileOrigin.INDEXING_STAGING)
            .where(
                FileRecord.file_metadata["cc_pair_id"].as_string() == str(cc_pair_id)
            )
            .where(FileRecord.file_metadata["tenant_id"].as_string() == tenant_id)
            .where(
                FileRecord.file_metadata["index_attempt_id"].as_string()
                != str(excluding_attempt_id)
            )
            .where(
                FileRecord.file_metadata["index_attempt_id"]
                .as_string()
                .notin_(non_terminal_cc_pair_attempt_ids_subq)
            )
        ).all()
    )


def upsert_filerecord(
    file_id: str,
    display_name: str,
    file_origin: FileOrigin,
    file_type: str,
    bucket_name: str,
    object_key: str,
    db_session: Session,
    file_metadata: dict | None = None,
    file_size: int | None = None,
) -> FileRecord:
    """Atomic upsert using INSERT ... ON CONFLICT DO UPDATE to avoid
    race conditions when concurrent calls target the same file_id.

    Every backend writes its record here, so this is also where a blob saved
    during a content-free chat turn gets stamped with its session. The stamp
    is the only handle cleanup has, and it lands with the record itself.
    """
    session_id = CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR.get()
    if session_id is not None:
        file_metadata = {
            **(file_metadata or {}),
            INCOGNITO_SESSION_METADATA_KEY: session_id,
        }
    stmt = insert(FileRecord).values(
        file_id=file_id,
        display_name=display_name,
        file_origin=file_origin,
        file_type=file_type,
        file_metadata=file_metadata,
        bucket_name=bucket_name,
        object_key=object_key,
        file_size=file_size,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[FileRecord.file_id],
        set_={
            "display_name": stmt.excluded.display_name,
            "file_origin": stmt.excluded.file_origin,
            "file_type": stmt.excluded.file_type,
            "file_metadata": stmt.excluded.file_metadata,
            "bucket_name": stmt.excluded.bucket_name,
            "object_key": stmt.excluded.object_key,
            "file_size": stmt.excluded.file_size,
        },
    )
    db_session.execute(stmt)

    return db_session.get(FileRecord, file_id)  # ty: ignore[invalid-return-type]


def get_incognito_file_ids(session_id: str, db_session: Session) -> list[str]:
    """Ids of blobs a content-free session produced and has not deleted yet."""
    return list(
        db_session.scalars(
            select(FileRecord.file_id).where(
                FileRecord.file_metadata[INCOGNITO_SESSION_METADATA_KEY].astext
                == session_id
            )
        )
    )


def get_session_ids_with_incognito_files(
    db_session: Session, limit: int | None = None
) -> list[str]:
    """Sessions still holding blobs. Empty in steady state, since teardown
    deletes the records, so this only sees what a store failure left.

    Sampled at random when limited: every row here is a retry, so a set that
    keeps failing must not occupy the batch and hide the sessions behind it.
    """
    stmt = (
        select(FileRecord.file_metadata[INCOGNITO_SESSION_METADATA_KEY].astext)
        .distinct()
        .where(FileRecord.file_metadata.has_key(INCOGNITO_SESSION_METADATA_KEY))
    )
    if limit is not None:
        # Postgres rejects ORDER BY random() on a DISTINCT select, so the
        # sample draws from a subquery.
        stmt = select(stmt.subquery()).order_by(func.random()).limit(limit)
    return list(db_session.scalars(stmt))


def _staged_for_cc_pair(
    cc_pair_id: int, file_ids: list[str], staged_within: timedelta
) -> ColumnElement[bool]:
    return and_(
        FileRecord.file_id.in_(file_ids),
        FileRecord.file_metadata[STAGED_FOR_CC_PAIR_METADATA_KEY].astext
        == str(cc_pair_id),
        FileRecord.created_at > func.now() - staged_within,
    )


def get_file_ids_staged_for_cc_pair(
    db_session: Session,
    cc_pair_id: int,
    file_ids: list[str],
    staged_within: timedelta,
) -> set[str]:
    """The given files that were staged for this pair's edit less than
    ``staged_within`` ago."""
    if not file_ids:
        return set()
    return set(
        db_session.scalars(
            select(FileRecord.file_id).where(
                _staged_for_cc_pair(cc_pair_id, file_ids, staged_within)
            )
        )
    )


def unmark_staged_files__no_commit(
    db_session: Session,
    cc_pair_id: int,
    file_ids: list[str],
    staged_within: timedelta,
) -> set[str]:
    """Removes the staged mark from the given files staged for this pair less
    than ``staged_within`` ago. Returns the files it unmarked."""
    if not file_ids:
        return set()
    return set(
        db_session.scalars(
            update(FileRecord)
            .where(_staged_for_cc_pair(cc_pair_id, file_ids, staged_within))
            .values(
                file_metadata=FileRecord.file_metadata.op("-")(
                    STAGED_FOR_CC_PAIR_METADATA_KEY
                )
            )
            .returning(FileRecord.file_id)
        )
    )


def get_expired_staged_file_ids(
    db_session: Session, staged_before: timedelta, limit: int
) -> list[str]:
    """Up to ``limit`` files still marked as staged that were saved more than
    ``staged_before`` ago, oldest first."""
    return list(
        db_session.scalars(
            select(FileRecord.file_id)
            .where(FileRecord.file_metadata.has_key(STAGED_FOR_CC_PAIR_METADATA_KEY))
            .where(FileRecord.created_at < func.now() - staged_before)
            .order_by(FileRecord.created_at)
            .limit(limit)
        )
    )
