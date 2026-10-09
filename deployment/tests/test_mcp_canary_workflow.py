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

    triggers: dict[str, Any] = workflow.get("on", workflow.get(True))
    assert triggers["schedule"] == [
        {"cron": "17 9 * * 1"},
        {"cron": "37 9 * * *"},
    ]
    assert "github.event.schedule == '17 9 * * 1'" in job["if"]
    assert "github.event_name == 'workflow_dispatch'" in job["if"]

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

    alert: dict[str, Any] = next(
        step
        for step in workflow["jobs"]["notify"]["steps"]
        if step.get("uses") == "./.github/actions/slack-post-message"
    )
    assert alert["with"]["channel"] == "C07K8KBMGKF"
    assert alert["with"]["mention"] == "rohoswagger"
    assert alert["with"]["bot-token"] == "${{ secrets.CVE_REVIEWS_BOT_TOKEN }}"
    assert "{mention}" in alert["with"]["text"]
    assert "\n\n• Routing:" in alert["with"]["text"]
    assert "|View workflow run and logs>" in alert["with"]["text"]
