"""Coverage for a pair's run feed and the single-attempt cancel route: kinds
merge newest first across pages, another pair's runs stay out unless its source
shares one group sync history, counts ignore the
status filter, `since` and `q` narrow the feed, `q` also reads an attempt's
document errors, `errors` keeps runs with open or resolved document errors, `superseded`
splits failed runs on whether a newer run of the kind followed them, a
non-synced pair shows only indexing, cancel acts only on active attempts of a
pair the caller operates,
and throughput counts only the pair's runs created inside the window."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db import cc_pair_runs
from onyx.db.enums import (
    AccessType,
    CCPairRunErrors,
    CCPairRunKind,
    CCPairRunStatusGroup,
    ConnectorCredentialPairStatus,
    IndexingStatus,
    IndexModelStatus,
    PermissionSyncStatus,
)
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    DocPermissionSyncAttempt,
    ExternalGroupPermissionSyncAttempt,
    IndexAttempt,
    IndexAttemptError,
    SearchSettings,
    User,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents import cc_pair as cc_pair_routes
from onyx.server.documents.cc_pair import (
    cancel_index_attempt,
    get_cc_pair_runs,
    get_cc_pair_throughput,
)
from onyx.server.documents.models import (
    CCPairRunsResponse,
    CCPairThroughputWindow,
    IndexAttemptSnapshot,
)
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair_and_future,
    make_future_search_settings,
)

# The sync kinds come from the EE-only sync_params helpers.
pytestmark = pytest.mark.usefixtures("enable_ee")

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _create_cc_pair(
    db_session: Session,
    access_type: AccessType,
    source: DocumentSource = DocumentSource.GOOGLE_DRIVE,
) -> ConnectorCredentialPair:
    owner = create_test_user(db_session, "runs_owner")
    connector = Connector(
        name="Runs Test Connector",
        source=source,
        input_type=InputType.POLL,
        connector_specific_config={},
        refresh_freq=None,
        # Scheduled to prune, so the feed lists the pruning kind.
        prune_freq=86400,
    )
    db_session.add(connector)
    db_session.flush()
    credential = Credential(credential_json={}, user_id=owner.id, admin_public=True)
    db_session.add(credential)
    db_session.flush()
    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name="Runs Test Pair",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=access_type,
    )
    db_session.add(cc_pair)
    db_session.commit()
    return cc_pair


def _index_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    minutes: int,
    status: IndexingStatus,
    error_msg: str | None = None,
    celery_task_id: str | None = None,
    started: bool = True,
    search_settings_id: int | None = None,
) -> IndexAttempt:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=(
            search_settings_id or get_current_search_settings(db_session).id
        ),
        from_beginning=False,
        status=status,
        error_msg=error_msg,
        celery_task_id=celery_task_id,
        time_started=_T0 + timedelta(minutes=minutes) if started else None,
    )
    db_session.add(attempt)
    db_session.flush()
    # Fixed times keep the order and the since window off the wall clock.
    attempt.time_created = _T0 + timedelta(minutes=minutes)
    db_session.commit()
    return attempt


def _doc_sync(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    minutes: int,
    status: PermissionSyncStatus,
) -> DocPermissionSyncAttempt:
    attempt = DocPermissionSyncAttempt(
        connector_credential_pair_id=cc_pair.id, status=status
    )
    db_session.add(attempt)
    db_session.flush()
    attempt.time_created = _T0 + timedelta(minutes=minutes)
    db_session.commit()
    return attempt


def _group_sync(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    minutes: int,
    status: PermissionSyncStatus,
    error_message: str | None = None,
) -> ExternalGroupPermissionSyncAttempt:
    attempt = ExternalGroupPermissionSyncAttempt(
        connector_credential_pair_id=cc_pair.id,
        status=status,
        error_message=error_message,
    )
    db_session.add(attempt)
    db_session.flush()
    attempt.time_created = _T0 + timedelta(minutes=minutes)
    db_session.commit()
    return attempt


def _runs(
    db_session: Session,
    user: User,
    cc_pair: ConnectorCredentialPair,
    page_num: int = 0,
    page_size: int = 10,
    since: datetime | None = None,
    kinds: list[CCPairRunKind] | None = None,
    status_groups: list[CCPairRunStatusGroup] | None = None,
    q: str | None = None,
    errors: CCPairRunErrors | None = None,
    superseded: bool | None = None,
) -> CCPairRunsResponse:
    return get_cc_pair_runs(
        cc_pair_id=cc_pair.id,
        page_num=page_num,
        page_size=page_size,
        since=since,
        kinds=kinds,
        status_groups=status_groups,
        q=q,
        errors=errors,
        superseded=superseded,
        resolved=None,
        user=user,
        db_session=db_session,
    )


def _doc_error(db_session: Session, attempt: IndexAttempt, is_resolved: bool) -> None:
    db_session.add(
        IndexAttemptError(
            index_attempt_id=attempt.id,
            connector_credential_pair_id=attempt.connector_credential_pair_id,
            document_id=f"doc-{attempt.id}-{is_resolved}",
            failure_message="boom",
            is_resolved=is_resolved,
        )
    )
    db_session.commit()


def _order(response: CCPairRunsResponse) -> list[tuple[CCPairRunKind, int]]:
    return [(run.kind, run.attempt.id) for run in response.items]


def test_merges_kinds_newest_first_across_pages(db_session: Session) -> None:
    admin = create_test_user(db_session, "runs_admin", is_admin=True)
    cc_pair = _create_cc_pair(db_session, AccessType.SYNC)
    index_0 = _index_attempt(db_session, cc_pair, 0, IndexingStatus.SUCCESS)
    doc_1 = _doc_sync(db_session, cc_pair, 1, PermissionSyncStatus.SUCCESS)
    index_2 = _index_attempt(db_session, cc_pair, 2, IndexingStatus.FAILED)
    group_3 = _group_sync(db_session, cc_pair, 3, PermissionSyncStatus.SUCCESS)
    index_4 = _index_attempt(db_session, cc_pair, 4, IndexingStatus.IN_PROGRESS)
    doc_5 = _doc_sync(db_session, cc_pair, 5, PermissionSyncStatus.FAILED)

    first = _runs(db_session, admin, cc_pair, page_num=0, page_size=4)
    second = _runs(db_session, admin, cc_pair, page_num=1, page_size=4)

    assert first.kinds == [
        CCPairRunKind.INDEXING,
        CCPairRunKind.DOC_PERMISSION_SYNC,
        CCPairRunKind.GROUP_SYNC,
        CCPairRunKind.PRUNING,
        CCPairRunKind.CHECKS,
    ]
    assert first.total_items == 6
    assert _order(first) == [
        (CCPairRunKind.DOC_PERMISSION_SYNC, doc_5.id),
        (CCPairRunKind.INDEXING, index_4.id),
        (CCPairRunKind.GROUP_SYNC, group_3.id),
        (CCPairRunKind.INDEXING, index_2.id),
    ]
    assert _order(second) == [
        (CCPairRunKind.DOC_PERMISSION_SYNC, doc_1.id),
        (CCPairRunKind.INDEXING, index_0.id),
    ]


def test_leaves_out_a_run_deleted_while_the_page_loads(db_session: Session) -> None:
    admin = create_test_user(db_session, "runs_admin", is_admin=True)
    cc_pair = _create_cc_pair(db_session, AccessType.PUBLIC)
    kept = _index_attempt(db_session, cc_pair, 0, IndexingStatus.SUCCESS)
    gone = _index_attempt(db_session, cc_pair, 1, IndexingStatus.SUCCESS)
    load_rows = cc_pair_runs._rows_by_id

    def load_rows_without_gone(
        db_session: Session, model: type[IndexAttempt], ids: list[int]
    ) -> dict[int, IndexAttempt]:
        return {
            row_id: row
            for row_id, row in load_rows(db_session, model, ids).items()
            if row_id != gone.id
        }

    with patch.object(cc_pair_runs, "_rows_by_id", load_rows_without_gone):
        response = _runs(db_session, admin, cc_pair, page_num=0, page_size=10)

    assert _order(response) == [(CCPairRunKind.INDEXING, kept.id)]


def test_errors_filter_keeps_runs_with_open_or_resolved_doc_errors(
    db_session: Session,
) -> None:
    admin = create_test_user(db_session, "runs_admin", is_admin=True)
    cc_pair = _create_cc_pair(db_session, AccessType.SYNC)
    clean = _index_attempt(db_session, cc_pair, 0, IndexingStatus.SUCCESS)
    open_errors = _index_attempt(
        db_session, cc_pair, 1, IndexingStatus.COMPLETED_WITH_ERRORS
    )
    _doc_error(db_session, open_errors, is_resolved=False)
    _doc_error(db_session, open_errors, is_resolved=True)
    resolved = _index_attempt(db_session, cc_pair, 2, IndexingStatus.SUCCESS)
    _doc_error(db_session, resolved, is_resolved=True)
    unreadable = _doc_sync(db_session, cc_pair, 3, PermissionSyncStatus.SUCCESS)
    unreadable.docs_with_permission_errors = 2
    _group_sync(db_session, cc_pair, 4, PermissionSyncStatus.FAILED)
    db_session.commit()

    unresolved = _runs(db_session, admin, cc_pair, errors=CCPairRunErrors.UNRESOLVED)
    resolved_only = _runs(db_session, admin, cc_pair, errors=CCPairRunErrors.RESOLVED)
    # The activity panel's errors group: open errors on runs that did not fail.
    not_failed = _runs(
        db_session,
        admin,
        cc_pair,
        status_groups=[CCPairRunStatusGroup.RUNNING, CCPairRunStatusGroup.SUCCEEDED],
        errors=CCPairRunErrors.UNRESOLVED,
    )
    by_doc_error = _runs(db_session, admin, cc_pair, q="boom")

    assert _order(unresolved) == [
        (CCPairRunKind.DOC_PERMISSION_SYNC, unreadable.id),
        (CCPairRunKind.INDEXING, open_errors.id),
    ]
    assert unresolved.total_items == 2
    assert unresolved.status_counts[CCPairRunStatusGroup.SUCCEEDED] == 2
    assert _order(resolved_only) == [(CCPairRunKind.INDEXING, resolved.id)]
    # The open count leaves out the resolved error, the total keeps it.
    open_run = next(run for run in unresolved.items if run.kind == "indexing")
    assert open_run.attempt.error_count == 2
    assert open_run.attempt.open_doc_error_count == 1
    resolved_run = next(run for run in resolved_only.items if run.kind == "indexing")
    assert resolved_run.attempt.open_doc_error_count == 0
    assert _order(not_failed) == _order(unresolved)
    assert not_failed.total_items == 2
    assert _order(by_doc_error) == [
        (CCPairRunKind.INDEXING, resolved.id),
        (CCPairRunKind.INDEXING, open_errors.id),
    ]
    assert clean.id not in {
        run.attempt.id for run in by_doc_error.items if run.kind == "indexing"
    }


def test_lists_a_model_switch_runs_and_marks_them(db_session: Session) -> None:
    admin = create_test_user(db_session, "runs_admin", is_admin=True)
    cc_pair = _create_cc_pair(db_session, AccessType.PUBLIC)
    future = make_future_search_settings(db_session)
    past = make_future_search_settings(db_session, status=IndexModelStatus.PAST)
    try:
        current = _index_attempt(db_session, cc_pair, 0, IndexingStatus.SUCCESS)
        new_model = _index_attempt(
            db_session,
            cc_pair,
            1,
            IndexingStatus.COMPLETED_WITH_ERRORS,
            search_settings_id=future.id,
        )
        _doc_error(db_session, new_model, is_resolved=False)
        _index_attempt(
            db_session, cc_pair, 2, IndexingStatus.SUCCESS, search_settings_id=past.id
        )

        feed = _runs(db_session, admin, cc_pair)
        unresolved = _runs(
            db_session, admin, cc_pair, errors=CCPairRunErrors.UNRESOLVED
        )

        # The retired model's run stays out of the feed.
        assert _order(feed) == [
            (CCPairRunKind.INDEXING, new_model.id),
            (CCPairRunKind.INDEXING, current.id),
        ]
        attempts = {run.attempt.id: run.attempt for run in feed.items}
        new_snapshot = attempts[new_model.id]
        assert isinstance(new_snapshot, IndexAttemptSnapshot)
        assert new_snapshot.is_new_model
        assert new_snapshot.open_doc_error_count == 1
        current_snapshot = attempts[current.id]
        assert isinstance(current_snapshot, IndexAttemptSnapshot)
        assert not current_snapshot.is_new_model
        assert _order(unresolved) == [(CCPairRunKind.INDEXING, new_model.id)]
    finally:
        db_session.rollback()
        db_session.query(IndexAttemptError).filter(
            IndexAttemptError.connector_credential_pair_id == cc_pair.id
        ).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair_and_future(db_session, cc_pair, future.id)
        db_session.query(SearchSettings).filter(SearchSettings.id == past.id).delete(
            synchronize_session="fetch"
        )
        db_session.commit()


def test_leaves_out_another_pairs_runs(db_session: Session) -> None:
    admin = create_test_user(db_session, "runs_admin", is_admin=True)
    cc_pair = _create_cc_pair(db_session, AccessType.SYNC)
    other = _create_cc_pair(db_session, AccessType.SYNC)
    own = _index_attempt(db_session, cc_pair, 0, IndexingStatus.SUCCESS)
    _index_attempt(db_session, other, 1, IndexingStatus.SUCCESS)
    _doc_sync(db_session, other, 2, PermissionSyncStatus.SUCCESS)

    response = _runs(db_session, admin, cc_pair)

    assert _order(response) == [(CCPairRunKind.INDEXING, own.id)]
    assert response.total_items == 1


def test_source_wide_group_sync_shows_on_every_pair_of_the_source(
    db_session: Session,
) -> None:
    """Jira logs one group sync per source against whichever pair ran it. The
    search token keeps the shared history from other runs of this test out."""
    admin = create_test_user(db_session, "runs_admin", is_admin=True)
    cc_pair = _create_cc_pair(db_session, AccessType.SYNC, DocumentSource.JIRA)
    sibling = _create_cc_pair(db_session, AccessType.SYNC, DocumentSource.JIRA)
    other_source = _create_cc_pair(db_session, AccessType.SYNC)
    token = f"run {uuid4().hex}"
    shared = _group_sync(
        db_session, sibling, 0, PermissionSyncStatus.FAILED, f"{token} sibling"
    )
    _group_sync(
        db_session, other_source, 1, PermissionSyncStatus.FAILED, f"{token} other"
    )

    response = _runs(db_session, admin, cc_pair, q=token)

    assert _order(response) == [(CCPairRunKind.GROUP_SYNC, shared.id)]
    assert response.total_items == 1
    assert response.status_counts[CCPairRunStatusGroup.FAILED] == 1


def test_status_filter_keeps_counts(db_session: Session) -> None:
    admin = create_test_user(db_session, "runs_admin", is_admin=True)
    cc_pair = _create_cc_pair(db_session, AccessType.SYNC)
    _index_attempt(db_session, cc_pair, 0, IndexingStatus.SUCCESS)
    failed_index = _index_attempt(db_session, cc_pair, 1, IndexingStatus.FAILED)
    _index_attempt(db_session, cc_pair, 2, IndexingStatus.COMPLETED_WITH_ERRORS)
    failed_doc = _doc_sync(db_session, cc_pair, 3, PermissionSyncStatus.FAILED)
    _index_attempt(db_session, cc_pair, 4, IndexingStatus.INTERRUPTED)

    everything = _runs(db_session, admin, cc_pair)
    failed = _runs(
        db_session, admin, cc_pair, status_groups=[CCPairRunStatusGroup.FAILED]
    )

    assert failed.total_items == 2
    assert _order(failed) == [
        (CCPairRunKind.DOC_PERMISSION_SYNC, failed_doc.id),
        (CCPairRunKind.INDEXING, failed_index.id),
    ]
    assert failed.status_counts == everything.status_counts
    assert everything.status_counts == {
        CCPairRunStatusGroup.RUNNING: 0,
        CCPairRunStatusGroup.SUCCEEDED: 2,
        CCPairRunStatusGroup.FAILED: 2,
        CCPairRunStatusGroup.CANCELED: 1,
    }


def test_a_newer_run_of_the_kind_supersedes_a_failure(db_session: Session) -> None:
    admin = create_test_user(db_session, "runs_admin", is_admin=True)
    cc_pair = _create_cc_pair(db_session, AccessType.SYNC)
    resolved = _index_attempt(db_session, cc_pair, 0, IndexingStatus.SUCCESS)
    _doc_error(db_session, resolved, is_resolved=True)
    old_index = _index_attempt(db_session, cc_pair, 1, IndexingStatus.FAILED)
    old_doc = _doc_sync(db_session, cc_pair, 2, PermissionSyncStatus.FAILED)
    new_index = _index_attempt(db_session, cc_pair, 3, IndexingStatus.FAILED)
    new_doc = _doc_sync(db_session, cc_pair, 4, PermissionSyncStatus.FAILED)
    failed = [CCPairRunStatusGroup.FAILED]

    # The activity panel's failures and resolved groups.
    live = _runs(db_session, admin, cc_pair, status_groups=failed, superseded=False)
    closed = _runs(
        db_session,
        admin,
        cc_pair,
        errors=CCPairRunErrors.RESOLVED,
        superseded=True,
    )
    superseded_only = _runs(db_session, admin, cc_pair, superseded=True)

    assert _order(live) == [
        (CCPairRunKind.DOC_PERMISSION_SYNC, new_doc.id),
        (CCPairRunKind.INDEXING, new_index.id),
    ]
    assert live.total_items == 2
    assert live.status_counts[CCPairRunStatusGroup.FAILED] == 2
    assert live.status_counts[CCPairRunStatusGroup.SUCCEEDED] == 1
    assert _order(superseded_only) == [
        (CCPairRunKind.DOC_PERMISSION_SYNC, old_doc.id),
        (CCPairRunKind.INDEXING, old_index.id),
    ]
    assert _order(closed) == [
        (CCPairRunKind.DOC_PERMISSION_SYNC, old_doc.id),
        (CCPairRunKind.INDEXING, old_index.id),
        (CCPairRunKind.INDEXING, resolved.id),
    ]
    assert closed.total_items == 3


def test_public_pair_shows_no_syncs(db_session: Session) -> None:
    admin = create_test_user(db_session, "runs_admin", is_admin=True)
    cc_pair = _create_cc_pair(db_session, AccessType.PUBLIC)
    index_attempt = _index_attempt(db_session, cc_pair, 0, IndexingStatus.SUCCESS)
    _doc_sync(db_session, cc_pair, 1, PermissionSyncStatus.SUCCESS)

    response = _runs(db_session, admin, cc_pair)

    assert response.kinds == [
        CCPairRunKind.INDEXING,
        CCPairRunKind.PRUNING,
        CCPairRunKind.CHECKS,
    ]
    assert _order(response) == [(CCPairRunKind.INDEXING, index_attempt.id)]


def test_window_and_error_search(db_session: Session) -> None:
    admin = create_test_user(db_session, "runs_admin", is_admin=True)
    cc_pair = _create_cc_pair(db_session, AccessType.PUBLIC)
    _index_attempt(db_session, cc_pair, 0, IndexingStatus.FAILED, "old 100% timeout")
    recent_timeout = _index_attempt(
        db_session, cc_pair, 10, IndexingStatus.FAILED, "Upstream 100% timeout"
    )
    _index_attempt(db_session, cc_pair, 20, IndexingStatus.FAILED, "auth refused")

    response = _runs(
        db_session, admin, cc_pair, since=_T0 + timedelta(minutes=5), q="100% time"
    )

    assert _order(response) == [(CCPairRunKind.INDEXING, recent_timeout.id)]
    assert response.total_items == 1


def test_cancel_requests_cancellation_of_a_running_attempt(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = create_test_user(db_session, "runs_admin", is_admin=True)
    cc_pair = _create_cc_pair(db_session, AccessType.PUBLIC)
    attempt = _index_attempt(
        db_session, cc_pair, 0, IndexingStatus.IN_PROGRESS, celery_task_id="task-1"
    )
    revoke = MagicMock()
    monkeypatch.setattr(cc_pair_routes.client_app.control, "revoke", revoke)

    cancel_index_attempt(index_attempt_id=attempt.id, user=admin, db_session=db_session)

    db_session.refresh(attempt)
    assert attempt.cancellation_requested is True
    revoke.assert_called_once_with("task-1")


def test_cancel_rejects_a_finished_or_unknown_attempt(db_session: Session) -> None:
    admin = create_test_user(db_session, "runs_admin", is_admin=True)
    cc_pair = _create_cc_pair(db_session, AccessType.PUBLIC)
    finished = _index_attempt(db_session, cc_pair, 0, IndexingStatus.SUCCESS)

    with pytest.raises(OnyxError) as finished_error:
        cancel_index_attempt(
            index_attempt_id=finished.id, user=admin, db_session=db_session
        )
    with pytest.raises(OnyxError) as unknown_error:
        cancel_index_attempt(
            index_attempt_id=finished.id + 10_000, user=admin, db_session=db_session
        )

    assert finished_error.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert unknown_error.value.error_code == OnyxErrorCode.NOT_FOUND


def test_cancel_ends_a_waiting_attempt_in_place(db_session: Session) -> None:
    admin = create_test_user(db_session, "runs_admin", is_admin=True)
    cc_pair = _create_cc_pair(db_session, AccessType.PUBLIC)
    attempt = _index_attempt(
        db_session, cc_pair, 0, IndexingStatus.NOT_STARTED, started=False
    )

    cancel_index_attempt(index_attempt_id=attempt.id, user=admin, db_session=db_session)

    db_session.refresh(attempt)
    assert attempt.status == IndexingStatus.CANCELED
    assert attempt.time_started is None
    # Finished at the cancel, so the run list shows when the admin canceled it.
    assert attempt.time_finished is not None


def test_cancel_requests_cancellation_of_a_queued_attempt_and_revokes_its_task(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = create_test_user(db_session, "runs_admin", is_admin=True)
    cc_pair = _create_cc_pair(db_session, AccessType.PUBLIC)
    attempt = _index_attempt(
        db_session,
        cc_pair,
        0,
        IndexingStatus.NOT_STARTED,
        celery_task_id="task-2",
        started=False,
    )
    revoke = MagicMock()
    monkeypatch.setattr(cc_pair_routes.client_app.control, "revoke", revoke)

    cancel_index_attempt(index_attempt_id=attempt.id, user=admin, db_session=db_session)

    # The task owns the status, as on a pause: it reads the request when it runs.
    db_session.refresh(attempt)
    assert attempt.status == IndexingStatus.NOT_STARTED
    assert attempt.cancellation_requested is True
    revoke.assert_called_once_with("task-2")


def test_cancel_refuses_a_caller_who_cannot_operate_the_pair(
    db_session: Session,
) -> None:
    reader = create_test_user(db_session, "runs_reader")
    cc_pair = _create_cc_pair(db_session, AccessType.PUBLIC)
    attempt = _index_attempt(db_session, cc_pair, 0, IndexingStatus.IN_PROGRESS)

    with pytest.raises(OnyxError) as refused:
        cancel_index_attempt(
            index_attempt_id=attempt.id, user=reader, db_session=db_session
        )

    db_session.refresh(attempt)
    assert refused.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    assert attempt.cancellation_requested is False


def test_throughput_counts_only_this_pairs_runs_in_the_window(
    db_session: Session,
) -> None:
    admin = create_test_user(db_session, "runs_admin", is_admin=True)
    cc_pair = _create_cc_pair(db_session, AccessType.PUBLIC)
    other = _create_cc_pair(db_session, AccessType.PUBLIC)
    now = datetime.now(timezone.utc)
    recent = _index_attempt(db_session, cc_pair, 0, IndexingStatus.SUCCESS)
    # Began before the window and ran 11 of its 12 hours inside it.
    overlapping = _index_attempt(db_session, cc_pair, 0, IndexingStatus.SUCCESS)
    old = _index_attempt(db_session, cc_pair, 0, IndexingStatus.SUCCESS)
    foreign = _index_attempt(db_session, other, 0, IndexingStatus.SUCCESS)
    # Cleanup touched this one days after it ran, as checkpoint cleanup does.
    cleaned = _index_attempt(db_session, cc_pair, 0, IndexingStatus.SUCCESS)
    for attempt, ran_for, ended in [
        (recent, timedelta(hours=1), now - timedelta(hours=2)),
        (overlapping, timedelta(hours=12), now - timedelta(hours=1)),
        (old, timedelta(hours=1), now - timedelta(days=2)),
        (foreign, timedelta(hours=1), now - timedelta(hours=2)),
        (cleaned, timedelta(hours=1), now - timedelta(days=9)),
    ]:
        attempt.time_created = ended - ran_for
        attempt.time_started = ended - ran_for
        attempt.time_finished = ended
        attempt.total_docs_indexed = 100
    # The overlapping run predates time_finished, so its heartbeat stands in.
    overlapping.time_finished = None
    overlapping.last_heartbeat_time = now - timedelta(hours=1)
    cleaned.time_updated = now - timedelta(minutes=5)
    db_session.commit()

    response = get_cc_pair_throughput(
        cc_pair_id=cc_pair.id,
        window=CCPairThroughputWindow.HOURS_12,
        user=admin,
        db_session=db_session,
    )

    assert sum(response.docs_indexed) == 100 + round(100 * 11 / 12)
    # The overlapping run is listed, so the status strip covers its slices.
    assert [(run.started, run.ended) for run in response.runs] == [
        (overlapping.time_started, overlapping.last_heartbeat_time),
        (recent.time_started, recent.time_finished),
    ]
