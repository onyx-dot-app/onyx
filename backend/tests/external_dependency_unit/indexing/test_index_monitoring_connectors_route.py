"""Coverage for the indexing status page's connector list: a pair's bucket
follows its own state before its latest attempt, the list sorts by bucket then
name, the search narrows the list and the counts while the status filter
narrows only the list, and a queued attempt knows its place in line."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    IndexingStatus,
)
from onyx.db.models import Connector, ConnectorCredentialPair, Credential, IndexAttempt
from onyx.db.search_settings import get_current_search_settings
from onyx.server.documents.index_monitoring import get_indexing_connectors
from onyx.server.documents.models import (
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
) -> ConnectorCredentialPair:
    owner = create_test_user(db_session, "monitor_list_owner")
    connector = Connector(
        name=f"{prefix} Connector",
        source=DocumentSource.GOOGLE_DRIVE,
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
        access_type=AccessType.PUBLIC,
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


def test_pairs_sort_by_bucket_then_name_and_the_filter_keeps_the_counts(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    prefix = _prefix()
    indexed_b = _create_cc_pair(db_session, prefix, "b indexed")
    indexed_a = _create_cc_pair(db_session, prefix, "a indexed")
    indexing = _create_cc_pair(db_session, prefix, "indexing")
    paused = _create_cc_pair(
        db_session, prefix, "paused", ConnectorCredentialPairStatus.PAUSED
    )
    erroring = _create_cc_pair(
        db_session, prefix, "erroring", in_repeated_error_state=True
    )
    fresh = _create_cc_pair(db_session, prefix, "fresh")
    canceled = _create_cc_pair(db_session, prefix, "canceled")
    _index_attempt(db_session, indexed_b, IndexingStatus.SUCCESS, now)
    _index_attempt(db_session, indexed_a, IndexingStatus.COMPLETED_WITH_ERRORS, now)
    _index_attempt(db_session, indexing, IndexingStatus.IN_PROGRESS, now)
    # A paused pair's attempt does not pull it out of the paused bucket.
    _index_attempt(db_session, paused, IndexingStatus.SUCCESS, now)
    _index_attempt(db_session, erroring, IndexingStatus.SUCCESS, now)
    # A canceled run never completed, so the pair waits for its next run.
    _index_attempt(db_session, canceled, IndexingStatus.CANCELED, now)

    response = _connectors(db_session, prefix)

    assert [row.name for row in response.items] == [
        indexing.name,
        erroring.name,
        paused.name,
        canceled.name,
        fresh.name,
        indexed_a.name,
        indexed_b.name,
    ]
    assert response.total_items == 7
    assert response.status_counts == {
        IndexingConnectorStatus.INDEXING: 1,
        IndexingConnectorStatus.FAILED: 1,
        IndexingConnectorStatus.PAUSED: 1,
        IndexingConnectorStatus.SCHEDULED: 2,
        IndexingConnectorStatus.INDEXED: 2,
    }
    by_name = {row.name: row for row in response.items}
    assert by_name[fresh.name].latest_index_attempt is None
    assert by_name[canceled.name].queue_position is None
    assert by_name[indexed_a.name].latest_index_attempt is not None
    assert by_name[indexed_a.name].creator_email is not None
    assert by_name[indexed_a.name].permissions["operate"] is True

    filtered = _connectors(db_session, prefix, status=IndexingConnectorStatus.INDEXED)

    assert [row.name for row in filtered.items] == [indexed_a.name, indexed_b.name]
    assert filtered.total_items == 2
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
