"""Pod steps shared by the sandbox pod backends.

The Craft ``KubernetesSandboxManager`` and the harness pod runtime both build
pods from a Helm PodTemplate, wait for readiness, and clean up through these
methods. They dispatch through ``self`` so a backend can override one step.
"""

import copy
import ipaddress
import time
from collections.abc import Callable, Iterator

from kubernetes import client, watch
from kubernetes.client.rest import ApiException

from onyx.server.features.build.sandbox.resources import remaining_request_timeout
from onyx.server.features.build.timeouts import POLL_INTERVAL_SECONDS
from onyx.utils.logger import setup_logger

logger = setup_logger()


def require_container(
    spec: client.V1PodSpec, name: str, template_name: str
) -> client.V1Container:
    """Find a container in the PodTemplate by name, or raise a clear error.

    A bare ``next()`` would surface a PodTemplate/version skew (template
    missing the expected container) as an opaque ``StopIteration``; this
    names the container and the fix, matching the 404 PodTemplate error.
    """
    for container in list(spec.containers or []) + list(spec.init_containers or []):
        if container.name == name:
            return container
    raise RuntimeError(
        f"PodTemplate '{template_name}' has no '{name}' container. "
        f"The PodTemplate and api-server versions are likely out of sync — "
        f"apply the matching sandbox PodTemplate."
    )


