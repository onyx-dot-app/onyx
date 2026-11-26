"""Harness sandboxes as Kubernetes pods (`SANDBOX_BACKEND=kubernetes`).

A pod starts from the harness PodTemplate (`SANDBOX_HARNESS_POD_TEMPLATE` in
`SANDBOX_NAMESPACE`), which owns the image, the `firewall-init` init
container and the proxy CA, scheduling (node pool, tolerations,
`runtimeClassName` for gVisor), the security context and the proxy env.
Its container `sandbox` runs the craft-runtime `container` image. The
overlay here sets what is per pod or part of the daemon contract: the
labels, the daemon arguments, port and readiness probe, the daemon's key
and TLS files (a Secret per pod, deleted with the pod), the sizes
(`SANDBOX_POD_*`), the restart policy, and the proxy hostAlias. PIDs are
limited only by the kubelet's `podPidsLimit`.
"""

from datetime import UTC, datetime

from kubernetes import client
from kubernetes.client.rest import ApiException

from onyx.server.features.build.configs import (
    SANDBOX_HARNESS_DAEMON_PORT,
    SANDBOX_HARNESS_POD_TEMPLATE,
    SANDBOX_NAMESPACE,
    SANDBOX_POD_CPU_LIMIT,
    SANDBOX_POD_CPU_REQUEST,
    SANDBOX_POD_EPHEMERAL_STORAGE_LIMIT,
    SANDBOX_POD_EPHEMERAL_STORAGE_REQUEST,
    SANDBOX_POD_MEMORY_LIMIT,
    SANDBOX_POD_MEMORY_REQUEST,
    SANDBOX_PROXY_HOST,
    SANDBOX_PROXY_NAMESPACE,
)
from onyx.server.features.build.sandbox.container.models import (
    ContainerRuntimeKind,
    ContainerSpec,
    ContainerState,
    DaemonCredentials,
    RuntimeContainer,
)
from onyx.server.features.build.sandbox.container.runtime import (
    DAEMON_CERT_FILE,
    DAEMON_FILES_DIR,
    DAEMON_KEY_FILE,
    DAEMON_PRIVATE_KEY_FILE,
    ContainerRuntime,
    daemon_args,
    harness_labels,
    parse_labels,
)
from onyx.server.features.build.sandbox.kubernetes.k8s_client import (
    build_runtime_api_client,
    load_kube_config,
)
from onyx.server.features.build.sandbox.kubernetes.pods import (
    SandboxPodOps,
    require_container,
)
from onyx.server.features.build.sandbox.labels import (
    LABEL_K8S_COMPONENT,
    LABEL_K8S_COMPONENT_SANDBOX,
    LABEL_K8S_MANAGED_BY,
    LABEL_K8S_MANAGED_BY_ONYX,
    LABEL_SANDBOX_KIND,
    SANDBOX_KIND_HARNESS,
)
from onyx.server.features.build.sandbox.models import SESSION_WORKSPACE_ROOT
from onyx.utils.logger import setup_logger

logger = setup_logger()

DAEMON_CONTAINER_NAME = "sandbox"
_DAEMON_FILES_VOLUME = "daemon-files"
# Session directories outlive a daemon (container) restart in the pod.
_WORKSPACES_VOLUME = "workspaces"
_OVERLAY_VOLUMES = frozenset({_DAEMON_FILES_VOLUME, _WORKSPACES_VOLUME})
_ENTRYPOINT = "/usr/local/bin/sandbox-entrypoint"
# The proxy hostname in the sandbox: the firewall blocks DNS, so the pod
# gets the proxy's ClusterIP as a hostAlias (as Craft pods do).
_PROXY_ALIAS = "sandbox-proxy"
_PROXY_RESOLVE_ATTEMPTS = 3
_PROXY_RESOLVE_BACKOFF_SECONDS = 0.5
_HARNESS_SELECTOR = (
    f"{LABEL_SANDBOX_KIND}={SANDBOX_KIND_HARNESS},"
    f"{LABEL_K8S_MANAGED_BY}={LABEL_K8S_MANAGED_BY_ONYX}"
)


_SECRET_SUFFIX = "-daemon"


def daemon_secret_name(pod_name: str) -> str:
    return f"{pod_name}{_SECRET_SUFFIX}"


