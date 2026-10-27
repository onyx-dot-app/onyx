"""Coverage for superseding: a later succeeded or failed full-pass run closes an
earlier run of its kind with errors, stopped ones included, while an index
attempt's open document errors stay open. Each run says whether it is superseded."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import (
    AccessType,
    CCPairRunErrors,
    CCPairRunKind,
    CCPairRunStatusGroup,
    ConnectorCredentialPairStatus,
    IndexingStatus,
    PermissionSyncStatus,
    SyncStatus,
    SyncType,
)
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    DocPermissionSyncAttempt,
    IndexAttempt,
    IndexAttemptError,
    SyncRecord,
    User,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.server.documents.cc_pair import (
    get_cc_pair_runs,
    get_resolvable_cc_pair_runs_count,
)
from onyx.server.documents.models import CCPairRunLevel, CCPairRunsResponse
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair

# The perm sync kinds come from the EE-only sync_params helpers.
pytestmark = pytest.mark.usefixtures("enable_ee")

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_NOT_FAILED = [
    CCPairRunStatusGroup.RUNNING,
    CCPairRunStatusGroup.SUCCEEDED,
    CCPairRunStatusGroup.CANCELED,
]
_FAILED = [CCPairRunStatusGroup.FAILED]


@pytest.fixture
def admin(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "supersede_admin", is_admin=True)
    yield user
    db_session.rollback()
    delete_test_user(db_session, user)
    db_session.commit()


@pytest.fixture
def cc_pair(db_session: Session) -> Generator[ConnectorCredentialPair, None, None]:
    owner = create_test_user(db_session, "supersede_owner")
    connector = Connector(
        name="Supersede Test Connector",
        source=DocumentSource.GOOGLE_DRIVE,
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
    pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name="Supersede Test Pair",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.SYNC,
    )
    db_session.add(pair)
    db_session.commit()
    yield pair
    db_session.rollback()
    # IndexAttemptError has no FK cascade, so its rows go first.
    for model in (IndexAttemptError, IndexAttempt, DocPermissionSyncAttempt):
        db_session.query(model).filter(
            model.connector_credential_pair_id == pair.id
        ).delete(synchronize_session="fetch")
    db_session.query(SyncRecord).filter(SyncRecord.entity_id == pair.id).delete(
        synchronize_session="fetch"
    )
    db_session.commit()
    cleanup_cc_pair(db_session, pair)
    delete_test_user(db_session, owner)
    db_session.commit()


def _doc_sync(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    minutes: int,
    status: PermissionSyncStatus,
    unreadable: int = 0,
) -> DocPermissionSyncAttempt:
    attempt = DocPermissionSyncAttempt(
        connector_credential_pair_id=cc_pair.id,
        status=status,
        docs_with_permission_errors=unreadable,
    )
    db_session.add(attempt)
    db_session.flush()
    attempt.time_created = _T0 + timedelta(minutes=minutes)
    db_session.commit()
    return attempt


def _prune(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    minutes: int,
    docs_failed: int,
) -> SyncRecord:
    record = SyncRecord(
        entity_id=cc_pair.id,
        sync_type=SyncType.PRUNING,
        sync_status=SyncStatus.SUCCESS,
        num_docs_synced=1,
        num_docs_failed=docs_failed,
        sync_start_time=_T0 + timedelta(minutes=minutes),
        sync_end_time=_T0 + timedelta(minutes=minutes + 1),
    )
    db_session.add(record)
    db_session.commit()
    return record


def _index_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    minutes: int,
    status: IndexingStatus,
    open_doc_error: bool = False,
) -> IndexAttempt:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=status,
        time_started=_T0 + timedelta(minutes=minutes),
    )
    db_session.add(attempt)
    db_session.flush()
    attempt.time_created = _T0 + timedelta(minutes=minutes)
    if open_doc_error:
        db_session.add(
            IndexAttemptError(
                index_attempt_id=attempt.id,
                connector_credential_pair_id=cc_pair.id,
                document_id=f"doc-{attempt.id}",
                failure_message="boom",
                is_resolved=False,
            )
        )
    db_session.commit()
    return attempt


def _runs(
    db_session: Session,
    user: User,
    cc_pair: ConnectorCredentialPair,
    status_groups: list[CCPairRunStatusGroup] | None = None,
    errors: CCPairRunErrors | None = None,
    superseded: bool | None = None,
    resolved: bool | None = None,
) -> CCPairRunsResponse:
    return get_cc_pair_runs(
        cc_pair_id=cc_pair.id,
        page_num=0,
        page_size=20,
        since=None,
        until=None,
        kinds=None,
        status_groups=status_groups,
        q=None,
        errors=errors,
        superseded=superseded,
        resolved=resolved,
        user=user,
        db_session=db_session,
    )


def _open_errors(
    db_session: Session, user: User, cc_pair: ConnectorCredentialPair
) -> CCPairRunsResponse:
    """The activity panel's open errors level."""
    return _runs(
        db_session, user, cc_pair, _NOT_FAILED, CCPairRunErrors.UNRESOLVED, False, False
    )


