"""Guest daemon exec and file calls through a fake host agent pass-through:
typed results and typed errors from google.rpc.ErrorInfo."""

import io
import zipfile
from collections.abc import Generator
from dataclasses import dataclass

import grpc
import pytest

from onyx.microvm.agent_client import (
    HostAgentClient,
    HostAgentErrorReason,
    VmNotRunningError,
    new_sandboxd_key,
)
from onyx.microvm.daemon_client import (
    SandboxDaemonClient,
    SandboxDaemonError,
    SandboxDaemonErrorReason,
)
from onyx.microvm.generated.hostagent.v1 import hostagent_pb2
from onyx.microvm.generated.sandboxd.v1 import sandboxd_pb2
from onyx.microvm.models import (
    CancelSignal,
    ExecCommand,
    ExecCompletion,
    ExecEvent,
    ExecGap,
    ExecOutput,
    ExecResult,
    ExecStarted,
    ExecState,
    FileType,
    OutputStream,
    ZipSummary,
)
from tests.external_dependency_unit.microvm.fake_agent import (
    FakeHostAgent,
    InsecureClientFactory,
    RunningFakeAgent,
)

SANDBOX_ID = "0f4b8d2e-7c1a-4e5b-9a3d-2b6c8e1f4a70"
SESSION = "s1"


@dataclass
class Guest:
    agent: FakeHostAgent
    host: HostAgentClient
    daemon: SandboxDaemonClient


@pytest.fixture
def guest() -> Generator[Guest, None, None]:
    running = RunningFakeAgent(FakeHostAgent())
    factory = InsecureClientFactory()
    host = factory.client(running.address)
    key = new_sandboxd_key()
    created = host.create(
        sandbox_id=SANDBOX_ID,
        attempt=1,
        template="tpl-1",
        vcpus=2,
        mem_mib=2048,
        scratch_gib=4,
        tenant_id="public",
        sandboxd_key=key,
    )
    daemon = SandboxDaemonClient(host.channel, sandbox_id=SANDBOX_ID, sandboxd_key=key)
    daemon.init(
        generation=created.vm.generation, scratch_gib=4, env={}, session_ids=[SESSION]
    )
    yield Guest(running.agent, host, daemon)
    factory.close()
    running.stop()


def _stdout(events: list[ExecEvent]) -> bytes:
    return b"".join(
        e.data
        for e in events
        if isinstance(e, ExecOutput) and e.stream is OutputStream.STDOUT
    )


def test_run_streams_started_output_and_result(guest: Guest) -> None:
    events = list(
        guest.daemon.run(
            ExecCommand(argv=["echo", "hi"], labels={"session_id": SESSION})
        )
    )

    assert isinstance(events[0], ExecStarted)
    assert _stdout(events) == b"hi\n"
    result = events[-1]
    assert isinstance(result, ExecResult)
    assert result.completion is ExecCompletion.EXITED
    assert result.exit_code == 0
    assert result.finished_at is not None


def test_run_streams_until_a_running_command_ends(guest: Guest) -> None:
    events = guest.daemon.run(ExecCommand(argv=["cat"], stdin=True))
    started = next(events)
    assert isinstance(started, ExecStarted)

    guest.daemon.interact(started.execution_id, data=b"late", close_stdin=True)

    rest = list(events)
    assert _stdout(rest) == b"late"
    assert isinstance(rest[-1], ExecResult)


def test_closing_a_run_keeps_the_command_running(guest: Guest) -> None:
    unread = guest.daemon.run(ExecCommand(argv=["echo", "never"]))
    events = guest.daemon.run(ExecCommand(argv=["sleep", "60"]))
    started = next(events)
    assert isinstance(started, ExecStarted)
    events.close()

    [record] = guest.daemon.list_executions()
    assert record.execution_id == started.execution_id
    assert record.state is ExecState.RUNNING
    del unread  # an unread run never starts its command


def test_a_stopped_vm_breaks_an_open_run(guest: Guest) -> None:
    events = guest.daemon.run(ExecCommand(argv=["sleep", "60"]))
    assert isinstance(next(events), ExecStarted)
    vm = guest.agent.vms[SANDBOX_ID]

    guest.host.stop(sandbox_id=SANDBOX_ID, attempt=vm.attempt, generation=vm.generation)

    with pytest.raises(VmNotRunningError):
        next(events)


def test_run_of_a_missing_program_raises_start_failed(guest: Guest) -> None:
    with pytest.raises(SandboxDaemonError) as exc:
        list(guest.daemon.run(ExecCommand(argv=["nope"])))
    assert exc.value.reason is SandboxDaemonErrorReason.START_FAILED
    assert exc.value.code is grpc.StatusCode.INVALID_ARGUMENT


