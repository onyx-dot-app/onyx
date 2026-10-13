"""Observable sandbox isolation and connectivity on IPv4 or IPv6 deployments."""

import ipaddress
import json
import os
import re
import subprocess
from collections.abc import Generator
from typing import Any, NamedTuple
from urllib.parse import SplitResult, urlsplit
from uuid import UUID, uuid4

import pytest

from tests.common.craft.local_http_probe import LOCAL_HTTP_PROBE
from tests.common.craft.proxy_probe import PROXY_PROBE
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.webapp_preview import (
    proxy_get,
    wait_for_webapp_ready,
    webapp_bootstrap_command,
)


class Sandbox(NamedTuple):
    owner: DATestUser
    session_id: UUID
    pod: str


def kubectl(namespace: str, *args: str, timeout: int = 60) -> str:
    return subprocess.run(
        [
            "kubectl",
            "--context",
            os.environ["SANDBOX_TEST_KUBE_CONTEXT"],
            "--namespace",
            namespace,
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=timeout,
    ).stdout


def sandbox_namespace() -> str:
    return os.environ.get("SANDBOX_TEST_NAMESPACE", "onyx-sandboxes")


def app_namespace() -> str:
    return os.environ.get("SANDBOX_TEST_APP_NAMESPACE", "onyx")


def proxy_pod() -> str:
    pods: list[dict[str, Any]] = json.loads(
        kubectl(app_namespace(), "get", "pods", "-o", "json")
    )["items"]
    proxies: list[dict[str, Any]] = [
        pod
        for pod in pods
        if any(
            container["name"] == "sandbox-proxy"
            for container in pod["spec"]["containers"]
        )
        and all(
            status["ready"] for status in pod["status"].get("containerStatuses", [])
        )
        and pod["status"].get("phase") == "Running"
    ]
    assert proxies, "No ready sandbox-proxy pod found"
    return proxies[0]["metadata"]["name"]


def exec_proxy(*command: str) -> str:
    return kubectl(
        app_namespace(), "exec", proxy_pod(), "-c", "sandbox-proxy", "--", *command
    )


def exec_sandbox(sandbox: Sandbox, *command: str, timeout: int = 60) -> str:
    return kubectl(
        sandbox_namespace(),
        "exec",
        sandbox.pod,
        "-c",
        "sandbox",
        "--",
        *command,
        timeout=timeout,
    )


@pytest.fixture(scope="module")
def sandbox() -> Generator[Sandbox, None, None]:
    owner: DATestUser = UserManager.create(
        name=f"sandbox-networking-{uuid4().hex[:10]}"
    )
    session_id, sandbox_id = BuildSessionManager.create_with_sandbox(
        owner, headless=False
    )
    try:
        pods: list[dict[str, Any]] = json.loads(
            kubectl(
                sandbox_namespace(),
                "get",
                "pods",
                "-l",
                f"onyx.app/sandbox-id={sandbox_id}",
                "-o",
                "json",
            )
        )["items"]
        assert len(pods) == 1, pods
        yield Sandbox(owner, session_id, pods[0]["metadata"]["name"])
    finally:
        try:
            response = client.delete(
                f"{API_SERVER_URL}/build/sessions/{session_id}",
                headers=owner.headers,
                cookies=owner.cookies,
            )
            response.raise_for_status()
        finally:
            # Session deletion retains the per-user pod. Reap only our new sandbox.
            kubectl(
                sandbox_namespace(),
                "delete",
                "pods",
                "-l",
                f"onyx.app/sandbox-id={sandbox_id}",
                "--ignore-not-found",
                "--wait=false",
            )


def api_url(sandbox: Sandbox) -> str:
    return exec_sandbox(sandbox, "printenv", "ONYX_SERVER_URL").strip()


def proxy_probe(
    sandbox: Sandbox,
    method: str,
    host: str,
    port: int,
    path: str = "/",
    *,
    scheme: str = "http",
) -> dict[str, Any]:
    return json.loads(
        exec_sandbox(
            sandbox,
            "python3",
            "-c",
            PROXY_PROBE,
            json.dumps(
                {
                    "method": method,
                    "host": host,
                    "port": port,
                    "path": path,
                    "scheme": scheme,
                }
            ),
        )
    )


def test_single_stack_and_public_egress(sandbox: Sandbox) -> None:
    pod: dict[str, Any] = json.loads(
        kubectl(sandbox_namespace(), "get", "pod", sandbox.pod, "-o", "json")
    )
    ips: list[dict[str, str]] = pod["status"]["podIPs"]
    assert len(ips) == 1, ips
    assert ipaddress.ip_address(ips[0]["ip"]).version == (
        6 if os.environ["SANDBOX_TEST_IP_FAMILY"] == "ipv6" else 4
    )
    assert all(status["ready"] for status in pod["status"]["containerStatuses"])
    public_url: str = os.environ.get("SANDBOX_TEST_PUBLIC_URL", "https://example.com")
    output: str = exec_sandbox(
        sandbox,
        "curl",
        "--fail",
        "--silent",
        "--show-error",
        "--max-time",
        "30",
        public_url,
    )
    assert output.strip(), "Public HTTPS returned no content"


def test_exact_api_exception_and_pat_injection(sandbox: Sandbox) -> None:
    api: SplitResult = urlsplit(api_url(sandbox))
    assert api.hostname
    port: int = api.port or (443 if api.scheme == "https" else 80)
    response = proxy_probe(
        sandbox,
        "GET",
        api.hostname,
        port,
        api.path.rstrip("/") + "/me",
        scheme=api.scheme,
    )
    assert response["status"] == 200, response
    assert json.loads(response["body"])["email"] == sandbox.owner.email
    assert proxy_probe(sandbox, "CONNECT", api.hostname, port)["status"] == 200


def test_ipv6_neighbor_discovery_after_cache_flush(sandbox: Sandbox) -> None:
    if os.environ["SANDBOX_TEST_IP_FAMILY"] != "ipv6":
        pytest.skip("Neighbor discovery applies to IPv6")
    if os.environ.get("SANDBOX_TEST_FLUSH_NEIGHBORS") != "true":
        pytest.skip("Enable SANDBOX_TEST_FLUSH_NEIGHBORS=true on a local kind cluster")
    assert os.environ["SANDBOX_TEST_KUBE_CONTEXT"].startswith("kind-"), (
        "Cache flush requires kind"
    )
    pod: dict[str, Any] = json.loads(
        kubectl(sandbox_namespace(), "get", "pod", sandbox.pod, "-o", "json")
    )
    node: str = pod["spec"]["nodeName"]

    def docker(*command: str) -> str:
        return subprocess.run(
            ["docker", *command], capture_output=True, text=True, check=True, timeout=30
        ).stdout.strip()

    runtime_ids: list[str] = docker(
        "exec", node, "crictl", "pods", "--name", sandbox.pod, "-q"
    ).splitlines()
    assert len(runtime_ids) == 1, runtime_ids
    runtime: dict[str, Any] = json.loads(
        docker("exec", node, "crictl", "inspectp", runtime_ids[0])
    )
    pid: str = str(runtime["info"]["pid"])
    prefix: list[str] = ["exec", "--privileged", node, "nsenter", "-t", pid, "-n"]
    assert docker(*prefix, "ip", "-6", "neigh", "show", "dev", "eth0")
    flushed: str = docker(
        *prefix, "ip", "-6", "-statistics", "neigh", "flush", "dev", "eth0"
    )
    assert (
        sum(int(count) for count in re.findall(r"deleting (\d+) entries", flushed)) > 0
    ), flushed
    # Health probes may restore neighbors before the next exec. Verify the flush itself.
    test_exact_api_exception_and_pat_injection(sandbox)
    assert docker(*prefix, "ip", "-6", "neigh", "show", "dev", "eth0")


@pytest.mark.parametrize("method", ["GET", "CONNECT"])
@pytest.mark.parametrize(
    "host",
    [
        "10.0.0.1",
        "169.254.169.254",
        "::1",
        "::ffff:10.0.0.1",
        "64:ff9b::a00:1",
        "64:ff9b::a9fe:a9fe",
    ],
)
def test_internal_destinations_blocked(
    sandbox: Sandbox, method: str, host: str
) -> None:
    response = proxy_probe(sandbox, method, host, 80)
    assert response["status"] == 403, response
    assert json.loads(response["body"])["error"] == "destination_blocked"


@pytest.mark.parametrize("method", ["GET", "CONNECT"])
def test_api_exception_requires_exact_port(sandbox: Sandbox, method: str) -> None:
    api: SplitResult = urlsplit(api_url(sandbox))
    assert api.hostname
    port: int = api.port or (443 if api.scheme == "https" else 80)
    response = proxy_probe(sandbox, method, api.hostname, port + 1, scheme=api.scheme)
    assert response["status"] == 403, response
    assert json.loads(response["body"])["error"] == "destination_blocked"


def test_direct_egress_is_blocked(sandbox: Sandbox) -> None:
    api: SplitResult = urlsplit(api_url(sandbox))
    assert api.hostname
    port: int = api.port or (443 if api.scheme == "https" else 80)
    assert (
        proxy_probe(
            sandbox,
            "GET",
            api.hostname,
            port,
            api.path.rstrip("/") + "/me",
            scheme=api.scheme,
        )["status"]
        == 200
    )
    # Sandbox DNS is intentionally blocked; resolve from the trusted proxy instead.
    addresses: list[str] = json.loads(
        exec_proxy(
            "python3",
            "-c",
            "import json,socket,sys; print(json.dumps([a[4][0] for a in socket.getaddrinfo(sys.argv[1],None,type=socket.SOCK_STREAM)]))",
            api.hostname,
        )
    )
    host: str = addresses[0]
    authority: str = f"[{host}]" if ":" in host else host
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [
            "kubectl",
            "--context",
            os.environ["SANDBOX_TEST_KUBE_CONTEXT"],
            "-n",
            sandbox_namespace(),
            "exec",
            sandbox.pod,
            "-c",
            "sandbox",
            "--",
            "curl",
            "--noproxy",
            "*",
            "--silent",
            "--show-error",
            "--max-time",
            "3",
            f"{api.scheme}://{authority}:{port}{api.path.rstrip('/')}/me",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode in {7, 28}, result.stderr


@pytest.mark.parametrize("method", ["GET", "CONNECT"])
def test_unknown_client_rejected(sandbox: Sandbox, method: str) -> None:
    proxy: SplitResult = urlsplit(
        exec_sandbox(sandbox, "printenv", "HTTP_PROXY").strip()
    )
    local: str = (
        "::1" if os.environ["SANDBOX_TEST_IP_FAMILY"] == "ipv6" else "127.0.0.1"
    )
    response = json.loads(
        exec_proxy(
            "python3",
            "-c",
            PROXY_PROBE,
            json.dumps(
                {
                    "method": method,
                    "host": "1.1.1.1",
                    "port": 443,
                    "local": local,
                    "proxy_port": proxy.port or 8080,
                }
            ),
        )
    )
    assert response["status"] == 403, response
    assert json.loads(response["body"])["error"] == "unidentified_sandbox"


def test_upload_reaches_signed_sidecar(sandbox: Sandbox) -> None:
    content: bytes = b"sandbox networking upload round trip\n"
    uploaded = BuildSessionManager.upload_file(
        sandbox.owner, sandbox.session_id, "networking.txt", content
    )
    assert uploaded.size_bytes == len(content)
    actual: str = exec_sandbox(
        sandbox, "cat", f"/workspace/sessions/{sandbox.session_id}/{uploaded.path}"
    )
    assert actual.encode() == content
    listing = BuildSessionManager.list_files(
        sandbox.owner, sandbox.session_id, "attachments"
    )
    assert uploaded.filename in {entry.name for entry in listing.entries}


def test_generated_webapp_preview(sandbox: Sandbox) -> None:
    output: str = exec_sandbox(
        sandbox, "bash", "-c", webapp_bootstrap_command(sandbox.session_id), timeout=420
    )
    assert "dev server running on port" in output, output[-2000:]
    # Avoid template font downloads while checking the actual generated Next server.
    base: str = f"/workspace/sessions/{sandbox.session_id}/outputs/web/app"
    files: dict[str, str] = {
        f"{base}/layout.tsx": "export default function Layout({children}:{children:React.ReactNode}){return <html><body>{children}</body></html>}",
        f"{base}/page.tsx": "export default function Page(){return <main>networking preview verified</main>}",
    }
    exec_sandbox(
        sandbox,
        "python3",
        "-c",
        "import json,pathlib,sys; [pathlib.Path(p).write_text(s) for p,s in json.loads(sys.argv[1]).items()]",
        json.dumps(files),
    )
    wait_for_webapp_ready(sandbox.owner, str(sandbox.session_id))
    response = proxy_get(sandbox.owner, str(sandbox.session_id))
    assert response.status_code == 200, response.text[:500]
    assert "networking preview verified" in response.text


def test_local_http_bypasses_proxy(sandbox: Sandbox) -> None:
    host: str = "::1" if os.environ["SANDBOX_TEST_IP_FAMILY"] == "ipv6" else "127.0.0.1"
    assert (
        exec_sandbox(sandbox, "python3", "-c", LOCAL_HTTP_PROBE, host).strip()
        == "sandbox loopback verified"
    )
