"""Shared Kubernetes configuration and readiness for local Craft processes."""

import base64
import ipaddress
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class Cluster:
    root: Path
    name: str = "onyx-dev"
    namespace: str = "onyx"
    sandbox_namespace: str = "onyx-sandboxes"

    @property
    def context(self) -> str:
        return f"kind-{self.name}"

    def command(self, *args: str, capture: bool = True, timeout: float = 30) -> str:
        result = subprocess.run(
            args,
            cwd=self.root,
            check=True,
            text=True,
            timeout=timeout,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
        return result.stdout.strip() if capture else ""

    def kube(
        self, *args: str, namespace: str | None = None, timeout: float = 30
    ) -> str:
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
        items = json.loads(
            self.kube(
                "get",
                "deployments",
                "-l",
                "app=api-server,app.kubernetes.io/instance=onyx",
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
        if host == "localhost" or "." in host or ":" in host:
            return host
        try:
            ipaddress.ip_address(host)
            return host
        except ValueError:
            return f"{host}.{self.namespace}.svc.cluster.local"

    def infrastructure_ready(self, timeout: float = 600) -> None:
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

    def intercept_active(self, name: str) -> bool:
        status = json.loads(self.command("telepresence", "status", "--format", "json"))
        user = status.get("user_daemon", {})
        if (
            user.get("kubernetes_context") != self.context
            or user.get("namespace") != self.namespace
        ):
            return False
        workloads = json.loads(
            self.command(
                "telepresence",
                "list",
                "--namespace",
                self.namespace,
                "--format",
                "json",
            )
        )
        # Telepresence's InterceptDispositionType.ACTIVE is protobuf enum value 1.
        return any(
            info.get("disposition") == 1 and info.get("spec", {}).get("name") == name
            for workload in workloads
            if workload.get("name") == name
            for info in workload.get("intercept_info", [])
        )

    def application_ready(self, frontend_url: str, timeout: float = 180) -> None:
        name = self.api_workload()["metadata"]["name"]
        if not self.intercept_active(name):
            raise ValueError(
                "No active API intercept for the selected cluster; run make craft-intercept first"
            )
        application_ready(frontend_url, timeout)

    def intercept(self) -> None:
        self.connect()
        name = self.api_workload()["metadata"]["name"]
        if self.intercept_active(name):
            print(f"Reusing API intercept {name}", flush=True)
        else:
            try:
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
            except subprocess.CalledProcessError:
                # Retry once only for the known stale-agent identity failure.
                logs = self.kube(
                    "logs",
                    "-l",
                    "app=api-server,app.kubernetes.io/instance=onyx",
                    "-c",
                    "traffic-agent",
                    "--since=2m",
                    "--tail=1",
                    "--prefix=true",
                )
                if not re.search(
                    r'code = NotFound desc = Session "agent:|code = PermissionDenied desc = agent session .*bound to another workload identity',
                    logs,
                ):
                    raise
                self.kube("rollout", "restart", f"deployment/{name}")
                self.kube(
                    "rollout",
                    "status",
                    f"deployment/{name}",
                    "--timeout=120s",
                    "--request-timeout=130s",
                    timeout=135,
                )
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
        self.kube(
            "rollout",
            "status",
            f"deployment/{name}",
            "--timeout=120s",
            "--request-timeout=130s",
            timeout=135,
        )
        print(
            "API intercept ready. Start the local API, then run make craft-ready after starting the frontend.",
            flush=True,
        )


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