def test_calls_before_init_raise_not_initialized(guest: Guest) -> None:
    guest.agent.daemon_inits.clear()
    with pytest.raises(SandboxDaemonError) as exc:
        guest.daemon.start(ExecCommand(argv=["echo"]))
    assert exc.value.reason is SandboxDaemonErrorReason.NOT_INITIALIZED


def test_start_then_stream_resumes_from_offsets(guest: Guest) -> None:
    started = guest.daemon.start(ExecCommand(argv=["fail", "3"]))

    events = list(guest.daemon.stream(started.execution_id))
    result = events[-1]
    assert isinstance(result, ExecResult)
    assert result.exit_code == 3
    stderr = [e for e in events if isinstance(e, ExecOutput)]
    assert [(e.stream, e.offset, e.data) for e in stderr] == [
        (OutputStream.STDERR, 0, b"failed\n")
    ]

    resumed = list(guest.daemon.stream(started.execution_id, stderr_offset=4))
    assert [e for e in resumed if isinstance(e, ExecOutput)][0].data == b"ed\n"


def test_stream_reports_a_gap_for_dropped_output(guest: Guest) -> None:
    started = guest.daemon.start(ExecCommand(argv=["echo", "abcdef"]))
    guest.agent.executions[SANDBOX_ID][started.execution_id].stdout_kept_from = 3

    events = list(guest.daemon.stream(started.execution_id))

    gap = next(e for e in events if isinstance(e, ExecGap))
    assert (gap.stream, gap.start, gap.end) == (OutputStream.STDOUT, 0, 3)
    output = next(e for e in events if isinstance(e, ExecOutput))
    assert (output.offset, output.data) == (3, b"def\n")


def test_stream_of_an_unknown_execution_raises_not_found(guest: Guest) -> None:
    with pytest.raises(SandboxDaemonError) as exc:
        list(guest.daemon.stream("exec-404"))
    assert exc.value.reason is SandboxDaemonErrorReason.EXECUTION_NOT_FOUND
    assert exc.value.code is grpc.StatusCode.NOT_FOUND


def test_interact_writes_stdin_and_closes_it(guest: Guest) -> None:
    started = guest.daemon.start(ExecCommand(argv=["cat"], stdin=True))

    assert guest.daemon.interact(started.execution_id, data=b"ab") == 2
    assert guest.daemon.interact(started.execution_id, data=b"c", close_stdin=True)

    events = list(guest.daemon.stream(started.execution_id))
    assert _stdout(events) == b"abc"


def test_interact_without_stdin_raises_stdin_not_open(guest: Guest) -> None:
    started = guest.daemon.start(ExecCommand(argv=["sleep", "60"]))
    with pytest.raises(SandboxDaemonError) as exc:
        guest.daemon.interact(started.execution_id, data=b"x")
    assert exc.value.reason is SandboxDaemonErrorReason.STDIN_NOT_OPEN


def test_cancel_returns_canceled_then_the_same_result(guest: Guest) -> None:
    started = guest.daemon.start(
        ExecCommand(argv=["sleep", "60"], deadline_seconds=120)
    )
    assert guest.daemon.health().running_executions == 1

    canceled = guest.daemon.cancel(started.execution_id)
    assert canceled.result is not None
    assert canceled.result.completion is ExecCompletion.CANCELED
    assert not canceled.already_ended
    assert not canceled.signaled

    again = guest.daemon.cancel(started.execution_id)
    assert again.already_ended
    assert again.result is not None
    assert again.result.completion is ExecCompletion.CANCELED

    with pytest.raises(SandboxDaemonError) as exc:
        guest.daemon.interact(started.execution_id, data=b"x")
    assert exc.value.reason is SandboxDaemonErrorReason.EXECUTION_ENDED


def test_cancel_with_sigint_signals_and_returns_no_result(guest: Guest) -> None:
    started = guest.daemon.start(
        ExecCommand(argv=["sleep", "60"], session_id="s-1", cwd="sub")
    )
    [execution] = guest.agent.executions[SANDBOX_ID].values()
    assert execution.session_id == "s-1"

    sent = guest.daemon.cancel(started.execution_id, CancelSignal.SIGINT)
    assert sent.signaled
    assert sent.result is None
    assert not sent.already_ended
    assert execution.signaled == sandboxd_pb2.CANCEL_SIGNAL_SIGINT


