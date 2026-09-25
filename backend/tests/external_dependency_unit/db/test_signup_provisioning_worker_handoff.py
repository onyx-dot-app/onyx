"""
Signup provisioning never runs alembic inside the api server.

A pool tenant at the code's head revision is assigned in the request. When no
such tenant exists the request hands off to the `provision_tenant_for_user`
worker task and waits for the mapping to appear. The worker task migrates a
stale pool tenant, assigns it, and waits on the per-email lock rather than
running alongside another holder. The control plane hears about a tenant
before its mapping is written, and a delete that keeps failing is queued for
the refill task to retry.

Uses real PostgreSQL for the pool and mapping tables and real Redis for the
per-user lock. Alembic and the control plane are the only mocks. Multi-tenant
mode is patched in so the suite runs in the default CI lane.
"""

import threading
import uuid
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import Table, delete

from ee.onyx.background.celery.tasks.tenant_provisioning import (
    tasks as provisioning_tasks,
)
from ee.onyx.db import user_tenant_mapping
from ee.onyx.db.user_tenant_mapping import add_users_to_tenant
from ee.onyx.server.tenants import provisioning
from ee.onyx.server.tenants.schema_management import get_alembic_head_revision
from onyx.configs.constants import (
    ONYX_CLOUD_CONTROL_PLANE_ORPHANS_KEY,
    ONYX_CLOUD_TENANT_ID,
    OnyxCeleryTask,
)
from onyx.db.engine.sql_engine import SqlEngine, get_session_with_shared_schema
from onyx.db.models import AvailableTenant, PublicBase, UserTenantMapping
from onyx.redis.redis_pool import get_redis_client
from shared_configs.configs import TENANT_ID_PREFIX


@pytest.fixture(autouse=True)
def _multi_tenant() -> Generator[None, None, None]:
    SqlEngine.init_engine(pool_size=5, max_overflow=2)
    # The pool and mapping tables come from the multi-tenant migration set,
    # which the single-tenant test database never runs.
    PublicBase.metadata.create_all(
        SqlEngine.get_engine(),
        tables=[
            cast(Table, AvailableTenant.__table__),
            cast(Table, UserTenantMapping.__table__),
        ],
    )
    with (
        patch.object(provisioning, "MULTI_TENANT", True),
        patch.object(provisioning_tasks, "MULTI_TENANT", True),
        patch.object(user_tenant_mapping, "MULTI_TENANT", True),
        # Seat billing calls the control plane, which is not under test here.
        patch("ee.onyx.server.tenants.billing.enforce_cloud_seat_limit"),
    ):
        yield


@pytest.fixture
def email() -> str:
    return f"signup-{uuid.uuid4().hex[:8]}@example.com"


@pytest.fixture
def pool_tenant_ids() -> Generator[list[str], None, None]:
    """Tenant ids this test may put in the pool. Rows are removed afterwards."""
    tenant_ids = [TENANT_ID_PREFIX + str(uuid.uuid4()) for _ in range(2)]
    yield tenant_ids
    with get_session_with_shared_schema() as db_session:
        db_session.execute(
            delete(AvailableTenant).where(AvailableTenant.tenant_id.in_(tenant_ids))
        )
        db_session.execute(
            delete(UserTenantMapping).where(UserTenantMapping.tenant_id.in_(tenant_ids))
        )
        db_session.commit()


@pytest.fixture
def pool_tenant_id(pool_tenant_ids: list[str]) -> str:
    return pool_tenant_ids[0]


def _add_pool_tenant(
    tenant_id: str, alembic_version: str, age: timedelta = timedelta()
) -> None:
    with get_session_with_shared_schema() as db_session:
        db_session.add(
            AvailableTenant(
                tenant_id=tenant_id,
                alembic_version=alembic_version,
                date_created=datetime.now(timezone.utc) - age,
                shard_name="default",
            )
        )
        db_session.commit()


