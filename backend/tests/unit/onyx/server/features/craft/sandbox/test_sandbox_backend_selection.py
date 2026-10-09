"""Unit tests for the ``get_sandbox_manager()`` factory.

Verifies the SANDBOX_BACKEND dispatch wires up the right manager class for
each backend value, without instantiating Docker/K8s clients.
"""

from __future__ import annotations

from typing import Any

import pytest

from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox import factory as factory_module


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the cached singleton before each test so backend switches are honored."""
    monkeypatch.setattr(factory_module, "_sandbox_manager_instance", None)


def test_unknown_backend_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory_module, "SANDBOX_BACKEND", "totally-bogus")
    with pytest.raises(ValueError, match="Unknown sandbox backend"):
        factory_module.get_sandbox_manager()


def test_docker_backend_returns_docker_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backend=docker must dispatch to ``DockerSandboxManager``, not raise NotImplementedError."""
    monkeypatch.setattr(factory_module, "SANDBOX_BACKEND", SandboxBackend.DOCKER)

    # Don't try to talk to /var/run/docker.sock in a unit test — stub __init__.
    from onyx.server.features.build.sandbox.docker import docker_sandbox_manager

    def _fake_init(self: Any) -> None:
        self._image = "fake"
        self._network_name = "fake"
        self._memory_limit = "2g"
        self._cpu_limit = 1.0
        self._snapshot_manager = None
        from pathlib import Path

        self._agent_instructions_template_path = Path("/tmp/AGENTS.template.md")  # noqa: S108

    monkeypatch.setattr(
        docker_sandbox_manager.DockerSandboxManager, "__init__", _fake_init
    )
    mgr = factory_module.get_sandbox_manager()
    assert mgr.__class__.__name__ == "DockerSandboxManager"


def test_repeated_calls_return_the_same_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(factory_module, "SANDBOX_BACKEND", SandboxBackend.DOCKER)
    from onyx.server.features.build.sandbox.docker import docker_sandbox_manager

    monkeypatch.setattr(
        docker_sandbox_manager.DockerSandboxManager,
        "__init__",
        lambda _self: None,
    )
    assert factory_module.get_sandbox_manager() is factory_module.get_sandbox_manager()


def test_failed_construction_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed init must not be cached; the next call retries."""
    monkeypatch.setattr(factory_module, "SANDBOX_BACKEND", SandboxBackend.DOCKER)
    from onyx.server.features.build.sandbox.docker import docker_sandbox_manager

    attempts = {"count": 0}

    def _flaky_init(_self: Any) -> None:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("transient docker socket failure")

    monkeypatch.setattr(
        docker_sandbox_manager.DockerSandboxManager, "__init__", _flaky_init
    )

    with pytest.raises(RuntimeError, match="transient docker socket failure"):
        factory_module.get_sandbox_manager()
    assert factory_module._sandbox_manager_instance is None

    mgr = factory_module.get_sandbox_manager()
    assert mgr is factory_module._sandbox_manager_instance
    assert attempts["count"] == 2