class SandboxPodOps:
    """Pod lifecycle steps. Subclasses set ``_core_api``, ``_namespace`` and
    ``_ready_container_name`` (the container whose readiness counts)."""

    _core_api: client.CoreV1Api
    _namespace: str
    _ready_container_name: str

    def _build_pod_from_template(
        self,
        *,
        template_name: str,
        pod_name: str,
        labels: dict[str, str],
        overlay: Callable[[client.V1PodSpec], None],
    ) -> client.V1Pod:
        """Build a Pod from the Helm PodTemplate. ``overlay`` sets the
        per-pod fields the template can't carry; ``labels`` win over the
        template's labels."""
        try:
            pod_template = self._core_api.read_namespaced_pod_template(
                name=template_name, namespace=self._namespace
            )
        except ApiException as e:
            if e.status == 404:
                raise RuntimeError(
                    f"Sandbox PodTemplate '{template_name}' not found in "
                    f"namespace '{self._namespace}'. It must be applied to the "
                    f"cluster (by the deploy tooling when Craft is enabled) "
                    f"before sandboxes can be provisioned."
                ) from e
            raise

        spec: client.V1PodSpec = copy.deepcopy(pod_template.template.spec)
        overlay(spec)

        return client.V1Pod(
            api_version="v1",
            kind="Pod",
            metadata=client.V1ObjectMeta(
                name=pod_name,
                namespace=self._namespace,
                labels={
                    **(pod_template.template.metadata.labels or {}),
                    **labels,
                },
            ),
            spec=spec,
        )

    def _get_init_container_logs(self, pod_name: str, container_name: str) -> str:
        """Get logs from an init container.

        Args:
            pod_name: Name of the pod
            container_name: Name of the init container

        Returns:
            Log output from the init container, or error message if logs cannot be retrieved
        """
        try:
            logs = self._core_api.read_namespaced_pod_log(
                name=pod_name,
                namespace=self._namespace,
                container=container_name,
                tail_lines=100,  # Get last 100 lines
            )
            return logs or "(no logs available)"
        except ApiException as e:
            return f"(failed to retrieve logs: {e})"

    def _check_init_container_status(self, pod: client.V1Pod) -> str | None:
        """Check if any init containers have failed.

        Args:
            pod: The pod object

        Returns:
            Error message if an init container failed, None otherwise
        """
        init_statuses = pod.status.init_container_statuses or []
        if not init_statuses:
            return None

        restartable_init_container_names = {
            init_container.name
            for init_container in pod.spec.init_containers or []
            if init_container.name and init_container.restart_policy == "Always"
        }

        for init_status in init_statuses:
            state = init_status.state
            if state is None:
                continue

            waiting = state.waiting
            if waiting and waiting.reason in ["Error", "CrashLoopBackOff"]:
                message = waiting.message or ""
                return (
                    f"Init container '{init_status.name}' is in "
                    f"'{waiting.reason}' state. Message: {message}"
                )

            terminated = state.terminated
            if terminated is None or terminated.exit_code == 0:
                continue
            if init_status.name in restartable_init_container_names:
                continue

            logs = self._get_init_container_logs(pod.metadata.name, init_status.name)
            return (
                f"Init container '{init_status.name}' failed with exit code "
                f"{terminated.exit_code}. Logs:\n{logs}"
            )

        return None

    def _evaluate_pod_readiness(self, pod: client.V1Pod, pod_name: str) -> bool | None:
        """Inspect one pod snapshot for readiness/failure.

        Returns ``True`` if Ready, ``False`` if still progressing, and raises
        ``RuntimeError`` on a terminal failure (init failure, Failed phase,
        Succeeded phase).
        """
        init_error = self._check_init_container_status(pod)
        if init_error:
            raise RuntimeError(f"Pod {pod_name} failed to start: {init_error}")

        phase = pod.status.phase
        if phase == "Failed":
            raise RuntimeError(f"Pod {pod_name} failed to start")
        if phase == "Succeeded":
            raise RuntimeError(
                f"Pod {pod_name} completed unexpectedly "
                f"(sandbox pods should run indefinitely)"
            )
        if phase == "Running":
            for condition in pod.status.conditions or []:
                if condition.type == "Ready" and condition.status == "True":
                    return True
        return False

    @staticmethod
    def _container_is_ready(pod: client.V1Pod, container_name: str) -> bool:
        """Return True only when the named container is running and ready."""
        for status in pod.status.container_statuses or []:
            if status.name != container_name:
                continue
            state = status.state
            return bool(
                status.ready and state is not None and state.running is not None
            )
        return False

    def _wait_for_pod_ready(
        self,
        pod_name: str,
        deadline: float,
    ) -> bool:
        """Block on a single-pod watch until Ready or the monotonic deadline.

        Watching beats polling: the apiserver pushes status transitions as
        they happen, so we catch ``Ready`` within ~100ms instead of waiting
        for the next poll tick. A bounded retry loop covers ``410 Gone``
        (resource version aged out under us) by re-listing and resuming.
        """
        field_selector = f"metadata.name={pod_name}"

        try:
            initial = self._core_api.read_namespaced_pod(
                name=pod_name, namespace=self._namespace
            )
            if self._evaluate_pod_readiness(initial, pod_name):
                logger.info("Pod %s is ready", pod_name)
                return True
            resource_version = initial.metadata.resource_version
        except ApiException as e:
            if e.status == 404:
                raise RuntimeError(f"Pod {pod_name} was deleted")
            raise

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            w = watch.Watch()
            try:
                stream = w.stream(
                    self._core_api.list_namespaced_pod,
                    namespace=self._namespace,
                    field_selector=field_selector,
                    resource_version=resource_version,
                    timeout_seconds=max(1, int(remaining)),
                    _request_timeout=remaining,
                )
                for event in stream:
                    event_type = event.get("type")
                    obj = event.get("object")
                    if event_type == "DELETED":
                        raise RuntimeError(f"Pod {pod_name} was deleted")
                    if not isinstance(obj, client.V1Pod):
                        continue
                    resource_version = obj.metadata.resource_version
                    if self._evaluate_pod_readiness(obj, pod_name):
                        logger.info("Pod %s is ready", pod_name)
                        return True
            except ApiException as e:
                # 410 Gone: resource_version aged out — re-list, check the
                # snapshot for Ready (the pod may have flipped while the
                # watch was expiring), then resume from the list's RV.
                if e.status == 410:
                    listing = self._core_api.list_namespaced_pod(
                        namespace=self._namespace, field_selector=field_selector
                    )
                    for pod in listing.items or []:
                        if self._evaluate_pod_readiness(pod, pod_name):
                            logger.info("Pod %s is ready", pod_name)
                            return True
                    resource_version = listing.metadata.resource_version
                    continue
                raise
            finally:
                w.stop()

        # On timeout, re-check init container status one more time.
        try:
            pod = self._core_api.read_namespaced_pod(
                name=pod_name, namespace=self._namespace
            )
            init_error = self._check_init_container_status(pod)
            if init_error:
                raise RuntimeError(f"Pod {pod_name} failed to start: {init_error}")
        except ApiException:
            pass

        logger.warning("Timeout waiting for pod %s to become ready", pod_name)
        return False

    def _wait_for_pod_ip(self, pod_name: str, deadline: float) -> bool:
        """Poll until the pod is assigned an IP, or the monotonic deadline.

        Waits for IP assignment only, never readiness: the init sidecar serves
        the restore endpoint while its startup probe stays blocked, so waiting
        for readiness here would deadlock the restore handshake.
        """
        while time.monotonic() < deadline:
            try:
                pod = self._core_api.read_namespaced_pod(
                    name=pod_name, namespace=self._namespace
                )
            except ApiException as e:
                if e.status == 404:
                    raise RuntimeError(f"Pod {pod_name} was deleted")
                raise
            if pod.status.pod_ip:
                logger.info("Pod %s assigned IP %s", pod_name, pod.status.pod_ip)
                return True
            time.sleep(POLL_INTERVAL_SECONDS)

        logger.warning("Timeout waiting for pod %s to be assigned an IP", pod_name)
        return False

    def _pod_exists_and_healthy(self, pod_name: str) -> bool:
        """Check if a pod exists and the sandbox app container is ready.

        Args:
            pod_name: Name of the pod to check

        Returns:
            True if pod exists and is running/ready, False otherwise
        """
        try:
            pod = self._core_api.read_namespaced_pod(
                name=pod_name,
                namespace=self._namespace,
            )
            phase = pod.status.phase

            # Check if running and ready
            if phase == "Running":
                conditions = pod.status.conditions or []
                for condition in conditions:
                    if (
                        condition.type == "Ready"
                        and condition.status == "True"
                        and self._container_is_ready(pod, self._ready_container_name)
                    ):
                        return True

            return False
        except ApiException as e:
            if e.status == 404:
                return False
            raise

    def _wait_for_resource_deletion(
        self,
        resource_type: str,
        name: str,
        timeout: float,
    ) -> bool:
        """Wait for a Kubernetes resource to be fully deleted.

        Kubernetes delete calls are asynchronous - the API returns immediately
        but the resource may still exist in a 'Terminating' state. This method
        polls until the resource returns 404 (not found).

        Args:
            resource_type: Type of resource ("pod", "service", or "secret")
            name: Name of the resource
            timeout: Maximum time to wait in seconds

        Returns:
            True if resource was deleted, False if timeout
        """
        start_time = time.monotonic()

        while True:
            try:
                if resource_type == "pod":
                    self._core_api.read_namespaced_pod(
                        name=name,
                        namespace=self._namespace,
                    )
                elif resource_type == "service":
                    self._core_api.read_namespaced_service(
                        name=name,
                        namespace=self._namespace,
                    )
                elif resource_type == "secret":
                    self._core_api.read_namespaced_secret(
                        name=name,
                        namespace=self._namespace,
                    )
                else:
                    raise ValueError(f"Unknown resource type: {resource_type}")

                # Resource still exists, wait and retry
                logger.debug("Waiting for %s %s to be deleted...", resource_type, name)
            except ApiException as e:
                if e.status == 404:
                    # Resource is gone
                    logger.debug(
                        "%s %s fully deleted", resource_type.capitalize(), name
                    )
                    return True
                # Other error, log and continue waiting
                logger.warning(
                    "Error checking %s %s status: %s", resource_type, name, e
                )
            remaining = timeout - (time.monotonic() - start_time)
            if remaining <= 0:
                break
            time.sleep(min(POLL_INTERVAL_SECONDS, remaining))

        logger.warning(
            "Timeout waiting for %s %s to be deleted after %ss",
            resource_type,
            name,
            timeout,
        )
        return False

    def _list_all_pages(
        self,
        list_resources: Callable[
            ..., client.V1PodList | client.V1ServiceList | client.V1SecretList
        ],
        label_selector: str,
        deadline: float,
    ) -> Iterator[client.V1Pod | client.V1Service | client.V1Secret]:
        continuation = None
        while True:
            page = list_resources(
                namespace=self._namespace,
                label_selector=label_selector,
                limit=100,
                _continue=continuation,
                _request_timeout=remaining_request_timeout(deadline),
            )
            yield from page.items
            continuation = page.metadata._continue
            if not continuation:
                return

    def _resolve_proxy_cluster_ip(
        self,
        proxy_host: str,
        default_namespace: str,
        attempts: int,
        backoff_seconds: float,
    ) -> str:
        """Resolve the proxy host to a pod-routable IP for the egress
        hostAlias. Reads the Service ClusterIP from the k8s API, not the
        api-server's OS resolver, so it stays correct under telepresence (whose
        resolver returns a synthetic, pod-unroutable IP). A numeric host (CI
        passes the ClusterIP directly) is returned unchanged."""
        host = proxy_host
        try:
            ipaddress.ip_address(host)
            return host
        except ValueError:
            pass
        name, _, rest = host.partition(".")
        namespace = rest.partition(".")[0] or default_namespace
        last_err: Exception | None = None
        for attempt in range(attempts):
            try:
                cluster_ip = self._core_api.read_namespaced_service(
                    name=name, namespace=namespace
                ).spec.cluster_ip
                if cluster_ip and cluster_ip != "None":
                    return cluster_ip
                last_err = RuntimeError(f"Service {name} has no ClusterIP")
            except ApiException as e:
                last_err = e
            if attempt < attempts - 1:
                time.sleep(backoff_seconds * (2**attempt))
        raise RuntimeError(
            f"failed to resolve proxy ClusterIP for SANDBOX_PROXY_HOST={host!r} "
            f"after {attempts} attempts: {last_err}"
        )
