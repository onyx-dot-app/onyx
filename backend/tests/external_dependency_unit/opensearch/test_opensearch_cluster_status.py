"""External dependency tests for the cluster status of the admin Service Status page.

The vector byte tests index known vectors into their own indexes on the real
cluster and check the estimate that the status page and the vector memory
warning share.
"""

import random
import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opensearchpy.helpers import bulk

from ee.onyx.server.service_status import api as service_status_api
from onyx.auth.users import current_user
from onyx.cache.redis_backend import RedisCacheBackend
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission, VectorQuantization
from onyx.db.models import User
from onyx.document_index.opensearch.client import (
    OpenSearchClient,
    OpenSearchIndexClient,
    vector_usage_percent,
    wait_for_opensearch_with_timeout,
)
from onyx.document_index.opensearch.cluster_status import (
    DISK_WARNING_PERCENT,
    VECTOR_CRITICAL_PERCENT,
    collect_cluster_status,
    evaluate_cluster_issues,
)
from onyx.document_index.opensearch.models import (
    ClusterIssueKind,
    ClusterIssueSeverity,
    ClusterNodeStatus,
    ClusterStatus,
    NodesMemoryStats,
    NodeVectorBytes,
    OnyxIndexRef,
    VectorResourceStats,
)
from onyx.document_index.opensearch.resource_health import (
    DISK_USAGE_THRESHOLD_PERCENT,
    VECTOR_USAGE_THRESHOLD_PERCENT,
)
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.redis.redis_pool import get_redis_client

DIM = 64
CHUNKS = 500
GB = 1024**3


def _vector_mapping(encoder: dict[str, Any] | None) -> dict[str, Any]:
    parameters: dict[str, Any] = {"m": 16, "ef_construction": 100}
    if encoder is not None:
        parameters["encoder"] = encoder
    method: dict[str, Any] = {
        "name": "hnsw",
        "engine": "lucene",
        "space_type": "cosinesimil",
        "parameters": parameters,
    }
    return {
        "properties": {
            "content_vector": {"type": "knn_vector", "dimension": DIM, "method": method}
        }
    }


