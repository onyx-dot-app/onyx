from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from onyx.db.enums import ChatSessionSharedStatus
from onyx.db.models import ChatSession, Persona, User
from onyx.server.query_and_chat.chat_backend import get_chat_session


@pytest.mark.parametrize("cache_construction_fails", [False, True])
def test_saved_session_loads_when_processing_cache_is_unavailable(
    cache_construction_fails: bool,
) -> None:
    user = User(id=uuid4(), email="reader@example.com")
    session = ChatSession(
        id=uuid4(),
        user_id=user.id,
        persona_id=1,
        persona=Persona(id=1, name="Assistant", icon_name=None),
        description="Saved conversation",
        time_created=datetime.now(timezone.utc),
        shared_status=ChatSessionSharedStatus.PRIVATE,
        deleted=False,
    )
    cache = MagicMock()
    cache.exists.side_effect = ConnectionError("Cache unavailable")
    with (
        patch(
            "onyx.server.query_and_chat.chat_backend.get_chat_session_by_id",
            return_value=session,
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.get_chat_messages_by_session",
            return_value=[],
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.get_cache_backend",
            return_value=cache,
            side_effect=ConnectionError("Cache unavailable")
            if cache_construction_fails
            else None,
        ),
    ):
        response = get_chat_session(session.id, user=user, db_session=MagicMock())

    assert response.chat_session_id == session.id
    assert response.description == "Saved conversation"
    assert response.current_stream is None
    assert response.is_processing is False
