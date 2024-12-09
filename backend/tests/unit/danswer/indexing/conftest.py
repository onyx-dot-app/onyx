import pytest

from danswer.indexing.indexing_heartbeat import IndexingHeartbeatInterface


class MockHeartbeat(IndexingHeartbeatInterface):
    def __init__(self) -> None:
        self.call_count = 0

    def should_stop(self) -> bool:
        return False

    def progress(self, tag: str, amount: int) -> None:
        self.call_count += 1


@pytest.fixture
def mock_heartbeat() -> MockHeartbeat:
    return MockHeartbeat()
