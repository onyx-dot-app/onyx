from collections.abc import Callable, Generator
from typing import Any
from uuid import UUID, uuid4

import pytest

from onyx.cache.factory import get_cache_backend, get_shared_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.microvm import reconcile, registry
from onyx.microvm.registry import set_node_agent_address
from onyx.tools.tool_implementations.sandbox import file_copies
from onyx.tools.tool_implementations.sandbox.file_copies import FileCopyPool
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
from shared_configs.contextvars import POSTGRES_DEFAULT_SCHEMA
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
    registry.clear_sandbox_reservation(tenant_cache, sandbox_id)


@pytest.fixture(autouse=True)
def no_built_in_skill_copies(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turns copy no built-in skills, so their results get no `[skills]`
    line, whatever the timing. A test marked `copies_built_in_skills` keeps
    the copies."""
    if request.node.get_closest_marker("copies_built_in_skills") is not None:
        return
    init = SandboxTurn.__init__

    def without_built_ins(turn: SandboxTurn, **kwargs: Any) -> None:
        kwargs["built_in_skills"] = ()
        init(turn, **kwargs)

    monkeypatch.setattr(SandboxTurn, "__init__", without_built_ins)


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
        shared_cache.delete(registry._NODE_ADDRESS_KEY_PREFIX + node_id)
        shared_cache.delete(registry._NODE_PLACEMENTS_PREFIX + node_id)
        shared_cache.delete(registry._NODE_LAST_REPORT_PREFIX + node_id)
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


NewFileCopyPool = Callable[[], FileCopyPool]


@pytest.fixture
def new_file_copy_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[NewFileCopyPool, None, None]:
    """Make a new pod pool, which `file_copy_pool` gives from then on. A test
    that changes the pool's limits makes its pool after the change. The pools
    shut down after the test."""
    pools: list[FileCopyPool] = []

    def new() -> FileCopyPool:
        pool = FileCopyPool()
        pools.append(pool)
        monkeypatch.setattr(file_copies, "file_copy_pool", lambda: pool)
        return pool

    yield new
    for pool in pools:
        pool.shutdown()


Idle = Callable[[], bool]


@pytest.fixture
def idle(monkeypatch: pytest.MonkeyPatch, new_file_copy_pool: NewFileCopyPool) -> Idle:
    """Whether every copy that the test started has ended. The test starts
    with a new pod pool; a pool that it makes for another pod counts too.
    A fixture that cleans up what copies use waits for this first."""
    pools: list[FileCopyPool] = []
    init = FileCopyPool.__init__

    def tracked(pool: FileCopyPool) -> None:
        init(pool)
        pools.append(pool)

    monkeypatch.setattr(FileCopyPool, "__init__", tracked)
    new_file_copy_pool()
    return lambda: all(pool.idle() for pool in pools)
