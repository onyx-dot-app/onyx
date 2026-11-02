"""The retry attempt's honest status: a targeted reindex attempt ends FAILED
when every target of its pair failed again and SUCCESS otherwise, set per pair,
and each document that failed again gets an open IndexAttemptError on the retry
attempt while the original error stays where it was.

The per-pair processor is mocked as in test_targeted_reindex_task.py."""

from collections.abc import Callable, Generator, Sequence
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docprocessing.targeted_reindex_task import (
    run_targeted_reindex,
)
from onyx.background.indexing.run_targeted_reindex import CCPairReindexResult
from onyx.db.enums import IndexingStatus
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
    resolve_error_ids_to_targets,
)
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_PROCESSOR_PATH = (
    "onyx.background.indexing.run_targeted_reindex.process_targets_for_cc_pair"
)


class _Made:
    def __init__(self, db_session: Session) -> None:
        self.db_session = db_session
        self.pairs: list[ConnectorCredentialPair] = []
        self.job_ids: list[int] = []

    def pair(self) -> ConnectorCredentialPair:
        pair = make_cc_pair(self.db_session)
        self.pairs.append(pair)
        return pair

    def cleanup(self) -> None:
        self.db_session.rollback()
        pair_ids = [pair.id for pair in self.pairs]
        self.db_session.query(TargetedReindexJobTarget).filter(
            TargetedReindexJobTarget.cc_pair_id.in_(pair_ids)
        ).delete(synchronize_session="fetch")
        for model in (IndexAttemptError, IndexAttempt):
            self.db_session.query(model).filter(
                model.connector_credential_pair_id.in_(pair_ids)
            ).delete(synchronize_session="fetch")
        self.db_session.query(TargetedReindexJob).filter(
            TargetedReindexJob.id.in_(self.job_ids)
        ).delete(synchronize_session="fetch")
        self.db_session.commit()
        for pair in self.pairs:
            cleanup_cc_pair(self.db_session, pair)


