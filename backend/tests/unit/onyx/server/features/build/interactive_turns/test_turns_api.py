from __future__ import annotations

import time as real_time
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import cast
from uuid import UUID
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.interactive_turns import api as turns_api
from onyx.server.features.build.interactive_turns.state import claim_turn_for_runner
from onyx.server.features.build.interactive_turns.state import create_interactive_turn
from onyx.server.features.build.interactive_turns.state import finish_turn
from onyx.server.features.build.interactive_turns.state import TURN_STATUS_FAILED
from onyx.server.features.build.interactive_turns.state import TURN_STATUS_SUCCEEDED
from tests.unit.fakes import FakeCache


class _FakeStreamingResponse:
    def __init__(
        self,
        body: Iterator[str],
        media_type: str,
        headers: dict[str, str],
    ) -> None:
        self.body = body
        self.media_type = media_type
        self.headers = headers


class _FakeDbSession:
    def __init__(self) -> None:
        self.expire_all_calls = 0

    def expire_all(self) -> None:
        self.expire_all_calls += 1


@contextmanager
def _fake_db_session_scope() -> Iterator[_FakeDbSession]:
    yield _FakeDbSession()


def _create_running_turn(
    cache: FakeCache,
    *,
    session_id: UUID,
    user_id: UUID,
) -> UUID:
    turn = create_interactive_turn(
        cache=cache,
        session_id=session_id,
        user_id=user_id,
        client_request_id="req-1",
        prompt="hello",
        turn_index=3,
    )
    claim_turn_for_runner(cache=cache, turn_id=turn.turn_id)
    return turn.turn_id


