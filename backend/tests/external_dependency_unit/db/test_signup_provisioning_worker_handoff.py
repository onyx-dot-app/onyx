"""
Signup provisioning never runs alembic inside the api server.

A pool tenant at the code's head revision is assigned in the request. A stale
pool tenant stays in the pool and the request hands off to the
`provision_tenant_for_user` worker task, then waits for the mapping to appear.
The worker task migrates the stale tenant, assigns it, and refuses to run twice
for one email.

Uses real PostgreSQL for the pool and mapping tables and real Redis for the
per-user lock. Alembic and the control plane are the only mocks.
"""

import uuid
from collections.abc import Generator
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import delete

from ee.onyx.background.celery.tasks.tenant_provisioning import (
    tasks as provisioning_tasks,
)
from ee.onyx.db.user_tenant_mapping import add_users_to_tenant
from ee.onyx.server.tenants import provisioning
from ee.onyx.server.tenants.schema_management import get_alembic_head_revision
from onyx.configs.constants import ONYX_CLOUD_TENANT_ID, OnyxCeleryTask
from onyx.db.engine.sql_engine import SqlEngine, get_session_with_shared_schema
from onyx.db.models import AvailableTenant, UserTenantMapping
from onyx.redis.redis_pool import get_redis_client
from shared_configs.configs import TENANT_ID_PREFIX

pytestmark = pytest.mark.skipif(
    not provisioning.MULTI_TENANT, reason="needs MULTI_TENANT=true"
)


@pytest.fixture(autouse=True)
def _engine() -> None:
    SqlEngine.init_engine(pool_size=5, max_overflow=2)


@pytest.fixture
def email() -> str:
    return f"signup-{uuid.uuid4().hex[:8]}@example.com"


@pytest.fixture
def pool_tenant_id() -> Generator[str, None, None]:
    tenant_id = TENANT_ID_PREFIX + str(uuid.uuid4())
    yield tenant_id
    with get_session_with_shared_schema() as db_session:
        db_session.execute(
            delete(AvailableTenant).where(AvailableTenant.tenant_id == tenant_id)
        )
        db_session.execute(
            delete(UserTenantMapping).where(UserTenantMapping.tenant_id == tenant_id)
        )
        db_session.commit()


def _add_pool_tenant(tenant_id: str, alembic_version: str) -> None:
    with get_session_with_shared_schema() as db_session:
        db_session.add(
            AvailableTenant(
                tenant_id=tenant_id,
                alembic_version=alembic_version,
                date_created=datetime.now(timezone.utc),
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


def _run_worker_task(email: str) -> bool:
    """Run the celery task in-process, as the monitoring worker would."""
    result = provisioning_tasks.provision_tenant_for_user.apply(
        kwargs={"email": email}
    ).get()
    return bool(result)


def _mapped_tenant(email: str) -> str | None:
    with get_session_with_shared_schema() as db_session:
        row = db_session.query(UserTenantMapping).filter_by(email=email).first()
        return row.tenant_id if row else None


@pytest.fixture
def no_alembic() -> Generator[MagicMock, None, None]:
    """The api path must never reach alembic; the worker path records the call."""
    with patch.object(provisioning, "run_alembic_migrations") as migrate:
        yield migrate


@pytest.fixture
def offline_control_plane() -> Generator[None, None, None]:
    with patch.object(provisioning, "DEV_MODE", True):
        yield


@pytest.mark.asyncio
async def test_current_pool_tenant_is_assigned_in_the_request(
    email: str,
    pool_tenant_id: str,
    no_alembic: MagicMock,
    offline_control_plane: None,  # noqa: ARG001
) -> None:
    _add_pool_tenant(pool_tenant_id, get_alembic_head_revision())

    with patch.object(provisioning.client_app, "send_task") as send_task:
        tenant_id = await provisioning.get_or_provision_tenant(email)

    assert tenant_id == pool_tenant_id
    assert _mapped_tenant(email) == pool_tenant_id
    assert not _pool_has(pool_tenant_id)
    send_task.assert_not_called()
    no_alembic.assert_not_called()


@pytest.mark.asyncio
async def test_stale_pool_tenant_is_handed_to_the_worker(
    email: str,
    pool_tenant_id: str,
    no_alembic: MagicMock,
    offline_control_plane: None,  # noqa: ARG001
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


def test_worker_migrates_a_stale_pool_tenant_and_assigns_it(
    email: str,
    pool_tenant_id: str,
    no_alembic: MagicMock,
    offline_control_plane: None,  # noqa: ARG001
) -> None:
    _add_pool_tenant(pool_tenant_id, "stale-revision")

    assert _run_worker_task(email) is True

    no_alembic.assert_called_once_with(pool_tenant_id)
    assert _mapped_tenant(email) == pool_tenant_id
    assert not _pool_has(pool_tenant_id)


def test_worker_runs_once_per_email(email: str, no_alembic: MagicMock) -> None:
    r = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)
    lock = r.lock(provisioning_tasks.user_provision_lock_name(email), timeout=30)
    assert lock.acquire(blocking=False)
    try:
        with patch.object(provisioning, "provision_user_tenant") as provision:
            assert _run_worker_task(email) is False
        provision.assert_not_called()
    finally:
        lock.release()
    no_alembic.assert_not_called()
