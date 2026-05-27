"""Unit tests for the ``get_sandbox_manager()`` factory.

Verifies the SANDBOX_BACKEND dispatch wires up the right manager class for
each backend value, without instantiating Docker/K8s clients.
"""

from __future__ import annotations

from typing import Any

import pytest

from onyx.server.features.build import configs
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox import base as base_module


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the cached singleton before each test so backend switches are honored."""
    monkeypatch.setattr(base_module, "_sandbox_manager_instance", None)


def test_unknown_backend_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base_module, "SANDBOX_BACKEND", "totally-bogus")
    with pytest.raises(ValueError, match="Unknown sandbox backend"):
        base_module.get_sandbox_manager()


def test_docker_backend_returns_docker_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backend=docker must dispatch to ``DockerSandboxManager``, not raise NotImplementedError."""
    monkeypatch.setattr(base_module, "SANDBOX_BACKEND", SandboxBackend.DOCKER)

    # Don't try to talk to /var/run/docker.sock in a unit test — stub _initialize.
    from onyx.server.features.build.sandbox.docker import docker_sandbox_manager

    monkeypatch.setattr(docker_sandbox_manager.DockerSandboxManager, "_instance", None)

    def _fake_init(self: Any) -> None:
        self._image = "fake"
        self._network_name = "fake"
        self._memory_limit = "2g"
        self._cpu_limit = 1.0
        self._snapshot_manager = None
        from pathlib import Path

        self._agent_instructions_template_path = Path("/tmp/AGENTS.template.md")  # noqa: S108

    monkeypatch.setattr(
        docker_sandbox_manager.DockerSandboxManager, "_initialize", _fake_init
    )
    mgr = base_module.get_sandbox_manager()
    assert mgr.__class__.__name__ == "DockerSandboxManager"


def test_sandbox_backend_enum_includes_docker_and_kubernetes() -> None:
    """Sanity: the enum still exposes DOCKER and KUBERNETES values."""
    assert SandboxBackend.DOCKER.value == "docker"
    assert SandboxBackend.KUBERNETES.value == "kubernetes"
    assert configs.SandboxBackend("docker") is SandboxBackend.DOCKER
    assert configs.SandboxBackend("kubernetes") is SandboxBackend.KUBERNETES


def test_local_backend_string_raises_helpful_error() -> None:
    """``SANDBOX_BACKEND=local`` is no longer supported; the parser raises a
    pointed startup error with a doc pointer rather than the bare
    ``ValueError`` from the enum constructor.
    """
    with pytest.raises(RuntimeError, match="local-kubernetes.md"):
        configs._parse_sandbox_backend("local")
