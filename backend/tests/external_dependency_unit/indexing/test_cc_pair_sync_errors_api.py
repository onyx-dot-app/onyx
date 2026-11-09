"""The users and groups a group sync could not read: the pair lists them, an
operator resolves them without retry one by one or with their run, the run's
chips count every row and its open count only open ones, and the activity
panel's Errors level, resolvable count and Resolve All agree on which group
syncs hold open rows."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ee.onyx.server.documents.cc_pair import (
    get_cc_pair_sync_errors,
    resolve_cc_pair_sync_errors,
)
from ee.onyx.server.documents.models import SyncAttemptErrorsResolveRequest
from onyx.configs.constants import DocumentSource
from onyx.db.enums import (
    AccessType,
    CCPairRunErrors,
    CCPairRunKind,
    IndexAttemptErrorOrder,
    PermissionSyncStatus,
    SyncAttemptErrorResolvedReason,
    SyncEntityKind,
)
from onyx.db.models import (
    ConnectorCredentialPair,
    ExternalGroupPermissionSyncAttempt,
    SyncAttemptError,
    User,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.cc_pair import (
    get_cc_pair_runs,
    get_resolvable_cc_pair_runs_count,
    resolve_cc_pair_runs,
    resolve_matching_cc_pair_runs,
)
from onyx.server.documents.models import (
    CCPairGroupSyncRun,
    CCPairRunKey,
    CCPairRunLevel,
    CCPairRunsResolveMatchingRequest,
    CCPairRunsResolveRequest,
    CCPairRunsResponse,
)
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.indexing.run_feed_records import (
    RunFeedRecords,
    run_mark,
)

# Group syncs and their routes are EE-only.
pytestmark = pytest.mark.usefixtures("enable_ee")


@pytest.fixture
def made(db_session: Session) -> Generator[RunFeedRecords, None, None]:
    created = RunFeedRecords(db_session)
    yield created
    db_session.rollback()
    # Group sync attempts do not cascade with their pair. Their rows do.
    db_session.query(ExternalGroupPermissionSyncAttempt).filter(
        ExternalGroupPermissionSyncAttempt.connector_credential_pair_id.in_(
            [pair.id for pair in created.pairs]
        )
    ).delete(synchronize_session=False)
    db_session.commit()
    created.cleanup()


def _synced_pair(made: RunFeedRecords, name: str) -> ConnectorCredentialPair:
    return made.pair(name, access_type=AccessType.SYNC)


def _group_sync(
    db_session: Session,
    pair: ConnectorCredentialPair,
    status: PermissionSyncStatus = PermissionSyncStatus.COMPLETED_WITH_ERRORS,
    minutes_ago: int = 30,
) -> ExternalGroupPermissionSyncAttempt:
    attempt = ExternalGroupPermissionSyncAttempt(
        connector_credential_pair_id=pair.id, status=status
    )
    db_session.add(attempt)
    db_session.flush()
    attempt.time_created = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    db_session.commit()
    return attempt


def _row(
    db_session: Session,
    attempt: ExternalGroupPermissionSyncAttempt,
    kind: SyncEntityKind,
    entity_id: str,
    *,
    name: str | None = None,
    message: str = "403 reading memberships",
    minutes_ago: int = 20,
    closed: bool = False,
) -> int:
    row = SyncAttemptError(
        external_group_sync_attempt_id=attempt.id,
        connector_credential_pair_id=attempt.connector_credential_pair_id,
        entity_kind=kind,
        entity_id=entity_id,
        entity_name=name,
        failure_message=message,
        resolved_reason=(
            SyncAttemptErrorResolvedReason.WITHOUT_RETRY if closed else None
        ),
        resolved_at=datetime.now(timezone.utc) if closed else None,
    )
    db_session.add(row)
    db_session.flush()
    row.time_created = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    db_session.commit()
    return row.id


def _list(
    db_session: Session,
    user: User,
    pair: ConnectorCredentialPair,
    include_resolved: bool = False,
    page_num: int = 0,
    page_size: int = 10,
    attempt_id: int | None = None,
    entity_kind: SyncEntityKind | None = None,
    q: str | None = None,
    order: IndexAttemptErrorOrder = IndexAttemptErrorOrder.TIME,
) -> tuple[list[int], int]:
    page = get_cc_pair_sync_errors(
        cc_pair_id=pair.id,
        include_resolved=include_resolved,
        page_num=page_num,
        page_size=page_size,
        attempt_id=attempt_id,
        entity_kind=entity_kind,
        order=order,
        q=q,
        user=user,
        db_session=db_session,
    )
    return [row.id for row in page.items], page.total_items


def _resolve_rows(
    db_session: Session, user: User, pair: ConnectorCredentialPair, ids: list[int]
) -> int:
    return resolve_cc_pair_sync_errors(
        cc_pair_id=pair.id,
        request=SyncAttemptErrorsResolveRequest(error_ids=ids),
        user=user,
        db_session=db_session,
    ).resolved_count


def _closure(
    db_session: Session, row_id: int
) -> tuple[bool, SyncAttemptErrorResolvedReason | None, bool]:
    """(is_resolved, resolved_reason, has resolved_at)."""
    db_session.expire_all()
    is_resolved, reason, resolved_at = db_session.execute(
        select(
            SyncAttemptError.is_resolved,
            SyncAttemptError.resolved_reason,
            SyncAttemptError.resolved_at,
        ).where(SyncAttemptError.id == row_id)
    ).one()
    return is_resolved, reason, resolved_at is not None


_OPEN = (False, None, False)
_WITHOUT_RETRY = (False, SyncAttemptErrorResolvedReason.WITHOUT_RETRY, True)


def _feed(
    db_session: Session,
    user: User,
    pair: ConnectorCredentialPair,
    errors: CCPairRunErrors | None = None,
    superseded: bool | None = None,
    resolved: bool | None = None,
    q: str | None = None,
) -> CCPairRunsResponse:
    return get_cc_pair_runs(
        cc_pair_id=pair.id,
        page_num=0,
        page_size=10,
        since=None,
        until=None,
        kinds=[CCPairRunKind.GROUP_SYNC],
        status_groups=None,
        q=q,
        errors=errors,
        superseded=superseded,
        resolved=resolved,
        user=user,
        db_session=db_session,
    )


def _open_errors_level(
    db_session: Session, user: User, pair: ConnectorCredentialPair
) -> list[int]:
    feed = _feed(
        db_session,
        user,
        pair,
        CCPairRunErrors.UNRESOLVED,
        superseded=False,
        resolved=False,
    )
    return [run.attempt.id for run in feed.items]


def _group_sync_item(
    db_session: Session, user: User, pair: ConnectorCredentialPair, attempt_id: int
) -> CCPairGroupSyncRun:
    for run in _feed(db_session, user, pair).items:
        if isinstance(run, CCPairGroupSyncRun) and run.attempt.id == attempt_id:
            return run
    raise AssertionError(f"group sync {attempt_id} is not in the feed")


def test_lists_open_rows_newest_first_and_pages_searches_and_narrows(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("sync_errors_admin", is_admin=True)
    pair = _synced_pair(made, "Sync Errors List")
    other = _synced_pair(made, "Sync Errors Other")
    mark = run_mark("sync-errors")
    attempt = _group_sync(db_session, pair)
    later = _group_sync(db_session, pair, minutes_ago=10)
    oldest = _row(db_session, attempt, SyncEntityKind.USER, "acct-1", minutes_ago=25)
    named = _row(
        db_session,
        attempt,
        SyncEntityKind.USER,
        "acct-2",
        name=f"{mark}@example.com",
        minutes_ago=24,
    )
    group = _row(
        db_session,
        attempt,
        SyncEntityKind.GROUP,
        "eng@example.com",
        message=f"{mark} group read failed",
        minutes_ago=23,
    )
    closed = _row(
        db_session, attempt, SyncEntityKind.USER, "acct-3", minutes_ago=22, closed=True
    )
    newest = _row(db_session, later, SyncEntityKind.USER, "acct-4", minutes_ago=5)
    _row(db_session, _group_sync(db_session, other), SyncEntityKind.USER, "acct-1")

    assert _list(db_session, admin, pair) == ([newest, group, named, oldest], 4)
    assert _list(db_session, admin, pair, page_num=1, page_size=3) == ([oldest], 4)
    assert _list(db_session, admin, pair, q=mark) == ([group, named], 2)
    assert _list(db_session, admin, pair, q="ENG@EXAMPLE") == ([group], 1)
    assert _list(db_session, admin, pair, attempt_id=later.id) == ([newest], 1)
    assert _list(
        db_session, admin, pair, include_resolved=True, attempt_id=attempt.id
    ) == (
        [closed, group, named, oldest],
        4,
    )
    listed = get_cc_pair_sync_errors(
        cc_pair_id=pair.id,
        include_resolved=True,
        page_num=0,
        page_size=10,
        attempt_id=attempt.id,
        q=mark,
        user=admin,
        db_session=db_session,
    ).items
    assert [
        (
            row.entity_kind,
            row.entity_id,
            row.entity_name,
            row.external_group_sync_attempt_id,
        )
        for row in listed
    ] == [
        (SyncEntityKind.GROUP, "eng@example.com", None, attempt.id),
        (SyncEntityKind.USER, "acct-2", f"{mark}@example.com", attempt.id),
    ]


def test_a_shared_source_lists_the_rows_of_its_sibling_pairs_sync(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("sync_errors_admin", is_admin=True)
    pair = _synced_pair(made, "Sync Errors Jira")
    sibling = _synced_pair(made, "Sync Errors Jira Sibling")
    for shared in (pair, sibling):
        shared.connector.source = DocumentSource.JIRA
    db_session.commit()
    # Jira syncs groups once for every pair, logged on the pair that ran it.
    row = _row(db_session, _group_sync(db_session, sibling), SyncEntityKind.USER, "a")

    assert _list(db_session, admin, pair) == ([row], 1)
    assert _resolve_rows(db_session, admin, pair, [row]) == 1


def test_resolve_closes_the_chosen_rows_without_retry(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("sync_errors_admin", is_admin=True)
    pair = _synced_pair(made, "Sync Errors Resolve")
    other = _synced_pair(made, "Sync Errors Resolve Other")
    attempt = _group_sync(db_session, pair)
    first = _row(db_session, attempt, SyncEntityKind.USER, "acct-1")
    second = _row(db_session, attempt, SyncEntityKind.GROUP, "eng@example.com")
    not_chosen = _row(db_session, attempt, SyncEntityKind.USER, "acct-2")
    other_pairs = _row(
        db_session, _group_sync(db_session, other), SyncEntityKind.USER, "acct-1"
    )

    assert _resolve_rows(db_session, admin, pair, [first, second, other_pairs]) == 2

    assert _closure(db_session, first) == _WITHOUT_RETRY
    assert _closure(db_session, second) == _WITHOUT_RETRY
    assert _closure(db_session, not_chosen) == _OPEN
    assert _closure(db_session, other_pairs) == _OPEN
    assert _list(db_session, admin, pair) == ([not_chosen], 1)
    # A second resolve of the same rows changes nothing.
    assert _resolve_rows(db_session, admin, pair, [first, second]) == 0


def test_resolving_the_run_closes_its_rows_without_retry(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("sync_errors_admin", is_admin=True)
    pair = _synced_pair(made, "Sync Errors Run Resolve")
    attempt = _group_sync(db_session, pair)
    other_run = _group_sync(db_session, pair, minutes_ago=40)
    rows = [
        _row(db_session, attempt, SyncEntityKind.USER, f"acct-{i}") for i in range(2)
    ]
    other_runs_row = _row(db_session, other_run, SyncEntityKind.USER, "acct-x")

    resolved = resolve_cc_pair_runs(
        cc_pair_id=pair.id,
        request=CCPairRunsResolveRequest(
            runs=[CCPairRunKey(kind=CCPairRunKind.GROUP_SYNC, attempt_id=attempt.id)]
        ),
        user=admin,
        db_session=db_session,
    ).resolved_count

    assert resolved == 1
    for row in rows:
        assert _closure(db_session, row) == _WITHOUT_RETRY
    assert _closure(db_session, other_runs_row) == _OPEN
    assert _group_sync_item(db_session, admin, pair, attempt.id).resolved_at is not None


def test_chips_count_every_row_and_the_open_count_only_open_ones(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("sync_errors_admin", is_admin=True)
    pair = _synced_pair(made, "Sync Errors Chips")
    attempt = _group_sync(db_session, pair)
    clean = _group_sync(db_session, pair, PermissionSyncStatus.SUCCESS, 50)
    for i in range(3):
        _row(db_session, attempt, SyncEntityKind.USER, f"acct-{i}", closed=i == 0)
    _row(db_session, attempt, SyncEntityKind.GROUP, "eng@example.com", closed=True)

    item = _group_sync_item(db_session, admin, pair, attempt.id)
    assert (
        item.attempt.failed_users,
        item.attempt.failed_groups,
        item.attempt.open_error_count,
    ) == (3, 1, 2)
    no_rows = _group_sync_item(db_session, admin, pair, clean.id)
    assert (
        no_rows.attempt.failed_users,
        no_rows.attempt.failed_groups,
        no_rows.attempt.open_error_count,
    ) == (0, 0, 0)


def test_errors_level_resolvable_count_and_resolve_all_agree_with_the_rows(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("sync_errors_admin", is_admin=True)
    pair = _synced_pair(made, "Sync Errors Level")
    mark = run_mark("sync-errors-level")
    with_open = _group_sync(db_session, pair, minutes_ago=40)
    row = _row(db_session, with_open, SyncEntityKind.USER, "acct-1", name=mark)
    all_closed = _group_sync(db_session, pair, minutes_ago=50)
    _row(db_session, all_closed, SyncEntityKind.USER, "acct-2", closed=True)
    _group_sync(db_session, pair, PermissionSyncStatus.SUCCESS, minutes_ago=60)

    assert _open_errors_level(db_session, admin, pair) == [with_open.id]
    assert [
        run.attempt.id
        for run in _feed(db_session, admin, pair, CCPairRunErrors.RESOLVED).items
    ] == [all_closed.id]
    # A search reads the run's rows too.
    assert [run.attempt.id for run in _feed(db_session, admin, pair, q=mark).items] == [
        with_open.id
    ]
    count = get_resolvable_cc_pair_runs_count(
        cc_pair_id=pair.id,
        level=CCPairRunLevel.ERRORS,
        q=None,
        since=None,
        until=None,
        kinds=None,
        user=admin,
        db_session=db_session,
    ).count
    assert count == 1

    resolved = resolve_matching_cc_pair_runs(
        cc_pair_id=pair.id,
        request=CCPairRunsResolveMatchingRequest(level=CCPairRunLevel.ERRORS),
        user=admin,
        db_session=db_session,
    ).resolved_count

    assert resolved == count
    assert _closure(db_session, row) == _WITHOUT_RETRY
    assert _open_errors_level(db_session, admin, pair) == []
    resolved_runs = _feed(db_session, admin, pair, resolved=True).items
    assert [run.attempt.id for run in resolved_runs] == [with_open.id]


def test_resolving_the_last_open_row_drops_the_run_from_the_errors_level(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("sync_errors_admin", is_admin=True)
    pair = _synced_pair(made, "Sync Errors Last Row")
    attempt = _group_sync(db_session, pair)
    row = _row(db_session, attempt, SyncEntityKind.GROUP, "eng@example.com")
    assert _open_errors_level(db_session, admin, pair) == [attempt.id]

    _resolve_rows(db_session, admin, pair, [row])

    assert _open_errors_level(db_session, admin, pair) == []


def test_entity_kind_keeps_only_users_or_only_groups_across_pages(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("sync_errors_admin", is_admin=True)
    pair = _synced_pair(made, "Sync Errors Kind")
    attempt = _group_sync(db_session, pair)
    # The group row is the oldest, so an unfiltered first page never holds it.
    group = _row(
        db_session, attempt, SyncEntityKind.GROUP, "eng@example.com", minutes_ago=25
    )
    users = [
        _row(db_session, attempt, SyncEntityKind.USER, f"acct-{i}", minutes_ago=20 - i)
        for i in range(3)
    ]

    assert _list(db_session, admin, pair, page_size=2)[0] == users[:0:-1]
    assert _list(
        db_session, admin, pair, page_size=2, entity_kind=SyncEntityKind.GROUP
    ) == ([group], 1)
    assert _list(
        db_session, admin, pair, page_size=10, entity_kind=SyncEntityKind.USER
    ) == (users[::-1], 3)


def test_state_order_lists_open_rows_first_across_pages(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("sync_errors_admin", is_admin=True)
    pair = _synced_pair(made, "Sync Errors State")
    attempt = _group_sync(db_session, pair)
    closed_new = _row(
        db_session, attempt, SyncEntityKind.USER, "acct-1", minutes_ago=5, closed=True
    )
    open_new = _row(db_session, attempt, SyncEntityKind.USER, "acct-2", minutes_ago=10)
    closed_old = _row(
        db_session, attempt, SyncEntityKind.USER, "acct-3", minutes_ago=15, closed=True
    )
    open_old = _row(db_session, attempt, SyncEntityKind.GROUP, "g", minutes_ago=20)
    open_tie = _row(db_session, attempt, SyncEntityKind.GROUP, "h", minutes_ago=20)
    # Two rows at one time: the higher id comes first.
    db_session.execute(
        update(SyncAttemptError)
        .where(SyncAttemptError.id == open_tie)
        .values(
            time_created=select(SyncAttemptError.time_created)
            .where(SyncAttemptError.id == open_old)
            .scalar_subquery()
        )
    )
    db_session.commit()

    def pages(order: IndexAttemptErrorOrder) -> list[int]:
        return [
            row_id
            for page_num in range(3)
            for row_id in _list(
                db_session,
                admin,
                pair,
                include_resolved=True,
                page_num=page_num,
                page_size=2,
                order=order,
            )[0]
        ]

    assert pages(IndexAttemptErrorOrder.STATE) == [
        open_new,
        open_tie,
        open_old,
        closed_new,
        closed_old,
    ]
    assert pages(IndexAttemptErrorOrder.TIME) == [
        closed_new,
        open_new,
        closed_old,
        open_tie,
        open_old,
    ]


@pytest.mark.parametrize(
    "older_status",
    # A sync that trips the failed-entity cap fails after writing its rows.
    [PermissionSyncStatus.COMPLETED_WITH_ERRORS, PermissionSyncStatus.FAILED],
)
def test_a_newer_sync_leaves_open_rows_listed_counted_and_under_errors(
    db_session: Session, made: RunFeedRecords, older_status: PermissionSyncStatus
) -> None:
    admin = made.user("sync_errors_admin", is_admin=True)
    pair = _synced_pair(made, "Sync Errors Newer")
    older = _group_sync(db_session, pair, older_status, minutes_ago=40)
    row = _row(db_session, older, SyncEntityKind.USER, "acct-1", minutes_ago=35)
    _group_sync(db_session, pair, PermissionSyncStatus.SUCCESS, minutes_ago=10)

    assert _list(db_session, admin, pair) == ([row], 1)
    assert (
        _group_sync_item(db_session, admin, pair, older.id).attempt.open_error_count
        == 1
    )
    assert _open_errors_level(db_session, admin, pair) == [older.id]


def test_a_caller_who_cannot_read_or_operate_the_pair_is_refused(
    db_session: Session, made: RunFeedRecords
) -> None:
    # Every user reads a SYNC pair's activity, so the pair is restricted.
    pair = made.pair("Sync Errors Scope", access_type=AccessType.SYNC_RESTRICTED)
    row = _row(db_session, _group_sync(db_session, pair), SyncEntityKind.USER, "a")
    outsider = create_test_user(
        db_session, "sync_errors_outsider", assign_default_group=False
    )
    made.users.append(outsider)

    with pytest.raises(OnyxError) as list_refused:
        _list(db_session, outsider, pair)
    with pytest.raises(OnyxError) as resolve_refused:
        _resolve_rows(db_session, outsider, pair, [row])

    assert list_refused.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    assert resolve_refused.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    assert _closure(db_session, row) == _OPEN
