"""FirecrackerHarnessSandbox against Redis and fake host agents: lifecycle,
the Codex exec contract with durable exec sessions, files, artifacts and the
busy signals."""

import time
from collections.abc import Callable, Generator, Iterator
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import grpc
import pytest

from onyx.cache.interface import CacheBackend
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.microvm import registry
from onyx.microvm.agent_client import HostAgentError, HostAgentErrorReason
from onyx.microvm.daemon_client import (
    SandboxDaemonClient,
    SandboxDaemonError,
)
from onyx.microvm.generated.hostagent.v1 import hostagent_pb2
from onyx.microvm.generated.sandboxd.v1 import sandboxd_pb2
from onyx.microvm.lifecycle import sandbox_daemon
from onyx.microvm.models import ExecCommand, ExecStarted, OutputStream
from onyx.microvm.registry import get_sandbox_placement
from onyx.server.features.build.sandbox import harness_base, harness_factory
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
    session_relative_path,
)
from onyx.server.features.build.sandbox.harness_base import (
    EXEC_DEFAULT_ENV,
    ExecCapReachedError,
    ExecSessionEndedError,
    ExecSessionNotFoundError,
    SandboxFileTooLargeError,
    SandboxPathError,
    collect_exec_result,
    session_workspace,
)
from onyx.server.features.build.sandbox.models import (
    ExecCommandResult,
    ExecEvent,
    ExecOutputDelta,
    HarnessSandboxRef,
)
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    get_current_tenant_id,
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

MakeSandbox = Callable[[], FirecrackerHarnessSandbox]
NewRef = Callable[[], HarnessSandboxRef]


