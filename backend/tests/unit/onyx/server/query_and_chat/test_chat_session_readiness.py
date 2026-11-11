from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks

from onyx.db.models import User
from onyx.server.query_and_chat.chat_backend import get_chat_session_processing_status


def test_status_does_not_report_idle_when_cache_fails() -> None:
    with (
        patch(
            "onyx.server.query_and_chat.chat_backend.get_session_with_current_tenant"
        ),
        patch("onyx.server.query_and_chat.chat_backend.get_chat_session_by_id"),
        patch(
            "onyx.server.query_and_chat.chat_backend.has_chat_inputs",
            return_value=False,
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.get_cache_backend",
            side_effect=ConnectionError,
        ),
        pytest.raises(ConnectionError),
    ):
        get_chat_session_processing_status(
            uuid4(), background_tasks=BackgroundTasks(), user=User(id=uuid4())
        )
