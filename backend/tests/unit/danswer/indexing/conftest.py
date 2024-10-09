from typing import Any

import pytest

from danswer.indexing.indexing_heartbeat import Heartbeat


class MockHeartbeat(Heartbeat):
    def __init__(self) -> None:
        self.call_count = 0

    def heartbeat(self, metadata: Any = None) -> None:
        self.call_count += 1


@pytest.fixture
def mock_heartbeat() -> MockHeartbeat:
    return MockHeartbeat()
