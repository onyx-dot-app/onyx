"""A targeted reindex attempt is a run on both feeds and the throughput chart,
marked `is_retry` and listed once per job, while the pair's own state skips it."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.cc_pair_runs import count_pairs_indexing
from onyx.db.enums import CCPairRunKind, CCPairRunStatusGroup, IndexingStatus
from onyx.server.documents.cc_pair import get_cc_pair_throughput
from onyx.server.documents.index_monitoring import (
    get_indexing_connectors,
    get_indexing_runs,
)
from onyx.server.documents.models import (
    CCPairIndexRun,
    CCPairRun,
    CCPairRunsResponse,
    CCPairThroughputWindow,
    IndexingConnectorStatus,
)
from tests.external_dependency_unit.indexing.run_feed_records import (
    RunFeedRecords,
    make_index_attempt,
    read_pair_feed,
    run_mark,
)
from tests.external_dependency_unit.indexing_helpers import make_future_search_settings

# The perm sync kinds come from the EE-only sync_params helpers.
pytestmark = pytest.mark.usefixtures("enable_ee")

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def made(db_session: Session) -> Generator[RunFeedRecords, None, None]:
    created = RunFeedRecords(db_session)
    yield created
    created.cleanup()


def _mark() -> str:
    return run_mark("retry-runs")


def _minutes(minutes: int) -> datetime:
    return _T0 + timedelta(minutes=minutes)


def _ids(response: CCPairRunsResponse) -> list[int]:
    return [run.attempt.id for run in response.items]


def _is_retry(run: CCPairRun) -> bool | None:
    return run.is_retry if isinstance(run, CCPairIndexRun) else None


def _is_retry_by_id(response: CCPairRunsResponse) -> dict[int, bool | None]:
    return {run.attempt.id: _is_retry(run) for run in response.items}


def test_a_retry_attempt_is_a_run_on_the_pair_and_fleet_feeds(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("retry_runs_admin", is_admin=True)
    mark = _mark()
    cc_pair = made.pair("Retry Runs Feeds")
    full = make_index_attempt(
        db_session, cc_pair, _minutes(0), IndexingStatus.FAILED, mark
    )
    retry = make_index_attempt(
        db_session, cc_pair, _minutes(10), IndexingStatus.FAILED, mark, made.job()
    )

    pair_feed = read_pair_feed(db_session, admin, cc_pair)

    assert _ids(pair_feed) == [retry.id, full.id]
    assert _is_retry_by_id(pair_feed) == {retry.id: True, full.id: False}
    assert pair_feed.total_items == 2
    assert pair_feed.status_counts[CCPairRunStatusGroup.FAILED] == 2

    fleet_feed = get_indexing_runs(
        page_num=0,
        page_size=10,
        since=None,
        until=None,
        kinds=None,
        status_groups=None,
        q=mark,
        errors=None,
        superseded=None,
        resolved=None,
        user=admin,
        db_session=db_session,
    )

    assert [
        (item.run.attempt.id, _is_retry(item.run)) for item in fleet_feed.items
    ] == [
        (retry.id, True),
        (full.id, False),
    ]
    assert fleet_feed.status_counts[CCPairRunStatusGroup.FAILED] == 2


def test_a_retry_attempt_honors_the_feed_filters(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("retry_runs_admin", is_admin=True)
    mark = _mark()
    cc_pair = made.pair("Retry Runs Filters")
    full = make_index_attempt(
        db_session, cc_pair, _minutes(0), IndexingStatus.SUCCESS, mark
    )
    retry = make_index_attempt(
        db_session, cc_pair, _minutes(10), IndexingStatus.FAILED, mark, made.job()
    )
    failed = [CCPairRunStatusGroup.FAILED]

    assert _ids(read_pair_feed(db_session, admin, cc_pair, status_groups=failed)) == [
        retry.id
    ]
    assert _ids(
        read_pair_feed(
            db_session, admin, cc_pair, kinds=[CCPairRunKind.INDEXING], q=mark
        )
    ) == [retry.id, full.id]
    assert _ids(read_pair_feed(db_session, admin, cc_pair, since=_minutes(5))) == [
        retry.id
    ]
    assert _ids(read_pair_feed(db_session, admin, cc_pair, until=_minutes(5))) == [
        full.id
    ]
    assert (
        _ids(
            read_pair_feed(
                db_session, admin, cc_pair, kinds=[CCPairRunKind.DOC_PERMISSION_SYNC]
            )
        )
        == []
    )
    assert _ids(read_pair_feed(db_session, admin, cc_pair, q=_mark())) == []
    succeeded = read_pair_feed(
        db_session, admin, cc_pair, status_groups=[CCPairRunStatusGroup.SUCCEEDED]
    )
    assert _ids(succeeded) == [full.id]
    # The counts ignore the status filter and include the retry.
    assert succeeded.status_counts[CCPairRunStatusGroup.FAILED] == 1


def test_throughput_lists_a_retry_run(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("retry_runs_admin", is_admin=True)
    mark = _mark()
    cc_pair = made.pair("Retry Runs Throughput")
    now = datetime.now(timezone.utc)
    full = make_index_attempt(
        db_session, cc_pair, now - timedelta(hours=3), IndexingStatus.SUCCESS, mark
    )
    retry = make_index_attempt(
        db_session,
        cc_pair,
        now - timedelta(hours=2),
        IndexingStatus.SUCCESS,
        mark,
        made.job(),
    )
    for attempt in (full, retry):
        attempt.time_finished = attempt.time_created + timedelta(minutes=30)
    db_session.commit()

    response = get_cc_pair_throughput(
        cc_pair_id=cc_pair.id,
        window=CCPairThroughputWindow.HOURS_24,
        user=admin,
        db_session=db_session,
    )

    assert [run.started for run in response.runs] == [
        full.time_started,
        retry.time_started,
    ]


def test_a_running_retry_leaves_the_indexing_count_and_bucket_alone(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("retry_runs_admin", is_admin=True)
    mark = _mark()
    name = f"Retry Runs Bucket {uuid4().hex}"
    cc_pair = made.pair(name)
    full = make_index_attempt(
        db_session, cc_pair, _minutes(0), IndexingStatus.SUCCESS, mark
    )
    retry = make_index_attempt(
        db_session, cc_pair, _minutes(10), IndexingStatus.IN_PROGRESS, mark, made.job()
    )

    feed = read_pair_feed(db_session, admin, cc_pair)

    # The retry is listed and counted as running in the feed.
    assert _ids(feed) == [retry.id, full.id]
    assert feed.status_counts[CCPairRunStatusGroup.RUNNING] == 1

    # It is not the pair's own run: the overview, bucket and latest attempt skip it.
    assert count_pairs_indexing(db_session, [cc_pair.id]) == 0
    rows = get_indexing_connectors(
        page_num=0,
        page_size=20,
        q=name,
        status=None,
        user=admin,
        db_session=db_session,
    ).items
    assert [row.cc_pair_id for row in rows] == [cc_pair.id]
    assert rows[0].status == IndexingConnectorStatus.INDEXED
    latest = rows[0].latest_index_attempt
    assert latest is not None
    assert latest.id == full.id


def test_a_retry_during_a_model_switch_is_listed_once(
    db_session: Session, made: RunFeedRecords
) -> None:
    admin = made.user("retry_runs_admin", is_admin=True)
    mark = _mark()
    cc_pair = made.pair("Retry Runs Model Switch")
    future = make_future_search_settings(db_session)
    made.settings_ids.append(future.id)
    job = made.job()
    # The job makes one attempt per active search settings.
    current_retry = make_index_attempt(
        db_session, cc_pair, _minutes(0), IndexingStatus.FAILED, mark, job
    )
    make_index_attempt(
        db_session,
        cc_pair,
        _minutes(0),
        IndexingStatus.FAILED,
        mark,
        job,
        search_settings_id=future.id,
    )

    feed = read_pair_feed(db_session, admin, cc_pair)

    assert len(feed.items) == 1
    assert feed.items[0].attempt.id == current_retry.id
    assert _is_retry_by_id(feed) == {feed.items[0].attempt.id: True}
    assert feed.total_items == 1
    assert feed.status_counts[CCPairRunStatusGroup.FAILED] == 1
