"""PostgreSQL races for durable agent execution and model-group completion."""

from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Barrier
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, insert, update
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from onyx.db import agent_runs
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.models import AgentRun
from onyx.error_handling.exceptions import OnyxError


@pytest.fixture
def run_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[Callable[..., list[AgentRun]], None, None]:
    """Use isolated tables and real independent transactions for each callback."""
    SqlEngine.init_engine(pool_size=10, max_overflow=10)
    engine = SqlEngine.get_engine()
    schema = f"agent_run_test_{uuid4().hex}"
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    isolated = engine.execution_options(schema_translate_map={None: schema})
    metadata = MetaData()
    chats = Table(
        "chat_session",
        metadata,
        Column("id", PGUUID, primary_key=True),
        Column("incognito_record_mode", String),
    )
    messages = Table("chat_message", metadata, Column("id", Integer, primary_key=True))
    cast(Table, AgentRun.__table__).to_metadata(metadata)
    metadata.create_all(isolated)
    sessions = sessionmaker(isolated, expire_on_commit=False)

    @contextmanager
    def session_scope() -> Generator[Session, None, None]:
        with sessions() as session:
            yield session

    monkeypatch.setattr(agent_runs, "get_session_with_current_tenant", session_scope)
    message_id = 0

    def create(
        count: int = 1,
        *,
        cancelled: bool = False,
        expired: bool = False,
        content_free: bool = False,
    ) -> list[AgentRun]:
        nonlocal message_id
        session_id = uuid4()
        now = datetime.now(timezone.utc)
        runs = []
        with sessions.begin() as session:
            session.execute(
                insert(chats).values(
                    id=session_id,
                    incognito_record_mode="usage_only" if content_free else None,
                )
            )
            for index in range(count):
                message_id += 1
                session.execute(insert(messages).values(id=message_id))
                runs.append(
                    AgentRun(
                        id=uuid4(),
                        chat_session_id=session_id,
                        message_id=message_id,
                        group_id=1,
                        model_index=index,
                        cancel_requested=cancelled,
                        expires_at=now + timedelta(minutes=-1 if expired else 30),
                    )
                )
        agent_runs.create_runs(runs)
        return runs

    try:
        yield create
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))


def test_only_one_attempt_can_claim_and_run_is_never_replayed(
    run_factory: Callable[..., list[AgentRun]],
) -> None:
    run = run_factory()[0]
    attempts = [uuid4() for _ in range(8)]
    barrier = Barrier(len(attempts))

    def claim(attempt: UUID) -> bool:
        barrier.wait()
        return agent_runs.claim_run(run.id, attempt)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(claim, attempts))
    assert results.count(True) == 1
    winner = attempts[results.index(True)]
    assert agent_runs.get_run(run.id).attempt_id == winner
    assert agent_runs.begin_finish(run.id, winner)
    assert agent_runs.complete_run(run.id, "completed")
    assert not agent_runs.claim_run(run.id, uuid4())
    assert not agent_runs.complete_run(run.id, "failed")
    assert agent_runs.get_run(run.id).status == "completed"


def test_callbacks_deduplicate_and_reject_gaps_cancellation_and_wrong_owner(
    run_factory: Callable[..., list[AgentRun]],
) -> None:
    run = run_factory()[0]
    attempt = uuid4()
    assert agent_runs.claim_run(run.id, attempt)
    barrier = Barrier(8)

    def callback(_: int) -> bool:
        barrier.wait()
        try:
            agent_runs.claim_operation(run.id, attempt, 1)
            return True
        except OnyxError:
            return False

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert list(executor.map(callback, range(8))).count(True) == 1
    with pytest.raises(OnyxError):
        agent_runs.claim_operation(run.id, attempt, 3)
    with pytest.raises(OnyxError):
        agent_runs.claim_operation(run.id, uuid4(), 2)
    assert agent_runs.claim_operation(run.id, attempt, 2).last_sequence == 2
    agent_runs.cancel_session_runs(run.chat_session_id)
    with pytest.raises(OnyxError):
        agent_runs.claim_operation(run.id, attempt, 3)
    with pytest.raises(OnyxError):
        agent_runs.require_owner(run.id, attempt)
    assert not agent_runs.heartbeat_run(run.id, attempt)
    assert agent_runs.get_run(run.id).last_sequence == 2


@pytest.mark.parametrize("cancelled,expired", [(True, False), (False, True)])
def test_unrunnable_queue_entries_are_discoverable_and_finish_without_execution(
    run_factory: Callable[..., list[AgentRun]], cancelled: bool, expired: bool
) -> None:
    run = run_factory(cancelled=cancelled, expired=expired)[0]
    assert not agent_runs.claim_run(run.id, uuid4())
    assert [entry.id for entry in agent_runs.recovery_candidates()] == [run.id]
    assert agent_runs.begin_finish(run.id, None)
    assert agent_runs.complete_run(run.id, "interrupted")
    result = agent_runs.get_run(run.id)
    assert (result.status, result.attempt_id) == (
        "cancelled" if cancelled else "interrupted",
        None,
    )


