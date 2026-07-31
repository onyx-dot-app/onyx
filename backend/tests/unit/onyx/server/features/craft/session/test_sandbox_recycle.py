"""Deciding which sandboxes get moved onto the current image, and how.

Almost every case is a refusal: a sandbox a version behind still works, so
anything uncertain leaves it alone and tries again next pass.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

import onyx.server.features.build.session.sandbox_recycle as recycle
from onyx.db.models import Sandbox
from onyx.server.features.build.sandbox.models import (
    ImageMoveOutcome,
    SandboxImageState,
    SandboxImageTarget,
)
from onyx.server.features.build.session.sandbox_busy import (
    SandboxBusyClaim,
    SandboxBusyKind,
)

TARGET = SandboxImageTarget(
    ref="docker.io/onyxdotapp/sandbox@sha256:" + "b" * 64,
    digest="sha256:" + "b" * 64,
)
OLD_DIGEST = "sha256:" + "a" * 64


def _sandbox() -> Sandbox:
    return Sandbox(id=uuid4(), user_id=uuid4())


def _manager(
    *,
    target: SandboxImageTarget | None = TARGET,
    live: dict[UUID, str] | None = None,
    outcome: ImageMoveOutcome = ImageMoveOutcome.MOVED,
) -> MagicMock:
    """Kubernetes-shaped: moves a sandbox or can't, never NEEDS_PROVISION."""
    manager = MagicMock()
    manager.get_image_state.return_value = SandboxImageState(
        target=target, live_digests=live or {}
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
    monkeypatch.setattr(recycle, "get_active_session_ids_for_user", lambda *_a: [])


@pytest.fixture
def rebuilt(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    """Sandboxes sent down the slow path."""
    slept: list[UUID] = []

    def fake_sleep(_db: Any, _mgr: Any, sandbox: Sandbox, *_a: Any, **_kw: Any) -> bool:
        slept.append(sandbox.id)
        return True

    monkeypatch.setattr(recycle, "sleep_sandbox", fake_sleep)
    return slept


def _run(manager: MagicMock) -> None:
    recycle.recycle_sandboxes_on_stale_images(
        MagicMock(), manager, MagicMock(), "tenant"
    )


def test_stale_sandbox_is_swapped_in_place(sandboxes: list[Sandbox]) -> None:
    sandbox = _sandbox()
    sandboxes.append(sandbox)
    manager = _manager(live={sandbox.id: OLD_DIGEST})

    _run(manager)

    manager.move_to_image.assert_called_once_with(sandbox.id, TARGET)


def test_current_sandbox_is_left_alone(sandboxes: list[Sandbox]) -> None:
    sandbox = _sandbox()
    sandboxes.append(sandbox)
    manager = _manager(live={sandbox.id: TARGET.digest})

    _run(manager)

    manager.move_to_image.assert_not_called()


def test_nothing_happens_without_a_confirmed_target(
    sandboxes: list[Sandbox],
) -> None:
    """Restarting onto an image the host lacks would leave it unable to serve."""
    sandbox = _sandbox()
    sandboxes.append(sandbox)
    manager = _manager(target=None, live={sandbox.id: OLD_DIGEST})

    _run(manager)

    manager.move_to_image.assert_not_called()


def test_unreported_sandbox_is_left_alone(sandboxes: list[Sandbox]) -> None:
    """A pod that hasn't reported is either starting or already gone."""
    sandbox = _sandbox()
    sandboxes.append(sandbox)
    manager = _manager(live={})

    _run(manager)

    manager.move_to_image.assert_not_called()


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
