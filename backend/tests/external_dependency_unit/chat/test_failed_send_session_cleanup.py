"""Tests for husk prevention in the send-message failure path.

A send that fails before the user message is committed leaves a session with
no user-visible content; the failure path is expected to delete it so it never
shows up as an unnamed husk in the sidebar. A failure after the user message
landed is a real conversation and must survive.
"""

import uuid
from collections.abc import Generator
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.chat.models import AnswerStreamPart, StreamingError
from onyx.chat.process_message import handle_stream_message_objects
from onyx.configs.constants import MessageType
from onyx.db.chat import create_chat_session, delete_chat_session
from onyx.db.models import ChatMessage, ChatSession, Persona, User
from onyx.db.persona import upsert_persona
from onyx.server.query_and_chat.models import SendMessageRequest
from tests.external_dependency_unit.answer.conftest import ensure_default_llm_provider
from tests.external_dependency_unit.conftest import create_test_user


@pytest.fixture
def test_user(db_session: Session) -> User:
    return create_test_user(db_session, email_prefix="failed_send_cleanup")


@pytest.fixture
def test_persona(db_session: Session) -> Persona:
    ensure_default_llm_provider(db_session)
    return upsert_persona(
        user=None,
        name=f"Failed Send Cleanup Persona {uuid.uuid4()}",
        description="Tool-less persona for send-failure tests",
        starter_messages=None,
        system_prompt=None,
        task_prompt=None,
        datetime_aware=None,
        is_public=True,
        db_session=db_session,
        tool_ids=[],
        document_set_ids=None,
        is_listed=True,
        default_model_configuration_id=None,
    )


def _session_row_exists(db_session: Session, chat_session_id: UUID) -> bool:
    # Plain SELECT on purpose: Session.get() on an identity-map instance whose
    # row was deleted by another session raises ObjectDeletedError on refresh.
    return (
        db_session.execute(
            select(ChatSession.id).where(ChatSession.id == chat_session_id)
        ).first()
        is not None
    )


@pytest.fixture
def session_tracker(db_session: Session) -> Generator[list[UUID], None, None]:
    created: list[UUID] = []
    yield created
    db_session.expunge_all()
    for session_id in created:
        if _session_row_exists(db_session, session_id):
            delete_chat_session(
                user_id=None,
                chat_session_id=session_id,
                db_session=db_session,
                include_deleted=True,
                hard_delete=True,
            )


def _consume_stream_expecting_error(
    new_msg_req: SendMessageRequest, user: User
) -> None:
    packets: list[AnswerStreamPart] = list(
        handle_stream_message_objects(new_msg_req=new_msg_req, user=user)
    )
    assert any(isinstance(packet, StreamingError) for packet in packets)


def test_failure_before_user_message_commit_deletes_session(
    db_session: Session,
    test_user: User,
    test_persona: Persona,
    session_tracker: list[UUID],
) -> None:
    chat_session = create_chat_session(
        db_session=db_session,
        description=None,
        user_id=test_user.id,
        persona_id=test_persona.id,
    )
    session_tracker.append(chat_session.id)
    # Release this session's snapshot so we observe the flow's own commits.
    db_session.commit()

    # verify_user_files runs during setup, before the user message is written.
    with patch(
        "onyx.chat.process_message.verify_user_files",
        side_effect=RuntimeError("forced setup failure"),
    ):
        _consume_stream_expecting_error(
            SendMessageRequest(message="hello", chat_session_id=chat_session.id),
            test_user,
        )

    db_session.expunge_all()
    assert not _session_row_exists(db_session, chat_session.id)
    assert (
        db_session.execute(
            select(ChatMessage.id).where(ChatMessage.chat_session_id == chat_session.id)
        ).first()
        is None
    )


def test_failure_after_user_message_commit_keeps_session(
    db_session: Session,
    test_user: User,
    test_persona: Persona,
    session_tracker: list[UUID],
) -> None:
    chat_session = create_chat_session(
        db_session=db_session,
        description=None,
        user_id=test_user.id,
        persona_id=test_persona.id,
    )
    session_tracker.append(chat_session.id)
    db_session.commit()

    # reserve_message_id runs right after the user message is committed.
    with patch(
        "onyx.chat.process_message.reserve_message_id",
        side_effect=RuntimeError("forced post-commit failure"),
    ):
        _consume_stream_expecting_error(
            SendMessageRequest(message="hello", chat_session_id=chat_session.id),
            test_user,
        )

    db_session.expunge_all()
    assert _session_row_exists(db_session, chat_session.id)
    user_messages = (
        db_session.execute(
            select(ChatMessage)
            .where(ChatMessage.chat_session_id == chat_session.id)
            .where(ChatMessage.message_type == MessageType.USER)
        )
        .scalars()
        .all()
    )
    assert len(user_messages) == 1
    assert user_messages[0].message == "hello"
