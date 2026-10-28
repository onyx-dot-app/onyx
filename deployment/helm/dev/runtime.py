"""Shared Kubernetes configuration and readiness for local Craft processes."""

import base64
import ipaddress
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

API_SELECTOR = "app=api-server,app.kubernetes.io/instance=onyx"
# Time a new traffic agent gets to register with the traffic manager.
AGENT_REGISTRATION_GRACE = timedelta(seconds=30)


@dataclass(frozen=True)
class Cluster:
    root: Path
    name: str = "onyx-dev"
    namespace: str = "onyx"
    sandbox_namespace: str = "onyx-sandboxes"

    @property
    def context(self) -> str:
        """Return the explicit kubectl context for this kind cluster."""
        return f"kind-{self.name}"

    def command(self, *args: str, capture: bool = True, timeout: float = 30) -> str:
        """Run a bounded command, keeping captured configuration and secrets out of terminal output."""
        try:
            result = subprocess.run(
                args,
                cwd=self.root,
                check=True,
                text=True,
                timeout=timeout,
                stdout=subprocess.PIPE if capture else None,
                stderr=subprocess.PIPE if capture else None,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            if capture and exc.stderr:
                message = exc.stderr
                if isinstance(message, bytes):
                    message = message.decode(errors="replace")
                print(message.strip(), file=sys.stderr)
            raise
        return result.stdout.strip() if capture else ""

    def kube(
        self, *args: str, namespace: str | None = None, timeout: float = 30
    ) -> str:
        """Run kubectl with an explicit context, namespace, and request timeout."""
        return self.command(
            "kubectl",
            "--context",
            self.context,
            "--request-timeout=10s",
            "-n",
            namespace or self.namespace,
            *args,
            timeout=timeout,
        )

    def api_workload(self) -> dict[str, Any]:
        """Find the single API deployment that defines local process configuration."""
        items = json.loads(
            self.kube(
                "get",
                "deployments",
                "-l",
                API_SELECTOR,
                "-o",
                "json",
            )
        )["items"]
        if len(items) != 1:
            raise ValueError("Expected one Onyx API deployment; run make craft-up")
        return items[0]

    def deployment_env(self) -> dict[str, str]:
        """Resolve the API container's Kubernetes envFrom and env precedence."""
        workload = self.api_workload()
        container = next(
            (
                c
                for c in workload["spec"]["template"]["spec"]["containers"]
                if c["name"] == "api-server"
            ),
            None,
        )
        if container is None:
            raise ValueError("API deployment has no api-server container")
        cache: dict[tuple[str, str], dict[str, str] | None] = {}

        def source(kind: str, name: str, optional: bool = False) -> dict[str, str]:
            """Read and cache referenced configuration, respecting optional Kubernetes sources."""
            key = (kind, name)
            if key not in cache:
                raw = self.kube("get", kind, name, "--ignore-not-found", "-o", "json")
                if not raw:
                    cache[key] = None
                else:
                    data = json.loads(raw).get("data", {})
                    cache[key] = (
                        {
                            k: base64.b64decode(v, validate=True).decode()
                            for k, v in data.items()
                        }
                        if kind == "secret"
                        else data
                    )
            values = cache[key]
            if values is None:
                if optional:
                    return {}
                raise ValueError(f"Missing {kind} {name!r} in {self.namespace}")
            return values

        env: dict[str, str] = {}
        for entry in container.get("envFrom", []):
            for ref, kind in (("configMapRef", "configmap"), ("secretRef", "secret")):
                if ref in entry:
                    config = entry[ref]
                    env.update(
                        {
                            entry.get("prefix", "") + k: v
                            for k, v in source(
                                kind, config["name"], config.get("optional", False)
                            ).items()
                        }
                    )
        for entry in container.get("env", []):
            name = entry["name"]
            if "value" in entry:
                value = str(entry["value"])
                # Kubernetes expands earlier bindings, retaining unknown references.
                env[name] = re.sub(
                    r"\$\((\w+)\)",
                    lambda m: env.get(m[1], m[0]),
                    value.replace("$$", "\0"),
                ).replace("\0", "$")
                continue
            value_from = entry.get("valueFrom", {})
            if not value_from:
                env[name] = ""
                continue
            for ref, kind in (
                ("configMapKeyRef", "configmap"),
                ("secretKeyRef", "secret"),
            ):
                if ref not in value_from:
                    continue
                config = value_from[ref]
                values = source(kind, config["name"], config.get("optional", False))
                if config["key"] not in values and not config.get("optional", False):
                    raise ValueError(
                        f"Missing key {config['key']!r} in {kind} {config['name']!r}"
                    )
                if config["key"] in values:
                    env[name] = values[config["key"]]
                break
            else:
                if (
                    value_from.get("fieldRef", {}).get("fieldPath")
                    == "metadata.namespace"
                ):
                    env[name] = self.namespace
                else:
                    raise ValueError(
                        f"Cannot use pod-specific valueFrom for local variable {name}"
                    )
        return env

    def environment(
        self, env_file: Path | None = None, *, settings: dict[str, str] | None = None
    ) -> dict[str, str]:
        """Combine deployed settings and personal overrides, qualifying cluster service hosts."""
        from dotenv import dotenv_values

        settings = dict(self.deployment_env() if settings is None else settings)
        result = dict(os.environ)
        result.update(settings)
        path = env_file or self.root / ".vscode/.env.k8s"
        if path.is_file():
            result.update(
                {
                    k: v
                    for k, v in dotenv_values(path, interpolate=False).items()
                    if v is not None and not v.startswith("<")
                }
            )
        for key in (
            "POSTGRES_HOST",
            "REDIS_HOST",
            "MODEL_SERVER_HOST",
            "INDEXING_MODEL_SERVER_HOST",
            "OPENSEARCH_HOST",
            "SANDBOX_PROXY_HOST",
        ):
            if result.get(key):
                result[key] = self.qualify(result[key])
        for key in (
            "S3_ENDPOINT_URL",
            "S3_LEGACY_ENDPOINT_URL",
            "INTERNAL_URL",
            "ONYX_SERVER_URL",
        ):
            if result.get(key):
                url = urlsplit(result[key])
                if url.hostname and url.netloc == url.hostname + (
                    f":{url.port}" if url.port else ""
                ):
                    result[key] = urlunsplit(
                        url._replace(
                            netloc=self.qualify(url.hostname)
                            + (f":{url.port}" if url.port else "")
                        )
                    )
        result.update(
            K8S_CONTEXT=self.context,
            SANDBOX_BACKEND="kubernetes",
            SANDBOX_NAMESPACE=self.sandbox_namespace,
        )
        return result

    def database_environment(self, env_file: Path | None = None) -> dict[str, str]:
        """Resolve migration settings and reject changes to the deployed database target."""
        settings = self.deployment_env()
        env = self.environment(env_file, settings=settings)
        defaults = {
            "POSTGRES_HOST": "localhost",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "postgres",
        }
        for key, default in defaults.items():
            declared = settings.get(key) or default
            actual = env.get(key) or default
            if key == "POSTGRES_HOST":
                declared, actual = self.qualify(declared), self.qualify(actual)
            if actual != declared:
                raise ValueError(
                    f"{key} override differs from the selected cluster's database; remove it before migrations"
                )
        return env

    def qualify(self, host: str) -> str:
        """Expand a bare service name while retaining addresses and qualified hosts."""
        if host == "localhost" or "." in host or ":" in host:
            return host
        try:
            ipaddress.ip_address(host)
            return host
        except ValueError:
            return f"{host}.{self.namespace}.svc.cluster.local"

    def infrastructure_ready(self, timeout: float = 600) -> None:
        """Wait for active Onyx workloads and the installed Telepresence manager."""
        deadline = time.monotonic() + timeout
        workloads = json.loads(
            self.kube(
                "get",
                "deployments,statefulsets",
                "-o",
                "json",
            )
        )["items"]
        workloads = [
            w
            for w in workloads
            if w["metadata"].get("annotations", {}).get("meta.helm.sh/release-name")
            == "onyx"
            or w["metadata"].get("labels", {}).get("app.kubernetes.io/instance")
            == "onyx"
            or w["metadata"].get("labels", {}).get("release") == "onyx"
        ]
        if not workloads:
            raise ValueError("No Onyx workloads found; run make craft-up")
        for workload in workloads:
            if workload["spec"].get("replicas", 1) == 0:
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("Timed out waiting for Onyx infrastructure")
            name = f"{workload['kind'].lower()}/{workload['metadata']['name']}"
            print(f"Waiting for {name} ...", flush=True)
            self.kube(
                "rollout",
                "status",
                name,
                f"--timeout={int(remaining)}s",
                f"--request-timeout={int(remaining) + 5}s",
                timeout=remaining + 10,
            )
        manager = self.kube(
            "get",
            "deployment",
            "traffic-manager",
            "--ignore-not-found",
            "-o",
            "name",
            namespace="ambassador",
        )
        if manager:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("Timed out waiting for Telepresence infrastructure")
            self.kube(
                "rollout",
                "status",
                "deployment/traffic-manager",
                f"--timeout={int(remaining)}s",
                f"--request-timeout={int(remaining) + 5}s",
                namespace="ambassador",
                timeout=remaining + 10,
            )
        print(
            "Infrastructure ready. Local API and frontend readiness are checked separately.",
            flush=True,
        )

    def connect(self) -> None:
        """Connect Telepresence to the selected cluster and application namespace."""
        self.kube("get", "namespace", self.namespace, "-o", "name")
        self.command(
            "telepresence",
            "connect",
            "--context",
            self.context,
            "-n",
            self.namespace,
            capture=False,
            timeout=120,
        )

    def telepresence_workloads(self) -> list[dict[str, Any]]:
        """List workloads as the traffic manager sees them in the application namespace."""
        return json.loads(
            self.command(
                "telepresence",
                "list",
                "--namespace",
                self.namespace,
                "--format",
                "json",
            )
        )

    def intercept_active(self, name: str) -> bool:
        """Check for an active API intercept in this cluster and namespace."""
        status = json.loads(self.command("telepresence", "status", "--format", "json"))
        user = status.get("user_daemon", {})
        if (
            user.get("kubernetes_context") != self.context
            or user.get("namespace") != self.namespace
        ):
            return False
        workloads = self.telepresence_workloads()
        # Telepresence's InterceptDispositionType.ACTIVE is protobuf enum value 1.
        for workload in workloads:
            if workload.get("name") != name:
                continue
            for info in workload.get("intercept_info", []):
                spec = info.get("spec", {})
                if spec.get("name") != name or info.get("disposition") != 1:
                    continue
                if (
                    spec.get("target_host") not in ("127.0.0.1", "localhost", "::1")
                    or spec.get("target_port") != 8080
                    or spec.get("container_port") != 8080
                ):
                    raise ValueError(
                        f"API intercept {name} must forward to localhost:8080 from container port 8080; "
                        f"leave the incompatible intercept with 'telepresence leave {name}' first"
                    )
                return True
        return False

    def api_pods(self) -> list[dict[str, Any]]:
        """List the API deployment's pods."""
        return json.loads(self.kube("get", "pods", "-l", API_SELECTOR, "-o", "json"))[
            "items"
        ]

    def agent_session_rejected(self, since: datetime) -> bool:
        """Check the API traffic agents' logs since ``since`` for a session the manager rejected."""
        try:
            logs = self.kube(
                "logs",
                "-l",
                API_SELECTOR,
                "-c",
                "traffic-agent",
                f"--since-time={since.astimezone(timezone.utc):%Y-%m-%dT%H:%M:%SZ}",
                "--prefix=true",
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False
        return bool(
            re.search(
                r'code = NotFound desc = Session "agent:|code = PermissionDenied desc = agent session .*bound to another workload identity',
                logs,
            )
        )

    def restart_api(self, name: str) -> None:
        """Restart the API deployment so Telepresence injects a fresh traffic agent."""
        self.kube("rollout", "restart", f"deployment/{name}")
        self.kube(
            "rollout",
            "status",
            f"deployment/{name}",
            "--timeout=120s",
            "--request-timeout=130s",
            timeout=135,
        )

    def create_intercept(self, name: str) -> None:
        self.command(
            "telepresence",
            "intercept",
            name,
            "--namespace",
            self.namespace,
            "--port",
            "8080:8080",
            "--mount=false",
            capture=False,
            timeout=150,
        )

    def application_ready(self, frontend_url: str, timeout: float = 180) -> None:
        name = self.api_workload()["metadata"]["name"]
        if not self.intercept_active(name):
            raise ValueError(
                "No active API intercept for the selected cluster; run make craft-intercept first"
            )
        application_ready(frontend_url, timeout)

    def intercept(self, ownership_file: Path | None = None) -> None:
        """Reuse or create the API intercept, replacing a stale traffic agent first."""
        self.connect()
        name = self.api_workload()["metadata"]["name"]
        reused = self.intercept_active(name)
        if reused:
            print(f"Reusing API intercept {name}", flush=True)
        else:
            restarted = False
            if agent_stale(
                name,
                self.telepresence_workloads(),
                self.api_pods(),
                datetime.now(timezone.utc),
            ):
                print(
                    f"Restarting {name}: its traffic agent is unknown to the traffic manager",
                    flush=True,
                )
                self.restart_api(name)
                restarted = True
            attempt_started = datetime.now(timezone.utc)
            try:
                self.create_intercept(name)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                # Retry once if the manager rejected an agent the list still reported.
                if restarted or not self.agent_session_rejected(attempt_started):
                    raise
                self.restart_api(name)
                self.create_intercept(name)
        try:
            if not reused and ownership_file is not None:
                ownership_file.write_text(name + "\n")
            self.kube(
                "rollout",
                "status",
                f"deployment/{name}",
                "--timeout=120s",
                "--request-timeout=130s",
                timeout=135,
            )
        except BaseException:
            if not reused:
                try:
                    self.command(
                        "telepresence", "leave", name, capture=False, timeout=10
                    )
                    if ownership_file is not None:
                        ownership_file.write_text("")
                except (OSError, subprocess.SubprocessError):
                    print(
                        f"Could not release API intercept {name}; leave it manually",
                        file=sys.stderr,
                    )
            raise
        print(
            "API intercept ready. Start the local API, then run make craft-ready after starting the frontend.",
            flush=True,
        )


def agent_stale(
    name: str,
    workloads: list[dict[str, Any]],
    pods: list[dict[str, Any]],
    now: datetime,
) -> bool:
    """Report a traffic agent that has run past its registration grace but is unknown to the traffic manager.

    Telepresence sets ``agent_version`` only for agents with a live manager session.
    An injected agent without one makes ``telepresence intercept`` hang or fail.
    Agents that started within the grace period may still be registering.
    """
    has_agent = any(
        status.get("name") == "traffic-agent"
        and (started := status.get("state", {}).get("running", {}).get("startedAt"))
        and now - datetime.fromisoformat(started) > AGENT_REGISTRATION_GRACE
        for pod in pods
        if not pod.get("metadata", {}).get("deletionTimestamp")
        for status in pod.get("status", {}).get("containerStatuses", [])
    )
    known = any(
        workload.get("name") == name and workload.get("agent_version")
        for workload in workloads
    )
    return has_agent and not known


def application_ready(frontend_url: str, timeout: float = 180) -> None:
    """Verify real API readiness through the frontend, then the frontend page."""
    url = urlsplit(frontend_url)
    if (
        url.scheme not in {"http", "https"}
        or not url.netloc
        or url.username
        or url.password
    ):
        raise ValueError("Frontend URL must be an HTTP(S) URL without credentials")
    base = frontend_url.rstrip("/")
    deadline = time.monotonic() + timeout
    api_reported = False
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(  # noqa: S310 - HTTP(S) scheme validated above
                f"{base}/api/health/ready",
                timeout=max(0.1, min(5, deadline - time.monotonic())),
            ) as response:
                body = json.load(response)
                api_ready = (
                    response.status == 200
                    and isinstance(body, dict)
                    and body.get("success") is True
                )
            if api_ready:
                if not api_reported:
                    print("API ready through the frontend proxy.", flush=True)
                    api_reported = True
                with urllib.request.urlopen(  # noqa: S310 - HTTP(S) scheme validated above
                    base, timeout=max(0.1, min(5, deadline - time.monotonic()))
                ) as response:
                    if (
                        response.status == 200
                        and response.headers.get_content_type() == "text/html"
                    ):
                        print(f"Frontend ready: {base}", flush=True)
                        return
        except (OSError, ValueError, urllib.error.URLError):
            pass
        time.sleep(max(0, min(1, deadline - time.monotonic())))
    raise ValueError(
        "Timed out waiting for the local API and frontend; check their logs and the API intercept, then rerun make craft-ready"
    )
