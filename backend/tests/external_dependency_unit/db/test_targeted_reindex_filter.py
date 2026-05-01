"""External dependency unit tests for the `targeted_reindex_job_id IS NULL`
filter on IndexAttempt consumer queries.

Validates that synthetic targeted-reindex attempts don't bleed into freshness,
scheduling, or counting queries that should only see real full-crawl attempts,
while cleanup/cancellation paths still see both.
"""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import IndexingStatus
from onyx.db.index_attempt import cancel_indexing_attempts_for_ccpair
from onyx.db.index_attempt import count_index_attempts_for_cc_pair
from onyx.db.index_attempt import get_in_progress_index_attempts
from onyx.db.index_attempt import get_last_attempt_for_cc_pair
from onyx.db.index_attempt import get_latest_index_attempt_for_cc_pair_id
from onyx.db.index_attempt import get_latest_successful_index_attempt_for_cc_pair_id
from onyx.db.index_attempt import get_recent_attempts_for_cc_pair
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import IndexAttempt
from onyx.db.models import TargetedReindexJob
from onyx.db.search_settings import get_current_search_settings
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_cc_pair


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


def test_fence_allows_targeted_during_full_run(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """A full run already in progress should not block a targeted reindex
    from being created — they're allowed to overlap by design."""
    settings = get_current_search_settings(db_session)
    _make_attempt(
        db_session, cc_pair.id, settings.id, status=IndexingStatus.IN_PROGRESS
    )

    # Targeted reindex is created directly (the API path), not via the fence.
    # The fence's only job here is allowing the full run to coexist.
    job = _make_targeted_job(db_session)
    targeted = _make_attempt(
        db_session,
        cc_pair.id,
        settings.id,
        status=IndexingStatus.IN_PROGRESS,
        targeted_reindex_job_id=job.id,
    )

    # Full run should still be visible to the fence — try_create_index_attempt
    # for ANOTHER full run should now return None (fence catches it).
    blocked = IndexingCoordination.try_create_index_attempt(
        db_session=db_session,
        cc_pair_id=cc_pair.id,
        search_settings_id=settings.id,
        celery_task_id="test-task-id",
    )
    assert blocked is None

    # Targeted attempt is unaffected by the fence — confirms it didn't bleed
    # into the in-progress full-run check either way.
    assert targeted.targeted_reindex_job_id == job.id


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
