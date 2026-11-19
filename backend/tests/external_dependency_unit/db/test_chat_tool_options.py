"""The tool options saved on a chat, checked against Postgres."""

from unittest.mock import patch

import pytest
from pydantic import JsonValue
from sqlalchemy.orm import Session

from onyx.chat.process_message import prepare_chat_turn
from onyx.configs.constants import DEFAULT_PERSONA_ID, MessageType
from onyx.context.search.models import BaseFilters, Tag
from onyx.db.chat import (
    MAX_TOOL_OPTIONS_BYTES,
    MAX_TOOL_OPTIONS_ITEMS,
    create_chat_session,
    set_chat_session_tool_options__no_commit,
)
from onyx.db.chat_checkpoint import parked_response_settings
from onyx.db.enums import IncognitoRecordMode
from onyx.db.models import (
    ChatMessage,
    ChatResponseCheckpoint,
    ChatSession,
    User,
)
from onyx.db.tools import get_builtin_tool
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.interfaces import LLMConfig
from onyx.llm.models import AssistantMessage, TextContent
from onyx.server.query_and_chat.chat_backend import (
    get_chat_session,
    update_chat_tool_options,
)
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.tools.models import (
    CapabilityEntry,
    IntegrationEntry,
    ToolOptions,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.unit.onyx.agents.fakes import FakeModelClient

SAVED = ToolOptions(
    allowed=[
        CapabilityEntry(tool_id=3),
        IntegrationEntry(integration_id=7, actions=["hello"]),
    ],
    preferred=CapabilityEntry(tool_id=3),
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
    return make_test_user("chat-tool-options")


def _chat(
    db_session: Session, owner: User, mode: IncognitoRecordMode | None = None
) -> ChatSession:
    return create_chat_session(
        db_session, "Chat", owner.id, DEFAULT_PERSONA_ID, incognito_record_mode=mode
    )


def _stored(db_session: Session, chat_session: ChatSession) -> ToolOptions | None:
    db_session.expire_all()
    stored = db_session.get(ChatSession, chat_session.id)
    assert stored is not None
    return stored.tool_options


def _prepare(owner: User, request: SendMessageRequest) -> None:
    with (
        patch(
            "onyx.chat.process_message.get_llm_for_persona",
            return_value=ResearchCapableModel(),
        ),
        patch("onyx.chat.process_message.check_llm_cost_limit_for_provider"),
    ):
        setup = prepare_chat_turn(request, owner, llm_overrides=None)
    setup.admission.release()


@pytest.mark.parametrize(
    "mode", [None, IncognitoRecordMode.FULL_HISTORY], ids=["normal", "full_history"]
)
def test_a_chat_that_keeps_content_saves_its_options(
    db_session: Session, owner: User, mode: IncognitoRecordMode | None
) -> None:
    chat_session = _chat(db_session, owner, mode)
    assert update_chat_tool_options(chat_session.id, SAVED, owner, db_session) == (
        SAVED
    )
    assert _stored(db_session, chat_session) == SAVED


def test_a_content_free_incognito_chat_saves_no_options(
    db_session: Session, owner: User
) -> None:
    chat_session = _chat(db_session, owner, IncognitoRecordMode.USAGE_ONLY)
    assert update_chat_tool_options(chat_session.id, SAVED, owner, db_session) is (None)
    assert _stored(db_session, chat_session) is None


def test_a_partial_update_keeps_the_saved_fields_it_does_not_set(
    db_session: Session, owner: User
) -> None:
    chat_session = _chat(db_session, owner)
    update_chat_tool_options(
        chat_session.id,
        ToolOptions(
            allowed=[CapabilityEntry(tool_id=3)],
            preferred=CapabilityEntry(tool_id=3),
        ),
        owner,
        db_session,
    )
    filters = BaseFilters(source_type=None, tags=[])
    stored = update_chat_tool_options(
        chat_session.id,
        ToolOptions(internal_search_filters=filters),
        owner,
        db_session,
    )
    expected = ToolOptions(
        allowed=[CapabilityEntry(tool_id=3)],
        preferred=CapabilityEntry(tool_id=3),
        internal_search_filters=filters,
    )
    assert stored == expected
    assert _stored(db_session, chat_session) == expected


def test_unchanged_options_write_nothing(db_session: Session, owner: User) -> None:
    chat_session = _chat(db_session, owner)
    update_chat_tool_options(chat_session.id, SAVED, owner, db_session)
    with patch.object(db_session, "refresh", wraps=db_session.refresh) as lock:
        assert (
            set_chat_session_tool_options__no_commit(
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
        update_chat_tool_options(
            chat_session.id,
            ToolOptions(
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


@pytest.mark.parametrize(
    "options",
    [
        ToolOptions(
            allowed=[
                CapabilityEntry(tool_id=tool_id)
                for tool_id in range(MAX_TOOL_OPTIONS_ITEMS + 1)
            ]
        ),
        ToolOptions(
            allowed=[
                IntegrationEntry(
                    integration_id=7,
                    actions=[str(i) for i in range(MAX_TOOL_OPTIONS_ITEMS + 1)],
                )
            ]
        ),
        ToolOptions(
            internal_search_filters=BaseFilters(
                tags=[Tag(tag_key="team", tag_value="x" * MAX_TOOL_OPTIONS_BYTES)]
            )
        ),
    ],
    ids=["too_many_entries", "too_many_actions", "too_many_bytes"],
)
def test_oversized_options_are_rejected_before_they_are_stored(
    db_session: Session, owner: User, options: ToolOptions
) -> None:
    chat_session = _chat(db_session, owner)
    with pytest.raises(OnyxError) as raised:
        update_chat_tool_options(chat_session.id, options, owner, db_session)
    assert raised.value.error_code is OnyxErrorCode.PAYLOAD_TOO_LARGE
    db_session.rollback()
    assert _stored(db_session, chat_session) is None


def test_a_partial_update_is_rejected_when_the_merged_options_are_too_large(
    db_session: Session, owner: User
) -> None:
    chat_session = _chat(db_session, owner)
    half = "x" * (MAX_TOOL_OPTIONS_BYTES // 2 + 1)
    saved = ToolOptions(allowed=[IntegrationEntry(integration_id=7, actions=[half])])
    update_chat_tool_options(chat_session.id, saved, owner, db_session)
    with pytest.raises(OnyxError) as raised:
        update_chat_tool_options(
            chat_session.id,
            ToolOptions(
                internal_search_filters=BaseFilters(
                    tags=[Tag(tag_key="team", tag_value=half)]
                )
            ),
            owner,
            db_session,
        )
    assert raised.value.error_code is OnyxErrorCode.PAYLOAD_TOO_LARGE
    db_session.rollback()
    assert _stored(db_session, chat_session) == saved


def test_only_the_owner_of_a_live_chat_saves_options(
    db_session: Session, make_test_user: MakeTestUser, owner: User
) -> None:
    chat_session = _chat(db_session, owner)
    other = make_test_user("chat-tool-options-other")
    with pytest.raises(OnyxError) as raised:
        update_chat_tool_options(chat_session.id, SAVED, other, db_session)
    assert raised.value.error_code is OnyxErrorCode.SESSION_NOT_FOUND

    anonymous = User(id=None, email="anonymous@example.com")
    with pytest.raises(OnyxError) as raised:
        update_chat_tool_options(chat_session.id, SAVED, anonymous, db_session)
    assert raised.value.error_code is OnyxErrorCode.UNAUTHORIZED

    chat_session.deleted = True
    db_session.commit()
    with pytest.raises(OnyxError) as raised:
        update_chat_tool_options(chat_session.id, SAVED, owner, db_session)
    assert raised.value.error_code is OnyxErrorCode.SESSION_NOT_FOUND
    assert _stored(db_session, chat_session) is None


def test_the_chat_detail_returns_the_saved_options_to_its_owner(
    db_session: Session, owner: User
) -> None:
    chat_session = _chat(db_session, owner)
    update_chat_tool_options(chat_session.id, SAVED, owner, db_session)
    detail = get_chat_session(chat_session.id, user=owner, db_session=db_session)
    assert detail.tool_options == SAVED


def test_a_send_leaves_the_saved_options_alone(
    db_session: Session, owner: User
) -> None:
    """A send's one-message options never change the chat's saved options."""
    chat_session = _chat(db_session, owner)
    update_chat_tool_options(chat_session.id, SAVED, owner, db_session)
    _prepare(
        owner,
        SendMessageRequest(
            message="Answer without tools",
            chat_session_id=chat_session.id,
            tool_options=ToolOptions(allowed=[]),
        ),
    )
    assert _stored(db_session, chat_session) == SAVED


def test_a_deep_research_send_leaves_the_saved_options_alone(
    db_session: Session, owner: User
) -> None:
    """Deep Research drops the preferred tool for one message only."""
    chat_session = _chat(db_session, owner)
    update_chat_tool_options(chat_session.id, SAVED, owner, db_session)
    _prepare(
        owner,
        SendMessageRequest(
            message="Research the market",
            chat_session_id=chat_session.id,
            deep_research=True,
        ),
    )
    assert _stored(db_session, chat_session) == SAVED


def test_a_parked_response_continues_with_the_tool_options_of_its_checkpoint(
    db_session: Session, owner: User
) -> None:
    search_id = get_builtin_tool(db_session, SearchTool).id
    chat_session = _chat(db_session, owner)
    response = ChatMessage(
        chat_session_id=chat_session.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(response)
    db_session.flush()
    options = ToolOptions(allowed=[CapabilityEntry(tool_id=search_id)])
    state: dict[str, JsonValue] = {"tool_options": options.model_dump(mode="json")}
    db_session.add(ChatResponseCheckpoint(chat_message_id=response.id, state=state))
    db_session.commit()

    _model, parked_options = parked_response_settings(db_session, response.id)

    assert parked_options == options
