from collections.abc import Callable
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


def _setup(
    monkeypatch: pytest.MonkeyPatch, chat_session: SimpleNamespace
) -> tuple[MagicMock, Callable[[str | None], None]]:
    """Patch the session lookup and return (mock db session, endpoint invoker)."""
    db_session = MagicMock()
    monkeypatch.setattr(
        "onyx.server.query_and_chat.chat_backend.get_chat_session_by_id",
        lambda **_: chat_session,
    )

    def call(override: str | None) -> None:
        update_chat_session_reasoning(
            UpdateChatSessionReasoningRequest(
                chat_session_id=uuid4(), reasoning_effort_override=override
            ),
            user=cast(User, SimpleNamespace(id=uuid4())),
            db_session=db_session,
        )

    return db_session, call


@pytest.mark.parametrize("invalid_override", ["auto", "bogus"])
def test_update_chat_session_reasoning_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    invalid_override: str,
) -> None:
    chat_session = SimpleNamespace(reasoning_effort_override="medium")
    db_session, call = _setup(monkeypatch, chat_session)

    with pytest.raises(OnyxError) as exc:
        call(invalid_override)

    assert exc.value.error_code is OnyxErrorCode.INVALID_INPUT
    assert chat_session.reasoning_effort_override == "medium"
    db_session.add.assert_not_called()
    db_session.commit.assert_not_called()


def test_update_chat_session_reasoning_writes_valid_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_session = SimpleNamespace(reasoning_effort_override=None)
    db_session, call = _setup(monkeypatch, chat_session)

    call("high")

    assert chat_session.reasoning_effort_override == "high"
    db_session.add.assert_called_once_with(chat_session)
    db_session.commit.assert_called_once()


def test_update_chat_session_reasoning_clears_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_session = SimpleNamespace(reasoning_effort_override="off")
    db_session, call = _setup(monkeypatch, chat_session)

    call(None)

    assert chat_session.reasoning_effort_override is None
    db_session.add.assert_called_once_with(chat_session)
    db_session.commit.assert_called_once()
