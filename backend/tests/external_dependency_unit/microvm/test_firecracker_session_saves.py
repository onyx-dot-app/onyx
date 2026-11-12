"""Session saves and hydrate of FirecrackerHarnessSandbox against Redis and
fake host agents: save on sleep, restore on the next use, busy and failure
cases keep the VM, and the idle evictor stops only after a save."""

import hashlib
import time
from collections.abc import Callable, Generator
from typing import Protocol
from uuid import UUID, uuid4

import grpc
import pytest
from pydantic import SecretStr

from onyx.cache.factory import get_cache_backend, get_shared_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.microvm import placement, registry
from onyx.microvm.configs import SANDBOX_FC_IDLE_TIMEOUT_SECONDS
from onyx.microvm.daemon_client import (
    SandboxDaemonClient,
    SandboxDaemonError,
    SandboxDaemonErrorReason,
)
from onyx.microvm.generated.hostagent.v1 import hostagent_pb2
from onyx.microvm.lifecycle import (
    NoCheckpointSupport,
    UnknownActivity,
    VmStopOutcome,
    evict_idle_sandbox_vm,
)
from onyx.microvm.models import PresignedRequest
from onyx.microvm.registry import get_sandbox_placement
from onyx.server.features.build.sandbox import harness_factory
from onyx.server.features.build.sandbox.firecracker import (
    harness_sandbox,
    harness_state,
    session_saves,
)
from onyx.server.features.build.sandbox.firecracker.harness_sandbox import (
    FirecrackerHarnessSandbox,
)
from onyx.server.features.build.sandbox.firecracker.session_saves import (
    BackgroundIdleStop,
    SessionArchiveStore,
)
from onyx.server.features.build.sandbox.harness_base import (
    ExecCapReachedError,
    ExecSessionEndedError,
    HarnessSandboxError,
    HarnessSandboxRef,
    collect_exec_result,
)
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.microvm.conftest import (
    TENANT_ID,
    AddNode,
    NewSandboxId,
)
from tests.external_dependency_unit.microvm.fake_agent import (
    InsecureClientFactory,
    RunningFakeAgent,
)


class FakeArchiveStore(SessionArchiveStore):
    """Object storage in the fake agent's presigned "objects"."""

    def __init__(self, node: RunningFakeAgent) -> None:
        self.node = node
        self.pending: dict[str, tuple[str, int, str]] = {}
        self.deleted: list[str] = []
        self.downloads = 0
        self.fail_next_presign = False
        self.presign_delay_seconds = 0.0
        self.presign_tenants: list[str | None] = []
        self.download_tenants: list[str | None] = []
        self.on_presign: Callable[[], None] | None = None

    def presign_upload(self, *, size: int, sha256: str) -> tuple[str, PresignedRequest]:
        self.presign_tenants.append(CURRENT_TENANT_ID_CONTEXTVAR.get())
        time.sleep(self.presign_delay_seconds)
        if self.on_presign is not None:
            self.on_presign()
        if self.fail_next_presign:
            self.fail_next_presign = False
            raise RuntimeError("presign failed")
        pending_id = uuid4().hex
        url = f"https://store.test/{uuid4().hex}"
        self.pending[pending_id] = (url, size, sha256)
        return pending_id, PresignedRequest(
            url=SecretStr(url), method="PUT", headers={"Content-Length": str(size)}
        )

    def finalize(self, pending_upload_id: str) -> str:
        url, size, sha256 = self.pending.pop(pending_upload_id)
        data = self.node.agent.objects[url]
        assert len(data) == size and hashlib.sha256(data).hexdigest() == sha256
        return url

    def presign_download(self, file_id: str) -> PresignedRequest:
        self.downloads += 1
        self.download_tenants.append(CURRENT_TENANT_ID_CONTEXTVAR.get())
        return PresignedRequest(url=SecretStr(file_id), method="GET")

    def delete(self, file_id: str) -> None:
        self.deleted.append(file_id)
        self.node.agent.objects.pop(file_id, None)


class MakeSandbox(Protocol):
    def __call__(
        self, *, archive_store: SessionArchiveStore | None = ...
    ) -> FirecrackerHarnessSandbox: ...


