"""Deciding which sandboxes get moved onto the current image, and how.

Almost every case is a refusal: a sandbox a version behind still works, so
anything uncertain leaves it alone and tries again next pass.
"""

from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, cast
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

import onyx.server.features.build.session.sandbox_recycle as recycle
from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.models import (
    ImageMoveOutcome,
    SandboxImageState,
    SandboxImageTarget,
)
from onyx.server.features.build.sandbox.serve_transport import PromptSlot
from onyx.server.features.build.session.sandbox_busy import (
    SandboxBusyClaim,
    SandboxBusyKind,
)

# The barrier's own tests need the real thing; the autouse fixture below replaces
# it for every other test in the file.
_REAL_PROMPT_BARRIER = recycle._no_prompts_in_flight

TARGET = SandboxImageTarget(
    ref="docker.io/onyxdotapp/sandbox@sha256:" + "b" * 64,
    digest="sha256:" + "b" * 64,
)
OLD_DIGEST = "sha256:" + "a" * 64


def _sandbox(
    status: SandboxStatus = SandboxStatus.RUNNING,
    last_heartbeat: datetime | None = None,
) -> Sandbox:
    """RUNNING and recently active — what the drain expects to be handed."""
    return Sandbox(
        id=uuid4(),
        user_id=uuid4(),
        status=status,
        last_heartbeat=last_heartbeat or datetime.now(timezone.utc),
    )


def _manager(
    *,
    target: SandboxImageTarget | None = TARGET,
    live: dict[UUID, str] | None = None,
    outcome: ImageMoveOutcome = ImageMoveOutcome.MOVED,
) -> MagicMock:
    """Kubernetes-shaped: moves a sandbox or can't, never NEEDS_PROVISION."""
    manager = MagicMock()
    manager.get_image_state.return_value = SandboxImageState(
        target=target, movable_digests=live or {}
    )
    manager.move_to_image.return_value = outcome
    return manager


@pytest.fixture
def sandboxes(monkeypatch: pytest.MonkeyPatch) -> list[Sandbox]:
    """The RUNNING rows the drain works from; tests append to it."""
    rows: list[Sandbox] = []
    monkeypatch.setattr(recycle, "get_running_sandboxes", lambda *_a, **_kw: rows)
    return rows


@pytest.fixture(autouse=True)
def _free_and_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    """No chat work, every slot free; tests override one to force a refusal."""
    monkeypatch.setattr(recycle, "sandbox_busy_claim", lambda *_a, **_kw: None)

    @contextmanager
    def all_free(*_a: Any, **_kw: Any) -> Iterator[bool]:
        yield True

    monkeypatch.setattr(recycle, "_no_prompts_in_flight", all_free)
    monkeypatch.setattr(recycle, "get_live_session_ids_for_user", lambda *_a: [])


