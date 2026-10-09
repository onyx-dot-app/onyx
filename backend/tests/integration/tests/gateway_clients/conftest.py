"""Fixtures for gateway client integration tests.

These tests drive REAL coding-agent CLIs (Claude Code, Codex) against the
gateway's Anthropic/OpenAI passthrough endpoints. Unlike the rest of
tests/integration, the request is made by an external subprocess, not by this
test process, so the in-process FastAPI TestClient the root conftest wires up
(no real socket) cannot serve it. This directory instead requires a real,
out-of-process api_server and swaps the shared `http_client` client for a raw
`httpx.Client` for its duration, so the existing Manager helpers (which always
build full URLs) hit the real server too.
"""

import os
import shutil
import subprocess
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Never
from uuid import uuid4

import httpx
import pytest

from onyx.db.enums import Permission
from onyx.llm.constants import LlmProviderNames
from tests.integration.common_utils import http_client
from tests.integration.common_utils.constants import API_SERVER_URL, GENERAL_HEADERS
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.pat import PATManager
from tests.integration.common_utils.managers.user import DEFAULT_PASSWORD, UserManager
from tests.integration.common_utils.test_models import (
    DATestLLMProvider,
    DATestPAT,
    DATestUser,
)

# Opt this directory into the shared @pytest.mark.secrets / test_secrets
# infrastructure (see tests/utils/pytest_secrets.py).
from tests.utils.pytest_secrets import (
    pytest_collection_modifyitems as pytest_collection_modifyitems,
)
from tests.utils.pytest_secrets import pytest_configure as pytest_configure
from tests.utils.pytest_secrets import test_secrets as test_secrets
from tests.utils.secret_names import TestSecret

CLI_TIMEOUT_SECONDS = 120
ANTHROPIC_MODEL_NAME = "claude-haiku-4-5"
OPENAI_MODEL_NAME = "gpt-5-mini"
CLAUDE_CODE_PACKAGE = "@anthropic-ai/claude-code@2.1.221"
CODEX_PACKAGE = "@openai/codex@0.146.0"

# The dev admin account created by the playwright global setup / first-user
# registration (see the project CLAUDE.md). Reused here rather than
# UserManager.create()/reset_all() so this suite never wipes a shared,
# already-running dev deployment.
_DEV_ADMIN_EMAIL = "admin_user@example.com"

# Set by the CI integration lane for this directory (see
# .github/workflows/pr-integration-tests.yml). When truthy, every missing
# prerequisite fails loudly instead of skipping, so the lane can never go
# green by silently skipping; locally it stays unset and skips keep dev
# boxes without npm, a running server, or provider keys usable.
_STRICT_ENV = "GATEWAY_CLIENT_TESTS_REQUIRED"


def _skip_or_fail(reason: str) -> Never:
    if os.environ.get(_STRICT_ENV):
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture(scope="module", autouse=True)
def _real_api_server() -> Generator[None, None, None]:
    """Point the shared http_client at a real, out-of-process api_server.

    Skips the whole module unless API_SERVER_URL returns the Onyx health
    payload: a CLI subprocess needs an actual TCP socket to connect to, which
    the rest of tests/integration does not provide.
    """
    try:
        response = httpx.get(f"{API_SERVER_URL}/health", timeout=5)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise ValueError(f"unexpected health response: {payload!r}")
    except (httpx.HTTPError, ValueError) as e:
        _skip_or_fail(
            f"No real api_server returned the Onyx health payload at "
            f"{API_SERVER_URL} ({e!r}); gateway client tests require an "
            "out-of-process dev server. See README.md."
        )

    previous = http_client._test_client
    real_client = httpx.Client(
        transport=http_client.RetryingTransport(),
        timeout=httpx.Timeout(60.0, connect=10.0),
    )
    http_client.set_test_client(real_client)
    try:
        yield
    finally:
        http_client.set_test_client(previous)
        real_client.close()


