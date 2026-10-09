"""Getting a session's runtime up before a turn touches it.

The bug these pin: provisioning the sandbox and rebuilding the session
workspace used to be separate, so a turn could provision a pod and create an
opencode instance for a session directory while the restore endpoint was still
writing that directory's config. opencode caches the config it finds at
instance creation, so the turn then ran against an empty provider catalog —
"model not found", with a correct opencode.json sitting on disk.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

import onyx.server.features.build.interactive_turns.executor as executor
from onyx.db.enums import BuildSessionStatus, SandboxStatus
from onyx.server.features.build.session.session_ready import session_runtime_intact


def _session(status: BuildSessionStatus = BuildSessionStatus.ACTIVE) -> Any:
    return SimpleNamespace(id=uuid4(), status=status)


def _sandbox(status: SandboxStatus = SandboxStatus.RUNNING) -> Any:
    return SimpleNamespace(id=uuid4(), status=status)


@pytest.mark.parametrize(
    "session,sandbox,intact",
    [
        (_session(), _sandbox(), True),
        (_session(BuildSessionStatus.IDLE), _sandbox(), False),
        (_session(), _sandbox(SandboxStatus.SLEEPING), False),
        (_session(), None, False),
        (None, _sandbox(), False),
    ],
    ids=["settled", "session-idle", "sandbox-asleep", "no-sandbox", "no-session"],
)
def test_only_a_settled_session_skips_the_ensure(
    session: Any, sandbox: Any, intact: bool
) -> None:
    """The fast path must be exactly "the records say this is live" — a reaped
    sandbox or an idled session has to fall through to the full ensure."""
    assert session_runtime_intact(session, sandbox) is intact


def test_settled_turn_records_activity_and_does_not_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every turn on a live session: no lock, no exec to confirm a workspace we
    already believe in — but it records the activity, or the next sweep reaps a
    session in use."""
    session_id, user_id = uuid4(), uuid4()
    sandbox = _sandbox()

    monkeypatch.setattr(executor, "get_build_session", lambda *_a: _session())
    monkeypatch.setattr(executor, "get_sandbox_by_user_id", lambda *_a: sandbox)

    lock_taken = MagicMock()
    monkeypatch.setattr(executor, "session_creation_lock", lock_taken)
    ensure = MagicMock()
    monkeypatch.setattr(executor, "ensure_session_ready", ensure)
    manager = MagicMock()
    manager.health_check.return_value = True
    monkeypatch.setattr(executor, "get_sandbox_manager", lambda: manager)
    heartbeat = MagicMock()
    monkeypatch.setattr(executor, "update_sandbox_heartbeat", heartbeat)

    assert executor._ready_session_runtime(MagicMock(), session_id, user_id) is sandbox

    lock_taken.assert_not_called()
    ensure.assert_not_called()
    manager.session_workspace_exists.assert_not_called()
    assert heartbeat.call_args.args[1] == sandbox.id


def test_turn_wakes_the_session_when_the_pod_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A record saying RUNNING must be verified before a prompt is posted into
    it — the reaper terminates the pod before it writes SLEEPING. A failed
    check wakes the session instead of using the dead pod."""
    session_id, user_id = uuid4(), uuid4()
    rebuilt = _sandbox()
    order: list[str] = []

    monkeypatch.setattr(executor, "get_build_session", lambda *_a: _session())
    monkeypatch.setattr(executor, "get_sandbox_by_user_id", lambda *_a: _sandbox())
    monkeypatch.setattr(executor, "fetch_user_by_id", lambda *_a: MagicMock())
    monkeypatch.setattr(executor, "update_sandbox_heartbeat", MagicMock())

    manager = MagicMock()
    # What a terminated pod looks like from here.
    manager.health_check.return_value = False
    monkeypatch.setattr(executor, "get_sandbox_manager", lambda: manager)

    class FakeLock:
        def __init__(self, uid: object) -> None:
            assert uid == user_id

        def __enter__(self) -> None:
            order.append("lock")

        def __exit__(self, *_a: object) -> None:
            order.append("unlock")

    def fake_ensure(*_args: Any, **_kwargs: Any) -> Any:
        order.append("ensure")
        return rebuilt

    monkeypatch.setattr(executor, "session_creation_lock", FakeLock)
    monkeypatch.setattr(executor, "ensure_session_ready", fake_ensure)

    assert executor._ready_session_runtime(MagicMock(), session_id, user_id) is rebuilt

    # Rebuilt through the restore path rather than handed the doomed pod.
    assert order == ["lock", "ensure", "unlock"]


def test_reaped_session_is_rebuilt_under_the_restore_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn arriving after the reaper took the sandbox must rebuild the
    workspace through the same path and the same lock the restore endpoint
    uses — not race it."""
    session_id, user_id = uuid4(), uuid4()
    session = _session(BuildSessionStatus.IDLE)
    rebuilt = _sandbox()
    order: list[str] = []

    monkeypatch.setattr(executor, "get_build_session", lambda *_a: session)
    monkeypatch.setattr(
        executor, "get_sandbox_by_user_id", lambda *_a: _sandbox(SandboxStatus.SLEEPING)
    )
    monkeypatch.setattr(executor, "fetch_user_by_id", lambda *_a: MagicMock())
    monkeypatch.setattr(executor, "get_sandbox_manager", lambda: MagicMock())

    class FakeLock:
        def __init__(self, uid: object) -> None:
            assert uid == user_id

        def __enter__(self) -> None:
            order.append("lock")

        def __exit__(self, *_a: object) -> None:
            order.append("unlock")

    def fake_ensure(*_args: Any, **_kwargs: Any) -> Any:
        order.append("ensure")
        return rebuilt

    monkeypatch.setattr(executor, "session_creation_lock", FakeLock)
    monkeypatch.setattr(executor, "ensure_session_ready", fake_ensure)

    assert executor._ready_session_runtime(MagicMock(), session_id, user_id) is rebuilt

    # The rebuild happens inside the lock, which is the whole point.
    assert order == ["lock", "ensure", "unlock"]