@pytest.fixture
def node(add_node: AddNode) -> RunningFakeAgent:
    return add_node(f"fcs-{uuid4().hex[:6]}")


@pytest.fixture
def store(node: RunningFakeAgent) -> FakeArchiveStore:
    return FakeArchiveStore(node)


@pytest.fixture
def make_sandbox(
    client_factory: InsecureClientFactory, store: FakeArchiveStore
) -> MakeSandbox:
    def make(
        *, archive_store: SessionArchiveStore | None = store
    ) -> FirecrackerHarnessSandbox:
        return FirecrackerHarnessSandbox(
            template="tpl-1", client_factory=client_factory, archive_store=archive_store
        )

    return make


@pytest.fixture
def ref(
    tenant_cache: CacheBackend, new_sandbox_id: NewSandboxId
) -> Generator[HarnessSandboxRef, None, None]:
    ref = HarnessSandboxRef(
        tenant_id=TENANT_ID, sandbox_id=new_sandbox_id(), session_id=uuid4()
    )
    yield ref
    for prefix in (
        harness_state.EXEC_SESSIONS_PREFIX,
        harness_state.ACTIVITY_PREFIX,
        harness_state.SESSION_INSTANCES_PREFIX,
        harness_state.LAST_ATTEMPT_PREFIX,
    ):
        tenant_cache.delete(prefix + str(ref.sandbox_id))
    tenant_cache.delete(harness_state.SESSION_SAVE_PREFIX + str(ref.session_id))


def _sleep(sandbox: FirecrackerHarnessSandbox, sandbox_id: UUID) -> VmStopOutcome:
    """The idle stop of the sandbox now, as if it were idle long enough."""
    return evict_idle_sandbox_vm(
        get_shared_cache_backend(),
        get_cache_backend(tenant_id=TENANT_ID),
        sandbox._client_factory,
        sandbox.session_checkpointer() or NoCheckpointSupport(),
        sandbox,
        tenant_id=TENANT_ID,
        sandbox_id=sandbox_id,
        last_active=0,
        now=int(time.time()),
    )


def _make_idle(tenant_cache: CacheBackend, sandbox_id: UUID) -> None:
    placed = get_sandbox_placement(tenant_cache, sandbox_id)
    assert placed is not None
    tenant_cache.set(
        registry._PLACEMENT_PREFIX + str(sandbox_id),
        registry._placement_record(placed.model_copy(update={"last_active": 1})),
    )


def _session_files(node: RunningFakeAgent, ref: HarnessSandboxRef) -> dict[str, bytes]:
    return {
        path: data
        for (sid, session, path), data in node.agent.files.items()
        if sid == str(ref.sandbox_id) and session == str(ref.session_id)
    }


def test_sleep_saves_the_session_and_the_next_use_restores_it(
    tenant_cache: CacheBackend,
    make_sandbox: MakeSandbox,
    node: RunningFakeAgent,
    store: FakeArchiveStore,
    ref: HarnessSandboxRef,
) -> None:
    sandbox = make_sandbox()
    sandbox.write_file(ref, "src/app.py", b"print(1)\n")
    sandbox.write_file(ref, "out/report.md", b"# Report\n")
    sandbox.write_file(ref, "report.py", b"print(2)\n")
    sandbox.write_file(ref, "node_modules/x/index.js", b"dependency")
    sandbox.write_file(ref, ".pytest_cache/v/cache", b"cache")
    sandbox.write_file(ref, "env-3.12/pyvenv.cfg", b"home = /usr/bin\n")
    result = collect_exec_result(
        sandbox.exec_command(ref, "sleep 60", yield_time_ms=250)
    )
    assert result.exec_session_id is not None
    collect_exec_result(sandbox.write_stdin(ref, result.exec_session_id, "\x03"))

    assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.STOPPED
    save = harness_state.get_session_save(tenant_cache, ref.session_id)
    assert save is not None and save.file_id in node.agent.objects
    assert save.roots == [".onyx-top-level", "out", "src"]
    assert get_sandbox_placement(tenant_cache, ref.sandbox_id) is None
    assert _session_files(node, ref) == {}

    # Another pod uses the session again: a new VM, the files come back.
    other_pod = make_sandbox()
    assert other_pod.read_file(ref, "src/app.py", max_bytes=100) == b"print(1)\n"
    assert _session_files(node, ref) == {
        "src/app.py": b"print(1)\n",
        "out/report.md": b"# Report\n",
        "report.py": b"print(2)\n",
    }
    assert node.agent.create_calls == 2
    assert store.downloads == 1
    # Restored once per VM instance, on any pod.
    sandbox.read_file(ref, "out/report.md", max_bytes=100)
    collect_exec_result(sandbox.exec_command(ref, "echo hi"))
    assert store.downloads == 1


