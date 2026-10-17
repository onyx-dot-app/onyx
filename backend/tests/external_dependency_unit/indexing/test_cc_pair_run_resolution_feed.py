"""Coverage for run resolution: a resolved failed index attempt and a resolved
failed permission sync leave the failures feed and show under resolved with
their status kept, a resolved run with open document errors moves the same way
within the errors level, and only a caller who operates the pair resolves. A
fleet batch resolve marks only the matching runs of the pairs the caller operates."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

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
)
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    DocPermissionSyncAttempt,
    IndexAttempt,
    IndexAttemptError,
    User,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.cc_pair import get_cc_pair_runs, resolve_cc_pair_runs
from onyx.server.documents.index_monitoring import (
    get_indexing_runs,
    get_resolvable_indexing_runs_count,
    resolve_indexing_runs,
)
from onyx.server.documents.models import (
    CCPairIndexRun,
    CCPairRunKey,
    CCPairRunLevel,
    CCPairRunsResolveMatchingRequest,
    CCPairRunsResolveRequest,
    CCPairRunsResponse,
)
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair

# The perm sync kinds come from the EE-only sync_params helpers.
pytestmark = pytest.mark.usefixtures("enable_ee")

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_FAILED = [CCPairRunStatusGroup.FAILED]


@pytest.fixture
def admin(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "resolution_admin", is_admin=True)
    yield user
    db_session.rollback()
    delete_test_user(db_session, user)
    db_session.commit()


@pytest.fixture
def cc_pair(db_session: Session) -> Generator[ConnectorCredentialPair, None, None]:
    owner = create_test_user(db_session, "resolution_owner")
    connector = Connector(
        name="Resolution Test Connector",
        source=DocumentSource.GOOGLE_DRIVE,
        input_type=InputType.POLL,
        connector_specific_config={},
        refresh_freq=None,
    )
    db_session.add(connector)
    db_session.flush()
    credential = Credential(credential_json={}, user_id=owner.id, admin_public=True)
    db_session.add(credential)
    db_session.flush()
    pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name="Resolution Test Pair",
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
    db_session.commit()
    cleanup_cc_pair(db_session, pair)
    delete_test_user(db_session, owner)
    db_session.commit()


def _index_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    minutes: int,
    status: IndexingStatus,
    error_msg: str | None = None,
) -> IndexAttempt:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=status,
        time_started=_T0 + timedelta(minutes=minutes),
        error_msg=error_msg,
    )
    db_session.add(attempt)
    db_session.flush()
    attempt.time_created = _T0 + timedelta(minutes=minutes)
    db_session.commit()
    return attempt


def _doc_sync(
    db_session: Session, cc_pair: ConnectorCredentialPair, minutes: int
) -> DocPermissionSyncAttempt:
    attempt = DocPermissionSyncAttempt(
        connector_credential_pair_id=cc_pair.id, status=PermissionSyncStatus.FAILED
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
    status_groups: list[CCPairRunStatusGroup] | None,
    errors: CCPairRunErrors | None,
    resolved: bool,
) -> CCPairRunsResponse:
    return get_cc_pair_runs(
        cc_pair_id=cc_pair.id,
        page_num=0,
        page_size=10,
        since=None,
        until=None,
        kinds=None,
        status_groups=status_groups,
        q=None,
        errors=errors,
        superseded=False,
        resolved=resolved,
        user=user,
        db_session=db_session,
    )


def _keys(response: CCPairRunsResponse) -> list[tuple[CCPairRunKind, int]]:
    return [(run.kind, run.attempt.id) for run in response.items]


def _resolve(
    db_session: Session,
    user: User,
    cc_pair: ConnectorCredentialPair,
    runs: list[tuple[CCPairRunKind, int]],
) -> None:
    resolve_cc_pair_runs(
        cc_pair_id=cc_pair.id,
        request=CCPairRunsResolveRequest(
            runs=[CCPairRunKey(kind=kind, attempt_id=run_id) for kind, run_id in runs]
        ),
        user=user,
        db_session=db_session,
    )


def test_resolved_failures_leave_the_failures_feed_and_keep_their_status(
    db_session: Session, admin: User, cc_pair: ConnectorCredentialPair
) -> None:
    index = _index_attempt(db_session, cc_pair, 0, IndexingStatus.FAILED)
    doc_sync = _doc_sync(db_session, cc_pair, 1)
    both = [
        (CCPairRunKind.DOC_PERMISSION_SYNC, doc_sync.id),
        (CCPairRunKind.INDEXING, index.id),
    ]
    assert _keys(_runs(db_session, admin, cc_pair, _FAILED, None, False)) == both

    _resolve(db_session, admin, cc_pair, both)

    live = _runs(db_session, admin, cc_pair, _FAILED, None, False)
    closed = _runs(db_session, admin, cc_pair, _FAILED, None, True)
    assert live.items == []
    assert _keys(closed) == both
    assert all(run.resolved_at is not None for run in closed.items)
    assert closed.status_counts[CCPairRunStatusGroup.FAILED] == 2
    # Resolving twice keeps the first resolution.
    _resolve(db_session, admin, cc_pair, both)
    again = _runs(db_session, admin, cc_pair, _FAILED, None, True)
    assert [run.resolved_at for run in again.items] == [
        run.resolved_at for run in closed.items
    ]


def test_a_resolved_run_with_open_doc_errors_stays_in_the_errors_level(
    db_session: Session, admin: User, cc_pair: ConnectorCredentialPair
) -> None:
    attempt = _index_attempt(db_session, cc_pair, 0, IndexingStatus.SUCCESS)
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
    key = (CCPairRunKind.INDEXING, attempt.id)
    unresolved = CCPairRunErrors.UNRESOLVED

    _resolve(db_session, admin, cc_pair, [key])

    assert _runs(db_session, admin, cc_pair, None, unresolved, False).items == []
    closed = _runs(db_session, admin, cc_pair, None, unresolved, True)
    assert _keys(closed) == [key]
    run = closed.items[0]
    assert isinstance(run, CCPairIndexRun)
    assert run.attempt.open_doc_error_count == 1


def test_resolve_refuses_a_run_with_nothing_open(
    db_session: Session, admin: User, cc_pair: ConnectorCredentialPair
) -> None:
    attempt = _index_attempt(db_session, cc_pair, 0, IndexingStatus.SUCCESS)

    with pytest.raises(OnyxError) as refused:
        _resolve(db_session, admin, cc_pair, [(CCPairRunKind.INDEXING, attempt.id)])

    assert refused.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_resolve_refuses_a_run_still_going(
    db_session: Session, admin: User, cc_pair: ConnectorCredentialPair
) -> None:
    attempt = _index_attempt(db_session, cc_pair, 0, IndexingStatus.IN_PROGRESS)
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

    # More failures can still land on it, so nothing is settled enough to resolve.
    with pytest.raises(OnyxError) as refused:
        _resolve(db_session, admin, cc_pair, [(CCPairRunKind.INDEXING, attempt.id)])

    assert refused.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_resolve_refuses_a_caller_who_cannot_operate_the_pair(
    db_session: Session, admin: User, cc_pair: ConnectorCredentialPair
) -> None:
    reader = create_test_user(db_session, "resolution_reader")
    attempt = _index_attempt(db_session, cc_pair, 0, IndexingStatus.FAILED)
    key = (CCPairRunKind.INDEXING, attempt.id)

    with pytest.raises(OnyxError) as refused:
        _resolve(db_session, reader, cc_pair, [key])

    assert refused.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    live = _runs(db_session, admin, cc_pair, _FAILED, None, False)
    assert _keys(live) == [key]
    delete_test_user(db_session, reader)
    db_session.commit()


def _fleet_pair(
    db_session: Session, name: str, access_type: AccessType, creator: User
) -> ConnectorCredentialPair:
    connector = Connector(
        name="Resolution Fleet Connector",
        source=DocumentSource.GOOGLE_DRIVE,
        input_type=InputType.POLL,
        connector_specific_config={},
        refresh_freq=None,
    )
    db_session.add(connector)
    db_session.flush()
    credential = Credential(credential_json={}, user_id=creator.id, admin_public=True)
    db_session.add(credential)
    db_session.flush()
    pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=name,
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=access_type,
        creator_id=creator.id,
    )
    db_session.add(pair)
    db_session.commit()
    return pair


@pytest.fixture
def fleet_pairs(
    db_session: Session,
) -> Generator[
    tuple[User, ConnectorCredentialPair, ConnectorCredentialPair], None, None
]:
    """A scoped user who operates their own private pair and only reads a public one."""
    scoped = create_test_user(db_session, "resolution_scoped")
    owner = create_test_user(db_session, "resolution_fleet_owner")
    operated = _fleet_pair(
        db_session, "Resolution Operated Pair", AccessType.PRIVATE, scoped
    )
    read_only = _fleet_pair(
        db_session, "Resolution Read Only Pair", AccessType.PUBLIC, owner
    )
    yield scoped, operated, read_only
    db_session.rollback()
    for pair in (operated, read_only):
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == pair.id
        ).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, pair)
    delete_test_user(db_session, scoped)
    delete_test_user(db_session, owner)
    db_session.commit()


def test_fleet_batch_resolve_marks_only_the_operated_pairs_matching_runs(
    db_session: Session,
    admin: User,
    fleet_pairs: tuple[User, ConnectorCredentialPair, ConnectorCredentialPair],
) -> None:
    scoped, operated, read_only = fleet_pairs
    # Earlier runs leave rows behind, so the runs carry a mark the batch searches by.
    mark = f"resolution-batch-{uuid4().hex}"
    first = _index_attempt(db_session, operated, 0, IndexingStatus.FAILED, mark)
    second = _index_attempt(db_session, operated, 1, IndexingStatus.FAILED, mark)
    other = _index_attempt(db_session, read_only, 2, IndexingStatus.FAILED, mark)

    def resolvable() -> int:
        return get_resolvable_indexing_runs_count(
            level=CCPairRunLevel.FAILURES,
            q=mark,
            since=None,
            until=None,
            kinds=None,
            user=scoped,
            db_session=db_session,
        ).count

    assert resolvable() == 2

    response = resolve_indexing_runs(
        request=CCPairRunsResolveMatchingRequest(level=CCPairRunLevel.FAILURES, q=mark),
        user=scoped,
        db_session=db_session,
    )

    assert response.resolved_count == 2
    assert response.cc_pair_ids == [operated.id]
    assert resolvable() == 0

    def fleet(resolved: bool) -> list[int]:
        feed = get_indexing_runs(
            page_num=0,
            page_size=10,
            since=None,
            until=None,
            kinds=None,
            status_groups=_FAILED,
            q=mark,
            errors=None,
            superseded=None,
            resolved=resolved,
            user=admin,
            db_session=db_session,
        )
        return [item.run.attempt.id for item in feed.items]

    assert fleet(False) == [other.id]
    assert fleet(True) == [second.id, first.id]
