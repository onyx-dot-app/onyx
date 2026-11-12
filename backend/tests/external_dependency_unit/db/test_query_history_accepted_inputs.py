"""The query history export includes messages a response accepted while it ran."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ee.onyx.server.query_history.api import snapshot_from_chat_session
from ee.onyx.server.query_history.models import QuestionAnswerPairSnapshot
from onyx.agents.models import ExecutionStatus, InputSource
from onyx.configs.constants import MessageType
from onyx.db.chat import (
    create_chat_session,
    create_new_chat_message,
    get_or_create_root_message,
)
from onyx.db.models import (
    AcceptedChatInput,
    ChatResponseItem,
    ChatSession,
    User,
)
from onyx.llm.models import AssistantMessage, TextContent
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user


@pytest.fixture
def owner(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "query-history-inputs")
    yield user

    db_session.rollback()
    db_session.query(ChatSession).filter(ChatSession.user_id == user.id).delete()
    delete_test_user(db_session, user)
    db_session.commit()


def test_export_lists_accepted_inputs_in_model_order(
    db_session: Session, owner: User
) -> None:
    chat_session = create_chat_session(
        db_session=db_session,
        description="steered chat",
        user_id=owner.id,
        persona_id=None,
    )
    root = get_or_create_root_message(
        chat_session_id=chat_session.id, db_session=db_session
    )
    question = create_new_chat_message(
        chat_session_id=chat_session.id,
        parent_message=root,
        message="Compare the vendors",
        token_count=3,
        message_type=MessageType.USER,
        db_session=db_session,
    )
    answer = create_new_chat_message(
        chat_session_id=chat_session.id,
        parent_message=question,
        message="Vendor B is cheaper",
        token_count=4,
        message_type=MessageType.ASSISTANT,
        db_session=db_session,
    )
    steps = [
        [AcceptedChatInput(id="late", source=InputSource.HUMAN, content="Then cost")],
        [
            AcceptedChatInput(
                id="first", source=InputSource.HUMAN, content="Focus on latency"
            ),
            AcceptedChatInput(
                id="second", source=InputSource.HUMAN, content="Include support"
            ),
        ],
    ]
    # Rows are added out of step order; the export follows the model's order.
    for step_index, inputs in ((1, steps[0]), (0, steps[1])):
        item_id = str(uuid4())
        db_session.add(
            ChatResponseItem(
                id=item_id,
                chat_message_id=answer.id,
                step_index=step_index,
                message=AssistantMessage(
                    id=item_id, content=[TextContent(text="Working")]
                ),
                inputs=inputs,
                generation_status=ExecutionStatus.COMPLETE,
            )
        )
    db_session.commit()
    db_session.expire_all()

    snapshot = snapshot_from_chat_session(
        chat_session=db_session.get_one(ChatSession, chat_session.id),
        db_session=db_session,
    )

    assert snapshot is not None
    [pair] = QuestionAnswerPairSnapshot.from_chat_session_snapshot(snapshot)
    assert [accepted.id for accepted in pair.accepted_inputs] == [
        "first",
        "second",
        "late",
    ]
    assert pair.to_json()["accepted_inputs"] == (
        "[human] Focus on latency\n\n[human] Include support\n\n[human] Then cost"
    )
