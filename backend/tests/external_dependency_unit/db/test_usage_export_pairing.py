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


def test_multi_model_branch_emits_row_per_assistant_child(
    db_session: Session,
) -> None:
    """A user message answered by multiple models (multi-model branch) must
    produce one report row per assistant child so no model invocation is
    dropped — even non-preferred branches."""
    user = create_test_user(db_session, "usage-export-branch")
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

    # Even when one branch is marked preferred, both must still be reported.
    user_msg.preferred_response_id = assistant_b.id
    db_session.commit()

    _, skeletons = get_empty_chat_messages_entries__paginated(
        db_session, _full_period()
    )

    matching = [s for s in skeletons if s.message_id == user_msg.id]
    assert {s.llm_model for s in matching} == {"model-a", "model-b"}
    assert len(matching) == 2


def test_single_assistant_child_emits_single_row(db_session: Session) -> None:
    """The common case (one assistant reply per user message) still produces
    exactly one row with that model. Guards against the per-pair change
    inflating row counts in non-branched conversations."""
    user = create_test_user(db_session, "usage-export-single")
    chat_session = create_chat_session(
        db_session=db_session,
        description="single reply",
        user_id=user.id,
        persona_id=None,
    )
    root = get_or_create_root_message(chat_session.id, db_session)

    user_msg = _make_user_message(db_session, chat_session.id, root)
    _make_assistant_message(db_session, chat_session.id, user_msg, "only-model")

    _, skeletons = get_empty_chat_messages_entries__paginated(
        db_session, _full_period()
    )

    matching = [s for s in skeletons if s.message_id == user_msg.id]
    assert len(matching) == 1
    assert matching[0].llm_model == "only-model"


def test_orphan_user_message_emits_row_with_null_model(db_session: Session) -> None:
    """User message with no assistant reply (still streaming, errored) gets a
    single row with `llm_model=None` rather than being dropped."""
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
