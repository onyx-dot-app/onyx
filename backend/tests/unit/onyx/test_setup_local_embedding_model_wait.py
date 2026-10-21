"""API server startup waits for the model server to load the self-hosted
embedding model, and fails with a clear error when the wait runs out."""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from onyx.setup import wait_for_local_embedding_model

_NOMIC = "nomic-ai/nomic-embed-text-v1"
_NOT_CACHED_ERROR = (
    "HTTP error occurred: Error during embedding process: nomic-ai/nomic-embed-text-v1 "
    "is not in the model server's Hugging Face cache and could not be downloaded"
)


class _FakeClock:
    """Stands in for the `time` module in onyx.setup: sleep advances monotonic."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock() -> Iterator[_FakeClock]:
    fake = _FakeClock()
    with patch("onyx.setup.time", fake):
        yield fake


@pytest.fixture
def encode() -> Iterator[MagicMock]:
    with patch("onyx.setup.EmbeddingModel") as embedding_model_cls:
        yield embedding_model_cls.from_db_model.return_value.encode


def _search_settings() -> MagicMock:
    settings = MagicMock()
    settings.model_name = _NOMIC
    return settings


def test_retries_until_the_model_server_is_ready(
    clock: _FakeClock, encode: MagicMock
) -> None:
    encode.side_effect = [
        Exception("Request failed: Connection refused"),
        Exception(_NOT_CACHED_ERROR),
        [[0.1, 0.2]],
    ]

    wait_for_local_embedding_model(_search_settings())

    assert encode.call_count == 3
    assert clock.sleeps == [10, 10]


def test_fails_with_the_last_error_when_the_wait_runs_out(
    clock: _FakeClock, encode: MagicMock
) -> None:
    encode.side_effect = Exception(_NOT_CACHED_ERROR)

    with (
        patch("onyx.setup.LOCAL_EMBEDDING_MODEL_STARTUP_TIMEOUT", 30),
        pytest.raises(RuntimeError) as exc_info,
    ):
        wait_for_local_embedding_model(_search_settings())

    # The operator sees the last error and the setting that controls the wait.
    assert _NOT_CACHED_ERROR in str(exc_info.value)
    assert "LOCAL_EMBEDDING_MODEL_STARTUP_TIMEOUT" in str(exc_info.value)
    assert str(exc_info.value.__cause__) == _NOT_CACHED_ERROR
    assert encode.call_count == 3
    assert clock.now == 30


@pytest.mark.usefixtures("clock", "encode")
def test_fails_when_a_request_is_still_waiting_at_the_deadline() -> None:
    with (
        patch("onyx.setup.run_with_timeout", side_effect=TimeoutError),
        pytest.raises(RuntimeError, match="still waiting for the model server"),
    ):
        wait_for_local_embedding_model(_search_settings())
