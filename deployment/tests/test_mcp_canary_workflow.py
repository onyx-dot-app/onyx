from pathlib import Path
from typing import Any

import yaml

WORKFLOW: Path = (
    Path(__file__).resolve().parents[2] / ".github/workflows/mcp-compatibility.yml"
)


def test_scheduled_canary_uses_an_isolated_compose_stack() -> None:
    source: str = WORKFLOW.read_text()
    workflow: dict[str, Any] = yaml.safe_load(source)
    job: dict[str, Any] = workflow["jobs"]["compose-smoke"]

    assert "craft-dev.onyx.app" not in source
    assert "st-dev.onyx.app" not in source
    assert "MCP_COMPATIBILITY_BASE_URL" not in source
    assert "deployed-smoke" not in workflow["jobs"]
    assert job["env"]["COMPOSE_PROJECT_NAME"].startswith("onyx-mcp-ci-")
    assert job["env"]["COMPOSE_FILE"].endswith("docker-compose.mcp-ci.yml")
    build: dict[str, Any] = next(
        step
        for step in job["steps"]
        if step.get("name") == "Build the backend under test"
    )
    assert build["with"]["target"] == "runtime"
    assert build["with"]["load"] is True
    commands: str = "\n".join(step.get("run", "") for step in job["steps"])
    assert "docker compose up -d --no-build --wait" in commands
    assert '--base-url "http://localhost:${MCP_CANARY_PORT}"' in commands
    cleanup: dict[str, Any] = next(
        step for step in job["steps"] if step.get("name") == "Stop the isolated stack"
    )
    assert cleanup["if"] == "always()"
    assert cleanup["run"] == "docker compose down --volumes --remove-orphans"
    assert "compose-smoke" in workflow["jobs"]["notify"]["needs"]
