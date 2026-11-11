import pytest

from onyx.connectors.capability_checks import runner


@pytest.fixture
def one_check_at_a_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runs capability checks one at a time, in run order, for tests that
    assert which check a rate limit stops or the order checks execute in."""
    monkeypatch.setattr(runner, "MAX_PARALLEL_CHECKS", 1)
