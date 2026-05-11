"""
Integration tests for the onyx-cli binary against a real Onyx backend.

These tests require a pre-built CLI binary passed via the ONYX_CLI_BINARY
env var. In CI, the workflow builds the binary and mounts it into the test
container. The tests are skipped when ONYX_CLI_BINARY is not set.

To run locally (requires Go toolchain + all Onyx services running):

    cd cli && go build -o /tmp/onyx-cli-test .
    cd ..
    ONYX_CLI_BINARY=/tmp/onyx-cli-test \
      python -m dotenv -f .vscode/.env run -- \
      pytest backend/tests/integration/tests/cli/

Test Suite:
1.  test_validate_config_success - Authenticates with PAT, reports connected
2.  test_validate_config_bad_pat - Invalid PAT returns exit code 4
3.  test_validate_config_not_configured - Missing PAT returns exit code 3
4.  test_ask_plain_text - Answer contains expected content
5.  test_ask_json - NDJSON stream has correct event types
6.  test_ask_quiet - Buffered output contains answer
7.  test_ask_stdin_pipe - Piped context is used in the answer
8.  test_ask_truncation - Output truncated with temp file path
9.  test_ask_agent_id - Routes question to a specific persona
10. test_ask_no_truncation - --max-output 0 disables truncation
11. test_ask_not_configured - Missing PAT returns exit code 3
12. test_configure_non_tty - Non-TTY returns exit code 2
13. test_agents_list - Seeded persona appears in table output
14. test_agents_json - Seeded persona appears in JSON output
15. test_help_non_tty - No subcommand prints help, exits 0
16. test_version_flag - Prints client and server version
17. test_experiments - Lists feature flags
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.pat import PATManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestPersona
from tests.integration.common_utils.test_models import DATestUser

_CLI_BINARY = os.environ.get("ONYX_CLI_BINARY")

pytestmark = pytest.mark.skipif(
    _CLI_BINARY is None,
    reason="CLI integration tests require ONYX_CLI_BINARY env var pointing to the built binary",
)


@pytest.fixture(scope="module")
def cli_binary() -> Path:
    """Return the pre-built CLI binary path from ONYX_CLI_BINARY."""
    assert _CLI_BINARY is not None
    binary = Path(_CLI_BINARY)
    assert binary.exists(), f"CLI binary not found at {binary}"
    return binary


@pytest.fixture
def pat_token(admin_user: DATestUser) -> str:
    """Create a PAT and return the raw token string."""
    pat = PATManager.create(
        name="cli-integration-test",
        expiration_days=1,
        user_performing_action=admin_user,
    )
    assert pat.token is not None
    return pat.token


@pytest.fixture
def seeded_persona(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> DATestPersona:
    """Create a persona with a known name for verification."""
    import uuid

    return PersonaManager.create(
        user_performing_action=admin_user,
        name=f"CLI Test Agent {uuid.uuid4().hex[:8]}",
        description="An agent created for CLI integration tests",
    )


def run_cli(
    binary: Path,
    args: list[str],
    *,
    pat: str | None = None,
    server_url: str = API_SERVER_URL,
    stdin_data: str | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    """Run the CLI binary with isolated config and return the result."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "ONYX_SERVER_URL": server_url,
        "XDG_CONFIG_HOME": tempfile.mkdtemp(),
    }
    if pat is not None:
        env["ONYX_PAT"] = pat

    return subprocess.run(
        [str(binary)] + args,
        capture_output=True,
        text=True,
        env=env,
        input=stdin_data,
        timeout=timeout,
    )


# --- validate-config ---


def test_validate_config_success(cli_binary: Path, pat_token: str) -> None:
    """CLI authenticates and reports success with a valid PAT."""
    result = run_cli(cli_binary, ["validate-config"], pat=pat_token)

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "connected and authenticated" in result.stdout
    assert "environment variables" in result.stdout


def test_validate_config_bad_pat(
    cli_binary: Path, admin_user: DATestUser  # noqa: ARG001
) -> None:
    """Invalid PAT returns AuthFailure (exit code 4)."""
    result = run_cli(cli_binary, ["validate-config"], pat="bad-token")

    assert result.returncode == 4


def test_validate_config_not_configured(
    cli_binary: Path, admin_user: DATestUser  # noqa: ARG001
) -> None:
    """Missing PAT returns NotConfigured (exit code 3)."""
    result = run_cli(cli_binary, ["validate-config"])

    assert result.returncode == 3
    assert "not configured" in result.stderr.lower()


# --- ask ---