def test_a_new_save_replaces_the_old_one_and_deletes_its_archive(
    tenant_cache: CacheBackend,
    make_sandbox: MakeSandbox,
    store: FakeArchiveStore,
    ref: HarnessSandboxRef,
) -> None:
    sandbox = make_sandbox()
    sandbox.write_file(ref, "src/a.txt", b"one")
    assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.STOPPED
    first = harness_state.get_session_save(tenant_cache, ref.session_id)
    assert first is not None and first.file_id is not None

    sandbox.write_file(ref, "src/a.txt", b"two")
    assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.STOPPED
    second = harness_state.get_session_save(tenant_cache, ref.session_id)
    assert second is not None and second.file_id != first.file_id
    assert store.deleted == [first.file_id]
    assert sandbox.read_file(ref, "src/a.txt", max_bytes=10) == b"two"


def test_a_busy_sandbox_is_not_saved_or_stopped(
    make_sandbox: MakeSandbox,
    node: RunningFakeAgent,
    ref: HarnessSandboxRef,
) -> None:
    sandbox = make_sandbox()
    sandbox.write_file(ref, "src/a.txt", b"x")

    sandbox.begin_turn(ref)
    assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.KEPT_BUSY
    sandbox.end_turn(ref)

    sandbox.set_approval_parked(ref, True)
    assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.KEPT_BUSY
    sandbox.set_approval_parked(ref, False)

    result = collect_exec_result(
        sandbox.exec_command(ref, "sleep 60", yield_time_ms=250)
    )
    assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.KEPT_BUSY
    assert node.agent.captures == {} and node.agent.objects == {}
    assert node.agent.stop_calls == []

    # Idle now: the save runs and the command's session ends with the VM.
    assert result.exec_session_id is not None
    collect_exec_result(sandbox.write_stdin(ref, result.exec_session_id, "\x03"))
    assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.STOPPED


def test_a_failed_save_keeps_the_vm_and_the_old_save(
    tenant_cache: CacheBackend,
    make_sandbox: MakeSandbox,
    store: FakeArchiveStore,
    ref: HarnessSandboxRef,
) -> None:
    sandbox = make_sandbox()
    sandbox.write_file(ref, "src/a.txt", b"one")
    assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.STOPPED
    first = harness_state.get_session_save(tenant_cache, ref.session_id)

    sandbox.write_file(ref, "src/a.txt", b"two")
    store.fail_next_presign = True
    assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.KEPT_NO_CHECKPOINT
    assert harness_state.get_session_save(tenant_cache, ref.session_id) == first
    # The VM still runs with its files.
    assert get_sandbox_placement(tenant_cache, ref.sandbox_id) is not None
    assert sandbox.read_file(ref, "src/a.txt", max_bytes=10) == b"two"


def test_a_session_with_nothing_to_save_commits_an_empty_save(
    tenant_cache: CacheBackend,
    make_sandbox: MakeSandbox,
    node: RunningFakeAgent,
    ref: HarnessSandboxRef,
) -> None:
    sandbox = make_sandbox()
    collect_exec_result(sandbox.exec_command(ref, "echo hi"))
    assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.STOPPED
    save = harness_state.get_session_save(tenant_cache, ref.session_id)
    assert save is not None and save.file_id is None
    assert node.agent.objects == {}


