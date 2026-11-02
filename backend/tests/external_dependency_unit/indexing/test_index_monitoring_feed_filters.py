"""Coverage for the fleet feed's pair filter and the queued group: `cc_pair_ids`
narrows the fleet feed, its resolvable count and its batch resolve to the named
pairs the caller can read, and a queued (NOT_STARTED) index attempt sits in the
`scheduled` group on both feeds, stays in every window, is never superseded and
never resolvable."""

from collections.abc import Generator, Mapping
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import (
    AccessType,
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
    User,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.server.documents.cc_pair import (
    get_cc_pair_runs,
    get_resolvable_cc_pair_runs_count,
)
from onyx.server.documents.index_monitoring import (
    get_indexing_runs,
    get_resolvable_indexing_runs_count,
    resolve_indexing_runs,
)
from onyx.server.documents.models import (
    CCPairRunLevel,
    CCPairRunsResolveMatchingRequest,
    CCPairRunsResponse,
    IndexingRunsResponse,
)
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair

# The perm sync kinds come from the EE-only sync_params helpers.
pytestmark = pytest.mark.usefixtures("enable_ee")

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_SCHEDULED = "scheduled"


def _mark() -> str:
    """Earlier runs leave rows behind, so each test marks its runs and searches by it."""
    return f"feed-filters-{uuid4().hex}"


def _group_count(counts: Mapping[CCPairRunStatusGroup, int], name: str) -> int | None:
    return next((count for group, count in counts.items() if group.value == name), None)


class _Pairs:
    """Creates pairs and tears down them, their attempts and their owners."""

    def __init__(self, db_session: Session) -> None:
        self.db_session = db_session
        self.pairs: list[ConnectorCredentialPair] = []
        self.users: list[User] = []

    def user(self, prefix: str, is_admin: bool = False) -> User:
        user = create_test_user(self.db_session, prefix, is_admin=is_admin)
        self.users.append(user)
        return user

    def pair(
        self, name: str, access_type: AccessType, creator: User
    ) -> ConnectorCredentialPair:
        connector = Connector(
            name="Feed Filters Connector",
            source=DocumentSource.GOOGLE_DRIVE,
            input_type=InputType.POLL,
            connector_specific_config={},
            refresh_freq=None,
        )
        self.db_session.add(connector)
        self.db_session.flush()
        credential = Credential(
            credential_json={}, user_id=creator.id, admin_public=True
        )
        self.db_session.add(credential)
        self.db_session.flush()
        pair = ConnectorCredentialPair(
            connector_id=connector.id,
            credential_id=credential.id,
            name=name,
            status=ConnectorCredentialPairStatus.ACTIVE,
            access_type=access_type,
            creator_id=creator.id,
        )
        self.db_session.add(pair)
        self.db_session.commit()
        self.pairs.append(pair)
        return pair

    def cleanup(self) -> None:
        self.db_session.rollback()
        for pair in self.pairs:
            # IndexAttemptError has no FK cascade, so its rows go first.
            for model in (IndexAttemptError, IndexAttempt):
                self.db_session.query(model).filter(
                    model.connector_credential_pair_id == pair.id
                ).delete(synchronize_session="fetch")
            self.db_session.commit()
            cleanup_cc_pair(self.db_session, pair)
        for user in self.users:
            delete_test_user(self.db_session, user)
        self.db_session.commit()


@pytest.fixture
def made(db_session: Session) -> Generator[_Pairs, None, None]:
    pairs = _Pairs(db_session)
    yield pairs
    pairs.cleanup()


def _index_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    minutes: int,
    status: IndexingStatus,
    mark: str,
) -> IndexAttempt:
    queued = status == IndexingStatus.NOT_STARTED
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=status,
        error_msg=mark,
        time_started=None if queued else _T0 + timedelta(minutes=minutes),
    )
    db_session.add(attempt)
    db_session.flush()
    attempt.time_created = _T0 + timedelta(minutes=minutes)
    db_session.commit()
    return attempt


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


def _pair_feed(
    db_session: Session,
    user: User,
    cc_pair: ConnectorCredentialPair,
    since: datetime | None = None,
    status_groups: list[CCPairRunStatusGroup] | None = None,
) -> CCPairRunsResponse:
    return get_cc_pair_runs(
        cc_pair_id=cc_pair.id,
        page_num=0,
        page_size=10,
        since=since,
        until=None,
        kinds=None,
        status_groups=status_groups,
        q=None,
        errors=None,
        superseded=None,
        resolved=None,
        user=user,
        db_session=db_session,
    )


