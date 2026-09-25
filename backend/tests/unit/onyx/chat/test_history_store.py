"""Temporary content saves follow the database recording-policy check."""

from contextlib import nullcontext
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.chat.history_store import (
    PostgresChatHistoryStore,
    RedisChatHistoryStore,
    get_chat_history_store,
)
from onyx.chat.models import ChatResponseSnapshot
from onyx.configs.constants import MessageType
from onyx.db.chat_response import save_chat_response_to_db
from onyx.db.enums import IncognitoRecordMode
from onyx.db.models import ChatMessage, ChatSession


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
