"""Test-owned HTTPS proxy and OAuth service fixtures for CIMD."""

from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
import tarfile
import threading
import time
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import docker
import httpx
import pytest
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from docker.client import DockerClient
from docker.errors import NotFound
from docker.models.containers import Container
from fastapi.testclient import TestClient

from onyx.server.features.mcp import client_metadata
from tests.integration.common_utils.cimd_oauth import (
    CimdHttpsEndpoint,
    CimdOAuthTestServices,
)

NGINX_IMAGE = os.getenv("MCP_CIMD_NGINX_IMAGE", "nginx:1.25.5-alpine")
DOCKER_NETWORK = "onyx_default"
NGINX_HTTPS_PORT = "443/tcp"
STARTUP_TIMEOUT_SECONDS = 30.0

MOCK_SERVER_DIR = (
    Path(__file__).resolve().parents[2] / "mock_services" / "mcp_test_server"
)
MOCK_OIDC_SCRIPT = MOCK_SERVER_DIR / "run_mock_oidc_idp.py"
MCP_OAUTH_SERVER_SCRIPT = MOCK_SERVER_DIR / "run_mcp_server_oauth.py"


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("0.0.0.0", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(
    host: str,
    port: int,
    process: subprocess.Popen[bytes] | None = None,
) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(
                f"Process exited during startup with code {process.returncode}"
            )
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            try:
                sock.connect((host, port))
                return
            except OSError:
                time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for {host}:{port}")


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _docker_network(client: DockerClient) -> str | None:
    try:
        client.networks.get(DOCKER_NETWORK)
    except NotFound:
        return None
    return DOCKER_NETWORK


def _copy_to_container(
    container: Container,
    destination: str,
    files: dict[str, bytes],
) -> None:
    archive_buffer = io.BytesIO()
    with tarfile.open(fileobj=archive_buffer, mode="w") as archive:
        for filename, content in files.items():
            info = tarfile.TarInfo(filename)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    archive_buffer.seek(0)
    if not container.put_archive(destination, archive_buffer.read()):
        raise RuntimeError(f"Failed to copy files into {container.name}")


def _write_certificate(directory: Path, hostname: str) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName(hostname),
                    x509.DNSName("localhost"),
                    x509.DNSName("host.docker.internal"),
                ]
            ),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )

    certificate_path = directory / "mcp-cimd.crt"
    key_path = directory / "mcp-cimd.key"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return certificate_path, key_path


def _nginx_config(upstream_host: str, upstream_port: int) -> str:
    return f"""
events {{}}
http {{
    server {{
        listen 443 ssl;
        ssl_certificate /etc/nginx/mcp-cimd.crt;
        ssl_certificate_key /etc/nginx/mcp-cimd.key;

        location /api/ {{
            rewrite ^/api/(.*)$ /$1 break;
            proxy_pass http://{upstream_host}:{upstream_port};
            proxy_set_header Host $host;
        }}
    }}
}}
"""