def test_exec_sessions_end_after_a_sleep(
    tenant_cache: CacheBackend,
    make_sandbox: MakeSandbox,
    ref: HarnessSandboxRef,
) -> None:
    sandbox = make_sandbox()
    started = collect_exec_result(sandbox.exec_command(ref, "cat", yield_time_ms=250))
    assert started.exec_session_id is not None
    assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.KEPT_BUSY

    # The command ends with no poll: its record stays until the VM stops.
    record = harness_state.get_exec_session(
        tenant_cache, ref.sandbox_id, started.exec_session_id
    )
    assert record is not None
    sandbox._session_vm(ref)[1].cancel(record.execution_id)
    assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.STOPPED
    with pytest.raises(ExecSessionEndedError):
        collect_exec_result(sandbox.write_stdin(ref, started.exec_session_id))


def test_the_idle_evictor_stops_only_an_idle_saved_sandbox(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    make_sandbox: MakeSandbox,
    ref: HarnessSandboxRef,
) -> None:
    sandbox = make_sandbox()
    sandbox.write_file(ref, "src/a.txt", b"x")
    checkpointer = sandbox.session_checkpointer()
    assert checkpointer is not None
    now = int(time.time())

    def evict(last_active: int) -> VmStopOutcome:
        return evict_idle_sandbox_vm(
            shared_cache,
            tenant_cache,
            client_factory,
            checkpointer,
            sandbox,
            tenant_id=TENANT_ID,
            sandbox_id=ref.sandbox_id,
            last_active=last_active,
            now=now,
        )

    assert evict(now) is VmStopOutcome.NOT_IDLE
    idle = now - SANDBOX_FC_IDLE_TIMEOUT_SECONDS - 1
    sandbox.begin_turn(ref)
    assert evict(idle) is VmStopOutcome.KEPT_BUSY
    sandbox.end_turn(ref)
    assert evict(idle) is VmStopOutcome.STOPPED
    assert harness_state.get_session_save(tenant_cache, ref.session_id) is not None


def test_without_an_archive_store_no_vm_is_stopped(
    make_sandbox: MakeSandbox,
    node: RunningFakeAgent,
    ref: HarnessSandboxRef,
) -> None:
    sandbox = make_sandbox(archive_store=None)
    sandbox.write_file(ref, "src/a.txt", b"x")
    checkpointer, _ = sandbox.eviction_policy()
    assert isinstance(checkpointer, NoCheckpointSupport)
    assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.KEPT_NO_CHECKPOINT
    assert node.agent.stop_calls == []


def test_the_eviction_policy_is_off_without_harness_sandboxes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(harness_factory, "_instance", None)
    monkeypatch.setattr(harness_factory, "FIRECRACKER_ENABLED", False)
    checkpointer, _ = harness_factory.get_eviction_policy()
    assert isinstance(checkpointer, NoCheckpointSupport)


def test_a_session_is_not_recorded_on_a_vm_that_stopped_during_its_setup(
    monkeypatch: pytest.MonkeyPatch,
    tenant_cache: CacheBackend,
    make_sandbox: MakeSandbox,
    node: RunningFakeAgent,
    ref: HarnessSandboxRef,
) -> None:
    sandbox = make_sandbox()
    sandbox.ensure_running(ref)
    real_restore = harness_sandbox.restore_session

    def stopped_meanwhile(*args: object, **kwargs: object) -> None:  # noqa: ARG001
        # An idle stop saved and stopped the VM during the restore.
        node.agent.vms[str(ref.sandbox_id)].state = hostagent_pb2.VM_STATE_EXITED
        registry.clear_sandbox_placement(tenant_cache, ref.sandbox_id)

    monkeypatch.setattr(harness_sandbox, "restore_session", stopped_meanwhile)
    with pytest.raises(HarnessSandboxError, match="stopped while this session"):
        sandbox.read_file(ref, "a.txt", max_bytes=10)
    assert (
        harness_state.sessions_on_instance(tenant_cache, ref.sandbox_id, (1, 1001))
        == []
    )

    # The next call wakes a new VM and sets the session up there.
    monkeypatch.setattr(harness_sandbox, "restore_session", real_restore)
    sandbox.write_file(ref, "a.txt", b"x")
    placement = get_sandbox_placement(tenant_cache, ref.sandbox_id)
    assert placement is not None
    instance = (placement.attempt, placement.generation)
    assert harness_state.sessions_on_instance(
        tenant_cache, ref.sandbox_id, instance
    ) == [ref.session_id]
    # The setup takes no command slot.
    assert node.agent.executions.get(str(ref.sandbox_id), {}) == {}


