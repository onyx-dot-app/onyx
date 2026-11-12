from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.agents.models import InputSource
from onyx.db.models import ChatInput, ChatSession
from tests.external_dependency_unit.conftest import MakeTestUser


def test_source_check_rejects_rows_with_null_required_fields(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    owner = make_test_user("chat-input-constraint")
    conversation = ChatSession(id=uuid4(), user_id=owner.id)
    db_session.add(conversation)
    db_session.flush()
    db_session.add(
        ChatInput(
            recipient_session_id=conversation.id,
            message_id=str(uuid4()),
            source=InputSource.HUMAN,
            delivery=None,
            content="No delivery",
        )
    )
    with pytest.raises(IntegrityError, match="ck_chat_input_source"):
        db_session.flush()
    db_session.rollback()
