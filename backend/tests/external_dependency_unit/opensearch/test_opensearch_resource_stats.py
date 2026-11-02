"""Read real cluster statistics without creating indices or changing cluster settings."""

from onyx.document_index.opensearch.client import OpenSearchClient
from onyx.document_index.opensearch.constants import RESOURCE_CHECK_TIMEOUT_SECONDS
from onyx.document_index.opensearch.models import (
    NodesResourceStats,
    VectorResourceStats,
)


def test_resource_node_stats_request_and_response() -> None:
    with OpenSearchClient(
        timeout=RESOURCE_CHECK_TIMEOUT_SECONDS, max_retries=0
    ) as client:
        stats: NodesResourceStats = client.get_node_resource_stats()
    assert stats.failed == 0
    assert stats.nodes
    for node in stats.nodes.values():
        assert 0 <= node.heap_used_percent <= 100
        assert node.disks
        for disk in node.disks:
            assert 0 <= disk.available_in_bytes <= disk.total_in_bytes


def test_resource_vector_stats_request_and_response() -> None:
    with OpenSearchClient(
        timeout=RESOURCE_CHECK_TIMEOUT_SECONDS, max_retries=0
    ) as client:
        stats: VectorResourceStats = client.get_vector_resource_stats()
    assert stats.failed == 0
    assert stats.nodes
    assert isinstance(stats.circuit_breaker_triggered, bool)
    for node in stats.nodes.values():
        assert node.graph_memory_usage_percentage >= 0
