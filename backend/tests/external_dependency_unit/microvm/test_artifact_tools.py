"""artifacts_list and artifacts_download against FirecrackerHarnessSandbox
with a fake host agent, Postgres and the file store: where a download lands,
the cache, refusals that never start the VM, Stop, the timeout, the size cap,
the chat file cleanup, and chat turns through the chat flow (the generic
card, live and replayed, and the code mode group `artifacts`)."""

import base64
import json
import threading
import time
from collections.abc import Generator, Sequence
from typing import IO
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, JsonValue
from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from onyx.agents.tools import ToolInvocation
from onyx.cache.interface import CacheBackend
from onyx.chat import process_message
from onyx.chat.execution import chat_turn_work
from onyx.chat.process_message import handle_stream_message_objects
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.db.chat import (
    create_chat_session,
    get_user_published_files,
    save_chat_artifact,
)
from onyx.db.models import ChatSession, FileRecord, User
from onyx.db.sandbox import get_or_create_sandbox
from onyx.file_store.file_store import get_default_file_store
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.model_response import Delta
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
)
from onyx.server.features.build.sandbox import harness_factory
from onyx.server.features.build.sandbox.firecracker.harness_sandbox import (
    FirecrackerHarnessSandbox,
)
from onyx.server.features.build.sandbox.harness_base import ARTIFACT_FILES_DIR
from onyx.server.features.build.sandbox.models import (
    HarnessSandboxRef,
    session_workspace,
)
from onyx.server.query_and_chat import streaming_models as packets
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.tools.constants import SPAWN_AGENT_TOOL_NAME
from onyx.tools.models import ToolContext, ToolOptions
from onyx.tools.tool_implementations.sandbox import file_copies, sandbox_tools
from onyx.tools.tool_implementations.sandbox.file_copies import TurnFileCopies
from onyx.tools.tool_implementations.sandbox.models import (
    PUBLISH_FILES_MAX_BYTES,
    VmChatFile,
)
from onyx.tools.tool_implementations.sandbox.sandbox_tools import (
    ArtifactsDownloadTool,
    ArtifactsListTool,
    PublishFilesTool,
)
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
from tests.external_dependency_unit.chat.test_wait_agents import (
    ScriptedLLM as WaitAgentsLLM,
)
from tests.external_dependency_unit.code_mode_helpers import (
    ChatLLM,
    code_step,
    last_tool_text,
    tool_step,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.microvm.conftest import (
    TENANT_ID,
    AddNode,
    Idle,
    NewFileCopyPool,
)
from tests.external_dependency_unit.microvm.fake_agent import (
    InsecureClientFactory,
    RunningFakeAgent,
)
from tests.external_dependency_unit.microvm.test_sandbox_tools import (
    SandboxChat,
    _forget_sandboxes,
    _wait_until,
)

pytestmark = pytest.mark.usefixtures("tenant_context", "initialize_file_store")


@pytest.fixture
def sandbox(
    monkeypatch: pytest.MonkeyPatch, client_factory: InsecureClientFactory
) -> FirecrackerHarnessSandbox:
    """The process's harness sandbox, on the fake agents."""
    instance = FirecrackerHarnessSandbox(
        template="tpl-1", client_factory=client_factory
    )
    monkeypatch.setattr(harness_factory, "HARNESS_SANDBOX_ENABLED", True)
    monkeypatch.setattr(harness_factory, "_instance", instance)
    monkeypatch.setattr(process_message, "HARNESS_SANDBOX_ENABLED", True)
    return instance


@pytest.fixture
def node(add_node: AddNode) -> RunningFakeAgent:
    return add_node(f"art-{uuid4().hex[:6]}")


@pytest.fixture
def user(
    db_session: Session,
    tenant_cache: CacheBackend,
    make_test_user: MakeTestUser,
    idle: Idle,
) -> Generator[User, None, None]:
    user = make_test_user("artifact_tools")
    yield user
    # A turn's last calls and saves, and a download's copy after a timeout or
    # a Stop, run on their own threads.
    assert chat_turn_work.wait_idle(timeout=30)
    _wait_until(idle)
    _forget_sandboxes(db_session, tenant_cache, user.id)


def _chat(db_session: Session, owner: User, title: str = "A chat") -> UUID:
    return create_chat_session(
        db_session, title, owner.id, persona_id=DEFAULT_PERSONA_ID
    ).id


def _publish(chat_session_id: UUID, name: str, data: bytes) -> str:
    """The file ID of a file that publish_files saved in the chat."""
    return save_chat_artifact(
        data,
        name=name,
        mime_type="text/plain",
        chat_session_id=chat_session_id,
        path=f"{session_workspace(chat_session_id)}/{name}",
        title=None,
        thumbnail=None,
    ).file_id


def _turn(owner: User, chat_session_id: UUID) -> SandboxTurn:
    return SandboxTurn(
        tenant_id=TENANT_ID,
        user_id=owner.id,
        chat_session_id=chat_session_id,
        vm_chat_files=[],
        copy_vm_chat_files=False,
    )


def _ref(db_session: Session, owner: User, chat_session_id: UUID) -> HarnessSandboxRef:
    return HarnessSandboxRef(
        tenant_id=TENANT_ID,
        sandbox_id=get_or_create_sandbox(db_session, owner.id).id,
        session_id=chat_session_id,
    )


def _call(
    tool: ArtifactsListTool | ArtifactsDownloadTool,
    arguments: dict[str, JsonValue],
    cancellation: CancellationSignal | None = None,
) -> ToolResult:
    outcome = tool.run(
        ToolInvocation(
            call_id="call-1",
            arguments=arguments,
            cancellation=cancellation or CancellationSignal(),
            update=lambda _progress: None,
        ),
        ToolContext(),
    )
    assert isinstance(outcome, ToolResult)
    return outcome


def _landed(file_id: str, name: str) -> str:
    return f"{ARTIFACT_FILES_DIR}/{file_id[:8]}-{name}"


def _vm_file(node: RunningFakeAgent, ref: HarnessSandboxRef, path: str) -> bytes | None:
    return node.agent.files.get((str(ref.sandbox_id), str(ref.session_id), path))


@pytest.fixture
def chats(db_session: Session, user: User) -> tuple[UUID, UUID]:
    """A chat of the user with a published file, and the chat that calls."""
    return _chat(db_session, user, "Reports"), _chat(db_session, user, "Today")


@pytest.mark.usefixtures("sandbox")
def test_a_download_lands_in_the_calling_chats_attachments_and_is_then_cached(
    db_session: Session,
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
) -> None:
    source, calling = chats
    data = b"a,b\n1,2\n"
    file_id = _publish(source, "report.csv", data)
    tool = ArtifactsDownloadTool(_turn(user, calling))
    ref = _ref(db_session, user, calling)
    path = _landed(file_id, "report.csv")

    first = _call(tool, {"file_id": file_id})
    assert not first.is_error
    assert json.loads(first.content) == {
        "path": path,
        "file_id": file_id,
        "name": "report.csv",
        "size": len(data),
        "mime_type": "text/plain",
        "chat_id": str(source),
        "cached": False,
    }
    assert _vm_file(node, ref, path) == data
    # Nothing lands in the chat that published the file.
    assert _vm_file(node, _ref(db_session, user, source), path) is None

    # A regular file of the record's size is in place: nothing is written.
    assert json.loads(_call(tool, {"file_id": file_id}).content)["cached"] is True
    assert node.agent.write_paths.count(path) == 1

    # A file of another size is written again.
    node.agent.files[(str(ref.sandbox_id), str(ref.session_id), path)] = b"x"
    assert json.loads(_call(tool, {"file_id": file_id}).content)["cached"] is False
    assert _vm_file(node, ref, path) == data
    assert node.agent.write_paths.count(path) == 2


@pytest.mark.usefixtures("sandbox")
def test_a_refused_file_never_starts_the_vm(
    db_session: Session,
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
    make_test_user: MakeTestUser,
) -> None:
    source, calling = chats
    stranger = make_test_user("artifact_tools_stranger")
    theirs = _publish(_chat(db_session, stranger), "theirs.txt", b"theirs")
    deleted_chat = _chat(db_session, user)
    in_deleted = _publish(deleted_chat, "gone.txt", b"gone")
    db_session.execute(
        update(ChatSession).where(ChatSession.id == deleted_chat).values(deleted=True)
    )
    big = _publish(source, "big.bin", b"big")
    db_session.execute(
        update(FileRecord)
        .where(FileRecord.file_id == big)
        .values(file_size=PUBLISH_FILES_MAX_BYTES + 1)
    )
    db_session.commit()
    tool = ArtifactsDownloadTool(_turn(user, calling))

    for file_id in (theirs, in_deleted, str(uuid4())):
        result = _call(tool, {"file_id": file_id})
        assert result.is_error
        assert result.content == f"No published file {file_id} in your chats"
    over = _call(tool, {"file_id": big})
    assert over.is_error
    assert over.content == "big.bin is larger than 100 MiB"
    # Listing reads the database only.
    assert not _call(ArtifactsListTool(_turn(user, calling)), {}).is_error
    assert node.agent.create_calls == 0


@pytest.mark.usefixtures("sandbox")
def test_a_stop_ends_the_wait_and_the_write_lands_on_its_own(
    db_session: Session,
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
) -> None:
    source, calling = chats
    file_id = _publish(source, "slow.txt", b"slow")
    path = _landed(file_id, "slow.txt")
    gate = threading.Event()
    node.agent.write_gates[path] = gate
    tool = ArtifactsDownloadTool(_turn(user, calling))
    signal = CancellationSignal()
    raised: list[BaseException] = []

    def download() -> None:
        try:
            _call(tool, {"file_id": file_id}, signal)
        except BaseException as error:
            raised.append(error)

    thread = threading.Thread(target=download)
    thread.start()
    try:
        _wait_until(lambda: path in node.agent.write_waiting)
        signal.cancel("user")
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert [type(error) for error in raised] == [AgentCancelled]
    finally:
        gate.set()
    _wait_until(
        lambda: _vm_file(node, _ref(db_session, user, calling), path) == b"slow"
    )
    assert json.loads(_call(tool, {"file_id": file_id}).content)["cached"] is True


@pytest.mark.usefixtures("sandbox")
def test_a_failed_or_timed_out_download_is_a_tool_error_without_details(
    monkeypatch: pytest.MonkeyPatch,
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
) -> None:
    source, calling = chats
    tool = ArtifactsDownloadTool(_turn(user, calling))
    monkeypatch.setattr(sandbox_tools, "COPY_BASE_SECONDS", 0.2)

    # The write passes its own deadline: the gRPC error stays in the log.
    hung = _publish(source, "hung.txt", b"hung")
    gate = threading.Event()
    node.agent.write_gates[_landed(hung, "hung.txt")] = gate
    try:
        failed = _call(tool, {"file_id": hung})
    finally:
        gate.set()
    assert failed.is_error
    assert failed.content == "The download failed; try again"

    # The file store read does not end before the wait does.
    slow = _publish(source, "slow.txt", b"slow")
    released = threading.Event()
    store = get_default_file_store()

    class SlowStore:
        def read_file(self, file_id: str, *, use_tempfile: bool) -> IO[bytes]:
            released.wait(10)
            return store.read_file(file_id, use_tempfile=use_tempfile)

    monkeypatch.setattr(sandbox_tools, "get_default_file_store", SlowStore)
    try:
        timed_out = _call(tool, {"file_id": slow})
    finally:
        released.set()
    assert timed_out.is_error
    assert timed_out.content == "The download timed out; try again"


@pytest.mark.usefixtures("sandbox")
def test_parallel_downloads_take_the_vms_write_slots(
    monkeypatch: pytest.MonkeyPatch,
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
    new_file_copy_pool: NewFileCopyPool,
) -> None:
    """Downloads read and write in the chat file copies' slots: at most
    VM_COPY_WRITES of one VM at a time."""
    source, calling = chats
    new_file_copy_pool()
    file_ids = [_publish(source, f"f{index}.txt", b"x") for index in range(5)]
    store = get_default_file_store()
    lock = threading.Lock()
    active = [0]
    most = [0]
    release = threading.Event()

    class CountingStore:
        def read_file(self, file_id: str, *, use_tempfile: bool) -> IO[bytes]:
            with lock:
                active[0] += 1
                most[0] = max(most[0], active[0])
            release.wait(10)
            try:
                return store.read_file(file_id, use_tempfile=use_tempfile)
            finally:
                with lock:
                    active[0] -= 1

    monkeypatch.setattr(sandbox_tools, "get_default_file_store", CountingStore)
    turn = _turn(user, calling)
    results: list[ToolResult] = []
    threads = [
        threading.Thread(
            target=lambda file_id=file_id: results.append(
                _call(ArtifactsDownloadTool(turn), {"file_id": file_id})
            )
        )
        for file_id in file_ids
    ]
    for thread in threads:
        thread.start()
    try:
        # Every download got past its checks; two hold the slots.
        _wait_until(
            lambda: (
                node.agent.list_requests.count((ARTIFACT_FILES_DIR, False)) == 5
                and active[0] == file_copies.VM_COPY_WRITES
            )
        )
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            assert active[0] <= file_copies.VM_COPY_WRITES
            time.sleep(0.01)  # test-flakes: allow polls a bound for a short window
    finally:
        release.set()
        for thread in threads:
            thread.join(timeout=30)
    assert most[0] == file_copies.VM_COPY_WRITES
    assert node.agent.most_writes_running <= file_copies.VM_COPY_WRITES
    assert [result.is_error for result in results] == [False] * 5


@pytest.mark.usefixtures("sandbox", "node")
def test_a_queued_download_waits_for_its_slot_until_pod_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    user: User,
    chats: tuple[UUID, UUID],
    new_file_copy_pool: NewFileCopyPool,
) -> None:
    """Downloads that hold both write slots past their own timeout do not
    time out the download queued behind them. Pod shutdown, which drops
    the queued task, fails it."""
    source, calling = chats
    pool = new_file_copy_pool()
    monkeypatch.setattr(sandbox_tools, "COPY_BASE_SECONDS", 0.3)
    held = [_publish(source, f"held{index}.txt", b"x") for index in range(2)]
    queued = _publish(source, "queued.txt", b"queued")
    dropped = _publish(source, "dropped.txt", b"dropped")
    store = get_default_file_store()
    release = threading.Event()
    reading: list[str] = []

    class HoldingStore:
        def read_file(self, file_id: str, *, use_tempfile: bool) -> IO[bytes]:
            if file_id in held:
                reading.append(file_id)
                release.wait(10)
            return store.read_file(file_id, use_tempfile=use_tempfile)

    monkeypatch.setattr(sandbox_tools, "get_default_file_store", HoldingStore)
    turn = _turn(user, calling)
    results: dict[str, ToolResult] = {}

    def download(file_id: str) -> None:
        results[file_id] = _call(ArtifactsDownloadTool(turn), {"file_id": file_id})

    threads = [threading.Thread(target=download, args=(file_id,)) for file_id in held]
    for thread in threads:
        thread.start()
    _wait_until(lambda: len(reading) == 2)
    queued_thread = threading.Thread(target=download, args=(queued,))
    queued_thread.start()
    threads.append(queued_thread)
    try:
        # The held downloads time out (twice 0.3 s from their slot); the
        # queued one waits longer than its own timeout for a slot.
        started = time.monotonic()
        _wait_until(
            lambda: (
                all(file_id in results for file_id in held)
                and time.monotonic() - started > 1.5
            )
        )
        assert queued not in results
        release.set()
        queued_thread.join(timeout=30)
        assert not results[queued].is_error

        # The held files are in place now; two new ones hold the slots.
        release.clear()
        reading.clear()
        held[:] = [_publish(source, f"again{index}.txt", b"x") for index in range(2)]
        threads = [
            threading.Thread(target=download, args=(file_id,)) for file_id in held
        ]
        for thread in threads:
            thread.start()
        _wait_until(lambda: len(reading) == 2)
        dropped_thread = threading.Thread(target=download, args=(dropped,))
        dropped_thread.start()
        threads.append(dropped_thread)
        _wait_until(lambda: all(file_id in results for file_id in held))
        pool.shutdown()
        dropped_thread.join(timeout=10)
        assert results[dropped].content == "The download failed; try again"
    finally:
        release.set()
        for thread in threads:
            thread.join(timeout=30)
    assert [results[file_id].content for file_id in held] == [
        "The download timed out; try again"
    ] * 2


