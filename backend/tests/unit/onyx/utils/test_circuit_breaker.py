import time

from onyx.utils.circuit_breaker import CircuitBreaker


def _age(breaker: CircuitBreaker, seconds: float) -> None:
    """Move the last failure into the past instead of sleeping."""
    breaker._last_failure_at -= seconds


def test_stays_closed_below_the_threshold() -> None:
    breaker = CircuitBreaker(failures_before_open=3)

    breaker.record_failure()
    breaker.record_failure()

    assert breaker.is_open is False


def test_opens_on_the_threshold_failure() -> None:
    breaker = CircuitBreaker(failures_before_open=3)

    for _ in range(3):
        breaker.record_failure()

    assert breaker.is_open is True


def test_a_success_among_failures_keeps_it_closed() -> None:
    """An isolated failure between healthy calls must not open the breaker."""
    breaker = CircuitBreaker(failures_before_open=3)

    for _ in range(10):
        breaker.record_failure()
        breaker.record_success()

    assert breaker.is_open is False


def test_closes_once_the_delay_passes() -> None:
    breaker = CircuitBreaker(failures_before_open=3, base_delay=60)

    for _ in range(3):
        breaker.record_failure()
    assert breaker.is_open is True

    _age(breaker, 61)

    assert breaker.is_open is False


def test_delay_doubles_per_failure_and_is_capped() -> None:
    """Persistent failure has to decay to a negligible cost, so the wait
    doubles — but stays bounded so it can still recover."""
    breaker = CircuitBreaker(failures_before_open=1, base_delay=10, max_delay=40)

    waits = []
    for _ in range(5):
        breaker.record_failure()
        waits.append(breaker._delay())

    assert waits == [10, 20, 40, 40, 40]


def test_success_resets_the_backoff() -> None:
    breaker = CircuitBreaker(failures_before_open=1, base_delay=10, max_delay=40)

    for _ in range(4):
        breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()

    assert breaker._delay() == 10


def test_record_failure_reports_the_run_length() -> None:
    """Callers log the first failure loudly and the rest quietly."""
    breaker = CircuitBreaker()

    assert [breaker.record_failure() for _ in range(3)] == [1, 2, 3]
    breaker.record_success()
    assert breaker.record_failure() == 1


def test_is_open_is_a_read_not_a_countdown() -> None:
    """Checking the breaker must not extend the wait, or a busy caller would
    hold it open forever."""
    breaker = CircuitBreaker(failures_before_open=1, base_delay=1)

    breaker.record_failure()
    deadline = time.monotonic() + 1.1
    checks = 0
    while time.monotonic() < deadline:
        checks += breaker.is_open

    assert checks > 0  # it really was open for a while
    assert breaker.is_open is False
