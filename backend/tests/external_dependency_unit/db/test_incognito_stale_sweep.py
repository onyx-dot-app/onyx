"""Guards which uploads the sweep's query returns, and how it reads the mode of
the session that claims each one.

An absent session row and an ordinary chat both arrive as a NULL mode through
the outer join while meaning opposite things. Exercises the real SQL against
Postgres, since the distinction lives entirely in the join.
"""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import IncognitoRecordMode, UserFileStatus
from onyx.db.incognito import (
    INCOGNITO_FILE_ORPHAN_AGE,
    stale_incognito_session_ids,
    stale_unadopted_upload_ids,
)
from onyx.db.models import ChatSession, User, UserFile
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

PAST_THE_WINDOW = INCOGNITO_FILE_ORPHAN_AGE + timedelta(hours=1)


@pytest.fixture
def owner(db_session: Session) -> Generator[User, None, None]:
    """A user whose rows are deleted afterwards rather than rolled back, since
    the helpers below commit and a rollback cannot reach committed rows."""
    user = create_test_user(db_session, "incognito-sweep")
    yield user

    db_session.rollback()
    db_session.query(UserFile).filter(UserFile.user_id == user.id).delete()
    db_session.query(ChatSession).filter(ChatSession.user_id == user.id).delete()
    delete_test_user(db_session, user)
    db_session.commit()


def _make_chat_session(
    db_session: Session, user_id: UUID, mode: IncognitoRecordMode | None
) -> UUID:
    chat_session = ChatSession(
        id=uuid4(), user_id=user_id, description="", incognito_record_mode=mode
    )
    db_session.add(chat_session)
    db_session.commit()
    return chat_session.id


def _make_upload(
    db_session: Session,
    user_id: UUID,
    session_id: UUID | None,
    age: timedelta = PAST_THE_WINDOW,
) -> UUID:
    user_file = UserFile(
        id=uuid4(),
        user_id=user_id,
        file_id=f"file-{uuid4()}",
        name="attachment.txt",
        file_type="text/plain",
        status=UserFileStatus.COMPLETED,
        incognito=True,
        incognito_session_id=session_id,
        last_accessed_at=datetime.now(timezone.utc) - age,
    )
    db_session.add(user_file)
    db_session.commit()
    return user_file.id


def _session_is_swept(db_session: Session, session_id: UUID) -> bool:
    """Whether the session-keyed pass considers this session at all."""
    return session_id in stale_incognito_session_ids(db_session)


@pytest.mark.parametrize(
    "mode, returned",
    [
        # No session row at all: the client-minted id never became a session,
        # which the query must not read as the NULL mode of an ordinary chat.
        ("no_session", True),
        (None, False),
        (IncognitoRecordMode.FULL_HISTORY, False),
        (IncognitoRecordMode.USAGE_ONLY, True),
    ],
    ids=["no_session_row", "ordinary_chat", "full_history", "usage_only"],
)
def test_the_session_pass_considers_only_sessions_a_sweep_may_act_on(
    db_session: Session,
    owner: User,
    mode: object,
    returned: bool,
) -> None:
    if mode == "no_session":
        session_id = uuid4()
    else:
        session_id = _make_chat_session(db_session, owner.id, mode)  # ty: ignore[invalid-argument-type]
    _make_upload(db_session, owner.id, session_id)

    assert _session_is_swept(db_session, session_id) is returned


def test_an_unadopted_upload_is_returned_by_its_own_pass(
    db_session: Session, owner: User
) -> None:
    """It has no session to ask about, so it must not depend on the session
    pass having room for it."""
    file_id = _make_upload(db_session, owner.id, None)

    assert file_id in stale_unadopted_upload_ids(db_session)


@pytest.mark.parametrize(
    "age, status",
    [
        (timedelta(minutes=5), UserFileStatus.COMPLETED),
        (PAST_THE_WINDOW, UserFileStatus.DELETING),
    ],
    ids=["inside_the_orphan_window", "already_deleting"],
)
def test_the_query_skips_uploads_it_has_no_business_with(
    db_session: Session, owner: User, age: timedelta, status: UserFileStatus
) -> None:
    file_id = _make_upload(db_session, owner.id, None, age=age)
    if status is UserFileStatus.DELETING:
        db_session.query(UserFile).filter(UserFile.id == file_id).update(
            {"status": status}
        )
        db_session.commit()

    assert file_id not in stale_unadopted_upload_ids(db_session)
