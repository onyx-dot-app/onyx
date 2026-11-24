"""Background chat file copies into the sandbox VM (`sandbox/file_copies.py`)
against Redis or Postgres, the file store and a fake host agent: whole files
only, retries, the listing that finds files in place, cleanup, chat
generations, overlapping turns, purges, the limits, the pod's slots and
shutdown, the busy mark, and the `[files]` status line."""

import io
import os
import threading
import time
from collections.abc import Buffer, Callable, Generator
from typing import IO, Protocol
from uuid import UUID, uuid4

import grpc
import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.agents.tools import ToolInvocation
from onyx.cache.interface import CacheBackend
from onyx.configs.constants import FileOrigin
from onyx.db.models import FileRecord, User
from onyx.file_store.file_store import (
    FILE_SIZE_MISSING_SENTINEL,
    get_default_file_store,
)
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import ToolResult
from onyx.microvm.daemon_client import SandboxDaemonErrorReason
from onyx.microvm.models import FileListing
from onyx.server.features.build.sandbox import harness_factory
from onyx.server.features.build.sandbox.file_copy_state import copy_generation_key
from onyx.server.features.build.sandbox.firecracker import harness_state
from onyx.server.features.build.sandbox.firecracker.harness_sandbox import (
    FirecrackerHarnessSandbox,
)
from onyx.server.features.build.sandbox.harness_base import (
    HarnessSandboxError,
    SandboxPathError,
    SessionFiles,
)
from onyx.server.features.build.sandbox.models import HarnessSandboxRef
from onyx.server.settings.models import Settings
from onyx.tools.models import ToolContext
from onyx.tools.tool_implementations.sandbox import file_copies
from onyx.tools.tool_implementations.sandbox.file_copies import (
    FileCopyPool,
    TurnFileCopies,
)
from onyx.tools.tool_implementations.sandbox.models import VmChatFile
from onyx.tools.tool_implementations.sandbox.sandbox_tools import ExecCommandTool
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.microvm.conftest import (
    TENANT_ID,
    AddNode,
    NewFileCopyPool,
    forget_sandbox_keys,
)
from tests.external_dependency_unit.microvm.fake_agent import (
    ANY_PATH,
    InsecureClientFactory,
    RunningFakeAgent,
    WriteFailure,
)

pytestmark = pytest.mark.usefixtures("tenant_context", "initialize_file_store")

DONE = "All files are in attachments/."
_INDENT = "\n        "

StoreFile = Callable[[bytes], str]


class NewTurn(Protocol):
    def __call__(
        self,
        chat_files: list[VmChatFile] | None = None,
        chat: UUID | None = None,
        turn_user: User | None = None,
    ) -> tuple[SandboxTurn, HarnessSandboxRef]: ...


Idle = Callable[[], bool]


@pytest.fixture
def sandbox(
    monkeypatch: pytest.MonkeyPatch, client_factory: InsecureClientFactory
) -> FirecrackerHarnessSandbox:
    """The process's harness sandbox, on the fake agents, with fast retries."""
    instance = FirecrackerHarnessSandbox(
        template="tpl-1", client_factory=client_factory
    )
    monkeypatch.setattr(harness_factory, "HARNESS_SANDBOX_ENABLED", True)
    monkeypatch.setattr(harness_factory, "_instance", instance)
    monkeypatch.setattr(file_copies, "RETRY_PAUSE_SECONDS", 0.0)
    return instance


@pytest.fixture
def node(add_node: AddNode) -> RunningFakeAgent:
    return add_node(f"fcp-{uuid4().hex[:6]}")


def _wait_until(condition: Callable[[], bool], seconds: float = 15) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "the condition did not hold in time"
        time.sleep(0.02)  # test-flakes: allow polls a condition until a deadline


@pytest.fixture
def idle(monkeypatch: pytest.MonkeyPatch, new_file_copy_pool: NewFileCopyPool) -> Idle:
    """Whether every copy that the test started has ended. The test starts
    with a new pod pool; a pool that it makes for another pod counts too."""
    pools: list[FileCopyPool] = []
    init = FileCopyPool.__init__

    def tracked(pool: FileCopyPool) -> None:
        init(pool)
        pools.append(pool)

    monkeypatch.setattr(FileCopyPool, "__init__", tracked)
    new_file_copy_pool()
    return lambda: all(pool.idle() for pool in pools)


@pytest.fixture
def user(make_test_user: MakeTestUser) -> User:
    return make_test_user("file_copies")


@pytest.fixture
def chat_session_id() -> UUID:
    return uuid4()


@pytest.fixture
def new_turn(
    user: User,
    chat_session_id: UUID,
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,  # noqa: ARG001
    node: RunningFakeAgent,
    idle: Idle,
    store_file: StoreFile,  # noqa: ARG001
) -> Generator[NewTurn, None, None]:
    """A new turn of the chat (or of another chat of the user), after its
    first sandbox call, which starts the copy of `chat_files` (None: no
    copy). It drains the copies before `store_file` deletes the files."""
    refs: list[HarnessSandboxRef] = []

    def new(
        chat_files: list[VmChatFile] | None = None,
        chat: UUID | None = None,
        turn_user: User | None = None,
    ) -> tuple[SandboxTurn, HarnessSandboxRef]:
        turn = SandboxTurn(
            tenant_id=TENANT_ID,
            user=turn_user or user,
            chat_session_id=chat or chat_session_id,
            vm_chat_files=chat_files or [],
            copy_vm_chat_files=chat_files is not None,
        )
        refs.append(turn.start_call())
        return turn, refs[-1]

    yield new
    # A test that fails early leaves no write waiting.
    for gate in node.agent.write_gates.values():
        gate.set()
    for _, hold in node.agent.write_holds.values():
        hold.set()
    _wait_until(idle, 30)
    for ref in refs:
        tenant_cache.delete(copy_generation_key(ref.session_id))
        harness_state.clear_retention_mark(tenant_cache, ref.session_id)
    for sandbox_id in {ref.sandbox_id for ref in refs}:
        forget_sandbox_keys(tenant_cache, sandbox_id)
        for prefix in harness_state.SANDBOX_STATE_PREFIXES:
            tenant_cache.delete(prefix + str(sandbox_id))


@pytest.fixture
def store_file() -> Generator[StoreFile, None, None]:
    file_ids: list[str] = []
    store = get_default_file_store()

    def save(data: bytes) -> str:
        file_ids.append(
            store.save_file(
                content=io.BytesIO(data),
                display_name="f.bin",
                file_origin=FileOrigin.OTHER,
                file_type="application/octet-stream",
            )
        )
        return file_ids[-1]

    yield save
    for file_id in file_ids:
        store.delete_file(file_id, error_on_missing=False)


def _file(file_id: str, path: str) -> VmChatFile:
    return VmChatFile(file_id=file_id, path=path)


def _copies(turn: SandboxTurn) -> TurnFileCopies:
    assert turn.file_copies is not None
    return turn.file_copies


def _status(turn: SandboxTurn) -> str | None:
    return _copies(turn).status.line()


def _wait_for_status(turn: SandboxTurn, part: str) -> None:
    """Wait for a status line with `part`; earlier lines are read and
    dropped."""
    _wait_until(lambda: part in (_status(turn) or ""))


def _key(ref: HarnessSandboxRef, path: str) -> tuple[str, str, str]:
    return (str(ref.sandbox_id), str(ref.session_id), path)


def _deletes(node: RunningFakeAgent) -> list[str]:
    return [path for call, path in node.agent.daemon_calls if call == "DeleteFile"]


def _exec(turn: SandboxTurn) -> ToolResult:
    outcome = ExecCommandTool(turn).run(
        ToolInvocation(
            call_id="call-1",
            arguments={"cmd": "echo hi"},
            cancellation=CancellationSignal(),
            update=lambda _progress: None,
        ),
        ToolContext(),
    )
    assert isinstance(outcome, ToolResult)
    return outcome


def _restart(
    client_factory: InsecureClientFactory,
    node: RunningFakeAgent,
    ref: HarnessSandboxRef,
) -> None:
    """Stop the VM, which loses its files."""
    vm = node.agent.vms[str(ref.sandbox_id)]
    client_factory.client(node.address).stop(
        sandbox_id=str(ref.sandbox_id), attempt=vm.attempt, generation=vm.generation
    )