def _closed_errors(
    db_session: Session, user: User, cc_pair: ConnectorCredentialPair
) -> CCPairRunsResponse:
    """The activity panel's closed errors level."""
    return _runs(
        db_session, user, cc_pair, _NOT_FAILED, CCPairRunErrors.RESOLVED, True, True
    )


def _keys(response: CCPairRunsResponse) -> list[tuple[CCPairRunKind, int]]:
    return [(run.kind, run.attempt.id) for run in response.items]


def _superseded_keys(
    response: CCPairRunsResponse,
) -> set[tuple[CCPairRunKind, int]]:
    return {(run.kind, run.attempt.id) for run in response.items if run.superseded}


def test_a_later_sync_supersedes_a_sync_completed_with_errors(
    db_session: Session, admin: User, cc_pair: ConnectorCredentialPair
) -> None:
    with_errors = _doc_sync(
        db_session, cc_pair, 0, PermissionSyncStatus.COMPLETED_WITH_ERRORS, 3
    )
    clean = _doc_sync(db_session, cc_pair, 1, PermissionSyncStatus.SUCCESS)
    key = (CCPairRunKind.DOC_PERMISSION_SYNC, with_errors.id)

    assert _keys(_open_errors(db_session, admin, cc_pair)) == []
    closed = _closed_errors(db_session, admin, cc_pair)
    assert _keys(closed) == [key]
    assert closed.items[0].superseded is True
    assert closed.items[0].resolved_at is None
    everything = _runs(db_session, admin, cc_pair)
    assert _superseded_keys(everything) == {key}
    assert (CCPairRunKind.DOC_PERMISSION_SYNC, clean.id) in _keys(everything)


def test_the_latest_sync_with_errors_stays_open(
    db_session: Session, admin: User, cc_pair: ConnectorCredentialPair
) -> None:
    older = _doc_sync(
        db_session, cc_pair, 0, PermissionSyncStatus.COMPLETED_WITH_ERRORS, 3
    )
    latest = _doc_sync(
        db_session, cc_pair, 1, PermissionSyncStatus.COMPLETED_WITH_ERRORS, 2
    )

    assert _keys(_open_errors(db_session, admin, cc_pair)) == [
        (CCPairRunKind.DOC_PERMISSION_SYNC, latest.id)
    ]
    assert _keys(_closed_errors(db_session, admin, cc_pair)) == [
        (CCPairRunKind.DOC_PERMISSION_SYNC, older.id)
    ]
    # Resolve all shown on the open errors level marks only the open run.
    count = get_resolvable_cc_pair_runs_count(
        cc_pair_id=cc_pair.id,
        level=CCPairRunLevel.ERRORS,
        q=None,
        since=None,
        until=None,
        kinds=None,
        user=admin,
        db_session=db_session,
    )
    assert count.count == 1


