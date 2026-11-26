"""The container harness sandbox against real Docker containers of the
craft-runtime `container` image.

Build the image first (from the repository root):

    TAG=dev docker buildx bake -f deployment/craft-runtime/docker-bake.hcl \\
        --load container

The tests use `SANDBOX_HARNESS_TEST_IMAGE` (default
`onyxdotapp/craft-runtime:dev-container`) and skip when Docker or the image
is missing. Each container dials a published port on 127.0.0.1. A
documentation address (192.0.2.1) stands in for the egress proxy, so the
lockdown runs and nothing answers it.
"""

import os
import threading
import time
from collections.abc import Callable, Generator, Iterator
from uuid import uuid4

import pytest
from docker import DockerClient
from docker.errors import ImageNotFound, NotFound
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.file_store.file_store import get_default_file_store
from onyx.llm.cancellation import AgentCancelled, CancellationSignal, cancellation_scope
from onyx.microvm.registry import get_sandbox_daemon_key
from onyx.server.features.build.sandbox.container.docker_runtime import DockerRuntime
from onyx.server.features.build.sandbox.container.harness_sandbox import (
    ContainerHarnessSandbox,
    IdleStopOutcome,
)
from onyx.server.features.build.sandbox.container.models import (
    ContainerSpec,
)
from onyx.server.features.build.sandbox.container.runtime import container_name
from onyx.server.features.build.sandbox.container.state import (
    get_container_record,
    update_container_record,
)
from onyx.server.features.build.sandbox.container.tls import new_daemon_credentials
from onyx.server.features.build.sandbox.container.transfer import FileStoreArchives
from onyx.server.features.build.sandbox.firecracker.harness_state import (
    WANTED_PREFIX,
    get_session_save,
    set_mark,
)
from onyx.server.features.build.sandbox.harness_base import (
    ExecSessionEndedError,
    SandboxFileNotFoundError,
    collect_exec_result,
)
from onyx.server.features.build.sandbox.labels import LABEL_SANDBOX_ID
from onyx.server.features.build.sandbox.models import (
    ExecCommandResult,
    ExecEvent,
    HarnessSandboxRef,
    chat_skill_folder,
)
from shared_configs.contextvars import POSTGRES_DEFAULT_SCHEMA

_DOCKER_SOCKET = os.environ.get("SANDBOX_DOCKER_SOCKET", "/var/run/docker.sock")
_IMAGE = os.environ.get(
    "SANDBOX_HARNESS_TEST_IMAGE", "onyxdotapp/craft-runtime:dev-container"
)
_TENANT = POSTGRES_DEFAULT_SCHEMA
_PROXY_HOST = "192.0.2.1"
# The image is amd64; on other hosts it runs emulated and starts slowly.
_START_SECONDS = 180.0


def _docker_and_image() -> bool:
    if not os.path.exists(_DOCKER_SOCKET):
        return False
    client = DockerClient(base_url=f"unix://{_DOCKER_SOCKET}")
    try:
        client.images.get(_IMAGE)
    except ImageNotFound:
        return False
    finally:
        client.close()
    return True


pytestmark = pytest.mark.skipif(
    not _docker_and_image(),
    reason="needs Docker and the harness test image (see the module docstring)",
)


@pytest.fixture(scope="module")
def docker_client() -> Generator[DockerClient, None, None]:
    client = DockerClient(base_url=f"unix://{_DOCKER_SOCKET}")
    yield client
    client.close()


@pytest.fixture(scope="module")
def network(docker_client: DockerClient) -> Generator[str, None, None]:
    name = f"onyx-harness-test-{uuid4().hex[:8]}"
    docker_client.networks.create(name, driver="bridge")
    yield name
    docker_client.networks.get(name).remove()


@pytest.fixture(scope="module")
def proxy_ca_volume(docker_client: DockerClient) -> Generator[str, None, None]:
    """A volume with a proxy CA certificate, as the sandbox proxy makes."""
    name = f"onyx-harness-test-ca-{uuid4().hex[:8]}"
    docker_client.volumes.create(name)
    ca_pem = new_daemon_credentials().cert_pem
    docker_client.containers.run(
        _IMAGE,
        entrypoint=["sh", "-c", 'printf "%s" "$CA" > /ca/ca.crt'],
        command=[],
        environment={"CA": ca_pem},
        user="0:0",
        volumes={name: {"bind": "/ca", "mode": "rw"}},
        remove=True,
    )
    yield name
    docker_client.volumes.get(name).remove(force=True)


