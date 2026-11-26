"""Models of the container harness sandbox."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, SecretStr


class ContainerRuntimeKind(str, Enum):
    DOCKER = "docker"
    POD = "pod"


class DaemonCredentials(BaseModel):
    """What one sandbox container's guest daemon starts with: the bearer key
    and a self-signed TLS certificate that the client pins."""

    model_config = ConfigDict(frozen=True)

    key: SecretStr
    cert_pem: str
    private_key_pem: SecretStr


class ContainerSpec(BaseModel):
    """One sandbox container to create."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str
    sandbox_id: UUID
    attempt: int
    name: str


class ContainerState(str, Enum):
    # Running, or started and not yet failed (the daemon may still come up).
    RUNNING = "running"
    # Exited, failed, or being deleted: it never serves again.
    FAILED = "failed"


class RuntimeContainer(BaseModel):
    """A harness sandbox container as the runtime reports it."""

    model_config = ConfigDict(frozen=True)

    name: str
    tenant_id: str | None
    sandbox_id: UUID | None
    attempt: int | None
    state: ContainerState
    # host:port of the guest daemon; None while the runtime has none.
    address: str | None
    created_at: datetime


class ContainerRecord(BaseModel):
    """The running container of one sandbox, in the tenant cache. An
    instance is `(attempt, generation)`: the attempt counts creates (shared
    with Firecracker VMs of the sandbox), the generation counts daemon
    starts in one container."""

    model_config = ConfigDict(frozen=True)

    runtime: ContainerRuntimeKind
    name: str
    address: str
    attempt: int
    generation: int
    # The daemon's certificate, pinned on the client channel.
    cert_pem: str
    # Unix seconds of the last activity (idle stop).
    last_active: int
