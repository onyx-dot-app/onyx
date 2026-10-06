"""Backfills an applied edit leaves on a cc-pair: the indexing beat creates
them one at a time, only while the pair is ACTIVE with no active attempt and
no pending trigger, and drops each request once its attempt exists. A full
re-index covers the backfills requested before it, and a restart puts a
stopped backfill back on the list."""

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


def _finish(db_session: Session, attempt: IndexAttempt) -> None:
    attempt.status = IndexingStatus.SUCCESS
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
    assert cc_pair.pending_backfills == []


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
    assert _attempts(db_session, cc_pair.id)[-1].is_backfill
    assert cc_pair.pending_backfills == []


def test_several_backfills_run_one_at_a_time_in_order(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> None:
    _request(db_session, cc_pair, _scoped(), _window())

    _run_beat(db_session, cc_pair, search_settings)
    [first] = _attempts(db_session, cc_pair.id)
    assert first.connector_config_override == _SCOPED_CONFIG
    assert len(cc_pair.pending_backfills) == 1

    # The first one is still active.
    _run_beat(db_session, cc_pair, search_settings)
    assert len(_attempts(db_session, cc_pair.id)) == 1

    _finish(db_session, first)
    _run_beat(db_session, cc_pair, search_settings)
    [_, second] = _attempts(db_session, cc_pair.id)
    assert second.is_backfill
    assert second.poll_range_end == _START
    assert second.connector_config_override is None
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
    _run_beat(db_session, cc_pair, search_settings)
    [backfill] = _attempts(db_session, cc_pair.id)
    assert cc_pair.pending_backfills == []

    request_attempt_restart__no_commit(db_session, cc_pair.id, IndexingMode.UPDATE)
    db_session.commit()
    db_session.expire_all()

    assert backfill.cancellation_requested
    [requeued] = cc_pair.pending_backfills
    assert requeued.backfill == _scoped()
    assert requeued.requested_at == backfill.time_created
