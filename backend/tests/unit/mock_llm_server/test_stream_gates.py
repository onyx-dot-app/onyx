"""A forgotten mock-stream gate must terminate its generator."""

from collections.abc import Iterator
from threading import Event
from unittest.mock import patch

import pytest

from tests.integration.mock_services.mock_llm_server.models import Reply
from tests.integration.mock_services.mock_llm_server.server import _sse


def test_unreleased_gate_times_out() -> None:
    gate: Event = Event()
    output: Iterator[str] = _sse(
        Reply(text="first secondthird "), {"model": "mock"}, gate
    )
    with patch(
        "tests.integration.mock_services.mock_llm_server.server._GATE_TIMEOUT_S", 0.01
    ):
        assert '"role": "assistant"' in next(output)
        assert '"content": "first "' in next(output)
        with pytest.raises(TimeoutError, match="gate was not released"):
            next(output)
        assert list(output) == []
