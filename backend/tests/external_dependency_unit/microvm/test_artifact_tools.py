"""library_list, library_prepare_materialize and library_search against
FirecrackerHarnessSandbox with a fake host agent, Postgres and the file
store, and for search also OpenSearch and the model server: where a copy
lands, the cache, the conflict policies, refusals that never start the VM,
item errors, Stop, the write slots and tries, the chat file cleanup, what a
search finds, filters, sorts and pages, and chat turns through the chat flow
(the generic card, live and replayed, and the code mode group `library`).
Then the operations of
both tool families, and the text tools library_read and library_find: lines,
pages, versions, matching, refusals, the cached text and the result limit."""

import base64
import json
import threading
import time
from collections.abc import Callable, Generator, Sequence
from datetime import datetime, timedelta, timezone
from io import BytesIO
from itertools import product
from typing import IO
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import openpyxl
import pytest
from fastapi import Request
from openpyxl.worksheet.worksheet import Worksheet
from pydantic import BaseModel, JsonValue
from reportlab.pdfgen import canvas
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from onyx.agents.models import RunStatus
from onyx.agents.tools import ToolInvocation
from onyx.background.celery.tasks.chat_artifact_indexing.tasks import (
    process_single_chat_artifact,
)
from onyx.cache.interface import CacheBackend
from onyx.chat import process_message
from onyx.chat.execution import chat_turn_work
from onyx.chat.process_message import handle_stream_message_objects
from onyx.configs.constants import DEFAULT_PERSONA_ID, FileOrigin, MessageType
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
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import build_opensearch_document_index
from onyx.error_handling.exceptions import OnyxError
from onyx.file_processing import extract_file_text
from onyx.file_store.constants import ARTIFACT_TEXT_MAX_FILE_BYTES
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.indexing.chat_artifact_index import delete_chat_artifacts_from_index
from onyx.integrations.models import ApprovalMode
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.model_capabilities import ToolFamily
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
from onyx.natural_language_processing.utils import HuggingFaceTokenizer, get_tokenizer
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
from onyx.tools.models import ToolCallException, ToolContext, ToolOptions
from onyx.tools.tool_implementations.code_mode.shapes import (
    CLAUDE_CODE_MODE,
    OPENAI_CODE_MODE,
)
from onyx.tools.tool_implementations.sandbox import (
    artifact_operations,
    file_copies,
)
from onyx.tools.tool_implementations.sandbox.file_copies import TurnFileCopies
from onyx.tools.tool_implementations.sandbox.models import (
    ARTIFACT_CURSOR,
    ARTIFACT_RESULT_MAX_CHARS,
    ARTIFACTS_CHAT_TITLE_MAX_CHARS,
    ARTIFACTS_PATH_MAX_CHARS,
    DELETE_OF_A_VERSION,
    LIBRARY_SEARCH_CHUNKS_PER_QUERY,
    ArtifactAtPath,
    ArtifactById,
    ArtifactList,
    ArtifactNotFound,
    ArtifactPublished,
    ArtifactsFound,
    ArtifactsRead,
    DeleteOperation,
    FileUri,
    FoundText,
    LibraryFileTarget,
    LibraryListFilters,
    LibrarySearchResult,
    ManageLibraryArguments,
    ManageResult,
    ManageResults,
    MaterializedItems,
    PublishedFile,
    PublishFileArgument,
    RenameOperation,
    RestoreVersionOperation,
    UpdateOperation,
    VmChatFile,
    artifact_url,
)
from onyx.tools.tool_implementations.sandbox.sandbox_tools import (
    ArtifactTool,
    LibraryCreateLibraryFileTool,
    LibraryFindTool,
    LibraryListTool,
    LibraryManageLibraryTool,
    LibraryPrepareMaterializeTool,
    LibraryReadTool,
    LibraryReplaceLibraryFileTool,
    LibrarySearchTool,
    SandboxTool,
)
from onyx.tools.tool_implementations.sandbox.shapes import SHELL_SHAPES
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
from tests.external_dependency_unit.chat.test_wait_agent import (
    ScriptedLLM as WaitAgentLLM,
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
        preview_pdf=None,
    ).file_id


def _artifact_id(file_id: str) -> UUID:
    with get_session_with_current_tenant() as db_session:
        return db_session.scalars(
            select(ChatArtifactVersion.artifact_id).where(
                ChatArtifactVersion.file_id == file_id
            )
        ).one()