@pytest.mark.usefixtures("sandbox")
def test_the_chat_file_copies_leave_downloads_alone(
    db_session: Session,
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
    new_file_copy_pool: NewFileCopyPool,
) -> None:
    source, calling = chats
    pool = new_file_copy_pool()
    file_id = _publish(source, "kept.txt", b"kept")
    turn = _turn(user, calling)
    _call(ArtifactsDownloadTool(turn), {"file_id": file_id})
    ref = _ref(db_session, user, calling)
    files = node.agent.files
    # A project file that left the chat, which the cleanup deletes.
    files[(str(ref.sandbox_id), str(ref.session_id), "attachments/project/x.txt")] = (
        b"left"
    )

    store = get_default_file_store()
    project_file = _publish(source, "p.txt", b"project")
    TurnFileCopies(
        ref,
        turn.sandbox,
        [VmChatFile(file_id=project_file, path="attachments/project/p.txt")],
        generation=turn.copy_target().generation,
    )
    _wait_until(pool.idle)
    assert _vm_file(node, ref, "attachments/project/p.txt") == b"project"
    assert _vm_file(node, ref, "attachments/project/x.txt") is None
    assert _vm_file(node, ref, _landed(file_id, "kept.txt")) == b"kept"
    assert store.read_file(file_id).read() == b"kept"


