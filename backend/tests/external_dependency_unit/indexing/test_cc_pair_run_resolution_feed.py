"""Coverage for run resolution: a resolved failed index attempt and a resolved
failed permission sync leave the failures feed and show under resolved with
their status kept, a resolved run with open document errors moves the same way
within the errors level, and only a caller who operates the pair resolves."""

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
from onyx.server.documents.models import (
    CCPairIndexRun,
    CCPairRunKey,
    CCPairRunsResolveRequest,
    CCPairRunsResponse,
)
from tests.external_dependency_unit.conftest import create_test_user

# The perm sync kinds come from the EE-only sync_params helpers.
pytestmark = pytest.mark.usefixtures("enable_ee")

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_FAILED = [CCPairRunStatusGroup.FAILED]


def _create_cc_pair(db_session: Session) -> ConnectorCredentialPair:
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
    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name="Resolution Test Pair",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.SYNC,
    )
    db_session.add(cc_pair)
    db_session.commit()
    return cc_pair


def _index_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    minutes: int,
    status: IndexingStatus,
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
    db_session: Session,
) -> None:
    admin = create_test_user(db_session, "resolution_admin", is_admin=True)
    cc_pair = _create_cc_pair(db_session)
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
    db_session: Session,
) -> None:
    admin = create_test_user(db_session, "resolution_admin", is_admin=True)
    cc_pair = _create_cc_pair(db_session)
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


def test_resolve_refuses_a_run_with_nothing_open(db_session: Session) -> None:
    admin = create_test_user(db_session, "resolution_admin", is_admin=True)
    cc_pair = _create_cc_pair(db_session)
    attempt = _index_attempt(db_session, cc_pair, 0, IndexingStatus.SUCCESS)

    with pytest.raises(OnyxError) as refused:
        _resolve(db_session, admin, cc_pair, [(CCPairRunKind.INDEXING, attempt.id)])

    assert refused.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_resolve_refuses_a_caller_who_cannot_operate_the_pair(
    db_session: Session,
) -> None:
    admin = create_test_user(db_session, "resolution_admin", is_admin=True)
    reader = create_test_user(db_session, "resolution_reader")
    cc_pair = _create_cc_pair(db_session)
    attempt = _index_attempt(db_session, cc_pair, 0, IndexingStatus.FAILED)
    key = (CCPairRunKind.INDEXING, attempt.id)

    with pytest.raises(OnyxError) as refused:
        _resolve(db_session, reader, cc_pair, [key])

    assert refused.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    live = _runs(db_session, admin, cc_pair, _FAILED, None, False)
    assert _keys(live) == [key]
