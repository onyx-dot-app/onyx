"""library_list and library_prepare_materialize against
FirecrackerHarnessSandbox with a fake host agent, Postgres and the file
store: where a copy lands, the cache, the conflict policies, refusals that
never start the VM, item errors, Stop, the write slots and tries, the chat
file cleanup, and chat turns through the chat flow (the generic card, live
and replayed, and the code mode group `library`)."""

import base64
import json
import threading
import time
from collections.abc import Callable, Generator, Sequence
from typing import IO
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, JsonValue
from sqlalchemy import delete, select, update
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
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ChatArtifactVersion, ChatSession, User
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
from onyx.microvm.models import FileListing
from onyx.server.features.build.sandbox import harness_factory
from onyx.server.features.build.sandbox.firecracker.harness_sandbox import (
    FirecrackerHarnessSandbox,
)
from onyx.server.features.build.sandbox.harness_base import (
    ARTIFACT_FILES_DIR,
    SessionFiles,
)
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
    ARTIFACT_CURSOR,
    LibraryListFilters,
    VmChatFile,
)
from onyx.tools.tool_implementations.sandbox.sandbox_tools import (
    LibraryListTool,
    LibraryPrepareMaterializeTool,
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
from tests.external_dependency_unit.microvm.test_file_copies import _wrap, _Wrapped
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
    # A turn's last calls and saves, and a copy's write after a timeout or
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


def _artifact_id(file_id: str) -> UUID:
    with get_session_with_current_tenant() as db_session:
        return db_session.scalars(
            select(ChatArtifactVersion.artifact_id).where(
                ChatArtifactVersion.file_id == file_id
            )
        ).one()


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
    tool: LibraryListTool | LibraryPrepareMaterializeTool,
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


def _copy(
    tool: LibraryPrepareMaterializeTool,
    items: list[JsonValue],
    destination: dict[str, JsonValue] | None = None,
    cancellation: CancellationSignal | None = None,
) -> ToolResult:
    arguments: dict[str, JsonValue] = {"items": items}
    if destination is not None:
        arguments["destination"] = destination
    return _call(tool, arguments, cancellation)


def _items(result: ToolResult) -> list[dict[str, JsonValue]]:
    assert not result.is_error, result.content
    return json.loads(result.content)["items"]


def _landed(file_id: str, name: str) -> str:
    return f"{ARTIFACT_FILES_DIR}/{file_id[:8]}-{name}"


def _vm_file(node: RunningFakeAgent, ref: HarnessSandboxRef, path: str) -> bytes | None:
    return node.agent.files.get((str(ref.sandbox_id), str(ref.session_id), path))


def _put_vm_file(
    node: RunningFakeAgent, ref: HarnessSandboxRef, path: str, data: bytes
) -> None:
    node.agent.files[(str(ref.sandbox_id), str(ref.session_id), path)] = data


@pytest.fixture
def chats(db_session: Session, user: User) -> tuple[UUID, UUID]:
    """A chat of the user with a published file, and the chat that calls."""
    return _chat(db_session, user, "Reports"), _chat(db_session, user, "Today")


@pytest.mark.usefixtures("sandbox")
def test_a_copy_lands_in_the_calling_chats_attachments_and_is_then_cached(
    db_session: Session,
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
) -> None:
    source, calling = chats
    data = b"a,b\n1,2\n"
    file_id = _publish(source, "report.csv", data)
    artifact_id = _artifact_id(file_id)
    tool = LibraryPrepareMaterializeTool(_turn(user, calling))
    ref = _ref(db_session, user, calling)
    path = _landed(file_id, "report.csv")

    assert _items(_copy(tool, [{"file_id": file_id}])) == [
        {
            "library_file_id": str(artifact_id),
            "file_id": file_id,
            "version_number": 1,
            "file_name": f"{file_id[:8]}-report.csv",
            "path": path,
            "file_size_bytes": len(data),
            "mime_type": "text/plain",
            "status": "written",
        }
    ]
    assert _vm_file(node, ref, path) == data
    # Nothing lands in the chat that published the file.
    assert _vm_file(node, _ref(db_session, user, source), path) is None

    # A regular file of the record's size is in place: nothing is written,
    # under every policy.
    for policy in ("dedupe", "overwrite", "error"):
        [item] = _items(
            _copy(tool, [{"file_id": file_id}], {"conflict_policy": policy})
        )
        assert (item["status"], item["path"]) == ("cached", path)
    assert node.agent.write_paths.count(path) == 1

    # A file of another size at the file's own name is written over.
    _put_vm_file(node, ref, path, b"x")
    [item] = _items(_copy(tool, [{"file_id": file_id}], {"conflict_policy": "error"}))
    assert item["status"] == "written"
    assert _vm_file(node, ref, path) == data
    assert node.agent.write_paths.count(path) == 2


@pytest.mark.usefixtures("sandbox")
def test_a_library_file_id_copies_its_newest_version_and_a_file_id_its_own(
    db_session: Session,
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
) -> None:
    source, calling = chats
    first = _publish(source, "notes.md", b"first")
    second = _publish(source, "notes.md", b"second version")
    artifact_id = _artifact_id(first)
    tool = LibraryPrepareMaterializeTool(_turn(user, calling))

    by_artifact, by_file = _items(
        _copy(tool, [{"library_file_id": str(artifact_id)}, {"file_id": first}])
    )
    assert (by_artifact["file_id"], by_artifact["version_number"]) == (second, 2)
    assert (by_file["file_id"], by_file["version_number"]) == (first, 1)
    ref = _ref(db_session, user, calling)
    assert _vm_file(node, ref, _landed(second, "notes.md")) == b"second version"
    assert _vm_file(node, ref, _landed(first, "notes.md")) == b"first"

    # An item gives exactly one of them.
    for item in ({}, {"file_id": first, "library_file_id": str(artifact_id)}):
        result = _copy(tool, [item])
        assert result.is_error
        assert "exactly one of file_id and library_file_id" in result.content


@pytest.mark.usefixtures("sandbox")
def test_each_conflict_policy_outside_the_default_names(
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
) -> None:
    source, calling = chats
    file_id = _publish(source, "report.csv", b"new")
    turn = _turn(user, calling)
    tool = LibraryPrepareMaterializeTool(turn)
    # The VM starts empty, so the file goes in after it starts.
    ref = turn.start_call()
    turn.sandbox.ensure_running(ref)
    _put_vm_file(node, ref, "work/report.csv", b"old")

    # dedupe, the default, takes the first free name, also against the
    # names that the call itself wrote.
    first, second = _items(
        _copy(tool, [{"file_id": file_id}] * 2, {"directory": "work"})
    )
    assert (first["path"], second["path"]) == (
        "work/report (1).csv",
        "work/report (2).csv",
    )
    assert first["file_name"] == "report (1).csv"
    assert _vm_file(node, ref, "work/report.csv") == b"old"
    assert _vm_file(node, ref, "work/report (2).csv") == b"new"

    failed = _copy(
        tool, [{"file_id": file_id}], {"directory": "work", "conflict_policy": "error"}
    )
    assert failed.is_error
    assert failed.content == "No file was copied:\n- work/report.csv already exists"

    [item] = _items(
        _copy(
            tool,
            [{"file_id": file_id}],
            {"directory": "work", "conflict_policy": "overwrite"},
        )
    )
    assert (item["path"], item["status"]) == ("work/report.csv", "written")
    assert _vm_file(node, ref, "work/report.csv") == b"new"

    # file_name and relative_directory choose the place; parents are made,
    # and a name keeps only its last part, in its shell-safe form.
    [named] = _items(
        _copy(
            tool,
            [
                {
                    "file_id": file_id,
                    "file_name": "sub/Q3 $report.csv",
                    "relative_directory": "a/b",
                }
            ],
            {"directory": "."},
        )
    )
    assert named["path"] == "a/b/Q3 _report.csv"
    assert _vm_file(node, ref, "a/b/Q3 _report.csv") == b"new"
    # A subdirectory of the default directory is not the default naming.
    [nested] = _items(_copy(tool, [{"file_id": file_id, "relative_directory": "x"}]))
    assert nested["path"] == f"{ARTIFACT_FILES_DIR}/x/report.csv"

    # An absolute directory in the working directory is that directory.
    [absolute] = _items(
        _copy(
            tool,
            [{"file_id": file_id}],
            {
                "directory": f"{session_workspace(calling)}/work",
                "conflict_policy": "overwrite",
            },
        )
    )
    assert absolute["path"] == "work/report.csv"


@pytest.mark.usefixtures("sandbox")
def test_a_deduped_name_cuts_its_stem_to_fit_the_name_limit(
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
) -> None:
    source, calling = chats
    name = "\u00e9" * 125 + ".csv"
    file_id = _publish(source, name, b"new")
    turn = _turn(user, calling)
    tool = LibraryPrepareMaterializeTool(turn)
    ref = turn.start_call()
    turn.sandbox.ensure_running(ref)
    _put_vm_file(node, ref, f"work/{name}", b"old")

    [deduped] = _items(_copy(tool, [{"file_id": file_id}], {"directory": "work"}))

    written = deduped["file_name"]
    assert isinstance(written, str)
    assert len(written.encode()) <= 255
    assert written.endswith(" (1).csv")
    assert _vm_file(node, ref, f"work/{written}") == b"new"


@pytest.mark.usefixtures("sandbox")
def test_the_conflict_check_sees_hidden_files_and_a_cut_listing(
    monkeypatch: pytest.MonkeyPatch,
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
) -> None:
    source, calling = chats
    file_id = _publish(source, "report.csv", b"new")
    turn = _turn(user, calling)
    tool = LibraryPrepareMaterializeTool(turn)
    ref = turn.start_call()
    turn.sandbox.ensure_running(ref)
    _put_vm_file(node, ref, "work/.env", b"secret")

    hidden = _copy(
        tool,
        [{"file_id": file_id, "file_name": ".env"}],
        {"directory": "work", "conflict_policy": "error"},
    )
    assert hidden.content == "No file was copied:\n- work/.env already exists"
    assert _vm_file(node, ref, "work/.env") == b"secret"

    # A listing cut before the name may miss a file there.
    _put_vm_file(node, ref, "work/a.txt", b"a")
    monkeypatch.setattr(file_copies, "MAX_LISTED", 1)
    cut = _copy(
        tool, [{"file_id": file_id}], {"directory": "work", "conflict_policy": "error"}
    )
    assert cut.content == "No file was copied:\n- work/report.csv may already exist"
    [deduped] = _items(_copy(tool, [{"file_id": file_id}], {"directory": "work"}))
    assert deduped["path"] == "work/report (1).csv"
    assert _vm_file(node, ref, "work/report.csv") is None


@pytest.mark.usefixtures("sandbox")
def test_a_copy_never_replaces_a_file_that_its_listing_missed(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
) -> None:
    """The listing is a snapshot: a parallel copy can take a name after it.
    The write then refuses the name; error reports it, and dedupe tries the
    next free name, a bounded number of times."""
    source, calling = chats
    file_id = _publish(source, "report.csv", b"new")
    turn = _turn(user, calling)
    tool = LibraryPrepareMaterializeTool(turn)
    ref = turn.start_call()
    turn.sandbox.ensure_running(ref)
    _put_vm_file(node, ref, "work/report.csv", b"old")
    _put_vm_file(node, ref, "work/report (1).csv", b"old 1")

    class _EmptyListing(_Wrapped):
        def list_files(
            self,
            directory: str,  # noqa: ARG002
            *,
            max_entries: int,  # noqa: ARG002
            include_hidden: bool = False,  # noqa: ARG002
        ) -> FileListing:
            return FileListing(entries=[], truncated=False)

    _wrap(monkeypatch, sandbox, _EmptyListing)
    failed = _copy(
        tool, [{"file_id": file_id}], {"directory": "work", "conflict_policy": "error"}
    )
    assert failed.content == "No file was copied:\n- work/report.csv already exists"
    [deduped] = _items(_copy(tool, [{"file_id": file_id}], {"directory": "work"}))
    assert deduped["path"] == "work/report (2).csv"
    assert _vm_file(node, ref, "work/report.csv") == b"old"
    assert _vm_file(node, ref, "work/report (1).csv") == b"old 1"
    assert _vm_file(node, ref, "work/report (2).csv") == b"new"

    monkeypatch.setattr(sandbox_tools, "_MATERIALIZE_NAME_TRIES", 3)
    exhausted = _copy(tool, [{"file_id": file_id}], {"directory": "work"})
    assert exhausted.content == (
        "No file was copied:\n- work/report (2).csv and the names before it are "
        "taken; try again"
    )


@pytest.mark.usefixtures("sandbox", "node")
def test_a_listing_that_times_out_stops_the_remaining_items(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    user: User,
    chats: tuple[UUID, UUID],
) -> None:
    """A listing past its deadline ends the copy, as a write does: the later
    items fail without another listing."""
    source, calling = chats
    file_ids = [_publish(source, f"f{index}.txt", b"x") for index in range(3)]
    turn = _turn(user, calling)
    tool = LibraryPrepareMaterializeTool(turn)
    turn.start_call()
    listed: list[str] = []

    class _HungListing(_Wrapped):
        def list_files(
            self, directory: str, *, max_entries: int, include_hidden: bool = False
        ) -> FileListing:
            if directory != "work":
                return super().list_files(
                    directory, max_entries=max_entries, include_hidden=include_hidden
                )
            listed.append(directory)
            raise TimeoutError("the listing timed out")

    _wrap(monkeypatch, sandbox, _HungListing)
    failed = _copy(
        tool, [{"file_id": file_id} for file_id in file_ids], {"directory": "work"}
    )
    stopped = "- The copy failed: the sandbox did not respond; try again"
    assert failed.content == (
        f"No file was copied:\n- The copy timed out; try again\n{stopped}\n{stopped}"
    )
    assert listed == ["work"]


@pytest.mark.usefixtures("sandbox")
def test_only_an_item_that_needs_the_listing_lists_its_directory(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
) -> None:
    """An overwrite outside the chat file names lists nothing; a chat file
    name lists its directory once, for the cache."""
    source, calling = chats
    file_ids = [_publish(source, f"f{index}.txt", b"x") for index in range(2)]
    turn = _turn(user, calling)
    tool = LibraryPrepareMaterializeTool(turn)
    ref = turn.start_call()
    listed: list[str] = []

    class _CountedListing(_Wrapped):
        def list_files(
            self, directory: str, *, max_entries: int, include_hidden: bool = False
        ) -> FileListing:
            listed.append(directory)
            return super().list_files(
                directory, max_entries=max_entries, include_hidden=include_hidden
            )

    _wrap(monkeypatch, sandbox, _CountedListing)
    written = _items(
        _copy(
            tool,
            [{"file_id": file_id} for file_id in file_ids],
            {"directory": "work", "conflict_policy": "overwrite"},
        )
    )
    assert [item["status"] for item in written] == ["written", "written"]
    assert _vm_file(node, ref, "work/f1.txt") == b"x"
    assert listed == []

    _items(_copy(tool, [{"file_id": file_id} for file_id in file_ids]))
    assert listed == [ARTIFACT_FILES_DIR]


@pytest.mark.usefixtures("sandbox")
def test_bad_destinations_and_refused_files_never_start_the_vm(
    db_session: Session,
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
    make_test_user: MakeTestUser,
) -> None:
    source, calling = chats
    file_id = _publish(source, "a.txt", b"a")
    stranger = make_test_user("artifact_tools_stranger")
    theirs = _publish(_chat(db_session, stranger), "theirs.txt", b"theirs")
    deleted_chat = _chat(db_session, user)
    in_deleted = _publish(deleted_chat, "gone.txt", b"gone")
    db_session.execute(
        update(ChatSession).where(ChatSession.id == deleted_chat).values(deleted=True)
    )
    db_session.commit()
    tool = LibraryPrepareMaterializeTool(_turn(user, calling))

    for directory, refusal in (
        ("../up", "leaves the working directory"),
        ("a/../../b", "leaves the working directory"),
        ("/tmp/onyx", "is outside the working directory"),
        ("attachments", "is not a destination"),
        ("attachments/project", "is not a destination"),
        ("attachments/search/x", "is not a destination"),
        (f"{session_workspace(calling)}/attachments/agent", "is not a destination"),
    ):
        result = _copy(tool, [{"file_id": file_id}], {"directory": directory})
        assert result.is_error
        assert result.content.startswith(f"{directory!r} "), result.content
        assert refusal in result.content

    # In the working directory, attachments/ is refused below it too.
    inside = _copy(
        tool,
        [{"file_id": file_id, "relative_directory": "attachments/project"}],
        {"directory": "."},
    )
    assert inside.is_error
    assert "'attachments/project' is not a destination" in inside.content

    unknown = str(uuid4())
    unknown_library = str(uuid4())
    refused = _copy(
        tool,
        [
            {"file_id": theirs},
            {"file_id": in_deleted},
            {"file_id": unknown},
            {"library_file_id": unknown_library},
            {"file_id": file_id, "relative_directory": "../../../x"},
            {"file_id": file_id, "relative_directory": "/abs"},
        ],
    )
    assert refused.is_error
    lines = refused.content.splitlines()
    assert lines[0] == "No file was copied:"
    assert lines[1:5] == [
        f"- No published file {theirs} in your chats",
        f"- No published file {in_deleted} in your chats",
        f"- No published file {unknown} in your chats",
        f"- No published file {unknown_library} in your chats",
    ]
    assert [line.split("' ", 1)[1] for line in lines[5:]] == [
        "leaves the working directory",
        f"is outside the working directory {session_workspace(calling)}; use "
        "exec_command elsewhere",
    ]
    # Listing reads the database only.
    assert not _call(LibraryListTool(_turn(user, calling)), {}).is_error
    assert node.agent.create_calls == 0


@pytest.mark.usefixtures("sandbox")
def test_a_failed_item_does_not_stop_the_others(
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
) -> None:
    source, calling = chats
    first = _publish(source, "one.txt", b"one")
    second = _publish(source, "two.txt", b"two")
    turn = _turn(user, calling)
    tool = LibraryPrepareMaterializeTool(turn)
    ref = turn.start_call()
    turn.sandbox.ensure_running(ref)
    _put_vm_file(node, ref, "out/one.txt", b"taken")
    unknown = str(uuid4())

    items = _items(
        _copy(
            tool,
            [
                {"file_id": first},
                {"file_id": unknown},
                {"file_id": second, "relative_directory": "../../x"},
                {"file_id": second},
            ],
            {"directory": "out", "conflict_policy": "error"},
        )
    )
    assert items == [
        {"file_id": first, "status": "error", "error": "out/one.txt already exists"},
        {
            "file_id": unknown,
            "status": "error",
            "error": f"No published file {unknown} in your chats",
        },
        {
            "file_id": second,
            "status": "error",
            "error": items[2]["error"],
        },
        {
            "library_file_id": str(_artifact_id(second)),
            "file_id": second,
            "version_number": 1,
            "file_name": "two.txt",
            "path": "out/two.txt",
            "file_size_bytes": 3,
            "mime_type": "text/plain",
            "status": "written",
        },
    ]
    assert "leaves the working directory" in str(items[2]["error"])
    assert _vm_file(node, ref, "out/one.txt") == b"taken"
    assert _vm_file(node, ref, "out/two.txt") == b"two"


@pytest.mark.usefixtures("sandbox")
def test_a_stop_ends_the_wait_and_the_write_lands_on_its_own(
    db_session: Session,
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
) -> None:
    source, calling = chats
    file_id = _publish(source, "slow.txt", b"slow")
    later = _publish(source, "later.txt", b"later")
    path = _landed(file_id, "slow.txt")
    gate = threading.Event()
    node.agent.write_gates[path] = gate
    tool = LibraryPrepareMaterializeTool(_turn(user, calling))
    signal = CancellationSignal()
    raised: list[BaseException] = []

    def copy() -> None:
        try:
            _copy(tool, [{"file_id": file_id}, {"file_id": later}], cancellation=signal)
        except BaseException as error:
            raised.append(error)

    thread = threading.Thread(target=copy)
    thread.start()
    try:
        _wait_until(lambda: path in node.agent.write_waiting)
        signal.cancel("user")
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert [type(error) for error in raised] == [AgentCancelled]
    finally:
        gate.set()
    ref = _ref(db_session, user, calling)
    _wait_until(lambda: _vm_file(node, ref, path) == b"slow")
    # The Stop came before the next item.
    assert _vm_file(node, ref, _landed(later, "later.txt")) is None
    [item] = _items(_copy(tool, [{"file_id": file_id}]))
    assert item["status"] == "cached"


@pytest.mark.usefixtures("sandbox")
def test_a_stop_before_the_next_item_ends_the_copy_without_writing(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
) -> None:
    """Stop is checked at the start of each item, so an item that writes
    nothing (here a cached one) does not let the next item list its folder."""
    source, calling = chats
    cached = _publish(source, "cached.txt", b"cached")
    later = _publish(source, "later.txt", b"later")
    turn = _turn(user, calling)
    tool = LibraryPrepareMaterializeTool(turn)
    ref = turn.start_call()
    turn.sandbox.ensure_running(ref)
    _put_vm_file(node, ref, _landed(cached, "cached.txt"), b"cached")
    signal = CancellationSignal()
    listed: list[str] = []

    class _StopWhileListing(_Wrapped):
        def list_files(
            self, directory: str, *, max_entries: int, include_hidden: bool = False
        ) -> FileListing:
            listed.append(directory)
            listing = super().list_files(
                directory, max_entries=max_entries, include_hidden=include_hidden
            )
            signal.cancel("user")
            return listing

    _wrap(monkeypatch, sandbox, _StopWhileListing)
    with pytest.raises(AgentCancelled):
        _copy(
            tool,
            [
                {"file_id": cached},
                {"file_id": later, "relative_directory": "later"},
            ],
            cancellation=signal,
        )
    assert listed == [ARTIFACT_FILES_DIR]
    assert _vm_file(node, ref, f"{ARTIFACT_FILES_DIR}/later/later.txt") is None


@pytest.mark.usefixtures("sandbox")
def test_a_sandbox_that_stops_responding_fails_the_remaining_items(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
) -> None:
    """A write past its deadline ends the copy, as in the chat file copies:
    no retry, and the later items fail without a write. The gRPC error
    stays in the log."""
    source, calling = chats
    tool = LibraryPrepareMaterializeTool(_turn(user, calling))
    monkeypatch.setattr(file_copies, "COPY_BASE_SECONDS", 0.2)
    hung = _publish(source, "hung.txt", b"hung")
    later = _publish(source, "later.txt", b"later")
    hung_path = _landed(hung, "hung.txt")
    gate = threading.Event()
    node.agent.write_gates[hung_path] = gate
    try:
        failed = _copy(tool, [{"file_id": hung}, {"file_id": later}])
    finally:
        gate.set()
    no_response = "- The copy failed: the sandbox did not respond; try again"
    assert failed.content == f"No file was copied:\n{no_response}\n{no_response}"
    ref = _ref(db_session, user, calling)
    assert _vm_file(node, ref, _landed(later, "later.txt")) is None


def test_a_vm_that_is_gone_fails_the_remaining_items(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
) -> None:
    """A VM that is gone from its node ends the copy as a sandbox that stops
    responding does: a later file that the listing showed in place is not
    reported cached."""
    source, calling = chats
    first = _publish(source, "first.txt", b"first")
    second = _publish(source, "second.txt", b"second")
    cached = _publish(source, "cached.txt", b"cached")
    turn = _turn(user, calling)
    tool = LibraryPrepareMaterializeTool(turn)
    ref = turn.start_call()
    turn.sandbox.ensure_running(ref)
    _put_vm_file(node, ref, _landed(cached, "cached.txt"), b"cached")
    first_path = _landed(first, "first.txt")

    class _GoneAfterFirst(_Wrapped):
        def write(
            self, path: str, data: IO[bytes], *, timeout_seconds: float, overwrite: bool
        ) -> None:
            super().write(
                path, data, timeout_seconds=timeout_seconds, overwrite=overwrite
            )
            if path == first_path:
                node.agent.vms.pop(str(ref.sandbox_id))

    _wrap(monkeypatch, sandbox, _GoneAfterFirst)
    items = _items(
        _copy(tool, [{"file_id": first}, {"file_id": second}, {"file_id": cached}])
    )
    no_response = "The copy failed: the sandbox did not respond; try again"
    assert [(item["status"], item.get("error")) for item in items] == [
        ("written", None),
        ("error", no_response),
        ("error", no_response),
    ]


@pytest.mark.usefixtures("node")
def test_the_next_items_write_keeps_its_busy_mark(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    user: User,
    chats: tuple[UUID, UUID],
) -> None:
    """The end of one item's write never clears the busy mark that the next
    item's write set. A clear that comes after the item was reported waits
    for the next item's mark, as a slow clear would."""
    source, calling = chats
    first = _publish(source, "first.txt", b"first")
    second = _publish(source, "second.txt", b"second")
    second_path = _landed(second, "second.txt")
    events: list[str] = []
    reported = threading.Event()
    next_mark = threading.Event()

    class _Recorded(_Wrapped):
        def write(
            self, path: str, data: IO[bytes], *, timeout_seconds: float, overwrite: bool
        ) -> None:
            events.append(f"write {path}")
            super().write(
                path, data, timeout_seconds=timeout_seconds, overwrite=overwrite
            )

        def mark_busy(self, seconds: float | None) -> None:
            if seconds is None and reported.is_set():
                next_mark.wait(10)
            events.append("set" if seconds is not None else "clear")
            if seconds is not None and reported.is_set():
                next_mark.set()
            super().mark_busy(seconds)

    class _Reported(file_copies.FileWrites):
        def __init__(
            self,
            ref: HarnessSandboxRef,
            pool: file_copies.FileCopyPool,
            files: SessionFiles,
            writes: Sequence[file_copies.FileWrite],
            superseded: Callable[[], bool],
            on_end: Callable[
                [Sequence[file_copies.FileWrite], file_copies.CopyFailure | None],
                None,
            ],
        ) -> None:
            def end(
                ended: Sequence[file_copies.FileWrite],
                failure: file_copies.CopyFailure | None,
            ) -> None:
                reported.set()
                on_end(ended, failure)

            super().__init__(ref, pool, files, writes, superseded, end)

    _wrap(monkeypatch, sandbox, _Recorded)
    monkeypatch.setattr(file_copies, "FileWrites", _Reported)
    tool = LibraryPrepareMaterializeTool(_turn(user, calling))

    items = _items(_copy(tool, [{"file_id": first}, {"file_id": second}]))
    assert [item["status"] for item in items] == ["written", "written"]
    before_second = events[: events.index(f"write {second_path}")]
    assert [event for event in before_second if event in ("set", "clear")][-1] == "set"


@pytest.mark.usefixtures("sandbox")
def test_the_same_file_twice_in_one_call_is_written_once(
    db_session: Session,
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
) -> None:
    source, calling = chats
    file_id = _publish(source, "report.csv", b"a,b\n")
    path = _landed(file_id, "report.csv")
    tool = LibraryPrepareMaterializeTool(_turn(user, calling))

    items = _items(_copy(tool, [{"file_id": file_id}, {"file_id": file_id}]))
    assert [(item["status"], item["path"]) for item in items] == [
        ("written", path),
        ("cached", path),
    ]
    assert node.agent.write_paths.count(path) == 1
    assert _vm_file(node, _ref(db_session, user, calling), path) == b"a,b\n"


@pytest.mark.usefixtures("sandbox")
def test_pod_shutdown_fails_the_later_items_without_a_listing(
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
    new_file_copy_pool: NewFileCopyPool,
) -> None:
    source, calling = chats
    new_file_copy_pool().shutdown()
    first = _publish(source, "first.txt", b"first")
    later = _publish(source, "later.txt", b"later")
    tool = LibraryPrepareMaterializeTool(_turn(user, calling))

    failed = _copy(
        tool, [{"file_id": first}, {"file_id": later, "relative_directory": "later"}]
    )
    shutdown = "the server is shutting down; try again"
    assert failed.content == (
        f"No file was copied:\n- The copy stopped: {shutdown}\n"
        f"- The copy failed: {shutdown}"
    )
    assert [path for path, _ in node.agent.list_requests] == [ARTIFACT_FILES_DIR]
    assert node.agent.write_paths == []


@pytest.mark.usefixtures("sandbox")
def test_parallel_copies_take_the_vms_write_slots(
    monkeypatch: pytest.MonkeyPatch,
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
    new_file_copy_pool: NewFileCopyPool,
) -> None:
    """Copies read and write in the chat file copies' slots: at most
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

    monkeypatch.setattr(file_copies, "get_default_file_store", CountingStore)
    turn = _turn(user, calling)
    results: list[ToolResult] = []
    threads = [
        threading.Thread(
            target=lambda file_id=file_id: results.append(
                _copy(LibraryPrepareMaterializeTool(turn), [{"file_id": file_id}])
            )
        )
        for file_id in file_ids
    ]
    for thread in threads:
        thread.start()
    try:
        # Every copy got past its checks; two hold the slots.
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
def test_a_queued_copy_waits_for_its_slot_until_pod_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    user: User,
    chats: tuple[UUID, UUID],
    new_file_copy_pool: NewFileCopyPool,
) -> None:
    """A copy queued behind copies that hold both write slots waits past its
    own write timeout. Pod shutdown, which drops the queued write, fails it
    and the copies that wait for theirs."""
    source, calling = chats
    pool = new_file_copy_pool()
    monkeypatch.setattr(file_copies, "COPY_BASE_SECONDS", 0.3)
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

    queued_writes: list[str] = []

    class SeenWrites(file_copies.FileWrites):
        def __init__(
            self,
            ref: HarnessSandboxRef,
            pool: file_copies.FileCopyPool,
            files: SessionFiles,
            writes: Sequence[file_copies.FileWrite],
            superseded: Callable[[], bool],
            on_end: Callable[
                [Sequence[file_copies.FileWrite], file_copies.CopyFailure | None],
                None,
            ],
        ) -> None:
            super().__init__(ref, pool, files, writes, superseded, on_end)
            queued_writes.extend(write.file_id for write in writes)

    monkeypatch.setattr(file_copies, "get_default_file_store", HoldingStore)
    monkeypatch.setattr(file_copies, "FileWrites", SeenWrites)
    turn = _turn(user, calling)
    results: dict[str, ToolResult] = {}

    def copy(file_id: str) -> None:
        results[file_id] = _copy(
            LibraryPrepareMaterializeTool(turn), [{"file_id": file_id}]
        )

    threads = [threading.Thread(target=copy, args=(file_id,)) for file_id in held]
    for thread in threads:
        thread.start()
    _wait_until(lambda: len(reading) == 2)
    queued_thread = threading.Thread(target=copy, args=(queued,))
    queued_thread.start()
    threads.append(queued_thread)
    try:
        _wait_until(lambda: queued in queued_writes)
        # Longer than twice the queued write's timeout.
        time.sleep(1.0)  # test-flakes: allow the wait must outlast a timeout
        assert queued not in results
        release.set()
        for thread in threads:
            thread.join(timeout=30)
        assert [results[file_id].is_error for file_id in (*held, queued)] == [False] * 3

        # Two new copies hold the slots, and pod shutdown drops the queued one.
        release.clear()
        reading.clear()
        held[:] = [_publish(source, f"again{index}.txt", b"x") for index in range(2)]
        threads = [threading.Thread(target=copy, args=(file_id,)) for file_id in held]
        for thread in threads:
            thread.start()
        _wait_until(lambda: len(reading) == 2)
        dropped_thread = threading.Thread(target=copy, args=(dropped,))
        dropped_thread.start()
        threads.append(dropped_thread)
        _wait_until(lambda: dropped in queued_writes)
        pool.shutdown()
        dropped_thread.join(timeout=10)
        assert results[dropped].content == (
            "No file was copied:\n- The copy stopped: the server is shutting "
            "down; try again"
        )
        # The held copies stop on the shutdown while their reads still wait.
        _wait_until(lambda: all(file_id in results for file_id in held))
        assert [results[file_id].content for file_id in held] == [
            results[dropped].content
        ] * 2
    finally:
        release.set()
        for thread in threads:
            thread.join(timeout=30)


@pytest.mark.usefixtures("sandbox")
def test_the_chat_file_copies_leave_copied_artifacts_alone(
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
    _copy(LibraryPrepareMaterializeTool(turn), [{"file_id": file_id}])
    ref = _ref(db_session, user, calling)
    # A project file that left the chat, which the cleanup deletes.
    _put_vm_file(node, ref, "attachments/project/x.txt", b"left")

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
def test_a_chat_lists_and_copies_files_published_in_other_chats(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    user: User,
) -> None:
    """Chat A publishes a report, a subagent of chat B publishes its notes,
    and chat C finds both with a query and a cursor, then copies the
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
        db_session,
        user.id,
        query="REPORT",
        chat_session_id=None,
        filters=LibraryListFilters(),
        sort="modified_at",
        sort_order="desc",
        limit=2,
        cursor=None,
    )
    assert found is not None
    [(notes, after), (report, _)] = found
    assert (notes.chat_id, notes.path) == (chat_b.chat_session_id, "report-notes.md")
    assert (report.chat_id, report.path, report.title) == (
        chat_a.chat_session_id,
        "out/report.csv",
        "Report",
    )
    cursor = base64.urlsafe_b64encode(ARTIFACT_CURSOR.dump_json(after)).decode()

    llm = ChatLLM(
        [
            tool_step(LibraryListTool.NAME, "list", {"query": "REPORT", "limit": 1}),
            tool_step(
                LibraryListTool.NAME,
                "next",
                {"query": "REPORT", "limit": 1, "cursor": cursor},
            ),
            tool_step(
                LibraryPrepareMaterializeTool.NAME,
                "copy",
                {"items": [{"file_id": report.file_id}]},
            ),
            Delta(content="Done."),
        ]
    )
    parts = chat_c.send(llm)

    listed = json.loads(last_tool_text(llm, "list"))
    assert [entry["file_id"] for entry in listed["files"]] == [notes.file_id]
    assert listed["next_cursor"] == cursor
    following = json.loads(last_tool_text(llm, "next"))
    assert [entry["file_id"] for entry in following["files"]] == [report.file_id]
    assert following["next_cursor"] is None
    [copied] = json.loads(last_tool_text(llm, "copy"))["items"]
    path = _landed(report.file_id, "report.csv")
    assert copied["path"] == path
    assert _vm_file(node, chat_c.ref(db_session), path) == b"a,b\n1,2\n"

    live = _card_packets(parts)
    assert [
        obj.display_name for obj in live if isinstance(obj, packets.CustomToolStart)
    ] == [
        LibraryListTool.display_name,
        LibraryListTool.display_name,
        LibraryPrepareMaterializeTool.display_name,
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
                "matches = await tool_search('copy a published file')\n"
                "print([match['name'] for match in matches])\n"
                "r = await tools.library__prepare_materialize(\n"
                f"    items=[{{'file_id': '{file_id}'}}]\n"
                ")\n"
                "print(r['items'][0]['path'], r['items'][0]['status'])\n",
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
        "\n  - library: Find the files that you published in this chat and the "
        "user's other chats, and copy them into this chat.\n" in description
    )
    assert "library__prepare_materialize" not in description
    text = last_tool_text(llm, "code")
    assert "'library__prepare_materialize'" in text
    path = _landed(file_id, "report.csv")
    assert f"{path} written" in text
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

        assert {PublishFilesTool.NAME, LibraryListTool.NAME} <= offered(owned)
        assert not {PublishFilesTool.NAME, LibraryListTool.NAME} & offered(ownerless)
    finally:
        db_session.rollback()
        db_session.execute(delete(ChatSession).where(ChatSession.id == ownerless))
        db_session.commit()
