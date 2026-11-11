from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks

from onyx.chat.chat_processing_checker import BACKGROUND_CONTROL_PREFIX
from onyx.chat.models import ChatBackgroundActivity
from onyx.db.models import ChatSession, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.query_and_chat.chat_backend import get_chat_session_processing_status
from tests.unit.fakes import FakeCache


@pytest.mark.parametrize(
    "processing, stream_id", [(False, None), (True, None), (True, 12)]
)
def test_status_checks_session_access_before_processing(
    processing: bool, stream_id: int | None
) -> None:
    session_id = uuid4()
    user = User(id=uuid4(), email="reader@example.com")
    cache = MagicMock()
    with (
        patch(
            "onyx.server.query_and_chat.chat_backend.get_session_with_current_tenant"
        ) as database,
        patch(
            "onyx.server.query_and_chat.chat_backend.get_chat_session_by_id"
        ) as lookup,
        patch(
            "onyx.server.query_and_chat.chat_backend.get_cache_backend",
            return_value=cache,
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.get_processing_stream_id",
            return_value=stream_id,
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.is_chat_session_processing",
            return_value=processing,
        ) as check,
        patch(
            "onyx.server.query_and_chat.chat_backend.read_chat_background_activity",
            return_value=ChatBackgroundActivity(),
        ),
    ):
        response = get_chat_session_processing_status(
            session_id, background_tasks=BackgroundTasks(), user=user
        )
    lookup.assert_called_once_with(
        chat_session_id=session_id,
        user_id=user.id,
        db_session=database.return_value.__enter__.return_value,
    )
    if stream_id is None:
        check.assert_called_once_with(session_id, cache)
    else:
        check.assert_not_called()
    assert response.model_dump() == {
        "is_processing": processing,
        "has_active_subagents": False,
        "latest_response_id": None,
        "current_stream": {"stream_id": stream_id} if stream_id is not None else None,
    }


def test_status_does_not_disclose_inaccessible_session() -> None:
    with (
        patch(
            "onyx.server.query_and_chat.chat_backend.get_session_with_current_tenant"
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.get_chat_session_by_id",
            side_effect=ValueError,
        ),
        patch("onyx.server.query_and_chat.chat_backend.get_cache_backend") as cache,
        pytest.raises(OnyxError) as error,
    ):
        get_chat_session_processing_status(
            uuid4(), background_tasks=BackgroundTasks(), user=User(id=uuid4())
        )
    assert error.value.error_code == OnyxErrorCode.SESSION_NOT_FOUND
    cache.assert_not_called()


def test_status_does_not_report_idle_when_cache_fails() -> None:
    with (
        patch(
            "onyx.server.query_and_chat.chat_backend.get_session_with_current_tenant"
        ),
        patch("onyx.server.query_and_chat.chat_backend.get_chat_session_by_id"),
        patch(
            "onyx.server.query_and_chat.chat_backend.read_chat_background_activity",
            return_value=ChatBackgroundActivity(),
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


@pytest.mark.parametrize(
    "refreshed, control_alive, expected_active",
    [
        (
            ChatBackgroundActivity(
                latest_response_id=12, has_pending_root_results=True
            ),
            False,
            True,
        ),
        (
            ChatBackgroundActivity(latest_response_id=13, running_response_ids=[14]),
            False,
            True,
        ),
        (
            ChatBackgroundActivity(latest_response_id=12, running_response_ids=[11]),
            False,
            False,
        ),
        (
            ChatBackgroundActivity(
                latest_response_id=12, completion_host_response_ids=[12]
            ),
            True,
            True,
        ),
        (
            ChatBackgroundActivity(
                latest_response_id=12, completion_host_response_ids=[12]
            ),
            False,
            False,
        ),
    ],
)
def test_status_observes_result_handoff_when_child_releases_ownership(
    refreshed: ChatBackgroundActivity, control_alive: bool, expected_active: bool
) -> None:
    user = User(id=uuid4(), email="reader@example.com")
    chat = ChatSession(id=uuid4(), user_id=user.id)
    cache = FakeCache()
    if control_alive:
        cache.set(f"{BACKGROUND_CONTROL_PREFIX}12", 1)
    background_tasks = BackgroundTasks()
    with (
        patch(
            "onyx.server.query_and_chat.chat_backend.get_session_with_current_tenant"
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.get_chat_session_by_id",
            return_value=chat,
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.get_cache_backend",
            return_value=cache,
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.read_chat_background_activity",
            side_effect=[
                ChatBackgroundActivity(
                    latest_response_id=12, running_response_ids=[11]
                ),
                refreshed,
            ],
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.active_response_ids",
            return_value=set(),
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.get_processing_stream_id",
            return_value=None,
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.is_chat_session_processing",
            return_value=False,
        ),
    ):
        status = get_chat_session_processing_status(
            chat.id, background_tasks=background_tasks, user=user
        )
    assert status.has_active_subagents is expected_active
    assert status.latest_response_id == refreshed.latest_response_id
    assert bool(background_tasks.tasks) is refreshed.has_pending_root_results
