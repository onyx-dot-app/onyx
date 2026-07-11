"""Docker-backend opencode-serve streaming end-to-end tests."""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Generator
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import NamedTuple
from uuid import UUID
from uuid import uuid4

import pytest

from onyx.llm.constants import LlmProviderNames
from onyx.server.features.build.configs import OPENCODE_SERVER_PASSWORD
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.docker_e2e.conftest import DockerExec
from tests.integration.tests.craft.docker_e2e.conftest import DockerSandbox
from tests.integration.tests.craft.docker_e2e.conftest import ProvisionSandbox

pytestmark = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.DOCKER,
    reason="Docker integration tests require SANDBOX_BACKEND=docker.",
)


class DockerLiveSession(NamedTuple):
    user: DATestUser
    session_id: UUID


_LIVE_MODEL = "gpt-5-mini"

_SKIP_NO_LLM_KEY = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="docker-serve streaming tests that drive real turns need a real "
    "OPENAI_API_KEY (the compose lane seeds a fake provider key by default).",
)


@dataclass
class _Collected:
    text: str = ""
    thoughts: list[dict[str, Any]] = field(default_factory=list)
    tool_starts: list[dict[str, Any]] = field(default_factory=list)
    tool_progress: list[dict[str, Any]] = field(default_factory=list)
    terminators: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def term(self) -> dict[str, Any] | None:
        return self.terminators[0] if self.terminators else None


def _iter_sse_events(
    raw_lines: Generator[str, None, None],
) -> Generator[dict[str, Any], None, None]:
    for line in raw_lines:
        if not line.startswith("data:"):
            continue
        raw = line[len("data:") :].strip()
        if not raw:
            continue
        try:
            yield json.loads(raw)
        except json.JSONDecodeError:
            continue


def _drive_turn(
    user: DATestUser,
    session_id: UUID,
    prompt: str,
    *,
    timeout: float = 180.0,
) -> _Collected:
    turn = BuildSessionManager.start_turn(user, session_id, prompt)
    turn_id = turn.turn_id

    out = _Collected()
    url = f"{API_SERVER_URL}/build/sessions/{session_id}/turns/{turn_id}/events"
    with client.stream(
        "GET",
        url,
        headers=user.headers,
        cookies=user.cookies,
        timeout=timeout,
    ) as resp:
        resp.raise_for_status()
        for event in _iter_sse_events(resp.iter_lines()):
            etype = event.get("type")
            if etype == "agent_message_chunk":
                out.text += _chunk_text(event)
            elif etype == "agent_thought_chunk":
                out.thoughts.append(event)
            elif etype == "tool_call_start":
                out.tool_starts.append(event)
            elif etype == "tool_call_progress":
                out.tool_progress.append(event)
            elif etype == "prompt_response":
                out.terminators.append(event)
            elif etype == "error":
                out.errors.append(event)

    # The SSE stream closes slightly before the server releases the turn slot;
    # wait for it to clear so a follow-up start_turn isn't refused with 409.
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if BuildSessionManager.get_active_turn(user, session_id) is None:
            break
        time.sleep(0.5)
    return out


def _chunk_text(event: dict[str, Any]) -> str:
    content = event.get("content")
    if isinstance(content, dict) and content.get("type") == "text":
        return content.get("text") or ""
    return ""


@pytest.fixture
def streaming_user() -> DATestUser:
    return UserManager.create(name=f"craft_docker_streaming_{uuid4().hex[:8]}")


@pytest.fixture
def live_session(
    admin_user: DATestUser,
    streaming_user: DATestUser,
    provision_sandbox: ProvisionSandbox,
) -> Generator[DockerLiveSession, None, None]:
    real_key = os.environ.get("OPENAI_API_KEY")
    if not real_key:
        pytest.skip("OPENAI_API_KEY not set; live-turn streaming tests need it.")
    # The base craft conftest seeds a fake-keyed openai provider, and both the
    # session-config and sandbox-proxy key resolvers pick the *first* openai
    # provider. Delete any existing openai provider so the real key is the only
    # one in play, then seed it (with gpt-5-mini visible).
    for provider in LLMProviderManager.get_all(admin_user):
        if provider.provider == LlmProviderNames.OPENAI:
            LLMProviderManager.delete(provider, admin_user, force=True)
    created_provider = LLMProviderManager.create(
        user_performing_action=admin_user,
        api_key=real_key,
        default_model_name=_LIVE_MODEL,
    )
    result: DockerSandbox | None = None
    try:
        # Pin the cheap model on the turn; provisioning otherwise selects the
        # provider's recommended (flagship) model, ignoring default_model_name.
        result = provision_sandbox(
            streaming_user,
            llm_provider_type=LlmProviderNames.OPENAI,
            llm_model_name=_LIVE_MODEL,
        )
        yield DockerLiveSession(user=streaming_user, session_id=result.session_id)
    finally:
        try:
            LLMProviderManager.delete(created_provider, admin_user, force=True)
        except Exception as exc:
            print(
                "WARNING: failed to delete live-test LLM provider "
                f"{created_provider.id!r}: {exc}"
            )
        if result is not None:
            try:
                subprocess.run(
                    ["docker", "rm", "-f", result.container_name],
                    capture_output=True,
                    text=True,
                    timeout=30.0,
                    check=False,
                )
            except Exception as exc:
                print(
                    "WARNING: failed to remove container "
                    f"{result.container_name!r}: {exc}"
                )


