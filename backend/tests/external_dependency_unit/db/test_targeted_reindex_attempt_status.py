"""A retry attempt ends FAILED when every target of its pair failed again, and
each document that failed again gets an open error on the retry attempt."""

from collections.abc import Callable, Generator, Sequence
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docprocessing.targeted_reindex_task import (
    run_targeted_reindex,
)
from onyx.background.indexing.run_targeted_reindex import CCPairReindexResult
from onyx.connectors.models import ConnectorFailure, DocumentFailure
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IndexingStatus
from onyx.db.indexing_coordination import IndexingCoordination
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


def test_every_target_failing_again_fails_the_retry_attempt(
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


def test_some_targets_failing_again_keeps_success_with_their_errors(
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


def test_the_status_is_set_per_pair(db_session: Session, made: _Made) -> None:
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


def test_a_pair_whose_processor_raises_fails_its_retry_attempt(
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


def _errors_of(
    db_session: Session, attempts: list[IndexAttempt]
) -> list[IndexAttemptError]:
    return (
        db_session.query(IndexAttemptError)
        .filter(IndexAttemptError.index_attempt_id.in_([a.id for a in attempts]))
        .all()
    )


def test_a_failed_retry_files_this_runs_failure_message(
    db_session: Session, made: _Made
) -> None:
    pair = made.pair()
    targets, _ = _failed_docs(db_session, pair, ["doc-new", "doc-unreturned"])

    def processor(**_: object) -> CCPairReindexResult:
        return CCPairReindexResult(
            landed_doc_ids=set(),
            failed_doc_ids={"doc-new", "doc-unreturned"},
            unsupported=False,
            failures={
                "doc-new": ConnectorFailure(
                    failed_document=DocumentFailure(document_id="doc-new"),
                    failure_message="parse failed again",
                )
            },
        )

    job_id = _run(db_session, made, targets, processor)

    attempts = _retry_attempts(db_session, job_id, pair)
    messages = {
        (e.document_id, e.failure_message) for e in _errors_of(db_session, attempts)
    }
    # A document with no new failure keeps the original error's message.
    assert messages == {("doc-new", "parse failed again"), ("doc-unreturned", "boom")}
    assert all(a.error_msg == "Every retried document failed again." for a in attempts)


def test_a_raising_pair_files_the_exception_on_its_errors_and_attempts(
    db_session: Session, made: _Made
) -> None:
    pair = made.pair()
    targets, _ = _failed_docs(db_session, pair, ["doc-raised"])

    def raises(**_: object) -> CCPairReindexResult:
        raise RuntimeError("no usable credential")

    job_id = _run(db_session, made, targets, raises)

    attempts = _retry_attempts(db_session, job_id, pair)
    assert all(a.error_msg == "no usable credential" for a in attempts)
    assert all(a.full_exception_trace for a in attempts)
    errors = _errors_of(db_session, attempts)
    assert {(e.failure_message, e.error_type) for e in errors} == {
        ("no usable credential", "RuntimeError")
    }
    # One error per retry attempt, one attempt per active search settings.
    assert len(errors) == len(attempts)


def test_a_landed_retry_closes_every_open_error_of_the_document(
    db_session: Session, made: _Made
) -> None:
    pair = made.pair()
    targets, original_error_ids = _failed_docs(db_session, pair, ["doc-x"])
    first_job_id = _run(db_session, made, targets, _outcome({}, {pair.id: {"doc-x"}}))
    retry_errors = _errors_of(
        db_session, _retry_attempts(db_session, first_job_id, pair)
    )
    assert retry_errors

    # Retry again from the error the first retry filed, and land the document.
    retry_targets, _ = resolve_error_ids_to_targets(db_session, [retry_errors[0].id])
    _run(db_session, made, retry_targets, _outcome({pair.id: {"doc-x"}}, {}))

    open_errors = (
        db_session.query(IndexAttemptError)
        .filter(
            IndexAttemptError.connector_credential_pair_id == pair.id,
            IndexAttemptError.document_id == "doc-x",
            IndexAttemptError.is_resolved.is_(False),
        )
        .all()
    )
    assert open_errors == []
    for error_id in original_error_ids:
        original = db_session.get(IndexAttemptError, error_id)
        assert original is not None
        assert original.is_resolved is True


def test_a_failed_error_insert_rolls_back_the_terminal_state(
    db_session: Session, made: _Made
) -> None:
    pair = made.pair()
    targets, _ = _failed_docs(db_session, pair, ["doc-a"])

    with (
        patch(
            "onyx.background.celery.tasks.docprocessing.targeted_reindex_task"
            ".create_index_attempt_errors__no_commit",
            side_effect=RuntimeError("insert failed"),
        ),
        pytest.raises(RuntimeError),
    ):
        _run(db_session, made, targets, _outcome({}, {pair.id: {"doc-a"}}))

    db_session.expire_all()
    job = (
        db_session.query(TargetedReindexJob)
        .filter(TargetedReindexJob.id.in_(made.job_ids))
        .one()
    )
    assert job.status == IndexingStatus.FAILED
    attempts = _retry_attempts(db_session, job.id, pair)
    assert all(a.status == IndexingStatus.FAILED for a in attempts)
    assert _errors_of(db_session, attempts) == []


def _cancel_pair(job_id: int, cc_pair_id: int) -> None:
    """Cancels one of the pair's retry attempts in its own session, as the
    cancel route does."""
    with get_session_with_current_tenant() as other_session:
        attempt_id = (
            other_session.query(IndexAttempt.id)
            .filter(
                IndexAttempt.targeted_reindex_job_id == job_id,
                IndexAttempt.connector_credential_pair_id == cc_pair_id,
            )
            .limit(1)
            .scalar()
        )
        assert attempt_id is not None
        IndexingCoordination.request_cancellation__no_commit(other_session, attempt_id)
        other_session.commit()


def test_a_cancel_skips_the_pairs_not_yet_fetched(
    db_session: Session, made: _Made
) -> None:
    first = made.pair()
    second = made.pair()
    first_targets, _ = _failed_docs(db_session, first, ["doc-first"])
    second_targets, _ = _failed_docs(db_session, second, ["doc-second"])
    fetched: list[int] = []

    def cancels_the_other_pair(cc_pair_id: int, **_: object) -> CCPairReindexResult:
        fetched.append(cc_pair_id)
        other = second.id if cc_pair_id == first.id else first.id
        _cancel_pair(made.job_ids[-1], other)
        doc_id = "doc-first" if cc_pair_id == first.id else "doc-second"
        return CCPairReindexResult(
            landed_doc_ids={doc_id}, failed_doc_ids=set(), unsupported=False
        )

    job_id = _run(
        db_session, made, first_targets + second_targets, cancels_the_other_pair
    )

    assert len(fetched) == 1
    ran = first if fetched[0] == first.id else second
    skipped = second if ran is first else first
    skipped_attempts = _retry_attempts(db_session, job_id, skipped)
    assert all(a.status == IndexingStatus.CANCELED for a in skipped_attempts)
    assert all(a.error_msg == "Canceled by a user." for a in skipped_attempts)
    assert _errors_of(db_session, skipped_attempts) == []
    assert all(
        a.status == IndexingStatus.SUCCESS
        for a in _retry_attempts(db_session, job_id, ran)
    )


def test_a_cancel_during_a_pair_ends_its_attempts_canceled(
    db_session: Session, made: _Made
) -> None:
    pair = made.pair()
    targets, _ = _failed_docs(db_session, pair, ["doc-a"])

    def canceled_while_running(cc_pair_id: int, **_: object) -> CCPairReindexResult:
        _cancel_pair(made.job_ids[-1], cc_pair_id)
        return CCPairReindexResult(
            landed_doc_ids=set(), failed_doc_ids={"doc-a"}, unsupported=False
        )

    job_id = _run(db_session, made, targets, canceled_while_running)

    attempts = _retry_attempts(db_session, job_id, pair)
    assert all(a.status == IndexingStatus.CANCELED for a in attempts)
    assert all(a.time_finished is not None for a in attempts)
    # The document that failed again before the Cancel keeps its error.
    assert {doc for doc, _, _ in _retry_error_docs(db_session, attempts)} == {"doc-a"}


def test_a_pair_that_ends_before_fetching_files_its_reason(
    db_session: Session, made: _Made
) -> None:
    pair = made.pair()
    targets, _ = _failed_docs(db_session, pair, ["doc-a"])
    reason = "This connector does not support retrying documents."

    def unsupported(**_: object) -> CCPairReindexResult:
        return CCPairReindexResult(set(), {"doc-a"}, unsupported=True, reason=reason)

    job_id = _run(db_session, made, targets, unsupported)

    attempts = _retry_attempts(db_session, job_id, pair)
    assert all(a.status == IndexingStatus.FAILED for a in attempts)
    assert all(a.error_msg == reason for a in attempts)
    assert {e.failure_message for e in _errors_of(db_session, attempts)} == {reason}
