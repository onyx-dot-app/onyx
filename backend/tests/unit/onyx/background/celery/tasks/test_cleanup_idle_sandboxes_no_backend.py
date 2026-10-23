from unittest.mock import MagicMock, patch

import pytest

from onyx.background.celery.tasks.build.tasks import cleanup_idle_sandboxes_task

TASKS_MODULE = "onyx.background.celery.tasks.build.tasks"
TENANT_ID = "public"


def _redis_with_free_lock() -> MagicMock:
    redis_client = MagicMock()
    lock = MagicMock()
    lock.acquire.return_value = True
    lock.owned.return_value = False
    redis_client.lock.return_value = lock
    return redis_client


def _run_task(
    running_sandboxes: list[MagicMock], manager_error: Exception
) -> MagicMock:
    get_manager = MagicMock(side_effect=manager_error)
    with (
        patch(f"{TASKS_MODULE}.get_redis_client", return_value=_redis_with_free_lock()),
        patch(f"{TASKS_MODULE}.get_session_with_current_tenant") as session_ctx,
        patch(f"{TASKS_MODULE}.get_running_sandboxes", return_value=running_sandboxes),
        patch(f"{TASKS_MODULE}.maybe_mark_tenant_active"),
        patch(f"{TASKS_MODULE}.get_sandbox_manager", get_manager),
    ):
        session_ctx.return_value.__enter__.return_value = MagicMock()
        cleanup_idle_sandboxes_task.run(tenant_id=TENANT_ID)  # ty: ignore[invalid-argument-type]
    return get_manager


def test_no_running_sandboxes_does_not_build_sandbox_manager() -> None:
    """Deployments without a sandbox backend (no Craft) must not fail the sweep.

    The sweep builds the sandbox manager only when it has sandboxes to sweep. A
    Docker Compose deployment has no Kubernetes configuration, so building the
    manager first made the task raise on every beat tick.
    """
    get_manager = _run_task(
        running_sandboxes=[], manager_error=RuntimeError("no kube config")
    )

    get_manager.assert_not_called()


def test_running_sandboxes_still_surface_sandbox_manager_errors() -> None:
    """With sandboxes to sweep, a broken sandbox backend is still an error."""
    with pytest.raises(RuntimeError, match="no kube config"):
        _run_task(
            running_sandboxes=[MagicMock()],
            manager_error=RuntimeError("no kube config"),
        )
