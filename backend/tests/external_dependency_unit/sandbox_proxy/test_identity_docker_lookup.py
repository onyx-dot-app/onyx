"""External-dependency-unit tests for ``DockerEventsLookup``.

Unit tests stub the docker SDK; This file spins up real labeled containers on
the host docker daemon and exercises the cache from the initial-sync + events
paths. Skipped automatically when the docker socket is absent so local
contributors without docker running aren't blocked.

These tests do not require Postgres or the compose stack — they touch the docker
socket only.
"""

from __future__ import annotations

import os
import time
from collections.abc import Generator
from uuid import UUID
from uuid import uuid4

import pytest
from docker import DockerClient
from docker.errors import APIError
from docker.errors import NotFound
from docker.models.containers import Container

from onyx.sandbox_proxy.identity_docker import _identity_from_container
from onyx.sandbox_proxy.identity_docker import DockerEventsLookup

_DOCKER_SOCKET = os.environ.get("SANDBOX_DOCKER_SOCKET", "/var/run/docker.sock")
_TEST_NETWORK = "onyx-craft-sandbox-test"
_BUSYBOX_IMAGE = "busybox:1.36"


pytestmark = pytest.mark.skipif(
    not os.path.exists(_DOCKER_SOCKET),
    reason=f"Docker socket not present at {_DOCKER_SOCKET}.",
)


@pytest.fixture(scope="module")
def docker_client() -> Generator[DockerClient, None, None]:
    client = DockerClient(base_url=f"unix://{_DOCKER_SOCKET}")
    try:
        yield client
    finally:
        client.close()


@pytest.fixture(scope="module")
def test_network(docker_client: DockerClient) -> Generator[str, None, None]:
    """Dedicated bridge for the test containers.

    Module-scoped so all tests in the file reuse one network — bridge creation
    is the slowest single op here and re-creating per test triples the wall
    clock.
    """
    try:
        docker_client.networks.get(_TEST_NETWORK)
    except NotFound:
        docker_client.networks.create(_TEST_NETWORK, driver="bridge")
    yield _TEST_NETWORK
    try:
        docker_client.networks.get(_TEST_NETWORK).remove()
    except (NotFound, APIError):
        pass


def _run_sandbox_labeled(
    docker_client: DockerClient,
    *,
    network: str,
    sandbox_id: UUID,
    tenant_id: str = "public",
    name: str | None = None,
) -> Container:
    """Spawn a busybox container with the sandbox label set + a long sleep.

    If the post-create wait times out (or anything in it raises) the caller
    never gets a reference, so ``cleanup_test_containers.append`` can't reach
    the container. Remove here so the test network's teardown isn't blocked by
    an orphan endpoint.
    """
    container = docker_client.containers.run(
        _BUSYBOX_IMAGE,
        command=["sleep", "3600"],
        detach=True,
        network=network,
        labels={
            "onyx.app/component": "craft-sandbox",
            "onyx.app/sandbox-id": str(sandbox_id),
            "onyx.app/tenant-id": tenant_id,
        },
        name=name or f"craft-sandbox-test-{str(sandbox_id)[:8]}",
    )
    try:
        # Wait for the network IP to be assigned. Bridge attachment is async
        # after container.run returns; Reload until NetworkSettings shows up.
        deadline = time.time() + 10.0
        while time.time() < deadline:
            container.reload()
            if _identity_from_container(container, network) is not None:
                return container
            time.sleep(0.1)
        raise RuntimeError(
            f"Container {container.name} did not attach to {network} within 10s."
        )
    except Exception:
        try:
            container.remove(force=True, v=False)
        except (NotFound, APIError):
            pass
        raise


@pytest.fixture
def fresh_lookup(
    docker_client: DockerClient, test_network: str
) -> Generator[DockerEventsLookup, None, None]:
    """A started lookup wired to the test network. Stops on teardown.

    ``stop()`` must wrap both the initial-sync assertion and the yield: if the
    assertion fires before yield, pytest skips the post-yield code and the
    events-watcher thread leaks, polling the shared docker socket and mutating
    caches in later tests.
    """
    lookup = DockerEventsLookup(docker_client=docker_client, network=test_network)
    lookup.start()
    try:
        assert lookup.wait_for_initial_sync(timeout_seconds=10.0), (
            "DockerEventsLookup initial sync did not complete within 10s."
        )
        yield lookup
    finally:
        lookup.stop()


