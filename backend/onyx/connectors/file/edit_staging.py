"""Files uploaded while a file connector is edited. They are saved as connector
files with a staged mark, and only an applied plan indexes them.

A plan can name a staged file for a day after the upload. Apply claims the
plan's new files (it removes their mark) while the plan lives, and the
cleanup task deletes marked files after that.
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from onyx.connectors.edit_plan.constants import EDIT_PLAN_TTL_SECONDS
from onyx.connectors.file.config import LocalFileConnectorConfig
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.file_record import (
    get_expired_staged_file_ids,
    get_file_ids_staged_for_cc_pair,
    unmark_staged_files__no_commit,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.staging import delete_files_best_effort

_STAGED_FILE_PLANNABLE = timedelta(seconds=EDIT_PLAN_TTL_SECONDS)
# A plan made at the end of the plannable window can be applied until it
# expires.
_STAGED_FILE_CLAIMABLE = _STAGED_FILE_PLANNABLE + timedelta(
    seconds=EDIT_PLAN_TTL_SECONDS
)
# Longer than any claim, so cleanup never deletes a file that apply claims.
_STAGED_FILE_RETENTION = _STAGED_FILE_CLAIMABLE + timedelta(hours=1)
# Bounds one cleanup pass; a backlog clears over later passes.
_CLEANUP_BATCH_SIZE = 500


def added_file_ids(
    old: LocalFileConnectorConfig, new: LocalFileConnectorConfig
) -> list[str]:
    """The stored files the new config reads and the old one does not: added
    files and a new metadata file."""
    old_ids = {*old.file_locations, old.zip_metadata_file_id}
    new_ids = [*new.file_locations, new.zip_metadata_file_id]
    return [
        file_id
        for file_id in dict.fromkeys(new_ids)
        if file_id is not None and file_id not in old_ids
    ]


def ensure_files_staged_for_edit(
    db_session: Session, cc_pair_id: int, file_ids: list[str]
) -> None:
    """Raises ``OnyxError`` unless every file was staged for this pair's edit
    within the plannable window."""
    staged = get_file_ids_staged_for_cc_pair(
        db_session, cc_pair_id, file_ids, _STAGED_FILE_PLANNABLE
    )
    if missing := [file_id for file_id in file_ids if file_id not in staged]:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "These files were not uploaded for this connector edit, or the "
            f"upload expired. Upload them again: {', '.join(missing)}.",
        )


def claim_staged_files__no_commit(
    db_session: Session,
    cc_pair_id: int,
    old: LocalFileConnectorConfig,
    new: LocalFileConnectorConfig,
) -> None:
    """Keeps the files that the edit from ``old`` to ``new`` adds: cleanup no
    longer deletes them. Raises ``OnyxError`` (the caller rolls back) when a
    file is not staged for this pair or expired."""
    file_ids = added_file_ids(old, new)
    claimed = unmark_staged_files__no_commit(
        db_session, cc_pair_id, file_ids, _STAGED_FILE_CLAIMABLE
    )
    if missing := [file_id for file_id in file_ids if file_id not in claimed]:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "The uploaded files of this edit expired. Upload them again and "
            f"compute a new plan: {', '.join(missing)}.",
        )


def delete_expired_staged_files() -> int:
    """Deletes one batch of staged files that no apply can claim any more.
    Returns how many it deleted."""
    with get_session_with_current_tenant() as db_session:
        file_ids = get_expired_staged_file_ids(
            db_session, _STAGED_FILE_RETENTION, _CLEANUP_BATCH_SIZE
        )
    return delete_files_best_effort(file_ids, context="staged connector file cleanup")
