from __future__ import annotations

import time
from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID
from uuid import uuid4

import pytest

from onyx.server.features.build.interactive_turns import executor
from onyx.server.features.build.interactive_turns.state import claim_turn_for_runner
from onyx.server.features.build.interactive_turns.state import create_interactive_turn
from onyx.server.features.build.interactive_turns.state import get_active_turn
from onyx.server.features.build.interactive_turns.state import get_turn
from onyx.server.features.build.interactive_turns.state import InteractiveTurn
from onyx.server.features.build.interactive_turns.state import TURN_STATUS_CANCELLED
from onyx.server.features.build.interactive_turns.state import TURN_STATUS_FAILED
from onyx.server.features.build.interactive_turns.state import TURN_STATUS_RUNNING
from onyx.server.features.build.interactive_turns.state import TURN_STATUS_SUCCEEDED
from onyx.server.features.build.sandbox.event_schema import Error as SandboxError
from onyx.server.features.build.sandbox.event_schema import PromptResponse
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.unit.fakes import FakeCache


class _FakeDbSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class _FakePromptSlot:
    def __init__(
        self,
        *,
        enter_result: bool = True,
        on_enter: Callable[[], None] | None = None,
    ) -> None:
        self._enter_result = enter_result
        self._on_enter = on_enter
        self.exited = False

    def __enter__(self) -> bool:
        if self._on_enter is not None:
            self._on_enter()
        return self._enter_result

    def __exit__(self, *_: object) -> None:
        self.exited = True


@contextmanager
def _fake_db_scope(db_session: _FakeDbSession) -> Iterator[_FakeDbSession]:
    yield db_session


