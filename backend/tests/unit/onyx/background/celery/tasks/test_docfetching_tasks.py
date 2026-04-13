import importlib
import logging
import sys
import types
from types import SimpleNamespace

import pytest

from onyx.background.celery.tasks.models import IndexingWatchdogTerminalStatus
from onyx.background.celery.tasks.models import SimpleJobResult
from onyx.db.enums import IndexingStatus


class _FakeSessionContext:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


class _FakeLogBuilder:
    def build(self, msg: str, **_: object) -> str:
        return msg


def _build_attempt(status: IndexingStatus) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        is_finished=lambda: status.is_terminal(),
    )


@pytest.fixture
def docfetching_tasks_module(monkeypatch: pytest.MonkeyPatch):
    app_base = types.ModuleType("onyx.background.celery.apps.app_base")
    app_base.task_logger = logging.getLogger("docfetching-test")
    monkeypatch.setitem(sys.modules, "onyx.background.celery.apps.app_base", app_base)

    heartbeat = types.ModuleType("onyx.background.celery.tasks.docprocessing.heartbeat")

    def _start_heartbeat(*_args: object, **_kwargs: object) -> tuple[None, None]:
        return (None, None)

    def _stop_heartbeat(*_args: object, **_kwargs: object) -> None:
        return None

    heartbeat.start_heartbeat = _start_heartbeat
    heartbeat.stop_heartbeat = _stop_heartbeat
    monkeypatch.setitem(
        sys.modules,
        "onyx.background.celery.tasks.docprocessing.heartbeat",
        heartbeat,
    )

    docprocessing_tasks = types.ModuleType(
        "onyx.background.celery.tasks.docprocessing.tasks"
    )

    class _ConnectorIndexingLogBuilder:
        def __init__(self, ctx: object) -> None:
            self.ctx = ctx

        def build(self, msg: str, **_: object) -> str:
            return msg

    docprocessing_tasks.ConnectorIndexingLogBuilder = _ConnectorIndexingLogBuilder
    monkeypatch.setitem(
        sys.modules,
        "onyx.background.celery.tasks.docprocessing.tasks",
        docprocessing_tasks,
    )

    docprocessing_utils = types.ModuleType(
        "onyx.background.celery.tasks.docprocessing.utils"
    )

    class _IndexingCallback:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

    docprocessing_utils.IndexingCallback = _IndexingCallback
    monkeypatch.setitem(
        sys.modules,
        "onyx.background.celery.tasks.docprocessing.utils",
        docprocessing_utils,
    )

    run_docfetching = types.ModuleType("onyx.background.indexing.run_docfetching")

    def _run_docfetching_entrypoint(*_args: object, **_kwargs: object) -> None:
        return None

    run_docfetching.run_docfetching_entrypoint = _run_docfetching_entrypoint
    monkeypatch.setitem(
        sys.modules,
        "onyx.background.indexing.run_docfetching",
        run_docfetching,
    )

    redis_connector = types.ModuleType("onyx.redis.redis_connector")

    class _RedisConnector:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.delete = SimpleNamespace(fenced=False, fence_key="delete-fence")
            self.stop = SimpleNamespace(fenced=False, fence_key="stop-fence")

    redis_connector.RedisConnector = _RedisConnector
    monkeypatch.setitem(sys.modules, "onyx.redis.redis_connector", redis_connector)

    monkeypatch.delitem(
        sys.modules,
        "onyx.background.celery.tasks.docfetching.tasks",
        raising=False,
    )

    return importlib.import_module("onyx.background.celery.tasks.docfetching.tasks")


def test_wait_for_index_attempt_completion_retries_until_terminal(
    monkeypatch: pytest.MonkeyPatch,
    docfetching_tasks_module,
) -> None:
    attempts: list[Exception | SimpleNamespace] = [
        RuntimeError("transient lookup error"),
        _build_attempt(IndexingStatus.IN_PROGRESS),
        _build_attempt(IndexingStatus.SUCCESS),
    ]
    sleep_calls: list[int] = []

    def fake_get_index_attempt(*_args: object, **_kwargs: object) -> SimpleNamespace:
        value = attempts.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(
        docfetching_tasks_module,
        "get_session_with_current_tenant",
        lambda: _FakeSessionContext(),
    )
    monkeypatch.setattr(
        docfetching_tasks_module,
        "get_index_attempt",
        fake_get_index_attempt,
    )
    monkeypatch.setattr(
        docfetching_tasks_module,
        "sleep",
        lambda seconds: sleep_calls.append(seconds),
    )

    docfetching_tasks_module._wait_for_index_attempt_completion(
        index_attempt_id=17,
        log_builder=_FakeLogBuilder(),
        poll_interval=7,
    )

    assert attempts == []
    assert sleep_calls == [7, 7, 7]


def test_should_wait_for_docprocessing_completion_enabled_on_success(
    monkeypatch: pytest.MonkeyPatch,
    docfetching_tasks_module,
) -> None:
    result = SimpleJobResult()
    result.status = IndexingWatchdogTerminalStatus.SUCCEEDED
    monkeypatch.setattr(docfetching_tasks_module, "CONSERVATIVE_INDEXING", True)
    assert (
        docfetching_tasks_module._should_wait_for_docprocessing_completion(result)
        is True
    )


def test_should_wait_for_docprocessing_completion_disabled_by_env(
    monkeypatch: pytest.MonkeyPatch,
    docfetching_tasks_module,
) -> None:
    result = SimpleJobResult()
    result.status = IndexingWatchdogTerminalStatus.SUCCEEDED
    monkeypatch.setattr(docfetching_tasks_module, "CONSERVATIVE_INDEXING", False)
    assert (
        docfetching_tasks_module._should_wait_for_docprocessing_completion(result)
        is False
    )


def test_should_wait_for_docprocessing_completion_skips_failed_fetch(
    monkeypatch: pytest.MonkeyPatch,
    docfetching_tasks_module,
) -> None:
    result = SimpleJobResult()
    result.status = IndexingWatchdogTerminalStatus.CONNECTOR_EXCEPTIONED
    result.exit_code = 255
    result.exception_str = "fetch failed"
    monkeypatch.setattr(docfetching_tasks_module, "CONSERVATIVE_INDEXING", True)
    assert (
        docfetching_tasks_module._should_wait_for_docprocessing_completion(result)
        is False
    )
