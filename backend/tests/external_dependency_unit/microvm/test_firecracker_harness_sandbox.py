"""FirecrackerHarnessSandbox against Redis and fake host agents: lifecycle,
the Codex exec contract with durable exec sessions, files, artifacts, the
managed drive and the busy signals."""

import io
import threading
import time
import zipfile
from collections.abc import Callable, Generator, Iterator
from uuid import UUID, uuid4

import pytest

from onyx.cache.interface import CacheBackend
from onyx.file_store.file_store import get_default_file_store
from onyx.microvm import registry
from onyx.microvm.generated.hostagent.v1 import hostagent_pb2
from onyx.microvm.models import OutputStream
from onyx.microvm.registry import get_sandbox_daemon_key, get_sandbox_placement
from onyx.server.features.build.sandbox import harness_factory
from onyx.server.features.build.sandbox.exec_output import (
    ExecOutputBuffer,
    cut_to_tokens,
)
from onyx.server.features.build.sandbox.firecracker import (
    harness_sandbox,
    harness_state,
)
from onyx.server.features.build.sandbox.firecracker.harness_sandbox import (
    FirecrackerHarnessSandbox,
    ManagedBundleSource,
    session_relative_path,
)
from onyx.server.features.build.sandbox.harness_base import (
    EXEC_DEFAULT_ENV,
    MAX_EXEC_SESSIONS_PER_SANDBOX,
    ExecCommandResult,
    ExecEvent,
    ExecOutputDelta,
    ExecSessionEndedError,
    ExecSessionNotFoundError,
    HarnessSandboxRef,
    SandboxFileTooLargeError,
    SandboxPathError,
    collect_exec_result,
    session_workspace,
)
from tests.external_dependency_unit.microvm.conftest import (
    TENANT_ID,
    AddNode,
    NewSandboxId,
)
from tests.external_dependency_unit.microvm.fake_agent import (
    InsecureClientFactory,
    RunningFakeAgent,
)

MakeSandbox = Callable[..., FirecrackerHarnessSandbox]
NewRef = Callable[[], HarnessSandboxRef]


@pytest.fixture
def make_sandbox(client_factory: InsecureClientFactory) -> MakeSandbox:
    """A sandbox per "API pod": they share only the cache."""

    def make(
        *,
        managed_bundle: ManagedBundleSource | None = None,
        max_exec_sessions: int = MAX_EXEC_SESSIONS_PER_SANDBOX,
    ) -> FirecrackerHarnessSandbox:
        return FirecrackerHarnessSandbox(
            template="tpl-1",
            client_factory=client_factory,
            init_env={"CRAFT_TEST": "1"},
            managed_bundle=managed_bundle,
            max_exec_sessions=max_exec_sessions,
        )

    return make


@pytest.fixture
def sandbox(make_sandbox: MakeSandbox) -> FirecrackerHarnessSandbox:
    return make_sandbox()


@pytest.fixture
def new_ref(
    tenant_cache: CacheBackend, new_sandbox_id: NewSandboxId
) -> Generator[NewRef, None, None]:
    refs: list[HarnessSandboxRef] = []

    def new() -> HarnessSandboxRef:
        refs.append(
            HarnessSandboxRef(
                tenant_id=TENANT_ID, sandbox_id=new_sandbox_id(), session_id=uuid4()
            )
        )
        return refs[-1]

    yield new
    for ref in refs:
        harness_state.clear_exec_sessions(tenant_cache, ref.sandbox_id)
        harness_state.clear_activity(tenant_cache, ref.sandbox_id)
        tenant_cache.delete(harness_sandbox._MANAGED_PREFIX + str(ref.sandbox_id))


@pytest.fixture
def node(add_node: AddNode) -> RunningFakeAgent:
    return add_node(f"fch-{uuid4().hex[:6]}")