def test_ac1_fleet_feed_lists_and_counts_only_the_named_pairs(
    db_session: Session, made: _Pairs
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


def test_ac1_fleet_resolve_marks_only_the_named_pairs_runs(
    db_session: Session, made: _Pairs
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


def test_ac1_fleet_resolvable_count_counts_only_the_named_pairs(
    db_session: Session, made: _Pairs
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
    made: _Pairs,
) -> tuple[User, ConnectorCredentialPair, ConnectorCredentialPair]:
    """A scoped user who operates their own private pair, and another owner's
    private pair the scoped user cannot read."""
    scoped = made.user("feed_filters_scoped")
    owner = made.user("feed_filters_owner")
    operated = made.pair("Feed Filters Operated", AccessType.PRIVATE, scoped)
    hidden = made.pair("Feed Filters Hidden", AccessType.PRIVATE, owner)
    return scoped, operated, hidden


def test_ac2_fleet_feed_drops_a_named_pair_the_caller_cannot_read(
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


def test_ac2_fleet_resolve_and_count_ignore_a_named_pair_the_caller_cannot_read(
    db_session: Session,
    made: _Pairs,
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


def test_ac3_a_queued_attempt_is_scheduled_not_running_on_both_feeds(
    db_session: Session, made: _Pairs
) -> None:
    admin = made.user("feed_filters_admin", is_admin=True)
    mark = _mark()
    cc_pair = made.pair("Feed Filters Queued", AccessType.PUBLIC, admin)
    running = _index_attempt(db_session, cc_pair, 0, IndexingStatus.IN_PROGRESS, mark)
    queued = _index_attempt(db_session, cc_pair, 1, IndexingStatus.NOT_STARTED, mark)

    pair_feed = _pair_feed(db_session, admin, cc_pair)

    assert _group_count(pair_feed.status_counts, _SCHEDULED) == 1
    assert pair_feed.status_counts[CCPairRunStatusGroup.RUNNING] == 1

    fleet_feed = _fleet(db_session, admin, mark)

    assert _group_count(fleet_feed.status_counts, _SCHEDULED) == 1
    assert fleet_feed.status_counts[CCPairRunStatusGroup.RUNNING] == 1

    scheduled_group = CCPairRunStatusGroup(_SCHEDULED)
    scheduled_only = _pair_feed(
        db_session, admin, cc_pair, status_groups=[scheduled_group]
    )
    running_only = _pair_feed(
        db_session, admin, cc_pair, status_groups=[CCPairRunStatusGroup.RUNNING]
    )
    fleet_scheduled = _fleet(db_session, admin, mark, status_groups=[scheduled_group])

    assert [run.attempt.id for run in scheduled_only.items] == [queued.id]
    assert scheduled_only.total_items == 1
    assert [run.attempt.id for run in running_only.items] == [running.id]
    assert [item.run.attempt.id for item in fleet_scheduled.items] == [queued.id]


def test_ac4_a_queued_attempt_older_than_the_window_is_still_listed(
    db_session: Session, made: _Pairs
) -> None:
    admin = made.user("feed_filters_admin", is_admin=True)
    mark = _mark()
    cc_pair = made.pair("Feed Filters Old Queued", AccessType.PUBLIC, admin)
    _index_attempt(db_session, cc_pair, 0, IndexingStatus.SUCCESS, mark)
    queued = _index_attempt(db_session, cc_pair, 1, IndexingStatus.NOT_STARTED, mark)
    recent = _index_attempt(db_session, cc_pair, 20, IndexingStatus.FAILED, mark)

    response = _pair_feed(db_session, admin, cc_pair, since=_T0 + timedelta(minutes=15))

    assert _group_count(response.status_counts, _SCHEDULED) == 1
    assert [run.attempt.id for run in response.items] == [recent.id, queued.id]
    assert response.status_counts[CCPairRunStatusGroup.SUCCEEDED] == 0


def test_ac5_a_queued_attempt_is_never_superseded_or_resolvable(
    db_session: Session, made: _Pairs
) -> None:
    admin = made.user("feed_filters_admin", is_admin=True)
    mark = _mark()
    cc_pair = made.pair("Feed Filters Queued Supersede", AccessType.PUBLIC, admin)
    queued = _index_attempt(db_session, cc_pair, 0, IndexingStatus.NOT_STARTED, mark)
    _doc_error(db_session, queued, mark)
    _index_attempt(db_session, cc_pair, 10, IndexingStatus.SUCCESS, mark)

    feed = _pair_feed(db_session, admin, cc_pair)

    assert _group_count(feed.status_counts, _SCHEDULED) == 1
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


def test_ac9_feed_json_carries_the_scheduled_count_and_is_retry(
    db_session: Session, made: _Pairs
) -> None:
    admin = made.user("feed_filters_admin", is_admin=True)
    mark = _mark()
    cc_pair = made.pair("Feed Filters Shape", AccessType.PUBLIC, admin)
    _index_attempt(db_session, cc_pair, 0, IndexingStatus.SUCCESS, mark)

    body = _pair_feed(db_session, admin, cc_pair).model_dump(mode="json")

    assert body["status_counts"].get(_SCHEDULED) == 0
    assert body["items"][0].get("is_retry") is False