def overlay_harness_pod(
    spec: client.V1PodSpec,
    *,
    template_name: str,
    pod_name: str,
    proxy_ip: str | None,
    daemon_port: int = SANDBOX_HARNESS_DAEMON_PORT,
) -> None:
    """Set the per-pod and contract fields of a harness pod on a copy of the
    PodTemplate's spec."""
    container = require_container(spec, DAEMON_CONTAINER_NAME, template_name)
    container.command = [_ENTRYPOINT]
    container.args = daemon_args(daemon_port)
    container.ports = [
        client.V1ContainerPort(
            name="sandboxd", container_port=daemon_port, protocol="TCP"
        )
    ]
    container.readiness_probe = client.V1Probe(
        tcp_socket=client.V1TCPSocketAction(port=daemon_port),
        period_seconds=1,
        failure_threshold=3,
    )
    container.resources = client.V1ResourceRequirements(
        requests={
            "cpu": SANDBOX_POD_CPU_REQUEST,
            "memory": SANDBOX_POD_MEMORY_REQUEST,
            "ephemeral-storage": SANDBOX_POD_EPHEMERAL_STORAGE_REQUEST,
        },
        limits={
            "cpu": SANDBOX_POD_CPU_LIMIT,
            "memory": SANDBOX_POD_MEMORY_LIMIT,
            "ephemeral-storage": SANDBOX_POD_EPHEMERAL_STORAGE_LIMIT,
        },
    )
    container.volume_mounts = [
        mount
        for mount in container.volume_mounts or []
        if mount.name not in _OVERLAY_VOLUMES
    ] + [
        client.V1VolumeMount(
            name=_DAEMON_FILES_VOLUME, mount_path=DAEMON_FILES_DIR, read_only=True
        ),
        client.V1VolumeMount(
            name=_WORKSPACES_VOLUME, mount_path=SESSION_WORKSPACE_ROOT
        ),
    ]
    spec.volumes = [
        volume for volume in spec.volumes or [] if volume.name not in _OVERLAY_VOLUMES
    ] + [
        client.V1Volume(
            name=_WORKSPACES_VOLUME, empty_dir=client.V1EmptyDirVolumeSource()
        ),
        client.V1Volume(
            name=_DAEMON_FILES_VOLUME,
            secret=client.V1SecretVolumeSource(
                secret_name=daemon_secret_name(pod_name),
                # Root's files, readable by the pod's fsGroup (the sandbox user).
                default_mode=0o440,
                items=[
                    client.V1KeyToPath(key=name, path=name)
                    for name in (
                        DAEMON_KEY_FILE,
                        DAEMON_CERT_FILE,
                        DAEMON_PRIVATE_KEY_FILE,
                    )
                ],
            ),
        ),
    ]
    # A daemon that exits restarts in the same pod (same IP); calls on its old
    # executions then end (ExecSessionEndedError).
    spec.restart_policy = "Always"
    spec.automount_service_account_token = False
    if proxy_ip is not None:
        spec.host_aliases = [client.V1HostAlias(ip=proxy_ip, hostnames=[_PROXY_ALIAS])]


def harness_pod_labels(spec: ContainerSpec) -> dict[str, str]:
    return {
        LABEL_K8S_COMPONENT: LABEL_K8S_COMPONENT_SANDBOX,
        LABEL_K8S_MANAGED_BY: LABEL_K8S_MANAGED_BY_ONYX,
        **harness_labels(spec),
    }