def _run(events: Iterator[ExecEvent]) -> tuple[list[str], ExecCommandResult]:
    """The streamed deltas and the result."""
    deltas: list[str] = []
    result: ExecCommandResult | None = None
    for event in events:
        if isinstance(event, ExecOutputDelta):
            deltas.append(event.text)
        else:
            assert isinstance(event, ExecCommandResult)
            result = event
    assert result is not None
    return deltas, result


def _session_ref(ref: HarnessSandboxRef) -> HarnessSandboxRef:
    """Another chat session of the same sandbox."""
    return ref.model_copy(update={"session_id": uuid4()})


# Lifecycle


def test_ensure_running_is_idempotent_with_one_init_per_boot(
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    sandbox.ensure_running(ref)
    assert node.agent.create_calls == 1
    assert len(node.agent.init_requests) == 1
    init, routed_to = node.agent.init_requests[0]
    assert routed_to == str(ref.sandbox_id)
    assert dict(init.env) == {**EXEC_DEFAULT_ENV, "CRAFT_TEST": "1"}
    placement = get_sandbox_placement(tenant_cache, ref.sandbox_id)
    assert placement is not None and init.generation == placement.generation

    sandbox.ensure_running(ref)
    assert node.agent.create_calls == 1
    assert len(node.agent.init_requests) == 1

    # A running VM whose daemon has no Init (an adopted VM): Init it.
    node.agent.daemon_inits.pop(str(ref.sandbox_id))
    sandbox.ensure_running(ref)
    assert node.agent.create_calls == 1
    assert len(node.agent.init_requests) == 2


def test_ensure_running_replaces_a_vm_whose_daemon_rejects_the_key(
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    sandbox.ensure_running(ref)

    node.agent.daemon_keys[str(ref.sandbox_id)] = "another-key-" + "x" * 32
    node.agent.daemon_inits.pop(str(ref.sandbox_id))
    sandbox.ensure_running(ref)

    placement = get_sandbox_placement(tenant_cache, ref.sandbox_id)
    assert placement is not None and placement.attempt == 2
    assert node.agent.create_calls == 2
    assert len(node.agent.stop_calls) == 1


def test_terminate_stops_the_exact_instance_and_clears_records(
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    _, running = _run(sandbox.exec_command(ref, "sleep 60", yield_time_ms=250))
    assert running.exec_session_id is not None
    sandbox.begin_turn(ref)
    placement = get_sandbox_placement(tenant_cache, ref.sandbox_id)
    assert placement is not None

    sandbox.terminate(tenant_id=TENANT_ID, sandbox_id=ref.sandbox_id)
    assert node.agent.stop_calls == [
        (str(ref.sandbox_id), placement.attempt, placement.generation)
    ]
    assert get_sandbox_placement(tenant_cache, ref.sandbox_id) is None
    assert (
        get_sandbox_daemon_key(tenant_cache, ref.sandbox_id, attempt=placement.attempt)
        is None
    )
    assert harness_state.list_exec_sessions(tenant_cache, ref.sandbox_id) == []
    assert not harness_state.has_activity(tenant_cache, ref.sandbox_id)

    # Nothing placed: a repeat terminate is a no-op.
    sandbox.terminate(tenant_id=TENANT_ID, sandbox_id=ref.sandbox_id)
    assert len(node.agent.stop_calls) == 1


def test_terminate_on_an_unregistered_node_clears_the_record(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    add_node: AddNode,
    new_ref: NewRef,
) -> None:
    node_id = f"fch-{uuid4().hex[:6]}"
    running = add_node(node_id)
    ref = new_ref()
    sandbox.ensure_running(ref)
    shared_cache.delete(registry._NODE_ADDRESS_PREFIX + node_id)

    sandbox.terminate(tenant_id=TENANT_ID, sandbox_id=ref.sandbox_id)
    assert get_sandbox_placement(tenant_cache, ref.sandbox_id) is None
    assert running.agent.stop_calls == []


def test_health_never_starts_a_vm(
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()

    def healthy() -> bool:
        return sandbox.health(
            tenant_id=TENANT_ID, sandbox_id=ref.sandbox_id, timeout=2.0
        )

    assert healthy() is False
    assert node.agent.create_calls == 0

    sandbox.ensure_running(ref)
    assert healthy() is True

    node.agent.daemon_inits.pop(str(ref.sandbox_id))
    assert healthy() is False

    node.agent.vms[str(ref.sandbox_id)].state = hostagent_pb2.VM_STATE_EXITED
    assert healthy() is False
    assert node.agent.create_calls == 1


# Exec


def test_exec_command_returns_the_exit_and_output_of_a_short_command(
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    deltas, result = _run(sandbox.exec_command(ref, "echo hi there"))

    assert result.exit_code == 0
    assert result.completion == "exited"
    assert result.exec_session_id is None
    assert result.output == "hi there\n"
    assert "".join(deltas) == "hi there\n"

    executions = node.agent.executions[str(ref.sandbox_id)].values()
    command = next(e for e in executions if e.argv[:2] == ["bash", "-c"])
    assert command.argv == ["bash", "-c", "echo hi there"]
    assert command.cwd == session_workspace(ref.session_id)
    assert command.env == EXEC_DEFAULT_ENV
    assert command.labels[harness_sandbox.LABEL_CHAT_SESSION] == str(ref.session_id)
    # The session directory is made once per VM instance.
    mkdirs = [e for e in executions if e.argv[0] == "mkdir"]
    assert [m.argv for m in mkdirs] == [
        ["mkdir", "-p", session_workspace(ref.session_id)]
    ]
    _run(sandbox.exec_command(ref, "echo again"))
    assert len([e for e in executions if e.argv[0] == "mkdir"]) == 1


def test_exec_command_reports_a_failed_command_and_relative_workdir(
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    _, result = _run(sandbox.exec_command(ref, "fail 3", workdir="sub/dir"))
    assert result.exit_code == 3
    assert result.output == "failed\n"
    command = next(
        e
        for e in node.agent.executions[str(ref.sandbox_id)].values()
        if e.argv[:2] == ["bash", "-c"]
    )
    assert command.cwd == f"{session_workspace(ref.session_id)}/sub/dir"


@pytest.mark.usefixtures("node")
def test_a_running_command_gets_an_exec_session_that_another_pod_serves(
    tenant_cache: CacheBackend,
    make_sandbox: MakeSandbox,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    pod_a, pod_b = make_sandbox(), make_sandbox()

    started = time.monotonic()
    deltas, result = _run(pod_a.exec_command(ref, "cat", yield_time_ms=300))
    assert time.monotonic() - started >= 0.3
    assert deltas == [] and result.output == ""
    assert result.exit_code is None and result.completion is None
    session = result.exec_session_id
    assert session is not None
    [record] = harness_state.list_exec_sessions(tenant_cache, ref.sandbox_id)
    assert record.exec_session_id == session

    # Another pod writes stdin and streams the new output.
    deltas, result = _run(pod_b.write_stdin(ref, session, "hello "))
    assert "".join(deltas) == "hello " and result.output == "hello "
    assert result.exec_session_id == session

    # Only output after the last read comes back.
    _, result = _run(pod_a.write_stdin(ref, session, "world"))
    assert result.output == "world"
    record_after = harness_state.get_exec_session(tenant_cache, ref.sandbox_id, session)
    assert record_after is not None and record_after.stdout_offset == len("hello world")


def test_an_empty_write_polls_until_the_command_ends(
    monkeypatch: pytest.MonkeyPatch,
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    monkeypatch.setattr(harness_sandbox, "POLL_MIN_YIELD_MS", 300)
    ref = new_ref()
    _, result = _run(sandbox.exec_command(ref, "cat", yield_time_ms=250))
    session = result.exec_session_id
    assert session is not None
    execution_id = next(
        e.execution_id
        for e in node.agent.executions[str(ref.sandbox_id)].values()
        if e.argv[-1:] == ["cat"]
    )

    started = time.monotonic()
    _, polled = _run(sandbox.write_stdin(ref, session))
    assert time.monotonic() - started >= 0.3
    assert polled.exec_session_id == session and polled.output == ""

    # The command ends between polls: the poll returns its exit at once.
    sandbox._daemon(sandbox._place(ref)).interact(
        execution_id, data=b"bye", close_stdin=True
    )
    _, ended = _run(sandbox.write_stdin(ref, session, yield_time_ms=10_000))
    assert ended.exit_code == 0 and ended.output == "bye"
    assert ended.exec_session_id is None
    assert harness_state.get_exec_session(tenant_cache, ref.sandbox_id, session) is None


def test_ctrl_c_cancels_the_command(
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    _, result = _run(sandbox.exec_command(ref, "cat", yield_time_ms=250))
    session = result.exec_session_id
    assert session is not None

    _, result = _run(sandbox.write_stdin(ref, session, "last\x03"))
    assert result.completion == "canceled"
    assert result.exit_code is None and result.exec_session_id is None
    assert result.output == "last"
    assert len(node.agent.cancel_calls) == 1
    assert harness_state.get_exec_session(tenant_cache, ref.sandbox_id, session) is None


@pytest.mark.usefixtures("node")
def test_an_exec_session_of_another_chat_session_or_unknown_id_is_not_found(
    sandbox: FirecrackerHarnessSandbox,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    _, result = _run(sandbox.exec_command(ref, "sleep 60", yield_time_ms=250))
    assert result.exec_session_id is not None

    with pytest.raises(ExecSessionNotFoundError):
        _run(sandbox.write_stdin(_session_ref(ref), result.exec_session_id))
    with pytest.raises(ExecSessionNotFoundError):
        _run(sandbox.write_stdin(ref, "nope"))


def test_exec_sessions_end_when_the_vm_restarts(
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    _, result = _run(sandbox.exec_command(ref, "sleep 60", yield_time_ms=250))
    session = result.exec_session_id
    assert session is not None

    # The VM stops (idle stop, node loss); the next call wakes a new one.
    vm = node.agent.vms[str(ref.sandbox_id)]
    sandbox._client_factory.client(node.address).stop(
        sandbox_id=str(ref.sandbox_id), attempt=vm.attempt, generation=vm.generation
    )
    with pytest.raises(ExecSessionEndedError) as exc:
        _run(sandbox.write_stdin(ref, session))
    assert "Run the command again" in str(exc.value)
    assert harness_state.get_exec_session(tenant_cache, ref.sandbox_id, session) is None
    assert node.agent.create_calls == 2


def test_the_session_cap_evicts_ended_commands_first_then_cancels_the_lru(
    tenant_cache: CacheBackend,
    make_sandbox: MakeSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    sandbox = make_sandbox(max_exec_sessions=2)
    ref = new_ref()
    first = _run(sandbox.exec_command(ref, "sleep 60", yield_time_ms=250))[1]
    second = _run(sandbox.exec_command(ref, "sleep 60", yield_time_ms=250))[1]
    assert first.exec_session_id and second.exec_session_id
    record = harness_state.get_exec_session(
        tenant_cache, ref.sandbox_id, second.exec_session_id
    )
    assert record is not None
    # The second command ends with no poll: its record stays, but it is
    # evicted before the older, running first one.
    sandbox._daemon(sandbox._place(ref)).cancel(record.execution_id)
    node.agent.cancel_calls.clear()

    third = _run(sandbox.exec_command(ref, "sleep 60", yield_time_ms=250))[1]
    ids = {
        r.exec_session_id
        for r in harness_state.list_exec_sessions(tenant_cache, ref.sandbox_id)
    }
    assert ids == {first.exec_session_id, third.exec_session_id}
    assert node.agent.cancel_calls == []

    # All running: the least recently used one is evicted and canceled.
    fourth = _run(sandbox.exec_command(ref, "sleep 60", yield_time_ms=250))[1]
    ids = {
        r.exec_session_id
        for r in harness_state.list_exec_sessions(tenant_cache, ref.sandbox_id)
    }
    assert ids == {third.exec_session_id, fourth.exec_session_id}
    assert len(node.agent.cancel_calls) == 1
    with pytest.raises(ExecSessionNotFoundError):
        _run(sandbox.write_stdin(ref, first.exec_session_id))


@pytest.mark.usefixtures("node")
def test_output_is_cut_to_max_output_tokens_head_and_tail(
    sandbox: FirecrackerHarnessSandbox,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    text = "a" * 200 + "z" * 200
    _, result = _run(sandbox.exec_command(ref, f"echo {text}", max_output_tokens=20))
    assert result.truncated
    assert result.output.startswith("a" * 40)
    assert result.output.rstrip("\n").endswith("z" * 39)
    assert "tokens omitted" in result.output
    assert result.original_token_count == (len(text) + 1 + 3) // 4


def test_the_output_buffer_keeps_head_and_tail_bytes() -> None:
    buffer = ExecOutputBuffer(max_bytes=10)
    assert buffer.add(OutputStream.STDOUT, b"0123") == "0123"
    assert buffer.add(OutputStream.STDOUT, b"456789abcdef") == "4"
    assert buffer.truncated
    assert buffer.text() == "01234\n[... 6 bytes omitted ...]\n" + "bcdef"
    # A multibyte character split across chunks streams whole.
    split = ExecOutputBuffer()
    assert split.add(OutputStream.STDERR, "é".encode()[:1]) == ""
    assert split.add(OutputStream.STDERR, "é".encode()[1:]) == "é"
    assert cut_to_tokens("short", 10) == ("short", False)
    # A character split between the head and the tail stays whole.
    boundary = ExecOutputBuffer(max_bytes=4)
    boundary.add(OutputStream.STDOUT, "aé".encode())
    assert not boundary.truncated and boundary.text() == "aé"


# Files


@pytest.mark.usefixtures("node")
def test_files_round_trip_in_the_session_directory(
    sandbox: FirecrackerHarnessSandbox,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    sandbox.write_file(ref, "notes/a.txt", b"alpha")
    absolute = f"{session_workspace(ref.session_id)}/notes/b.txt"
    sandbox.write_file(ref, absolute, b"beta")

    assert sandbox.read_file(ref, absolute, max_bytes=10) == b"beta"
    assert sandbox.read_file(ref, "notes/./a.txt", max_bytes=10) == b"alpha"
    listing = sandbox.list_files(ref, "notes")
    assert sorted(e.name for e in listing.entries) == ["a.txt", "b.txt"]
    assert not any(e.is_directory for e in listing.entries)

    with pytest.raises(SandboxFileTooLargeError):
        sandbox.read_file(ref, "notes/a.txt", max_bytes=2)
    assert sandbox.delete_file(ref, "notes/a.txt") is True
    assert sandbox.delete_file(ref, "notes/a.txt") is False
    # Files of one chat session are not in another's directory.
    assert sandbox.list_files(_session_ref(ref)).entries == []


@pytest.mark.parametrize("path", ["/etc/passwd", "../other/x", "a/../../x"])
def test_file_paths_outside_the_session_directory_are_refused(path: str) -> None:
    ref = HarnessSandboxRef(tenant_id=TENANT_ID, sandbox_id=uuid4(), session_id=uuid4())
    with pytest.raises(SandboxPathError):
        session_relative_path(ref, path)


@pytest.mark.usefixtures("db_session", "initialize_file_store", "node")
def test_publish_artifact_copies_a_session_file_to_the_file_store(
    sandbox: FirecrackerHarnessSandbox,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    sandbox.write_file(ref, "out/report.csv", b"a,b\n1,2\n")

    file_id = sandbox.publish_artifact(ref, "out/report.csv")
    store = get_default_file_store()
    try:
        record = store.read_file_record(file_id)
        assert record.display_name == "report.csv"
        assert record.file_type == "text/csv"
        assert store.read_file(file_id).read() == b"a,b\n1,2\n"
    finally:
        store.delete_file(file_id)


# Managed drive


def _bundle(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("skills/demo/SKILL.md", text)
    return buf.getvalue()


def test_the_managed_drive_is_swapped_in_once_per_vm_instance(
    make_sandbox: MakeSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    content = {"text": "v1"}
    calls: list[UUID] = []

    def bundle(ref: HarnessSandboxRef) -> bytes:
        calls.append(ref.sandbox_id)
        return _bundle(content["text"])

    sandbox = make_sandbox(managed_bundle=bundle)
    ref = new_ref()
    sandbox.ensure_running(ref)
    assert len(node.agent.managed_images) == 1
    assert (
        node.agent.managed_active[str(ref.sandbox_id)] == hostagent_pb2.MANAGED_SLOT_B
    )

    sandbox.ensure_running(ref)
    assert len(calls) == 1

    content["text"] = "v2"
    sandbox.refresh_managed(ref)
    assert len(calls) == 2
    assert len(node.agent.managed_images) == 2
    assert (
        node.agent.managed_active[str(ref.sandbox_id)] == hostagent_pb2.MANAGED_SLOT_A
    )


# Activity


def test_busy_while_a_command_runs_a_turn_is_open_or_an_approval_waits(
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()

    def busy() -> bool:
        return sandbox.is_busy(tenant_id=TENANT_ID, sandbox_id=ref.sandbox_id)

    assert busy() is False
    assert node.agent.create_calls == 0

    sandbox.begin_turn(ref)
    assert busy() is True
    sandbox.end_turn(ref)
    assert busy() is False

    other = _session_ref(ref)
    sandbox.set_approval_parked(other, True)
    assert busy() is True
    # A session clears only its own mark.
    sandbox.set_approval_parked(ref, False)
    assert busy() is True
    sandbox.set_approval_parked(other, False)
    assert busy() is False

    _, result = _run(sandbox.exec_command(ref, "sleep 60", yield_time_ms=250))
    assert busy() is True
    assert result.exec_session_id is not None
    _run(sandbox.write_stdin(ref, result.exec_session_id, "\x03"))
    assert busy() is False


def test_a_turn_mark_expires_without_renewal(
    tenant_cache: CacheBackend, new_ref: NewRef
) -> None:
    ref = new_ref()
    harness_state.set_activity_mark(
        tenant_cache,
        ref.sandbox_id,
        ref.session_id,
        kind=harness_state.ActivityKind.TURN,
        ttl_seconds=0.05,
    )
    assert harness_state.has_activity(tenant_cache, ref.sandbox_id)
    time.sleep(0.1)
    assert not harness_state.has_activity(tenant_cache, ref.sandbox_id)


def test_touch_records_activity_without_starting_a_vm(
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    sandbox.touch(ref)
    assert node.agent.create_calls == 0

    sandbox.ensure_running(ref)
    placement = get_sandbox_placement(tenant_cache, ref.sandbox_id)
    assert placement is not None
    # Fenced writes keep the later time: reset it directly.
    tenant_cache.set(
        registry._PLACEMENT_PREFIX + str(ref.sandbox_id),
        registry._placement_record(placement.model_copy(update={"last_active": 1})),
    )
    sandbox.touch(ref)
    touched = get_sandbox_placement(tenant_cache, ref.sandbox_id)
    assert touched is not None and touched.last_active > 1


def test_the_factory_refuses_without_the_harness_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(harness_factory, "_instance", None)
    monkeypatch.setattr(harness_factory, "SANDBOX_FC_HARNESS_ENABLED", False)
    with pytest.raises(harness_factory.HarnessSandboxUnavailableError):
        harness_factory.get_harness_sandbox()


def test_collect_exec_result_reads_the_stream_to_its_end() -> None:
    result = ExecCommandResult(
        output="x",
        exec_session_id=None,
        exit_code=0,
        completion="exited",
        wall_time_seconds=0.1,
        original_token_count=1,
        truncated=False,
    )
    finished: list[bool] = []

    def stream() -> Generator[ExecEvent, None, None]:
        yield ExecOutputDelta(text="x")
        yield result
        finished.append(True)

    assert collect_exec_result(stream()) is result
    assert finished == [True]


def test_concurrent_wakes_run_init_once(
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    sandbox.ensure_running(ref)
    node.agent.daemon_inits.pop(str(ref.sandbox_id))
    node.agent.init_delay_seconds = 0.3

    errors: list[BaseException] = []

    def wake() -> None:
        try:
            sandbox.ensure_running(ref)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=wake) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    # One Init at the first wake, one after the lost Init.
    assert len(node.agent.init_requests) == 2


def test_a_failed_registration_stops_the_started_command(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()

    def fail(*_args: object, **_kwargs: object) -> None:
        raise harness_state.StateContentionError("contention")

    monkeypatch.setattr(harness_sandbox, "add_exec_session", fail)
    with pytest.raises(harness_state.StateContentionError):
        _run(sandbox.exec_command(ref, "sleep 60", yield_time_ms=250))
    [command] = [
        e
        for e in node.agent.executions[str(ref.sandbox_id)].values()
        if e.argv[:2] == ["bash", "-c"]
    ]
    assert node.agent.cancel_calls == [command.execution_id]


def test_a_record_of_an_older_vm_never_replaces_newer_records(
    tenant_cache: CacheBackend, new_ref: NewRef
) -> None:
    ref = new_ref()

    def record(attempt: int, generation: int) -> harness_state.ExecSessionRecord:
        return harness_state.ExecSessionRecord(
            exec_session_id=uuid4().hex[:8],
            chat_session_id=str(ref.session_id),
            execution_id=uuid4().hex,
            attempt=attempt,
            generation=generation,
            last_used=time.time(),
        )

    newer = record(2, 7)
    assert (
        harness_state.add_exec_session(
            tenant_cache,
            ref.sandbox_id,
            newer,
            max_sessions=64,
            ended_execution_ids=set(),
        )
        == []
    )
    assert (
        harness_state.add_exec_session(
            tenant_cache,
            ref.sandbox_id,
            record(1, 5),
            max_sessions=64,
            ended_execution_ids=set(),
        )
        is None
    )
    assert harness_state.list_exec_sessions(tenant_cache, ref.sandbox_id) == [newer]


def test_ctrl_c_is_not_held_back_by_a_long_poll(
    monkeypatch: pytest.MonkeyPatch,
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    monkeypatch.setattr(harness_sandbox, "_EXEC_LOCK_WAIT_SECONDS", 0.2)
    ref = new_ref()
    _, result = _run(sandbox.exec_command(ref, "cat", yield_time_ms=250))
    session = result.exec_session_id
    assert session is not None
    # Another call holds the read lock (a long poll).
    held = tenant_cache.lock(
        f"{harness_sandbox._EXEC_LOCK_PREFIX}{ref.sandbox_id}:{session}", timeout=30
    )
    assert held.acquire(blocking=False)
    try:
        _, interrupted = _run(sandbox.write_stdin(ref, session, "\x03"))
    finally:
        held.release()
    assert interrupted.completion == "canceled"
    assert interrupted.exec_session_id is None
    assert len(node.agent.cancel_calls) == 1
