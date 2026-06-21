"""Unit tests for ``DockerSandboxManager`` serve-transport wiring.

These tests exercise the pure logic added by the
docker-sandbox-serve port — no Docker engine required. We use
``object.__new__(DockerSandboxManager)`` to bypass ``_initialize``
(which would try to open the Docker socket) and verify:

- ``_load_serve_connection_info`` produces the expected container-name
  fallback URL or localhost-published URL + cleartext password from a mocked
  container's ``inspect`` data, yields a ``None`` password for legacy
  containers, and returns ``None`` when the container is gone.
- ``_render_agents_md`` produces shell-escaped AGENTS.md content.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest

import onyx.server.features.build.sandbox.docker.dev_mode_serve as dev_mode_serve
import onyx.server.features.build.sandbox.docker.docker_sandbox_manager as dsm
from onyx.server.features.build.configs import OPENCODE_SERVE_PORT
from onyx.server.features.build.configs import OPENCODE_SERVER_PASSWORD
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    DockerSandboxManager,
)
from onyx.server.features.build.sandbox.models import LLMProviderConfig

_SBX = UUID("12345678-1234-1234-1234-1234567890ab")


def _bare_manager() -> DockerSandboxManager:
    """
    DockerSandboxManager without touching the Docker socket: skips
    ``_initialize`` so contributors without docker running can still run
    these tests.
    """
    DockerSandboxManager._instance = None
    mgr: DockerSandboxManager = object.__new__(DockerSandboxManager)
    mgr._agent_instructions_template_path = (  # type: ignore[attr-defined]
        dsm.Path(dsm.__file__).parent.parent.parent / "AGENTS.template.md"
    )
    mgr._init_serve_state()
    return mgr


def test_load_serve_connection_info_uses_container_name_and_port() -> None:
    """Older/unpublished containers fall back to bridge DNS."""
    mgr = _bare_manager()
    fake_container = MagicMock()
    fake_container.attrs = {"Config": {"Env": []}}
    mgr._docker = MagicMock()  # type: ignore[attr-defined]
    mgr._docker.containers.get.return_value = fake_container

    info = mgr._load_serve_connection_info(_SBX)
    assert info is not None
    assert info.base_url == f"http://sandbox-12345678:{OPENCODE_SERVE_PORT}"


def test_load_serve_connection_info_prefers_localhost_published_port_in_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Host-run workers cannot resolve Docker bridge DNS; use the published port.
    """
    monkeypatch.setattr(dsm, "DEV_MODE", True)
    mgr = _bare_manager()
    fake_container = MagicMock()
    fake_container.attrs = {
        "Config": {"Env": []},
        "NetworkSettings": {
            "Ports": {
                dev_mode_serve.OPENCODE_SERVE_CONTAINER_PORT: [
                    {"HostIp": "127.0.0.1", "HostPort": "49153"},
                ],
            },
        },
    }
    mgr._docker = MagicMock()  # type: ignore[attr-defined]
    mgr._docker.containers.get.return_value = fake_container

    info = mgr._load_serve_connection_info(_SBX)
    assert info is not None
    assert info.base_url == "http://127.0.0.1:49153"


def test_load_serve_connection_info_ignores_published_port_outside_dev() -> None:
    """Compose workers use sandbox bridge DNS, not host localhost."""
    mgr = _bare_manager()
    fake_container = MagicMock()
    fake_container.attrs = {
        "Config": {"Env": []},
        "NetworkSettings": {
            "Ports": {
                dev_mode_serve.OPENCODE_SERVE_CONTAINER_PORT: [
                    {"HostIp": "127.0.0.1", "HostPort": "49153"},
                ],
            },
        },
    }
    mgr._docker = MagicMock()  # type: ignore[attr-defined]
    mgr._docker.containers.get.return_value = fake_container

    info = mgr._load_serve_connection_info(_SBX)
    assert info is not None
    assert info.base_url == f"http://sandbox-12345678:{OPENCODE_SERVE_PORT}"


