"""Temporary content saves follow the database recording-policy check."""

from contextlib import nullcontext
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.agents.models import (
    AgentInfo,
    ExecutionStatus,
    RunState,
    RunStatus,
    StepRecord,
)
from onyx.chat.citation_utils import message_citation_sources
from onyx.chat.history_store import (
    PostgresChatHistoryStore,
    RedisChatHistoryStore,
    get_chat_history_store,
)
from onyx.chat.models import (
    ChatMessageMetadata,
    ChatResponseSnapshot,
    IncognitoContext,
    IncognitoState,
)
from onyx.chat.presentation import project_response
from onyx.chat.prompt_formatting import prompt_metadata
from onyx.chat.subagents import ChatAgentDirectory
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import SearchDoc
from onyx.db.chat_response import save_chat_response_to_db
from onyx.db.enums import IncognitoRecordMode
from onyx.db.models import ChatMessage, ChatSession
from onyx.llm.interfaces import LLM, LLMUserIdentity
from onyx.llm.models import (
    AssistantMessage,
    TextContent,
    ToolResultMessage,
    UserMessage,
)
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


@pytest.mark.parametrize("persist_content", [False, True])
def test_recording_policy_selects_history_store(persist_content: bool) -> None:
    store = get_chat_history_store(
        message_id=17,
        chat_session_id=uuid4(),
        persist_content=persist_content,
    )
    expected_type = (
        PostgresChatHistoryStore if persist_content else RedisChatHistoryStore
    )
    assert isinstance(store, expected_type)


@pytest.mark.parametrize("accepted_text", [None, "", "Rewritten question"])
def test_temporary_history_preparation_waits_for_explicit_user_message_save(
    accepted_text: str | None,
) -> None:
    session_id = uuid4()
    store = RedisChatHistoryStore(
        message_id=17, chat_session_id=session_id, visible_message_ids=()
    )
    previous = UserMessage(id="chat:17", content="Original question")
    incoming = UserMessage(content="Converted request with attached context")
    saved = IncognitoContext(
        version=1, messages=[previous], previous_run_id="saved-run"
    )
    with (
        patch("onyx.chat.history_store.load_incognito_context", return_value=saved),
        patch("onyx.chat.history_store.save_incognito_user_message") as append,
    ):
        messages, previous_run_id = store.prepare_messages(
            [incoming], "database-run", accepted_text
        )
        assert previous_run_id == ("saved-run" if accepted_text is not None else None)
        append.assert_not_called()
        if accepted_text is None:
            assert messages == [previous]
        else:
            assert messages == [previous, UserMessage(content=accepted_text)]
            current_user = messages[-1]
            assert isinstance(current_user, UserMessage)
            store.save_user_message(current_user)
            append.assert_called_once_with(session_id, current_user)
        assert incoming.content == "Converted request with attached context"
        assert saved.messages == [previous]


@pytest.mark.parametrize("database_fails", [False, True])
def test_temporary_content_is_saved_only_after_database_success(
    database_fails: bool,
) -> None:
    session_id = uuid4()
    store = get_chat_history_store(
        message_id=17, chat_session_id=session_id, persist_content=False
    )
    response = ChatResponseSnapshot(
        answer="private answer",
        response=None,
        reasoning=None,
        request_params=None,
        citation_to_doc={},
        tool_calls=[],
        is_clarification=False,
        all_search_docs={},
        pre_answer_processing_time=None,
        cancelled=False,
    )
    calls = Mock()
    with (
        patch("onyx.chat.history_store.save_chat_response_to_db") as save_database,
        patch("onyx.chat.history_store.save_incognito_response") as save_temporary,
    ):
        calls.attach_mock(save_database, "database")
        calls.attach_mock(save_temporary, "temporary")
        if database_fails:
            save_database.side_effect = ValueError("recording mode changed")
            with pytest.raises(ValueError, match="recording mode changed"):
                store.save_response(response)
            save_temporary.assert_not_called()
        else:
            save_database.return_value = "saved answer"
            store.save_response(response)
            assert [call[0] for call in calls.mock_calls] == ["database", "temporary"]
            save_temporary.assert_called_once()
            assert save_temporary.call_args.kwargs["messages"][0].text == "saved answer"
        save_database.assert_called_once_with(
            message_id=17,
            chat_session_id=session_id,
            expected_persist_content=False,
            response=response,
        )


