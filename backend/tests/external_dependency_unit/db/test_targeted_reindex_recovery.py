from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docprocessing.targeted_reindex_task import (
    run_targeted_reindex,
)
from onyx.background.celery.tasks.docprocessing.tasks import (
    validate_active_indexing_attempts,
)
from onyx.background.indexing.run_targeted_reindex import CCPairReindexResult
from onyx.db.enums import IndexingStatus
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.db.models import IndexAttempt, TargetedReindexJob, TargetedReindexJobTarget
from onyx.db.targeted_reindex import TargetSpec, create_targeted_reindex_job
from onyx.server.documents.targeted_reindex import (
    DocumentTargetRequest,
    TargetedReindexRequest,
    submit_targeted_reindex,
)
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
    make_index_attempt,
)


def _delete_job(db_session: Session, job_id: int) -> None:
    db_session.rollback()
    db_session.query(TargetedReindexJobTarget).filter_by(
        targeted_reindex_job_id=job_id
    ).delete()
    db_session.query(IndexAttempt).filter_by(targeted_reindex_job_id=job_id).delete()
    db_session.query(TargetedReindexJob).filter_by(id=job_id).delete()
    db_session.commit()


@pytest.fixture
def job(db_session: Session) -> Generator[TargetedReindexJob, None, None]:
    pair = make_cc_pair(db_session)
    result = create_targeted_reindex_job(
        db_session, None, [TargetSpec(cc_pair_id=pair.id, document_id="lost-doc")]
    )
    row = db_session.get(TargetedReindexJob, result.targeted_reindex_job_id)
    assert row is not None
    yield row
    _delete_job(db_session, row.id)
    cleanup_cc_pair(db_session, pair)


@pytest.mark.parametrize(
    "status", [IndexingStatus.NOT_STARTED, IndexingStatus.IN_PROGRESS]
)
def test_lost_job_and_attempts_fail_together(
    db_session: Session, job: TargetedReindexJob, status: IndexingStatus
) -> None:
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


def test_reaped_job_stops_and_keeps_failed_state(db_session: Session) -> None:
    pairs = [make_cc_pair(db_session), make_cc_pair(db_session)]
    result = create_targeted_reindex_job(
        db_session,
        None,
        [TargetSpec(cc_pair_id=pair.id, document_id="lost-doc") for pair in pairs],
    )
    job_id = result.targeted_reindex_job_id

    def reap_while_processing(**_: object) -> CCPairReindexResult:
        db_session.expire_all()
        for attempt in db_session.query(IndexAttempt).filter_by(
            targeted_reindex_job_id=job_id
        ):
            attempt.time_started = datetime.now(timezone.utc) - timedelta(days=1)
        db_session.commit()
        validate_active_indexing_attempts(MagicMock())
        return CCPairReindexResult(
            landed_doc_ids=set(), failed_doc_ids=set(), unsupported=False
        )

    try:
        with patch(
            "onyx.background.indexing.run_targeted_reindex.process_targets_for_cc_pair",
            side_effect=reap_while_processing,
        ) as processor:
            run_targeted_reindex(job_id)
        assert processor.call_count == 1
        db_session.expire_all()
        job = db_session.get(TargetedReindexJob, job_id)
        assert job is not None
        assert job.status == IndexingStatus.FAILED
        assert all(
            attempt.status == IndexingStatus.FAILED for attempt in job.index_attempts
        )
    finally:
        _delete_job(db_session, job_id)
        for pair in pairs:
            cleanup_cc_pair(db_session, pair)


def test_startup_orphan_check_skips_synthetic_attempts(
    db_session: Session, job: TargetedReindexJob
) -> None:
    # A queued task also reads PENDING, so the startup check must not cancel it.
    synthetic_ids = {attempt.id for attempt in job.index_attempts}
    assert synthetic_ids
    pair = job.index_attempts[0].connector_credential_pair
    normal = make_index_attempt(
        db_session, pair, IndexingStatus.NOT_STARTED, datetime.now(timezone.utc), None
    )
    normal.celery_task_id = "normal-task"
    db_session.commit()
    try:
        orphan_ids = set(
            IndexingCoordination.get_orphaned_index_attempt_ids(db_session)
        )
        assert normal.id in orphan_ids
        assert not synthetic_ids & orphan_ids
    finally:
        db_session.delete(normal)
        db_session.commit()


def test_submit_and_start_mark_tenant_active(
    db_session: Session, job: TargetedReindexJob
) -> None:
    tenant_id = get_current_tenant_id()
    with (
        patch(
            "onyx.background.celery.tasks.docprocessing.targeted_reindex_task.maybe_mark_tenant_active"
        ) as mark,
        patch(
            "onyx.background.indexing.run_targeted_reindex.process_targets_for_cc_pair",
            return_value=CCPairReindexResult(
                landed_doc_ids=set(), failed_doc_ids=set(), unsupported=False
            ),
        ),
    ):
        run_targeted_reindex(job.id)
    mark.assert_called_once_with(tenant_id, caller="targeted_reindex")

    pair_id = job.index_attempts[0].connector_credential_pair_id
    with (
        patch(
            "onyx.server.documents.targeted_reindex.maybe_mark_tenant_active"
        ) as mark,
        patch("onyx.server.documents.targeted_reindex.client_app"),
        patch(
            "onyx.server.documents.targeted_reindex.verify_user_can_manage_all_cc_pairs",
            return_value=True,
        ),
    ):
        response = submit_targeted_reindex(
            TargetedReindexRequest(
                targets=[
                    DocumentTargetRequest(cc_pair_id=pair_id, document_id="new-doc")
                ]
            ),
            user=MagicMock(id=None),
            db_session=db_session,
        )
    _delete_job(db_session, response.targeted_reindex_job_id)
    mark.assert_called_once_with(tenant_id, caller="targeted_reindex")
