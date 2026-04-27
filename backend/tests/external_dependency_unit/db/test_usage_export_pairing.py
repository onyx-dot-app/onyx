from datetime import datetime
from datetime import timezone
from uuid import UUID

from sqlalchemy.orm import Session

from ee.onyx.db.usage_export import get_empty_chat_messages_entries__paginated
from onyx.configs.constants import MessageType
from onyx.db.chat import create_chat_session
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import get_or_create_root_message
from onyx.db.models import ChatMessage
from tests.external_dependency_unit.conftest import create_test_user


def _full_period() -> tuple[datetime, datetime]:
    return (
        datetime.fromtimestamp(0, tz=timezone.utc),
        datetime.now(tz=timezone.utc),
    )


def _make_user_message(
    db_session: Session, chat_session_id: UUID, parent: ChatMessage
) -> ChatMessage:
    return create_new_chat_message(
        chat_session_id=chat_session_id,
        parent_message=parent,
        message="user prompt",
        token_count=0,
        message_type=MessageType.USER,
        db_session=db_session,
    )


def _make_assistant_message(
    db_session: Session,
    chat_session_id: UUID,
    parent: ChatMessage,
    model_display_name: str,
) -> ChatMessage:
    msg = create_new_chat_message(
        chat_session_id=chat_session_id,
        parent_message=parent,
        message="assistant reply",
        token_count=0,
        message_type=MessageType.ASSISTANT,
        db_session=db_session,
    )
    msg.model_display_name = model_display_name
    db_session.commit()
    return msg


def test_pairing_prefers_preferred_response_when_set(db_session: Session) -> None:
    """Multi-model branch: user message has two assistant children with different
    models. `preferred_response_id` should determine which model is reported."""
    user = create_test_user(db_session, "usage-export-preferred")
    chat_session = create_chat_session(
        db_session=db_session,
        description="multi-model branch",
        user_id=user.id,
        persona_id=None,
    )
    root = get_or_create_root_message(chat_session.id, db_session)

    user_msg = _make_user_message(db_session, chat_session.id, root)
    _make_assistant_message(db_session, chat_session.id, user_msg, "model-a")
    assistant_b = _make_assistant_message(
        db_session, chat_session.id, user_msg, "model-b"
    )

    user_msg.preferred_response_id = assistant_b.id
    db_session.commit()

    _, skeletons = get_empty_chat_messages_entries__paginated(
        db_session, _full_period()
    )

    matching = [s for s in skeletons if s.message_id == user_msg.id]
    assert len(matching) == 1
    assert matching[0].llm_model == "model-b"


def test_pairing_falls_back_to_earliest_child_when_no_preference(
    db_session: Session,
) -> None:
    """No `preferred_response_id` set: pick the earliest assistant child (the
    original reply, before any retries)."""
    user = create_test_user(db_session, "usage-export-fallback")
    chat_session = create_chat_session(
        db_session=db_session,
        description="multi-model fallback",
        user_id=user.id,
        persona_id=None,
    )
    root = get_or_create_root_message(chat_session.id, db_session)

    user_msg = _make_user_message(db_session, chat_session.id, root)
    _make_assistant_message(db_session, chat_session.id, user_msg, "first-model")
    _make_assistant_message(db_session, chat_session.id, user_msg, "second-model")

    _, skeletons = get_empty_chat_messages_entries__paginated(
        db_session, _full_period()
    )

    matching = [s for s in skeletons if s.message_id == user_msg.id]
    assert len(matching) == 1
    assert matching[0].llm_model == "first-model"


def test_pairing_returns_none_for_orphan_user_message(db_session: Session) -> None:
    """User message with no assistant reply (e.g. still streaming, errored) gets
    a None llm_model rather than crashing."""
    user = create_test_user(db_session, "usage-export-orphan")
    chat_session = create_chat_session(
        db_session=db_session,
        description="orphan user message",
        user_id=user.id,
        persona_id=None,
    )
    root = get_or_create_root_message(chat_session.id, db_session)

    user_msg = _make_user_message(db_session, chat_session.id, root)

    _, skeletons = get_empty_chat_messages_entries__paginated(
        db_session, _full_period()
    )

    matching = [s for s in skeletons if s.message_id == user_msg.id]
    assert len(matching) == 1
    assert matching[0].llm_model is None
