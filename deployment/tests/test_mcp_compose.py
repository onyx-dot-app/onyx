import json
import os
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "deployment/docker_compose/docker-compose.mcp-ci.yml"


def test_mcp_canary_uses_isolated_real_compose_services() -> None:
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "config", "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": os.environ["PATH"]},
    )
    config: dict[str, Any] = json.loads(result.stdout)
    assert config["name"] == "onyx-mcp-ci"
    services: dict[str, Any] = config["services"]
    assert set(services) == {
        "relational_db",
        "cache",
        "api_server",
        "mcp_server",
        "web_server",
        "nginx",
    }
    api = services["api_server"]
    assert api["build"]["target"] == "runtime"
    assert "onyx.main:app" in api["command"][-1]
    assert services["mcp_server"]["command"] == ["python", "-m", "onyx.mcp_server_main"]
    assert api["environment"]["WEB_DOMAIN"] == "http://localhost:18080"
    assert api["environment"]["FILE_STORE_BACKEND"] == "postgres"
    assert services["nginx"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert not any(
        service.get("ports") for name, service in services.items() if name != "nginx"
    )
    mounts = {Path(mount["source"]).name for mount in services["nginx"]["volumes"]}
    assert {"app.conf.template", "mcp.conf.inc.template", "run-nginx.sh"} <= mounts