@pytest.fixture
def cleanup_test_containers() -> Generator[list[Container], None, None]:
    """Collects containers each test creates; Removes them all on teardown.

    Tests push containers onto the yielded list via ``.append()``; The teardown
    loop iterates whatever they registered.

    No ``docker_client`` arg -- each ``Container`` is bound to the client it was
    created from, so ``c.remove()`` resolves on its own.
    """
    created: list[Container] = []
    yield created
    for c in created:
        try:
            c.remove(force=True, v=False)
        except (NotFound, APIError):
            pass


def test_lookup_finds_running_container_via_initial_sync(
    docker_client: DockerClient,
    test_network: str,
    cleanup_test_containers: list[Container],
) -> None:
    """
    Container started BEFORE the lookup must be discovered by the initial sync
    against the docker daemon, not just by the events stream.
    """
    sandbox_id = uuid4()
    container = _run_sandbox_labeled(
        docker_client, network=test_network, sandbox_id=sandbox_id
    )
    cleanup_test_containers.append(container)

    # Build the lookup AFTER the container is up so we hit the initial-sync
    # path. (`fresh_lookup` fixture would start before — wrong shape here.)
    lookup = DockerEventsLookup(docker_client=docker_client, network=test_network)
    lookup.start()
    try:
        assert lookup.wait_for_initial_sync(timeout_seconds=10.0)
        ip = container.attrs["NetworkSettings"]["Networks"][test_network]["IPAddress"]
        identity = lookup.lookup(ip)
        assert identity is not None
        assert identity.sandbox_id == sandbox_id
        assert identity.tenant_id == "public"
    finally:
        lookup.stop()


def test_lookup_discovers_container_started_after_via_events(
    fresh_lookup: DockerEventsLookup,
    docker_client: DockerClient,
    test_network: str,
    cleanup_test_containers: list[Container],
) -> None:
    """
    Container started AFTER the lookup is up must appear in the cache via the
    events watcher (start event -> inspect -> upsert).
    """
    sandbox_id = uuid4()
    container = _run_sandbox_labeled(
        docker_client, network=test_network, sandbox_id=sandbox_id
    )
    cleanup_test_containers.append(container)

    ip = container.attrs["NetworkSettings"]["Networks"][test_network]["IPAddress"]
    # Events propagate within a few ms but allow generous slack for CI.
    deadline = time.time() + 10.0
    identity = None
    while time.time() < deadline:
        identity = fresh_lookup.lookup(ip)
        if identity is not None:
            break
        time.sleep(0.05)
    assert identity is not None, (
        f"Events watcher did not surface container {container.name} within 10s."
    )
    assert identity.sandbox_id == sandbox_id


def test_lookup_evicts_container_on_destroy(
    fresh_lookup: DockerEventsLookup,
    docker_client: DockerClient,
    test_network: str,
    cleanup_test_containers: list[Container],
) -> None:
    """
    Removing a container must drop its IP from the cache so the proxy stops
    resolving traffic against a dead container's identity.
    """
    sandbox_id = uuid4()
    container = _run_sandbox_labeled(
        docker_client, network=test_network, sandbox_id=sandbox_id
    )
    cleanup_test_containers.append(container)
    ip = container.attrs["NetworkSettings"]["Networks"][test_network]["IPAddress"]

    # Wait for the start event to land in the cache.
    deadline = time.time() + 10.0
    while time.time() < deadline:
        if fresh_lookup.lookup(ip) is not None:
            break
        time.sleep(0.05)
    assert fresh_lookup.lookup(ip) is not None

    # Now destroy and assert eviction.
    container.remove(force=True, v=False)
    deadline = time.time() + 10.0
    while time.time() < deadline:
        if fresh_lookup.lookup(ip) is None:
            return
        time.sleep(0.05)
    # If we get here, the eviction never happened. The container is already
    # gone, so don't try to clean it up further.
    cleanup_test_containers.clear()
    pytest.fail(f"Events watcher did not evict {container.name} within 10s of removal.")


def test_lookup_ignores_unlabeled_containers(
    fresh_lookup: DockerEventsLookup,
    docker_client: DockerClient,
    test_network: str,
    cleanup_test_containers: list[Container],
) -> None:
    """
    Containers without the craft-sandbox component label must not surface --
    otherwise random user containers could spoof identity.
    """
    container = docker_client.containers.run(
        _BUSYBOX_IMAGE,
        command=["sleep", "3600"],
        detach=True,
        network=test_network,
        labels={"some.other/label": "value"},
        name=f"unlabeled-test-{uuid4().hex[:8]}",
    )
    cleanup_test_containers.append(container)
    container.reload()
    ip = container.attrs["NetworkSettings"]["Networks"][test_network]["IPAddress"]

    # Give events stream time to (not) propagate.
    time.sleep(1.0)
    assert fresh_lookup.lookup(ip) is None
