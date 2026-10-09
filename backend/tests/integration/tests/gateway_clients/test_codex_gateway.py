"""Integration tests for the Codex CLI against the gateway's Responses API
passthrough (ee.onyx.server.gateway.openai_passthrough).

Test Suite:
1. test_basic_codex_turn - `codex exec` answers correctly through the gateway
2. test_encrypted_reasoning_statelessness - encrypted reasoning replay across turns, store forced false
3. test_previous_response_id_refused - previous_response_id -> NOT_IMPLEMENTED
4. test_mcp_tool_refused - an mcp tool entry -> INVALID_INPUT
"""

import tempfile
from pathlib import Path

import httpx
import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.test_models import DATestLLMProvider, DATestPAT
from tests.integration.tests.gateway_clients.conftest import (
    OPENAI_MODEL_NAME,
    cli_path,
    parse_jsonl,
    run_cli,
)
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(TestSecret.OPENAI_API_KEY)

_PROVIDER_KEY = "onyx_gateway"


def _write_codex_config(codex_home: str, provider: DATestLLMProvider) -> None:
    model = f"{provider.id}/{OPENAI_MODEL_NAME}"
    config_path = Path(codex_home) / "config.toml"
    config_path.write_text(
        f"""
model_provider = "{_PROVIDER_KEY}"
model = "{model}"

[model_providers.{_PROVIDER_KEY}]
name = "Onyx Gateway"
base_url = "{API_SERVER_URL}/gateway/v1"
env_key = "ONYX_GATEWAY_API_KEY"
wire_api = "responses"
"""
    )


def _codex_env(pat: DATestPAT, codex_home: str) -> dict[str, str]:
    return {
        "PATH": cli_path(),
        "HOME": codex_home,
        "CODEX_HOME": codex_home,
        "ONYX_GATEWAY_API_KEY": pat.token or "",
    }


def _last_agent_message(events: list[dict[str, object]]) -> str:
    """`codex exec --json` emits `{"type": "item.completed", "item": {...}}`
    events; the final agent reply is the last `item.type == "agent_message"`."""
    for event in reversed(events):
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            return str(item.get("text", ""))
    return ""


def test_basic_codex_turn(
    codex_bin: str, gateway_pat: DATestPAT, openai_provider: DATestLLMProvider
) -> None:
    with tempfile.TemporaryDirectory() as codex_home:
        _write_codex_config(codex_home, openai_provider)
        result = run_cli(
            [
                codex_bin,
                "exec",
                "--json",
                "--skip-git-repo-check",
                "What is 2+2? Reply with only the digit, nothing else.",
            ],
            env=_codex_env(gateway_pat, codex_home),
            cwd=codex_home,
        )

    assert result.returncode == 0, result.stderr
    events = parse_jsonl(result.stdout)
    assert "4" in _last_agent_message(events)


def test_encrypted_reasoning_statelessness(
    gateway_pat: DATestPAT, openai_provider: DATestLLMProvider
) -> None:
    """The gateway never stores responses (store is always forced false), so
    a second turn must carry the prior turn's encrypted reasoning item back
    in `input` rather than referencing it by id."""
    model = f"{openai_provider.id}/{OPENAI_MODEL_NAME}"
    headers = {"Authorization": f"Bearer {gateway_pat.token}"}

    first = httpx.post(
        f"{API_SERVER_URL}/gateway/v1/responses",
        headers=headers,
        json={
            "model": model,
            "input": [{"role": "user", "content": "What is 6 times 7?"}],
            "include": ["reasoning.encrypted_content"],
            "reasoning": {"effort": "low"},
        },
        timeout=60,
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body.get("store") is False

    reasoning_items = [
        item
        for item in first_body.get("output", [])
        if isinstance(item, dict) and item.get("type") == "reasoning"
    ]
    assert reasoning_items, "expected an encrypted reasoning item in the output"
    assert any(item.get("encrypted_content") for item in reasoning_items)

    second = httpx.post(
        f"{API_SERVER_URL}/gateway/v1/responses",
        headers=headers,
        json={
            "model": model,
            "input": [
                {"role": "user", "content": "What is 6 times 7?"},
                *reasoning_items,
                {
                    "role": "user",
                    "content": "Now divide that result by 2.",
                },
            ],
            "include": ["reasoning.encrypted_content"],
            "reasoning": {"effort": "low"},
        },
        timeout=60,
    )
    assert second.status_code == 200, second.text


def test_previous_response_id_refused(
    gateway_pat: DATestPAT, openai_provider: DATestLLMProvider
) -> None:
    response = httpx.post(
        f"{API_SERVER_URL}/gateway/v1/responses",
        headers={"Authorization": f"Bearer {gateway_pat.token}"},
        json={
            "model": f"{openai_provider.id}/{OPENAI_MODEL_NAME}",
            "input": [{"role": "user", "content": "hi"}],
            "previous_response_id": "resp_does_not_exist",
        },
        timeout=60,
    )
    assert response.status_code == 501, response.text
    assert response.json()["error_code"] == "NOT_IMPLEMENTED"


def test_mcp_tool_refused(
    gateway_pat: DATestPAT, openai_provider: DATestLLMProvider
) -> None:
    response = httpx.post(
        f"{API_SERVER_URL}/gateway/v1/responses",
        headers={"Authorization": f"Bearer {gateway_pat.token}"},
        json={
            "model": f"{openai_provider.id}/{OPENAI_MODEL_NAME}",
            "input": [{"role": "user", "content": "hi"}],
            "tools": [
                {
                    "type": "mcp",
                    "server_label": "attacker-controlled",
                    "server_url": "https://example.com/mcp",
                }
            ],
        },
        timeout=60,
    )
    assert response.status_code == 400, response.text
    assert response.json()["error_code"] == "INVALID_INPUT"
