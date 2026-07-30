from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.db.models import BuildSession
from onyx.db.slack_session_link import get_link_for_session
from onyx.db.slack_session_link import get_session_id_for_slack_thread
from onyx.db.slack_session_link import insert_slack_session_link


def _make_build_session(db_session: Session) -> BuildSession:
    session = BuildSession(id=uuid4())
    db_session.add(session)
    db_session.commit()
    return session


def _random_thread_ts() -> str:
    return f"{uuid4().int % 10_000_000_000}.{uuid4().int % 1_000_000:06d}"


def test_insert_and_lookup_by_thread_and_session(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    build_session = _make_build_session(db_session)
    team_id, channel_id, thread_ts = f"T-{uuid4()}", f"C-{uuid4()}", _random_thread_ts()

    link = insert_slack_session_link(
        db_session,
        slack_team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
        build_session_id=build_session.id,
    )
    assert link.build_session_id == build_session.id

    found_id = get_session_id_for_slack_thread(
        db_session,
        slack_team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
    )
    assert found_id == build_session.id

    reverse_link = get_link_for_session(db_session, build_session.id)
    assert reverse_link is not None
    assert reverse_link.slack_team_id == team_id
    assert reverse_link.channel_id == channel_id
    assert reverse_link.thread_ts == thread_ts


def test_lookup_miss_returns_none(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    assert (
        get_session_id_for_slack_thread(
            db_session,
            slack_team_id=f"T-{uuid4()}",
            channel_id=f"C-{uuid4()}",
            thread_ts=_random_thread_ts(),
        )
        is None
    )
    assert get_link_for_session(db_session, uuid4()) is None


def test_duplicate_thread_raises_integrity_error(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    session_a = _make_build_session(db_session)
    session_b = _make_build_session(db_session)
    team_id, channel_id, thread_ts = f"T-{uuid4()}", f"C-{uuid4()}", _random_thread_ts()

    insert_slack_session_link(
        db_session,
        slack_team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
        build_session_id=session_a.id,
    )

    with pytest.raises(IntegrityError):
        insert_slack_session_link(
            db_session,
            slack_team_id=team_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            build_session_id=session_b.id,
        )

    assert (
        get_session_id_for_slack_thread(
            db_session,
            slack_team_id=team_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
        )
        == session_a.id
    )


def test_same_thread_ts_different_channel_succeeds(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """The unique constraint is composite over all three columns, not just
    thread_ts, so the same thread_ts under a different team/channel is fine."""
    session_a = _make_build_session(db_session)
    session_b = _make_build_session(db_session)
    shared_thread_ts = _random_thread_ts()
    team_a, channel_a = f"T-{uuid4()}", f"C-{uuid4()}"
    team_b, channel_b = f"T-{uuid4()}", f"C-{uuid4()}"

    insert_slack_session_link(
        db_session,
        slack_team_id=team_a,
        channel_id=channel_a,
        thread_ts=shared_thread_ts,
        build_session_id=session_a.id,
    )
    insert_slack_session_link(
        db_session,
        slack_team_id=team_b,
        channel_id=channel_b,
        thread_ts=shared_thread_ts,
        build_session_id=session_b.id,
    )

    assert (
        get_session_id_for_slack_thread(
            db_session,
            slack_team_id=team_a,
            channel_id=channel_a,
            thread_ts=shared_thread_ts,
        )
        == session_a.id
    )
    assert (
        get_session_id_for_slack_thread(
            db_session,
            slack_team_id=team_b,
            channel_id=channel_b,
            thread_ts=shared_thread_ts,
        )
        == session_b.id
    )


def test_duplicate_build_session_raises_integrity_error(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    build_session = _make_build_session(db_session)
    team_a, channel_a, thread_ts_a = (
        f"T-{uuid4()}",
        f"C-{uuid4()}",
        _random_thread_ts(),
    )
    team_b, channel_b, thread_ts_b = (
        f"T-{uuid4()}",
        f"C-{uuid4()}",
        _random_thread_ts(),
    )

    insert_slack_session_link(
        db_session,
        slack_team_id=team_a,
        channel_id=channel_a,
        thread_ts=thread_ts_a,
        build_session_id=build_session.id,
    )

    with pytest.raises(IntegrityError):
        insert_slack_session_link(
            db_session,
            slack_team_id=team_b,
            channel_id=channel_b,
            thread_ts=thread_ts_b,
            build_session_id=build_session.id,
        )

    assert (
        get_session_id_for_slack_thread(
            db_session,
            slack_team_id=team_a,
            channel_id=channel_a,
            thread_ts=thread_ts_a,
        )
        == build_session.id
    )