def test_concurrent_model_completions_emit_one_group_done(
    run_factory: Callable[..., list[AgentRun]],
) -> None:
    runs = run_factory(4)
    for run in runs:
        attempt = uuid4()
        assert agent_runs.claim_run(run.id, attempt)
        assert agent_runs.begin_finish(run.id, attempt)
    barrier = Barrier(len(runs))

    def complete(run: AgentRun) -> bool:
        barrier.wait()
        return agent_runs.complete_run(run.id, "completed")

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(complete, runs))
    assert results.count(True) == 1
    assert [agent_runs.get_run(run.id).status for run in runs] == ["completed"] * 4


def test_stale_finalizer_recovery_is_single_transition_and_never_replays(
    run_factory: Callable[..., list[AgentRun]],
) -> None:
    run = run_factory()[0]
    attempt = uuid4()
    assert agent_runs.claim_run(run.id, attempt)
    assert agent_runs.begin_finish(run.id, attempt)
    current = agent_runs.get_run(run.id)
    assert agent_runs.recover_stale_finish(run.id, current.updated_at) is None
    stale = datetime.now(timezone.utc) - timedelta(minutes=10)
    with agent_runs.get_session_with_current_tenant() as session:
        session.execute(
            update(AgentRun).where(AgentRun.id == run.id).values(updated_at=stale)
        )
        session.commit()
    assert agent_runs.recover_stale_finish(run.id, current.updated_at) is None
    assert agent_runs.recover_stale_finish(run.id, stale) is True
    assert agent_runs.recover_stale_finish(run.id, stale) is None
    assert not agent_runs.begin_finish(run.id, attempt)
    assert not agent_runs.complete_run(run.id, "completed")
    assert agent_runs.get_run(run.id).status == "interrupted"


@pytest.mark.parametrize("content_free", [False, True])
def test_group_completion_remains_pending_until_stream_acknowledgement(
    run_factory: Callable[..., list[AgentRun]],
    content_free: bool,
) -> None:
    runs = run_factory(2, content_free=content_free)
    for run in runs:
        assert agent_runs.begin_finish(run.id, None)
    assert not agent_runs.complete_run(runs[0].id, "interrupted")
    assert agent_runs.pending_stream_closures() == []
    assert agent_runs.complete_run(runs[1].id, "completed")
    expected = [
        agent_runs.PendingStreamClosure(runs[0].chat_session_id, 1, content_free, True)
    ]
    assert agent_runs.pending_stream_closures() == expected
    # Reading or a failed Redis notification must not acknowledge the durable row.
    assert agent_runs.pending_stream_closures() == expected
    agent_runs.mark_group_stream_closed(runs[0].chat_session_id, 1)
    assert agent_runs.pending_stream_closures() == []


def test_finalizer_heartbeat_fences_stale_recovery(
    run_factory: Callable[..., list[AgentRun]],
) -> None:
    run = run_factory()[0]
    assert agent_runs.begin_finish(run.id, None)
    stale = datetime.now(timezone.utc) - timedelta(minutes=10)
    with agent_runs.get_session_with_current_tenant() as session:
        session.execute(
            update(AgentRun).where(AgentRun.id == run.id).values(updated_at=stale)
        )
        session.commit()
    assert agent_runs.heartbeat_finalizer(run.id, None)
    assert agent_runs.recover_stale_finish(run.id, stale) is None
    assert agent_runs.get_run(run.id).status == "finishing"


def test_recovery_scan_cannot_interrupt_a_worker_that_renewed_ownership(
    run_factory: Callable[..., list[AgentRun]],
) -> None:
    run = run_factory()[0]
    attempt = uuid4()
    assert agent_runs.claim_run(run.id, attempt)
    stale = datetime.now(timezone.utc) - timedelta(minutes=2)
    with agent_runs.get_session_with_current_tenant() as session:
        session.execute(
            update(AgentRun).where(AgentRun.id == run.id).values(updated_at=stale)
        )
        session.commit()
    scanned = agent_runs.recovery_candidates()[0]
    assert agent_runs.heartbeat_run(run.id, attempt)
    assert not agent_runs.begin_finish(
        run.id, attempt, observed_updated_at=scanned.updated_at
    )
    assert agent_runs.get_run(run.id).status == "running"


