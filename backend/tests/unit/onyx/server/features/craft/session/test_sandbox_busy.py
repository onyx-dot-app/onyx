"""Whether a sandbox is committed to work, and why.

The "why" is the point: a recycle blocked for an hour is a support question, so
each probe names what holds the sandbox rather than just declining.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

import onyx.server.features.build.session.sandbox_busy as sandbox_busy
from onyx.db.enums import ScheduledTaskRunStatus
from onyx.db.models import Sandbox
from onyx.server.features.build.session.sandbox_busy import (
    SandboxBusyKind,
    sandbox_busy_claim,
)

USER_ID = uuid4()


def _sandbox() -> Sandbox:
    return Sandbox(id=UUID("12345678-1234-1234-1234-1234567890ab"), user_id=USER_ID)


def _turn(status: str = "RUNNING") -> MagicMock:
    turn = MagicMock()
    turn.turn_id = uuid4()
    turn.status = status
    return turn


@pytest.fixture
def no_work(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither route holds the sandbox; tests re-patch one probe to fire."""
    monkeypatch.setattr(
        sandbox_busy, "get_live_session_ids_for_user", lambda *_a, **_kw: []
    )
    monkeypatch.setattr(sandbox_busy, "get_unfinished_run_for_user", lambda **_kw: None)


@pytest.mark.usefixtures("no_work")
def test_free_sandbox_has_no_claim() -> None:
    assert sandbox_busy_claim(MagicMock(), _sandbox(), cache=MagicMock()) is None


@pytest.mark.usefixtures("no_work")
@pytest.mark.parametrize("status", ["QUEUED", "RUNNING"])
def test_interactive_turn_claims_the_sandbox(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    """Queued counts: the user was already told the message was accepted."""
    session_id = uuid4()
    monkeypatch.setattr(
        sandbox_busy, "get_live_session_ids_for_user", lambda *_a, **_kw: [session_id]
    )
    monkeypatch.setattr(
        sandbox_busy, "get_active_turn", lambda **_kw: _turn(status=status)
    )

    claim = sandbox_busy_claim(MagicMock(), _sandbox(), cache=MagicMock())

    assert claim is not None
    assert claim.kind is SandboxBusyKind.INTERACTIVE_TURN
    assert str(session_id) in claim.detail
    assert status in claim.detail


@pytest.mark.usefixtures("no_work")
def test_every_session_of_the_user_is_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One sandbox serves all a user's sessions, so any turn protects it."""
    sessions = [uuid4(), uuid4(), uuid4()]
    busy_session = sessions[-1]
    monkeypatch.setattr(
        sandbox_busy, "get_live_session_ids_for_user", lambda *_a, **_kw: sessions
    )

    def fake_get_active_turn(*, session_id: UUID, **_kw: Any) -> MagicMock | None:
        return _turn() if session_id == busy_session else None

    monkeypatch.setattr(sandbox_busy, "get_active_turn", fake_get_active_turn)

    claim = sandbox_busy_claim(MagicMock(), _sandbox(), cache=MagicMock())

    assert claim is not None
    assert str(busy_session) in claim.detail


@pytest.mark.usefixtures("no_work")
@pytest.mark.parametrize(
    "status",
    [
        ScheduledTaskRunStatus.QUEUED,
        ScheduledTaskRunStatus.RUNNING,
        ScheduledTaskRunStatus.AWAITING_APPROVAL,
    ],
)
def test_unfinished_scheduled_run_claims_the_sandbox(
    monkeypatch: pytest.MonkeyPatch, status: ScheduledTaskRunStatus
) -> None:
    """The scheduled executor registers no turn, so only this probe sees it.
    AWAITING_APPROVAL waits on a person and still owns the sandbox."""
    run = MagicMock()
    run.id = uuid4()
    run.status = status
    monkeypatch.setattr(sandbox_busy, "get_unfinished_run_for_user", lambda **_kw: run)

    claim = sandbox_busy_claim(MagicMock(), _sandbox(), cache=MagicMock())

    assert claim is not None
    assert claim.kind is SandboxBusyKind.SCHEDULED_RUN
    assert status.value in claim.detail


@pytest.mark.usefixtures("no_work")
def test_interactive_turn_short_circuits_the_scheduled_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One reason is enough, and the DB query is the costlier probe."""
    monkeypatch.setattr(
        sandbox_busy, "get_live_session_ids_for_user", lambda *_a, **_kw: [uuid4()]
    )
    monkeypatch.setattr(sandbox_busy, "get_active_turn", lambda **_kw: _turn())
    scheduled_probe = MagicMock(return_value=None)
    monkeypatch.setattr(sandbox_busy, "get_unfinished_run_for_user", scheduled_probe)

    assert sandbox_busy_claim(MagicMock(), _sandbox(), cache=MagicMock()) is not None
    scheduled_probe.assert_not_called()


def test_initializing_session_is_treated_as_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Its workspace setup execs into the sandbox, so disturbing the sandbox
    under it fails the session — and no turn exists yet to notice."""
    session_id = uuid4()
    monkeypatch.setattr(
        sandbox_busy, "get_live_session_ids_for_user", lambda *_a, **_kw: [session_id]
    )
    monkeypatch.setattr(sandbox_busy, "get_unfinished_run_for_user", lambda **_kw: None)
    monkeypatch.setattr(sandbox_busy, "get_active_turn", lambda **_kw: _turn())

    claim = sandbox_busy_claim(MagicMock(), _sandbox(), cache=MagicMock())

    assert claim is not None
    assert str(session_id) in claim.detail
