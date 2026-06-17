from __future__ import annotations

from uuid import UUID

import pytest

from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.kubernetes.sidecar_client import (
    SidecarStatusError,
)
from onyx.server.features.build.sandbox.models import FilesystemEntry

_SANDBOX_ID = UUID("9a5c81d5-931e-4348-b034-3ebd13bcba44")
_SESSION_ID = UUID("903a9a86-b7b1-4b49-9269-1fe558b243ee")


class _FakeSidecarClient:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, str]] = []

    def list_directory(
        self,
        *,
        sandbox_id: UUID,
        session_id: UUID,
        path: str,
    ) -> list[FilesystemEntry]:
        self.calls.append((sandbox_id, session_id, path))
        return [
            FilesystemEntry(
                name="outputs",
                path="outputs",
                is_directory=True,
            )
        ]


def test_kubernetes_list_directory_delegates_to_sidecar() -> None:
    manager: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    sidecar_client = _FakeSidecarClient()
    manager._sidecar_client = sidecar_client  # type: ignore[attr-defined]

    entries = manager.list_directory(_SANDBOX_ID, _SESSION_ID, ".")

    assert sidecar_client.calls == [(_SANDBOX_ID, _SESSION_ID, ".")]
    assert entries == [
        FilesystemEntry(name="outputs", path="outputs", is_directory=True)
    ]


def test_kubernetes_list_directory_maps_sidecar_not_found() -> None:
    class NotFoundSidecarClient:
        def list_directory(self, **_kwargs: object) -> list[FilesystemEntry]:
            raise SidecarStatusError(
                "filesystem list",
                404,
                '{"detail":"path not found or not a directory"}',
            )

    manager: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    manager._sidecar_client = NotFoundSidecarClient()  # type: ignore[attr-defined]

    with pytest.raises(ValueError, match="not found or not a directory"):
        manager.list_directory(_SANDBOX_ID, _SESSION_ID, "missing")


@pytest.mark.parametrize(
    ("status_code", "body"),
    [
        (400, '{"detail":"Invalid request body"}'),
        (404, '{"detail":"Not Found"}'),
    ],
)
def test_kubernetes_list_directory_surfaces_unexpected_sidecar_errors(
    status_code: int,
    body: str,
) -> None:
    class ErrorSidecarClient:
        def list_directory(self, **_kwargs: object) -> list[FilesystemEntry]:
            raise SidecarStatusError("filesystem list", status_code, body)

    manager: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    manager._sidecar_client = ErrorSidecarClient()  # type: ignore[attr-defined]

    with pytest.raises(RuntimeError, match="Failed to list directory"):
        manager.list_directory(_SANDBOX_ID, _SESSION_ID, "missing")
