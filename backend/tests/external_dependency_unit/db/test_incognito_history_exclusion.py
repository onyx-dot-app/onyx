"""Guards that an incognito session stays out of every surface its owner sees.

Covers the three that list a user's own sessions: history, search, and the
chat list a project carries. Exercises the real WHERE clauses against Postgres,
since a mocked session would happily return rows the SQL would have filtered.
"""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from ee.onyx.db.query_history import (
    fetch_chat_sessions_eagerly_by_time,
    fetch_persisting_chat_session_by_id,
    get_page_of_chat_sessions,
)
from onyx.configs.constants import MessageType
from onyx.db.chat import (
    create_chat_session,
    create_new_chat_message,
    get_chat_sessions_by_user,
    get_or_create_root_message,
)
from onyx.db.chat_search import search_chat_sessions
from onyx.db.enums import IncognitoRecordMode
from onyx.db.models import ChatSession, User, UserProject
from onyx.server.features.projects.models import UserProjectSnapshot
from tests.external_dependency_unit.conftest import create_test_user


@pytest.fixture
def owner(db_session: Session) -> Generator[User, None, None]:
    """A user whose rows are deleted afterwards rather than rolled back.

    ``create_chat_session`` commits, so a rollback cannot reach these rows, and
    the filter under test hides them from the UI that would otherwise clean them
    up. Left alone they accumulate as sessions nobody can see or remove.
    """
    user = create_test_user(db_session, "incognito-history")
    yield user

    db_session.rollback()
    # Sessions before projects: chat_session.project_id references user_project.
    db_session.query(ChatSession).filter(ChatSession.user_id == user.id).delete()
    db_session.query(UserProject).filter(UserProject.user_id == user.id).delete()
    db_session.delete(user)
    db_session.commit()


def _make_session(
    db_session: Session,
    user_id: UUID,
    description: str,
    mode: IncognitoRecordMode | None,
    project_id: int | None = None,
) -> ChatSession:
    chat_session = create_chat_session(
        db_session=db_session,
        description=description,
        user_id=user_id,
        persona_id=None,
        project_id=project_id,
    )
    chat_session.incognito_record_mode = mode
    # Commit rather than flush: the next create_chat_session would otherwise be
    # what commits this assignment, leaving the last one written only in memory.
    db_session.commit()
    return chat_session


def _sessions_by_user(
    db_session: Session,
    user_id: UUID,
    exclude_incognito: bool = False,
    exclude_content_free: bool = False,
) -> set[UUID]:
    return {
        session.id
        for session in get_chat_sessions_by_user(
            user_id=user_id,
            deleted=None,
            db_session=db_session,
            include_failed_chats=True,
            exclude_incognito=exclude_incognito,
            exclude_content_free=exclude_content_free,
        )
    }


def _history_ids(db_session: Session, user_id: UUID) -> set[UUID]:
    """The owner's own history, which is the call site that opts out."""
    return _sessions_by_user(db_session, user_id, exclude_incognito=True)


def test_history_excludes_incognito_by_default(
    db_session: Session, owner: User
) -> None:
    ordinary = _make_session(db_session, owner.id, "ordinary chat", None)
    incognito = _make_session(
        db_session, owner.id, "incognito chat", IncognitoRecordMode.FULL_HISTORY
    )

    returned_ids = _history_ids(db_session, owner.id)
    assert ordinary.id in returned_ids
    assert incognito.id not in returned_ids


def test_workspace_surface_keeps_full_history_and_drops_content_free(
    db_session: Session, owner: User
) -> None:
    """The exclusion the query-history endpoint uses, which is the weaker one:
    a full-history session is recorded for the workspace and only its owner is
    kept from seeing it."""
    full_history = _make_session(
        db_session, owner.id, "full history chat", IncognitoRecordMode.FULL_HISTORY
    )
    usage_only = _make_session(
        db_session, owner.id, "usage only chat", IncognitoRecordMode.USAGE_ONLY
    )

    returned_ids = _sessions_by_user(db_session, owner.id, exclude_content_free=True)
    assert full_history.id in returned_ids
    assert usage_only.id not in returned_ids


def test_admin_query_history_page_hides_content_free_sessions(
    db_session: Session, owner: User
) -> None:
    """Content-free sessions must not appear as blank rows in the table."""
    ordinary = _make_session(db_session, owner.id, "ordinary chat", None)
    full_history = _make_session(
        db_session, owner.id, "full history chat", IncognitoRecordMode.FULL_HISTORY
    )
    usage_only = _make_session(
        db_session, owner.id, "usage only chat", IncognitoRecordMode.USAGE_ONLY
    )

    page_ids = {
        session.id
        for session in get_page_of_chat_sessions(
            start_time=None,
            end_time=None,
            db_session=db_session,
            page_num=0,
            page_size=1000,
        )
    }
    assert ordinary.id in page_ids
    assert full_history.id in page_ids
    assert usage_only.id not in page_ids