def _run_turn_with_events(
    monkeypatch: pytest.MonkeyPatch,
    events: list[object],
) -> SimpleNamespace:
    cache = FakeCache()
    db_session = _FakeDbSession()
    session_id = uuid4()
    user_id = uuid4()
    sandbox_id = uuid4()
    prompt_slot = _FakePromptSlot()
    persisted: list[object] = []
    finalized: list[UUID] = []

    turn = create_interactive_turn(
        cache=cache,
        session_id=session_id,
        user_id=user_id,
        client_request_id="req-1",
        prompt="hello",
        turn_index=0,
    )

    class FakeSessionManager:
        def __init__(self, db_session_arg: _FakeDbSession) -> None:
            assert db_session_arg is db_session

        def ensure_sandbox_running(self, user_id_arg: UUID) -> SimpleNamespace:
            assert user_id_arg == user_id
            return SimpleNamespace(id=sandbox_id)

        def prompt_slot(
            self,
            sandbox_id_arg: UUID,
            session_id_arg: UUID,
        ) -> _FakePromptSlot:
            assert sandbox_id_arg == sandbox_id
            assert session_id_arg == session_id
            return prompt_slot

        def yield_sandbox_events(
            self,
            sandbox_id_arg: UUID,
            session_id_arg: UUID,
            prompt: str,
            *,
            should_interrupt: object,
        ) -> Iterator[object]:
            assert sandbox_id_arg == sandbox_id
            assert session_id_arg == session_id
            assert prompt == "hello"
            assert should_interrupt is not None
            yield from events

        def merge_events_with_announces(
            self,
            stream: Iterator[object],
            **_: object,
        ) -> Iterator[object]:
            yield from stream

        def persist_sandbox_event(
            self,
            session_id_arg: UUID,
            state: object,
            sandbox_event: object,
        ) -> None:
            assert session_id_arg == session_id
            assert state is not None
            persisted.append(sandbox_event)

        def finalize_persist(self, session_id_arg: UUID, state: object) -> None:
            assert state is not None
            finalized.append(session_id_arg)

    monkeypatch.setattr(executor, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(
        executor,
        "get_session_with_current_tenant",
        lambda: _fake_db_scope(db_session),
    )
    monkeypatch.setattr(executor, "SessionManager", FakeSessionManager)
    monkeypatch.setattr(executor, "update_session_activity", lambda *_: None)
    monkeypatch.setattr(executor, "is_interrupt_requested", lambda *_: False)
    monkeypatch.setattr(executor, "clear_interrupt", lambda *_: None)

    claimed = claim_turn_for_runner(cache=cache, turn_id=turn.turn_id)
    assert claimed is not None
    executor.run_claimed_interactive_build_turn(claimed, budget_seconds=30)

    return SimpleNamespace(
        cache=cache,
        db_session=db_session,
        finalized=finalized,
        persisted=persisted,
        prompt_slot=prompt_slot,
        session_id=session_id,
        turn=turn,
        user_id=user_id,
    )


def test_runner_succeeds_on_prompt_response(monkeypatch: pytest.MonkeyPatch) -> None:
    prompt_response = PromptResponse.model_validate({"stopReason": "end_turn"})

    result = _run_turn_with_events(monkeypatch, [prompt_response])

    finished = get_turn(result.cache, result.turn.turn_id)
    assert finished is not None
    assert finished.status == TURN_STATUS_SUCCEEDED
    assert (
        get_active_turn(
            cache=result.cache,
            session_id=result.session_id,
            user_id=result.user_id,
        )
        is None
    )
    assert result.persisted == [prompt_response]
    assert result.finalized == [result.session_id]
    assert result.prompt_slot.exited
    assert result.db_session.rollbacks == 0


def test_runner_fails_turn_on_sandbox_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox_error = SandboxError(code=-32000, message="provider model not found")

    result = _run_turn_with_events(monkeypatch, [sandbox_error])

    finished = get_turn(result.cache, result.turn.turn_id)
    assert finished is not None
    assert finished.status == TURN_STATUS_FAILED
    assert finished.error_detail == "provider model not found"
    assert (
        get_active_turn(
            cache=result.cache,
            session_id=result.session_id,
            user_id=result.user_id,
        )
        is None
    )
    assert result.persisted == [sandbox_error]
    assert result.finalized == [result.session_id]
    assert result.prompt_slot.exited
    assert result.db_session.rollbacks == 0


def test_runner_fails_turn_when_stream_ends_without_prompt_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run_turn_with_events(monkeypatch, [])

    finished = get_turn(result.cache, result.turn.turn_id)
    assert finished is not None
    assert finished.status == TURN_STATUS_FAILED
    assert (
        finished.error_detail == "Turn ended before opencode returned a final response."
    )
    assert (
        get_active_turn(
            cache=result.cache,
            session_id=result.session_id,
            user_id=result.user_id,
        )
        is None
    )
    assert result.persisted == []
    assert result.finalized == [result.session_id]
    assert result.prompt_slot.exited
    assert result.db_session.rollbacks == 0


def test_runner_records_cancelled_prompt_response_as_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt_response = PromptResponse.model_validate({"stopReason": "cancelled"})

    result = _run_turn_with_events(monkeypatch, [prompt_response])

    finished = get_turn(result.cache, result.turn.turn_id)
    assert finished is not None
    assert finished.status == TURN_STATUS_CANCELLED
    assert (
        get_active_turn(
            cache=result.cache,
            session_id=result.session_id,
            user_id=result.user_id,
        )
        is None
    )
    assert result.persisted == [prompt_response]
    assert result.finalized == [result.session_id]
    assert result.prompt_slot.exited
    assert result.db_session.rollbacks == 0


def test_prompt_slot_busy_does_not_finish_reclaimed_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    db_session = _FakeDbSession()
    session_id = uuid4()
    user_id = uuid4()
    sandbox_id = uuid4()
    reclaimed: InteractiveTurn | None = None

    turn = create_interactive_turn(
        cache=cache,
        session_id=session_id,
        user_id=user_id,
        client_request_id="req-1",
        prompt="hello",
        turn_index=0,
    )
    claimed = claim_turn_for_runner(cache=cache, turn_id=turn.turn_id)
    assert claimed is not None

    def reclaim_turn() -> None:
        nonlocal reclaimed
        reclaimed = claim_turn_for_runner(
            cache=cache,
            turn_id=turn.turn_id,
            stale_after_seconds=0,
        )
        assert reclaimed is not None

    prompt_slot = _FakePromptSlot(enter_result=False, on_enter=reclaim_turn)

    class FakeSessionManager:
        def __init__(self, db_session_arg: _FakeDbSession) -> None:
            assert db_session_arg is db_session

        def ensure_sandbox_running(self, user_id_arg: UUID) -> SimpleNamespace:
            assert user_id_arg == user_id
            return SimpleNamespace(id=sandbox_id)

        def prompt_slot(
            self,
            sandbox_id_arg: UUID,
            session_id_arg: UUID,
        ) -> _FakePromptSlot:
            assert sandbox_id_arg == sandbox_id
            assert session_id_arg == session_id
            return prompt_slot

    monkeypatch.setattr(executor, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(
        executor,
        "get_session_with_current_tenant",
        lambda: _fake_db_scope(db_session),
    )
    monkeypatch.setattr(executor, "SessionManager", FakeSessionManager)

    executor.run_claimed_interactive_build_turn(claimed, budget_seconds=30)

    current = get_turn(cache, turn.turn_id)
    assert current is not None
    assert reclaimed is not None
    assert current.status == TURN_STATUS_RUNNING
    assert current.runner_id == reclaimed.runner_id
    active = get_active_turn(cache=cache, session_id=session_id, user_id=user_id)
    assert active is not None
    assert active.runner_id == reclaimed.runner_id
    assert prompt_slot.exited


def test_lost_runner_does_not_clear_reclaimed_turn_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    db_session = _FakeDbSession()
    session_id = uuid4()
    user_id = uuid4()
    sandbox_id = uuid4()
    prompt_slot = _FakePromptSlot()
    reclaimed: InteractiveTurn | None = None
    clear_calls: list[UUID] = []

    turn = create_interactive_turn(
        cache=cache,
        session_id=session_id,
        user_id=user_id,
        client_request_id="req-1",
        prompt="hello",
        turn_index=0,
    )
    claimed = claim_turn_for_runner(cache=cache, turn_id=turn.turn_id)
    assert claimed is not None

    class FakeSessionManager:
        def __init__(self, db_session_arg: _FakeDbSession) -> None:
            assert db_session_arg is db_session

        def ensure_sandbox_running(self, user_id_arg: UUID) -> SimpleNamespace:
            assert user_id_arg == user_id
            return SimpleNamespace(id=sandbox_id)

        def prompt_slot(
            self,
            sandbox_id_arg: UUID,
            session_id_arg: UUID,
        ) -> _FakePromptSlot:
            assert sandbox_id_arg == sandbox_id
            assert session_id_arg == session_id
            return prompt_slot

        def yield_sandbox_events(
            self,
            sandbox_id_arg: UUID,
            session_id_arg: UUID,
            prompt: str,
            *,
            should_interrupt: object,
        ) -> Iterator[object]:
            nonlocal reclaimed
            assert sandbox_id_arg == sandbox_id
            assert session_id_arg == session_id
            assert prompt == "hello"
            assert should_interrupt is not None
            reclaimed = claim_turn_for_runner(
                cache=cache,
                turn_id=turn.turn_id,
                stale_after_seconds=0,
            )
            assert reclaimed is not None
            yield object()

    monkeypatch.setattr(executor, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(
        executor,
        "get_session_with_current_tenant",
        lambda: _fake_db_scope(db_session),
    )
    monkeypatch.setattr(executor, "SessionManager", FakeSessionManager)
    monkeypatch.setattr(executor, "update_session_activity", lambda *_: None)
    monkeypatch.setattr(executor, "is_interrupt_requested", lambda *_: False)
    monkeypatch.setattr(
        executor,
        "clear_interrupt",
        lambda session_id_arg, _: clear_calls.append(session_id_arg),
    )

    executor.run_claimed_interactive_build_turn(claimed, budget_seconds=30)

    current = get_turn(cache, turn.turn_id)
    assert current is not None
    assert reclaimed is not None
    assert current.status == TURN_STATUS_RUNNING
    assert current.runner_id == reclaimed.runner_id
    active = get_active_turn(cache=cache, session_id=session_id, user_id=user_id)
    assert active is not None
    assert active.runner_id == reclaimed.runner_id
    assert clear_calls == []
    assert prompt_slot.exited


def test_start_interactive_turn_runner_preserves_tenant_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    user_id = uuid4()
    turn = create_interactive_turn(
        cache=cache,
        session_id=session_id,
        user_id=user_id,
        client_request_id="req-1",
        prompt="hello",
        turn_index=0,
    )

    observed: list[tuple[UUID, str | None, str | None]] = []

    def run_logic(turn_arg: InteractiveTurn) -> None:
        observed.append(
            (
                turn_arg.turn_id,
                CURRENT_TENANT_ID_CONTEXTVAR.get(),
                turn_arg.runner_id,
            )
        )

    monkeypatch.setattr(executor, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(executor, "run_claimed_interactive_build_turn", run_logic)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant-a")
    try:
        executor.start_interactive_turn_runner(turn.turn_id)
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    deadline = time.monotonic() + 5
    while not observed and time.monotonic() < deadline:
        time.sleep(0.01)

    assert len(observed) == 1
    observed_turn_id, observed_tenant, observed_runner_id = observed[0]
    assert observed_turn_id == turn.turn_id
    assert observed_tenant == "tenant-a"
    assert observed_runner_id is not None


def test_start_interactive_turn_runner_skips_fresh_running_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    turn = create_interactive_turn(
        cache=cache,
        session_id=uuid4(),
        user_id=uuid4(),
        client_request_id="req-1",
        prompt="hello",
        turn_index=0,
    )
    assert claim_turn_for_runner(cache=cache, turn_id=turn.turn_id) is not None
    observed: list[UUID] = []

    monkeypatch.setattr(executor, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(
        executor,
        "run_claimed_interactive_build_turn",
        lambda turn_arg: observed.append(turn_arg.turn_id),
    )

    executor.start_interactive_turn_runner(turn.turn_id)
    time.sleep(0.05)

    assert observed == []