def test_file_calls_of_a_new_session_work_when_command_slots_are_full(
    make_sandbox: MakeSandbox,
    node: RunningFakeAgent,
    ref: HarnessSandboxRef,
) -> None:
    sandbox = make_sandbox()
    node.agent.max_running_executions = 1
    first = collect_exec_result(sandbox.exec_command(ref, "cat", yield_time_ms=250))
    assert first.exec_session_id is not None

    other = ref.model_copy(update={"session_id": uuid4()})
    sandbox.write_file(other, "a.txt", b"x")
    assert sandbox.read_file(other, "a.txt", max_bytes=10) == b"x"
    another = ref.model_copy(update={"session_id": uuid4()})
    with pytest.raises(ExecCapReachedError):
        collect_exec_result(sandbox.exec_command(another, "echo hi"))


def test_a_session_without_a_directory_saves_nothing_and_keeps_its_save(
    monkeypatch: pytest.MonkeyPatch,
    tenant_cache: CacheBackend,
    make_sandbox: MakeSandbox,
    node: RunningFakeAgent,
    ref: HarnessSandboxRef,
) -> None:
    def no_directory(*_args: object, **_kwargs: object) -> None:
        raise SandboxDaemonError(
            grpc.StatusCode.NOT_FOUND,
            "no session",
            SandboxDaemonErrorReason.FILE_NOT_FOUND,
        )

    sandbox = make_sandbox()
    sandbox.write_file(ref, "src/a.txt", b"x")
    assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.STOPPED
    saved = harness_state.get_session_save(tenant_cache, ref.session_id)
    assert saved is not None and saved.file_id is not None

    # The next VM has no directory for the session: the save stays.
    with pytest.raises(SandboxDaemonError):
        sandbox.read_file(ref, "missing.txt", max_bytes=10)
    monkeypatch.setattr(SandboxDaemonClient, "list_files", no_directory)
    assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.STOPPED
    assert harness_state.get_session_save(tenant_cache, ref.session_id) == saved
    assert node.agent.objects.get(saved.file_id) is not None

    # A session with no save and no directory commits an empty save.
    fresh = ref.model_copy(update={"session_id": uuid4()})
    try:
        monkeypatch.undo()
        sandbox.write_file(fresh, "b.txt", b"y")
        monkeypatch.setattr(SandboxDaemonClient, "list_files", no_directory)
        assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.STOPPED
        empty = harness_state.get_session_save(tenant_cache, fresh.session_id)
        assert empty is not None and empty.file_id is None
    finally:
        tenant_cache.delete(harness_state.SESSION_SAVE_PREFIX + str(fresh.session_id))


def test_a_stop_that_loses_the_sandbox_lock_during_saves_keeps_the_vm(
    tenant_cache: CacheBackend,
    make_sandbox: MakeSandbox,
    node: RunningFakeAgent,
    store: FakeArchiveStore,
    ref: HarnessSandboxRef,
) -> None:
    sandbox = make_sandbox()
    second = ref.model_copy(update={"session_id": uuid4()})
    sandbox.write_file(ref, "src/a.txt", b"x")
    sandbox.write_file(second, "src/b.txt", b"y")

    def lease_expires() -> None:
        store.on_presign = None
        tenant_cache.delete(placement._PLACEMENT_LOCK_PREFIX + str(ref.sandbox_id))

    store.on_presign = lease_expires
    try:
        assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.KEPT_NO_CHECKPOINT
        assert node.agent.stop_calls == []
        saves = [
            harness_state.get_session_save(tenant_cache, r.session_id)
            for r in (ref, second)
        ]
        # The first save commits; the second never starts.
        assert sum(s is not None for s in saves) == 1
        assert len(store.presign_tenants) == 1
    finally:
        tenant_cache.delete(harness_state.SESSION_SAVE_PREFIX + str(second.session_id))


