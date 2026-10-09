"""Membership query and file cleanup for incognito chats.

A file's privacy is decided when it is uploaded. The client mints the session
id when incognito is switched on and sends it with every upload, so a file
names its session before that session exists and the server never has to take
the client's word for whether the upload is private.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session

from onyx.db.enums import IncognitoRecordMode, UserFileStatus
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


def mark_user_files_deleting(db_session: Session, file_ids: Sequence[UUID]) -> None:
    """Move these files to DELETING. Caller commits."""
    if not file_ids:
        return
    db_session.execute(
        update(UserFile)
        .where(UserFile.id.in_(file_ids))
        .values(status=UserFileStatus.DELETING)
    )


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
    mark_user_files_deleting(db_session, file_ids)
    return file_ids


def _stale_upload_conditions() -> list[Any]:
    """Uploads old enough for a sweep to consider, whatever claims them."""
    cutoff = datetime.now(timezone.utc) - INCOGNITO_FILE_ORPHAN_AGE
    return [
        # Matches ix_user_file_incognito_sweep's partial predicate.
        UserFile.incognito.is_(True),
        UserFile.status != UserFileStatus.DELETING,
        UserFile.last_accessed_at < cutoff,
    ]


def stale_unadopted_upload_ids(db_session: Session) -> list[UUID]:
    """Stale uploads no session ever claimed.

    Separate from the session-keyed pass so they can never queue behind a
    session that is still live: every row here is deletable on sight.
    """
    return list(
        db_session.scalars(
            select(UserFile.id)
            .where(*_stale_upload_conditions(), UserFile.incognito_session_id.is_(None))
            .order_by(UserFile.last_accessed_at)
            .limit(INCOGNITO_STALE_SWEEP_LIMIT)
        ).all()
    )


def stale_incognito_session_ids(db_session: Session) -> list[UUID]:
    """Sessions holding stale uploads whose liveness decides their fate.

    Bounded by distinct sessions rather than files, so one session holding
    thousands of uploads costs a single slot. Sessions that persist content are
    excluded in SQL: a session row that is absent means the client-minted id
    never became a session, which is not the same as a NULL mode on a row that
    exists, since that is an ordinary chat.
    """
    session_persists_content = ChatSession.id.is_not(None) & (
        ChatSession.incognito_record_mode.is_(None)
        | (ChatSession.incognito_record_mode == IncognitoRecordMode.FULL_HISTORY)
    )
    rows = db_session.scalars(
        select(UserFile.incognito_session_id)
        .outerjoin(ChatSession, ChatSession.id == UserFile.incognito_session_id)
        .where(
            *_stale_upload_conditions(),
            UserFile.incognito_session_id.is_not(None),
            ~session_persists_content,
        )
        .group_by(UserFile.incognito_session_id)
        .order_by(func.min(UserFile.last_accessed_at))
        .limit(INCOGNITO_STALE_SWEEP_LIMIT)
    ).all()
    # The is_not(None) filter above already excludes NULLs. This narrows the
    # column's Optional type for the caller.
    return [session_id for session_id in rows if session_id is not None]


def touch_incognito_uploads_for_sessions(
    db_session: Session, chat_session_ids: Sequence[UUID]
) -> None:
    """Restart the orphan clock on these sessions' uploads. Caller commits.

    A session whose context is still live is still using its files, so the
    sweep records that rather than reconsidering the same rows every pass and
    starving the sessions behind them.
    """
    if not chat_session_ids:
        return
    db_session.execute(
        update(UserFile)
        .where(
            UserFile.incognito_session_id.in_(chat_session_ids),
            UserFile.status != UserFileStatus.DELETING,
        )
        .values(last_accessed_at=datetime.now(timezone.utc))
    )


def stale_upload_ids_for_sessions(
    db_session: Session, chat_session_ids: Sequence[UUID]
) -> list[UUID]:
    """The stale uploads these sessions hold."""
    if not chat_session_ids:
        return []
    return list(
        db_session.scalars(
            select(UserFile.id).where(
                *_stale_upload_conditions(),
                UserFile.incognito_session_id.in_(chat_session_ids),
            )
        ).all()
    )