def _turn(
    owner: User, chat_session_id: UUID, family: ToolFamily = ToolFamily.OPENAI
) -> SandboxTurn:
    return SandboxTurn(
        tenant_id=TENANT_ID,
        user_id=owner.id,
        chat_session_id=chat_session_id,
        vm_chat_files=[],
        copy_vm_chat_files=False,
        shell=SHELL_SHAPES[family],
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
        "a shell command elsewhere",
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
                _copy(
                    LibraryPrepareMaterializeTool(turn),
                    [{"file_id": file_id}],
                )
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
            LibraryPrepareMaterializeTool(turn),
            [{"file_id": file_id}],
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
    _copy(
        LibraryPrepareMaterializeTool(turn),
        [{"file_id": file_id}],
    )
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
    and chat C finds both with a cursor, then copies the report. The generic
    cards stream as the reload replays them."""
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
                    arguments={"task_name": "helper", "message": "Task helper"},
                )
            ]
        )

    monkeypatch.setattr("onyx.chat.agent.CODE_MODE_ENABLED", False)
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona",
        lambda **_kwargs: WaitAgentLLM(generate),
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
            tool_step(LibraryListTool.NAME, "list", {"limit": 1}),
            tool_step(LibraryListTool.NAME, "next", {"limit": 1, "cursor": cursor}),
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
                OPENAI_CODE_MODE,
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
        if tool["function"]["name"] == "exec"
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
                OPENAI_CODE_MODE,
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
        if tool["function"]["name"] == OPENAI_CODE_MODE.run_name
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

    def search(self, call_id: str, query: str, limit: int, cursor: str | None) -> Delta:
        raise NotImplementedError

    def replace(
        self,
        call_id: str,
        artifact_id: UUID,
        file: str,
        seen: int,
        force: bool,
        reason: str | None = None,
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

    def rename(self, call_id: str, artifact_id: UUID, name: str) -> Delta:
        raise NotImplementedError

    def restore(
        self, call_id: str, artifact_id: UUID, version: int, reason: str | None
    ) -> Delta:
        raise NotImplementedError

    def update(
        self,
        call_id: str,
        artifact_id: UUID,
        file_id: str,
        seen: int,
        reason: str | None = None,
    ) -> Delta:
        """A copy of the published file `file_id` as the artifact's next
        version, by a caller that last saw version `seen`."""
        raise NotImplementedError

    def read_text(
        self,
        call_id: str,
        file: UUID | str,
        version: int | None = None,
        start_line: int | None = None,
        max_lines: int | None = None,
    ) -> Delta:
        """The numbered lines of `file`: an artifact (at `version`, by
        default its newest) or a version's file ID."""
        raise NotImplementedError

    def find(
        self,
        call_id: str,
        file: UUID | str,
        text: str,
        offset: int | None = None,
        limit: int | None = None,
    ) -> Delta:
        """The lines of `file` that contain `text`, in any case."""
        raise NotImplementedError


def _without_none(values: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {key: value for key, value in values.items() if value is not None}


def _library_reference(file: UUID | str, version: int | None) -> dict[str, JsonValue]:
    if isinstance(file, str):
        return {"file_id": file}
    return _without_none({"library_file_id": str(file), "version_number": version})


def _artifact_tool_reference(
    file: UUID | str, version: int | None
) -> dict[str, JsonValue]:
    if isinstance(file, str):
        return {"path": file}
    return {
        "url": f"/app/artifacts/{file}"
        if version is None
        else artifact_url(file, version)
    }


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

    def search(self, call_id: str, query: str, limit: int, cursor: str | None) -> Delta:
        return tool_step(
            LibrarySearchTool.NAME,
            call_id,
            {"search_query": [{"q": query}], "top_k": limit, "cursor": cursor},
        )

    def replace(
        self,
        call_id: str,
        artifact_id: UUID,
        file: str,
        seen: int,
        force: bool,
        reason: str | None = None,
    ) -> Delta:
        return tool_step(
            LibraryReplaceLibraryFileTool.NAME,
            call_id,
            {
                "library_file_id": str(artifact_id),
                "file": file,
                "expected_current_version": None if force else seen,
                "version_reason": reason,
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

    def rename(self, call_id: str, artifact_id: UUID, name: str) -> Delta:
        return tool_step(
            LibraryManageLibraryTool.NAME,
            call_id,
            {
                "operations": [
                    {
                        "operation": "rename",
                        "target": {"library_file_id": str(artifact_id)},
                        "new_name": name,
                    }
                ]
            },
        )

    def restore(
        self, call_id: str, artifact_id: UUID, version: int, reason: str | None
    ) -> Delta:
        return tool_step(
            LibraryManageLibraryTool.NAME,
            call_id,
            {
                "operations": [
                    {
                        "operation": "restore_version",
                        "library_file_id": str(artifact_id),
                        "version_number": version,
                        "version_reason": reason,
                    }
                ]
            },
        )

    def update(
        self,
        call_id: str,
        artifact_id: UUID,
        file_id: str,
        seen: int,
        reason: str | None = None,
    ) -> Delta:
        return tool_step(
            LibraryManageLibraryTool.NAME,
            call_id,
            {
                "operations": [
                    {
                        "operation": "update",
                        "library_file_id": str(artifact_id),
                        "file_uri": {"file_id": file_id},
                        "expected_current_version": seen,
                        "version_reason": reason,
                    }
                ]
            },
        )

    def read_text(
        self,
        call_id: str,
        file: UUID | str,
        version: int | None = None,
        start_line: int | None = None,
        max_lines: int | None = None,
    ) -> Delta:
        return tool_step(
            LibraryReadTool.NAME,
            call_id,
            {
                "read": [
                    _library_reference(file, version)
                    | _without_none({"start_line": start_line, "max_lines": max_lines})
                ]
            },
        )

    def find(
        self,
        call_id: str,
        file: UUID | str,
        text: str,
        offset: int | None = None,
        limit: int | None = None,
    ) -> Delta:
        return tool_step(
            LibraryFindTool.NAME,
            call_id,
            {
                "find": [
                    _library_reference(file, None)
                    | _without_none(
                        {"pattern": text, "match_offset": offset, "max_matches": limit}
                    )
                ]
            },
        )


class _Artifact(_Family):
    def llm(self, steps: list[Delta]) -> ChatLLM:
        return ChatLLM(steps, family=ToolFamily.CLAUDE)

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

    def search(self, call_id: str, query: str, limit: int, cursor: str | None) -> Delta:
        return tool_step(
            ArtifactTool.NAME,
            call_id,
            {"action": "list", "query": query, "limit": limit, "after": cursor},
        )

    def replace(
        self,
        call_id: str,
        artifact_id: UUID,
        file: str,
        seen: int,
        force: bool,
        reason: str | None = None,
    ) -> Delta:
        return tool_step(
            ArtifactTool.NAME,
            call_id,
            {
                "file_path": file,
                "url": artifact_url(artifact_id, seen),
                "force": force or None,
                "label": reason,
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

    def rename(self, call_id: str, artifact_id: UUID, name: str) -> Delta:
        return tool_step(
            ArtifactTool.NAME,
            call_id,
            {"action": "rename", "url": artifact_url(artifact_id, 1), "name": name},
        )

    def restore(
        self, call_id: str, artifact_id: UUID, version: int, reason: str | None
    ) -> Delta:
        return tool_step(
            ArtifactTool.NAME,
            call_id,
            {
                "action": "restore",
                "url": artifact_url(artifact_id, version),
                "label": reason,
            },
        )

    def update(
        self,
        call_id: str,
        artifact_id: UUID,
        file_id: str,
        seen: int,
        reason: str | None = None,
    ) -> Delta:
        return tool_step(
            ArtifactTool.NAME,
            call_id,
            {"url": artifact_url(artifact_id, seen), "path": file_id, "label": reason},
        )

    def read_text(
        self,
        call_id: str,
        file: UUID | str,
        version: int | None = None,
        start_line: int | None = None,
        max_lines: int | None = None,
    ) -> Delta:
        return tool_step(
            ArtifactTool.NAME,
            call_id,
            {"action": "read", "offset": start_line, "limit": max_lines}
            | _artifact_tool_reference(file, version),
        )

    def find(
        self,
        call_id: str,
        file: UUID | str,
        text: str,
        offset: int | None = None,
        limit: int | None = None,
    ) -> Delta:
        return tool_step(
            ArtifactTool.NAME,
            call_id,
            {"action": "read", "query": text, "offset": offset, "limit": limit}
            | _artifact_tool_reference(file, None),
        )


_LIBRARY_CONFLICT = (
    "Current version is 2, not the one you named; nothing changed. Copy "
    "the newest version, merge your change and try again, or omit "
    "expected_current_version"
)
_ARTIFACT_CONFLICT = (
    "Current version is 2; read it with out_dir, merge your change, then "
    "publish with the url from that result, or pass force:true"
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
    llm = ChatLLM(
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
        ],
        family=ToolFamily.CLAUDE,
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
    llm = ChatLLM(
        [
            code_step(
                CLAUDE_CODE_MODE,
                "code",
                "matches = await search_tools('publish a file')\n"
                "print([match['name'] for match in matches])\n"
                "r = await tools.artifact__artifact(file_path='out/a.md')\n"
                "print(r['files'][0]['url'])\n",
            ),
            Delta(content="Done."),
        ],
        family=ToolFamily.CLAUDE,
    )
    parts = chat.send(llm, code_mode=True)

    [description] = [
        tool["function"]["description"]
        for tool in llm.requests[0]["tools"]
        if tool["function"]["name"] == CLAUDE_CODE_MODE.run_name
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
        preview_pdf=None,
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
def test_a_replace_that_names_a_version_above_the_newest_says_they_differ(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    user: User,
) -> None:
    source = _chat(db_session, user, "Reports")
    _publish(source, "report.md", b"v1")
    artifact_id = _artifact_id(_publish(source, "report.md", b"v2"))
    chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
    sandbox.write_file(chat.ref(db_session), "mine.md", b"mine")
    family = _Library()
    llm = family.llm(
        [
            family.replace("ahead", artifact_id, "mine.md", 5, False),
            Delta(content="Done."),
        ]
    )
    chat.send(llm)

    message = last_tool_text(llm, "ahead")
    assert message.startswith("Current version is 2, not the one you named")
    assert "newer" not in message


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

    # Each family words a conflict one way, for replace and manage alike.
    assert last_tool_text(llm, "stale") == (
        _LIBRARY_CONFLICT if isinstance(family, _Library) else _ARTIFACT_CONFLICT
    )
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
    calling = _chat(db_session, user)
    tool = LibraryReplaceLibraryFileTool(_turn(user, calling))
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
        ArtifactTool(_turn(user, calling, ToolFamily.CLAUDE)),
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
        preview_pdf=None,
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

    def publish_meanwhile(
        file_ids: Sequence[str],
    ) -> None:
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
        real_delete_files(file_ids)

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
            preview_pdf=None,
        ).artifact_id
        for folder in ("q3", "q4")
    ]

    targets = [
        LibraryFileTarget(library_file_id=artifact_id)
        for artifact_id in artifact_ids
        if artifact_id is not None
    ]

    both = artifact_operations.delete_approval_details(
        user.id,
        ManageLibraryArguments(
            operations=[
                DeleteOperation(operation="delete", target=target) for target in targets
            ]
        ),
    )
    one = artifact_operations.delete_approval_details(
        user.id,
        ManageLibraryArguments(
            operations=[
                DeleteOperation(operation="delete", target=targets[0]),
                RenameOperation(operation="rename", target=targets[1], new_name="a.md"),
            ]
        ),
    )

    assert both is not None and one is not None
    assert both.payload == {
        "Delete": [
            "q3/report.md (1 version) from chat \u201cReports\u201d",
            "q4/report.md (1 version) from chat \u201cReports\u201d",
        ]
    }
    assert one.display_name == "Delete q3/report.md"
    assert one.payload == {
        "Delete": ["q3/report.md (1 version) from chat \u201cReports\u201d"],
        "Also in this call": [
            "rename q4/report.md from chat \u201cReports\u201d to a.md"
        ],
    }


def test_the_delete_card_names_the_chat_of_each_other_operations_file(
    db_session: Session, user: User
) -> None:
    deleted = _artifact_id(
        _publish(_chat(db_session, user, "Reports"), "notes.md", b"a")
    )
    renamed = _artifact_id(
        _publish(_chat(db_session, user, "Drafts"), "notes.md", b"b")
    )

    card = artifact_operations.delete_approval_details(
        user.id,
        ManageLibraryArguments(
            operations=[
                DeleteOperation(
                    operation="delete",
                    target=LibraryFileTarget(library_file_id=deleted),
                ),
                RenameOperation(
                    operation="rename",
                    target=LibraryFileTarget(library_file_id=renamed),
                    new_name="final.md",
                ),
            ]
        ),
    )

    assert card is not None
    assert card.payload == {
        "Delete": ["notes.md (1 version) from chat \u201cReports\u201d"],
        "Also in this call": [
            "rename notes.md from chat \u201cDrafts\u201d to final.md"
        ],
    }


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
        ManageLibraryArguments(
            operations=[
                DeleteOperation(
                    operation="delete",
                    target=LibraryFileTarget(
                        library_file_id=artifact_id, version_number=2
                    ),
                ),
                DeleteOperation(
                    operation="delete",
                    target=LibraryFileTarget(library_file_id=missing),
                ),
            ]
        ),
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
    artifact_ids = [
        save_chat_artifact(
            b"report",
            name=name,
            mime_type="text/plain",
            target=ArtifactAtPath(
                chat_session_id=source,
                path=f"{session_workspace(source)}/{folder}/{name}",
            ),
            title=None,
            thumbnail=None,
            preview_pdf=None,
        ).artifact_id
        for name in ("report.md", "notes.md")
    ]
    deleted, renamed = [
        LibraryFileTarget(library_file_id=artifact_id)
        for artifact_id in artifact_ids
        if artifact_id is not None
    ]
    shown = [
        "\u2026" + path[-(ARTIFACTS_PATH_MAX_CHARS - 1) :]
        for path in (f"{folder}/report.md", f"{folder}/notes.md")
    ]
    assert len(folder) > ARTIFACTS_PATH_MAX_CHARS

    card = artifact_operations.delete_approval_details(
        user.id,
        ManageLibraryArguments(
            operations=[
                DeleteOperation(operation="delete", target=deleted),
                RenameOperation(operation="rename", target=renamed, new_name="b.md"),
            ]
        ),
    )

    assert card is not None
    assert card.display_name == f"Delete {shown[0]}"
    assert card.payload == {
        "Delete": [
            f"{shown[0]} (1 version) from chat "
            f"\u201c{title[:ARTIFACTS_CHAT_TITLE_MAX_CHARS]}\u201d"
        ],
        "Also in this call": [
            f"rename {shown[1]} from chat "
            f"\u201c{title[:ARTIFACTS_CHAT_TITLE_MAX_CHARS]}\u201d to b.md"
        ],
    }


def test_a_delete_of_the_version_that_an_earlier_update_makes_asks(
    db_session: Session, user: User
) -> None:
    """The update makes version 2 of a.md, which the delete names: the card
    shows that version as not published yet, so the call never deletes
    unasked."""
    source = _chat(db_session, user, "Reports")
    artifact_id = _artifact_id(_publish(source, "a.md", b"v1"))
    other = _publish(source, "b.md", b"b")
    tool = LibraryManageLibraryTool(_turn(user, _chat(db_session, user)))

    card = tool.approval_details(
        {
            "operations": [
                {
                    "operation": "update",
                    "library_file_id": str(artifact_id),
                    "file_uri": {"file_id": other},
                },
                {
                    "operation": "delete",
                    "target": {
                        "library_file_id": str(artifact_id),
                        "version_number": 2,
                    },
                },
            ]
        }
    )

    assert card is not None
    assert card.payload == {
        "Delete": [
            "a.md (version 2 not published yet; the delete removes the file and every version)"
        ],
        "Also in this call": [
            f"add {other} as a new version of a.md from chat \u201cReports\u201d"
        ],
    }


def test_the_delete_card_names_the_new_name_of_a_restore_or_update(
    db_session: Session, user: User
) -> None:
    source = _chat(db_session, user, "Reports")
    deleted = _artifact_id(_publish(source, "gone.md", b"x"))
    artifact_id = _artifact_id(_publish(source, "a.md", b"v1"))
    other = _publish(source, "b.md", b"b")

    card = artifact_operations.delete_approval_details(
        user.id,
        ManageLibraryArguments(
            operations=[
                DeleteOperation(
                    operation="delete",
                    target=LibraryFileTarget(library_file_id=deleted),
                ),
                UpdateOperation(
                    operation="update",
                    library_file_id=artifact_id,
                    file_uri=FileUri(file_id=other),
                    file_name="c.md",
                ),
                RestoreVersionOperation(
                    operation="restore_version",
                    library_file_id=artifact_id,
                    version_number=1,
                    file_name="d.md",
                ),
            ]
        ),
    )

    assert card is not None and card.payload is not None
    assert card.payload["Also in this call"] == [
        f"add {other} as a new version of a.md from chat \u201cReports\u201d and rename it to c.md",
        "restore version 1 of a.md from chat \u201cReports\u201d and rename it to d.md",
    ]


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
        store: FileStore,
        file_id: str,
        error_on_missing: bool = True,
        db_session: Session | None = None,
    ) -> None:
        if file_id == first:
            raise RuntimeError("The store is down")
        real_delete_file(store, file_id, error_on_missing, db_session)

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

    def delete_then_stop(
        file_ids: Sequence[str],
    ) -> None:
        real_delete_files(file_ids)
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
            preview_pdf=None,
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


def test_a_rename_by_an_older_version_gives_the_newest_version(
    db_session: Session, user: User
) -> None:
    chat = _chat(db_session, user, "Notes")
    older = _publish(chat, "notes.md", b"v1")
    newest = _publish(chat, "notes.md", b"v2")
    artifact_id = _artifact_id(older)

    [result] = artifact_operations.manage(
        user.id,
        CancellationSignal(),
        ManageLibraryArguments.model_validate(
            {
                "operations": [
                    {
                        "operation": "rename",
                        "target": {"file_id": older},
                        "new_name": "summary.md",
                    }
                ]
            }
        ),
        conflict_message=str,
    ).results

    assert (
        result.ok,
        result.file_id,
        result.version_number,
        result.file_name,
        result.url,
    ) == (True, newest, 2, "summary.md", artifact_url(artifact_id, 2))


def test_a_rename_into_a_chat_deleted_during_it_writes_no_name(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, user: User
) -> None:
    """The artifact's chat is checked when the rename writes: a chat deleted
    after the lookup gets the not-found error, and the name stays."""
    chat = _chat(db_session, user, "Notes")
    artifact_id = _artifact_id(_publish(chat, "notes.md", b"v1"))
    real_rename = artifact_operations.rename_chat_artifact

    def delete_the_chat_then_rename(
        session: Session, renamed_id: UUID, name: str
    ) -> None:
        with get_session_with_current_tenant() as other:
            other.execute(
                update(ChatSession).where(ChatSession.id == chat).values(deleted=True)
            )
            other.commit()
        real_rename(session, renamed_id, name)

    monkeypatch.setattr(
        artifact_operations, "rename_chat_artifact", delete_the_chat_then_rename
    )
    with pytest.raises(ToolCallException) as refused:
        artifact_operations.manage(
            user.id,
            CancellationSignal(),
            ManageLibraryArguments.model_validate(
                {
                    "operations": [
                        {
                            "operation": "rename",
                            "target": {"library_file_id": str(artifact_id)},
                            "new_name": "summary.md",
                        }
                    ]
                }
            ),
            conflict_message=str,
        )

    assert f"No published file {artifact_id} in your chats" in (
        refused.value.llm_facing_message
    )
    db_session.expire_all()
    renamed = db_session.get(ChatArtifact, artifact_id)
    assert renamed is not None and renamed.name is None


def test_a_rename_keeps_the_extension_by_the_lists_last_dot_rule(
    db_session: Session, user: User
) -> None:
    """The list reads a file's type from the text after the last dot, so a
    rename that adds an extension to a file without one is refused."""
    artifact_id = _artifact_id(_publish(_chat(db_session, user), "README", b"r"))

    with pytest.raises(ToolCallException) as refused:
        artifact_operations.manage(
            user.id,
            CancellationSignal(),
            ManageLibraryArguments.model_validate(
                {
                    "operations": [
                        {
                            "operation": "rename",
                            "target": {"library_file_id": str(artifact_id)},
                            "new_name": ".csv",
                        }
                    ]
                }
            ),
            conflict_message=str,
        )

    assert "README, so its name must have no extension" in (
        refused.value.llm_facing_message
    )
    db_session.expire_all()
    assert db_session.get_one(ChatArtifact, artifact_id).name is None


def test_a_rename_needs_a_name_before_the_extension(
    db_session: Session, user: User
) -> None:
    """A name that is only an extension has no stem, so the rename is
    refused and the file keeps its name and type."""
    artifact_id = _artifact_id(_publish(_chat(db_session, user), "chart.png", b"p"))

    with pytest.raises(ToolCallException) as refused:
        artifact_operations.manage(
            user.id,
            CancellationSignal(),
            ManageLibraryArguments.model_validate(
                {
                    "operations": [
                        {
                            "operation": "rename",
                            "target": {"library_file_id": str(artifact_id)},
                            "new_name": ".png",
                        }
                    ]
                }
            ),
            conflict_message=str,
        )

    assert "'.png' has no name before its extension" in (
        refused.value.llm_facing_message
    )
    db_session.expire_all()
    assert db_session.get_one(ChatArtifact, artifact_id).name is None


def test_the_delete_card_lists_the_other_operations_of_the_call(
    db_session: Session, user: User
) -> None:
    """One approval covers the whole call, so the card shows what else it
    does."""
    chat = _chat(db_session, user, "Reports")
    doomed = _artifact_id(_publish(chat, "old.md", b"old"))
    kept = _artifact_id(_publish(chat, "draft.md", b"draft"))
    turn = MagicMock(spec=SandboxTurn)
    turn.user_id = user.id
    turn.shell = SHELL_SHAPES[ToolFamily.OPENAI]

    details = LibraryManageLibraryTool(turn).approval_details(
        {
            "operations": [
                {"operation": "delete", "target": {"library_file_id": str(doomed)}},
                {
                    "operation": "rename",
                    "target": {"library_file_id": str(kept)},
                    "new_name": "final.md",
                },
                {
                    "operation": "restore_version",
                    "library_file_id": str(kept),
                    "version_number": 1,
                },
            ]
        }
    )

    assert details is not None
    assert details.payload == {
        "Delete": ["old.md (1 version) from chat \u201cReports\u201d"],
        "Also in this call": [
            "rename draft.md from chat \u201cReports\u201d to final.md",
            "restore version 1 of draft.md from chat \u201cReports\u201d",
        ],
    }


def test_a_rename_names_the_file_everywhere_and_later_publishes_keep_it(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    user: User,
    family: _Family,
) -> None:
    """A rename shows in the list, the name sort, the panel, a copy's name
    and the card of a later publish of the same path, which keeps it. A
    name with another extension, or one that the VM would change, is
    refused."""
    _publish(_chat(db_session, user, "Other"), "b.md", b"b")
    chat = _sandbox_chat(db_session, user, monkeypatch, "Notes")
    ref = chat.ref(db_session)
    sandbox.write_file(ref, "notes.md", b"v1")
    llm = family.llm([family.publish("publish", ["notes.md"]), Delta(content="Done.")])
    chat.send(llm)
    [published] = ArtifactPublished.model_validate_json(
        last_tool_text(llm, "publish")
    ).files
    artifact_id = published.library_file_id
    published_at = db_session.get_one(ChatArtifact, artifact_id).updated_at
    sandbox.write_file(ref, "notes.md", b"v2")
    llm = family.llm(
        [
            family.rename("extension", artifact_id, "summary.txt"),
            family.rename("unsafe", artifact_id, "sum:mary.md"),
            family.rename("rename", artifact_id, "a-summary.md"),
            family.list("list", None, 10, None),
            family.read("read", artifact_id, None, "work"),
            family.publish("again", ["notes.md"]),
            Delta(content="Done."),
        ]
    )
    parts = chat.send(llm)

    assert "its name must end in '.md'" in last_tool_text(llm, "extension")
    assert "try 'sum_mary.md'" in last_tool_text(llm, "unsafe")
    assert '"file_name":"a-summary.md"' in last_tool_text(llm, "rename")
    listed = ArtifactList.model_validate_json(last_tool_text(llm, "list")).files
    assert [entry.file_name for entry in listed] == ["a-summary.md", "b.md"]
    # A rename bumps the artifact's modified_at, as a publish does.
    assert listed[0].modified_at > published_at
    [copied] = MaterializedItems.model_validate_json(last_tool_text(llm, "read")).items
    assert copied.path == "work/a-summary.md"
    assert _vm_file(node, ref, "work/a-summary.md") == b"v1"
    [again] = [
        obj
        for obj in _publish_packets(parts)
        if isinstance(obj, packets.PublishFilesEnd)
    ]
    assert [(file.name, file.version) for file in again.files] == [("a-summary.md", 2)]
    db_session.expire_all()
    [panel] = get_chat_published_files(chat.chat_session_id, db_session)
    assert (panel.name, panel.version) == ("a-summary.md", 2)
    page = get_user_published_files(
        db_session,
        user.id,
        chat_session_id=None,
        filters=LibraryListFilters(),
        sort="name",
        sort_order="asc",
        limit=10,
        cursor=None,
    )
    assert page is not None
    assert [entry.file_name for entry, _ in page] == ["a-summary.md", "b.md"]


@pytest.mark.usefixtures("node", "sandbox")
def test_a_delete_batched_with_a_rename_runs_both_only_after_approval(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, user: User
) -> None:
    """One request covers the whole call: its card lists the delete, and
    nothing runs before the approval."""
    source = _chat(db_session, user, "Reports")
    doomed = _artifact_id(_publish(source, "old.md", b"old"))
    kept = _artifact_id(_publish(source, "notes.md", b"notes"))
    chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
    llm = ChatLLM(
        [
            tool_step(
                LibraryManageLibraryTool.NAME,
                "manage",
                {
                    "operations": [
                        {
                            "operation": "rename",
                            "target": {"library_file_id": str(kept)},
                            "new_name": "summary.md",
                        },
                        {
                            "operation": "delete",
                            "target": {"library_file_id": str(doomed)},
                        },
                    ]
                },
            ),
            Delta(content="Done."),
        ]
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: llm
    )
    assert _stops(chat.send(llm)) == [packets.AWAITING_USER]

    [request] = _requests(db_session, chat.chat_session_id)
    assert request.display_name == "Delete old.md"
    db_session.expire_all()
    assert db_session.get_one(ChatArtifact, kept).name is None
    assert db_session.get(ChatArtifact, doomed) is not None

    _decide(db_session, chat, ApprovalChoice.APPROVE_ONCE)
    db_session.expire_all()
    assert db_session.get_one(ChatArtifact, kept).name == "summary.md"
    assert db_session.get(ChatArtifact, doomed) is None


def _versions(
    db_session: Session, artifact_id: UUID
) -> list[tuple[str, str | None, str | None, str | None]]:
    """Each version's file ID, thumbnail file ID, title and reason."""
    db_session.expire_all()
    return [
        (row.file_id, row.thumbnail_file_id, row.title, row.version_reason)
        for row in db_session.scalars(
            select(ChatArtifactVersion)
            .where(ChatArtifactVersion.artifact_id == artifact_id)
            .order_by(ChatArtifactVersion.version)
        )
    ]


@pytest.mark.usefixtures("node")
def test_a_restore_and_an_update_copy_a_version_and_its_thumbnail(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    user: User,
    family: _Family,
) -> None:
    """A restore copies version 1 of chat A's report, with its thumbnail and
    title, into new records as version 3; an update copies another
    artifact's file as version 4 with the newest title; a replace adds
    version 5. Each keeps its reason and the name, and shows the generic
    card."""
    chat_a = _chat(db_session, user, "Reports")
    path = f"{session_workspace(chat_a)}/report.md"
    first = save_chat_artifact(
        b"v1",
        name="report.md",
        mime_type="text/markdown",
        title="First",
        thumbnail=b"thumb-1",
        preview_pdf=None,
        target=ArtifactAtPath(
            chat_session_id=chat_a,
            path=path,
        ),
    )
    save_chat_artifact(
        b"v2",
        name="report.md",
        mime_type="text/markdown",
        title="Second",
        thumbnail=None,
        preview_pdf=None,
        target=ArtifactAtPath(
            chat_session_id=chat_a,
            path=path,
        ),
    )
    assert first.artifact_id is not None and first.thumbnail_file_id is not None
    artifact_id = first.artifact_id
    other = _publish(_chat(db_session, user, "Other"), "notes.md", b"other")
    chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
    sandbox.write_file(chat.ref(db_session), "merged.md", b"merged")
    llm = family.llm(
        [
            family.restore("restore", artifact_id, 1, "back to v1"),
            family.update("update", artifact_id, other, 3, "from notes"),
            family.replace("replace", artifact_id, "merged.md", 4, False, "merged"),
            Delta(content="Done."),
        ]
    )
    parts = chat.send(llm)

    [restored] = ManageResults.model_validate_json(
        last_tool_text(llm, "restore")
    ).results
    assert (restored.version_number, restored.url, restored.version_reason) == (
        3,
        artifact_url(artifact_id, 3),
        "back to v1",
    )
    [updated] = ManageResults.model_validate_json(last_tool_text(llm, "update")).results
    assert (updated.version_number, updated.file_name) == (4, "report.md")
    versions = _versions(db_session, artifact_id)
    assert [(title, reason) for _, _, title, reason in versions] == [
        ("First", None),
        ("Second", None),
        ("First", "back to v1"),
        ("First", "from notes"),
        ("First", "merged"),
    ]
    file_ids = [file_id for file_id, _, _, _ in versions]
    assert len(set(file_ids)) == 5
    assert file_ids[2:4] == [restored.file_id, updated.file_id]
    store = get_default_file_store()
    assert [store.read_file(file_id).read() for file_id in file_ids] == [
        b"v1",
        b"v2",
        b"v1",
        b"other",
        b"merged",
    ]
    thumbnail = versions[2][1]
    assert thumbnail is not None and thumbnail != first.thumbnail_file_id
    assert store.read_file(thumbnail).read() == b"thumb-1"
    assert versions[3][1] is None
    names = db_session.scalars(
        select(FileRecord.display_name).where(FileRecord.file_id.in_(file_ids[2:4]))
    ).all()
    assert names == ["report.md", "report.md"]
    # Only the replace shows the publish card.
    start, end, section_end = _publish_packets(parts)
    assert start == packets.PublishFilesStart(
        files=[PublishFileArgument(path="merged.md")]
    )
    assert isinstance(end, packets.PublishFilesEnd)
    assert [file.version for file in end.files] == [5]
    assert section_end == packets.SectionEnd()
    [panel] = get_chat_published_files(chat_a, db_session)
    assert panel.version == 5


def test_an_update_renames_only_with_its_own_file_name_and_keeps_the_type(
    db_session: Session, user: User
) -> None:
    """The operation's file_name renames the artifact within its extension;
    file_uri.file_name does not rename. The artifact tool's path takes a
    url too."""
    chat = _chat(db_session, user, "Reports")
    artifact_id = _artifact_id(_publish(chat, "report.md", b"v1"))
    source = _publish(chat, "notes.md", b"notes")

    def update(operation: dict[str, JsonValue]) -> ManageResult:
        [result] = artifact_operations.manage(
            user.id,
            CancellationSignal(),
            ManageLibraryArguments.model_validate(
                {
                    "operations": [
                        {
                            "operation": "update",
                            "library_file_id": str(artifact_id),
                            "file_uri": {"file_id": source},
                        }
                        | operation
                    ]
                }
            ),
            conflict_message=str,
        ).results
        return result

    renamed = update({"file_name": "final.md"})
    assert (renamed.ok, renamed.file_name, renamed.version_number) == (
        True,
        "final.md",
        2,
    )
    kept = update({"file_uri": {"file_id": source, "file_name": "ignored.md"}})
    assert (kept.ok, kept.file_name, kept.version_number) == (True, "final.md", 3)
    with pytest.raises(
        ToolCallException,
        match="The file's content is final.md, so its name must end in '.md'",
    ):
        update({"file_name": "final.csv"})

    result = _call(
        ArtifactTool(_turn(user, _chat(db_session, user), ToolFamily.CLAUDE)),
        {
            "url": artifact_url(artifact_id, 3),
            "path": artifact_url(_artifact_id(source), 1),
        },
    )
    [by_url] = ManageResults.model_validate_json(result.content).results
    assert (by_url.ok, by_url.file_name, by_url.version_number) == (
        True,
        "final.md",
        4,
    )
    newest_file_id = _versions(db_session, artifact_id)[-1][0]
    assert get_default_file_store().read_file(newest_file_id).read() == b"notes"


@pytest.mark.usefixtures("node", "sandbox")
def test_a_stale_or_foreign_update_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    make_test_user: MakeTestUser,
    family: _Family,
) -> None:
    source = _chat(db_session, user, "Reports")
    # A source with a thumbnail, whose copy a refused update must not keep.
    first = save_chat_artifact(
        b"v1",
        name="report.md",
        mime_type="text/markdown",
        title=None,
        thumbnail=b"thumb-1",
        preview_pdf=None,
        target=ArtifactAtPath(
            chat_session_id=source,
            path=f"{session_workspace(source)}/report.md",
        ),
    ).file_id
    _publish(source, "report.md", b"v2")
    artifact_id = _artifact_id(first)
    sheet = _publish(source, "data.csv", b"a,b\n")
    theirs = _publish(
        _chat(db_session, make_test_user("artifact_tools_update_stranger")),
        "a.md",
        b"a",
    )
    upload = get_default_file_store().save_file(
        content=BytesIO(b"upload"),
        display_name="upload.md",
        file_origin=FileOrigin.CHAT_UPLOAD,
        file_type="text/markdown",
    )
    try:
        chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
        before = _versions(db_session, artifact_id)
        records = db_session.scalars(select(func.count(FileRecord.file_id))).one()
        llm = family.llm(
            [
                family.update("stale", artifact_id, first, 1),
                family.update("theirs", artifact_id, theirs, 2),
                family.update("upload", artifact_id, upload, 2),
                family.update("sheet", artifact_id, sheet, 2),
                family.restore("missing", artifact_id, 9, None),
                Delta(content="Done."),
            ]
        )
        chat.send(llm)

        assert (
            _LIBRARY_CONFLICT if isinstance(family, _Library) else _ARTIFACT_CONFLICT
        ) in last_tool_text(llm, "stale")
        assert f"No published file {theirs} in your chats" in last_tool_text(
            llm, "theirs"
        )
        assert f"No published file {upload} in your chats" in last_tool_text(
            llm, "upload"
        )
        assert "data.csv is not a file of the type of report.md" in last_tool_text(
            llm, "sheet"
        )
        assert f"No version 9 of {artifact_id}; its newest is 2" in last_tool_text(
            llm, "missing"
        )
        assert _versions(db_session, artifact_id) == before
        # The stale copy left no file record or thumbnail behind.
        assert (
            db_session.scalars(select(func.count(FileRecord.file_id))).one() == records
        )
    finally:
        get_default_file_store().delete_file(upload)


# Reading and finding text: library_read, library_find and the artifact
# tool's read without out_dir


def _birds_pdf() -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    for line in ("Page one about herons.", "Page two about egrets."):
        pdf.drawString(72, 720, line)
        pdf.drawString(72, 700, "Birds wade.")
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


@pytest.mark.usefixtures("sandbox")
def test_a_read_pages_through_a_published_pdf_in_both_families(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    user: User,
    family: _Family,
) -> None:
    """Chat C reads a PDF that chat A published, one line and then the
    rest, without starting the VM; the generic cards stream as the reload
    replays them."""
    file_id = _publish(_chat(db_session, user, "Reports"), "birds.pdf", _birds_pdf())
    artifact_id = _artifact_id(file_id)
    chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
    llm = family.llm(
        [family.read_text("first", artifact_id, max_lines=1), Delta(content="Done.")]
    )
    parts = chat.send(llm)

    [first] = ArtifactsRead.model_validate_json(last_tool_text(llm, "first")).items
    assert (
        first.file.file_id,
        first.file.version_number,
        first.file.latest_version_number,
        first.total_pages,
    ) == (file_id, 1, 1, 2)
    assert first.text == "--- page 1 ---\n     1\tPage one about herons.\n"
    assert (first.start_line, first.end_line, first.next_start_line) == (1, 1, 2)

    llm = family.llm(
        [
            family.read_text("rest", artifact_id, start_line=first.next_start_line),
            Delta(content="Done."),
        ]
    )
    chat.send(llm)
    [rest] = ArtifactsRead.model_validate_json(last_tool_text(llm, "rest")).items
    assert rest.text.startswith("--- page 1 ---\n     2\tBirds wade.\n--- page 2 ---\n")
    assert "Page two about egrets." in rest.text
    assert (rest.end_line, rest.next_start_line) == (rest.total_lines, None)

    live = _card_packets(parts)
    assert any(isinstance(obj, packets.CustomToolStart) for obj in live)
    first_turn, _ = chat.replayed(db_session)
    assert _card_packets(first_turn) == live
    assert node.agent.create_calls == 0


@pytest.mark.usefixtures("sandbox", "node")
def test_a_page_read_that_the_limit_cuts_resumes_at_its_next_start_line(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, user: User
) -> None:
    file_id = _publish(_chat(db_session, user, "Reports"), "birds.pdf", _birds_pdf())
    tool = LibraryReadTool(_turn(user, _chat(db_session, user)))
    pages: dict[str, JsonValue] = {
        "file_id": file_id,
        "mode": "pages",
        "start_page": 1,
        "end_page": 2,
    }

    whole = _call(tool, {"read": [pages]}).content
    text = ArtifactsRead.model_validate_json(whole).items[0].text
    page_two = text[text.index("--- page 2 ---") :]
    # Room for page 1 only.
    monkeypatch.setattr(
        artifact_operations,
        "ARTIFACT_RESULT_MAX_CHARS",
        len(whole)
        + artifact_operations._ITEM_NUMBERS_CHARS
        - (len(json.dumps(page_two)) - 2)
        + 5,
    )
    [cut] = ArtifactsRead.model_validate_json(
        _call(tool, {"read": [pages]}).content
    ).items
    assert (cut.end_line, cut.next_start_line) == (2, 3)

    [rest] = ArtifactsRead.model_validate_json(
        _call(tool, {"read": [pages | {"start_line": cut.next_start_line}]}).content
    ).items
    assert rest.text == page_two
    assert (rest.start_line, rest.end_line, rest.next_start_line) == (3, 4, None)


@pytest.mark.usefixtures("sandbox", "node")
def test_a_whole_page_read_ends_and_refuses_a_start_line_outside_its_pages(
    db_session: Session, user: User
) -> None:
    file_id = _publish(_chat(db_session, user, "Reports"), "birds.pdf", _birds_pdf())
    tool = LibraryReadTool(_turn(user, _chat(db_session, user)))
    page_one: dict[str, JsonValue] = {"file_id": file_id, "mode": "pages"}

    [read] = ArtifactsRead.model_validate_json(
        _call(tool, {"read": [page_one]}).content
    ).items
    assert (read.start_line, read.end_line, read.total_lines) == (1, 2, 4)
    assert read.next_start_line is None

    outside = _call(tool, {"read": [page_one | {"start_line": 3}]})
    assert outside.is_error
    assert outside.content == (
        "start_line 3 is outside pages 1 to 1 of birds.pdf, lines 1 to 2"
    )


@pytest.mark.usefixtures("sandbox", "node")
def test_a_read_reaches_any_version_in_both_families(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    family: _Family,
) -> None:
    source = _chat(db_session, user, "Reports")
    old = _publish(source, "notes.md", b"first draft\n")
    _publish(source, "notes.md", b"second draft\nmore\n")
    artifact_id = _artifact_id(old)
    chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
    llm = family.llm(
        [
            family.read_text("old", artifact_id, version=1),
            family.read_text("newest", artifact_id),
            family.read_text("by_file_id", old),
            family.read_text("missing", artifact_id, version=7),
            Delta(content="Done."),
        ]
    )
    chat.send(llm)

    def read(call_id: str) -> tuple[int, int | None, str]:
        [item] = ArtifactsRead.model_validate_json(last_tool_text(llm, call_id)).items
        return item.file.version_number, item.file.latest_version_number, item.text

    assert read("old") == (1, 2, "     1\tfirst draft\n")
    assert read("newest") == (2, 2, "     1\tsecond draft\n     2\tmore\n")
    assert read("by_file_id") == (1, 2, "     1\tfirst draft\n")
    assert last_tool_text(llm, "missing") == (
        f"No version 7 of {artifact_id}; its newest is 2"
    )


@pytest.mark.usefixtures("sandbox", "node")
def test_a_find_matches_literal_text_in_any_case_and_pages_in_both_families(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    family: _Family,
) -> None:
    file_id = _publish(
        _chat(db_session, user, "Reports"),
        "log.txt",
        b"alpha\nBeta needle\ngamma\nNEEDLE delta\nneedle.\n",
    )
    chat = _sandbox_chat(db_session, user, monkeypatch, "Today")
    llm = family.llm(
        [
            family.find("all", file_id, "needle"),
            family.find("page", file_id, "needle", offset=1, limit=1),
            family.find("literal", file_id, "needle."),
            Delta(content="Done."),
        ]
    )
    chat.send(llm)

    def found(call_id: str) -> tuple[list[int], int, int | None]:
        [item] = ArtifactsFound.model_validate_json(last_tool_text(llm, call_id)).items
        assert not item.timed_out
        return (
            [match.line for match in item.matches],
            item.total_matches_seen,
            item.next_match_offset,
        )

    assert found("all") == ([2, 4, 5], 3, None)
    assert found("page") == ([4], 3, 2)
    # Literal text: the dot matches only a dot.
    assert found("literal") == ([5], 1, None)


@pytest.mark.usefixtures("sandbox", "node")
def test_a_find_takes_a_regex_case_pages_and_context(
    db_session: Session, user: User
) -> None:
    file_id = _publish(_chat(db_session, user, "Reports"), "birds.pdf", _birds_pdf())
    tool = LibraryFindTool(_turn(user, _chat(db_session, user)))

    def found(item: dict[str, JsonValue]) -> FoundText:
        [result] = ArtifactsFound.model_validate_json(
            _call(tool, {"find": [{"file_id": file_id} | item]}).content
        ).items
        return result

    egrets = found(
        {
            "pattern": r"about \w+",
            "regex": True,
            "start_page": 2,
            "context_before_lines": 1,
        }
    )
    [match] = egrets.matches
    assert (match.page, match.text, match.before) == (
        2,
        "Page two about egrets.",
        ["Birds wade."],
    )
    assert found({"pattern": "page", "case_sensitive": True}).matches == []
    assert len(found({"pattern": "page"}).matches) == 2

    bad = _call(tool, {"find": [{"file_id": file_id, "pattern": "(", "regex": True}]})
    assert bad.is_error
    assert bad.content.startswith("The pattern '(' is not a regular expression")


@pytest.mark.usefixtures("sandbox", "node")
def test_a_find_in_a_sheet_cut_at_the_cell_cap_says_truncated(
    db_session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(extract_file_text, "MAX_XLSX_CELLS_PER_SHEET", 4)
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    for row in range(5):
        sheet.append([f"needle {row}", "hay"])
    data = BytesIO()
    workbook.save(data)
    file_id = _publish(_chat(db_session, user, "Reports"), "big.xlsx", data.getvalue())

    [found] = ArtifactsFound.model_validate_json(
        _call(
            LibraryFindTool(_turn(user, _chat(db_session, user))),
            {"find": [{"file_id": file_id, "pattern": "needle"}]},
        ).content
    ).items

    assert found.matches
    assert found.truncated


@pytest.mark.usefixtures("sandbox", "node")
def test_refused_files_fail_the_whole_read_with_every_reason(
    db_session: Session, user: User, make_test_user: MakeTestUser
) -> None:
    source = _chat(db_session, user, "Reports")
    text_file = _publish(source, "notes.md", b"notes\n")
    picture = _publish(source, "pixel.png", b"\x89PNG\r\n\x1a\n")
    big = _publish(source, "big.txt", b"big\n")
    db_session.execute(
        update(FileRecord)
        .where(FileRecord.file_id == big)
        .values(file_size=ARTIFACT_TEXT_MAX_FILE_BYTES + 1)
    )
    db_session.commit()
    theirs = _publish(
        _chat(db_session, make_test_user("artifact_text_stranger")), "a.md", b"a\n"
    )
    tool = LibraryReadTool(_turn(user, _chat(db_session, user)))

    refused = _call(
        tool,
        {"read": [{"file_id": text_file}, {"file_id": theirs}, {"file_id": "nope"}]},
    )
    assert refused.is_error
    assert refused.content == (
        f"No published file {theirs} in your chats\nNo published file nope in your chats"
    )
    no_text = _call(
        tool, {"read": [{"file_id": text_file}, {"file_id": picture}, {"file_id": big}]}
    )
    assert no_text.is_error
    assert no_text.content == (
        "pixel.png has no text; copy it into the sandbox to work with it\n"
        "big.txt is larger than 50 MiB; copy it into the sandbox to work with it"
    )
    pages = _call(tool, {"read": [{"file_id": text_file, "mode": "pages"}]})
    assert pages.is_error
    assert pages.content == "notes.md has no pages; read or search it by line instead"


@pytest.mark.usefixtures("sandbox", "node")
def test_read_and_find_results_stay_within_their_limit_at_worst_case_sizes(
    db_session: Session, user: User
) -> None:
    """Five items of long lines that JSON escapes share one result of at
    most ARTIFACT_RESULT_MAX_CHARS, and say where each continues."""
    line = '"\t\\' * 400 + "x"
    file_id = _publish(
        _chat(db_session, user, "Reports"),
        "wide.txt",
        "\n".join([line] * 3_000).encode(),
    )
    turn = _turn(user, _chat(db_session, user))
    read = _call(
        LibraryReadTool(turn),
        {"read": [{"file_id": file_id, "max_lines": 2_000}] * 5},
    )
    assert not read.is_error, read.content
    assert len(read.content) <= ARTIFACT_RESULT_MAX_CHARS
    items = ArtifactsRead.model_validate_json(read.content).items
    assert items[0].end_line > 0
    assert [item.next_start_line for item in items] == [
        item.end_line + 1 for item in items
    ]

    found = _call(
        LibraryFindTool(turn),
        {
            "find": [
                {
                    "file_id": file_id,
                    "pattern": "x",
                    "max_matches": 100,
                    "context_before_lines": 5,
                    "context_after_lines": 5,
                }
            ]
            * 5
        },
    )
    assert not found.is_error, found.content
    assert len(found.content) <= ARTIFACT_RESULT_MAX_CHARS
    finds = ArtifactsFound.model_validate_json(found.content).items
    assert finds[0].matches
    assert all(
        item.next_match_offset == len(item.matches) and item.total_matches_seen == 3_000
        for item in finds
    )


# Searching published files


Index = Callable[[Sequence[str]], list[UUID]]


@pytest.fixture
def index() -> Generator[Index, None, None]:
    """Indexes published files, by file ID, with their task as a worker
    does, and refreshes the index so that a search sees them; deletes their
    documents at the end."""
    indexed: list[UUID] = []

    def run(file_ids: Sequence[str]) -> list[UUID]:
        artifact_ids = [_artifact_id(file_id) for file_id in file_ids]
        indexed.extend(artifact_ids)
        for artifact_id in artifact_ids:
            process_single_chat_artifact.run(
                artifact_id=str(artifact_id),  # ty: ignore[invalid-argument-type]
                tenant_id=TENANT_ID,  # ty: ignore[invalid-argument-type]
            )
        with get_session_with_current_tenant() as db_session:
            search_settings = get_current_search_settings(db_session)
        # The lookup refreshes the index first.
        build_opensearch_document_index(search_settings).get_documents_with_any_chunk(
            [str(artifact_id) for artifact_id in artifact_ids]
        )
        return artifact_ids

    yield run
    delete_chat_artifacts_from_index(indexed)


def _search(
    user: User, chat_session_id: UUID, arguments: dict[str, JsonValue]
) -> LibrarySearchResult:
    result = _call(
        LibrarySearchTool(_turn(user, chat_session_id)),
        arguments,
    )
    assert not result.is_error, result.content
    return LibrarySearchResult.model_validate_json(result.content)


def _names(result: LibrarySearchResult) -> list[str]:
    return [hit.file.file_name for hit in result.results]


def _published_at(file_id: str, created_at: datetime, updated_at: datetime) -> None:
    with get_session_with_current_tenant() as db_session:
        db_session.execute(
            update(ChatArtifact)
            .where(ChatArtifact.id == _artifact_id(file_id))
            .values(created_at=created_at, updated_at=updated_at)
        )
        db_session.commit()


@pytest.mark.usefixtures("full_deployment_setup", "fake_embeddings")
def test_a_chat_finds_a_file_by_its_content_and_copies_it_in_both_families(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    user: User,
    family: _Family,
    make_test_user: MakeTestUser,
    index: Index,
) -> None:
    """Chat A publishes a survey; chat C finds it by a word of its body,
    with a snippet, then copies it. Another user's file with the same word
    never shows. The generic cards stream as the reload replays them."""
    word = f"quokka{uuid4().hex[:8]}"
    body = f"# Survey\n\nThe team counted {word} near the river bend.\n".encode()
    chat_a = _sandbox_chat(db_session, user, monkeypatch, "Field work")
    sandbox.write_file(chat_a.ref(db_session), "out/survey.md", body)
    chat_a.send(
        family.llm(
            [
                family.publish("publish", ["out/survey.md"], "Survey"),
                Delta(content="Done."),
            ]
        )
    )
    db_session.expire_all()
    [artifact] = db_session.scalars(
        select(ChatArtifact).where(
            ChatArtifact.chat_session_id == chat_a.chat_session_id
        )
    ).all()
    [file_id] = db_session.scalars(
        select(ChatArtifactVersion.file_id).where(
            ChatArtifactVersion.artifact_id == artifact.id
        )
    ).all()
    stranger = make_test_user("artifact_search_stranger")
    theirs = _publish(
        _chat(db_session, stranger), "theirs.md", f"{word} lives here.".encode()
    )
    index([file_id, theirs])

    chat_c = _sandbox_chat(db_session, user, monkeypatch, "Today")
    llm = family.llm(
        [
            family.search("search", word, 5, None),
            family.read("copy", artifact.id, None, "work"),
            Delta(content="Done."),
        ]
    )
    parts = chat_c.send(llm)

    found = LibrarySearchResult.model_validate_json(last_tool_text(llm, "search"))
    [hit] = found.results
    assert (hit.file.library_file_id, hit.file.file_name, hit.file.title) == (
        artifact.id,
        "survey.md",
        "Survey",
    )
    assert (hit.file.chat_id, hit.file.url) == (
        chat_a.chat_session_id,
        artifact_url(artifact.id, 1),
    )
    assert hit.content_indexed
    assert hit.snippets and word in hit.snippets[0]
    assert (found.next_cursor, found.complete, found.content_search) == (
        None,
        True,
        None,
    )
    [copied] = MaterializedItems.model_validate_json(last_tool_text(llm, "copy")).items
    assert copied.path == "work/survey.md"
    assert _vm_file(node, chat_c.ref(db_session), "work/survey.md") == body
    live = _card_packets(parts)
    assert len([obj for obj in live if isinstance(obj, packets.CustomToolStart)]) == 2
    [replayed] = chat_c.replayed(db_session)
    assert _card_packets(replayed) == live


@pytest.mark.usefixtures("sandbox", "full_deployment_setup", "fake_embeddings")
def test_content_matches_need_the_index_and_names_match_without_it(
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
    index: Index,
) -> None:
    source, calling = chats
    word = f"wombat{uuid4().hex[:8]}"
    survey = _publish(source, "survey.md", f"Counting {word} at dusk.".encode())
    index([survey])
    # Published, and not indexed yet.
    plan = f"{word}-plan.md"
    _publish(source, plan, b"Nothing to see.")

    def search(query: str, *, title_only: bool = False) -> LibrarySearchResult:
        return _search(
            user,
            calling,
            {"search_query": [{"q": query, "search_title_only": title_only}]},
        )

    found = search(word)
    assert [(hit.file.file_name, hit.content_indexed) for hit in found.results] == [
        ("survey.md", True),
        (plan, False),
    ]
    assert found.results[0].snippets and word in found.results[0].snippets[0]
    assert found.results[1].snippets == []
    # Title only: every word in the name, the title or the chat title.
    assert _names(search(word, title_only=True)) == [plan]
    assert _names(search("REPORTS survey", title_only=True)) == ["survey.md"]
    assert _names(search("reports elephant", title_only=True)) == []

    # A new version waits for the index: the result shows it, and its
    # content still matches the version before it.
    newer = _publish(source, "survey.md", b"Rewritten without the animal.")
    [hit] = [hit for hit in search(word).results if hit.file.file_name == "survey.md"]
    assert (hit.file.file_id, hit.file.version_number, hit.content_indexed) == (
        newer,
        2,
        False,
    )
    assert hit.snippets and word in hit.snippets[0]
    index([newer])
    [hit] = [hit for hit in search(word).results if hit.file.file_name == "survey.md"]
    assert hit.content_indexed
    assert word not in " ".join(hit.snippets or [])
    # Search reads the database and the index only.
    assert node.agent.create_calls == 0


@pytest.mark.usefixtures("sandbox", "full_deployment_setup", "fake_embeddings")
def test_a_name_match_not_indexed_yet_stays_on_the_first_page(
    user: User,
    chats: tuple[UUID, UUID],
    index: Index,
) -> None:
    """The nearest chunks of a dozen unrelated indexed files never push a
    file whose name matches off the first page."""
    source, calling = chats
    word = f"lemur{uuid4().hex[:8]}"
    index(
        [
            _publish(
                source, f"memo-{number}.md", f"Memo {number} on logistics.".encode()
            )
            for number in range(12)
        ]
    )
    plan = f"{word}-plan.md"
    _publish(source, plan, b"Nothing to see.")

    found = _search(user, calling, {"search_query": [{"q": word}]})

    assert plan in _names(found)


@pytest.mark.usefixtures("sandbox", "full_deployment_setup", "fake_embeddings")
def test_a_sort_other_than_relevance_lists_only_matching_files(
    user: User,
    chats: tuple[UUID, UUID],
    index: Index,
) -> None:
    source, calling = chats
    word = f"tapir{uuid4().hex[:8]}"
    survey = _publish(source, "survey.md", f"Counting {word} at dawn.".encode())
    unrelated = _publish(source, "unrelated.md", b"Quarterly logistics memo.")
    index([survey, unrelated])

    found = _search(
        user, calling, {"search_query": [{"q": word}], "sort": "modified_at"}
    )

    assert _names(found) == ["survey.md"]


@pytest.mark.usefixtures("sandbox", "full_deployment_setup", "fake_embeddings")
def test_a_long_file_never_hides_the_shorter_files_that_match(
    user: User,
    chats: tuple[UUID, UUID],
    index: Index,
) -> None:
    """The matching chunks of one long file are more than a content query
    retrieves; the short files that match still show."""
    source, calling = chats
    word = f"okapi{uuid4().hex[:8]}"
    long = _publish(
        source,
        "long.md",
        " ".join(
            [f"The {word} grazes."] * LIBRARY_SEARCH_CHUNKS_PER_QUERY * 100
        ).encode(),
    )
    filler = " ".join(["Trucks carry the freight."] * 50)
    shorts = [
        _publish(source, f"short-{number}.md", f"{filler} A {word}. {filler}".encode())
        for number in range(3)
    ]
    with get_session_with_current_tenant() as db_session:
        settings = get_current_search_settings(db_session)
    # Not needed once the indexing tokenizer counts without truncation: a
    # tokenizer that cuts at 128 tokens leaves the long file one chunk.
    tokenizer = get_tokenizer(settings.model_name, settings.provider_type)
    assert isinstance(tokenizer, HuggingFaceTokenizer)
    truncation = tokenizer.encoder.truncation
    tokenizer.encoder.no_truncation()
    try:
        index([long, *shorts])
    finally:
        if truncation is not None:
            tokenizer.encoder.enable_truncation(**truncation)

    found = _search(
        user,
        calling,
        {"search_query": [{"q": word}], "sort": "name", "sort_order": "asc"},
    )

    assert _names(found) == ["long.md", "short-0.md", "short-1.md", "short-2.md"]


@pytest.mark.usefixtures("sandbox")
@pytest.mark.parametrize(
    "question", ["What is the Q3 budget?", "What's the Q3 budget?", "Q3_budget"]
)
def test_a_question_matches_a_file_name_without_its_stopwords_and_punctuation(
    user: User,
    chats: tuple[UUID, UUID],
    question: str,
) -> None:
    source, calling = chats
    _publish(source, "q3-budget.xlsx", b"x")
    _publish(source, "q4-budget.xlsx", b"x")

    found = _search(
        user,
        calling,
        {"search_query": [{"q": question, "search_title_only": True}]},
    )

    assert _names(found) == ["q3-budget.xlsx"]


@pytest.mark.usefixtures("sandbox", "full_deployment_setup", "fake_embeddings")
def test_filters_the_chat_and_file_refs_keep_the_files_that_a_search_reaches(
    db_session: Session,
    user: User,
    chats: tuple[UUID, UUID],
    index: Index,
) -> None:
    source, calling = chats
    archive = _chat(db_session, user, "Archive")
    word = f"numbat{uuid4().hex[:8]}"
    notes_v1 = _publish(source, "notes.md", f"First notes on {word}.".encode())
    notes = _publish(source, "notes.md", f"Notes on {word}.".encode())
    table = _publish(source, "table.csv", f"animal,count\n{word},3\n".encode())
    log = _publish(archive, "log.txt", f"Saw a {word} today.".encode())
    now = datetime.now(timezone.utc)
    for file_id, days in ((notes, 10), (table, 5), (log, 1)):
        _published_at(file_id, now - timedelta(days=days), now - timedelta(days=days))
    index([notes, table, log])

    def found(**arguments: JsonValue) -> list[str]:
        return sorted(
            _names(_search(user, calling, {"search_query": [{"q": word}], **arguments}))
        )

    assert found() == ["log.txt", "notes.md", "table.csv"]
    assert found(filters={"include_file_types": ["CSV"]}) == ["table.csv"]
    assert found(filters={"exclude_file_types": [".md", "csv"]}) == ["log.txt"]
    assert found(filters={"category": "sheet"}) == ["table.csv"]
    cutoff = (now - timedelta(days=3)).isoformat()
    assert found(filters={"created_after": cutoff}) == ["log.txt"]
    assert found(filters={"created_before": cutoff}) == ["notes.md", "table.csv"]
    assert found(filters={"modified_after": cutoff}) == ["log.txt"]
    assert found(filters={"modified_before": cutoff}) == ["notes.md", "table.csv"]
    assert found(chat_id=str(archive)) == ["log.txt"]
    notes_id = str(_artifact_id(notes))
    assert found(scope={"file_refs": [{"library_file_id": notes_id}]}) == ["notes.md"]
    assert found(scope={"file_refs": [{"file_id": notes}, {"file_id": table}]}) == [
        "notes.md",
        "table.csv",
    ]

    tool = LibrarySearchTool(_turn(user, calling))
    unknown = str(uuid4())
    for arguments, error in (
        (
            {"scope": {"file_refs": [{"file_id": notes_v1}]}},
            f"{notes_v1} is version 1 of {notes_id}; only the newest version is "
            "searchable: find text in that version instead",
        ),
        (
            {
                "scope": {
                    "file_refs": [{"library_file_id": notes_id, "version_number": 1}]
                }
            },
            f"{notes_id} is version 1 of {notes_id}; only the newest version is "
            "searchable: find text in that version instead",
        ),
        (
            {"scope": {"file_refs": [{"library_file_id": unknown}]}},
            f"No published file {unknown} in your chats",
        ),
        ({"chat_id": unknown}, f"No chat {unknown} of yours"),
    ):
        refused = _call(tool, {"search_query": [{"q": word}], **arguments})
        assert refused.is_error
        assert refused.content == error


@pytest.mark.usefixtures("sandbox")
def test_each_sort_orders_the_matches_and_pages_never_overlap(
    db_session: Session,
    node: RunningFakeAgent,
    user: User,
    chats: tuple[UUID, UUID],
) -> None:
    source, calling = chats
    word = f"kiwi{uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    # (name, size, days since the first publish, days since the latest)
    shapes = [
        ("b", 30, 5, 1),
        ("d", 10, 4, 3),
        ("a", 50, 3, 2),
        ("e", 20, 2, 5),
        ("c", 40, 1, 4),
    ]
    for name, size, created, updated in shapes:
        file_id = _publish(source, f"{name}-{word}.txt", b"x" * size)
        _published_at(
            file_id, now - timedelta(days=created), now - timedelta(days=updated)
        )
    _publish(_chat(db_session, user), "unrelated.txt", b"x")
    by_name = {
        name: (size, created, updated) for name, size, created, updated in shapes
    }
    expected = {
        # The name matches rank by the latest change (publish or rename).
        "relevance": sorted(by_name, key=lambda name: by_name[name][2]),
        "created_at": sorted(by_name, key=lambda name: -by_name[name][1]),
        "modified_at": sorted(by_name, key=lambda name: -by_name[name][2]),
        "name": sorted(by_name),
        "size": sorted(by_name, key=lambda name: by_name[name][0]),
    }

    for sort, order in product(expected, ("asc", "desc")):
        seen: list[str] = []
        cursor: str | None = None
        # Five files, two a page.
        for _ in range(3):
            page = _search(
                user,
                calling,
                {
                    "search_query": [{"q": word, "search_title_only": True}],
                    "sort": sort,
                    "sort_order": order,
                    "top_k": 2,
                    "cursor": cursor,
                },
            )
            seen += [name.split("-")[0] for name in _names(page)]
            cursor = page.next_cursor
        assert cursor is None, (sort, order)
        assert seen == (
            expected[sort]
            if sort == "relevance" or order == "asc"
            else expected[sort][::-1]
        ), (sort, order)
    assert node.agent.create_calls == 0


@pytest.mark.usefixtures("sandbox")
def test_without_a_search_index_only_names_and_titles_match(
    monkeypatch: pytest.MonkeyPatch,
    user: User,
    chats: tuple[UUID, UUID],
) -> None:
    source, calling = chats
    word = f"emu{uuid4().hex[:8]}"
    _publish(source, "body.md", f"The {word} runs.".encode())
    _publish(source, f"{word}.md", b"Nothing here.")

    def no_index(*_args: object) -> None:
        raise AssertionError("no search index to query")

    monkeypatch.setattr(artifact_operations, "DISABLE_VECTOR_DB", True)
    monkeypatch.setattr(artifact_operations, "search_chunks", no_index)
    found = _search(user, calling, {"search_query": [{"q": word}]})
    assert _names(found) == [f"{word}.md"]
    assert found.content_search == "unavailable"
    assert not found.results[0].content_indexed
