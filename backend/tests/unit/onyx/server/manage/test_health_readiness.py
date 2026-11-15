"""Unit tests for the /health/ready readiness and /health liveness endpoints."""

import asyncio
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.responses import JSONResponse

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.server.manage import get_state


@pytest.fixture(autouse=True)
def reset_saturation_latch() -> Iterator[None]:
    """The latches are module state, so clear them around every test."""
    get_state._SATURATED_SINCE = None
    get_state._REPORTED_NOT_READY = False
    yield
    get_state._SATURATED_SINCE = None
    get_state._REPORTED_NOT_READY = False


def _limiter(borrowed: float, total: float, waiting: int) -> MagicMock:
    limiter = MagicMock()
    limiter.statistics.return_value = MagicMock(
        borrowed_tokens=borrowed,
        total_tokens=total,
        tasks_waiting=waiting,
    )
    return limiter


def _readiness(
    borrowed: float, total: float, waiting: int, now: float
) -> get_state.StatusResponse[dict[str, float]] | JSONResponse:
    """Run the readiness handler against a fixed pool state and clock."""
    with (
        patch.object(
            get_state.to_thread,
            "current_default_thread_limiter",
            return_value=_limiter(borrowed, total, waiting),
        ),
        patch.object(get_state.time, "monotonic", return_value=now),
    ):
        return asyncio.run(get_state.readiness())


def _ready(
    borrowed: float, total: float, waiting: int, now: float
) -> get_state.StatusResponse[dict[str, float]]:
    """Run the readiness handler and assert it reported ready."""
    response = _readiness(borrowed, total, waiting, now)
    assert not isinstance(response, JSONResponse)
    return response


def test_idle_pool_is_ready() -> None:
    response = _ready(borrowed=0, total=40, waiting=0, now=100.0)

    assert response.success is True
    assert response.data == {
        "threadpool_total_tokens": 40,
        "threadpool_borrowed_tokens": 0,
        "threadpool_tasks_waiting": 0,
    }


def test_fully_borrowed_pool_with_empty_queue_is_ready() -> None:
    """Every thread busy is normal. Only a backed-up queue means saturation."""
    response = _ready(borrowed=40, total=40, waiting=0, now=100.0)

    assert response.success is True
    assert get_state._SATURATED_SINCE is None


def test_brief_saturation_does_not_flip_readiness() -> None:
    """A single saturated sample starts the timer but still reports ready."""
    response = _ready(borrowed=40, total=40, waiting=5, now=100.0)

    assert response.success is True
    assert get_state._SATURATED_SINCE == 100.0


def test_sustained_saturation_reports_not_ready() -> None:
    _readiness(borrowed=40, total=40, waiting=5, now=100.0)

    response = _readiness(
        borrowed=40,
        total=40,
        waiting=5,
        now=100.0 + get_state._UNREADY_AFTER_SECONDS,
    )

    # Returned, not raised, so the global handler does not log every probe.
    assert isinstance(response, JSONResponse)
    assert response.status_code == 503
    assert OnyxErrorCode.SERVICE_UNAVAILABLE.code in bytes(response.body).decode()


def test_recovery_between_samples_restarts_the_timer() -> None:
    """A healthy sample clears the latch, so the grace window starts over."""
    _readiness(borrowed=40, total=40, waiting=5, now=100.0)
    _readiness(borrowed=10, total=40, waiting=0, now=105.0)
    assert get_state._SATURATED_SINCE is None

    # Long past the original window, but this is a fresh saturation streak.
    response = _ready(borrowed=40, total=40, waiting=5, now=200.0)

    assert response.success is True
    assert get_state._SATURATED_SINCE == 200.0


def test_not_ready_is_logged_once_per_streak() -> None:
    """Probes are frequent, so only readiness changes may write to the log."""
    with patch.object(get_state, "logger") as mock_logger:
        _readiness(borrowed=40, total=40, waiting=5, now=100.0)
        for offset in range(3):
            _readiness(
                borrowed=40,
                total=40,
                waiting=5,
                now=100.0 + get_state._UNREADY_AFTER_SECONDS + offset,
            )

        assert mock_logger.warning.call_count == 1

        _readiness(borrowed=0, total=40, waiting=0, now=200.0)
        _readiness(borrowed=0, total=40, waiting=0, now=201.0)

        assert mock_logger.notice.call_count == 1


def test_liveness_stays_up_while_saturated() -> None:
    """Liveness must never fail on load, or saturation restarts every replica."""
    _readiness(borrowed=40, total=40, waiting=5, now=100.0)
    _readiness(
        borrowed=40,
        total=40,
        waiting=5,
        now=100.0 + get_state._UNREADY_AFTER_SECONDS,
    )

    response = asyncio.run(get_state.healthcheck())

    assert response.success is True
