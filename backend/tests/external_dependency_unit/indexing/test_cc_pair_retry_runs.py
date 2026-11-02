"""Coverage for retry runs: a targeted reindex attempt is a run on the pair feed,
the fleet feed and the throughput chart, marked `is_retry`, filtered and counted
like any index run and listed once during a model switch, while the pair's
indexing count, bucket and latest attempt still come from its full runs."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.cc_pair_runs import count_pairs_indexing
from onyx.db.enums import (
    AccessType,
    CCPairRunKind,
    CCPairRunStatusGroup,
    ConnectorCredentialPairStatus,
    IndexingStatus,
)
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    IndexAttempt,
    IndexAttemptError,
    SearchSettings,
    TargetedReindexJob,
    User,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.server.documents.cc_pair import get_cc_pair_runs, get_cc_pair_throughput
from onyx.server.documents.index_monitoring import (
    get_indexing_connectors,
    get_indexing_runs,
)
from onyx.server.documents.models import (
    CCPairRunsResponse,
    CCPairThroughputWindow,
    IndexingConnectorStatus,
)
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_future_search_settings,
)

# The perm sync kinds come from the EE-only sync_params helpers.
pytestmark = pytest.mark.usefixtures("enable_ee")

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _mark() -> str:
    return f"retry-runs-{uuid4().hex}"


class _Made:
    """What a test creates, torn down in FK order."""

    def __init__(self, db_session: Session) -> None:
        self.db_session = db_session
        self.pairs: list[ConnectorCredentialPair] = []
        self.job_ids: list[int] = []
        self.settings_ids: list[int] = []
        self.users: list[User] = []

    def admin(self) -> User:
        user = create_test_user(self.db_session, "retry_runs_admin", is_admin=True)
        self.users.append(user)
        return user

    def pair(self, name: str) -> ConnectorCredentialPair:
        connector = Connector(
            name="Retry Runs Connector",
            source=DocumentSource.GOOGLE_DRIVE,
            input_type=InputType.POLL,
            connector_specific_config={},
            refresh_freq=None,
        )
        self.db_session.add(connector)
        self.db_session.flush()
        credential = Credential(credential_json={}, user_id=None, admin_public=True)
        self.db_session.add(credential)
        self.db_session.flush()
        pair = ConnectorCredentialPair(
            connector_id=connector.id,
            credential_id=credential.id,
            name=name,
            status=ConnectorCredentialPairStatus.ACTIVE,
            access_type=AccessType.PUBLIC,
        )
        self.db_session.add(pair)
        self.db_session.commit()
        self.pairs.append(pair)
        return pair

    def job(self) -> TargetedReindexJob:
        job = TargetedReindexJob()
        self.db_session.add(job)
        self.db_session.commit()
        self.job_ids.append(job.id)
        return job

    def cleanup(self) -> None:
        self.db_session.rollback()
        for pair in self.pairs:
            for model in (IndexAttemptError, IndexAttempt):
                self.db_session.query(model).filter(
                    model.connector_credential_pair_id == pair.id
                ).delete(synchronize_session="fetch")
        self.db_session.query(TargetedReindexJob).filter(
            TargetedReindexJob.id.in_(self.job_ids)
        ).delete(synchronize_session="fetch")
        self.db_session.commit()
        for settings_id in self.settings_ids:
            self.db_session.query(SearchSettings).filter(
                SearchSettings.id == settings_id
            ).delete(synchronize_session="fetch")
        self.db_session.commit()
        for pair in self.pairs:
            cleanup_cc_pair(self.db_session, pair)
        for user in self.users:
            delete_test_user(self.db_session, user)
        self.db_session.commit()


@pytest.fixture
def made(db_session: Session) -> Generator[_Made, None, None]:
    created = _Made(db_session)
    yield created
    created.cleanup()


def _attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    created: datetime,
    status: IndexingStatus,
    mark: str,
    job: TargetedReindexJob | None = None,
    search_settings_id: int | None = None,
) -> IndexAttempt:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=(
            search_settings_id or get_current_search_settings(db_session).id
        ),
        from_beginning=False,
        status=status,
        error_msg=mark,
        targeted_reindex_job_id=None if job is None else job.id,
        time_started=created,
    )
    db_session.add(attempt)
    db_session.flush()
    attempt.time_created = created
    db_session.commit()
    return attempt


def _minutes(minutes: int) -> datetime:
    return _T0 + timedelta(minutes=minutes)


def _pair_feed(
    db_session: Session,
    user: User,
    cc_pair: ConnectorCredentialPair,
    since: datetime | None = None,
    until: datetime | None = None,
    kinds: list[CCPairRunKind] | None = None,
    status_groups: list[CCPairRunStatusGroup] | None = None,
    q: str | None = None,
) -> CCPairRunsResponse:
    return get_cc_pair_runs(
        cc_pair_id=cc_pair.id,
        page_num=0,
        page_size=10,
        since=since,
        until=until,
        kinds=kinds,
        status_groups=status_groups,
        q=q,
        errors=None,
        superseded=None,
        resolved=None,
        user=user,
        db_session=db_session,
    )


def _ids(response: CCPairRunsResponse) -> list[int]:
    return [run.attempt.id for run in response.items]


def _is_retry_by_id(response: CCPairRunsResponse) -> dict[int, object]:
    return {
        run.attempt.id: run.model_dump(mode="json").get("is_retry")
        for run in response.items
    }


def test_ac6_a_retry_attempt_is_a_run_on_the_pair_and_fleet_feeds(
    db_session: Session, made: _Made
) -> None:
    admin = made.admin()
    mark = _mark()
    cc_pair = made.pair("Retry Runs Feeds")
    full = _attempt(db_session, cc_pair, _minutes(0), IndexingStatus.FAILED, mark)
    retry = _attempt(
        db_session, cc_pair, _minutes(10), IndexingStatus.FAILED, mark, made.job()
    )

    pair_feed = _pair_feed(db_session, admin, cc_pair)

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
        (item.run.attempt.id, item.run.model_dump(mode="json").get("is_retry"))
        for item in fleet_feed.items
    ] == [(retry.id, True), (full.id, False)]
    assert fleet_feed.status_counts[CCPairRunStatusGroup.FAILED] == 2


def test_ac6_a_retry_attempt_honors_the_feed_filters(
    db_session: Session, made: _Made
) -> None:
    admin = made.admin()
    mark = _mark()
    cc_pair = made.pair("Retry Runs Filters")
    full = _attempt(db_session, cc_pair, _minutes(0), IndexingStatus.SUCCESS, mark)
    retry = _attempt(
        db_session, cc_pair, _minutes(10), IndexingStatus.FAILED, mark, made.job()
    )
    failed = [CCPairRunStatusGroup.FAILED]

    assert _ids(_pair_feed(db_session, admin, cc_pair, status_groups=failed)) == [
        retry.id
    ]
    assert _ids(
        _pair_feed(db_session, admin, cc_pair, kinds=[CCPairRunKind.INDEXING], q=mark)
    ) == [retry.id, full.id]
    assert _ids(_pair_feed(db_session, admin, cc_pair, since=_minutes(5))) == [retry.id]
    assert _ids(_pair_feed(db_session, admin, cc_pair, until=_minutes(5))) == [full.id]
    assert (
        _ids(
            _pair_feed(
                db_session, admin, cc_pair, kinds=[CCPairRunKind.DOC_PERMISSION_SYNC]
            )
        )
        == []
    )
    assert _ids(_pair_feed(db_session, admin, cc_pair, q=_mark())) == []
    succeeded = _pair_feed(
        db_session, admin, cc_pair, status_groups=[CCPairRunStatusGroup.SUCCEEDED]
    )
    assert _ids(succeeded) == [full.id]
    # The counts ignore the status filter and include the retry.
    assert succeeded.status_counts[CCPairRunStatusGroup.FAILED] == 1


def test_ac6_throughput_lists_a_retry_run(db_session: Session, made: _Made) -> None:
    admin = made.admin()
    mark = _mark()
    cc_pair = made.pair("Retry Runs Throughput")
    now = datetime.now(timezone.utc)
    full = _attempt(
        db_session, cc_pair, now - timedelta(hours=3), IndexingStatus.SUCCESS, mark
    )
    retry = _attempt(
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


def test_ac8_a_running_retry_leaves_the_indexing_count_and_bucket_alone(
    db_session: Session, made: _Made
) -> None:
    admin = made.admin()
    mark = _mark()
    name = f"Retry Runs Bucket {uuid4().hex}"
    cc_pair = made.pair(name)
    full = _attempt(db_session, cc_pair, _minutes(0), IndexingStatus.SUCCESS, mark)
    retry = _attempt(
        db_session, cc_pair, _minutes(10), IndexingStatus.IN_PROGRESS, mark, made.job()
    )

    feed = _pair_feed(db_session, admin, cc_pair)

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
    db_session: Session, made: _Made
) -> None:
    admin = made.admin()
    mark = _mark()
    cc_pair = made.pair("Retry Runs Model Switch")
    future = make_future_search_settings(db_session)
    made.settings_ids.append(future.id)
    job = made.job()
    # The job makes one attempt per active search settings.
    current_retry = _attempt(
        db_session, cc_pair, _minutes(0), IndexingStatus.FAILED, mark, job
    )
    future_retry = _attempt(
        db_session,
        cc_pair,
        _minutes(0),
        IndexingStatus.FAILED,
        mark,
        job,
        search_settings_id=future.id,
    )

    feed = _pair_feed(db_session, admin, cc_pair)

    assert len(feed.items) == 1
    assert feed.items[0].attempt.id in {current_retry.id, future_retry.id}
    assert _is_retry_by_id(feed) == {feed.items[0].attempt.id: True}
    assert feed.total_items == 1
    assert feed.status_counts[CCPairRunStatusGroup.FAILED] == 1
