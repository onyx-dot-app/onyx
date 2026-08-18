"""Unit tests for the /health readiness and /health/live liveness endpoints."""

import asyncio
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage import get_state


@pytest.fixture(autouse=True)
def reset_saturation_latch() -> Iterator[None]:
    """The latch is module state, so clear it around every test."""
    get_state._SATURATED_SINCE = None
    yield
    get_state._SATURATED_SINCE = None


def _limiter(borrowed: float, total: float, waiting: int) -> MagicMock:
    limiter = MagicMock()
    limiter.statistics.return_value = MagicMock(
        borrowed_tokens=borrowed,
        total_tokens=total,
        tasks_waiting=waiting,
    )
    return limiter


def _healthcheck(
    borrowed: float, total: float, waiting: int, now: float
) -> get_state.StatusResponse[dict[str, float]]:
    """Run the readiness handler against a fixed pool state and clock."""
    with (
        patch.object(
            get_state.to_thread,
            "current_default_thread_limiter",
            return_value=_limiter(borrowed, total, waiting),
        ),
        patch.object(get_state.time, "monotonic", return_value=now),
    ):
        return asyncio.run(get_state.healthcheck())


def test_idle_pool_is_ready() -> None:
    response = _healthcheck(borrowed=0, total=40, waiting=0, now=100.0)

    assert response.success is True
    assert response.data == {
        "threadpool_total_tokens": 40,
        "threadpool_borrowed_tokens": 0,
        "threadpool_tasks_waiting": 0,
    }


def test_fully_borrowed_pool_with_empty_queue_is_ready() -> None:
    """Every thread busy is normal. Only a backed-up queue means saturation."""
    response = _healthcheck(borrowed=40, total=40, waiting=0, now=100.0)

    assert response.success is True
    assert get_state._SATURATED_SINCE is None


def test_brief_saturation_does_not_flip_readiness() -> None:
    """A single saturated sample starts the timer but still reports ready."""
    response = _healthcheck(borrowed=40, total=40, waiting=5, now=100.0)

    assert response.success is True
    assert get_state._SATURATED_SINCE == 100.0


def test_sustained_saturation_reports_not_ready() -> None:
    _healthcheck(borrowed=40, total=40, waiting=5, now=100.0)

    with pytest.raises(OnyxError) as err:
        _healthcheck(
            borrowed=40,
            total=40,
            waiting=5,
            now=100.0 + get_state._UNREADY_AFTER_SECONDS,
        )

    assert err.value.error_code == OnyxErrorCode.SERVICE_UNAVAILABLE
    assert err.value.status_code == 503


def test_recovery_between_samples_restarts_the_timer() -> None:
    """A healthy sample clears the latch, so the grace window starts over."""
    _healthcheck(borrowed=40, total=40, waiting=5, now=100.0)
    _healthcheck(borrowed=10, total=40, waiting=0, now=105.0)
    assert get_state._SATURATED_SINCE is None

    # Long past the original window, but this is a fresh saturation streak.
    response = _healthcheck(borrowed=40, total=40, waiting=5, now=200.0)

    assert response.success is True
    assert get_state._SATURATED_SINCE == 200.0


def test_liveness_stays_up_while_saturated() -> None:
    """Liveness must never fail on load, or saturation restarts every replica."""
    _healthcheck(borrowed=40, total=40, waiting=5, now=100.0)
    with pytest.raises(OnyxError):
        _healthcheck(
            borrowed=40,
            total=40,
            waiting=5,
            now=100.0 + get_state._UNREADY_AFTER_SECONDS,
        )

    response = asyncio.run(get_state.liveness())

    assert response.success is True