def test_a_canceled_sync_supersedes_nothing(
    db_session: Session, admin: User, cc_pair: ConnectorCredentialPair
) -> None:
    failed = _doc_sync(db_session, cc_pair, 0, PermissionSyncStatus.FAILED)
    _doc_sync(db_session, cc_pair, 1, PermissionSyncStatus.CANCELED)

    live = _runs(db_session, admin, cc_pair, _FAILED, None, False, False)

    assert _keys(live) == [(CCPairRunKind.DOC_PERMISSION_SYNC, failed.id)]
    assert live.items[0].superseded is False


def test_a_later_sync_supersedes_a_stopped_sync_with_errors(
    db_session: Session, admin: User, cc_pair: ConnectorCredentialPair
) -> None:
    clean = _doc_sync(db_session, cc_pair, 0, PermissionSyncStatus.SUCCESS)
    stopped = _doc_sync(db_session, cc_pair, 1, PermissionSyncStatus.CANCELED, 4)
    stopped_key = (CCPairRunKind.DOC_PERMISSION_SYNC, stopped.id)

    # A clean sync before the stopped one leaves it open.
    assert _keys(_open_errors(db_session, admin, cc_pair)) == [stopped_key]

    _doc_sync(db_session, cc_pair, 2, PermissionSyncStatus.SUCCESS)

    assert _keys(_open_errors(db_session, admin, cc_pair)) == []
    assert _keys(_closed_errors(db_session, admin, cc_pair)) == [stopped_key]
    assert (CCPairRunKind.DOC_PERMISSION_SYNC, clean.id) not in _superseded_keys(
        _runs(db_session, admin, cc_pair)
    )


def test_a_later_prune_supersedes_a_prune_with_failed_docs(
    db_session: Session, admin: User, cc_pair: ConnectorCredentialPair
) -> None:
    with_failures = _prune(db_session, cc_pair, 0, docs_failed=2)
    _prune(db_session, cc_pair, 2, docs_failed=0)
    key = (CCPairRunKind.PRUNING, with_failures.id)

    assert _keys(_open_errors(db_session, admin, cc_pair)) == []
    closed = _closed_errors(db_session, admin, cc_pair)
    assert _keys(closed) == [key]
    assert closed.items[0].superseded is True


def test_an_index_attempt_with_open_doc_errors_stays_open(
    db_session: Session, admin: User, cc_pair: ConnectorCredentialPair
) -> None:
    with_errors = _index_attempt(
        db_session,
        cc_pair,
        0,
        IndexingStatus.COMPLETED_WITH_ERRORS,
        open_doc_error=True,
    )
    _index_attempt(db_session, cc_pair, 1, IndexingStatus.SUCCESS)

    open_errors = _open_errors(db_session, admin, cc_pair)

    assert _keys(open_errors) == [(CCPairRunKind.INDEXING, with_errors.id)]
    assert open_errors.items[0].superseded is False
    assert _keys(_closed_errors(db_session, admin, cc_pair)) == []


def test_a_failed_index_attempt_is_flagged_superseded(
    db_session: Session, admin: User, cc_pair: ConnectorCredentialPair
) -> None:
    failed = _index_attempt(db_session, cc_pair, 0, IndexingStatus.FAILED)
    latest = _index_attempt(db_session, cc_pair, 1, IndexingStatus.FAILED)

    closed = _runs(db_session, admin, cc_pair, _FAILED, None, True, True)

    assert _keys(closed) == [(CCPairRunKind.INDEXING, failed.id)]
    assert closed.items[0].superseded is True
    assert _superseded_keys(_runs(db_session, admin, cc_pair)) == {
        (CCPairRunKind.INDEXING, failed.id)
    }
    assert latest.id not in {run.attempt.id for run in closed.items}
