"""Child conversations inherit root access and lifecycle without becoming public chats."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ee.onyx.db.query_history import fetch_persisting_chat_session_by_id
from onyx.configs.constants import MessageType
from onyx.db.chat import (
    delete_chat_session,
    get_chat_message,
    get_chat_messages_by_session,
    get_chat_session_by_id,
    get_chat_sessions_by_slack_thread_id,
    get_chat_sessions_by_user,
    get_chat_sessions_older_than,
    get_owned_chat_session,
)
from onyx.db.incognito import is_incognito_teardown_target
from onyx.db.models import ChatMessage, ChatSession


def test_child_access_and_root_lifecycle(db_session: Session) -> None:
    root = ChatSession(id=uuid4(), description="Root", user_id=None)
    db_session.add(root)
    db_session.flush()
    root_response = ChatMessage(
        chat_session_id=root.id,
        message="Created child",
        token_count=2,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(root_response)
    db_session.flush()
    child = ChatSession(
        id=uuid4(), description="Child", spawned_by_message_id=root_response.id
    )
    db_session.add(child)
    db_session.flush()
    child_message = ChatMessage(
        chat_session_id=child.id,
        message="Private child",
        token_count=2,
        message_type=MessageType.ASSISTANT,
        files=[{"id": "child-file", "type": "plain_text"}],
    )
    visible = ChatMessage(
        chat_session_id=root.id,
        message="Visible",
        token_count=1,
        message_type=MessageType.ASSISTANT,
    )
    summary = ChatMessage(
        chat_session_id=root.id,
        message="Summary",
        token_count=1,
        message_type=MessageType.SUMMARY,
        summary_covered_count=1,
        summary_covered_digest="covered-prefix",
    )
    db_session.add_all([child_message, visible, summary])
    db_session.flush()
    grandchild = ChatSession(id=uuid4(), spawned_by_message_id=child_message.id)
    db_session.add(grandchild)
    db_session.commit()
    root_id, child_id, grandchild_id = root.id, child.id, grandchild.id
    try:
        assert get_owned_chat_session(root_id, uuid4(), db_session) is None
        assert get_owned_chat_session(child_id, uuid4(), db_session) is None
        for shared in (False, True):
            with pytest.raises(ValueError):
                get_chat_session_by_id(child_id, None, db_session, is_shared=shared)
        with pytest.raises(ValueError):
            fetch_persisting_chat_session_by_id(child_id, db_session)
        with pytest.raises(ValueError):
            get_chat_message(child_message.id, None, db_session)
        with pytest.raises(ValueError):
            get_chat_message(summary.id, None, db_session)
        assert not is_incognito_teardown_target(db_session, child_id, uuid4())
        assert (
            get_chat_messages_by_session(
                child_id, None, db_session, skip_permission_check=True
            )
            == []
        )
        assert [
            m.id for m in get_chat_messages_by_session(root_id, None, db_session)
        ] == [root_response.id, visible.id]
        assert child_id not in {
            s.id
            for s in get_chat_sessions_by_user(
                None, False, db_session, include_failed_chats=True
            )
        }
        assert (
            get_chat_sessions_by_slack_thread_id("not-a-thread", None, db_session) == []
        )
        with patch("onyx.db.chat.get_default_file_store") as store:
            delete_chat_session(None, root_id, db_session, hard_delete=True)
            store.return_value.delete_file.assert_called_once_with(
                file_id="child-file", error_on_missing=False
            )
        db_session.expire_all()
        assert db_session.get(ChatSession, root_id) is None
        assert db_session.get(ChatSession, child_id) is None
        assert db_session.get(ChatSession, grandchild_id) is None
    finally:
        db_session.rollback()
        if db_session.get(ChatSession, root_id) is not None:
            with patch("onyx.db.chat.get_default_file_store"):
                delete_chat_session(None, root_id, db_session, hard_delete=True)


def test_retention_uses_nested_child_activity(db_session: Session) -> None:
    old = datetime.now(timezone.utc) - timedelta(days=30)
    root = ChatSession(id=uuid4(), time_created=old)
    db_session.add(root)
    db_session.flush()
    creation = ChatMessage(
        chat_session_id=root.id,
        message="Created child",
        token_count=2,
        message_type=MessageType.ASSISTANT,
        time_sent=old,
    )
    db_session.add(creation)
    db_session.flush()
    child = ChatSession(id=uuid4(), spawned_by_message_id=creation.id, time_created=old)
    db_session.add(child)
    db_session.flush()
    child_creation = ChatMessage(
        chat_session_id=child.id,
        message="Created grandchild",
        token_count=2,
        message_type=MessageType.ASSISTANT,
        time_sent=old,
    )
    db_session.add(child_creation)
    db_session.flush()
    grandchild = ChatSession(
        id=uuid4(), spawned_by_message_id=child_creation.id, time_created=old
    )
    db_session.add(grandchild)
    db_session.flush()
    db_session.add(
        ChatMessage(
            chat_session_id=grandchild.id,
            message="Recent",
            token_count=1,
            message_type=MessageType.USER,
        )
    )
    db_session.commit()
    try:
        expired = {
            session_id for _, session_id in get_chat_sessions_older_than(7, db_session)
        }
        assert root.id not in expired
        assert child.id not in expired
        assert grandchild.id not in expired
        delete_chat_session(None, root.id, db_session, hard_delete=False)
        with pytest.raises(ValueError, match="deleted"):
            get_chat_session_by_id(root.id, None, db_session)
    finally:
        delete_chat_session(
            None, root.id, db_session, include_deleted=True, hard_delete=True
        )
