from datetime import datetime, timezone
from uuid import uuid4

from ee.onyx.server.query_history.models import (
    ChatSessionSnapshot,
    MessageSnapshot,
    QuestionAnswerPairSnapshot,
)
from onyx.configs.constants import MessageType, SessionType


def _message(message_id: int, message_type: MessageType, text: str) -> MessageSnapshot:
    return MessageSnapshot(
        id=message_id,
        message=text,
        message_type=message_type,
        documents=[],
        feedback_type=None,
        feedback_text=None,
        time_created=datetime(2026, 1, 1, 0, 0, message_id, tzinfo=timezone.utc),
    )


def test_an_automatic_follow_up_pairs_with_no_question_and_keeps_later_pairs() -> None:
    # The follow-up's hidden question is removed before pairing.
    snapshot = ChatSessionSnapshot(
        id=uuid4(),
        user_email="reader@example.com",
        name=None,
        messages=[
            _message(1, MessageType.USER, "Research the market"),
            _message(2, MessageType.ASSISTANT, "Started the research"),
            _message(4, MessageType.ASSISTANT, "The research found three rivals"),
            _message(5, MessageType.USER, "Compare their prices"),
            _message(6, MessageType.ASSISTANT, "Rival A is cheapest"),
        ],
        assistant_id=None,
        assistant_name=None,
        time_created=datetime(2026, 1, 1, tzinfo=timezone.utc),
        flow_type=SessionType.CHAT,
    )

    pairs = QuestionAnswerPairSnapshot.from_chat_session_snapshot(snapshot)

    assert [(pair.user_message, pair.ai_response) for pair in pairs] == [
        ("Research the market", "Started the research"),
        ("", "The research found three rivals"),
        ("Compare their prices", "Rival A is cheapest"),
    ]
    assert [pair.message_pair_num for pair in pairs] == [1, 2, 3]
