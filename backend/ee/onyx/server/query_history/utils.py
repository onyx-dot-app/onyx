from datetime import datetime

from sqlalchemy.orm import Session

from ee.onyx.db.query_history import fetch_chat_sessions_eagerly_by_time
from ee.onyx.server.query_history.models import ChatSessionSnapshot
from ee.onyx.server.query_history.models import MessageSnapshot
from onyx.auth.users import get_display_email
from onyx.chat.chat_utils import create_chat_chain
from onyx.configs.constants import MessageType
from onyx.configs.constants import QAFeedbackType
from onyx.configs.constants import SessionType
from onyx.db.models import ChatSession

ONYX_ANONYMIZED_EMAIL = "anonymous@anonymous.invalid"


def fetch_and_process_chat_session_history(
    db_session: Session,
    start: datetime,
    end: datetime,
    feedback_type: QAFeedbackType | None,  # type: ignore
    limit: int | None = 500,
) -> list[ChatSessionSnapshot]:
    # observed to be slow a scale of 8192 sessions and 4 messages per session

    # this is a little slow (5 seconds)
    chat_sessions = fetch_chat_sessions_eagerly_by_time(
        start=start, end=end, db_session=db_session, limit=limit
    )

    # this is VERY slow (80 seconds) due to create_chat_chain being called
    # for each session. Needs optimizing.
    chat_session_snapshots = [
        snapshot_from_chat_session(chat_session=chat_session, db_session=db_session)
        for chat_session in chat_sessions
    ]

    valid_snapshots = [
        snapshot for snapshot in chat_session_snapshots if snapshot is not None
    ]

    if feedback_type:
        valid_snapshots = [
            snapshot
            for snapshot in valid_snapshots
            if any(
                message.feedback_type == feedback_type for message in snapshot.messages
            )
        ]

    return valid_snapshots


def snapshot_from_chat_session(
    chat_session: ChatSession,
    db_session: Session,
) -> ChatSessionSnapshot | None:
    try:
        # Older chats may not have the right structure
        last_message, messages = create_chat_chain(
            chat_session_id=chat_session.id, db_session=db_session
        )
        messages.append(last_message)
    except RuntimeError:
        return None

    flow_type = SessionType.SLACK if chat_session.onyxbot_flow else SessionType.CHAT

    return ChatSessionSnapshot(
        id=chat_session.id,
        user_email=get_display_email(
            chat_session.user.email if chat_session.user else None
        ),
        name=chat_session.description,
        messages=[
            MessageSnapshot.build(message)
            for message in messages
            if message.message_type != MessageType.SYSTEM
        ],
        assistant_id=chat_session.persona_id,
        assistant_name=chat_session.persona.name if chat_session.persona else None,
        time_created=chat_session.time_created,
        flow_type=flow_type,
    )
