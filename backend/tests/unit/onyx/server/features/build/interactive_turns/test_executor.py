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
from onyx.server.features.build.sandbox.event_schema import ActivityTimeoutError
from onyx.server.features.build.sandbox.event_schema import Error as SandboxError
from onyx.server.features.build.sandbox.event_schema import PromptResponse
from onyx.server.features.build.sandbox.event_schema import TURN_ERROR_CODE_TIMEOUT
from onyx.server.features.build.sandbox.serve_transport import (
    PROMPT_SLOT_FAST_FAIL_ACQUIRE_SECONDS,
)
from onyx.server.features.build.sandbox.serve_transport import (
    PROMPT_SLOT_WAIT_OUT_ORPHAN_SECONDS,
)
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
        lost_after_extends: int | None = None,
    ) -> None:
        self.acquired = enter_result
        self._on_enter = on_enter
        self.exited = False
        self.extend_calls = 0
        self.acquire_timeouts: list[float] = []
        self.lost = False
        self._lost_after_extends = lost_after_extends

    def __enter__(self) -> "_FakePromptSlot":
        if self._on_enter is not None:
            self._on_enter()
        return self

    def __exit__(self, *_: object) -> None:
        self.exited = True

    def extend(self) -> None:
        self.extend_calls += 1
        if (
            self._lost_after_extends is not None
            and self.extend_calls >= self._lost_after_extends
        ):
            self.lost = True


@contextmanager
def _fake_db_scope(db_session: _FakeDbSession) -> Iterator[_FakeDbSession]:
    yield db_session


def _run_turn_with_events(
    monkeypatch: pytest.MonkeyPatch,
    events: list[object],
    *,
    reclaimed: bool = False,
    prompt_slot: "_FakePromptSlot | None" = None,
) -> SimpleNamespace:
    cache = FakeCache()
    db_session = _FakeDbSession()
    session_id = uuid4()
    user_id = uuid4()
    sandbox_id = uuid4()
    prompt_slot = prompt_slot if prompt_slot is not None else _FakePromptSlot()
    persisted: list[object] = []
    finalized: list[UUID] = []
    captured_should_abort_on_teardown: list[Callable[[], bool]] = []

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
            acquire_timeout: float = PROMPT_SLOT_FAST_FAIL_ACQUIRE_SECONDS,
        ) -> _FakePromptSlot:
            assert sandbox_id_arg == sandbox_id
            assert session_id_arg == session_id
            prompt_slot.acquire_timeouts.append(acquire_timeout)
            return prompt_slot

        def yield_sandbox_events(
            self,
            sandbox_id_arg: UUID,
            session_id_arg: UUID,
            prompt: str,
            *,
            should_interrupt: object,
            should_abort_on_teardown: Callable[[], bool],
        ) -> Iterator[object]:
            assert sandbox_id_arg == sandbox_id
            assert session_id_arg == session_id
            assert prompt == "hello"
            assert should_interrupt is not None
            captured_should_abort_on_teardown.append(should_abort_on_teardown)
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
    claimed.reclaimed = reclaimed
    executor.run_claimed_interactive_build_turn(claimed, budget_seconds=30)

    return SimpleNamespace(
        cache=cache,
        db_session=db_session,
        finalized=finalized,
        persisted=persisted,
        prompt_slot=prompt_slot,
        session_id=session_id,
        should_abort_on_teardown=(
            captured_should_abort_on_teardown[0]
            if captured_should_abort_on_teardown
            else None
        ),
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
    assert result.prompt_slot.extend_calls == 1
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
    assert result.prompt_slot.extend_calls == 1
    assert result.db_session.rollbacks == 0


def test_lost_lease_fails_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    prompt_slot = _FakePromptSlot(lost_after_extends=1)
    non_terminal_event = object()
    second_event = object()

    result = _run_turn_with_events(
        monkeypatch,
        [non_terminal_event, second_event],
        prompt_slot=prompt_slot,
    )

    finished = get_turn(result.cache, result.turn.turn_id)
    assert finished is not None
    assert finished.status == TURN_STATUS_FAILED
    assert finished.error_detail == "Prompt slot lease lost mid-turn."
    assert (
        get_active_turn(
            cache=result.cache,
            session_id=result.session_id,
            user_id=result.user_id,
        )
        is None
    )
    assert result.prompt_slot.exited
    assert result.prompt_slot.lost is True


def test_ownership_recheck_after_slot_acquire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    db_session = _FakeDbSession()
    session_id = uuid4()
    user_id = uuid4()
    sandbox_id = uuid4()
    reclaimed: InteractiveTurn | None = None
    yield_sandbox_events_called = False

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

    def steal_turn() -> None:
        nonlocal reclaimed
        reclaimed = claim_turn_for_runner(
            cache=cache,
            turn_id=turn.turn_id,
            stale_after_seconds=0,
        )
        assert reclaimed is not None

    prompt_slot = _FakePromptSlot(on_enter=steal_turn)

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
            acquire_timeout: float = PROMPT_SLOT_FAST_FAIL_ACQUIRE_SECONDS,
        ) -> _FakePromptSlot:
            assert sandbox_id_arg == sandbox_id
            assert session_id_arg == session_id
            prompt_slot.acquire_timeouts.append(acquire_timeout)
            return prompt_slot

        def yield_sandbox_events(
            self,
            sandbox_id_arg: UUID,
            session_id_arg: UUID,
            prompt: str,
            *,
            should_interrupt: object,
            should_abort_on_teardown: Callable[[], bool],
        ) -> Iterator[object]:
            nonlocal yield_sandbox_events_called
            assert sandbox_id_arg == sandbox_id
            assert session_id_arg == session_id
            assert prompt == "hello"
            assert should_interrupt is not None
            assert should_abort_on_teardown() is True
            yield_sandbox_events_called = True
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
    monkeypatch.setattr(executor, "clear_interrupt", lambda *_: None)

    executor.run_claimed_interactive_build_turn(claimed, budget_seconds=30)

    current = get_turn(cache, turn.turn_id)
    assert current is not None
    assert reclaimed is not None
    assert current.status == TURN_STATUS_RUNNING
    assert current.runner_id == reclaimed.runner_id
    active = get_active_turn(cache=cache, session_id=session_id, user_id=user_id)
    assert active is not None
    assert active.runner_id == reclaimed.runner_id
    assert yield_sandbox_events_called is False
    assert prompt_slot.exited


