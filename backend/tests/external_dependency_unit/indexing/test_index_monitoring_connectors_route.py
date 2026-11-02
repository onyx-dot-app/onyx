"""Coverage for the indexing status page's connector list: buckets, rank sort,
search, filter and queue place, per-source counts across pages, the row's shared
groups, and the row's open error count, whole entities included."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.cc_pair_run_resolution import resolve_runs__no_commit
from onyx.db.enums import (
    AccessType,
    CapabilityCheckRunStatus,
    CapabilityCheckTrigger,
    CCPairRunKind,
    ConnectorCredentialPairStatus,
    ConnectorManageRole,
    IndexingStatus,
    PermissionSyncStatus,
    SyncStatus,
    SyncType,
)
from onyx.db.models import (
    CapabilityCheckRun,
    Connector,
    ConnectorCredentialPair,
    Credential,
    DocPermissionSyncAttempt,
    ExternalGroupPermissionSyncAttempt,
    IndexAttempt,
    IndexAttemptError,
    SyncRecord,
    User,
    User__UserGroup,
    UserGroup,
    UserGroup__CCPairDataAccess,
    UserGroup__ConnectorCredentialPair,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.server.documents.index_monitoring import get_indexing_connectors
from onyx.server.documents.models import (
    IndexingConnectorRow,
    IndexingConnectorsResponse,
    IndexingConnectorStatus,
)
from tests.external_dependency_unit.conftest import create_test_user


def _prefix() -> str:
    """Earlier runs of these tests leave pairs behind, so each test names its
    pairs with its own prefix and searches the route by it."""
    return f"Monitor List {uuid4().hex[:8]}"


def _create_cc_pair(
    db_session: Session,
    prefix: str,
    name: str,
    status: ConnectorCredentialPairStatus = ConnectorCredentialPairStatus.ACTIVE,
    in_repeated_error_state: bool = False,
    source: DocumentSource = DocumentSource.GOOGLE_DRIVE,
    access_type: AccessType = AccessType.PUBLIC,
) -> ConnectorCredentialPair:
    owner = create_test_user(db_session, "monitor_list_owner")
    owner.personal_name = "Monitor List Owner"
    connector = Connector(
        name=f"{prefix} Connector",
        source=source,
        input_type=InputType.POLL,
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
        name=f"{prefix} {name}",
        status=status,
        access_type=access_type,
        in_repeated_error_state=in_repeated_error_state,
        creator_id=owner.id,
    )
    db_session.add(cc_pair)
    db_session.commit()
    return cc_pair


def _index_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    status: IndexingStatus,
    created: datetime,
    dispatched: bool = True,
    is_backfill: bool = False,
) -> IndexAttempt:
    queued = status == IndexingStatus.NOT_STARTED
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        is_backfill=is_backfill,
        status=status,
        time_started=(None if queued else created),
        # A queued attempt joins the line only once its task is sent.
        celery_task_id=(f"task-{uuid4().hex}" if queued and dispatched else None),
    )
    db_session.add(attempt)
    db_session.flush()
    attempt.time_created = created
    db_session.commit()
    return attempt


def _open_error(
    db_session: Session, cc_pair: ConnectorCredentialPair, attempt: IndexAttempt
) -> None:
    db_session.add(
        IndexAttemptError(
            index_attempt_id=attempt.id,
            connector_credential_pair_id=cc_pair.id,
            document_id=f"doc-{uuid4().hex[:8]}",
            failure_message="document unreadable",
            is_resolved=False,
        )
    )
    db_session.commit()


def _doc_permission_sync(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    status: PermissionSyncStatus = PermissionSyncStatus.IN_PROGRESS,
) -> None:
    db_session.add(
        DocPermissionSyncAttempt(
            connector_credential_pair_id=cc_pair.id,
            status=status,
            time_started=datetime.now(timezone.utc),
        )
    )
    db_session.commit()


def _group_sync(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    status: PermissionSyncStatus = PermissionSyncStatus.IN_PROGRESS,
) -> None:
    db_session.add(
        ExternalGroupPermissionSyncAttempt(
            connector_credential_pair_id=cc_pair.id,
            status=status,
            time_started=datetime.now(timezone.utc),
        )
    )
    db_session.commit()


def _share_with_groups(
    db_session: Session, cc_pair: ConnectorCredentialPair, names: list[str]
) -> None:
    """Shares the pair with new groups the way pair creation does for a private
    pair: each group both manages the pair and reads its documents."""
    for name in names:
        group = UserGroup(name=name)
        db_session.add(group)
        db_session.flush()
        db_session.add(
            UserGroup__ConnectorCredentialPair(
                user_group_id=group.id,
                cc_pair_id=cc_pair.id,
                role=ConnectorManageRole.OPERATOR,
            )
        )
        db_session.add(
            UserGroup__CCPairDataAccess(user_group_id=group.id, cc_pair_id=cc_pair.id)
        )
    db_session.commit()


def _prune(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    status: SyncStatus,
    started: datetime,
) -> None:
    db_session.add(
        SyncRecord(
            entity_id=cc_pair.id,
            sync_type=SyncType.PRUNING,
            sync_status=status,
            num_docs_synced=0,
            sync_start_time=started,
            sync_end_time=started + timedelta(minutes=1),
        )
    )
    db_session.commit()


def _failed_check(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> CapabilityCheckRun:
    run = CapabilityCheckRun(
        credential_id=cc_pair.credential_id,
        connector_id=cc_pair.connector_id,
        run_id=uuid4(),
        trigger=CapabilityCheckTrigger.SCHEDULED,
        status=CapabilityCheckRunStatus.FAILED_TO_RUN,
    )
    db_session.add(run)
    db_session.commit()
    return run


def _connectors(
    db_session: Session,
    q: str,
    status: IndexingConnectorStatus | None = None,
    page_num: int = 0,
    page_size: int = 20,
) -> IndexingConnectorsResponse:
    admin = create_test_user(db_session, "monitor_list_admin", is_admin=True)
    return get_indexing_connectors(
        page_num=page_num,
        page_size=page_size,
        q=q,
        status=status,
        user=admin,
        db_session=db_session,
    )


def test_ac2_pairs_sort_by_rank_then_name_and_open_errors_take_rank_three(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    prefix = _prefix()
    # Indexing and Syncing share rank 1, so the name orders them.
    indexing = _create_cc_pair(db_session, prefix, "b indexing")
    syncing = _create_cc_pair(db_session, prefix, "a syncing")
    failed = _create_cc_pair(db_session, prefix, "failed", in_repeated_error_state=True)
    # Open errors outrank the name: "y" sorts after every other name.
    errors = _create_cc_pair(db_session, prefix, "y errors")
    deleting = _create_cc_pair(
        db_session, prefix, "deleting", ConnectorCredentialPairStatus.DELETING
    )
    scheduled = _create_cc_pair(db_session, prefix, "scheduled")
    indexed_b = _create_cc_pair(db_session, prefix, "b indexed")
    # Case-insensitive: "C" sorts after "b". The source plays no part.
    indexed_c = _create_cc_pair(db_session, prefix, "C indexed")
    indexed_z = _create_cc_pair(
        db_session, prefix, "z indexed", source=DocumentSource.CONFLUENCE
    )
    paused = _create_cc_pair(
        db_session, prefix, "paused", ConnectorCredentialPairStatus.PAUSED
    )
    running = _index_attempt(db_session, indexing, IndexingStatus.IN_PROGRESS, now)
    # A running pair with open errors keeps rank 1.
    _open_error(db_session, indexing, running)
    _index_attempt(db_session, syncing, IndexingStatus.SUCCESS, now)
    _doc_permission_sync(db_session, syncing)
    failed_attempt = _index_attempt(db_session, failed, IndexingStatus.SUCCESS, now)
    # A failed pair with open errors keeps rank 2.
    _open_error(db_session, failed, failed_attempt)
    errored = _index_attempt(
        db_session, errors, IndexingStatus.COMPLETED_WITH_ERRORS, now
    )
    _open_error(db_session, errors, errored)
    for cc_pair in (indexed_b, indexed_c, indexed_z, paused):
        _index_attempt(db_session, cc_pair, IndexingStatus.SUCCESS, now)

    response = _connectors(db_session, prefix)

    expected = [
        syncing.name,
        indexing.name,
        failed.name,
        errors.name,
        deleting.name,
        scheduled.name,
        indexed_b.name,
        indexed_c.name,
        indexed_z.name,
        paused.name,
    ]
    assert [row.name for row in response.items] == expected
    by_name = {row.name: row for row in response.items}
    # Open errors are a count, not a state.
    assert by_name[errors.name].status == IndexingConnectorStatus.INDEXED
    assert by_name[errors.name].open_error_count == 1
    assert by_name[syncing.name].status == IndexingConnectorStatus.SYNCING
    assert response.total_items == len(expected)
    assert response.status_counts == {
        IndexingConnectorStatus.INDEXING: 1,
        IndexingConnectorStatus.SYNCING: 1,
        IndexingConnectorStatus.FAILED: 1,
        IndexingConnectorStatus.DELETING: 1,
        IndexingConnectorStatus.SCHEDULED: 1,
        IndexingConnectorStatus.INDEXED: 4,
        IndexingConnectorStatus.PAUSED: 1,
    }
    assert by_name[indexed_b.name].creator_name == "Monitor List Owner"
    assert by_name[indexed_b.name].permissions["operate"] is True

    # The open-errors rank holds across page boundaries, not only within a page.
    paged = [
        row.name
        for page_num in range(4)
        for row in _connectors(db_session, prefix, page_num=page_num, page_size=3).items
    ]
    assert paged == expected

    filtered = _connectors(db_session, prefix, status=IndexingConnectorStatus.INDEXED)

    assert [row.name for row in filtered.items] == [
        errors.name,
        indexed_b.name,
        indexed_c.name,
        indexed_z.name,
    ]
    assert filtered.total_items == 4
    assert filtered.status_counts == response.status_counts


def test_a_deleting_pair_has_its_own_bucket_and_an_invalid_one_reads_failed(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    prefix = _prefix()
    deleting = _create_cc_pair(
        db_session, prefix, "deleting", ConnectorCredentialPairStatus.DELETING
    )
    invalid = _create_cc_pair(
        db_session, prefix, "invalid", ConnectorCredentialPairStatus.INVALID
    )
    # A failed last run does not pull a deleting pair into the failed bucket.
    _index_attempt(db_session, deleting, IndexingStatus.FAILED, now)

    response = _connectors(db_session, prefix)

    statuses = {row.name: row.status for row in response.items}
    assert statuses == {
        deleting.name: IndexingConnectorStatus.DELETING,
        invalid.name: IndexingConnectorStatus.FAILED,
    }
    assert response.status_counts[IndexingConnectorStatus.DELETING] == 1
    assert response.status_counts[IndexingConnectorStatus.FAILED] == 1

    filtered = _connectors(db_session, prefix, status=IndexingConnectorStatus.DELETING)

    assert [row.name for row in filtered.items] == [deleting.name]
    assert filtered.status_counts == response.status_counts


def test_a_running_backfill_is_the_pairs_current_run(db_session: Session) -> None:
    now = datetime.now(timezone.utc)
    prefix = _prefix()
    cc_pair = _create_cc_pair(db_session, prefix, "backfilling")
    _index_attempt(
        db_session, cc_pair, IndexingStatus.SUCCESS, now - timedelta(hours=1)
    )
    backfill = _index_attempt(
        db_session, cc_pair, IndexingStatus.IN_PROGRESS, now, is_backfill=True
    )

    response = _connectors(db_session, prefix)

    row = response.items[0]
    assert row.status == IndexingConnectorStatus.INDEXING
    assert row.latest_index_attempt is not None
    assert row.latest_index_attempt.id == backfill.id


def test_search_narrows_the_counts_and_pages_hold_their_order(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    prefix = _prefix()
    names = ["page c", "page a", "page b"]
    for name in names:
        pair = _create_cc_pair(db_session, prefix, name)
        _index_attempt(db_session, pair, IndexingStatus.SUCCESS, now)
    _create_cc_pair(db_session, prefix, "other")

    first = _connectors(db_session, f"{prefix} page", page_size=2)
    second = _connectors(db_session, f"{prefix} page", page_num=1, page_size=2)

    assert [row.name for row in first.items] == [
        f"{prefix} page a",
        f"{prefix} page b",
    ]
    assert [row.name for row in second.items] == [f"{prefix} page c"]
    assert first.total_items == 3
    assert first.status_counts[IndexingConnectorStatus.INDEXED] == 3
    assert first.status_counts[IndexingConnectorStatus.SCHEDULED] == 0


def test_a_queued_attempt_knows_its_place_in_line(db_session: Session) -> None:
    now = datetime.now(timezone.utc)
    prefix = _prefix()
    second = _create_cc_pair(db_session, prefix, "queued second")
    first = _create_cc_pair(db_session, prefix, "queued first")
    held = _create_cc_pair(db_session, prefix, "queued held")
    _index_attempt(db_session, first, IndexingStatus.NOT_STARTED, now)
    _index_attempt(
        db_session, second, IndexingStatus.NOT_STARTED, now + timedelta(seconds=1)
    )
    # Still in capability checks: scheduled, but not in the line yet.
    _index_attempt(db_session, held, IndexingStatus.NOT_STARTED, now, dispatched=False)

    response = _connectors(db_session, prefix, status=IndexingConnectorStatus.SCHEDULED)

    positions = {row.name: row.queue_position for row in response.items}
    assert positions[held.name] is None
    first_position = positions[first.name]
    second_position = positions[second.name]
    assert first_position is not None
    assert second_position is not None
    # Other pairs may be queued ahead, so only the order between these two holds.
    assert first_position < second_position


def test_a_rows_open_error_count_includes_whole_entity_failures(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    prefix = _prefix()
    entity_only = _create_cc_pair(db_session, prefix, "a entity only")
    resolved = _create_cc_pair(db_session, prefix, "b resolved")
    for cc_pair in (entity_only, resolved):
        attempt = _index_attempt(
            db_session, cc_pair, IndexingStatus.COMPLETED_WITH_ERRORS, now
        )
        # A whole mailbox failed, so the error names no document.
        db_session.add(
            IndexAttemptError(
                index_attempt_id=attempt.id,
                connector_credential_pair_id=cc_pair.id,
                entity_id="mailbox-1",
                failure_message="mailbox unreadable",
                is_resolved=False,
            )
        )
        db_session.commit()
    resolve_runs__no_commit(
        db_session, {(CCPairRunKind.INDEXING, attempt.id): resolved.id}, None
    )
    db_session.commit()

    rows = {row.name: row for row in _connectors(db_session, prefix).items}

    assert rows[entity_only.name].open_error_count == 1
    latest = rows[entity_only.name].latest_index_attempt
    assert latest is not None
    assert latest.open_doc_error_count == 0
    assert rows[resolved.name].open_error_count == 0


def test_ac1_a_running_permission_or_group_sync_reads_syncing_unless_an_index_runs(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    prefix = _prefix()
    doc_sync = _create_cc_pair(db_session, prefix, "doc sync")
    group_sync = _create_cc_pair(db_session, prefix, "group sync")
    both = _create_cc_pair(db_session, prefix, "index and sync")
    finished = _create_cc_pair(db_session, prefix, "sync finished")
    for cc_pair in (doc_sync, group_sync, finished):
        _index_attempt(db_session, cc_pair, IndexingStatus.SUCCESS, now)
    _index_attempt(db_session, both, IndexingStatus.IN_PROGRESS, now)
    _doc_permission_sync(db_session, doc_sync)
    _group_sync(db_session, group_sync)
    _doc_permission_sync(db_session, both)
    _group_sync(db_session, both)
    # Only a sync that runs now counts.
    _doc_permission_sync(db_session, finished, PermissionSyncStatus.SUCCESS)
    _group_sync(db_session, finished, PermissionSyncStatus.SUCCESS)

    response = _connectors(db_session, prefix)

    statuses = {row.name: row.status for row in response.items}
    assert statuses == {
        doc_sync.name: IndexingConnectorStatus.SYNCING,
        group_sync.name: IndexingConnectorStatus.SYNCING,
        both.name: IndexingConnectorStatus.INDEXING,
        finished.name: IndexingConnectorStatus.INDEXED,
    }
    assert response.status_counts[IndexingConnectorStatus.SYNCING] == 2
    assert response.status_counts[IndexingConnectorStatus.INDEXING] == 1


def test_ac3_source_counts_hold_the_full_counts_on_every_page(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    prefix = _prefix()
    gmail_a = _create_cc_pair(
        db_session, prefix, "a gmail", source=DocumentSource.GMAIL
    )
    gmail_b = _create_cc_pair(
        db_session, prefix, "b gmail", source=DocumentSource.GMAIL
    )
    drive = _create_cc_pair(db_session, prefix, "c drive")
    gmail_paused = _create_cc_pair(
        db_session,
        prefix,
        "d gmail paused",
        ConnectorCredentialPairStatus.PAUSED,
        source=DocumentSource.GMAIL,
    )
    for cc_pair in (gmail_a, gmail_b, drive, gmail_paused):
        _index_attempt(db_session, cc_pair, IndexingStatus.SUCCESS, now)

    pages = [
        _connectors(db_session, prefix, page_num=page_num, page_size=1)
        for page_num in range(4)
    ]

    assert [page.items[0].name for page in pages] == [
        gmail_a.name,
        gmail_b.name,
        drive.name,
        gmail_paused.name,
    ]
    for page in pages:
        assert page.source_counts == {
            DocumentSource.GMAIL: 3,
            DocumentSource.GOOGLE_DRIVE: 1,
        }

    # The status filter and the search narrow the counts too.
    indexed = _connectors(
        db_session, prefix, status=IndexingConnectorStatus.INDEXED, page_size=1
    )
    assert indexed.source_counts == {
        DocumentSource.GMAIL: 2,
        DocumentSource.GOOGLE_DRIVE: 1,
    }
    searched = _connectors(db_session, f"{prefix} c drive")
    assert searched.source_counts == {DocumentSource.GOOGLE_DRIVE: 1}


def test_ac3_no_matching_pairs_gives_empty_counts(db_session: Session) -> None:
    response = _connectors(db_session, _prefix())

    assert response.items == []
    assert response.source_counts == {}
    assert response.status_counts == dict.fromkeys(IndexingConnectorStatus, 0)
    assert IndexingConnectorStatus.SYNCING in response.status_counts


def test_ac4_a_private_row_names_its_shared_groups(db_session: Session) -> None:
    prefix = _prefix()
    private = _create_cc_pair(
        db_session, prefix, "private", access_type=AccessType.PRIVATE
    )
    public = _create_cc_pair(db_session, prefix, "public")
    synced = _create_cc_pair(db_session, prefix, "synced", access_type=AccessType.SYNC)
    group_names = [f"{prefix} group {index}" for index in range(3)]
    _share_with_groups(db_session, private, group_names)
    # Groups that manage a public or synced pair do not make it shared.
    _share_with_groups(db_session, public, [f"{prefix} public managers"])
    _share_with_groups(db_session, synced, [f"{prefix} synced managers"])

    rows = {row.name: row for row in _connectors(db_session, prefix).items}

    assert rows[private.name].group_count == 3
    assert sorted(rows[private.name].group_names) == sorted(group_names)
    for name in (public.name, synced.name):
        assert rows[name].group_count == 0
        assert rows[name].group_names == []


def test_ac5_a_scoped_reader_counts_only_readable_pairs(db_session: Session) -> None:
    now = datetime.now(timezone.utc)
    prefix = _prefix()
    reader = create_test_user(db_session, "monitor_list_reader")
    readable_paused = _create_cc_pair(
        db_session, prefix, "readable paused", ConnectorCredentialPairStatus.PAUSED
    )
    readable_gmail = _create_cc_pair(
        db_session, prefix, "readable gmail", source=DocumentSource.GMAIL
    )
    # Private with no group the reader belongs to, so the reader cannot read it.
    hidden_paused = _create_cc_pair(
        db_session,
        prefix,
        "hidden paused",
        ConnectorCredentialPairStatus.PAUSED,
        source=DocumentSource.GMAIL,
        access_type=AccessType.PRIVATE,
    )
    hidden_syncing = _create_cc_pair(
        db_session, prefix, "hidden syncing", access_type=AccessType.PRIVATE
    )
    for cc_pair in (readable_paused, readable_gmail, hidden_paused, hidden_syncing):
        _index_attempt(db_session, cc_pair, IndexingStatus.SUCCESS, now)
    _doc_permission_sync(db_session, hidden_syncing)

    response = get_indexing_connectors(
        page_num=0,
        page_size=20,
        q=prefix,
        status=None,
        user=reader,
        db_session=db_session,
    )

    assert {row.name for row in response.items} == {
        readable_paused.name,
        readable_gmail.name,
    }
    assert response.status_counts[IndexingConnectorStatus.PAUSED] == 1
    assert response.status_counts[IndexingConnectorStatus.INDEXED] == 1
    assert response.status_counts[IndexingConnectorStatus.SYNCING] == 0
    assert sum(response.status_counts.values()) == 2
    assert response.source_counts == {
        DocumentSource.GOOGLE_DRIVE: 1,
        DocumentSource.GMAIL: 1,
    }


def test_ac7_the_syncing_filter_returns_only_syncing_rows_and_keeps_every_count(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    prefix = _prefix()
    syncing = _create_cc_pair(db_session, prefix, "syncing")
    indexed = _create_cc_pair(db_session, prefix, "indexed")
    paused = _create_cc_pair(
        db_session, prefix, "paused", ConnectorCredentialPairStatus.PAUSED
    )
    for cc_pair in (syncing, indexed, paused):
        _index_attempt(db_session, cc_pair, IndexingStatus.SUCCESS, now)
    _group_sync(db_session, syncing)

    unfiltered = _connectors(db_session, prefix)
    filtered = _connectors(db_session, prefix, status=IndexingConnectorStatus.SYNCING)

    assert [row.name for row in filtered.items] == [syncing.name]
    assert filtered.total_items == 1
    assert filtered.status_counts == unfiltered.status_counts
    assert filtered.status_counts[IndexingConnectorStatus.SYNCING] == 1
    assert filtered.status_counts[IndexingConnectorStatus.INDEXED] == 1
    assert filtered.status_counts[IndexingConnectorStatus.PAUSED] == 1


def test_a_failed_prune_or_check_ranks_a_connector_third(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    prefix = _prefix()
    running = _create_cc_pair(db_session, prefix, "b running")
    prune_failed = _create_cc_pair(db_session, prefix, "z prune failed")
    check_failed = _create_cc_pair(db_session, prefix, "y check failed")
    indexed = _create_cc_pair(db_session, prefix, "a indexed")
    prune_fixed = _create_cc_pair(db_session, prefix, "x prune fixed")
    check_resolved = _create_cc_pair(db_session, prefix, "w check resolved")
    _index_attempt(db_session, running, IndexingStatus.IN_PROGRESS, now)
    for cc_pair in (prune_failed, check_failed, indexed, prune_fixed, check_resolved):
        _index_attempt(db_session, cc_pair, IndexingStatus.SUCCESS, now)
    # A running pair with a failed prune keeps rank 1.
    _prune(db_session, running, SyncStatus.FAILED, now)
    _prune(db_session, prune_failed, SyncStatus.FAILED, now)
    _failed_check(db_session, check_failed)
    # A newer prune that succeeded closes the failure.
    _prune(db_session, prune_fixed, SyncStatus.FAILED, now - timedelta(hours=2))
    _prune(db_session, prune_fixed, SyncStatus.SUCCESS, now - timedelta(hours=1))
    resolved_check = _failed_check(db_session, check_resolved)
    resolve_runs__no_commit(
        db_session, {(CCPairRunKind.CHECKS, resolved_check.id): check_resolved.id}, None
    )
    db_session.commit()

    response = _connectors(db_session, prefix)

    assert [row.name for row in response.items] == [
        running.name,
        check_failed.name,
        prune_failed.name,
        indexed.name,
        check_resolved.name,
        prune_fixed.name,
    ]
    rows = {row.name: row for row in response.items}
    # Pruning and checks never set the state.
    assert rows[prune_failed.name].status == IndexingConnectorStatus.INDEXED
    assert rows[check_failed.name].status == IndexingConnectorStatus.INDEXED
    assert rows[running.name].status == IndexingConnectorStatus.INDEXING
    open_counts = {name: row.open_error_count for name, row in rows.items()}
    assert open_counts == {
        running.name: 1,
        check_failed.name: 1,
        prune_failed.name: 1,
        indexed.name: 0,
        check_resolved.name: 0,
        prune_fixed.name: 0,
    }


def test_a_scoped_reader_sees_only_the_shared_groups_they_can_see(
    db_session: Session,
) -> None:
    prefix = _prefix()
    private = _create_cc_pair(
        db_session, prefix, "private", access_type=AccessType.PRIVATE
    )
    restricted = _create_cc_pair(
        db_session, prefix, "restricted", access_type=AccessType.SYNC_RESTRICTED
    )
    group_names = [f"{prefix} group {index}" for index in range(3)]
    _share_with_groups(db_session, private, group_names)
    _share_with_groups(db_session, restricted, [f"{prefix} restricted group"])
    groups = {
        group.name: group
        for group in db_session.scalars(
            select(UserGroup).where(UserGroup.name.in_(group_names))
        )
    }
    manager = create_test_user(db_session, "monitor_list_manager")
    member = create_test_user(db_session, "monitor_list_member")
    for name in group_names[:2]:
        db_session.add(
            User__UserGroup(
                user_id=manager.id, user_group_id=groups[name].id, is_manager=True
            )
        )
    db_session.add(
        User__UserGroup(
            user_id=member.id, user_group_id=groups[group_names[2]].id, is_manager=False
        )
    )
    manager.is_group_manager = True
    db_session.commit()

    def private_row(user: User) -> IndexingConnectorRow:
        response = get_indexing_connectors(
            page_num=0,
            page_size=20,
            q=prefix,
            status=None,
            user=user,
            db_session=db_session,
        )
        return next(row for row in response.items if row.name == private.name)

    admin_rows = {row.name: row for row in _connectors(db_session, prefix).items}
    assert admin_rows[private.name].group_names == group_names
    # A sync-restricted pair's data-access groups gate its documents too.
    assert admin_rows[restricted.name].group_names == [f"{prefix} restricted group"]
    # A scoped manager sees the groups they manage, as the pair's own data-access route lists them.
    managed = private_row(manager)
    assert managed.group_names == group_names[:2]
    assert managed.group_count == 2
    # A member who reads the pair through a group sees no group names.
    read_only = private_row(member)
    assert read_only.group_names == []
    assert read_only.group_count == 0
