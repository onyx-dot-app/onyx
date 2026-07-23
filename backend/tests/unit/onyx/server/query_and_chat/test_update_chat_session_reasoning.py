from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.query_and_chat.chat_backend import update_chat_session_reasoning
from onyx.server.query_and_chat.models import UpdateChatSessionReasoningRequest


def test_update_chat_session_reasoning_rejects_auto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_session = SimpleNamespace(reasoning_effort_override="medium")
    db_session = MagicMock()
    user = cast(User, SimpleNamespace(id=uuid4()))

    monkeypatch.setattr(
        "onyx.server.query_and_chat.chat_backend.get_chat_session_by_id",
        lambda **_: chat_session,
    )

    with pytest.raises(OnyxError) as exc:
        update_chat_session_reasoning(
            UpdateChatSessionReasoningRequest(
                chat_session_id=uuid4(), reasoning_effort_override="auto"
            ),
            user=user,
            db_session=db_session,
        )

    assert exc.value.error_code is OnyxErrorCode.INVALID_INPUT
    assert chat_session.reasoning_effort_override == "medium"
    db_session.add.assert_not_called()
    db_session.commit.assert_not_called()


def test_update_chat_session_reasoning_rejects_unknown_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_session = SimpleNamespace(reasoning_effort_override="low")
    db_session = MagicMock()
    user = cast(User, SimpleNamespace(id=uuid4()))

    monkeypatch.setattr(
        "onyx.server.query_and_chat.chat_backend.get_chat_session_by_id",
        lambda **_: chat_session,
    )

    with pytest.raises(OnyxError) as exc:
        update_chat_session_reasoning(
            UpdateChatSessionReasoningRequest(
                chat_session_id=uuid4(), reasoning_effort_override="bogus"
            ),
            user=user,
            db_session=db_session,
        )

    assert exc.value.error_code is OnyxErrorCode.INVALID_INPUT
    assert chat_session.reasoning_effort_override == "low"
    db_session.add.assert_not_called()
    db_session.commit.assert_not_called()


def test_update_chat_session_reasoning_writes_valid_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_session = SimpleNamespace(reasoning_effort_override=None)
    db_session = MagicMock()
    user = cast(User, SimpleNamespace(id=uuid4()))

    monkeypatch.setattr(
        "onyx.server.query_and_chat.chat_backend.get_chat_session_by_id",
        lambda **_: chat_session,
    )

    update_chat_session_reasoning(
        UpdateChatSessionReasoningRequest(
            chat_session_id=uuid4(), reasoning_effort_override="high"
        ),
        user=user,
        db_session=db_session,
    )

    assert chat_session.reasoning_effort_override == "high"
    db_session.add.assert_called_once_with(chat_session)
    db_session.commit.assert_called_once()


def test_update_chat_session_reasoning_clears_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_session = SimpleNamespace(reasoning_effort_override="off")
    db_session = MagicMock()
    user = cast(User, SimpleNamespace(id=uuid4()))

    monkeypatch.setattr(
        "onyx.server.query_and_chat.chat_backend.get_chat_session_by_id",
        lambda **_: chat_session,
    )

    update_chat_session_reasoning(
        UpdateChatSessionReasoningRequest(
            chat_session_id=uuid4(), reasoning_effort_override=None
        ),
        user=user,
        db_session=db_session,
    )

    assert chat_session.reasoning_effort_override is None
    db_session.add.assert_called_once_with(chat_session)
    db_session.commit.assert_called_once()
