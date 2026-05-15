"""External dependency unit tests for the targeted reindex celery task.

Covers the lifecycle and resolution-tracking layers of the task:
- Job + synthetic IndexAttempt lifecycle transitions
- Resolution tracking on `IndexAttemptError` rows referenced by targets
  with `source_error_id` (gated on landed_doc_ids)
- Idempotent re-run (job already terminal → drop)
- Resolved-summary snapshot
- Mid-task exception → FAILED recovery

The per-cc-pair connector + pipeline path is mocked out via
`process_targets_for_cc_pair`; its own coverage lives in
`test_run_targeted_reindex.py`. That separation keeps these tests
fast and lets us exercise lifecycle without spinning up a connector.
"""

from collections.abc import Generator
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docprocessing.targeted_reindex_task import (
    run_targeted_reindex,
)
from onyx.background.indexing.run_targeted_reindex import CCPairReindexResult
from onyx.db.enums import IndexingStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexAttemptError
from onyx.db.models import TargetedReindexJob
from onyx.db.models import TargetedReindexJobTarget
from onyx.db.search_settings import get_current_search_settings
from onyx.db.targeted_reindex import create_targeted_reindex_job
from onyx.db.targeted_reindex import resolve_error_ids_to_targets
from onyx.db.targeted_reindex import TargetSpec
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_cc_pair

_PROCESSOR_PATH = (
    "onyx.background.celery.tasks.docprocessing."
    "targeted_reindex_task.process_targets_for_cc_pair"
)


def _patch_processor(
    landed_doc_ids: set[str] | None = None,
    failed_doc_ids: set[str] | None = None,
    unsupported: bool = False,
):  # type: ignore[no-untyped-def]
    """Patch the per-cc-pair processor with a fixed result.

    Defaults to landing nothing / failing nothing (no-op) so the
    existing lifecycle tests don't need to know about doc semantics.
    Pass `landed_doc_ids` to simulate successful reindex of specific
    docs.
    """
    return patch(
        _PROCESSOR_PATH,
        return_value=CCPairReindexResult(
            landed_doc_ids=landed_doc_ids or set(),
            failed_doc_ids=failed_doc_ids or set(),
            unsupported=unsupported,
        ),
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
        db_session.query(TargetedReindexJobTarget).delete(synchronize_session="fetch")
        db_session.query(IndexAttemptError).delete(synchronize_session="fetch")
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == pair.id
        ).delete(synchronize_session="fetch")
        db_session.query(TargetedReindexJob).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


def _run_task(job_id: int) -> None:
    """Invoke the task body synchronously, bypassing celery binding."""
    run_targeted_reindex(
        targeted_reindex_job_id=job_id, celery_task_id="test-celery-id"
    )


