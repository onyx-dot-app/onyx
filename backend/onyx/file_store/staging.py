from collections.abc import Callable
from typing import Any
from typing import IO

from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db.file_record import get_staged_file_ids_by_index_attempt_id
from onyx.db.file_record import get_staged_file_ids_for_cc_pair_excluding_attempt
from onyx.db.file_record import update_filerecord_origin
from onyx.file_store.file_store import get_default_file_store
from onyx.utils.logger import setup_logger

logger = setup_logger()


# (content, content_type) -> file_id
RawFileCallback = Callable[[IO[bytes], str], str]


def stage_raw_file(
    content: IO,
    content_type: str,
    *,
    metadata: dict[str, Any],
) -> str:
    """Persist raw bytes to the file store with FileOrigin.INDEXING_STAGING.

    `metadata` is attached to the file_record so that downstream promotion
    (in docprocessing) and orphan reaping (TTL janitor) can locate the file
    by its originating context.
    """
    file_store = get_default_file_store()
    file_id = file_store.save_file(
        content=content,
        display_name=None,
        file_origin=FileOrigin.INDEXING_STAGING,
        file_type=content_type,
        file_metadata=metadata,
    )
    return file_id


def build_raw_file_callback(
    *,
    index_attempt_id: int,
    cc_pair_id: int,
    tenant_id: str,
) -> RawFileCallback:
    """Build a per-attempt callback that connectors can invoke to opt in to
    raw-file persistence. The closure binds the attempt-level context as the
    staging metadata so the connector only needs to pass per-call info
    (bytes, content_type) and gets back a file_id to attach to its Document.
    """
    metadata: dict[str, Any] = {
        "index_attempt_id": index_attempt_id,
        "cc_pair_id": cc_pair_id,
        "tenant_id": tenant_id,
    }

    def _callback(content: IO[bytes], content_type: str) -> str:
        return stage_raw_file(
            content=content,
            content_type=content_type,
            metadata=metadata,
        )

    return _callback


def delete_files_best_effort(
    file_ids: list[str],
    context: str = "document cleanup",
) -> int:
    """Delete a list of files from the file store, logging individual
    failures rather than raising. Returns the count successfully removed.
    """
    if not file_ids:
        return 0
    file_store = get_default_file_store()
    deleted = 0
    for file_id in file_ids:
        try:
            file_store.delete_file(file_id, error_on_missing=False)
            deleted += 1
        except Exception:
            logger.exception(
                "[%s] Failed to delete file_id=%s; will be retried on next sweep.",
                context,
                file_id,
            )
    if deleted:
        logger.info("[%s] reaped %s file(s)", context, deleted)
    return deleted


def promote_staged_file(db_session: Session, file_id: str) -> None:
    """Mark a previously-staged file as `FileOrigin.CONNECTOR`."""
    update_filerecord_origin(
        file_id=file_id,
        from_origin=FileOrigin.INDEXING_STAGING,
        to_origin=FileOrigin.CONNECTOR,
        db_session=db_session,
    )


# ---------------------------------------------------------------------------
# STAGING orphan reaping
# ---------------------------------------------------------------------------
# Two lifecycle seams in the docfetching flow cover every non-catastrophic
# orphan case for STAGING files:
#
#   Boundary                                Helper
#   --------------------------------------  ---------------------------------
#   attempt ends (success or failure)       cleanup_staged_files_for_attempt
#   attempt starts; prior attempt crashed   reap_prior_attempt_staged_files


def cleanup_staged_files_for_attempt(
    index_attempt_id: int,
    db_session: Session,
) -> int:
    """Reap every STAGING file tagged with this attempt's id.

    Runs at attempt end (success or failure) in a `try/finally`. Any file
    still STAGING at this point was never promoted — the Document either
    wasn't produced (filtered, connector skipped it) or the upsert never
    reached `_promote_new_staged_files`. In either case it's an orphan.
    """
    file_ids = get_staged_file_ids_by_index_attempt_id(
        index_attempt_id=index_attempt_id, db_session=db_session
    )
    return delete_files_best_effort(
        file_ids, context=f"attempt-end-cleanup attempt={index_attempt_id}"
    )


def reap_prior_attempt_staged_files(
    current_attempt_id: int,
    cc_pair_id: int,
    tenant_id: str,
    db_session: Session,
) -> int:
    """Reap STAGING files left by earlier attempts on this cc_pair.

    Runs at the start of a new docfetching attempt, before any fetching
    work begins. Anything STAGING tagged with a different attempt_id for
    this same cc_pair is by definition an orphan — the owning attempt
    either crashed hard (its `finally` couldn't run) or finished without
    promoting the file. Scoped to the cc_pair + tenant to stay bounded.
    """
    file_ids = get_staged_file_ids_for_cc_pair_excluding_attempt(
        cc_pair_id=cc_pair_id,
        tenant_id=tenant_id,
        excluding_attempt_id=current_attempt_id,
        db_session=db_session,
    )
    return delete_files_best_effort(
        file_ids,
        context=f"attempt-start-sweep cc_pair={cc_pair_id} "
        f"attempt={current_attempt_id}",
    )
