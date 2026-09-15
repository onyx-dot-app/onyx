"""External dependency unit tests for the `targeted_reindex_job_id IS NULL`
filter on IndexAttempt consumer queries.

Validates that synthetic targeted-reindex attempts don't bleed into freshness,
scheduling, or counting queries that should only see real full-crawl attempts,
while cleanup/cancellation paths still see both.
"""

from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from onyx.db.connector_credential_pair import get_last_successful_attempt_poll_range_end
from onyx.db.enums import IndexingStatus
from onyx.db.index_attempt import (
    cancel_indexing_attempts_for_ccpair,
    count_index_attempts_for_cc_pair,
    count_unique_active_cc_pairs_with_successful_index_attempts,
    count_unique_cc_pairs_with_successful_index_attempts,
    get_in_progress_index_attempts,
    get_index_attempts_for_cc_pair,
    get_last_attempt,
    get_last_attempt_for_cc_pair,
    get_latest_index_attempt_for_cc_pair_id,
    get_latest_index_attempts,
    get_latest_index_attempts_by_status,
    get_latest_successful_index_attempt_for_cc_pair_id,
    get_latest_successful_index_attempts_parallel,
    get_paginated_index_attempts_for_cc_pair_id,
    get_recent_attempts_for_cc_pair,
    get_recent_completed_attempts_for_cc_pair,
)
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.db.models import ConnectorCredentialPair, IndexAttempt, TargetedReindexJob
from onyx.db.search_settings import get_current_search_settings
from onyx.server.documents.models import ConnectorCredentialPairIdentifier
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    try:
        yield pair
    finally:
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == pair.id
        ).delete(synchronize_session="fetch")
        db_session.query(TargetedReindexJob).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


def _make_attempt(
    db_session: Session,
    cc_pair_id: int,
    search_settings_id: int,
    *,
    status: IndexingStatus,
    targeted_reindex_job_id: int | None = None,
) -> IndexAttempt:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair_id,
        search_settings_id=search_settings_id,
        from_beginning=False,
        status=status,
        targeted_reindex_job_id=targeted_reindex_job_id,
    )
    db_session.add(attempt)
    db_session.commit()
    db_session.refresh(attempt)
    return attempt