# The chat flow


def _card_packets(parts: Sequence[object]) -> list[packets.PacketObj]:
    """The generic tool card packets of streamed parts or replayed packets,
    and their section ends."""
    card_types = (
        packets.CustomToolStart,
        packets.CustomToolArgs,
        packets.CustomToolDelta,
    )
    objects = [
        part.obj if isinstance(part, packets.Packet) else part
        for part in parts
        if isinstance(part, (packets.Packet, BaseModel))
    ]
    return [
        obj
        for index, obj in enumerate(objects)
        if isinstance(obj, card_types)
        or (
            isinstance(obj, packets.SectionEnd)
            and index > 0
            and isinstance(objects[index - 1], card_types)
        )
    ]


def _sandbox_chat(
    db_session: Session, owner: User, monkeypatch: pytest.MonkeyPatch, title: str
) -> SandboxChat:
    return SandboxChat(
        user=owner,
        chat_session_id=_chat(db_session, owner, title),
        monkeypatch=monkeypatch,
    )


@pytest.mark.usefixtures("node")
def test_a_chat_lists_and_downloads_files_published_in_other_chats(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    user: User,
) -> None:
    """Chat A publishes a report, a subagent of chat B publishes its notes,
    and chat C finds both with a query and a cursor, then downloads the
    report. The generic cards stream as the reload replays them."""
    chat_a = _sandbox_chat(db_session, user, monkeypatch, "Quarter")
    chat_b = _sandbox_chat(db_session, user, monkeypatch, "Notes")
    chat_c = _sandbox_chat(db_session, user, monkeypatch, "Today")
    sandbox.write_file(chat_a.ref(db_session), "out/report.csv", b"a,b\n1,2\n")
    chat_a.send(
        ChatLLM(
            [
                tool_step(
                    PublishFilesTool.NAME,
                    "publish",
                    {"files": [{"path": "out/report.csv", "title": "Report"}]},
                ),
                Delta(content="Done."),
            ]
        )
    )
    sandbox.write_file(chat_b.ref(db_session), "report-notes.md", b"# Notes\n")

    # A subagent of chat B publishes the notes.
    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        texts = [message.text for message in request.messages]
        results = [
            message
            for message in request.messages
            if isinstance(message, ToolResultMessage)
        ]
        if "Task helper" in texts:
            if results:
                return AssistantMessage(content=[TextContent(text="Helped.")])
            return AssistantMessage(
                content=[
                    ToolCall(
                        id="child-publish",
                        name=PublishFilesTool.NAME,
                        arguments={"files": [{"path": "report-notes.md"}]},
                    )
                ]
            )
        if results:
            return AssistantMessage(content=[TextContent(text="Done.")])
        return AssistantMessage(
            content=[
                ToolCall(
                    id="spawn",
                    name=SPAWN_AGENT_TOOL_NAME,
                    arguments={"name": "helper", "instruction": "Task helper"},
                )
            ]
        )

    monkeypatch.setattr("onyx.chat.agent.CODE_MODE_ENABLED", False)
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona",
        lambda **_kwargs: WaitAgentsLLM(generate),
    )
    for _part in handle_stream_message_objects(
        new_msg_req=SendMessageRequest(
            message="Work in the sandbox.",
            chat_session_id=chat_b.chat_session_id,
            tool_options=ToolOptions(allowed=[]),
            accepts_follow_ups=True,
        ),
        user=chat_b.user,
    ):
        pass
    assert chat_turn_work.wait_idle(timeout=30)

    found = get_user_published_files(
        db_session, user.id, query="REPORT", chat_session_id=None, limit=2, before=None
    )
    assert found is not None
    [(notes, after), (report, _)] = found
    assert (notes.chat_id, notes.path) == (chat_b.chat_session_id, "report-notes.md")
    assert (report.chat_id, report.path, report.title) == (
        chat_a.chat_session_id,
        "out/report.csv",
        "Report",
    )
    cursor = base64.urlsafe_b64encode(after.model_dump_json().encode()).decode()

    llm = ChatLLM(
        [
            tool_step(ArtifactsListTool.NAME, "list", {"query": "REPORT", "limit": 1}),
            tool_step(
                ArtifactsListTool.NAME,
                "next",
                {"query": "REPORT", "limit": 1, "cursor": cursor},
            ),
            tool_step(
                ArtifactsDownloadTool.NAME, "download", {"file_id": report.file_id}
            ),
            Delta(content="Done."),
        ]
    )
    parts = chat_c.send(llm)

    listed = json.loads(last_tool_text(llm, "list"))
    assert [entry["file_id"] for entry in listed["artifacts"]] == [notes.file_id]
    assert listed["next_cursor"] == cursor
    following = json.loads(last_tool_text(llm, "next"))
    assert [entry["file_id"] for entry in following["artifacts"]] == [report.file_id]
    assert following["next_cursor"] is None
    downloaded = json.loads(last_tool_text(llm, "download"))
    path = _landed(report.file_id, "report.csv")
    assert downloaded["path"] == path
    assert _vm_file(node, chat_c.ref(db_session), path) == b"a,b\n1,2\n"

    live = _card_packets(parts)
    assert [
        obj.display_name for obj in live if isinstance(obj, packets.CustomToolStart)
    ] == [
        ArtifactsListTool.display_name,
        ArtifactsListTool.display_name,
        ArtifactsDownloadTool.display_name,
    ]
    [replayed] = chat_c.replayed(db_session)
    assert _card_packets(replayed) == live