def test_the_idle_stop_executor_starts_on_first_use(
    make_sandbox: MakeSandbox,
) -> None:
    assert make_sandbox().idle_stop._executor is None


def test_a_file_store_config_error_turns_eviction_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken() -> None:
        raise RuntimeError("bad file store config")

    monkeypatch.setattr(harness_factory, "_instance", None)
    monkeypatch.setattr(harness_factory, "_eviction_error_logged", False)
    monkeypatch.setattr(harness_factory, "FIRECRACKER_ENABLED", True)
    monkeypatch.setattr(harness_factory, "SANDBOX_FC_TEMPLATE", "tpl-1")
    monkeypatch.setattr(session_saves, "default_archive_store", broken)
    for _ in range(2):
        checkpointer, activity = harness_factory.get_eviction_policy()
        assert isinstance(checkpointer, NoCheckpointSupport)
        assert isinstance(activity, UnknownActivity)
    assert harness_factory._eviction_error_logged


def test_record_attempt_never_lowers_the_stored_attempt(
    monkeypatch: pytest.MonkeyPatch, tenant_cache: CacheBackend
) -> None:
    sandbox_id = uuid4()
    key = harness_state.LAST_ATTEMPT_PREFIX + str(sandbox_id)
    try:
        harness_state.record_attempt(tenant_cache, sandbox_id, 3)
        harness_state.record_attempt(tenant_cache, sandbox_id, 2)
        assert harness_state.last_attempt(tenant_cache, sandbox_id) == 3

        # A pod read attempt 1 before another pod stored 3.
        real_get = tenant_cache.get
        stale = iter([b"1"])
        monkeypatch.setattr(
            tenant_cache, "get", lambda k: next(stale, None) or real_get(k)
        )
        harness_state.record_attempt(tenant_cache, sandbox_id, 2)
        monkeypatch.setattr(tenant_cache, "get", real_get)
        assert harness_state.last_attempt(tenant_cache, sandbox_id) == 3
    finally:
        tenant_cache.delete(key)


def test_a_wake_after_sleep_starts_past_the_stopped_attempt(
    tenant_cache: CacheBackend,
    make_sandbox: MakeSandbox,
    ref: HarnessSandboxRef,
) -> None:
    sandbox = make_sandbox()
    later = ref.model_copy(update={"attempt": 3})
    sandbox.write_file(later, "src/a.txt", b"x")
    assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.STOPPED

    # The row's attempt (1) is lower; the agent will not create 3 again.
    assert sandbox.read_file(ref, "src/a.txt", max_bytes=10) == b"x"
    placement = get_sandbox_placement(tenant_cache, ref.sandbox_id)
    assert placement is not None and placement.attempt == 4
    result = collect_exec_result(sandbox.exec_command(ref, "echo ok"))
    assert result.output == "ok\n"


def test_a_save_runs_in_the_sandbox_tenant(
    make_sandbox: MakeSandbox,
    store: FakeArchiveStore,
    ref: HarnessSandboxRef,
) -> None:
    sandbox = make_sandbox()
    sandbox.write_file(ref, "src/a.txt", b"x")
    token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_other")
    try:
        assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.STOPPED
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    assert store.presign_tenants == [TENANT_ID]
    # The restore signs in the sandbox tenant too.
    token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_other")
    try:
        assert sandbox.read_file(ref, "src/a.txt", max_bytes=10) == b"x"
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    assert store.download_tenants == [TENANT_ID]


def test_a_truncated_listing_keeps_the_vm(
    tenant_cache: CacheBackend,
    make_sandbox: MakeSandbox,
    node: RunningFakeAgent,
    ref: HarnessSandboxRef,
) -> None:
    sandbox = make_sandbox()
    sandbox.write_file(ref, "src/a.txt", b"x")
    sandbox.write_file(ref, "docs/b.txt", b"y")
    node.agent.list_max_entries = 1
    assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.KEPT_NO_CHECKPOINT
    assert harness_state.get_session_save(tenant_cache, ref.session_id) is None
    assert node.agent.stop_calls == []


