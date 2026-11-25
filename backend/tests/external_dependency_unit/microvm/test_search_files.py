"""Search result files in a sandbox chat, against a fake host agent: an
internal search through the chat flow names each shown result's connector
file by its path in attachments/search/, and copies the file there in the
background (`sandbox/file_copies.py`, TurnSearchFiles): once per chat and
VM, within the turn's budget, only with access, under the chat's cap, and
never deleted by the chat file copy."""

import io
import threading
import time
from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from onyx.cache.interface import CacheBackend
from onyx.chat import process_message
from onyx.chat.execution import chat_turn_work
from onyx.chat.process_message import handle_stream_message_objects
from onyx.configs.constants import DEFAULT_PERSONA_ID, DocumentSource, FileOrigin
from onyx.context.search.models import InferenceSection
from onyx.db.chat import create_chat_session
from onyx.db.enums import AccessType
from onyx.db.models import (
    ConnectorCredentialPair,
    DocumentByConnectorCredentialPair,
    FileRecord,
    Sandbox,
    User,
)
from onyx.db.models import Document as DbDocument
from onyx.db.tools import get_builtin_tool
from onyx.file_store.file_store import get_default_file_store
from onyx.kg.models import KGStage
from onyx.llm.cancellation import CancellationSignal, current_cancellation
from onyx.llm.model_capabilities import ToolFamily
from onyx.llm.model_response import Delta
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolResultMessage,
)
from onyx.microvm.daemon_client import SandboxDaemonErrorReason
from onyx.microvm.models import FileListing
from onyx.prompts.sandbox_tools import SEARCH_FILE_GUIDANCE
from onyx.server.features.build.sandbox import harness_factory
from onyx.server.features.build.sandbox.file_copy_state import copy_generation_key
from onyx.server.features.build.sandbox.firecracker import harness_state, purge
from onyx.server.features.build.sandbox.firecracker.harness_sandbox import (
    FirecrackerHarnessSandbox,
)
from onyx.server.features.build.sandbox.harness_base import (
    SessionFiles,
    search_file_name,
)
from onyx.server.features.build.sandbox.models import HarnessSandboxRef
from onyx.server.query_and_chat.chat_backend import delete_chat_session_by_id
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.tools.constants import PYTHON_TOOL_NAME, SPAWN_AGENT_TOOL_NAME
from onyx.tools.models import CapabilityEntry, SearchResult, SearchResults, ToolOptions
from onyx.tools.tool_implementations.code_mode.shapes import OPENAI_CODE_MODE
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.sandbox import file_copies
from onyx.tools.tool_implementations.sandbox.models import (
    SearchResultFile,
    VmChatFile,
)
from onyx.tools.tool_implementations.sandbox.shapes import SHELL_SHAPES
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
from onyx.tools.tool_implementations.search import search_tool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.search.search_utils import (
    merge_overlapping_sections,
)
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
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)
from tests.external_dependency_unit.microvm.conftest import (
    TENANT_ID,
    AddNode,
    Idle,
    NewFileCopyPool,
    forget_sandbox_keys,
)
from tests.external_dependency_unit.microvm.fake_agent import (
    InsecureClientFactory,
    RunningFakeAgent,
    WriteFailure,
)
from tests.external_dependency_unit.microvm.test_file_copies import (
    _FailedDeletes,
    _wrap,
    _Wrapped,
)
from tests.external_dependency_unit.microvm.test_sandbox_tools import (
    SandboxChat,
    _stop_when,
)
from tests.external_dependency_unit.mock_search_pipeline import (
    MockInternalSearchResult,
    SearchPipelineController,
    use_mock_search_pipeline,
)

pytestmark = pytest.mark.usefixtures("tenant_context", "initialize_file_store")

SOURCE = DocumentSource.GOOGLE_DRIVE
EXCERPT = "region,revenue"
QUERY = "Q2 revenue"


@pytest.fixture
def sandbox(
    monkeypatch: pytest.MonkeyPatch, client_factory: InsecureClientFactory
) -> FirecrackerHarnessSandbox:
    instance = FirecrackerHarnessSandbox(
        template="tpl-1", client_factory=client_factory
    )
    monkeypatch.setattr(harness_factory, "HARNESS_SANDBOX_ENABLED", True)
    monkeypatch.setattr(harness_factory, "_instance", instance)
    monkeypatch.setattr(process_message, "HARNESS_SANDBOX_ENABLED", True)
    monkeypatch.setattr(file_copies, "RETRY_PAUSE_SECONDS", 0.0)
    # The fake VM and the database share the host's clock.
    monkeypatch.setattr(file_copies, "SEARCH_COPY_CLOCK_SKEW", timedelta(0))
    return instance


@pytest.fixture
def node(add_node: AddNode) -> RunningFakeAgent:
    return add_node(f"srf-{uuid4().hex[:6]}")


@pytest.fixture
def chat_ids() -> list[UUID]:
    """The chats of the test, whose copy generations the `user` teardown
    deletes."""
    return []


@pytest.fixture
def user(
    db_session: Session,
    tenant_cache: CacheBackend,
    make_test_user: MakeTestUser,
    idle: Idle,
    chat_ids: list[UUID],
) -> Generator[User, None, None]:
    user = make_test_user("search_files")
    yield user
    assert chat_turn_work.wait_idle(timeout=30)
    _wait_until(idle)
    for chat_id in chat_ids:
        tenant_cache.delete(copy_generation_key(chat_id))
    db_session.rollback()
    for sandbox_id in db_session.scalars(
        select(Sandbox.id).where(Sandbox.user_id == user.id)
    ):
        forget_sandbox_keys(tenant_cache, sandbox_id)
        for prefix in harness_state.SANDBOX_STATE_PREFIXES:
            tenant_cache.delete(prefix + str(sandbox_id))


def _new_chat(
    db_session: Session,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
    chat_ids: list[UUID],
) -> SandboxChat:
    chat_session = create_chat_session(
        db_session, "search files", user.id, persona_id=DEFAULT_PERSONA_ID
    )
    chat_ids.append(chat_session.id)
    return SandboxChat(
        user=user, chat_session_id=chat_session.id, monkeypatch=monkeypatch
    )


