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

from onyx.chat.incognito_context import (
    incognito_context_available,
    incognito_session_ended,
)
from onyx.db.enums import IncognitoRecordMode, record_mode_persists_content
from onyx.db.file_record import get_incognito_file_ids
from onyx.db.incognito import (
    is_content_persisting_session,
    mark_incognito_user_files_deleting,
    mark_unadopted_incognito_files_deleting,
    stale_incognito_session_ids,
    user_in_incognito_enabled_group,
)
from onyx.db.models import User
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import FileDescriptor
from onyx.server.security.models import IncognitoAvailability
from onyx.server.security.store import get_security_settings, load_effective_uncached
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_incognito_record_mode

logger = setup_logger()


def current_turn_persists_content() -> bool:
    mode = IncognitoRecordMode.from_context_value(get_current_incognito_record_mode())
    return record_mode_persists_content(mode)


def incognito_allowed_for_user(
    user: User, db_session: Session, *, cached: bool = True
) -> bool:
    """Whether this user may start an incognito chat.

    Availability composes the deployment capability (the ephemeral store must
    exist) with the admin's security setting, which defaults to off. Anonymous
    users never qualify: they share an identity, have no memberships, and
    cannot authenticate against the teardown endpoint.

    ``cached`` must be False wherever this decides an action rather than an
    affordance. Cache invalidation is process-local, so a second api_server can
    authorize against a revoked setting for the cache TTL.
    """
    if user.is_anonymous:
        return False
    if not incognito_context_available():
        return False
    settings = get_security_settings() if cached else load_effective_uncached()
    availability = settings.incognito_availability
    if availability is IncognitoAvailability.EVERYONE:
        return True
    if availability is IncognitoAvailability.GROUPS:
        return user_in_incognito_enabled_group(db_session, user.id)
    return False


def resolve_incognito_record_mode() -> IncognitoRecordMode:
    """The mode a new incognito session must pin: the workspace's admin
    record-mode setting, usage_only by default.

    Reads past the settings cache. Cache invalidation is process-local, so a
    second api_server can hold the pre-save mode for the cache TTL, and this
    read decides for the whole life of the session: pinning a stale
    full_history would persist content the admin has already disallowed.
    """
    return load_effective_uncached().incognito_record_mode


def sweep_stale_incognito_user_files(db_session: Session) -> int:
    """Queue uploads of dead incognito sessions for deletion. Caller commits.

    Covers both shapes: uploads no session ever adopted, and uploads whose
    session is gone. A session whose live context is still present is skipped
    however old its files are, so a chat left open past the orphan window keeps
    its attachments. Shared by the Celery beat task and the lite deployment
    poller, which have no scheduler in common.
    """
    marked = mark_unadopted_incognito_files_deleting(db_session)
    for session_id in stale_incognito_session_ids(db_session):
        # Full-history sessions never create a Redis context, so liveness would
        # read them as ended and delete a live chat's attachments.
        if is_content_persisting_session(db_session, session_id):
            continue
        if not incognito_session_ended(session_id):
            continue
        marked += len(mark_incognito_user_files_deleting(db_session, session_id))
    return marked


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