class _Wrapped(SessionFiles):
    """Session files that pass every call to `files`."""

    def __init__(self, files: SessionFiles) -> None:
        self.files = files

    def write(self, path: str, data: IO[bytes], *, timeout_seconds: float) -> None:
        self.files.write(path, data, timeout_seconds=timeout_seconds)

    def delete(self, path: str) -> bool:
        return self.files.delete(path)

    def list_files(self, directory: str, *, max_entries: int) -> FileListing:
        return self.files.list_files(directory, max_entries=max_entries)

    def mark_busy(self, seconds: float | None) -> None:
        self.files.mark_busy(seconds)


def _wrap(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    wrap: Callable[[SessionFiles], SessionFiles],
) -> None:
    """Wrap the session files of `sandbox` until the test undoes it."""
    session_files = sandbox.session_files
    monkeypatch.setattr(sandbox, "session_files", lambda ref: wrap(session_files(ref)))


def test_a_copy_is_never_partial_at_its_path(
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    data = os.urandom(3 << 20)
    file_id = store_file(data)
    hold = threading.Event()
    node.agent.write_holds["attachments/big.bin"] = (2, hold)
    turn, ref = new_turn([_file(file_id, "attachments/big.bin")])

    _wait_until(lambda: "attachments/big.bin" in node.agent.write_held)
    assert _key(ref, "attachments/big.bin") not in node.agent.files
    assert _status(turn) == "[files] Copying: attachments/big.bin."
    hold.set()
    _wait_until(idle)
    assert node.agent.files[_key(ref, "attachments/big.bin")] == data
    assert node.agent.write_chunk_sizes[-1] == [1 << 20] * 3


def test_the_status_line_comes_only_when_the_status_changes(
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    small = store_file(b"a")
    large = store_file(b"b" * 64)
    gate = threading.Event()
    node.agent.write_gates["attachments/b.txt"] = gate
    files = [_file(large, "attachments/b.txt"), _file(small, "attachments/a.txt")]
    turn, _ = new_turn(files)
    _wait_until(lambda: "attachments/b.txt" in node.agent.write_waiting)
    lines: list[str] = []

    def a_done() -> bool:
        line = _status(turn)
        if line is not None:
            lines.append(line)
        return line is not None and "Done since last status" in line

    # Each read gives the line only when it changed.
    _wait_until(a_done)
    assert lines[:-1] in (
        [],
        ["[files] Copying: attachments/b.txt, attachments/a.txt."],
    )
    assert lines[-1] == (
        "[files] Copying: attachments/b.txt."
        f"{_INDENT}Done since last status: attachments/a.txt."
    )
    assert _status(turn) is None

    gate.set()
    _wait_until(idle)
    assert _status(turn) == (
        f"[files] Done since last status: attachments/b.txt.{_INDENT}{DONE}"
    )
    assert _status(turn) is None

    # A turn whose files are all in place says nothing.
    next_turn, _ = new_turn(files)
    _wait_until(idle)
    assert _status(next_turn) is None


def test_a_failed_copy_is_tried_three_times_and_again_next_turn(
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    file_id = store_file(b"a")
    node.agent.write_failures["attachments/a.txt"] = WriteFailure(
        SandboxDaemonErrorReason.INTERNAL, count=3
    )
    files = [_file(file_id, "attachments/a.txt")]
    turn, ref = new_turn(files)
    _wait_until(idle)

    assert node.agent.write_paths.count("attachments/a.txt") == 3
    assert _key(ref, "attachments/a.txt") not in node.agent.files
    assert _status(turn) == (
        "[files] Failed: attachments/a.txt (the sandbox did not take the file); "
        "retrying next turn."
    )

    # The next turn tries it again.
    next_turn, ref = new_turn(files)
    _wait_until(idle)
    assert node.agent.files[_key(ref, "attachments/a.txt")] == b"a"
    assert node.agent.write_paths.count("attachments/a.txt") == 4
    assert _status(next_turn) == (
        f"[files] Done since last status: attachments/a.txt.{_INDENT}{DONE}"
    )


class _NoStart(FirecrackerHarnessSandbox):
    def session_files(self, ref: HarnessSandboxRef) -> SessionFiles:  # noqa: ARG002
        raise HarnessSandboxError("no capacity")


@pytest.mark.parametrize(
    "reason",
    [
        "the sandbox did not start",
        "the file store did not return the file",
        "the sandbox did not respond",
        "the copy stopped on an error",
    ],
)
def test_each_failure_has_its_reason(
    monkeypatch: pytest.MonkeyPatch,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    client_factory: InsecureClientFactory,
    store_file: StoreFile,
    idle: Idle,
    reason: str,
) -> None:
    file_id = store_file(b"a" * 64)
    chat_files = [_file(file_id, "attachments/a.txt")]
    downloads: list[str] = []
    if reason == "the file store did not return the file":
        store = get_default_file_store()

        def unreadable(
            file_id: str,
            mode: str | None = None,  # noqa: ARG001
            use_tempfile: bool = False,  # noqa: ARG001
        ) -> IO[bytes]:
            downloads.append(file_id)
            raise OSError("the store is down")

        monkeypatch.setattr(store, "read_file", unreadable)
        monkeypatch.setattr(file_copies, "get_default_file_store", lambda: store)
    elif reason == "the sandbox did not respond":
        # The write's deadline passed.
        node.agent.write_failures["attachments/a.txt"] = WriteFailure(
            grpc.StatusCode.DEADLINE_EXCEEDED
        )
    elif reason == "the copy stopped on an error":
        # The file records cannot be read.
        def no_records(*_args: object) -> None:
            raise ConnectionError("the database is gone")

        monkeypatch.setattr(file_copies, "get_filerecords_by_file_ids", no_records)
    if reason == "the sandbox did not start":
        _, ref = new_turn()
        copies = TurnFileCopies(
            ref, _NoStart(template="tpl-1", client_factory=client_factory), chat_files
        )
    else:
        turn, _ = new_turn(chat_files)
        copies = _copies(turn)
    _wait_until(idle, 30)

    assert copies.status.line() == (
        f"[files] Failed: attachments/a.txt ({reason}); retrying next turn."
    )
    if reason == "the file store did not return the file":
        # Each try asks the store again.
        assert downloads == [file_id] * 3
    if reason == "the sandbox did not respond":
        # No more tries.
        assert node.agent.write_paths.count("attachments/a.txt") == 1


def test_a_file_missing_from_the_file_store_is_not_copied(
    new_turn: NewTurn, idle: Idle
) -> None:
    turn, _ = new_turn([_file("no-such-file", "attachments/a.txt")])
    _wait_until(idle)
    assert _status(turn) == (
        "[files] Not copied: attachments/a.txt (the file is not in the file store)."
    )


def test_a_file_without_a_size_or_a_stored_object_is_not_copied_alone(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    """A file record with no size whose stored object is gone: that file is
    not copied, and the other files are."""
    gone, kept = store_file(b"gone"), store_file(b"kept")
    db_session.execute(
        update(FileRecord).where(FileRecord.file_id == gone).values(file_size=None)
    )
    db_session.commit()
    store = get_default_file_store()
    get_file_size = store.get_file_size

    def missing_object(file_id: str, db_session: Session | None = None) -> int | None:
        if file_id == gone:
            raise FileNotFoundError(f"Object for file {file_id} does not exist")
        return get_file_size(file_id, db_session)

    monkeypatch.setattr(store, "get_file_size", missing_object)
    monkeypatch.setattr(file_copies, "get_default_file_store", lambda: store)
    turn, ref = new_turn(
        [_file(gone, "attachments/gone.txt"), _file(kept, "attachments/kept.txt")]
    )
    _wait_until(idle)

    assert node.agent.files[_key(ref, "attachments/kept.txt")] == b"kept"
    assert _status(turn) == (
        "[files] Not copied: attachments/gone.txt (the file is not in the file "
        "store)."
        f"{_INDENT}Done since last status: attachments/kept.txt."
        f"{_INDENT}All other files are in attachments/."
    )


def test_a_file_whose_stored_object_is_known_gone_is_not_copied(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    """A file record whose size is FILE_SIZE_MISSING_SENTINEL: the file is
    not downloaded or copied, and the other files are."""
    gone, kept = store_file(b"gone"), store_file(b"kept")
    db_session.execute(
        update(FileRecord)
        .where(FileRecord.file_id == gone)
        .values(file_size=FILE_SIZE_MISSING_SENTINEL)
    )
    db_session.commit()
    downloads: list[str] = []
    store = get_default_file_store()
    read_file = store.read_file

    def counted(
        file_id: str, mode: str | None = None, use_tempfile: bool = False
    ) -> IO[bytes]:
        downloads.append(file_id)
        return read_file(file_id, mode, use_tempfile)

    monkeypatch.setattr(store, "read_file", counted)
    monkeypatch.setattr(file_copies, "get_default_file_store", lambda: store)
    turn, ref = new_turn(
        [_file(gone, "attachments/gone.txt"), _file(kept, "attachments/kept.txt")]
    )
    _wait_until(idle)

    assert downloads == [kept]
    assert "attachments/gone.txt" not in node.agent.write_paths
    assert node.agent.files[_key(ref, "attachments/kept.txt")] == b"kept"
    assert _status(turn) == (
        "[files] Not copied: attachments/gone.txt (the file is not in the file "
        "store)."
        f"{_INDENT}Done since last status: attachments/kept.txt."
        f"{_INDENT}All other files are in attachments/."
    )


def test_a_file_is_copied_once_per_vm_instance_and_again_when_wrong(
    new_turn: NewTurn,
    node: RunningFakeAgent,
    client_factory: InsecureClientFactory,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    file_id = store_file(b"original")
    files = [_file(file_id, "attachments/a.txt")]
    _, ref = new_turn(files)
    _wait_until(idle)
    key = _key(ref, "attachments/a.txt")
    assert node.agent.files[key] == b"original"

    # The model's change of the same size stays while the VM runs.
    node.agent.files[key] = b"ORIGINAL"
    new_turn(files)
    _wait_until(idle)
    assert node.agent.files[key] == b"ORIGINAL"
    assert node.agent.write_paths.count("attachments/a.txt") == 1

    # A missing file, or one of another size, is copied again.
    del node.agent.files[key]
    new_turn(files)
    _wait_until(idle)
    assert node.agent.files[key] == b"original"
    node.agent.files[key] = b"changed"
    new_turn(files)
    _wait_until(idle)
    assert node.agent.files[key] == b"original"
    assert node.agent.write_paths.count("attachments/a.txt") == 3

    # A new VM instance gets every file again.
    _restart(client_factory, node, ref)
    new_turn(files)
    _wait_until(idle)
    assert node.agent.write_paths.count("attachments/a.txt") == 4


def test_a_restarted_vm_gets_its_files_again_without_a_delete(
    new_turn: NewTurn,
    node: RunningFakeAgent,
    client_factory: InsecureClientFactory,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    kept, gone = store_file(b"kept"), store_file(b"gone")
    _, ref = new_turn(
        [_file(kept, "attachments/kept.txt"), _file(gone, "attachments/agent/gone.txt")]
    )
    _wait_until(idle)

    _restart(client_factory, node, ref)
    new_turn([_file(kept, "attachments/kept.txt")])
    _wait_until(idle)

    assert node.agent.files[_key(ref, "attachments/kept.txt")] == b"kept"
    assert node.agent.write_paths.count("attachments/kept.txt") == 2
    # The file went with the instance.
    assert _deletes(node) == []


def test_the_models_own_files_in_attachments_stay(
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    """The model's own files in attachments/, and a copy that it moved into a
    directory of its own, stay."""
    file_id = store_file(b"report")
    _, ref = new_turn([_file(file_id, "attachments/report.txt")])
    _wait_until(idle)
    files = node.agent.files
    files[_key(ref, "attachments/notes.txt")] = b"mine"
    files[_key(ref, "attachments/kept/report.txt")] = files.pop(
        _key(ref, "attachments/report.txt")
    )

    new_turn([])
    _wait_until(idle)
    assert files[_key(ref, "attachments/notes.txt")] == b"mine"
    assert files[_key(ref, "attachments/kept/report.txt")] == b"report"


def test_a_hidden_file_in_a_directory_of_chat_files_stays(
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    """A hidden file, such as the daemon's temporary file of a write in
    progress, stays in attachments/project/."""
    file_id = store_file(b"project")
    chat_files = [_file(file_id, "attachments/project/p.txt")]
    _, ref = new_turn(chat_files)
    _wait_until(idle)
    files = node.agent.files
    files[_key(ref, "attachments/project/.craft-write-x")] = b"partial"

    new_turn(chat_files)
    _wait_until(idle)
    assert files[_key(ref, "attachments/project/.craft-write-x")] == b"partial"
    assert _deletes(node) == []


def test_a_sandbox_call_does_not_wait_for_copies(
    new_turn: NewTurn,
    node: RunningFakeAgent,
    sandbox: FirecrackerHarnessSandbox,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    file_id = store_file(b"a")
    gate = threading.Event()
    node.agent.write_gates["attachments/a.txt"] = gate
    turn, ref = new_turn([_file(file_id, "attachments/a.txt")])
    _wait_until(lambda: "attachments/a.txt" in node.agent.write_waiting)
    assert _exec(turn).content.endswith("Output:\nhi\n")

    # After the turn, the copy keeps the VM busy, so no idle stop.
    turn.end()
    assert sandbox.is_busy(tenant_id=TENANT_ID, sandbox_id=ref.sandbox_id)
    gate.set()
    _wait_until(idle)
    assert node.agent.files[_key(ref, "attachments/a.txt")] == b"a"
    assert not sandbox.is_busy(tenant_id=TENANT_ID, sandbox_id=ref.sandbox_id)


def test_a_copy_in_its_first_download_keeps_the_vm_busy(
    monkeypatch: pytest.MonkeyPatch,
    new_turn: NewTurn,
    sandbox: FirecrackerHarnessSandbox,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    file_id = store_file(b"a")
    downloading = threading.Event()
    release = threading.Event()
    store = get_default_file_store()
    read_file = store.read_file

    def slow(
        file_id: str, mode: str | None = None, use_tempfile: bool = False
    ) -> IO[bytes]:
        downloading.set()
        assert release.wait(30)
        return read_file(file_id, mode, use_tempfile)

    monkeypatch.setattr(store, "read_file", slow)
    monkeypatch.setattr(file_copies, "get_default_file_store", lambda: store)
    turn, ref = new_turn([_file(file_id, "attachments/a.txt")])
    try:
        _wait_until(downloading.is_set)
        turn.end()
        assert sandbox.is_busy(tenant_id=TENANT_ID, sandbox_id=ref.sandbox_id)
    finally:
        release.set()
    _wait_until(idle)
    assert not sandbox.is_busy(tenant_id=TENANT_ID, sandbox_id=ref.sandbox_id)


def test_one_busy_mark_covers_the_writes_of_a_copy(
    monkeypatch: pytest.MonkeyPatch,
    new_turn: NewTurn,
    sandbox: FirecrackerHarnessSandbox,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    marks: list[float | None] = []

    class _Counted(_Wrapped):
        def mark_busy(self, seconds: float | None) -> None:
            marks.append(seconds)
            super().mark_busy(seconds)

    _wrap(monkeypatch, sandbox, _Counted)
    new_turn([_file(store_file(b"x"), f"attachments/{i}.txt") for i in range(6)])
    _wait_until(idle)
    # Set once, then cleared once.
    assert len(marks) == 2
    assert marks[-1] is None


class _BreaksAtHalf(io.RawIOBase):
    """Reads half of `source`, then fails: the stream breaks as the pod
    dies."""

    def __init__(self, source: IO[bytes], size: int) -> None:
        super().__init__()
        self._source = source
        self._half = size // 2

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        return self._source.seek(offset, whence)

    def readinto(self, buffer: Buffer) -> int:
        if self._source.tell() >= self._half:
            raise OSError("the pod died")
        view = memoryview(buffer).cast("B")
        data = self._source.read(min(len(view), self._half - self._source.tell()))
        view[: len(data)] = data
        return len(data)


class _DyingFiles(_Wrapped):
    def __init__(self, files: SessionFiles, pod: "_DyingPod") -> None:
        super().__init__(files)
        self._pod = pod

    def write(self, path: str, data: IO[bytes], *, timeout_seconds: float) -> None:
        if self._pod.broke.is_set():
            raise HarnessSandboxError("the pod is gone")
        size = data.seek(0, os.SEEK_END)
        data.seek(0)
        try:
            self.files.write(
                path,
                io.BufferedReader(_BreaksAtHalf(data, size)),
                timeout_seconds=timeout_seconds,
            )
        except Exception:
            self._pod.broke.set()
            # Dead: nothing runs on until the test ends.
            self._pod.release.wait()
        raise HarnessSandboxError("the pod is gone")


class _DyingPod(FirecrackerHarnessSandbox):
    """An API pod that dies in its first write: the write streams half the
    file, and the copy never goes on (until the test releases it)."""

    def __init__(self, client_factory: InsecureClientFactory) -> None:
        super().__init__(template="tpl-1", client_factory=client_factory)
        self.broke = threading.Event()
        self.release = threading.Event()

    def session_files(self, ref: HarnessSandboxRef) -> SessionFiles:
        return _DyingFiles(super().session_files(ref), self)


def test_a_copy_lost_with_its_pod_is_copied_again_by_the_next_turn(
    new_turn: NewTurn,
    node: RunningFakeAgent,
    client_factory: InsecureClientFactory,
    store_file: StoreFile,
) -> None:
    data = os.urandom(3 << 20)
    file_id = store_file(data)
    files = [_file(file_id, "attachments/big.bin")]
    pod = _DyingPod(client_factory)
    _, ref = new_turn()
    key = _key(ref, "attachments/big.bin")
    try:
        TurnFileCopies(ref, pod, files)
        _wait_until(pod.broke.is_set)
        # The broken stream left nothing at the path.
        assert key not in node.agent.files

        # The next turn, on another pod, copies the file.
        new_turn(files)
        _wait_until(lambda: node.agent.files.get(key) == data)
    finally:
        pod.release.set()


def test_two_chats_copy_into_one_vm_without_waiting_for_each_other(
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
) -> None:
    first = store_file(b"first")
    second = store_file(b"second")
    gate = threading.Event()
    node.agent.write_gates["attachments/first.txt"] = gate
    new_turn([_file(first, "attachments/first.txt")], uuid4())
    _wait_until(lambda: "attachments/first.txt" in node.agent.write_waiting)
    try:
        _, ref_b = new_turn([_file(second, "attachments/second.txt")], uuid4())
        _wait_until(lambda: _key(ref_b, "attachments/second.txt") in node.agent.files)
    finally:
        gate.set()


def test_a_copy_writes_in_parallel_up_to_the_vm_cap(
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    paths = [f"attachments/{i}.bin" for i in range(file_copies.VM_COPY_WRITES + 2)]
    gates = {path: threading.Event() for path in paths}
    node.agent.write_gates.update(gates)
    _, ref = new_turn([_file(store_file(b"x"), path) for path in paths])

    _wait_until(lambda: len(node.agent.write_waiting) == file_copies.VM_COPY_WRITES)
    first = set(node.agent.write_waiting)
    gates[next(iter(first))].set()
    # A finished write frees its slot for the next file, never more.
    _wait_until(lambda: len(node.agent.write_waiting - first) == 1)
    assert len(node.agent.write_waiting) == file_copies.VM_COPY_WRITES
    for gate in gates.values():
        gate.set()
    _wait_until(idle)
    assert node.agent.most_writes_running == file_copies.VM_COPY_WRITES
    assert all(node.agent.files[_key(ref, path)] == b"x" for path in paths)


def test_a_file_is_written_unless_listed_in_place_and_files_that_left_go(
    new_turn: NewTurn,
    node: RunningFakeAgent,
    sandbox: FirecrackerHarnessSandbox,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    """The next turn writes a file that is missing or has another size, keeps
    one in place, and deletes the project and agent files that left the
    chat's set. The model's files elsewhere stay."""
    upload, project, agent, gone = (
        store_file(name.encode()) for name in ("upload", "project", "agent", "gone")
    )
    chat_files = [
        _file(upload, "attachments/upload.txt"),
        _file(project, "attachments/project/p.txt"),
        _file(agent, "attachments/agent/a.txt"),
    ]
    _, ref = new_turn([*chat_files, _file(gone, "attachments/project/gone.txt")])
    _wait_until(idle)
    files = node.agent.files
    del files[_key(ref, "attachments/upload.txt")]
    files[_key(ref, "attachments/project/p.txt")] = b"other size"
    files[_key(ref, "attachments/notes.txt")] = b"mine"
    files[_key(ref, "notes.txt")] = b"mine"
    files[_key(ref, "attachments/agent/kept/inner.txt")] = b"mine"

    new_turn(chat_files)
    _wait_until(idle)
    assert files[_key(ref, "attachments/upload.txt")] == b"upload"
    assert files[_key(ref, "attachments/project/p.txt")] == b"project"
    assert files[_key(ref, "attachments/agent/a.txt")] == b"agent"
    assert node.agent.write_paths.count("attachments/upload.txt") == 2
    assert node.agent.write_paths.count("attachments/project/p.txt") == 2
    assert node.agent.write_paths.count("attachments/agent/a.txt") == 1
    assert _key(ref, "attachments/project/gone.txt") not in files
    assert _deletes(node) == ["attachments/project/gone.txt"]
    for path in (
        "attachments/notes.txt",
        "notes.txt",
        "attachments/agent/kept/inner.txt",
    ):
        assert files[_key(ref, path)] == b"mine"

    # A chat file is in a directory of chat files.
    for path in ("notes.txt", "attachments/kept/notes.txt"):
        with pytest.raises(SandboxPathError):
            TurnFileCopies(ref, sandbox, [_file(upload, path)])


def test_the_limits_of_one_file_and_of_the_bytes_written_in_one_turn(
    monkeypatch: pytest.MonkeyPatch,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    # The limit for one file is the admin's upload limit.
    monkeypatch.setattr(
        file_copies,
        "load_settings",
        lambda: Settings(user_file_max_upload_size_mb=1),
    )
    monkeypatch.setattr(file_copies, "MAX_TURN_BYTES", 5)
    a, b = (store_file(b"x" * 3) for _ in range(2))
    huge = store_file(b"x" * (2 << 20))
    files = [
        _file(a, "attachments/a.bin"),
        _file(b, "attachments/b.bin"),
        _file(huge, "attachments/huge.bin"),
    ]
    turn, ref = new_turn(files)
    _wait_until(idle)
    assert _status(turn) == (
        "[files] Not copied: attachments/b.bin (over the copy limit of one turn; "
        "copying next turn); attachments/huge.bin (2 MB, over the 1 MB limit "
        "for one file)."
        f"{_INDENT}Done since last status: attachments/a.bin."
        f"{_INDENT}All other files are in attachments/."
    )

    # The next turn has a new limit.
    new_turn(files)
    _wait_until(idle)
    assert node.agent.files[_key(ref, "attachments/b.bin")] == b"xxx"


def test_a_file_over_the_limit_of_one_turn_is_never_copied(
    monkeypatch: pytest.MonkeyPatch,
    new_turn: NewTurn,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    """An upload limit above the limit of one turn lets in a file that no
    turn can copy."""
    monkeypatch.setattr(
        file_copies,
        "load_settings",
        lambda: Settings(user_file_max_upload_size_mb=3),
    )
    monkeypatch.setattr(file_copies, "MAX_TURN_BYTES", 1 << 20)
    files = [_file(store_file(b"x" * (2 << 20)), "attachments/big.bin")]
    turn, _ = new_turn(files)
    _wait_until(idle)
    assert _status(turn) == (
        "[files] Not copied: attachments/big.bin (2 MB, over the 1 MB copy "
        "limit of one turn)."
    )


def test_one_download_serves_every_try(
    monkeypatch: pytest.MonkeyPatch,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    file_id = store_file(b"a")
    node.agent.write_failures["attachments/a.txt"] = WriteFailure(
        SandboxDaemonErrorReason.INTERNAL, count=2
    )
    downloads: list[str] = []
    store = get_default_file_store()
    read_file = store.read_file

    def counted(
        file_id: str, mode: str | None = None, use_tempfile: bool = False
    ) -> IO[bytes]:
        downloads.append(file_id)
        return read_file(file_id, mode, use_tempfile)

    monkeypatch.setattr(store, "read_file", counted)
    monkeypatch.setattr(file_copies, "get_default_file_store", lambda: store)
    _, ref = new_turn([_file(file_id, "attachments/a.txt")])
    _wait_until(idle)

    assert node.agent.write_paths.count("attachments/a.txt") == 3
    assert node.agent.files[_key(ref, "attachments/a.txt")] == b"a"
    assert downloads == [file_id]


def test_a_newer_turn_on_another_pod_takes_over_from_a_write_in_progress(
    monkeypatch: pytest.MonkeyPatch,
    new_file_copy_pool: NewFileCopyPool,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    client_factory: InsecureClientFactory,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    """Two turns of one chat on two API pods: the earlier turn is in the
    middle of a write when the later turn starts, with fewer project files.
    The older copy stops before its next write. Its write in flight lands,
    and the next turn deletes it."""
    first, kept, other = (
        store_file(name.encode()) for name in ("first", "kept", "the y file")
    )
    monkeypatch.setattr(file_copies, "VM_COPY_WRITES", 1)
    new_file_copy_pool()
    gate = threading.Event()
    node.agent.write_gates["attachments/project/first.txt"] = gate
    older, ref = new_turn(
        [
            _file(first, "attachments/project/first.txt"),
            _file(kept, "attachments/project/x.txt"),
            _file(other, "attachments/project/y.txt"),
        ]
    )
    _wait_until(lambda: "attachments/project/first.txt" in node.agent.write_waiting)
    other_pod = FirecrackerHarnessSandbox(
        template="tpl-1", client_factory=client_factory
    )
    other_pool = new_file_copy_pool()
    TurnFileCopies(ref, other_pod, [_file(kept, "attachments/project/x.txt")])
    _wait_until(other_pool.idle)
    gate.set()
    _wait_until(idle)

    assert node.agent.files[_key(ref, "attachments/project/x.txt")] == b"kept"
    assert node.agent.write_paths.count("attachments/project/x.txt") == 1
    assert node.agent.write_paths.count("attachments/project/y.txt") == 0
    assert _status(older) == (
        "[files] Failed: attachments/project/y.txt (the copy stopped); "
        "retrying next turn."
        f"{_INDENT}Done since last status: attachments/project/x.txt, "
        "attachments/project/first.txt."
        f"{_INDENT}All other files are in attachments/."
    )
    # The late write stays until the next turn.
    assert _key(ref, "attachments/project/first.txt") in node.agent.files
    new_turn([_file(kept, "attachments/project/x.txt")])
    _wait_until(idle)
    assert _key(ref, "attachments/project/first.txt") not in node.agent.files


def test_overlapping_turns_leave_one_whole_file(
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    """An older turn's write lands after a newer turn wrote the same file.
    Each write is whole, so the file stays, and the next turn finds it in
    place."""
    data = os.urandom(3 << 20)
    chat_files = [_file(store_file(data), "attachments/report.bin")]
    hold = threading.Event()
    node.agent.write_holds["attachments/report.bin"] = (1, hold)
    _, ref = new_turn(chat_files)
    try:
        _wait_until(lambda: "attachments/report.bin" in node.agent.write_held)
        del node.agent.write_holds["attachments/report.bin"]
        newer_turn, _ = new_turn(chat_files)
        _wait_for_status(newer_turn, "Done since last status")
    finally:
        hold.set()
    _wait_until(idle)
    assert node.agent.write_paths.count("attachments/report.bin") == 2
    assert node.agent.files[_key(ref, "attachments/report.bin")] == data

    new_turn(chat_files)
    _wait_until(idle)
    assert node.agent.write_paths.count("attachments/report.bin") == 2


def test_a_file_that_an_older_cleanup_deleted_is_copied_by_the_next_turn(
    monkeypatch: pytest.MonkeyPatch,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    sandbox: FirecrackerHarnessSandbox,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    """An older turn's cleanup deletes a path just after a newer turn found
    the file there in place; the next turn finds it missing and copies it."""
    chat_files = [_file(store_file(b"agent file"), "attachments/agent/x.txt")]
    path = "attachments/agent/x.txt"
    _, ref = new_turn(chat_files)
    _wait_until(idle)
    deleting = threading.Event()
    release = threading.Event()
    held_files: list[SessionFiles] = []

    class _HeldDeletes(_Wrapped):
        def delete(self, path: str) -> bool:
            deleting.set()
            assert release.wait(30)
            return super().delete(path)

    def wrap(files: SessionFiles) -> SessionFiles:
        # Only the first copy from here holds its deletes.
        if held_files:
            return files
        held_files.append(_HeldDeletes(files))
        return held_files[-1]

    _wrap(monkeypatch, sandbox, wrap)
    try:
        # A turn after the file left the agent, then one after it came back.
        new_turn([])
        _wait_until(deleting.is_set)
        listed = len(node.agent.list_requests)
        new_turn(chat_files)
        _wait_until(lambda: len(node.agent.list_requests) == listed + 4)
    finally:
        release.set()
    _wait_until(idle)
    assert _key(ref, path) not in node.agent.files

    new_turn(chat_files)
    _wait_until(idle)
    assert node.agent.files[_key(ref, path)] == b"agent file"


def test_the_models_own_trees_in_attachments_are_not_listed(
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    """A large tree that the model makes in attachments/ (an npm install)
    costs the listing nothing: the copy lists the session directory and
    each directory of chat files one level deep."""
    file_id = store_file(b"a")
    chat_files = [_file(file_id, "attachments/a.txt")]
    _, ref = new_turn(chat_files)
    _wait_until(idle)
    for i in range(50):
        node.agent.files[_key(ref, f"attachments/node_modules/p{i}/index.js")] = b"x"
    node.agent.list_response_limit = 10
    node.agent.list_requests.clear()

    turn, _ = new_turn(chat_files)
    _wait_until(idle)
    assert node.agent.write_paths.count("attachments/a.txt") == 1
    assert _status(turn) is None
    assert node.agent.list_requests == [
        ("", False),
        ("attachments", False),
        ("attachments/project", False),
        ("attachments/agent", False),
    ]


def test_a_listing_that_fails_writes_every_file_and_deletes_nothing(
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    """The model's files make the listing of attachments/ fail, other than by
    a timeout: what is there is unknown, so the copy writes its files again
    and deletes nothing."""
    kept, gone = store_file(b"kept"), store_file(b"gone")
    _, ref = new_turn(
        [
            _file(kept, "attachments/kept.txt"),
            _file(gone, "attachments/project/gone.txt"),
        ]
    )
    _wait_until(idle)
    for i in range(20):
        node.agent.files[_key(ref, f"attachments/mine-{i}.txt")] = b"mine"
    node.agent.list_response_limit = 10

    turn, _ = new_turn([_file(kept, "attachments/kept.txt")])
    _wait_until(idle)
    assert node.agent.write_paths.count("attachments/kept.txt") == 2
    assert node.agent.files[_key(ref, "attachments/kept.txt")] == b"kept"
    assert node.agent.files[_key(ref, "attachments/project/gone.txt")] == b"gone"
    assert _deletes(node) == []
    assert _status(turn) == (
        f"[files] Done since last status: attachments/kept.txt.{_INDENT}{DONE}"
    )


def test_links_and_directories_in_the_directories_of_chat_files(
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    """The model put a link at a chat file's path, a link in the project
    files, and a directory where a project file was. The link is not the
    file, so the copy writes the file over it. The stray link goes; the
    directory, which a delete cannot take, stays."""
    linked, gone = store_file(b"linked"), store_file(b"gone")
    _, ref = new_turn(
        [
            _file(linked, "attachments/linked.txt"),
            _file(gone, "attachments/project/gone.txt"),
        ]
    )
    _wait_until(idle)
    files = node.agent.files
    files[_key(ref, "notes.txt")] = files.pop(_key(ref, "attachments/linked.txt"))
    node.agent.links[_key(ref, "attachments/linked.txt")] = "../notes.txt"
    node.agent.links[_key(ref, "attachments/project/stray")] = "../../notes.txt"
    del files[_key(ref, "attachments/project/gone.txt")]
    files[_key(ref, "attachments/project/gone.txt/inner.txt")] = b"mine"

    new_turn([_file(linked, "attachments/linked.txt")])
    _wait_until(idle)
    assert files[_key(ref, "attachments/linked.txt")] == b"linked"
    assert _key(ref, "attachments/linked.txt") not in node.agent.links
    assert _key(ref, "attachments/project/stray") not in node.agent.links
    assert files[_key(ref, "attachments/project/gone.txt/inner.txt")] == b"mine"
    assert _deletes(node) == ["attachments/project/stray"]


@pytest.mark.parametrize(
    "link,target", [("attachments/project", "../work"), ("attachments", "work")]
)
def test_a_link_in_place_of_a_directory_of_chat_files_is_left_alone(
    link: str,
    target: str,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    """The model replaced a directory of chat files with a link to its own
    work. The copy neither cleans up nor writes in the link's target, and
    keeps the link."""
    kept, added = store_file(b"kept"), store_file(b"added")
    _, ref = new_turn([_file(kept, "attachments/project/kept.txt")])
    _wait_until(idle)
    files = node.agent.files
    for key in [key for key in files if key[2].startswith(f"{link}/")]:
        del files[key]
    files[_key(ref, "work/report.docx")] = b"mine"
    node.agent.links[_key(ref, link)] = target

    turn, _ = new_turn([_file(added, "attachments/project/added.txt")])
    _wait_until(idle)
    assert [key[2] for key in files if key[:2] == _key(ref, "")[:2]] == [
        "work/report.docx"
    ]
    assert node.agent.links[_key(ref, link)] == target
    assert _deletes(node) == []
    line = _status(turn)
    assert line is not None
    assert f"attachments/project/added.txt ({link} is not a directory)" in line, line


@pytest.mark.parametrize(
    "failed,link,target",
    [("attachments", "attachments/project", "../work"), ("", "attachments", "work")],
)
def test_a_failed_listing_writes_only_in_verified_directories(
    failed: str,
    link: str,
    target: str,
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    """A listing fails, other than by a timeout, and a directory of chat
    files below it is a link. The copy does not know that, so it writes
    nothing in the directories that the listing would have checked."""
    kept, added = store_file(b"kept"), store_file(b"added")
    _, ref = new_turn([_file(kept, "attachments/project/kept.txt")])
    _wait_until(idle)
    files = node.agent.files
    for key in [key for key in files if key[2].startswith(f"{link}/")]:
        del files[key]
    files[_key(ref, "work/report.docx")] = b"mine"
    node.agent.links[_key(ref, link)] = target

    class _FailedListing(_Wrapped):
        def list_files(self, directory: str, *, max_entries: int) -> FileListing:
            if directory == failed:
                raise RuntimeError("the listing failed")
            return super().list_files(directory, max_entries=max_entries)

    _wrap(monkeypatch, sandbox, _FailedListing)
    turn, _ = new_turn([_file(added, "attachments/project/added.txt")])
    _wait_until(idle)
    assert [key[2] for key in files if key[:2] == _key(ref, "")[:2]] == [
        "work/report.docx"
    ]
    assert node.agent.links[_key(ref, link)] == target
    assert node.agent.write_paths.count("attachments/project/added.txt") == 0
    line = _status(turn)
    assert line is not None
    assert "attachments/project/added.txt (could not be checked)" in line, line


@pytest.mark.parametrize(
    "truncated,link,target",
    [("attachments", "attachments/project", "../work"), ("", "attachments", "work")],
)
def test_a_truncated_listing_writes_only_in_verified_directories(
    truncated: str,
    link: str,
    target: str,
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    """A listing is cut at its limit before a directory of chat files that
    is a link. The copy does not know that directory's type, so it neither
    cleans up nor writes through the link."""
    kept, added = store_file(b"kept"), store_file(b"added")
    _, ref = new_turn([_file(kept, "attachments/project/kept.txt")])
    _wait_until(idle)
    files = node.agent.files
    for key in [key for key in files if key[2].startswith(f"{link}/")]:
        del files[key]
    files[_key(ref, "work/report.docx")] = b"mine"
    node.agent.links[_key(ref, link)] = target

    class _TruncatedListing(_Wrapped):
        def list_files(self, directory: str, *, max_entries: int) -> FileListing:
            listing = super().list_files(directory, max_entries=max_entries)
            if directory != truncated:
                return listing
            return FileListing(
                entries=[entry for entry in listing.entries if entry.path != link],
                truncated=True,
            )

    _wrap(monkeypatch, sandbox, _TruncatedListing)
    turn, _ = new_turn([_file(added, "attachments/project/added.txt")])
    _wait_until(idle)
    assert [key[2] for key in files if key[:2] == _key(ref, "")[:2]] == [
        "work/report.docx"
    ]
    assert node.agent.links[_key(ref, link)] == target
    assert _deletes(node) == []
    assert node.agent.write_paths.count("attachments/project/added.txt") == 0
    line = _status(turn)
    assert line is not None
    assert "attachments/project/added.txt (could not be checked)" in line, line


def _hold(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    match: Callable[[HarnessSandboxRef], bool] | None = None,
) -> tuple[list[HarnessSandboxRef], threading.Event]:
    """Hold each session setup (`session_files`) for a matching reference
    (all: None) until the returned event is set; the list gets each held
    one."""
    held: list[HarnessSandboxRef] = []
    release = threading.Event()
    session_files = sandbox.session_files

    def held_call(ref: HarnessSandboxRef) -> SessionFiles:
        if match is None or match(ref):
            held.append(ref)
            assert release.wait(60)
        return session_files(ref)

    monkeypatch.setattr(sandbox, "session_files", held_call)
    return held, release


def test_the_chats_of_a_slow_vm_do_not_delay_copies_into_other_vms(
    monkeypatch: pytest.MonkeyPatch,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    sandbox: FirecrackerHarnessSandbox,
    store_file: StoreFile,
    make_test_user: MakeTestUser,
) -> None:
    """One VM's writes hang and another VM's session setups hang, each with
    four chats. The per-VM caps keep each VM to its slots; a chat on a third
    VM still gets its file while they hang."""
    file_id = store_file(b"x")
    gate = threading.Event()
    hung_user, slow_user = make_test_user("fcp_hung"), make_test_user("fcp_slow")
    hung_paths = [[f"attachments/hung-{i}-{j}.txt" for j in range(4)] for i in range(4)]
    for paths in hung_paths:
        node.agent.write_gates.update(dict.fromkeys(paths, gate))
    _, slow_ref = new_turn(None, uuid4(), slow_user)
    held, release = _hold(
        monkeypatch, sandbox, lambda ref: ref.sandbox_id == slow_ref.sandbox_id
    )
    try:
        for paths in hung_paths:
            new_turn([_file(file_id, path) for path in paths], uuid4(), hung_user)
        for _ in range(4):
            new_turn([_file(file_id, "attachments/slow.txt")], uuid4(), slow_user)
        _wait_until(lambda: len(node.agent.write_waiting) == file_copies.VM_COPY_WRITES)
        _wait_until(lambda: len(held) == file_copies.VM_INTAKES)

        _, ref = new_turn([_file(file_id, "attachments/ok.txt")])
        _wait_until(lambda: _key(ref, "attachments/ok.txt") in node.agent.files)
        assert len(held) == file_copies.VM_INTAKES
        assert len(node.agent.write_waiting) == file_copies.VM_COPY_WRITES
    finally:
        gate.set()
        release.set()


def test_a_purge_stops_a_running_copy(
    monkeypatch: pytest.MonkeyPatch,
    new_file_copy_pool: NewFileCopyPool,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    sandbox: FirecrackerHarnessSandbox,
    store_file: StoreFile,
    tenant_cache: CacheBackend,
    idle: Idle,
) -> None:
    monkeypatch.setattr(file_copies, "VM_COPY_WRITES", 1)
    new_file_copy_pool()
    a, b = store_file(b"a"), store_file(b"bb")
    gate = threading.Event()
    node.agent.write_gates["attachments/a.txt"] = gate
    turn, ref = new_turn([_file(a, "attachments/a.txt"), _file(b, "attachments/b.txt")])
    _wait_until(lambda: "attachments/a.txt" in node.agent.write_waiting)
    assert tenant_cache.get(copy_generation_key(ref.session_id)) == b"1"
    sandbox.purge_session(
        tenant_id=TENANT_ID,
        sandbox_id=ref.sandbox_id,
        session_id=ref.session_id,
        retention=True,
    )
    # The purge takes a generation, so no later copy reuses one.
    assert tenant_cache.get(copy_generation_key(ref.session_id)) == b"2"
    gate.set()
    _wait_until(idle)

    # The write in flight lands after the purge, sees it, and deletes the
    # session directory that it made; the copy stops before its next write.
    assert "attachments/b.txt" not in node.agent.write_paths
    assert not [key for key in node.agent.files if key[:2] == _key(ref, "")[:2]]
    assert _status(turn) == (
        "[files] Failed: attachments/a.txt (the copy stopped); "
        "attachments/b.txt (the copy stopped); retrying next turn."
    )
    vm = node.agent.vms[str(ref.sandbox_id)]
    assert ref.session_id not in harness_state.sessions_on_instance(
        tenant_cache, ref.sandbox_id, (vm.attempt, vm.generation)
    )
    # A purged session is never set up again.
    with pytest.raises(HarnessSandboxError):
        sandbox.session_files(ref)


def test_after_a_purge_no_copy_sets_the_session_up(
    monkeypatch: pytest.MonkeyPatch,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    sandbox: FirecrackerHarnessSandbox,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    """A purge while a copy waits to set its session up, then a newer
    turn: neither writes anything."""
    a, b, c = store_file(b"a"), store_file(b"b"), store_file(b"c")
    held, release = _hold(monkeypatch, sandbox)
    try:
        _, ref = new_turn(
            [_file(a, "attachments/a.txt"), _file(b, "attachments/b.txt")]
        )
        _wait_until(lambda: bool(held))
        sandbox.purge_session(
            tenant_id=TENANT_ID,
            sandbox_id=ref.sandbox_id,
            session_id=ref.session_id,
            retention=True,
        )
        next_turn, _ = new_turn([_file(c, "attachments/c.txt")])
    finally:
        release.set()
    _wait_until(idle)

    assert not [
        path for path in node.agent.write_paths if path.startswith("attachments/")
    ]
    assert _status(next_turn) == (
        "[files] Failed: attachments/c.txt (the sandbox did not start); "
        "retrying next turn."
    )


def test_a_copy_taken_in_after_a_vm_restart_copies_onto_the_new_instance(
    monkeypatch: pytest.MonkeyPatch,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    sandbox: FirecrackerHarnessSandbox,
    client_factory: InsecureClientFactory,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    file_id = store_file(b"a")
    files = [_file(file_id, "attachments/a.txt")]
    turn, ref = new_turn()
    _exec(turn)
    held, release = _hold(monkeypatch, sandbox)
    try:
        TurnFileCopies(ref, sandbox, files)
        _wait_until(lambda: bool(held))
        _restart(client_factory, node, ref)
    finally:
        release.set()
    _wait_until(idle)

    assert node.agent.write_paths.count("attachments/a.txt") == 1
    new_turn(files)
    _wait_until(idle)
    assert node.agent.write_paths.count("attachments/a.txt") == 1


def test_many_chats_copy_at_once_on_a_bounded_number_of_threads(
    monkeypatch: pytest.MonkeyPatch,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    sandbox: FirecrackerHarnessSandbox,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    """60 turns of the user's chats copy into one VM at once: the pod's
    threads stay bounded, the VM's writes stay under its cap, and the chats
    take the VM's write slots in turn."""
    chats, files_per_chat = 60, 5
    intake_seconds = 60
    # The gated writes wait for every intake; their deadline must outlast it.
    monkeypatch.setattr(file_copies, "COPY_BASE_SECONDS", 3.0 * intake_seconds)
    file_id = store_file(b"x" * 1024)
    gate = threading.Event()
    node.agent.write_gates.update(
        (f"attachments/c{i}-{j}.bin", gate)
        for i in range(chats)
        for j in range(files_per_chat)
    )
    turns = [new_turn(None, uuid4()) for _ in range(chats)]
    # The chats use the sandbox already, so their sessions are set up.
    for turn, _ in turns:
        _exec(turn)

    def copy_threads() -> int:
        return sum(
            thread.name.startswith("sandbox-file-") for thread in threading.enumerate()
        )

    # Earlier pods of the test process keep their idle threads.
    threads_before = copy_threads()
    for i, (_, ref) in enumerate(turns):
        TurnFileCopies(
            ref,
            sandbox,
            [
                _file(file_id, f"attachments/c{i}-{j}.bin")
                for j in range(files_per_chat)
            ],
        )
    most_threads = copy_threads()

    def sampled(condition: Callable[[], bool]) -> Callable[[], bool]:
        def check() -> bool:
            nonlocal most_threads
            most_threads = max(most_threads, copy_threads())
            return condition()

        return check

    # Every intake has queued its copy's writes before any write lands.
    _wait_until(sampled(file_copies.file_copy_pool().intake.idle), intake_seconds)
    gate.set()
    _wait_until(sampled(idle), 120)

    assert all(
        node.agent.files[_key(ref, f"attachments/c{i}-{j}.bin")] == b"x" * 1024
        for i, (_, ref) in enumerate(turns)
        for j in range(files_per_chat)
    )
    assert (
        most_threads - threads_before
        <= file_copies.POD_INTAKE_THREADS + file_copies.POD_COPY_THREADS
    )
    assert node.agent.most_writes_running <= file_copies.VM_COPY_WRITES
    # Copies take the VM's slots in turn, so every chat has a file in the
    # first half of the writes.
    first_half = node.agent.write_paths[: chats * files_per_chat // 2]
    progressed = {path.split("-")[0] for path in first_half}
    assert len(progressed) == chats


def test_vms_whose_writes_hang_leave_threads_for_other_vms(
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
    make_test_user: MakeTestUser,
) -> None:
    file_id = store_file(b"x")
    gate = threading.Event()
    try:
        for i in range(2):
            paths = [f"attachments/hung-{i}-{j}.txt" for j in range(4)]
            node.agent.write_gates.update(dict.fromkeys(paths, gate))
            new_turn(
                [_file(file_id, path) for path in paths],
                uuid4(),
                make_test_user(f"fcp_hung{i}"),
            )
        _wait_until(
            lambda: len(node.agent.write_waiting) == 2 * file_copies.VM_COPY_WRITES
        )

        _, ref = new_turn([_file(file_id, "attachments/ok.txt")])
        _wait_until(lambda: _key(ref, "attachments/ok.txt") in node.agent.files)
        assert len(node.agent.write_waiting) == 2 * file_copies.VM_COPY_WRITES
    finally:
        gate.set()


def test_a_write_timeout_fails_the_rest_of_the_copy_without_a_try(
    monkeypatch: pytest.MonkeyPatch,
    new_file_copy_pool: NewFileCopyPool,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    file_id = store_file(b"x")
    monkeypatch.setattr(file_copies, "VM_COPY_WRITES", 1)
    new_file_copy_pool()
    node.agent.write_failures[ANY_PATH] = WriteFailure(
        grpc.StatusCode.DEADLINE_EXCEEDED
    )
    turn, _ = new_turn([_file(file_id, f"attachments/{i}.txt") for i in range(4)])
    _wait_until(idle)
    line = _status(turn)
    assert line is not None
    assert line.count("(the sandbox did not respond)") == 4, line
    assert len(node.agent.write_paths) == 1


def test_a_slow_session_setup_does_not_delay_other_chats_in_its_vm(
    monkeypatch: pytest.MonkeyPatch,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    sandbox: FirecrackerHarnessSandbox,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    file_id = store_file(b"x")
    _, slow_ref = new_turn(None, uuid4())
    held, release = _hold(
        monkeypatch,
        sandbox,
        lambda held_ref: held_ref.session_id == slow_ref.session_id,
    )
    try:
        TurnFileCopies(slow_ref, sandbox, [_file(file_id, "attachments/slow.txt")])
        _wait_until(lambda: bool(held))
        _, ref = new_turn(
            [_file(file_id, "attachments/a.txt"), _file(file_id, "attachments/b.txt")],
            uuid4(),
        )
        _wait_until(
            lambda: all(
                _key(ref, path) in node.agent.files
                for path in ("attachments/a.txt", "attachments/b.txt")
            )
        )
        assert len(held) == 1
    finally:
        release.set()
    _wait_until(idle)
    assert node.agent.files[_key(slow_ref, "attachments/slow.txt")] == b"x"


def test_vms_with_a_hung_session_setup_do_not_delay_another_vm(
    monkeypatch: pytest.MonkeyPatch,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    sandbox: FirecrackerHarnessSandbox,
    store_file: StoreFile,
    make_test_user: MakeTestUser,
) -> None:
    """Two VMs whose session setups hang, each with more chats than its
    intake slots: a chat on a third VM still gets its file while they
    hang."""
    file_id = store_file(b"x")
    slow_users = [make_test_user(f"fcp_setup{i}") for i in range(2)]
    slow = [
        new_turn(None, uuid4(), slow_user)
        for slow_user in slow_users
        for _ in range(file_copies.VM_INTAKES + 1)
    ]
    slow_sandboxes = {ref.sandbox_id for _, ref in slow}
    held, release = _hold(
        monkeypatch,
        sandbox,
        lambda ref: ref.sandbox_id in slow_sandboxes,
    )
    try:
        for _, slow_ref in slow:
            TurnFileCopies(slow_ref, sandbox, [_file(file_id, "attachments/slow.txt")])
        _wait_until(lambda: len(held) == 2 * file_copies.VM_INTAKES)

        _, ref = new_turn([_file(file_id, "attachments/ok.txt")])
        _wait_until(lambda: _key(ref, "attachments/ok.txt") in node.agent.files)
        # Each slow VM holds only its intake slots.
        assert len(held) == 2 * file_copies.VM_INTAKES
    finally:
        release.set()


class _TimedOutDeletes(_Wrapped):
    """Session files whose deletes time out."""

    def __init__(self, files: SessionFiles) -> None:
        super().__init__(files)
        self.deleted: list[str] = []

    def delete(self, path: str) -> bool:
        self.deleted.append(path)
        raise TimeoutError("the VM does not respond")


def test_a_delete_that_times_out_is_tried_again_by_the_next_turn(
    monkeypatch: pytest.MonkeyPatch,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    sandbox: FirecrackerHarnessSandbox,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    """The timeout ends the cleanup and fails the writes; the next turn
    deletes the files and copies the rest."""
    a, b, c = store_file(b"a"), store_file(b"b"), store_file(b"c")
    _, ref = new_turn(
        [
            _file(a, "attachments/project/a.txt"),
            _file(b, "attachments/project/b.txt"),
        ]
    )
    _wait_until(idle)
    timed_out: list[_TimedOutDeletes] = []

    def wrap(files: SessionFiles) -> SessionFiles:
        timed_out.append(_TimedOutDeletes(files))
        return timed_out[-1]

    session_files = sandbox.session_files
    _wrap(monkeypatch, sandbox, wrap)
    turn, _ = new_turn([_file(c, "attachments/c.txt")])
    _wait_until(idle)

    # The first delete ends the cleanup.
    assert [path for files in timed_out for path in files.deleted] == [
        "attachments/project/a.txt"
    ]
    assert "attachments/c.txt" not in node.agent.write_paths
    assert _status(turn) == (
        "[files] Failed: attachments/c.txt (the sandbox did not respond); "
        "retrying next turn."
    )

    monkeypatch.setattr(sandbox, "session_files", session_files)
    new_turn([_file(c, "attachments/c.txt")])
    _wait_until(idle)
    for path in ("attachments/project/a.txt", "attachments/project/b.txt"):
        assert _key(ref, path) not in node.agent.files
    assert node.agent.files[_key(ref, "attachments/c.txt")] == b"c"


def test_a_vm_that_stops_during_a_copy_fails_the_rest_at_once(
    monkeypatch: pytest.MonkeyPatch,
    new_file_copy_pool: NewFileCopyPool,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    sandbox: FirecrackerHarnessSandbox,
    client_factory: InsecureClientFactory,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    """The VM stops between two writes: the next write finds the instance
    gone and fails the copy's other files with no more tries; the next turn
    copies them onto the new instance."""
    monkeypatch.setattr(file_copies, "VM_COPY_WRITES", 1)
    new_file_copy_pool()
    a, b, c = store_file(b"a"), store_file(b"bb"), store_file(b"ccc")
    files = [
        _file(a, "attachments/a.txt"),
        _file(b, "attachments/b.txt"),
        _file(c, "attachments/c.txt"),
    ]
    gate = threading.Event()
    node.agent.write_gates["attachments/a.txt"] = gate
    turn, ref = new_turn()
    _exec(turn)
    copies = TurnFileCopies(ref, sandbox, files)
    _wait_until(lambda: "attachments/a.txt" in node.agent.write_waiting)
    _restart(client_factory, node, ref)
    gate.set()
    _wait_until(idle)

    assert "attachments/c.txt" not in node.agent.write_paths
    assert node.agent.write_paths.count("attachments/b.txt") <= 1
    line = copies.status.line()
    assert line is not None
    assert "attachments/c.txt (the sandbox did not respond)" in line, line

    _, ref = new_turn(files)
    _wait_until(idle)
    assert {
        path: node.agent.files.get(_key(ref, path))
        for path in ("attachments/a.txt", "attachments/b.txt", "attachments/c.txt")
    } == {
        "attachments/a.txt": b"a",
        "attachments/b.txt": b"bb",
        "attachments/c.txt": b"ccc",
    }


def test_pod_shutdown_stops_the_copies(
    monkeypatch: pytest.MonkeyPatch,
    new_file_copy_pool: NewFileCopyPool,
    new_turn: NewTurn,
    node: RunningFakeAgent,
    store_file: StoreFile,
    idle: Idle,
) -> None:
    monkeypatch.setattr(file_copies, "VM_COPY_WRITES", 1)
    pool = new_file_copy_pool()
    a, b = store_file(b"a"), store_file(b"b")
    gate = threading.Event()
    node.agent.write_gates["attachments/a.txt"] = gate
    # The write in progress fails once; shutdown stops its next try.
    node.agent.write_failures["attachments/a.txt"] = WriteFailure(
        SandboxDaemonErrorReason.INTERNAL, count=1
    )
    turn, _ = new_turn([_file(a, "attachments/a.txt"), _file(b, "attachments/b.txt")])
    _wait_until(lambda: "attachments/a.txt" in node.agent.write_waiting)
    other, _ = new_turn([_file(b, "attachments/other.txt")], uuid4())
    # The other chat's write waits for the VM's write slot.
    _wait_until(pool.intake.idle)

    pool.shutdown()
    gate.set()
    _wait_until(idle)
    assert _status(turn) == (
        "[files] Failed: attachments/a.txt (the copy stopped); "
        "attachments/b.txt (the copy stopped); retrying next turn."
    )
    # Nothing else is written, and the dropped copy stays copying.
    assert node.agent.write_paths == ["attachments/a.txt"]
    assert _status(other) == "[files] Copying: attachments/other.txt."
    # A copy after shutdown starts nothing.
    new_turn([_file(b, "attachments/late.txt")], uuid4())
    assert idle()
