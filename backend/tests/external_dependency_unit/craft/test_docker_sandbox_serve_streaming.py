"""Streaming-output regression tests for ``DockerSandboxManager`` under
``AGENT_TRANSPORT=serve``.

Mirrors :mod:`test_opencode_serve_streaming` (which runs against a real
``KubernetesSandboxManager`` pod) but provisions a real Docker sandbox
container via :class:`DockerSandboxManager`. The tests assert on the
``ACPEvent`` stream that ``send_message`` yields — the same events the
session manager persists and the frontend renders — so any divergence
between the Docker and K8s serve paths surfaces here.

Why these aren't unit tests
---------------------------
The Docker serve port is mostly orchestration: provision generates a
password, injects env, calls ``docker run``, the container's entrypoint
exec's ``opencode serve``, the api_server side polls ``GET /doc`` until
ready, then drives prompts over HTTP. Almost every load-bearing
interaction is across a process boundary into ``opencode serve`` —
something a mock can't validate. The matching K8s tests run on every
PR via ``pr-craft-k8s-tests.yml``; this file does the same for the
Docker lane.

Skip conditions
---------------
Tests in this module pytest.skip unless ALL of the following hold:
- ``SANDBOX_BACKEND=docker`` (deployer must opt-in; default is k8s).
- ``OPENAI_API_KEY`` is set (we make real LLM calls).
- The Docker daemon is reachable on the configured socket.

The test runner must also be reachable to the sandbox container by name
on the ``onyx_craft_sandbox`` bridge network — e.g. running via
``docker compose exec api_server pytest ...``. From the host without
bridge attachment, ``_wait_for_opencode_serve_ready`` will time out.
That's a configuration error, not a test bug, so we don't silently skip;
the readiness timeout surfaces a real diagnostic.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from dataclasses import dataclass
from uuid import UUID
from uuid import uuid4

import pytest
from acp.schema import AgentMessageChunk
from acp.schema import AgentThoughtChunk
from acp.schema import Error
from acp.schema import PromptResponse
from acp.schema import ToolCallProgress
from acp.schema import ToolCallStart

import onyx.server.features.build.configs as cfg
import onyx.server.features.build.sandbox.base as sandbox_base
import onyx.server.features.build.sandbox.docker.docker_sandbox_manager as docker_mgr
from onyx.server.features.build.configs import AgentTransport
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_DOCKER_SOCKET
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    _sandbox_container_name,
)
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    DockerSandboxManager,
)
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.sse import SSEKeepalive
from tests.external_dependency_unit.craft._test_helpers import default_llm_config

# ----------------------------------------------------------------------
# Module-wide skip gate
# ----------------------------------------------------------------------

_SKIP_MISSING_KEY = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="docker-serve streaming tests need a real OPENAI_API_KEY",
)
_SKIP_WRONG_BACKEND = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.DOCKER,
    reason="docker-serve streaming tests require SANDBOX_BACKEND=docker",
)
_SKIP_NO_SOCKET = pytest.mark.skipif(
    not os.path.exists(SANDBOX_DOCKER_SOCKET),
    reason=f"Docker socket missing at {SANDBOX_DOCKER_SOCKET}",
)

pytestmark = [_SKIP_WRONG_BACKEND, _SKIP_NO_SOCKET, _SKIP_MISSING_KEY]


# ----------------------------------------------------------------------
# Manager-side fixture: AGENT_TRANSPORT=serve at the import sites that
# read it. configs.AGENT_TRANSPORT is captured at module import time, so
# monkeypatching the env doesn't propagate — we patch the symbol where
# the read happens (base.py is where send_message branches now, plus
# the Docker manager for its own send_message branch).
# ----------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _force_serve_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg, "AGENT_TRANSPORT", AgentTransport.SERVE)
    monkeypatch.setattr(sandbox_base, "AGENT_TRANSPORT", AgentTransport.SERVE)
    monkeypatch.setattr(docker_mgr, "AGENT_TRANSPORT", AgentTransport.SERVE)


@dataclass(frozen=True)
class _PoolContainer:
    sandbox_id: UUID
    manager: DockerSandboxManager
    session_id: UUID
    llm_config: LLMProviderConfig


@pytest.fixture(scope="module")
def _pool_container() -> Generator[_PoolContainer, None, None]:
    """One Docker sandbox container per test module.

    Provisioning a container is fast (~3s) but opencode-serve takes
    another 1–5s to bind :4096. Amortizing across the module avoids
    paying that cost per test.
    """
    manager = DockerSandboxManager()
    sandbox_id = uuid4()
    user_id = uuid4()
    # Override the helper's default model — gpt-5-mini is the project's
    # cheap-and-fast tier for live-LLM tests. ``default_llm_config``'s
    # built-in default is not appropriate here.
    llm_config = default_llm_config(
        api_key=os.environ["OPENAI_API_KEY"],
        model_name="gpt-5-mini",
    )

    info = manager.provision(
        sandbox_id=sandbox_id,
        user_id=user_id,
        tenant_id="docker-streaming-test",
        llm_config=llm_config,
        onyx_pat="ci-test-pat",
    )
    assert info.directory_path.startswith("docker://"), (
        f"unexpected directory_path shape: {info.directory_path!r}"
    )

    session_id = uuid4()
    manager.setup_session_workspace(
        sandbox_id=sandbox_id,
        session_id=session_id,
        llm_config=llm_config,
        nextjs_port=None,
        skills_section="No skills available.",
    )

    try:
        yield _PoolContainer(
            sandbox_id=sandbox_id,
            manager=manager,
            session_id=session_id,
            llm_config=llm_config,
        )
    finally:
        try:
            manager.terminate(sandbox_id)
        except Exception:
            pass


# ----------------------------------------------------------------------
# Event-collection helpers (mirrors test_opencode_serve_streaming)
# ----------------------------------------------------------------------


class _Collected:
    __slots__ = ("chunks", "thoughts", "tool_starts", "tool_progress", "term", "errors")

    def __init__(self) -> None:
        self.chunks: list[AgentMessageChunk] = []
        self.thoughts: list[AgentThoughtChunk] = []
        self.tool_starts: list[ToolCallStart] = []
        self.tool_progress: list[ToolCallProgress] = []
        self.term: PromptResponse | None = None
        self.errors: list[Error] = []

    @property
    def text(self) -> str:
        return "".join(c.content.text for c in self.chunks)  # type: ignore[union-attr]


def _drive_turn(
    pool: _PoolContainer,
    prompt: str,
    *,
    opencode_session_id: str | None = None,
) -> tuple[_Collected, str | None]:
    """One turn end-to-end via ``DockerSandboxManager.send_message``."""
    if opencode_session_id is None:
        opencode_session_id = pool.manager.ensure_opencode_session(
            pool.sandbox_id, pool.session_id
        )
    assert opencode_session_id, "ensure_opencode_session must return an id under serve"

    out = _Collected()
    for ev in pool.manager.send_message(
        pool.sandbox_id,
        pool.session_id,
        prompt,
        opencode_session_id=opencode_session_id,
    ):
        if isinstance(ev, AgentMessageChunk):
            out.chunks.append(ev)
        elif isinstance(ev, AgentThoughtChunk):
            out.thoughts.append(ev)
        elif isinstance(ev, ToolCallStart):
            out.tool_starts.append(ev)
        elif isinstance(ev, ToolCallProgress):
            out.tool_progress.append(ev)
        elif isinstance(ev, PromptResponse):
            out.term = ev
        elif isinstance(ev, Error):
            out.errors.append(ev)
        elif isinstance(ev, SSEKeepalive):
            pass
    return out, opencode_session_id


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


def test_provision_injects_serve_env_into_real_container(
    _pool_container: _PoolContainer,
) -> None:
    """The container actually got AGENT_TRANSPORT=serve + the password +
    OPENCODE_CONFIG_CONTENT in its env. Mock tests assert on
    ``build_container_create_kwargs`` output; this asserts on what Docker
    actually accepted. If the env-allowlist invariant regresses (e.g. a
    contributor adds a new env via a different code path), this fails."""
    pool = _pool_container
    name = _sandbox_container_name(pool.sandbox_id)
    container = pool.manager._docker.containers.get(name)
    env_list: list[str] = container.attrs["Config"]["Env"]
    env_keys = {entry.split("=", 1)[0] for entry in env_list}
    # All four serve-related vars are present.
    assert "AGENT_TRANSPORT" in env_keys
    assert "OPENCODE_SERVER_PASSWORD" in env_keys
    assert "OPENCODE_SERVE_PORT" in env_keys
    assert "OPENCODE_CONFIG_CONTENT" in env_keys
    # Sanity-check the transport value.
    for entry in env_list:
        if entry.startswith("AGENT_TRANSPORT="):
            assert entry == "AGENT_TRANSPORT=serve"
            break


def test_read_opencode_password_roundtrips_via_docker_inspect(
    _pool_container: _PoolContainer,
) -> None:
    """The api_server-side password lookup MUST return exactly what
    opencode-serve in the container loaded — otherwise every request 401s.
    This is the load-bearing invariant the Docker port adds, and a unit
    test with a mocked container can't catch a divergence between
    `build_container_create_kwargs` and `_read_opencode_password`."""
    pool = _pool_container
    pw = pool.manager._read_opencode_password(pool.sandbox_id)
    assert pw is not None
    # token_urlsafe(32) produces 43-char output; allow slack for future
    # changes but the absolute floor is 32 chars for any reasonable secret.
    assert len(pw) >= 32


def test_simple_message_streams_text_and_terminates(
    _pool_container: _PoolContainer,
) -> None:
    """End-to-end smoke: drive one real turn against opencode-serve
    inside the Docker sandbox container, assert we get text deltas and a
    terminator. If this passes, the entire stack works: password injected
    correctly, bridge-network reachability, serve binds :4096, prompt
    POST + event SSE roundtrip, translator emits ACP events."""
    out, _ = _drive_turn(_pool_container, "Say hi briefly.")

    assert out.term is not None, "send_message never terminated"
    assert out.term.stop_reason == "end_turn"
    assert out.errors == [], f"unexpected errors: {out.errors}"
    assert len(out.text) > 0, "expected at least one AgentMessageChunk"
    # Regression: user prompt must NOT leak into assistant text.
    assert "Say hi briefly" not in out.text, (
        f"user prompt leaked into assistant text: {out.text!r}"
    )


def test_bash_tool_call_lifecycle(
    _pool_container: _PoolContainer,
) -> None:
    """Tool call lifecycle parity with K8s: exactly one ToolCallStart per
    call_id; ToolCallProgress sequence ends in status=completed."""
    out, _ = _drive_turn(
        _pool_container,
        "Run the bash command `echo DOCKER_SERVE_OK` and then say DONE.",
    )

    assert out.term is not None
    assert out.errors == []
    assert len(out.tool_starts) >= 1, "expected at least one ToolCallStart"
    bash_starts = [s for s in out.tool_starts if s.kind == "execute"]
    assert len(bash_starts) >= 1, (
        f"no bash tool call seen; got kinds: {[s.kind for s in out.tool_starts]}"
    )
    for cid in {s.tool_call_id for s in out.tool_starts}:
        progress = [p for p in out.tool_progress if p.tool_call_id == cid]
        assert any(p.status == "completed" for p in progress), (
            f"tool call {cid} never reached status=completed; "
            f"statuses: {[p.status for p in progress]}"
        )


def test_multi_turn_session_terminates_each_turn(
    _pool_container: _PoolContainer,
) -> None:
    """Three back-to-back prompts on the same opencode session. Each
    must terminate cleanly. Catches event-bus cross-talk and stuck
    prompt-slot locks — both of which would block subsequent turns."""
    opencode_session_id: str | None = None
    for i, prompt in enumerate(
        [
            "Say 'one' and nothing else.",
            "Say 'two' and nothing else.",
            "Say 'three' and nothing else.",
        ]
    ):
        out, opencode_session_id = _drive_turn(
            _pool_container, prompt, opencode_session_id=opencode_session_id
        )
        assert out.term is not None, f"turn {i + 1} did not terminate"
        assert out.errors == [], f"turn {i + 1} had errors: {out.errors}"
        assert len(out.text) > 0, f"turn {i + 1} produced no text"


def test_yields_at_most_one_terminator(
    _pool_container: _PoolContainer,
) -> None:
    """opencode emits several end-of-turn signals (``message.updated``
    completed, ``session.idle``, ``session.status``→idle). Whichever
    fires first must terminate the turn; the rest must be suppressed.
    Catches a regression in the terminator-dedup logic on the shared
    base-class ``_send_message_via_serve`` path."""
    pool = _pool_container
    opencode_session_id: str | None = pool.manager.ensure_opencode_session(
        pool.sandbox_id, pool.session_id
    )
    extra_terms = 0
    for i in range(3):
        term_count = 0
        for ev in pool.manager.send_message(
            pool.sandbox_id,
            pool.session_id,
            f"Say '{i}'.",
            opencode_session_id=opencode_session_id,
        ):
            if isinstance(ev, PromptResponse):
                term_count += 1
        if term_count != 1:
            extra_terms += 1
    assert extra_terms == 0, (
        f"{extra_terms} turn(s) yielded ≠1 PromptResponse — terminator de-dup is broken"
    )


def test_prompt_slot_blocks_concurrent_turn(
    _pool_container: _PoolContainer,
) -> None:
    """``prompt_slot`` is the load-bearing lock that prevents the
    phantom-user_message bug. The Docker manager inherits the impl from
    base — this test confirms the lock state actually got initialized via
    ``_init_serve_state`` during ``_initialize``. A regression where
    Docker forgot to call it would surface as the lock dict missing."""
    pool = _pool_container
    with pool.manager.prompt_slot(pool.sandbox_id, pool.session_id) as outer:
        assert outer is True
        with pool.manager.prompt_slot(pool.sandbox_id, pool.session_id) as inner:
            assert inner is False, (
                "second concurrent prompt_slot acquire must return False"
            )


def test_terminate_then_subscribe_refuses(
    _pool_container: _PoolContainer,
) -> None:
    """After ``terminate``, late ``_get_or_create_event_bus`` calls MUST
    raise rather than spin a reader thread against the deleted container.
    The K8s manager tombstones the sandbox_id; Docker inherits the same
    machinery via base. This is in its own test (separate sandbox_id, not
    the pool) so the teardown doesn't break other tests."""
    pool = _pool_container
    sandbox_id = uuid4()
    pool.manager.provision(
        sandbox_id=sandbox_id,
        user_id=uuid4(),
        tenant_id="docker-streaming-test",
        llm_config=pool.llm_config,
        onyx_pat="ci-test-pat",
    )
    pool.manager.terminate(sandbox_id)

    with pytest.raises(RuntimeError, match="terminated"):
        pool.manager._get_or_create_event_bus(sandbox_id)
