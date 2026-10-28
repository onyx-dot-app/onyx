from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from onyx.background.celery.tasks.build import tasks
from onyx.feature_flags.interface import NoOpFeatureFlagProvider


def _run_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    enable_craft: bool,
    provider: object,
    sandbox_exists: bool,
) -> MagicMock:
    db_session = MagicMock()

    @contextmanager
    def fake_session() -> Iterator[MagicMock]:
        yield db_session

    get_manager = MagicMock(side_effect=RuntimeError("Invalid kube-config file"))
    cache = MagicMock()
    cache.lock.return_value.acquire.return_value = False

    monkeypatch.setattr(tasks, "ENABLE_CRAFT", enable_craft)
    monkeypatch.setattr(tasks, "get_default_feature_flag_provider", lambda: provider)
    monkeypatch.setattr(tasks, "any_sandbox_exists", lambda _db: sandbox_exists)
    monkeypatch.setattr(tasks, "get_session_with_current_tenant", fake_session)
    monkeypatch.setattr(tasks, "get_sandbox_manager", get_manager)
    monkeypatch.setattr(tasks, "get_redis_client", MagicMock())
    monkeypatch.setattr(tasks, "get_cache_backend", lambda **_kwargs: cache)

    tasks.cleanup_idle_sandboxes_task.run(tenant_id="public")  # ty: ignore[invalid-argument-type]
    return cache


def test_cleanup_skips_without_craft_or_sandboxes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _run_cleanup(
        monkeypatch,
        enable_craft=False,
        provider=NoOpFeatureFlagProvider(),
        sandbox_exists=False,
    )

    cache.lock.return_value.acquire.assert_not_called()


@pytest.mark.parametrize(
    ("enable_craft", "provider", "sandbox_exists"),
    [
        (True, NoOpFeatureFlagProvider(), False),
        (False, MagicMock(), False),
        (False, NoOpFeatureFlagProvider(), True),
    ],
)
def test_cleanup_runs_when_craft_may_be_in_use(
    monkeypatch: pytest.MonkeyPatch,
    enable_craft: bool,
    provider: object,
    sandbox_exists: bool,
) -> None:
    cache = _run_cleanup(
        monkeypatch,
        enable_craft=enable_craft,
        provider=provider,
        sandbox_exists=sandbox_exists,
    )

    cache.lock.return_value.acquire.assert_called_once_with(blocking=False)