def test_bulk_heartbeat_rejects_cancelled_expired_unknown_and_wrong_attempts(
    run_factory: Callable[..., list[AgentRun]],
) -> None:
    runs = [run_factory()[0] for _ in range(4)]
    attempts = [uuid4() for _ in runs]
    for run, attempt in zip(runs, attempts, strict=True):
        assert agent_runs.claim_run(run.id, attempt)
    agent_runs.cancel_session_runs(runs[1].chat_session_id)
    with agent_runs.get_session_with_current_tenant() as session:
        session.execute(
            update(AgentRun)
            .where(AgentRun.id == runs[2].id)
            .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
        session.commit()
    unknown = uuid4()
    result = agent_runs.heartbeat_runs(
        [
            (runs[0].id, attempts[0]),
            (runs[1].id, attempts[1]),
            (runs[2].id, attempts[2]),
            (runs[3].id, uuid4()),
            (unknown, uuid4()),
        ]
    )
    assert result == [runs[1].id, runs[2].id, runs[3].id, unknown]
    assert agent_runs.heartbeat_runs([]) == []


def test_bulk_heartbeat_cannot_renew_another_tenants_run(
    run_factory: Callable[..., list[AgentRun]], monkeypatch: pytest.MonkeyPatch
) -> None:
    run = run_factory()[0]
    attempt = uuid4()
    assert agent_runs.claim_run(run.id, attempt)
    before = agent_runs.get_run(run.id).updated_at
    with agent_runs.get_session_with_current_tenant() as session:
        source_schema = session.connection().get_execution_options()[
            "schema_translate_map"
        ][None]
    schema = f"agent_other_tenant_{uuid4().hex}"
    engine = SqlEngine.get_engine()
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
        # Both identifiers are generated by this test, never user input.
        connection.exec_driver_sql(
            f'CREATE TABLE "{schema}".agent_run (LIKE "{source_schema}".agent_run INCLUDING ALL)'
        )
    isolated = engine.execution_options(schema_translate_map={None: schema})

    @contextmanager
    def other_tenant() -> Generator[Session, None, None]:
        with Session(isolated) as session:
            yield session

    try:
        with monkeypatch.context() as patch:
            patch.setattr(agent_runs, "get_session_with_current_tenant", other_tenant)
            assert agent_runs.heartbeat_runs([(run.id, attempt)]) == [run.id]
        assert agent_runs.get_run(run.id).updated_at == before
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))


@pytest.mark.parametrize(
    "rejection", ["attempt", "sequence", "cancelled", "expired", "public", "tenant"]
)
def test_http_tool_callback_checks_authority_before_tool_execution(
    run_factory: Callable[..., list[AgentRun]],
    monkeypatch: pytest.MonkeyPatch,
    rejection: str,
) -> None:
    import asyncio
    from unittest.mock import MagicMock

    from anyio import CapacityLimiter
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from onyx.chat.pi import auth, runtime
    from onyx.chat.pi.api import router
    from onyx.error_handling.exceptions import register_onyx_exception_handlers
    from shared_configs.contextvars import get_current_tenant_id

    run = run_factory()[0]
    attempt = uuid4()
    assert agent_runs.claim_run(run.id, attempt)
    if rejection == "cancelled":
        agent_runs.cancel_session_runs(run.chat_session_id)
    if rejection == "expired":
        with agent_runs.get_session_with_current_tenant() as session:
            session.execute(
                update(AgentRun)
                .where(AgentRun.id == run.id)
                .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
            )
            session.commit()
    load = MagicMock(
        side_effect=AssertionError(
            "Rejected requests must not load credentials or tools"
        )
    )
    monkeypatch.setattr(runtime, "load_run_inputs", load)
    monkeypatch.setenv("ONYX_AGENT_SERVICE_TOKEN", "test-worker-token")
    monkeypatch.setattr(auth, "MULTI_TENANT", False)
    monkeypatch.setattr(auth, "POSTGRES_DEFAULT_SCHEMA", get_current_tenant_id())
    headers = {
        "authorization": "Bearer test-worker-token",
        "x-onyx-tenant-id": get_current_tenant_id(),
    }
    if rejection == "public":
        headers["x-onyx-public-request"] = "true"
    elif rejection == "tenant":
        headers["x-onyx-tenant-id"] = "other_tenant"
    app = FastAPI()
    app.include_router(router)
    register_onyx_exception_handlers(app)

    async def exercise() -> None:
        app.state.agent_tool_limiter = CapacityLimiter(1)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http:
            response = await http.post(
                f"/internal/agent/runs/{run.id}/callback",
                headers=headers,
                json={
                    "attemptId": str(uuid4() if rejection == "attempt" else attempt),
                    "sequence": 2 if rejection == "sequence" else 1,
                    "type": "tools",
                    "payload": {"calls": []},
                },
            )
            assert response.status_code == {"public": 404, "tenant": 400}.get(
                rejection, 409
            )
        load.assert_not_called()
        assert agent_runs.get_run(run.id).last_sequence == 0

    asyncio.run(exercise())
