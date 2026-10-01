"""Namespace-scoped, bounded Kubernetes health reads in the isolated collector."""

import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import requests

from onyx.utils.fleet_telemetry import _VERSION, BoundedTelemetry

_SERVICE_ROLES = {
    "api-server": "api",
    "onyx-api": "api",
    "api": "api",
    "celery-worker-primary": "worker",
    "celery-worker-docfetching": "worker",
    "celery-worker-docprocessing": "worker",
    "celery-worker-heavy": "worker",
    "celery-worker-light": "worker",
    "celery-worker-monitoring": "worker",
    "celery-worker-user-file-processing": "worker",
    "celery-worker-scheduled-tasks": "worker",
    "celery-worker-indexing": "worker",
    "celery-beat": "scheduler",
    "web-server": "web",
    "web": "web",
    "mcp-server": "api",
    "pgbouncer": "postgres",
    "code-interpreter": "background",
    "sandbox-proxy": "background",
    "background": "background",
    "metrics-scraper": "collector",
    "telemetry-collector": "collector",
    "telemetry-collector-canary": "collector",
    "inference-model-server": "indexing",
    "indexing-model-server": "indexing",
    "opensearch": "opensearch",
    "postgresql": "postgres",
    "redis": "redis",
    "slack-bot": "slack",
    "discord-bot": "discord",
}


def quantity(value: Any, *, cpu: bool = False) -> float | None:
    if not isinstance(value, str) or len(value) > 32:
        return None
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([A-Za-z]*)", value)
    if not match:
        return None
    suffix = match[2]
    multipliers = (
        {"": 1, "m": 0.001, "u": 1e-6, "n": 1e-9}
        if cpu
        else {
            "": 1,
            "Ki": 1024,
            "Mi": 1024**2,
            "Gi": 1024**3,
            "Ti": 1024**4,
            "K": 1000,
            "M": 1000**2,
            "G": 1000**3,
            "T": 1000**4,
        }
    )
    if suffix not in multipliers:
        return None
    result = float(match[1]) * multipliers[suffix]
    return result if math.isfinite(result) and 0 <= result <= 1e18 else None