@pytest.fixture
def made(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[_Made, None, None]:
    created = _Made(db_session)
    yield created
    created.cleanup()


def _failed_docs(
    db_session: Session, pair: ConnectorCredentialPair, doc_ids: Sequence[str]
) -> tuple[list[TargetSpec], list[int]]:
    """A failed full run with one open error per document, and the Retry
    targets those errors resolve to."""
    parent = IndexAttempt(
        connector_credential_pair_id=pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=IndexingStatus.FAILED,
    )
    db_session.add(parent)
    db_session.flush()
    errors = [
        IndexAttemptError(
            index_attempt_id=parent.id,
            connector_credential_pair_id=pair.id,
            document_id=doc_id,
            failure_message="boom",
            is_resolved=False,
        )
        for doc_id in doc_ids
    ]
    db_session.add_all(errors)
    db_session.commit()
    targets, _ = resolve_error_ids_to_targets(db_session, [e.id for e in errors])
    return targets, [e.id for e in errors]


def _run(
    db_session: Session,
    made: _Made,
    targets: list[TargetSpec],
    processor: Callable[..., CCPairReindexResult],
) -> int:
    result = create_targeted_reindex_job(
        db_session=db_session, requested_by_user_id=None, targets=targets
    )
    made.job_ids.append(result.targeted_reindex_job_id)
    with patch(_PROCESSOR_PATH, side_effect=processor):
        run_targeted_reindex(
            targeted_reindex_job_id=result.targeted_reindex_job_id,
            celery_task_id="test-celery-id",
        )
    db_session.expire_all()
    return result.targeted_reindex_job_id


def _outcome(
    landed: dict[int, set[str]], failed: dict[int, set[str]]
) -> Callable[..., CCPairReindexResult]:
    def processor(cc_pair_id: int, **_: object) -> CCPairReindexResult:
        return CCPairReindexResult(
            landed_doc_ids=landed.get(cc_pair_id, set()),
            failed_doc_ids=failed.get(cc_pair_id, set()),
            unsupported=False,
        )

    return processor


def _retry_attempts(
    db_session: Session, job_id: int, pair: ConnectorCredentialPair
) -> list[IndexAttempt]:
    attempts = (
        db_session.query(IndexAttempt)
        .filter(
            IndexAttempt.targeted_reindex_job_id == job_id,
            IndexAttempt.connector_credential_pair_id == pair.id,
        )
        .all()
    )
    # One per active search settings. CI may run with PRESENT and FUTURE.
    assert attempts
    return attempts


def _retry_error_docs(
    db_session: Session, attempts: list[IndexAttempt]
) -> list[tuple[str | None, bool, int]]:
    rows = (
        db_session.query(IndexAttemptError)
        .filter(IndexAttemptError.index_attempt_id.in_([a.id for a in attempts]))
        .all()
    )
    return sorted(
        (row.document_id, row.is_resolved, row.connector_credential_pair_id)
        for row in rows
    )


def test_ac7_every_target_failing_again_fails_the_retry_attempt(
    db_session: Session, made: _Made
) -> None:
    pair = made.pair()
    targets, original_error_ids = _failed_docs(db_session, pair, ["doc-a", "doc-b"])

    job_id = _run(
        db_session, made, targets, _outcome({}, {pair.id: {"doc-a", "doc-b"}})
    )

    attempts = _retry_attempts(db_session, job_id, pair)
    assert all(a.status == IndexingStatus.FAILED for a in attempts)
    assert all(a.time_finished is not None for a in attempts)
    assert {doc for doc, _, _ in _retry_error_docs(db_session, attempts)} == {
        "doc-a",
        "doc-b",
    }
    assert all(
        not resolved and cc_pair_id == pair.id
        for _, resolved, cc_pair_id in _retry_error_docs(db_session, attempts)
    )
    # The original errors stay open on the run that first failed.
    for error_id in original_error_ids:
        original = db_session.get(IndexAttemptError, error_id)
        assert original is not None
        assert original.is_resolved is False
        assert original.index_attempt_id not in {a.id for a in attempts}


def test_ac7_some_targets_failing_again_keeps_success_with_their_errors(
    db_session: Session, made: _Made
) -> None:
    pair = made.pair()
    targets, _ = _failed_docs(db_session, pair, ["doc-landed", "doc-broken"])

    job_id = _run(
        db_session,
        made,
        targets,
        _outcome({pair.id: {"doc-landed"}}, {pair.id: {"doc-broken"}}),
    )

    attempts = _retry_attempts(db_session, job_id, pair)
    assert {doc for doc, _, _ in _retry_error_docs(db_session, attempts)} == {
        "doc-broken"
    }
    assert all(a.status == IndexingStatus.SUCCESS for a in attempts)


def test_ac7_the_status_is_set_per_pair(db_session: Session, made: _Made) -> None:
    broken = made.pair()
    healthy = made.pair()
    broken_targets, _ = _failed_docs(db_session, broken, ["doc-broken"])
    healthy_targets, _ = _failed_docs(db_session, healthy, ["doc-healthy"])

    job_id = _run(
        db_session,
        made,
        broken_targets + healthy_targets,
        _outcome({healthy.id: {"doc-healthy"}}, {broken.id: {"doc-broken"}}),
    )

    broken_attempts = _retry_attempts(db_session, job_id, broken)
    healthy_attempts = _retry_attempts(db_session, job_id, healthy)
    assert all(a.status == IndexingStatus.FAILED for a in broken_attempts)
    assert all(a.status == IndexingStatus.SUCCESS for a in healthy_attempts)
    assert {doc for doc, _, _ in _retry_error_docs(db_session, broken_attempts)} == {
        "doc-broken"
    }
    assert _retry_error_docs(db_session, healthy_attempts) == []


def test_ac7_a_pair_whose_processor_raises_fails_its_retry_attempt(
    db_session: Session, made: _Made
) -> None:
    pair = made.pair()
    targets, _ = _failed_docs(db_session, pair, ["doc-raised"])

    def raises(cc_pair_id: int, **_: object) -> CCPairReindexResult:
        raise RuntimeError(f"connector down for {cc_pair_id}")

    job_id = _run(db_session, made, targets, raises)

    attempts = _retry_attempts(db_session, job_id, pair)
    assert all(a.status == IndexingStatus.FAILED for a in attempts)
    assert {doc for doc, _, _ in _retry_error_docs(db_session, attempts)} == {
        "doc-raised"
    }