def test_query_history_export_hides_content_free_sessions(
    db_session: Session, owner: User
) -> None:
    ordinary = _make_session(db_session, owner.id, "ordinary chat", None)
    usage_only = _make_session(
        db_session, owner.id, "usage only chat", IncognitoRecordMode.USAGE_ONLY
    )

    window = timedelta(minutes=5)
    now = datetime.now(timezone.utc)
    export_ids = {
        session.id
        for session in fetch_chat_sessions_eagerly_by_time(
            start=now - window,
            end=now + window,
            db_session=db_session,
            limit=None,
        )
    }
    assert ordinary.id in export_ids
    assert usage_only.id not in export_ids


def test_query_history_detail_hides_content_free_sessions(
    db_session: Session, owner: User
) -> None:
    """Knowing the id must not be a way around the list filter: the detail
    route is the one surface that takes an id straight from the caller."""
    ordinary = _make_session(db_session, owner.id, "ordinary chat", None)
    full_history = _make_session(
        db_session, owner.id, "full history chat", IncognitoRecordMode.FULL_HISTORY
    )
    usage_only = _make_session(
        db_session, owner.id, "usage only chat", IncognitoRecordMode.USAGE_ONLY
    )

    for visible in (ordinary, full_history):
        assert fetch_persisting_chat_session_by_id(visible.id, db_session).id == (
            visible.id
        )

    with pytest.raises(ValueError):
        fetch_persisting_chat_session_by_id(usage_only.id, db_session)


def test_every_mode_is_excluded_from_history(db_session: Session, owner: User) -> None:
    """Every mode must stay out of the owner's history.

    Iterates the enum so a newly added mode is covered without editing this
    test.
    """
    sessions = {
        mode: _make_session(db_session, owner.id, f"chat {mode.value}", mode)
        for mode in IncognitoRecordMode
    }

    returned_ids = _history_ids(db_session, owner.id)
    for mode, chat_session in sessions.items():
        assert chat_session.id not in returned_ids, f"{mode.value} leaked"


def test_search_excludes_incognito_without_a_query(
    db_session: Session, owner: User
) -> None:
    ordinary = _make_session(db_session, owner.id, "quarterly revenue notes", None)
    incognito = _make_session(
        db_session,
        owner.id,
        "quarterly revenue secrets",
        IncognitoRecordMode.FULL_HISTORY,
    )

    sessions, _ = search_chat_sessions(user_id=owner.id, db_session=db_session)
    returned_ids = {session.id for session in sessions}
    assert ordinary.id in returned_ids
    assert incognito.id not in returned_ids


def test_search_excludes_incognito_matching_the_query(
    db_session: Session, owner: User
) -> None:
    """The description arm of the union must not surface an incognito session."""
    ordinary = _make_session(db_session, owner.id, "penguin migration notes", None)
    incognito = _make_session(
        db_session,
        owner.id,
        "penguin migration secrets",
        IncognitoRecordMode.FULL_HISTORY,
    )

    sessions, _ = search_chat_sessions(
        user_id=owner.id, db_session=db_session, query="penguin"
    )
    returned_ids = {session.id for session in sessions}
    assert ordinary.id in returned_ids
    assert incognito.id not in returned_ids


def test_project_does_not_list_its_incognito_sessions(
    db_session: Session, owner: User
) -> None:
    """A project lists sessions by title, which is the thing incognito hides."""
    project = UserProject(name="incognito-project", user_id=owner.id)
    db_session.add(project)
    db_session.commit()

    ordinary = _make_session(
        db_session, owner.id, "ordinary chat", None, project_id=project.id
    )
    incognito = _make_session(
        db_session,
        owner.id,
        "incognito chat",
        IncognitoRecordMode.FULL_HISTORY,
        project_id=project.id,
    )

    db_session.expire(project)
    listed = UserProjectSnapshot.from_model(project).chat_sessions
    listed_ids = {session.id for session in listed}
    assert ordinary.id in listed_ids
    assert incognito.id not in listed_ids
    assert all(session.name != "incognito chat" for session in listed)


def test_search_excludes_incognito_matching_only_in_a_message(
    db_session: Session, owner: User
) -> None:
    """The message-body arm of the union is filtered too.

    Both arms carry base_conditions, so a hit on message text must not surface
    a session whose description never matched.
    """
    incognito = _make_session(
        db_session, owner.id, "untitled", IncognitoRecordMode.FULL_HISTORY
    )
    ordinary = _make_session(db_session, owner.id, "untitled", None)

    for chat_session in (incognito, ordinary):
        create_new_chat_message(
            chat_session_id=chat_session.id,
            parent_message=get_or_create_root_message(
                chat_session_id=chat_session.id, db_session=db_session
            ),
            message="the aardvark budget is confidential",
            token_count=7,
            message_type=MessageType.USER,
            db_session=db_session,
        )
    db_session.commit()

    sessions, _ = search_chat_sessions(
        user_id=owner.id, db_session=db_session, query="aardvark"
    )
    returned_ids = {session.id for session in sessions}
    # The ordinary control proves the query actually matches message bodies,
    # so the incognito assertion is not passing for want of any hit at all.
    assert ordinary.id in returned_ids
    assert incognito.id not in returned_ids
