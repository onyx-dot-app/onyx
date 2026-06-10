"""
Unit tests for the LOG_LEVEL env var override in Celery's ``setup_logging``
handler.

Verifies the precedence rule in
``onyx.background.celery.apps.app_base.on_setup_logging``:
    explicit --loglevel CLI arg > LOG_LEVEL env var > Celery default.
"""

import logging
import sys
from collections.abc import Generator

import pytest

from onyx.background.celery.apps import app_base
from onyx.utils.logger import NOISY_THIRD_PARTY_LOGGER_PREFIXES

NOISY_DEPENDENCY_CHILD_LOGGER_NAMES = (
    "googleapiclient.discovery",
    "googleapiclient.discovery_cache",
    "googleapiclient.http",
    "httpcore.connection",
    "httpcore.http11",
    "httpx",
    "kubernetes.client.rest",
    "slack_sdk.web.base_client",
    "urllib3.connectionpool",
)


class CapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _matches_noisy_dependency_prefix(logger_name: str) -> bool:
    return logger_name in NOISY_THIRD_PARTY_LOGGER_PREFIXES or any(
        logger_name.startswith(f"{logger_prefix}.")
        for logger_prefix in NOISY_THIRD_PARTY_LOGGER_PREFIXES
    )


def _noisy_dependency_loggers() -> dict[str, logging.Logger]:
    loggers = {
        logger_prefix: logging.getLogger(logger_prefix)
        for logger_prefix in NOISY_THIRD_PARTY_LOGGER_PREFIXES
    }

    for logger_name, candidate_logger in list(
        logging.Logger.manager.loggerDict.items()
    ):
        if not isinstance(candidate_logger, logging.Logger):
            continue
        if _matches_noisy_dependency_prefix(logger_name):
            loggers[logger_name] = candidate_logger

    return loggers


@pytest.fixture
def _snapshot_loggers() -> Generator[None, None, None]:
    """on_setup_logging mutates the root logger and the Celery task logger.

    Snapshot and restore both so tests don't bleed into each other or the rest
    of the suite.
    """
    root = logging.getLogger()
    task = app_base.task_logger

    root_handlers_before = list(root.handlers)
    root_level_before = root.level
    task_handlers_before = list(task.handlers)
    task_level_before = task.level
    task_propagate_before = task.propagate
    noisy_logger_levels_before = {
        logger_name: logger.level
        for logger_name, logger in _noisy_dependency_loggers().items()
    }

    yield

    root.handlers = root_handlers_before
    root.setLevel(root_level_before)
    task.handlers = task_handlers_before
    task.setLevel(task_level_before)
    task.propagate = task_propagate_before

    for logger_name, logger in _noisy_dependency_loggers().items():
        logger.setLevel(noisy_logger_levels_before.get(logger_name, logging.NOTSET))


def _clean_argv(monkeypatch: pytest.MonkeyPatch, *extra: str) -> None:
    """Replaces sys.argv with a celery-like invocation (plus any extra args).

    Strips pytest's own argv so the --loglevel detector doesn't see e.g. ``-v``
    from pytest's command line as a false short-flag match.
    """
    monkeypatch.setattr(sys, "argv", ["celery", "-A", "app", "worker", *extra])


def _dependency_loggers() -> list[logging.Logger]:
    return [
        logging.getLogger(logger_name)
        for logger_name in NOISY_DEPENDENCY_CHILD_LOGGER_NAMES
    ]


