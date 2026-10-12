"""Docker sandbox networking through the deployed frontend and real proxy."""

import ipaddress
import json
import os
import subprocess
from collections.abc import Generator
from typing import Any
from urllib.parse import SplitResult, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest

from onyx.server.features.build.models import UploadResponse
from onyx.server.features.build.session.models import DetailedSessionResponse
from tests.common.craft.local_http_probe import LOCAL_HTTP_PROBE
from tests.common.craft.proxy_probe import PROXY_PROBE
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.docker_e2e.conftest import (
    SANDBOX_EXEC_ENV,
    SANDBOX_EXEC_USER,
    DockerSandbox,
    exec_container,
    start_session_webapp,
)
from tests.integration.tests.craft.webapp_preview import (
    proxy_get,
    wait_for_webapp_ready,
)


def docker(*args: str, timeout: int = 60) -> str:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=True, timeout=timeout
    ).stdout.strip()


def execute(sandbox: DockerSandbox, *args: str) -> str:
    result: subprocess.CompletedProcess[str] = exec_container(
        sandbox.container_name,
        list(args),
        user=SANDBOX_EXEC_USER,
        env=SANDBOX_EXEC_ENV,
        timeout=60,
    )
    result.check_returncode()
    return result.stdout.strip()


@pytest.fixture(scope="module")
def owner() -> DATestUser:
    return UserManager.create(name=f"docker-networking-{uuid4().hex[:10]}")


@pytest.fixture(scope="module")
def sandbox(owner: DATestUser) -> Generator[DockerSandbox, None, None]:
    session: DetailedSessionResponse = BuildSessionManager.create(owner, headless=False)
    assert session.sandbox
    container: str = f"sandbox-{session.sandbox.id.split('-')[0]}"
    result: DockerSandbox = DockerSandbox(
        session_id=UUID(session.id), container_name=container
    )
    try:
        yield result
    finally:
        try:
            response: httpx.Response = client.delete(
                f"{API_SERVER_URL}/build/sessions/{session.id}",
                headers=owner.headers,
                cookies=owner.cookies,
            )
            response.raise_for_status()
        finally:
            docker("rm", "-f", container)


