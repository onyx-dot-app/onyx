"""Shared Craft sandbox runtime boundary and runtime selection."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import BinaryIO, Protocol
from uuid import UUID

from onyx.server.features.build.configs import CRAFT_SANDBOX_RUNTIME
from onyx.server.features.build.sandbox.models import ExecResult, SandboxInfo


class SandboxRuntime(Protocol):
    def provision(
        self,
        sandbox_id: UUID,
        user_id: UUID,
        tenant_id: str,
        onyx_pat: str | None,
        provisioning_attempt_number: int,
        initialize: Callable[[UUID, float], None],
    ) -> SandboxInfo: ...

    def terminate(self, sandbox_id: UUID) -> None: ...

    def exists(self, sandbox_id: UUID) -> bool: ...

    def health_check(self, sandbox_id: UUID) -> bool: ...

    def helper(
        self,
        sandbox_id: UUID,
        operation: str,
        metadata: dict[str, object],
        *,
        stdin: bytes | BinaryIO | None = None,
        timeout: float,
    ) -> ExecResult: ...

    def helper_stream(
        self,
        sandbox_id: UUID,
        operation: str,
        metadata: dict[str, object],
        *,
        stdin: bytes | BinaryIO | None = None,
        timeout: float,
    ) -> Iterator[bytes]: ...

    def service_url(self, sandbox_id: UUID, port: int) -> str: ...

    def read_password(self, sandbox_id: UUID) -> str | None: ...

    def stream_logs(
        self, sandbox_id: UUID, *, tail_lines: int = 200
    ) -> Iterator[str]: ...


def get_sandbox_runtime() -> SandboxRuntime:
    if CRAFT_SANDBOX_RUNTIME == "kubernetes_firecracker":
        from onyx.server.features.build.sandbox.kubernetes_runtime import (
            KubernetesRuntime,
        )

        return KubernetesRuntime()
    raise ValueError("CRAFT_SANDBOX_RUNTIME must be 'kubernetes_firecracker'")
