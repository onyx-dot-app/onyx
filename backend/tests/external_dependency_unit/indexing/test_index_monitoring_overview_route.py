"""Coverage for the indexing status page's overview: a pair mid-run counts as
indexing, backfills included, a paused pair is not active, the window's
documents come from the runs inside it, and a reader sees only the pairs they
can read. The database holds other pairs, so every figure is read against the
overview from before the pairs were created, with the clock frozen so no other
run crosses the window's edge between the two reads."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.connector_credential_pair import (
    CCPairAccessLevel,
    get_connector_credential_pairs_for_user,
)
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    IndexingStatus,
)
from onyx.db.models import Connector, ConnectorCredentialPair, Credential, IndexAttempt
from onyx.db.search_settings import get_current_search_settings
from onyx.server.documents import cc_pair_throughput
from onyx.server.documents.index_monitoring import get_indexing_overview
from onyx.server.documents.models import CCPairThroughputWindow
from tests.external_dependency_unit.conftest import create_test_user


@contextmanager
def _clock_at(now: datetime) -> Iterator[None]:
    """Pins the window's end, so the two overview reads see the same hour."""
    with patch.object(cc_pair_throughput, "datetime", wraps=datetime) as frozen:
        frozen.now.return_value = now
        yield


def _create_cc_pair(
    db_session: Session,
    status: ConnectorCredentialPairStatus = ConnectorCredentialPairStatus.ACTIVE,
    access_type: AccessType = AccessType.PUBLIC,
) -> ConnectorCredentialPair:
    owner = create_test_user(db_session, "overview_owner")
    connector = Connector(
        name="Overview Test Connector",
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
        name="Overview Test Pair",
        status=status,
        access_type=access_type,
    )
    db_session.add(cc_pair)
    db_session.commit()
    return cc_pair


def _index_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    status: IndexingStatus,
    started: datetime,
    finished: datetime | None,
    docs: int,
    is_backfill: bool = False,
) -> IndexAttempt:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=status,
        time_started=started,
        time_finished=finished,
        total_docs_indexed=docs,
        is_backfill=is_backfill,
    )
    db_session.add(attempt)
    db_session.flush()
    attempt.time_created = started
    db_session.commit()
    return attempt


def test_overview_counts_the_readable_pairs_and_the_window(
    db_session: Session,
) -> None:
    admin = create_test_user(db_session, "overview_admin", is_admin=True)
    now = datetime.now(timezone.utc)
    with _clock_at(now):
        before = get_indexing_overview(
            window=CCPairThroughputWindow.HOURS_1, user=admin, db_session=db_session
        )
    running = _create_cc_pair(db_session)
    backfilling = _create_cc_pair(db_session)
    finished = _create_cc_pair(db_session)
    paused = _create_cc_pair(db_session, ConnectorCredentialPairStatus.PAUSED)
    _index_attempt(
        db_session,
        running,
        IndexingStatus.IN_PROGRESS,
        now - timedelta(minutes=30),
        None,
        30,
    )
    # A backfill is the pair's only run, and it indexes like any other.
    _index_attempt(
        db_session,
        backfilling,
        IndexingStatus.IN_PROGRESS,
        now - timedelta(minutes=30),
        None,
        10,
        is_backfill=True,
    )
    _index_attempt(
        db_session,
        finished,
        IndexingStatus.SUCCESS,
        now - timedelta(minutes=20),
        now - timedelta(minutes=10),
        50,
    )
    # Finished a day ago, so it adds nothing to the window.
    _index_attempt(
        db_session,
        paused,
        IndexingStatus.SUCCESS,
        now - timedelta(days=1, hours=1),
        now - timedelta(days=1),
        500,
    )

    with _clock_at(now):
        response = get_indexing_overview(
            window=CCPairThroughputWindow.HOURS_1, user=admin, db_session=db_session
        )

    assert response.indexing_connectors == before.indexing_connectors + 2
    assert response.active_connectors == before.active_connectors + 3
    assert response.recent_docs_indexed == before.recent_docs_indexed + 90
    # The new pairs hold no documents.
    assert response.total_docs_indexed == before.total_docs_indexed
    assert sum(response.throughput.docs_indexed) == response.recent_docs_indexed
    assert len(response.throughput.runs) == len(before.throughput.runs) + 3


def test_a_reader_sees_only_the_pairs_they_can_read(db_session: Session) -> None:
    reader = create_test_user(db_session, "overview_reader")
    now = datetime.now(timezone.utc)
    with _clock_at(now):
        before = get_indexing_overview(
            window=CCPairThroughputWindow.HOURS_1, user=reader, db_session=db_session
        )
    public = _create_cc_pair(db_session)
    private = _create_cc_pair(db_session, access_type=AccessType.PRIVATE)
    started = now - timedelta(minutes=10)
    finished = now - timedelta(minutes=5)
    _index_attempt(db_session, public, IndexingStatus.SUCCESS, started, finished, 5)
    _index_attempt(db_session, private, IndexingStatus.SUCCESS, started, finished, 500)
    readable = {
        cc_pair.id
        for cc_pair in get_connector_credential_pairs_for_user(
            db_session, reader, CCPairAccessLevel.READ
        )
    }
    assert public.id in readable
    assert private.id not in readable

    with _clock_at(now):
        response = get_indexing_overview(
            window=CCPairThroughputWindow.HOURS_1, user=reader, db_session=db_session
        )

    assert response.active_connectors == before.active_connectors + 1
    assert response.recent_docs_indexed == before.recent_docs_indexed + 5
    assert len(response.throughput.runs) == len(before.throughput.runs) + 1
