from __future__ import annotations

import json
import time as real_time
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.interactive_turns import api as turns_api
from onyx.server.features.build.interactive_turns.state import (
    TURN_STATUS_CANCELLED,
    TURN_STATUS_FAILED,
    TURN_STATUS_SUCCEEDED,
    InteractiveTurnStatus,
    claim_turn_for_runner,
    create_interactive_turn,
    finish_turn,
)
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


@pytest.fixture(autouse=True)
def _short_database_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        turns_api, "get_session_with_current_tenant", _fake_db_session_scope
    )


def _running_sandbox(*_args: object, **_kwargs: object) -> SimpleNamespace:
    """The wait loop consults the sandbox as well as the session; most tests
    are about the session half, so hand them a live runtime."""
    return SimpleNamespace(id=uuid4(), status=SandboxStatus.RUNNING)


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
    monkeypatch.setattr(turns_api, "get_sandbox_by_user_id", _running_sandbox)

    response = turns_api.get_active_interactive_turn(
        session_id=session_id,
        user=cast(User, SimpleNamespace(id=user_id)),
        db_session=cast(Session, _FakeDbSession()),
    )

    assert response is not None
    assert response.turn_id == str(turn_id)
    assert response.status == "RUNNING"
    assert response.turn_index == 3


@pytest.mark.parametrize(
    "next_chunk",
    [
        'event: message\ndata: {"type":"text_chunk","text":"successor"}\n\n',
        turns_api.SSE_KEEPALIVE,
    ],
)
def test_stream_stops_before_forwarding_events_after_committed_completion(
    monkeypatch: pytest.MonkeyPatch,
    next_chunk: str,
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
            yield next_chunk
            pytest.fail("A terminal turn must stop before successor output")

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
    monkeypatch.setattr(turns_api, "get_sandbox_by_user_id", _running_sandbox)

    response = cast(
        _FakeStreamingResponse,
        turns_api.get_interactive_turn_events(
            session_id=session_id,
            turn_id=turn_id,
            user=cast(User, SimpleNamespace(id=user_id)),
        ),
    )
    monkeypatch.setattr(turns_api, "get_sandbox_by_user_id", _running_sandbox)

    chunks = list(response.body)

    assert json.loads(chunks[-1].split("data: ", 1)[1])["type"] == "turn_completed"
    assert chunks[:-1] == [
        turns_api.SSE_KEEPALIVE,
    ]
    assert started == [turn_id]


@pytest.mark.parametrize(
    "status", [TURN_STATUS_SUCCEEDED, TURN_STATUS_CANCELLED, TURN_STATUS_FAILED]
)
def test_get_interactive_turn_events_streams_retained_completion(
    monkeypatch: pytest.MonkeyPatch,
    status: InteractiveTurnStatus,
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    user_id = uuid4()
    turn_id = _create_running_turn(cache, session_id=session_id, user_id=user_id)
    finish_turn(
        cache=cache,
        turn_id=turn_id,
        status=status,
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
    monkeypatch.setattr(turns_api, "get_sandbox_by_user_id", _running_sandbox)

    response = cast(
        _FakeStreamingResponse,
        turns_api.get_interactive_turn_events(
            session_id=session_id,
            turn_id=turn_id,
            user=cast(User, SimpleNamespace(id=user_id)),
        ),
    )

    chunks = list(response.body)

    assert len(chunks) == 1
    packet = json.loads(chunks[0].split("data: ", 1)[1])
    assert packet["type"] == "turn_completed"
    assert packet["status"] == status
    assert packet["turn_id"] == str(turn_id)
    assert packet["error_detail"] == "provider model not found"


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
    monkeypatch.setattr(turns_api, "get_sandbox_by_user_id", _running_sandbox)

    response = cast(
        _FakeStreamingResponse,
        turns_api.get_interactive_turn_events(
            session_id=session_id,
            turn_id=turn_id,
            user=cast(User, SimpleNamespace(id=user_id)),
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
    packet = json.loads(error_chunk.split("data: ", 1)[1])
    assert packet["type"] == "turn_completed"
    assert packet["status"] == "FAILED"
    assert packet["error_detail"] == "provider model not found"

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
            yield 'event: message\ndata: {"type":"text_chunk","text":"partial"}\n\n'
            finish_turn(
                cache=cache,
                turn_id=turn_id,
                status=TURN_STATUS_FAILED,
                error_detail="provider model not found",
            )

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
    monkeypatch.setattr(turns_api, "get_sandbox_by_user_id", _running_sandbox)

    response = turns_api.get_interactive_turn_events(
        session_id=session_id,
        turn_id=turn_id,
        user=cast(User, SimpleNamespace(id=user_id)),
    )

    chunks = list(response.body)

    assert chunks[0] == (
        'event: message\ndata: {"type":"text_chunk","text":"partial"}\n\n'
    )
    packet = json.loads(chunks[1].split("data: ", 1)[1])
    assert packet["type"] == "turn_completed"
    assert packet["status"] == "FAILED"
    assert packet["error_detail"] == "provider model not found"
    assert len(chunks) == 2


def test_get_interactive_turn_events_retries_runner_start_mid_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    user_id = uuid4()
    turn_id = _create_running_turn(cache, session_id=session_id, user_id=user_id)
    started: list[UUID] = []

    fake_monotonic_value = [0.0]

    def fake_monotonic() -> float:
        fake_monotonic_value[0] += turns_api.LIVE_STREAM_RUNNER_RETRY_SECONDS + 1.0
        return fake_monotonic_value[0]

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
            for i in range(3):
                yield (
                    "event: message\n"
                    f'data: {{"type":"text_chunk","text":"chunk-{i}"}}\n\n'
                )

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
        SimpleNamespace(sleep=lambda _: None, monotonic=fake_monotonic),
    )
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
    monkeypatch.setattr(turns_api, "get_sandbox_by_user_id", _running_sandbox)

    response = cast(
        _FakeStreamingResponse,
        turns_api.get_interactive_turn_events(
            session_id=session_id,
            turn_id=turn_id,
            user=cast(User, SimpleNamespace(id=user_id)),
        ),
    )

    chunks = list(response.body)

    assert len(chunks) == 3
    assert len(started) >= 2
    assert started[0] == turn_id


def test_get_interactive_turn_events_rate_limits_runner_retry_within_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    user_id = uuid4()
    turn_id = _create_running_turn(cache, session_id=session_id, user_id=user_id)
    started: list[UUID] = []

    fake_monotonic_value = [0.0]

    def fake_monotonic() -> float:
        fake_monotonic_value[0] += 0.01
        return fake_monotonic_value[0]

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
            for i in range(3):
                yield (
                    "event: message\n"
                    f'data: {{"type":"text_chunk","text":"chunk-{i}"}}\n\n'
                )

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
        SimpleNamespace(sleep=lambda _: None, monotonic=fake_monotonic),
    )
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
    monkeypatch.setattr(turns_api, "get_sandbox_by_user_id", _running_sandbox)

    response = cast(
        _FakeStreamingResponse,
        turns_api.get_interactive_turn_events(
            session_id=session_id,
            turn_id=turn_id,
            user=cast(User, SimpleNamespace(id=user_id)),
        ),
    )

    chunks = list(response.body)

    assert len(chunks) == 3
    assert started == [turn_id]


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
    monkeypatch.setattr(turns_api, "get_sandbox_by_user_id", _running_sandbox)

    with pytest.raises(OnyxError):
        turns_api.get_interactive_turn_events(
            session_id=session_id,
            turn_id=uuid4(),
            user=cast(User, SimpleNamespace(id=user_id)),
        )


def test_get_interactive_turn_events_waits_out_a_reclaimed_sandbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sandbox reclaimed between turns must not fail the next message.

    ``opencode_session_id`` outlives the pod that minted it, so after a reap the
    session still carries one while nothing is listening. Treating that alone as
    "ready" attached to a sandbox that was still provisioning and surfaced
    "Sandbox is not running" — for a turn whose own runner was, at that moment,
    waking the sandbox. The stream has to hold the line instead.
    """
    cache = FakeCache()
    session_id = uuid4()
    user_id = uuid4()
    turn_id = _create_running_turn(cache, session_id=session_id, user_id=user_id)

    # The id is set from the previous incarnation the whole time.
    session_row = SimpleNamespace(id=session_id, opencode_session_id="opencode-stale")
    sandbox_states = iter(
        [
            SimpleNamespace(id=uuid4(), status=SandboxStatus.SLEEPING),
            SimpleNamespace(id=uuid4(), status=SandboxStatus.PROVISIONING),
            SimpleNamespace(id=uuid4(), status=SandboxStatus.RUNNING),
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
            _ = (session_id_arg, user_id_arg, keepalive_seconds)
            yield 'event: message\ndata: {"type":"text_chunk","text":"awake"}\n\n'
            finish_turn(cache=cache, turn_id=turn_id, status=TURN_STATUS_SUCCEEDED)

    monkeypatch.setattr(turns_api, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(turns_api, "start_interactive_turn_runner", lambda _: False)
    monkeypatch.setattr(turns_api, "StreamingResponse", _FakeStreamingResponse)
    monkeypatch.setattr(
        turns_api,
        "time",
        SimpleNamespace(sleep=lambda _: None, monotonic=real_time.monotonic),
    )
    monkeypatch.setattr(turns_api, "SessionManager", FakeSessionManager)
    monkeypatch.setattr(
        turns_api, "get_session_with_current_tenant", _fake_db_session_scope
    )
    monkeypatch.setattr(turns_api, "get_build_session", lambda *_: session_row)
    monkeypatch.setattr(
        turns_api, "get_sandbox_by_user_id", lambda *_: next(sandbox_states)
    )

    response = cast(
        _FakeStreamingResponse,
        turns_api.get_interactive_turn_events(
            session_id=session_id,
            turn_id=turn_id,
            user=cast(User, SimpleNamespace(id=user_id)),
        ),
    )

    chunks = list(response.body)

    # Two keepalives while the sandbox came back, then the turn's output — and
    # no error packet anywhere.
    assert json.loads(chunks[-1].split("data: ", 1)[1])["type"] == "turn_completed"
    assert chunks[:-1] == [
        turns_api.SSE_KEEPALIVE,
        turns_api.SSE_KEEPALIVE,
        'event: message\ndata: {"type":"text_chunk","text":"awake"}\n\n',
    ]


@pytest.mark.parametrize("failed", [False, True])
def test_known_turn_returns_terminal_outcome_after_active_marker_clears(
    monkeypatch: pytest.MonkeyPatch, failed: bool
) -> None:
    cache = FakeCache()
    session_id, user_id = uuid4(), uuid4()
    turn_id = _create_running_turn(cache, session_id=session_id, user_id=user_id)
    finish_turn(
        cache=cache,
        turn_id=turn_id,
        status=TURN_STATUS_FAILED if failed else TURN_STATUS_SUCCEEDED,
        error_detail="provider failed" if failed else None,
    )
    monkeypatch.setattr(turns_api, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(
        turns_api, "get_build_session", lambda *_: SimpleNamespace(id=session_id)
    )
    user = cast(User, SimpleNamespace(id=user_id))
    db = cast(Session, _FakeDbSession())
    assert turns_api.get_active_interactive_turn(session_id, user, db) is None
    outcome = turns_api.get_interactive_turn(session_id, turn_id, user, db)
    assert outcome is not None
    assert outcome.status == ("FAILED" if failed else "SUCCEEDED")
    assert outcome.error_detail == ("provider failed" if failed else None)
    assert turns_api.get_interactive_turn(uuid4(), turn_id, user, db) is None
    assert (
        turns_api.get_interactive_turn(
            session_id, turn_id, cast(User, SimpleNamespace(id=uuid4())), db
        )
        is None
    )
    assert turns_api.get_interactive_turn(session_id, uuid4(), user, db) is None


@pytest.mark.parametrize("terminal_type", ["prompt_response", "error"])
@pytest.mark.parametrize("outcome", ["complete", "timeout", "disconnect"])
def test_completion_waits_for_persistence_and_closes_live_subscription(
    monkeypatch: pytest.MonkeyPatch, terminal_type: str, outcome: str
) -> None:
    cache = FakeCache()
    session_id, user_id = uuid4(), uuid4()
    turn_id = _create_running_turn(cache, session_id=session_id, user_id=user_id)
    live_closed: list[bool] = []
    open_db_scopes: list[bool] = []

    @contextmanager
    def database_scope() -> Iterator[_FakeDbSession]:
        open_db_scopes.append(True)
        try:
            yield _FakeDbSession()
        finally:
            open_db_scopes.pop()

    class FakeSessionManager:
        def __init__(self, db_session: object) -> None:
            pass

        def subscribe_to_existing_session_events(
            self, *_: object, **__: object
        ) -> Iterator[str]:
            try:
                yield 'event: message\ndata: {"type":"text_chunk","text":"answer"}\n\n'
                yield f'event: message\ndata: {{"type":"{terminal_type}"}}\n\n'
                pytest.fail("A completed stream must not consume a successor's events")
            finally:
                live_closed.append(True)

    sleeps: list[float] = []
    clock = [0.0]

    def complete_after_wait(seconds: float) -> None:
        assert live_closed
        assert not open_db_scopes
        sleeps.append(seconds)
        clock[0] += turns_api.TURN_COMPLETION_WAIT_SECONDS
        if outcome == "complete":
            finish_turn(cache=cache, turn_id=turn_id, status=TURN_STATUS_SUCCEEDED)

    monkeypatch.setattr(turns_api, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(turns_api, "start_interactive_turn_runner", lambda _: False)
    monkeypatch.setattr(turns_api, "StreamingResponse", _FakeStreamingResponse)
    monkeypatch.setattr(turns_api, "SessionManager", FakeSessionManager)
    monkeypatch.setattr(turns_api, "get_session_with_current_tenant", database_scope)
    monkeypatch.setattr(
        turns_api,
        "get_build_session",
        lambda *_: SimpleNamespace(id=session_id, opencode_session_id="opencode-1"),
    )
    monkeypatch.setattr(turns_api, "get_sandbox_by_user_id", _running_sandbox)
    monkeypatch.setattr(
        turns_api,
        "time",
        SimpleNamespace(sleep=complete_after_wait, monotonic=lambda: clock[0]),
    )
    response = cast(
        _FakeStreamingResponse,
        turns_api.get_interactive_turn_events(
            session_id, turn_id, cast(User, SimpleNamespace(id=user_id))
        ),
    )
    if outcome == "disconnect":
        stream = cast(Generator[str, None, None], response.body)
        next(stream)
        assert next(stream) == turns_api.SSE_KEEPALIVE
        stream.close()
        assert live_closed
        assert not open_db_scopes
        assert not sleeps
        return
    chunks = list(response.body)
    if outcome == "timeout":
        assert len(chunks) == 2
        assert chunks[-1] == turns_api.SSE_KEEPALIVE
        assert live_closed
        assert not open_db_scopes
        return
    assert len(chunks) == 3
    assert chunks[1] == turns_api.SSE_KEEPALIVE
    assert sleeps == [turns_api.TURN_COMPLETION_CHECK_SECONDS]
    packet = json.loads(chunks[-1].split("data: ", 1)[1])
    assert packet == {
        "type": "turn_completed",
        "session_id": str(session_id),
        "turn_id": str(turn_id),
        "turn_index": 3,
        "status": "SUCCEEDED",
        "error_detail": None,
    }


@pytest.mark.parametrize("mismatch", ["session", "user"])
def test_terminal_stream_replay_checks_turn_ownership(
    monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    cache = FakeCache()
    session_id, user_id = uuid4(), uuid4()
    turn_id = _create_running_turn(cache, session_id=session_id, user_id=user_id)
    finish_turn(cache=cache, turn_id=turn_id, status=TURN_STATUS_SUCCEEDED)
    monkeypatch.setattr(turns_api, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(
        turns_api, "get_build_session", lambda *_: SimpleNamespace(id=session_id)
    )
    with pytest.raises(OnyxError):
        turns_api.get_interactive_turn_events(
            uuid4() if mismatch == "session" else session_id,
            turn_id,
            cast(User, SimpleNamespace(id=uuid4() if mismatch == "user" else user_id)),
        )