@pytest.fixture(scope="module")
def runtime(
    docker_client: DockerClient, network: str, proxy_ca_volume: str
) -> DockerRuntime:
    return DockerRuntime(
        docker_client=docker_client,
        image=_IMAGE,
        network=network,
        proxy_host=_PROXY_HOST,
        proxy_ca_volume=proxy_ca_volume,
        publish_daemon_port=True,
    )


@pytest.fixture
def sandbox(
    runtime: DockerRuntime,
    db_session: Session,  # noqa: ARG001 - the file store records saves in Postgres.
    initialize_file_store: None,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
) -> ContainerHarnessSandbox:
    return ContainerHarnessSandbox(
        runtime=runtime,
        archives=FileStoreArchives(get_default_file_store()),
        idle_timeout_seconds=0,
        start_timeout_seconds=_START_SECONDS,
        turn_end_save_interval_seconds=0,
        orphan_grace_seconds=0,
    )


@pytest.fixture
def tenant_cache() -> CacheBackend:
    return get_cache_backend(tenant_id=_TENANT)


NewRef = Callable[[], HarnessSandboxRef]


@pytest.fixture
def new_ref(
    sandbox: ContainerHarnessSandbox, docker_client: DockerClient
) -> Iterator[NewRef]:
    refs: list[HarnessSandboxRef] = []

    def make() -> HarnessSandboxRef:
        ref = HarnessSandboxRef(
            tenant_id=_TENANT, sandbox_id=uuid4(), session_id=uuid4()
        )
        refs.append(ref)
        return ref

    yield make
    for ref in refs:
        sandbox.purge_sandbox(tenant_id=ref.tenant_id, sandbox_id=ref.sandbox_id)
        for left in docker_client.containers.list(
            all=True, filters={"label": f"{LABEL_SANDBOX_ID}={ref.sandbox_id}"}
        ):
            left.remove(force=True)


def _run(events: Generator[ExecEvent]) -> ExecCommandResult:
    return collect_exec_result(events)


def _make_idle(tenant_cache: CacheBackend, ref: HarnessSandboxRef) -> None:
    update_container_record(
        tenant_cache,
        ref.sandbox_id,
        lambda record: record.model_copy(update={"last_active": 0}),
    )


def _container_names(docker_client: DockerClient, ref: HarnessSandboxRef) -> list[str]:
    return [
        c.name or ""
        for c in docker_client.containers.list(
            all=True, filters={"label": f"{LABEL_SANDBOX_ID}={ref.sandbox_id}"}
        )
    ]


def test_exec_stdin_and_interrupt(
    sandbox: ContainerHarnessSandbox, new_ref: NewRef
) -> None:
    ref = new_ref()
    done = _run(sandbox.exec_command(ref, "echo hello; id -u; pwd"))
    assert done.exit_code == 0
    assert done.head.split() == [
        "hello",
        "1000",
        f"/home/onyx/workspaces/{ref.session_id}",
    ]

    waiting = _run(
        sandbox.exec_command(ref, "read line; echo got $line", yield_time_ms=250)
    )
    assert waiting.session_id is not None
    answered = _run(
        sandbox.write_stdin(ref, waiting.session_id, "abc\n", yield_time_ms=5000)
    )
    assert answered.exit_code == 0
    assert "got abc" in answered.head

    sleeping = _run(sandbox.exec_command(ref, "sleep 300", yield_time_ms=250))
    assert sleeping.session_id is not None
    interrupted = _run(
        sandbox.write_stdin(ref, sleeping.session_id, "\x03", yield_time_ms=5000)
    )
    assert interrupted.session_id is None
    assert interrupted.completion in ("canceled", "signaled")