def _make_targeted_job(db_session: Session) -> TargetedReindexJob:
    job = TargetedReindexJob()
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def test_get_last_attempt_skips_targeted_reindex(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """A more recent targeted-reindex attempt should not displace the
    latest full-run attempt for `last indexed` UI."""
    settings = get_current_search_settings(db_session)
    full_run = _make_attempt(
        db_session, cc_pair.id, settings.id, status=IndexingStatus.SUCCESS
    )
    job = _make_targeted_job(db_session)
    _make_attempt(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.SUCCESS,
        targeted_reindex_job_id=job.id,
    )

    result = get_last_attempt_for_cc_pair(cc_pair.id, settings.id, db_session)

    assert result is not None
    assert result.id == full_run.id


def test_get_latest_successful_skips_targeted_reindex(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    settings = get_current_search_settings(db_session)
    full_run = _make_attempt(
        db_session, cc_pair.id, settings.id, status=IndexingStatus.SUCCESS
    )
    job = _make_targeted_job(db_session)
    _make_attempt(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.SUCCESS,
        targeted_reindex_job_id=job.id,
    )

    result = get_latest_successful_index_attempt_for_cc_pair_id(db_session, cc_pair.id)

    assert result is not None
    assert result.id == full_run.id


def test_get_latest_index_attempt_for_cc_pair_skips_targeted(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    settings = get_current_search_settings(db_session)
    full_run = _make_attempt(
        db_session, cc_pair.id, settings.id, status=IndexingStatus.SUCCESS
    )
    job = _make_targeted_job(db_session)
    _make_attempt(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.SUCCESS,
        targeted_reindex_job_id=job.id,
    )

    result = get_latest_index_attempt_for_cc_pair_id(
        db_session, cc_pair.id, secondary_index=False, only_finished=True
    )

    assert result is not None
    assert result.id == full_run.id


def test_count_index_attempts_for_cc_pair_skips_targeted(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    settings = get_current_search_settings(db_session)
    _make_attempt(db_session, cc_pair.id, settings.id, status=IndexingStatus.SUCCESS)
    _make_attempt(db_session, cc_pair.id, settings.id, status=IndexingStatus.FAILED)
    job = _make_targeted_job(db_session)
    _make_attempt(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.SUCCESS,
        targeted_reindex_job_id=job.id,
    )

    count = count_index_attempts_for_cc_pair(db_session, cc_pair.id)

    assert count == 2


def test_get_recent_attempts_skips_targeted(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    settings = get_current_search_settings(db_session)
    full_run = _make_attempt(
        db_session, cc_pair.id, settings.id, status=IndexingStatus.SUCCESS
    )
    job = _make_targeted_job(db_session)
    _make_attempt(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.SUCCESS,
        targeted_reindex_job_id=job.id,
    )

    results = get_recent_attempts_for_cc_pair(
        cc_pair.id, settings.id, limit=10, db_session=db_session
    )

    assert [a.id for a in results] == [full_run.id]


def test_fence_blocks_second_full_run_but_ignores_targeted(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """Two assertions on the fence's filtering behaviour:

    1. With a full run in progress, a second full run is blocked.
    2. A targeted reindex sitting on the same cc_pair does NOT make the
       fence think a full run is in progress (covered by the symmetric
       test below — this test just sets up the precondition).

    The targeted reindex creation path itself is not exercised here — that
    path bypasses the fence entirely (PR 3 lands the API + retry task that
    inserts targeted attempts directly)."""
    settings = get_current_search_settings(db_session)
    _make_attempt(
        db_session, cc_pair.id, settings.id, status=IndexingStatus.IN_PROGRESS
    )
    job = _make_targeted_job(db_session)
    _make_attempt(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.IN_PROGRESS,
        targeted_reindex_job_id=job.id,
    )

    # A second full run gets blocked by the in-progress full run.
    blocked = IndexingCoordination.try_create_index_attempt(
        db_session=db_session,
        cc_pair_id=cc_pair.id,
        search_settings_id=settings.id,
        celery_task_id="test-task-id",
    )
    assert blocked is None


def test_fence_allows_full_run_when_only_targeted_in_progress(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """A targeted reindex in progress should not block a full run from
    being created."""
    settings = get_current_search_settings(db_session)
    job = _make_targeted_job(db_session)
    _make_attempt(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.IN_PROGRESS,
        targeted_reindex_job_id=job.id,
    )

    new_attempt_id = IndexingCoordination.try_create_index_attempt(
        db_session=db_session,
        cc_pair_id=cc_pair.id,
        search_settings_id=settings.id,
        celery_task_id="test-task-id-2",
    )

    assert new_attempt_id is not None


def test_cancel_includes_targeted_attempts(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """Cancellation must NOT filter — both full-run and targeted attempts
    on the cc_pair get canceled together."""
    settings = get_current_search_settings(db_session)
    full_run = _make_attempt(
        db_session, cc_pair.id, settings.id, status=IndexingStatus.NOT_STARTED
    )
    job = _make_targeted_job(db_session)
    targeted = _make_attempt(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.NOT_STARTED,
        targeted_reindex_job_id=job.id,
    )

    cancel_indexing_attempts_for_ccpair(cc_pair.id, db_session)
    db_session.commit()

    db_session.refresh(full_run)
    db_session.refresh(targeted)
    assert full_run.status == IndexingStatus.CANCELED
    assert targeted.status == IndexingStatus.CANCELED


def test_in_progress_query_includes_both(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """get_in_progress_index_attempts is used by watchdog/heartbeat — it
    must see both attempt types so retry attempts are also monitored."""
    settings = get_current_search_settings(db_session)
    full_run = _make_attempt(
        db_session, cc_pair.id, settings.id, status=IndexingStatus.IN_PROGRESS
    )
    job = _make_targeted_job(db_session)
    targeted = _make_attempt(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.IN_PROGRESS,
        targeted_reindex_job_id=job.id,
    )

    in_progress = get_in_progress_index_attempts(cc_pair.connector_id, db_session)

    ids = {a.id for a in in_progress}
    assert full_run.id in ids
    assert targeted.id in ids


def test_get_recent_completed_attempts_skips_targeted(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    settings = get_current_search_settings(db_session)
    full_run = _make_attempt(
        db_session, cc_pair.id, settings.id, status=IndexingStatus.SUCCESS
    )
    job = _make_targeted_job(db_session)
    _make_attempt(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.SUCCESS,
        targeted_reindex_job_id=job.id,
    )

    results = get_recent_completed_attempts_for_cc_pair(
        cc_pair.id, settings.id, limit=10, db_session=db_session
    )

    assert [a.id for a in results] == [full_run.id]


def test_get_last_attempt_skips_targeted(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    settings = get_current_search_settings(db_session)
    full_run = _make_attempt(
        db_session, cc_pair.id, settings.id, status=IndexingStatus.SUCCESS
    )
    job = _make_targeted_job(db_session)
    _make_attempt(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.SUCCESS,
        targeted_reindex_job_id=job.id,
    )

    result = get_last_attempt(
        cc_pair.connector_id, cc_pair.credential_id, settings.id, db_session
    )

    assert result is not None
    assert result.id == full_run.id


def test_get_latest_index_attempts_by_status_skips_targeted(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    settings = get_current_search_settings(db_session)
    full_run = _make_attempt(
        db_session, cc_pair.id, settings.id, status=IndexingStatus.FAILED
    )
    job = _make_targeted_job(db_session)
    _make_attempt(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.FAILED,
        targeted_reindex_job_id=job.id,
    )

    results = get_latest_index_attempts_by_status(
        secondary_index=False, db_session=db_session, status=IndexingStatus.FAILED
    )

    matching = [a for a in results if a.connector_credential_pair_id == cc_pair.id]
    assert len(matching) == 1
    assert matching[0].id == full_run.id


def test_get_latest_index_attempts_skips_targeted(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    settings = get_current_search_settings(db_session)
    full_run = _make_attempt(
        db_session, cc_pair.id, settings.id, status=IndexingStatus.SUCCESS
    )
    job = _make_targeted_job(db_session)
    _make_attempt(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.SUCCESS,
        targeted_reindex_job_id=job.id,
    )

    results = get_latest_index_attempts(secondary_index=False, db_session=db_session)

    matching = [a for a in results if a.connector_credential_pair_id == cc_pair.id]
    assert len(matching) == 1
    assert matching[0].id == full_run.id


def test_get_latest_successful_parallel_skips_targeted(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    settings = get_current_search_settings(db_session)
    full_run = _make_attempt(
        db_session, cc_pair.id, settings.id, status=IndexingStatus.SUCCESS
    )
    job = _make_targeted_job(db_session)
    _make_attempt(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.SUCCESS,
        targeted_reindex_job_id=job.id,
    )

    results = get_latest_successful_index_attempts_parallel(secondary_index=False)

    matching = [a for a in results if a.connector_credential_pair_id == cc_pair.id]
    assert len(matching) == 1
    assert matching[0].id == full_run.id


def test_get_paginated_index_attempts_skips_targeted(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    settings = get_current_search_settings(db_session)
    full_run = _make_attempt(
        db_session, cc_pair.id, settings.id, status=IndexingStatus.SUCCESS
    )
    job = _make_targeted_job(db_session)
    _make_attempt(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.SUCCESS,
        targeted_reindex_job_id=job.id,
    )

    results = get_paginated_index_attempts_for_cc_pair_id(
        db_session, cc_pair.id, page=0, page_size=10
    )

    assert [a.id for a in results] == [full_run.id]


def test_get_index_attempts_for_cc_pair_skips_targeted(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    settings = get_current_search_settings(db_session)
    full_run = _make_attempt(
        db_session, cc_pair.id, settings.id, status=IndexingStatus.SUCCESS
    )
    job = _make_targeted_job(db_session)
    _make_attempt(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.SUCCESS,
        targeted_reindex_job_id=job.id,
    )

    identifier = ConnectorCredentialPairIdentifier(
        connector_id=cc_pair.connector_id, credential_id=cc_pair.credential_id
    )
    results = get_index_attempts_for_cc_pair(db_session, identifier)

    assert [a.id for a in results] == [full_run.id]


def test_count_unique_cc_pairs_skips_targeted(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """Counting unique cc_pairs with successful attempts: a targeted-only
    cc_pair must not contribute. Build that scenario by giving the test
    cc_pair only a targeted-reindex SUCCESS row and no full-run row."""
    settings = get_current_search_settings(db_session)
    job = _make_targeted_job(db_session)
    _make_attempt(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.SUCCESS,
        targeted_reindex_job_id=job.id,
    )

    distinct_ids_before = {
        cid
        for (cid,) in db_session.query(IndexAttempt.connector_credential_pair_id)
        .filter(
            IndexAttempt.search_settings_id == settings.id,
            IndexAttempt.status == IndexingStatus.SUCCESS,
            IndexAttempt.targeted_reindex_job_id.is_(None),
        )
        .distinct()
        .all()
    }

    count = count_unique_cc_pairs_with_successful_index_attempts(
        settings.id, db_session
    )

    assert count == len(distinct_ids_before)
    # The targeted-only cc_pair must NOT be in the count
    assert cc_pair.id not in distinct_ids_before


def test_count_unique_active_cc_pairs_skips_targeted(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    settings = get_current_search_settings(db_session)
    job = _make_targeted_job(db_session)
    _make_attempt(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.SUCCESS,
        targeted_reindex_job_id=job.id,
    )

    distinct_ids_before = {
        cid
        for (cid,) in db_session.query(IndexAttempt.connector_credential_pair_id)
        .filter(
            IndexAttempt.search_settings_id == settings.id,
            IndexAttempt.status == IndexingStatus.SUCCESS,
            IndexAttempt.targeted_reindex_job_id.is_(None),
        )
        .distinct()
        .all()
    }

    count = count_unique_active_cc_pairs_with_successful_index_attempts(
        settings.id, db_session
    )

    assert count == len(distinct_ids_before)
    assert cc_pair.id not in distinct_ids_before


def test_get_last_successful_poll_range_end_skips_targeted(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """The freshness scheduler reads `poll_range_end` from the latest
    successful full-run attempt, ignoring targeted reindexes."""
    settings = get_current_search_settings(db_session)
    full_run_end = datetime(2026, 1, 1, tzinfo=timezone.utc)
    targeted_end = datetime(2026, 6, 1, tzinfo=timezone.utc)

    full_run = _make_attempt(
        db_session, cc_pair.id, settings.id, status=IndexingStatus.SUCCESS
    )
    full_run.poll_range_end = full_run_end
    db_session.commit()

    job = _make_targeted_job(db_session)
    targeted = _make_attempt(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.SUCCESS,
        targeted_reindex_job_id=job.id,
    )
    targeted.poll_range_end = targeted_end
    db_session.commit()

    result = get_last_successful_attempt_poll_range_end(
        cc_pair_id=cc_pair.id,
        earliest_index=0.0,
        search_settings=settings,
        db_session=db_session,
    )

    assert result == full_run_end.timestamp()


def _make_attempt_with_times(
    db_session: Session,
    cc_pair_id: int,
    search_settings_id: int,
    *,
    status: IndexingStatus,
    time_created: datetime,
) -> IndexAttempt:
    """Create an attempt and pin its creation time, mirroring `_make_attempt`

    but allowing control of `time_created` so tests can reproduce the
    checkpoint-cleanup race without waiting 7 days.
    """
    attempt = _make_attempt(
        db_session,
        cc_pair_id,
        search_settings_id,
        status=status,
    )
    attempt.time_created = time_created
    attempt.time_updated = time_created
    db_session.commit()
    db_session.refresh(attempt)
    return attempt


def test_get_last_attempt_orders_by_creation_not_mutated_updated(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """The scheduler must not be fooled by an old attempt whose `time_updated`
    was bumped by hourly checkpoint cleanup (issue #14064).

    Regression: `get_last_attempt_for_cc_pair` sorted by `time_updated`, which
    `check_for_checkpoint_cleanup` refreshes on attempts older than 7 days.
    A bumped 7-day-old attempt then looked like the newest, so
    `should_index()` never saw a gap bigger than 1 hour for connectors with
    `refresh_freq >= 3600`.
    """
    settings = get_current_search_settings(db_session)
    real_latest = _make_attempt_with_times(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.SUCCESS,
        time_created=datetime(2026, 1, 10, tzinfo=timezone.utc),
    )
    # An older attempt that checkpoint cleanup later "touches", giving it a
    # NEWER `time_updated` than the genuinely-latest attempt.
    cleanup_bumped = _make_attempt_with_times(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.SUCCESS,
        time_created=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    cleanup_bumped.time_updated = datetime(2026, 2, 1, tzinfo=timezone.utc)
    db_session.commit()
    db_session.refresh(cleanup_bumped)

    result = get_last_attempt_for_cc_pair(cc_pair.id, settings.id, db_session)

    assert result is not None
    assert result.id == real_latest.id


def test_get_recent_attempts_orders_by_creation_not_mutated_updated(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """The repeated-error detector also relies on these helpers; it must see
    the genuinely-most-recent attempts, not rows the cleanup task touched."""
    settings = get_current_search_settings(db_session)
    newest = _make_attempt_with_times(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.SUCCESS,
        time_created=datetime(2026, 1, 10, tzinfo=timezone.utc),
    )
    older_bumped = _make_attempt_with_times(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.FAILED,
        time_created=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    older_bumped.time_updated = datetime(2026, 2, 1, tzinfo=timezone.utc)
    db_session.commit()
    db_session.refresh(older_bumped)

    results = get_recent_attempts_for_cc_pair(
        cc_pair.id, settings.id, limit=10, db_session=db_session
    )

    assert [attempt.id for attempt in results] == [newest.id, older_bumped.id]


def test_get_recent_completed_orders_by_creation_not_mutated_updated(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """Checkpoint candidate selection (`get_latest_valid_checkpoint`) consumes
    `get_recent_completed_attempts_for_cc_pair`; like the others it must order
    by creation so cleanup writes don't reorder the candidates."""
    settings = get_current_search_settings(db_session)
    newest = _make_attempt_with_times(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.SUCCESS,
        time_created=datetime(2026, 1, 10, tzinfo=timezone.utc),
    )
    older_bumped = _make_attempt_with_times(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.SUCCESS,
        time_created=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    older_bumped.time_updated = datetime(2026, 2, 1, tzinfo=timezone.utc)
    db_session.commit()
    db_session.refresh(older_bumped)

    results = get_recent_completed_attempts_for_cc_pair(
        cc_pair.id, settings.id, limit=10, db_session=db_session
    )

    assert [attempt.id for attempt in results] == [newest.id, older_bumped.id]