def test_task_transitions_job_to_terminal(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    targets = [TargetSpec(cc_pair_id=cc_pair.id, document_id="doc-1")]
    result = create_targeted_reindex_job(
        db_session=db_session, requested_by_user_id=None, targets=targets
    )

    with _patch_processor(landed_doc_ids={"doc-1"}):
        _run_task(result.targeted_reindex_job_id)

    db_session.expire_all()
    job = db_session.get(TargetedReindexJob, result.targeted_reindex_job_id)
    assert job is not None
    assert job.status == IndexingStatus.SUCCESS
    assert job.completed_at is not None


def test_task_transitions_synthetic_attempts_to_success(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    targets = [TargetSpec(cc_pair_id=cc_pair.id, document_id="doc-1")]
    result = create_targeted_reindex_job(
        db_session=db_session, requested_by_user_id=None, targets=targets
    )

    with _patch_processor(landed_doc_ids={"doc-1"}):
        _run_task(result.targeted_reindex_job_id)

    db_session.expire_all()
    attempts = (
        db_session.query(IndexAttempt)
        .filter(IndexAttempt.targeted_reindex_job_id == result.targeted_reindex_job_id)
        .all()
    )
    # One synthetic attempt per (cc_pair × active SearchSettings); CI may
    # run with PRESENT+FUTURE active. Assert all of them transitioned.
    assert len(attempts) >= 1
    assert all(a.status == IndexingStatus.SUCCESS for a in attempts)


def test_task_marks_failure_derived_errors_resolved(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    settings = get_current_search_settings(db_session)
    parent = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=settings.id,
        from_beginning=False,
        status=IndexingStatus.FAILED,
    )
    db_session.add(parent)
    db_session.commit()
    db_session.refresh(parent)

    err = IndexAttemptError(
        index_attempt_id=parent.id,
        connector_credential_pair_id=cc_pair.id,
        document_id="failed-doc",
        failure_message="boom",
        is_resolved=False,
    )
    db_session.add(err)
    db_session.commit()
    db_session.refresh(err)

    derived, _ = resolve_error_ids_to_targets(db_session, [err.id])
    result = create_targeted_reindex_job(
        db_session=db_session, requested_by_user_id=None, targets=derived
    )

    with _patch_processor(landed_doc_ids={"failed-doc"}):
        _run_task(result.targeted_reindex_job_id)

    db_session.expire_all()
    err_after = db_session.get(IndexAttemptError, err.id)
    assert err_after is not None
    assert err_after.is_resolved is True

    job = db_session.get(TargetedReindexJob, result.targeted_reindex_job_id)
    assert job is not None
    assert job.resolved_count == 1
    assert job.still_failing_count == 0
    assert len(job.resolved_summary) == 1
    assert job.resolved_summary[0]["id"] == err.id
    assert job.resolved_summary[0]["document_id"] == "failed-doc"


def test_task_does_not_touch_arbitrary_targets(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """Targets without `source_error_id` are arbitrary reindexes; they
    have no error row to mark resolved, and the task must not crash on
    their absence."""
    targets = [
        TargetSpec(cc_pair_id=cc_pair.id, document_id="arb-1"),
        TargetSpec(cc_pair_id=cc_pair.id, document_id="arb-2"),
    ]
    result = create_targeted_reindex_job(
        db_session=db_session, requested_by_user_id=None, targets=targets
    )

    with _patch_processor(landed_doc_ids={"arb-1", "arb-2"}):
        _run_task(result.targeted_reindex_job_id)

    db_session.expire_all()
    job = db_session.get(TargetedReindexJob, result.targeted_reindex_job_id)
    assert job is not None
    assert job.status == IndexingStatus.SUCCESS
    assert job.resolved_count == 0
    assert job.resolved_summary == []


def test_task_does_not_resolve_errors_when_doc_failed_to_land(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """Resolution-tracking gate: an IndexAttemptError stays open if the
    targeted reindex couldn't actually re-fetch + re-index its doc."""
    settings = get_current_search_settings(db_session)
    parent = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=settings.id,
        from_beginning=False,
        status=IndexingStatus.FAILED,
    )
    db_session.add(parent)
    db_session.commit()
    db_session.refresh(parent)

    err = IndexAttemptError(
        index_attempt_id=parent.id,
        connector_credential_pair_id=cc_pair.id,
        document_id="still-broken",
        failure_message="boom",
        is_resolved=False,
    )
    db_session.add(err)
    db_session.commit()
    db_session.refresh(err)

    derived, _ = resolve_error_ids_to_targets(db_session, [err.id])
    result = create_targeted_reindex_job(
        db_session=db_session, requested_by_user_id=None, targets=derived
    )

    # Doc didn't land — connector or pipeline failed.
    with _patch_processor(failed_doc_ids={"still-broken"}):
        _run_task(result.targeted_reindex_job_id)

    db_session.expire_all()
    err_after = db_session.get(IndexAttemptError, err.id)
    assert err_after is not None
    assert err_after.is_resolved is False  # NOT resolved; doc still failing

    job = db_session.get(TargetedReindexJob, result.targeted_reindex_job_id)
    assert job is not None
    assert job.resolved_count == 0
    assert job.still_failing_count == 1
    assert job.resolved_summary == []


def test_task_does_not_resolve_error_when_doc_landed_for_other_cc_pair(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """Cross-cc_pair safety: the same doc id can be a target across two
    cc_pairs. If it lands for cc_pair A but fails for cc_pair B, the
    error filed against cc_pair B must stay open. Resolution is gated
    on the (cc_pair_id, document_id) pair, not on bare document_id."""
    second = make_cc_pair(db_session)
    settings = get_current_search_settings(db_session)
    try:
        # Failure-derived target on cc_pair B (the one that won't land)
        parent_b = IndexAttempt(
            connector_credential_pair_id=second.id,
            search_settings_id=settings.id,
            from_beginning=False,
            status=IndexingStatus.FAILED,
        )
        db_session.add(parent_b)
        db_session.commit()
        db_session.refresh(parent_b)

        err_b = IndexAttemptError(
            index_attempt_id=parent_b.id,
            connector_credential_pair_id=second.id,
            document_id="shared-doc",
            failure_message="still failing for cc_pair B",
            is_resolved=False,
        )
        db_session.add(err_b)
        db_session.commit()
        db_session.refresh(err_b)

        # Same shared-doc on cc_pair A as an arbitrary target
        # (no source_error_id; landing it should not affect cc_pair B's err).
        derived_b, _ = resolve_error_ids_to_targets(db_session, [err_b.id])
        arbitrary_a = [TargetSpec(cc_pair_id=cc_pair.id, document_id="shared-doc")]
        result = create_targeted_reindex_job(
            db_session=db_session,
            requested_by_user_id=None,
            targets=[*derived_b, *arbitrary_a],
        )

        # Processor lands shared-doc for cc_pair A, fails it for cc_pair B.
        def _by_cc_pair(*_args, **kwargs):  # type: ignore[no-untyped-def]
            from onyx.background.indexing.run_targeted_reindex import (
                CCPairReindexResult,
            )

            cc_id = kwargs["cc_pair_id"]
            if cc_id == cc_pair.id:
                return CCPairReindexResult(
                    landed_doc_ids={"shared-doc"},
                    failed_doc_ids=set(),
                    unsupported=False,
                )
            return CCPairReindexResult(
                landed_doc_ids=set(),
                failed_doc_ids={"shared-doc"},
                unsupported=False,
            )

        with patch(_PROCESSOR_PATH, side_effect=_by_cc_pair):
            _run_task(result.targeted_reindex_job_id)

        db_session.expire_all()
        err_after = db_session.get(IndexAttemptError, err_b.id)
        assert err_after is not None
        assert err_after.is_resolved is False  # NOT resolved — failed for B
    finally:
        # Per-test cleanup of the second cc_pair's rows.
        db_session.query(TargetedReindexJobTarget).delete(synchronize_session="fetch")
        db_session.query(IndexAttemptError).delete(synchronize_session="fetch")
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == second.id
        ).delete(synchronize_session="fetch")
        db_session.query(TargetedReindexJob).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, second)


def test_task_skips_already_terminal_job(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """If the task is somehow re-delivered after the job already ran,
    it must not attempt to re-run the work."""
    targets = [TargetSpec(cc_pair_id=cc_pair.id, document_id="doc-1")]
    result = create_targeted_reindex_job(
        db_session=db_session, requested_by_user_id=None, targets=targets
    )
    job = db_session.get(TargetedReindexJob, result.targeted_reindex_job_id)
    assert job is not None
    job.status = IndexingStatus.SUCCESS
    db_session.commit()

    _run_task(result.targeted_reindex_job_id)

    # synthetic attempt should NOT have been transitioned, since we
    # bailed early.
    db_session.expire_all()
    attempts = (
        db_session.query(IndexAttempt)
        .filter(IndexAttempt.targeted_reindex_job_id == result.targeted_reindex_job_id)
        .all()
    )
    assert all(a.status == IndexingStatus.NOT_STARTED for a in attempts)


def test_task_handles_mix_of_failure_derived_and_arbitrary(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """A single job can carry both flavors of target. Failure-derived
    ones get resolved; arbitrary ones contribute to skipped_count."""
    settings = get_current_search_settings(db_session)
    parent = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=settings.id,
        from_beginning=False,
        status=IndexingStatus.FAILED,
    )
    db_session.add(parent)
    db_session.commit()
    db_session.refresh(parent)

    err = IndexAttemptError(
        index_attempt_id=parent.id,
        connector_credential_pair_id=cc_pair.id,
        document_id="failed-doc",
        failure_message="boom",
        is_resolved=False,
    )
    db_session.add(err)
    db_session.commit()
    db_session.refresh(err)

    derived, _ = resolve_error_ids_to_targets(db_session, [err.id])
    arbitrary = [TargetSpec(cc_pair_id=cc_pair.id, document_id="arb-1")]
    result = create_targeted_reindex_job(
        db_session=db_session,
        requested_by_user_id=None,
        targets=[*derived, *arbitrary],
    )

    # Both docs land. Failure-derived → resolved; arbitrary contributes
    # to runtime_skipped (no error linkage to record against).
    with _patch_processor(landed_doc_ids={"failed-doc", "arb-1"}):
        _run_task(result.targeted_reindex_job_id)

    db_session.expire_all()
    job = db_session.get(TargetedReindexJob, result.targeted_reindex_job_id)
    assert job is not None
    assert job.resolved_count == 1
    assert job.skipped_count == 1  # the arbitrary target had no error to clear


def test_task_marks_job_failed_on_mid_task_exception(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """Mid-task failure must transition the job + synthetic attempts to
    FAILED rather than wedging in IN_PROGRESS forever."""
    targets = [TargetSpec(cc_pair_id=cc_pair.id, document_id="doc-1")]
    result = create_targeted_reindex_job(
        db_session=db_session, requested_by_user_id=None, targets=targets
    )

    # Force the resolution-tracking helper to blow up after the
    # IN_PROGRESS commit but before the SUCCESS commit.
    with (
        _patch_processor(landed_doc_ids={"doc-1"}),
        patch(
            "onyx.background.celery.tasks.docprocessing."
            "targeted_reindex_task.resolve_failure_derived_targets",
            side_effect=RuntimeError("simulated mid-task crash"),
        ),
    ):
        with pytest.raises(RuntimeError, match="simulated mid-task crash"):
            _run_task(result.targeted_reindex_job_id)

    db_session.expire_all()
    job = db_session.get(TargetedReindexJob, result.targeted_reindex_job_id)
    assert job is not None
    assert job.status == IndexingStatus.FAILED
    assert job.completed_at is not None

    attempts = (
        db_session.query(IndexAttempt)
        .filter(IndexAttempt.targeted_reindex_job_id == result.targeted_reindex_job_id)
        .all()
    )
    assert all(a.status == IndexingStatus.FAILED for a in attempts)
