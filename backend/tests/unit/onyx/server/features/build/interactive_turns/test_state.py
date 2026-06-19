from __future__ import annotations

from collections.abc import Callable
from uuid import UUID
from uuid import uuid4

from onyx.server.features.build.interactive_turns.state import acquire_active_turn_lock
from onyx.server.features.build.interactive_turns.state import claim_turn_for_runner
from onyx.server.features.build.interactive_turns.state import create_interactive_turn
from onyx.server.features.build.interactive_turns.state import finish_turn
from onyx.server.features.build.interactive_turns.state import get_active_turn
from onyx.server.features.build.interactive_turns.state import get_turn
from onyx.server.features.build.interactive_turns.state import get_turn_for_request
from onyx.server.features.build.interactive_turns.state import InteractiveTurn
from onyx.server.features.build.interactive_turns.state import REQUEST_ID_TTL_SECONDS
from onyx.server.features.build.interactive_turns.state import touch_turn
from onyx.server.features.build.interactive_turns.state import TURN_STATUS_FAILED
from onyx.server.features.build.interactive_turns.state import TURN_STATUS_QUEUED
from onyx.server.features.build.interactive_turns.state import TURN_STATUS_RUNNING
from tests.unit.fakes import FakeCache


class _InterleavingCache(FakeCache):
    def __init__(self) -> None:
        super().__init__()
        self.after_next_turn_read: Callable[[], None] | None = None

    def get(self, key: str) -> bytes | None:
        value = super().get(key)
        if (
            key.startswith("craft:interactive_turn:")
            and self.after_next_turn_read is not None
        ):
            callback = self.after_next_turn_read
            self.after_next_turn_read = None
            callback()
        return value


def _create_turn(
    cache: FakeCache,
    *,
    session_id: UUID | None = None,
    user_id: UUID | None = None,
    request_id: str = "req-1",
) -> tuple[UUID, UUID, InteractiveTurn]:
    session_id = session_id or uuid4()
    user_id = user_id or uuid4()
    lock = acquire_active_turn_lock(cache, session_id)
    try:
        turn = create_interactive_turn(
            cache=cache,
            session_id=session_id,
            user_id=user_id,
            client_request_id=request_id,
            prompt="hello",
            turn_index=0,
        )
    finally:
        lock.release()
    return session_id, user_id, turn


def test_create_turn_records_active_and_request_mappings() -> None:
    cache = FakeCache()
    request_id = "req-1"
    session_id, user_id, turn = _create_turn(cache, request_id=request_id)

    assert turn.status == TURN_STATUS_QUEUED
    active_turn = get_active_turn(cache=cache, session_id=session_id, user_id=user_id)
    assert active_turn is not None
    assert active_turn.turn_id == turn.turn_id
    request_turn = get_turn_for_request(
        cache=cache,
        session_id=session_id,
        user_id=user_id,
        client_request_id=request_id,
    )
    assert request_turn is not None
    assert request_turn.turn_id == turn.turn_id


def test_finish_turn_clears_active_marker_but_keeps_request_mapping() -> None:
    cache = FakeCache()
    request_id = "req-1"
    session_id, user_id, turn = _create_turn(cache, request_id=request_id)

    finish_turn(
        cache=cache,
        turn_id=turn.turn_id,
        status=TURN_STATUS_FAILED,
        error_detail="boom",
    )

    assert get_active_turn(cache=cache, session_id=session_id, user_id=user_id) is None
    finished = get_turn_for_request(
        cache=cache,
        session_id=session_id,
        user_id=user_id,
        client_request_id=request_id,
    )
    assert finished is not None
    assert finished.status == TURN_STATUS_FAILED
    assert finished.error_detail == "boom"


def test_terminal_turn_lives_as_long_as_request_mapping() -> None:
    cache = FakeCache()
    request_id = "req-1"
    session_id, user_id, turn = _create_turn(cache, request_id=request_id)

    finish_turn(cache=cache, turn_id=turn.turn_id, status=TURN_STATUS_FAILED)

    assert (
        cache.expiries[f"craft:interactive_turn:{turn.turn_id}"]
        == REQUEST_ID_TTL_SECONDS
    )
    assert (
        cache.expiries[
            f"craft:session:{session_id}:turn_request:{user_id}:{request_id}"
        ]
        == REQUEST_ID_TTL_SECONDS
    )


