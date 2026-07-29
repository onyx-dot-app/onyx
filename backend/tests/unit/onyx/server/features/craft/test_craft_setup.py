"""Unit tests for Craft's startup work.

The prewarm is an optimisation over work provision() still does on demand, so it
must never block startup and never raise.
"""

from __future__ import annotations

import logging
import threading
from unittest.mock import MagicMock

import pytest

import onyx.server.features.build.setup as craft_setup
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    DockerSandboxManager,
)


def _install_manager(monkeypatch: pytest.MonkeyPatch, manager: MagicMock) -> None:
    monkeypatch.setattr(craft_setup, "get_sandbox_manager", lambda: manager)


def test_setup_prewarms_in_the_background(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = MagicMock()
    _install_manager(monkeypatch, manager)

    thread = craft_setup.setup_craft()

    # Daemon, so a hung pull can never keep the process alive on shutdown.
    assert thread.daemon
    thread.join(timeout=10)
    assert not thread.is_alive()
    manager.prewarm.assert_called_once_with()


def test_setup_returns_before_the_work_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blocking here would hold api_server readiness behind a registry call."""
    release = threading.Event()
    manager = MagicMock()
    manager.prewarm.side_effect = lambda: release.wait(timeout=10)
    _install_manager(monkeypatch, manager)

    thread = craft_setup.setup_craft()

    assert thread.is_alive()  # still working; setup_craft already returned
    release.set()
    thread.join(timeout=10)


# Required by the two tests below: a thread that dies on an escaping exception is
# also not alive, so `not is_alive()` alone passes either way. Erroring on the
# unhandled-thread warning is what separates "swallowed" from "crashed".
_UNHANDLED_THREAD_EXC = "error::pytest.PytestUnhandledThreadExceptionWarning"


@pytest.mark.filterwarnings(_UNHANDLED_THREAD_EXC)
def test_setup_swallows_an_unresolvable_manager(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """get_sandbox_manager() raises on a misconfigured deployment — a missing
    kubeconfig, or no SANDBOX_PROXY_HOST. Startup must survive it."""
    monkeypatch.setattr(
        craft_setup,
        "get_sandbox_manager",
        MagicMock(side_effect=RuntimeError("Failed to load Kubernetes configuration")),
    )

    with caplog.at_level(logging.WARNING):
        craft_setup.setup_craft().join(timeout=10)

    assert "prewarm failed" in caplog.text


@pytest.mark.filterwarnings(_UNHANDLED_THREAD_EXC)
def test_setup_swallows_failed_work(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    manager = MagicMock()
    manager.prewarm.side_effect = RuntimeError("registry down")
    _install_manager(monkeypatch, manager)

    with caplog.at_level(logging.WARNING):
        craft_setup.setup_craft().join(timeout=10)

    assert "prewarm failed" in caplog.text


def test_prewarm_defaults_to_a_no_op() -> None:
    """Backends with nothing to warm inherit the base implementation, so adding
    one never forces a stub. Kubernetes relies on this: it pre-pulls at deploy
    time via the DaemonSet."""
    SandboxManager.prewarm(MagicMock())  # must not raise


def test_docker_prewarm_pulls_the_image() -> None:
    """Docker is the backend that overrides it. Called unbound so the singleton
    is never built — no Docker socket needed."""
    manager = MagicMock()

    DockerSandboxManager.prewarm(manager)

    manager._ensure_sandbox_image.assert_called_once_with()
