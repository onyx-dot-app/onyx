import logging
import os
from collections.abc import MutableMapping
from typing import Any

from shared_configs.configs import LOG_LEVEL


class IndexAttemptSingleton:
    """Used to tell if this process is an indexing job, and if so what is the
    unique identifier for this indexing attempt. For things like the API server,
    main background job (scheduler), etc. this will not be used."""

    _INDEX_ATTEMPT_ID: None | int = None

    @classmethod
    def get_index_attempt_id(cls) -> None | int:
        return cls._INDEX_ATTEMPT_ID

    @classmethod
    def set_index_attempt_id(cls, index_attempt_id: int) -> None:
        cls._INDEX_ATTEMPT_ID = index_attempt_id


def get_log_level_from_str(log_level_str: str = LOG_LEVEL) -> int:
    log_level_dict = {
        "CRITICAL": logging.CRITICAL,
        "ERROR": logging.ERROR,
        "WARNING": logging.WARNING,
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG,
        "NOTSET": logging.NOTSET,
    }

    return log_level_dict.get(log_level_str.upper(), logging.INFO)


class _IndexAttemptLoggingAdapter(logging.LoggerAdapter):
    """This is used to globally add the index attempt id to all log messages
    during indexing by workers. This is done so that the logs can be filtered
    by index attempt ID to get a better idea of what happened during a specific
    indexing attempt. If the index attempt ID is not set, then this adapter
    is a no-op."""

    def process(
        self, msg: str, kwargs: MutableMapping[str, Any]
    ) -> tuple[str, MutableMapping[str, Any]]:
        attempt_id = IndexAttemptSingleton.get_index_attempt_id()
        if attempt_id is None:
            return msg, kwargs

        return f"[Attempt ID: {attempt_id}] {msg}", kwargs


def setup_logger(
    name: str = __name__,
    log_level: int = get_log_level_from_str(),
    logfile_name: str | None = None,
) -> logging.LoggerAdapter:
    logger = logging.getLogger(name)

    # If the logger already has handlers, assume it was already configured and return it.
    if logger.handlers:
        return _IndexAttemptLoggingAdapter(logger)

    logger.setLevel(log_level)

    formatter = logging.Formatter(
        "%(asctime)s %(filename)20s%(lineno)4s : %(message)s",
        datefmt="%m/%d/%Y %I:%M:%S %p",
    )

    handler = logging.StreamHandler()
    handler.setLevel(log_level)
    handler.setFormatter(formatter)

    logger.addHandler(handler)

    if logfile_name:
        is_containerized = os.path.exists("/.dockerenv")
        file_name_template = (
            "/var/log/{name}.log" if is_containerized else "./log/{name}.log"
        )
        file_handler = logging.FileHandler(file_name_template.format(name=logfile_name))
        logger.addHandler(file_handler)

    return _IndexAttemptLoggingAdapter(logger)
