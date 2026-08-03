import logging
from collections.abc import Generator

import pytest

import onyx.utils.logger as logger_module
from onyx.utils.logger import (
    THIRD_PARTY_CAPPED_LOGGER_NAMES,
    cap_third_party_log_levels,
    remove_litellm_native_log_handlers,
)


@pytest.fixture(autouse=True)
def _restore_third_party_logger_levels() -> Generator[None, None, None]:
    """Snapshot and restore the global logging state these tests mutate,
    including the module-level already-capped flag that setup_logger consults —
    leaking it True would make later tests skip capping based on test order."""
    saved = {
        name: logging.getLogger(name).level for name in THIRD_PARTY_CAPPED_LOGGER_NAMES
    }
    saved_capped_flag = logger_module._third_party_log_levels_capped
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)
    logger_module._third_party_log_levels_capped = saved_capped_flag


def test_third_party_loggers_capped_at_info_when_app_is_debug() -> None:
    for name in THIRD_PARTY_CAPPED_LOGGER_NAMES:
        logging.getLogger(name).setLevel(logging.NOTSET)

    cap_third_party_log_levels(
        app_log_level=logging.DEBUG, allow_third_party_debug=False
    )

    for name in THIRD_PARTY_CAPPED_LOGGER_NAMES:
        assert logging.getLogger(name).getEffectiveLevel() == logging.INFO, name


def test_escape_hatch_lets_third_party_loggers_run_at_debug() -> None:
    for name in THIRD_PARTY_CAPPED_LOGGER_NAMES:
        logging.getLogger(name).setLevel(logging.NOTSET)

    cap_third_party_log_levels(
        app_log_level=logging.DEBUG, allow_third_party_debug=True
    )

    for name in THIRD_PARTY_CAPPED_LOGGER_NAMES:
        assert logging.getLogger(name).getEffectiveLevel() == logging.DEBUG, name


def test_escape_hatch_never_lowers_an_already_raised_level() -> None:
    # An explicitly suppressed logger (e.g. httpx pinned to WARNING) must stay
    # suppressed even when LOG_THIRD_PARTY_DEBUG opts back into DEBUG output.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cap_third_party_log_levels(
        app_log_level=logging.DEBUG, allow_third_party_debug=True
    )

    assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING


def test_cap_follows_app_level_when_app_is_stricter_than_info() -> None:
    for name in THIRD_PARTY_CAPPED_LOGGER_NAMES:
        logging.getLogger(name).setLevel(logging.NOTSET)

    cap_third_party_log_levels(
        app_log_level=logging.WARNING, allow_third_party_debug=False
    )

    for name in THIRD_PARTY_CAPPED_LOGGER_NAMES:
        assert logging.getLogger(name).getEffectiveLevel() == logging.WARNING, name


def test_cap_never_lowers_an_already_raised_level() -> None:
    # e.g. litellm itself sets httpx to WARNING at import time
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cap_third_party_log_levels(
        app_log_level=logging.DEBUG, allow_third_party_debug=False
    )

    assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING


def test_remove_litellm_native_log_handlers_leaves_single_emission_path() -> None:
    litellm_logger = logging.getLogger("LiteLLM")
    saved_handlers = litellm_logger.handlers[:]
    saved_propagate = litellm_logger.propagate
    try:
        # Simulate litellm's import-time handler attachment.
        litellm_logger.addHandler(logging.StreamHandler())
        litellm_logger.propagate = True

        remove_litellm_native_log_handlers()

        assert litellm_logger.handlers == []
        assert litellm_logger.propagate is True
    finally:
        litellm_logger.handlers = saved_handlers
        litellm_logger.propagate = saved_propagate
