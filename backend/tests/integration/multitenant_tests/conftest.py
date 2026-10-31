"""Hang diagnostics for the multi-tenant suite. Its api_server runs in the
pytest process, and a job that reaches timeout-minutes is cancelled before
pytest prints captured output. So the in-process logs, with LLM stream and
agent step timings, and repeated thread dumps go to files under backend/log,
which the workflow uploads when the job is cancelled."""

import faulthandler
import logging
from collections.abc import Generator
from pathlib import Path
from typing import TextIO

import pytest

_LOG_DIR = Path(__file__).resolve().parents[3] / "log"
_THREAD_DUMP_INTERVAL_S = 120
# Every onyx module logs through this one logger.
_ONYX_LOGGER = "onyx.utils.logger"


@pytest.fixture(scope="session", autouse=True)
def _in_process_log_file() -> Generator[None, None, None]:
    _LOG_DIR.mkdir(exist_ok=True)
    handler = logging.FileHandler(_LOG_DIR / "multitenant_in_process.log")
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(threadName)s %(name)s %(levelname)s %(message)s"
        )
    )
    # Debug reaches only this file: the stdout handler keeps its own level.
    onyx_logger = logging.getLogger(_ONYX_LOGGER)
    previous_level = onyx_logger.level
    onyx_logger.setLevel(logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(handler)
    yield
    root.removeHandler(handler)
    handler.close()
    onyx_logger.setLevel(previous_level)


@pytest.fixture(scope="session")
def _thread_dump_file() -> Generator[TextIO, None, None]:
    _LOG_DIR.mkdir(exist_ok=True)
    with open(_LOG_DIR / "multitenant_thread_dumps.log", "a") as dump_file:
        yield dump_file


@pytest.fixture(autouse=True)
def _dump_threads_while_hung(
    request: pytest.FixtureRequest, _thread_dump_file: TextIO
) -> Generator[None, None, None]:
    # Repeated dumps show whether a hung test is stuck in one place or moving.
    # This replaces pytest's faulthandler_timeout: faulthandler keeps one timer.
    _thread_dump_file.write(f"\n=== {request.node.nodeid}\n")
    _thread_dump_file.flush()
    faulthandler.dump_traceback_later(
        _THREAD_DUMP_INTERVAL_S, repeat=True, file=_thread_dump_file
    )
    yield
    faulthandler.cancel_dump_traceback_later()