def test_a_stop_kills_the_command(
    sandbox: ContainerHarnessSandbox, new_ref: NewRef
) -> None:
    ref = new_ref()
    started = _run(sandbox.exec_command(ref, "sleep 300", yield_time_ms=250))
    assert started.session_id is not None
    signal = CancellationSignal()
    stop = threading.Timer(0.5, signal.cancel)
    stop.start()
    begun = time.monotonic()
    with cancellation_scope(signal), pytest.raises(AgentCancelled):
        _run(sandbox.write_stdin(ref, started.session_id, yield_time_ms=30_000))
    stop.join()
    assert time.monotonic() - begun < 10
    assert not sandbox.is_busy(tenant_id=ref.tenant_id, sandbox_id=ref.sandbox_id)


def test_files_and_skills(sandbox: ContainerHarnessSandbox, new_ref: NewRef) -> None:
    ref = new_ref()
    sandbox.write_file(ref, "notes/a.txt", b"alpha")
    assert sandbox.read_file(ref, "notes/a.txt", max_bytes=100) == b"alpha"
    [info, missing] = sandbox.stat_files(ref, ["notes/a.txt", "nope"])
    assert info.exists and info.type == "file"
    assert not missing.exists
    sandbox.delete_listed_files(
        ref, "notes", lambda listing: [e.path for e in listing.entries], max_entries=10
    )
    with pytest.raises(SandboxFileNotFoundError):
        sandbox.read_file(ref, "notes/a.txt", max_bytes=100)

    assert sandbox.install_skill(
        ref,
        "hello",
        "v1",
        {"hello/SKILL.md": b"# hi", "hello/run.sh": b"#!/bin/sh\necho skill\n"},
    )
    assert not sandbox.install_skill(ref, "hello", "v1", {"hello/SKILL.md": b"# hi"})
    ran = _run(sandbox.exec_command(ref, f"{chat_skill_folder('hello')}/run.sh"))
    assert ran.exit_code == 0 and "skill" in ran.head


def test_the_proxy_ca_is_in_the_browser_trust_store(
    sandbox: ContainerHarnessSandbox, new_ref: NewRef
) -> None:
    ref = new_ref()
    listed = _run(sandbox.exec_command(ref, 'certutil -L -d "sql:$HOME/.pki/nssdb"'))
    assert listed.exit_code == 0
    assert "sandbox-proxy" in listed.head


def test_egress_is_locked_down(
    sandbox: ContainerHarnessSandbox, new_ref: NewRef
) -> None:
    ref = new_ref()
    blocked = _run(
        sandbox.exec_command(
            ref, "curl --noproxy '*' -sS -m 5 http://1.1.1.1/ >/dev/null"
        )
    )
    assert blocked.exit_code not in (None, 0)


def test_idle_stop_saves_and_the_next_call_restores(
    sandbox: ContainerHarnessSandbox,
    new_ref: NewRef,
    tenant_cache: CacheBackend,
    docker_client: DockerClient,
) -> None:
    ref = new_ref()
    sandbox.write_file(ref, "work/result.txt", b"kept")
    running = _run(sandbox.exec_command(ref, "sleep 300", yield_time_ms=250))
    assert running.session_id is not None
    first = get_container_record(tenant_cache, ref.sandbox_id)
    assert first is not None

    # Busy: a command runs, then a turn is in progress.
    _make_idle(tenant_cache, ref)
    assert sandbox.stop_if_idle(ref.tenant_id, ref.sandbox_id) is IdleStopOutcome.BUSY
    _run(sandbox.write_stdin(ref, running.session_id, "\x03", yield_time_ms=5000))
    set_mark(tenant_cache, ref.sandbox_id, f"turn:{ref.session_id}", 60)
    _make_idle(tenant_cache, ref)
    assert sandbox.stop_if_idle(ref.tenant_id, ref.sandbox_id) is IdleStopOutcome.BUSY
    sandbox.end_turn(ref)

    later = _run(sandbox.exec_command(ref, "sleep 300", yield_time_ms=250))
    assert later.session_id is not None
    _run(sandbox.write_stdin(ref, later.session_id, "\x03", yield_time_ms=5000))
    # A call in the last start window keeps the sandbox.
    _make_idle(tenant_cache, ref)
    assert sandbox.stop_if_idle(ref.tenant_id, ref.sandbox_id) is IdleStopOutcome.BUSY
    tenant_cache.delete(f"{WANTED_PREFIX}{ref.sandbox_id}")
    assert (
        sandbox.stop_if_idle(ref.tenant_id, ref.sandbox_id) is IdleStopOutcome.STOPPED
    )
    assert get_container_record(tenant_cache, ref.sandbox_id) is None
    assert (
        get_sandbox_daemon_key(tenant_cache, ref.sandbox_id, attempt=first.attempt)
        is None
    )
    assert _container_names(docker_client, ref) == []
    save = get_session_save(tenant_cache, ref.session_id)
    assert save is not None and save.file_id is not None

    # The next call starts a new container and restores the session.
    assert sandbox.read_file(ref, "work/result.txt", max_bytes=100) == b"kept"
    second = get_container_record(tenant_cache, ref.sandbox_id)
    assert second is not None and second.attempt == first.attempt + 1


