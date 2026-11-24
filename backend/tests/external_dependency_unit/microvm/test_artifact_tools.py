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
from fastapi import Request
from pydantic import BaseModel, JsonValue
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from onyx.agents.models import RunStatus
from onyx.agents.tools import ToolInvocation
from onyx.cache.interface import CacheBackend
from onyx.chat import process_message
from onyx.chat.execution import chat_turn_work
from onyx.chat.process_message import handle_stream_message_objects
from onyx.configs.constants import DEFAULT_PERSONA_ID, MessageType
from onyx.db import chat as chat_db
from onyx.db.chat import (
    create_chat_session,
    get_chat_published_files,
    get_user_published_files,
    save_chat_artifact,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ApprovalDecision
from onyx.db.models import (
    ApprovalRequest,
    ChatArtifact,
    ChatArtifactVersion,
    ChatMessage,
    ChatSession,
    FileRecord,
    User,
)
from onyx.db.sandbox import get_or_create_sandbox
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.integrations.models import ApprovalMode
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.interfaces import LLMConfig
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
from onyx.server.features.action_policies.models import ApprovalChoice
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
from onyx.server.query_and_chat.chat_backend import (
    decide_approval,
    delete_chat_session_by_id,
    fetch_chat_file,
)
from onyx.server.query_and_chat.models import (
    ChatApprovalDecisionRequest,
    SendMessageRequest,
)
from onyx.tools.constants import SPAWN_AGENT_TOOL_NAME
from onyx.tools.models import ToolContext, ToolOptions
from onyx.tools.tool_implementations.sandbox import artifact_operations, file_copies
from onyx.tools.tool_implementations.sandbox.file_copies import TurnFileCopies
from onyx.tools.tool_implementations.sandbox.models import (
    ARTIFACT_CURSOR,
    ARTIFACTS_CHAT_TITLE_MAX_CHARS,
    ARTIFACTS_PATH_MAX_CHARS,
    DELETE_OF_A_VERSION,
    ArtifactAtPath,
    ArtifactById,
    ArtifactList,
    ArtifactNotFound,
    LibraryFileTarget,
    LibraryListFilters,
    ManageResults,
    MaterializedItems,
    PublishedFile,
    PublishFileArgument,
    VmChatFile,
    artifact_url,
)
from onyx.tools.tool_implementations.sandbox.sandbox_tools import (
    ArtifactTool,
    LibraryCreateLibraryFileTool,
    LibraryListTool,
    LibraryManageLibraryTool,
    LibraryPrepareMaterializeTool,
    LibraryReplaceLibraryFileTool,
    SandboxTool,
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
    _stops,
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
    """The file ID of a file that a publish saved in the chat."""
    return save_chat_artifact(
        data,
        name=name,
        mime_type="text/plain",
        target=ArtifactAtPath(
            chat_session_id=chat_session_id,
            path=f"{session_workspace(chat_session_id)}/{name}",
        ),
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
    tool: SandboxTool,
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
            "url": artifact_url(artifact_id, 1),
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

    monkeypatch.setattr(artifact_operations, "_MATERIALIZE_NAME_TRIES", 3)
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
            "url": artifact_url(_artifact_id(second), 1),
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
                    LibraryCreateLibraryFileTool.NAME,
                    "publish",
                    {"file": "out/report.csv", "title": "Report"},
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
                        name=LibraryCreateLibraryFileTool.NAME,
                        arguments={"file": "report-notes.md"},
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
        f"\n  - library: {LibraryListTool.CODE_MODE_NAMESPACE_DESCRIPTION}\n"
        in description
    )
    assert "library__prepare_materialize" not in description
    text = last_tool_text(llm, "code")
    assert "'library__prepare_materialize'" in text
    path = _landed(file_id, "report.csv")
    assert f"{path} written" in text
    assert _vm_file(node, chat.ref(db_session), path) == b"a,b\n"


@pytest.mark.usefixtures("sandbox", "node")
def test_a_program_finds_the_publish_tool_with_tool_search(
    db_session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
    llm = ChatLLM(
        [
            code_step(
                "code",
                "matches = await tool_search('publish a file for the user')\n"
                "print([match['name'] for match in matches][:3])\n",
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
    assert "library__create_library_file" not in description
    # It is among the three best matches.
    assert "'library__create_library_file'" in last_tool_text(llm, "code")


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

        assert {LibraryCreateLibraryFileTool.NAME, LibraryListTool.NAME} <= offered(
            owned
        )
        assert not {LibraryCreateLibraryFileTool.NAME, LibraryListTool.NAME} & offered(
            ownerless
        )
    finally:
        db_session.rollback()
        db_session.execute(delete(ChatSession).where(ChatSession.id == ownerless))
        db_session.commit()


# Both tool families, the library tools and the artifact tool of Claude
# models, run the same operations, so each case runs through both.


class _ClaudeLLM(ChatLLM):
    """A scripted Claude model: its turns get the artifact tool."""

    @property
    def config(self) -> LLMConfig:
        return super().config.model_copy(
            update={"model_provider": "anthropic", "model_name": "claude-sonnet-4-5"}
        )


class _Family:
    """How one tool family calls each operation."""

    def llm(self, steps: list[Delta]) -> ChatLLM:
        raise NotImplementedError

    def publish(
        self, call_id: str, paths: list[str], title: str | None = None
    ) -> Delta:
        raise NotImplementedError

    def list(
        self, call_id: str, category: str | None, limit: int, cursor: str | None
    ) -> Delta:
        raise NotImplementedError

    def read(
        self,
        call_id: str,
        artifact_id: UUID,
        version: int | None,
        out_dir: str,
    ) -> Delta:
        raise NotImplementedError

    def replace(
        self, call_id: str, artifact_id: UUID, file: str, seen: int, force: bool
    ) -> Delta:
        """A new version of the artifact from `file`, by a caller that last
        saw version `seen`; `force` adds it whatever the newest version."""
        raise NotImplementedError

    def delete(
        self, call_id: str, artifact_id: UUID, version: int | None = None
    ) -> Delta:
        """A delete of the artifact, by the url or the target of its
        version `version` when there is one."""
        raise NotImplementedError


class _Library(_Family):
    def llm(self, steps: list[Delta]) -> ChatLLM:
        return ChatLLM(steps)

    def publish(
        self, call_id: str, paths: list[str], title: str | None = None
    ) -> Delta:
        return tool_step(
            LibraryCreateLibraryFileTool.NAME,
            call_id,
            {"file": paths[0], "title": title} if len(paths) == 1 else {"files": paths},
        )

    def list(
        self, call_id: str, category: str | None, limit: int, cursor: str | None
    ) -> Delta:
        return tool_step(
            LibraryListTool.NAME,
            call_id,
            {"filters": {"category": category}, "limit": limit, "cursor": cursor},
        )

    def read(
        self,
        call_id: str,
        artifact_id: UUID,
        version: int | None,
        out_dir: str,
    ) -> Delta:
        return tool_step(
            LibraryPrepareMaterializeTool.NAME,
            call_id,
            {
                "items": [
                    {"library_file_id": str(artifact_id), "version_number": version}
                ],
                "destination": {"directory": out_dir},
            },
        )

    def replace(
        self, call_id: str, artifact_id: UUID, file: str, seen: int, force: bool
    ) -> Delta:
        return tool_step(
            LibraryReplaceLibraryFileTool.NAME,
            call_id,
            {
                "library_file_id": str(artifact_id),
                "file": file,
                "expected_current_version": None if force else seen,
            },
        )

    def delete(
        self, call_id: str, artifact_id: UUID, version: int | None = None
    ) -> Delta:
        target: dict[str, JsonValue] = {"library_file_id": str(artifact_id)}
        if version is not None:
            target["version_number"] = version
        return tool_step(
            LibraryManageLibraryTool.NAME,
            call_id,
            {"operations": [{"operation": "delete", "target": target}]},
        )


class _Artifact(_Family):
    def llm(self, steps: list[Delta]) -> ChatLLM:
        return _ClaudeLLM(steps)

    def publish(
        self, call_id: str, paths: list[str], title: str | None = None
    ) -> Delta:
        return tool_step(
            ArtifactTool.NAME,
            call_id,
            {"file_path": paths[0], "title": title}
            if len(paths) == 1
            else {"file_paths": paths},
        )

    def list(
        self, call_id: str, category: str | None, limit: int, cursor: str | None
    ) -> Delta:
        return tool_step(
            ArtifactTool.NAME,
            call_id,
            {"action": "list", "type": category, "limit": limit, "after": cursor},
        )

    def read(
        self,
        call_id: str,
        artifact_id: UUID,
        version: int | None,
        out_dir: str,
    ) -> Delta:
        url = (
            f"/app/artifacts/{artifact_id}"
            if version is None
            else artifact_url(artifact_id, version)
        )
        return tool_step(
            ArtifactTool.NAME,
            call_id,
            {"action": "read", "url": url, "out_dir": out_dir},
        )

    def replace(
        self, call_id: str, artifact_id: UUID, file: str, seen: int, force: bool
    ) -> Delta:
        return tool_step(
            ArtifactTool.NAME,
            call_id,
            {
                "file_path": file,
                "url": artifact_url(artifact_id, seen),
                "force": force or None,
            },
        )

    def delete(
        self, call_id: str, artifact_id: UUID, version: int | None = None
    ) -> Delta:
        return tool_step(
            ArtifactTool.NAME,
            call_id,
            {
                "action": "delete",
                "url": f"/app/artifacts/{artifact_id}"
                if version is None
                else artifact_url(artifact_id, version),
            },
        )


@pytest.fixture(params=[_Library(), _Artifact()], ids=["library", "artifact"])
def family(request: pytest.FixtureRequest) -> _Family:
    return request.param


def _publish_packets(parts: Sequence[object]) -> list[packets.PacketObj]:
    """The publish cards of streamed parts or replayed packets, and their
    section ends."""
    objects = [
        part.obj if isinstance(part, packets.Packet) else part
        for part in parts
        if isinstance(part, (packets.Packet, BaseModel))
    ]
    card = (packets.PublishFilesStart, packets.PublishFilesEnd)
    return [
        obj
        for index, obj in enumerate(objects)
        if isinstance(obj, card)
        or (
            isinstance(obj, packets.SectionEnd)
            and index > 0
            and isinstance(objects[index - 1], card)
        )
    ]


@pytest.mark.usefixtures("node")
def test_a_publish_gives_the_same_card_rows_and_message_files_in_both_families(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    user: User,
    family: _Family,
) -> None:
    chat = _sandbox_chat(db_session, user, monkeypatch, "Report")
    ref = chat.ref(db_session)
    for path, data in (("out/report.csv", b"a,b\n"), ("a.md", b"a"), ("b.md", b"b")):
        sandbox.write_file(ref, path, data)
    llm = family.llm(
        [
            family.publish("one", ["out/report.csv"], "Report"),
            family.publish("two", ["a.md", "b.md"]),
            Delta(content="Done."),
        ]
    )
    parts = chat.send(llm)

    live = _publish_packets(parts)
    (
        first_start,
        first_end,
        first_section_end,
        second_start,
        second_end,
        second_section_end,
    ) = live
    assert first_start == packets.PublishFilesStart(
        files=[PublishFileArgument(path="out/report.csv", title="Report")]
    )
    assert second_start == packets.PublishFilesStart(
        files=[PublishFileArgument(path="a.md"), PublishFileArgument(path="b.md")]
    )
    assert first_section_end == second_section_end == packets.SectionEnd()
    assert isinstance(first_end, packets.PublishFilesEnd)
    assert isinstance(second_end, packets.PublishFilesEnd)
    assert first_end.error is None and second_end.error is None
    # Each card lists only the files that its own call published.
    assert [(file.name, file.title, file.version) for file in first_end.files] == [
        ("report.csv", "Report", 1)
    ]
    assert [(file.name, file.title, file.version) for file in second_end.files] == [
        ("a.md", None, 1),
        ("b.md", None, 1),
    ]
    published = [*first_end.files, *second_end.files]
    [replayed] = chat.replayed(db_session)
    assert _publish_packets(replayed) == live
    db_session.expire_all()
    for call_id, file in zip(("one", "two", "two"), published, strict=True):
        assert file.artifact_id is not None and file.version is not None
        artifact = db_session.get_one(ChatArtifact, file.artifact_id)
        assert artifact.chat_session_id == chat.chat_session_id
        # Each result links the version that it published.
        assert artifact_url(file.artifact_id, file.version) in last_tool_text(
            llm, call_id
        )
    [answer] = db_session.scalars(
        select(ChatMessage).where(
            ChatMessage.chat_session_id == chat.chat_session_id,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
    )
    assert [descriptor["id"] for descriptor in answer.files or []] == [
        file.file_id for file in published
    ]


@pytest.mark.usefixtures("node")
def test_a_failed_publish_publishes_nothing_and_ends_its_card_with_the_error(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    user: User,
    family: _Family,
) -> None:
    chat = _sandbox_chat(db_session, user, monkeypatch, "Report")
    sandbox.write_file(chat.ref(db_session), "a.md", b"a")
    parts = chat.send(
        family.llm(
            [family.publish("publish", ["a.md", "missing.md"]), Delta(content="Done.")]
        )
    )

    start, end, section_end = _publish_packets(parts)
    assert start == packets.PublishFilesStart(
        files=[PublishFileArgument(path="a.md"), PublishFileArgument(path="missing.md")]
    )
    assert isinstance(end, packets.PublishFilesEnd)
    assert end.files == [] and end.error is not None and "missing.md" in end.error
    assert section_end == packets.SectionEnd()
    assert not db_session.scalars(
        select(ChatArtifact).where(ChatArtifact.chat_session_id == chat.chat_session_id)
    ).all()


@pytest.mark.usefixtures("node", "sandbox")
def test_a_list_filters_pages_and_links_in_both_families(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    family: _Family,
) -> None:
    source = _chat(db_session, user, "Reports")
    for name in ("report.pdf", "data.csv", "deck.pptx"):
        _publish(source, name, name.encode())
    chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
    llm = family.llm(
        [
            family.list("sheets", "sheet", 10, None),
            family.list("first", None, 2, None),
            Delta(content="Done."),
        ]
    )
    parts = chat.send(llm)

    sheets = ArtifactList.model_validate_json(last_tool_text(llm, "sheets"))
    assert [entry.file_name for entry in sheets.files] == ["data.csv"]
    [entry] = sheets.files
    assert entry.url == artifact_url(entry.library_file_id, 1)
    first = ArtifactList.model_validate_json(last_tool_text(llm, "first"))
    assert [entry.file_name for entry in first.files] == ["deck.pptx", "data.csv"]
    assert first.next_cursor is not None

    llm = family.llm(
        [
            family.list("rest", None, 2, first.next_cursor),
            family.list("bad", None, 2, "junk"),
            Delta(content="Done."),
        ]
    )
    parts = chat.send(llm)
    rest = ArtifactList.model_validate_json(last_tool_text(llm, "rest"))
    assert [entry.file_name for entry in rest.files] == ["report.pdf"]
    assert rest.next_cursor is None
    assert last_tool_text(llm, "bad").startswith("The cursor is not a next_cursor")
    # A failed list ends on the generic card, never a publish card.
    assert _publish_packets(parts) == []
    calls: dict[tuple[int, int], list[packets.PacketObj]] = {}
    for part in parts:
        if isinstance(part, packets.Packet):
            calls.setdefault(
                (part.placement.turn_index, part.placement.tab_index), []
            ).append(part.obj)
    [bad] = [
        objects
        for objects in calls.values()
        if any(
            isinstance(obj, packets.CustomToolArgs) and "junk" in str(obj.tool_args)
            for obj in objects
        )
    ]
    assert isinstance(bad[0], packets.CustomToolStart)
    assert bad[-1] == packets.SectionEnd()


@pytest.mark.usefixtures("sandbox")
def test_a_read_copies_the_newest_or_a_named_version_in_both_families(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    user: User,
    family: _Family,
) -> None:
    source = _chat(db_session, user, "Reports")
    _publish(source, "report.md", b"first")
    newest = _publish(source, "report.md", b"second")
    artifact_id = _artifact_id(newest)
    chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
    llm = family.llm(
        [
            family.read("newest", artifact_id, None, "work"),
            family.read("old", artifact_id, 1, "work"),
            Delta(content="Done."),
        ]
    )
    chat.send(llm)

    [copied] = MaterializedItems.model_validate_json(
        last_tool_text(llm, "newest")
    ).items
    assert (copied.path, copied.version_number, copied.url) == (
        "work/report.md",
        2,
        artifact_url(artifact_id, 2),
    )
    [old] = MaterializedItems.model_validate_json(last_tool_text(llm, "old")).items
    assert (old.path, old.version_number) == ("work/report (1).md", 1)
    ref = chat.ref(db_session)
    assert _vm_file(node, ref, "work/report.md") == b"second"
    assert _vm_file(node, ref, "work/report (1).md") == b"first"


@pytest.mark.usefixtures("sandbox", "node")
def test_a_read_of_a_missing_version_names_the_version_in_both_families(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    family: _Family,
) -> None:
    source = _chat(db_session, user, "Reports")
    artifact_id = _artifact_id(_publish(source, "report.md", b"first"))
    chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
    llm = family.llm(
        [family.read("missing", artifact_id, 9, "work"), Delta(content="Done.")]
    )
    chat.send(llm)

    assert last_tool_text(llm, "missing") == (
        f"No file was copied:\n- No version 9 of {artifact_id}; its newest is 1"
    )


@pytest.mark.usefixtures("sandbox")
def test_an_artifact_read_takes_urls_and_file_ids_in_path_and_paths(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    user: User,
) -> None:
    source = _chat(db_session, user, "Reports")
    first = _publish(source, "report.md", b"first")
    _publish(source, "report.md", b"second")
    notes = _publish(source, "notes.md", b"notes")
    artifact_id = _artifact_id(first)
    chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
    llm = _ClaudeLLM(
        [
            tool_step(
                ArtifactTool.NAME,
                "read",
                {
                    "action": "read",
                    "path": artifact_url(artifact_id, 1),
                    "paths": [f"/app/artifacts/{artifact_id}", notes],
                    "out_dir": "work",
                },
            ),
            Delta(content="Done."),
        ]
    )
    chat.send(llm)

    items = MaterializedItems.model_validate_json(last_tool_text(llm, "read")).items
    assert [(item.path, item.version_number) for item in items] == [
        ("work/report.md", 1),
        ("work/report (1).md", 2),
        ("work/notes.md", 1),
    ]
    ref = chat.ref(db_session)
    assert _vm_file(node, ref, "work/report.md") == b"first"
    assert _vm_file(node, ref, "work/report (1).md") == b"second"
    assert _vm_file(node, ref, "work/notes.md") == b"notes"


@pytest.mark.usefixtures("node")
def test_a_claude_program_finds_the_artifact_tool_and_publishes_with_it(
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
    sandbox.write_file(chat.ref(db_session), "out/a.md", b"# A\n")
    llm = _ClaudeLLM(
        [
            code_step(
                "code",
                "matches = await tool_search('publish a file')\n"
                "print([match['name'] for match in matches])\n"
                "r = await tools.artifact__artifact(file_path='out/a.md')\n"
                "print(r['files'][0]['url'])\n",
            ),
            Delta(content="Done."),
        ]
    )
    parts = chat.send(llm, code_mode=True)

    [description] = [
        tool["function"]["description"]
        for tool in llm.requests[0]["tools"]
        if tool["function"]["name"] == "execute_code"
    ]
    assert "\n  - artifact: Give files from the VM to the user" in description
    assert "artifact__artifact" not in description
    db_session.expire_all()
    [artifact] = db_session.scalars(
        select(ChatArtifact).where(ChatArtifact.chat_session_id == chat.chat_session_id)
    ).all()
    text = last_tool_text(llm, "code")
    assert "'artifact__artifact'" in text
    assert artifact_url(artifact.id, 1) in text
    # The program's publish shows the publish card.
    assert any(
        isinstance(part, packets.Packet)
        and isinstance(part.obj, packets.PublishFilesEnd)
        and [file.artifact_id for file in part.obj.files] == [artifact.id]
        for part in parts
    )


@pytest.mark.usefixtures("node")
def test_a_replace_from_another_chat_versions_its_artifact_in_both_families(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    user: User,
    family: _Family,
) -> None:
    """Chat B adds version 2 to chat A's report: the artifact keeps its name,
    path and title, A's panel shows the new version, B's card and message
    files hold it, and a hard delete of B keeps it while one of A deletes
    it."""
    chat_a = _chat(db_session, user, "Reports")
    first = save_chat_artifact(
        b"v1",
        name="report.md",
        mime_type="text/markdown",
        title="Report",
        thumbnail=None,
        target=ArtifactAtPath(
            chat_session_id=chat_a, path=f"{session_workspace(chat_a)}/report.md"
        ),
    )
    assert first.artifact_id is not None
    chat_b = _sandbox_chat(db_session, user, monkeypatch, "Today")
    # The extension matches in any case.
    sandbox.write_file(chat_b.ref(db_session), "draft-v2.MD", b"v2")
    llm = family.llm(
        [
            family.replace("replace", first.artifact_id, "draft-v2.MD", 1, False),
            Delta(content="Done."),
        ]
    )
    parts = chat_b.send(llm)

    start, end, section_end = _publish_packets(parts)
    assert start == packets.PublishFilesStart(
        files=[PublishFileArgument(path="draft-v2.MD")]
    )
    assert isinstance(end, packets.PublishFilesEnd) and end.error is None
    [second] = end.files
    # The live packet names the owning chat, A, not the calling chat.
    assert (
        second.artifact_id,
        second.version,
        second.chat_id,
        second.name,
        second.title,
        second.path,
    ) == (first.artifact_id, 2, chat_a, "report.md", "Report", first.path)
    assert section_end == packets.SectionEnd()
    [replayed] = chat_b.replayed(db_session)
    assert _publish_packets(replayed) == [start, end, section_end]
    [_, replayed_end, _] = _publish_packets(replayed)
    assert isinstance(replayed_end, packets.PublishFilesEnd)
    assert replayed_end.files[0].chat_id == chat_a
    assert artifact_url(first.artifact_id, 2) in last_tool_text(llm, "replace")
    # Chat A's panel lists the new version; chat B's answer holds it.
    db_session.expire_all()
    [listed] = get_chat_published_files(chat_a, db_session)
    assert (listed.file_id, listed.version) == (second.file_id, 2)
    [answer] = db_session.scalars(
        select(ChatMessage).where(
            ChatMessage.chat_session_id == chat_b.chat_session_id,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
    )
    assert [descriptor["id"] for descriptor in answer.files or []] == [second.file_id]

    store = get_default_file_store()
    delete_chat_session_by_id(
        chat_b.chat_session_id, hard_delete=True, user=user, db_session=db_session
    )
    assert store.read_file(second.file_id).read() == b"v2"
    db_session.expire_all()
    [listed] = get_chat_published_files(chat_a, db_session)
    assert listed.file_id == second.file_id
    delete_chat_session_by_id(
        chat_a, hard_delete=True, user=user, db_session=db_session
    )
    db_session.expire_all()
    assert db_session.get(FileRecord, second.file_id) is None


@pytest.mark.usefixtures("node")
def test_a_stale_replace_writes_nothing_and_force_adds_the_version(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    user: User,
    family: _Family,
) -> None:
    source = _chat(db_session, user, "Reports")
    _publish(source, "report.md", b"v1")
    newest = _publish(source, "report.md", b"v2")
    artifact_id = _artifact_id(newest)
    chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
    sandbox.write_file(chat.ref(db_session), "mine.md", b"mine")
    records = db_session.scalars(select(func.count(FileRecord.file_id))).one()
    llm = family.llm(
        [
            family.replace("stale", artifact_id, "mine.md", 1, False),
            family.replace("forced", artifact_id, "mine.md", 1, True),
            Delta(content="Done."),
        ]
    )
    parts = chat.send(llm)

    assert last_tool_text(llm, "stale").startswith("Current version is 2;")
    db_session.expire_all()
    versions = db_session.scalars(
        select(ChatArtifactVersion.version)
        .where(ChatArtifactVersion.artifact_id == artifact_id)
        .order_by(ChatArtifactVersion.version)
    ).all()
    assert versions == [1, 2, 3]
    # The stale call left no file record; the forced one added its file.
    assert (
        db_session.scalars(select(func.count(FileRecord.file_id))).one() == records + 1
    )
    [stale_end, forced_end] = [
        obj
        for obj in _publish_packets(parts)
        if isinstance(obj, packets.PublishFilesEnd)
    ]
    assert stale_end.files == [] and stale_end.error is not None
    assert [file.version for file in forced_end.files] == [3]


@pytest.mark.usefixtures("node")
def test_a_replace_reads_the_type_from_the_normalized_path(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    user: User,
    family: _Family,
) -> None:
    """A trailing slash or dot names the same file, so the type check passes
    and the file publishes."""
    artifact_id = _artifact_id(
        _publish(_chat(db_session, user, "Reports"), "report.md", b"v1")
    )
    chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
    sandbox.write_file(chat.ref(db_session), "draft.md", b"v2")
    llm = family.llm(
        [
            family.replace("slash", artifact_id, "draft.md/", 1, False),
            family.replace("dot", artifact_id, "./draft.md/.", 2, False),
            Delta(content="Done."),
        ]
    )
    parts = chat.send(llm)

    assert [
        (obj.error, [file.version for file in obj.files])
        for obj in _publish_packets(parts)
        if isinstance(obj, packets.PublishFilesEnd)
    ] == [(None, [2]), (None, [3])]


@pytest.mark.usefixtures("sandbox")
def test_a_replace_of_a_file_that_is_not_yours_never_starts_the_vm(
    db_session: Session,
    node: RunningFakeAgent,
    user: User,
    make_test_user: MakeTestUser,
) -> None:
    stranger = make_test_user("artifact_tools_replace_stranger")
    theirs = _artifact_id(_publish(_chat(db_session, stranger), "a.md", b"a"))
    deleted_chat = _chat(db_session, user)
    in_deleted = _artifact_id(_publish(deleted_chat, "b.md", b"b"))
    db_session.execute(
        update(ChatSession).where(ChatSession.id == deleted_chat).values(deleted=True)
    )
    db_session.commit()
    turn = _turn(user, _chat(db_session, user))
    tool = LibraryReplaceLibraryFileTool(turn)
    for artifact_id in (theirs, in_deleted, uuid4()):
        result = _call(tool, {"library_file_id": str(artifact_id), "file": "x.md"})
        assert result.is_error
        assert result.content == f"No published file {artifact_id} in your chats"

    # A file of another type is refused too, in both families.
    mine = _publish(_chat(db_session, user), "report.md", b"v1")
    refusal = (
        "draft.txt is not a file of the type of report.md; a new version keeps "
        "the file's name and type, so publish it as a new file instead"
    )
    other_type = _call(
        tool, {"library_file_id": str(_artifact_id(mine)), "file": "out/draft.txt"}
    )
    assert other_type.content == refusal
    other_type = _call(
        ArtifactTool(turn),
        {"file_path": "out/draft.txt", "url": artifact_url(_artifact_id(mine), 1)},
    )
    assert other_type.content == refusal
    assert node.agent.create_calls == 0


def _requests(db_session: Session, chat_session_id: UUID) -> list[ApprovalRequest]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.chat_session_id == chat_session_id)
            .order_by(ApprovalRequest.created_at)
        )
    )


def _decide(
    db_session: Session, chat: SandboxChat, choice: ApprovalChoice
) -> ApprovalRequest:
    """Decide the chat's open request, and wait until its resumed response
    completes."""
    [request] = [
        request
        for request in _requests(db_session, chat.chat_session_id)
        if request.decision is None
    ]
    with get_session_with_current_tenant() as session:
        decide_approval(
            approval_id=request.id,
            body=ChatApprovalDecisionRequest(decision=choice),
            request=Request({"type": "http", "headers": []}),
            user=chat.user,
            db_session=session,
        )

    def completed() -> bool:
        with get_session_with_current_tenant() as session:
            status = session.get_one(ChatMessage, request.chat_message_id)
        return status.response_status == RunStatus.COMPLETE

    _wait_until(completed)
    assert chat_turn_work.wait_idle(timeout=30)
    return request


def _report(chat_session_id: UUID, data: bytes) -> PublishedFile:
    return save_chat_artifact(
        data,
        name="report.pdf",
        mime_type="application/pdf",
        title=None,
        thumbnail=b"thumb-" + data,
        target=ArtifactAtPath(
            chat_session_id=chat_session_id,
            path=f"{session_workspace(chat_session_id)}/report.pdf",
        ),
    )


@pytest.mark.usefixtures("node", "sandbox")
def test_a_delete_from_another_chat_asks_then_removes_every_version(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    family: _Family,
) -> None:
    """The card names the file, its version count and its chat; after the
    approval, the versions, thumbnails and rows are gone, the owning chat's
    panel and the list leave the file out, and its download is not found."""
    chat_a = _chat(db_session, user, "Q3 planning")
    first = _report(chat_a, b"v1")
    second = _report(chat_a, b"v2")
    assert first.artifact_id is not None
    artifact_id = first.artifact_id
    chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
    llm = family.llm([family.delete("delete", artifact_id), Delta(content="Done.")])
    # The resumed response runs after the send returns.
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: llm
    )
    assert _stops(chat.send(llm)) == [packets.AWAITING_USER]

    [request] = _requests(db_session, chat.chat_session_id)
    assert (request.display_name, request.arguments) == (
        "Delete report.pdf",
        {"Delete": ["report.pdf (2 versions) from chat \u201cQ3 planning\u201d"]},
    )
    assert (request.integration_id, request.action_id) == (
        None,
        "onyx:artifacts.delete",
    )
    assert db_session.get(ChatArtifact, artifact_id) is not None

    _decide(db_session, chat, ApprovalChoice.APPROVE_ONCE)
    [result] = ManageResults.model_validate_json(last_tool_text(llm, "delete")).results
    assert (result.ok, result.file_name, result.deleted_versions) == (
        True,
        "report.pdf",
        2,
    )
    db_session.expire_all()
    file_ids = [
        first.file_id,
        second.file_id,
        first.thumbnail_file_id,
        second.thumbnail_file_id,
    ]
    assert not db_session.scalars(
        select(FileRecord.file_id).where(FileRecord.file_id.in_(file_ids))
    ).all()
    assert db_session.get(ChatArtifact, artifact_id) is None
    assert get_chat_published_files(chat_a, db_session) == []
    with pytest.raises(OnyxError):
        fetch_chat_file(
            second.file_id,
            Request({"type": "http", "headers": []}),
            parsed=False,
            user=user,
            db_session=db_session,
        )


@pytest.mark.usefixtures("node", "sandbox")
def test_a_delete_of_a_file_that_is_not_yours_asks_with_only_its_id(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    make_test_user: MakeTestUser,
    family: _Family,
) -> None:
    """The card shows the target as given and nothing of the other user's
    file; the approved call finds no file and deletes nothing."""
    stranger = make_test_user("artifact_tools_delete_stranger")
    theirs = _artifact_id(_publish(_chat(db_session, stranger), "a.md", b"a"))
    chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
    llm = family.llm([family.delete("theirs", theirs), Delta(content="Done.")])
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: llm
    )
    assert _stops(chat.send(llm)) == [packets.AWAITING_USER]

    [request] = _requests(db_session, chat.chat_session_id)
    assert (request.display_name, request.arguments) == (
        f"Delete {theirs}",
        {"Delete": [f"{theirs} (not found yet)"]},
    )
    _decide(db_session, chat, ApprovalChoice.APPROVE_ONCE)
    assert f"No published file {theirs} in your chats" in last_tool_text(llm, "theirs")
    assert db_session.get(ChatArtifact, theirs) is not None


@pytest.mark.usefixtures("node", "sandbox")
def test_a_chat_grant_from_one_family_covers_a_delete_of_the_other(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
) -> None:
    """Both families ask under one action key, so "Approve for this chat"
    survives a switch of model."""
    source = _chat(db_session, user, "Reports")
    first = _artifact_id(_publish(source, "a.md", b"a"))
    second = _artifact_id(_publish(source, "b.md", b"b"))
    chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
    library_llm = _Library().llm(
        [_Library().delete("one", first), Delta(content="Done.")]
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: library_llm
    )
    assert _stops(chat.send(library_llm)) == [packets.AWAITING_USER]
    _decide(db_session, chat, ApprovalChoice.APPROVE_SESSION)

    artifact_llm = _Artifact().llm(
        [_Artifact().delete("two", second), Delta(content="Done.")]
    )
    assert _stops(chat.send(artifact_llm)) != [packets.AWAITING_USER]

    assert '"ok":true' in last_tool_text(artifact_llm, "two")
    db_session.expire_all()
    assert db_session.get(ChatArtifact, first) is None
    assert db_session.get(ChatArtifact, second) is None
    [request] = _requests(db_session, chat.chat_session_id)
    assert request.decision is ApprovalDecision.APPROVED


@pytest.mark.usefixtures("node", "sandbox")
def test_a_turn_that_runs_without_asking_deletes_without_a_card(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    family: _Family,
) -> None:
    artifact_id = _artifact_id(_publish(_chat(db_session, user), "a.md", b"a"))
    chat_session_id = _chat(db_session, user, "Eval")
    llm = family.llm([family.delete("delete", artifact_id), Delta(content="Done.")])
    monkeypatch.setattr("onyx.chat.agent.CODE_MODE_ENABLED", False)
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: llm
    )
    parts = list(
        handle_stream_message_objects(
            new_msg_req=SendMessageRequest(
                message="Clean up.", chat_session_id=chat_session_id, stream=True
            ),
            user=user,
            approval_mode=ApprovalMode.RUN_WITHOUT_ASKING,
        )
    )

    assert _stops(parts) != [packets.AWAITING_USER]
    assert '"ok":true' in last_tool_text(llm, "delete")
    assert _requests(db_session, chat_session_id) == []
    db_session.expire_all()
    assert db_session.get(ChatArtifact, artifact_id) is None


def _waits_on_a_lock() -> bool:
    with get_session_with_current_tenant() as session:
        return bool(
            session.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' AND query ILIKE '%chat_artifact%'"
                )
            )
        )


@pytest.mark.usefixtures("sandbox")
def test_a_publish_during_a_delete_makes_a_new_file(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, user: User
) -> None:
    """The delete holds the artifact's row lock, so a publish of its path
    waits and then makes a new artifact: no link of the deleted file opens
    the new content."""
    source = _chat(db_session, user, "Reports")
    artifact_id = _artifact_id(_publish(source, "a.md", b"v1"))
    published: list[str] = []
    publishes: list[threading.Thread] = []
    published_before_the_delete: list[bool] = []
    real_delete_files = chat_db.delete_chat_artifact_files

    def publish_meanwhile(versions: Sequence[tuple[str, str | None]]) -> None:
        # The publish starts while the versions still exist, so only the
        # delete's row lock can keep it from adding a version to the artifact.
        if not publishes:
            publish = threading.Thread(
                target=lambda: published.append(_publish(source, "a.md", b"v2"))
            )
            publish.start()
            publishes.append(publish)
            _wait_until(lambda: bool(published) or _waits_on_a_lock())
            published_before_the_delete.append(bool(published))
        real_delete_files(versions)

    monkeypatch.setattr(chat_db, "delete_chat_artifact_files", publish_meanwhile)
    try:
        result = _call(
            LibraryManageLibraryTool(_turn(user, _chat(db_session, user))),
            {
                "operations": [
                    {
                        "operation": "delete",
                        "target": {"library_file_id": str(artifact_id)},
                    }
                ]
            },
        )
    finally:
        for publish in publishes:
            publish.join(timeout=30)

    assert published_before_the_delete == [False], "the publish did not wait"
    assert not result.is_error, result.content
    db_session.expire_all()
    assert db_session.get(ChatArtifact, artifact_id) is None
    [file_id] = published
    version = db_session.scalars(
        select(ChatArtifactVersion).where(ChatArtifactVersion.file_id == file_id)
    ).one()
    assert version.artifact_id != artifact_id
    assert version.version == 1


@pytest.mark.usefixtures("sandbox")
def test_a_stop_after_the_first_delete_keeps_the_next_file(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, user: User
) -> None:
    """A Stop ends the call between operations, as in materialize: the
    started delete ends, and the next one does not start."""
    source = _chat(db_session, user, "Reports")
    first = _artifact_id(_publish(source, "a.md", b"a"))
    second = _artifact_id(_publish(source, "b.md", b"b"))
    signal = CancellationSignal()
    real_delete = artifact_operations.delete_chat_artifact

    def delete_then_stop(artifact_id: UUID) -> int:
        deleted = real_delete(artifact_id)
        signal.cancel("user")
        return deleted

    monkeypatch.setattr(artifact_operations, "delete_chat_artifact", delete_then_stop)
    with pytest.raises(AgentCancelled):
        _call(
            LibraryManageLibraryTool(_turn(user, _chat(db_session, user))),
            {
                "operations": [
                    {"operation": "delete", "target": {"library_file_id": str(first)}},
                    {"operation": "delete", "target": {"library_file_id": str(second)}},
                ]
            },
            signal,
        )

    db_session.expire_all()
    assert db_session.get(ChatArtifact, first) is None
    assert db_session.get(ChatArtifact, second) is not None


def test_the_delete_card_tells_apart_same_name_files_by_their_folders(
    db_session: Session, user: User
) -> None:
    source = _chat(db_session, user, "Reports")
    artifact_ids = [
        save_chat_artifact(
            b"report",
            name="report.md",
            mime_type="text/plain",
            target=ArtifactAtPath(
                chat_session_id=source,
                path=f"{session_workspace(source)}/{folder}/report.md",
            ),
            title=None,
            thumbnail=None,
        ).artifact_id
        for folder in ("q3", "q4")
    ]

    targets = [
        LibraryFileTarget(library_file_id=artifact_id)
        for artifact_id in artifact_ids
        if artifact_id is not None
    ]

    both = artifact_operations.delete_approval_details(user.id, targets)
    one = artifact_operations.delete_approval_details(user.id, targets[:1])

    assert both is not None and one is not None
    assert both.payload == {
        "Delete": [
            "q3/report.md (1 version) from chat \u201cReports\u201d",
            "q4/report.md (1 version) from chat \u201cReports\u201d",
        ]
    }
    assert one.display_name == "Delete q3/report.md"


def test_a_delete_of_a_file_that_is_not_found_yet_still_asks(
    db_session: Session, user: User
) -> None:
    """Another chat can still publish the version or the file, so the card
    names the artifact of a missing version and shows a target that finds
    nothing as given."""
    artifact_id = _artifact_id(_publish(_chat(db_session, user), "a.md", b"v1"))
    missing = uuid4()

    card = artifact_operations.delete_approval_details(
        user.id,
        [
            LibraryFileTarget(library_file_id=artifact_id, version_number=2),
            LibraryFileTarget(library_file_id=missing),
        ],
    )

    assert card is not None
    assert card.display_name == "Delete 2 published files"
    assert card.payload == {
        "Delete": [
            "a.md (version 2 not published yet; the delete removes the file and every version)",
            f"{missing} (not found yet)",
        ]
    }


def test_the_delete_card_cuts_a_long_path_and_chat_title_as_the_list_does(
    db_session: Session, user: User
) -> None:
    title = "T" * (ARTIFACTS_CHAT_TITLE_MAX_CHARS + 50)
    source = _chat(db_session, user, title)
    folder = "/".join(f"folder{index:02d}" for index in range(40))
    artifact_id = save_chat_artifact(
        b"report",
        name="report.md",
        mime_type="text/plain",
        target=ArtifactAtPath(
            chat_session_id=source,
            path=f"{session_workspace(source)}/{folder}/report.md",
        ),
        title=None,
        thumbnail=None,
    ).artifact_id
    assert artifact_id is not None
    path = f"{folder}/report.md"
    assert len(path) > ARTIFACTS_PATH_MAX_CHARS
    shown = "\u2026" + path[-(ARTIFACTS_PATH_MAX_CHARS - 1) :]

    card = artifact_operations.delete_approval_details(
        user.id, [LibraryFileTarget(library_file_id=artifact_id)]
    )

    assert card is not None
    assert card.display_name == f"Delete {shown}"
    assert card.payload == {
        "Delete": [
            f"{shown} (1 version) from chat "
            f"\u201c{title[:ARTIFACTS_CHAT_TITLE_MAX_CHARS]}\u201d"
        ]
    }


def test_a_failed_delete_keeps_the_newest_version_and_its_number(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, user: User
) -> None:
    """The versions go oldest first and the first failure stops the
    delete, so the newest version stays, and a later publish never takes
    the number of a deleted version."""
    source = _chat(db_session, user, "Reports")
    first = _publish(source, "a.md", b"v1")
    artifact_id = _artifact_id(first)
    _publish(source, "a.md", b"v2")
    store_type = type(get_default_file_store())
    real_delete_file = store_type.delete_file

    def fail_on_the_first_version(
        store: FileStore, file_id: str, error_on_missing: bool = True
    ) -> None:
        if file_id == first:
            raise RuntimeError("The store is down")
        real_delete_file(store, file_id, error_on_missing)

    monkeypatch.setattr(store_type, "delete_file", fail_on_the_first_version)
    with pytest.raises(RuntimeError):
        chat_db.delete_chat_artifact(artifact_id)
    monkeypatch.undo()

    third = _publish(source, "a.md", b"v3")
    assert _artifact_id(third) == artifact_id
    assert sorted(
        db_session.scalars(
            select(ChatArtifactVersion.version).where(
                ChatArtifactVersion.artifact_id == artifact_id
            )
        )
    ) == [1, 2, 3]


def test_a_delete_that_stopped_after_its_files_never_lends_its_id_to_a_publish(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, user: User
) -> None:
    """A delete that removed every file but not the artifact row leaves a
    row without a version. A publish at its path makes a new artifact, so
    the deleted artifact's links never open the new file, and a save by
    its ID finds nothing."""
    source = _chat(db_session, user, "Reports")
    artifact_id = _artifact_id(_publish(source, "a.md", b"v1"))
    real_delete_files = chat_db.delete_chat_artifact_files

    def delete_then_stop(versions: Sequence[tuple[str, str | None]]) -> None:
        real_delete_files(versions)
        raise RuntimeError("The pod stopped")

    monkeypatch.setattr(chat_db, "delete_chat_artifact_files", delete_then_stop)
    with pytest.raises(RuntimeError):
        chat_db.delete_chat_artifact(artifact_id)
    monkeypatch.undo()
    db_session.expire_all()
    assert db_session.get(ChatArtifact, artifact_id) is not None

    with pytest.raises(ArtifactNotFound):
        save_chat_artifact(
            b"by id",
            name="a.md",
            mime_type="text/plain",
            title=None,
            thumbnail=None,
            target=ArtifactById(artifact_id=artifact_id),
        )
    republished = _publish(source, "a.md", b"new")
    new_id = _artifact_id(republished)
    assert new_id != artifact_id
    db_session.expire_all()
    assert db_session.get(ChatArtifact, artifact_id) is None
    assert db_session.scalars(
        select(ChatArtifactVersion.version).where(
            ChatArtifactVersion.artifact_id == new_id
        )
    ).all() == [1]


@pytest.mark.usefixtures("node", "sandbox")
def test_a_delete_by_the_newest_version_asks_then_removes_the_file(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    family: _Family,
) -> None:
    """Every url that the tools return names a version; the newest one's
    deletes the whole file."""
    source = _chat(db_session, user, "Reports")
    artifact_id = _artifact_id(_publish(source, "a.md", b"v1"))
    _publish(source, "a.md", b"v2")
    chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
    llm = family.llm(
        [family.delete("delete", artifact_id, version=2), Delta(content="Done.")]
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: llm
    )
    assert _stops(chat.send(llm)) == [packets.AWAITING_USER]

    _decide(db_session, chat, ApprovalChoice.APPROVE_ONCE)
    [result] = ManageResults.model_validate_json(last_tool_text(llm, "delete")).results
    assert (result.ok, result.deleted_versions) == (True, 2)
    db_session.expire_all()
    assert db_session.get(ChatArtifact, artifact_id) is None


@pytest.mark.usefixtures("node", "sandbox")
def test_a_delete_by_an_older_version_asks_and_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    family: _Family,
) -> None:
    source = _chat(db_session, user, "Reports")
    artifact_id = _artifact_id(_publish(source, "a.md", b"v1"))
    _publish(source, "a.md", b"v2")
    chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
    llm = family.llm(
        [family.delete("delete", artifact_id, version=1), Delta(content="Done.")]
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: llm
    )
    assert _stops(chat.send(llm)) == [packets.AWAITING_USER]

    [request] = _requests(db_session, chat.chat_session_id)
    assert (request.display_name, request.arguments) == (
        "Delete a.md",
        {
            "Delete": [
                "a.md version 1 (not its newest version, 2; the delete refuses it "
                "while it is not the newest)"
            ]
        },
    )
    _decide(db_session, chat, ApprovalChoice.APPROVE_ONCE)
    assert (
        f"Version 1 of a.md is not its newest, 2; {DELETE_OF_A_VERSION}"
        in last_tool_text(llm, "delete")
    )
    db_session.expire_all()
    assert db_session.get(ChatArtifact, artifact_id) is not None
