"""The tool selection saved on a chat, checked against Postgres."""

from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.chat.process_message import prepare_chat_turn
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.context.search.models import BaseFilters
from onyx.db.chat import create_chat_session, set_chat_session_tool_selection__no_commit
from onyx.db.enums import IncognitoRecordMode
from onyx.db.models import ChatSession, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.interfaces import LLMConfig
from onyx.llm.models import AssistantMessage, TextContent
from onyx.server.query_and_chat.chat_backend import (
    get_chat_session,
    update_chat_tool_selection,
)
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.tools.models import ChatToolSelection
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.unit.onyx.agents.fakes import FakeModelClient

SAVED = ChatToolSelection(
    allowed_tool_ids=[3],
    preferred_tool_id=3,
    internal_search_filters=BaseFilters(tags=[]),
)


class ResearchCapableModel(FakeModelClient):
    """Large enough for Deep Research; never asked for a reply here."""

    def __init__(self) -> None:
        super().__init__(
            lambda _request, _signal: AssistantMessage(content=[TextContent(text="")])
        )

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="openai",
            model_name="test-model",
            max_input_tokens=1_000_000,
            temperature=0,
        )


@pytest.fixture
def owner(make_test_user: MakeTestUser) -> User:
    return make_test_user("chat-tool-selection")


def _chat(
    db_session: Session, owner: User, mode: IncognitoRecordMode | None = None
) -> ChatSession:
    return create_chat_session(
        db_session, "Chat", owner.id, DEFAULT_PERSONA_ID, incognito_record_mode=mode
    )


def _stored(db_session: Session, chat_session: ChatSession) -> ChatToolSelection | None:
    db_session.expire_all()
    stored = db_session.get(ChatSession, chat_session.id)
    assert stored is not None
    return stored.tool_selection


@pytest.mark.parametrize(
    "mode", [None, IncognitoRecordMode.FULL_HISTORY], ids=["normal", "full_history"]
)
def test_a_chat_that_keeps_content_saves_its_selection(
    db_session: Session, owner: User, mode: IncognitoRecordMode | None
) -> None:
    chat_session = _chat(db_session, owner, mode)
    assert update_chat_tool_selection(chat_session.id, SAVED, owner, db_session) == (
        SAVED
    )
    assert _stored(db_session, chat_session) == SAVED


def test_a_content_free_incognito_chat_saves_no_selection(
    db_session: Session, owner: User
) -> None:
    chat_session = _chat(db_session, owner, IncognitoRecordMode.USAGE_ONLY)
    assert update_chat_tool_selection(chat_session.id, SAVED, owner, db_session) is (
        None
    )
    assert _stored(db_session, chat_session) is None


def test_a_partial_selection_keeps_the_saved_fields_it_does_not_set(
    db_session: Session, owner: User
) -> None:
    chat_session = _chat(db_session, owner)
    update_chat_tool_selection(
        chat_session.id,
        ChatToolSelection(allowed_tool_ids=[3], preferred_tool_id=3),
        owner,
        db_session,
    )
    filters = BaseFilters(source_type=None, tags=[])
    stored = update_chat_tool_selection(
        chat_session.id,
        ChatToolSelection(internal_search_filters=filters),
        owner,
        db_session,
    )
    expected = ChatToolSelection(
        allowed_tool_ids=[3], preferred_tool_id=3, internal_search_filters=filters
    )
    assert stored == expected
    assert _stored(db_session, chat_session) == expected


def test_an_unchanged_selection_writes_nothing(
    db_session: Session, owner: User
) -> None:
    chat_session = _chat(db_session, owner)
    update_chat_tool_selection(chat_session.id, SAVED, owner, db_session)
    with patch.object(db_session, "refresh", wraps=db_session.refresh) as lock:
        assert (
            set_chat_session_tool_selection__no_commit(
                db_session, chat_session.id, SAVED, owner
            )
            == SAVED
        )
    lock.assert_not_called()
    assert not db_session.dirty


def test_filters_naming_an_inaccessible_document_set_are_rejected(
    db_session: Session, owner: User
) -> None:
    chat_session = _chat(db_session, owner)
    with pytest.raises(OnyxError) as raised:
        update_chat_tool_selection(
            chat_session.id,
            ChatToolSelection(
                internal_search_filters=BaseFilters(
                    document_set=["no-such-document-set"]
                )
            ),
            owner,
            db_session,
        )
    assert raised.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    db_session.rollback()
    assert _stored(db_session, chat_session) is None


def test_only_the_owner_of_a_live_chat_saves_a_selection(
    db_session: Session, make_test_user: MakeTestUser, owner: User
) -> None:
    chat_session = _chat(db_session, owner)
    other = make_test_user("chat-tool-selection-other")
    with pytest.raises(OnyxError) as raised:
        update_chat_tool_selection(chat_session.id, SAVED, other, db_session)
    assert raised.value.error_code is OnyxErrorCode.SESSION_NOT_FOUND

    anonymous = User(id=None, email="anonymous@example.com")
    with pytest.raises(OnyxError) as raised:
        update_chat_tool_selection(chat_session.id, SAVED, anonymous, db_session)
    assert raised.value.error_code is OnyxErrorCode.UNAUTHORIZED

    chat_session.deleted = True
    db_session.commit()
    with pytest.raises(OnyxError) as raised:
        update_chat_tool_selection(chat_session.id, SAVED, owner, db_session)
    assert raised.value.error_code is OnyxErrorCode.SESSION_NOT_FOUND
    assert _stored(db_session, chat_session) is None


def test_the_chat_detail_returns_the_saved_selection_to_its_owner(
    db_session: Session, owner: User
) -> None:
    chat_session = _chat(db_session, owner)
    update_chat_tool_selection(chat_session.id, SAVED, owner, db_session)
    detail = get_chat_session(chat_session.id, user=owner, db_session=db_session)
    assert detail.tool_selection == SAVED


def test_a_deep_research_send_leaves_the_saved_selection_alone(
    db_session: Session, owner: User
) -> None:
    """A send's one-message choices, such as Deep Research dropping the
    preferred tool, never change the chat's saved selection."""
    chat_session = _chat(db_session, owner)
    update_chat_tool_selection(chat_session.id, SAVED, owner, db_session)
    with (
        patch(
            "onyx.chat.process_message.get_llm_for_persona",
            return_value=ResearchCapableModel(),
        ),
        patch("onyx.chat.process_message.check_llm_cost_limit_for_provider"),
    ):
        setup = prepare_chat_turn(
            SendMessageRequest(
                message="Research the market",
                chat_session_id=chat_session.id,
                deep_research=True,
                preferred_tool_id=None,
            ),
            owner,
            llm_overrides=None,
        )
    setup.admission.release()
    assert _stored(db_session, chat_session) == SAVED
