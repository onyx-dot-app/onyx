"""Coverage for the indexing status page's fleet-wide run feed: runs of every
readable pair merge newest first with each run naming its pair, the status
filter narrows the feed but not the counts, and a scoped reader sees only the
pairs they can read, plus the group sync their source shares even when another
pair logged it. A creator holds operate on their groupless private pair, so they read it
through the operate level, but without MANAGE_CONNECTORS they cannot resolve
its errors."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import (
    AccessType,
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
    ExternalGroupPermissionSyncAttempt,
    IndexAttempt,
    User,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.server.documents.index_monitoring import get_indexing_runs
from onyx.server.documents.models import IndexingRunsResponse
from tests.external_dependency_unit.conftest import create_test_user

# Group sync scoping asks the EE-only sync_params helpers which sources share a history.
pytestmark = pytest.mark.usefixtures("enable_ee")

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _mark() -> str:
    """Earlier runs of these tests leave rows behind, so each test marks its
    runs' errors with its own value and searches the feed by it."""
    return f"monitor-runs-feed-{uuid4().hex}"


def _create_cc_pair(
    db_session: Session,
    name: str,
    access_type: AccessType = AccessType.PUBLIC,
    source: DocumentSource = DocumentSource.GOOGLE_DRIVE,
    creator: User | None = None,
) -> ConnectorCredentialPair:
    owner = creator or create_test_user(db_session, "monitor_runs_owner")
    connector = Connector(
        name="Monitor Runs Connector",
        source=source,
        input_type=(
            InputType.LOAD_STATE if source == DocumentSource.WEB else InputType.POLL
        ),
        connector_specific_config={},
        refresh_freq=None,
        prune_freq=None,
    )
    db_session.add(connector)
    db_session.flush()
    credential = Credential(credential_json={}, user_id=owner.id, admin_public=True)
    db_session.add(credential)
    db_session.flush()
    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=name,
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=access_type,
        creator_id=owner.id,
    )
    db_session.add(cc_pair)
    db_session.commit()
    return cc_pair


def _index_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    minutes: int,
    status: IndexingStatus,
    mark: str,
) -> IndexAttempt:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=status,
        error_msg=mark,
        time_started=_T0 + timedelta(minutes=minutes),
    )
    db_session.add(attempt)
    db_session.flush()
    attempt.time_created = _T0 + timedelta(minutes=minutes)
    db_session.commit()
    return attempt


def _doc_sync(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    minutes: int,
    status: PermissionSyncStatus,
    mark: str,
) -> DocPermissionSyncAttempt:
    attempt = DocPermissionSyncAttempt(
        connector_credential_pair_id=cc_pair.id,
        status=status,
        error_message=mark,
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
    mark: str,
) -> ExternalGroupPermissionSyncAttempt:
    attempt = ExternalGroupPermissionSyncAttempt(
        connector_credential_pair_id=cc_pair.id,
        status=status,
        error_message=mark,
    )
    db_session.add(attempt)
    db_session.flush()
    attempt.time_created = _T0 + timedelta(minutes=minutes)
    db_session.commit()
    return attempt


def _runs(
    db_session: Session,
    user: User,
    mark: str,
    status_groups: list[CCPairRunStatusGroup] | None = None,
) -> IndexingRunsResponse:
    return get_indexing_runs(
        page_num=0,
        page_size=10,
        since=None,
        kinds=None,
        status_groups=status_groups,
        q=mark,
        errors=None,
        user=user,
        db_session=db_session,
    )