def test_cancel_of_an_unknown_execution_raises_not_found(guest: Guest) -> None:
    with pytest.raises(SandboxDaemonError) as exc:
        guest.daemon.cancel("exec-404")
    assert exc.value.reason is SandboxDaemonErrorReason.EXECUTION_NOT_FOUND


def test_list_and_inspect_filter_by_labels(guest: Guest) -> None:
    running = guest.daemon.start(
        ExecCommand(argv=["sleep", "60"], labels={"session_id": "a", "kind": "dev"})
    )
    guest.daemon.start(ExecCommand(argv=["echo"], labels={"session_id": "b"}))

    records = guest.daemon.list_executions({"session_id": "a"})
    assert [r.execution_id for r in records] == [running.execution_id]
    assert records[0].state is ExecState.RUNNING
    assert records[0].result is None
    assert len(guest.daemon.list_executions()) == 2

    guest.daemon.cancel(running.execution_id)
    record = guest.daemon.inspect(running.execution_id)
    assert record.state is ExecState.ENDED
    assert record.result is not None
    assert record.argv == ["sleep", "60"]
    with pytest.raises(SandboxDaemonError) as exc:
        guest.daemon.inspect("exec-404")
    assert exc.value.reason is SandboxDaemonErrorReason.EXECUTION_NOT_FOUND


def test_write_then_read_a_file_in_chunks(guest: Guest) -> None:
    data = bytes(range(256)) * 1024 * 5  # 1.25 MiB: two write chunks
    written = guest.daemon.write_file(
        session_id=SESSION, path="outputs/a.bin", data=data
    )
    assert written.info.path == "outputs/a.bin"
    assert written.info.size == len(data)

    info, chunks = guest.daemon.read_file(session_id=SESSION, path="outputs/a.bin")
    parts = list(chunks)
    assert info.type is FileType.REGULAR
    assert b"".join(parts) == data
    assert max(len(p) for p in parts) <= 64 << 10

    _, tail = guest.daemon.read_file(
        session_id=SESSION, path="outputs/a.bin", offset=10, length=5
    )
    assert b"".join(tail) == data[10:15]


def test_write_without_overwrite_raises_file_exists(guest: Guest) -> None:
    guest.daemon.write_file(session_id=SESSION, path="a.txt", data=b"1")
    with pytest.raises(SandboxDaemonError) as exc:
        guest.daemon.write_file(
            session_id=SESSION, path="a.txt", data=b"2", overwrite=False
        )
    assert exc.value.reason is SandboxDaemonErrorReason.FILE_EXISTS
    assert exc.value.code is grpc.StatusCode.ALREADY_EXISTS


def test_read_of_a_missing_file_raises_at_the_call(guest: Guest) -> None:
    with pytest.raises(SandboxDaemonError) as exc:
        guest.daemon.read_file(session_id=SESSION, path="missing.txt")
    assert exc.value.reason is SandboxDaemonErrorReason.FILE_NOT_FOUND


def test_upload_picks_a_free_name(guest: Guest) -> None:
    first = guest.daemon.upload_file(session_id=SESSION, file_name="r.pdf", data=b"one")
    second = guest.daemon.upload_file(
        session_id=SESSION, file_name="r.pdf", data=b"two"
    )
    assert first.info.path == "attachments/r.pdf"
    assert second.info.path == "attachments/r_1.pdf"


def test_upload_with_a_path_in_the_name_raises_invalid_argument(guest: Guest) -> None:
    with pytest.raises(SandboxDaemonError) as exc:
        guest.daemon.upload_file(session_id=SESSION, file_name="a/b.pdf", data=b"x")
    assert exc.value.reason is SandboxDaemonErrorReason.INVALID_ARGUMENT


def test_list_files_one_directory_or_the_tree(guest: Guest) -> None:
    for path in ("outputs/a.txt", "outputs/sub/b.txt", "node_modules/x.js"):
        guest.daemon.write_file(session_id=SESSION, path=path, data=b"x")

    top = guest.daemon.list_files(session_id=SESSION, path="outputs")
    assert [(e.path, e.type) for e in top.entries] == [
        ("outputs/sub", FileType.DIRECTORY),
        ("outputs/a.txt", FileType.REGULAR),
    ]
    tree = guest.daemon.list_files(
        session_id=SESSION, recursive=True, exclude_names=["node_modules"]
    )
    assert {e.path for e in tree.entries if e.type is FileType.REGULAR} == {
        "outputs/a.txt",
        "outputs/sub/b.txt",
    }
    cut = guest.daemon.list_files(session_id=SESSION, recursive=True, max_entries=1)
    assert cut.truncated and len(cut.entries) == 1

    guest.daemon.write_file(session_id=SESSION, path="outputs/.hidden", data=b"x")
    shallow = guest.daemon.list_files(
        session_id=SESSION,
        path="outputs",
        recursive=True,
        max_depth=1,
        skip_hidden=True,
    )
    assert [e.path for e in shallow.entries] == ["outputs/sub", "outputs/a.txt"]
    assert shallow.truncated