def test_a_daemon_restart_is_a_new_generation(
    sandbox: ContainerHarnessSandbox,
    new_ref: NewRef,
    tenant_cache: CacheBackend,
    docker_client: DockerClient,
) -> None:
    ref = new_ref()
    running = _run(sandbox.exec_command(ref, "sleep 300", yield_time_ms=250))
    assert running.session_id is not None
    record = get_container_record(tenant_cache, ref.sandbox_id)
    assert record is not None
    docker_client.containers.get(record.name).restart(timeout=1)

    again = _run(sandbox.exec_command(ref, "echo back"))
    assert again.exit_code == 0
    restarted = get_container_record(tenant_cache, ref.sandbox_id)
    assert restarted is not None
    assert restarted.name == record.name
    assert restarted.generation == record.generation + 1
    with pytest.raises(ExecSessionEndedError):
        _run(sandbox.write_stdin(ref, running.session_id))


def test_purge_deletes_the_session_and_the_sandbox(
    sandbox: ContainerHarnessSandbox,
    new_ref: NewRef,
    tenant_cache: CacheBackend,
    docker_client: DockerClient,
) -> None:
    ref = new_ref()
    sandbox.write_file(ref, "a.txt", b"a")
    _make_idle(tenant_cache, ref)
    tenant_cache.delete(f"{WANTED_PREFIX}{ref.sandbox_id}")
    assert (
        sandbox.stop_if_idle(ref.tenant_id, ref.sandbox_id) is IdleStopOutcome.STOPPED
    )
    assert get_session_save(tenant_cache, ref.session_id) is not None
    sandbox.write_file(ref, "b.txt", b"b")

    sandbox.purge_session(
        tenant_id=ref.tenant_id, sandbox_id=ref.sandbox_id, session_id=ref.session_id
    )
    assert get_session_save(tenant_cache, ref.session_id) is None
    other = ref.model_copy(update={"session_id": uuid4()})
    gone = _run(
        sandbox.exec_command(other, f"test -e /home/onyx/workspaces/{ref.session_id}")
    )
    assert gone.exit_code == 1

    sandbox.purge_sandbox(tenant_id=ref.tenant_id, sandbox_id=ref.sandbox_id)
    assert get_container_record(tenant_cache, ref.sandbox_id) is None
    assert _container_names(docker_client, ref) == []


def test_the_sweep_deletes_orphans_and_lists_idle_sandboxes(
    sandbox: ContainerHarnessSandbox,
    runtime: DockerRuntime,
    new_ref: NewRef,
    tenant_cache: CacheBackend,
    docker_client: DockerClient,
) -> None:
    kept = new_ref()
    _run(sandbox.exec_command(kept, "true"))
    _make_idle(tenant_cache, kept)
    orphan = new_ref()
    name = container_name(orphan.sandbox_id, 1)
    runtime.create(
        ContainerSpec(
            tenant_id=orphan.tenant_id,
            sandbox_id=orphan.sandbox_id,
            attempt=1,
            name=name,
        ),
        new_daemon_credentials(),
        time.monotonic() + _START_SECONDS,
    )

    idle = sandbox.sweep(time.monotonic() + 60)
    assert (kept.tenant_id, kept.sandbox_id) in {
        (key.tenant_id, key.sandbox_id) for key in idle
    }
    with pytest.raises(NotFound):
        docker_client.containers.get(name)
    assert _container_names(docker_client, kept) != []