def test_provision_injects_serve_env_into_real_container(
    provision_sandbox: ProvisionSandbox,
    docker_exec: DockerExec,
) -> None:
    user = UserManager.create(name=f"craft_docker_env_{uuid4().hex[:8]}")
    _session_id, container = provision_sandbox(user)

    env_dump = docker_exec(container, ["env"])
    assert env_dump.returncode == 0, f"env failed: {env_dump.stderr!r}"
    env_keys = {
        line.split("=", 1)[0] for line in env_dump.stdout.splitlines() if "=" in line
    }
    assert OPENCODE_SERVER_PASSWORD in env_keys, (
        f"{OPENCODE_SERVER_PASSWORD} not injected into container env: {env_keys}"
    )
    assert "OPENCODE_CONFIG_CONTENT" in env_keys, (
        f"OPENCODE_CONFIG_CONTENT not injected into container env: {env_keys}"
    )


def test_concurrent_turn_is_rejected(
    streaming_user: DATestUser,
    provision_sandbox: ProvisionSandbox,
) -> None:
    session_id, _container = provision_sandbox(streaming_user)

    first = BuildSessionManager.start_turn(
        streaming_user, session_id, "Say hi briefly."
    )
    assert first.turn_id

    second = client.post(
        f"{API_SERVER_URL}/build/sessions/{session_id}/send-message",
        json={"content": "and again"},
        headers=streaming_user.headers,
        cookies=streaming_user.cookies,
    )
    assert second.status_code == 409, (
        f"Concurrent turn was not rejected with CONFLICT: "
        f"{second.status_code} {second.text!r}"
    )


@_SKIP_NO_LLM_KEY
def test_simple_message_streams_text_and_terminates(
    live_session: DockerLiveSession,
) -> None:
    user, session_id = live_session
    out = _drive_turn(user, session_id, "Say hi briefly.")

    assert out.term is not None, "turn never produced a prompt_response terminator"
    assert out.term.get("stopReason") == "end_turn", (
        f"unexpected stop reason: {out.term!r}"
    )
    assert out.errors == [], f"unexpected errors: {out.errors}"
    assert len(out.text) > 0, "expected at least one agent_message_chunk"
    assert "Say hi briefly" not in out.text, (
        f"user prompt leaked into assistant text: {out.text!r}"
    )


@_SKIP_NO_LLM_KEY
def test_bash_tool_call_lifecycle(
    live_session: DockerLiveSession,
) -> None:
    user, session_id = live_session
    out = _drive_turn(
        user,
        session_id,
        "Run the bash command `echo DOCKER_SERVE_OK` and then say DONE.",
    )

    assert out.term is not None, "turn never terminated"
    assert out.errors == [], f"unexpected errors: {out.errors}"
    assert len(out.tool_starts) >= 1, "expected at least one tool_call_start"
    bash_starts = [s for s in out.tool_starts if s.get("kind") == "execute"]
    assert len(bash_starts) >= 1, (
        f"no bash tool call seen; kinds: {[s.get('kind') for s in out.tool_starts]}"
    )
    for cid in {s.get("toolCallId") for s in out.tool_starts}:
        progress = [p for p in out.tool_progress if p.get("toolCallId") == cid]
        assert any(p.get("status") == "completed" for p in progress), (
            f"tool call {cid} never reached status=completed; "
            f"statuses: {[p.get('status') for p in progress]}"
        )


@_SKIP_NO_LLM_KEY
def test_multi_turn_session_terminates_each_turn(
    live_session: DockerLiveSession,
) -> None:
    user, session_id = live_session
    for i, prompt in enumerate(
        [
            "Say 'one' and nothing else.",
            "Say 'two' and nothing else.",
            "Say 'three' and nothing else.",
        ]
    ):
        out = _drive_turn(user, session_id, prompt)
        assert out.term is not None, f"turn {i + 1} did not terminate"
        assert out.errors == [], f"turn {i + 1} had errors: {out.errors}"
        assert len(out.text) > 0, f"turn {i + 1} produced no text"
