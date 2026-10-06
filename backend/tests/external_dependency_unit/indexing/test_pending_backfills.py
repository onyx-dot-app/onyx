"""Backfills an applied edit leaves on a cc-pair: the indexing beat creates
them one at a time, only while the pair is ACTIVE with no active attempt and
no pending trigger, and drops each request once its attempt succeeds. A
failed attempt is retried after a backoff. A full re-index covers the
backfills requested before it, and a restart releases a stopped backfill
without a backoff."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docprocessing.tasks import _kickoff_indexing_tasks
from onyx.db.backfill_models import BackfillSpec
from onyx.db.connector_edit_requests import (
    request_attempt_restart__no_commit,
    request_backfills__no_commit,
)
from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.enums import ConnectorCredentialPairStatus, IndexingMode, IndexingStatus
from onyx.db.models import ConnectorCredentialPair, IndexAttempt, SearchSettings
from onyx.db.search_settings import get_current_search_settings
from onyx.redis.redis_pool import get_redis_client
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_START = datetime(2025, 1, 1, tzinfo=timezone.utc)
_END = datetime(2026, 1, 1, tzinfo=timezone.utc)
_SCOPED_CONFIG: dict[str, Any] = {"channels": ["new"]}


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    try:
        yield pair
    finally:
        db_session.rollback()
        db_session.execute(
            delete(IndexAttempt).where(
                IndexAttempt.connector_credential_pair_id == pair.id
            )
        )
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


@pytest.fixture
def search_settings(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> SearchSettings:
    return get_current_search_settings(db_session)


def _scoped() -> BackfillSpec:
    return BackfillSpec(
        window_start=_START, window_end=_END, connector_config_override=_SCOPED_CONFIG
    )


def _window() -> BackfillSpec:
    return BackfillSpec(window_start=_START - timedelta(days=30), window_end=_START)


def _request(
    db_session: Session, cc_pair: ConnectorCredentialPair, *backfills: BackfillSpec
) -> None:
    request_backfills__no_commit(
        db_session, cc_pair.id, list(backfills), get_db_current_time(db_session)
    )
    db_session.commit()


def _run_beat(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    db_session.expire_all()
    _kickoff_indexing_tasks(
        celery_app=MagicMock(),
        db_session=db_session,
        search_settings=search_settings,
        cc_pair_ids=[cc_pair.id],
        secondary_index_building=False,
        redis_client=get_redis_client(),
        lock_beat=MagicMock(),
        tenant_id=get_current_tenant_id(),
    )
    db_session.expire_all()


def _attempts(db_session: Session, cc_pair_id: int) -> list[IndexAttempt]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(IndexAttempt)
            .where(IndexAttempt.connector_credential_pair_id == cc_pair_id)
            .order_by(IndexAttempt.id)
        ).all()
    )


def _finish(
    db_session: Session,
    attempt: IndexAttempt,
    status: IndexingStatus = IndexingStatus.SUCCESS,
) -> None:
    attempt.status = status
    db_session.commit()


def _backfills(db_session: Session, cc_pair_id: int) -> list[IndexAttempt]:
    return [
        attempt for attempt in _attempts(db_session, cc_pair_id) if attempt.is_backfill
    ]


def _index_once(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    """A finished normal run, so the pair is not due without refresh_freq."""
    db_session.add(
        IndexAttempt(
            connector_credential_pair_id=cc_pair.id,
            search_settings_id=search_settings.id,
            from_beginning=False,
            status=IndexingStatus.SUCCESS,
        )
    )
    db_session.commit()


def _end_backoffs(db_session: Session, cc_pair: ConnectorCredentialPair) -> None:
    past = get_db_current_time(db_session) - timedelta(seconds=1)
    cc_pair.pending_backfills = [
        pending.model_copy(update={"retry_after": past})
        if pending.retry_after is not None
        else pending
        for pending in cc_pair.pending_backfills
    ]
    db_session.commit()


def test_backfill_waits_for_an_active_free_pair(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    _request(db_session, cc_pair, _scoped())

    cc_pair.status = ConnectorCredentialPairStatus.PAUSED
    db_session.commit()
    _run_beat(db_session, cc_pair, search_settings)
    assert _attempts(db_session, cc_pair.id) == []
    assert len(cc_pair.pending_backfills) == 1

    cc_pair.status = ConnectorCredentialPairStatus.ACTIVE
    running = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=search_settings.id,
        from_beginning=False,
        status=IndexingStatus.IN_PROGRESS,
        celery_task_id=f"pending_backfill_{uuid4().hex[:8]}",
    )
    db_session.add(running)
    db_session.commit()
    _run_beat(db_session, cc_pair, search_settings)
    assert [attempt.id for attempt in _attempts(db_session, cc_pair.id)] == [running.id]
    assert len(cc_pair.pending_backfills) == 1

    _finish(db_session, running)
    _run_beat(db_session, cc_pair, search_settings)

    [_, backfill] = _attempts(db_session, cc_pair.id)
    assert backfill.is_backfill
    assert backfill.poll_range_start == _START
    assert backfill.poll_range_end == _END
    assert backfill.connector_config_override == _SCOPED_CONFIG
    [tracked] = cc_pair.pending_backfills
    assert tracked.attempt_id == backfill.id

    _finish(db_session, backfill, IndexingStatus.COMPLETED_WITH_ERRORS)
    _run_beat(db_session, cc_pair, search_settings)
    assert cc_pair.pending_backfills == []
    # A settled request starts no new attempt.
    assert len(_attempts(db_session, cc_pair.id)) == 2


def test_a_pending_trigger_runs_first(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    _request(db_session, cc_pair, _scoped())
    cc_pair.indexing_trigger = IndexingMode.UPDATE
    db_session.commit()

    _run_beat(db_session, cc_pair, search_settings)

    [normal] = _attempts(db_session, cc_pair.id)
    assert not normal.is_backfill
    assert len(cc_pair.pending_backfills) == 1

    _finish(db_session, normal)
    _run_beat(db_session, cc_pair, search_settings)
    backfill = _attempts(db_session, cc_pair.id)[-1]
    assert backfill.is_backfill
    [tracked] = cc_pair.pending_backfills
    assert tracked.attempt_id == backfill.id


def test_several_backfills_run_one_at_a_time_in_order(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    _request(db_session, cc_pair, _scoped(), _window())

    _run_beat(db_session, cc_pair, search_settings)
    [first] = _attempts(db_session, cc_pair.id)
    assert first.connector_config_override == _SCOPED_CONFIG
    assert len(cc_pair.pending_backfills) == 2

    # The first one is still active.
    _run_beat(db_session, cc_pair, search_settings)
    assert len(_attempts(db_session, cc_pair.id)) == 1

    _finish(db_session, first)
    _run_beat(db_session, cc_pair, search_settings)
    [_, second] = _attempts(db_session, cc_pair.id)
    assert second.is_backfill
    assert second.poll_range_end == _START
    assert second.connector_config_override is None
    [tracked] = cc_pair.pending_backfills
    assert tracked.attempt_id == second.id

    _finish(db_session, second)
    _run_beat(db_session, cc_pair, search_settings)
    assert cc_pair.pending_backfills == []


def test_a_full_reindex_covers_earlier_backfills(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    _request(db_session, cc_pair, _scoped())
    # Requested after the re-index is created, so it is not covered.
    request_backfills__no_commit(
        db_session,
        cc_pair.id,
        [_window()],
        get_db_current_time(db_session) + timedelta(hours=1),
    )
    cc_pair.indexing_trigger = IndexingMode.REINDEX
    db_session.commit()

    _run_beat(db_session, cc_pair, search_settings)

    [reindex] = _attempts(db_session, cc_pair.id)
    assert reindex.from_beginning
    assert not reindex.is_backfill
    [kept] = cc_pair.pending_backfills
    assert kept.backfill.connector_config_override is None


def test_a_restart_puts_a_running_backfill_back(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    _request(db_session, cc_pair, _scoped())
    [requested] = cc_pair.pending_backfills
    _run_beat(db_session, cc_pair, search_settings)
    [backfill] = _attempts(db_session, cc_pair.id)
    assert cc_pair.pending_backfills[0].attempt_id == backfill.id

    request_attempt_restart__no_commit(db_session, cc_pair.id, IndexingMode.UPDATE)
    db_session.commit()
    db_session.expire_all()

    assert backfill.cancellation_requested
    # Released with no failure, so it runs again with no backoff.
    assert cc_pair.pending_backfills == [requested]

    # The canceled attempt is not a failure of the request.
    _finish(db_session, backfill, IndexingStatus.CANCELED)
    _run_beat(db_session, cc_pair, search_settings)
    [_, restart_run] = _attempts(db_session, cc_pair.id)
    assert not restart_run.is_backfill
    _finish(db_session, restart_run)
    _run_beat(db_session, cc_pair, search_settings)
    [_, _, rerun] = _attempts(db_session, cc_pair.id)
    assert rerun.is_backfill
    [tracked] = cc_pair.pending_backfills
    assert tracked.attempt_id == rerun.id
    assert tracked.failure_count == 0


def test_a_failed_backfill_is_retried_after_a_backoff(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    _index_once(db_session, cc_pair, search_settings)
    _request(db_session, cc_pair, _scoped())
    _run_beat(db_session, cc_pair, search_settings)
    [first] = _backfills(db_session, cc_pair.id)

    _finish(db_session, first, IndexingStatus.FAILED)
    before = get_db_current_time(db_session)
    _run_beat(db_session, cc_pair, search_settings)

    # The request stays, in a 5 minute backoff, and the beat waits.
    [failed] = cc_pair.pending_backfills
    assert failed.attempt_id is None
    assert failed.failure_count == 1
    assert failed.retry_after is not None
    assert (
        before + timedelta(minutes=5)
        <= failed.retry_after
        <= before + timedelta(minutes=6)
    )
    assert [attempt.id for attempt in _backfills(db_session, cc_pair.id)] == [first.id]

    _end_backoffs(db_session, cc_pair)
    _run_beat(db_session, cc_pair, search_settings)
    [_, retry] = _backfills(db_session, cc_pair.id)
    assert retry.is_backfill
    assert retry.connector_config_override == _SCOPED_CONFIG

    # A second failure doubles the backoff.
    _finish(db_session, retry, IndexingStatus.FAILED)
    before = get_db_current_time(db_session)
    _run_beat(db_session, cc_pair, search_settings)
    [failed_again] = cc_pair.pending_backfills
    assert failed_again.failure_count == 2
    assert failed_again.retry_after is not None
    assert failed_again.retry_after >= before + timedelta(minutes=10)

    _end_backoffs(db_session, cc_pair)
    _run_beat(db_session, cc_pair, search_settings)
    [_, _, last] = _backfills(db_session, cc_pair.id)
    _finish(db_session, last)
    _run_beat(db_session, cc_pair, search_settings)
    assert cc_pair.pending_backfills == []


def test_a_backfill_in_backoff_does_not_hold_back_later_ones(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    _index_once(db_session, cc_pair, search_settings)
    _request(db_session, cc_pair, _scoped(), _window())
    _run_beat(db_session, cc_pair, search_settings)
    [first] = _backfills(db_session, cc_pair.id)
    assert first.connector_config_override == _SCOPED_CONFIG

    _finish(db_session, first, IndexingStatus.FAILED)
    # One beat settles the failure and starts the next request.
    _run_beat(db_session, cc_pair, search_settings)
    [_, second] = _backfills(db_session, cc_pair.id)
    assert second.poll_range_end == _START
    assert second.connector_config_override is None
    [in_backoff, running] = cc_pair.pending_backfills
    assert in_backoff.failure_count == 1
    assert in_backoff.attempt_id is None
    assert running.attempt_id == second.id

    # The first one still waits for its backoff.
    _finish(db_session, second)
    _run_beat(db_session, cc_pair, search_settings)
    assert len(_backfills(db_session, cc_pair.id)) == 2
    assert cc_pair.pending_backfills == [in_backoff]

    _end_backoffs(db_session, cc_pair)
    _run_beat(db_session, cc_pair, search_settings)
    [_, _, retry] = _backfills(db_session, cc_pair.id)
    assert retry.connector_config_override == _SCOPED_CONFIG
