from collections.abc import Callable, Generator
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend, get_shared_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.microvm import placement, reconcile, registry
from onyx.microvm.registry import set_node_agent_address
from shared_configs.contextvars import POSTGRES_DEFAULT_SCHEMA
from tests.external_dependency_unit.conftest import delete_test_users_and_owned_rows
from tests.external_dependency_unit.craft.db_helpers import make_sandbox, make_user
from tests.external_dependency_unit.microvm.fake_agent import (
    FakeHostAgent,
    InsecureClientFactory,
    RunningFakeAgent,
)

TENANT_ID = POSTGRES_DEFAULT_SCHEMA


def forget_sandbox_keys(tenant_cache: CacheBackend, sandbox_id: UUID) -> None:
    """Delete every tenant-cache key that placement writes for a sandbox."""
    registry.clear_sandbox_placement(tenant_cache, sandbox_id)
    registry.clear_sandbox_daemon_key(tenant_cache, sandbox_id)
    placement.clear_pending_create(tenant_cache, sandbox_id)


@pytest.fixture
def shared_cache() -> Generator[CacheBackend, None, None]:
    cache = get_shared_cache_backend()
    # The node directory is cluster-wide: start every test with no nodes.
    cache.delete(registry._NODES_KEY)
    yield cache
    cache.delete(registry._NODES_KEY)


@pytest.fixture
def tenant_cache() -> CacheBackend:
    return get_cache_backend(tenant_id=TENANT_ID)


@pytest.fixture
def client_factory() -> Generator[InsecureClientFactory, None, None]:
    factory = InsecureClientFactory()
    yield factory
    factory.close()


AddNode = Callable[..., RunningFakeAgent]


@pytest.fixture
def add_node(shared_cache: CacheBackend) -> Generator[AddNode, None, None]:
    """Start a fake agent and register it as `node_id`."""
    started: list[tuple[str, RunningFakeAgent]] = []

    def add(node_id: str, agent: FakeHostAgent | None = None) -> RunningFakeAgent:
        running = RunningFakeAgent(agent or FakeHostAgent())
        set_node_agent_address(shared_cache, node_id=node_id, address=running.address)
        started.append((node_id, running))
        return running

    yield add
    for node_id, running in started:
        running.stop()
        shared_cache.delete(registry._NODE_ADDRESS_PREFIX + node_id)
        shared_cache.delete(registry._NODE_PLACEMENTS_PREFIX + node_id)
        shared_cache.delete_prefix(f"{reconcile._ORPHAN_MARK_PREFIX}{node_id}:")


NewSandboxId = Callable[[], UUID]


@pytest.fixture
def new_sandbox_id(
    tenant_cache: CacheBackend,
) -> Generator[NewSandboxId, None, None]:
    """A fresh sandbox id whose placement keys are deleted after the test."""
    ids: list[UUID] = []

    def new() -> UUID:
        ids.append(uuid4())
        return ids[-1]

    yield new
    for sandbox_id in ids:
        forget_sandbox_keys(tenant_cache, sandbox_id)


MakeSandbox = Callable[..., Sandbox]


@pytest.fixture
def make_db_sandbox(
    db_session: Session, tenant_cache: CacheBackend
) -> Generator[MakeSandbox, None, None]:
    users: list[tuple[UUID, str]] = []
    sandbox_ids: list[UUID] = []

    def make(
        status: SandboxStatus = SandboxStatus.RUNNING,
        attempt: int = 1,
        last_heartbeat: datetime | None = None,
    ) -> Sandbox:
        user = make_user(db_session, email_prefix="microvm")
        sandbox = make_sandbox(db_session, user, status=status)
        sandbox.provisioning_attempt_number = attempt
        sandbox.last_heartbeat = last_heartbeat or datetime.now(timezone.utc)
        db_session.commit()
        users.append((user.id, user.email))
        sandbox_ids.append(sandbox.id)
        return sandbox

    yield make
    for sandbox_id in sandbox_ids:
        forget_sandbox_keys(tenant_cache, sandbox_id)
    if users:
        delete_test_users_and_owned_rows(
            db_session, [u for u, _ in users], [e for _, e in users]
        )
