"""Coverage for a pair's throughput with a client bin count: the query takes 12
to 84 bins on the pair and fleet routes, each slice names the runs in it by
attempt id with their status and whether an admin resolved them, a slice with
no run is empty, and an old client without ``bins`` keeps today's shape. The
clock is frozen off a bin boundary, so the window's end rounds up to one."""

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.cc_pair_run_resolution import resolve_runs__no_commit
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import (
    AccessType,
    CCPairRunKind,
    ConnectorCredentialPairStatus,
    IndexingStatus,
)
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    IndexAttempt,
    User,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server.documents import cc_pair_throughput
from onyx.server.documents.cc_pair import get_cc_pair_throughput
from onyx.server.documents.cc_pair import router as cc_pair_router
from onyx.server.documents.index_monitoring import router as index_monitoring_router
from onyx.server.documents.models import CCPairThroughputWindow
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_WIDTH = timedelta(minutes=30)


@contextmanager
def _clock_at(now: datetime) -> Iterator[None]:
    with patch.object(cc_pair_throughput, "datetime", wraps=datetime) as frozen:
        frozen.now.return_value = now
        yield


def _now_off_boundary() -> datetime:
    # 17 seconds past a minute is never on a 30-minute boundary.
    return datetime.now(timezone.utc).replace(second=17, microsecond=0)


def _next_boundary(moment: datetime, width: timedelta) -> datetime:
    return _EPOCH + width * -(-(moment - _EPOCH) // width)


@pytest.fixture
def admin(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "throughput_bins_admin", is_admin=True)
    yield user
    db_session.rollback()
    delete_test_user(db_session, user)
    db_session.commit()


@pytest.fixture
def cc_pair(db_session: Session) -> Generator[ConnectorCredentialPair, None, None]:
    owner = create_test_user(db_session, "throughput_bins_owner")
    connector = Connector(
        name="Throughput Bins Connector",
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
    pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name="Throughput Bins Pair",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
    )
    db_session.add(pair)
    db_session.commit()
    yield pair
    db_session.rollback()
    db_session.query(IndexAttempt).filter(
        IndexAttempt.connector_credential_pair_id == pair.id
    ).delete(synchronize_session="fetch")
    db_session.commit()
    cleanup_cc_pair(db_session, pair)
    delete_test_user(db_session, owner)
    db_session.commit()


@pytest.fixture
def client(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    admin: User,
) -> Generator[TestClient, None, None]:
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(cc_pair_router)
    app.include_router(index_monitoring_router)
    app.dependency_overrides[current_user] = lambda: admin

    def override_get_session() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _index_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    status: IndexingStatus,
    started: datetime,
    finished: datetime | None,
    docs: int = 0,
) -> IndexAttempt:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=status,
        time_started=started,
        time_finished=finished,
        total_docs_indexed=docs,
    )
    db_session.add(attempt)
    db_session.flush()
    attempt.time_created = started
    db_session.commit()
    return attempt


@pytest.mark.parametrize("bins", [11, 85])
def test_ac1_bins_outside_12_to_84_is_refused(
    client: TestClient, cc_pair: ConnectorCredentialPair, bins: int
) -> None:
    pair = client.get(
        f"/manage/admin/cc-pair/{cc_pair.id}/throughput",
        params={"window": "24h", "bins": bins},
    )
    fleet = client.get(
        "/manage/admin/index-monitoring/overview",
        params={"window": "24h", "bins": bins},
    )

    assert pair.status_code == 422
    assert fleet.status_code == 422


@pytest.mark.parametrize("bins", [12, 84])
def test_ac1_bins_at_the_edges_of_the_range_sets_the_slice_count(
    client: TestClient, cc_pair: ConnectorCredentialPair, bins: int
) -> None:
    pair = client.get(
        f"/manage/admin/cc-pair/{cc_pair.id}/throughput",
        params={"window": "24h", "bins": bins},
    )
    fleet = client.get(
        "/manage/admin/index-monitoring/overview",
        params={"window": "24h", "bins": bins},
    )

    assert pair.status_code == 200
    assert len(pair.json()["docs_indexed"]) == bins
    assert len(pair.json()["slices"]) == bins
    assert fleet.status_code == 200
    assert len(fleet.json()["throughput"]["slices"]) == bins


def test_ac3_ac5_each_slice_names_its_runs_and_an_empty_slice_is_empty(
    db_session: Session, admin: User, cc_pair: ConnectorCredentialPair
) -> None:
    now = _now_off_boundary()
    window_end = _next_boundary(now, _WIDTH)
    window_start = window_end - timedelta(hours=24)

    def in_slice(index: int, minutes: int) -> datetime:
        return window_start + _WIDTH * index + timedelta(minutes=minutes)

    resolved_failure = _index_attempt(
        db_session, cc_pair, IndexingStatus.FAILED, in_slice(10, 5), in_slice(10, 20)
    )
    open_failure = _index_attempt(
        db_session, cc_pair, IndexingStatus.FAILED, in_slice(20, 5), in_slice(20, 20)
    )
    succeeded = _index_attempt(
        db_session,
        cc_pair,
        IndexingStatus.SUCCESS,
        in_slice(30, 5),
        in_slice(30, 25),
        docs=40,
    )
    running = _index_attempt(
        db_session, cc_pair, IndexingStatus.IN_PROGRESS, in_slice(40, 5), None
    )
    resolve_runs__no_commit(
        db_session,
        {(CCPairRunKind.INDEXING, resolved_failure.id): cc_pair.id},
        admin.id,
    )
    db_session.commit()

    with _clock_at(now):
        response = get_cc_pair_throughput(
            cc_pair_id=cc_pair.id,
            window=CCPairThroughputWindow.HOURS_24,
            bins=48,
            user=admin,
            db_session=db_session,
        )

    runs = [
        {run.attempt_id: (run.status, run.resolved) for run in s.runs}
        for s in response.slices
    ]
    assert len(runs) == 48
    assert runs[10] == {resolved_failure.id: (IndexingStatus.FAILED, True)}
    assert runs[20] == {open_failure.id: (IndexingStatus.FAILED, False)}
    assert runs[30] == {succeeded.id: (IndexingStatus.SUCCESS, False)}
    # A running run lands in every slice from its start to now.
    assert running.id not in runs[39]
    for index in range(40, 48):
        assert runs[index] == {running.id: (IndexingStatus.IN_PROGRESS, False)}
    # AC-5: a slice with no run.
    assert runs[5] == {}
    assert response.slices[5].runs == []
    assert response.docs_indexed[5] == 0
    assert response.docs_indexed[30] == 40
    assert [s.docs_indexed for s in response.slices] == response.docs_indexed


def test_ac6_an_old_client_without_bins_keeps_todays_shape(
    db_session: Session, admin: User, cc_pair: ConnectorCredentialPair
) -> None:
    now = _now_off_boundary()
    started = now - timedelta(hours=3)
    finished = now - timedelta(hours=2)
    _index_attempt(db_session, cc_pair, IndexingStatus.SUCCESS, started, finished, 9)

    with _clock_at(now):
        response = get_cc_pair_throughput(
            cc_pair_id=cc_pair.id,
            window=CCPairThroughputWindow.HOURS_24,
            user=admin,
            db_session=db_session,
        )

    assert len(response.docs_indexed) == 72
    assert sum(response.docs_indexed) == 9
    # Today's fields stay. New ones may be added beside them.
    assert [(run.started, run.ended, run.status) for run in response.runs] == [
        (started, finished, IndexingStatus.SUCCESS)
    ]
    assert len(response.slices) == 72
