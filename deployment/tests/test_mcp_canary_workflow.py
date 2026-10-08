from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[2] / ".github/workflows/mcp-compatibility.yml"
)


def test_scheduled_canary_uses_an_isolated_compose_stack() -> None:
    source = WORKFLOW.read_text()
    workflow = yaml.safe_load(source)
    job = workflow["jobs"]["compose-smoke"]

    assert "craft-dev.onyx.app" not in source
    assert "st-dev.onyx.app" not in source
    assert "MCP_COMPATIBILITY_BASE_URL" not in source
    assert "deployed-smoke" not in workflow["jobs"]
    assert job["env"]["COMPOSE_PROJECT_NAME"].startswith("onyx-mcp-ci-")
    assert job["env"]["COMPOSE_FILE"].endswith("docker-compose.mcp-ci.yml")
    build = next(
        step
        for step in job["steps"]
        if step.get("name") == "Build the backend under test"
    )
    assert build["with"]["target"] == "runtime"
    assert build["with"]["load"] is True
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "docker compose up -d --no-build --wait" in commands
    assert '--base-url "http://localhost:${MCP_CANARY_PORT}"' in commands
    cleanup = next(
        step for step in job["steps"] if step.get("name") == "Stop the isolated stack"
    )
    assert cleanup["if"] == "always()"
    assert cleanup["run"] == "docker compose down --volumes --remove-orphans"
    assert "compose-smoke" in workflow["jobs"]["notify"]["needs"]