@pytest.mark.parametrize(
    ("wrong_session", "stored_mode", "expected_persist_content"),
    [
        (True, None, True),
        (False, IncognitoRecordMode.USAGE_ONLY, True),
        (False, IncognitoRecordMode.FULL_HISTORY, False),
        (False, None, False),
    ],
)
def test_database_save_rejects_mismatched_storage_before_mutation(
    wrong_session: bool,
    stored_mode: IncognitoRecordMode | None,
    expected_persist_content: bool,
) -> None:
    session_id = uuid4()
    chat_session = ChatSession(id=session_id, incognito_record_mode=stored_mode)
    message = ChatMessage(
        id=17,
        chat_session_id=session_id,
        chat_session=chat_session,
        message="original content",
        error="original error",
        message_type=MessageType.ASSISTANT,
        token_count=0,
    )
    response = ChatResponseSnapshot(
        answer="private answer",
        error="private error",
        response=None,
        reasoning=None,
        request_params=None,
        citation_to_doc={},
        tool_calls=[],
        is_clarification=False,
        all_search_docs={},
        pre_answer_processing_time=None,
        cancelled=False,
    )
    session = Mock(spec=Session)
    session.get.return_value = message
    with (
        patch(
            "onyx.db.chat_response.get_session_with_current_tenant",
            return_value=nullcontext(session),
        ),
        patch("onyx.db.chat_response.finish_checkpoint__no_commit") as finish,
        patch("onyx.db.chat_response.save_chat_turn") as save_turn,
    ):
        expected_error = "another chat session" if wrong_session else "recording mode"
        with pytest.raises(ValueError, match=expected_error):
            save_chat_response_to_db(
                message_id=17,
                chat_session_id=uuid4() if wrong_session else session_id,
                expected_persist_content=expected_persist_content,
                response=response,
            )
        finish.assert_not_called()
        save_turn.assert_not_called()
    session.get.assert_called_once_with(ChatMessage, 17)
    session.flush.assert_not_called()
    session.commit.assert_not_called()
    assert message.message == "original content"
    assert message.error == "original error"


def test_temporary_response_restores_file_sources_before_serialization() -> None:
    source = SearchDoc(
        document_id="project-file",
        chunk_ind=0,
        semantic_identifier="Project.txt",
        link="https://example.com/project",
        blurb="Evidence",
        source_type=DocumentSource.FILE,
        boost=0,
        hidden=False,
        metadata={},
        match_highlights=[],
    )
    message = AssistantMessage(
        id="answer",
        content=[TextContent(text="Evidence [7]")],
        metadata=ChatMessageMetadata(sources={7: source}),
    )
    response = project_response(
        RunState(
            run_id="17",
            status=RunStatus.COMPLETE,
            answer_step_index=0,
            steps=[
                StepRecord(message=message, generation_status=ExecutionStatus.COMPLETE)
            ],
        ),
        tool_ids={},
    )
    store = RedisChatHistoryStore(
        message_id=17,
        chat_session_id=uuid4(),
        visible_message_ids=(),
    )
    with (
        patch(
            "onyx.chat.history_store.save_chat_response_to_db",
            return_value="Evidence [7]",
        ),
        patch("onyx.chat.history_store.save_incognito_response") as save_temporary,
    ):
        store.save_response(response)
    restored = IncognitoState.model_validate_json(
        IncognitoState(
            messages=save_temporary.call_args.kwargs["messages"]
        ).model_dump_json()
    )
    assert message_citation_sources(restored.messages[0]) == {7: source}
    assert response.response is not None
    assert response.response.messages[0].metadata is None


@pytest.mark.parametrize("lookup_fails", [False, True])
def test_agent_lookup_uses_its_tenant_and_restores_the_callers_context(
    lookup_fails: bool,
) -> None:
    agent = AgentInfo(
        id="child",
        path="/root/child",
        parent_id="root",
        description="",
        restoration_config=None,
    )
    token = CURRENT_TENANT_ID_CONTEXTVAR.set("conversation-tenant")
    try:
        directory = ChatAgentDirectory(
            history_store=PostgresChatHistoryStore(
                message_id=17, chat_session_id=uuid4()
            ),
            llm=Mock(spec=LLM),
            tools=[],
            user_identity=LLMUserIdentity(),
            store=None,
        )
        CURRENT_TENANT_ID_CONTEXTVAR.set("caller-tenant")

        def lookup(message_id: int, agent_id: str, parent_id: str) -> AgentInfo:
            assert CURRENT_TENANT_ID_CONTEXTVAR.get() == "conversation-tenant"
            assert (message_id, agent_id, parent_id) == (17, "child", "root")
            if lookup_fails:
                raise RuntimeError("Storage unavailable")
            return agent

        with patch("onyx.chat.history_store.lookup_session_agent", side_effect=lookup):
            if lookup_fails:
                with pytest.raises(RuntimeError, match="Storage unavailable"):
                    directory.lookup_agent("child", "root")
            else:
                assert directory.lookup_agent("child", "root") == agent
        assert CURRENT_TENANT_ID_CONTEXTVAR.get() == "caller-tenant"
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def test_incognito_regeneration_uses_selected_question_and_prompt_only_tool_policy() -> (
    None
):
    store = RedisChatHistoryStore(
        message_id=17, chat_session_id=uuid4(), visible_message_ids=()
    )
    search = ToolResultMessage(
        tool_call_id="search", tool_name="search", content="large passages"
    )
    image = ToolResultMessage(
        tool_call_id="image", tool_name="generate_image", content="image location"
    )
    question = UserMessage(id="chat:17", content="Original question")
    answer = AssistantMessage(content=[TextContent(text="Old answer")])
    cached = IncognitoContext(
        version=1,
        messages=[search, image, question, answer],
        previous_run_id="old-answer",
    )
    with patch("onyx.chat.history_store.load_incognito_context", return_value=cached):
        messages, previous = store.prepare_messages([], None, None)

    assert messages[-1] is question
    assert answer not in messages
    assert previous is None
    assert prompt_metadata(messages[0]).omit_tool_result_content
    assert not prompt_metadata(messages[1]).omit_tool_result_content
    assert search.metadata is None
    assert cached.messages[-1] is answer