def _pool_has(tenant_id: str) -> bool:
    with get_session_with_shared_schema() as db_session:
        return (
            db_session.query(AvailableTenant).filter_by(tenant_id=tenant_id).first()
            is not None
        )


def _run_worker_task(email: str, attempt_id: str | None = None) -> bool:
    """Run the celery task in-process, as the monitoring worker would."""
    result = provisioning_tasks.provision_tenant_for_user.apply(
        kwargs={
            "tenant_id": ONYX_CLOUD_TENANT_ID,
            "email": email,
            "attempt_id": attempt_id or str(uuid.uuid4()),
        }
    ).get()
    return bool(result)


def _mapped_tenant(email: str) -> str | None:
    with get_session_with_shared_schema() as db_session:
        row = db_session.query(UserTenantMapping).filter_by(email=email).first()
        return row.tenant_id if row else None


@pytest.fixture
def no_alembic() -> Generator[MagicMock, None, None]:
    """The api path must never reach alembic. The worker path records the call."""
    with patch.object(provisioning, "run_alembic_migrations") as migrate:
        yield migrate


@pytest.fixture
def control_plane() -> Generator[MagicMock, None, None]:
    with (
        patch.object(provisioning, "DEV_MODE", False),
        patch.object(provisioning, "notify_control_plane") as notify,
    ):
        yield notify


@pytest.mark.asyncio
async def test_current_pool_tenant_is_assigned_in_the_request(
    email: str,
    pool_tenant_id: str,
    no_alembic: MagicMock,
    control_plane: MagicMock,
) -> None:
    _add_pool_tenant(pool_tenant_id, get_alembic_head_revision())

    with patch.object(provisioning.client_app, "send_task") as send_task:
        tenant_id = await provisioning.get_or_provision_tenant(email)

    assert tenant_id == pool_tenant_id
    assert _mapped_tenant(email) == pool_tenant_id
    assert not _pool_has(pool_tenant_id)
    control_plane.assert_called_once_with(pool_tenant_id, email, None)
    send_task.assert_not_called()
    no_alembic.assert_not_called()


@pytest.mark.asyncio
async def test_a_stale_older_tenant_does_not_hide_a_current_one(
    email: str,
    pool_tenant_ids: list[str],
    no_alembic: MagicMock,
    control_plane: MagicMock,  # noqa: ARG001
) -> None:
    stale_id, current_id = pool_tenant_ids
    _add_pool_tenant(stale_id, "stale-revision", age=timedelta(hours=1))
    _add_pool_tenant(current_id, get_alembic_head_revision())

    with patch.object(provisioning.client_app, "send_task") as send_task:
        tenant_id = await provisioning.get_or_provision_tenant(email)

    assert tenant_id == current_id
    assert _pool_has(stale_id)
    send_task.assert_not_called()
    no_alembic.assert_not_called()


@pytest.mark.asyncio
async def test_request_waits_for_the_lock_then_assigns(
    email: str,
    pool_tenant_id: str,
    no_alembic: MagicMock,
    control_plane: MagicMock,  # noqa: ARG001
) -> None:
    _add_pool_tenant(pool_tenant_id, get_alembic_head_revision())
    r = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)
    # Not thread-local, so the timer thread may release it.
    lock = r.lock(
        provisioning.user_provision_lock_name(email), timeout=30, thread_local=False
    )
    assert lock.acquire(blocking=False)
    # Released while the request polls for it, as a finishing holder would.
    threading.Timer(0.5, lock.release).start()

    with patch.object(provisioning.client_app, "send_task") as send_task:
        tenant_id = await provisioning.get_or_provision_tenant(email)

    assert tenant_id == pool_tenant_id
    send_task.assert_not_called()
    no_alembic.assert_not_called()


