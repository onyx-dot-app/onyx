"""A chat retention chain carries the limit it started with. Once the limit is
cleared, the next batch must delete nothing and release the chain marker."""

from unittest.mock import MagicMock, patch

from ee.onyx.background.celery.tasks.ttl_management import tasks as ttl_tasks
from onyx.server.settings.models import Settings

_TASKS: str = "ee.onyx.background.celery.tasks.ttl_management.tasks"


def _run_batch(current_limit_days: int | None) -> tuple[MagicMock, MagicMock]:
    """Runs one batch of a chain that started with a 30 day limit. Returns the
    session lookup and marker release mocks."""
    redis_client: MagicMock = MagicMock()
    redis_client.eval.return_value = 1
    with (
        patch(f"{_TASKS}.get_redis_client", return_value=redis_client),
        patch(
            f"{_TASKS}.load_settings",
            return_value=Settings(maximum_chat_retention_days=current_limit_days),
        ),
        patch(f"{_TASKS}.get_session_with_current_tenant"),
        patch(f"{_TASKS}.get_chat_sessions_older_than", return_value=[]) as lookup,
        patch(f"{_TASKS}._release_chain_if_owned") as release,
    ):
        run_batch = ttl_tasks.perform_ttl_management_task.run
        run_batch(30, "token", tenant_id="public")  # ty: ignore[invalid-argument-type]
    return lookup, release


def test_a_cleared_limit_ends_the_chain_before_any_delete() -> None:
    lookup, release = _run_batch(current_limit_days=None)

    lookup.assert_not_called()
    release.assert_called_once()


def test_a_kept_limit_lets_the_batch_run() -> None:
    lookup, _ = _run_batch(current_limit_days=30)

    lookup.assert_called_once()
