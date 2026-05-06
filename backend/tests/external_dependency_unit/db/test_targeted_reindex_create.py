"""External dependency unit tests for `create_targeted_reindex_job`.

Validates that submitting a targeted reindex request:
- writes the job row + target rows + per-cc-pair synthetic IndexAttempts
- pre-allocates a celery task UUID
- dedupes (cc_pair, document_id) pairs
- enforces the MAX_TARGETS_PER_REQUEST cap
- raises on unknown cc_pair_id
- correctly resolves error IDs into targets, skipping already-resolved
  and entity-level rows
"""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import IndexingStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexAttemptError
from onyx.db.models import TargetedReindexJob
from onyx.db.models import TargetedReindexJobTarget
from onyx.db.search_settings import get_current_search_settings
from onyx.db.targeted_reindex import create_targeted_reindex_job
from onyx.db.targeted_reindex import get_targeted_reindex_job
from onyx.db.targeted_reindex import MAX_TARGETS_PER_REQUEST
from onyx.db.targeted_reindex import resolve_error_ids_to_targets
from onyx.db.targeted_reindex import TargetSpec
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
        # FK order: targets → errors → attempts → job
        db_session.query(TargetedReindexJobTarget).delete(synchronize_session="fetch")
        db_session.query(IndexAttemptError).delete(synchronize_session="fetch")
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == pair.id
        ).delete(synchronize_session="fetch")
        db_session.query(TargetedReindexJob).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


