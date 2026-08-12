"""Recording policy for incognito chat turns.

An incognito chat is an ordinary chat carrying a mode. ``IncognitoRecordMode``
is the only policy object: behavior is exposed as derived properties on it, so
the legal states are the only representable ones and no caller can assemble an
illegal combination out of loose booleans.

The contract that enforcement points must honor: an incognito session must pin
its mode on a metadata-only ``chat_session`` row at creation, and downstream
code must read the pinned value, never the live admin setting, so a setting
change cannot alter a session under way. Only FULL_HISTORY may write
conversation content into ``chat_message`` rows. USAGE_ONLY writes
content-free rows and must carry the live conversation outside Postgres
for the length of the session.
"""

from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.enums import IncognitoRecordMode, record_mode_persists_content
from onyx.db.file_record import get_incognito_file_ids
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import FileDescriptor
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_incognito_record_mode

logger = setup_logger()


def current_turn_persists_content() -> bool:
    mode = IncognitoRecordMode.from_context_value(get_current_incognito_record_mode())
    return record_mode_persists_content(mode)


def resolve_incognito_record_mode() -> IncognitoRecordMode:
    """The mode a new incognito session must pin.

    The seam a workspace's record-mode setting must resolve through. Today it
    returns the default unconditionally.
    """
    return IncognitoRecordMode.USAGE_ONLY


def content_free_file_descriptors(
    file_descriptors: list[FileDescriptor],
) -> list[FileDescriptor]:
    """Descriptors safe to persist for a content-free turn. Linkage ids and
    type survive for the file-reader tool and teardown. The content-derived
    filename does not."""
    return [
        FileDescriptor(
            id=fd["id"], type=fd["type"], user_file_id=fd.get("user_file_id")
        )
        for fd in file_descriptors
    ]


def delete_incognito_generated_files(
    chat_session_id: UUID, db_session: Session
) -> bool:
    """Delete the blobs the session's tools saved. True when none remain.

    The file record carries the session stamp, so deleting the blob deletes the
    handle with it. A blob the store refuses keeps both, which is what the
    cleanup sweep retries from."""
    file_store = get_default_file_store()
    outstanding = False
    for file_id in get_incognito_file_ids(str(chat_session_id), db_session):
        try:
            file_store.delete_file(file_id, error_on_missing=False)
        except Exception:
            logger.warning("Failed to delete incognito generated file %s", file_id)
            outstanding = True
    return not outstanding
