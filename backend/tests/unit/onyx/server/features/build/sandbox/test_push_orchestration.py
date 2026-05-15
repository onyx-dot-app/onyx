"""Tests for push_to_sandbox and push_to_sandboxes on SandboxManager base class."""

from collections.abc import Generator
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest

from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.models import FatalWriteError
from onyx.server.features.build.sandbox.models import FileSet
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.models import RetriableWriteError
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.sandbox.models import SnapshotResult


class StubSandboxManager(SandboxManager):
    """Minimal stub that implements all abstract methods for testing push logic."""

    def __init__(self) -> None:
        self.write_calls: list[dict[str, Any]] = []
        self._write_side_effect: Exception | None = None
        # List of side effects for sequential calls (pops from front)
        self._write_side_effects: list[Exception | None] = []

    def set_write_side_effect(self, effect: Exception | None) -> None:
        """Set a single side effect for all write_files_to_sandbox calls."""
        self._write_side_effect = effect
        self._write_side_effects = []

    def set_write_side_effects(self, effects: list[Exception | None]) -> None:
        """Set sequential side effects (one per call, pops from front)."""
        self._write_side_effects = list(effects)
        self._write_side_effect = None

    def write_files_to_sandbox(
        self,
        *,
        sandbox_id: UUID,
        mount_path: str,
        files: FileSet,
    ) -> None:
        self.write_calls.append(
            {"sandbox_id": sandbox_id, "mount_path": mount_path, "files": files}
        )
        if self._write_side_effects:
            effect = self._write_side_effects.pop(0)
            if effect is not None:
                raise effect
            return
        if self._write_side_effect is not None:
            raise self._write_side_effect

    # -- All other abstract methods raise NotImplementedError --

    def provision(
        self,
        sandbox_id: UUID,
        user_id: UUID,
        tenant_id: str,
        llm_config: LLMProviderConfig,
        onyx_pat: str | None = None,
    ) -> SandboxInfo:
        raise NotImplementedError

    def terminate(self, sandbox_id: UUID) -> None:
        raise NotImplementedError

    def setup_session_workspace(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        llm_config: LLMProviderConfig,
        nextjs_port: int | None,
        snapshot_path: str | None = None,
        user_name: str | None = None,
        user_role: str | None = None,
        user_work_area: str | None = None,
        user_level: str | None = None,
    ) -> None:
        raise NotImplementedError

    def cleanup_session_workspace(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        nextjs_port: int | None = None,
    ) -> None:
        raise NotImplementedError

    def create_snapshot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        tenant_id: str,
    ) -> SnapshotResult | None:
        raise NotImplementedError

    def restore_snapshot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        snapshot_storage_path: str,
        tenant_id: str,
        nextjs_port: int | None,
        llm_config: LLMProviderConfig,
    ) -> None:
        raise NotImplementedError

    def session_workspace_exists(
        self,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> bool:
        raise NotImplementedError

    def health_check(self, sandbox_id: UUID, timeout: float = 60.0) -> bool:
        raise NotImplementedError

    def send_message(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        message: str,
    ) -> Generator[Any, None, None]:
        raise NotImplementedError

    def list_directory(
        self, sandbox_id: UUID, session_id: UUID, path: str
    ) -> list[FilesystemEntry]:
        raise NotImplementedError

    def read_file(self, sandbox_id: UUID, session_id: UUID, path: str) -> bytes:
        raise NotImplementedError

    def upload_file(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        filename: str,
        content: bytes,
    ) -> str:
        raise NotImplementedError

    def delete_file(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        path: str,
    ) -> bool:
        raise NotImplementedError

    def write_sandbox_file(
        self,
        sandbox_id: UUID,
        path: str,
        content: str,
    ) -> None:
        raise NotImplementedError

    def get_upload_stats(
        self,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> tuple[int, int]:
        raise NotImplementedError

    def get_webapp_url(self, sandbox_id: UUID, port: int) -> str:
        raise NotImplementedError

    def generate_pptx_preview(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        pptx_path: str,
        cache_dir: str,
    ) -> tuple[list[str], bool]:
        raise NotImplementedError


SB_1 = UUID("00000000-0000-0000-0000-000000000001")
SB_2 = UUID("00000000-0000-0000-0000-000000000002")
SB_FAIL = UUID("00000000-0000-0000-0000-0000000000ff")


# ---------------------------------------------------------------------------
# push_to_sandbox tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mgr() -> StubSandboxManager:
    return StubSandboxManager()


def _sample_files() -> FileSet:
    return {"hello.txt": b"hello world"}


@patch("onyx.server.features.build.sandbox.base.time.sleep")
def test_push_to_sandbox_happy_path(
    mock_sleep: Any,  # noqa: ARG001
    mgr: StubSandboxManager,
) -> None:
    result = mgr.push_to_sandbox(
        sandbox_id=SB_1,
        mount_path="/workspace/managed/skills",
        files=_sample_files(),
    )
    assert result.targets == 1
    assert result.succeeded == 1
    assert result.failures == []
    assert len(mgr.write_calls) == 1
    assert mgr.write_calls[0]["sandbox_id"] == SB_1


@patch("onyx.server.features.build.sandbox.base.time.sleep")
def test_push_to_sandbox_fatal_write_error(
    mock_sleep: Any,  # noqa: ARG001
    mgr: StubSandboxManager,
) -> None:
    mgr.set_write_side_effect(FatalWriteError("bad auth"))
    result = mgr.push_to_sandbox(
        sandbox_id=SB_1,
        mount_path="/workspace/managed/skills",
        files=_sample_files(),
    )
    assert result.targets == 1
    assert result.succeeded == 0
    assert len(result.failures) == 1
    assert result.failures[0].reason == "write_error"
    assert "bad auth" in (result.failures[0].detail or "")
    # FatalWriteError should not retry
    assert len(mgr.write_calls) == 1


@patch("onyx.server.features.build.sandbox.base.time.sleep")
def test_push_to_sandbox_retriable_all_attempts_fail(
    mock_sleep: Any,  # noqa: ARG001
    mgr: StubSandboxManager,
) -> None:
    mgr.set_write_side_effect(RetriableWriteError("timeout"))
    result = mgr.push_to_sandbox(
        sandbox_id=SB_1,
        mount_path="/workspace/managed/skills",
        files=_sample_files(),
    )
    assert result.targets == 1
    assert result.succeeded == 0
    assert len(result.failures) == 1
    assert result.failures[0].reason == "timeout"
    # Should have retried 3 times
    assert len(mgr.write_calls) == 3


@patch("onyx.server.features.build.sandbox.base.time.sleep")
def test_push_to_sandbox_retriable_then_success(
    mock_sleep: Any,  # noqa: ARG001
    mgr: StubSandboxManager,
) -> None:
    # First two calls fail with retriable error, third succeeds
    mgr.set_write_side_effects(
        [RetriableWriteError("transient"), RetriableWriteError("transient"), None]
    )
    result = mgr.push_to_sandbox(
        sandbox_id=SB_1,
        mount_path="/workspace/managed/skills",
        files=_sample_files(),
    )
    assert result.targets == 1
    assert result.succeeded == 1
    assert result.failures == []
    assert len(mgr.write_calls) == 3


@patch("onyx.server.features.build.sandbox.base.time.sleep")
def test_push_to_sandbox_unexpected_exception(
    mock_sleep: Any,  # noqa: ARG001
    mgr: StubSandboxManager,
) -> None:
    """Unexpected exceptions are caught and converted to PushFailure, not re-raised."""
    mgr.set_write_side_effect(RuntimeError("boom"))
    result = mgr.push_to_sandbox(
        sandbox_id=SB_1,
        mount_path="/workspace/managed/skills",
        files=_sample_files(),
    )
    assert result.targets == 1
    assert result.succeeded == 0
    assert len(result.failures) == 1
    assert result.failures[0].reason == "write_error"
    assert "boom" in (result.failures[0].detail or "")
    # Unexpected exceptions should not retry
    assert len(mgr.write_calls) == 1


# ---------------------------------------------------------------------------
# push_to_sandboxes tests
# ---------------------------------------------------------------------------


@patch("onyx.server.features.build.sandbox.base.time.sleep")
def test_push_to_sandboxes_empty_dict(
    mock_sleep: Any,  # noqa: ARG001
    mgr: StubSandboxManager,
) -> None:
    result = mgr.push_to_sandboxes(
        mount_path="/workspace/managed/skills",
        sandbox_files={},
    )
    assert result.targets == 0
    assert result.succeeded == 0
    assert result.failures == []


@patch("onyx.server.features.build.sandbox.base.time.sleep")
def test_push_to_sandboxes_multiple_all_succeed(
    mock_sleep: Any,  # noqa: ARG001
    mgr: StubSandboxManager,
) -> None:
    sb_3 = UUID("00000000-0000-0000-0000-000000000003")
    sandbox_files: dict[UUID, FileSet] = {
        SB_1: {"a.txt": b"aaa"},
        SB_2: {"b.txt": b"bbb"},
        sb_3: {"c.txt": b"ccc"},
    }
    result = mgr.push_to_sandboxes(
        mount_path="/workspace/managed/skills",
        sandbox_files=sandbox_files,
    )
    assert result.targets == 3
    assert result.succeeded == 3
    assert result.failures == []


@patch("onyx.server.features.build.sandbox.base.time.sleep")
def test_push_to_sandboxes_mixed_success_and_failure(
    mock_sleep: Any,  # noqa: ARG001
) -> None:
    """Some sandboxes succeed, some fail with FatalWriteError."""

    sb_ok_1 = UUID("00000000-0000-0000-0000-000000000011")
    sb_ok_2 = UUID("00000000-0000-0000-0000-000000000012")

    class MixedStub(StubSandboxManager):
        def write_files_to_sandbox(
            self,
            *,
            sandbox_id: UUID,
            mount_path: str,
            files: FileSet,
        ) -> None:
            self.write_calls.append(
                {"sandbox_id": sandbox_id, "mount_path": mount_path, "files": files}
            )
            if sandbox_id == SB_FAIL:
                raise FatalWriteError("pod missing")

    mgr = MixedStub()
    sandbox_files: dict[UUID, FileSet] = {
        sb_ok_1: {"a.txt": b"aaa"},
        SB_FAIL: {"b.txt": b"bbb"},
        sb_ok_2: {"c.txt": b"ccc"},
    }
    result = mgr.push_to_sandboxes(
        mount_path="/workspace/managed/skills",
        sandbox_files=sandbox_files,
    )
    assert result.targets == 3
    assert result.succeeded == 2
    assert len(result.failures) == 1
    assert result.failures[0].sandbox_id == SB_FAIL
    assert result.failures[0].reason == "write_error"