@pytest.fixture
def rebuilt(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    """Sandboxes sent down the slow path."""
    slept: list[UUID] = []

    def fake_sleep(_db: Any, _mgr: Any, sandbox: Sandbox, *_a: Any, **_kw: Any) -> bool:
        slept.append(sandbox.id)
        return True

    monkeypatch.setattr(recycle, "sleep_sandbox", fake_sleep)
    return slept


@pytest.fixture
def creation_lock() -> MagicMock:
    """The per-user session-creation lock, free unless a test says otherwise."""
    lock = MagicMock()
    lock.acquire.return_value = True
    lock.owned.return_value = True
    return lock


def _run(manager: MagicMock, creation_lock: MagicMock | None = None) -> None:
    redis_client = MagicMock()
    if creation_lock is not None:
        redis_client.lock.return_value = creation_lock
    recycle.recycle_sandboxes_on_stale_images(
        MagicMock(), manager, redis_client, "tenant"
    )


def test_stale_sandbox_is_swapped_in_place(sandboxes: list[Sandbox]) -> None:
    sandbox = _sandbox()
    sandboxes.append(sandbox)
    manager = _manager(live={sandbox.id: OLD_DIGEST})

    _run(manager)

    manager.move_to_image.assert_called_once_with(sandbox.id, TARGET)


@pytest.mark.parametrize(
    "target,reported",
    [
        (TARGET, TARGET.digest),
        (None, OLD_DIGEST),
        (TARGET, None),
    ],
    ids=["already-current", "unconfirmed-target", "unreported"],
)
def test_the_drain_acts_only_on_what_the_state_calls_stale(
    sandboxes: list[Sandbox],
    target: SandboxImageTarget | None,
    reported: str | None,
) -> None:
    """Which sandboxes are behind is ``SandboxImageState``'s answer, covered
    directly in test_image_target; the drain must not second-guess it."""
    sandbox = _sandbox()
    sandboxes.append(sandbox)
    manager = _manager(target=target, live={sandbox.id: reported} if reported else {})

    _run(manager)

    manager.move_to_image.assert_not_called()


def test_idle_sandbox_is_left_for_the_reaper(
    sandboxes: list[Sandbox], rebuilt: list[UUID]
) -> None:
    """It is about to be reclaimed — and if its reap was refused this pass, it
    is tried again next pass. Restarting a user's pod in between buys nothing."""
    sandbox = _sandbox(last_heartbeat=datetime.now(timezone.utc) - timedelta(days=1))
    sandboxes.append(sandbox)
    manager = _manager(live={sandbox.id: OLD_DIGEST})

    _run(manager)

    manager.move_to_image.assert_not_called()
    assert rebuilt == []


def test_busy_sandbox_is_left_on_the_old_image(
    sandboxes: list[Sandbox], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A move restarts opencode-serve, dropping a turn or a queued message."""
    sandbox = _sandbox()
    sandboxes.append(sandbox)
    monkeypatch.setattr(
        recycle,
        "sandbox_busy_claim",
        lambda *_a, **_kw: SandboxBusyClaim(
            kind=SandboxBusyKind.INTERACTIVE_TURN, detail="turn running"
        ),
    )
    manager = _manager(live={sandbox.id: OLD_DIGEST})

    _run(manager)

    manager.move_to_image.assert_not_called()


def test_a_prompt_starting_first_defers_the_recycle(
    sandboxes: list[Sandbox], monkeypatch: pytest.MonkeyPatch, rebuilt: list[UUID]
) -> None:
    """A prompt can start between the gate and the move; the barrier catches it."""
    sandbox = _sandbox()
    sandboxes.append(sandbox)

    @contextmanager
    def slot_taken(*_a: Any, **_kw: Any) -> Iterator[bool]:
        yield False

    monkeypatch.setattr(recycle, "_no_prompts_in_flight", slot_taken)
    manager = _manager(live={sandbox.id: OLD_DIGEST})

    _run(manager)

    manager.move_to_image.assert_not_called()
    assert rebuilt == []


def test_a_session_being_created_defers_the_recycle(
    sandboxes: list[Sandbox], creation_lock: MagicMock, rebuilt: list[UUID]
) -> None:
    """Session setup execs into the sandbox holding no prompt slot, so only the
    creation lock can see it — restarting under it fails the session."""
    sandbox = _sandbox()
    sandboxes.append(sandbox)
    creation_lock.acquire.return_value = False
    manager = _manager(live={sandbox.id: OLD_DIGEST})

    _run(manager, creation_lock)

    manager.move_to_image.assert_not_called()
    assert rebuilt == []


def test_a_sandbox_that_stopped_running_is_left_alone(
    sandboxes: list[Sandbox], rebuilt: list[UUID]
) -> None:
    """A pass can span minutes of swaps; the row is re-read under the lock."""
    sandbox = _sandbox(status=SandboxStatus.SLEEPING)
    sandboxes.append(sandbox)
    manager = _manager(live={sandbox.id: OLD_DIGEST})

    _run(manager)

    manager.move_to_image.assert_not_called()
    assert rebuilt == []


def test_backend_that_cannot_swap_falls_back_to_rebuilding(
    sandboxes: list[Sandbox], rebuilt: list[UUID]
) -> None:
    """Either way the sandbox still has to leave the old image."""
    sandbox = _sandbox()
    sandboxes.append(sandbox)
    manager = _manager(
        live={sandbox.id: OLD_DIGEST}, outcome=ImageMoveOutcome.UNSUPPORTED
    )

    _run(manager)

    assert rebuilt == [sandbox.id]


def test_a_swap_that_raises_falls_back_to_rebuilding(
    sandboxes: list[Sandbox], rebuilt: list[UUID]
) -> None:
    sandbox = _sandbox()
    sandboxes.append(sandbox)
    manager = _manager(live={sandbox.id: OLD_DIGEST})
    manager.move_to_image.side_effect = RuntimeError("api server said no")

    _run(manager)

    assert rebuilt == [sandbox.id]


def test_a_disrupted_swap_is_not_rebuilt(
    sandboxes: list[Sandbox], rebuilt: list[UUID]
) -> None:
    """The move landed and did not come up: the old runtime is already gone, so
    snapshotting the pod would risk terminating a workspace it cannot capture."""
    sandbox = _sandbox()
    sandboxes.append(sandbox)
    manager = _manager(
        live={sandbox.id: OLD_DIGEST}, outcome=ImageMoveOutcome.DISRUPTED
    )

    _run(manager)

    assert rebuilt == []


def test_recycles_are_bounded_per_pass(
    sandboxes: list[Sandbox], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rollout must not become a fleet-wide stampede of restarts."""
    monkeypatch.setattr(recycle, "_MAX_RECYCLES_PER_PASS", 2)
    live = {}
    for _ in range(5):
        sandbox = _sandbox()
        sandboxes.append(sandbox)
        live[sandbox.id] = OLD_DIGEST
    manager = _manager(live=live)

    _run(manager)

    assert manager.move_to_image.call_count == 2


def test_busy_sandboxes_do_not_consume_the_budget(
    sandboxes: list[Sandbox], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skipping is not recycling, so busy sandboxes must not starve the rest."""
    monkeypatch.setattr(recycle, "_MAX_RECYCLES_PER_PASS", 2)
    live = {}
    rows = [_sandbox() for _ in range(4)]
    for sandbox in rows:
        sandboxes.append(sandbox)
        live[sandbox.id] = OLD_DIGEST
    busy = {rows[0].id, rows[1].id}
    monkeypatch.setattr(
        recycle,
        "sandbox_busy_claim",
        lambda _db, sandbox, **_kw: (
            SandboxBusyClaim(kind=SandboxBusyKind.SCHEDULED_RUN, detail="run")
            if sandbox.id in busy
            else None
        ),
    )
    manager = _manager(live=live)

    _run(manager)

    swapped = {call.args[0] for call in manager.move_to_image.call_args_list}
    assert swapped == {rows[2].id, rows[3].id}


def test_a_pass_is_bounded_by_wall_clock_too(
    sandboxes: list[Sandbox], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The restart count doesn't bound the tick: one slow swap can cost a minute,
    and the idle reaps sharing this sweep wait behind them."""

    class _Clock:
        now = 0.0

        def monotonic(self) -> float:
            return self.now

    clock = _Clock()
    monkeypatch.setattr(recycle, "time", clock)
    monkeypatch.setattr(recycle, "_MAX_RECYCLE_SECONDS_PER_PASS", 180.0)

    live = {}
    for _ in range(5):
        sandbox = _sandbox()
        sandboxes.append(sandbox)
        live[sandbox.id] = OLD_DIGEST
    manager = _manager(live=live)

    def slow_swap(*_a: Any, **_kw: Any) -> ImageMoveOutcome:
        clock.now += 100.0
        return ImageMoveOutcome.MOVED

    manager.move_to_image.side_effect = slow_swap

    _run(manager)

    assert manager.move_to_image.call_count == 2


class _SlotManager:
    """A manager whose prompt slots record what was asked for and held."""

    def __init__(self, refuse: set[UUID] | None = None) -> None:
        self.refuse = refuse or set()
        self.requested: list[UUID] = []
        self.held: list[UUID] = []
        self.kwargs: dict[str, Any] = {}

    @contextmanager
    def prompt_slot(
        self, _sandbox_id: UUID, session_id: UUID, **kwargs: Any
    ) -> Iterator[PromptSlot]:
        self.requested.append(session_id)
        self.kwargs = kwargs
        acquired = session_id not in self.refuse
        if acquired:
            self.held.append(session_id)
        try:
            yield PromptSlot(acquired=acquired)
        finally:
            if acquired:
                self.held.remove(session_id)


def _barrier(
    manager: _SlotManager, session_ids: list[UUID]
) -> AbstractContextManager[bool]:
    """The real barrier over a manager that only implements ``prompt_slot``."""
    return _REAL_PROMPT_BARRIER(cast(SandboxManager, manager), uuid4(), session_ids)


def test_the_barrier_holds_every_session_slot_at_once() -> None:
    """One sandbox serves all the user's sessions, so a prompt on any of them
    would be interrupted by the restart."""
    manager = _SlotManager()
    session_ids = [uuid4(), uuid4(), uuid4()]

    with _barrier(manager, session_ids) as held:
        assert held
        assert manager.held == session_ids

    assert manager.held == []


def test_the_barrier_fails_closed_and_stops_asking() -> None:
    """A refusal is the answer; the slots already taken are given straight back
    rather than held while we ask the rest."""
    session_ids = [uuid4(), uuid4(), uuid4()]
    manager = _SlotManager(refuse={session_ids[1]})

    with _barrier(manager, session_ids) as held:
        assert not held

    assert manager.requested == session_ids[:2]
    assert manager.held == []


def test_the_barrier_never_waits_and_never_assumes_a_free_slot() -> None:
    """A sweep must not block on a live turn, and a cache that cannot answer is
    not permission to restart the sandbox."""
    manager = _SlotManager()

    with _barrier(manager, [uuid4()]):
        pass

    assert manager.kwargs == {"acquire_timeout": 0.0, "fail_open": False}
