"""A watchdog that raises after it spawned the docfetching process must stop that
process. Its thread takes the next task at once, so a left-behind process stacks
up with the next one (for example, every queued task after a database reset)."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from onyx.background.celery.tasks.docfetching import tasks
from onyx.configs.constants import CELERY_INDEXING_WATCHDOG_SIGTERM_GRACE_SECONDS


@contextmanager
def _session() -> Iterator[MagicMock]:
    yield MagicMock()


def test_a_watchdog_exception_terminates_the_spawned_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = MagicMock()
    job.process.is_alive.return_value = True
    client = MagicMock()
    client.submit.return_value = job
    monkeypatch.setattr(tasks, "SimpleJobClient", lambda: client)
    monkeypatch.setattr(tasks, "get_session_with_current_tenant", _session)
    # The attempt is gone, as after a database reset.
    monkeypatch.setattr(tasks, "get_index_attempt", lambda *_, **__: None)

    with pytest.raises(RuntimeError, match="Index attempt not found"):
        tasks.docfetching_proxy_task.run(
            index_attempt_id=10,  # ty: ignore[invalid-argument-type]
            cc_pair_id=1,  # ty: ignore[invalid-argument-type]
            search_settings_id=1,  # ty: ignore[invalid-argument-type]
            tenant_id="public",  # ty: ignore[invalid-argument-type]
        )

    job.terminate_and_wait.assert_called_once_with(
        CELERY_INDEXING_WATCHDOG_SIGTERM_GRACE_SECONDS
    )
