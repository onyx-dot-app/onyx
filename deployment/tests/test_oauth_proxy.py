import json
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Generator
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def get_json(url: str) -> tuple[int, dict[str, str]]:
    split = urlsplit(url)
    assert split.hostname is not None
    connection = HTTPConnection(split.hostname, split.port, timeout=2)
    try:
        connection.request("GET", split.path or "/")
        response = connection.getresponse()
        body: bytes = response.read()
        return response.status, json.loads(body) if body else {}
    finally:
        connection.close()


class MetadataBackend(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        valid: bool = self.path == "/oauth-provider/metadata" or self.path.startswith(
            "/.well-known/oauth-protected-resource/"
        )
        self.send_response(200 if valid else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"backend_path": self.path}).encode())

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture(params=["compose", "helm"])
def oauth_proxy(request: pytest.FixtureRequest, tmp_path: Path) -> Generator[str]:
    # Docker reaches this test-only upstream through host-gateway.
    backend = ThreadingHTTPServer(("0.0.0.0", 0), MetadataBackend)  # noqa: S104
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()
    container: str = f"mcp-routing-{uuid4().hex}"
    try:
        if request.param == "compose":
            fragment: str = (
                REPO_ROOT / "deployment/data/nginx/mcp.conf.inc.template"
            ).read_text()
            server: str = (
                f"server {{ listen 1024; {fragment} location / {{ return 404; }} }}"
            )
        else:
            chart: Path = REPO_ROOT / "deployment/helm/charts/onyx"
            templates: Path = tmp_path / "chart/templates"
            templates.mkdir(parents=True)
            (tmp_path / "chart/Chart.yaml").write_text(
                "apiVersion: v2\nname: onyx\nversion: 0.9.5\n"
            )
            shutil.copyfile(chart / "values.yaml", tmp_path / "chart/values.yaml")
            for name in ("_helpers.tpl", "nginx-conf.yaml"):
                shutil.copyfile(chart / "templates" / name, templates / name)
            rendered: str = subprocess.check_output(
                [
                    "helm",
                    "template",
                    "onyx",
                    str(tmp_path / "chart"),
                    "--set",
                    "mcpServer.enabled=true",
                ],
                text=True,
            )
            server = yaml.safe_load(rendered)["data"]["server.conf"].replace(
                "$$DOMAIN", "localhost"
            )
        upstreams: str = "\n".join(
            f"upstream {name} {{ server host.docker.internal:{backend.server_port}; }}"
            for name in ("api_server", "mcp_server", "web_server")
        )
        config: Path = tmp_path / "nginx.conf"
        config.write_text(
            "events {}\nhttp {\n"
            + upstreams
            + "\nmap $http_upgrade $connection_upgrade { default upgrade; '' close; }\n"
            + server
            + "\n}\n"
        )
        subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                container,
                "--add-host",
                "host.docker.internal:host-gateway",
                "--publish",
                "127.0.0.1::1024",
                "--volume",
                f"{config}:/etc/nginx/nginx.conf:ro",
                os.environ.get("MCP_PROXY_NGINX_IMAGE", "nginx:1.25.5-alpine"),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        address: str = subprocess.check_output(
            ["docker", "port", container, "1024/tcp"], text=True
        ).strip()
        deadline: float = time.monotonic() + 20
        while True:
            try:
                get_json(
                    f"http://{address}/.well-known/oauth-authorization-server/api/oauth-provider"
                )
                break
            except (OSError, json.JSONDecodeError):
                if time.monotonic() >= deadline:
                    logs: str = subprocess.check_output(
                        ["docker", "logs", container],
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                    pytest.fail(f"nginx did not start: {logs}")
                time.sleep(0.1)
        yield f"http://{address}"
    finally:
        subprocess.run(["docker", "rm", "--force", container], capture_output=True)
        backend.shutdown()
        backend.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize(
    "suffix", ["", "/", "/mcp", "/api/oauth-provider", "/api/oauth-provider/"]
)
def test_authorization_metadata_aliases_reach_api(
    oauth_proxy: str, suffix: str
) -> None:
    status, body = get_json(
        oauth_proxy + "/.well-known/oauth-authorization-server" + suffix
    )
    assert status == 200
    assert body["backend_path"] == "/oauth-provider/metadata"


@pytest.mark.parametrize("suffix", ["/mcp", "/mcp/"])
def test_protected_resource_metadata_keeps_its_path(
    oauth_proxy: str, suffix: str
) -> None:
    path: str = "/.well-known/oauth-protected-resource" + suffix
    status, body = get_json(oauth_proxy + path)
    assert status == 200
    assert body["backend_path"] == path
