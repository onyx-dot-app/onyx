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


# --- what each backend can preserve -----------------------------------------


@pytest.fixture
def provisioned(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    """Sandboxes provisioned again after their runtime was replaced."""
    done: list[UUID] = []

    def fake_provision(
        _db: Any, _mgr: Any, sandbox: Sandbox, *_a: Any, **_kw: Any
    ) -> None:
        done.append(sandbox.id)

    monkeypatch.setattr(recycle, "provision_sandbox", fake_provision)
    monkeypatch.setattr(recycle, "fetch_user_by_id", lambda *_a: MagicMock())
    return done


def _compose_manager(
    *,
    outcome: ImageMoveOutcome = ImageMoveOutcome.NEEDS_PROVISION,
    history: bool = True,
) -> MagicMock:
    """Compose: cannot swap an image, but keeps workspaces outside the runtime."""
    manager = _manager(live={}, outcome=outcome)
    manager.supports_opencode_history_persistence = history
    return manager


def test_compose_replaces_the_runtime_and_keeps_the_workspace(
    sandboxes: list[Sandbox], provisioned: list[UUID], rebuilt: list[UUID]
) -> None:
    """The workspace lives in a volume the container doesn't own."""
    sandbox = _sandbox()
    sandboxes.append(sandbox)
    manager = _compose_manager()
    manager.get_image_state.return_value = SandboxImageState(
        target=TARGET, live_digests={sandbox.id: OLD_DIGEST}
    )

    _run(manager)

    manager.move_to_image.assert_called_once_with(sandbox.id, TARGET)
    assert provisioned == [sandbox.id]
    assert rebuilt == []


def test_history_is_captured_before_the_runtime_goes(
    sandboxes: list[Sandbox], provisioned: list[UUID]
) -> None:
    """History lives in the discarded layer, so it is snapshotted first."""
    sandbox = _sandbox()
    sandboxes.append(sandbox)
    manager = _compose_manager()
    manager.get_image_state.return_value = SandboxImageState(
        target=TARGET, live_digests={sandbox.id: OLD_DIGEST}
    )
    order: list[str] = []
    manager.create_opencode_history_snapshot.side_effect = lambda *_a, **_kw: (
        order.append("snapshot")
    )
    manager.move_to_image.side_effect = lambda *_a: (
        order.append("move") or ImageMoveOutcome.NEEDS_PROVISION
    )

    _run(manager)

    assert order == ["snapshot", "move"]
    assert provisioned == [sandbox.id]


def test_failed_history_capture_falls_through_to_rebuilding(
    sandboxes: list[Sandbox], provisioned: list[UUID], rebuilt: list[UUID]
) -> None:
    """Fail closed: without the snapshot the history would be silently lost."""
    sandbox = _sandbox()
    sandboxes.append(sandbox)
    manager = _compose_manager()
    manager.get_image_state.return_value = SandboxImageState(
        target=TARGET, live_digests={sandbox.id: OLD_DIGEST}
    )
    manager.create_opencode_history_snapshot.side_effect = RuntimeError("no filestore")

    _run(manager)

    manager.move_to_image.assert_not_called()
    assert provisioned == []
    assert rebuilt == [sandbox.id]


@pytest.mark.usefixtures("provisioned")
def test_backend_without_history_persistence_rebuilds_instead(
    sandboxes: list[Sandbox], rebuilt: list[UUID]
) -> None:
    """Nothing would restore the history a discarded runtime holds."""
    sandbox = _sandbox()
    sandboxes.append(sandbox)
    manager = _compose_manager(history=False)
    manager.get_image_state.return_value = SandboxImageState(
        target=TARGET, live_digests={sandbox.id: OLD_DIGEST}
    )

    _run(manager)

    manager.move_to_image.assert_not_called()
    assert rebuilt == [sandbox.id]


def test_unsupported_move_falls_through_to_rebuilding(
    sandboxes: list[Sandbox], provisioned: list[UUID], rebuilt: list[UUID]
) -> None:  # noqa: ARG001
    """A move that can't happen still has to get the sandbox off the old image."""
    sandbox = _sandbox()
    sandboxes.append(sandbox)
    manager = _compose_manager(outcome=ImageMoveOutcome.UNSUPPORTED)
    manager.get_image_state.return_value = SandboxImageState(
        target=TARGET, live_digests={sandbox.id: OLD_DIGEST}
    )

    _run(manager)

    assert provisioned == []
    assert rebuilt == [sandbox.id]


def test_provisioning_failure_does_not_then_rebuild(
    sandboxes: list[Sandbox], monkeypatch: pytest.MonkeyPatch, rebuilt: list[UUID]
) -> None:
    """Rebuilding here would destroy what the move preserved: with no runtime to
    snapshot, the rebuild path terminates and takes the workspace volume with it.
    Stopping leaves it for the readiness path instead."""
    sandbox = _sandbox()
    sandboxes.append(sandbox)
    manager = _compose_manager()
    manager.get_image_state.return_value = SandboxImageState(
        target=TARGET, live_digests={sandbox.id: OLD_DIGEST}
    )
    monkeypatch.setattr(recycle, "fetch_user_by_id", lambda *_a: MagicMock())

    def boom(*_a: Any, **_kw: Any) -> None:
        raise RuntimeError("daemon refused")

    monkeypatch.setattr(recycle, "provision_sandbox", boom)

    _run(manager)

    assert rebuilt == []