def test_env_unset_cli_not_passed_falls_back_to_celery_default(
    _snapshot_loggers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    _clean_argv(monkeypatch)

    # Celery would pass its own default here when --loglevel is absent.
    app_base.on_setup_logging(
        loglevel=logging.WARNING,
        logfile=None,
        format="",
        colorize=False,
    )

    assert logging.getLogger().level == logging.WARNING
    assert app_base.task_logger.level == logging.WARNING


def test_env_set_cli_not_passed_env_wins(
    _snapshot_loggers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    _clean_argv(monkeypatch)

    app_base.on_setup_logging(
        loglevel=logging.WARNING,  # Celery default; should be ignored
        logfile=None,
        format="",
        colorize=False,
    )

    assert logging.getLogger().level == logging.DEBUG
    assert app_base.task_logger.level == logging.DEBUG


def test_env_empty_string_falls_back_to_info(
    _snapshot_loggers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "")
    _clean_argv(monkeypatch)

    app_base.on_setup_logging(
        loglevel=logging.WARNING,  # Celery default; should be ignored
        logfile=None,
        format="",
        colorize=False,
    )

    assert logging.getLogger().level == logging.INFO
    assert app_base.task_logger.level == logging.INFO


def test_cli_long_form_wins_over_env(
    _snapshot_loggers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    _clean_argv(monkeypatch, "--loglevel=INFO")

    app_base.on_setup_logging(
        loglevel=logging.INFO,
        logfile=None,
        format="",
        colorize=False,
    )

    assert logging.getLogger().level == logging.INFO
    assert app_base.task_logger.level == logging.INFO


def test_cli_long_form_separate_token_wins_over_env(
    _snapshot_loggers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    _clean_argv(monkeypatch, "--loglevel", "WARNING")

    app_base.on_setup_logging(
        loglevel=logging.WARNING,
        logfile=None,
        format="",
        colorize=False,
    )

    assert logging.getLogger().level == logging.WARNING
    assert app_base.task_logger.level == logging.WARNING


def test_cli_short_form_wins_over_env(
    _snapshot_loggers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    _clean_argv(monkeypatch, "-l", "ERROR")

    app_base.on_setup_logging(
        loglevel=logging.ERROR,
        logfile=None,
        format="",
        colorize=False,
    )

    assert logging.getLogger().level == logging.ERROR
    assert app_base.task_logger.level == logging.ERROR


def test_env_loglevel_case_insensitive(
    _snapshot_loggers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "warning")
    _clean_argv(monkeypatch)

    app_base.on_setup_logging(
        loglevel=logging.DEBUG,
        logfile=None,
        format="",
        colorize=False,
    )

    assert logging.getLogger().level == logging.WARNING
    assert app_base.task_logger.level == logging.WARNING


def test_noisy_dependency_loggers_suppress_debug_and_info_with_debug_root(
    _snapshot_loggers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    _clean_argv(monkeypatch)

    dependency_loggers = _dependency_loggers()
    for dependency_logger in dependency_loggers:
        dependency_logger.setLevel(logging.DEBUG)

    app_base.on_setup_logging(
        loglevel=logging.WARNING,
        logfile=None,
        format="",
        colorize=False,
    )

    assert logging.getLogger().level == logging.DEBUG
    assert app_base.task_logger.level == logging.DEBUG
    capture_handler = CapturingHandler()
    logging.getLogger().addHandler(capture_handler)

    for dependency_logger in dependency_loggers:
        dependency_logger.debug("debug should be hidden")
        dependency_logger.info("info should be hidden")
        dependency_logger.warning("warning should be visible")

    dependency_records = [
        record
        for record in capture_handler.records
        if record.name in NOISY_DEPENDENCY_CHILD_LOGGER_NAMES
    ]
    assert {record.getMessage() for record in dependency_records} == {
        "warning should be visible"
    }
    assert {record.name for record in dependency_records} == set(
        NOISY_DEPENDENCY_CHILD_LOGGER_NAMES
    )


def test_noisy_dependency_loggers_do_not_loosen_error_root(
    _snapshot_loggers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    _clean_argv(monkeypatch)

    dependency_loggers = _dependency_loggers()
    for dependency_logger in dependency_loggers:
        dependency_logger.setLevel(logging.DEBUG)

    app_base.on_setup_logging(
        loglevel=logging.WARNING,
        logfile=None,
        format="",
        colorize=False,
    )

    assert logging.getLogger().level == logging.ERROR
    assert app_base.task_logger.level == logging.ERROR
    capture_handler = CapturingHandler()
    logging.getLogger().addHandler(capture_handler)

    for dependency_logger in dependency_loggers:
        dependency_logger.warning("warning should be hidden")
        dependency_logger.error("error should be visible")

    dependency_records = [
        record
        for record in capture_handler.records
        if record.name in NOISY_DEPENDENCY_CHILD_LOGGER_NAMES
    ]
    assert {record.getMessage() for record in dependency_records} == {
        "error should be visible"
    }
    assert {record.name for record in dependency_records} == set(
        NOISY_DEPENDENCY_CHILD_LOGGER_NAMES
    )


# Direct tests of the resolver helper so we can assert on the human-readable
# source string without fighting on_setup_logging clearing root_logger.handlers
# (which kills pytest's caplog handler).


def test_resolve_unrecognized_env_loglevel_falls_back_to_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LOG_LEVEL=WARN (common typo for WARNING) should fall back to INFO and
    surface that fact in the source string so the boot log makes the silent
    fallback discoverable.
    """
    monkeypatch.setenv("LOG_LEVEL", "WARN")
    _clean_argv(monkeypatch)

    level, source = app_base._resolve_effective_loglevel(cli_loglevel=logging.DEBUG)

    assert level == logging.INFO
    assert "'WARN'" in source
    assert "unrecognized" in source
    assert "INFO" in source


def test_resolve_garbage_env_loglevel_falls_back_to_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "INVALID")
    _clean_argv(monkeypatch)

    level, source = app_base._resolve_effective_loglevel(cli_loglevel=logging.DEBUG)

    assert level == logging.INFO
    assert "'INVALID'" in source
    assert "unrecognized" in source


def test_resolve_valid_env_loglevel_has_clean_source_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    _clean_argv(monkeypatch)

    level, source = app_base._resolve_effective_loglevel(cli_loglevel=logging.WARNING)

    assert level == logging.DEBUG
    assert "unrecognized" not in source
    assert "'DEBUG'" in source


def test_resolve_cli_explicit_wins_source_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    _clean_argv(monkeypatch, "--loglevel=ERROR")

    level, source = app_base._resolve_effective_loglevel(cli_loglevel=logging.ERROR)

    assert level == logging.ERROR
    assert "CLI" in source
