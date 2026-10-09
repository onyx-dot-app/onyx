"""Integration tests for the Claude Code CLI against the gateway's
Anthropic Messages API passthrough (ee.onyx.server.gateway.anthropic_passthrough).

Test Suite:
1. test_basic_turn_answers_correctly - `claude -p` answers correctly through the gateway
2. test_tool_use_turn_replays_thinking - tool-use turn proves thinking-block signature replay
3. test_web_search_server_tool - passthrough-only web_search server tool
4. test_count_tokens_matches_usage - count_tokens exactness against a real turn's usage
5. test_mcp_servers_refused - mcp_servers is refused with INVALID_INPUT
"""

import tempfile

import httpx
import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.test_models import DATestLLMProvider, DATestPAT
from tests.integration.tests.gateway_clients.conftest import (
    ANTHROPIC_MODEL_NAME,
    cli_path,
    parse_trailing_json,
    run_cli,
)
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(TestSecret.ANTHROPIC_API_KEY)


def _claude_env(
    pat: DATestPAT, provider: DATestLLMProvider, tmp_home: str
) -> dict[str, str]:
    model = f"{provider.id}/{ANTHROPIC_MODEL_NAME}"
    return {
        "PATH": cli_path(),
        "HOME": tmp_home,
        "ANTHROPIC_BASE_URL": f"{API_SERVER_URL}/gateway",
        "ANTHROPIC_AUTH_TOKEN": pat.token or "",
        "ANTHROPIC_MODEL": model,
        "ANTHROPIC_SMALL_FAST_MODEL": model,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CI": "true",
    }


def test_basic_turn_answers_correctly(
    claude_bin: str, gateway_pat: DATestPAT, anthropic_provider: DATestLLMProvider
) -> None:
    with tempfile.TemporaryDirectory() as tmp_home:
        result = run_cli(
            [
                claude_bin,
                "-p",
                "What is 2+2? Respond with only the digit, nothing else.",
                "--output-format",
                "json",
            ],
            env=_claude_env(gateway_pat, anthropic_provider, tmp_home),
            cwd=tmp_home,
        )

    assert result.returncode == 0, result.stderr
    payload = parse_trailing_json(result.stdout)
    assert payload.get("is_error") is False
    assert "4" in str(payload.get("result", ""))


def test_tool_use_turn_replays_thinking(
    claude_bin: str, gateway_pat: DATestPAT, anthropic_provider: DATestLLMProvider
) -> None:
    """A multi-turn tool-use conversation proves the passthrough replays
    Anthropic thinking-block signatures correctly across turns."""
    with tempfile.TemporaryDirectory() as tmp_home:
        env = _claude_env(gateway_pat, anthropic_provider, tmp_home)
        env["MAX_THINKING_TOKENS"] = "4096"
        result = run_cli(
            [
                claude_bin,
                "-p",
                "Run `ls` in the current directory, then tell me how many "
                "entries it printed.",
                "--output-format",
                "json",
                "--allowedTools",
                "Bash(ls:*)",
            ],
            env=env,
            cwd=tmp_home,
        )

    assert result.returncode == 0, result.stderr
    payload = parse_trailing_json(result.stdout)
    assert payload.get("is_error") is False
    num_turns = payload.get("num_turns", 0)
    assert isinstance(num_turns, int) and num_turns >= 2


def test_web_search_server_tool(
    gateway_pat: DATestPAT, anthropic_provider: DATestLLMProvider
) -> None:
    """web_search is a passthrough-only capability: the OpenAI-shaped
    translation path cannot carry Anthropic server tools."""
    response = httpx.post(
        f"{API_SERVER_URL}/gateway/v1/messages",
        headers={"Authorization": f"Bearer {gateway_pat.token}"},
        json={
            "model": f"{anthropic_provider.id}/{ANTHROPIC_MODEL_NAME}",
            "max_tokens": 1024,
            "messages": [
                {
                    "role": "user",
                    "content": "Search the web for the current Onyx (formerly "
                    "Danswer) GitHub star count and tell me the number.",
                }
            ],
            "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        },
        timeout=60,
    )
    assert response.status_code == 200, response.text
    content_blocks = response.json()["content"]
    block_types = {block.get("type") for block in content_blocks}
    assert "server_tool_use" in block_types
    assert "web_search_tool_result" in block_types


def test_count_tokens_matches_usage(
    gateway_pat: DATestPAT, anthropic_provider: DATestLLMProvider
) -> None:
    messages = [{"role": "user", "content": "Say hello in exactly one word."}]
    model = f"{anthropic_provider.id}/{ANTHROPIC_MODEL_NAME}"
    headers = {"Authorization": f"Bearer {gateway_pat.token}"}

    count_response = httpx.post(
        f"{API_SERVER_URL}/gateway/v1/messages/count_tokens",
        headers=headers,
        json={"model": model, "messages": messages},
        timeout=60,
    )
    assert count_response.status_code == 200, count_response.text
    counted_tokens = count_response.json()["input_tokens"]

    turn_response = httpx.post(
        f"{API_SERVER_URL}/gateway/v1/messages",
        headers=headers,
        json={"model": model, "max_tokens": 32, "messages": messages},
        timeout=60,
    )
    assert turn_response.status_code == 200, turn_response.text
    assert turn_response.json()["usage"]["input_tokens"] == counted_tokens


def test_mcp_servers_refused(
    gateway_pat: DATestPAT, anthropic_provider: DATestLLMProvider
) -> None:
    response = httpx.post(
        f"{API_SERVER_URL}/gateway/v1/messages",
        headers={"Authorization": f"Bearer {gateway_pat.token}"},
        json={
            "model": f"{anthropic_provider.id}/{ANTHROPIC_MODEL_NAME}",
            "max_tokens": 32,
            "messages": [{"role": "user", "content": "hi"}],
            "mcp_servers": [
                {
                    "type": "url",
                    "url": "https://example.com/mcp",
                    "name": "attacker-controlled",
                }
            ],
        },
        timeout=60,
    )
    assert response.status_code == 400, response.text
    assert response.json()["error_code"] == "INVALID_INPUT"
