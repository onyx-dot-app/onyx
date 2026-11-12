"""The tool selection saved on a chat, checked against Postgres."""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.context.search.models import BaseFilters
from onyx.db.chat import create_chat_session, set_chat_session_tool_selection__no_commit
from onyx.db.enums import IncognitoRecordMode
from onyx.db.models import ChatSession, User
from onyx.tools.models import ChatToolSelection
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user


@pytest.fixture
def owner(db_session: Session) -> Generator[User, None, None]:
    # create_chat_session commits, so the rows are deleted rather than rolled back.
    user = create_test_user(db_session, "chat-tool-selection")
    yield user

    db_session.rollback()
    db_session.query(ChatSession).filter(ChatSession.user_id == user.id).delete()
    delete_test_user(db_session, user)
    db_session.commit()


def _saved(
    db_session: Session, owner: User, mode: IncognitoRecordMode | None
) -> ChatToolSelection | None:
    chat_session = create_chat_session(
        db_session, "Chat", owner.id, None, incognito_record_mode=mode
    )
    set_chat_session_tool_selection__no_commit(
        db_session,
        chat_session.id,
        ChatToolSelection(
            allowed_tool_ids=[3],
            preferred_tool_id=3,
            internal_search_filters=BaseFilters(tags=[]),
        ),
    )
    db_session.commit()
    db_session.refresh(chat_session)
    return chat_session.tool_selection


@pytest.mark.parametrize(
    "mode", [None, IncognitoRecordMode.FULL_HISTORY], ids=["normal", "full_history"]
)
def test_a_chat_that_keeps_content_saves_its_selection(
    db_session: Session, owner: User, mode: IncognitoRecordMode | None
) -> None:
    saved = _saved(db_session, owner, mode)
    assert saved is not None
    assert saved.allowed_tool_ids == [3]
    assert saved.internal_search_filters == BaseFilters(tags=[])


def test_a_content_free_incognito_chat_saves_no_selection(
    db_session: Session, owner: User
) -> None:
    assert _saved(db_session, owner, IncognitoRecordMode.USAGE_ONLY) is None


def test_a_partial_selection_keeps_the_saved_fields_it_does_not_set(
    db_session: Session, owner: User
) -> None:
    chat_session = create_chat_session(db_session, "Chat", owner.id, None)
    set_chat_session_tool_selection__no_commit(
        db_session,
        chat_session.id,
        ChatToolSelection(allowed_tool_ids=[3], preferred_tool_id=3),
    )
    db_session.commit()

    filters = BaseFilters(document_set=["Handbook"])
    set_chat_session_tool_selection__no_commit(
        db_session,
        chat_session.id,
        ChatToolSelection(internal_search_filters=filters),
    )
    db_session.commit()
    db_session.refresh(chat_session)
    assert chat_session.tool_selection == ChatToolSelection(
        allowed_tool_ids=[3], preferred_tool_id=3, internal_search_filters=filters
    )
