"""Kubernetes resource lifecycle for Firecracker-backed Craft sandboxes."""

from __future__ import annotations

import base64
import copy
import ipaddress
import json
import math
import secrets
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import BinaryIO, cast
from uuid import UUID

from kubernetes import client
from kubernetes.client.rest import ApiException
from urllib3.exceptions import HTTPError
from urllib3.response import HTTPResponse

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS
from onyx.db.enums import SandboxStatus
from onyx.server.features.build.configs import (
    ONYX_SERVER_URL,
    OPENCODE_SERVE_PORT,
    OPENCODE_SERVER_PASSWORD,
    SANDBOX_NAMESPACE,
    SANDBOX_NEXTJS_PORT_END,
    SANDBOX_NEXTJS_PORT_START,
    SANDBOX_PROXY_HOST,
    SANDBOX_PROXY_NAMESPACE,
)
from onyx.server.features.build.sandbox.exec import ExecClient, FramedStdin
from onyx.server.features.build.sandbox.image.guest.security import GUEST_PYTHON
from onyx.server.features.build.sandbox.k8s_client import build_core_v1_api
from onyx.server.features.build.sandbox.labels import (
    LABEL_K8S_COMPONENT,
    LABEL_K8S_COMPONENT_SANDBOX,
    LABEL_K8S_MANAGED_BY,
    LABEL_K8S_MANAGED_BY_ONYX,
    LABEL_PROVISIONING_ATTEMPT,
    LABEL_SANDBOX_ID,
    LABEL_SANDBOX_PROTOCOL,
    LABEL_TENANT_ID,
    SANDBOX_PROTOCOL_VERSION,
)
from onyx.server.features.build.sandbox.models import (
    ExecResult,
    LegacySandboxError,
    SandboxExecError,
    SandboxInfo,
    SandboxProvisionContentionError,
)
from onyx.server.features.build.sandbox.nextjs_dev import allowed_dev_origins
from onyx.server.features.build.sandbox.runtime import SandboxRuntime
from onyx.server.features.build.sandbox.util.api_url_check import (
    validate_sandbox_api_url,
)
from onyx.server.features.build.sandbox.util.opencode_config import (
    build_opencode_base_config,
)
from onyx.server.features.build.timeouts import (
    POLL_INTERVAL_SECONDS,
    PROVISION_DEADLINE_SECONDS,
    RUNTIME_TEARDOWN_SECONDS,
)
from onyx.server.features.build.utils import get_opencode_disabled_tools
from onyx.server.metrics.craft_sandbox import (
    SandboxProvisionPhase,
    time_provision_phase,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_PROXY_ALIAS = "sandbox-proxy"
_SANDBOX_CONTAINER_NAME = "sandbox"
_FIREWALL_INIT_CONTAINER_NAME = "sandbox-firewall"
_PODTEMPLATE_NAME = "sandbox-pod"
_REQUIRED_RUNTIME_CLASS_NAME = "kata-fc"

_OPENCODE_CONNECT_APP_PLUGIN_PATH = "/workspace/opencode-plugins/connect-app.ts"
_OPENCODE_TURN_BUDGET_PLUGIN_PATH = "/workspace/opencode-plugins/turn-budget.ts"
_OPENCODE_WEBAPP_PLUGIN_PATH = "/workspace/opencode-plugins/webapp.ts"
_OPENCODE_SESSION_TAG_PLUGIN_PATH = "/workspace/opencode-plugins/session-proxy-tag.ts"

_PROXY_RESOLVE_RETRY_ATTEMPTS = 5
_PROXY_RESOLVE_RETRY_BACKOFF_S = 0.5


def _provisioning_lock_key(sandbox_id: UUID) -> str:
    return f"sandbox_provision_{sandbox_id}"


@contextmanager
def _provisioning_lock(sandbox_id: UUID, tenant_id: str) -> Iterator[None]:
    try:
        lock = get_cache_backend(tenant_id=tenant_id).lock(
            _provisioning_lock_key(sandbox_id),
            timeout=PROVISION_DEADLINE_SECONDS,
        )
        acquired = lock.acquire(blocking=False)
    except CACHE_TRANSIENT_ERRORS as error:
        logger.warning(
            "Provisioning lock unavailable for sandbox %s (%s); proceeding",
            sandbox_id,
            error,
            exc_info=True,
        )
        yield
        return

    if not acquired:
        raise SandboxProvisionContentionError(
            f"A concurrent provisioner holds the lock for sandbox {sandbox_id}"
        )
    try:
        yield
    finally:
        try:
            if lock.owned():
                lock.release()
        except CACHE_TRANSIENT_ERRORS:
            logger.warning(
                "Provisioning lock release failed for sandbox %s; relying on TTL",
                sandbox_id,
                exc_info=True,
            )


class KubernetesRuntime(SandboxRuntime):
    """Owns Kubernetes objects for the single Firecracker sandbox implementation."""

    _OPENCODE_PASSWORD_SECRET_KEY = "password"
    _OPENCODE_CONFIG_SECRET_KEY = "config"

    def __init__(self) -> None:
        self.core_api = build_core_v1_api()
        self.configuration = self.core_api.api_client.configuration
        self.namespace = SANDBOX_NAMESPACE
        self._exec = ExecClient(self.configuration, self.namespace)

    def pod_name(self, sandbox_id: str | UUID) -> str:
        return f"sandbox-{UUID(str(sandbox_id)).hex}"

    def service_url(self, sandbox_id: str | UUID, port: int) -> str:
        service_name = self.pod_name(sandbox_id)
        return f"http://{service_name}.{self.namespace}.svc.cluster.local:{port}"

    def opencode_service_url(self, sandbox_id: str | UUID) -> str:
        return self.service_url(sandbox_id, OPENCODE_SERVE_PORT)

    def get_pod(self, sandbox_id: str | UUID) -> client.V1Pod | None:
        """Return a conforming Firecracker sandbox pod, or None if absent.

        A pod with the same generated name but old labels/topology raises
        LegacySandboxError so callers never mistake it for safe-to-manage.
        """
        try:
            pod = cast(
                client.V1Pod,
                self.core_api.read_namespaced_pod(
                    name=self.pod_name(sandbox_id),
                    namespace=self.namespace,
                ),
            )
        except ApiException as error:
            if error.status == 404:
                legacy_name = f"sandbox-{str(sandbox_id)[:8]}"
                try:
                    legacy = self.core_api.read_namespaced_pod(
                        name=legacy_name, namespace=self.namespace
                    )
                except ApiException as legacy_error:
                    if legacy_error.status == 404:
                        return None
                    raise
                if (legacy.metadata.labels or {}).get(LABEL_SANDBOX_ID) == str(
                    sandbox_id
                ):
                    raise LegacySandboxError(
                        f"Legacy sandbox {legacy_name} must be snapshotted and drained before this upgrade"
                    )
                return None
            raise
        self._validate_conforming_pod(pod)
        if pod.metadata.deletion_timestamp:
            return None
        return pod

    def exists(self, sandbox_id: UUID) -> bool:
        return self.get_pod(sandbox_id) is not None

    def read_password(self, sandbox_id: str | UUID) -> str | None:
        secret_name = self._opencode_secret_name(sandbox_id)
        try:
            secret = self.core_api.read_namespaced_secret(
                name=secret_name, namespace=self.namespace
            )
        except ApiException as error:
            if error.status == 404:
                return None
            raise
        data = secret.data or {}
        self._validate_owned_labels(secret.metadata.labels or {}, secret_name)
        raw = data.get(self._OPENCODE_PASSWORD_SECRET_KEY)
        if not raw:
            return None
        return base64.b64decode(raw).decode("utf-8")

    def stream_logs(
        self,
        sandbox_id: UUID,
        *,
        tail_lines: int = 200,
    ) -> Iterator[str]:
        pod_name = self.pod_name(sandbox_id)
        try:
            stream = cast(
                HTTPResponse,
                self.core_api.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=self.namespace,
                    container=_SANDBOX_CONTAINER_NAME,
                    follow=True,
                    tail_lines=tail_lines,
                    _preload_content=False,
                ),
            )
        except ApiException as error:
            logger.warning(
                "stream_pod_logs: read_namespaced_pod_log failed for %s/%s: %s",
                pod_name,
                _SANDBOX_CONTAINER_NAME,
                error,
            )
            return
        buffer = ""
        try:
            for chunk in stream.stream(decode_content=True):
                if not chunk:
                    continue
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    yield line
        finally:
            try:
                stream.close()
            except Exception:
                pass

    @staticmethod
    def guest_command(operation: str, metadata: dict[str, object]) -> list[str]:
        if operation in {"serve", "serve-user", "_restore-history"}:
            raise ValueError(f"{operation} is not a public guest operation")
        return [
            GUEST_PYTHON,
            "-I",
            "-m",
            "onyx_guest",
            operation,
            json.dumps(metadata, separators=(",", ":")),
        ]

    def _helper_target(self, sandbox_id: UUID, timeout: float) -> tuple[str, float]:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Sandbox exec timeout must be finite and positive")
        deadline = time.monotonic() + timeout
        pod_name = self.pod_name(sandbox_id)
        try:
            pod = self.core_api.read_namespaced_pod(
                name=pod_name, namespace=self.namespace, _request_timeout=timeout
            )
        except ApiException as error:
            if error.status == 404:
                raise SandboxExecError(
                    f"Sandbox pod {pod_name} is unavailable"
                ) from error
            raise SandboxExecError(
                f"Sandbox pod {pod_name} validation failed: Kubernetes API {error.status}"
            ) from error
        except (HTTPError, OSError, TimeoutError) as error:
            raise SandboxExecError(
                "Sandbox pod validation connection failed"
            ) from error
        self._validate_conforming_pod(pod)
        if pod.metadata.deletion_timestamp:
            raise SandboxExecError(f"Sandbox pod {pod_name} is being deleted")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SandboxExecError("Sandbox exec deadline exceeded")
        return pod_name, remaining

    def helper(
        self,
        sandbox_id: UUID,
        operation: str,
        metadata: dict[str, object],
        *,
        stdin: bytes | BinaryIO | None = None,
        timeout: float,
    ) -> ExecResult:
        command = self.guest_command(operation, metadata)
        pod_name, remaining = self._helper_target(sandbox_id, timeout)
        return self._exec.run(
            pod_name,
            command,
            stdin=FramedStdin(stdin),
            timeout=remaining,
        )

    def helper_stream(
        self,
        sandbox_id: UUID,
        operation: str,
        metadata: dict[str, object],
        *,
        stdin: bytes | BinaryIO | None = None,
        timeout: float,
    ) -> Iterator[bytes]:
        command = self.guest_command(operation, metadata)
        pod_name, remaining = self._helper_target(sandbox_id, timeout)
        yield from self._exec.stream(
            pod_name,
            command,
            stdin=FramedStdin(stdin),
            timeout=remaining,
        )

    def health_check(self, sandbox_id: UUID) -> bool:
        pod = self.get_pod(sandbox_id)
        if pod is None:
            return False
        return self._sandbox_container_is_ready(pod)

    def provision(
        self,
        sandbox_id: UUID,
        user_id: UUID,
        tenant_id: str,
        onyx_pat: str | None,
        provisioning_attempt_number: int,
        initialize: Callable[[UUID, float], None],
    ) -> SandboxInfo:
        logger.info(
            "Starting Firecracker sandbox provisioning for sandbox %s, user %s, tenant %s",
            sandbox_id,
            user_id,
            tenant_id,
        )
        self._validate_provisioning_config(onyx_pat)
        with _provisioning_lock(sandbox_id, tenant_id):
            deadline = time.monotonic() + PROVISION_DEADLINE_SECONDS
            pod_name = self.pod_name(sandbox_id)
            if self._pod_exists_and_ready(sandbox_id):
                self._ensure_service_exists(sandbox_id, tenant_id, deadline)
                initialize(sandbox_id, max(1.0, deadline - time.monotonic()))
                return self._info(sandbox_id)

            created_pod_uid: str | None = None
            created_service_uid: str | None = None
            created_secret_uid: str | None = None
            try:
                pod = self._create_sandbox_pod(
                    sandbox_id=str(sandbox_id),
                    tenant_id=tenant_id,
                    provisioning_attempt_number=provisioning_attempt_number,
                )
                created_secret_uid = self._provision_opencode_secret(str(sandbox_id))
                created_pod_uid = self._create_pod_or_reuse_existing(
                    pod, pod_name, deadline
                )
                created_service_uid = self._ensure_service_exists(
                    sandbox_id, tenant_id, deadline
                )
                if not self._wait_for_container_running(pod_name, deadline):
                    raise RuntimeError(
                        f"Timeout waiting for sandbox pod {pod_name} to run"
                    )
                initialize(sandbox_id, max(1.0, deadline - time.monotonic()))
                if not self._wait_for_pod_ready(pod_name, deadline):
                    raise RuntimeError(
                        f"Timeout waiting for sandbox pod {pod_name} to become ready"
                    )
                return self._info(sandbox_id)
            except Exception as error:
                if not isinstance(
                    error, LegacySandboxError
                ) and self._pod_exists_and_ready_safely(sandbox_id):
                    logger.warning(
                        "Provisioning failed for sandbox %s but pod is ready: %s",
                        sandbox_id,
                        error,
                        exc_info=True,
                    )
                else:
                    logger.error(
                        "Provisioning failed for sandbox %s: %s",
                        sandbox_id,
                        error,
                        exc_info=True,
                    )
                    self._cleanup_created_resources(
                        sandbox_id=sandbox_id,
                        pod_uid=created_pod_uid,
                        service_uid=created_service_uid,
                        secret_uid=created_secret_uid,
                        wait_for_deletion=True,
                    )
                raise

    def terminate(self, sandbox_id: UUID) -> None:
        self._cleanup_kubernetes_resources(sandbox_id, wait_for_deletion=True)
        logger.info("Terminated Firecracker sandbox %s", sandbox_id)

    def _info(self, sandbox_id: UUID) -> SandboxInfo:
        return SandboxInfo(
            sandbox_id=sandbox_id,
            directory_path=f"k8s://{self.namespace}/{self.pod_name(sandbox_id)}",
            status=SandboxStatus.RUNNING,
            last_heartbeat=None,
        )

    def _validate_provisioning_config(self, onyx_pat: str | None) -> None:
        if not onyx_pat:
            raise ValueError("onyx_pat is required for sandbox provisioning")
        if not ONYX_SERVER_URL:
            raise ValueError("ONYX_SERVER_URL must be set for sandbox provisioning")
        validate_sandbox_api_url(ONYX_SERVER_URL)
        if not SANDBOX_PROXY_HOST:
            raise ValueError("SANDBOX_PROXY_HOST must be set for sandbox provisioning")

    def _opencode_secret_name(self, sandbox_id: str | UUID) -> str:
        return f"{self.pod_name(sandbox_id)}-opencode-auth"

    @time_provision_phase(SandboxProvisionPhase.OPENCODE_SECRET)
    def _provision_opencode_secret(self, sandbox_id: str) -> str | None:
        secret_name = self._opencode_secret_name(sandbox_id)
        config_json = json.dumps(
            build_opencode_base_config(
                disabled_tools=get_opencode_disabled_tools(),
                plugins=[
                    _OPENCODE_CONNECT_APP_PLUGIN_PATH,
                    _OPENCODE_TURN_BUDGET_PLUGIN_PATH,
                    _OPENCODE_WEBAPP_PLUGIN_PATH,
                    _OPENCODE_SESSION_TAG_PLUGIN_PATH,
                ],
            )
        )

        def build_secret(password: str) -> client.V1Secret:
            return client.V1Secret(
                metadata=client.V1ObjectMeta(
                    name=secret_name,
                    namespace=self.namespace,
                    labels={
                        LABEL_K8S_COMPONENT: "sandbox-opencode-auth",
                        LABEL_K8S_MANAGED_BY: LABEL_K8S_MANAGED_BY_ONYX,
                        LABEL_SANDBOX_ID: sandbox_id,
                        LABEL_SANDBOX_PROTOCOL: SANDBOX_PROTOCOL_VERSION,
                    },
                ),
                type="Opaque",
                string_data={
                    self._OPENCODE_PASSWORD_SECRET_KEY: password,
                    self._OPENCODE_CONFIG_SECRET_KEY: config_json,
                },
            )

        existing_password = self.read_password(sandbox_id)
        password = existing_password or secrets.token_urlsafe(32)
        try:
            secret = self.core_api.create_namespaced_secret(
                namespace=self.namespace, body=build_secret(password)
            )
            return self._resource_uid(secret, secret_name)
        except ApiException as error:
            if error.status != 409:
                raise
            winner_password = self.read_password(sandbox_id)
            if winner_password is None:
                raise
            self.core_api.replace_namespaced_secret(
                name=secret_name,
                namespace=self.namespace,
                body=build_secret(winner_password),
            )
            return None

    def _delete_opencode_secret(self, sandbox_id: str | UUID) -> None:
        try:
            secret = self.core_api.read_namespaced_secret(
                name=self._opencode_secret_name(sandbox_id), namespace=self.namespace
            )
            self._validate_owned_labels(
                secret.metadata.labels or {}, secret.metadata.name
            )
            self.core_api.delete_namespaced_secret(
                name=self._opencode_secret_name(sandbox_id),
                namespace=self.namespace,
                body=client.V1DeleteOptions(
                    preconditions=client.V1Preconditions(uid=secret.metadata.uid)
                ),
            )
        except ApiException as error:
            if error.status not in (404, 410):
                raise

    @staticmethod
    def _resource_uid(
        resource: client.V1Pod | client.V1Service | client.V1Secret, name: str
    ) -> str:
        metadata = resource.metadata
        if metadata is None:
            raise RuntimeError(f"Kubernetes did not return a UID for {name}")
        uid = metadata.uid
        if not isinstance(uid, str) or not uid:
            raise RuntimeError(f"Kubernetes did not return a UID for {name}")
        return uid

    def _create_sandbox_pod(
        self,
        sandbox_id: str,
        tenant_id: str,
        provisioning_attempt_number: int,
    ) -> client.V1Pod:
        try:
            pod_template = self.core_api.read_namespaced_pod_template(
                name=_PODTEMPLATE_NAME, namespace=self.namespace
            )
        except ApiException as error:
            if error.status == 404:
                raise RuntimeError(
                    f"Sandbox PodTemplate '{_PODTEMPLATE_NAME}' not found in "
                    f"namespace '{self.namespace}'."
                ) from error
            raise

        template_labels = pod_template.template.metadata.labels or {}
        if template_labels.get(LABEL_SANDBOX_PROTOCOL) != SANDBOX_PROTOCOL_VERSION:
            raise RuntimeError("Sandbox PodTemplate has an unsupported guest protocol")
        spec = cast(client.V1PodSpec, copy.deepcopy(pod_template.template.spec))
        self._validate_template_spec(spec)
        self._overlay_dynamic_fields(spec, sandbox_id)
        return client.V1Pod(
            api_version="v1",
            kind="Pod",
            metadata=client.V1ObjectMeta(
                name=self.pod_name(sandbox_id),
                namespace=self.namespace,
                labels={
                    **template_labels,
                    LABEL_K8S_COMPONENT: LABEL_K8S_COMPONENT_SANDBOX,
                    LABEL_K8S_MANAGED_BY: LABEL_K8S_MANAGED_BY_ONYX,
                    LABEL_SANDBOX_ID: sandbox_id,
                    LABEL_TENANT_ID: tenant_id,
                    LABEL_PROVISIONING_ATTEMPT: str(provisioning_attempt_number),
                    LABEL_SANDBOX_PROTOCOL: SANDBOX_PROTOCOL_VERSION,
                },
            ),
            spec=spec,
        )

    def _validate_template_spec(self, spec: client.V1PodSpec) -> None:
        if spec.runtime_class_name != _REQUIRED_RUNTIME_CLASS_NAME:
            raise RuntimeError(
                "Sandbox PodTemplate must set runtimeClassName to "
                f"{_REQUIRED_RUNTIME_CLASS_NAME!r}"
            )
        containers = list(spec.containers or [])
        if len(containers) != 1 or containers[0].name != _SANDBOX_CONTAINER_NAME:
            raise RuntimeError("Sandbox PodTemplate must contain only sandbox")
        init_names = [container.name for container in spec.init_containers or []]
        if init_names != [_FIREWALL_INIT_CONTAINER_NAME]:
            raise RuntimeError("Sandbox PodTemplate contains legacy init containers")

    def _overlay_dynamic_fields(self, spec: client.V1PodSpec, sandbox_id: str) -> None:
        spec.host_aliases = [
            client.V1HostAlias(ip=self._resolve_proxy_ip(), hostnames=[_PROXY_ALIAS])
        ]
        sandbox_container = self._require_container(spec, _SANDBOX_CONTAINER_NAME)
        sandbox_container.env = list(sandbox_container.env or []) + [
            client.V1EnvVar(
                name=OPENCODE_SERVER_PASSWORD,
                value_from=client.V1EnvVarSource(
                    secret_key_ref=client.V1SecretKeySelector(
                        name=self._opencode_secret_name(sandbox_id),
                        key=self._OPENCODE_PASSWORD_SECRET_KEY,
                    )
                ),
            ),
            client.V1EnvVar(
                name="OPENCODE_CONFIG_CONTENT",
                value_from=client.V1EnvVarSource(
                    secret_key_ref=client.V1SecretKeySelector(
                        name=self._opencode_secret_name(sandbox_id),
                        key=self._OPENCODE_CONFIG_SECRET_KEY,
                    )
                ),
            ),
            client.V1EnvVar(
                name="ONYX_WEBAPP_ALLOWED_DEV_ORIGINS",
                value=allowed_dev_origins(),
            ),
        ]

    def _require_container(
        self, spec: client.V1PodSpec, name: str
    ) -> client.V1Container:
        containers = cast(list[client.V1Container], spec.containers or [])
        init_containers = cast(list[client.V1Container], spec.init_containers or [])
        for container in containers + init_containers:
            if container.name == name:
                return container
        raise RuntimeError(f"PodTemplate '{_PODTEMPLATE_NAME}' has no {name!r}")

    def _create_sandbox_service(
        self, sandbox_id: UUID, tenant_id: str
    ) -> client.V1Service:
        ports = [
            client.V1ServicePort(
                name="opencode",
                port=OPENCODE_SERVE_PORT,
                target_port=OPENCODE_SERVE_PORT,
            )
        ]
        ports.extend(
            client.V1ServicePort(name=f"nextjs-{port}", port=port, target_port=port)
            for port in range(SANDBOX_NEXTJS_PORT_START, SANDBOX_NEXTJS_PORT_END)
        )
        return client.V1Service(
            api_version="v1",
            kind="Service",
            metadata=client.V1ObjectMeta(
                name=self.pod_name(sandbox_id),
                namespace=self.namespace,
                labels={
                    LABEL_K8S_COMPONENT: LABEL_K8S_COMPONENT_SANDBOX,
                    LABEL_K8S_MANAGED_BY: LABEL_K8S_MANAGED_BY_ONYX,
                    LABEL_SANDBOX_ID: str(sandbox_id),
                    LABEL_TENANT_ID: tenant_id,
                    LABEL_SANDBOX_PROTOCOL: SANDBOX_PROTOCOL_VERSION,
                },
            ),
            spec=client.V1ServiceSpec(
                type="ClusterIP",
                selector={LABEL_SANDBOX_ID: str(sandbox_id)},
                ports=ports,
                publish_not_ready_addresses=True,
            ),
        )

    @time_provision_phase(SandboxProvisionPhase.SERVICE_ENSURE)
    def _ensure_service_exists(
        self, sandbox_id: UUID, tenant_id: str, deadline: float
    ) -> str | None:
        service_name = self.pod_name(sandbox_id)
        try:
            service = self.core_api.read_namespaced_service(
                name=service_name,
                namespace=self.namespace,
            )
            self._validate_owned_labels(service.metadata.labels or {}, service_name)
            if service.metadata.deletion_timestamp:
                self._wait_for_resource_deletion(
                    "service", service_name, deadline - time.monotonic()
                )
                created_service = self.core_api.create_namespaced_service(
                    namespace=self.namespace,
                    body=self._create_sandbox_service(sandbox_id, tenant_id),
                )
                return self._resource_uid(created_service, service_name)
            return None
        except ApiException as error:
            if error.status != 404:
                raise
        try:
            created_service = self.core_api.create_namespaced_service(
                namespace=self.namespace,
                body=self._create_sandbox_service(sandbox_id, tenant_id),
            )
            return self._resource_uid(created_service, service_name)
        except ApiException as error:
            if error.status == 409:
                service = self.core_api.read_namespaced_service(
                    name=service_name,
                    namespace=self.namespace,
                )
                self._validate_owned_labels(service.metadata.labels or {}, service_name)
                if not service.metadata.deletion_timestamp:
                    return None
                self._wait_for_resource_deletion(
                    "service", service_name, deadline - time.monotonic()
                )
                created_service = self.core_api.create_namespaced_service(
                    namespace=self.namespace,
                    body=self._create_sandbox_service(sandbox_id, tenant_id),
                )
                return self._resource_uid(created_service, service_name)
            raise

    def _validate_owned_labels(self, labels: dict[str, str], name: str) -> None:
        if labels.get(LABEL_SANDBOX_PROTOCOL) != SANDBOX_PROTOCOL_VERSION:
            raise LegacySandboxError(f"{name} is not a Firecracker sandbox resource")
        if labels.get(LABEL_K8S_MANAGED_BY) != LABEL_K8S_MANAGED_BY_ONYX:
            raise LegacySandboxError(f"{name} is not managed by Onyx")
        try:
            sandbox_id = UUID(labels.get(LABEL_SANDBOX_ID, ""))
        except ValueError as error:
            raise LegacySandboxError(f"{name} has no valid sandbox owner") from error
        expected_name = self.pod_name(sandbox_id)
        if name not in {expected_name, f"{expected_name}-opencode-auth"}:
            raise LegacySandboxError(f"{name} does not match its sandbox owner")

    def _validate_conforming_pod(self, pod: client.V1Pod) -> None:
        name = pod.metadata.name or "<unknown>"
        self._validate_owned_labels(pod.metadata.labels or {}, name)
        spec = pod.spec
        if spec is None:
            raise LegacySandboxError(f"{name} has no pod spec")
        if spec.runtime_class_name != _REQUIRED_RUNTIME_CLASS_NAME:
            raise LegacySandboxError(
                f"{name} does not use RuntimeClass {_REQUIRED_RUNTIME_CLASS_NAME!r}"
            )
        containers = list(spec.containers or [])
        if len(containers) != 1 or containers[0].name != _SANDBOX_CONTAINER_NAME:
            raise LegacySandboxError(f"{name} has legacy containers")
        init_names = [container.name for container in spec.init_containers or []]
        if init_names != [_FIREWALL_INIT_CONTAINER_NAME]:
            raise LegacySandboxError(f"{name} has legacy init containers")

    def _pod_exists_and_ready(self, sandbox_id: str | UUID) -> bool:
        pod = self.get_pod(sandbox_id)
        if pod is None:
            return False
        return self._sandbox_container_is_ready(pod)

    def _pod_exists_and_ready_safely(self, sandbox_id: str | UUID) -> bool:
        try:
            return self._pod_exists_and_ready(sandbox_id)
        except (ApiException, LegacySandboxError):
            return False

    def _create_pod_or_reuse_existing(
        self, pod: client.V1Pod, pod_name: str, deadline: float
    ) -> str | None:
        for retry_after_delete in (True, False):
            try:
                with time_provision_phase(SandboxProvisionPhase.POD_CREATE):
                    created_pod = self.core_api.create_namespaced_pod(
                        namespace=self.namespace,
                        body=pod,
                    )
                return self._resource_uid(created_pod, pod_name)
            except ApiException as error:
                if error.status != 409:
                    raise
                existing = self.core_api.read_namespaced_pod(
                    name=pod_name, namespace=self.namespace
                )
                self._validate_conforming_pod(existing)
                if not existing.metadata.deletion_timestamp:
                    logger.warning(
                        "Sandbox pod %s already exists; reusing conforming pod",
                        pod_name,
                    )
                    return None
                if not retry_after_delete:
                    raise RuntimeError(
                        f"Sandbox pod {pod_name} is still deleting after retry"
                    )
                self._wait_for_resource_deletion(
                    "pod", pod_name, deadline - time.monotonic()
                )
        raise RuntimeError(f"Failed to create sandbox pod {pod_name}")

    def _get_init_container_logs(self, pod_name: str, container_name: str) -> str:
        try:
            return (
                cast(
                    str,
                    self.core_api.read_namespaced_pod_log(
                        name=pod_name,
                        namespace=self.namespace,
                        container=container_name,
                        tail_lines=100,
                    ),
                )
                or "(no logs available)"
            )
        except ApiException as error:
            return f"(failed to retrieve logs: {error})"

    def _check_init_container_status(self, pod: client.V1Pod) -> str | None:
        for init_status in pod.status.init_container_statuses or []:
            state = init_status.state
            if state is None:
                continue
            waiting = state.waiting
            if waiting and waiting.reason in {"Error", "CrashLoopBackOff"}:
                return (
                    f"Init container {init_status.name!r} is in "
                    f"{waiting.reason!r}: {waiting.message or ''}"
                )
            terminated = state.terminated
            if terminated is not None and terminated.exit_code != 0:
                logs = self._get_init_container_logs(
                    pod.metadata.name, init_status.name
                )
                return (
                    f"Init container {init_status.name!r} failed with exit code "
                    f"{terminated.exit_code}. Logs:\n{logs}"
                )
        return None

    def _evaluate_pod_ready(self, pod: client.V1Pod, pod_name: str) -> bool:
        self._validate_conforming_pod(pod)
        if pod.metadata.deletion_timestamp:
            raise RuntimeError(f"Pod {pod_name} is being deleted")
        init_error = self._check_init_container_status(pod)
        if init_error:
            raise RuntimeError(f"Pod {pod_name} failed to start: {init_error}")
        phase = pod.status.phase
        if phase == "Failed":
            raise RuntimeError(f"Pod {pod_name} failed to start")
        if phase == "Succeeded":
            raise RuntimeError(f"Pod {pod_name} completed unexpectedly")
        if phase == "Running":
            for condition in pod.status.conditions or []:
                if condition.type == "Ready" and condition.status == "True":
                    return True
        return False

    @staticmethod
    def _sandbox_container_is_ready(pod: client.V1Pod) -> bool:
        for status in pod.status.container_statuses or []:
            if status.name != _SANDBOX_CONTAINER_NAME:
                continue
            state = status.state
            return bool(
                status.ready and state is not None and state.running is not None
            )
        return False

    @time_provision_phase(SandboxProvisionPhase.POD_IP_WAIT)
    def _wait_for_container_running(self, pod_name: str, deadline: float) -> bool:
        while time.monotonic() < deadline:
            pod = self.core_api.read_namespaced_pod(
                name=pod_name, namespace=self.namespace
            )
            self._validate_conforming_pod(pod)
            if pod.metadata.deletion_timestamp:
                raise RuntimeError(f"Pod {pod_name} is being deleted")
            init_error = self._check_init_container_status(pod)
            if init_error:
                raise RuntimeError(f"Pod {pod_name} failed to start: {init_error}")
            for status in pod.status.container_statuses or []:
                if (
                    status.name == _SANDBOX_CONTAINER_NAME
                    and status.state is not None
                    and status.state.running is not None
                ):
                    return True
            time.sleep(POLL_INTERVAL_SECONDS)
        return False

    @time_provision_phase(SandboxProvisionPhase.POD_READY_WAIT)
    def _wait_for_pod_ready(self, pod_name: str, deadline: float) -> bool:
        while time.monotonic() < deadline:
            try:
                pod = self.core_api.read_namespaced_pod(
                    name=pod_name, namespace=self.namespace
                )
            except ApiException as error:
                if error.status == 404:
                    raise RuntimeError(f"Pod {pod_name} was deleted") from error
                raise
            if self._evaluate_pod_ready(pod, pod_name):
                return True
            time.sleep(min(POLL_INTERVAL_SECONDS, max(0, deadline - time.monotonic())))
        return False

    def _wait_for_resource_deletion(
        self, resource_type: str, name: str, timeout: float
    ) -> None:
        if timeout <= 0:
            raise TimeoutError(f"Timed out waiting for {resource_type} {name} deletion")
        started_at = time.monotonic()
        while time.monotonic() - started_at < timeout:
            try:
                if resource_type == "pod":
                    self.core_api.read_namespaced_pod(
                        name=name, namespace=self.namespace
                    )
                elif resource_type == "service":
                    self.core_api.read_namespaced_service(
                        name=name, namespace=self.namespace
                    )
                else:
                    raise ValueError(f"Unknown resource type: {resource_type}")
            except ApiException as error:
                if error.status == 404:
                    return
                logger.warning(
                    "Error checking %s %s status: %s", resource_type, name, error
                )
            time.sleep(POLL_INTERVAL_SECONDS)
        raise TimeoutError(f"Timed out waiting for {resource_type} {name} deletion")

    def _cleanup_kubernetes_resources(
        self, sandbox_id: str | UUID, *, wait_for_deletion: bool
    ) -> None:
        sandbox_id = str(sandbox_id)
        name = self.pod_name(sandbox_id)
        self.get_pod(sandbox_id)
        self._delete_service_if_owned(name)
        self._delete_pod_if_owned(sandbox_id)
        self._delete_opencode_secret(sandbox_id)
        if wait_for_deletion:
            self._wait_for_resource_deletion("service", name, RUNTIME_TEARDOWN_SECONDS)
            self._wait_for_resource_deletion("pod", name, RUNTIME_TEARDOWN_SECONDS)

    def _cleanup_created_resources(
        self,
        *,
        sandbox_id: str | UUID,
        pod_uid: str | None,
        service_uid: str | None,
        secret_uid: str | None,
        wait_for_deletion: bool,
    ) -> None:
        name = self.pod_name(sandbox_id)
        secret_name = self._opencode_secret_name(sandbox_id)
        try:
            if service_uid is not None:
                self._delete_service_by_uid(name, service_uid)
            if pod_uid is not None:
                self._delete_pod_by_uid(name, pod_uid)
            if secret_uid is not None:
                self._delete_secret_by_uid(secret_name, secret_uid)
            if wait_for_deletion:
                if service_uid is not None:
                    self._wait_for_resource_deletion(
                        "service", name, RUNTIME_TEARDOWN_SECONDS
                    )
                if pod_uid is not None:
                    self._wait_for_resource_deletion(
                        "pod", name, RUNTIME_TEARDOWN_SECONDS
                    )
        except Exception:
            logger.warning(
                "Failed to clean up attempt-created resources for sandbox %s",
                sandbox_id,
                exc_info=True,
            )

    def _delete_service_if_owned(self, name: str) -> None:
        try:
            service = self.core_api.read_namespaced_service(
                name=name, namespace=self.namespace
            )
        except ApiException as error:
            if error.status == 404:
                return
            raise
        self._validate_owned_labels(service.metadata.labels or {}, name)
        try:
            self.core_api.delete_namespaced_service(
                name=name,
                namespace=self.namespace,
                body=client.V1DeleteOptions(
                    preconditions=client.V1Preconditions(uid=service.metadata.uid)
                ),
            )
        except ApiException as error:
            if error.status not in (404, 410):
                raise

    def _delete_service_by_uid(self, name: str, uid: str) -> None:
        try:
            self.core_api.delete_namespaced_service(
                name=name,
                namespace=self.namespace,
                body=client.V1DeleteOptions(
                    preconditions=client.V1Preconditions(uid=uid)
                ),
            )
        except ApiException as error:
            if error.status not in (404, 410):
                raise

    def _delete_pod_if_owned(self, sandbox_id: str | UUID) -> None:
        pod = self.get_pod(sandbox_id)
        if pod is None:
            return
        name = self.pod_name(sandbox_id)
        try:
            self.core_api.delete_namespaced_pod(
                name=name,
                namespace=self.namespace,
                body=client.V1DeleteOptions(
                    preconditions=client.V1Preconditions(uid=pod.metadata.uid)
                ),
            )
        except ApiException as error:
            if error.status not in (404, 410):
                raise

    def _delete_pod_by_uid(self, name: str, uid: str) -> None:
        try:
            self.core_api.delete_namespaced_pod(
                name=name,
                namespace=self.namespace,
                body=client.V1DeleteOptions(
                    preconditions=client.V1Preconditions(uid=uid)
                ),
            )
        except ApiException as error:
            if error.status not in (404, 410):
                raise

    def _delete_secret_by_uid(self, name: str, uid: str) -> None:
        try:
            self.core_api.delete_namespaced_secret(
                name=name,
                namespace=self.namespace,
                body=client.V1DeleteOptions(
                    preconditions=client.V1Preconditions(uid=uid)
                ),
            )
        except ApiException as error:
            if error.status not in (404, 410):
                raise

    def _resolve_proxy_ip(self) -> str:
        host = SANDBOX_PROXY_HOST
        try:
            ipaddress.ip_address(host)
            return host
        except ValueError:
            pass
        name, _, rest = host.partition(".")
        namespace = rest.partition(".")[0] or SANDBOX_PROXY_NAMESPACE
        last_error: Exception | None = None
        for attempt in range(_PROXY_RESOLVE_RETRY_ATTEMPTS):
            try:
                cluster_ip = self.core_api.read_namespaced_service(
                    name=name,
                    namespace=namespace,
                ).spec.cluster_ip
                if isinstance(cluster_ip, str) and cluster_ip not in {"", "None"}:
                    return cluster_ip
                last_error = RuntimeError(f"Service {name} has no ClusterIP")
            except ApiException as error:
                last_error = error
            if attempt < _PROXY_RESOLVE_RETRY_ATTEMPTS - 1:
                time.sleep(_PROXY_RESOLVE_RETRY_BACKOFF_S * (2**attempt))
        raise RuntimeError(
            f"failed to resolve proxy ClusterIP for SANDBOX_PROXY_HOST={host!r} "
            f"after {_PROXY_RESOLVE_RETRY_ATTEMPTS} attempts: {last_error}"
        )
