"""A pair's throughput with a client bin count: the pair and fleet routes take
12 to 84 bins, each slice names its runs by attempt id with status and whether
they still count as open, a slice with no run is empty, and a request without
``bins`` keeps the flat fields. The direct calls pin the clock off a bin
boundary so the window's end rounds up."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.cc_pair_run_resolution import resolve_runs__no_commit
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import CCPairRunKind, IndexingStatus
from onyx.db.models import ConnectorCredentialPair, IndexAttempt, User
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server.documents.cc_pair import get_cc_pair_throughput
from onyx.server.documents.cc_pair import router as cc_pair_router
from onyx.server.documents.index_monitoring import router as index_monitoring_router
from onyx.server.documents.models import CCPairThroughputWindow
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
    make_index_attempt,
    throughput_clock_at,
)

_WIDTH = timedelta(minutes=30)
# Off every 30-minute boundary, so the window's end rounds up to 14:00.
_NOW = datetime(2026, 1, 1, 13, 47, 12, tzinfo=timezone.utc)
_WINDOW_END = datetime(2026, 1, 1, 14, tzinfo=timezone.utc)
_WINDOW_START = _WINDOW_END - timedelta(hours=24)


def _in_slice(index: int, minutes: int) -> datetime:
    return _WINDOW_START + _WIDTH * index + timedelta(minutes=minutes)


@pytest.fixture
def admin(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "throughput_bins_admin", is_admin=True)
    yield user
    db_session.rollback()
    delete_test_user(db_session, user)
    db_session.commit()


@pytest.fixture
def cc_pair(db_session: Session) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    yield pair
    db_session.rollback()
    db_session.query(IndexAttempt).filter(
        IndexAttempt.connector_credential_pair_id == pair.id
    ).delete(synchronize_session="fetch")
    db_session.commit()
    cleanup_cc_pair(db_session, pair)


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
    resolved_failure = make_index_attempt(
        db_session, cc_pair, IndexingStatus.FAILED, _in_slice(10, 5), _in_slice(10, 20)
    )
    superseded_failure = make_index_attempt(
        db_session, cc_pair, IndexingStatus.FAILED, _in_slice(20, 5), _in_slice(20, 20)
    )
    succeeded = make_index_attempt(
        db_session,
        cc_pair,
        IndexingStatus.SUCCESS,
        _in_slice(30, 5),
        _in_slice(30, 25),
        docs=40,
    )
    open_failure = make_index_attempt(
        db_session, cc_pair, IndexingStatus.FAILED, _in_slice(35, 5), _in_slice(35, 20)
    )
    running = make_index_attempt(
        db_session, cc_pair, IndexingStatus.IN_PROGRESS, _in_slice(40, 5), None
    )
    resolve_runs__no_commit(
        db_session,
        {(CCPairRunKind.INDEXING, resolved_failure.id): cc_pair.id},
        admin.id,
    )
    db_session.commit()

    with throughput_clock_at(_NOW):
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
    # Resolved and also superseded by the success at 30. The newest-failure test
    # pins resolution alone.
    assert runs[10] == {resolved_failure.id: (IndexingStatus.FAILED, True)}
    # The newer success supersedes it, so it is no open failure.
    assert runs[20] == {superseded_failure.id: (IndexingStatus.FAILED, True)}
    assert runs[30] == {succeeded.id: (IndexingStatus.SUCCESS, False)}
    assert runs[35] == {open_failure.id: (IndexingStatus.FAILED, False)}
    # A running run is in every slice from its start to the slice holding now.
    assert running.id not in runs[39]
    for index in range(40, 48):
        assert runs[index] == {running.id: (IndexingStatus.IN_PROGRESS, False)}
    # A slice with no run is empty.
    assert runs[5] == {}
    assert response.slices[5].runs == []
    assert response.docs_indexed[5] == 0
    assert response.docs_indexed[30] == 40
    assert [s.docs_indexed for s in response.slices] == response.docs_indexed


def test_an_admin_resolved_newest_failure_is_resolved(
    db_session: Session, admin: User, cc_pair: ConnectorCredentialPair
) -> None:
    make_index_attempt(
        db_session, cc_pair, IndexingStatus.SUCCESS, _in_slice(10, 5), _in_slice(10, 20)
    )
    # The newest settled run, so nothing supersedes it.
    newest_failure = make_index_attempt(
        db_session, cc_pair, IndexingStatus.FAILED, _in_slice(20, 5), _in_slice(20, 20)
    )
    resolve_runs__no_commit(
        db_session,
        {(CCPairRunKind.INDEXING, newest_failure.id): cc_pair.id},
        admin.id,
    )
    db_session.commit()

    with throughput_clock_at(_NOW):
        response = get_cc_pair_throughput(
            cc_pair_id=cc_pair.id,
            window=CCPairThroughputWindow.HOURS_24,
            bins=48,
            user=admin,
            db_session=db_session,
        )

    assert [
        (run.attempt_id, run.status, run.resolved) for run in response.slices[20].runs
    ] == [(newest_failure.id, IndexingStatus.FAILED, True)]


def test_ac6_a_request_without_bins_keeps_the_flat_fields(
    db_session: Session, admin: User, cc_pair: ConnectorCredentialPair
) -> None:
    started = _NOW - timedelta(hours=3)
    finished = _NOW - timedelta(hours=2)
    make_index_attempt(
        db_session, cc_pair, IndexingStatus.SUCCESS, started, finished, 9
    )

    with throughput_clock_at(_NOW):
        response = get_cc_pair_throughput(
            cc_pair_id=cc_pair.id,
            window=CCPairThroughputWindow.HOURS_24,
            user=admin,
            db_session=db_session,
        )

    assert len(response.docs_indexed) == 72
    assert sum(response.docs_indexed) == 9
    # The flat fields keep their values beside ``slices``.
    assert [(run.started, run.ended, run.status) for run in response.runs] == [
        (started, finished, IndexingStatus.SUCCESS)
    ]
    assert len(response.slices) == 72


def test_a_run_is_in_each_slice_it_spans_and_not_past_a_boundary_it_ends_on(
    db_session: Session, admin: User, cc_pair: ConnectorCredentialPair
) -> None:
    spanning = make_index_attempt(
        db_session,
        cc_pair,
        IndexingStatus.SUCCESS,
        _in_slice(12, 20),
        _in_slice(13, 10),
    )
    on_boundary = make_index_attempt(
        db_session, cc_pair, IndexingStatus.SUCCESS, _in_slice(15, 10), _in_slice(16, 0)
    )

    with throughput_clock_at(_NOW):
        response = get_cc_pair_throughput(
            cc_pair_id=cc_pair.id,
            window=CCPairThroughputWindow.HOURS_24,
            bins=48,
            user=admin,
            db_session=db_session,
        )

    ids = [{run.attempt_id for run in s.runs} for s in response.slices]
    assert [index for index, held in enumerate(ids) if spanning.id in held] == [12, 13]
    assert [index for index, held in enumerate(ids) if on_boundary.id in held] == [15]
    assert response.slices[-1].end == response.window_end
