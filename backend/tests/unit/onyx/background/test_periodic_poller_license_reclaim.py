"""Guards license renewal on deployments the poller exists for: no Redis and
no Celery worker, so the point-of-use scheduler has nothing to enqueue onto
and this thread is the only thing that can renew an expiring license."""

from unittest.mock import MagicMock, patch

from onyx.background.periodic_poller import _build_periodic_tasks, _run_license_reclaim


def _task_names() -> list[str]:
    with patch("onyx.utils.variable_functionality.global_version") as mock_version:
        mock_version.is_ee_version.return_value = True
        return [t.name for t in _build_periodic_tasks()]


def test_license_reclaim_is_registered_on_ee() -> None:
    assert "license-reclaim" in _task_names()


def test_license_reclaim_lock_id_is_unique() -> None:
    """A shared id would make two periodic tasks starve each other, since the
    claim is a try-lock that gives up rather than waiting."""
    with patch("onyx.utils.variable_functionality.global_version") as mock_version:
        mock_version.is_ee_version.return_value = True
        with patch("onyx.configs.app_configs.AUTO_LLM_CONFIG_URL", "http://llm"):
            with patch("onyx.configs.app_configs.SCHEDULED_EVAL_DATASET_NAMES", ["ds"]):
                lock_ids = [t.lock_id for t in _build_periodic_tasks()]

    assert len(lock_ids) == len(set(lock_ids))


def test_license_reclaim_is_absent_without_ee() -> None:
    with patch("onyx.utils.variable_functionality.global_version") as mock_version:
        mock_version.is_ee_version.return_value = False
        assert "license-reclaim" not in [t.name for t in _build_periodic_tasks()]


@patch("shared_configs.contextvars.get_current_tenant_id", return_value="tenant_1")
@patch("onyx.utils.variable_functionality.fetch_versioned_implementation")
def test_reclaim_runs_against_the_polling_thread_tenant(
    mock_fetch: MagicMock, _mock_tenant: MagicMock
) -> None:
    """The poller sets the tenant contextvar once per thread, and a reclaim
    addressed to the wrong schema would renew nothing."""
    _run_license_reclaim()

    mock_fetch.return_value.assert_called_once_with(tenant_id="tenant_1")
