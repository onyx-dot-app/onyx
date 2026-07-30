"""Whether a sandbox is committed to work, and why.

The "why" is the point: a recycle or reap that has been blocked for an hour is a
support question, so each probe has to name what is holding the sandbox rather
than just declining.
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
    """Neither route holds the sandbox. Individual tests re-patch one probe's
    inputs to make it fire."""
    monkeypatch.setattr(
        sandbox_busy, "get_active_session_ids_for_user", lambda *_a, **_kw: []
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
    """A queued turn counts: the user has already been told the message was
    accepted, so losing it is as bad as interrupting a running one."""
    session_id = uuid4()
    monkeypatch.setattr(
        sandbox_busy, "get_active_session_ids_for_user", lambda *_a, **_kw: [session_id]
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
    """One sandbox serves all of a user's sessions, so a turn on any of them
    protects it."""
    sessions = [uuid4(), uuid4(), uuid4()]
    busy_session = sessions[-1]
    monkeypatch.setattr(
        sandbox_busy, "get_active_session_ids_for_user", lambda *_a, **_kw: sessions
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
    """The scheduled executor registers no interactive turn, so this is the only
    probe that sees it. AWAITING_APPROVAL waits on a person and still owns the
    sandbox."""
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
    """Callers need one reason, not all of them, and the DB query is the more
    expensive of the two."""
    monkeypatch.setattr(
        sandbox_busy, "get_active_session_ids_for_user", lambda *_a, **_kw: [uuid4()]
    )
    monkeypatch.setattr(sandbox_busy, "get_active_turn", lambda **_kw: _turn())
    scheduled_probe = MagicMock(return_value=None)
    monkeypatch.setattr(sandbox_busy, "get_unfinished_run_for_user", scheduled_probe)

    assert sandbox_busy_claim(MagicMock(), _sandbox(), cache=MagicMock()) is not None
    scheduled_probe.assert_not_called()
