"""Busy-ness claims against real Postgres.

Both halves of the gate are queries that mocks will happily agree with while
they are wrong: the scheduled-run probe is a join plus a "not terminal" filter,
and which sessions count as live decides both what the turn probe asks about and
whose prompt slots a recycle has to hold. The turn probe's own logic is a cache
read, and stays in the unit tests.
"""

from __future__ import annotations

import datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

import onyx.server.features.build.session.sandbox_busy as sandbox_busy
from onyx.db.enums import (
    BuildSessionStatus,
    ScheduledTaskRunStatus,
    ScheduledTaskStatus,
    ScheduledTaskTriggerSource,
)
from onyx.db.models import BuildSession, ScheduledTask, ScheduledTaskRun, User
from onyx.server.features.build.db.build_session import get_live_session_ids_for_user
from onyx.server.features.build.session.sandbox_busy import (
    SandboxBusyKind,
    sandbox_busy_claim,
)
from tests.external_dependency_unit.craft.db_helpers import make_sandbox, make_user


@pytest.fixture(autouse=True)
def _no_interactive_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the scheduled-run probe: with no ACTIVE sessions the turn probe
    can't fire, so any claim here comes from Postgres."""
    monkeypatch.setattr(
        sandbox_busy, "get_live_session_ids_for_user", lambda *_a, **_kw: []
    )


def _seed_run(
    db_session: Session, user: User, status: ScheduledTaskRunStatus
) -> ScheduledTaskRun:
    now = datetime.datetime.now(datetime.timezone.utc)
    task = ScheduledTask(
        user_id=user.id,
        name="nightly-report",
        prompt="Summarise yesterday's events",
        cron_expression="0 9 * * *",
        editor_mode="advanced",
        status=ScheduledTaskStatus.ACTIVE,
        next_run_at=now + datetime.timedelta(days=1),
    )
    db_session.add(task)
    db_session.flush()
    run = ScheduledTaskRun(
        task_id=task.id,
        status=status,
        trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
        started_at=now,
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    return run


@pytest.mark.parametrize(
    "status",
    [
        ScheduledTaskRunStatus.QUEUED,
        ScheduledTaskRunStatus.RUNNING,
        ScheduledTaskRunStatus.AWAITING_APPROVAL,
    ],
)
def test_unfinished_run_claims_the_sandbox(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    status: ScheduledTaskRunStatus,
) -> None:
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)
    run = _seed_run(db_session, user, status)

    claim = sandbox_busy_claim(db_session, sandbox)

    assert claim is not None
    assert claim.kind is SandboxBusyKind.SCHEDULED_RUN
    assert str(run.id) in claim.detail


@pytest.mark.parametrize(
    "status",
    [
        ScheduledTaskRunStatus.SUCCEEDED,
        ScheduledTaskRunStatus.FAILED,
        ScheduledTaskRunStatus.SKIPPED,
    ],
)
def test_finished_run_leaves_the_sandbox_free(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    status: ScheduledTaskRunStatus,
) -> None:
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)
    _seed_run(db_session, user, status)

    assert sandbox_busy_claim(db_session, sandbox) is None


def test_another_users_run_does_not_claim_this_sandbox(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """Sandboxes are per user; the join is what keeps one tenant's busy
    scheduled task from freezing everyone else's recycles."""
    owner = make_user(db_session)
    sandbox = make_sandbox(db_session, owner)
    _seed_run(db_session, make_user(db_session), ScheduledTaskRunStatus.RUNNING)

    assert sandbox_busy_claim(db_session, sandbox) is None


def _seed_session(
    db_session: Session, user: User, status: BuildSessionStatus
) -> BuildSession:
    session = BuildSession(
        id=uuid4(), user_id=user.id, name=status.value, status=status
    )
    db_session.add(session)
    db_session.commit()
    return session


def test_live_sessions_are_the_ones_using_the_sandbox(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """This set decides what the turn probe asks about *and* whose prompt slots
    a recycle holds, so both a missing status and a spurious one are wrong.

    INITIALIZING counts because its workspace setup execs into the sandbox;
    IDLE does not, because its sandbox is already asleep.
    """
    user = make_user(db_session)
    live = {
        _seed_session(db_session, user, status).id
        for status in (BuildSessionStatus.INITIALIZING, BuildSessionStatus.ACTIVE)
    }
    for status in (BuildSessionStatus.IDLE, BuildSessionStatus.FAILED):
        _seed_session(db_session, user, status)

    assert set(get_live_session_ids_for_user(user.id, db_session)) == live


def test_another_users_sessions_are_not_live_here(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """The barrier holds slots keyed on these ids; one user's chat must not
    block another's recycle."""
    user = make_user(db_session)
    _seed_session(db_session, make_user(db_session), BuildSessionStatus.ACTIVE)

    assert get_live_session_ids_for_user(user.id, db_session) == []