@pytest.fixture
def index_with_vectors(
    request: pytest.FixtureRequest,
) -> Generator[str, None, None]:
    """Creates an index with CHUNKS known vectors, in one segment on disk."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")
    encoder: dict[str, Any] | None = request.param
    name = f"test_cluster_status_{uuid.uuid4().hex[:8]}"
    rng = random.Random(0)
    with OpenSearchIndexClient(index_name=name) as client:
        client.create_index(
            mappings=_vector_mapping(encoder),
            settings={
                "index": {"knn": True, "number_of_shards": 1, "number_of_replicas": 0}
            },
        )
    try:
        with OpenSearchIndexClient(index_name=name) as client:
            bulk(
                client._client,
                (
                    {
                        "_index": name,
                        "_id": str(i),
                        "content_vector": [rng.uniform(-1, 1) for _ in range(DIM)],
                    }
                    for i in range(CHUNKS)
                ),
            )
            client._client.indices.forcemerge(index=name, max_num_segments=1)
            client._client.indices.flush(index=name)
        yield name
    finally:
        with OpenSearchIndexClient(index_name=name) as client:
            client.delete_index()


def _index_vector_bytes(index_name: str) -> int:
    with OpenSearchIndexClient(index_name=index_name) as client:
        per_node: dict[str, NodeVectorBytes] = client.get_node_vector_bytes(index_name)
    assert sum(node.shard_count for node in per_node.values()) == 1
    return sum(node.vector_bytes for node in per_node.values())


@pytest.mark.parametrize("index_with_vectors", [None], indirect=True)
def test_float_index_counts_float_vectors(index_with_vectors: str) -> None:
    float_bytes: int = CHUNKS * DIM * 4
    vector_bytes: int = _index_vector_bytes(index_with_vectors)
    # The float32 vectors plus the HNSW graph.
    assert float_bytes <= vector_bytes < 2 * float_bytes


@pytest.mark.parametrize("index_with_vectors", [None], indirect=True)
def test_vector_memory_warning_sees_lucene_vectors(index_with_vectors: str) -> None:
    # k-NN graph memory stays 0 for the Lucene engine, so the warning reads
    # the vector files against the file cache instead.
    with OpenSearchIndexClient(index_name=index_with_vectors) as client:
        stats: VectorResourceStats = client.get_vector_resource_stats()
    assert any(node.usage_percent > 0 for node in stats.nodes.values())


@pytest.mark.parametrize(
    "index_with_vectors",
    [{"name": "sq", "parameters": {"bits": 7, "confidence_interval": 1.0}}],
    indirect=True,
)
def test_quantized_index_counts_quantized_vectors(index_with_vectors: str) -> None:
    # One byte per dimension plus the graph, not the float32 copy kept on disk.
    vector_bytes: int = _index_vector_bytes(index_with_vectors)
    assert CHUNKS * DIM <= vector_bytes < CHUNKS * DIM * 4


@pytest.mark.parametrize("index_with_vectors", [None], indirect=True)
def test_collect_cluster_status_reads_the_index(index_with_vectors: str) -> None:
    status: ClusterStatus = collect_cluster_status(
        [
            OnyxIndexRef(
                index_name=index_with_vectors,
                is_current=True,
                model_name="test-model",
                model_dim=DIM,
                vector_quantization=VectorQuantization.NONE,
            ),
            OnyxIndexRef(
                index_name=f"{index_with_vectors}_missing",
                is_current=False,
                model_name="test-model",
                model_dim=DIM,
                vector_quantization=VectorQuantization.NONE,
            ),
        ]
    )
    assert status.nodes
    assert status.data_node_count == len(status.nodes)
    for node in status.nodes:
        assert 0 < node.file_cache_bytes < node.memory_bytes
        assert 0 <= node.disk_used_bytes <= node.disk_total_bytes
        assert node.vector_bytes >= CHUNKS * DIM * 4
    # A missing index is left out, not reported as empty.
    [index] = status.indexes
    assert index.index_name == index_with_vectors
    assert index.chunk_count == CHUNKS
    assert index.primary_shards == 1
    assert index.replicas == 0
    assert index.store_size_bytes > 0
    # A reindex creates its index after it starts, so its absence is no issue.
    assert all(issue.kind != ClusterIssueKind.INDEX_MISSING for issue in status.issues)
    # The page colors its bars with the limits the issues use.
    assert status.thresholds.disk_warning_percent == DISK_WARNING_PERCENT
    assert status.thresholds.disk_critical_percent == DISK_USAGE_THRESHOLD_PERCENT
    assert status.thresholds.vector_warning_percent == VECTOR_USAGE_THRESHOLD_PERCENT
    assert status.thresholds.vector_critical_percent == VECTOR_CRITICAL_PERCENT


def test_missing_current_index_is_critical() -> None:
    status: ClusterStatus = collect_cluster_status(
        [
            OnyxIndexRef(
                index_name=f"test_missing_{uuid.uuid4().hex}",
                is_current=True,
                model_name="test-model",
                model_dim=DIM,
                vector_quantization=VectorQuantization.NONE,
            )
        ]
    )
    assert status.indexes == []
    assert status.issues[0].kind == ClusterIssueKind.INDEX_MISSING
    assert status.issues[0].severity == ClusterIssueSeverity.CRITICAL


@pytest.mark.parametrize("index_with_vectors", [None], indirect=True)
def test_vector_check_fails_when_a_node_does_not_answer(
    index_with_vectors: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with OpenSearchIndexClient(index_name=index_with_vectors) as client:
        real_stats = client._client.nodes.stats

        def one_node_failed(*args: Any, **kwargs: Any) -> dict[str, Any]:
            response: dict[str, Any] = real_stats(*args, **kwargs)
            response["_nodes"] = {"failed": 1}
            return response

        monkeypatch.setattr(client._client.nodes, "stats", one_node_failed)
        stats: VectorResourceStats = client.get_vector_resource_stats()
    # The health check skips a run with a failed node and keeps its last result.
    assert stats.failed == 1


@pytest.mark.parametrize("index_with_vectors", [None], indirect=True)
def test_status_shows_nodes_that_did_not_answer(
    index_with_vectors: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_stats = OpenSearchClient.get_node_memory_stats

    def one_node_failed(self: OpenSearchClient) -> NodesMemoryStats:
        stats: NodesMemoryStats = real_stats(self)
        return NodesMemoryStats(failed=1, nodes=stats.nodes)

    monkeypatch.setattr(OpenSearchClient, "get_node_memory_stats", one_node_failed)
    status: ClusterStatus = collect_cluster_status(
        [
            OnyxIndexRef(
                index_name=index_with_vectors,
                is_current=True,
                model_name="test-model",
                model_dim=DIM,
                vector_quantization=VectorQuantization.NONE,
            )
        ]
    )
    # Its rows and warnings are missing, so the read must not look healthy.
    assert status.issues[0].kind == ClusterIssueKind.NODES_UNANSWERED
    assert status.issues[0].severity == ClusterIssueSeverity.CRITICAL
    assert status.issues[0].value == 1


@pytest.mark.parametrize("index_with_vectors", [None], indirect=True)
def test_failed_shard_stats_are_not_summed(
    index_with_vectors: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with OpenSearchIndexClient(index_name=index_with_vectors) as client:
        real_stats = client._client.indices.stats

        def one_shard_failed(*args: Any, **kwargs: Any) -> dict[str, Any]:
            response: dict[str, Any] = real_stats(*args, **kwargs)
            response["_shards"] = {"failed": 1}
            return response

        monkeypatch.setattr(client._client.indices, "stats", one_shard_failed)
        # Partial totals would understate the vectors.
        with pytest.raises(RuntimeError):
            client.get_node_vector_bytes(index_with_vectors)


def test_vectors_without_a_file_cache_are_full() -> None:
    assert vector_usage_percent(GB, 0) == 100
    assert vector_usage_percent(0, 0) == 0
    node = _node("node-1")
    node.file_cache_bytes = 0
    [issue] = evaluate_cluster_issues("green", 0, [node])
    assert (issue.kind, issue.severity) == (
        ClusterIssueKind.VECTOR_MEMORY,
        ClusterIssueSeverity.CRITICAL,
    )


def test_nodes_with_the_same_name_keep_their_own_issues() -> None:
    # OpenSearch does not require unique node names.
    full = _node("data", disk_percent=95)
    empty = _node("data", disk_percent=10)
    empty.node_id = "other"
    [issue] = evaluate_cluster_issues("green", 0, [full, empty])
    assert issue.kind == ClusterIssueKind.DISK
    assert issue.node_names == ["data"]
    assert issue.value == 95


def _node(
    name: str,
    disk_percent: float = 10,
    vector_percent: float = 10,
    heap_percent: float = 10,
) -> ClusterNodeStatus:
    return ClusterNodeStatus(
        node_id=name,
        name=name,
        shard_count=3,
        memory_bytes=64 * GB,
        file_cache_bytes=32 * GB,
        vector_bytes=int(32 * GB * vector_percent / 100),
        heap_max_bytes=32 * GB,
        heap_used_bytes=int(32 * GB * heap_percent / 100),
        disk_total_bytes=100 * GB,
        disk_used_bytes=int(100 * GB * disk_percent / 100),
        cpu_percent=5,
        load_average_1m=0.5,
        search_queue=0,
        search_rejected=0,
    )


def test_healthy_cluster_has_no_issues() -> None:
    assert evaluate_cluster_issues("green", 0, [_node("node-1"), _node("node-2")]) == []


def test_issues_group_nodes_and_put_critical_first() -> None:
    issues = evaluate_cluster_issues(
        "yellow",
        2,
        [
            _node("node-1", disk_percent=76, vector_percent=96),
            _node("node-2", disk_percent=95, vector_percent=95),
            _node("node-3", disk_percent=40, vector_percent=120, heap_percent=90),
        ],
    )
    summary = [
        (issue.severity, issue.kind, issue.node_names, issue.value) for issue in issues
    ]
    assert summary == [
        (ClusterIssueSeverity.CRITICAL, ClusterIssueKind.DISK, ["node-2"], 95.0),
        (
            ClusterIssueSeverity.CRITICAL,
            ClusterIssueKind.VECTOR_MEMORY,
            ["node-3"],
            120.0,
        ),
        (ClusterIssueSeverity.WARNING, ClusterIssueKind.UNASSIGNED_SHARDS, [], 2.0),
        (ClusterIssueSeverity.WARNING, ClusterIssueKind.DISK, ["node-1"], 76.0),
        (
            ClusterIssueSeverity.WARNING,
            ClusterIssueKind.VECTOR_MEMORY,
            ["node-1", "node-2"],
            96.0,
        ),
        (ClusterIssueSeverity.WARNING, ClusterIssueKind.JVM_MEMORY, ["node-3"], 90.0),
    ]


def test_unassigned_replicas_on_one_data_node_are_no_issue() -> None:
    # A replica can never be placed on a single node; the default index has one.
    assert evaluate_cluster_issues("yellow", 2, [_node("node-1")]) == []
    # The cluster's count decides, not the nodes that answered.
    [issue] = evaluate_cluster_issues("yellow", 2, [_node("node-1")], 2)
    assert issue.kind == ClusterIssueKind.UNASSIGNED_SHARDS


def test_red_cluster_is_critical() -> None:
    [issue] = evaluate_cluster_issues("red", 4, [_node("node-1")])
    assert issue.kind == ClusterIssueKind.CLUSTER_RED
    assert issue.severity == ClusterIssueSeverity.CRITICAL


STATUS_URL = "/admin/service-status/opensearch"


@pytest.fixture
def status_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, User, list[int]], None, None]:
    """The endpoint on a test app, with its own cache prefix and a counted collector."""
    redis = get_redis_client(tenant_id=f"test_service_status_{uuid.uuid4().hex}")
    monkeypatch.setattr(
        service_status_api, "get_shared_cache_backend", lambda: RedisCacheBackend(redis)
    )
    monkeypatch.setattr(
        service_status_api,
        "onyx_index_refs",
        lambda _db: [
            OnyxIndexRef(
                index_name="test_missing_index",
                is_current=True,
                model_name="test-model",
                model_dim=DIM,
                vector_quantization=VectorQuantization.NONE,
            )
        ],
    )
    calls: list[int] = []

    def counted_collect(indexes: list[OnyxIndexRef]) -> ClusterStatus:
        calls.append(len(indexes))
        return collect_cluster_status(indexes)

    monkeypatch.setattr(service_status_api, "collect_cluster_status", counted_collect)
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(service_status_api.router)
    user = User(
        id=uuid.uuid4(),
        effective_permissions=[Permission.FULL_ADMIN_PANEL_ACCESS.value],
    )
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: None
    with TestClient(app) as browser:
        yield browser, user, calls
    redis.delete(service_status_api.CLUSTER_STATUS_KEY)


def test_status_endpoint_caches_and_refreshes(
    status_api: tuple[TestClient, User, list[int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser, _, calls = status_api
    first = browser.get(STATUS_URL)
    assert first.status_code == 200
    assert first.json()["nodes"]
    # A missing current index is left out instead of failing the page.
    assert first.json()["indexes"] == []

    # Within the shared window, reads and early refreshes reuse the result.
    assert browser.get(STATUS_URL).json()["checked_at"] == first.json()["checked_at"]
    assert browser.get(f"{STATUS_URL}?refresh=true").json() == first.json()
    assert calls == [1]

    monkeypatch.setattr(service_status_api, "CLUSTER_STATUS_MIN_REFRESH_SECONDS", 0)
    refreshed = browser.get(f"{STATUS_URL}?refresh=true").json()
    assert refreshed["checked_at"] != first.json()["checked_at"]
    assert calls == [1, 1]


def test_status_endpoint_denies_non_admins(
    status_api: tuple[TestClient, User, list[int]],
) -> None:
    browser, user, calls = status_api
    user.effective_permissions = []
    assert browser.get(STATUS_URL).status_code == 403
    assert calls == []


def test_status_endpoint_is_single_tenant_only(
    status_api: tuple[TestClient, User, list[int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser, _, calls = status_api
    monkeypatch.setattr(service_status_api, "MULTI_TENANT", True)
    response = browser.get(STATUS_URL)
    assert response.status_code == 403
    assert response.json()["error_code"] == "SINGLE_TENANT_ONLY"
    assert calls == []


def test_status_endpoint_reports_an_unreachable_cluster(
    status_api: tuple[TestClient, User, list[int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser, _, _ = status_api

    def unreachable(_indexes: list[OnyxIndexRef]) -> ClusterStatus:
        raise ConnectionError("no route to host")

    monkeypatch.setattr(service_status_api, "collect_cluster_status", unreachable)
    response = browser.get(STATUS_URL)
    assert response.status_code == 503
    assert response.json()["error_code"] == "SERVICE_UNAVAILABLE"
