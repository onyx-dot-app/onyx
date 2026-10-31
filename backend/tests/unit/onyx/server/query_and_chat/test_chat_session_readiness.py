from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.query_and_chat.chat_backend import get_chat_session_processing_status


@pytest.mark.parametrize("processing", [False, True])
def test_status_checks_session_access_before_processing(processing: bool) -> None:
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
            "onyx.server.query_and_chat.chat_backend.is_chat_session_processing",
            return_value=processing,
        ) as check,
    ):
        response = get_chat_session_processing_status(session_id, user=user)
    lookup.assert_called_once_with(
        chat_session_id=session_id,
        user_id=user.id,
        db_session=database.return_value.__enter__.return_value,
    )
    check.assert_called_once_with(session_id, cache)
    assert response.is_processing is processing


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
        get_chat_session_processing_status(uuid4(), user=User(id=uuid4()))
    assert error.value.error_code == OnyxErrorCode.SESSION_NOT_FOUND
    cache.assert_not_called()


def test_status_does_not_report_idle_when_cache_fails() -> None:
    with (
        patch(
            "onyx.server.query_and_chat.chat_backend.get_session_with_current_tenant"
        ),
        patch("onyx.server.query_and_chat.chat_backend.get_chat_session_by_id"),
        patch(
            "onyx.server.query_and_chat.chat_backend.get_cache_backend",
            side_effect=ConnectionError,
        ),
        pytest.raises(ConnectionError),
    ):
        get_chat_session_processing_status(uuid4(), user=User(id=uuid4()))
