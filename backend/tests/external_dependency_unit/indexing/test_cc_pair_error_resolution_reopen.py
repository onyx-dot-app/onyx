"""What reopens a resolved index run, the readers that share the open error
definition with the pair's errors list, and how a Retry and a batched
resolve-matching close errors."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docprocessing.targeted_reindex_task import (
    run_targeted_reindex,
)
from onyx.background.indexing.run_targeted_reindex import CCPairReindexResult
from onyx.db import cc_pair_runs
from onyx.db.cc_pair_run_resolution import get_resolution_times
from onyx.db.enums import (
    CCPairRunErrors,
    CCPairRunKind,
    CCPairRunStatusGroup,
    IndexingStatus,
)
from onyx.db.index_attempt import (
    get_index_attempt_errors_across_connectors,
    get_open_error_counts_for_index_attempts,
    mark_attempt_failed,
)
from onyx.db.models import (
    CCPairRunResolution,
    ConnectorCredentialPair,
    IndexAttempt,
    User,
)
from onyx.db.targeted_reindex import (
    create_targeted_reindex_job,
    resolve_error_ids_to_targets,
)
from onyx.server.documents.cc_pair import (
    get_cc_pair_runs,
    resolve_matching_cc_pair_runs,
)
from onyx.server.documents.models import (
    CCPairIndexRun,
    CCPairRunLevel,
    CCPairRunsResolveMatchingRequest,
)
from tests.external_dependency_unit.indexing.test_cc_pair_errors_resolve_route import (
    _RETRY,
    _assert_open,
    _assert_resolved_without_retry,
    _attempt,
    _closure,
    _error,
    _open_error_runs,
    _resolve_errors,
    _resolve_runs,
    admin,  # noqa: F401
    pairs,  # noqa: F401
)

# The pair feed lists perm sync kinds, which come from EE-only helpers.
pytestmark = pytest.mark.usefixtures("enable_ee")

_Pairs = tuple[ConnectorCredentialPair, ConnectorCredentialPair]


def _runs(
    db_session: Session,
    user: User,
    pair: ConnectorCredentialPair,
    status_groups: list[CCPairRunStatusGroup] | None = None,
    errors: CCPairRunErrors | None = None,
    resolved: bool | None = None,
) -> dict[int, CCPairIndexRun]:
    page = get_cc_pair_runs(
        cc_pair_id=pair.id,
        page_num=0,
        page_size=10,
        since=None,
        until=None,
        kinds=[CCPairRunKind.INDEXING],
        status_groups=status_groups,
        q=None,
        errors=errors,
        superseded=None,
        resolved=resolved,
        user=user,
        db_session=db_session,
    )
    return {
        run.attempt.id: run for run in page.items if isinstance(run, CCPairIndexRun)
    }


def _backdate_resolution(
    db_session: Session, attempt_id: int, resolved_at: datetime
) -> None:
    db_session.execute(
        update(CCPairRunResolution)
        .where(
            CCPairRunResolution.run_kind == CCPairRunKind.INDEXING.value,
            CCPairRunResolution.attempt_id == attempt_id,
        )
        .values(resolved_at=resolved_at)
    )
    db_session.commit()


def test_a_resolved_running_run_that_then_fails_opens_again(
    db_session: Session,
    admin: User,  # noqa: F811
    pairs: _Pairs,  # noqa: F811
) -> None:
    pair, _ = pairs
    running = _attempt(db_session, pair, IndexingStatus.IN_PROGRESS)
    _error(db_session, running, "doc-a")
    failed_group = [CCPairRunStatusGroup.FAILED]
    assert _resolve_runs(db_session, admin, pair, running.id) == 1
    # Minutes apart, as time_finished is the app's clock and resolved_at the
    # database's, which can disagree by more than the test's own gaps.
    now = datetime.now(timezone.utc)
    _backdate_resolution(db_session, running.id, now - timedelta(minutes=2))

    mark_attempt_failed(running.id, db_session, failure_reason="connector raised")
    db_session.execute(
        update(IndexAttempt)
        .where(IndexAttempt.id == running.id)
        .values(time_finished=now - timedelta(minutes=1))
    )
    db_session.commit()

    assert list(_runs(db_session, admin, pair, failed_group, resolved=False)) == [
        running.id
    ]
    assert _runs(db_session, admin, pair)[running.id].resolved_at is None

    # Resolved after it failed, the run stays closed.
    assert _resolve_runs(db_session, admin, pair, running.id) == 1
    assert _runs(db_session, admin, pair, failed_group, resolved=False) == {}
    assert _runs(db_session, admin, pair)[running.id].resolved_at is not None


def test_a_later_error_clears_the_runs_resolved_at_until_it_is_resolved_again(
    db_session: Session,
    admin: User,  # noqa: F811
    pairs: _Pairs,  # noqa: F811
) -> None:
    pair, _ = pairs
    running = _attempt(db_session, pair, IndexingStatus.IN_PROGRESS)
    _error(db_session, running, "doc-a")
    assert _resolve_runs(db_session, admin, pair, running.id) == 1
    # Backdated so the re-resolve's later resolved_at shows.
    first_resolved_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    _backdate_resolution(db_session, running.id, first_resolved_at)
    assert _runs(db_session, admin, pair)[running.id].resolved_at == first_resolved_at

    later = _error(db_session, running, "doc-b")
    assert _runs(db_session, admin, pair)[running.id].resolved_at is None

    assert _resolve_runs(db_session, admin, pair, running.id) == 1
    _assert_resolved_without_retry(db_session, later)
    again_resolved_at = _runs(db_session, admin, pair)[running.id].resolved_at
    assert again_resolved_at is not None
    assert again_resolved_at > first_resolved_at


def test_an_error_filed_after_the_resolve_started_stays_open(
    db_session: Session,
    admin: User,  # noqa: F811
    pairs: _Pairs,  # noqa: F811
) -> None:
    pair, _ = pairs
    running = _attempt(db_session, pair, IndexingStatus.IN_PROGRESS)
    so_far = _error(db_session, running, "doc-a")
    after = _error(
        db_session,
        running,
        "doc-b",
        created=datetime.now(timezone.utc) + timedelta(minutes=1),
    )

    assert _resolve_runs(db_session, admin, pair, running.id) == 1

    _assert_resolved_without_retry(db_session, so_far)
    _assert_open(db_session, after)
    running_group = [CCPairRunStatusGroup.RUNNING]
    assert _open_error_runs(db_session, admin, pair, running_group) == [running.id]


def test_an_error_whose_writer_began_before_the_resolve_reopens_the_run(
    db_session: Session,
    admin: User,  # noqa: F811
    pairs: _Pairs,  # noqa: F811
) -> None:
    pair, _ = pairs
    running = _attempt(db_session, pair, IndexingStatus.IN_PROGRESS)
    _error(db_session, running, "doc-a")
    assert _resolve_runs(db_session, admin, pair, running.id) == 1
    resolved_at = _runs(db_session, admin, pair)[running.id].resolved_at
    assert resolved_at is not None

    # time_created is the writer's transaction start, so this row is stamped
    # before the click but committed after the close ran.
    straggler = _error(
        db_session, running, "doc-b", created=resolved_at - timedelta(seconds=1)
    )

    running_group = [CCPairRunStatusGroup.RUNNING]
    assert _open_error_runs(db_session, admin, pair, running_group) == [running.id]
    assert _runs(db_session, admin, pair)[running.id].resolved_at is None
    counts = get_open_error_counts_for_index_attempts(db_session, [running.id])
    assert counts[running.id].total == 1
    assert (
        get_resolution_times(db_session, [(CCPairRunKind.INDEXING, running.id)]) == {}
    )

    assert _resolve_runs(db_session, admin, pair, running.id) == 1
    _assert_resolved_without_retry(db_session, straggler)
    assert _open_error_runs(db_session, admin, pair, running_group) == []


def test_errors_resolved_one_by_one_leave_the_runs_open_errors(
    db_session: Session,
    admin: User,  # noqa: F811
    pairs: _Pairs,  # noqa: F811
) -> None:
    pair, _ = pairs
    attempt = _attempt(db_session, pair, IndexingStatus.COMPLETED_WITH_ERRORS)
    errors = [_error(db_session, attempt, f"doc-{i}") for i in range(2)]
    assert _open_error_runs(db_session, admin, pair, None) == [attempt.id]

    assert _resolve_errors(db_session, admin, pair, errors) == 2

    assert _open_error_runs(db_session, admin, pair, None) == []
    snapshot = _runs(db_session, admin, pair)[attempt.id].attempt
    assert snapshot.open_error_count == 0
    assert snapshot.open_doc_error_count == 0


def test_failed_documents_hides_errors_resolved_without_retry(
    db_session: Session,
    admin: User,  # noqa: F811
    pairs: _Pairs,  # noqa: F811
) -> None:
    pair, _ = pairs
    attempt = _attempt(db_session, pair, IndexingStatus.COMPLETED_WITH_ERRORS)
    open_error = _error(db_session, attempt, "doc-open")
    dismissed = _error(db_session, attempt, "doc-dismissed")
    _resolve_errors(db_session, admin, pair, [dismissed])

    listed, total = get_index_attempt_errors_across_connectors(
        db_session, cc_pair_id=pair.id, unresolved_only=True
    )

    assert [error.id for error in listed] == [open_error]
    assert total == 1


def test_a_retry_closes_every_open_error_of_a_landed_document_as_retry(
    db_session: Session,
    admin: User,  # noqa: F811
    pairs: _Pairs,  # noqa: F811
) -> None:
    pair, _ = pairs
    attempt = _attempt(db_session, pair, IndexingStatus.COMPLETED_WITH_ERRORS)
    source = _error(db_session, attempt, "doc-a")
    # Another open row on the document, as an earlier failed Retry files.
    earlier = _error(
        db_session,
        attempt,
        "doc-a",
        created=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    targets, _ = resolve_error_ids_to_targets(db_session, [source])
    job = create_targeted_reindex_job(
        db_session=db_session, requested_by_user_id=admin.id, targets=targets
    )
    db_session.commit()

    with patch(
        "onyx.background.indexing.run_targeted_reindex.process_targets_for_cc_pair",
        return_value=CCPairReindexResult(
            landed_doc_ids={"doc-a"}, failed_doc_ids=set(), unsupported=False
        ),
    ):
        run_targeted_reindex(
            targeted_reindex_job_id=job.targeted_reindex_job_id,
            celery_task_id="test-celery-id",
        )

    for error_id in (source, earlier):
        is_resolved, reason, resolved_by, resolved_at = _closure(db_session, error_id)
        assert is_resolved is True
        assert reason == _RETRY
        assert resolved_by in set(job.synthetic_attempt_ids)
        assert resolved_at is not None


def test_resolve_matching_in_batches_keeps_the_total(
    db_session: Session,
    admin: User,  # noqa: F811
    pairs: _Pairs,  # noqa: F811
) -> None:
    pair, _ = pairs
    errors = [
        _error(
            db_session,
            _attempt(db_session, pair, IndexingStatus.COMPLETED_WITH_ERRORS),
            f"doc-{i}",
        )
        for i in range(3)
    ]

    with patch.object(cc_pair_runs, "_RESOLVE_BATCH_SIZE", 2):
        response = resolve_matching_cc_pair_runs(
            cc_pair_id=pair.id,
            request=CCPairRunsResolveMatchingRequest(level=CCPairRunLevel.ERRORS),
            user=admin,
            db_session=db_session,
        )

    assert response.resolved_count == 3
    for error_id in errors:
        _assert_resolved_without_retry(db_session, error_id)