def test_list_files_with_dotdot_raises_invalid_argument(guest: Guest) -> None:
    with pytest.raises(SandboxDaemonError) as exc:
        guest.daemon.list_files(session_id=SESSION, path="../other")
    assert exc.value.reason is SandboxDaemonErrorReason.INVALID_ARGUMENT


def test_delete_file_and_directory(guest: Guest) -> None:
    guest.daemon.write_file(session_id=SESSION, path="d/a.txt", data=b"x")
    guest.daemon.write_file(session_id=SESSION, path="d/b.txt", data=b"x")

    assert guest.daemon.delete_file(session_id=SESSION, path="d/a.txt")
    assert not guest.daemon.delete_file(session_id=SESSION, path="d/a.txt")
    with pytest.raises(SandboxDaemonError) as exc:
        guest.daemon.delete_file(session_id=SESSION, path="d")
    assert exc.value.reason is SandboxDaemonErrorReason.INVALID_ARGUMENT
    assert guest.daemon.delete_file(session_id=SESSION, path="d", recursive=True)


def _drain_zip(gen: Generator[bytes, None, ZipSummary]) -> tuple[bytes, ZipSummary]:
    data = bytearray()
    while True:
        try:
            data += next(gen)
        except StopIteration as stop:
            return bytes(data), stop.value


def test_zip_files_streams_a_zip_and_returns_the_summary(guest: Guest) -> None:
    guest.daemon.write_file(session_id=SESSION, path="outputs/a.txt", data=b"aa")
    guest.daemon.write_file(session_id=SESSION, path="outputs/b/c.txt", data=b"c")
    guest.daemon.write_file(session_id=SESSION, path="outputs/.git/x", data=b"g")
    guest.daemon.write_file(session_id=SESSION, path="outputs/dist/y", data=b"d")

    data, summary = _drain_zip(
        guest.daemon.zip_files(
            session_id=SESSION,
            path="outputs",
            exclude_names=["dist"],
            skip_hidden=True,
        )
    )

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert sorted(zf.namelist()) == ["a.txt", "b/c.txt"]
    assert (summary.files, summary.input_bytes, summary.zip_bytes) == (
        2,
        3,
        len(data),
    )


def test_zip_of_a_directory_with_only_excluded_files_is_empty(guest: Guest) -> None:
    guest.daemon.write_file(session_id=SESSION, path="outputs/.git/x", data=b"g")

    data, summary = _drain_zip(
        guest.daemon.zip_files(session_id=SESSION, path="outputs", skip_hidden=True)
    )

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.namelist() == []
    assert summary.files == 0
    with pytest.raises(SandboxDaemonError) as exc:
        _drain_zip(guest.daemon.zip_files(session_id=SESSION, path="missing"))
    assert exc.value.reason is SandboxDaemonErrorReason.FILE_NOT_FOUND


def test_zip_files_over_a_limit_raises_limit_exceeded(guest: Guest) -> None:
    guest.agent.zip_max_input_bytes = 1
    guest.daemon.write_file(session_id=SESSION, path="outputs/a.txt", data=b"aa")
    with pytest.raises(SandboxDaemonError) as exc:
        _drain_zip(guest.daemon.zip_files(session_id=SESSION, path="outputs"))
    assert exc.value.reason is SandboxDaemonErrorReason.LIMIT_EXCEEDED
    assert exc.value.code is grpc.StatusCode.RESOURCE_EXHAUSTED


def test_every_proto_reason_has_a_typed_reason() -> None:
    names = {
        v.name for v in sandboxd_pb2.DESCRIPTOR.enum_types_by_name["ErrorReason"].values
    } - {"ERROR_REASON_UNSPECIFIED"}
    assert names == {r.value for r in SandboxDaemonErrorReason}

    agent_names = {
        v.name
        for v in hostagent_pb2.DESCRIPTOR.enum_types_by_name["ErrorReason"].values
    } - {"ERROR_REASON_UNSPECIFIED"}
    assert agent_names == {r.value for r in HostAgentErrorReason}
