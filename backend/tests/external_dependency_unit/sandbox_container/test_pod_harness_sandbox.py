"""The container harness sandbox as Kubernetes pods, on a kind cluster.

Set `SANDBOX_HARNESS_KIND_CONTEXT` to a kubeconfig context whose cluster
has the image (`SANDBOX_HARNESS_TEST_IMAGE`) loaded, for example:

    kind create cluster --name harness
    kind load docker-image onyxdotapp/craft-runtime:dev-container --name harness
    SANDBOX_HARNESS_KIND_CONTEXT=kind-harness uv run --env-file .vscode/.env \\
        pytest backend/tests/external_dependency_unit/sandbox_container

The host cannot reach pod IPs, so the test dials each pod through
`kubectl port-forward`. The pod has no egress proxy (no init container).
"""

import os
import re
import select
import subprocess
import time
from collections.abc import Generator, Iterator
from uuid import uuid4

import pytest
from kubernetes import client, config
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.sandbox.container.harness_sandbox import (
    ContainerHarnessSandbox,
    IdleStopOutcome,
)
from onyx.server.features.build.sandbox.container.models import (
    ContainerSpec,
    DaemonCredentials,
    RuntimeContainer,
)
from onyx.server.features.build.sandbox.container.pod_runtime import (
    PodRuntime,
    daemon_secret_name,
    harness_pod_labels,
)
from onyx.server.features.build.sandbox.container.state import (
    get_container_record,
    update_container_record,
)
from onyx.server.features.build.sandbox.container.transfer import FileStoreArchives
from onyx.server.features.build.sandbox.firecracker.harness_state import WANTED_PREFIX
from onyx.server.features.build.sandbox.harness_base import collect_exec_result
from onyx.server.features.build.sandbox.models import HarnessSandboxRef
from shared_configs.contextvars import POSTGRES_DEFAULT_SCHEMA

_CONTEXT = os.environ.get("SANDBOX_HARNESS_KIND_CONTEXT", "")
_IMAGE = os.environ.get(
    "SANDBOX_HARNESS_TEST_IMAGE", "onyxdotapp/craft-runtime:dev-container"
)
_TEMPLATE = "harness-sandbox-pod"
_START_SECONDS = 240.0
_FORWARD_START_SECONDS = 30.0
_FORWARD_LINE = re.compile(r"Forwarding from 127\.0\.0\.1:(\d+)")

pytestmark = pytest.mark.skipif(
    not _CONTEXT, reason="SANDBOX_HARNESS_KIND_CONTEXT is not set"
)


class _ForwardedPodRuntime(PodRuntime):
    """Dials each pod through a local port-forward."""

    def __init__(self, core_api: client.CoreV1Api, namespace: str) -> None:
        super().__init__(
            core_api=core_api,
            namespace=namespace,
            template_name=_TEMPLATE,
            proxy_host="",
        )
        self._forwards: dict[str, tuple[subprocess.Popen[str], str]] = {}

    def _forward(self, name: str) -> str:
        existing = self._forwards.get(name)
        if existing is not None and existing[0].poll() is None:
            return existing[1]
        process = subprocess.Popen(
            [
                "kubectl",
                "--context",
                _CONTEXT,
                "-n",
                self._namespace,
                "port-forward",
                f"pod/{name}",
                ":8052",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if process.stdout is None:
            raise RuntimeError("Bug: port-forward has no stdout")
        ready, _, _ = select.select([process.stdout], [], [], _FORWARD_START_SECONDS)
        line = process.stdout.readline() if ready else ""
        match = _FORWARD_LINE.search(line)
        if match is None:
            process.kill()
            process.wait()
            raise RuntimeError(f"port-forward did not start: {line!r}")
        address = f"127.0.0.1:{match.group(1)}"
        self._forwards[name] = (process, address)
        return address

    def create(
        self, spec: ContainerSpec, credentials: DaemonCredentials, deadline: float
    ) -> str:
        super().create(spec, credentials, deadline)
        return self._forward(spec.name)

    def inspect(self, name: str) -> RuntimeContainer | None:
        found = super().inspect(name)
        if found is None or found.address is None:
            return found
        return found.model_copy(update={"address": self._forward(name)})

    def delete(self, name: str) -> None:
        forward = self._forwards.pop(name, None)
        if forward is not None:
            forward[0].kill()
        super().delete(name)

    def close(self) -> None:
        for process, _ in self._forwards.values():
            process.kill()
            process.wait()


@pytest.fixture(scope="module")
def core_api() -> client.CoreV1Api:
    return client.CoreV1Api(config.new_client_from_config(context=_CONTEXT))


@pytest.fixture(scope="module")
def namespace(core_api: client.CoreV1Api) -> Generator[str, None, None]:
    name = f"onyx-harness-test-{uuid4().hex[:8]}"
    core_api.create_namespace(
        client.V1Namespace(metadata=client.V1ObjectMeta(name=name))
    )
    try:
        core_api.create_namespaced_pod_template(
            namespace=name,
            body=client.V1PodTemplate(
                metadata=client.V1ObjectMeta(name=_TEMPLATE),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={"app.kubernetes.io/component": "sandbox"}
                    ),
                    spec=client.V1PodSpec(
                        enable_service_links=False,
                        termination_grace_period_seconds=1,
                        security_context=client.V1PodSecurityContext(
                            run_as_non_root=True,
                            run_as_user=1000,
                            fs_group=1000,
                            seccomp_profile=client.V1SeccompProfile(
                                type="RuntimeDefault"
                            ),
                        ),
                        containers=[
                            client.V1Container(
                                name="sandbox",
                                image=_IMAGE,
                                image_pull_policy="Never",
                                security_context=client.V1SecurityContext(
                                    allow_privilege_escalation=False,
                                    capabilities=client.V1Capabilities(drop=["ALL"]),
                                ),
                            )
                        ],
                    ),
                ),
            ),
        )
        yield name
    finally:
        core_api.delete_namespace(name)


