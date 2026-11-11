"""Pending human input is session-scoped and is accepted at most once."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.agents.models import (
    InputMessageMetadata,
    InputSource,
    MessageDelivery,
    RunStatus,
)
from onyx.configs.constants import MessageType
from onyx.db.chat import (
    create_chat_history_chain,
    create_new_chat_message,
    get_or_create_root_message,
    reserve_chat_response_ids,
)
from onyx.db.chat_inputs import (
    consume_inputs__no_commit,
    list_human_messages,
    read_run_inputs,
    submit_human_message__no_commit,
    withdraw_human_message__no_commit,
)
from onyx.db.models import ChatSession
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from tests.external_dependency_unit.conftest import MakeTestUser


def test_between_step_input_withdrawal_cannot_be_resurrected(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    owner = make_test_user("pending-chat-input")
    conversation = ChatSession(id=uuid4(), user_id=owner.id)
    db_session.add(conversation)
    db_session.flush()
    root = get_or_create_root_message(conversation.id, db_session)
    question = create_new_chat_message(
        conversation.id, root, "Question", 1, MessageType.USER, db_session, commit=False
    )
    response = create_new_chat_message(
        conversation.id,
        question,
        "",
        0,
        MessageType.ASSISTANT,
        db_session,
        commit=False,
    )
    response.response_status = RunStatus.RUNNING
    db_session.flush()
    pending = submit_human_message__no_commit(
        db_session,
        conversation.id,
        message="Focus on latency",
        delivery=MessageDelivery.SEND,
        target_response_id=response.id,
    )
    messages = read_run_inputs(
        db_session, str(conversation.id), str(response.id), [response.id], None
    )[0]
    assert len(messages) == 1
    assert messages[0].metadata == InputMessageMetadata(source=InputSource.HUMAN)
    assert (
        withdraw_human_message__no_commit(db_session, conversation.id, pending.id)
        == pending
    )
    db_session.flush()
    assert not consume_inputs__no_commit(
        db_session, response.id, messages, [], ownership_version=None
    )
    replacement = submit_human_message__no_commit(
        db_session,
        conversation.id,
        message="Focus on cost",
        delivery=MessageDelivery.SEND,
        target_response_id=response.id,
    )
    messages = read_run_inputs(
        db_session, str(conversation.id), str(response.id), [response.id], None
    )[0]
    assert consume_inputs__no_commit(
        db_session, response.id, messages, [], ownership_version=None
    )
    db_session.commit()
    with pytest.raises(OnyxError) as withdrawn:
        withdraw_human_message__no_commit(db_session, conversation.id, replacement.id)
    assert withdrawn.value.error_code == OnyxErrorCode.CONFLICT
    assert list_human_messages(db_session, conversation.id) == []
    # A second consumer finds nothing left to accept.
    assert not consume_inputs__no_commit(
        db_session, response.id, messages, [], ownership_version=None
    )


def test_follow_up_question_keeps_history_and_pending_messages(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    owner = make_test_user("agent-results-question")
    conversation = ChatSession(id=uuid4(), user_id=owner.id)
    db_session.add(conversation)
    db_session.flush()
    root = get_or_create_root_message(conversation.id, db_session)
    question = create_new_chat_message(
        conversation.id,
        root,
        "Research this",
        2,
        MessageType.USER,
        db_session,
        commit=False,
    )
    response = create_new_chat_message(
        conversation.id,
        question,
        "Research is running",
        3,
        MessageType.ASSISTANT,
        db_session,
        commit=False,
    )
    response.response_status = RunStatus.COMPLETE
    db_session.flush()
    pending = submit_human_message__no_commit(
        db_session,
        conversation.id,
        message="Then compare the results",
        delivery=MessageDelivery.QUEUE,
        target_response_id=response.id,
    )
    results = create_new_chat_message(
        conversation.id,
        response,
        "",
        0,
        MessageType.AGENT_RESULTS,
        db_session,
        commit=False,
    )
    follow_up_ids = reserve_chat_response_ids(
        db_session, conversation.id, results.id, ["Test model"]
    )
    db_session.expire_all()
    history = create_chat_history_chain(conversation.id, db_session)
    assert [message.id for message in history] == [
        question.id,
        response.id,
        results.id,
        follow_up_ids[0],
    ]
    assert [message.message_type for message in history] == [
        MessageType.USER,
        MessageType.ASSISTANT,
        MessageType.AGENT_RESULTS,
        MessageType.ASSISTANT,
    ]
    # Queued input belongs to the session, not to a response.
    assert list_human_messages(db_session, conversation.id) == [pending]
    assert pending.target_response_id is None

    reserve_chat_response_ids(
        db_session, conversation.id, follow_up_ids[0], ["Test model"]
    )
    db_session.expire_all()
    with pytest.raises(RuntimeError, match="two assistant messages"):
        create_chat_history_chain(conversation.id, db_session)
