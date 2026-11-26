"""FirecrackerHarnessSandbox against Redis and fake host agents: lifecycle,
the Codex exec contract with durable exec sessions, files, artifacts and the
busy signals."""

import io
import os
import threading
import time
from collections.abc import Callable, Generator, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import uuid4

import grpc
import pytest

from onyx.cache.interface import CacheBackend
from onyx.configs.constants import FileOrigin
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.llm.cancellation import (
    AgentCancelled,
    CancellationSignal,
    cancellation_scope,
)
from onyx.microvm import registry
from onyx.microvm.agent_client import HostAgentError, HostAgentErrorReason
from onyx.microvm.daemon_client import SandboxDaemonClient, SandboxDaemonErrorReason
from onyx.microvm.generated.hostagent.v1 import hostagent_pb2
from onyx.microvm.generated.sandboxd.v1 import sandboxd_pb2
from onyx.microvm.lifecycle import sandbox_daemon
from onyx.microvm.models import (
    ExecCommand,
    ExecStarted,
    FileListing,
    OutputStream,
    PlacedVm,
)
from onyx.microvm.models import ExecEvent as DaemonExecEvent
from onyx.microvm.registry import get_sandbox_placement
from onyx.server.features.build.sandbox import harness_base, harness_factory
from onyx.server.features.build.sandbox.exec_output import (
    ExecOutputBuffer,
)
from onyx.server.features.build.sandbox.firecracker import (
    harness_sandbox,
    harness_state,
)
from onyx.server.features.build.sandbox.firecracker.harness_sandbox import (
    FirecrackerHarnessSandbox,
)
from onyx.server.features.build.sandbox.firecracker.models import ExecSessionTable
from onyx.server.features.build.sandbox.harness_base import (
    EXEC_DEFAULT_ENV,
    ONYX_VM_FILES_ROOT,
    TOOL_RESULTS_ROOT,
    ExecCapReachedError,
    ExecSessionEndedError,
    ExecSessionNotFoundError,
    HarnessSandboxError,
    SandboxFileNotFoundError,
    SandboxFileTooLargeError,
    SandboxPathError,
    collect_exec_result,
    session_relative_path,
    session_tool_results,
)
from onyx.server.features.build.sandbox.models import (
    CHAT_SKILLS_PATH,
    ExecCommandResult,
    ExecEvent,
    ExecOutputDelta,
    FileSet,
    HarnessSandboxRef,
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


def _output(result: ExecCommandResult) -> str:
    """The output of a command that printed less than the byte cap."""
    assert not result.omitted_chars
    return result.head + result.tail


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
    assert _output(result) == "back\n"
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
    assert result.session_id is None
    assert _output(result) == "hi there\n"
    assert "".join(deltas) == "hi there\n"

    executions = node.agent.executions[str(ref.sandbox_id)].values()
    command = next(e for e in executions if e.argv[:2] == ["bash", "-c"])
    assert command.argv == ["bash", "-c", "echo hi there"]
    # The daemon makes the session directory and uses it as the default cwd.
    assert command.session_id == str(ref.session_id)
    assert command.cwd == ""
    assert command.env == {}


def test_exec_command_reports_a_failed_command_and_relative_workdir(
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    _, result = _run(sandbox.exec_command(ref, "fail 3", workdir="sub/dir"))
    assert result.exit_code == 3
    assert _output(result) == "failed\n"
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
    assert deltas == [] and _output(result) == ""
    assert result.exit_code is None and result.completion is None
    session = result.session_id
    assert session is not None
    assert harness_state.get_exec_session(tenant_cache, ref.sandbox_id, session)

    # Another pod writes stdin and streams the new output.
    deltas, result = _run(pod_b.write_stdin(ref, session, "hello "))
    assert "".join(deltas) == "hello " and _output(result) == "hello "
    assert result.session_id == session

    # Only output after the last read comes back.
    _, result = _run(pod_a.write_stdin(ref, session, "world"))
    assert _output(result) == "world"
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
    session = result.session_id
    assert session is not None
    execution_id = next(
        e.execution_id
        for e in node.agent.executions[str(ref.sandbox_id)].values()
        if e.argv[-1:] == ["cat"]
    )

    started = time.monotonic()
    _, polled = _run(sandbox.write_stdin(ref, session))
    assert time.monotonic() - started >= 0.3
    assert polled.session_id == session and _output(polled) == ""

    # The command ends between polls: the poll returns its exit at once.
    sandbox_daemon(client_factory, sandbox._place(ref)).interact(
        execution_id, data=b"bye", close_stdin=True
    )
    _, ended = _run(sandbox.write_stdin(ref, session, yield_time_ms=10_000))
    assert ended.exit_code == 0 and _output(ended) == "bye"
    assert ended.session_id is None
    assert harness_state.get_exec_session(tenant_cache, ref.sandbox_id, session) is None


def test_a_stream_reset_at_the_agent_deadline_ends_the_yield_cleanly(
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    # The agent resets the stream (CANCELLED) just before the deadline the
    # client sent: the client must end the yield first.
    node.agent.stream_reset_lead_seconds = 0.2
    ref = new_ref()
    _, result = _run(sandbox.exec_command(ref, "cat", yield_time_ms=300))
    session = result.session_id
    assert session is not None and result.completion is None
    assert harness_state.get_exec_session(tenant_cache, ref.sandbox_id, session)

    _, polled = _run(sandbox.write_stdin(ref, session, "hi", yield_time_ms=300))
    assert polled.session_id == session and _output(polled) == "hi"


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
    session = result.session_id
    assert session is not None
    execution = next(
        e
        for e in node.agent.executions[str(ref.sandbox_id)].values()
        if e.argv[-1:] == ["cat"]
    )
    daemon = sandbox_daemon(client_factory, sandbox._place(ref))

    daemon.interact(execution.execution_id, data="a€".encode()[:3])
    assert _output(_run(sandbox.write_stdin(ref, session))[1]) == "a"
    daemon.interact(execution.execution_id, data="a€".encode()[3:])
    assert _output(_run(sandbox.write_stdin(ref, session))[1]) == "€"


@pytest.mark.usefixtures("node")
def test_the_yield_window_counts_from_the_start_and_the_write(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    new_ref: NewRef,
) -> None:
    """A slow wake (a remote API pod) does not use up the yield window."""
    ref = new_ref()
    sandbox.ensure_running(ref)
    place = sandbox._place

    def slow_place(slow_ref: HarnessSandboxRef) -> PlacedVm:
        time.sleep(0.4)
        return place(slow_ref)

    monkeypatch.setattr(sandbox, "_place", slow_place)
    started = time.monotonic()
    _, result = _run(sandbox.exec_command(ref, "cat", yield_time_ms=300))
    assert time.monotonic() - started >= 0.7
    assert result.wall_time_seconds >= 0.7
    session = result.session_id
    assert session is not None

    # The default 250 ms window of a write starts after the write.
    _, echoed = _run(sandbox.write_stdin(ref, session, "hi"))
    assert _output(echoed) == "hi"
    assert echoed.wall_time_seconds >= 0.65
    _, interrupted = _run(sandbox.write_stdin(ref, session, "\x03"))
    assert interrupted.completion == "canceled"
    assert interrupted.session_id is None


def test_a_cancel_ends_the_wait_and_kills_the_command(
    sandbox: FirecrackerHarnessSandbox, node: RunningFakeAgent, new_ref: NewRef
) -> None:
    """A Stop ends a long poll at once and kills the command it waits on."""
    ref = new_ref()
    _, started = _run(sandbox.exec_command(ref, "cat", yield_time_ms=250))
    session = started.session_id
    assert session is not None
    signal = CancellationSignal()
    stop = threading.Timer(0.3, signal.cancel)
    stop.start()
    begun = time.monotonic()
    with cancellation_scope(signal), pytest.raises(AgentCancelled):
        _run(sandbox.write_stdin(ref, session, yield_time_ms=30_000))
    stop.join()
    assert time.monotonic() - begun < 5

    [killed] = node.agent.cancel_calls
    result = node.agent.executions[str(ref.sandbox_id)][killed].result
    assert result is not None and result.completion == sandboxd_pb2.CANCELED
    with pytest.raises(ExecSessionNotFoundError):
        _run(sandbox.write_stdin(ref, session, "hi"))


def test_a_broken_output_stream_keeps_the_command_and_names_its_session(
    monkeypatch: pytest.MonkeyPatch,
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,  # noqa: ARG001
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    _, started = _run(sandbox.exec_command(ref, "cat", yield_time_ms=250))
    session = started.session_id
    assert session is not None
    stream = SandboxDaemonClient.stream

    def broken(
        client: SandboxDaemonClient, execution_id: str, **kwargs: Any
    ) -> Iterator[DaemonExecEvent]:
        yield from stream(client, execution_id, **kwargs)
        raise HostAgentError(grpc.StatusCode.UNAVAILABLE, "connection reset", None)

    monkeypatch.setattr(SandboxDaemonClient, "stream", broken)
    with pytest.raises(HarnessSandboxError, match=f"session ID {session}"):
        _run(sandbox.write_stdin(ref, session, "hi"))
    monkeypatch.setattr(SandboxDaemonClient, "stream", stream)

    assert harness_state.get_exec_session(tenant_cache, ref.sandbox_id, session)
    _, polled = _run(sandbox.write_stdin(ref, session, yield_time_ms=250))
    assert polled.session_id == session and _output(polled) == "hi"


def test_a_stop_during_a_broken_output_stream_still_kills_the_command(
    monkeypatch: pytest.MonkeyPatch,
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    _, started = _run(sandbox.exec_command(ref, "cat", yield_time_ms=250))
    session = started.session_id
    assert session is not None
    signal = CancellationSignal()

    def broken(
        _client: SandboxDaemonClient, _execution_id: str, **_kwargs: Any
    ) -> Iterator[DaemonExecEvent]:
        signal.cancel()
        raise HostAgentError(grpc.StatusCode.UNAVAILABLE, "connection reset", None)
        yield

    monkeypatch.setattr(SandboxDaemonClient, "stream", broken)
    with cancellation_scope(signal), pytest.raises(AgentCancelled):
        _run(sandbox.write_stdin(ref, session, yield_time_ms=30_000))

    [killed] = node.agent.cancel_calls
    result = node.agent.executions[str(ref.sandbox_id)][killed].result
    assert result is not None and result.completion == sandboxd_pb2.CANCELED
    assert harness_state.get_exec_session(tenant_cache, ref.sandbox_id, session) is None


@pytest.mark.parametrize("kill_fails", [False, True], ids=["killed", "kill_failed"])
def test_a_stop_that_the_consumer_sees_first_still_kills_the_command(
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
    kill_fails: bool,
) -> None:
    """The consumer raises on the Stop at the first output and drops the
    stream: the command is killed all the same. A kill that fails keeps the
    command's record, so write_stdin can still reach it."""
    ref = new_ref()
    if kill_fails:
        node.agent.cancel_error = SandboxDaemonErrorReason.INTERNAL
    signal = CancellationSignal()
    with cancellation_scope(signal):
        events = sandbox.exec_command(ref, "say partial", yield_time_ms=30_000)
        assert next(events) == ExecOutputDelta(text="partial\n")
        signal.cancel()
        # The consumer stops reading: the generator gets GeneratorExit.
        events.close()

    [killed] = node.agent.cancel_calls
    assert node.agent.executions[str(ref.sandbox_id)][killed].argv[-1] == "say partial"
    records = ExecSessionTable.model_validate_json(
        tenant_cache.get(harness_state.EXEC_SESSIONS_PREFIX + str(ref.sandbox_id))
        or b"{}"
    ).sessions
    assert bool(records) == kill_fails


def test_a_call_stopped_before_its_side_effect_does_nothing(
    sandbox: FirecrackerHarnessSandbox, node: RunningFakeAgent, new_ref: NewRef
) -> None:
    ref = new_ref()
    _, started = _run(sandbox.exec_command(ref, "cat", yield_time_ms=250))
    session = started.session_id
    assert session is not None
    signal = CancellationSignal()
    signal.cancel()
    with cancellation_scope(signal):
        with pytest.raises(AgentCancelled):
            _run(sandbox.exec_command(ref, "say never"))
        with pytest.raises(AgentCancelled):
            _run(sandbox.write_stdin(ref, session, "never"))

    executions = node.agent.executions[str(ref.sandbox_id)].values()
    assert [e.argv[-1] for e in executions] == ["cat"]
    assert [bytes(e.stdin_data) for e in executions] == [b""]


def test_ctrl_c_sends_sigint_to_the_command(
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    _, result = _run(sandbox.exec_command(ref, "cat", yield_time_ms=250))
    session = result.session_id
    assert session is not None

    _, result = _run(sandbox.write_stdin(ref, session, "last\x03"))
    execution = next(
        e
        for e in node.agent.executions[str(ref.sandbox_id)].values()
        if e.argv[-1:] == ["cat"]
    )
    assert node.agent.cancel_calls == [execution.execution_id]
    # SIGINT (Ctrl-C), not a kill of the cgroup.
    assert execution.signaled == sandboxd_pb2.CANCEL_SIGNAL_SIGINT
    assert result.completion == "canceled"
    assert result.exit_code is None and result.session_id is None
    assert _output(result) == "last"
    assert harness_state.get_exec_session(tenant_cache, ref.sandbox_id, session) is None


def test_a_full_execution_table_is_a_clear_tool_error(
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    node.agent.max_running_executions = 1
    ref = new_ref()
    _, result = _run(sandbox.exec_command(ref, "cat", yield_time_ms=250))
    assert result.session_id is not None

    with pytest.raises(ExecCapReachedError, match="Too many commands"):
        _run(sandbox.exec_command(ref, "echo hi"))


@pytest.mark.usefixtures("node")
def test_an_exec_session_of_another_chat_session_or_unknown_id_is_not_found(
    sandbox: FirecrackerHarnessSandbox,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    _, result = _run(sandbox.exec_command(ref, "sleep 60", yield_time_ms=250))
    assert result.session_id is not None

    with pytest.raises(ExecSessionNotFoundError):
        _run(sandbox.write_stdin(_session_ref(ref), result.session_id))
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
    session = result.session_id
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
    assert (buffer.head, buffer.tail, buffer.omitted_chars) == ("01234", "bcdef", 6)
    # A multibyte character split across chunks streams whole.
    split = ExecOutputBuffer()
    assert split.add(OutputStream.STDERR, "é".encode()[:1]) == ""
    assert split.add(OutputStream.STDERR, "é".encode()[1:]) == "é"
    # A character split between the head and the tail stays whole.
    mixed = ExecOutputBuffer()
    mixed.add(OutputStream.STDOUT, "é".encode()[:1])
    mixed.add(OutputStream.STDERR, b"err")
    mixed.add(OutputStream.STDOUT, "é".encode()[1:])
    assert mixed.head + mixed.tail == "erré"
    # A command that ends inside a character still shows the bytes.
    cut = ExecOutputBuffer()
    cut.add(OutputStream.STDOUT, b"ok\xc3")
    assert cut.finish() == "\ufffd"
    assert cut.head + cut.tail == "ok\ufffd"
    # Bytes on each side of a gap never join into one character.
    gap = ExecOutputBuffer()
    gap.add(OutputStream.STDOUT, "é".encode()[:1])
    gap.add_gap(OutputStream.STDOUT, 5)
    gap.add(OutputStream.STDOUT, "é".encode()[1:])
    gap_text = gap.head + gap.tail
    assert "é" not in gap_text and "5 bytes of stdout lost" in gap_text
    boundary = ExecOutputBuffer(max_bytes=4)
    boundary.add(OutputStream.STDOUT, "aé".encode())
    assert not boundary.truncated and boundary.head + boundary.tail == "aé"


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
    with pytest.raises(SandboxFileNotFoundError):
        sandbox.read_file(_session_ref(ref), "notes/a.txt", max_bytes=10)
    # The guest daemon cannot write mode 000; the call fails, not writes 0644.
    with pytest.raises(HarnessSandboxError, match="mode 000"):
        sandbox.write_file(ref, "notes/locked.txt", b"x", mode=0)


def test_stat_files_maps_the_daemon_facts_of_each_path(
    sandbox: FirecrackerHarnessSandbox, node: RunningFakeAgent, new_ref: NewRef
) -> None:
    ref = new_ref()
    sandbox.write_file(ref, "a.txt", b"a", mode=0o750)
    root = session_workspace(ref.session_id)
    [a_info] = sandbox.stat_files(ref, ["a.txt"])
    assert a_info.identity is not None
    # The daemon's facts of each link (its os.Root rules have Go tests).
    targets = {
        "link": sandboxd_pb2.PathStat(
            target_type=sandboxd_pb2.FILE_TYPE_REGULAR,
            target_mode=0o750,
            device=a_info.identity[0],
            inode=a_info.identity[1],
        ),
        "loop": sandboxd_pb2.PathStat(target_error=sandboxd_pb2.STAT_ERROR_LOOP),
        "out": sandboxd_pb2.PathStat(target_error=sandboxd_pb2.STAT_ERROR_ESCAPES),
    }
    for name, stat in targets.items():
        stat.exists = True
        stat.type = sandboxd_pb2.FILE_TYPE_SYMLINK
        stat.mode = 0o777
        stat.link_target = {"link": "a.txt", "loop": "loop", "out": "/mnt/x"}[name]
        node.agent.path_stats[(str(ref.sandbox_id), str(ref.session_id), name)] = stat

    # More paths than one daemon call takes.
    paths = ["a.txt", f"{root}/link", "missing", "out", "loop"]
    paths += [f"many/{i}" for i in range(1000)]
    a, link, missing, out, loop, *many = sandbox.stat_files(ref, paths)

    assert (a.exists, a.is_link, a.type, a.mode, a.error) == (
        True,
        False,
        "file",
        0o750,
        None,
    )
    assert (link.is_link, link.link_target, link.type) == (True, "a.txt", "file")
    assert link.identity == a.identity is not None
    assert (missing.exists, missing.type, missing.identity, missing.error) == (
        False,
        None,
        None,
        None,
    )
    assert (out.is_link, out.type, out.error) == (True, None, "escapes")
    assert (loop.type, loop.error) == (None, "loop")
    assert len(many) == 1000 and not any(info.exists for info in many)
    # An older root drive's daemon has no StatFiles.
    node.agent.stat_files_supported = False
    with pytest.raises(HarnessSandboxError, match="older image"):
        sandbox.stat_files(ref, ["a.txt"])


@pytest.mark.parametrize("path", ["/etc/passwd", "../other/x", "a/../../x"])
def test_file_paths_outside_the_session_directory_are_refused(path: str) -> None:
    ref = HarnessSandboxRef(tenant_id=TENANT_ID, sandbox_id=uuid4(), session_id=uuid4())
    with pytest.raises(SandboxPathError):
        session_relative_path(ref.session_id, path)


@pytest.mark.usefixtures("node")
def test_read_file_reads_the_session_and_the_onyx_root_and_only_regular_files(
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    sandbox.write_file(ref, "out/report.csv", b"a,b\n")
    chart = f"{ONYX_VM_FILES_ROOT}/out/chart.svg"
    sandbox.write_file(ref, chart, b"<svg/>")
    node.agent.files[(str(ref.sandbox_id), "", "/tmp/elsewhere.svg")] = b"<svg/>"

    assert sandbox.read_file(ref, chart, max_bytes=10) == b"<svg/>"
    assert (
        sandbox.read_file(
            ref, f"{session_workspace(ref.session_id)}/out/report.csv", max_bytes=10
        )
        == b"a,b\n"
    )
    # Other absolute paths, and other sessions' directories, are refused.
    for path in (
        "/tmp/elsewhere.svg",
        f"{session_workspace(_session_ref(ref).session_id)}/out/report.csv",
        "../x",
    ):
        with pytest.raises(SandboxPathError, match="copy the file into the working"):
            sandbox.read_file(ref, path, max_bytes=10)
    for directory in ("out", f"{ONYX_VM_FILES_ROOT}/out"):
        with pytest.raises(HarnessSandboxError, match="not a regular file"):
            sandbox.read_file(ref, directory, max_bytes=10)
    with pytest.raises(SandboxFileNotFoundError):
        sandbox.read_file(ref, f"{ONYX_VM_FILES_ROOT}/missing.svg", max_bytes=10)


@pytest.mark.usefixtures("db_session", "initialize_file_store")
def test_file_store_files_stream_into_the_vm_and_its_sessions(
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    data = os.urandom((5 << 20) // 2)
    store = get_default_file_store()
    file_id = store.save_file(
        content=io.BytesIO(data),
        display_name="big.bin",
        file_origin=FileOrigin.OTHER,
        file_type="application/octet-stream",
    )
    vm_path = f"{ONYX_VM_FILES_ROOT}/files/{file_id}/big.bin"
    try:
        with store.read_file(file_id, use_tempfile=True) as content:
            sandbox.write_file(ref, vm_path, content)
        with store.read_file(file_id, use_tempfile=True) as content:
            sandbox.write_file(ref, "attachments/big.bin", content)
    finally:
        store.delete_file(file_id)

    sandbox_id = str(ref.sandbox_id)
    assert node.agent.files[(sandbox_id, "", vm_path)] == data
    session_file = (sandbox_id, str(ref.session_id), "attachments/big.bin")
    assert node.agent.files[session_file] == data
    # Both writes streamed in data messages of at most 1 MiB.
    chunked = [1 << 20, 1 << 20, len(data) - (2 << 20)]
    assert node.agent.write_chunk_sizes[-2:] == [chunked, chunked]


def test_onyx_root_file_calls_set_up_no_session(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
    tenant_cache: CacheBackend,
) -> None:
    ref = new_ref()
    path = f"{ONYX_VM_FILES_ROOT}/tool-results/call-1.txt"
    sandbox.write_file(ref, path, b"first")
    # Idempotent: a second write replaces the file.
    sandbox.write_file(ref, f"{ONYX_VM_FILES_ROOT}/./tool-results/call-1.txt", b"x")
    sandbox.write_file(
        ref, f"{ONYX_VM_FILES_ROOT}/tool-results/call-2.txt", [b"a", b"b"]
    )

    assert node.agent.files[(str(ref.sandbox_id), "", path)] == b"x"
    listings: list[FileListing] = []

    def pick(listing: FileListing) -> list[str]:
        listings.append(listing)
        return [entry.path for entry in listing.entries if entry.path == path]

    sandbox.delete_listed_files(
        ref, f"{ONYX_VM_FILES_ROOT}/tool-results", pick, max_entries=1
    )
    assert listings[-1].truncated and len(listings[-1].entries) == 1
    sandbox.write_file(ref, path, b"x")
    places = 0
    place = sandbox._place

    def counted_place(placed_ref: HarnessSandboxRef) -> PlacedVm:
        nonlocal places
        places += 1
        return place(placed_ref)

    monkeypatch.setattr(sandbox, "_place", counted_place)
    sandbox.delete_listed_files(
        ref, f"{ONYX_VM_FILES_ROOT}/tool-results", pick, max_entries=10
    )
    # One VM lookup for the listing and its deletes.
    assert places == 1
    assert not listings[-1].truncated
    assert sorted((entry.path, entry.size) for entry in listings[-1].entries) == [
        (path, 1),
        (f"{ONYX_VM_FILES_ROOT}/tool-results/call-2.txt", 2),
    ]
    assert (str(ref.sandbox_id), "", path) not in node.agent.files
    assert not sandbox.delete_file(ref, path)
    outside = f"{ONYX_VM_FILES_ROOT}/keep.txt"
    sandbox.write_file(ref, outside, b"keep")
    # A selected path that the listing did not return stays.
    sandbox.delete_listed_files(
        ref, f"{ONYX_VM_FILES_ROOT}/tool-results", lambda _: [outside], max_entries=10
    )
    assert node.agent.files[(str(ref.sandbox_id), "", outside)] == b"keep"
    sandbox.delete_listed_files(
        ref, f"{ONYX_VM_FILES_ROOT}/missing", pick, max_entries=10
    )
    placement = get_sandbox_placement(tenant_cache, ref.sandbox_id)
    assert placement is not None
    assert (
        harness_state.sessions_on_instance(
            tenant_cache, ref.sandbox_id, (placement.attempt, placement.generation)
        )
        == []
    )


def test_a_tool_result_written_after_its_session_purge_leaves_nothing(
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    other = _session_ref(ref)
    sandbox.write_file(other, f"{session_tool_results(other.session_id)}/a.txt", b"x")
    sandbox.purge_session(
        tenant_id=ref.tenant_id, sandbox_id=ref.sandbox_id, session_id=ref.session_id
    )

    # A write that the purge missed, for example one that was in flight.
    with pytest.raises(HarnessSandboxError, match="was deleted"):
        sandbox.write_file(
            ref, f"{session_tool_results(ref.session_id)}/late.txt", b"late"
        )

    paths = [
        path for (_, _, path) in node.agent.files if path.startswith(TOOL_RESULTS_ROOT)
    ]
    assert paths == [f"{session_tool_results(other.session_id)}/a.txt"]


def _start_command_and_spill(
    sandbox: FirecrackerHarnessSandbox, node: RunningFakeAgent, ref: HarnessSandboxRef
) -> str:
    """Start a command that keeps running and write a tool result in the
    session; the exec session ID. The daemon's call log starts empty."""
    _, started = _run(sandbox.exec_command(ref, "cat", yield_time_ms=250))
    assert started.session_id is not None
    sandbox.write_file(ref, f"{session_tool_results(ref.session_id)}/a.txt", b"x")
    node.agent.daemon_calls.clear()
    return started.session_id


def _purge_calls(
    node: RunningFakeAgent, ref: HarnessSandboxRef
) -> list[tuple[str, str]]:
    """The daemon calls of a purge of a session with a running command: a
    running command could write the tool results again, so it stops first."""
    [execution_id] = node.agent.cancel_calls
    return [
        ("Cancel", execution_id),
        ("DeleteFile", session_tool_results(ref.session_id)),
        ("DeleteFile", session_workspace(ref.session_id)),
    ]


def test_a_purge_cancels_the_session_commands_before_it_deletes_its_tool_results(
    sandbox: FirecrackerHarnessSandbox, node: RunningFakeAgent, new_ref: NewRef
) -> None:
    ref = new_ref()
    _start_command_and_spill(sandbox, node, ref)

    sandbox.purge_session(
        tenant_id=ref.tenant_id, sandbox_id=ref.sandbox_id, session_id=ref.session_id
    )

    assert node.agent.daemon_calls == _purge_calls(node, ref)


def test_a_failed_record_lookup_still_runs_every_purge_step(
    monkeypatch: pytest.MonkeyPatch,
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    session = _start_command_and_spill(sandbox, node, ref)

    def lookup_fails(*_args: object) -> bool:
        raise RuntimeError("cache down")

    monkeypatch.setattr(harness_sandbox, "has_session_records", lookup_fails)

    with pytest.raises(RuntimeError, match="cache down"):
        sandbox.purge_session(
            tenant_id=ref.tenant_id,
            sandbox_id=ref.sandbox_id,
            session_id=ref.session_id,
        )

    assert node.agent.daemon_calls == _purge_calls(node, ref)
    assert harness_state.get_exec_session(tenant_cache, ref.sandbox_id, session) is None


@pytest.mark.parametrize(
    "path",
    [
        ONYX_VM_FILES_ROOT,
        f"{ONYX_VM_FILES_ROOT}x/a.txt",
        f"{ONYX_VM_FILES_ROOT}/../etc/passwd",
        "/home/onyx/workspaces/s1/a.txt",
    ],
)
def test_file_calls_refuse_paths_outside_the_session_and_the_onyx_root(
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
    path: str,
) -> None:
    ref = new_ref()
    with pytest.raises(SandboxPathError):
        sandbox.write_file(ref, path, b"x")
    with pytest.raises(SandboxPathError):
        sandbox.delete_file(ref, path)
    with pytest.raises(SandboxPathError):
        sandbox.delete_listed_files(ref, path, lambda _listing: [], max_entries=10)
    # Refused before the sandbox starts.
    assert node.agent.create_calls == 0


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
    assert result.session_id is not None
    _run(sandbox.write_stdin(ref, result.session_id, "\x03"))
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


def test_the_factory_needs_harness_sandboxes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(harness_factory, "_instance", None)
    monkeypatch.setattr(harness_factory, "HARNESS_SANDBOX_ENABLED", False)
    with pytest.raises(harness_factory.HarnessSandboxUnavailableError):
        harness_factory.get_harness_sandbox()


def test_collect_exec_result_reads_the_stream_to_its_end() -> None:
    result = ExecCommandResult(
        head="x",
        tail="",
        omitted_chars=0,
        session_id=None,
        exit_code=0,
        completion="exited",
        wall_time_seconds=0.1,
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
    assert result.session_id is not None
    commands = [
        e
        for e in node.agent.executions[str(ref.sandbox_id)].values()
        if e.argv[:2] == ["bash", "-c"]
    ]
    assert len(commands) == 1 and commands[0].result is None
    monkeypatch.undo()
    _, result = _run(sandbox.write_stdin(ref, result.session_id, "hi"))
    assert _output(result) == "hi"


@pytest.mark.usefixtures("node")
def test_ctrl_c_on_an_ended_command_reports_its_exit(
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    sandbox: FirecrackerHarnessSandbox,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    _, result = _run(sandbox.exec_command(ref, "cat", yield_time_ms=250))
    session = result.session_id
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
        _run(sandbox.exec_command(ref, "cat", yield_time_ms=250))[1].session_id
        for _ in range(3)
    )
    assert first and second and third
    with pytest.raises(ExecSessionNotFoundError):
        _run(sandbox.write_stdin(ref, first, "x"))
    assert _output(_run(sandbox.write_stdin(ref, second, "y"))[1]) == "y"


def test_a_skill_copies_once_per_version_and_vm(
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    sandbox_id = str(ref.sandbox_id)

    def copied() -> dict[str, bytes]:
        return {
            key[2].removeprefix(CHAT_SKILLS_PATH + "/"): data
            for key, data in node.agent.files.items()
            if key[:2] == (sandbox_id, "") and key[2].startswith(CHAT_SKILLS_PATH)
        }

    v1: FileSet = {
        "report/SKILL.md": b"# report",
        "report/scripts/run.sh": b"#!/bin/sh\necho 1",
        "report/data.bin": b"\x7fELF...",
    }
    assert sandbox.install_skill(ref, "report", "v1", v1)
    assert copied() == {**v1, "report/.version": b"v1"}
    folder = (sandbox_id, "", f"{CHAT_SKILLS_PATH}/report")
    assert {
        path: node.agent.file_modes[(*folder[:2], f"{folder[2]}/{path}")]
        for path in ("SKILL.md", "scripts/run.sh", "data.bin")
    } == {"SKILL.md": 0o644, "scripts/run.sh": 0o755, "data.bin": 0o755}
    assert not sandbox.install_skill(ref, "report", "v1", v1)

    assert sandbox.install_skill(ref, "report", "v2", {"report/SKILL.md": b"# v2"})
    assert copied() == {"report/SKILL.md": b"# v2", "report/.version": b"v2"}

    # A new VM instance has no skills.
    vm = node.agent.vms[sandbox_id]
    sandbox._client_factory.client(node.address).stop(
        sandbox_id=sandbox_id, attempt=vm.attempt, generation=vm.generation
    )
    assert sandbox.install_skill(ref, "report", "v2", {"report/SKILL.md": b"# v2"})


def test_a_skill_with_files_outside_its_folder_is_refused(
    sandbox: FirecrackerHarnessSandbox,
    new_ref: NewRef,
) -> None:
    ref = new_ref()
    with pytest.raises(HarnessSandboxError):
        sandbox.install_skill(
            ref, "report", "v1", {"report/SKILL.md": b"", "other/x": b""}
        )
    with pytest.raises(HarnessSandboxError):
        sandbox.install_skill(ref, "../report", "v1", {})
