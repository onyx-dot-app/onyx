"""Resolve without retry: an operator closes chosen errors, or every error a
resolved run had so far, with the reason ``without_retry``. The row stays
unresolved for the poll cursor and Retry, leaves the open errors list, and
lists with its reason when resolved errors are asked for. A Retry still takes
it and closes it with ``retry``."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import (
    CCPairRunErrors,
    CCPairRunKind,
    CCPairRunStatusGroup,
    IndexingStatus,
)
from onyx.db.models import (
    CCPairRunResolution,
    ConnectorCredentialPair,
    IndexAttempt,
    IndexAttemptError,
    TargetedReindexJob,
    TargetedReindexJobTarget,
    User,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.db.targeted_reindex import (
    create_targeted_reindex_job,
    resolve_error_ids_to_targets,
    resolve_failure_derived_targets,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents import cc_pair as cc_pair_routes
from onyx.server.documents import models as document_models
from onyx.server.documents.cc_pair import (
    get_cc_pair_indexing_errors,
    get_cc_pair_runs,
    resolve_cc_pair_runs,
    resolve_matching_cc_pair_runs,
)
from onyx.server.documents.index_monitoring import resolve_indexing_runs
from onyx.server.documents.models import (
    CCPairRunKey,
    CCPairRunLevel,
    CCPairRunsResolveMatchingRequest,
    CCPairRunsResolveRequest,
)
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

# The pair feed lists perm sync kinds, which come from EE-only helpers.
pytestmark = pytest.mark.usefixtures("enable_ee")

_WITHOUT_RETRY = "without_retry"
_RETRY = "retry"


@pytest.fixture
def admin(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(
        db_session, f"errors_resolve_admin_{uuid4().hex[:8]}", is_admin=True
    )
    yield user
    db_session.rollback()
    delete_test_user(db_session, user)
    db_session.commit()


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
    db_session.query(CCPairRunResolution).filter(
        CCPairRunResolution.cc_pair_id.in_(pair_ids)
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
    db_session: Session, pair: ConnectorCredentialPair, status: IndexingStatus
) -> IndexAttempt:
    attempt = IndexAttempt(
        connector_credential_pair_id=pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=status,
        time_started=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    db_session.add(attempt)
    db_session.commit()
    return attempt


def _error(
    db_session: Session,
    attempt: IndexAttempt,
    document_id: str,
    *,
    message: str = "boom",
    is_resolved: bool = False,
    created: datetime | None = None,
) -> int:
    error = IndexAttemptError(
        index_attempt_id=attempt.id,
        connector_credential_pair_id=attempt.connector_credential_pair_id,
        document_id=document_id,
        failure_message=message,
        is_resolved=is_resolved,
    )
    db_session.add(error)
    db_session.flush()
    error.time_created = created or datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    return error.id


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


def _assert_resolved_without_retry(db_session: Session, error_id: int) -> None:
    is_resolved, reason, resolved_by, resolved_at = _closure(db_session, error_id)
    # The poll cursor and Retry read is_resolved, so it stays false.
    assert is_resolved is False
    assert reason == _WITHOUT_RETRY
    assert resolved_by is None
    assert resolved_at is not None


def _resolve_errors(
    db_session: Session,
    user: User,
    pair: ConnectorCredentialPair,
    error_ids: list[int],
) -> int:
    response = cc_pair_routes.resolve_cc_pair_indexing_errors(
        cc_pair_id=pair.id,
        request=document_models.IndexAttemptErrorsResolveRequest(error_ids=error_ids),
        user=user,
        db_session=db_session,
    )
    return response.resolved_count


def _resolve_runs(
    db_session: Session, user: User, pair: ConnectorCredentialPair, attempt_id: int
) -> int:
    return resolve_cc_pair_runs(
        cc_pair_id=pair.id,
        request=CCPairRunsResolveRequest(
            runs=[CCPairRunKey(kind=CCPairRunKind.INDEXING, attempt_id=attempt_id)]
        ),
        user=user,
        db_session=db_session,
    ).resolved_count


def _open_error_runs(
    db_session: Session,
    user: User,
    pair: ConnectorCredentialPair,
    status_groups: list[CCPairRunStatusGroup] | None,
) -> list[int]:
    return [
        run.attempt.id
        for run in get_cc_pair_runs(
            cc_pair_id=pair.id,
            page_num=0,
            page_size=10,
            since=None,
            until=None,
            kinds=[CCPairRunKind.INDEXING],
            status_groups=status_groups,
            q=None,
            errors=CCPairRunErrors.UNRESOLVED,
            superseded=None,
            resolved=False,
            user=user,
            db_session=db_session,
        ).items
    ]


def test_ac3_resolve_closes_the_pairs_chosen_errors_without_retry(
    db_session: Session,
    admin: User,
    pairs: tuple[ConnectorCredentialPair, ConnectorCredentialPair],
) -> None:
    pair, other_pair = pairs
    attempt = _attempt(db_session, pair, IndexingStatus.COMPLETED_WITH_ERRORS)
    other_attempt = _attempt(
        db_session, other_pair, IndexingStatus.COMPLETED_WITH_ERRORS
    )
    first = _error(db_session, attempt, "doc-a")
    second = _error(db_session, attempt, "doc-b")
    not_chosen = _error(db_session, attempt, "doc-c")
    already_resolved = _error(db_session, attempt, "doc-d", is_resolved=True)
    other_pairs = _error(db_session, other_attempt, "doc-a")

    resolved = _resolve_errors(
        db_session, admin, pair, [first, second, already_resolved, other_pairs]
    )

    assert resolved == 2
    _assert_resolved_without_retry(db_session, first)
    _assert_resolved_without_retry(db_session, second)
    _assert_open(db_session, not_chosen)
    _assert_open(db_session, other_pairs)
    assert _closure(db_session, already_resolved)[:3] == (True, None, None)
    # A second admin resolving the same errors resolves nothing.
    assert _resolve_errors(db_session, admin, pair, [first, second]) == 0


def test_ac3_resolve_refuses_a_caller_who_cannot_operate_the_pair(
    db_session: Session,
    pairs: tuple[ConnectorCredentialPair, ConnectorCredentialPair],
) -> None:
    pair, _ = pairs
    reader = create_test_user(db_session, f"errors_resolve_reader_{uuid4().hex[:8]}")
    attempt = _attempt(db_session, pair, IndexingStatus.COMPLETED_WITH_ERRORS)
    error = _error(db_session, attempt, "doc-a")

    try:
        with pytest.raises(OnyxError) as refused:
            _resolve_errors(db_session, reader, pair, [error])
        assert refused.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
        _assert_open(db_session, error)
    finally:
        db_session.rollback()
        delete_test_user(db_session, reader)
        db_session.commit()


def test_ac3_resolve_takes_one_to_500_error_ids() -> None:
    request_model = document_models.IndexAttemptErrorsResolveRequest
    assert request_model(error_ids=list(range(500))).error_ids == list(range(500))
    with pytest.raises(ValidationError):
        request_model(error_ids=[])
    with pytest.raises(ValidationError):
        request_model(error_ids=list(range(501)))


def test_ac6_errors_list_resolved_rows_with_how_they_closed(
    db_session: Session,
    admin: User,
    pairs: tuple[ConnectorCredentialPair, ConnectorCredentialPair],
) -> None:
    pair, _ = pairs
    attempt = _attempt(db_session, pair, IndexingStatus.COMPLETED_WITH_ERRORS)
    open_error = _error(db_session, attempt, "doc-open")
    dismissed = _error(db_session, attempt, "doc-dismissed")
    legacy = _error(db_session, attempt, "doc-legacy", is_resolved=True)
    _resolve_errors(db_session, admin, pair, [dismissed])

    def listed(
        include_resolved: bool,
    ) -> dict[int, tuple[str | None, int | None, bool]]:
        page = get_cc_pair_indexing_errors(
            cc_pair_id=pair.id,
            include_resolved=include_resolved,
            page_num=0,
            page_size=10,
            index_attempt_id=None,
            q=None,
            user=admin,
            db_session=db_session,
        )
        assert page.total_items == len(page.items)
        return {
            error.id: (
                error.resolved_reason,
                error.resolved_by_index_attempt_id,
                error.resolved_at is not None,
            )
            for error in page.items
        }

    assert listed(include_resolved=False) == {open_error: (None, None, False)}
    assert listed(include_resolved=True) == {
        open_error: (None, None, False),
        dismissed: (_WITHOUT_RETRY, None, True),
        # Closed before resolutions were recorded: resolved, with no reason.
        legacy: (None, None, False),
    }


def test_ac4_resolving_a_failed_run_closes_its_errors_without_retry(
    db_session: Session,
    admin: User,
    pairs: tuple[ConnectorCredentialPair, ConnectorCredentialPair],
) -> None:
    pair, _ = pairs
    failed = _attempt(db_session, pair, IndexingStatus.FAILED)
    other_run = _attempt(db_session, pair, IndexingStatus.COMPLETED_WITH_ERRORS)
    errors = [_error(db_session, failed, f"doc-{i}") for i in range(2)]
    other_runs_error = _error(db_session, other_run, "doc-other")

    assert _resolve_runs(db_session, admin, pair, failed.id) == 1

    for error in errors:
        _assert_resolved_without_retry(db_session, error)
    _assert_open(db_session, other_runs_error)
    assert db_session.get(
        CCPairRunResolution, (CCPairRunKind.INDEXING.value, failed.id)
    )


def test_ac4_resolve_matching_closes_the_runs_errors_without_retry(
    db_session: Session,
    admin: User,
    pairs: tuple[ConnectorCredentialPair, ConnectorCredentialPair],
) -> None:
    pair, _ = pairs
    with_errors = _attempt(db_session, pair, IndexingStatus.COMPLETED_WITH_ERRORS)
    error = _error(db_session, with_errors, "doc-a")

    response = resolve_matching_cc_pair_runs(
        cc_pair_id=pair.id,
        request=CCPairRunsResolveMatchingRequest(level=CCPairRunLevel.ERRORS),
        user=admin,
        db_session=db_session,
    )

    assert response.resolved_count == 1
    _assert_resolved_without_retry(db_session, error)


def test_ac4_fleet_resolve_closes_the_runs_errors_without_retry(
    db_session: Session,
    admin: User,
    pairs: tuple[ConnectorCredentialPair, ConnectorCredentialPair],
) -> None:
    pair, _ = pairs
    mark = f"fleet-resolve-{uuid4().hex}"
    failed = _attempt(db_session, pair, IndexingStatus.FAILED)
    error = _error(db_session, failed, "doc-a", message=f"{mark} failed")

    response = resolve_indexing_runs(
        request=CCPairRunsResolveMatchingRequest(q=mark),
        user=admin,
        db_session=db_session,
    )

    assert response.resolved_count == 1
    assert response.cc_pair_ids == [pair.id]
    _assert_resolved_without_retry(db_session, error)


def test_ac5_resolving_a_running_run_closes_its_errors_so_far(
    db_session: Session,
    admin: User,
    pairs: tuple[ConnectorCredentialPair, ConnectorCredentialPair],
) -> None:
    pair, _ = pairs
    running = _attempt(db_session, pair, IndexingStatus.IN_PROGRESS)
    so_far = _error(db_session, running, "doc-a")
    running_group = [CCPairRunStatusGroup.RUNNING]
    assert _open_error_runs(db_session, admin, pair, running_group) == [running.id]

    assert _resolve_runs(db_session, admin, pair, running.id) == 1

    _assert_resolved_without_retry(db_session, so_far)
    db_session.refresh(running)
    assert running.status == IndexingStatus.IN_PROGRESS
    assert _open_error_runs(db_session, admin, pair, running_group) == []

    later = _error(
        db_session,
        running,
        "doc-b",
        created=datetime.now(timezone.utc) + timedelta(minutes=1),
    )

    _assert_open(db_session, later)
    assert _open_error_runs(db_session, admin, pair, running_group) == [running.id]


def test_ac5_resolve_matching_takes_a_running_run(
    db_session: Session,
    admin: User,
    pairs: tuple[ConnectorCredentialPair, ConnectorCredentialPair],
) -> None:
    pair, _ = pairs
    running = _attempt(db_session, pair, IndexingStatus.IN_PROGRESS)
    so_far = _error(db_session, running, "doc-a")

    response = resolve_matching_cc_pair_runs(
        cc_pair_id=pair.id,
        request=CCPairRunsResolveMatchingRequest(level=CCPairRunLevel.ERRORS),
        user=admin,
        db_session=db_session,
    )

    assert response.resolved_count == 1
    _assert_resolved_without_retry(db_session, so_far)


def test_ac7_a_retry_takes_errors_resolved_without_retry(
    db_session: Session,
    admin: User,
    pairs: tuple[ConnectorCredentialPair, ConnectorCredentialPair],
) -> None:
    pair, _ = pairs
    attempt = _attempt(db_session, pair, IndexingStatus.COMPLETED_WITH_ERRORS)
    dismissed = _error(db_session, attempt, "doc-a")
    _resolve_errors(db_session, admin, pair, [dismissed])

    targets, skipped = resolve_error_ids_to_targets(db_session, [dismissed])
    assert skipped == 0
    assert [(t.cc_pair_id, t.document_id) for t in targets] == [(pair.id, "doc-a")]

    job = create_targeted_reindex_job(
        db_session=db_session, requested_by_user_id=admin.id, targets=targets
    )
    db_session.commit()
    resolved_count, _ = resolve_failure_derived_targets(
        db_session, job.targeted_reindex_job_id, landed_keys={(pair.id, "doc-a")}
    )
    db_session.commit()

    assert resolved_count == 1
    is_resolved, reason, resolved_by, resolved_at = _closure(db_session, dismissed)
    assert is_resolved is True
    assert reason == _RETRY
    assert resolved_by in set(job.synthetic_attempt_ids)
    assert resolved_at is not None