@pytest.fixture
def chat(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    sandbox: FirecrackerHarnessSandbox,  # noqa: ARG001
    node: RunningFakeAgent,  # noqa: ARG001
    chat_ids: list[UUID],
) -> SandboxChat:
    return _new_chat(db_session, user, monkeypatch, chat_ids)


@dataclass(frozen=True)
class ConnectorFile:
    file_id: str
    document_id: str
    title: str
    data: bytes
    # The file record's last write.
    updated_at: datetime

    def result(self) -> MockInternalSearchResult:
        return MockInternalSearchResult(
            document_id=self.document_id.removeprefix(f"{SOURCE.value.upper()}_"),
            source_type=SOURCE,
            semantic_identifier=self.title,
            chunk_ind=0,
            content=EXCERPT,
            file_id=self.file_id,
        )


MakeFile = Callable[[bytes], ConnectorFile]


@pytest.fixture
def cc_pair(db_session: Session) -> Iterator[ConnectorCredentialPair]:
    pair = make_cc_pair(db_session, source=SOURCE)
    yield pair
    db_session.rollback()
    cleanup_cc_pair(db_session, pair)


@pytest.fixture
def make_file(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> Iterator[MakeFile]:
    """A connector file in the file store, and the public document that has
    it. Teardown deletes both, whatever a test did to the document's links."""
    made: list[ConnectorFile] = []

    def make(data: bytes) -> ConnectorFile:
        name = uuid4().hex[:8]
        file_id = get_default_file_store().save_file(
            content=io.BytesIO(data),
            display_name=f"{name}.csv",
            file_origin=FileOrigin.CONNECTOR,
            file_type="text/csv",
        )
        document_id = f"{SOURCE.value.upper()}_{name}"
        db_session.add(
            DbDocument(
                id=document_id,
                semantic_id=f"{name}.csv",
                file_id=file_id,
                kg_stage=KGStage.NOT_STARTED,
            )
        )
        db_session.flush()
        db_session.add(
            DocumentByConnectorCredentialPair(
                id=document_id,
                connector_id=cc_pair.connector_id,
                credential_id=cc_pair.credential_id,
                has_been_indexed=True,
            )
        )
        db_session.commit()
        record = db_session.get_one(FileRecord, file_id)
        made.append(
            ConnectorFile(file_id, document_id, f"{name}.csv", data, record.updated_at)
        )
        return made[-1]

    yield make
    db_session.rollback()
    document_ids = [file.document_id for file in made]
    db_session.execute(
        delete(DocumentByConnectorCredentialPair).where(
            DocumentByConnectorCredentialPair.id.in_(document_ids)
        )
    )
    db_session.execute(delete(DbDocument).where(DbDocument.id.in_(document_ids)))
    db_session.commit()
    for file in made:
        get_default_file_store().delete_file(file.file_id, error_on_missing=False)


@pytest.fixture
def internal() -> Iterator[SearchPipelineController]:
    """Internal search with mocked results whose chunks keep their files."""
    with (
        use_mock_search_pipeline([SOURCE]) as controller,
        # The mocked pipeline has no index rows; keep the chunk's file.
        patch(
            "onyx.tools.tool_implementations.search.search_tool.populate_file_ids_on_sections"
        ),
        patch(
            "onyx.tools.tool_constructor.get_default_document_index",
            return_value=MagicMock(),
        ),
    ):
        yield controller


def _search_tool_id(db_session: Session) -> int:
    return get_builtin_tool(db_session, SearchTool).id


def _search(call_id: str, query: str = QUERY) -> Delta:
    return tool_step(SearchTool.NAME, call_id, {"queries": [query]})


def _results(llm: ChatLLM, call_id: str) -> list[SearchResult]:
    return SearchResults.model_validate_json(last_tool_text(llm, call_id)).results


def _path(file: ConnectorFile) -> str:
    return f"attachments/search/{search_file_name(file.file_id, file.title)}"


def _key(ref: HarnessSandboxRef, path: str) -> tuple[str, str, str]:
    return (str(ref.sandbox_id), str(ref.session_id), path)


def _session_files(node: RunningFakeAgent, ref: HarnessSandboxRef) -> dict[str, bytes]:
    # The agent's handlers change `files` on their threads.
    with node.agent.lock:
        files = dict(node.agent.files)
    return {
        path: data
        for (sandbox_id, session_id, path), data in files.items()
        if (sandbox_id, session_id) == _key(ref, "")[:2]
    }


def _search_files(node: RunningFakeAgent, ref: HarnessSandboxRef) -> dict[str, bytes]:
    return {
        path: data
        for path, data in _session_files(node, ref).items()
        if path.startswith("attachments/search/")
    }


def _wait_until(condition: Callable[[], bool], seconds: float = 15) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "the condition did not hold in time"
        time.sleep(0.02)  # test-flakes: allow polls a condition until a deadline


def test_a_search_names_the_vm_path_and_the_file_arrives(
    db_session: Session,
    chat: SandboxChat,
    node: RunningFakeAgent,
    make_file: MakeFile,
    internal: SearchPipelineController,
    idle: Idle,
) -> None:
    file = make_file(b"region,revenue\nwest,10\n")
    internal.add_search_results(QUERY, [file.result()])
    llm = ChatLLM([_search("found"), Delta(content="Done.")])
    chat.send(llm, tool_ids=[_search_tool_id(db_session)])

    [result] = _results(llm, "found")
    assert result.file_name is not None
    assert result.file_name == _path(file)
    assert result.content == SEARCH_FILE_GUIDANCE.format(
        filename=result.file_name, content=EXCERPT
    )
    ref = chat.ref(db_session)
    _wait_until(lambda: _search_files(node, ref) == {result.file_name: file.data})
    _wait_until(idle)


def test_a_file_is_copied_once_for_each_chat(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    chat: SandboxChat,
    node: RunningFakeAgent,
    make_file: MakeFile,
    internal: SearchPipelineController,
    idle: Idle,
    chat_ids: list[UUID],
) -> None:
    file = make_file(b"a,b\n1,2\n")
    internal.add_search_results(QUERY, [file.result()])
    tool_ids = [_search_tool_id(db_session)]
    ref = chat.ref(db_session)

    # Two searches of one turn.
    llm = ChatLLM([_search("first"), _search("second"), Delta(content="Done.")])
    chat.send(llm, tool_ids=tool_ids)
    [first] = _results(llm, "first")
    [second] = _results(llm, "second")
    assert first.file_name is not None
    assert second.file_name == first.file_name
    path = first.file_name
    _wait_until(lambda: _search_files(node, ref) == {path: file.data})
    _wait_until(idle)
    assert node.agent.write_paths.count(path) == 1

    # A later turn finds the file in place, and writes it no more.
    llm = ChatLLM([_search("again"), Delta(content="Done.")])
    chat.send(llm, tool_ids=tool_ids)
    assert [result.file_name for result in _results(llm, "again")] == [path]
    _wait_until(idle)
    assert node.agent.write_paths.count(path) == 1
    assert _search_files(node, ref) == {path: file.data}

    # Another chat copies its own.
    other = _new_chat(db_session, user, monkeypatch, chat_ids)
    llm = ChatLLM([_search("other"), Delta(content="Done.")])
    other.send(llm, tool_ids=tool_ids)
    assert [result.file_name for result in _results(llm, "other")] == [path]
    other_ref = other.ref(db_session)
    _wait_until(lambda: _search_files(node, other_ref) == {path: file.data})
    _wait_until(idle)
    assert node.agent.write_paths.count(path) == 2
    assert _search_files(node, ref) == {path: file.data}


def test_a_file_whose_content_changed_at_the_same_size_is_copied_again(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    chat: SandboxChat,
    node: RunningFakeAgent,
    make_file: MakeFile,
    internal: SearchPipelineController,
    idle: Idle,
) -> None:
    file = make_file(b"west,10\n")
    internal.add_search_results(QUERY, [file.result()])
    tool_ids = [_search_tool_id(db_session)]
    ref = chat.ref(db_session)
    path = _path(file)
    chat.send(ChatLLM([_search("first"), Delta(content="Done.")]), tool_ids=tool_ids)
    _wait_until(lambda: _search_files(node, ref) == {path: file.data})
    _wait_until(idle)

    # A connector indexes new content under the same file ID and size.
    edited = b"west,99\n"
    assert len(edited) == len(file.data)
    get_default_file_store().save_file(
        content=io.BytesIO(edited),
        display_name=file.title,
        file_origin=FileOrigin.CONNECTOR,
        file_type="text/csv",
        file_id=file.file_id,
    )
    chat.send(ChatLLM([_search("edited"), Delta(content="Done.")]), tool_ids=tool_ids)
    _wait_until(lambda: _search_files(node, ref) == {path: edited})
    _wait_until(idle)
    assert node.agent.write_paths.count(path) == 2

    # An unchanged file stays in place.
    chat.send(ChatLLM([_search("same"), Delta(content="Done.")]), tool_ids=tool_ids)
    _wait_until(idle)
    assert node.agent.write_paths.count(path) == 2
    assert _search_files(node, ref) == {path: edited}

    # A copy within the clock skew of the record's last write is copied again.
    monkeypatch.setattr(file_copies, "SEARCH_COPY_CLOCK_SKEW", timedelta(hours=1))
    chat.send(ChatLLM([_search("skew"), Delta(content="Done.")]), tool_ids=tool_ids)
    _wait_until(idle)
    assert node.agent.write_paths.count(path) == 3
    assert _search_files(node, ref) == {path: edited}


def test_a_file_in_place_gives_its_turn_budget_back(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    chat: SandboxChat,
    node: RunningFakeAgent,
    make_file: MakeFile,
    internal: SearchPipelineController,
    idle: Idle,
) -> None:
    placed, added = make_file(b"placed"), make_file(b"added")
    internal.add_search_results(QUERY, [placed.result()])
    internal.add_search_results("added", [added.result()])
    tool_ids = [_search_tool_id(db_session)]
    chat.send(ChatLLM([_search("placed"), Delta(content="Done.")]), tool_ids=tool_ids)
    ref = chat.ref(db_session)
    _wait_until(lambda: len(_search_files(node, ref)) == 1)
    _wait_until(idle)

    # A turn of one new file finds its first file in place, so a second fits.
    monkeypatch.setattr(file_copies, "MAX_TURN_SEARCH_FILES", 1)
    llm = ChatLLM(
        [_search("again"), _search("added", "added"), Delta(content="Done.")],
        gates={1: lambda: _wait_until(idle)},
    )
    chat.send(llm, tool_ids=tool_ids)
    [result] = _results(llm, "added")
    assert result.file_name is not None
    _wait_until(lambda: len(_search_files(node, ref)) == 2)
    _wait_until(idle)


def test_a_search_in_a_program_copies_its_file(
    db_session: Session,
    chat: SandboxChat,
    node: RunningFakeAgent,
    make_file: MakeFile,
    internal: SearchPipelineController,
    idle: Idle,
) -> None:
    file = make_file(b"x,y\n")
    internal.add_search_results(QUERY, [file.result()])
    llm = ChatLLM(
        [
            code_step(
                OPENAI_CODE_MODE,
                "program",
                f"r = await tools.internal_search(queries=[{QUERY!r}])\n"
                "print(r['results'][0]['file_name'])\n",
            ),
            Delta(content="Done."),
        ]
    )
    chat.send(llm, code_mode=True, tool_ids=[_search_tool_id(db_session)])

    ref = chat.ref(db_session)
    _wait_until(lambda: len(_search_files(node, ref)) == 1)
    _wait_until(idle)
    [(path, data)] = _search_files(node, ref).items()
    assert path == _path(file)
    assert data == file.data
    assert path in last_tool_text(llm, "program")


def test_files_over_a_limit_get_no_path(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    chat: SandboxChat,
    node: RunningFakeAgent,
    make_file: MakeFile,
    internal: SearchPipelineController,
    idle: Idle,
) -> None:
    small, large, other = make_file(b"123"), make_file(b"12345"), make_file(b"456")
    internal.add_search_results(QUERY, [large.result(), small.result()])
    internal.add_search_results("more", [other.result()])
    # One file over the limit of one file, then one over the turn's budget.
    monkeypatch.setattr(search_tool, "SEARCH_FILE_MAX_BYTES", 4)
    monkeypatch.setattr(file_copies, "MAX_TURN_SEARCH_FILES", 1)
    llm = ChatLLM([_search("found"), _search("more", "more"), Delta(content="Done.")])
    chat.send(llm, tool_ids=[_search_tool_id(db_session)])

    over_file, within = _results(llm, "found")
    [over_turn] = _results(llm, "more")
    assert within.file_name is not None
    assert within.file_name == _path(small)
    for result in (over_file, over_turn):
        assert result.file_name is None
        assert result.content == EXCERPT
    ref = chat.ref(db_session)
    _wait_until(idle)
    assert _search_files(node, ref) == {within.file_name: small.data}


def test_a_sandbox_chat_stages_no_search_files_for_python(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    chat: SandboxChat,
    make_file: MakeFile,
    internal: SearchPipelineController,
    idle: Idle,
) -> None:
    file = make_file(b"a\n")
    internal.add_search_results(QUERY, [file.result()])
    monkeypatch.setattr(PythonTool, "is_available", classmethod(lambda _cls, _db: True))
    staged: list[Any] = []
    monkeypatch.setattr(
        "onyx.chat.agent.build_python_chat_files_from_search_docs",
        lambda docs: staged.append(docs) or [],
    )
    llm = ChatLLM([_search("found"), Delta(content="Done.")])
    chat.send(
        llm,
        tool_ids=[
            _search_tool_id(db_session),
            get_builtin_tool(db_session, PythonTool).id,
        ],
    )

    assert PYTHON_TOOL_NAME in {
        tool["function"]["name"] for tool in llm.requests[0]["tools"]
    }
    [result] = _results(llm, "found")
    assert result.file_name is not None
    assert result.file_name == _path(file)
    assert staged == []
    _wait_until(idle)


def test_the_cap_evicts_the_oldest_search_files_but_not_this_turns(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    chat: SandboxChat,
    node: RunningFakeAgent,
    make_file: MakeFile,
    internal: SearchPipelineController,
    idle: Idle,
) -> None:
    kept, added = make_file(b"kept"), make_file(b"adds")
    internal.add_search_results(QUERY, [kept.result()])
    internal.add_search_results("both", [kept.result(), added.result()])
    tool_ids = [_search_tool_id(db_session)]
    llm = ChatLLM([_search("kept"), Delta(content="Done.")])
    chat.send(llm, tool_ids=tool_ids)
    [result] = _results(llm, "kept")
    assert result.file_name is not None
    kept_path = result.file_name
    ref = chat.ref(db_session)
    _wait_until(lambda: kept_path in _search_files(node, ref))
    _wait_until(idle)

    # An older file of an earlier turn; the kept file, still in place, is
    # older still.
    old_path = "attachments/search/00000000-old.csv"
    node.agent.files[_key(ref, old_path)] = b"older!"
    copied_at = kept.updated_at.timestamp()
    node.agent.file_times[_key(ref, old_path)] = copied_at + 2
    node.agent.file_times[_key(ref, kept_path)] = copied_at + 1
    monkeypatch.setattr(file_copies, "MAX_CHAT_SEARCH_BYTES", 12)

    llm = ChatLLM([_search("both", "both"), Delta(content="Done.")])
    chat.send(llm, tool_ids=tool_ids)
    _, new = _results(llm, "both")
    assert new.file_name is not None
    _wait_until(idle)
    assert _search_files(node, ref) == {kept_path: b"kept", new.file_name: b"adds"}
    assert node.agent.write_paths.count(kept_path) == 1


def test_the_chat_file_copy_never_deletes_search_or_artifact_files(
    user: User,
    sandbox: FirecrackerHarnessSandbox,  # noqa: ARG001
    node: RunningFakeAgent,
    idle: Idle,
    chat_ids: list[UUID],
) -> None:
    file_id = get_default_file_store().save_file(
        content=io.BytesIO(b"project"),
        display_name="p.txt",
        file_origin=FileOrigin.OTHER,
        file_type="text/plain",
    )
    try:

        def turn(chat_session_id: UUID) -> SandboxTurn:
            return SandboxTurn(
                tenant_id=TENANT_ID,
                user_id=user.id,
                chat_session_id=chat_session_id,
                vm_chat_files=[
                    VmChatFile(file_id=file_id, path="attachments/project/p.txt")
                ],
                copy_vm_chat_files=True,
                shell=SHELL_SHAPES[ToolFamily.OPENAI],
            )

        chat_session_id = uuid4()
        chat_ids.append(chat_session_id)
        ref = turn(chat_session_id).start_call()
        _wait_until(idle)
        kept = (
            "attachments/search/12345678-sheet.csv",
            "attachments/artifacts/report.pdf",
        )
        for path in (*kept, "attachments/project/left.txt"):
            node.agent.files[_key(ref, path)] = b"x"

        turn(chat_session_id).start_call()
        _wait_until(idle)
        assert set(_session_files(node, ref)) == {*kept, "attachments/project/p.txt"}
    finally:
        get_default_file_store().delete_file(file_id, error_on_missing=False)


def test_a_search_leaves_the_chat_file_copy_of_its_turn_running(
    monkeypatch: pytest.MonkeyPatch,
    new_file_copy_pool: NewFileCopyPool,
    user: User,
    sandbox: FirecrackerHarnessSandbox,  # noqa: ARG001
    node: RunningFakeAgent,
    make_file: MakeFile,
    chat_ids: list[UUID],
) -> None:
    """The turn's copies of both roots share its copy generation, so the
    chat file copy writes its next file after the search's copy started."""
    monkeypatch.setattr(file_copies, "VM_COPY_WRITES", 1)
    pool = new_file_copy_pool()
    store = get_default_file_store()
    uploads = [
        store.save_file(
            content=io.BytesIO(name.encode()),
            display_name=name,
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
        )
        for name in ("a", "bb")
    ]
    gate = threading.Event()
    node.agent.write_gates["attachments/a.txt"] = gate
    try:
        chat_id = uuid4()
        chat_ids.append(chat_id)
        turn = SandboxTurn(
            tenant_id=TENANT_ID,
            user_id=user.id,
            chat_session_id=chat_id,
            vm_chat_files=[
                VmChatFile(file_id=uploads[0], path="attachments/a.txt"),
                VmChatFile(file_id=uploads[1], path="attachments/b.txt"),
            ],
            copy_vm_chat_files=True,
            shell=SHELL_SHAPES[ToolFamily.OPENAI],
        )
        ref = turn.start_call()
        _wait_until(lambda: "attachments/a.txt" in node.agent.write_waiting)
        file = make_file(b"found")
        paths = turn.search_files.offer(
            {
                file.file_id: SearchResultFile(
                    title=file.title,
                    size=len(file.data),
                    updated_at=file.updated_at,
                    document_ids=(file.document_id,),
                )
            }
        )
        # The search intake ends while the chat file write still waits.
        _wait_until(pool.intake.idle)
        gate.set()
        _wait_until(pool.idle)
        assert node.agent.files[_key(ref, "attachments/b.txt")] == b"bb"
        assert _search_files(node, ref) == {paths[file.file_id]: b"found"}
    finally:
        gate.set()
        _wait_until(pool.idle)
        for upload in uploads:
            store.delete_file(upload, error_on_missing=False)


def test_a_chat_delete_purges_its_search_files(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    chat: SandboxChat,
    node: RunningFakeAgent,
    make_file: MakeFile,
    internal: SearchPipelineController,
    idle: Idle,
) -> None:
    monkeypatch.setattr(purge, "HARNESS_SANDBOX_ENABLED", True)
    file = make_file(b"gone soon")
    internal.add_search_results(QUERY, [file.result()])
    chat.send(
        ChatLLM([_search("found"), Delta(content="Done.")]),
        tool_ids=[_search_tool_id(db_session)],
    )
    ref = chat.ref(db_session)
    _wait_until(lambda: len(_search_files(node, ref)) == 1)
    _wait_until(idle)

    delete_chat_session_by_id(
        chat.chat_session_id, hard_delete=True, user=user, db_session=db_session
    )
    _wait_until(lambda: not _session_files(node, ref))


def test_a_file_without_access_at_copy_time_is_not_copied(
    db_session: Session,
    chat: SandboxChat,
    node: RunningFakeAgent,
    make_file: MakeFile,
    internal: SearchPipelineController,
    idle: Idle,
) -> None:
    readable, revoked = make_file(b"readable"), make_file(b"revoked")
    internal.add_search_results(QUERY, [readable.result(), revoked.result()])
    # The index still returns the document; Postgres no longer grants it.
    db_session.execute(
        delete(DocumentByConnectorCredentialPair).where(
            DocumentByConnectorCredentialPair.id == revoked.document_id
        )
    )
    db_session.commit()
    llm = ChatLLM([_search("found"), Delta(content="Done.")])
    chat.send(llm, tool_ids=[_search_tool_id(db_session)])

    first, second = _results(llm, "found")
    assert first.file_name is not None and second.file_name is not None
    ref = chat.ref(db_session)
    _wait_until(lambda: first.file_name in _search_files(node, ref))
    _wait_until(idle)
    assert _search_files(node, ref) == {first.file_name: readable.data}


def test_a_stopped_search_offers_no_file(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    chat: SandboxChat,
    node: RunningFakeAgent,
    make_file: MakeFile,
    internal: SearchPipelineController,
    idle: Idle,
) -> None:
    file = make_file(b"never")
    internal.add_search_results(QUERY, [file.result()])
    entered: list[bool] = []

    def merged_after_stop(sections: list[InferenceSection]) -> list[InferenceSection]:
        """The search's last step before its result, which ends only after
        Stop."""
        entered.append(True)
        signal = current_cancellation()
        assert signal is not None
        _wait_until(lambda: signal.cancelled)
        return merge_overlapping_sections(sections)

    monkeypatch.setattr(
        "onyx.tools.tool_implementations.search.search_tool.merge_overlapping_sections",
        merged_after_stop,
    )
    join = _stop_when(chat, lambda: bool(entered))
    try:
        chat.send(
            ChatLLM([_search("found"), Delta(content="Done.")]),
            tool_ids=[_search_tool_id(db_session)],
        )
    finally:
        join()
    assert entered
    assert chat_turn_work.wait_idle(timeout=30)
    _wait_until(idle)
    assert not any(
        path.startswith("attachments/search/") for path in node.agent.write_paths
    )


def _searched(
    chat: SandboxChat,
    db_session: Session,
    *searches: tuple[str, str],
    between: Callable[[], None] | None = None,
) -> ChatLLM:
    """One turn whose model runs each (call ID, query) search in turn;
    `between` runs before each later search."""
    llm = ChatLLM(
        [
            *(_search(call_id, query) for call_id, query in searches),
            Delta(content="Done."),
        ],
        gates=dict.fromkeys(range(1, len(searches)), between) if between else None,
    )
    chat.send(llm, tool_ids=[_search_tool_id(db_session)])
    return llm


def test_an_earlier_turns_late_search_leaves_the_newer_turn_alone(
    monkeypatch: pytest.MonkeyPatch,
    new_file_copy_pool: NewFileCopyPool,
    user: User,
    sandbox: FirecrackerHarnessSandbox,  # noqa: ARG001
    node: RunningFakeAgent,
    make_file: MakeFile,
    chat_ids: list[UUID],
) -> None:
    """A background subagent of an earlier turn searches after the next turn
    started: its copy is superseded, so it neither stops the newer turn's
    copies nor evicts their files."""
    monkeypatch.setattr(file_copies, "VM_COPY_WRITES", 1)
    pool = new_file_copy_pool()
    store = get_default_file_store()
    uploads = [
        store.save_file(
            content=io.BytesIO(name.encode()),
            display_name=name,
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
        )
        for name in ("a", "bb")
    ]
    chat_session_id = uuid4()
    chat_ids.append(chat_session_id)

    def turn(chat_files: list[VmChatFile]) -> SandboxTurn:
        return SandboxTurn(
            tenant_id=TENANT_ID,
            user_id=user.id,
            chat_session_id=chat_session_id,
            vm_chat_files=chat_files,
            copy_vm_chat_files=bool(chat_files),
            shell=SHELL_SHAPES[ToolFamily.OPENAI],
        )

    def offer(of: SandboxTurn, file: ConnectorFile) -> str:
        return of.search_files.offer(
            {
                file.file_id: SearchResultFile(
                    title=file.title,
                    size=len(file.data),
                    updated_at=file.updated_at,
                    document_ids=(file.document_id,),
                )
            }
        )[file.file_id]

    gate = threading.Event()
    node.agent.write_gates["attachments/a.txt"] = gate
    try:
        earlier = turn([])
        newer = turn(
            [
                VmChatFile(file_id=uploads[0], path="attachments/a.txt"),
                VmChatFile(file_id=uploads[1], path="attachments/b.txt"),
            ]
        )
        newer_path = offer(newer, make_file(b"newer"))
        ref = newer.copy_target().ref
        _wait_until(lambda: newer_path in _search_files(node, ref))
        newer.start_call()
        _wait_until(lambda: "attachments/a.txt" in node.agent.write_waiting)
        # The earlier turn's copy would evict the newer turn's file.
        monkeypatch.setattr(file_copies, "MAX_CHAT_SEARCH_BYTES", 6)
        earlier_path = offer(earlier, make_file(b"late"))
        # The earlier turn's intake ends while the chat file write still waits.
        _wait_until(pool.intake.idle)
        gate.set()
        _wait_until(pool.idle)
        assert node.agent.files[_key(ref, "attachments/b.txt")] == b"bb"
        assert _search_files(node, ref) == {newer_path: b"newer"}
        assert earlier_path not in node.agent.write_paths
    finally:
        gate.set()
        _wait_until(pool.idle)
        for upload in uploads:
            store.delete_file(upload, error_on_missing=False)


def test_a_file_with_no_recorded_size_meets_the_limits_by_its_real_size(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    chat: SandboxChat,
    node: RunningFakeAgent,
    make_file: MakeFile,
    internal: SearchPipelineController,
    idle: Idle,
) -> None:
    small, large = make_file(b"1234"), make_file(b"12345")
    db_session.execute(
        update(FileRecord)
        .where(FileRecord.file_id.in_([small.file_id, large.file_id]))
        .values(file_size=None)
    )
    db_session.commit()
    internal.add_search_results(QUERY, [small.result(), large.result()])
    monkeypatch.setattr(search_tool, "SEARCH_FILE_MAX_BYTES", 4)
    monkeypatch.setattr(file_copies, "SEARCH_FILE_MAX_BYTES", 4)
    llm = _searched(chat, db_session, ("found", QUERY))

    # Unknown sizes get paths; the copy keeps the file within the limit.
    first, second = _results(llm, "found")
    assert first.file_name is not None and second.file_name is not None
    _wait_until(idle)
    assert _search_files(node, chat.ref(db_session)) == {first.file_name: b"1234"}


def test_a_truncated_listing_evicts_nothing(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    chat: SandboxChat,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    make_file: MakeFile,
    internal: SearchPipelineController,
    idle: Idle,
) -> None:
    file = make_file(b"new")
    internal.add_search_results(QUERY, [file.result()])
    ref = chat.ref(db_session)
    sandbox.ensure_running(ref)
    old_path = "attachments/search/00000000-old.csv"
    node.agent.files[_key(ref, old_path)] = b"old file"
    node.agent.file_times[_key(ref, old_path)] = time.time() - 100
    monkeypatch.setattr(file_copies, "MAX_CHAT_SEARCH_BYTES", 8)

    class _Truncated(_Wrapped):
        def list_files(
            self, directory: str, *, max_entries: int, include_hidden: bool = False
        ) -> FileListing:
            listing = super().list_files(
                directory, max_entries=max_entries, include_hidden=include_hidden
            )
            if directory != "attachments/search":
                return listing
            return FileListing(entries=listing.entries, truncated=True)

    _wrap(monkeypatch, sandbox, _Truncated)
    llm = _searched(chat, db_session, ("found", QUERY))
    [result] = _results(llm, "found")
    assert result.file_name is not None
    _wait_until(idle)
    assert _search_files(node, ref) == {old_path: b"old file", result.file_name: b"new"}


@pytest.mark.parametrize(
    "error",
    [TimeoutError("no response"), PermissionError("the daemon refuses")],
    ids=["no_response", "refused"],
)
def test_an_eviction_that_fails_stops_the_intake(
    error: Exception,
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    chat: SandboxChat,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    make_file: MakeFile,
    internal: SearchPipelineController,
    idle: Idle,
) -> None:
    """The first delete fails: no other delete and no write follow, so the
    chat's search files do not go over the cap."""
    file = make_file(b"new")
    internal.add_search_results(QUERY, [file.result()])
    ref = chat.ref(db_session)
    sandbox.ensure_running(ref)
    old_paths = [
        "attachments/search/00000000-older.csv",
        "attachments/search/00000000-old.csv",
    ]
    for age, path in zip((200, 100), old_paths, strict=True):
        node.agent.files[_key(ref, path)] = b"old!"
        node.agent.file_times[_key(ref, path)] = time.time() - age
    monkeypatch.setattr(file_copies, "MAX_CHAT_SEARCH_BYTES", 4)
    failed: list[_FailedDeletes] = []

    def wrap(files: SessionFiles) -> SessionFiles:
        failed.append(_FailedDeletes(files, error))
        return failed[-1]

    _wrap(monkeypatch, sandbox, wrap)
    llm = _searched(chat, db_session, ("found", QUERY))
    [result] = _results(llm, "found")
    assert result.file_name is not None
    _wait_until(idle)
    assert [path for files in failed for path in files.deleted] == old_paths[:1]
    assert not any(
        path.startswith("attachments/search/") for path in node.agent.write_paths
    )
    assert _search_files(node, ref) == dict.fromkeys(old_paths, b"old!")


def test_when_the_turns_files_fill_the_cap_only_what_fits_is_written(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    chat: SandboxChat,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    make_file: MakeFile,
    internal: SearchPipelineController,
    idle: Idle,
) -> None:
    first, second, large = make_file(b"11111"), make_file(b"22222"), make_file(b"9" * 9)
    internal.add_search_results(QUERY, [first.result(), second.result()])
    internal.add_search_results("large", [large.result()])
    ref = chat.ref(db_session)
    sandbox.ensure_running(ref)
    old_path = "attachments/search/00000000-old.csv"
    node.agent.files[_key(ref, old_path)] = b"old!!!"
    node.agent.file_times[_key(ref, old_path)] = time.time() - 100
    monkeypatch.setattr(file_copies, "MAX_CHAT_SEARCH_BYTES", 8)

    # No write fits: nothing is deleted for it.
    _searched(chat, db_session, ("large", "large"))
    _wait_until(idle)
    assert _search_files(node, ref) == {old_path: b"old!!!"}

    # One of the two fits: the old file makes room for it alone.
    llm = _searched(chat, db_session, ("found", QUERY))
    fits, _ = _results(llm, "found")
    assert fits.file_name is not None
    _wait_until(idle)
    assert _search_files(node, ref) == {fits.file_name: b"11111"}


def test_a_file_refused_at_copy_time_gives_its_budget_back(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    chat: SandboxChat,
    node: RunningFakeAgent,
    make_file: MakeFile,
    internal: SearchPipelineController,
    idle: Idle,
) -> None:
    revoked, later = make_file(b"revoked"), make_file(b"later")
    db_session.execute(
        delete(DocumentByConnectorCredentialPair).where(
            DocumentByConnectorCredentialPair.id == revoked.document_id
        )
    )
    db_session.commit()
    internal.add_search_results(QUERY, [revoked.result()])
    internal.add_search_results("later", [later.result()])
    monkeypatch.setattr(file_copies, "MAX_TURN_SEARCH_FILES", 1)
    llm = _searched(
        chat,
        db_session,
        ("first", QUERY),
        ("later", "later"),
        between=lambda: _wait_until(idle),
    )

    [result] = _results(llm, "later")
    assert result.file_name is not None
    _wait_until(idle)
    assert _search_files(node, chat.ref(db_session)) == {result.file_name: b"later"}


def test_a_file_that_fails_to_copy_gives_its_budget_back(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    chat: SandboxChat,
    node: RunningFakeAgent,
    make_file: MakeFile,
    internal: SearchPipelineController,
    idle: Idle,
) -> None:
    failed, later = make_file(b"failed"), make_file(b"later")
    node.agent.write_failures[_path(failed)] = WriteFailure(
        SandboxDaemonErrorReason.INTERNAL
    )
    internal.add_search_results(QUERY, [failed.result()])
    internal.add_search_results("later", [later.result()])
    monkeypatch.setattr(file_copies, "MAX_TURN_SEARCH_FILES", 1)
    llm = _searched(
        chat,
        db_session,
        ("first", QUERY),
        ("later", "later"),
        between=lambda: _wait_until(idle),
    )

    [result] = _results(llm, "later")
    assert result.file_name is not None
    _wait_until(idle)
    assert node.agent.write_paths.count(_path(failed)) == file_copies.COPY_TRIES
    assert _search_files(node, chat.ref(db_session)) == {result.file_name: b"later"}


def test_a_subagent_search_copies_its_file(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    chat: SandboxChat,
    node: RunningFakeAgent,
    make_file: MakeFile,
    internal: SearchPipelineController,
    idle: Idle,
) -> None:
    file = make_file(b"from a subagent")
    internal.add_search_results(QUERY, [file.result()])
    monkeypatch.setattr("onyx.chat.agent.CODE_MODE_ENABLED", False)
    helper_results: list[str] = []

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        texts = [message.text for message in request.messages]
        results = [
            message.text
            for message in request.messages
            if isinstance(message, ToolResultMessage)
        ]
        if "Task helper" in texts:
            if results:
                helper_results.extend(results)
                return AssistantMessage(content=[TextContent(text="Helped.")])
            return AssistantMessage(
                content=[
                    ToolCall(
                        id="child-search",
                        name=SearchTool.NAME,
                        arguments={"queries": [QUERY]},
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

    model = WaitAgentLLM(generate)
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )
    for _part in handle_stream_message_objects(
        new_msg_req=SendMessageRequest(
            message="Work in the sandbox.",
            chat_session_id=chat.chat_session_id,
            tool_options=ToolOptions(
                allowed=[CapabilityEntry(tool_id=_search_tool_id(db_session))]
            ),
            accepts_follow_ups=True,
        ),
        user=chat.user,
    ):
        pass
    assert chat_turn_work.wait_idle(timeout=30)

    [child_result] = helper_results
    [result] = SearchResults.model_validate_json(child_result).results
    assert result.file_name is not None
    ref = chat.ref(db_session)
    _wait_until(lambda: result.file_name in _search_files(node, ref))
    _wait_until(idle)


def test_a_renamed_users_synced_document_is_copied(
    db_session: Session,
    chat: SandboxChat,
    node: RunningFakeAgent,
    make_file: MakeFile,
    cc_pair: ConnectorCredentialPair,
    internal: SearchPipelineController,
    idle: Idle,
) -> None:
    """A synced ACL names the user's earlier email; search and the copy both
    match it."""
    file = make_file(b"synced")
    old_email = f"old_{uuid4().hex[:8]}@example.com"
    db_session.execute(
        update(ConnectorCredentialPair)
        .where(ConnectorCredentialPair.id == cc_pair.id)
        .values(access_type=AccessType.SYNC)
    )
    db_session.execute(
        update(DbDocument)
        .where(DbDocument.id == file.document_id)
        .values(is_public=False, external_user_emails=[old_email])
    )
    user = db_session.get(User, chat.user.id)
    assert user is not None
    user.prior_emails = [old_email]
    db_session.commit()
    internal.add_search_results(QUERY, [file.result()])
    llm = _searched(chat, db_session, ("found", QUERY))

    [result] = _results(llm, "found")
    assert result.file_name is not None
    _wait_until(idle)
    assert _search_files(node, chat.ref(db_session)) == {result.file_name: b"synced"}


def test_a_failed_size_lookup_skips_only_its_file(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    chat: SandboxChat,
    node: RunningFakeAgent,
    make_file: MakeFile,
    internal: SearchPipelineController,
    idle: Idle,
) -> None:
    broken, fine = make_file(b"broken"), make_file(b"fine")
    db_session.execute(
        update(FileRecord)
        .where(FileRecord.file_id.in_([broken.file_id, fine.file_id]))
        .values(file_size=None)
    )
    db_session.commit()
    internal.add_search_results(QUERY, [broken.result(), fine.result()])
    store = get_default_file_store()
    get_file_size = store.get_file_size

    def failing(file_id: str, db_session: Session | None = None) -> int | None:
        if file_id == broken.file_id:
            raise ConnectionError("the object store did not answer")
        return get_file_size(file_id, db_session)

    monkeypatch.setattr(store, "get_file_size", failing)
    monkeypatch.setattr(file_copies, "get_default_file_store", lambda: store)
    llm = _searched(chat, db_session, ("found", QUERY))

    _, kept = _results(llm, "found")
    assert kept.file_name is not None
    _wait_until(idle)
    assert _search_files(node, chat.ref(db_session)) == {kept.file_name: b"fine"}


def test_a_file_offered_while_the_intake_runs_is_copied(
    monkeypatch: pytest.MonkeyPatch,
    new_file_copy_pool: NewFileCopyPool,
    user: User,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    make_file: MakeFile,
    chat_ids: list[UUID],
) -> None:
    pool = new_file_copy_pool()
    listing = threading.Event()
    release = threading.Event()

    class _HeldListing(_Wrapped):
        def list_files(
            self, directory: str, *, max_entries: int, include_hidden: bool = False
        ) -> FileListing:
            if directory == "attachments/search" and not release.is_set():
                listing.set()
                release.wait(15)
            return super().list_files(
                directory, max_entries=max_entries, include_hidden=include_hidden
            )

    _wrap(monkeypatch, sandbox, _HeldListing)
    chat_id = uuid4()
    chat_ids.append(chat_id)
    turn = SandboxTurn(
        tenant_id=TENANT_ID,
        user_id=user.id,
        chat_session_id=chat_id,
        vm_chat_files=[],
        copy_vm_chat_files=False,
        shell=SHELL_SHAPES[ToolFamily.OPENAI],
    )

    def offer(file: ConnectorFile) -> str:
        return turn.search_files.offer(
            {
                file.file_id: SearchResultFile(
                    title=file.title,
                    size=len(file.data),
                    updated_at=file.updated_at,
                    document_ids=(file.document_id,),
                )
            }
        )[file.file_id]

    try:
        first = offer(make_file(b"first"))
        assert listing.wait(15)
        # The intake took the first file; the second waits for the next one.
        second = offer(make_file(b"second"))
    finally:
        release.set()
    _wait_until(pool.idle)
    ref = turn.copy_target().ref
    assert _search_files(node, ref) == {first: b"first", second: b"second"}


def test_a_write_that_ends_during_the_listing_still_counts_toward_the_cap(
    monkeypatch: pytest.MonkeyPatch,
    new_file_copy_pool: NewFileCopyPool,
    user: User,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    make_file: MakeFile,
    chat_ids: list[UUID],
) -> None:
    """The listing does not show a running write, which then ends before the
    intake reads the turn's running writes: it is counted all the same, so
    the older file makes room."""
    pool = new_file_copy_pool()
    monkeypatch.setattr(file_copies, "MAX_CHAT_SEARCH_BYTES", 12)
    chat_id = uuid4()
    chat_ids.append(chat_id)
    turn = SandboxTurn(
        tenant_id=TENANT_ID,
        user_id=user.id,
        chat_session_id=chat_id,
        vm_chat_files=[],
        copy_vm_chat_files=False,
        shell=SHELL_SHAPES[ToolFamily.OPENAI],
    )
    ref = turn.copy_target().ref
    sandbox.ensure_running(ref)
    old_path = "attachments/search/00000000-old.csv"
    node.agent.files[_key(ref, old_path)] = b"old!!!"
    node.agent.file_times[_key(ref, old_path)] = time.time() - 100

    def offer(file: ConnectorFile) -> str:
        return turn.search_files.offer(
            {
                file.file_id: SearchResultFile(
                    title=file.title,
                    size=len(file.data),
                    updated_at=file.updated_at,
                    document_ids=(file.document_id,),
                )
            }
        )[file.file_id]

    first = make_file(b"11111")
    gate = threading.Event()
    armed = threading.Event()
    running = turn.search_files._writing

    class _StaleListing(_Wrapped):
        def list_files(
            self, directory: str, *, max_entries: int, include_hidden: bool = False
        ) -> FileListing:
            listing = super().list_files(
                directory, max_entries=max_entries, include_hidden=include_hidden
            )
            if directory == "attachments/search" and armed.is_set():
                gate.set()
                _wait_until(lambda: not running)
            return listing

    _wrap(monkeypatch, sandbox, _StaleListing)
    try:
        first_path = (
            f"attachments/search/{search_file_name(first.file_id, first.title)}"
        )
        node.agent.write_gates[first_path] = gate
        assert offer(first) == first_path
        _wait_until(lambda: first_path in node.agent.write_waiting)
        armed.set()
        second_path = offer(make_file(b"22222"))
        _wait_until(pool.idle)
    finally:
        gate.set()
        _wait_until(pool.idle)
    assert _search_files(node, ref) == {first_path: b"11111", second_path: b"22222"}