def test_get_active_interactive_turn_returns_cache_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    user_id = uuid4()
    turn_id = _create_running_turn(cache, session_id=session_id, user_id=user_id)

    monkeypatch.setattr(turns_api, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(turns_api, "start_interactive_turn_runner", lambda _: False)
    monkeypatch.setattr(
        turns_api,
        "get_build_session",
        lambda *_: SimpleNamespace(id=session_id),
    )

    response = turns_api.get_active_interactive_turn(
        session_id=session_id,
        user=cast(User, SimpleNamespace(id=user_id)),
        db_session=cast(Session, SimpleNamespace()),
    )

    assert response is not None
    assert response.turn_id == str(turn_id)
    assert response.status == "RUNNING"
    assert response.turn_index == 3


def test_get_interactive_turn_events_waits_then_forwards_live_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    user_id = uuid4()
    turn_id = _create_running_turn(cache, session_id=session_id, user_id=user_id)
    started: list[UUID] = []
    session_rows = iter(
        [
            SimpleNamespace(id=session_id, opencode_session_id=None),
            SimpleNamespace(id=session_id, opencode_session_id=None),
            SimpleNamespace(id=session_id, opencode_session_id="opencode-1"),
        ]
    )

    class FakeSessionManager:
        def __init__(self, db_session: object) -> None:
            _ = db_session

        def subscribe_to_existing_session_events(
            self,
            session_id_arg: UUID,
            user_id_arg: UUID,
            keepalive_seconds: float,
        ) -> Iterator[str]:
            assert session_id_arg == session_id
            assert user_id_arg == user_id
            assert keepalive_seconds == turns_api.LIVE_STREAM_KEEPALIVE_SECONDS
            finish_turn(
                cache=cache,
                turn_id=turn_id,
                status=TURN_STATUS_SUCCEEDED,
            )
            yield 'event: message\ndata: {"type":"text_chunk","text":"hi"}\n\n'
            yield 'event: message\ndata: {"type":"text_chunk","text":"bye"}\n\n'

    monkeypatch.setattr(turns_api, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(
        turns_api,
        "start_interactive_turn_runner",
        lambda turn_id_arg: started.append(turn_id_arg) or False,
    )
    monkeypatch.setattr(turns_api, "StreamingResponse", _FakeStreamingResponse)
    monkeypatch.setattr(
        turns_api,
        "time",
        SimpleNamespace(sleep=lambda _: None, monotonic=real_time.monotonic),
    )
    monkeypatch.setattr(turns_api, "SessionManager", FakeSessionManager)
    monkeypatch.setattr(
        turns_api,
        "get_session_with_current_tenant",
        _fake_db_session_scope,
    )
    monkeypatch.setattr(turns_api, "get_build_session", lambda *_: next(session_rows))

    response = cast(
        _FakeStreamingResponse,
        turns_api.get_interactive_turn_events(
            session_id=session_id,
            turn_id=turn_id,
            user=cast(User, SimpleNamespace(id=user_id)),
            db_session=cast(Session, SimpleNamespace()),
        ),
    )

    chunks = list(response.body)

    assert chunks == [
        turns_api.SSE_KEEPALIVE,
        'event: message\ndata: {"type":"text_chunk","text":"hi"}\n\n',
        'event: message\ndata: {"type":"text_chunk","text":"bye"}\n\n',
    ]
    assert started == [turn_id]


def test_get_interactive_turn_events_streams_retained_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    user_id = uuid4()
    turn_id = _create_running_turn(cache, session_id=session_id, user_id=user_id)
    finish_turn(
        cache=cache,
        turn_id=turn_id,
        status=TURN_STATUS_FAILED,
        error_detail="provider model not found",
    )

    monkeypatch.setattr(turns_api, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(turns_api, "start_interactive_turn_runner", lambda _: False)
    monkeypatch.setattr(turns_api, "StreamingResponse", _FakeStreamingResponse)
    monkeypatch.setattr(
        turns_api,
        "get_build_session",
        lambda *_: SimpleNamespace(id=session_id),
    )

    response = cast(
        _FakeStreamingResponse,
        turns_api.get_interactive_turn_events(
            session_id=session_id,
            turn_id=turn_id,
            user=cast(User, SimpleNamespace(id=user_id)),
            db_session=cast(Session, SimpleNamespace()),
        ),
    )

    chunks = list(response.body)

    assert len(chunks) == 1
    assert '"type": "error"' in chunks[0]
    assert '"message": "provider model not found"' in chunks[0]


def test_get_interactive_turn_events_yields_failed_turn_error_before_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    user_id = uuid4()
    turn_id = _create_running_turn(cache, session_id=session_id, user_id=user_id)

    monkeypatch.setattr(turns_api, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(turns_api, "start_interactive_turn_runner", lambda _: False)
    monkeypatch.setattr(turns_api, "StreamingResponse", _FakeStreamingResponse)
    monkeypatch.setattr(
        turns_api,
        "time",
        SimpleNamespace(sleep=lambda _: None, monotonic=real_time.monotonic),
    )
    monkeypatch.setattr(
        turns_api,
        "get_session_with_current_tenant",
        _fake_db_session_scope,
    )
    monkeypatch.setattr(
        turns_api,
        "get_build_session",
        lambda *_: SimpleNamespace(id=session_id, opencode_session_id=None),
    )

    response = cast(
        _FakeStreamingResponse,
        turns_api.get_interactive_turn_events(
            session_id=session_id,
            turn_id=turn_id,
            user=cast(User, SimpleNamespace(id=user_id)),
            db_session=cast(Session, SimpleNamespace()),
        ),
    )

    chunks = response.body
    assert next(chunks) == turns_api.SSE_KEEPALIVE

    finish_turn(
        cache=cache,
        turn_id=turn_id,
        status=TURN_STATUS_FAILED,
        error_detail="provider model not found",
    )

    error_chunk = next(chunks)
    assert '"type": "error"' in error_chunk
    assert '"message": "provider model not found"' in error_chunk

    with pytest.raises(StopIteration):
        next(chunks)


def test_get_interactive_turn_events_yields_failed_turn_error_after_stream_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    user_id = uuid4()
    turn_id = _create_running_turn(cache, session_id=session_id, user_id=user_id)

    class FakeSessionManager:
        def __init__(self, db_session: object) -> None:
            _ = db_session

        def subscribe_to_existing_session_events(
            self,
            session_id_arg: UUID,
            user_id_arg: UUID,
            keepalive_seconds: float,
        ) -> Iterator[str]:
            assert session_id_arg == session_id
            assert user_id_arg == user_id
            assert keepalive_seconds == turns_api.LIVE_STREAM_KEEPALIVE_SECONDS
            finish_turn(
                cache=cache,
                turn_id=turn_id,
                status=TURN_STATUS_FAILED,
                error_detail="provider model not found",
            )
            yield 'event: message\ndata: {"type":"text_chunk","text":"partial"}\n\n'

    monkeypatch.setattr(turns_api, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(turns_api, "start_interactive_turn_runner", lambda _: False)
    monkeypatch.setattr(turns_api, "StreamingResponse", _FakeStreamingResponse)
    monkeypatch.setattr(turns_api, "SessionManager", FakeSessionManager)
    monkeypatch.setattr(
        turns_api,
        "get_session_with_current_tenant",
        _fake_db_session_scope,
    )
    monkeypatch.setattr(
        turns_api,
        "get_build_session",
        lambda *_: SimpleNamespace(id=session_id, opencode_session_id="opencode-1"),
    )

    response = turns_api.get_interactive_turn_events(
        session_id=session_id,
        turn_id=turn_id,
        user=cast(User, SimpleNamespace(id=user_id)),
        db_session=cast(Session, SimpleNamespace()),
    )

    chunks = list(response.body)

    assert chunks[0] == (
        'event: message\ndata: {"type":"text_chunk","text":"partial"}\n\n'
    )
    assert '"type": "error"' in chunks[1]
    assert '"message": "provider model not found"' in chunks[1]
    assert len(chunks) == 2


def test_get_interactive_turn_events_requires_active_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    user_id = uuid4()

    monkeypatch.setattr(turns_api, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(turns_api, "start_interactive_turn_runner", lambda _: False)
    monkeypatch.setattr(
        turns_api,
        "get_build_session",
        lambda *_: SimpleNamespace(id=session_id),
    )

    with pytest.raises(OnyxError):
        turns_api.get_interactive_turn_events(
            session_id=session_id,
            turn_id=uuid4(),
            user=cast(User, SimpleNamespace(id=user_id)),
            db_session=cast(Session, SimpleNamespace()),
        )
