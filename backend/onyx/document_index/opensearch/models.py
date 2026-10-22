from datetime import datetime
from enum import Enum

from pydantic import AliasPath, BaseModel, Field


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
    graph_memory_usage_percentage: float = Field(ge=0)


class VectorResourceStats(BaseModel):
    failed: int = Field(validation_alias=AliasPath("_nodes", "failed"))
    circuit_breaker_triggered: bool
    nodes: dict[str, VectorNodeStats] = Field(min_length=1)
