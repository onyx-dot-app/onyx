"""An error closes with the run that closed it and why: a newer error on the
same document closes the older open ones (later_run), indexing the document or
finishing the run clean closes them (later_run), and a successful retry closes
the errors it was asked to retry (retry)."""

from collections.abc import Generator
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docprocessing.tasks import check_indexing_completion
from onyx.connectors.models import ConnectorFailure, DocumentFailure, EntityFailure
from onyx.db.enums import IndexingStatus
from onyx.db.index_attempt import (
    create_index_attempt_error,
    resolve_index_attempt_errors_for_documents,
)
from onyx.db.indexing_coordination import CoordinationStatus
from onyx.db.models import (
    ConnectorCredentialPair,
    IndexAttempt,
    IndexAttemptError,
    TargetedReindexJob,
    TargetedReindexJobTarget,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.db.targeted_reindex import (
    TargetSpec,
    create_targeted_reindex_job,
    resolve_failure_derived_targets,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_LATER_RUN = "later_run"
_RETRY = "retry"


@pytest.fixture
def pairs(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[tuple[ConnectorCredentialPair, ConnectorCredentialPair], None, None]:
    made = (make_cc_pair(db_session), make_cc_pair(db_session))
    yield made
    db_session.rollback()
    pair_ids = [pair.id for pair in made]
    job_ids = list(
        db_session.scalars(
            select(IndexAttempt.targeted_reindex_job_id).where(
                IndexAttempt.connector_credential_pair_id.in_(pair_ids),
                IndexAttempt.targeted_reindex_job_id.is_not(None),
            )
        ).all()
    )
    db_session.query(TargetedReindexJobTarget).filter(
        TargetedReindexJobTarget.cc_pair_id.in_(pair_ids)
    ).delete(synchronize_session=False)
    for model in (IndexAttemptError, IndexAttempt):
        db_session.query(model).filter(
            model.connector_credential_pair_id.in_(pair_ids)
        ).delete(synchronize_session=False)
    db_session.query(TargetedReindexJob).filter(
        TargetedReindexJob.id.in_(job_ids)
    ).delete(synchronize_session=False)
    db_session.commit()
    for pair in made:
        cleanup_cc_pair(db_session, pair)


def _attempt(
    db_session: Session,
    pair: ConnectorCredentialPair,
    status: IndexingStatus = IndexingStatus.IN_PROGRESS,
) -> IndexAttempt:
    attempt = IndexAttempt(
        connector_credential_pair_id=pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=status,
    )
    db_session.add(attempt)
    db_session.commit()
    return attempt


def _doc_error(db_session: Session, attempt: IndexAttempt, document_id: str) -> int:
    return create_index_attempt_error(
        attempt.id,
        attempt.connector_credential_pair_id,
        ConnectorFailure(
            failed_document=DocumentFailure(document_id=document_id),
            failure_message=f"{document_id} failed",
        ),
        db_session,
    )


def _entity_error(db_session: Session, attempt: IndexAttempt, entity_id: str) -> int:
    return create_index_attempt_error(
        attempt.id,
        attempt.connector_credential_pair_id,
        ConnectorFailure(
            failed_entity=EntityFailure(entity_id=entity_id),
            failure_message=f"{entity_id} failed",
        ),
        db_session,
    )


def _closure(
    db_session: Session, error_id: int
) -> tuple[bool, str | None, int | None, datetime | None]:
    """(is_resolved, resolved_reason, resolved_by_index_attempt_id, resolved_at)."""
    db_session.expire_all()
    row = db_session.execute(
        select(
            IndexAttemptError.is_resolved,
            IndexAttemptError.resolved_reason,
            IndexAttemptError.resolved_by_index_attempt_id,
            IndexAttemptError.resolved_at,
        ).where(IndexAttemptError.id == error_id)
    ).one()
    return row[0], row[1], row[2], row[3]


def _assert_open(db_session: Session, error_id: int) -> None:
    assert _closure(db_session, error_id) == (False, None, None, None)


def _assert_closed(
    db_session: Session, error_id: int, reason: str, by_attempt_id: int
) -> None:
    is_resolved, resolved_reason, resolved_by, resolved_at = _closure(
        db_session, error_id
    )
    assert is_resolved is True
    assert resolved_reason == reason
    assert resolved_by == by_attempt_id
    assert resolved_at is not None


def test_ac1_a_newer_error_on_a_document_closes_the_older_open_ones(
    db_session: Session,
    pairs: tuple[ConnectorCredentialPair, ConnectorCredentialPair],
) -> None:
    pair, other_pair = pairs
    first_run = _attempt(db_session, pair)
    second_run = _attempt(db_session, pair)
    other_run = _attempt(db_session, other_pair)

    older = _doc_error(db_session, first_run, "doc-x")
    other_doc = _doc_error(db_session, first_run, "doc-y")
    entity = _entity_error(db_session, first_run, "space-a")
    other_pair_same_doc = _doc_error(db_session, other_run, "doc-x")

    newer = _doc_error(db_session, second_run, "doc-x")

    _assert_closed(db_session, older, _LATER_RUN, second_run.id)
    for still_open in (newer, other_doc, entity, other_pair_same_doc):
        _assert_open(db_session, still_open)


def test_ac1_a_repeat_inside_one_run_closes_the_earlier_error_with_that_run(
    db_session: Session,
    pairs: tuple[ConnectorCredentialPair, ConnectorCredentialPair],
) -> None:
    pair, _ = pairs
    run = _attempt(db_session, pair)

    earlier = _doc_error(db_session, run, "doc-x")
    later = _doc_error(db_session, run, "doc-x")

    _assert_closed(db_session, earlier, _LATER_RUN, run.id)
    _assert_open(db_session, later)


def test_ac2_indexing_a_document_closes_its_errors_with_the_indexing_run(
    db_session: Session,
    pairs: tuple[ConnectorCredentialPair, ConnectorCredentialPair],
) -> None:
    pair, other_pair = pairs
    failing_run = _attempt(db_session, pair)
    indexing_run = _attempt(db_session, pair)
    other_run = _attempt(db_session, other_pair)
    fixed = _doc_error(db_session, failing_run, "doc-x")
    untouched = _doc_error(db_session, failing_run, "doc-y")
    other_pair_same_doc = _doc_error(db_session, other_run, "doc-x")

    resolve_index_attempt_errors_for_documents(
        db_session=db_session,
        cc_pair_id=pair.id,
        document_ids=["doc-x"],
        resolved_by_index_attempt_id=indexing_run.id,
    )

    _assert_closed(db_session, fixed, _LATER_RUN, indexing_run.id)
    _assert_open(db_session, untouched)
    _assert_open(db_session, other_pair_same_doc)


def test_ac2_a_clean_run_closes_the_pairs_entity_errors_with_that_run(
    db_session: Session,
    pairs: tuple[ConnectorCredentialPair, ConnectorCredentialPair],
) -> None:
    pair, _ = pairs
    failing_run = _attempt(db_session, pair, IndexingStatus.COMPLETED_WITH_ERRORS)
    entity = _entity_error(db_session, failing_run, "space-a")
    clean_run = _attempt(db_session, pair)

    check_indexing_completion(
        clean_run.id,
        CoordinationStatus(
            found=True,
            total_batches=0,
            completed_batches=0,
            total_failures=0,
            total_docs=0,
            total_chunks=0,
        ),
        MagicMock(),
        POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
    )

    _assert_closed(db_session, entity, _LATER_RUN, clean_run.id)


def test_ac2_a_successful_retry_closes_its_errors_with_the_retry_attempt(
    db_session: Session,
    pairs: tuple[ConnectorCredentialPair, ConnectorCredentialPair],
) -> None:
    pair, _ = pairs
    failing_run = _attempt(db_session, pair, IndexingStatus.COMPLETED_WITH_ERRORS)
    landed = _doc_error(db_session, failing_run, "doc-x")
    still_failing = _doc_error(db_session, failing_run, "doc-y")
    job = create_targeted_reindex_job(
        db_session=db_session,
        requested_by_user_id=None,
        targets=[
            TargetSpec(cc_pair_id=pair.id, document_id="doc-x", source_error_id=landed),
            TargetSpec(
                cc_pair_id=pair.id, document_id="doc-y", source_error_id=still_failing
            ),
        ],
    )
    db_session.commit()
    retry_attempt_ids = set(job.synthetic_attempt_ids)

    resolved_count, _ = resolve_failure_derived_targets(
        db_session, job.targeted_reindex_job_id, landed_keys={(pair.id, "doc-x")}
    )
    db_session.commit()

    assert resolved_count == 1
    is_resolved, reason, resolved_by, resolved_at = _closure(db_session, landed)
    assert is_resolved is True
    assert reason == _RETRY
    assert resolved_by in retry_attempt_ids
    assert resolved_at is not None
    _assert_open(db_session, still_failing)
