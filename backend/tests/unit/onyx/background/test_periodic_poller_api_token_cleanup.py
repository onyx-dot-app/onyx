from unittest.mock import MagicMock, patch

from onyx.background.celery.apps.primary import celery_app
from onyx.background.periodic_poller import (
    _build_periodic_tasks,
    _run_api_token_cleanup,
)
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


def test_api_token_cleanup_always_runs() -> None:
    assert "api-token-cleanup" in [t.name for t in _build_periodic_tasks()]


_TASKS_MODULE = "onyx.background.celery.tasks.api_tokens.tasks"


@patch(f"{_TASKS_MODULE}.delete_orphaned_api_tokens", return_value=0)
@patch(f"{_TASKS_MODULE}.get_session_with_current_tenant")
def test_api_token_cleanup_keeps_poller_tenant_context(
    _mock_tenant_session: MagicMock,
    mock_delete: MagicMock,
) -> None:
    celery_app.set_current()
    token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_1")
    try:
        _run_api_token_cleanup()
        assert CURRENT_TENANT_ID_CONTEXTVAR.get() == "tenant_1"
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    mock_delete.assert_called_once()
