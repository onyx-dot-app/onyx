from unittest.mock import MagicMock, patch

from onyx.background.periodic_poller import (
    _build_periodic_tasks,
    _run_oauth_provider_cleanup,
)


def _task_names(*, enabled: bool) -> list[str]:
    with patch("onyx.configs.app_configs.OAUTH_PROVIDER_ENABLED", enabled):
        return [t.name for t in _build_periodic_tasks()]


def test_oauth_provider_cleanup_follows_provider_flag() -> None:
    assert "oauth-provider-cleanup" in _task_names(enabled=True)
    assert "oauth-provider-cleanup" not in _task_names(enabled=False)


def test_oauth_provider_cleanup_lock_id_is_unique() -> None:
    with (
        patch("onyx.configs.app_configs.OAUTH_PROVIDER_ENABLED", True),
        patch("onyx.configs.app_configs.AUTO_LLM_CONFIG_URL", "http://llm"),
        patch("onyx.configs.app_configs.SCHEDULED_EVAL_DATASET_NAMES", ["ds"]),
        patch("onyx.utils.variable_functionality.global_version") as mock_version,
    ):
        mock_version.is_ee_version.return_value = True
        lock_ids = [t.lock_id for t in _build_periodic_tasks()]

    assert len(lock_ids) == len(set(lock_ids))


@patch("shared_configs.contextvars.get_current_tenant_id", return_value="tenant_1")
@patch(
    "onyx.background.celery.tasks.oauth_provider.tasks.cleanup_oauth_provider_clients"
)
@patch(
    "onyx.background.celery.tasks.oauth_provider.tasks.cleanup_oauth_provider_grants"
)
def test_oauth_provider_cleanup_runs_grants_and_clients(
    mock_grants: MagicMock, mock_clients: MagicMock, _mock_tenant: MagicMock
) -> None:
    _run_oauth_provider_cleanup()

    mock_grants.assert_called_once_with(tenant_id="tenant_1")
    mock_clients.assert_called_once_with()