def test_create_job_writes_rows_and_synthetic_attempt(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    targets = [
        TargetSpec(cc_pair_id=cc_pair.id, document_id="doc-1"),
        TargetSpec(cc_pair_id=cc_pair.id, document_id="doc-2"),
    ]

    result = create_targeted_reindex_job(
        db_session=db_session, requested_by_user_id=None, targets=targets
    )

    assert result.queued_count == 2
    assert result.skipped_count == 0
    assert result.celery_task_id  # non-empty UUID
    # One synthetic attempt per (cc_pair × active search settings). Test env
    # may have PRESENT only or PRESENT+FUTURE, so just assert all attempts
    # belong to our cc_pair and the (cc_pair, search_settings) tuples are
    # unique.
    assert len(result.synthetic_attempt_ids) >= 1
    assert {p[0] for p in result.cc_pair_search_settings_pairs} == {cc_pair.id}
    assert len(set(result.cc_pair_search_settings_pairs)) == len(
        result.cc_pair_search_settings_pairs
    )

    job = get_targeted_reindex_job(db_session, result.targeted_reindex_job_id)
    assert job is not None
    assert job.celery_task_id == result.celery_task_id
    assert job.status == IndexingStatus.NOT_STARTED

    target_rows = (
        db_session.query(TargetedReindexJobTarget)
        .filter(
            TargetedReindexJobTarget.targeted_reindex_job_id
            == result.targeted_reindex_job_id
        )
        .all()
    )
    assert {t.document_id for t in target_rows} == {"doc-1", "doc-2"}
    assert all(t.source_error_id is None for t in target_rows)

    attempts = (
        db_session.query(IndexAttempt)
        .filter(IndexAttempt.targeted_reindex_job_id == result.targeted_reindex_job_id)
        .all()
    )
    assert len(attempts) == len(result.synthetic_attempt_ids)
    assert {a.connector_credential_pair_id for a in attempts} == {cc_pair.id}
    assert all(a.status == IndexingStatus.NOT_STARTED for a in attempts)


def test_create_job_dedups_duplicate_targets(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    targets = [
        TargetSpec(cc_pair_id=cc_pair.id, document_id="doc-1"),
        TargetSpec(cc_pair_id=cc_pair.id, document_id="doc-1"),
        TargetSpec(cc_pair_id=cc_pair.id, document_id="doc-2"),
    ]

    result = create_targeted_reindex_job(
        db_session=db_session, requested_by_user_id=None, targets=targets
    )

    assert result.queued_count == 2
    assert result.skipped_count == 1

    # GET endpoint reads from job row, so the create-time skip count must
    # be persisted there too.
    job = get_targeted_reindex_job(db_session, result.targeted_reindex_job_id)
    assert job is not None
    assert job.skipped_count == 1


def test_create_job_persists_upstream_skipped_count(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """API layer counts errors that resolved to no-op (already resolved,
    entity-level, invalid id) as skipped. That count is `upstream_skipped_count`
    and must end up on the job row so GET returns it before the task runs."""
    targets = [
        TargetSpec(cc_pair_id=cc_pair.id, document_id="doc-1"),
        TargetSpec(cc_pair_id=cc_pair.id, document_id="doc-1"),  # 1 dedup skip
    ]

    result = create_targeted_reindex_job(
        db_session=db_session,
        requested_by_user_id=None,
        targets=targets,
        upstream_skipped_count=3,  # e.g. 3 unresolvable error_ids
    )

    # 1 dedup + 3 upstream
    assert result.skipped_count == 4

    job = get_targeted_reindex_job(db_session, result.targeted_reindex_job_id)
    assert job is not None
    assert job.skipped_count == 4


def test_create_job_rejects_too_many_targets(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    too_many = [
        TargetSpec(cc_pair_id=cc_pair.id, document_id=f"doc-{i}")
        for i in range(MAX_TARGETS_PER_REQUEST + 1)
    ]

    with pytest.raises(ValueError, match="too many targets"):
        create_targeted_reindex_job(
            db_session=db_session, requested_by_user_id=None, targets=too_many
        )


def test_create_job_rejects_unknown_cc_pair(db_session: Session) -> None:
    targets = [TargetSpec(cc_pair_id=999_999_999, document_id="doc-1")]

    with pytest.raises(ValueError, match="unknown cc_pair_ids"):
        create_targeted_reindex_job(
            db_session=db_session, requested_by_user_id=None, targets=targets
        )


def test_create_job_rejects_empty_targets(db_session: Session) -> None:
    with pytest.raises(ValueError, match="at least one target"):
        create_targeted_reindex_job(
            db_session=db_session, requested_by_user_id=None, targets=[]
        )


def test_resolve_error_ids_to_targets(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """Failure-driven retry: the API accepts error IDs and resolves them
    to targets. Already-resolved errors and entity-level errors are skipped."""
    settings = get_current_search_settings(db_session)
    parent_attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=settings.id,
        from_beginning=False,
        status=IndexingStatus.FAILED,
    )
    db_session.add(parent_attempt)
    db_session.commit()
    db_session.refresh(parent_attempt)

    actionable = IndexAttemptError(
        index_attempt_id=parent_attempt.id,
        connector_credential_pair_id=cc_pair.id,
        document_id="actionable-doc",
        failure_message="boom",
        is_resolved=False,
    )
    already_resolved = IndexAttemptError(
        index_attempt_id=parent_attempt.id,
        connector_credential_pair_id=cc_pair.id,
        document_id="resolved-doc",
        failure_message="boom",
        is_resolved=True,
    )
    entity_level = IndexAttemptError(
        index_attempt_id=parent_attempt.id,
        connector_credential_pair_id=cc_pair.id,
        document_id=None,  # entity-level, no doc_id
        entity_id="some-entity",
        failure_message="boom",
        is_resolved=False,
    )
    db_session.add_all([actionable, already_resolved, entity_level])
    db_session.commit()
    db_session.refresh(actionable)
    db_session.refresh(already_resolved)
    db_session.refresh(entity_level)

    targets, skipped = resolve_error_ids_to_targets(
        db_session,
        [actionable.id, already_resolved.id, entity_level.id, 999_999_999],
    )

    assert len(targets) == 1
    assert targets[0].document_id == "actionable-doc"
    assert targets[0].source_error_id == actionable.id
    # 1 already-resolved + 1 entity-level + 1 invalid id = 3 skipped
    assert skipped == 3


def test_create_job_preserves_source_error_id_on_target_row(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """Failure-derived targets carry source_error_id through to the
    target row so the celery task can resolve the error at completion."""
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

    derived, skipped = resolve_error_ids_to_targets(db_session, [err.id])
    assert skipped == 0
    assert len(derived) == 1

    result = create_targeted_reindex_job(
        db_session=db_session, requested_by_user_id=None, targets=derived
    )

    target_row = (
        db_session.query(TargetedReindexJobTarget)
        .filter(
            TargetedReindexJobTarget.targeted_reindex_job_id
            == result.targeted_reindex_job_id
        )
        .one()
    )
    assert target_row.source_error_id == err.id


def test_create_job_dedup_keeps_source_error_id_when_overlapping(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """If the same (cc_pair, doc) appears in both the error-derived and
    arbitrary buckets, the error-derived one (carrying source_error_id)
    must win the dedup so the task can mark the error resolved."""
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
        document_id="dup-doc",
        failure_message="boom",
        is_resolved=False,
    )
    db_session.add(err)
    db_session.commit()
    db_session.refresh(err)

    error_derived = TargetSpec(
        cc_pair_id=cc_pair.id, document_id="dup-doc", source_error_id=err.id
    )
    manual_dup = TargetSpec(cc_pair_id=cc_pair.id, document_id="dup-doc")

    # Pass derived first.
    result = create_targeted_reindex_job(
        db_session=db_session,
        requested_by_user_id=None,
        targets=[error_derived, manual_dup],
    )

    target_row = (
        db_session.query(TargetedReindexJobTarget)
        .filter(
            TargetedReindexJobTarget.targeted_reindex_job_id
            == result.targeted_reindex_job_id
        )
        .one()
    )
    assert target_row.source_error_id == err.id


def test_create_job_dedup_prefers_source_error_id_regardless_of_order(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """The dedup must pick the linkage-bearing spec independent of
    input order. Same scenario as the previous test, but manual is
    passed FIRST. Without the prefer-linkage rule, last-in or
    first-in semantics would drop source_error_id depending on which
    side ordered the list."""
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
        document_id="dup-doc",
        failure_message="boom",
        is_resolved=False,
    )
    db_session.add(err)
    db_session.commit()
    db_session.refresh(err)

    manual_dup = TargetSpec(cc_pair_id=cc_pair.id, document_id="dup-doc")
    error_derived = TargetSpec(
        cc_pair_id=cc_pair.id, document_id="dup-doc", source_error_id=err.id
    )

    # Manual first this time. Linkage-bearing spec must still win.
    result = create_targeted_reindex_job(
        db_session=db_session,
        requested_by_user_id=None,
        targets=[manual_dup, error_derived],
    )

    target_row = (
        db_session.query(TargetedReindexJobTarget)
        .filter(
            TargetedReindexJobTarget.targeted_reindex_job_id
            == result.targeted_reindex_job_id
        )
        .one()
    )
    assert target_row.source_error_id == err.id