@pytest.fixture(scope="session")
def cimd_api_server(
    _test_client: TestClient,
) -> Generator[int, None, None]:
    port = _available_port()
    server = uvicorn.Server(
        uvicorn.Config(
            _test_client.app,
            host="0.0.0.0",
            port=port,
            log_level="warning",
            lifespan="off",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _wait_for_port("127.0.0.1", port)

    try:
        yield port
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture(scope="session")
def cimd_https_endpoint(
    cimd_api_server: int,
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[CimdHttpsEndpoint, None, None]:
    in_test_container = os.getenv("TEST_WEB_HOSTNAME") == "test-runner"
    public_host = "host.docker.internal" if in_test_container else "localhost"
    upstream_host = "test-runner" if in_test_container else "host.docker.internal"
    directory = tmp_path_factory.mktemp("mcp-cimd-tls")
    certificate_path, key_path = _write_certificate(directory, public_host)
    config_path = directory / "nginx.conf"
    config_path.write_text(
        _nginx_config(upstream_host, cimd_api_server),
        encoding="utf-8",
    )

    docker_client = docker.from_env()
    container: Container | None = None
    old_web_domain = client_metadata.WEB_DOMAIN
    try:
        container = docker_client.containers.create(
            NGINX_IMAGE,
            name=f"mcp-cimd-nginx-{uuid4().hex[:12]}",
            ports={NGINX_HTTPS_PORT: None},
            extra_hosts={"host.docker.internal": "host-gateway"},
            network=_docker_network(docker_client),
        )
        _copy_to_container(
            container,
            "/etc/nginx",
            {
                "nginx.conf": config_path.read_bytes(),
                "mcp-cimd.crt": certificate_path.read_bytes(),
                "mcp-cimd.key": key_path.read_bytes(),
            },
        )
        container.start()
        container.reload()

        port_bindings = container.attrs["NetworkSettings"]["Ports"][NGINX_HTTPS_PORT]
        if not port_bindings:
            raise RuntimeError("Nginx HTTPS port was not published")
        host_port = str(port_bindings[0]["HostPort"])
        origin = f"https://{public_host}:{host_port}"
        setattr(client_metadata, "WEB_DOMAIN", origin)

        metadata_url = f"{origin}/api/mcp/oauth/client-metadata"
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            try:
                response = httpx.get(
                    metadata_url,
                    verify=str(certificate_path),
                    timeout=1,
                )
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            logs = container.logs().decode(errors="replace")
            raise RuntimeError(f"CIMD HTTPS endpoint did not start:\n{logs}")

        yield CimdHttpsEndpoint(origin=origin, ca_file=certificate_path)
    finally:
        setattr(client_metadata, "WEB_DOMAIN", old_web_domain)
        if container is not None:
            container.remove(force=True)
        docker_client.close()


@pytest.fixture(scope="module")
def cimd_oauth_services(
    cimd_https_endpoint: CimdHttpsEndpoint,
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[CimdOAuthTestServices, None, None]:
    oidc_port = _available_port()
    mcp_port = _available_port()
    oidc_issuer = f"http://127.0.0.1:{oidc_port}"
    mcp_server_url = f"http://127.0.0.1:{mcp_port}/mcp"
    client_metadata_url = f"{cimd_https_endpoint.origin}/api/mcp/oauth/client-metadata"
    log_directory = tmp_path_factory.mktemp("mcp-cimd-services")
    oidc_log = (log_directory / "oidc.log").open("wb")
    mcp_log = (log_directory / "mcp.log").open("wb")

    oidc_env = {
        **os.environ,
        "MOCK_OIDC_PORT": str(oidc_port),
        "MOCK_OIDC_BIND_HOST": "0.0.0.0",
        "MOCK_OIDC_ISSUER": oidc_issuer,
        "MOCK_OIDC_CIMD_ONLY": "true",
        "MOCK_OIDC_EXPECTED_CLIENT_ID": client_metadata_url,
        "MOCK_OIDC_CLIENT_METADATA_CA_FILE": str(cimd_https_endpoint.ca_file),
    }
    oidc_process = subprocess.Popen(
        [sys.executable, str(MOCK_OIDC_SCRIPT), str(oidc_port)],
        cwd=MOCK_SERVER_DIR,
        env=oidc_env,
        stdout=oidc_log,
        stderr=subprocess.STDOUT,
    )

    mcp_process: subprocess.Popen[bytes] | None = None
    try:
        _wait_for_port("127.0.0.1", oidc_port, oidc_process)
        mcp_env = {
            **os.environ,
            "MCP_SERVER_HOST": "0.0.0.0",
            "MCP_SERVER_PUBLIC_URL": mcp_server_url,
            "MCP_OAUTH_ISSUER": oidc_issuer,
            "MCP_OAUTH_JWKS_URI": f"{oidc_issuer}/jwks",
            "MCP_OAUTH_AUDIENCE": "api://mcp",
            "MCP_OAUTH_REQUIRED_SCOPES": "mcp:use",
        }
        mcp_process = subprocess.Popen(
            [sys.executable, str(MCP_OAUTH_SERVER_SCRIPT), str(mcp_port)],
            cwd=MOCK_SERVER_DIR,
            env=mcp_env,
            stdout=mcp_log,
            stderr=subprocess.STDOUT,
        )
        _wait_for_port("127.0.0.1", mcp_port, mcp_process)

        yield CimdOAuthTestServices(
            mcp_server_url=mcp_server_url,
            oidc_issuer=oidc_issuer,
            client_metadata_url=client_metadata_url,
        )
    finally:
        if mcp_process is not None:
            _stop_process(mcp_process)
        _stop_process(oidc_process)
        mcp_log.close()
        oidc_log.close()