def test_runs_of_every_pair_merge_newest_first_and_name_their_pair(
    db_session: Session,
) -> None:
    admin = create_test_user(db_session, "monitor_runs_admin", is_admin=True)
    mark = _mark()
    first = _create_cc_pair(db_session, "Monitor Runs First", AccessType.SYNC)
    second = _create_cc_pair(db_session, "Monitor Runs Second")
    index_0 = _index_attempt(db_session, first, 0, IndexingStatus.SUCCESS, mark)
    sync_1 = _doc_sync(db_session, first, 1, PermissionSyncStatus.FAILED, mark)
    index_2 = _index_attempt(db_session, second, 2, IndexingStatus.FAILED, mark)

    response = _runs(db_session, admin, mark)

    assert [
        (item.cc_pair.id, item.run.kind, item.run.attempt.id) for item in response.items
    ] == [
        (second.id, CCPairRunKind.INDEXING, index_2.id),
        (first.id, CCPairRunKind.DOC_PERMISSION_SYNC, sync_1.id),
        (first.id, CCPairRunKind.INDEXING, index_0.id),
    ]
    assert response.items[0].cc_pair.name == second.name
    assert response.items[0].cc_pair.source == DocumentSource.GOOGLE_DRIVE
    # An admin operates every pair, and Google Drive resolves documents.
    assert response.items[0].cc_pair.can_resolve is True
    assert response.total_items == 3

    failed = _runs(db_session, admin, mark, status_groups=[CCPairRunStatusGroup.FAILED])

    assert [item.run.attempt.id for item in failed.items] == [index_2.id, sync_1.id]
    assert failed.total_items == 2
    assert failed.status_counts == response.status_counts
    assert failed.status_counts[CCPairRunStatusGroup.SUCCEEDED] == 1


def test_a_reader_without_access_to_a_pair_never_sees_its_runs(
    db_session: Session,
) -> None:
    reader = create_test_user(db_session, "monitor_runs_reader")
    mark = _mark()
    public = _create_cc_pair(db_session, "Monitor Runs Public")
    private = _create_cc_pair(db_session, "Monitor Runs Private", AccessType.PRIVATE)
    _index_attempt(db_session, public, 0, IndexingStatus.SUCCESS, mark)
    _index_attempt(db_session, private, 1, IndexingStatus.SUCCESS, mark)

    response = _runs(db_session, reader, mark)

    assert {item.cc_pair.id for item in response.items} == {public.id}
    # A reader does not operate the pair, so nothing is resolvable.
    assert response.items[0].cc_pair.can_resolve is False


def test_a_shared_group_sync_logged_on_an_unreadable_pair_names_a_readable_one(
    db_session: Session,
) -> None:
    reader = create_test_user(db_session, "monitor_runs_reader")
    mark = _mark()
    # Confluence runs one group sync for all its pairs and logs it on one of them.
    readable = _create_cc_pair(
        db_session, "Monitor Runs Confluence Public", source=DocumentSource.CONFLUENCE
    )
    recorder = _create_cc_pair(
        db_session,
        "Monitor Runs Confluence Private",
        AccessType.PRIVATE,
        source=DocumentSource.CONFLUENCE,
    )
    sync = _group_sync(db_session, recorder, 0, PermissionSyncStatus.FAILED, mark)
    _index_attempt(db_session, recorder, 1, IndexingStatus.FAILED, mark)

    response = _runs(db_session, reader, mark)

    assert [(item.run.kind, item.run.attempt.id) for item in response.items] == [
        (CCPairRunKind.GROUP_SYNC, sync.id)
    ]
    # Earlier runs leave Confluence pairs behind, so any readable one may be named.
    named = response.items[0].cc_pair
    assert named.source == DocumentSource.CONFLUENCE
    assert named.id != recorder.id
    assert named.id <= readable.id


def test_a_creator_reads_their_private_pair_but_cannot_resolve_it(
    db_session: Session,
) -> None:
    creator = create_test_user(db_session, "monitor_runs_creator")
    mark = _mark()
    drive = _create_cc_pair(
        db_session, "Monitor Runs Own Drive", AccessType.PRIVATE, creator=creator
    )
    # The web connector does not resolve single documents.
    web = _create_cc_pair(
        db_session,
        "Monitor Runs Own Web",
        AccessType.PRIVATE,
        source=DocumentSource.WEB,
        creator=creator,
    )
    _index_attempt(db_session, drive, 0, IndexingStatus.SUCCESS, mark)
    _index_attempt(db_session, web, 1, IndexingStatus.SUCCESS, mark)

    response = _runs(db_session, creator, mark)

    pairs = {item.cc_pair.id: item.cc_pair for item in response.items}
    assert set(pairs) == {drive.id, web.id}
    # The targeted reindex route needs MANAGE_CONNECTORS, which a creator lacks.
    assert pairs[drive.id].can_resolve is False
    assert pairs[web.id].can_resolve is False
