"""Celery worker logging must reach the onyx log files (the only logs the admin
log export collects on Kubernetes): task_logger and root-logger lines land in
them once each, and setup_logger lines are not written twice via the root."""

import logging
import sys
from collections.abc import Generator
from pathlib import Path

import pytest

import onyx.utils.logger as logger_module
from onyx.background.celery.apps import app_base
from onyx.utils.logger import setup_logger

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
