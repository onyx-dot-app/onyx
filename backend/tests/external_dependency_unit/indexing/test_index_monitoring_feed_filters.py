"""The fleet feed's `cc_pair_ids` narrows its list, count and resolve to the
named pairs the caller can read, and a queued attempt is `scheduled` on both feeds."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import AccessType, CCPairRunStatusGroup, IndexingStatus
from onyx.db.models import (
    ConnectorCredentialPair,
    IndexAttempt,
    IndexAttemptError,
    User,
)
from onyx.server.documents.cc_pair import get_resolvable_cc_pair_runs_count
from onyx.server.documents.index_monitoring import (
    get_indexing_runs,
    get_resolvable_indexing_runs_count,
    resolve_indexing_runs,
)
from onyx.server.documents.models import (
    CCPairRunLevel,
    CCPairRunsResolveMatchingRequest,
    IndexingRunsResponse,
)
from tests.external_dependency_unit.indexing.run_feed_records import (
    RunFeedRecords,
    make_index_attempt,
    read_pair_feed,
    run_mark,
)

# The perm sync kinds come from the EE-only sync_params helpers.
pytestmark = pytest.mark.usefixtures("enable_ee")

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _mark() -> str:
    return run_mark("feed-filters")


@pytest.fixture
def made(db_session: Session) -> Generator[RunFeedRecords, None, None]:
    pairs = RunFeedRecords(db_session)
    yield pairs
    pairs.cleanup()


def _index_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    minutes: int,
    status: IndexingStatus,
    mark: str,
) -> IndexAttempt:
    return make_index_attempt(
        db_session, cc_pair, _T0 + timedelta(minutes=minutes), status, mark
    )


def _doc_error(db_session: Session, attempt: IndexAttempt, mark: str) -> None:
    db_session.add(
        IndexAttemptError(
            index_attempt_id=attempt.id,
            connector_credential_pair_id=attempt.connector_credential_pair_id,
            document_id=f"doc-{attempt.id}",
            failure_message=mark,
            is_resolved=False,
        )
    )
    db_session.commit()


def _fleet(
    db_session: Session,
    user: User,
    mark: str,
    cc_pair_ids: list[int] | None = None,
    status_groups: list[CCPairRunStatusGroup] | None = None,
    resolved: bool | None = None,
) -> IndexingRunsResponse:
    return get_indexing_runs(
        page_num=0,
        page_size=10,
        since=None,
        until=None,
        kinds=None,
        status_groups=status_groups,
        q=mark,
        errors=None,
        superseded=None,
        resolved=resolved,
        cc_pair_ids=cc_pair_ids,
        user=user,
        db_session=db_session,
    )


def _fleet_resolvable(
    db_session: Session, user: User, mark: str, cc_pair_ids: list[int]
) -> int:
    return get_resolvable_indexing_runs_count(
        level=None,
        q=mark,
        since=None,
        until=None,
        kinds=None,
        cc_pair_ids=cc_pair_ids,
        user=user,
        db_session=db_session,
    ).count


def test_fleet_feed_lists_and_counts_only_the_named_pairs(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("feed_filters_admin", is_admin=True)
    mark = _mark()
    first = made.pair("Feed Filters First", AccessType.PUBLIC, admin)
    second = made.pair("Feed Filters Second", AccessType.PUBLIC, admin)
    third = made.pair("Feed Filters Third", AccessType.PUBLIC, admin)
    first_run = _index_attempt(db_session, first, 0, IndexingStatus.FAILED, mark)
    second_run = _index_attempt(db_session, second, 1, IndexingStatus.FAILED, mark)
    _index_attempt(db_session, third, 2, IndexingStatus.FAILED, mark)
    _index_attempt(db_session, third, 3, IndexingStatus.SUCCESS, mark)

    narrowed = _fleet(db_session, admin, mark, cc_pair_ids=[first.id, second.id])

    assert [(item.cc_pair.id, item.run.attempt.id) for item in narrowed.items] == [
        (second.id, second_run.id),
        (first.id, first_run.id),
    ]
    assert narrowed.total_items == 2
    assert narrowed.status_counts[CCPairRunStatusGroup.FAILED] == 2
    assert narrowed.status_counts[CCPairRunStatusGroup.SUCCEEDED] == 0

    # No pair filter means every readable pair.
    everything = _fleet(db_session, admin, mark)
    assert everything.total_items == 4


def test_fleet_resolve_marks_only_the_named_pairs_runs(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("feed_filters_admin", is_admin=True)
    mark = _mark()
    first = made.pair("Feed Filters Resolve First", AccessType.PUBLIC, admin)
    second = made.pair("Feed Filters Resolve Second", AccessType.PUBLIC, admin)
    third = made.pair("Feed Filters Resolve Third", AccessType.PUBLIC, admin)
    _index_attempt(db_session, first, 0, IndexingStatus.FAILED, mark)
    _index_attempt(db_session, second, 1, IndexingStatus.FAILED, mark)
    left_open = _index_attempt(db_session, third, 2, IndexingStatus.FAILED, mark)

    response = resolve_indexing_runs(
        request=CCPairRunsResolveMatchingRequest(
            q=mark,
            cc_pair_ids=[first.id, second.id],
        ),
        user=admin,
        db_session=db_session,
    )

    assert response.resolved_count == 2
    assert response.cc_pair_ids == sorted([first.id, second.id])
    still_open = _fleet(
        db_session,
        admin,
        mark,
        status_groups=[CCPairRunStatusGroup.FAILED],
        resolved=False,
    )
    assert [item.run.attempt.id for item in still_open.items] == [left_open.id]


def test_fleet_resolvable_count_counts_only_the_named_pairs(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("feed_filters_admin", is_admin=True)
    mark = _mark()
    first = made.pair("Feed Filters Count First", AccessType.PUBLIC, admin)
    second = made.pair("Feed Filters Count Second", AccessType.PUBLIC, admin)
    third = made.pair("Feed Filters Count Third", AccessType.PUBLIC, admin)
    _index_attempt(db_session, first, 0, IndexingStatus.FAILED, mark)
    _index_attempt(db_session, second, 1, IndexingStatus.FAILED, mark)
    _index_attempt(db_session, third, 2, IndexingStatus.FAILED, mark)

    assert _fleet_resolvable(db_session, admin, mark, [first.id, second.id]) == 2
    assert _fleet_resolvable(db_session, admin, mark, [third.id]) == 1


@pytest.fixture
def scoped_pairs(
    made: RunFeedRecords,
) -> tuple[User, ConnectorCredentialPair, ConnectorCredentialPair]:
    """A scoped user who operates their own private pair, and another owner's
    private pair the scoped user cannot read."""
    scoped = made.user("feed_filters_scoped")
    owner = made.user("feed_filters_owner")
    operated = made.pair("Feed Filters Operated", AccessType.PRIVATE, scoped)
    hidden = made.pair("Feed Filters Hidden", AccessType.PRIVATE, owner)
    return scoped, operated, hidden


def test_fleet_feed_drops_a_named_pair_the_caller_cannot_read(
    db_session: Session,
    scoped_pairs: tuple[User, ConnectorCredentialPair, ConnectorCredentialPair],
) -> None:
    scoped, operated, hidden = scoped_pairs
    mark = _mark()
    own_run = _index_attempt(db_session, operated, 0, IndexingStatus.FAILED, mark)
    _index_attempt(db_session, hidden, 1, IndexingStatus.FAILED, mark)

    mixed = _fleet(db_session, scoped, mark, cc_pair_ids=[operated.id, hidden.id])

    assert [(item.cc_pair.id, item.run.attempt.id) for item in mixed.items] == [
        (operated.id, own_run.id)
    ]
    assert mixed.total_items == 1

    unreadable_only = _fleet(db_session, scoped, mark, cc_pair_ids=[hidden.id])

    assert unreadable_only.items == []
    assert unreadable_only.total_items == 0
    assert all(count == 0 for count in unreadable_only.status_counts.values())


def test_fleet_resolve_and_count_ignore_a_named_pair_the_caller_cannot_read(
    db_session: Session,
    made: RunFeedRecords,
    scoped_pairs: tuple[User, ConnectorCredentialPair, ConnectorCredentialPair],
) -> None:
    scoped, operated, hidden = scoped_pairs
    admin = made.user("feed_filters_admin", is_admin=True)
    mark = _mark()
    own_run = _index_attempt(db_session, operated, 0, IndexingStatus.FAILED, mark)
    hidden_run = _index_attempt(db_session, hidden, 1, IndexingStatus.FAILED, mark)

    # An empty intersection resolves nothing, not every operated pair.
    response = resolve_indexing_runs(
        request=CCPairRunsResolveMatchingRequest(
            q=mark,
            cc_pair_ids=[hidden.id],
        ),
        user=scoped,
        db_session=db_session,
    )

    assert response.resolved_count == 0
    assert response.cc_pair_ids == []
    open_runs = _fleet(
        db_session,
        admin,
        mark,
        status_groups=[CCPairRunStatusGroup.FAILED],
        resolved=False,
    )
    assert {item.run.attempt.id for item in open_runs.items} == {
        own_run.id,
        hidden_run.id,
    }
    assert _fleet_resolvable(db_session, scoped, mark, [hidden.id]) == 0
    assert _fleet_resolvable(db_session, scoped, mark, [operated.id, hidden.id]) == 1


def test_a_queued_attempt_is_scheduled_not_running_on_both_feeds(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("feed_filters_admin", is_admin=True)
    mark = _mark()
    cc_pair = made.pair("Feed Filters Queued", AccessType.PUBLIC, admin)
    running = _index_attempt(db_session, cc_pair, 0, IndexingStatus.IN_PROGRESS, mark)
    queued = _index_attempt(db_session, cc_pair, 1, IndexingStatus.NOT_STARTED, mark)

    pair_feed = read_pair_feed(db_session, admin, cc_pair)

    assert pair_feed.status_counts[CCPairRunStatusGroup.SCHEDULED] == 1
    assert pair_feed.status_counts[CCPairRunStatusGroup.RUNNING] == 1

    fleet_feed = _fleet(db_session, admin, mark)

    assert fleet_feed.status_counts[CCPairRunStatusGroup.SCHEDULED] == 1
    assert fleet_feed.status_counts[CCPairRunStatusGroup.RUNNING] == 1

    scheduled_group = CCPairRunStatusGroup.SCHEDULED
    scheduled_only = read_pair_feed(
        db_session, admin, cc_pair, status_groups=[scheduled_group]
    )
    running_only = read_pair_feed(
        db_session, admin, cc_pair, status_groups=[CCPairRunStatusGroup.RUNNING]
    )
    fleet_scheduled = _fleet(db_session, admin, mark, status_groups=[scheduled_group])

    assert [run.attempt.id for run in scheduled_only.items] == [queued.id]
    assert scheduled_only.total_items == 1
    assert [run.attempt.id for run in running_only.items] == [running.id]
    assert [item.run.attempt.id for item in fleet_scheduled.items] == [queued.id]


def test_a_queued_attempt_older_than_the_window_is_still_listed(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("feed_filters_admin", is_admin=True)
    mark = _mark()
    cc_pair = made.pair("Feed Filters Old Queued", AccessType.PUBLIC, admin)
    _index_attempt(db_session, cc_pair, 0, IndexingStatus.SUCCESS, mark)
    queued = _index_attempt(db_session, cc_pair, 1, IndexingStatus.NOT_STARTED, mark)
    recent = _index_attempt(db_session, cc_pair, 20, IndexingStatus.FAILED, mark)

    response = read_pair_feed(
        db_session, admin, cc_pair, since=_T0 + timedelta(minutes=15)
    )

    assert response.status_counts[CCPairRunStatusGroup.SCHEDULED] == 1
    assert [run.attempt.id for run in response.items] == [recent.id, queued.id]
    assert response.status_counts[CCPairRunStatusGroup.SUCCEEDED] == 0


def test_a_queued_attempt_is_never_superseded_or_resolvable(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("feed_filters_admin", is_admin=True)
    mark = _mark()
    cc_pair = made.pair("Feed Filters Queued Supersede", AccessType.PUBLIC, admin)
    queued = _index_attempt(db_session, cc_pair, 0, IndexingStatus.NOT_STARTED, mark)
    _doc_error(db_session, queued, mark)
    _index_attempt(db_session, cc_pair, 10, IndexingStatus.SUCCESS, mark)

    feed = read_pair_feed(db_session, admin, cc_pair)

    assert feed.status_counts[CCPairRunStatusGroup.SCHEDULED] == 1
    queued_run = next(run for run in feed.items if run.attempt.id == queued.id)
    assert queued_run.superseded is False

    for level in (None, CCPairRunLevel.ERRORS, CCPairRunLevel.FAILURES):
        count = get_resolvable_cc_pair_runs_count(
            cc_pair_id=cc_pair.id,
            level=level,
            q=None,
            since=None,
            until=None,
            kinds=None,
            user=admin,
            db_session=db_session,
        ).count
        assert count == 0
    resolved = resolve_indexing_runs(
        request=CCPairRunsResolveMatchingRequest(q=mark),
        user=admin,
        db_session=db_session,
    )
    assert resolved.resolved_count == 0


def test_feed_json_carries_the_scheduled_count_and_is_retry(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("feed_filters_admin", is_admin=True)
    mark = _mark()
    cc_pair = made.pair("Feed Filters Shape", AccessType.PUBLIC, admin)
    _index_attempt(db_session, cc_pair, 0, IndexingStatus.SUCCESS, mark)

    body = read_pair_feed(db_session, admin, cc_pair).model_dump(mode="json")

    assert body["status_counts"].get(CCPairRunStatusGroup.SCHEDULED.value) == 0
    assert body["items"][0].get("is_retry") is False