def probe(
    sandbox: DockerSandbox,
    method: str,
    host: str,
    port: int,
    path: str = "/",
    scheme: str = "http",
) -> dict[str, Any]:
    return json.loads(
        execute(
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


def test_bridge_address_and_listener(sandbox: DockerSandbox) -> None:
    info: dict[str, Any] = json.loads(docker("inspect", sandbox.container_name))[0]
    bridges: dict[str, dict[str, Any]] = info["NetworkSettings"]["Networks"]
    assert len(bridges) == 1, bridges
    bridge: dict[str, Any] = next(iter(bridges.values()))
    family: str = os.environ["SANDBOX_TEST_IP_FAMILY"]
    if family == "ipv6":
        assert not bridge["IPAddress"], bridge
        assert ipaddress.ip_address(bridge["GlobalIPv6Address"]).version == 6
        assert execute(sandbox, "printenv", "SANDBOX_LISTEN_HOST") == "::"
    else:
        assert ipaddress.ip_address(bridge["IPAddress"]).version == 4
        assert not bridge["GlobalIPv6Address"], bridge
    status: str = execute(
        sandbox, "sh", "-c", 'cat /proc/$(pgrep -f "opencode serve" | head -n 1)/status'
    )
    assert (
        next(line for line in status.splitlines() if line.startswith("Uid:")).split()[
            1:
        ]
        == ["1000"] * 4
    )
    assert (
        next(
            line for line in status.splitlines() if line.startswith("CapBnd:")
        ).split()[1]
        == "0000000000000000"
    )


def test_local_http_bypasses_proxy(sandbox: DockerSandbox) -> None:
    host: str = "::1" if os.environ["SANDBOX_TEST_IP_FAMILY"] == "ipv6" else "127.0.0.1"
    # Curl inherits the sandbox's proxy settings. A local request must bypass the proxy.
    assert (
        execute(sandbox, "python3", "-c", LOCAL_HTTP_PROBE, host)
        == "sandbox loopback verified"
    )


def test_public_https(sandbox: DockerSandbox) -> None:
    assert execute(
        sandbox,
        "curl",
        "--fail",
        "--silent",
        "--show-error",
        "--max-time",
        "30",
        os.environ.get("SANDBOX_TEST_PUBLIC_URL", "https://example.com"),
    )


def test_api_identity(sandbox: DockerSandbox, owner: DATestUser) -> None:
    api: SplitResult = urlsplit(execute(sandbox, "printenv", "ONYX_SERVER_URL"))
    assert api.hostname
    port: int = api.port or (443 if api.scheme == "https" else 80)
    result: dict[str, Any] = probe(
        sandbox, "GET", api.hostname, port, api.path.rstrip("/") + "/me", api.scheme
    )
    assert result["status"] == 200, result
    assert json.loads(result["body"])["email"] == owner.email
    assert probe(sandbox, "CONNECT", api.hostname, port)["status"] == 200
    assert probe(sandbox, "GET", api.hostname, port + 1)["status"] == 403


@pytest.mark.parametrize("method", ["GET", "CONNECT"])
@pytest.mark.parametrize(
    "host",
    [
        "10.0.0.1",
        "169.254.169.254",
        "fd42:6f6e:7978::1",
        "::1",
        "::ffff:10.0.0.1",
        "64:ff9b::a9fe:a9fe",
    ],
)
def test_internal_destinations_denied(
    sandbox: DockerSandbox, method: str, host: str
) -> None:
    result: dict[str, Any] = probe(sandbox, method, host, 80)
    assert result["status"] == 403, result
    assert json.loads(result["body"])["error"] == "destination_blocked"


def test_direct_egress_denied(sandbox: DockerSandbox) -> None:
    # The proxy is reachable on the sandbox bridge. Its health port is reachable
    # from the host but is deliberately excluded from the sandbox firewall.
    proxy: SplitResult = urlsplit(execute(sandbox, "printenv", "HTTP_PROXY"))
    assert proxy.hostname
    addresses: list[str] = json.loads(
        execute(
            sandbox,
            "python3",
            "-c",
            "import socket,json,sys; print(json.dumps([a[4][0] for a in socket.getaddrinfo(sys.argv[1],8080,type=socket.SOCK_STREAM)]))",
            proxy.hostname,
        )
    )
    address: str = addresses[0]
    container: dict[str, Any] = json.loads(docker("inspect", sandbox.container_name))[0]
    network: str = next(iter(container["NetworkSettings"]["Networks"]))
    proxy_info: dict[str, Any] = json.loads(docker("network", "inspect", network))[0]
    proxies: list[dict[str, str]] = [
        c for c in proxy_info["Containers"].values() if "sandbox-proxy" in c["Name"]
    ]
    assert len(proxies) == 1, proxies

    authority: str = f"[{address}]" if ":" in address else address
    assert docker(
        "run",
        "--rm",
        "--network",
        network,
        "--entrypoint",
        "curl",
        container["Config"]["Image"],
        "--fail",
        "--silent",
        "--noproxy",
        "*",
        f"http://{authority}:8081/healthz",
    )
    rc: str = execute(
        sandbox,
        "sh",
        "-c",
        'curl --noproxy "*" --silent --max-time 3 "$1" >/dev/null; echo $?',
        "probe",
        f"http://{authority}:8081/healthz",
    )
    assert rc in {"7", "28"}, rc


def test_unknown_client_denied(sandbox: DockerSandbox) -> None:
    info: dict[str, Any] = json.loads(docker("inspect", sandbox.container_name))[0]
    network: str = next(iter(info["NetworkSettings"]["Networks"]))
    image: str = info["Config"]["Image"]
    proxy: str = execute(sandbox, "printenv", "HTTP_PROXY")
    assert (
        docker(
            "run",
            "--rm",
            "--network",
            network,
            "--entrypoint",
            "curl",
            image,
            "--silent",
            "--output",
            "/dev/null",
            "--write-out",
            "%{http_code}",
            "--max-time",
            "10",
            "--proxy",
            proxy,
            "http://1.1.1.1/",
        )
        == "403"
    )


def test_upload_and_preview(sandbox: DockerSandbox, owner: DATestUser) -> None:
    content: bytes = b"docker networking verified"
    uploaded: UploadResponse = BuildSessionManager.upload_file(
        owner, sandbox.session_id, "networking.txt", content
    )
    assert uploaded.size_bytes == len(content)
    assert (
        execute(
            sandbox, "cat", f"/workspace/sessions/{sandbox.session_id}/{uploaded.path}"
        )
        == content.decode()
    )
    start_session_webapp(sandbox.container_name, sandbox.session_id)
    base: str = f"/workspace/sessions/{sandbox.session_id}/outputs/web/app"
    files: dict[str, str] = {
        f"{base}/layout.tsx": "export default function Layout({children}:{children:React.ReactNode}){return <html><body>{children}</body></html>}",
        f"{base}/page.tsx": "export default function Page(){return <main>docker networking verified</main>}",
    }
    execute(
        sandbox,
        "python3",
        "-c",
        "import json,pathlib,sys; [pathlib.Path(p).write_text(s) for p,s in json.loads(sys.argv[1]).items()]",
        json.dumps(files),
    )
    wait_for_webapp_ready(owner, str(sandbox.session_id))
    response: httpx.Response = proxy_get(owner, str(sandbox.session_id))
    assert response.status_code == 200, response.text
    assert "docker networking verified" in response.text
