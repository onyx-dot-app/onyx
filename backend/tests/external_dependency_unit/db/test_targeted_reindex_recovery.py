from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docprocessing.targeted_reindex_task import (
    run_targeted_reindex,
)
from onyx.db.enums import IndexingStatus
from onyx.db.models import IndexAttempt, TargetedReindexJob, TargetedReindexJobTarget
from onyx.db.targeted_reindex import TargetSpec, create_targeted_reindex_job
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


@pytest.fixture
def job(db_session: Session) -> Generator[TargetedReindexJob, None, None]:
    pair = make_cc_pair(db_session)
    result = create_targeted_reindex_job(
        db_session, None, [TargetSpec(cc_pair_id=pair.id, document_id="lost-doc")]
    )
    row = db_session.get(TargetedReindexJob, result.targeted_reindex_job_id)
    assert row is not None
    yield row
    db_session.rollback()
    db_session.query(TargetedReindexJobTarget).filter_by(
        targeted_reindex_job_id=row.id
    ).delete()
    db_session.query(IndexAttempt).filter_by(targeted_reindex_job_id=row.id).delete()
    db_session.delete(row)
    db_session.commit()
    cleanup_cc_pair(db_session, pair)


@pytest.mark.parametrize(
    "status", [IndexingStatus.NOT_STARTED, IndexingStatus.IN_PROGRESS]
)
def test_lost_job_and_attempts_fail_together(
    db_session: Session, job: TargetedReindexJob, status: IndexingStatus
) -> None:
    from onyx.background.celery.tasks.docprocessing.tasks import (
        validate_active_indexing_attempts,
    )

    old = datetime.now(timezone.utc) - timedelta(days=1)
    job.requested_at = old
    job.status = status
    for attempt in job.index_attempts:
        attempt.status = status
        attempt.time_started = old if status == IndexingStatus.IN_PROGRESS else None
    db_session.commit()
    validate_active_indexing_attempts(MagicMock())
    db_session.expire_all()
    db_session.refresh(job)
    assert job.status == IndexingStatus.FAILED
    assert job.completed_at is not None
    assert all(
        attempt.status == IndexingStatus.FAILED and attempt.error_msg
        for attempt in job.index_attempts
    )
    with patch(
        "onyx.background.indexing.run_targeted_reindex.process_targets_for_cc_pair"
    ) as processor:
        run_targeted_reindex(job.id)
        processor.assert_not_called()


def test_old_request_just_started_is_not_reaped(
    db_session: Session, job: TargetedReindexJob
) -> None:
    from onyx.background.celery.tasks.docprocessing.tasks import (
        validate_active_indexing_attempts,
    )

    job.requested_at = datetime.now(timezone.utc) - timedelta(days=1)
    job.status = IndexingStatus.IN_PROGRESS
    for attempt in job.index_attempts:
        attempt.status = IndexingStatus.IN_PROGRESS
        attempt.time_started = datetime.now(timezone.utc)
    db_session.commit()
    validate_active_indexing_attempts(MagicMock())
    db_session.expire_all()
    db_session.refresh(job)
    assert job.status == IndexingStatus.IN_PROGRESS


def test_late_worker_does_not_overwrite_reaped_state(
    db_session: Session, job: TargetedReindexJob
) -> None:
    from onyx.background.celery.tasks.docprocessing.tasks import (
        validate_active_indexing_attempts,
    )
    from onyx.background.indexing.run_targeted_reindex import CCPairReindexResult

    def reap_while_processing(**_: object) -> CCPairReindexResult:
        db_session.expire_all()
        for attempt in job.index_attempts:
            attempt.time_started = datetime.now(timezone.utc) - timedelta(days=1)
        db_session.commit()
        validate_active_indexing_attempts(MagicMock())
        return CCPairReindexResult(
            landed_doc_ids=set(), failed_doc_ids=set(), unsupported=False
        )

    with patch(
        "onyx.background.indexing.run_targeted_reindex.process_targets_for_cc_pair",
        side_effect=reap_while_processing,
    ):
        run_targeted_reindex(job.id)
    db_session.expire_all()
    db_session.refresh(job)
    assert job.status == IndexingStatus.FAILED
    assert all(
        attempt.status == IndexingStatus.FAILED for attempt in job.index_attempts
    )