def test_prompt_slot_acquire_timeout_reflects_reclaimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt_response = PromptResponse.model_validate({"stopReason": "end_turn"})

    fresh = _run_turn_with_events(monkeypatch, [prompt_response], reclaimed=False)
    assert fresh.prompt_slot.acquire_timeouts == [PROMPT_SLOT_FAST_FAIL_ACQUIRE_SECONDS]

    reclaimed_result = _run_turn_with_events(
        monkeypatch, [prompt_response], reclaimed=True
    )
    assert reclaimed_result.prompt_slot.acquire_timeouts == [
        PROMPT_SLOT_WAIT_OUT_ORPHAN_SECONDS
    ]


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
            acquire_timeout: float = PROMPT_SLOT_FAST_FAIL_ACQUIRE_SECONDS,
        ) -> _FakePromptSlot:
            assert sandbox_id_arg == sandbox_id
            assert session_id_arg == session_id
            prompt_slot.acquire_timeouts.append(acquire_timeout)
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
    captured_should_abort_on_teardown: list[Callable[[], bool]] = []

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
            acquire_timeout: float = PROMPT_SLOT_FAST_FAIL_ACQUIRE_SECONDS,
        ) -> _FakePromptSlot:
            assert sandbox_id_arg == sandbox_id
            assert session_id_arg == session_id
            prompt_slot.acquire_timeouts.append(acquire_timeout)
            return prompt_slot

        def yield_sandbox_events(
            self,
            sandbox_id_arg: UUID,
            session_id_arg: UUID,
            prompt: str,
            *,
            should_interrupt: object,
            should_abort_on_teardown: Callable[[], bool],
        ) -> Iterator[object]:
            nonlocal reclaimed
            assert sandbox_id_arg == sandbox_id
            assert session_id_arg == session_id
            assert prompt == "hello"
            assert should_interrupt is not None
            captured_should_abort_on_teardown.append(should_abort_on_teardown)
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
    assert captured_should_abort_on_teardown[0]() is False


def test_teardown_abort_allowed_after_successful_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt_response = PromptResponse.model_validate({"stopReason": "end_turn"})

    result = _run_turn_with_events(monkeypatch, [prompt_response])

    assert result.should_abort_on_teardown is not None
    assert result.should_abort_on_teardown() is True


def test_teardown_abort_suppressed_after_lost_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt_slot = _FakePromptSlot(lost_after_extends=1)
    non_terminal_event = object()
    second_event = object()

    result = _run_turn_with_events(
        monkeypatch,
        [non_terminal_event, second_event],
        prompt_slot=prompt_slot,
    )

    assert result.should_abort_on_teardown is not None
    assert result.should_abort_on_teardown() is False


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