@pytest.mark.asyncio
async def test_stale_pool_tenant_is_handed_to_the_worker(
    email: str,
    pool_tenant_id: str,
    no_alembic: MagicMock,
    control_plane: MagicMock,  # noqa: ARG001
) -> None:
    _add_pool_tenant(pool_tenant_id, "stale-revision")

    def worker_assigns(*_args: object, **_kwargs: object) -> None:
        # Stands in for the worker: the mapping appears while the api polls.
        add_users_to_tenant([email], pool_tenant_id)

    with (
        patch.object(provisioning, "TENANT_PROVISIONING_WAIT_SECONDS", 10),
        patch.object(
            provisioning.client_app, "send_task", side_effect=worker_assigns
        ) as send_task,
    ):
        tenant_id = await provisioning.get_or_provision_tenant(email)

    assert tenant_id == pool_tenant_id
    send_task.assert_called_once()
    assert send_task.call_args.args[0] == OnyxCeleryTask.CLOUD_PROVISION_TENANT_FOR_USER
    assert send_task.call_args.kwargs["expires"] == 10
    # The api left the stale tenant in the pool for the worker to migrate.
    assert _pool_has(pool_tenant_id)
    no_alembic.assert_not_called()


@pytest.mark.asyncio
async def test_request_fails_when_the_worker_never_answers(
    email: str,
    no_alembic: MagicMock,
) -> None:
    with (
        patch.object(provisioning, "TENANT_PROVISIONING_WAIT_SECONDS", 2),
        patch.object(provisioning.client_app, "send_task"),
        pytest.raises(provisioning.OnyxError) as excinfo,
    ):
        await provisioning.get_or_provision_tenant(email)

    assert excinfo.value.error_code == provisioning.OnyxErrorCode.SERVICE_UNAVAILABLE
    no_alembic.assert_not_called()


@pytest.mark.asyncio
async def test_request_fails_fast_when_the_worker_reports_failure(
    email: str,
    no_alembic: MagicMock,
) -> None:
    workers: list[threading.Thread] = []

    def worker_fails(*_args: object, **kwargs: object) -> None:
        task_kwargs = cast(dict[str, str], kwargs["kwargs"])

        def run() -> None:
            # Own thread, as on a worker: takes the lock once the request
            # releases it, and runs its own event loop.
            with patch.object(
                provisioning, "provision_user_tenant", side_effect=RuntimeError("boom")
            ):
                with pytest.raises(RuntimeError):
                    _run_worker_task(email, attempt_id=task_kwargs["attempt_id"])

        worker = threading.Thread(target=run)
        workers.append(worker)
        worker.start()

    with (
        patch.object(provisioning, "TENANT_PROVISIONING_WAIT_SECONDS", 30),
        patch.object(provisioning_tasks, "TENANT_PROVISIONING_WAIT_SECONDS", 30),
        patch.object(provisioning.client_app, "send_task", side_effect=worker_fails),
        pytest.raises(provisioning.OnyxError) as excinfo,
    ):
        await provisioning.get_or_provision_tenant(email)
    for worker in workers:
        worker.join(timeout=30)

    # Far inside the 30s deadline: the worker's failure marker ended the wait.
    assert excinfo.value.error_code == provisioning.OnyxErrorCode.INTERNAL_ERROR
    no_alembic.assert_not_called()


@pytest.mark.asyncio
async def test_a_failed_control_plane_call_leaves_no_mapping(
    email: str,
    pool_tenant_id: str,
    no_alembic: MagicMock,  # noqa: ARG001
    control_plane: MagicMock,
) -> None:
    _add_pool_tenant(pool_tenant_id, get_alembic_head_revision())
    control_plane.side_effect = RuntimeError("control plane down")

    with (
        patch.object(provisioning.client_app, "send_task"),
        pytest.raises(provisioning.OnyxError),
    ):
        await provisioning.get_or_provision_tenant(email)

    assert _mapped_tenant(email) is None
    # Rolled back rather than left orphaned outside the pool.
    assert not _pool_has(pool_tenant_id)


