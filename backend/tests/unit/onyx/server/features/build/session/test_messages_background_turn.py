from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import UUID
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.session import messages as messages_api
from onyx.server.features.build.session.models import MessageRequest
from tests.unit.fakes import FakeCache


class _FakeQuery:
    def __init__(self, count: int) -> None:
        self._count = count

    def filter(self, *args: object) -> "_FakeQuery":
        _ = args
        return self

    def count(self) -> int:
        return self._count


class _FakeDbSession:
    def __init__(self, user_message_count: int) -> None:
        self.user_message_count = user_message_count
        self.commits = 0
        self.rollbacks = 0

    def query(self, model: object) -> _FakeQuery:
        _ = model
        return _FakeQuery(self.user_message_count)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _create_message_noop(**_: object) -> None:
    return None


def test_send_message_starts_background_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = FakeCache()
    session_id = uuid4()
    user_id = uuid4()
    session = SimpleNamespace(
        id=session_id,
    )
    db_session = _FakeDbSession(user_message_count=2)
    persisted: list[tuple[int, str]] = []
    start_runner = MagicMock()

    def get_session_stub(*_: object, **__: object) -> SimpleNamespace:
        return session

    def create_message_stub(
        *,
        turn_index: int,
        message_metadata: dict[str, object],
        **_: object,
    ) -> None:
        content = cast(dict[str, str], message_metadata["content"])
        persisted.append((turn_index, content["text"]))

    monkeypatch.setattr(messages_api, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(messages_api, "get_build_session", get_session_stub)
    monkeypatch.setattr(messages_api, "check_build_rate_limits", lambda **_: None)
    monkeypatch.setattr(
        messages_api,
        "create_message",
        create_message_stub,
    )
    monkeypatch.setattr(
        messages_api,
        "start_interactive_turn_runner",
        start_runner,
    )

    response = messages_api.send_message(
        session_id=session_id,
        request=MessageRequest(
            content="hello",
            client_request_id="req-1",
            provider="openai",
            model="gpt-5-mini",
        ),
        user=cast(User, SimpleNamespace(id=user_id)),
        db_session=cast(Session, db_session),
    )

    assert response.session_id == str(session_id)
    assert response.status == "QUEUED"
    assert response.turn_index == 2
    assert persisted == [(2, "hello")]
    assert session.agent_provider == "openai"
    assert session.agent_model == "gpt-5-mini"
    assert db_session.commits == 1
    start_runner.assert_called_once()
    assert str(start_runner.call_args.args[0]) == response.turn_id


def test_send_message_rejects_second_active_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    user_id = uuid4()
    session = SimpleNamespace(id=session_id)

    def get_session_stub(*_: object, **__: object) -> SimpleNamespace:
        return session

    monkeypatch.setattr(messages_api, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(messages_api, "get_build_session", get_session_stub)
    monkeypatch.setattr(messages_api, "check_build_rate_limits", lambda **_: None)
    monkeypatch.setattr(messages_api, "create_message", _create_message_noop)
    monkeypatch.setattr(messages_api, "start_interactive_turn_runner", MagicMock())

    first = messages_api.send_message(
        session_id=session_id,
        request=MessageRequest(content="hello", client_request_id="req-1"),
        user=cast(User, SimpleNamespace(id=user_id)),
        db_session=cast(Session, _FakeDbSession(user_message_count=0)),
    )
    assert first.status == "QUEUED"

    with pytest.raises(OnyxError):
        messages_api.send_message(
            session_id=session_id,
            request=MessageRequest(content="again", client_request_id="req-2"),
            user=cast(User, SimpleNamespace(id=user_id)),
            db_session=cast(Session, _FakeDbSession(user_message_count=1)),
        )


def test_send_message_is_idempotent_for_same_client_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    user_id = uuid4()
    session = SimpleNamespace(id=session_id)
    persisted: list[tuple[int, str]] = []
    start_runner = MagicMock()
    rate_limit_check = MagicMock()

    def get_session_stub(*_: object, **__: object) -> SimpleNamespace:
        return session

    def create_message_stub(
        *,
        turn_index: int,
        message_metadata: dict[str, object],
        **_: object,
    ) -> None:
        content = cast(dict[str, str], message_metadata["content"])
        persisted.append((turn_index, content["text"]))

    monkeypatch.setattr(messages_api, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(messages_api, "get_build_session", get_session_stub)
    monkeypatch.setattr(messages_api, "check_build_rate_limits", rate_limit_check)
    monkeypatch.setattr(
        messages_api,
        "create_message",
        create_message_stub,
    )
    monkeypatch.setattr(
        messages_api,
        "start_interactive_turn_runner",
        start_runner,
    )

    first = messages_api.send_message(
        session_id=session_id,
        request=MessageRequest(content="hello", client_request_id="req-1"),
        user=cast(User, SimpleNamespace(id=user_id)),
        db_session=cast(Session, _FakeDbSession(user_message_count=0)),
    )
    same = messages_api.send_message(
        session_id=session_id,
        request=MessageRequest(content="hello", client_request_id="req-1"),
        user=cast(User, SimpleNamespace(id=user_id)),
        db_session=cast(Session, _FakeDbSession(user_message_count=1)),
    )

    assert same.turn_id == first.turn_id
    assert persisted == [(0, "hello")]
    start_runner.assert_called_once()
    rate_limit_check.assert_called_once()


def test_send_message_leaves_turn_active_if_runner_cannot_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    user_id = uuid4()
    session = SimpleNamespace(id=session_id)

    def get_session_stub(*_: object, **__: object) -> SimpleNamespace:
        return session

    def start_runner_stub(_: object) -> None:
        raise RuntimeError("capacity exhausted")

    monkeypatch.setattr(messages_api, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(messages_api, "get_build_session", get_session_stub)
    monkeypatch.setattr(messages_api, "check_build_rate_limits", lambda **_: None)
    monkeypatch.setattr(messages_api, "create_message", _create_message_noop)
    monkeypatch.setattr(
        messages_api,
        "start_interactive_turn_runner",
        start_runner_stub,
    )

    response = messages_api.send_message(
        session_id=session_id,
        request=MessageRequest(content="hello", client_request_id="req-1"),
        user=cast(User, SimpleNamespace(id=user_id)),
        db_session=cast(Session, _FakeDbSession(user_message_count=0)),
    )

    active = messages_api.get_active_turn(
        cache=cache,
        session_id=session_id,
        user_id=user_id,
    )
    assert response.status == "QUEUED"
    assert active is not None
    assert active.turn_id == UUID(response.turn_id)