@pytest.fixture
def runtime(
    core_api: client.CoreV1Api, namespace: str
) -> Iterator[_ForwardedPodRuntime]:
    runtime = _ForwardedPodRuntime(core_api, namespace)
    yield runtime
    runtime.close()


@pytest.fixture
def sandbox(
    runtime: _ForwardedPodRuntime,
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


def test_a_pod_sandbox_runs_saves_stops_and_restores(
    sandbox: ContainerHarnessSandbox,
    runtime: _ForwardedPodRuntime,
    core_api: client.CoreV1Api,
    namespace: str,
) -> None:
    ref = HarnessSandboxRef(
        tenant_id=POSTGRES_DEFAULT_SCHEMA, sandbox_id=uuid4(), session_id=uuid4()
    )
    tenant_cache = get_cache_backend(tenant_id=ref.tenant_id)
    try:
        ran = collect_exec_result(sandbox.exec_command(ref, "id -u; echo pod"))
        assert ran.exit_code == 0
        assert ran.head.split() == ["1000", "pod"]
        sandbox.write_file(ref, "kept.txt", b"from the pod")
        record = get_container_record(tenant_cache, ref.sandbox_id)
        assert record is not None

        pod = core_api.read_namespaced_pod(name=record.name, namespace=namespace)
        assert pod.spec.restart_policy == "Always"
        secret = core_api.read_namespaced_secret(
            name=daemon_secret_name(record.name), namespace=namespace
        )
        [owner] = secret.metadata.owner_references
        assert owner.kind == "Pod" and owner.uid == pod.metadata.uid

        update_container_record(
            tenant_cache,
            ref.sandbox_id,
            lambda r: r.model_copy(update={"last_active": 0}),
        )
        tenant_cache.delete(f"{WANTED_PREFIX}{ref.sandbox_id}")
        assert (
            sandbox.stop_if_idle(ref.tenant_id, ref.sandbox_id)
            is IdleStopOutcome.STOPPED
        )
        assert runtime._wait_for_resource_deletion("pod", record.name, 60)

        assert sandbox.read_file(ref, "kept.txt", max_bytes=100) == b"from the pod"
        restarted = get_container_record(tenant_cache, ref.sandbox_id)
        assert restarted is not None and restarted.attempt == record.attempt + 1
    finally:
        sandbox.purge_sandbox(tenant_id=ref.tenant_id, sandbox_id=ref.sandbox_id)


def test_the_sweep_deletes_a_daemon_secret_without_its_pod(
    sandbox: ContainerHarnessSandbox, core_api: client.CoreV1Api, namespace: str
) -> None:
    """A create that stopped after the Secret leaves no pod; the sweep
    deletes the Secret."""
    spec = ContainerSpec(
        tenant_id=POSTGRES_DEFAULT_SCHEMA,
        sandbox_id=uuid4(),
        attempt=1,
        name=f"harness-{uuid4()}-1",
    )
    secret_name = daemon_secret_name(spec.name)
    core_api.create_namespaced_secret(
        namespace=namespace,
        body=client.V1Secret(
            metadata=client.V1ObjectMeta(
                name=secret_name, labels=harness_pod_labels(spec)
            ),
            string_data={"key": "k"},
        ),
    )
    sandbox.sweep(time.monotonic() + 60)
    names = [
        s.metadata.name
        for s in core_api.list_namespaced_secret(namespace=namespace).items
    ]
    assert secret_name not in names