@pytest.mark.asyncio
async def test_a_failed_assignment_undoes_the_control_plane_record(
    email: str,
    pool_tenant_id: str,
    no_alembic: MagicMock,  # noqa: ARG001
    control_plane: MagicMock,
) -> None:
    _add_pool_tenant(pool_tenant_id, get_alembic_head_revision())

    with (
        patch.object(provisioning.client_app, "send_task"),
        patch.object(
            provisioning, "assign_tenant_to_user", side_effect=RuntimeError("seats")
        ),
        patch.object(provisioning, "delete_user_from_control_plane") as undo,
        pytest.raises(provisioning.OnyxError),
    ):
        await provisioning.get_or_provision_tenant(email)

    control_plane.assert_called_once()
    undo.assert_called_once_with(pool_tenant_id, email)
    assert _mapped_tenant(email) is None
    assert not _pool_has(pool_tenant_id)


@pytest.mark.asyncio
async def test_a_control_plane_delete_that_keeps_failing_is_reconciled_later(
    email: str,
    pool_tenant_id: str,
    no_alembic: MagicMock,  # noqa: ARG001
    control_plane: MagicMock,
) -> None:
    _add_pool_tenant(pool_tenant_id, get_alembic_head_revision())
    r = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)
    orphan_entry = f"{pool_tenant_id} {email}"

    with (
        patch.object(provisioning, "_CONTROL_PLANE_DELETE_BACKOFF_S", 0),
        patch.object(provisioning.client_app, "send_task"),
        patch.object(
            provisioning, "assign_tenant_to_user", side_effect=RuntimeError("seats")
        ),
        patch.object(
            provisioning,
            "delete_user_from_control_plane",
            side_effect=RuntimeError("down"),
        ) as undo,
        pytest.raises(provisioning.OnyxError),
    ):
        await provisioning.get_or_provision_tenant(email)

    control_plane.assert_called_once()
    assert undo.call_count == provisioning._CONTROL_PLANE_DELETE_ATTEMPTS
    assert r.sismember(ONYX_CLOUD_CONTROL_PLANE_ORPHANS_KEY, orphan_entry)

    # The refill task retries later, once the control plane answers again.
    try:
        with patch.object(provisioning, "delete_user_from_control_plane") as retry:
            assert await provisioning.reconcile_control_plane_orphans() >= 1
        retry.assert_any_call(pool_tenant_id, email)
        assert not r.sismember(ONYX_CLOUD_CONTROL_PLANE_ORPHANS_KEY, orphan_entry)
    finally:
        r.srem(ONYX_CLOUD_CONTROL_PLANE_ORPHANS_KEY, orphan_entry)


def test_worker_migrates_a_stale_pool_tenant_and_assigns_it(
    email: str,
    pool_tenant_id: str,
    no_alembic: MagicMock,
    control_plane: MagicMock,
) -> None:
    _add_pool_tenant(pool_tenant_id, "stale-revision")

    assert _run_worker_task(email) is True

    no_alembic.assert_called_once_with(pool_tenant_id)
    control_plane.assert_called_once_with(pool_tenant_id, email, None)
    assert _mapped_tenant(email) == pool_tenant_id
    assert not _pool_has(pool_tenant_id)


def test_worker_waits_for_the_per_email_lock(email: str, no_alembic: MagicMock) -> None:
    r = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)
    lock = r.lock(provisioning.user_provision_lock_name(email), timeout=30)
    assert lock.acquire(blocking=False)
    try:
        with (
            patch.object(provisioning_tasks, "TENANT_PROVISIONING_WAIT_SECONDS", 1),
            patch.object(provisioning, "provision_user_tenant") as provision,
            pytest.raises(RuntimeError),
        ):
            _run_worker_task(email)
        provision.assert_not_called()
    finally:
        lock.release()
    no_alembic.assert_not_called()