class KubernetesCollector:
    def __init__(self, client: BoundedTelemetry) -> None:
        self.client = client
        self.namespace = os.environ.get(
            "ONYX_TELEMETRY_KUBERNETES_NAMESPACE", "default"
        )
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", self.namespace):
            raise ValueError("Invalid namespace")
        host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
        port = os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
        self.base = f"https://{host}:{port}"
        self.base = os.environ.get(
            "ONYX_TELEMETRY_KUBERNETES_API_URL", self.base
        ).rstrip("/")
        parsed = urlsplit(self.base)
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Invalid Kubernetes API endpoint")
        self.token_path = Path(
            os.environ.get(
                "ONYX_TELEMETRY_KUBERNETES_TOKEN_FILE",
                "/var/run/secrets/kubernetes.io/serviceaccount/token",
            )
        )
        self.ca_path = os.environ.get(
            "ONYX_TELEMETRY_KUBERNETES_CA_FILE",
            "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
        )
        self._continuation: str | None = None
        self._last_poll = 0.0
        self._last_metrics = 0.0
        self.errors = 0
        self._state: dict[str, tuple[int, bool, float, str]] = {}
        self._limits: dict[
            tuple[str, str], tuple[str, float | None, float | None, str]
        ] = {}
        self._versions: dict[str, tuple[str, str | None]] = {}

    def _observe_version(
        self,
        identity: str,
        role: str,
        container: dict[str, Any],
        statuses: list[dict[str, Any]],
    ) -> None:
        image = container.get("image")
        version = "unknown"
        if isinstance(image, str) and len(image) <= 1024 and ":" in image:
            tag = image.rsplit(":", 1)[1]
            if _VERSION.fullmatch(tag):
                version = tag
        digest: str | None = None
        for status in statuses:
            if status.get("name") != container.get("name"):
                continue
            image_id = status.get("imageID")
            if isinstance(image_id, str) and len(image_id) <= 2048:
                match = re.search(r"sha256:[a-f0-9]{64}$", image_id)
                if match:
                    digest = match[0]
            break
        if version == "unknown" and digest is None:
            return
        observed = (version, digest)
        if self._versions.get(identity) == observed:
            return
        if identity not in self._versions and len(self._versions) >= 2000:
            self._versions.pop(next(iter(self._versions)))
        if self.client.emit(
            "version",
            {"version": version, "image_digest": digest, "shared": True},
            service=role,
        ):
            self._versions[identity] = observed

    def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        try:
            token = self.token_path.read_text().strip()
            if len(token) > 8192:
                return None
            with requests.get(
                self.base + path,
                params=params,
                # Bound the JSON payload itself. urllib3 raw reads otherwise
                # return gzip bytes when the API server compresses pod pages.
                headers={
                    "Authorization": "Bearer " + token,
                    "Accept-Encoding": "identity",
                },
                verify=self.ca_path,
                timeout=(0.5, 1),
                stream=True,
                allow_redirects=False,
            ) as response:
                if not response.ok or response.headers.get(
                    "Content-Encoding", "identity"
                ) not in {"", "identity"}:
                    self._failed()
                    return None
                body = response.raw.read(1_048_577)
                if len(body) > 1_048_576:
                    self._failed()
                    return None
                result = json.loads(body)
                return result if isinstance(result, dict) else None
        except Exception:
            self._failed()
            return None

    def _failed(self) -> None:
        self.errors += 1
        self.client.health = {**self.client.health, "kubernetes_errors": self.errors}

    def observe_pods(self, response: dict[str, Any]) -> None:
        now = time.monotonic()
        for pod in response.get("items", [])[:25]:
            metadata = pod.get("metadata", {})
            labels = metadata.get("labels", {})
            # Only a known role affects classification. All other labels are ignored.
            role = "unknown"
            for key in ("app", "app.kubernetes.io/component", "app.kubernetes.io/name"):
                if labels.get(key) in _SERVICE_ROLES:
                    role = _SERVICE_ROLES[labels[key]]
                    break
            pod_name = metadata.get("name", "")
            uid = metadata.get("uid", "")
            if (
                not isinstance(pod_name, str)
                or not isinstance(uid, str)
                or len(uid) > 128
            ):
                continue
            statuses = pod.get("status", {}).get("containerStatuses", [])[:20]
            for container in pod.get("spec", {}).get("containers", [])[:20]:
                name = container.get("name", "")
                limits = container.get("resources", {}).get("limits", {})
                if isinstance(name, str) and len(name) <= 128:
                    if (pod_name, name) not in self._limits and len(
                        self._limits
                    ) >= 2000:
                        self._limits.pop(next(iter(self._limits)))
                    identity = self.client.fingerprint(
                        self.namespace + ":" + uid + ":" + name
                    )
                    self._limits[(pod_name, name)] = (
                        identity,
                        quantity(limits.get("memory")),
                        quantity(limits.get("cpu"), cpu=True),
                        role,
                    )
                    self._observe_version(identity, role, container, statuses)
            for status in statuses:
                name = status.get("name", "")
                if not isinstance(name, str) or len(name) > 128:
                    continue
                identity = self.client.fingerprint(
                    self.namespace + ":" + uid + ":" + name
                )
                restarts = status.get("restartCount", 0)
                ready = status.get("ready", False)
                if (
                    type(restarts) is not int
                    or not 0 <= restarts <= 1e9
                    or type(ready) is not bool
                ):
                    continue
                previous = self._state.get(identity)
                restart_delta = (
                    max(0, restarts - previous[0]) if previous is not None else 0
                )
                current_termination = status.get("state", {}).get("terminated", {})
                terminated = current_termination or (
                    status.get("lastState", {}).get("terminated", {})
                    if restart_delta
                    else {}
                )
                phase = (
                    "terminated"
                    if current_termination
                    else "waiting"
                    if status.get("state", {}).get("waiting")
                    else "running"
                )
                if len(self._state) < 2000 or previous is not None:
                    self._state[identity] = (restarts, ready, now, phase)
                pod_reason = pod.get("status", {}).get("reason")
                reason = (
                    "evicted"
                    if pod_reason == "Evicted"
                    else "oom"
                    if terminated.get("reason") == "OOMKilled"
                    else "stopped"
                    if current_termination and terminated.get("exitCode") == 0
                    else "crash"
                    if terminated
                    else "restart"
                    if restart_delta
                    else "unready"
                    if not ready
                    else "started"
                )
                if (
                    previous is not None
                    and previous[0] == restarts
                    and previous[1] == ready
                    and previous[3] == phase
                ):
                    continue
                data: dict[str, Any] = {
                    "service_instance_id": identity,
                    "reason": reason,
                    "restart_count": restarts,
                    "restart_delta": restart_delta,
                    "planned": metadata.get("deletionTimestamp") is not None,
                    "shared": True,
                }
                exit_code = terminated.get("exitCode")
                if type(exit_code) is int and 0 <= exit_code <= 255:
                    data["exit_code"] = exit_code
                # No status messages, pod/container names, labels, or environment are exported.
                self.client.emit("runtime", data, service=role)
        self._state = {
            key: value for key, value in self._state.items() if now - value[2] < 3600
        }

    def observe_metrics(self, response: dict[str, Any]) -> None:
        for pod in response.get("items", [])[:200]:
            pod_name = pod.get("metadata", {}).get("name", "")
            for container in pod.get("containers", [])[:20]:
                name = container.get("name", "")
                cached = self._limits.get((pod_name, name))
                if cached is None:
                    continue
                identity, memory_limit, cpu_limit, role = cached
                usage = container.get("usage", {})
                self.client.emit(
                    "resource",
                    {
                        "service_instance_id": identity,
                        "memory_bytes": quantity(usage.get("memory")),
                        "memory_limit_bytes": memory_limit,
                        "cpu_cores": quantity(usage.get("cpu"), cpu=True),
                        "cpu_limit_cores": cpu_limit,
                        "shared": True,
                    },
                    service=role,
                )

    def tick(self) -> None:
        if not self.client.settings["enabled"]:
            return
        try:
            now = time.monotonic()
            if now - self._last_poll >= 30:
                params: dict[str, Any] = {"limit": 25}
                if self._continuation:
                    params["continue"] = self._continuation
                response = self._get(
                    f"/api/v1/namespaces/{quote(self.namespace)}/pods", params
                )
                if response:
                    self.observe_pods(response)
                    continuation = response.get("metadata", {}).get("continue")
                    self._continuation = (
                        continuation
                        if isinstance(continuation, str) and len(continuation) < 4096
                        else None
                    )
                self._last_poll = now
            if (
                now - self._last_metrics
                >= self.client.settings["resource_interval_seconds"]
            ):
                response = self._get(
                    f"/apis/metrics.k8s.io/v1beta1/namespaces/{quote(self.namespace)}/pods"
                )
                if response:
                    self.observe_metrics(response)
                self._last_metrics = now
        except Exception:
            pass
