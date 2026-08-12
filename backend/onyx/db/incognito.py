"""Membership query and file cleanup for incognito chats.

A file's privacy is decided when it is uploaded. The client mints the session
id when incognito is switched on and sends it with every upload, so a file
names its session before that session exists and the server never has to take
the client's word for whether the upload is private.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from onyx.db.enums import UserFileStatus, record_mode_persists_content
from onyx.db.models import ChatSession, User__UserGroup, UserFile, UserGroup

# Only reached once a session's live context is gone, so this bounds how long a
# teardown that never arrived (hard tab close, lost beacon) leaves files behind.
INCOGNITO_FILE_ORPHAN_AGE = timedelta(hours=48)
# Bounds one sweep so a backlog cannot flood the delete queue in a single pass.
INCOGNITO_STALE_SWEEP_LIMIT = 500


def user_in_incognito_enabled_group(db_session: Session, user_id: UUID) -> bool:
    """Whether any of the user's groups has its incognito flag set."""
    stmt = select(
        exists().where(
            User__UserGroup.user_id == user_id,
            User__UserGroup.user_group_id == UserGroup.id,
            UserGroup.incognito_enabled.is_(True),
        )
    )
    return bool(db_session.execute(stmt).scalar())


def is_content_persisting_session(db_session: Session, chat_session_id: UUID) -> bool:
    """Whether the session records content, which means it never creates a
    Redis context and so cannot be judged by context liveness."""
    row = db_session.execute(
        select(ChatSession.incognito_record_mode).where(
            ChatSession.id == chat_session_id
        )
    ).one_or_none()
    if row is None:
        # The id was minted client-side and no session ever followed, so there
        # is no live chat to protect and the files are abandoned.
        return False
    return record_mode_persists_content(row[0])


def is_incognito_teardown_target(
    db_session: Session, chat_session_id: UUID, user_id: UUID
) -> bool:
    """Whether this caller may tear down the session named by this id.

    A missing row is a teardown target, not an error: the id is minted
    client-side, so uploads can name a session that no message ever created.
    Ownership then rests on the per-user scope of the file marking.
    """
    row = db_session.execute(
        select(ChatSession.user_id, ChatSession.incognito_record_mode).where(
            ChatSession.id == chat_session_id
        )
    ).one_or_none()
    if row is None:
        return True
    owner_id, record_mode = row
    return owner_id in (user_id, None) and record_mode is not None


def mark_incognito_user_files_deleting(
    db_session: Session, chat_session_id: UUID, user_id: UUID | None = None
) -> list[UUID]:
    """Queue a session's uploads for deletion. Caller commits.

    Keyed on the session rather than a caller-supplied id list, so an upload
    that finishes after the user closes the chat is still found. Scoped to the
    owner where one is known, since the session id originates on a client.
    """
    conditions = [
        UserFile.incognito_session_id == chat_session_id,
        UserFile.status != UserFileStatus.DELETING,
    ]
    if user_id is not None:
        conditions.append(UserFile.user_id == user_id)
    file_ids = list(db_session.scalars(select(UserFile.id).where(*conditions)).all())
    if not file_ids:
        return []
    db_session.execute(
        update(UserFile)
        .where(UserFile.id.in_(file_ids))
        .values(status=UserFileStatus.DELETING)
    )
    return file_ids


def stale_incognito_session_ids(db_session: Session) -> list[UUID]:
    """Sessions whose uploads are past the orphan window."""
    cutoff = datetime.now(timezone.utc) - INCOGNITO_FILE_ORPHAN_AGE
    rows = db_session.scalars(
        select(UserFile.incognito_session_id)
        .where(
            # Matches the partial index predicate so Postgres can use it.
            UserFile.incognito.is_(True),
            UserFile.incognito_session_id.is_not(None),
            UserFile.status != UserFileStatus.DELETING,
            UserFile.last_accessed_at < cutoff,
        )
        .group_by(UserFile.incognito_session_id)
        .limit(INCOGNITO_STALE_SWEEP_LIMIT)
    ).all()
    # The is_not(None) filter above already excludes NULLs. This narrows the
    # column's Optional type for the caller.
    return [session_id for session_id in rows if session_id is not None]


def mark_unadopted_incognito_files_deleting(db_session: Session) -> int:
    """Queue incognito uploads no session ever adopted. Caller commits.

    Left by someone who attached a file in incognito and never sent a message,
    so no session exists to tear them down.
    """
    cutoff = datetime.now(timezone.utc) - INCOGNITO_FILE_ORPHAN_AGE
    file_ids = list(
        db_session.scalars(
            select(UserFile.id)
            .where(
                UserFile.incognito.is_(True),
                UserFile.incognito_session_id.is_(None),
                UserFile.status != UserFileStatus.DELETING,
                UserFile.last_accessed_at < cutoff,
            )
            .limit(INCOGNITO_STALE_SWEEP_LIMIT)
        ).all()
    )
    if not file_ids:
        return 0
    db_session.execute(
        update(UserFile)
        .where(UserFile.id.in_(file_ids))
        .values(status=UserFileStatus.DELETING)
    )
    return len(file_ids)