def test_ask_plain_text(
    cli_binary: Path,
    pat_token: str,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """Ask a question using the default persona (most common usage)."""
    result = run_cli(
        cli_binary,
        ["ask", 'Respond with exactly the word "pineapple" and nothing else'],
        pat=pat_token,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "pineapple" in result.stdout.lower()


def test_ask_json(
    cli_binary: Path,
    pat_token: str,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """Ask in NDJSON mode and verify event types and content."""
    result = run_cli(
        cli_binary,
        ["ask", "--json", "Say hi"],
        pat=pat_token,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"

    lines = [line for line in result.stdout.strip().split("\n") if line]
    assert len(lines) >= 3, f"expected at least 3 NDJSON lines, got {len(lines)}"

    events = [json.loads(line) for line in lines]
    event_types = [e["type"] for e in events]

    assert "session_created" in event_types
    assert "message_delta" in event_types
    assert "stop" in event_types

    # Verify message_delta events have content
    deltas = [e for e in events if e["type"] == "message_delta"]
    content = "".join(e["event"]["content"] for e in deltas)
    assert len(content) > 0, "expected non-empty message content"


def test_ask_quiet(
    cli_binary: Path,
    pat_token: str,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """Quiet mode buffers output and prints once."""
    result = run_cli(
        cli_binary,
        ["ask", "--quiet", 'Respond with exactly "quiet_ok"'],
        pat=pat_token,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "quiet_ok" in result.stdout.lower()


def test_ask_stdin_pipe(
    cli_binary: Path,
    pat_token: str,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """Piped stdin content is used as context in the answer."""
    result = run_cli(
        cli_binary,
        ["ask", "--prompt", "What is the secret code in the context below?"],
        pat=pat_token,
        stdin_data="The secret code is XRAY42.",
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "XRAY42" in result.stdout


def test_ask_truncation(
    cli_binary: Path,
    pat_token: str,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """Non-TTY output is truncated with a temp file path."""
    result = run_cli(
        cli_binary,
        ["ask", "--max-output", "50", "Write a 500-word essay about anything"],
        pat=pat_token,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "response truncated" in result.stdout
    assert "Full response:" in result.stdout


def test_ask_agent_id(
    cli_binary: Path,
    pat_token: str,
    seeded_persona: DATestPersona,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """--agent-id routes the question to a specific persona."""
    result = run_cli(
        cli_binary,
        ["ask", "--agent-id", str(seeded_persona.id), "Say hi"],
        pat=pat_token,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert len(result.stdout.strip()) > 0


def test_ask_no_truncation(
    cli_binary: Path,
    pat_token: str,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """--max-output 0 disables truncation entirely."""
    result = run_cli(
        cli_binary,
        ["ask", "--max-output", "0", "Write a paragraph about anything"],
        pat=pat_token,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "response truncated" not in result.stdout
    assert len(result.stdout.strip()) > 0


def test_ask_not_configured(
    cli_binary: Path, admin_user: DATestUser  # noqa: ARG001
) -> None:
    """Missing PAT returns NotConfigured (exit code 3)."""
    result = run_cli(cli_binary, ["ask", "test"])

    assert result.returncode == 3


# --- configure ---


def test_configure_non_tty(
    cli_binary: Path, admin_user: DATestUser  # noqa: ARG001
) -> None:
    """configure without TTY returns BadRequest (exit code 2)."""
    result = run_cli(cli_binary, ["configure"])

    assert result.returncode == 2
    assert "interactive terminal" in result.stderr.lower()


# --- agents ---


def test_agents_list(
    cli_binary: Path,
    pat_token: str,
    seeded_persona: DATestPersona,
) -> None:
    """Seeded persona appears in the table output."""
    result = run_cli(cli_binary, ["agents"], pat=pat_token)

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert seeded_persona.name in result.stdout


def test_agents_json(
    cli_binary: Path,
    pat_token: str,
    seeded_persona: DATestPersona,
) -> None:
    """Seeded persona appears in JSON output with correct fields."""
    result = run_cli(cli_binary, ["agents", "--json"], pat=pat_token)

    assert result.returncode == 0, f"stderr: {result.stderr}"

    agents = json.loads(result.stdout)
    assert isinstance(agents, list)

    matching = [a for a in agents if a["name"] == seeded_persona.name]
    assert len(matching) == 1, (
        f"expected 1 agent named '{seeded_persona.name}', "
        f"found {len(matching)} in {[a['name'] for a in agents]}"
    )

    agent = matching[0]
    assert agent["id"] == seeded_persona.id
    assert agent["description"] == seeded_persona.description


# --- general ---


def test_help_non_tty(cli_binary: Path) -> None:
    """Running with no subcommand in non-TTY prints help and exits 0."""
    result = run_cli(cli_binary, [])

    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "Available Commands:" in result.stdout


def test_version_flag(cli_binary: Path, pat_token: str) -> None:
    """--version prints client and server version."""
    result = run_cli(cli_binary, ["--version"], pat=pat_token)

    assert result.returncode == 0
    assert "Client version:" in result.stdout
    assert "Server version:" in result.stdout


def test_experiments(cli_binary: Path) -> None:
    """Experiments command lists feature flags without auth."""
    result = run_cli(cli_binary, ["experiments"])

    assert result.returncode == 0
    assert "Stream Markdown" in result.stdout