def _run_turn_with_batches(
    monkeypatch: pytest.MonkeyPatch,
    batches: list[list[object]],
) -> SimpleNamespace:
    cache = FakeCache()
    db_session = _FakeDbSession()
    session_id = uuid4()
    user_id = uuid4()
    sandbox_id = uuid4()
    prompt_slot = _FakePromptSlot()
    persisted: list[object] = []
    finalized: list[UUID] = []
    prompts_seen: list[str] = []

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
            acquire_timeout: float = PROMPT_SLOT_FAST_FAIL_ACQUIRE_SECONDS,
        ) -> _FakePromptSlot:
            assert sandbox_id_arg == sandbox_id
            assert session_id_arg == session_id
            prompt_slot.acquire_timeouts.append(acquire_timeout)
            return prompt_slot

        def yield_sandbox_events(
            self,
            sandbox_id_arg: UUID,
            session_id_arg: UUID,
            prompt: str,
            *,
            should_interrupt: object,
            should_abort_on_teardown: Callable[[], bool],
        ) -> Iterator[object]:
            assert sandbox_id_arg == sandbox_id
            assert session_id_arg == session_id
            assert should_interrupt is not None
            assert should_abort_on_teardown() is True
            idx = len(prompts_seen)
            prompts_seen.append(prompt)
            yield from (batches[idx] if idx < len(batches) else [])

        def persist_sandbox_event(
            self, session_id_arg: UUID, state: object, sandbox_event: object
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
        turn=turn,
        session_id=session_id,
        user_id=user_id,
        persisted=persisted,
        finalized=finalized,
        prompts_seen=prompts_seen,
        prompt_slot=prompt_slot,
    )


def test_runner_continues_after_tool_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeout = ActivityTimeoutError(message="Timeout waiting for activity")
    done = PromptResponse.model_validate({"stopReason": "end_turn"})

    result = _run_turn_with_batches(monkeypatch, [[timeout], [done]])

    finished = get_turn(result.cache, result.turn.turn_id)
    assert finished is not None
    assert finished.status == TURN_STATUS_SUCCEEDED
    assert result.persisted == [done]
    assert result.prompts_seen == [
        "hello",
        executor._TOOL_TIMEOUT_CONTINUATION_PROMPT,
    ]
    # The aborted step is flushed before the re-prompt, then the turn is
    # finalized once more at the end.
    assert result.finalized == [result.session_id, result.session_id]
    assert result.prompt_slot.exited


def test_runner_fails_after_max_timeout_continuations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeout = ActivityTimeoutError(message="Timeout waiting for activity")
    batches: list[list[object]] = [
        [timeout] for _ in range(executor.MAX_TIMEOUT_CONTINUATIONS + 1)
    ]

    result = _run_turn_with_batches(monkeypatch, batches)

    finished = get_turn(result.cache, result.turn.turn_id)
    assert finished is not None
    assert finished.status == TURN_STATUS_FAILED
    assert finished.error_detail == "Timeout waiting for activity"
    assert len(result.prompts_seen) == executor.MAX_TIMEOUT_CONTINUATIONS + 1
    assert result.persisted == [timeout]
    assert result.prompt_slot.exited


def test_runner_does_not_continue_on_absolute_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A hard absolute/budget timeout is a plain Error with the same code -2 as the
    # recoverable inactivity timeout; only the TYPE differs. It must fail the turn
    # immediately, never re-prompt.
    absolute = SandboxError(
        code=TURN_ERROR_CODE_TIMEOUT, message="Turn exceeded maximum duration"
    )

    result = _run_turn_with_batches(monkeypatch, [[absolute]])

    finished = get_turn(result.cache, result.turn.turn_id)
    assert finished is not None
    assert finished.status == TURN_STATUS_FAILED
    assert finished.error_detail == "Turn exceeded maximum duration"
    assert result.prompts_seen == ["hello"]
    assert result.persisted == [absolute]
    assert result.prompt_slot.exited


def test_runner_preserves_output_before_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = object()
    after = object()
    timeout = ActivityTimeoutError(message="Timeout waiting for activity")
    done = PromptResponse.model_validate({"stopReason": "end_turn"})

    result = _run_turn_with_batches(monkeypatch, [[before, timeout], [after, done]])

    finished = get_turn(result.cache, result.turn.turn_id)
    assert finished is not None
    assert finished.status == TURN_STATUS_SUCCEEDED
    # Output emitted before the timeout is persisted; the timeout event itself is
    # not, and the continuation's output follows it.
    assert result.persisted == [before, after, done]
    assert result.prompts_seen == [
        "hello",
        executor._TOOL_TIMEOUT_CONTINUATION_PROMPT,
    ]


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