def test_load_serve_connection_info_normalizes_wildcard_host_ip_in_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Docker may report wildcard binds; clients should connect via localhost.
    """
    monkeypatch.setattr(dsm, "DEV_MODE", True)
    mgr = _bare_manager()
    fake_container = MagicMock()
    fake_container.attrs = {
        "Config": {"Env": []},
        "NetworkSettings": {
            "Ports": {
                dev_mode_serve.OPENCODE_SERVE_CONTAINER_PORT: [
                    {"HostIp": "0.0.0.0", "HostPort": "49154"},
                ],
            },
        },
    }
    mgr._docker = MagicMock()  # type: ignore[attr-defined]
    mgr._docker.containers.get.return_value = fake_container

    info = mgr._load_serve_connection_info(_SBX)
    assert info is not None
    assert info.base_url == "http://127.0.0.1:49154"


def test_load_serve_connection_info_parses_password_from_container_env() -> None:
    """
    The cleartext password lives in the container's env (Docker Engine API).
    Decoded on every load; cached by the mixin so the hot path doesn't re-hit
    ``docker inspect``.
    """
    mgr = _bare_manager()
    fake_container = MagicMock()
    fake_container.attrs = {
        "Config": {
            "Env": [
                "ONYX_PAT=pat-redacted",
                "ONYX_SERVER_URL=http://api_server:8080",
                f"{OPENCODE_SERVER_PASSWORD}=correct-horse-battery-staple",
            ]
        }
    }
    mgr._docker = MagicMock()  # type: ignore[attr-defined]
    mgr._docker.containers.get.return_value = fake_container

    info = mgr._load_serve_connection_info(_SBX)
    assert info is not None
    assert info.password == "correct-horse-battery-staple"


def test_load_serve_connection_info_yields_none_password_for_legacy() -> None:
    """
    A container provisioned before this code landed has no
    ``OPENCODE_SERVER_PASSWORD`` in env. The bus then falls back to no-auth and
    logs a warning.
    """
    mgr = _bare_manager()
    fake_container = MagicMock()
    fake_container.attrs = {
        "Config": {"Env": ["ONYX_PAT=pat", "ONYX_SERVER_URL=https://onyx.example.com"]}
    }
    mgr._docker = MagicMock()  # type: ignore[attr-defined]
    mgr._docker.containers.get.return_value = fake_container

    info = mgr._load_serve_connection_info(_SBX)
    assert info is not None
    assert info.password is None


def test_load_serve_connection_info_returns_none_when_container_missing() -> None:
    """
    terminate() races provision() — looking up a deleted container should fail
    gracefully, not raise.
    """
    mgr = _bare_manager()
    mgr._docker = MagicMock()  # type: ignore[attr-defined]
    mgr._docker.containers.get.side_effect = dsm.NotFound("gone")

    assert mgr._load_serve_connection_info(_SBX) is None


def test_load_serve_connection_info_handles_password_with_equals_sign() -> None:
    """
    ``token_urlsafe(32)`` can produce ``=`` chars at the tail. The parser must
    split on the FIRST equals only.
    """
    mgr = _bare_manager()
    weird_password = "tail==padding=="
    fake_container = MagicMock()
    fake_container.attrs = {
        "Config": {
            "Env": [
                f"{OPENCODE_SERVER_PASSWORD}={weird_password}",
            ]
        }
    }
    mgr._docker = MagicMock()  # type: ignore[attr-defined]
    mgr._docker.containers.get.return_value = fake_container

    info = mgr._load_serve_connection_info(_SBX)
    assert info is not None
    assert info.password == weird_password


@pytest.fixture
def llm_config() -> LLMProviderConfig:
    return LLMProviderConfig(
        provider="openai",
        model_name="gpt-5-mini",
        api_key="sk-test",
        api_base=None,
    )


def test_render_agents_md_returns_escaped_string(
    llm_config: LLMProviderConfig,
) -> None:
    """
    opencode.json is not rendered per-session; only AGENTS.md is, with single
    quotes shell-escaped for ``printf '%s' '...'``.
    """
    mgr = _bare_manager()
    agents_md = mgr._render_agents_md(
        llm_config=llm_config,
        nextjs_port=None,
        skills_section="",
    )
    assert isinstance(agents_md, str)
    assert agents_md
    assert "'" not in agents_md or "'\\''" in agents_md


def test_init_serve_state_is_idempotent() -> None:
    """
    ``_init_serve_state`` is called from ``_initialize``; provision paths must
    not blow up if called twice.
    """
    mgr = _bare_manager()
    first_lock = mgr._event_buses_lock
    mgr._init_serve_state()  # second call
    assert mgr._event_buses_lock is first_lock
    assert mgr._event_buses == {}
    assert mgr._terminated_sandboxes == set()


def test_prompt_slot_serializes_on_docker() -> None:
    """
    Pins the prompt-slot lock contract on Docker — same as the K8s test, catches
    a regression if Docker skips ``_init_serve_state``.
    """
    mgr = _bare_manager()

    other_session = UUID("00000000-0000-0000-0000-000000000001")
    with mgr.prompt_slot(_SBX, other_session) as outer:
        assert outer is True
        with mgr.prompt_slot(_SBX, other_session) as inner:
            assert inner is False


def test_provision_generates_fresh_password_and_injects_into_container_env(
    monkeypatch: pytest.MonkeyPatch,
    llm_config: LLMProviderConfig,
) -> None:
    """
    ``provision()`` must mint a per-call HTTP Basic password and thread it
    through ``build_container_create_kwargs`` into the container env — otherwise
    every later request 401s.
    """
    monkeypatch.setattr(dsm, "DEV_MODE", True)
    monkeypatch.setattr(dsm, "SANDBOX_API_SERVER_URL", "https://onyx.example.com")
    # Skip the actual readiness HTTP probe — that needs a real container.
    monkeypatch.setattr(
        DockerSandboxManager,
        "_wait_for_opencode_serve_ready",
        lambda self, sandbox_id: True,  # noqa: ARG005 — patched callable
    )

    mgr = _bare_manager()
    # Mock the Docker client surface used by provision().
    mgr._docker = MagicMock()  # type: ignore[attr-defined]
    mgr._image = "onyxdotapp/sandbox:test"  # type: ignore[attr-defined]
    mgr._network_name = "onyx_craft_sandbox"  # type: ignore[attr-defined]
    mgr._memory_limit = "2g"  # type: ignore[attr-defined]
    mgr._cpu_limit = 1.0  # type: ignore[attr-defined]
    mgr._compose_project = None  # type: ignore[attr-defined]
    # No existing container.
    mgr._docker.containers.get.side_effect = dsm.NotFound("none")
    # _ensure_sandbox_network — pretend it exists already.
    mgr._docker.networks.get.return_value = MagicMock()
    # _ensure_sandbox_volume — pretend it exists already.
    mgr._docker.volumes.get.return_value = MagicMock()
    # No durable opencode history, so the fresh-container restore is a no-op.
    mgr._snapshot_manager = MagicMock()  # type: ignore[attr-defined]
    mgr._snapshot_manager.has_opencode_history_snapshot.return_value = False

    # Provision creates the container stopped, restores history, then starts it;
    # capture the create kwargs.
    fake_container = MagicMock()
    fake_container.name = "sandbox-12345678"
    fake_container.attrs = {"State": {"Status": "running"}}

    run_calls: list[dict[str, Any]] = []

    def _capture_create(**kwargs: Any) -> Any:
        run_calls.append(kwargs)
        return fake_container

    mgr._docker.containers.create.side_effect = _capture_create

    info = mgr.provision(
        sandbox_id=_SBX,
        user_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        tenant_id="tenant-abc",
        llm_config=llm_config,
        onyx_pat="pat-redacted",
    )

    assert info.status.value == "running"
    assert len(run_calls) == 1
    # Created stopped, then started explicitly after the (no-op) history
    # restore.
    fake_container.start.assert_called_once()
    # A successful provision must not remove the container it just started.
    fake_container.remove.assert_not_called()
    env = run_calls[0]["environment"]
    assert set(env.keys()) == {
        "ONYX_PAT",
        "ONYX_SERVER_URL",
        OPENCODE_SERVER_PASSWORD,
        "OPENCODE_CONFIG_CONTENT",
    }
    assert run_calls[0]["ports"] == {
        dev_mode_serve.OPENCODE_SERVE_CONTAINER_PORT: (
            dev_mode_serve.OPENCODE_SERVE_HOST_BIND_IP,
            None,
        ),
    }
    # The password is a fresh token_urlsafe(32) — long-ish, no spaces.
    pw = env[OPENCODE_SERVER_PASSWORD]
    assert len(pw) >= 32
    assert " " not in pw
    # OPENCODE_CONFIG_CONTENT is valid JSON the agent can parse.
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert "provider" in config

    # Fresh-per-call is stdlib's contract for ``secrets.token_urlsafe``;
    # asserting it across two provisions is just re-stating that.


def test_terminate_closes_event_bus_and_tombstones_sandbox() -> None:
    """
    terminate must close every per-directory bus and add the sandbox to
    ``_terminated_sandboxes`` so a late subscribe can't race in.
    """
    mgr = _bare_manager()
    mgr._docker = MagicMock()  # type: ignore[attr-defined]
    mgr._docker.containers.get.return_value = None
    mgr._docker.volumes.get.side_effect = dsm.NotFound("none")

    # Two buses on the same sandbox exercise the per-directory close path.
    fake_bus_a = MagicMock()
    fake_bus_a.closed = False
    fake_bus_b = MagicMock()
    fake_bus_b.closed = False
    mgr._event_buses[(_SBX, "/workspace/sessions/dir-a")] = fake_bus_a
    mgr._event_buses[(_SBX, "/workspace/sessions/dir-b")] = fake_bus_b

    mgr.terminate(_SBX)

    assert _SBX in mgr._terminated_sandboxes
    assert all(k[0] != _SBX for k in mgr._event_buses)
    fake_bus_a.close.assert_called_once()
    fake_bus_b.close.assert_called_once()


def test_reuse_existing_container_removes_created_state() -> None:
    """
    A container stranded in 'created' state is an incomplete prior provision.
    Reuse must remove it (not start it) so the retry re-creates and restores
    opencode history -- starting it would skip the restore.
    """
    mgr = _bare_manager()
    mgr._docker = MagicMock()  # type: ignore[attr-defined]

    stranded = MagicMock()
    stranded.name = "sandbox-12345678"
    stranded.attrs = {"State": {"Status": "created"}}
    mgr._docker.containers.get.return_value = stranded

    result = mgr._reuse_existing_container(_SBX)

    assert result is None, "A 'created' container must not be reused."
    stranded.remove.assert_called_once_with(force=True)
    stranded.start.assert_not_called()


def test_reuse_existing_container_starts_exited() -> None:
    """
    An 'exited' container ran before, so its writable-layer data home is
    populated; reuse should start it rather than discard it.
    """
    mgr = _bare_manager()
    mgr._docker = MagicMock()  # type: ignore[attr-defined]

    exited = MagicMock()
    exited.name = "sandbox-12345678"
    exited.attrs = {"State": {"Status": "exited"}}
    mgr._docker.containers.get.return_value = exited

    result = mgr._reuse_existing_container(_SBX)

    assert result is exited
    exited.start.assert_called_once()
    exited.remove.assert_not_called()


def test_provision_removes_container_when_history_restore_fails(
    monkeypatch: pytest.MonkeyPatch,
    llm_config: LLMProviderConfig,
) -> None:
    """
    If opencode-history restore fails on a fresh container, provision must
    remove the half-provisioned container (so a retry re-creates + restores) and
    propagate the failure -- it must not start opencode against an empty data
    home.
    """
    monkeypatch.setattr(dsm, "DEV_MODE", True)
    monkeypatch.setattr(dsm, "SANDBOX_API_SERVER_URL", "https://onyx.example.com")

    mgr = _bare_manager()
    mgr._docker = MagicMock()  # type: ignore[attr-defined]
    mgr._image = "onyxdotapp/sandbox:test"  # type: ignore[attr-defined]
    mgr._network_name = "onyx_craft_sandbox"  # type: ignore[attr-defined]
    mgr._memory_limit = "2g"  # type: ignore[attr-defined]
    mgr._cpu_limit = 1.0  # type: ignore[attr-defined]
    mgr._compose_project = None  # type: ignore[attr-defined]
    mgr._docker.containers.get.side_effect = dsm.NotFound("none")
    mgr._docker.networks.get.return_value = MagicMock()
    mgr._docker.volumes.get.return_value = MagicMock()

    # FileStore lookup blows up partway through the history restore.
    mgr._snapshot_manager = MagicMock()  # type: ignore[attr-defined]
    mgr._snapshot_manager.has_opencode_history_snapshot.side_effect = RuntimeError(
        "filestore unavailable"
    )

    fake_container = MagicMock()
    fake_container.name = "sandbox-12345678"
    mgr._docker.containers.create.return_value = fake_container

    with pytest.raises(RuntimeError):
        mgr.provision(
            sandbox_id=_SBX,
            user_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            tenant_id="tenant-abc",
            llm_config=llm_config,
            onyx_pat="pat-redacted",
        )

    # Half-provisioned container is force-removed; opencode never started.
    fake_container.remove.assert_called_once_with(force=True)
    fake_container.start.assert_not_called()
