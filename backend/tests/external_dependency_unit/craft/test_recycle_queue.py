"""The queue of sandboxes waiting to be recycled onto a newer image.

Enqueue is one statement over the RUNNING set, which is only correct because of
a timing argument (every RUNNING sandbox predates the image that just landed).
These tests pin the parts that argument depends on: who gets queued, who is left
alone, and that a second image landing mid-drain doesn't reorder the queue.
"""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox, User
from onyx.server.features.build.db.sandbox import (
    clear_recycle_request__no_commit,
    count_sandboxes_awaiting_recycle,
    get_sandboxes_awaiting_recycle,
    request_recycle_for_running_sandboxes__no_commit,
)
from tests.external_dependency_unit.craft.db_helpers import make_sandbox, make_user

NOW = datetime.datetime(2026, 7, 30, 12, 0, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture(autouse=True)
def _quiesce_leaked_sandboxes(db_session: Session) -> None:
    """Park RUNNING sandboxes leaked by earlier tests.

    Enqueue and queue depth are tenant-wide by design, so rows committed by
    other tests in this directory would otherwise leak into the assertions.
    """
    db_session.execute(
        update(Sandbox)
        .where(Sandbox.status == SandboxStatus.RUNNING)
        .values(status=SandboxStatus.TERMINATED, recycle_requested_at=None)
    )
    db_session.commit()


def test_running_sandboxes_are_queued(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    sandbox = make_sandbox(db_session, make_user(db_session))

    queued = request_recycle_for_running_sandboxes__no_commit(db_session, NOW)
    db_session.commit()

    assert queued >= 1
    db_session.refresh(sandbox)
    assert sandbox.recycle_requested_at == NOW
    assert sandbox.id in {s.id for s in get_sandboxes_awaiting_recycle(db_session)}


def test_sleeping_sandbox_is_not_queued(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """A sandbox that is not running will be re-provisioned onto whatever image
    is current when it wakes, so it needs no recycle."""
    sandbox = make_sandbox(db_session, make_user(db_session))
    sandbox.status = SandboxStatus.SLEEPING
    db_session.commit()

    request_recycle_for_running_sandboxes__no_commit(db_session, NOW)
    db_session.commit()

    db_session.refresh(sandbox)
    assert sandbox.recycle_requested_at is None
    assert sandbox.id not in {s.id for s in get_sandboxes_awaiting_recycle(db_session)}


def test_second_image_does_not_reorder_the_queue(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """Two deploys in quick succession must not starve whoever was waiting
    first — the drain is longest-waiting-first."""
    sandbox = make_sandbox(db_session, make_user(db_session))

    request_recycle_for_running_sandboxes__no_commit(db_session, NOW)
    db_session.commit()
    later = request_recycle_for_running_sandboxes__no_commit(
        db_session, NOW + datetime.timedelta(minutes=5)
    )
    db_session.commit()

    db_session.refresh(sandbox)
    assert later == 0
    assert sandbox.recycle_requested_at == NOW


def test_queue_is_ordered_longest_waiting_first(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    first = make_sandbox(db_session, make_user(db_session))
    first.recycle_requested_at = NOW
    second = make_sandbox(db_session, make_user(db_session))
    second.recycle_requested_at = NOW + datetime.timedelta(minutes=1)
    db_session.commit()

    queued_ids = [s.id for s in get_sandboxes_awaiting_recycle(db_session)]

    assert queued_ids.index(first.id) < queued_ids.index(second.id)


def test_limit_bounds_a_drain_pass(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """A fleet-wide rollout must be drainable in bounded chunks."""
    for offset in range(3):
        sandbox = make_sandbox(db_session, make_user(db_session))
        sandbox.recycle_requested_at = NOW + datetime.timedelta(minutes=offset)
    db_session.commit()

    assert len(get_sandboxes_awaiting_recycle(db_session, limit=2)) == 2


def test_clearing_removes_a_sandbox_from_the_queue(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    sandbox = make_sandbox(db_session, make_user(db_session))
    request_recycle_for_running_sandboxes__no_commit(db_session, NOW)
    db_session.commit()
    before = count_sandboxes_awaiting_recycle(db_session)

    clear_recycle_request__no_commit(db_session, sandbox.id)
    db_session.commit()

    db_session.refresh(sandbox)
    assert sandbox.recycle_requested_at is None
    assert count_sandboxes_awaiting_recycle(db_session) == before - 1


def test_clearing_is_idempotent(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """Every trigger path calls the same drain, so a double-clear has to be a
    no-op rather than an error."""
    sandbox = make_sandbox(db_session, make_user(db_session))

    clear_recycle_request__no_commit(db_session, sandbox.id)
    clear_recycle_request__no_commit(db_session, sandbox.id)
    db_session.commit()

    db_session.refresh(sandbox)
    assert sandbox.recycle_requested_at is None