@pytest.mark.usefixtures("sandbox")
def test_a_program_finds_the_artifact_tools_with_tool_search(
    db_session: Session,
    node: RunningFakeAgent,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _chat(db_session, user, "Reports")
    file_id = _publish(source, "report.csv", b"a,b\n")
    chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
    llm = ChatLLM(
        [
            code_step(
                "code",
                "matches = await tool_search('download a published file')\n"
                "print([match['name'] for match in matches])\n"
                f"r = await tools.artifacts__download(file_id='{file_id}')\n"
                "print(r['path'], r['cached'])\n",
            ),
            Delta(content="Done."),
        ]
    )
    chat.send(llm, code_mode=True)

    [description] = [
        tool["function"]["description"]
        for tool in llm.requests[0]["tools"]
        if tool["function"]["name"] == "execute_code"
    ]
    assert (
        "\n  - artifacts: Find and download the files that you published in this "
        "chat and the user's other chats.\n" in description
    )
    assert "artifacts__download" not in description
    text = last_tool_text(llm, "code")
    assert "'artifacts__download'" in text
    path = _landed(file_id, "report.csv")
    assert f"{path} False" in text
    assert _vm_file(node, chat.ref(db_session), path) == b"a,b\n"


@pytest.mark.usefixtures("sandbox", "node")
def test_only_the_chats_owner_gets_the_sandbox_tools(
    db_session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any user can open a chat without an owner; such a chat gets no
    sandbox, so nothing publishes into it."""
    ownerless = create_chat_session(
        db_session, "No owner", None, persona_id=DEFAULT_PERSONA_ID
    ).id
    try:
        owned = _chat(db_session, user, "Mine")

        def offered(chat_session_id: UUID) -> set[str]:
            llm = ChatLLM([Delta(content="Done.")])
            SandboxChat(
                user=user, chat_session_id=chat_session_id, monkeypatch=monkeypatch
            ).send(llm)
            return {tool["function"]["name"] for tool in llm.requests[0]["tools"]}

        assert {PublishFilesTool.NAME, ArtifactsListTool.NAME} <= offered(owned)
        assert not {PublishFilesTool.NAME, ArtifactsListTool.NAME} & offered(ownerless)
    finally:
        db_session.rollback()
        db_session.execute(delete(ChatSession).where(ChatSession.id == ownerless))
        db_session.commit()
