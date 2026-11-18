import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

import pytest
import yaml

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
NGINX_DIR: Path = REPO_ROOT / "deployment/data/nginx"
BASE_FILES: tuple[str, ...] = ("app.conf.template", "run-nginx.sh")
INCLUDE_FILES: tuple[str, ...] = (
    "mcp.conf.inc.template",
    "mcp_upstream.conf.inc.template",
    "webhook.conf.inc",
)


def start_nginx(tmp_path: Path, files: tuple[str, ...], mcp_enabled: str) -> str:
    for name in files:
        shutil.copy2(NGINX_DIR / name, tmp_path / name)
    compose: dict = yaml.safe_load(
        (REPO_ROOT / "deployment/docker_compose/docker-compose.yml").read_text()
    )
    command: str = compose["services"]["nginx"]["command"]
    container: str = f"run-nginx-{uuid4().hex}"
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                container,
                *(
                    arg
                    for host in ("api_server", "web_server", "mcp_server")
                    for arg in ("--add-host", f"{host}:127.0.0.1")
                ),
                "--env",
                "DOMAIN=localhost",
                "--env",
                f"MCP_SERVER_ENABLED={mcp_enabled}",
                "--publish",
                "127.0.0.1::80",
                "--volume",
                f"{tmp_path}:/nginx-templates:ro",
                os.environ.get("MCP_PROXY_NGINX_IMAGE", "nginx:1.30.7-alpine"),
                "/bin/sh",
                "-c",
                command,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        address: str = subprocess.check_output(
            ["docker", "port", container, "80/tcp"], text=True
        ).strip()
        deadline: float = time.monotonic() + 20
        while True:
            try:
                with urlopen(f"http://{address}/nginx-health", timeout=2) as response:
                    assert response.status == 200
                break
            except (OSError, URLError):
                if time.monotonic() >= deadline:
                    pytest.fail(f"nginx did not start: {logs(container)}")
                time.sleep(0.2)
        return logs(container)
    finally:
        subprocess.run(["docker", "rm", "--force", container], capture_output=True)


def logs(container: str) -> str:
    return subprocess.run(
        ["docker", "logs", container],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ).stdout


def test_nginx_renders_mcp_routes_from_the_templates(tmp_path: Path) -> None:
    output: str = start_nginx(tmp_path, BASE_FILES + INCLUDE_FILES, "true")
    assert "MCP server is enabled, creating MCP configuration" in output
    assert "WARNING" not in output


@pytest.mark.parametrize("mcp_enabled", ["true", "false"])
def test_nginx_starts_without_the_include_files(
    tmp_path: Path, mcp_enabled: str
) -> None:
    output: str = start_nginx(tmp_path, BASE_FILES, mcp_enabled)
    assert "webhook.conf.inc is missing" in output