@pytest.fixture
def make_sandbox(client_factory: InsecureClientFactory) -> MakeSandbox:
    """A sandbox per "API pod": they share only the cache."""

    def make() -> FirecrackerHarnessSandbox:
        return FirecrackerHarnessSandbox(
            template="tpl-1", client_factory=client_factory
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
        tenant_cache.delete(harness_state.EXEC_SESSIONS_PREFIX + str(ref.sandbox_id))
        tenant_cache.delete(harness_state.ACTIVITY_PREFIX + str(ref.sandbox_id))


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
    assert dict(init.env) == EXEC_DEFAULT_ENV
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


def test_concurrent_wakes_of_an_uninitialized_vm_run_one_init(
    make_sandbox: MakeSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    make_sandbox().ensure_running(ref)
    node.agent.daemon_inits.pop(str(ref.sandbox_id))
    node.agent.init_delay_seconds = 0.3

    # Two "API pods" wake the same VM at once.
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [
            pool.submit(make_sandbox().ensure_running, ref) for _ in range(2)
        ]:
            future.result()
    assert len(node.agent.init_requests) == 2
    assert node.agent.create_calls == 1


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


def test_a_full_node_is_retried_with_backoff_then_the_wake_succeeds(
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    node.agent.refuse_create = HostAgentErrorReason.CAPACITY_MEMORY
    node.agent.refuse_create_times = 2
    ref = new_ref()
    sandbox.ensure_running(ref)
    # Two refused Creates, then one that starts the VM.
    assert node.agent.create_calls == 3
    assert str(ref.sandbox_id) in node.agent.daemon_inits


def test_a_full_node_fails_the_call_after_the_retry_window(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    node.agent.refuse_create = HostAgentErrorReason.CAPACITY_MEMORY
    monkeypatch.setattr(harness_sandbox, "WAKE_RETRY_SECONDS", 0.6)
    started = time.monotonic()
    with pytest.raises(OnyxError) as exc:
        sandbox.ensure_running(new_ref())
    assert exc.value.error_code is OnyxErrorCode.SANDBOX_CAPACITY_UNAVAILABLE
    assert 0.1 <= time.monotonic() - started <= 1.5


def test_a_replaced_vm_after_a_crash_is_initialized(
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    sandbox.ensure_running(ref)
    node.agent.vms[str(ref.sandbox_id)].state = hostagent_pb2.VM_STATE_EXITED

    _, result = _run(sandbox.exec_command(ref, "echo back"))
    assert result.output == "back\n"
    placement = get_sandbox_placement(tenant_cache, ref.sandbox_id)
    assert placement is not None and placement.attempt == 2
    assert node.agent.daemon_inits[str(ref.sandbox_id)] == placement.generation


def test_each_node_runs_its_own_newest_template_of_the_image_tag(
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_ref: NewRef,
) -> None:
    def template(
        version: str, built: int, compatible: bool = True
    ) -> hostagent_pb2.TemplateInfo:
        info = hostagent_pb2.TemplateInfo(
            version=version, vcpus=2, mem_mib=2048, scratch_gib=4, compatible=compatible
        )
        info.built_at.FromSeconds(built)
        return info

    first = add_node(f"fch-{uuid4().hex[:6]}")
    second = add_node(f"fch-{uuid4().hex[:6]}")
    first.agent.templates = [
        template("dev-build-adf9a87-0123456789ab", 100),
        template("dev-build-adf9a87-ba9876543210", 200),
        # Newer, but its key does not fit the node.
        template("dev-build-adf9a87-cccccccccccc", 300, compatible=False),
        template("dev-build-old-dddddddddddd", 400),
    ]
    second.agent.templates = [template("dev-build-adf9a87-fedcba987654", 100)]
    second.agent.mem_available_mib = 4096
    sandbox = FirecrackerHarnessSandbox(
        template="dev-build-adf9a87", client_factory=client_factory
    )

    on_first = new_ref()
    sandbox.ensure_running(on_first)
    first.agent.mem_available_mib = 0
    on_second = new_ref()
    sandbox.ensure_running(on_second)

    vm = first.agent.vms[str(on_first.sandbox_id)]
    assert vm.template == "dev-build-adf9a87-ba9876543210"
    vm = second.agent.vms[str(on_second.sandbox_id)]
    assert vm.template == "dev-build-adf9a87-fedcba987654"


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
    # The daemon makes the session directory and uses it as the default cwd.
    assert command.session_id == str(ref.session_id)
    assert command.cwd == ""


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
    assert command.session_id == str(ref.session_id)
    assert command.cwd == "sub/dir"


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
    assert harness_state.get_exec_session(tenant_cache, ref.sandbox_id, session)

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
    client_factory: InsecureClientFactory,
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
    sandbox_daemon(client_factory, sandbox._place(ref)).interact(
        execution_id, data=b"bye", close_stdin=True
    )
    _, ended = _run(sandbox.write_stdin(ref, session, yield_time_ms=10_000))
    assert ended.exit_code == 0 and ended.output == "bye"
    assert ended.exec_session_id is None
    assert harness_state.get_exec_session(tenant_cache, ref.sandbox_id, session) is None


def test_a_character_split_between_polls_is_kept(
    monkeypatch: pytest.MonkeyPatch,
    client_factory: InsecureClientFactory,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    monkeypatch.setattr(harness_sandbox, "POLL_MIN_YIELD_MS", 250)
    ref = new_ref()
    _, result = _run(sandbox.exec_command(ref, "cat", yield_time_ms=250))
    session = result.exec_session_id
    assert session is not None
    [execution] = node.agent.executions[str(ref.sandbox_id)].values()
    daemon = sandbox_daemon(client_factory, sandbox._place(ref))

    daemon.interact(execution.execution_id, data="a€".encode()[:3])
    assert _run(sandbox.write_stdin(ref, session))[1].output == "a"
    daemon.interact(execution.execution_id, data="a€".encode()[3:])
    assert _run(sandbox.write_stdin(ref, session))[1].output == "€"


def test_ctrl_c_sends_sigint_to_the_command(
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
    [execution] = node.agent.executions[str(ref.sandbox_id)].values()
    assert node.agent.cancel_calls == [execution.execution_id]
    # SIGINT (Ctrl-C), not a kill of the cgroup.
    assert execution.signaled == sandboxd_pb2.CANCEL_SIGNAL_SIGINT
    assert result.completion == "canceled"
    assert result.exit_code is None and result.exec_session_id is None
    assert result.output == "last"
    assert harness_state.get_exec_session(tenant_cache, ref.sandbox_id, session) is None


def test_a_full_execution_table_is_a_clear_tool_error(
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    node.agent.max_running_executions = 1
    ref = new_ref()
    _, result = _run(sandbox.exec_command(ref, "cat", yield_time_ms=250))
    assert result.exec_session_id is not None

    with pytest.raises(ExecCapReachedError, match="Too many commands"):
        _run(sandbox.exec_command(ref, "echo hi"))


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


def test_output_that_the_daemon_dropped_marks_the_buffer_truncated() -> None:
    buffer = ExecOutputBuffer()
    buffer.add(OutputStream.STDOUT, b"a")
    assert not buffer.truncated
    assert "lost" in buffer.add_gap(OutputStream.STDOUT, 10)
    assert buffer.truncated


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
    mixed = ExecOutputBuffer()
    mixed.add(OutputStream.STDOUT, "é".encode()[:1])
    mixed.add(OutputStream.STDERR, b"err")
    mixed.add(OutputStream.STDOUT, "é".encode()[1:])
    assert mixed.text() == "erré"
    # A command that ends inside a character still shows the bytes.
    cut = ExecOutputBuffer()
    cut.add(OutputStream.STDOUT, b"ok\xc3")
    assert cut.finish() == "\ufffd"
    assert cut.text() == "ok\ufffd"
    # Bytes on each side of a gap never join into one character.
    gap = ExecOutputBuffer()
    gap.add(OutputStream.STDOUT, "é".encode()[:1])
    gap.add_gap(OutputStream.STDOUT, 5)
    gap.add(OutputStream.STDOUT, "é".encode()[1:])
    assert "é" not in gap.text() and "5 bytes of stdout lost" in gap.text()
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
    assert sandbox.read_file(ref, "notes/./a.txt", max_bytes=5) == b"alpha"
    with pytest.raises(SandboxFileTooLargeError):
        sandbox.read_file(ref, "notes/a.txt", max_bytes=2)
    # Files of one chat session are not in another's directory.
    with pytest.raises(SandboxDaemonError):
        sandbox.read_file(_session_ref(ref), "notes/a.txt", max_bytes=10)


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


@pytest.mark.usefixtures("node")
def test_publish_artifact_saves_under_the_sandbox_tenant(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    sandbox.write_file(ref, "a.txt", b"x")
    seen: list[str] = []

    class Store:
        def save_file(self, **_kwargs: object) -> str:
            seen.append(get_current_tenant_id())
            return "file-1"

    monkeypatch.setattr(harness_sandbox, "get_default_file_store", Store)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set("another_tenant")
    try:
        assert sandbox.publish_artifact(ref, "a.txt") == "file-1"
        assert get_current_tenant_id() == "another_tenant"
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    assert seen == [TENANT_ID]


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
    harness_state.set_mark(tenant_cache, ref.sandbox_id, "turn:x", 0.05)
    assert harness_state.has_marks(tenant_cache, ref.sandbox_id)
    time.sleep(0.1)
    assert not harness_state.has_marks(tenant_cache, ref.sandbox_id)


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


@pytest.mark.parametrize(("firecracker", "template"), [(False, "tpl-1"), (True, "")])
def test_the_factory_needs_firecracker_and_a_template(
    monkeypatch: pytest.MonkeyPatch, firecracker: bool, template: str
) -> None:
    monkeypatch.setattr(harness_factory, "_instance", None)
    monkeypatch.setattr(harness_factory, "FIRECRACKER_ENABLED", firecracker)
    monkeypatch.setattr(harness_factory, "SANDBOX_FC_TEMPLATE", template)
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


def test_a_failed_registration_stops_the_started_command(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()

    def fail(*_args: object, **_kwargs: object) -> None:
        raise harness_state.StateContentionError("contention")

    monkeypatch.setattr(harness_sandbox, "put_exec_session", fail)
    with pytest.raises(harness_state.StateContentionError):
        _run(sandbox.exec_command(ref, "sleep 60", yield_time_ms=250))
    [command] = [
        e
        for e in node.agent.executions[str(ref.sandbox_id)].values()
        if e.argv[:2] == ["bash", "-c"]
    ]
    assert node.agent.cancel_calls == [command.execution_id]


@pytest.mark.parametrize("reached_the_daemon", [True, False])
def test_a_start_without_an_answer_adopts_the_command_if_it_started(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
    reached_the_daemon: bool,
) -> None:
    ref = new_ref()
    real_start = SandboxDaemonClient.start

    def lost_answer(self: SandboxDaemonClient, command: ExecCommand) -> ExecStarted:
        if reached_the_daemon:
            real_start(self, command)
        raise HostAgentError(grpc.StatusCode.DEADLINE_EXCEEDED, "lost", None)

    monkeypatch.setattr(SandboxDaemonClient, "start", lost_answer)
    if not reached_the_daemon:
        with pytest.raises(HostAgentError):
            _run(sandbox.exec_command(ref, "cat", yield_time_ms=250))
        return
    _, result = _run(sandbox.exec_command(ref, "cat", yield_time_ms=250))
    assert result.exec_session_id is not None
    commands = [
        e
        for e in node.agent.executions[str(ref.sandbox_id)].values()
        if e.argv[:2] == ["bash", "-c"]
    ]
    assert len(commands) == 1 and commands[0].result is None
    monkeypatch.undo()
    _, result = _run(sandbox.write_stdin(ref, result.exec_session_id, "hi"))
    assert result.output == "hi"


@pytest.mark.usefixtures("node")
def test_ctrl_c_on_an_ended_command_reports_its_exit(
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    sandbox: FirecrackerHarnessSandbox,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    _, result = _run(sandbox.exec_command(ref, "cat", yield_time_ms=250))
    session = result.exec_session_id
    assert session is not None
    record = harness_state.get_exec_session(tenant_cache, ref.sandbox_id, session)
    assert record is not None
    sandbox_daemon(client_factory, sandbox._place(ref)).interact(
        record.execution_id, data=b"", close_stdin=True
    )
    _, interrupted = _run(sandbox.write_stdin(ref, session, "\x03"))
    assert interrupted.completion == "exited" and interrupted.exit_code == 0


@pytest.mark.usefixtures("node")
def test_the_least_recently_used_exec_session_record_goes_over_the_cap(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    new_ref: NewRef,
) -> None:
    monkeypatch.setattr(harness_base, "MAX_EXEC_SESSIONS_PER_SANDBOX", 2)
    ref = new_ref()
    first, second, third = (
        _run(sandbox.exec_command(ref, "cat", yield_time_ms=250))[1].exec_session_id
        for _ in range(3)
    )
    assert first and second and third
    with pytest.raises(ExecSessionNotFoundError):
        _run(sandbox.write_stdin(ref, first, "x"))
    assert _run(sandbox.write_stdin(ref, second, "y"))[1].output == "y"
