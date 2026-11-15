"""Celery worker logging must reach the onyx log files (the only logs the admin
log export collects on Kubernetes): task_logger and root-logger lines land in
them once each, and setup_logger lines are not written twice via the root."""

import logging
import sys
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace

import pytest
from celery.app import trace
from celery.worker import strategy

import onyx.utils.logger as logger_module
from onyx.background.celery.apps import app_base, task_formatters
from onyx.background.celery.apps.task_formatters import (
    CeleryTaskColoredFormatter,
    CeleryTaskPlainFormatter,
)
from onyx.utils.logger import THIRD_PARTY_CAPPED_LOGGER_NAMES, setup_logger

_MODULE_LOGGER_NAME = "test_celery_task_logger_file_handlers.module"


@pytest.fixture
def log_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Path, None, None]:
    """Route the onyx file handlers to tmp_path/log and restore every logger
    on_setup_logging and setup_logger touch."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(logger_module, "LOG_TO_FILE", True)
    monkeypatch.setattr(logger_module, "DEV_LOGGING_ENABLED", True)
    monkeypatch.setattr(logger_module, "_truncated_log_files", set())
    monkeypatch.setattr(logger_module, "is_running_in_container", lambda: False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.setattr(sys, "argv", ["celery", "-A", "app", "worker"])

    root = logging.getLogger()
    task = app_base.task_logger
    root_handlers_before = list(root.handlers)
    root_level_before = root.level
    task_handlers_before = list(task.handlers)
    task_level_before = task.level
    task_propagate_before = task.propagate
    celery_levels_before = {
        celery_logger: celery_logger.level
        for celery_logger in (strategy.logger, trace.logger)
    }
    third_party_levels_before = {
        name: logging.getLogger(name).level for name in THIRD_PARTY_CAPPED_LOGGER_NAMES
    }
    capped_flag_before = logger_module._third_party_log_levels_capped
    cap_applied_before = dict(logger_module._cap_applied_levels)

    yield tmp_path / "log"

    module_logger = logging.getLogger(_MODULE_LOGGER_NAME)
    for logger in (root, task, module_logger):
        for handler in logger.handlers:
            handler.close()
    module_logger.handlers = []
    root.handlers = root_handlers_before
    root.setLevel(root_level_before)
    task.handlers = task_handlers_before
    task.setLevel(task_level_before)
    task.propagate = task_propagate_before
    for celery_logger, level in celery_levels_before.items():
        celery_logger.setLevel(level)
    for name, level in third_party_levels_before.items():
        logging.getLogger(name).setLevel(level)
    logger_module._third_party_log_levels_capped = capped_flag_before
    logger_module._cap_applied_levels.clear()
    logger_module._cap_applied_levels.update(cap_applied_before)


def _setup_celery_logging() -> None:
    app_base.on_setup_logging(
        loglevel=logging.INFO, logfile=None, format="", colorize=False
    )


def _info_log(log_dir: Path) -> str:
    for handler in logging.getLogger().handlers + app_base.task_logger.handlers:
        handler.flush()
    return (log_dir / f"{logger_module.LOG_FILE_NAME}_info.log").read_text()


def test_task_and_root_lines_reach_log_files_once(log_dir: Path) -> None:
    _setup_celery_logging()
    # A second setup must replace the handlers, not stack more of them.
    _setup_celery_logging()

    app_base.task_logger.info("task-logger-line")
    logging.getLogger("celery.app.trace").error("celery-trace-line")

    content = _info_log(log_dir)
    assert content.count("task-logger-line") == 1
    assert content.count("celery-trace-line") == 1


def test_setup_logger_lines_not_duplicated_by_root(log_dir: Path) -> None:
    _setup_celery_logging()
    module_logger = setup_logger(_MODULE_LOGGER_NAME)

    module_logger.info("module-logger-line")

    for handler in logging.getLogger(_MODULE_LOGGER_NAME).handlers:
        handler.flush()
    assert _info_log(log_dir).count("module-logger-line") == 1


@pytest.mark.parametrize(
    "formatter_cls", [CeleryTaskPlainFormatter, CeleryTaskColoredFormatter]
)
def test_task_prefix_added_once_per_handler(
    formatter_cls: type[logging.Formatter], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_task = SimpleNamespace(
        name="docprocessing_task", request=SimpleNamespace(id="abc")
    )
    monkeypatch.setattr(task_formatters, "current_task", fake_task)
    formatter = formatter_cls("%(message)s")
    record = logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="batch %s done",
        args=(7,),
        exc_info=None,
    )

    # One record formatted by several handlers, as with stdout plus file handlers.
    outputs = [formatter.format(record) for _ in range(3)]

    for output in outputs:
        assert output.count("[docprocessing_task(abc)]") == 1
        assert "batch 7 done" in output
    assert record.msg == "batch %s done"


def test_dev_log_files_truncated_once_per_process(log_dir: Path) -> None:
    log_dir.mkdir()
    info_file = log_dir / f"{logger_module.LOG_FILE_NAME}_info.log"
    info_file.write_text("stale-line\n")

    _setup_celery_logging()
    logging.getLogger("celery.app.trace").error("after-first-setup-line")
    # The second setup adds file handlers again; it must not wipe this line.
    _setup_celery_logging()

    content = _info_log(log_dir)
    assert "stale-line" not in content
    assert "after-first-setup-line" in content
