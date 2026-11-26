"""Where container sandboxes run: Kubernetes pods (`PodRuntime`) or Docker
containers on Compose (`DockerRuntime`).

Every harness container runs the craft-runtime `container` image with the
guest daemon on TCP and TLS, and carries the sandbox labels (component,
managed-by, sandbox and tenant IDs, attempt) plus `onyx.app/sandbox-kind=
harness`. The egress proxy identifies it by them; Craft cleanup skips it.
"""

import abc
from uuid import UUID

from onyx.server.features.build.configs import SANDBOX_HARNESS_DAEMON_PORT
from onyx.server.features.build.sandbox.container.models import (
    ContainerRuntimeKind,
    ContainerSpec,
    DaemonCredentials,
    RuntimeContainer,
)
from onyx.server.features.build.sandbox.labels import (
    LABEL_PROVISIONING_ATTEMPT,
    LABEL_SANDBOX_ID,
    LABEL_SANDBOX_KIND,
    LABEL_TENANT_ID,
    SANDBOX_KIND_HARNESS,
)

# The daemon's files in the container (README contract: file calls with no
# session refuse /run/craft-fc).
DAEMON_FILES_DIR = "/run/craft-fc/daemon"
DAEMON_KEY_FILE = "key"
DAEMON_CERT_FILE = "tls.crt"
DAEMON_PRIVATE_KEY_FILE = "tls.key"


def container_name(sandbox_id: UUID, attempt: int) -> str:
    """One name per attempt: a pod of the last attempt can still be
    terminating when the next one starts."""
    return f"harness-{sandbox_id}-{attempt}"


def daemon_args(port: int = SANDBOX_HARNESS_DAEMON_PORT) -> list[str]:
    """Arguments of the image entrypoint (`sandbox-entrypoint`), which adds
    `--container`."""
    return [
        "--listen",
        f"tcp:0.0.0.0:{port}",
        "--key-file",
        f"{DAEMON_FILES_DIR}/{DAEMON_KEY_FILE}",
        "--tls-cert",
        f"{DAEMON_FILES_DIR}/{DAEMON_CERT_FILE}",
        "--tls-key",
        f"{DAEMON_FILES_DIR}/{DAEMON_PRIVATE_KEY_FILE}",
    ]


def harness_labels(spec: ContainerSpec) -> dict[str, str]:
    """The harness labels on top of a runtime's sandbox labels."""
    return {
        LABEL_SANDBOX_ID: str(spec.sandbox_id),
        LABEL_TENANT_ID: spec.tenant_id,
        LABEL_PROVISIONING_ATTEMPT: str(spec.attempt),
        LABEL_SANDBOX_KIND: SANDBOX_KIND_HARNESS,
    }


def parse_labels(labels: dict[str, str]) -> tuple[str | None, UUID | None, int | None]:
    """Tenant ID, sandbox ID and attempt of a harness container; None for a
    label that is missing or bad."""
    sandbox_id: UUID | None
    try:
        sandbox_id = UUID(labels.get(LABEL_SANDBOX_ID, ""))
    except ValueError:
        sandbox_id = None
    raw_attempt = labels.get(LABEL_PROVISIONING_ATTEMPT, "")
    attempt = int(raw_attempt) if raw_attempt.isdigit() else None
    return labels.get(LABEL_TENANT_ID) or None, sandbox_id, attempt


class ContainerRuntime(abc.ABC):
    kind: ContainerRuntimeKind

    @abc.abstractmethod
    def prepare(self) -> None:
        """Make what every create needs (for example pull the image) before
        a start's budget begins."""

    @abc.abstractmethod
    def create(
        self, spec: ContainerSpec, credentials: DaemonCredentials, deadline: float
    ) -> str:
        """Create and start the container with the daemon's files, and return
        the daemon address (host:port) once the container runs. Deletes
        what it made when it fails. `deadline` is time.monotonic()."""

    @abc.abstractmethod
    def inspect(self, name: str) -> RuntimeContainer | None:
        """None when the container does not exist."""

    @abc.abstractmethod
    def delete(self, name: str) -> None:
        """Delete the container and its own parts; nothing when it is gone."""

    @abc.abstractmethod
    def list_containers(self, deadline: float) -> list[RuntimeContainer]:
        """Every harness container of this deployment."""
