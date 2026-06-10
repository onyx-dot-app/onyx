"""Retention selection (keep-last-N + age expiry) against a real DB."""

import datetime
from uuid import UUID
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.db.models import BuildSession
from onyx.db.models import Snapshot
from onyx.server.features.build.db.sandbox import get_prunable_snapshots


def _make_session_with_snapshots(db_session: Session, ages_days: list[int]) -> UUID:
    session = BuildSession(id=uuid4(), name="RETENTION-TEST")
    db_session.add(session)
    db_session.flush()
    now = datetime.datetime.now(datetime.timezone.utc)
    for age in ages_days:
        snap = Snapshot(
            session_id=session.id,
            storage_path=f"snap/{uuid4()}.tar.gz",
            size_bytes=1,
        )
        snap.created_at = now - datetime.timedelta(days=age)
        db_session.add(snap)
    db_session.flush()
    return session.id


def _pruned_ages(
    db_session: Session, session_id: UUID, retention_days: int, keep_last_n: int
) -> list[int]:
    now = datetime.datetime.now(datetime.timezone.utc)
    prunable = get_prunable_snapshots(db_session, retention_days, keep_last_n)
    return sorted(
        (now - s.created_at).days for s in prunable if s.session_id == session_id
    )


def test_keeps_latest_even_when_ancient(db_session: Session) -> None:
    session_id = _make_session_with_snapshots(db_session, [400])
    assert _pruned_ages(db_session, session_id, retention_days=30, keep_last_n=3) == []


def test_hard_caps_at_keep_last_n(db_session: Session) -> None:
    session_id = _make_session_with_snapshots(db_session, [0, 1, 2, 3])
    # keep newest 2; ages 2 and 3 prune despite being recent.
    assert _pruned_ages(db_session, session_id, retention_days=30, keep_last_n=2) == [
        2,
        3,
    ]


def test_expires_old_within_cap_but_keeps_anchor(db_session: Session) -> None:
    session_id = _make_session_with_snapshots(db_session, [40, 35, 31])
    # all older than retention, but the newest (31d) is the kept anchor.
    assert _pruned_ages(db_session, session_id, retention_days=30, keep_last_n=10) == [
        35,
        40,
    ]


def test_recent_within_cap_are_kept(db_session: Session) -> None:
    session_id = _make_session_with_snapshots(db_session, [0, 5, 10])
    assert _pruned_ages(db_session, session_id, retention_days=30, keep_last_n=10) == []