def test_claim_turn_for_runner_sets_running_owner() -> None:
    cache = FakeCache()
    _, _, turn = _create_turn(cache)

    claimed = claim_turn_for_runner(cache=cache, turn_id=turn.turn_id)

    assert claimed is not None
    assert claimed.status == TURN_STATUS_RUNNING
    assert claimed.runner_id is not None
    assert claim_turn_for_runner(cache=cache, turn_id=turn.turn_id) is None


def test_stale_running_turn_can_be_reclaimed_by_new_runner() -> None:
    cache = FakeCache()
    session_id, user_id, turn = _create_turn(cache)

    first = claim_turn_for_runner(cache=cache, turn_id=turn.turn_id)
    assert first is not None
    first_runner_id = first.runner_id
    assert first_runner_id is not None

    reclaimed = claim_turn_for_runner(
        cache=cache,
        turn_id=turn.turn_id,
        stale_after_seconds=0,
    )

    assert reclaimed is not None
    assert reclaimed.runner_id is not None
    assert reclaimed.runner_id != first_runner_id
    assert not touch_turn(cache=cache, turn_id=turn.turn_id, runner_id=first_runner_id)
    assert (
        finish_turn(
            cache=cache,
            turn_id=turn.turn_id,
            status=TURN_STATUS_FAILED,
            runner_id=first_runner_id,
        )
        is None
    )
    active = get_active_turn(cache=cache, session_id=session_id, user_id=user_id)
    assert active is not None
    assert active.runner_id == reclaimed.runner_id


def test_finish_turn_does_not_clobber_concurrent_reclaim() -> None:
    cache = _InterleavingCache()
    session_id, user_id, turn = _create_turn(cache)

    first = claim_turn_for_runner(cache=cache, turn_id=turn.turn_id)
    assert first is not None
    first_runner_id = first.runner_id
    assert first_runner_id is not None
    reclaimed: InteractiveTurn | None = None

    def reclaim_turn() -> None:
        nonlocal reclaimed
        reclaimed = claim_turn_for_runner(
            cache=cache,
            turn_id=turn.turn_id,
            stale_after_seconds=0,
        )

    cache.after_next_turn_read = reclaim_turn

    assert (
        finish_turn(
            cache=cache,
            turn_id=turn.turn_id,
            status=TURN_STATUS_FAILED,
            runner_id=first_runner_id,
        )
        is None
    )

    current = get_turn(cache, turn.turn_id)
    assert current is not None
    assert reclaimed is not None
    assert current.status == TURN_STATUS_RUNNING
    assert current.runner_id == reclaimed.runner_id
    active = get_active_turn(cache=cache, session_id=session_id, user_id=user_id)
    assert active is not None
    assert active.runner_id == reclaimed.runner_id


def test_touch_turn_does_not_clobber_concurrent_reclaim() -> None:
    cache = _InterleavingCache()
    session_id, user_id, turn = _create_turn(cache)

    first = claim_turn_for_runner(cache=cache, turn_id=turn.turn_id)
    assert first is not None
    first_runner_id = first.runner_id
    assert first_runner_id is not None
    reclaimed: InteractiveTurn | None = None

    def reclaim_turn() -> None:
        nonlocal reclaimed
        reclaimed = claim_turn_for_runner(
            cache=cache,
            turn_id=turn.turn_id,
            stale_after_seconds=0,
        )

    cache.after_next_turn_read = reclaim_turn

    assert not touch_turn(cache=cache, turn_id=turn.turn_id, runner_id=first_runner_id)

    current = get_turn(cache, turn.turn_id)
    assert current is not None
    assert reclaimed is not None
    assert current.status == TURN_STATUS_RUNNING
    assert current.runner_id == reclaimed.runner_id
    active = get_active_turn(cache=cache, session_id=session_id, user_id=user_id)
    assert active is not None
    assert active.runner_id == reclaimed.runner_id