def test_a_slow_save_keeps_the_sandbox_lock(
    monkeypatch: pytest.MonkeyPatch,
    make_sandbox: MakeSandbox,
    store: FakeArchiveStore,
    ref: HarnessSandboxRef,
) -> None:
    monkeypatch.setattr(placement, "_LOCK_LEASE_SECONDS", 1)
    sandbox = make_sandbox()
    sandbox.write_file(ref, "src/a.txt", b"x")
    store.presign_delay_seconds = 1.5
    assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.STOPPED


def test_the_report_evictor_stops_in_the_background(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    make_sandbox: MakeSandbox,
    ref: HarnessSandboxRef,
) -> None:
    sandbox = make_sandbox()
    sandbox.write_file(ref, "src/a.txt", b"x")
    _make_idle(tenant_cache, ref.sandbox_id)
    checkpointer, activity = sandbox.eviction_policy()
    now = int(time.time())
    outcome = evict_idle_sandbox_vm(
        shared_cache,
        tenant_cache,
        client_factory,
        checkpointer,
        activity,
        tenant_id=TENANT_ID,
        sandbox_id=ref.sandbox_id,
        last_active=now - SANDBOX_FC_IDLE_TIMEOUT_SECONDS - 1,
        now=now,
    )
    # The report keeps the VM; the background stop saves and stops it.
    assert outcome is VmStopOutcome.KEPT_NO_CHECKPOINT
    assert isinstance(checkpointer, BackgroundIdleStop)
    pending = checkpointer.running.get(ref.sandbox_id)
    if pending is not None:
        pending.result(timeout=30)
    assert get_sandbox_placement(tenant_cache, ref.sandbox_id) is None
    assert harness_state.get_session_save(tenant_cache, ref.session_id) is not None


def test_repeated_sleeps_wake_past_stopped_attempts(
    tenant_cache: CacheBackend,
    make_sandbox: MakeSandbox,
    node: RunningFakeAgent,
    ref: HarnessSandboxRef,
) -> None:
    node.agent.remember_stopped_attempts = True
    sandbox = make_sandbox()
    sandbox.write_file(ref, "src/a.txt", b"x")
    for expected_attempt in (1, 2, 3, 4):
        placement = get_sandbox_placement(tenant_cache, ref.sandbox_id)
        assert placement is not None and placement.attempt == expected_attempt
        assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.STOPPED
        assert sandbox.read_file(ref, "src/a.txt", max_bytes=10) == b"x"


def test_a_queued_idle_stop_skips_a_sandbox_that_is_used_again(
    tenant_cache: CacheBackend,
    make_sandbox: MakeSandbox,
    node: RunningFakeAgent,
    ref: HarnessSandboxRef,
) -> None:
    sandbox = make_sandbox()
    sandbox.write_file(ref, "src/a.txt", b"x")
    # The report queued the stop; the sandbox was used after that.
    outcome = sandbox._stop_if_idle(TENANT_ID, ref.sandbox_id)
    assert outcome is VmStopOutcome.NOT_IDLE
    assert node.agent.stop_calls == []
    _make_idle(tenant_cache, ref.sandbox_id)
    assert sandbox._stop_if_idle(TENANT_ID, ref.sandbox_id) is VmStopOutcome.STOPPED


def test_a_turn_that_begins_during_the_save_keeps_the_vm(
    tenant_cache: CacheBackend,
    make_sandbox: MakeSandbox,
    store: FakeArchiveStore,
    node: RunningFakeAgent,
    ref: HarnessSandboxRef,
) -> None:
    sandbox = make_sandbox()
    sandbox.write_file(ref, "src/a.txt", b"x")
    store.on_presign = lambda: sandbox.begin_turn(ref)
    assert _sleep(sandbox, ref.sandbox_id) is VmStopOutcome.KEPT_NO_CHECKPOINT
    assert node.agent.stop_calls == []
    assert get_sandbox_placement(tenant_cache, ref.sandbox_id) is not None
