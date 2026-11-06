"""External dependency unit tests for the full-run guard during a port-flow
reindex: a crawl from the beginning or a backfill on PRESENT adds documents an
incremental FUTURE catch-up never fetches, so the connector endpoints refuse them
while a port-flow FUTURE exists, and a reindex refuses to start while one is
running (see `raise_if_port_reindex_in_progress` and
`cc_pairs_with_full_run_in_progress`); a queued one waits in the beat.
"""

from collections.abc import Generator
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docprocessing.tasks import (
    _kickoff_indexing_tasks,
)
from onyx.connectors.edit_plan.apply import _ensure_no_full_run_during_reindex
from onyx.connectors.edit_plan.models import EditStep, EditStepKind
from onyx.db.backfill_models import BackfillSpec
from onyx.db.connector_edit_requests import request_backfills__no_commit
from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.enums import IndexingMode, IndexingStatus, SwitchoverType
from onyx.db.models import IndexAttempt, SearchSettings
from onyx.db.search_settings import (
    REINDEX_BLOCKS_FULL_RUN_MESSAGE,
    cc_pairs_with_full_run_in_progress,
    get_current_search_settings,
    raise_if_port_reindex_in_progress,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import get_redis_client
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
    make_future_search_settings,
)


@pytest.fixture
def legacy_future(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[SearchSettings, None, None]:
    future = make_future_search_settings(db_session, use_port_flow=False)
    try:
        yield future
    finally:
        db_session.rollback()
        db_session.delete(future)
        db_session.commit()


def _step(kind: EditStepKind) -> EditStep:
    return EditStep(kind=kind, required=False, reasons=[])


def test_full_runs_are_refused_only_during_a_port_flow_reindex(
    db_session: Session, legacy_future: SearchSettings
) -> None:
    # A legacy FUTURE crawls from scratch and needs no guard.
    raise_if_port_reindex_in_progress(db_session)

    legacy_future.use_port_flow = True
    db_session.commit()
    with pytest.raises(OnyxError) as excinfo:
        raise_if_port_reindex_in_progress(db_session)
    assert excinfo.value.error_code == OnyxErrorCode.CONFLICT
    assert REINDEX_BLOCKS_FULL_RUN_MESSAGE in str(excinfo.value.detail)

    # ACTIVE_ONLY ports too; INSTANT promotes at once and leaves no FUTURE row.
    legacy_future.switchover_type = SwitchoverType.ACTIVE_ONLY
    db_session.commit()
    with pytest.raises(OnyxError):
        raise_if_port_reindex_in_progress(db_session)


def test_edit_steps_that_recrawl_are_refused_during_a_port_flow_reindex(
    db_session: Session, legacy_future: SearchSettings
) -> None:
    legacy_future.use_port_flow = True
    db_session.commit()

    for kind in (
        EditStepKind.FULL_REINDEX,
        EditStepKind.FULL_REINDEX_THEN_PRUNE,
        EditStepKind.SCOPED_BACKFILL,
        EditStepKind.WINDOW_BACKFILL,
    ):
        with pytest.raises(OnyxError):
            _ensure_no_full_run_during_reindex(
                db_session, [_step(EditStepKind.PRUNE), _step(kind)]
            )

    # Incremental and metadata-only steps go through.
    _ensure_no_full_run_during_reindex(
        db_session,
        [
            _step(EditStepKind.RESTART_ATTEMPT),
            _step(EditStepKind.PRUNE),
            _step(EditStepKind.ACCESS_TYPE),
        ],
    )


def test_cc_pairs_with_full_run_in_progress(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """A reindex refuses to start while a connector runs or has queued an
    attempt from the beginning or a backfill attempt. A queued request alone
    (trigger, full re-index request) does not count: the beat holds it."""
    pair = make_cc_pair(db_session)
    present_id = get_current_search_settings(db_session).id
    try:

        def running() -> list[int]:
            db_session.expire_all()
            return [
                cc_pair_id
                for cc_pair_id, _ in cc_pairs_with_full_run_in_progress(
                    db_session, present_id
                )
                if cc_pair_id == pair.id
            ]

        pair.indexing_trigger = IndexingMode.REINDEX
        pair.full_reindex_requested_at = get_db_current_time(db_session)
        db_session.commit()
        assert running() == []

        attempt = IndexAttempt(
            connector_credential_pair_id=pair.id,
            search_settings_id=present_id,
            status=IndexingStatus.NOT_STARTED,
            from_beginning=True,
        )
        db_session.add(attempt)
        db_session.commit()
        assert running() == [pair.id]
        attempt.from_beginning = False
        attempt.is_backfill = True
        attempt.status = IndexingStatus.IN_PROGRESS
        db_session.commit()
        assert running() == [pair.id]
        attempt.status = IndexingStatus.SUCCESS
        attempt.time_finished = get_db_current_time(db_session)
        db_session.commit()
        assert running() == []
    finally:
        db_session.rollback()
        db_session.execute(
            delete(IndexAttempt).where(
                IndexAttempt.connector_credential_pair_id == pair.id
            )
        )
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


def test_the_beat_leaves_a_full_run_pending_during_a_port_flow_reindex(
    db_session: Session, legacy_future: SearchSettings
) -> None:
    """A REINDEX trigger that exists while a port-flow reindex builds FUTURE is
    left as it is: no attempt, trigger untouched. Once no port-flow FUTURE
    exists, the beat consumes it as usual."""
    legacy_future.use_port_flow = True
    db_session.commit()
    pair = make_cc_pair(db_session)
    present = get_current_search_settings(db_session)
    attempts = (
        select(func.count())
        .select_from(IndexAttempt)
        .where(IndexAttempt.connector_credential_pair_id == pair.id)
    )

    def beat() -> None:
        db_session.expire_all()
        _kickoff_indexing_tasks(
            celery_app=MagicMock(),
            db_session=db_session,
            search_settings=present,
            cc_pair_ids=[pair.id],
            secondary_index_building=False,
            redis_client=get_redis_client(),
            lock_beat=MagicMock(),
            tenant_id=get_current_tenant_id(),
        )
        db_session.expire_all()

    try:
        pair.indexing_trigger = IndexingMode.REINDEX
        db_session.commit()
        beat()
        assert db_session.scalar(attempts) == 0
        assert pair.indexing_trigger == IndexingMode.REINDEX

        legacy_future.use_port_flow = False
        db_session.commit()
        beat()
        assert db_session.scalar(attempts) == 1
        assert pair.indexing_trigger is None
    finally:
        db_session.rollback()
        db_session.execute(
            delete(IndexAttempt).where(
                IndexAttempt.connector_credential_pair_id == pair.id
            )
        )
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


def test_the_beat_leaves_a_pending_backfill_during_a_port_flow_reindex(
    db_session: Session, legacy_future: SearchSettings
) -> None:
    legacy_future.use_port_flow = True
    db_session.commit()
    pair = make_cc_pair(db_session)
    present = get_current_search_settings(db_session)
    now = get_db_current_time(db_session)
    # An earlier successful run, so the beat has no regular run to start
    # (no refresh schedule) and only the backfill is up.
    db_session.add(
        IndexAttempt(
            connector_credential_pair_id=pair.id,
            search_settings_id=present.id,
            status=IndexingStatus.SUCCESS,
            from_beginning=False,
            time_started=now,
            time_finished=now,
        )
    )
    request_backfills__no_commit(
        db_session,
        pair.id,
        [BackfillSpec(window_start=now - timedelta(days=2), window_end=now)],
        requested_at=now,
    )
    db_session.commit()
    attempts = (
        select(IndexAttempt)
        .where(IndexAttempt.connector_credential_pair_id == pair.id)
        .order_by(IndexAttempt.id)
    )

    def beat() -> list[IndexAttempt]:
        db_session.expire_all()
        _kickoff_indexing_tasks(
            celery_app=MagicMock(),
            db_session=db_session,
            search_settings=present,
            cc_pair_ids=[pair.id],
            secondary_index_building=False,
            redis_client=get_redis_client(),
            lock_beat=MagicMock(),
            tenant_id=get_current_tenant_id(),
        )
        db_session.expire_all()
        return list(db_session.scalars(attempts))

    try:
        assert [attempt.is_backfill for attempt in beat()] == [False]
        legacy_future.use_port_flow = False
        db_session.commit()
        assert [attempt.is_backfill for attempt in beat()] == [False, True]
    finally:
        db_session.rollback()
        db_session.execute(
            delete(IndexAttempt).where(
                IndexAttempt.connector_credential_pair_id == pair.id
            )
        )
        db_session.commit()
        cleanup_cc_pair(db_session, pair)
