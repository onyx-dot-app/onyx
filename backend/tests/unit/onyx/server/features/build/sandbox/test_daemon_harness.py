"""DaemonHarnessSandbox against a minimal backend: the shared logic reaches
the sandbox only through the hooks, and keeps its contract (session setup
once per instance, exec sessions end with their instance, purge steps run
past a failure)."""

from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from onyx.cache.interface import CacheBackend
from onyx.server.features.build.sandbox import daemon_harness
from onyx.server.features.build.sandbox.daemon_harness import (
    DaemonHarnessSandbox,
    RunningInstance,
)
from onyx.server.features.build.sandbox.firecracker import harness_state
from onyx.server.features.build.sandbox.firecracker.models import (
    ExecSessionRecord,
    SessionSave,
)
from onyx.server.features.build.sandbox.firecracker.session_saves import (
    SessionTransfer,
)
from onyx.server.features.build.sandbox.harness_base import (
    ExecSessionEndedError,
    HarnessSandboxError,
)
from onyx.server.features.build.sandbox.models import (
    HarnessSandboxKey,
    HarnessSandboxRef,
)
from tests.unit.fakes import FakeCache


class _Backend(DaemonHarnessSandbox[RunningInstance]):
    """One instance at a time; `generation` names it. Records each hook."""

    def __init__(self, transfer: SessionTransfer | None) -> None:
        super().__init__(archive_store=None, turn_end_save_interval_seconds=0)
        self.daemon = MagicMock()
        self.generation = 1
        self.running = True
        self.transfer = transfer
        self.calls: list[str] = []
        self.stop_error: Exception | None = None

    def _current(self) -> RunningInstance:
        return RunningInstance(
            daemon=self.daemon, attempt=1, generation=self.generation
        )

    def _instance(self, sandbox: HarnessSandboxKey) -> RunningInstance:  # noqa: ARG002
        self.calls.append("instance")
        return self._current()

    def _instance_if_running(
        self,
        tenant_cache: CacheBackend,  # noqa: ARG002
        sandbox_id: UUID,  # noqa: ARG002
    ) -> RunningInstance | None:
        return self._current() if self.running else None

    def _transfer(self, instance: RunningInstance) -> SessionTransfer | None:  # noqa: ARG002
        return self.transfer

    def _mark_session_set_up(
        self,
        tenant_cache: CacheBackend,
        ref: HarnessSandboxRef,
        instance: RunningInstance,
    ) -> None:
        self.calls.append("mark")
        if instance.identity != self._current().identity:
            raise HarnessSandboxError("stopped")
        harness_state.mark_session_on_instance(
            tenant_cache, ref.sandbox_id, ref.session_id, instance.identity
        )

    def _stop(
        self,
        tenant_id: str,  # noqa: ARG002
        tenant_cache: CacheBackend,  # noqa: ARG002
        sandbox_id: UUID,  # noqa: ARG002
    ) -> None:
        self.calls.append("stop")
        if self.stop_error is not None:
            raise self.stop_error

    def _forget_sandbox(
        self,
        tenant_cache: CacheBackend,  # noqa: ARG002
        sandbox_id: UUID,  # noqa: ARG002
    ) -> None:
        self.calls.append("forget")

    def touch(self, ref: HarnessSandboxRef) -> None:  # noqa: ARG002
        self.calls.append("touch")


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch) -> FakeCache:
    fake = FakeCache()
    monkeypatch.setattr(daemon_harness, "get_cache_backend", lambda **_: fake)
    return fake


@pytest.fixture
def ref() -> HarnessSandboxRef:
    return HarnessSandboxRef(tenant_id="tenant", sandbox_id=uuid4(), session_id=uuid4())


def test_a_session_is_restored_once_per_instance(
    cache: FakeCache, ref: HarnessSandboxRef
) -> None:
    transfer = MagicMock(spec=SessionTransfer)
    backend = _Backend(transfer)
    save = SessionSave(
        file_id="file", size_bytes=3, sha256="abc", roots=["a"], saved_at=1.0
    )
    harness_state.set_session_save(cache, ref.session_id, save)

    backend.stat_files(ref, ["a"])
    backend.stat_files(ref, ["a"])
    transfer.restore.assert_called_once_with(session_id=ref.session_id, save=save)
    assert backend.calls.count("mark") == 1

    # A new instance sets the session up again.
    backend.generation = 2
    backend.stat_files(ref, ["a"])
    assert transfer.restore.call_count == 2
    assert harness_state.sessions_on_instance(cache, ref.sandbox_id, (1, 2)) == [
        ref.session_id
    ]


def test_without_a_transfer_a_session_is_set_up_without_a_restore(
    cache: FakeCache, ref: HarnessSandboxRef
) -> None:
    backend = _Backend(None)
    backend.stat_files(ref, ["a"])
    assert backend.calls == ["instance", "mark"]
    assert harness_state.sessions_on_instance(cache, ref.sandbox_id, (1, 1)) == [
        ref.session_id
    ]


def test_an_exec_session_ends_with_its_instance(
    cache: FakeCache, ref: HarnessSandboxRef
) -> None:
    backend = _Backend(None)
    record = ExecSessionRecord(
        exec_session_id="s1",
        chat_session_id=str(ref.session_id),
        execution_id="e1",
        attempt=1,
        generation=1,
        last_used=1.0,
    )
    harness_state.put_exec_session(cache, ref.sandbox_id, record)
    backend.generation = 2

    with pytest.raises(ExecSessionEndedError):
        list(backend.write_stdin(ref, "s1"))
    assert harness_state.get_exec_session(cache, ref.sandbox_id, "s1") is None
    backend.daemon.interact.assert_not_called()


def test_a_session_purge_cancels_only_its_commands_on_the_running_instance(
    cache: FakeCache, ref: HarnessSandboxRef
) -> None:
    backend = _Backend(None)
    other = uuid4()
    for exec_id, session, generation in (
        ("mine", ref.session_id, 1),
        ("old", ref.session_id, 0),
        ("other", other, 1),
    ):
        harness_state.put_exec_session(
            cache,
            ref.sandbox_id,
            ExecSessionRecord(
                exec_session_id=exec_id,
                chat_session_id=str(session),
                execution_id=f"e-{exec_id}",
                attempt=1,
                generation=generation,
                last_used=1.0,
            ),
        )

    backend.purge_session(
        tenant_id=ref.tenant_id, sandbox_id=ref.sandbox_id, session_id=ref.session_id
    )

    backend.daemon.cancel.assert_called_once_with("e-mine")
    assert harness_state.get_exec_session(cache, ref.sandbox_id, "mine") is None
    assert harness_state.get_exec_session(cache, ref.sandbox_id, "old") is None
    assert harness_state.get_exec_session(cache, ref.sandbox_id, "other") is not None
    assert harness_state.is_purged(cache, ref.sandbox_id, ref.session_id)
    # The sandbox is never started for a purge.
    assert "instance" not in backend.calls


def test_a_sandbox_purge_forgets_the_sandbox_when_its_stop_fails(
    cache: FakeCache, ref: HarnessSandboxRef
) -> None:
    backend = _Backend(None)
    backend.stop_error = RuntimeError("agent down")
    harness_state.mark_session_on_instance(
        cache, ref.sandbox_id, ref.session_id, (1, 1)
    )

    with pytest.raises(RuntimeError, match="agent down"):
        backend.purge_sandbox(tenant_id=ref.tenant_id, sandbox_id=ref.sandbox_id)

    assert backend.calls == ["stop", "forget"]
    assert harness_state.sessions_on_instance(cache, ref.sandbox_id, (1, 1)) == []
