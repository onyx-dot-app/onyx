from datetime import datetime
from enum import Enum

from pydantic import AliasPath, BaseModel, Field

from onyx.db.enums import VectorQuantization


class ResourceIssue(str, Enum):
    DISK = "disk"
    JVM_MEMORY = "jvm_memory"
    VECTOR_MEMORY = "vector_memory"


class ResourceHealth(BaseModel):
    checked_at: datetime | None = None
    issues: list[ResourceIssue] = Field(default_factory=list)
    stale: bool = True


class ResourceSnapshot(BaseModel):
    checked_at: datetime
    issues: list[ResourceIssue]
    heap_high_nodes: set[str]
    vector_high_nodes: set[str]


class DiskStats(BaseModel):
    total_in_bytes: int = Field(gt=0)
    available_in_bytes: int = Field(ge=0)


class NodeResourceStats(BaseModel):
    heap_used_percent: float = Field(
        validation_alias=AliasPath("jvm", "mem", "heap_used_percent"),
        ge=0,
        le=100,
    )
    disks: list[DiskStats] = Field(
        validation_alias=AliasPath("fs", "data"), min_length=1
    )


class NodesResourceStats(BaseModel):
    failed: int = Field(validation_alias=AliasPath("_nodes", "failed"))
    nodes: dict[str, NodeResourceStats] = Field(min_length=1)


class VectorNodeStats(BaseModel):
    # Estimated vector bytes on the node as a share of its file cache. Lucene
    # reads vectors through the OS file cache, not k-NN native memory.
    usage_percent: float = Field(ge=0)


class VectorResourceStats(BaseModel):
    failed: int = Field(validation_alias=AliasPath("_nodes", "failed"))
    circuit_breaker_triggered: bool
    nodes: dict[str, VectorNodeStats] = Field(min_length=1)


class NodeVectorBytes(BaseModel):
    """The vector files that search reads, summed over the shards on a node."""

    vector_bytes: int = 0
    shard_count: int = 0


class NodeMemoryStats(BaseModel):
    name: str
    # The smaller of the host RAM and the container memory limit.
    memory_bytes: int
    heap_max_bytes: int
    heap_used_bytes: int
    disk_total_bytes: int
    disk_available_bytes: int
    cpu_percent: float
    load_average_1m: float | None
    search_queue: int
    search_rejected: int

    @property
    def file_cache_bytes(self) -> int:
        return max(self.memory_bytes - self.heap_max_bytes, 0)


class NodesMemoryStats(BaseModel):
    # Data nodes that did not answer; nodes lists only the ones that did.
    failed: int
    nodes: dict[str, NodeMemoryStats]


class ClusterIssueKind(str, Enum):
    CLUSTER_RED = "cluster_red"
    UNASSIGNED_SHARDS = "unassigned_shards"
    DISK = "disk"
    VECTOR_MEMORY = "vector_memory"
    JVM_MEMORY = "jvm_memory"
    # The index that serves search is not in OpenSearch.
    INDEX_MISSING = "index_missing"
    # Data nodes that did not answer the stats request; value is their count.
    NODES_UNANSWERED = "nodes_unanswered"


class ClusterIssueSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"


class ClusterIssue(BaseModel):
    kind: ClusterIssueKind
    severity: ClusterIssueSeverity
    # Data nodes the issue applies to; empty for cluster-wide issues.
    node_names: list[str] = Field(default_factory=list)
    # The highest usage among node_names, or the count of unassigned shards or
    # unanswered nodes.
    value: float


class ClusterNodeStatus(BaseModel):
    node_id: str
    name: str
    shard_count: int
    memory_bytes: int
    file_cache_bytes: int
    vector_bytes: int
    heap_max_bytes: int
    heap_used_bytes: int
    disk_total_bytes: int
    disk_used_bytes: int
    cpu_percent: float
    load_average_1m: float | None
    search_queue: int
    search_rejected: int


class ClusterIndexStatus(BaseModel):
    index_name: str
    # True for the index that serves search, False for the one a reindex builds.
    is_current: bool
    model_name: str
    model_dim: int
    vector_quantization: VectorQuantization
    health: str | None
    chunk_count: int
    deleted_chunk_count: int
    store_size_bytes: int
    primary_shards: int
    replicas: int


class UsageThresholds(BaseModel):
    """The usage percents at which a data node gets a warning or critical issue."""

    disk_warning_percent: float
    disk_critical_percent: float
    vector_warning_percent: float
    vector_critical_percent: float


class ClusterStatus(BaseModel):
    checked_at: datetime
    version: str | None
    health: str
    data_node_count: int
    primary_shards: int
    active_shards: int
    unassigned_shards: int
    nodes: list[ClusterNodeStatus]
    indexes: list[ClusterIndexStatus]
    issues: list[ClusterIssue]
    thresholds: UsageThresholds


class OnyxIndexRef(BaseModel):
    """An Onyx index the status page reports on."""

    index_name: str
    is_current: bool
    model_name: str
    model_dim: int
    vector_quantization: VectorQuantization


class SearchResult(str, Enum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"


class SearchSample(BaseModel):
    # Epoch milliseconds when the search finished.
    at_ms: int
    client_ms: float
    server_ms: int | None
    search_type: str
    result: SearchResult


class SearchRatePoint(BaseModel):
    """The searches of one minute."""

    # Epoch milliseconds at the start of the minute.
    minute_ms: int
    # 60, or the seconds elapsed so far for the current minute.
    seconds: float
    count: int
    error_count: int = 0
    # Percentiles of the minute's successful searches; None without any.
    p10_ms: float | None = None
    p90_ms: float | None = None


class SearchActivity(BaseModel):
    window_minutes: int
    total_count: int
    error_count: int
    p90_ms: float | None
    rate: list[SearchRatePoint]
    # A minute whose p90 is above this shows as slow.
    slow_p90_ms: int
    # Every slow or failed search, and a random few of each minute's others.
    samples: list[SearchSample]
    # True when more slow or failed searches happened than samples lists.
    sampled: bool
    # True when a minute had more batches than a read takes, so the counts and
    # percentiles cover only part of it.
    partial: bool
