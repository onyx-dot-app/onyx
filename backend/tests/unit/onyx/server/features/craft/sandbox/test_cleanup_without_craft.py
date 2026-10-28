import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.background.celery.tasks.build import tasks
from onyx.feature_flags.interface import NoOpFeatureFlagProvider
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox.kubernetes import k8s_client


def _run_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    enable_craft: bool = False,
    provider: object | None = None,
    backend: SandboxBackend = SandboxBackend.KUBERNETES,
    kube_config: bool = False,
    sandbox_exists: bool = False,
    lock_acquired: bool = False,
) -> tuple[MagicMock, MagicMock, MagicMock]:
    db_session = MagicMock()

    @contextmanager
    def fake_session() -> Iterator[MagicMock]:
        yield db_session

    get_manager = MagicMock()
    if not kube_config:
        get_manager.side_effect = RuntimeError("Invalid kube-config file")
    reconcile = MagicMock()
    cache = MagicMock()
    cache.lock.return_value.acquire.return_value = lock_acquired
    cache.get.return_value = None

    monkeypatch.setattr(tasks, "ENABLE_CRAFT", enable_craft)
    monkeypatch.setattr(tasks, "SANDBOX_BACKEND", backend)
    monkeypatch.setattr(
        tasks,
        "get_default_feature_flag_provider",
        lambda: provider if provider is not None else NoOpFeatureFlagProvider(),
    )
    monkeypatch.setattr(k8s_client, "kube_config_available", lambda: kube_config)
    monkeypatch.setattr(tasks, "any_sandbox_exists", lambda _db: sandbox_exists)
    monkeypatch.setattr(tasks, "get_session_with_current_tenant", fake_session)
    monkeypatch.setattr(tasks, "get_sandbox_manager", get_manager)
    monkeypatch.setattr(tasks, "reconcile_sandbox_resources", reconcile)
    monkeypatch.setattr(tasks, "get_running_sandboxes", lambda *_a, **_k: [])
    monkeypatch.setattr(tasks, "get_redis_client", MagicMock())
    monkeypatch.setattr(tasks, "get_cache_backend", lambda **_kwargs: cache)

    tasks.cleanup_idle_sandboxes_task.run(tenant_id="public")  # ty: ignore[invalid-argument-type]
    return cache, get_manager, reconcile


def test_cleanup_skips_without_craft_or_kube_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache, get_manager, _ = _run_cleanup(monkeypatch, lock_acquired=True)

    cache.lock.return_value.acquire.assert_not_called()
    get_manager.assert_not_called()


@pytest.mark.parametrize(
    "overrides",
    [
        {"enable_craft": True},
        {"provider": MagicMock()},
        {"backend": SandboxBackend.DOCKER},
        {"kube_config": True},
        {"sandbox_exists": True},
    ],
)
def test_cleanup_runs_when_sandboxes_may_exist(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, Any],
) -> None:
    cache, _, _ = _run_cleanup(monkeypatch, **overrides)

    cache.lock.return_value.acquire.assert_called_once_with(blocking=False)


def test_orphan_resources_reconciled_without_sandbox_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Craft is off and the last sandbox row is gone, but a cluster is still
    # reachable, so leftover resources must still be reconciled.
    _, get_manager, reconcile = _run_cleanup(
        monkeypatch, kube_config=True, sandbox_exists=False, lock_acquired=True
    )

    get_manager.assert_called_once()
    reconcile.assert_called_once()
    assert reconcile.call_args.args[0] is get_manager.return_value
    assert reconcile.call_args.args[1] == "public"


@pytest.mark.parametrize(
    ("env", "files", "expected"),
    [
        ({}, set(), False),
        (
            {"KUBERNETES_SERVICE_HOST": "10.0.0.1", "KUBERNETES_SERVICE_PORT": "443"},
            {"token"},
            True,
        ),
        ({"KUBERNETES_SERVICE_HOST": "10.0.0.1"}, {"token"}, False),
        ({}, {"kubeconfig"}, True),
    ],
)
def test_kube_config_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    env: dict[str, str],
    files: set[str],
    expected: bool,
) -> None:
    root = tmp_path
    token = root / "token"
    kubeconfig = root / "kubeconfig"
    for name in files:
        (root / name).write_text("x")
    for key in ("KUBERNETES_SERVICE_HOST", "KUBERNETES_SERVICE_PORT"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        k8s_client.incluster_config, "SERVICE_TOKEN_FILENAME", str(token)
    )
    monkeypatch.setattr(
        k8s_client.kube_config,
        "KUBE_CONFIG_DEFAULT_LOCATION",
        os.pathsep.join([str(root / "missing"), str(kubeconfig)]),
    )

    assert k8s_client.kube_config_available() is expected