class PodRuntime(SandboxPodOps, ContainerRuntime):
    kind = ContainerRuntimeKind.POD
    _ready_container_name = DAEMON_CONTAINER_NAME

    def __init__(
        self,
        *,
        core_api: client.CoreV1Api | None = None,
        namespace: str = SANDBOX_NAMESPACE,
        template_name: str = SANDBOX_HARNESS_POD_TEMPLATE,
        proxy_host: str = SANDBOX_PROXY_HOST,
        daemon_port: int = SANDBOX_HARNESS_DAEMON_PORT,
    ) -> None:
        if core_api is None:
            load_kube_config()
            core_api = client.CoreV1Api(api_client=build_runtime_api_client())
        self._core_api = core_api
        self._namespace = namespace
        self._template_name = template_name
        self._proxy_host = proxy_host
        self._port = daemon_port

    def build_pod(self, spec: ContainerSpec) -> client.V1Pod:
        proxy_ip = (
            self._resolve_proxy_cluster_ip(
                self._proxy_host,
                SANDBOX_PROXY_NAMESPACE,
                _PROXY_RESOLVE_ATTEMPTS,
                _PROXY_RESOLVE_BACKOFF_SECONDS,
            )
            if self._proxy_host
            else None
        )
        return self._build_pod_from_template(
            template_name=self._template_name,
            pod_name=spec.name,
            labels=harness_pod_labels(spec),
            overlay=lambda pod_spec: overlay_harness_pod(
                pod_spec,
                template_name=self._template_name,
                pod_name=spec.name,
                proxy_ip=proxy_ip,
                daemon_port=self._port,
            ),
        )

    def prepare(self) -> None:
        # The image prepuller and the kubelet pull images.
        return None

    def create(
        self, spec: ContainerSpec, credentials: DaemonCredentials, deadline: float
    ) -> str:
        pod = self.build_pod(spec)
        secret_name = daemon_secret_name(spec.name)
        self._core_api.create_namespaced_secret(
            namespace=self._namespace,
            body=client.V1Secret(
                metadata=client.V1ObjectMeta(
                    name=secret_name, labels=harness_pod_labels(spec)
                ),
                type="Opaque",
                string_data={
                    DAEMON_KEY_FILE: credentials.key.get_secret_value(),
                    DAEMON_CERT_FILE: credentials.cert_pem,
                    DAEMON_PRIVATE_KEY_FILE: credentials.private_key_pem.get_secret_value(),
                },
            ),
        )
        try:
            created: client.V1Pod = self._core_api.create_namespaced_pod(
                namespace=self._namespace, body=pod
            )
            # The Secret goes with its pod (garbage collection).
            self._core_api.patch_namespaced_secret(
                name=secret_name,
                namespace=self._namespace,
                body={
                    "metadata": {
                        "ownerReferences": [
                            {
                                "apiVersion": "v1",
                                "kind": "Pod",
                                "name": spec.name,
                                "uid": created.metadata.uid,
                            }
                        ]
                    }
                },
            )
            if not self._wait_for_pod_ready(spec.name, deadline):
                raise TimeoutError(f"sandbox pod {spec.name} did not become ready")
            ready: client.V1Pod = self._core_api.read_namespaced_pod(
                name=spec.name, namespace=self._namespace
            )
            if not ready.status.pod_ip:
                raise RuntimeError(f"sandbox pod {spec.name} has no IP")
        except BaseException:
            self.delete(spec.name)
            raise
        logger.info("sandbox_pod_created name=%s", spec.name)
        return f"{ready.status.pod_ip}:{self._port}"

    def _runtime_container(self, pod: client.V1Pod) -> RuntimeContainer:
        tenant_id, sandbox_id, attempt = parse_labels(pod.metadata.labels or {})
        phase = pod.status.phase if pod.status else None
        failed = pod.metadata.deletion_timestamp is not None or phase in (
            "Failed",
            "Succeeded",
        )
        pod_ip = pod.status.pod_ip if pod.status else None
        return RuntimeContainer(
            name=pod.metadata.name,
            tenant_id=tenant_id,
            sandbox_id=sandbox_id,
            attempt=attempt,
            state=ContainerState.FAILED if failed else ContainerState.RUNNING,
            address=f"{pod_ip}:{self._port}" if pod_ip else None,
            created_at=pod.metadata.creation_timestamp or datetime.now(UTC),
        )

    def inspect(self, name: str) -> RuntimeContainer | None:
        try:
            pod: client.V1Pod = self._core_api.read_namespaced_pod(
                name=name, namespace=self._namespace
            )
        except ApiException as e:
            if e.status == 404:
                return None
            raise
        if (pod.metadata.labels or {}).get(LABEL_SANDBOX_KIND) != SANDBOX_KIND_HARNESS:
            return None
        return self._runtime_container(pod)

    def delete(self, name: str) -> None:
        for resource, delete_call in (
            (name, self._core_api.delete_namespaced_pod),
            (daemon_secret_name(name), self._core_api.delete_namespaced_secret),
        ):
            try:
                delete_call(
                    name=resource, namespace=self._namespace, grace_period_seconds=0
                )
            except ApiException as e:
                if e.status != 404:
                    raise
        logger.info("sandbox_pod_deleted name=%s", name)

    def list_containers(self, deadline: float) -> list[RuntimeContainer]:
        """The harness pods, and a failed entry for each daemon Secret whose
        pod does not exist (a create that stopped between the two), so the
        sweep deletes it."""
        found = [
            self._runtime_container(pod)
            for pod in self._list_all_pages(
                self._core_api.list_namespaced_pod, _HARNESS_SELECTOR, deadline
            )
            if isinstance(pod, client.V1Pod)
        ]
        pods = {item.name for item in found}
        for secret in self._list_all_pages(
            self._core_api.list_namespaced_secret, _HARNESS_SELECTOR, deadline
        ):
            if not isinstance(secret, client.V1Secret):
                continue
            name = secret.metadata.name.removesuffix(_SECRET_SUFFIX)
            if name in pods or not secret.metadata.name.endswith(_SECRET_SUFFIX):
                continue
            tenant_id, sandbox_id, attempt = parse_labels(secret.metadata.labels or {})
            found.append(
                RuntimeContainer(
                    name=name,
                    tenant_id=tenant_id,
                    sandbox_id=sandbox_id,
                    attempt=attempt,
                    state=ContainerState.FAILED,
                    address=None,
                    created_at=secret.metadata.creation_timestamp or datetime.now(UTC),
                )
            )
        return found