def _install_cli(package: str, executable: str) -> Generator[str, None, None]:
    """Install one pinned CLI package into an isolated npm prefix."""
    if shutil.which("npm") is None:
        _skip_or_fail(f"npm is not available; cannot install {package}.")

    with tempfile.TemporaryDirectory(prefix="onyx-gateway-cli-") as tmpdir:
        prefix = Path(tmpdir)
        try:
            result = subprocess.run(
                [
                    "npm",
                    "install",
                    "--prefix",
                    str(prefix),
                    package,
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            _skip_or_fail(f"npm install of {package} timed out after 180 seconds")
        if result.returncode != 0:
            _skip_or_fail(f"npm install of {package} failed: {result.stderr[-2000:]}")

        path = prefix / "node_modules" / ".bin" / executable
        if not path.exists():
            _skip_or_fail(
                f"{executable} CLI binary not found after installing {package}"
            )
        yield str(path)


@pytest.fixture(scope="module")
def claude_bin() -> Generator[str, None, None]:
    yield from _install_cli(CLAUDE_CODE_PACKAGE, "claude")


@pytest.fixture(scope="module")
def codex_bin() -> Generator[str, None, None]:
    yield from _install_cli(CODEX_PACKAGE, "codex")


@pytest.fixture(scope="module")
def gateway_admin(_real_api_server: None) -> DATestUser:  # noqa: ARG001
    """Log in as the standing dev admin rather than creating/reset_all()-ing.

    This suite runs against a real, shared dev deployment; it must not wipe
    its data the way the root `admin_user` fixture does on role mismatch.
    """
    try:
        # is_admin/is_active are placeholders; login_as_user overwrites them
        # from the real /me response.
        return UserManager.login_as_user(
            DATestUser(
                id="",
                email=_DEV_ADMIN_EMAIL,
                password=DEFAULT_PASSWORD,
                headers=dict(GENERAL_HEADERS),
                is_admin=False,
                is_active=True,
            )
        )
    except Exception as login_error:
        if not os.environ.get(_STRICT_ENV):
            pytest.fail(
                f"Could not log in as {_DEV_ADMIN_EMAIL}; the gateway client "
                f"suite needs the standard dev admin account to already exist: "
                f"{login_error}"
            )

    try:
        user = UserManager.create(email=_DEV_ADMIN_EMAIL)
    except Exception as create_error:
        pytest.fail(
            f"Could not create {_DEV_ADMIN_EMAIL} in the fresh CI deployment: "
            f"{create_error}"
        )
    if not UserManager.is_admin(user):
        pytest.fail(f"Created {_DEV_ADMIN_EMAIL} without admin panel access")
    return user


@pytest.fixture(scope="module")
def gateway_pat(gateway_admin: DATestUser) -> Generator[DATestPAT, None, None]:
    pat = PATManager.create(
        name=f"gateway-client-test-{uuid4()}",
        expiration_days=1,
        user_performing_action=gateway_admin,
        scopes=[Permission.USE_LLM_GATEWAY],
    )
    try:
        yield pat
    finally:
        PATManager.revoke(pat.id, gateway_admin)


@pytest.fixture(scope="module")
def anthropic_provider(
    gateway_admin: DATestUser,
    test_secrets: dict[TestSecret, str],
) -> Generator[DATestLLMProvider, None, None]:
    api_key = test_secrets.get(TestSecret.ANTHROPIC_API_KEY)
    if not api_key:
        _skip_or_fail("ANTHROPIC_API_KEY secret is not available")

    provider = LLMProviderManager.create(
        user_performing_action=gateway_admin,
        name=f"gateway-client-test-anthropic-{uuid4()}",
        provider=LlmProviderNames.ANTHROPIC,
        api_key=api_key,
        default_model_name=ANTHROPIC_MODEL_NAME,
        # Never touch the shared dev deployment's default model.
        set_as_default=False,
    )
    try:
        yield provider
    finally:
        LLMProviderManager.delete(provider, gateway_admin)


@pytest.fixture(scope="module")
def openai_provider(
    gateway_admin: DATestUser,
    test_secrets: dict[TestSecret, str],
) -> Generator[DATestLLMProvider, None, None]:
    api_key = test_secrets.get(TestSecret.OPENAI_API_KEY)
    if not api_key:
        _skip_or_fail("OPENAI_API_KEY secret is not available")

    provider = LLMProviderManager.create(
        user_performing_action=gateway_admin,
        name=f"gateway-client-test-openai-{uuid4()}",
        provider=LlmProviderNames.OPENAI,
        api_key=api_key,
        default_model_name=OPENAI_MODEL_NAME,
        set_as_default=False,
    )
    try:
        yield provider
    finally:
        LLMProviderManager.delete(provider, gateway_admin)


def cli_path() -> str:
    """A minimal but real PATH for CLI subprocesses.

    `codex`'s bin script is a `#!/usr/bin/env node` shim, so PATH needs to
    resolve `node`, not just the CLI binaries themselves (already passed as
    absolute paths).
    """
    node = shutil.which("node")
    node_dir = str(Path(node).parent) if node else ""
    return os.pathsep.join(
        p for p in (node_dir, "/usr/bin", "/bin", "/usr/local/bin") if p
    )


def run_cli(
    cmd: list[str], env: dict[str, str], cwd: str, timeout: int = CLI_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess[str]:
    """Run a CLI subprocess with a hard timeout, capturing text output."""
    return subprocess.run(
        cmd,
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def parse_trailing_json(stdout: str) -> dict[str, object]:
    """Parse the JSON object at the end of CLI stdout.

    `claude -p --output-format json` occasionally prints a warning line
    before the JSON payload; find the first `{` and parse from there.
    """
    import json

    start = stdout.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in CLI output: {stdout!r}")
    return json.loads(stdout[start:])


def parse_jsonl(stdout: str) -> list[dict[str, object]]:
    """Parse newline-delimited JSON event output (`codex exec --json`)."""
    import json

    events: list[dict[str, object]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        events.append(json.loads(line))
    return events
