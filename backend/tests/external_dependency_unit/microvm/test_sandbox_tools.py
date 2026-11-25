"""exec_command, write_stdin, apply_patch, edit, write and library_create_library_file
against FirecrackerHarnessSandbox with a fake host agent: chat turns through the chat flow (streamed and
replayed packets, code mode values, approvals, Stop, turns that offer no
sandbox), the tools' model text and file effects, published files (access,
the message's files, the chat delete), chat files in attachments/ (the
paths in file messages, late uploads, branch switches, project and agent
files), the turn lifecycle, the Sandbox row and the chat delete purge."""

import io
import json
import threading
import time
from collections.abc import Callable, Generator, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from typing import Any
from unittest.mock import ANY, MagicMock, call, patch
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import Text, cast, delete, select, update
from sqlalchemy.orm import Session

from onyx.access.access import user_can_access_chat_file
from onyx.agents.models import InputSource, MessageDelivery, RunStatus
from onyx.agents.runtime import Agent, Run
from onyx.agents.tools import ToolInvocation, ToolProgress
from onyx.auth.users import get_anonymous_user
from onyx.background.celery.tasks.chat_artifact_indexing.tasks import (
    process_single_chat_artifact,
)
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.chat import execution, process_message
from onyx.chat import files as chat_files
from onyx.chat.agent import ChatAgent
from onyx.chat.chat_processing_checker import get_processing_stream
from onyx.chat.execution import chat_turn_work
from onyx.chat.incognito_context import teardown_incognito_session
from onyx.chat.process_message import (
    dispatch_pending_chat_messages,
    handle_multi_model_stream,
    handle_stream_message_objects,
    run_chat_turn,
)
from onyx.chat.renderer import SPILLED_OUTPUT_NOTE
from onyx.chat.stop_signal_checker import request_stop
from onyx.configs.constants import (
    CELERY_USER_FILE_PROCESSING_TASK_EXPIRES,
    DEFAULT_PERSONA_ID,
    DocumentSource,
    FileOrigin,
    MessageType,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
)
from onyx.context.search.models import (
    InferenceChunk,
    InferenceSection,
    SearchDoc,
    SearchDocsResponse,
)
from onyx.db import chat as db_chat
from onyx.db.chat import (
    create_chat_session,
    delete_all_chat_sessions_for_user,
    delete_chat_session,
    get_chat_published_files,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    ApprovalDecision,
    ChatSessionSharedStatus,
    IncognitoRecordMode,
    PluginInstallationPolicy,
    SandboxStatus,
    UserFileStatus,
)
from onyx.db.models import (
    ApprovalRequest,
    ChatArtifact,
    ChatArtifactVersion,
    ChatInput,
    ChatMessage,
    ChatSession,
    FileRecord,
    Persona__UserFile,
    Project__UserFile,
    Sandbox,
    User,
    UserFile,
    UserProject,
)
from onyx.db.models import ToolCall as ToolCallRecord
from onyx.db.persona import upsert_persona
from onyx.db.sandbox import (
    create_sandbox__no_commit,
    get_or_create_sandbox,
    get_sandbox_by_user_id,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.db.skill import delete_skill
from onyx.db.tools import get_builtin_tool
from onyx.db.users import fetch_user_by_id
from onyx.deep_research.agent import DeepResearchAgent
from onyx.document_index.factory import build_opensearch_document_index
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import ChatFileType, FileDescriptor
from onyx.file_store.utils import plaintext_file_name_for_id
from onyx.indexing.chat_artifact_index import (
    chat_artifact_queued_key,
    delete_chat_artifacts_from_index,
)
from onyx.integrations.models import ApprovalMode
from onyx.llm.cancellation import (
    AgentCancelled,
    CancellationSignal,
    cancellation_scope,
)
from onyx.llm.interfaces import LLMConfig
from onyx.llm.model_capabilities import ToolFamily
from onyx.llm.model_request import UserMessage as PromptUserMessage
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    ResponseFunctionCall,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    TextContentPart,
    ToolCall,
    ToolResult,
    ToolResultMessage,
)
from onyx.llm.override_models import LLMOverride
from onyx.microvm.daemon_client import SandboxDaemonErrorReason
from onyx.microvm.generated.sandboxd.v1 import sandboxd_pb2
from onyx.prompts.sandbox_tools import ATTACHMENTS_NOT_SAVED_NOTE, CHAT_FILES_LAYOUT
from onyx.server.features.action_policies.models import ApprovalChoice
from onyx.server.features.build.sandbox import harness_factory
from onyx.server.features.build.sandbox.exec_output import EXEC_CALL_OUTPUT_MAX_BYTES
from onyx.server.features.build.sandbox.file_copy_state import copy_generation_key
from onyx.server.features.build.sandbox.firecracker import (
    harness_sandbox,
    harness_state,
    purge,
)
from onyx.server.features.build.sandbox.firecracker.harness_sandbox import (
    FirecrackerHarnessSandbox,
)
from onyx.server.features.build.sandbox.firecracker.harness_state import (
    EXEC_SESSIONS_PREFIX,
)
from onyx.server.features.build.sandbox.firecracker.models import ExecSessionTable
from onyx.server.features.build.sandbox.harness_base import (
    ONYX_VM_FILES_ROOT,
    RENDER_FIRST_PAGE_ROOT,
    TOOL_RESULTS_ROOT,
    ExecSessionNotFoundError,
)
from onyx.server.features.build.sandbox.models import (
    CHAT_SKILLS_PATH,
    ExecEvent,
    ExecOutputDelta,
    HarnessSandboxRef,
    SandboxPathInfo,
    session_workspace,
)
from onyx.server.query_and_chat import streaming_models as packets
from onyx.server.query_and_chat.chat_backend import (
    decide_approval,
    delete_all_chat_sessions,
    delete_chat_session_by_id,
    fetch_chat_file,
    get_chat_session,
)
from onyx.server.query_and_chat.models import (
    AUTO_PLACE_AFTER_LATEST_MESSAGE,
    ChatApprovalDecisionRequest,
    MessageOrigin,
    SendMessageRequest,
)
from onyx.server.query_and_chat.streaming_models import StreamingError
from onyx.skills.ingest import delete_bundle_blob
from onyx.tools.constants import (
    EXEC_COMMAND_TOOL_NAME,
    EXEC_TOOL_NAME,
    INTERNAL_SEARCH_TOOL_NAME,
    LOAD_SKILL_TOOL_NAME,
    POSTGRES_TOOL_NAME,
    SKILLS_READ_TOOL_NAME,
    SPAWN_AGENT_TOOL_NAME,
    WRITE_STDIN_TOOL_NAME,
)
from onyx.tools.interface import Tool
from onyx.tools.models import (
    CapabilityEntry,
    CustomToolCallSummary,
    SearchResult,
    SearchResults,
    ToolContext,
    ToolOptions,
)
from onyx.tools.tool_constructor import construct_tools
from onyx.tools.tool_implementations.code_mode import cells
from onyx.tools.tool_implementations.code_mode.models import CodeModeExecutionResult
from onyx.tools.tool_implementations.code_mode.shapes import (
    CLAUDE_CODE_MODE,
    OPENAI_CODE_MODE,
)
from onyx.tools.tool_implementations.open_url import open_url_tool
from onyx.tools.tool_implementations.open_url.open_url_tool import (
    MAX_CHARS_ACROSS_URLS,
    MAX_URLS_PER_CALL,
    OPEN_URL_SHAPES,
    IndexedDocumentRequest,
    IndexedRetrievalResult,
    OpenedPage,
    OpenURLTool,
)
from onyx.tools.tool_implementations.sandbox import (
    artifact_operations,
    file_copies,
    sandbox_tools,
    spill,
)
from onyx.tools.tool_implementations.sandbox.file_copies import CopyStatus
from onyx.tools.tool_implementations.sandbox.models import (
    PUBLISH_FILES_MAX_FILES,
    ApplyPatchFileChange,
    ApplyPatchResult,
    ArtifactPublished,
    PublishedFile,
    PublishedFiles,
    PublishFileArgument,
    SandboxExecResult,
    SpilledOutput,
    artifact_url,
)
from onyx.tools.tool_implementations.sandbox.sandbox_tools import (
    ApplyPatchTool,
    EditTool,
    ExecCommandTool,
    LibraryCreateLibraryFileTool,
    WriteStdinTool,
    WriteTool,
)
from onyx.tools.tool_implementations.sandbox.shapes import SHELL_SHAPES
from onyx.tools.tool_implementations.sandbox.spill import (
    FULL_VALUE_NOTE,
    SPILL_FAILED_NOTE,
)
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
from onyx.tools.tool_implementations.web_search.models import WEB_SEARCH_PREFIX
from onyx.tools.tool_implementations.web_search.utils import (
    TRUNCATED_CONTENT_PREFIX,
    TRUNCATED_CONTENT_SUFFIX,
    inference_section_from_internet_page_scrape,
)
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.chat.test_chat_tool_approvals import ACTION
from tests.external_dependency_unit.chat.test_parked_agent_handoff import _gated
from tests.external_dependency_unit.chat.test_wait_agent import (
    ScriptedLLM as WaitAgentLLM,
)
from tests.external_dependency_unit.code_mode_helpers import (
    ChatLLM,
    code_step,
    final_deltas,
    last_tool_text,
    saved_cells,
    send,
    tool_step,
    wait_step,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.craft.db_helpers import make_chat_custom_skill
from tests.external_dependency_unit.db.test_chat_tool_options import (
    ResearchCapableModel,
)
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
    make_mcp_integration,
)
from tests.external_dependency_unit.microvm.conftest import (
    TENANT_ID,
    AddNode,
    forget_sandbox_keys,
)
from tests.external_dependency_unit.microvm.fake_agent import (
    ANY_PATH,
    FAKE_JPEG,
    InsecureClientFactory,
    RunningFakeAgent,
    WriteFailure,
)
from tests.external_dependency_unit.mock_content_provider import (
    MockWebContent,
    use_mock_content_provider,
)
from tests.external_dependency_unit.mock_search_provider import (
    MockWebSearchResult,
    use_mock_web_provider,
)
from tests.unit.onyx.agents.fakes import ScriptedLLM
from tests.unit.onyx.tools.code_mode.fakes import FakeMCPTool

pytestmark = pytest.mark.usefixtures("tenant_context")

SANDBOX_NAMES = frozenset(
    {EXEC_COMMAND_TOOL_NAME, WRITE_STDIN_TOOL_NAME, ApplyPatchTool.NAME}
)
ADD_A = "*** Begin Patch\n*** Add File: a.txt\n+x\n*** End Patch"


class SandboxTools(BaseModel):
    """The tools of one construction (every file tool), their turn, and its
    sandbox reference."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    turn: SandboxTurn
    ref: HarnessSandboxRef
    exec_command: ExecCommandTool
    write_stdin: WriteStdinTool
    # The shell of the Claude shape.
    bash: ExecCommandTool
    bash_write_stdin: WriteStdinTool
    apply_patch: ApplyPatchTool
    edit: EditTool
    write: WriteTool
    create_file: LibraryCreateLibraryFileTool

    @property
    def all(self) -> list[Tool]:
        return [self.exec_command, self.write_stdin, self.apply_patch]


MakeTools = Callable[..., SandboxTools]


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
    return add_node(f"sbt-{uuid4().hex[:6]}")


def _forget_sandboxes(
    db_session: Session, tenant_cache: CacheBackend, user_id: UUID
) -> None:
    db_session.rollback()
    for sandbox_id in db_session.scalars(
        select(Sandbox.id).where(Sandbox.user_id == user_id)
    ):
        forget_sandbox_keys(tenant_cache, sandbox_id)
        for prefix in harness_state.SANDBOX_STATE_PREFIXES:
            tenant_cache.delete(prefix + str(sandbox_id))


@pytest.fixture
def user(
    db_session: Session, tenant_cache: CacheBackend, make_test_user: MakeTestUser
) -> Generator[User, None, None]:
    user = make_test_user("sandbox_tools")
    yield user
    # A turn's last calls and saves run on their own threads.
    assert chat_turn_work.wait_idle(timeout=30)
    _forget_sandboxes(db_session, tenant_cache, user.id)


@pytest.fixture
def make_tools(db_session: Session, user: User) -> MakeTools:
    def make(chat_session_id: UUID | None = None) -> SandboxTools:
        session_id = chat_session_id or uuid4()
        # A turn of each shell shape, on the same sandbox session.
        turn, claude_turn = (
            SandboxTurn(
                tenant_id=TENANT_ID,
                user_id=user.id,
                chat_session_id=session_id,
                vm_chat_files=[],
                copy_vm_chat_files=False,
                shell=SHELL_SHAPES[family],
            )
            for family in (ToolFamily.OPENAI, ToolFamily.CLAUDE)
        )
        return SandboxTools(
            turn=turn,
            ref=HarnessSandboxRef(
                tenant_id=TENANT_ID,
                sandbox_id=get_or_create_sandbox(db_session, user.id).id,
                session_id=session_id,
            ),
            exec_command=ExecCommandTool(turn),
            write_stdin=WriteStdinTool(turn),
            bash=ExecCommandTool(claude_turn),
            bash_write_stdin=WriteStdinTool(claude_turn),
            apply_patch=ApplyPatchTool(turn),
            edit=EditTool(claude_turn),
            write=WriteTool(claude_turn),
            create_file=LibraryCreateLibraryFileTool(turn),
        )

    return make


def _run(
    tool: Tool, arguments: dict[str, JsonValue]
) -> tuple[ToolResult, list[ToolProgress]]:
    """Run one call as the agent runtime does; returns its result and progress."""
    progress: list[ToolProgress] = []
    outcome = tool.run(
        ToolInvocation(
            call_id="call-1",
            arguments=arguments,
            cancellation=CancellationSignal(),
            update=progress.append,
        ),
        ToolContext(),
    )
    assert isinstance(outcome, ToolResult)
    return outcome, progress


def _key(ref: HarnessSandboxRef, path: str) -> tuple[str, str, str]:
    return (str(ref.sandbox_id), str(ref.session_id), path)


def _files(node: RunningFakeAgent, ref: HarnessSandboxRef) -> dict[str, bytes]:
    return {
        path: data
        for (sandbox_id, session_id, path), data in node.agent.files.items()
        if (sandbox_id, session_id) == (str(ref.sandbox_id), str(ref.session_id))
    }


def _ended_turns(
    monkeypatch: pytest.MonkeyPatch, sandbox: FirecrackerHarnessSandbox
) -> list[HarnessSandboxRef]:
    """The refs of each end_turn from now on."""
    ended: list[HarnessSandboxRef] = []
    end_turn = sandbox.end_turn

    def counted_end_turn(ref: HarnessSandboxRef) -> None:
        ended.append(ref)
        end_turn(ref)

    monkeypatch.setattr(sandbox, "end_turn", counted_end_turn)
    return ended


def _wait_until(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 10
    while not condition():
        assert time.monotonic() < deadline, "the condition did not hold in time"
        time.sleep(0.05)


# The chat flow


class SandboxChat(BaseModel):
    """A user's chat with the default agent, limited to the sandbox tools."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user: User
    chat_session_id: UUID
    monkeypatch: pytest.MonkeyPatch

    def ref(self, db_session: Session) -> HarnessSandboxRef:
        return HarnessSandboxRef(
            tenant_id=TENANT_ID,
            sandbox_id=get_or_create_sandbox(db_session, self.user.id).id,
            session_id=self.chat_session_id,
        )

    def send(
        self,
        llm: ScriptedLLM,
        *,
        code_mode: bool = False,
        on_part: Callable[[object], None] = lambda _part: None,
        tool_ids: Sequence[int] = (),
        file_descriptors: Sequence[FileDescriptor] = (),
        parent_message_id: int | None = AUTO_PLACE_AFTER_LATEST_MESSAGE,
    ) -> list[object]:
        """Send a message with `file_descriptors` attached, under
        `parent_message_id`; the agent's tools in `tool_ids` join the sandbox
        tools. `code_mode` stays set until the test ends, so a resume after
        the send restores the run with the same code mode."""
        self.monkeypatch.setattr("onyx.chat.agent.CODE_MODE_ENABLED", code_mode)
        return list(
            send(
                self.chat_session_id,
                self.user,
                llm,
                "Work in the sandbox.",
                code_mode=code_mode,
                on_part=on_part,
                tool_options=ToolOptions(
                    allowed=[CapabilityEntry(tool_id=tool_id) for tool_id in tool_ids]
                ),
                file_descriptors=file_descriptors,
                parent_message_id=parent_message_id,
            )
        )

    def replayed(self, db_session: Session) -> list[list[packets.PacketObj]]:
        """The packets of each saved response, as a reload sends them."""
        detail = get_chat_session(
            session_id=self.chat_session_id, user=self.user, db_session=db_session
        )
        return [[packet.obj for packet in response] for response in detail.packets]


@pytest.fixture
def chat(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    sandbox: FirecrackerHarnessSandbox,  # noqa: ARG001
) -> SandboxChat:
    chat_session = create_chat_session(
        db_session, "sandbox chat", user.id, persona_id=DEFAULT_PERSONA_ID
    )
    return SandboxChat(
        user=user, chat_session_id=chat_session.id, monkeypatch=monkeypatch
    )


def _sandbox_packets(parts: Sequence[object]) -> list[packets.PacketObj]:
    """The sandbox tools' packets of streamed parts or replayed packets, and
    their section ends."""
    sandbox_types = (
        packets.FileToolProgress,
        packets.ExecCommandStart,
        packets.WriteStdinStart,
        packets.ExecOutputDelta,
        packets.ExecEnd,
        packets.ApplyPatchStart,
        packets.ApplyPatchEnd,
        packets.PublishFilesStart,
        packets.PublishFilesEnd,
    )
    objects = [
        part.obj if isinstance(part, packets.Packet) else part
        for part in parts
        if isinstance(part, packets.Packet) or isinstance(part, BaseModel)
    ]
    return [
        obj
        for index, obj in enumerate(objects)
        if isinstance(obj, sandbox_types)
        or (
            isinstance(obj, packets.SectionEnd)
            and index > 0
            and isinstance(objects[index - 1], sandbox_types)
        )
    ]


def _stops(parts: Sequence[object]) -> list[str | None]:
    return [
        part.obj.stop_reason
        for part in parts
        if isinstance(part, packets.Packet)
        and isinstance(part.obj, packets.OverallStop)
    ]


@pytest.mark.usefixtures("node")
def test_a_chat_turn_streams_saves_and_replays_its_sandbox_calls(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    ended = _ended_turns(monkeypatch, sandbox)
    llm = ChatLLM(
        [
            tool_step(EXEC_COMMAND_TOOL_NAME, "exec", {"cmd": "echo hi there"}),
            tool_step(ApplyPatchTool.NAME, "patch", {"input": ADD_A}),
            Delta(content="Done."),
        ]
    )
    parts = chat.send(llm)

    ref = chat.ref(db_session)
    assert _files(node, ref) == {"a.txt": b"x\n"}
    assert ended == [ref]
    exec_text = last_tool_text(llm, "exec")
    assert exec_text.startswith("Wall time: ")
    assert exec_text.endswith(
        "Process exited with code 0\nOriginal character count: 9\nOutput:\nhi there\n"
    )
    assert last_tool_text(llm, "patch") == (
        "Success. Updated the following files:\nA a.txt\n"
    )
    live = _sandbox_packets(parts)
    end = next(obj for obj in live if isinstance(obj, packets.ExecEnd))
    assert end.wall_time_seconds is not None
    assert end == packets.ExecEnd(
        output="hi there\n",
        exit_code=0,
        completion="exited",
        wall_time_seconds=end.wall_time_seconds,
    )
    patched = [
        packets.ApplyPatchStart(patch=ADD_A, tool_name=ApplyPatchTool.NAME),
        packets.ApplyPatchEnd(files=[ApplyPatchFileChange(path="a.txt", change="add")]),
        packets.SectionEnd(),
    ]
    start = packets.ExecCommandStart(cmd="echo hi there")
    assert live == [
        start,
        packets.ExecOutputDelta(text="hi there\n"),
        end,
        packets.SectionEnd(),
        # The streamed arguments report their progress live only.
        packets.FileToolProgress(tool_name=ApplyPatchTool.NAME, paths=["a.txt"]),
        *patched,
    ]
    # A reload sends the saved output with the end, without deltas.
    [replayed] = chat.replayed(db_session)
    assert _sandbox_packets(replayed) == [start, end, packets.SectionEnd(), *patched]


@pytest.mark.usefixtures("node")
def test_a_program_gets_a_dict_from_exec_command_and_a_failed_call_raises(
    chat: SandboxChat,
) -> None:
    program = (
        "r = await tools.exec_command(cmd='echo hi')\n"
        "print(sorted(r), r['output'], r['exit_code'], r['completion'])\n"
        "print(await tools.apply_patch(input='*** Begin Patch\\n*** Add File: a.txt\\n+x\\n"
        "*** End Patch'))\n"
        "try:\n"
        "    await tools.write_stdin(session_id='nope')\n"
        "except Exception as error:\n"
        "    print('raised:', error)\n"
    )
    llm = ChatLLM(
        [code_step(OPENAI_CODE_MODE, "code", program), Delta(content="Done.")]
    )
    chat.send(llm, code_mode=True)

    text = last_tool_text(llm, "code")
    assert (
        "['completion', 'exit_code', 'output', 'wall_time_seconds'] hi\n 0 exited"
        in text
    )
    assert "Success. Updated the following files:\nA a.txt" in text
    assert f"raised: {ExecSessionNotFoundError('nope')}" in text
    assert "class ExecCommandOutput(TypedDict)" in str(llm.requests[0]["tools"])


@pytest.mark.usefixtures("node")
def test_a_program_call_whose_saved_output_is_cut_is_marked_truncated(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, chat: SandboxChat
) -> None:
    monkeypatch.setattr(cells, "MAX_SAVED_CALL_CHARS", 1_000)
    llm = ChatLLM(
        [
            code_step(
                OPENAI_CODE_MODE,
                "code",
                f"r = await tools.exec_command(cmd='echo {'x' * 3_000}')\n"
                "print(len(r['output']))\n",
            ),
            Delta(content="Done."),
        ]
    )
    chat.send(llm, code_mode=True)

    # The program gets all of the output; the saved call keeps a cut copy.
    assert "3001" in last_tool_text(llm, "code")
    [cell] = saved_cells(db_session, chat.chat_session_id)
    [call] = cell.calls
    assert isinstance(call.details, SandboxExecResult)
    assert call.details.truncated
    assert len(call.details.output) < 1_200


@pytest.fixture
def gated_integration(db_session: Session) -> Generator[int, None, None]:
    integration, _ = make_mcp_integration(
        db_session,
        server_url="https://example.com/mcp",
        name=f"sandbox_gate_{uuid4().hex[:8]}",
        tools=[ACTION],
    )
    give_access(
        db_session, [integration], installation_policy=PluginInstallationPolicy.DEFAULT
    )
    integration_id = integration.id
    yield integration_id
    assert chat_turn_work.wait_idle(timeout=30)
    delete_integrations(db_session, [integration_id])


@pytest.mark.usefixtures("node")
def test_a_turn_that_parks_for_approval_and_its_resumed_root_each_end_the_turn(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    chat: SandboxChat,
    gated_integration: int,
) -> None:
    ended = _ended_turns(monkeypatch, sandbox)
    sent: list[str] = []
    gated = _gated(gated_integration, sent)
    real_construct_tools = construct_tools

    def with_gated_tool(**kwargs: Any) -> list[Tool]:
        return [*real_construct_tools(**kwargs), gated]

    monkeypatch.setattr("onyx.chat.execution.construct_tools", with_gated_tool)
    llm = ChatLLM(
        [
            tool_step(EXEC_COMMAND_TOOL_NAME, "exec", {"cmd": "echo hi"}),
            tool_step(gated.name, "send", {"value": "team"}),
            tool_step(EXEC_COMMAND_TOOL_NAME, "again", {"cmd": "echo again"}),
            Delta(content="Done."),
        ]
    )
    # The resumed response runs after the send returns.
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: llm
    )
    parts = chat.send(llm)

    ref = chat.ref(db_session)
    assert _stops(parts) == [packets.AWAITING_USER]
    assert ended == [ref]

    # The approval resumes the root from its saved state with new agent and
    # tool objects, as another API pod does; its release ends the turn again.
    approval = db_session.scalars(
        select(ApprovalRequest).where(
            ApprovalRequest.chat_session_id == chat.chat_session_id
        )
    ).one()
    response_id = approval.chat_message_id
    with get_session_with_current_tenant() as session:
        decide_approval(
            approval_id=approval.id,
            body=ChatApprovalDecisionRequest(decision=ApprovalChoice.APPROVE_ONCE),
            request=Request({"type": "http", "headers": []}),
            user=chat.user,
            db_session=session,
        )

    def completed() -> bool:
        with get_session_with_current_tenant() as session:
            status = session.get_one(ChatMessage, response_id).response_status
        return status == RunStatus.COMPLETE

    _wait_until(completed)
    assert chat_turn_work.wait_idle(timeout=30)
    db_session.refresh(approval)
    assert approval.decision is ApprovalDecision.APPROVED
    assert sent == ["team"]
    assert len(llm.requests) == 4
    assert ended == [ref, ref]


def _running(node: RunningFakeAgent, ref: HarnessSandboxRef, cmd: str) -> list[str]:
    """The execution IDs of the sandbox's `cmd` commands that still run."""
    return [
        execution_id
        for execution_id, execution in node.agent.executions.get(
            str(ref.sandbox_id), {}
        ).items()
        if execution.argv[-1:] == [cmd] and execution.result is None
    ]


def _streamed(text: str) -> tuple[threading.Event, Callable[[object], None]]:
    """An event set once a chat streams `text` as exec output, and the part
    callback that sets it."""
    seen = threading.Event()

    def on_part(part: object) -> None:
        if (
            isinstance(part, packets.Packet)
            and isinstance(part.obj, packets.ExecOutputDelta)
            and part.obj.text == text
        ):
            seen.set()

    return seen, on_part


def _stop_when(chat: SandboxChat, ready: Callable[[], bool]) -> Callable[[], float]:
    """Press Stop on the chat's turn once `ready` holds, on a thread. Returns
    a join that re-raises the thread's failure and returns when Stop was
    pressed."""
    pressed: list[float] = []
    errors: list[BaseException] = []

    def stop() -> None:
        try:
            _wait_until(ready)
            cache = get_cache_backend()
            stream = get_processing_stream(chat.chat_session_id, cache)
            assert stream is not None, "the turn has no processing stream"
            pressed.append(time.monotonic())
            request_stop(chat.chat_session_id, cache, stream_id=stream.stream_id)
        except BaseException as error:
            errors.append(error)

    stopper = threading.Thread(target=copy_context().run, args=(stop,))
    stopper.start()

    def join() -> float:
        stopper.join(timeout=30)
        assert not stopper.is_alive(), "the stopper thread did not end"
        if errors:
            raise errors[0]
        return pressed[0]

    return join


def test_a_stop_kills_the_command_that_its_call_waits_on(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    ended = _ended_turns(monkeypatch, sandbox)
    ref = chat.ref(db_session)
    streamed, on_part = _streamed("partial\n")
    join = _stop_when(chat, streamed.is_set)
    llm = ChatLLM(
        [
            # Its call returns while the command runs.
            tool_step(
                EXEC_COMMAND_TOOL_NAME, "earlier", {"cmd": "cat", "yield_time_ms": 250}
            ),
            tool_step(
                EXEC_COMMAND_TOOL_NAME,
                "exec",
                {"cmd": "say partial", "yield_time_ms": 30_000},
            ),
        ]
    )
    try:
        parts = chat.send(llm, on_part=on_part)
    finally:
        pressed = join()

    # The 30 s wait ends with the Stop. The stopped call has no result: it
    # renders as stopped, live and after a reload.
    assert time.monotonic() - pressed < 10
    assert _stops(parts) == ["user_cancelled"]
    [replayed] = chat.replayed(db_session)
    for shown in (_sandbox_packets(parts), _sandbox_packets(replayed)):
        [earlier] = [obj for obj in shown if isinstance(obj, packets.ExecEnd)]
        assert earlier.session_id is not None
    # Only the waited command dies (SIGKILL); the earlier one keeps running.
    [killed] = node.agent.cancel_calls
    result = node.agent.executions[str(ref.sandbox_id)][killed].result
    assert result is not None and result.completion == sandboxd_pb2.CANCELED
    assert _running(node, ref, "say partial") == []
    assert len(_running(node, ref, "cat")) == 1
    # The turn ends once the stopped call's thread has returned.
    _wait_until(lambda: ended == [ref])


def test_a_stop_kills_the_command_that_a_program_call_waits_on(
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    ref = chat.ref(db_session)
    streamed, on_part = _streamed("partial\n")
    join = _stop_when(chat, streamed.is_set)
    llm = ChatLLM(
        [
            code_step(
                OPENAI_CODE_MODE,
                "code",
                "await tools.exec_command(cmd='say partial', yield_time_ms=30000)",
            )
        ]
    )
    try:
        parts = chat.send(llm, code_mode=True, on_part=on_part)
    finally:
        join()

    # The cell's stop signal ends the call: the command dies, and the call
    # renders as stopped, live and on replay.
    _wait_until(lambda: not _running(node, ref, "say partial"))
    assert len(node.agent.cancel_calls) == 1
    assert _stops(parts) == ["user_cancelled"]
    [replayed] = chat.replayed(db_session)
    for shown in (_sandbox_packets(parts), _sandbox_packets(replayed)):
        assert not [obj for obj in shown if isinstance(obj, packets.ExecEnd)]


def test_a_stop_during_a_program_patch_ends_the_turn_after_its_write(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    """A Stop ends the program while its apply_patch call writes. The call's
    thread outlives the program; the turn ends, and its save starts, only
    after the write returns."""
    ended = _ended_turns(monkeypatch, sandbox)
    ref = chat.ref(db_session)
    writing, release_write = threading.Event(), threading.Event()
    write_file = sandbox.write_file

    def slow_write(*args: Any, **kwargs: Any) -> None:
        writing.set()
        assert release_write.wait(30)
        write_file(*args, **kwargs)

    monkeypatch.setattr(sandbox, "write_file", slow_write)
    ended_while_writing: list[list[HarnessSandboxRef]] = []

    roots: list[Run] = []
    start = Agent.start

    def start_and_keep_the_root(agent: Agent, *args: Any, **kwargs: Any) -> Run:
        run = start(agent, *args, **kwargs)
        if run.parent_run_id is None:
            roots.append(run)
        return run

    monkeypatch.setattr(Agent, "start", start_and_keep_the_root)

    def only_the_write_runs() -> bool:
        """The run's tool call and the program's driver have returned, and
        the run's events are delivered; the nested apply_patch call still
        writes."""
        # A foreground start returns once the run has ended.
        if not roots:
            return False
        names = [thread.name for thread in threading.enumerate()]
        delivery = roots[0].event_delivery
        return (
            roots[0].status.is_terminal
            and (delivery is None or not delivery.dispatcher.has_pending_events)
            and not any(
                name == "agent-operation" or name.startswith("code-mode-cell-")
                for name in names
            )
        )

    def release_later() -> None:
        assert writing.wait(30)
        _wait_until(only_the_write_runs)
        ended_while_writing.append(list(ended))
        release_write.set()

    releaser = threading.Thread(target=copy_context().run, args=(release_later,))
    releaser.start()
    join = _stop_when(chat, writing.is_set)
    llm = ChatLLM(
        [
            code_step(
                OPENAI_CODE_MODE, "code", f"await tools.apply_patch(input={ADD_A!r})"
            )
        ]
    )
    try:
        parts = chat.send(llm, code_mode=True)
    finally:
        join()
        releaser.join(timeout=60)

    assert _stops(parts) == ["user_cancelled"]
    # A patch has no result to keep: it renders as stopped (no end packet).
    [replayed] = chat.replayed(db_session)
    for shown in (_sandbox_packets(parts), _sandbox_packets(replayed)):
        assert not [obj for obj in shown if isinstance(obj, packets.ApplyPatchEnd)]
    assert ended_while_writing == [[]]
    _wait_until(lambda: ended == [ref])
    assert chat_turn_work.wait_idle(timeout=30)
    assert _files(node, ref) == {"a.txt": b"x\n"}


@pytest.mark.usefixtures("node")
def test_incognito_and_multi_model_turns_offer_no_sandbox(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, chat: SandboxChat
) -> None:
    def offered(llm: ChatLLM, *, multi_model: bool) -> list[str]:
        """Send a message; returns the tools of each model request."""
        monkeypatch.setattr(
            "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: llm
        )
        request = SendMessageRequest(
            message="Work.",
            chat_session_id=chat.chat_session_id,
            tool_options=ToolOptions(allowed=[]),
        )
        parts = (
            handle_multi_model_stream(
                new_msg_req=request,
                user=chat.user,
                llm_overrides=[
                    LLMOverride(model_version="a"),
                    LLMOverride(model_version="b"),
                ],
            )
            if multi_model
            else handle_stream_message_objects(new_msg_req=request, user=chat.user)
        )
        assert not [part for part in parts if isinstance(part, StreamingError)]
        return [str(request.get("tools")) for request in llm.requests]

    # Two models must not change one session directory at once.
    both = offered(
        ChatLLM([Delta(content="No sandbox."), Delta(content="No sandbox.")]),
        multi_model=True,
    )
    assert len(both) == 2
    assert all(EXEC_COMMAND_TOOL_NAME not in tools for tools in both)

    db_session.execute(
        update(ChatSession)
        .where(ChatSession.id == chat.chat_session_id)
        .values(incognito_record_mode=IncognitoRecordMode.USAGE_ONLY)
    )
    db_session.commit()
    try:
        [tools] = offered(ChatLLM([Delta(content="No sandbox.")]), multi_model=False)
        assert EXEC_COMMAND_TOOL_NAME not in tools
    finally:
        teardown_incognito_session(chat.chat_session_id)


@pytest.mark.usefixtures("node")
@pytest.mark.parametrize("origin", [MessageOrigin.SLACKBOT, MessageOrigin.DISCORDBOT])
def test_a_bot_turn_offers_no_sandbox(
    monkeypatch: pytest.MonkeyPatch, chat: SandboxChat, origin: MessageOrigin
) -> None:
    # Bots get no sandbox until they have service-account sandboxes.
    llm = ChatLLM([Delta(content="No sandbox.")])
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: llm
    )
    run_chat_turn(
        new_msg_req=SendMessageRequest(
            message="Work.",
            chat_session_id=chat.chat_session_id,
            tool_options=ToolOptions(allowed=[]),
            origin=origin,
        ),
        user=chat.user,
        approval_mode=ApprovalMode.NO_APPROVER,
    )
    [request] = llm.requests
    assert EXEC_COMMAND_TOOL_NAME not in str(request.get("tools"))


@pytest.mark.usefixtures("sandbox", "node")
def test_an_anonymous_turn_offers_no_sandbox(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    anonymous = get_anonymous_user()
    chat_session_id = create_chat_session(
        db_session, "anonymous sandbox", anonymous.id, persona_id=DEFAULT_PERSONA_ID
    ).id
    llm = ChatLLM([Delta(content="No sandbox.")])
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: llm
    )
    try:
        # One sandbox serves one user; anonymous visitors share one user.
        errors = [
            part.error
            for part in handle_stream_message_objects(
                new_msg_req=SendMessageRequest(
                    message="Work.",
                    chat_session_id=chat_session_id,
                    tool_options=ToolOptions(allowed=[]),
                ),
                user=anonymous,
            )
            if isinstance(part, StreamingError)
        ]
        assert errors == []
        [request] = llm.requests
        assert EXEC_COMMAND_TOOL_NAME not in str(request.get("tools"))
    finally:
        assert chat_turn_work.wait_idle(timeout=30)
        delete_chat_session(anonymous.id, chat_session_id, db_session, hard_delete=True)


# The tools


@pytest.mark.usefixtures("sandbox", "node")
def test_a_running_command_takes_input_polls_and_stops_through_write_stdin(
    monkeypatch: pytest.MonkeyPatch, make_tools: MakeTools
) -> None:
    monkeypatch.setattr(harness_sandbox, "POLL_MIN_YIELD_MS", 250)
    tools = make_tools()
    started, _ = _run(tools.exec_command, {"cmd": "cat", "yield_time_ms": 250})
    running = started.details
    assert isinstance(running, SandboxExecResult)
    session = running.session_id
    assert session is not None and running.exit_code is None
    assert f"Process running with session ID {session}\n" in started.content
    assert "Process exited" not in started.content

    echoed, progress = _run(
        tools.write_stdin, {"session_id": session, "chars": "hello"}
    )
    assert echoed.content.endswith("Output:\nhello")
    assert [update.details for update in progress] == [ExecOutputDelta(text="hello")]
    polled, _ = _run(tools.write_stdin, {"session_id": session})
    assert polled.content.endswith("Output:\n")

    stopped, _ = _run(tools.write_stdin, {"session_id": session, "chars": "\u0003"})
    ended = stopped.details
    assert isinstance(ended, SandboxExecResult)
    assert ended.completion == "canceled" and ended.session_id is None
    assert "Process ended: canceled\n" in stopped.content
    assert "session ID" not in stopped.content


@pytest.mark.usefixtures("sandbox", "node")
def test_the_live_output_of_a_call_stops_at_its_character_budget(
    make_tools: MakeTools,
) -> None:
    """The final output replaces the live preview, so the preview streams no
    more than the call's character budget (max_output_tokens, 4 characters a
    token)."""
    tools = make_tools()
    # The budget counts a multi-byte character as one and never splits it.
    text = "a" * 79 + "é" * 2 + "z" * 200
    result, progress = _run(
        tools.exec_command, {"cmd": f"echo {text}", "max_output_tokens": 20}
    )
    streamed = "".join(
        update.details.text
        for update in progress
        if isinstance(update.details, ExecOutputDelta)
    )
    assert streamed == "a" * 79 + "é"
    details = result.details
    assert isinstance(details, SandboxExecResult)
    # The card shows that the cut left output out.
    assert details.truncated
    assert details.output == (
        "a" * 40
        + "\n... [output truncated, 202 characters omitted] ...\n"
        + "z" * 39
        + "\n"
    )


@pytest.mark.usefixtures("sandbox", "node")
def test_the_claude_shell_runs_commands_by_its_own_arguments(
    monkeypatch: pytest.MonkeyPatch, make_tools: MakeTools
) -> None:
    """bash takes `command`; its `timeout` is how long the call waits, and
    `run_in_background` returns at once with the session ID while the
    command runs. write_stdin takes its wait as `timeout` too, and
    `description` changes nothing."""
    monkeypatch.setattr(harness_sandbox, "POLL_MIN_YIELD_MS", 250)
    tools = make_tools()
    assert tools.bash.name == "bash"
    bash = tools.bash.tool_definition().parameters["properties"]
    write = tools.bash_write_stdin.tool_definition().parameters["properties"]
    assert isinstance(bash, dict) and isinstance(write, dict)
    assert set(bash) == {"command", "timeout", "description", "run_in_background"}
    assert set(write) == {"session_id", "chars", "timeout"}
    done, _ = _run(tools.bash, {"command": "echo hi", "description": "Say hi"})
    assert isinstance(done.details, SandboxExecResult)
    assert done.details.exit_code == 0
    assert done.content.endswith("Output:\nhi\n")

    background, _ = _run(
        tools.bash, {"command": "cat", "run_in_background": True, "timeout": 30_000}
    )
    running = background.details
    assert isinstance(running, SandboxExecResult)
    assert running.session_id is not None and running.exit_code is None
    assert running.wall_time_seconds < 5
    echoed, _ = _run(
        tools.bash_write_stdin,
        {"session_id": running.session_id, "chars": "hello", "timeout": 250},
    )
    assert echoed.content.endswith("Output:\nhello")
    _run(tools.bash_write_stdin, {"session_id": running.session_id, "chars": "\u0003"})

    waited, _ = _run(tools.bash, {"command": "sleep 30", "timeout": 500})
    assert isinstance(waited.details, SandboxExecResult)
    assert waited.details.session_id is not None
    assert waited.details.wall_time_seconds < 5
    _run(
        tools.bash_write_stdin,
        {"session_id": waited.details.session_id, "chars": "\u0003"},
    )


@pytest.mark.usefixtures("node")
def test_a_numeric_session_id_keeps_the_exec_card(chat: SandboxChat) -> None:
    # Models may send the session ID as a number.
    llm = ChatLLM(
        [
            tool_step(WRITE_STDIN_TOOL_NAME, "poll", {"session_id": 123}),
            Delta(content="Done."),
        ]
    )
    parts = chat.send(llm)

    assert _sandbox_packets(parts) == [
        packets.WriteStdinStart(session_id="123", chars=""),
        packets.ExecEnd(error=str(ExecSessionNotFoundError("123"))),
        packets.SectionEnd(),
    ]

    # A program's poll passes chars as None; the card stays an exec card.
    llm = ChatLLM(
        [
            code_step(
                OPENAI_CODE_MODE,
                "code",
                "await tools.write_stdin(session_id='nope', yield_time_ms=1000)",
            ),
            Delta(content="Done."),
        ]
    )
    assert packets.WriteStdinStart(session_id="nope", chars="") in _sandbox_packets(
        chat.send(llm, code_mode=True)
    )


@pytest.mark.usefixtures("sandbox", "node")
def test_an_unknown_exec_session_is_a_tool_error(make_tools: MakeTools) -> None:
    # Models may send the session ID as a number.
    result, _ = _run(make_tools().write_stdin, {"session_id": 123, "chars": ""})
    assert result.is_error
    assert result.content == str(ExecSessionNotFoundError("123"))


@pytest.mark.usefixtures("sandbox")
def test_a_patch_at_the_command_cap_still_applies(
    node: RunningFakeAgent, make_tools: MakeTools
) -> None:
    tools = make_tools()
    # The file check is a daemon file call, not a command: the cap of
    # running commands does not stop it.
    node.agent.max_running_executions = 0
    result, _ = _run(tools.apply_patch, {"input": ADD_A})

    assert not result.is_error
    assert _files(node, tools.ref) == {"a.txt": b"x\n"}


@pytest.mark.parametrize(
    ("kill_error", "kept"),
    [
        (SandboxDaemonErrorReason.INTERNAL, True),
        (SandboxDaemonErrorReason.EXECUTION_NOT_FOUND, False),
    ],
    ids=["kill_failed", "command_gone"],
)
@pytest.mark.usefixtures("sandbox")
def test_a_stopped_call_keeps_its_command_reachable_only_when_the_kill_fails(
    tenant_cache: CacheBackend,
    node: RunningFakeAgent,
    make_tools: MakeTools,
    kill_error: SandboxDaemonErrorReason,
    kept: bool,
) -> None:
    tools = make_tools()
    ref = tools.ref
    node.agent.cancel_error = kill_error
    signal = CancellationSignal()
    invocation = ToolInvocation(
        call_id="call-1",
        arguments={"cmd": "cat", "yield_time_ms": 30_000},
        cancellation=signal,
        update=lambda _progress: None,
    )

    def stop() -> None:
        _wait_until(lambda: len(_running(node, ref, "cat")) == 1)
        signal.cancel()

    stopper = threading.Thread(target=stop)
    stopper.start()
    with cancellation_scope(signal), pytest.raises(AgentCancelled):
        tools.exec_command.run(invocation, ToolContext())
    stopper.join(timeout=10)

    assert len(node.agent.cancel_calls) == 1
    records = ExecSessionTable.model_validate_json(
        tenant_cache.get(EXEC_SESSIONS_PREFIX + str(ref.sandbox_id)) or b"{}"
    ).sessions
    if not kept:
        # The daemon has no such command, so its record goes.
        assert records == {}
        return
    # The command still runs, and write_stdin still reaches it.
    [session_id] = records
    node.agent.cancel_error = None
    polled, _ = _run(tools.write_stdin, {"session_id": session_id, "chars": "\u0003"})
    ended = polled.details
    assert isinstance(ended, SandboxExecResult)
    assert ended.completion == "canceled"


@pytest.mark.usefixtures("sandbox")
def test_a_patch_that_stages_too_many_bytes_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, node: RunningFakeAgent, make_tools: MakeTools
) -> None:
    monkeypatch.setattr(sandbox_tools, "APPLY_PATCH_MAX_STAGED_BYTES", 10)
    tools = make_tools()
    ref = tools.ref
    tools.turn.sandbox.ensure_running(ref)
    for name in ("a.txt", "b.txt"):
        node.agent.files[_key(ref, name)] = b"old line\n"
    result, _ = _run(
        tools.apply_patch,
        {
            "input": "*** Begin Patch\n"
            "*** Update File: a.txt\n@@\n-old line\n+new line\n"
            "*** Update File: b.txt\n@@\n-old line\n+new line\n"
            "*** End Patch"
        },
    )
    assert result.is_error
    assert "larger than 10 bytes in total" in result.content
    for name in ("a.txt", "b.txt"):
        assert node.agent.files[_key(ref, name)] == b"old line\n"


@pytest.mark.usefixtures("sandbox")
def test_a_patch_adds_updates_moves_and_deletes_files(
    node: RunningFakeAgent, make_tools: MakeTools
) -> None:
    tools = make_tools()
    ref = tools.ref
    tools.turn.sandbox.ensure_running(ref)
    agent = node.agent
    agent.files[_key(ref, "run.sh")] = b"a\nb\nc\n"
    agent.file_modes[_key(ref, "run.sh")] = 0o755
    agent.files[_key(ref, "tool.sh")] = b"old\n"
    agent.file_modes[_key(ref, "tool.sh")] = 0o700
    agent.files[_key(ref, "old.txt")] = b"x\r\ny\r\n"
    agent.files[_key(ref, "real/target.txt")] = b"t\n"
    agent.links[_key(ref, "link.txt")] = "real/target.txt"
    agent.links[_key(ref, "out.txt")] = "/etc/hosts"
    # Deletes read no content: binary and large files go too.
    agent.files[_key(ref, "image.bin")] = b"\xff\xfe\x00"
    agent.files[_key(ref, "big.log")] = b"x" * (
        sandbox_tools.FILE_TOOL_MAX_FILE_BYTES + 1
    )
    patch_text = (
        "*** Begin Patch\n"
        "*** Add File: new/dir/hello.txt\n"
        "+hi\n"
        "*** Add File: tool.sh\n"
        "+new\n"
        f"*** Update File: {session_workspace(ref.session_id)}/run.sh\n"
        "@@\n"
        " a\n"
        "-b\n"
        "+B\n"
        "*** Update File: old.txt\n"
        "*** Move to: moved/new.txt\n"
        "@@\n"
        "-x\n"
        "+z\n"
        "*** Delete File: link.txt\n"
        "*** Delete File: out.txt\n"
        "*** Delete File: image.bin\n"
        "*** Delete File: big.log\n"
        "*** End Patch"
    )
    result, _ = _run(tools.apply_patch, {"input": patch_text})

    assert result.content == (
        "Success. Updated the following files:\n"
        "A new/dir/hello.txt\nA tool.sh\nM run.sh\nM moved/new.txt\n"
        "D link.txt\nD out.txt\nD image.bin\nD big.log\n"
    )
    assert _files(node, ref) == {
        "new/dir/hello.txt": b"hi\n",
        "tool.sh": b"new\n",
        "run.sh": b"a\nB\nc\n",
        # Kept lines keep their endings; new lines use the file's first one.
        "moved/new.txt": b"z\r\ny\r\n",
        # A delete of a link removes the link, not its target.
        "real/target.txt": b"t\n",
    }
    assert agent.links == {}
    # An add over a file and an update keep the file's mode.
    assert agent.file_modes[_key(ref, "new/dir/hello.txt")] == 0o644
    assert agent.file_modes[_key(ref, "tool.sh")] == 0o700
    assert agent.file_modes[_key(ref, "run.sh")] == 0o755
    assert result.details == ApplyPatchResult(
        files=[
            ApplyPatchFileChange(path="new/dir/hello.txt", change="add"),
            ApplyPatchFileChange(path="tool.sh", change="add"),
            ApplyPatchFileChange(path="run.sh", change="update"),
            ApplyPatchFileChange(
                path="old.txt", change="update", move_path="moved/new.txt"
            ),
            ApplyPatchFileChange(path="link.txt", change="delete"),
            ApplyPatchFileChange(path="out.txt", change="delete"),
            ApplyPatchFileChange(path="image.bin", change="delete"),
            ApplyPatchFileChange(path="big.log", change="delete"),
        ]
    )


@pytest.mark.parametrize(
    ("patch_text", "error"),
    [
        (
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Update File: absent.py\n@@\n-a\n+b\n*** End Patch",
            "apply_patch verification failed: Failed to read file to update "
            "absent.py: No such file or directory",
        ),
        (
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Delete File: absent.py\n*** End Patch",
            "apply_patch verification failed: Failed to delete file absent.py: "
            "No such file or directory",
        ),
        (
            # Two spellings of one new file.
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Delete File: ./new.txt\n*** End Patch",
            "apply_patch verification failed: multiple operations target new.txt",
        ),
        (
            # Two paths of one existing file: through a directory link.
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Update File: here/keep.py\n@@\n-a\n+A\n"
            "*** Delete File: keep.py\n*** End Patch",
            "apply_patch verification failed: multiple operations target keep.py",
        ),
        (
            # Two paths of one new file: its directory through a link.
            "*** Begin Patch\n*** Add File: dir/new.txt\n+n\n"
            "*** Add File: alias/new.txt\n+n\n*** End Patch",
            "apply_patch verification failed: multiple operations target alias/new.txt",
        ),
        (
            # A patch never writes through a link.
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Add File: link.txt\n+l\n*** End Patch",
            "apply_patch verification failed: link.txt is a symbolic link to "
            "keep.py; edit that path instead",
        ),
        (
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Update File: link.txt\n@@\n-a\n+A\n*** End Patch",
            "apply_patch verification failed: link.txt is a symbolic link to "
            "keep.py; edit that path instead",
        ),
        (
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Update File: keep.py\n*** Move to: out.txt\n@@\n-a\n+A\n"
            "*** End Patch",
            "apply_patch verification failed: out.txt is a symbolic link to "
            "/etc/hosts; edit that path instead",
        ),
        (
            # A link on the way out of the session directory.
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Add File: uploads/new.txt\n+u\n*** End Patch",
            "apply_patch verification failed: uploads/new.txt goes through a "
            "link with an absolute target or one that leads outside the session "
            "directory",
        ),
        (
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Add File: /etc/passwd\n+root\n*** End Patch",
            "'/etc/passwd' is outside the working directory",
        ),
        (
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Add File: ../other/x.txt\n+x\n*** End Patch",
            "'../other/x.txt' leaves the working directory",
        ),
        (
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Update File: loop/x.txt\n@@\n-a\n+b\n*** End Patch",
            "apply_patch verification failed: loop/x.txt goes through too many "
            "symbolic links",
        ),
        (
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Delete File: dir\n*** End Patch",
            "apply_patch verification failed: Failed to delete file dir: it is a "
            "directory",
        ),
        (
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Update File: image.bin\n@@\n-a\n+b\n*** End Patch",
            "apply_patch verification failed: Failed to read file to update "
            "image.bin: the file is not UTF-8 text",
        ),
    ],
)
@pytest.mark.usefixtures("sandbox")
def test_a_patch_that_fails_verification_changes_nothing(
    node: RunningFakeAgent, make_tools: MakeTools, patch_text: str, error: str
) -> None:
    tools = make_tools()
    ref = tools.ref
    tools.turn.sandbox.ensure_running(ref)
    before = {
        _key(ref, "keep.py"): b"a\nb\n",
        _key(ref, "dir/inside.txt"): b"i\n",
        _key(ref, "image.bin"): b"\xff\xfe",
    }
    node.agent.files.update(before)
    node.agent.links[_key(ref, "out.txt")] = "/etc/hosts"
    node.agent.links[_key(ref, "link.txt")] = "keep.py"
    node.agent.links[_key(ref, "here")] = "."
    node.agent.links[_key(ref, "alias")] = "dir"
    node.agent.links[_key(ref, "uploads")] = "/mnt/user-uploads"
    node.agent.links[_key(ref, "loop")] = "loop2"
    node.agent.links[_key(ref, "loop2")] = "loop"
    links = dict(node.agent.links)
    # What os.Root reports through those links (its rules have Go tests).
    keep, directory = tools.turn.sandbox.stat_files(ref, ["keep.py", "dir"])
    assert keep.identity is not None and directory.identity is not None
    node.agent.path_stats.update(
        {
            _key(ref, "here/keep.py"): sandboxd_pb2.PathStat(
                target_type=sandboxd_pb2.FILE_TYPE_REGULAR,
                target_mode=0o644,
                device=keep.identity[0],
                inode=keep.identity[1],
            ),
            _key(ref, "alias"): sandboxd_pb2.PathStat(
                exists=True,
                type=sandboxd_pb2.FILE_TYPE_SYMLINK,
                link_target="dir",
                target_type=sandboxd_pb2.FILE_TYPE_DIRECTORY,
                target_mode=0o755,
                device=directory.identity[0],
                inode=directory.identity[1],
            ),
            _key(ref, "uploads/new.txt"): sandboxd_pb2.PathStat(
                target_error=sandboxd_pb2.STAT_ERROR_ESCAPES
            ),
            _key(ref, "loop/x.txt"): sandboxd_pb2.PathStat(
                target_error=sandboxd_pb2.STAT_ERROR_LOOP
            ),
        }
    )

    result, _ = _run(tools.apply_patch, {"input": patch_text})

    assert result.is_error
    assert result.content.startswith(error)
    assert _files(node, ref) == {key[2]: data for key, data in before.items()}
    assert node.agent.links == links


@pytest.mark.usefixtures("sandbox")
def test_a_patch_on_an_older_root_drive_says_that_it_updates_after_a_restart(
    node: RunningFakeAgent, make_tools: MakeTools
) -> None:
    tools = make_tools()
    tools.turn.sandbox.ensure_running(tools.ref)
    node.agent.stat_files_supported = False

    result, _ = _run(tools.apply_patch, {"input": ADD_A})

    assert result.is_error
    assert "older image" in result.content
    assert "updates after the sandbox restarts" in result.content
    assert _files(node, tools.ref) == {}


@pytest.mark.usefixtures("sandbox")
def test_a_stop_before_the_first_write_of_a_patch_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, node: RunningFakeAgent, make_tools: MakeTools
) -> None:
    tools = make_tools()
    ref = tools.ref
    tools.turn.sandbox.ensure_running(ref)
    node.agent.files[_key(ref, "keep.py")] = b"a\n"
    signal = CancellationSignal()
    read_file = tools.turn.sandbox.read_file

    def stopped_while_reading(*args: Any, **kwargs: Any) -> bytes:
        signal.cancel()
        return read_file(*args, **kwargs)

    monkeypatch.setattr(tools.turn.sandbox, "read_file", stopped_while_reading)
    invocation = ToolInvocation(
        call_id="call-1",
        arguments={
            "input": "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Update File: keep.py\n@@\n-a\n+A\n*** End Patch"
        },
        cancellation=signal,
        update=lambda _progress: None,
    )
    with pytest.raises(AgentCancelled):
        tools.apply_patch.run(invocation, ToolContext())

    assert _files(node, ref) == {"keep.py": b"a\n"}


@pytest.mark.usefixtures("sandbox", "node")
def test_a_failed_write_names_the_files_already_changed(
    monkeypatch: pytest.MonkeyPatch, make_tools: MakeTools
) -> None:
    tools = make_tools()
    write_file = FirecrackerHarnessSandbox.write_file

    def failing_write(
        sandbox: FirecrackerHarnessSandbox,
        ref: HarnessSandboxRef,
        path: str,
        data: bytes,
        *,
        mode: int = 0o644,
    ) -> None:
        if path == "b.txt":
            raise RuntimeError("disk full")
        write_file(sandbox, ref, path, data, mode=mode)

    monkeypatch.setattr(FirecrackerHarnessSandbox, "write_file", failing_write)
    result, _ = _run(
        tools.apply_patch,
        {
            "input": "*** Begin Patch\n*** Add File: a.txt\n+a\n"
            "*** Add File: b.txt\n+b\n*** Add File: c.txt\n+c\n*** End Patch"
        },
    )
    assert result.is_error
    assert result.content == (
        "apply_patch failed to change b.txt: disk full. Files already changed: a.txt."
    )


# The file tools of Claude models


class NamedChatLLM(ChatLLM):
    """A scripted chat model with a model name and deployment alias."""

    def __init__(
        self,
        steps: Sequence[Delta],
        *,
        model_name: str,
        deployment_name: str | None = None,
    ) -> None:
        super().__init__(steps)
        self.model_name = model_name
        self.deployment_name = deployment_name

    @property
    def config(self) -> LLMConfig:
        return super().config.model_copy(
            update={
                "model_name": self.model_name,
                "deployment_name": self.deployment_name,
            }
        )


@pytest.mark.parametrize(
    ("model_name", "deployment_name", "claude"),
    [
        # A gateway alias whose deployment is a Claude model.
        ("team-default", "anthropic/claude-opus-4-5", True),
        ("gpt-5.1", None, False),
    ],
)
@pytest.mark.usefixtures("node")
def test_claude_models_get_edit_and_write_and_others_apply_patch(
    chat: SandboxChat, model_name: str, deployment_name: str | None, claude: bool
) -> None:
    llm = NamedChatLLM(
        [Delta(content="Ready.")],
        model_name=model_name,
        deployment_name=deployment_name,
    )
    chat.send(llm)

    [request] = llm.requests
    offered = {tool["function"]["name"] for tool in request.get("tools") or []}
    file_tools = {EditTool.NAME, WriteTool.NAME}
    assert offered & (file_tools | {ApplyPatchTool.NAME}) == (
        file_tools if claude else {ApplyPatchTool.NAME}
    )
    # The file tools say that the user sees each change as a diff.
    descriptions = {
        tool["function"]["name"]: tool["function"]["description"]
        for tool in request.get("tools") or []
    }
    assert all(
        "The user sees the change as a diff." in descriptions[name]
        for name in (file_tools if claude else {ApplyPatchTool.NAME})
    )


@pytest.mark.usefixtures("node")
def test_edit_and_write_calls_render_patch_cards_live_and_on_replay(
    db_session: Session, node: RunningFakeAgent, chat: SandboxChat
) -> None:
    llm = ChatLLM(
        [
            tool_step(
                WriteTool.NAME, "create", {"file_path": "a.py", "content": "x = 1\n"}
            ),
            tool_step(
                EditTool.NAME,
                "edit",
                {"file_path": "a.py", "old_string": "x = 1", "new_string": "x = 2"},
            ),
            tool_step(
                WriteTool.NAME,
                "overwrite",
                {"file_path": "a.py", "content": "y = 3\n"},
            ),
            tool_step(
                EditTool.NAME,
                "missing",
                {"file_path": "a.py", "old_string": "zzz", "new_string": "q"},
            ),
            Delta(content="Done."),
        ],
        family=ToolFamily.CLAUDE,
    )
    parts = chat.send(llm)

    assert _files(node, chat.ref(db_session)) == {"a.py": b"y = 3\n"}
    assert last_tool_text(llm, "create") == "File created successfully at: a.py"
    assert last_tool_text(llm, "edit") == "The file a.py has been updated successfully."
    assert last_tool_text(llm, "overwrite") == (
        "The file a.py has been updated successfully."
    )
    not_found = "String to replace not found in file.\nString: zzz"
    assert last_tool_text(llm, "missing") == not_found
    added = "*** Begin Patch\n*** Add File: a.py\n+{}\n*** End Patch"
    expected = [
        packets.ApplyPatchStart(patch=added.format("x = 1"), tool_name=WriteTool.NAME),
        packets.ApplyPatchEnd(files=[ApplyPatchFileChange(path="a.py", change="add")]),
        packets.SectionEnd(),
        packets.ApplyPatchStart(
            patch="*** Begin Patch\n*** Update File: a.py\n@@\n-x = 1\n+x = 2\n"
            "*** End Patch",
            tool_name=EditTool.NAME,
        ),
        packets.ApplyPatchEnd(
            files=[ApplyPatchFileChange(path="a.py", change="update")]
        ),
        packets.SectionEnd(),
        # The end packet tells the overwrite from a new file.
        packets.ApplyPatchStart(patch=added.format("y = 3"), tool_name=WriteTool.NAME),
        packets.ApplyPatchEnd(
            files=[ApplyPatchFileChange(path="a.py", change="update")]
        ),
        packets.SectionEnd(),
        packets.ApplyPatchStart(
            patch="*** Begin Patch\n*** Update File: a.py\n@@\n-zzz\n+q\n*** End Patch",
            tool_name=EditTool.NAME,
        ),
        packets.ApplyPatchEnd(error=not_found),
        packets.SectionEnd(),
    ]
    # The streamed arguments report their progress live only, before each start.
    progress = [
        packets.FileToolProgress(tool_name=name, paths=["a.py"])
        for name in (WriteTool.NAME, EditTool.NAME, WriteTool.NAME, EditTool.NAME)
    ]
    assert _sandbox_packets(parts) == [
        packet
        for index, obj in enumerate(expected)
        for packet in ([progress[index // 3], obj] if index % 3 == 0 else [obj])
    ]
    [replayed] = chat.replayed(db_session)
    assert _sandbox_packets(replayed) == expected


@pytest.mark.usefixtures("node")
def test_a_program_edits_and_writes_files(
    db_session: Session, node: RunningFakeAgent, chat: SandboxChat
) -> None:
    program = (
        "print(await tools.write(file_path='a.txt', content='one\\ntwo\\n'))\n"
        "print(await tools.edit(file_path='a.txt', old_string='two', new_string='2'))\n"
        "try:\n"
        "    await tools.edit(file_path='a.txt', old_string='nope', new_string='x')\n"
        "except Exception as error:\n"
        "    print('raised:', error)\n"
    )
    llm = ChatLLM(
        [code_step(CLAUDE_CODE_MODE, "code", program), Delta(content="Done.")],
        family=ToolFamily.CLAUDE,
    )
    chat.send(llm, code_mode=True)

    text = last_tool_text(llm, "code")
    assert "File created successfully at: a.txt" in text
    assert "The file a.txt has been updated successfully." in text
    assert "raised: String to replace not found in file." in text
    assert _files(node, chat.ref(db_session)) == {"a.txt": b"one\n2\n"}


def test_file_calls_of_one_step_take_turns(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    """A write and an edit of the same file in one step both apply: the edit
    reads the file only after the write returns."""
    writing = threading.Event()
    statted_while_writing = threading.Event()
    stat_files, write_file = sandbox.stat_files, sandbox.write_file

    def watched_stat_files(*args: Any, **kwargs: Any) -> Any:
        if writing.is_set():
            statted_while_writing.set()
        return stat_files(*args, **kwargs)

    def slow_write(*args: Any, **kwargs: Any) -> None:
        writing.set()
        # Gives a concurrent edit the time to read the file first.
        statted_while_writing.wait(1)
        write_file(*args, **kwargs)
        writing.clear()

    monkeypatch.setattr(sandbox, "stat_files", watched_stat_files)
    monkeypatch.setattr(sandbox, "write_file", slow_write)
    [write_call] = tool_step(
        WriteTool.NAME, "write", {"file_path": "a.py", "content": "a = 1\n"}
    ).tool_calls
    [edit_call] = tool_step(
        EditTool.NAME,
        "edit",
        {"file_path": "a.py", "old_string": "a = 1", "new_string": "a = 2"},
    ).tool_calls
    llm = ChatLLM(
        [
            Delta(tool_calls=[write_call, edit_call.model_copy(update={"index": 1})]),
            Delta(content="Done."),
        ],
        family=ToolFamily.CLAUDE,
    )
    chat.send(llm)

    assert last_tool_text(llm, "edit") == "The file a.py has been updated successfully."
    assert _files(node, chat.ref(db_session)) == {"a.py": b"a = 2\n"}


@pytest.mark.usefixtures("sandbox")
def test_write_and_edit_create_change_and_keep_the_mode_of_files(
    node: RunningFakeAgent, make_tools: MakeTools
) -> None:
    tools = make_tools()
    ref = tools.ref
    tools.turn.sandbox.ensure_running(ref)
    agent = node.agent
    agent.files[_key(ref, "run.sh")] = b"echo a\necho b\n"
    agent.file_modes[_key(ref, "run.sh")] = 0o755

    created, _ = _run(
        tools.write, {"file_path": "new/dir/hello.txt", "content": "hi\n"}
    )
    edited, _ = _run(
        tools.edit,
        {
            "file_path": f"{session_workspace(ref.session_id)}/run.sh",
            "old_string": "echo b\n",
            "new_string": "echo B\necho C\n",
        },
    )
    # An empty old_string creates a file.
    started, _ = _run(
        tools.edit, {"file_path": "fresh.txt", "old_string": "", "new_string": "f"}
    )
    renamed, _ = _run(
        tools.edit,
        {
            "file_path": "new/dir/hello.txt",
            "old_string": "hi",
            "new_string": "yo",
            "replace_all": True,
        },
    )

    assert created.content == "File created successfully at: new/dir/hello.txt"
    assert edited.content == "The file run.sh has been updated successfully."
    assert started.details == ApplyPatchResult(
        files=[ApplyPatchFileChange(path="fresh.txt", change="add")]
    )
    assert renamed.content == (
        "The file new/dir/hello.txt has been updated. All occurrences were "
        "successfully replaced."
    )
    assert _files(node, ref) == {
        "new/dir/hello.txt": b"yo\n",
        "run.sh": b"echo a\necho B\necho C\n",
        "fresh.txt": b"f",
    }
    assert agent.file_modes[_key(ref, "run.sh")] == 0o755
    assert agent.file_modes[_key(ref, "new/dir/hello.txt")] == 0o644


@pytest.mark.parametrize(
    ("tool_name", "arguments", "error"),
    [
        (
            EditTool.NAME,
            {"file_path": "image.bin", "old_string": "a", "new_string": "q"},
            "Failed to read file to update image.bin: the file is not UTF-8 text",
        ),
        (
            EditTool.NAME,
            {"file_path": "link.txt", "old_string": "a", "new_string": "q"},
            "link.txt is a symbolic link to keep.py; edit that path instead",
        ),
        (
            WriteTool.NAME,
            {"file_path": "link.txt", "content": "q"},
            "link.txt is a symbolic link to keep.py; edit that path instead",
        ),
        (
            WriteTool.NAME,
            {"file_path": "../other/x.txt", "content": "q"},
            "'../other/x.txt' leaves the working directory",
        ),
    ],
)
@pytest.mark.usefixtures("sandbox")
def test_a_failed_edit_or_write_changes_nothing(
    node: RunningFakeAgent,
    make_tools: MakeTools,
    tool_name: str,
    arguments: dict[str, JsonValue],
    error: str,
) -> None:
    tools = make_tools()
    ref = tools.ref
    tools.turn.sandbox.ensure_running(ref)
    before = {_key(ref, "keep.py"): b"a\na\n", _key(ref, "image.bin"): b"\xff\xfe"}
    node.agent.files.update(before)
    node.agent.links[_key(ref, "link.txt")] = "keep.py"

    result, _ = _run(
        tools.edit if tool_name == EditTool.NAME else tools.write, arguments
    )

    assert result.is_error
    assert result.content.startswith(error)
    assert _files(node, ref) == {key[2]: data for key, data in before.items()}
    assert node.agent.links == {_key(ref, "link.txt"): "keep.py"}


# The turn


@pytest.mark.parametrize("code_mode", [False, True])
@pytest.mark.usefixtures("node")
def test_a_subagent_that_ends_during_a_root_call_leaves_the_turn_to_the_root(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    chat: SandboxChat,
    code_mode: bool,
) -> None:
    """Subagents share the root's sandbox tools. A subagent run whose work
    drains while the root's sandbox call runs ends no turn; the root's run
    ends it once."""
    monkeypatch.setattr("onyx.chat.agent.CODE_MODE_ENABLED", code_mode)
    ended = _ended_turns(monkeypatch, sandbox)
    child_drained = threading.Event()
    start = Agent.start

    def start_and_watch_children(agent: Agent, *args: Any, **kwargs: Any) -> Run:
        run = start(agent, *args, **kwargs)
        if run.parent_run_id is not None:
            run.add_idle_callback(child_drained.set)
        return run

    monkeypatch.setattr(Agent, "start", start_and_watch_children)
    exec_command = sandbox.exec_command
    ended_during_call: list[list[HarnessSandboxRef]] = []

    def exec_after_the_child(
        ref: HarnessSandboxRef, cmd: str, **kwargs: Any
    ) -> Iterator[ExecEvent]:
        # The call has started its turn; the child ends meanwhile.
        assert child_drained.wait(30)
        ended_during_call.append(list(ended))
        yield from exec_command(ref, cmd, **kwargs)

    monkeypatch.setattr(sandbox, "exec_command", exec_after_the_child)

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        texts = [message.text for message in request.messages]
        if "Task helper" in texts:
            return AssistantMessage(content=[TextContent(text="Helped.")])
        if any(isinstance(message, ToolResultMessage) for message in request.messages):
            return AssistantMessage(content=[TextContent(text="Done.")])
        return AssistantMessage(
            content=[
                ToolCall(
                    id="spawn",
                    name=SPAWN_AGENT_TOOL_NAME,
                    arguments={"task_name": "helper", "message": "Task helper"},
                ),
                ToolCall(
                    id="exec",
                    name=EXEC_TOOL_NAME if code_mode else EXEC_COMMAND_TOOL_NAME,
                    arguments={"code": "await tools.exec_command(cmd='echo hi')"}
                    if code_mode
                    else {"cmd": "echo hi"},
                ),
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
            tool_options=ToolOptions(allowed=[]),
            accepts_follow_ups=True,
        ),
        user=chat.user,
    ):
        pass
    assert chat_turn_work.wait_idle(timeout=30)

    assert child_drained.is_set()
    assert ended_during_call == [[]]
    assert ended == [chat.ref(db_session)]


@pytest.mark.usefixtures("node")
def test_each_end_of_a_used_turn_ends_it(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    make_tools: MakeTools,
) -> None:
    """`SandboxTurn.end` is the root chat agent's on_drained hook."""
    ended = _ended_turns(monkeypatch, sandbox)
    tools = make_tools()

    def busy() -> bool:
        return sandbox.is_busy(tenant_id=TENANT_ID, sandbox_id=tools.ref.sandbox_id)

    # A run without a call ends no turn.
    tools.turn.end()
    assert ended == []
    # A call renews the turn before it runs, so a failed call keeps the
    # sandbox busy until its run ends.
    assert _run(tools.write_stdin, {"session_id": "nope"})[0].is_error
    assert busy()
    tools.turn.end()
    assert not busy()

    # A later run's call renews the turn, and that run's end ends it again.
    assert not _run(tools.apply_patch, {"input": ADD_A})[0].is_error
    assert busy()
    tools.turn.end()
    assert not busy()
    assert ended == [tools.ref] * 2


@pytest.mark.usefixtures("node")
def test_a_call_renews_the_turn_before_it_runs_and_a_renewal_error_does_not_fail_it(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    make_tools: MakeTools,
) -> None:
    order: list[str] = []
    stat_files = sandbox.stat_files

    def failing_begin_turn(_ref: HarnessSandboxRef) -> None:
        order.append("renew")
        raise RuntimeError("cache unavailable")

    def recorded_stat_files(
        ref: HarnessSandboxRef, paths: Sequence[str]
    ) -> list[SandboxPathInfo]:
        order.append("stat")
        return stat_files(ref, paths)

    monkeypatch.setattr(sandbox, "begin_turn", failing_begin_turn)
    monkeypatch.setattr(sandbox, "stat_files", recorded_stat_files)
    result, _ = _run(make_tools().apply_patch, {"input": ADD_A})

    assert not result.is_error
    assert order == ["renew", "stat"]


# Availability


@pytest.mark.usefixtures("node")
@pytest.mark.parametrize("enabled", [True, False])
def test_every_agent_gets_the_sandbox_tools_when_harness_sandboxes_run(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    sandbox: FirecrackerHarnessSandbox,  # noqa: ARG001
    enabled: bool,
) -> None:
    monkeypatch.setattr(process_message, "HARNESS_SANDBOX_ENABLED", enabled)
    built: list[ChatAgent | DeepResearchAgent] = []
    create_chat_agent = execution.create_chat_agent

    def recorded_create_chat_agent(
        *args: Any, **kwargs: Any
    ) -> ChatAgent | DeepResearchAgent:
        agent = create_chat_agent(*args, **kwargs)
        built.append(agent)
        return agent

    monkeypatch.setattr(execution, "create_chat_agent", recorded_create_chat_agent)
    no_tools = upsert_persona(
        user=user,
        name=f"no tools {uuid4().hex[:8]}",
        description="",
        starter_messages=None,
        system_prompt=None,
        task_prompt=None,
        datetime_aware=None,
        is_public=False,
        tool_ids=[],
        db_session=db_session,
    )
    assert no_tools.tools == []
    for persona_id in (DEFAULT_PERSONA_ID, no_tools.id):
        chat_session_id = create_chat_session(
            db_session, "sandbox agent", user.id, persona_id=persona_id
        ).id
        llm = ChatLLM([Delta(content="Ready.")])
        send(chat_session_id, user, llm, "Work.", code_mode=False)
        [request] = llm.requests
        offered = {tool["function"]["name"] for tool in request.get("tools") or []}
        assert SANDBOX_NAMES & offered == (SANDBOX_NAMES if enabled else set())

    assert len(built) == 2
    for agent in built:
        tools = [tool for tool in agent.application_tools if tool.name in SANDBOX_NAMES]
        if enabled:
            # The three tools have no tool row; the root's runs end their turn.
            assert sorted(tool.name for tool in tools) == sorted(SANDBOX_NAMES)
            assert {tool.id for tool in tools} == {None}
            assert agent.on_drained is not None
        else:
            assert tools == []
            assert agent.on_drained is None


@pytest.mark.usefixtures("node", "sandbox")
def test_a_deep_research_turn_offers_no_sandbox(
    db_session: Session, user: User
) -> None:
    chat_session_id = create_chat_session(
        db_session, "research", user.id, persona_id=DEFAULT_PERSONA_ID
    ).id
    with (
        patch(
            "onyx.chat.process_message.get_llm_for_persona",
            return_value=ResearchCapableModel(),
        ),
        patch("onyx.chat.process_message.check_llm_cost_limit_for_provider"),
    ):
        setup = process_message.prepare_chat_turn(
            SendMessageRequest(
                message="Research the market",
                chat_session_id=chat_session_id,
                deep_research=True,
            ),
            user,
            llm_overrides=None,
        )
    try:
        assert not setup.sandbox_tools
        agent = execution.create_chat_agent(
            setup, user, 0, CancellationSignal(), False, with_subagents=False
        )
    finally:
        setup.admission.release()
    assert isinstance(agent, DeepResearchAgent)
    assert not {tool.name for tool in agent.application_tools} & SANDBOX_NAMES
    assert agent.on_drained is None


# The Sandbox row


def test_concurrent_first_calls_create_one_terminated_sandbox_row(
    db_session: Session, tenant_cache: CacheBackend, make_test_user: MakeTestUser
) -> None:
    user = make_test_user("sandbox_row_race")

    def get_or_create() -> UUID:
        with get_session_with_current_tenant() as session:
            return get_or_create_sandbox(session, user.id).id

    try:
        # Each worker gets the caller's context: the tenant of its sessions.
        with ThreadPoolExecutor(max_workers=8) as pool:
            calls = [pool.submit(copy_context().run, get_or_create) for _ in range(8)]
            ids = {call.result(timeout=30) for call in calls}
        [row] = db_session.scalars(select(Sandbox).where(Sandbox.user_id == user.id))
        assert ids == {row.id}
        assert row.status is SandboxStatus.TERMINATED
    finally:
        _forget_sandboxes(db_session, tenant_cache, user.id)


def test_a_first_call_waits_for_a_craft_reservation_of_the_row(
    db_session: Session, tenant_cache: CacheBackend, make_test_user: MakeTestUser
) -> None:
    """Craft finds no row under the user-row lock, then inserts its own; a
    chat call meanwhile waits for it and gets Craft's row."""
    user = make_test_user("sandbox_row_craft")

    def chat_call() -> UUID:
        with get_session_with_current_tenant() as session:
            return get_or_create_sandbox(session, user.id).id

    try:
        with get_session_with_current_tenant() as craft:
            fetch_user_by_id(craft, user.id, for_update=True)
            assert get_sandbox_by_user_id(craft, user.id) is None
            with ThreadPoolExecutor(max_workers=1) as pool:
                chat = pool.submit(copy_context().run, chat_call)
                time.sleep(0.5)
                assert not chat.done()
                craft_id = create_sandbox__no_commit(craft, user.id).id
                craft.commit()
                assert chat.result(timeout=10) == craft_id
    finally:
        _forget_sandboxes(db_session, tenant_cache, user.id)


# Chat session delete


def _wait_for_purges() -> None:
    _wait_until(
        lambda: (
            not any(
                thread.name == "fc-session-purge" for thread in threading.enumerate()
            )
        )
    )


def test_a_chat_delete_purges_the_session_directory_hard_or_soft(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    make_tools: MakeTools,
) -> None:
    monkeypatch.setattr(purge, "HARNESS_SANDBOX_ENABLED", True)
    refs: dict[str, HarnessSandboxRef] = {}
    for name in ("hard", "soft", "bulk"):
        chat_session = create_chat_session(db_session, name, user.id, persona_id=0)
        tools = make_tools(chat_session.id)
        assert not _run(tools.apply_patch, {"input": ADD_A})[0].is_error
        refs[name] = tools.ref
        assert _files(node, refs[name]) == {"a.txt": b"x\n"}
    unused = create_chat_session(db_session, "unused", user.id, persona_id=0)

    # A session that never used the sandbox costs no archive call; while the
    # VM runs, its tool results directory, which no record shows, goes.
    list_calls = node.agent.list_calls
    delete_chat_session_by_id(
        unused.id, hard_delete=True, user=user, db_session=db_session
    )
    _wait_for_purges()
    assert node.agent.list_calls == list_calls + 1

    delete_chat_session_by_id(
        refs["hard"].session_id, hard_delete=True, user=user, db_session=db_session
    )
    # No one can restore a soft-deleted chat, so its files go too.
    delete_chat_session_by_id(
        refs["soft"].session_id, hard_delete=False, user=user, db_session=db_session
    )
    _wait_for_purges()
    assert _files(node, refs["hard"]) == {}
    assert _files(node, refs["soft"]) == {}

    # A bulk delete purges only the chats it deleted.
    purged: list[UUID] = []
    purge_session = sandbox.purge_session

    def recorded_purge_session(*, session_id: UUID, **kwargs: Any) -> None:
        purged.append(session_id)
        purge_session(session_id=session_id, **kwargs)

    monkeypatch.setattr(sandbox, "purge_session", recorded_purge_session)
    delete_all_chat_sessions(user=user, db_session=db_session)
    # Teardown deletes the records that the purge thread still writes.
    _wait_for_purges()
    assert _files(node, refs["bulk"]) == {}
    assert purged == [refs["bulk"].session_id]


def test_a_bulk_delete_keeps_a_chat_created_while_it_runs(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, user: User
) -> None:
    """The delete and the purge cover the same chats: a chat that a concurrent
    request creates is neither deleted nor left unpurged."""
    first = create_chat_session(db_session, "first", user.id, persona_id=0).id
    created: list[UUID] = []
    delete_messages = db_chat.delete_messages_and_files_from_chat_session

    def delete_and_create(chat_session_id: UUID, session: Session) -> None:
        delete_messages(chat_session_id, session)
        with get_session_with_current_tenant() as other:
            created.append(create_chat_session(other, "new", user.id, 0).id)

    monkeypatch.setattr(
        db_chat, "delete_messages_and_files_from_chat_session", delete_and_create
    )
    assert delete_all_chat_sessions_for_user(user, db_session, hard_delete=True) == (
        [first],
        [],
    )
    db_session.expire_all()
    assert db_session.get(ChatSession, first) is None
    assert db_session.get(ChatSession, created[0]) is not None


# library_create_library_file


def _published_records(db_session: Session, chat_session_id: UUID) -> list[FileRecord]:
    """The published files of the chat session."""
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(FileRecord)
            .join(
                ChatArtifactVersion,
                ChatArtifactVersion.file_id == FileRecord.file_id,
            )
            .join(ChatArtifact, ChatArtifact.id == ChatArtifactVersion.artifact_id)
            .where(ChatArtifact.chat_session_id == chat_session_id)
        )
    )


def _remaining_file_ids(db_session: Session, file_ids: list[str]) -> list[str]:
    """The file IDs among `file_ids` that still have a file record."""
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(FileRecord.file_id).where(FileRecord.file_id.in_(file_ids))
        )
    )


def _answer_file_ids(db_session: Session, chat_session_id: UUID) -> list[str]:
    db_session.expire_all()
    [answer] = db_session.scalars(
        select(ChatMessage).where(
            ChatMessage.chat_session_id == chat_session_id,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
    )
    return [descriptor["id"] for descriptor in answer.files or []]


@pytest.mark.usefixtures("node", "initialize_file_store")
def test_published_files_stream_replay_belong_to_the_message_and_go_with_the_chat(
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    ref = chat.ref(db_session)
    sandbox.write_file(ref, "out/report.csv", b"a,b\n1,2\n")
    # A file in the Onyx directory outside the working directory.
    chart = f"{ONYX_VM_FILES_ROOT}/chart.svg"
    node.agent.files[(str(ref.sandbox_id), "", chart)] = b"<svg/>"
    report = f"{session_workspace(chat.chat_session_id)}/out/report.csv"
    llm = ChatLLM(
        [
            tool_step(
                LibraryCreateLibraryFileTool.NAME,
                "publish",
                {
                    "files": ["out/report.csv", chart],
                    "description": "The report and its chart.",
                },
            ),
            # Publishing a path again adds a version of its artifact.
            tool_step(
                LibraryCreateLibraryFileTool.NAME,
                "again",
                {"file": report, "title": "Report"},
            ),
            Delta(content="Done."),
        ]
    )
    parts = chat.send(llm)

    live = _sandbox_packets(parts)
    ends = [obj for obj in live if isinstance(obj, packets.PublishFilesEnd)]
    published = [file for end in ends for file in end.files]
    assert [
        (file.name, file.title, file.path, file.size, file.mime_type, file.version)
        for file in published
    ] == [
        ("report.csv", None, report, 8, "text/csv", 1),
        ("chart.svg", None, chart, 6, "image/svg+xml", 1),
        ("report.csv", "Report", report, 8, "text/csv", 2),
    ]
    assert len({file.file_id for file in published}) == 3
    assert published[0].artifact_id == published[2].artifact_id
    assert published[0].artifact_id != published[1].artifact_id
    assert live == [
        packets.PublishFilesStart(
            files=[
                PublishFileArgument(path="out/report.csv"),
                PublishFileArgument(path=chart),
            ],
            description="The report and its chart.",
        ),
        ends[0],
        packets.SectionEnd(),
        packets.PublishFilesStart(
            files=[PublishFileArgument(path=report, title="Report")]
        ),
        ends[1],
        packets.SectionEnd(),
    ]
    [replayed] = chat.replayed(db_session)
    assert _sandbox_packets(replayed) == live
    # The model gets each file's version and link.
    assert [
        (file.file_id, file.version_number, file.path, file.url)
        for file in ArtifactPublished.model_validate_json(
            last_tool_text(llm, "publish")
        ).files
    ] == [
        (
            file.file_id,
            1,
            file.display_path,
            artifact_url(file.artifact_id, 1),
        )
        for file in published[:2]
        if file.artifact_id is not None
    ]

    store = get_default_file_store()
    for file, data in zip(
        published, [b"a,b\n1,2\n", b"<svg/>", b"a,b\n1,2\n"], strict=True
    ):
        record = store.read_file_record(file.file_id)
        assert record.file_origin == FileOrigin.CHAT_ARTIFACT
        assert record.display_name == file.name
        assert record.file_metadata is None
        # The chat's file list and access read the artifact and its version.
        version = db_session.get_one(
            ChatArtifactVersion, (file.artifact_id, file.version)
        )
        artifact = db_session.get_one(ChatArtifact, file.artifact_id)
        assert (
            version.file_id,
            version.title,
            artifact.chat_session_id,
            artifact.path,
        ) == (file.file_id, file.title, chat.chat_session_id, file.path)
        assert store.read_file(file.file_id).read() == data
    # Packets carry the path to show; the saved details do not store it.
    assert [file.display_path for file in published] == [
        "out/report.csv",
        chart,
        "out/report.csv",
    ]
    saved_results = db_session.scalars(
        select(cast(ToolCallRecord.result, Text)).where(
            ToolCallRecord.chat_session_id == chat.chat_session_id
        )
    ).all()
    assert any(published[0].file_id in saved for saved in saved_results)
    assert not any("display_path" in saved for saved in saved_results)
    assert _answer_file_ids(db_session, chat.chat_session_id) == [
        file.file_id for file in published
    ]

    delete_chat_session_by_id(
        chat.chat_session_id, hard_delete=True, user=chat.user, db_session=db_session
    )
    assert _remaining_file_ids(db_session, [file.file_id for file in published]) == []


@pytest.mark.usefixtures("node", "initialize_file_store")
def test_everyone_who_can_read_the_chat_can_download_a_published_file(
    db_session: Session,
    user: User,
    sandbox: FirecrackerHarnessSandbox,
    make_tools: MakeTools,
    make_test_user: MakeTestUser,
) -> None:
    chat_session = create_chat_session(
        db_session, "published", user.id, persona_id=DEFAULT_PERSONA_ID
    )
    tools = make_tools(chat_session.id)
    sandbox.write_file(tools.ref, "report.md", b"# Report\n")
    result, _ = _run(tools.create_file, {"file": "report.md"})
    assert isinstance(result.details, PublishedFiles)
    [file] = result.details.files
    other = make_test_user("published_viewer")

    def download(reader: User) -> int:
        return fetch_chat_file(
            file.file_id,
            Request({"type": "http", "headers": []}),
            parsed=False,
            user=reader,
            db_session=db_session,
        ).status_code

    try:
        # No response saved the file yet: the artifact alone gives access.
        assert download(user) == 200
        with pytest.raises(OnyxError):
            download(other)
        assert not user_can_access_chat_file(file.file_id, other, db_session)
        chat_session.shared_status = ChatSessionSharedStatus.PUBLIC
        db_session.commit()
        assert download(other) == 200
    finally:
        get_default_file_store().delete_file(file.file_id)


def _thumbnail_ids(db_session: Session, name: str) -> list[str]:
    """The thumbnail records of published files named `name`."""
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(FileRecord.file_id).where(
                FileRecord.file_origin == FileOrigin.CHAT_ARTIFACT_THUMBNAIL,
                FileRecord.display_name == f"{name} thumbnail",
            )
        )
    )


@pytest.mark.usefixtures("initialize_file_store")
def test_a_published_document_gets_a_thumbnail_with_the_chat_access_and_delete(
    db_session: Session,
    user: User,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    make_tools: MakeTools,
    make_test_user: MakeTestUser,
) -> None:
    """A PDF, a deck and a Word file each get a JPEG of their first page, also
    under the Onyx directory, which reads with the file's chat access and goes
    with the chat's hard delete. A markdown file gets none."""
    chat_session = create_chat_session(
        db_session, "thumbnails", user.id, persona_id=DEFAULT_PERSONA_ID
    )
    tools = make_tools(chat_session.id)
    sandbox.write_file(tools.ref, "out/report.pdf", b"%PDF-1.7 report")
    sandbox.write_file(tools.ref, "out/q3.deck.pptx", b"deck")
    sandbox.write_file(tools.ref, "memo.docx", b"memo")
    sandbox.write_file(tools.ref, "notes.md", b"# Notes\n")
    # A file in the Onyx directory outside the working directory.
    chart = f"{ONYX_VM_FILES_ROOT}/chart.pdf"
    node.agent.files[(str(tools.ref.sandbox_id), "", chart)] = b"%PDF-1.7 chart"

    result, _ = _run(
        tools.create_file,
        {
            "files": [
                "out/report.pdf",
                "out/q3.deck.pptx",
                "memo.docx",
                chart,
                "notes.md",
            ]
        },
    )

    assert isinstance(result.details, PublishedFiles)
    pdf, deck, memo, chart_file, notes = result.details.files
    assert notes.thumbnail_file_id is None
    thumbnail_ids = [
        file.thumbnail_file_id
        for file in (pdf, deck, memo, chart_file)
        if file.thumbnail_file_id is not None
    ]
    assert len(set(thumbnail_ids)) == 4
    store = get_default_file_store()
    for thumbnail_id in thumbnail_ids:
        record = store.read_file_record(thumbnail_id)
        assert (record.file_origin, record.file_type) == (
            FileOrigin.CHAT_ARTIFACT_THUMBNAIL,
            "image/jpeg",
        )
        assert store.read_file(thumbnail_id).read() == FAKE_JPEG
    assert [
        file.thumbnail_file_id
        for file in get_chat_published_files(chat_session.id, db_session)
    ] == [*thumbnail_ids, None]

    # Office files convert to a PDF in a scratch directory of their own,
    # which the render deletes.
    commands = [
        execution
        for execution in node.agent.executions[str(tools.ref.sandbox_id)].values()
        if execution.argv[0] in ("soffice", "pdftoppm")
    ]
    workspace = session_workspace(chat_session.id)
    assert [
        (
            execution.argv[0],
            execution.argv[-2 if execution.argv[0] == "pdftoppm" else -1],
        )
        for execution in commands
    ] == [
        ("pdftoppm", f"{workspace}/out/report.pdf"),
        ("soffice", f"{workspace}/out/q3.deck.pptx"),
        (
            "pdftoppm",
            f"{commands[1].argv[commands[1].argv.index('--outdir') + 1]}/q3.deck.pdf",
        ),
        ("soffice", f"{workspace}/memo.docx"),
        (
            "pdftoppm",
            f"{commands[3].argv[commands[3].argv.index('--outdir') + 1]}/memo.pdf",
        ),
        ("pdftoppm", chart),
    ]
    assert all(
        execution.env == {"SAL_USE_VCLPLUGIN": "svp"}
        and execution.argv[1].startswith(
            f"-env:UserInstallation=file://{RENDER_FIRST_PAGE_ROOT}/"
        )
        for execution in commands
        if execution.argv[0] == "soffice"
    )
    assert not any(
        key[2].startswith(RENDER_FIRST_PAGE_ROOT + "/") for key in node.agent.files
    )

    other = make_test_user("thumbnail_viewer")
    assert user_can_access_chat_file(thumbnail_ids[0], user, db_session)
    assert not user_can_access_chat_file(thumbnail_ids[0], other, db_session)
    chat_session.shared_status = ChatSessionSharedStatus.PUBLIC
    db_session.commit()
    assert user_can_access_chat_file(thumbnail_ids[0], other, db_session)

    delete_chat_session_by_id(
        chat_session.id, hard_delete=True, user=user, db_session=db_session
    )
    assert _remaining_file_ids(db_session, thumbnail_ids) == []


@pytest.mark.usefixtures("node", "initialize_file_store")
def test_a_chat_delete_deletes_the_thumbnail_of_a_file_that_its_message_lists(
    db_session: Session, sandbox: FirecrackerHarnessSandbox, chat: SandboxChat
) -> None:
    """The delete of a file that the saved message lists also removes its
    version, which links the thumbnail; the thumbnail goes all the same."""
    sandbox.write_file(chat.ref(db_session), "report.pdf", b"%PDF-1.7 report")
    chat.send(
        ChatLLM(
            [
                tool_step(
                    LibraryCreateLibraryFileTool.NAME,
                    "publish",
                    {"file": "report.pdf"},
                ),
                Delta(content="Done."),
            ]
        )
    )
    [version] = db_session.scalars(
        select(ChatArtifactVersion)
        .join(ChatArtifact, ChatArtifact.id == ChatArtifactVersion.artifact_id)
        .where(ChatArtifact.chat_session_id == chat.chat_session_id)
    )
    assert version.thumbnail_file_id is not None
    assert _answer_file_ids(db_session, chat.chat_session_id) == [version.file_id]
    file_ids = [version.file_id, version.thumbnail_file_id]

    delete_chat_session_by_id(
        chat.chat_session_id, hard_delete=True, user=chat.user, db_session=db_session
    )

    assert _remaining_file_ids(db_session, file_ids) == []


@pytest.mark.usefixtures("node", "initialize_file_store")
def test_a_failed_thumbnail_delete_keeps_the_file_for_the_next_chat_delete(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    chat: SandboxChat,
) -> None:
    """A thumbnail goes before its file, so a failed thumbnail delete keeps
    the file and its version's link, and the next hard delete removes both."""
    sandbox.write_file(chat.ref(db_session), "report.pdf", b"%PDF-1.7 report")
    chat.send(
        ChatLLM(
            [
                tool_step(
                    LibraryCreateLibraryFileTool.NAME,
                    "publish",
                    {"file": "report.pdf"},
                ),
                Delta(content="Done."),
            ]
        )
    )
    [version] = db_session.scalars(
        select(ChatArtifactVersion)
        .join(ChatArtifact, ChatArtifact.id == ChatArtifactVersion.artifact_id)
        .where(ChatArtifact.chat_session_id == chat.chat_session_id)
    )
    file_id, thumbnail_id = version.file_id, version.thumbnail_file_id
    assert thumbnail_id is not None
    store_type = type(get_default_file_store())
    delete_file = store_type.delete_file
    store_down = [True]

    def failing_delete(self: Any, file_id: str, *args: Any, **kwargs: Any) -> None:
        if store_down[0] and file_id == thumbnail_id:
            raise RuntimeError("the file store is down")
        delete_file(self, file_id, *args, **kwargs)

    monkeypatch.setattr(store_type, "delete_file", failing_delete)
    with pytest.raises(RuntimeError, match="the file store is down"):
        delete_chat_session_by_id(
            chat.chat_session_id,
            hard_delete=True,
            user=chat.user,
            db_session=db_session,
        )
    db_session.rollback()

    assert sorted(_remaining_file_ids(db_session, [file_id, thumbnail_id])) == sorted(
        [file_id, thumbnail_id]
    )
    assert (
        db_session.scalar(
            select(ChatArtifactVersion.thumbnail_file_id).where(
                ChatArtifactVersion.file_id == file_id
            )
        )
        == thumbnail_id
    )

    store_down[0] = False
    delete_chat_session_by_id(
        chat.chat_session_id, hard_delete=True, user=chat.user, db_session=db_session
    )
    assert _remaining_file_ids(db_session, [file_id, thumbnail_id]) == []


@pytest.mark.usefixtures("node", "initialize_file_store")
def test_a_failed_publish_keeps_a_file_whose_thumbnail_delete_fails(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    sandbox: FirecrackerHarnessSandbox,
    make_tools: MakeTools,
) -> None:
    """The clean-up of a failed publish deletes a thumbnail before its file.
    When the thumbnail delete fails, the file, its version and its artifact
    stay, and the hard chat delete removes them."""
    chat_session = create_chat_session(
        db_session, "published", user.id, persona_id=DEFAULT_PERSONA_ID
    )
    tools = make_tools(chat_session.id)
    first = f"{uuid4().hex}.pdf"
    sandbox.write_file(tools.ref, first, b"%PDF-1.7 report")
    store_type = type(get_default_file_store())
    delete_file = store_type.delete_file
    store_down = [True]

    def failing_delete(self: Any, file_id: str, *args: Any, **kwargs: Any) -> None:
        if store_down[0] and file_id in _thumbnail_ids(db_session, first):
            raise RuntimeError("the file store is down")
        delete_file(self, file_id, *args, **kwargs)

    monkeypatch.setattr(store_type, "delete_file", failing_delete)

    result, _ = _run(tools.create_file, {"files": [first, "missing.md"]})

    assert result.is_error
    [thumbnail_id] = _thumbnail_ids(db_session, first)
    [version] = db_session.scalars(
        select(ChatArtifactVersion)
        .join(ChatArtifact, ChatArtifact.id == ChatArtifactVersion.artifact_id)
        .where(ChatArtifact.chat_session_id == chat_session.id)
    )
    assert version.thumbnail_file_id == thumbnail_id
    assert sorted(_remaining_file_ids(db_session, [version.file_id, thumbnail_id])) == (
        sorted([version.file_id, thumbnail_id])
    )

    store_down[0] = False
    delete_chat_session_by_id(
        chat_session.id, hard_delete=True, user=user, db_session=db_session
    )
    assert _remaining_file_ids(db_session, [version.file_id, thumbnail_id]) == []


@pytest.mark.usefixtures("node", "initialize_file_store")
def test_a_file_that_does_not_render_publishes_without_a_thumbnail(
    db_session: Session,
    user: User,
    sandbox: FirecrackerHarnessSandbox,
    make_tools: MakeTools,
) -> None:
    tools = make_tools(
        create_chat_session(
            db_session, "thumbnails", user.id, persona_id=DEFAULT_PERSONA_ID
        ).id
    )
    # The fake pdftoppm reads only a file that starts with "%PDF".
    name = f"{uuid4().hex}.pdf"
    sandbox.write_file(tools.ref, name, b"not a pdf")

    result, _ = _run(tools.create_file, {"file": name})

    assert not result.is_error
    assert isinstance(result.details, PublishedFiles)
    [file] = result.details.files
    assert file.thumbnail_file_id is None
    [record] = _published_records(db_session, tools.ref.session_id)
    assert record.file_id == file.file_id
    assert _thumbnail_ids(db_session, name) == []


@pytest.mark.usefixtures("node", "initialize_file_store")
@pytest.mark.parametrize(
    ("path", "error"),
    [
        ("missing.md", "'missing.md' does not exist"),
        ("out", "out is not a regular file"),
        (f"{ONYX_VM_FILES_ROOT}/dir", "is not a regular file"),
        ("big.bin", "'big.bin' is larger than the limit of 16 bytes"),
        (
            "/tmp/chart.svg",
            "'/tmp/chart.svg' is not in the working directory or under "
            f"{ONYX_VM_FILES_ROOT}; copy the file into the working directory first",
        ),
    ],
)
def test_a_publish_that_fails_on_one_file_publishes_none(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    make_tools: MakeTools,
    path: str,
    error: str,
    user: User,
) -> None:
    monkeypatch.setattr(artifact_operations, "PUBLISH_FILES_MAX_BYTES", 16)
    tools = make_tools(
        create_chat_session(
            db_session, "published", user.id, persona_id=DEFAULT_PERSONA_ID
        ).id
    )
    # It renders: the fake pdftoppm reads a file that starts with "%PDF".
    first = f"{uuid4().hex}.pdf"
    sandbox.write_file(tools.ref, first, b"%PDF")
    sandbox.write_file(tools.ref, "out/a.txt", b"a")
    sandbox.write_file(tools.ref, "big.bin", b"x" * 17)
    for vm_path in ("/tmp/chart.svg", f"{ONYX_VM_FILES_ROOT}/dir/a.svg"):
        node.agent.files[(str(tools.ref.sandbox_id), "", vm_path)] = b"<svg/>"

    result, _ = _run(tools.create_file, {"files": [first, path]})

    assert result.is_error
    assert result.text.endswith(error)
    # The file that the call copied first is deleted again, with its
    # thumbnail and its artifact.
    assert _published_records(db_session, tools.ref.session_id) == []
    assert any(
        execution.argv[0] == "pdftoppm" and execution.argv[-2].endswith(f"/{first}")
        for execution in node.agent.executions[str(tools.ref.sandbox_id)].values()
    )
    assert _thumbnail_ids(db_session, first) == []
    assert (
        db_session.scalars(
            select(ChatArtifact.id).where(
                ChatArtifact.chat_session_id == tools.ref.session_id
            )
        ).all()
        == []
    )


@pytest.mark.usefixtures("node", "initialize_file_store")
def test_a_publish_sends_the_indexing_task_of_each_artifact(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    make_tools: MakeTools,
    user: User,
) -> None:
    tools = make_tools(
        create_chat_session(
            db_session, "indexed", user.id, persona_id=DEFAULT_PERSONA_ID
        ).id
    )
    sandbox.write_file(tools.ref, "a.md", b"a")
    sandbox.write_file(tools.ref, "b.md", b"b")
    send_task = MagicMock()
    monkeypatch.setattr(client_app, "send_task", send_task)

    result, _ = _run(tools.create_file, {"files": ["a.md", "b.md"]})

    assert isinstance(result.details, PublishedFiles)
    artifact_ids = [file.artifact_id for file in result.details.files]
    try:
        assert send_task.mock_calls == [
            call(
                OnyxCeleryTask.PROCESS_SINGLE_CHAT_ARTIFACT,
                kwargs={
                    "artifact_id": str(artifact_id),
                    "tenant_id": POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
                },
                queue=OnyxCeleryQueues.USER_FILE_PROCESSING,
                priority=OnyxCeleryPriority.HIGH,
                expires=CELERY_USER_FILE_PROCESSING_TASK_EXPIRES,
            )
            for artifact_id in artifact_ids
        ]
    finally:
        cache = get_cache_backend()
        for artifact_id in artifact_ids:
            if artifact_id is not None:
                cache.delete(chat_artifact_queued_key(artifact_id))


@pytest.mark.usefixtures(
    "node", "initialize_file_store", "full_deployment_setup", "fake_embeddings"
)
def test_a_failed_publish_takes_an_artifact_indexed_meanwhile_out_of_the_index(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    make_tools: MakeTools,
    user: User,
) -> None:
    """The indexing beat indexes the call's first file before its second
    file fails; the call's clean-up deletes that artifact's document."""
    monkeypatch.setattr(artifact_operations, "PUBLISH_FILES_MAX_BYTES", 16)
    tools = make_tools(
        create_chat_session(
            db_session, "unpublished", user.id, persona_id=DEFAULT_PERSONA_ID
        ).id
    )
    sandbox.write_file(tools.ref, "a.md", b"Pelicans")
    sandbox.write_file(tools.ref, "big.bin", b"x" * 17)
    indexed_ids: list[UUID] = []
    save = artifact_operations.save_chat_artifact
    document_index = build_opensearch_document_index(
        get_current_search_settings(db_session)
    )

    def indexed() -> bool:
        """Whether the PRESENT index holds the document, after a refresh."""
        return bool(document_index.get_documents_with_any_chunk([str(indexed_ids[0])]))

    def save_then_index(*args: Any, **kwargs: Any) -> PublishedFile:
        published = save(*args, **kwargs)
        if published.artifact_id is None:
            raise RuntimeError("save_chat_artifact always sets the artifact")
        process_single_chat_artifact.run(
            artifact_id=str(published.artifact_id),  # ty: ignore[invalid-argument-type]
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,  # ty: ignore[invalid-argument-type]
        )
        indexed_ids.append(published.artifact_id)
        if not indexed():
            raise RuntimeError("the beat's write did not land")
        return published

    monkeypatch.setattr(artifact_operations, "save_chat_artifact", save_then_index)
    try:
        result, _ = _run(tools.create_file, {"files": ["a.md", "big.bin"]})

        assert result.is_error
        assert result.text.endswith("'big.bin' is larger than the limit of 16 bytes")
        assert len(indexed_ids) == 1
        assert not indexed()
    finally:
        delete_chat_artifacts_from_index(indexed_ids)


@pytest.mark.usefixtures("node", "initialize_file_store")
def test_a_paged_chat_load_lists_the_latest_version_of_each_artifact(
    db_session: Session, sandbox: FirecrackerHarnessSandbox, chat: SandboxChat
) -> None:
    """A first answer publishes a report and a chart. A later answer's code
    mode program publishes the report's path again. A load of only the latest
    message lists the report's second version and the chart, by first
    publish, each with its path and title."""
    try:
        ref = chat.ref(db_session)
        sandbox.write_file(ref, "report.md", b"# Draft\n")
        sandbox.write_file(ref, "chart.svg", b"<svg/>")
        chat.send(
            ChatLLM(
                [
                    tool_step(
                        LibraryCreateLibraryFileTool.NAME,
                        "publish",
                        {"files": ["report.md", "chart.svg"]},
                    ),
                    Delta(content="Done."),
                ]
            )
        )
        sandbox.write_file(ref, "report.md", b"# Final report\n")
        parts = chat.send(
            ChatLLM(
                [
                    code_step(
                        OPENAI_CODE_MODE,
                        "code",
                        "print(await tools.library__create_library_file(file='report.md'))\n",
                    ),
                    Delta(content="Done."),
                ]
            ),
            code_mode=True,
        )
        [live_end] = [
            obj
            for obj in _sandbox_packets(parts)
            if isinstance(obj, packets.PublishFilesEnd)
        ]
        # The path to show is relative to the chat's working directory.
        assert [file.display_path for file in live_end.files] == ["report.md"]

        db_session.expire_all()
        first_answer, last_answer = db_session.scalars(
            select(ChatMessage)
            .where(
                ChatMessage.chat_session_id == chat.chat_session_id,
                ChatMessage.message_type == MessageType.ASSISTANT,
            )
            .order_by(ChatMessage.id)
        ).all()
        detail = get_chat_session(
            session_id=chat.chat_session_id,
            limit=1,
            user=chat.user,
            db_session=db_session,
        )

        assert first_answer.id not in {
            message.message_id for message in detail.messages
        }
        workspace = session_workspace(chat.chat_session_id)
        assert detail.published_files is not None
        assert [
            (file.name, file.title, file.path, file.size, file.mime_type)
            for file in detail.published_files
        ] == [
            ("report.md", None, f"{workspace}/report.md", 15, "text/markdown"),
            ("chart.svg", None, f"{workspace}/chart.svg", 6, "image/svg+xml"),
        ]
        assert [file.display_path for file in detail.published_files] == [
            "report.md",
            "chart.svg",
        ]
        assert [
            (file.file_id, file.artifact_id, file.version)
            for file in detail.published_files
        ] == [
            ((last_answer.files or [])[0]["id"], live_end.files[0].artifact_id, 2),
            ((first_answer.files or [])[1]["id"], ANY, 1),
        ]
    finally:
        delete_chat_session_by_id(
            chat.chat_session_id,
            hard_delete=True,
            user=chat.user,
            db_session=db_session,
        )


@pytest.mark.usefixtures("node", "initialize_file_store")
def test_a_program_publishes_files_that_belong_to_the_message(
    db_session: Session, sandbox: FirecrackerHarnessSandbox, chat: SandboxChat
) -> None:
    sandbox.write_file(chat.ref(db_session), "report.md", b"# Report\n")
    llm = ChatLLM(
        [
            code_step(
                OPENAI_CODE_MODE,
                "code",
                "print(await tools.library__create_library_file(file='report.md'))\n",
            ),
            Delta(content="Done."),
        ]
    )
    chat.send(llm, code_mode=True)

    # The program gets the publish result as a dict.
    assert "{'files': [{'library_file_id': " in last_tool_text(llm, "code")
    [cell] = saved_cells(db_session, chat.chat_session_id)
    [call] = cell.calls
    assert isinstance(call.details, PublishedFiles)
    [file] = call.details.files
    assert _answer_file_ids(db_session, chat.chat_session_id) == [file.file_id]
    delete_chat_session_by_id(
        chat.chat_session_id, hard_delete=True, user=chat.user, db_session=db_session
    )


@pytest.mark.usefixtures("node", "initialize_file_store")
def test_the_non_streaming_response_lists_published_files(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    chat: SandboxChat,
) -> None:
    sandbox.write_file(chat.ref(db_session), "report.md", b"# Report\n")
    llm = ChatLLM(
        [
            tool_step(
                LibraryCreateLibraryFileTool.NAME, "publish", {"file": "report.md"}
            ),
            Delta(content="Done."),
        ]
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: llm
    )
    monkeypatch.setattr("onyx.chat.agent.CODE_MODE_ENABLED", False)

    response = run_chat_turn(
        new_msg_req=SendMessageRequest(
            message="Work.",
            chat_session_id=chat.chat_session_id,
            tool_options=ToolOptions(allowed=[]),
        ),
        user=chat.user,
    )

    [call] = response.tool_calls
    [file_id] = _answer_file_ids(db_session, chat.chat_session_id)
    assert call.published_files == [
        PublishedFile(
            file_id=file_id,
            artifact_id=db_session.scalars(
                select(ChatArtifactVersion.artifact_id).where(
                    ChatArtifactVersion.file_id == file_id
                )
            ).one(),
            version=1,
            chat_id=chat.chat_session_id,
            name="report.md",
            path=f"{session_workspace(chat.chat_session_id)}/report.md",
            size=9,
            mime_type="text/markdown",
        )
    ]
    delete_chat_session_by_id(
        chat.chat_session_id, hard_delete=True, user=chat.user, db_session=db_session
    )


@pytest.mark.usefixtures("node", "initialize_file_store")
def test_a_publish_in_the_step_of_a_patch_publishes_the_patched_file(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    chat: SandboxChat,
) -> None:
    write_file = sandbox.write_file
    read_file = sandbox.read_file
    publish_read = threading.Event()

    def recorded_read(*args: Any, **kwargs: Any) -> bytes:
        publish_read.set()
        return read_file(*args, **kwargs)

    def write_after_any_read(*args: Any, **kwargs: Any) -> None:
        # Holds the patch's write while a publish beside it would read; the
        # publish runs after the write, so it never reads during the wait.
        assert not publish_read.wait(timeout=1)
        write_file(*args, **kwargs)

    monkeypatch.setattr(sandbox, "read_file", recorded_read)
    monkeypatch.setattr(sandbox, "write_file", write_after_any_read)
    llm = ChatLLM(
        [
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        id=call_id,
                        index=index,
                        function=ResponseFunctionCall(
                            name=name, arguments=json.dumps(arguments)
                        ),
                    )
                    for index, (call_id, name, arguments) in enumerate(
                        [
                            ("patch", ApplyPatchTool.NAME, {"input": ADD_A}),
                            (
                                "publish",
                                LibraryCreateLibraryFileTool.NAME,
                                {"file": "a.txt"},
                            ),
                        ]
                    )
                ]
            ),
            Delta(content="Done."),
        ]
    )
    chat.send(llm)

    # The file tools take turns, so the publish sees the patch's file.
    [record] = _published_records(db_session, chat.chat_session_id)
    [file] = ArtifactPublished.model_validate_json(last_tool_text(llm, "publish")).files
    assert file.file_id == record.file_id
    assert get_default_file_store().read_file(record.file_id).read() == b"x\n"
    delete_chat_session_by_id(
        chat.chat_session_id, hard_delete=True, user=chat.user, db_session=db_session
    )


@pytest.mark.usefixtures("node", "initialize_file_store")
def test_a_later_turn_reads_no_text_of_published_files(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    chat: SandboxChat,
) -> None:
    sandbox.write_file(chat.ref(db_session), "report.csv", b"a,b\n1,2\n")
    chat.send(
        ChatLLM(
            [
                tool_step(
                    LibraryCreateLibraryFileTool.NAME,
                    "publish",
                    {"file": "report.csv"},
                ),
                Delta(content="Done."),
            ]
        )
    )
    [record] = _published_records(db_session, chat.chat_session_id)
    extracted: list[str] = []
    extract_file_text = chat_files.extract_file_text

    def recorded_extract_file_text(**kwargs: Any) -> str:
        extracted.append(kwargs["file_name"])
        return extract_file_text(**kwargs)

    monkeypatch.setattr(chat_files, "extract_file_text", recorded_extract_file_text)

    chat.send(ChatLLM([Delta(content="Still done.")]))

    assert extracted == []
    db_session.expire_all()
    assert (
        db_session.get(FileRecord, plaintext_file_name_for_id(record.file_id)) is None
    )
    delete_chat_session_by_id(
        chat.chat_session_id, hard_delete=True, user=chat.user, db_session=db_session
    )


@pytest.mark.usefixtures("node", "initialize_file_store")
def test_a_stop_during_the_last_copy_publishes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    make_tools: MakeTools,
    user: User,
) -> None:
    tools = make_tools(
        create_chat_session(
            db_session, "published", user.id, persona_id=DEFAULT_PERSONA_ID
        ).id
    )
    sandbox.write_file(tools.ref, "report.md", b"# Report\n")
    cancellation = CancellationSignal()
    save_chat_artifact = artifact_operations.save_chat_artifact

    def save_then_stop(*args: Any, **kwargs: Any) -> PublishedFile:
        file = save_chat_artifact(*args, **kwargs)
        cancellation.cancel()
        return file

    monkeypatch.setattr(artifact_operations, "save_chat_artifact", save_then_stop)

    with pytest.raises(AgentCancelled):
        tools.create_file.run(
            ToolInvocation(
                call_id="publish",
                arguments={"file": "report.md"},
                cancellation=cancellation,
                update=lambda _progress: None,
            ),
            ToolContext(),
        )

    assert _published_records(db_session, tools.ref.session_id) == []


@pytest.mark.usefixtures("node", "initialize_file_store")
@pytest.mark.parametrize("resume", [True, False])
def test_a_parked_response_lists_its_published_file_once_and_a_chat_delete_deletes_it(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    chat: SandboxChat,
    gated_integration: int,
    resume: bool,
) -> None:
    sandbox.write_file(chat.ref(db_session), "report.md", b"# Report\n")
    gated = _gated(gated_integration, [])
    real_construct_tools = construct_tools

    def with_gated_tool(**kwargs: Any) -> list[Tool]:
        return [*real_construct_tools(**kwargs), gated]

    monkeypatch.setattr("onyx.chat.execution.construct_tools", with_gated_tool)
    llm = ChatLLM(
        [
            tool_step(
                LibraryCreateLibraryFileTool.NAME, "publish", {"file": "report.md"}
            ),
            tool_step(gated.name, "send", {"value": "team"}),
            Delta(content="Done."),
        ]
    )
    # The resumed response runs after the send returns.
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: llm
    )
    assert _stops(chat.send(llm)) == [packets.AWAITING_USER]
    approval = db_session.scalars(
        select(ApprovalRequest).where(
            ApprovalRequest.chat_session_id == chat.chat_session_id
        )
    ).one()
    response_id = approval.chat_message_id
    [file_id] = [
        record.file_id
        for record in _published_records(db_session, chat.chat_session_id)
    ]
    if not resume:
        # No save lists the file: the chat delete finds it by its row.
        assert _answer_file_ids(db_session, chat.chat_session_id) == []
        delete_chat_session_by_id(
            chat.chat_session_id,
            hard_delete=True,
            user=chat.user,
            db_session=db_session,
        )
        assert _remaining_file_ids(db_session, [file_id]) == []
        return

    with get_session_with_current_tenant() as session:
        decide_approval(
            approval_id=approval.id,
            body=ChatApprovalDecisionRequest(decision=ApprovalChoice.APPROVE_ONCE),
            request=Request({"type": "http", "headers": []}),
            user=chat.user,
            db_session=session,
        )

    def completed() -> bool:
        with get_session_with_current_tenant() as session:
            status = session.get_one(ChatMessage, response_id).response_status
        return status == RunStatus.COMPLETE

    _wait_until(completed)
    assert chat_turn_work.wait_idle(timeout=30)
    assert _answer_file_ids(db_session, chat.chat_session_id) == [file_id]
    delete_chat_session_by_id(
        chat.chat_session_id, hard_delete=True, user=chat.user, db_session=db_session
    )
    assert _remaining_file_ids(db_session, [file_id]) == []


@pytest.mark.usefixtures("node", "initialize_file_store")
def test_a_publish_of_too_many_files_publishes_none(
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    make_tools: MakeTools,
    user: User,
) -> None:
    tools = make_tools(
        create_chat_session(
            db_session, "published", user.id, persona_id=DEFAULT_PERSONA_ID
        ).id
    )
    sandbox.write_file(tools.ref, "report.md", b"# Report\n")

    result, _ = _run(
        tools.create_file,
        {"files": ["report.md"] * (PUBLISH_FILES_MAX_FILES + 1)},
    )

    assert result.is_error
    assert f"at most {PUBLISH_FILES_MAX_FILES} items" in result.text
    assert _published_records(db_session, tools.ref.session_id) == []


# Large tool results


def _offer_mcp_tool(
    monkeypatch: pytest.MonkeyPatch, name: str, text: Callable[[str], str]
) -> None:
    """Add to the turn's tools an MCP tool whose result for a call is
    `text(call_id)`, in the shape of MCPTool's results."""

    def run(invocation: ToolInvocation, _context: ToolContext) -> ToolResult:
        value: dict[str, JsonValue] = {"tool_result": text(invocation.call_id)}
        return ToolResult(
            content=json.dumps(value),
            details=CustomToolCallSummary(
                tool_name=name, response_type="json", tool_result=value
            ),
        )

    tool = FakeMCPTool(name, run, {"type": "object", "properties": {}})
    real_construct_tools = construct_tools
    monkeypatch.setattr(
        "onyx.chat.execution.construct_tools",
        lambda **kwargs: [*real_construct_tools(**kwargs), tool],
    )


def _calls_step(name: str, call_ids: Sequence[str]) -> Delta:
    """One model step that calls `name` once for each call ID."""
    return Delta(
        tool_calls=[
            ChatCompletionDeltaToolCall(
                id=call_id,
                index=index,
                function=ResponseFunctionCall(name=name, arguments="{}"),
            )
            for index, call_id in enumerate(call_ids)
        ]
    )


def _custom_tool_deltas(parts: Sequence[object]) -> list[packets.CustomToolDelta]:
    """The custom tool packets of streamed parts or replayed packets."""
    return [
        obj
        for part in parts
        if isinstance(
            obj := part.obj if isinstance(part, packets.Packet) else part,
            packets.CustomToolDelta,
        )
    ]


def _saved_results(
    db_session: Session, chat_session_id: UUID
) -> list[ToolResultMessage]:
    db_session.expire_all()
    return [
        row.result
        for row in db_session.scalars(
            select(ToolCallRecord)
            .where(ToolCallRecord.chat_session_id == chat_session_id)
            .order_by(ToolCallRecord.id)
        )
        if row.result is not None
    ]


def _spills(node: RunningFakeAgent, ref: HarnessSandboxRef) -> dict[str, bytes]:
    return {
        path: data
        for (sandbox_id, session_id, path), data in node.agent.files.items()
        if sandbox_id == str(ref.sandbox_id)
        and not session_id
        and path.startswith(TOOL_RESULTS_ROOT + "/")
    }


def _note(path: str, size: int, body: str, *, code_mode: bool = False) -> str:
    """The model's note of a spilled result."""
    # In code mode the shell is a function of programs.
    read_with = "tools.exec_command in exec programs" if code_mode else "exec_command"
    return (
        f'<persisted-output path="{path}" bytes={size}>\n{body}\n'
        f"Read the file with {read_with} (grep, sed, head, tail). It lasts while "
        "the sandbox runs. If it is missing, the sandbox restarted or newer results "
        "replaced it: call the tool again only if the call is read-only."
        "\n</persisted-output>"
    )


def _big(call_id: str) -> str:
    return f"HEAD-{call_id} " + "m" * 60_000 + f" TAIL-{call_id}"


@pytest.mark.usefixtures("node")
def test_a_large_mcp_result_spills_to_the_vm_and_the_history_keeps_the_preview(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    _offer_mcp_tool(monkeypatch, "fetch_report", _big)
    llm = ChatLLM([tool_step("fetch_report", "big", {}), Delta(content="Done.")])
    parts = chat.send(llm)

    full = json.dumps({"tool_result": _big("big")})
    shown = last_tool_text(llm, "big")
    ref = chat.ref(db_session)
    # No call started the VM; the write did.
    assert [request[0] for request in node.agent.create_requests] == [
        str(ref.sandbox_id)
    ]
    [(path, data)] = _spills(node, ref).items()
    assert data == full.encode()
    assert path.startswith(f"{TOOL_RESULTS_ROOT}/{chat.chat_session_id}/")
    assert path.endswith("_big.txt")
    assert shown == _note(
        path,
        len(full),
        f"Preview (first 2,000 characters):\n{full[:2000]}\n"
        f"Preview (last 1,000 characters):\n{full[-1000:]}\n"
        "The file holds the whole output.",
    )
    # The history keeps only the preview: the content, and the details that
    # mark the result as spilled.
    [saved] = _saved_results(db_session, chat.chat_session_id)
    assert saved.content == shown
    assert isinstance(saved.details, CustomToolCallSummary)
    assert saved.details.tool_result is None
    assert saved.details.spilled == SpilledOutput(head=full[:2000], tail=full[-1000:])
    # The card shows the preview with a note, not the model's instructions.
    live = _custom_tool_deltas(parts)
    assert [delta.data for delta in live] == [
        f"{full[:2000]}\n\n[{SPILLED_OUTPUT_NOTE}]\n\n{full[-1000:]}"
    ]
    [replayed] = chat.replayed(db_session)
    assert _custom_tool_deltas(replayed) == live


@pytest.mark.usefixtures("node")
def test_results_after_the_step_budget_is_used_up_spill(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    # Each result is under the limit of one result; five are over the budget.
    def text(call_id: str) -> str:
        return call_id + "x" * 45_000

    _offer_mcp_tool(monkeypatch, "fetch_page", text)
    call_ids = [f"page{index}" for index in range(5)]
    llm = ChatLLM([_calls_step("fetch_page", call_ids), Delta(content="Done.")])
    chat.send(llm)

    shown = {call_id: last_tool_text(llm, call_id) for call_id in call_ids}
    spilled = [
        call_id
        for call_id, content in shown.items()
        if content.startswith("<persisted-output ")
    ]
    # The results that arrived first used the budget; the last one spilled.
    assert len(spilled) == 1
    for call_id in call_ids:
        if call_id not in spilled:
            assert shown[call_id] == json.dumps({"tool_result": text(call_id)})
    [(path, data)] = _spills(node, chat.ref(db_session)).items()
    assert path.endswith(f"_{spilled[0]}.txt")
    assert data == json.dumps({"tool_result": text(spilled[0])}).encode()


@pytest.mark.usefixtures("node")
def test_a_large_result_that_the_vm_cannot_take_keeps_its_head_and_tail(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    node.agent.write_failures[ANY_PATH] = WriteFailure(
        SandboxDaemonErrorReason.INTERNAL
    )
    _offer_mcp_tool(monkeypatch, "fetch_report", _big)
    llm = ChatLLM([tool_step("fetch_report", "big", {}), Delta(content="Done.")])
    chat.send(llm)

    full = json.dumps({"tool_result": _big("big")})
    shown = last_tool_text(llm, "big")
    assert shown == (
        full[:2000]
        + f"\n... [output truncated, {len(full) - 3000} characters omitted] ...\n"
        + full[-1000:]
        + f"\n{SPILL_FAILED_NOTE}"
    )
    assert _spills(node, chat.ref(db_session)) == {}
    [saved] = _saved_results(db_session, chat.chat_session_id)
    assert saved.content == shown
    assert isinstance(saved.details, CustomToolCallSummary)
    assert saved.details.tool_result == shown
    assert saved.details.spilled is None


@pytest.mark.usefixtures("node")
@pytest.mark.parametrize("name", [INTERNAL_SEARCH_TOOL_NAME, POSTGRES_TOOL_NAME])
def test_a_large_citeable_tool_result_stays_whole(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
    name: str,
) -> None:
    _offer_mcp_tool(monkeypatch, name, _big)
    llm = ChatLLM([tool_step(name, "found", {}), Delta(content="Done.")])
    chat.send(llm)

    assert last_tool_text(llm, "found") == json.dumps({"tool_result": _big("found")})
    assert _spills(node, chat.ref(db_session)) == {}


_ROWS_PROGRAM = "for i in range(3000):\n    print(f'row {i}')\n"
_ROWS = "".join(f"row {i}\n" for i in range(3000))


@pytest.mark.usefixtures("node")
def test_a_cell_over_its_output_limit_saves_its_output_to_the_vm(
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    program = _ROWS_PROGRAM + "'done'\n"
    llm = ChatLLM(
        [
            code_step(OPENAI_CODE_MODE, "rows", program, max_output_tokens=1_250),
            Delta(content="Done."),
        ]
    )
    parts = chat.send(llm, code_mode=True)

    [(path, data)] = _spills(node, chat.ref(db_session)).items()
    output = f"Output:\n{_ROWS.rstrip()}\n\nResult:\n'done'"
    assert data == output.encode()
    assert path.endswith("_rows.txt")
    shown = last_tool_text(llm, "rows")
    # The model keeps the preview that the limit cut, then the file's path.
    preview, note = shown.split("\n\n<persisted-output ")
    assert preview.startswith("Warning: truncated output (original character count: ")
    assert "characters omitted] ...\n" in preview
    assert len(preview) < 5_200
    assert f"<persisted-output {note}" == _note(
        path, len(data), FULL_VALUE_NOTE, code_mode=True
    )
    [saved] = saved_cells(db_session, chat.chat_session_id)
    assert (saved.stdout, saved.result, saved.error) == ("", None, None)
    assert saved.spilled == SpilledOutput(head=output[:2000], tail=output[-1000:])
    # The card shows the head and the tail with a note, live and on replay.
    card = f"{output[:2000]}\n\n[{SPILLED_OUTPUT_NOTE}]\n\n{output[-1000:]}"
    [live] = final_deltas(parts)
    assert (live.stdout, live.result) == (card, None)
    detail = get_chat_session(
        session_id=chat.chat_session_id, user=chat.user, db_session=db_session
    )
    [replayed] = final_deltas(
        [packet for response in detail.packets for packet in response]
    )
    assert (replayed.stdout, replayed.result) == (card, None)


@pytest.mark.usefixtures("node")
def test_a_cell_counts_the_printed_output_that_it_dropped_before_the_save(
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    # Over the 640,000 characters that the cell keeps of its printed output.
    printed = 700_000
    program = f"print('h' * 1000 + 'm' * {printed - 2000} + 't' * 1000)\n"
    llm = ChatLLM(
        [
            code_step(OPENAI_CODE_MODE, "big", program, max_output_tokens=1_250),
            Delta(content="Done."),
        ]
    )
    chat.send(llm, code_mode=True)

    [data] = _spills(node, chat.ref(db_session)).values()
    kept = data.decode()
    assert kept.startswith("Output:\nh") and kept.endswith("t")
    # The file marks what the cell dropped; the model's count includes it.
    dropped = printed + 1 - 640_000
    assert f"[output truncated, {dropped} characters omitted]" in kept
    shown = last_tool_text(llm, "big")
    count = shown.removeprefix("Warning: truncated output (original character count: ")
    assert int(count.split(")")[0]) > printed


@pytest.mark.usefixtures("node")
def test_cell_results_within_their_limit_never_spill(
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    # Each observation is over the limit of one result, and the two are over
    # the step budget, but within the cell's own output limit.
    rows = "".join(f"{'x' * 60} {i}\n" for i in range(1_500))
    program = f"print({rows!r}, end='')\nyield_control()\nprint({rows!r}, end='')\n"
    llm = ChatLLM(
        [
            code_step(OPENAI_CODE_MODE, "start", program, max_output_tokens=40_000),
            wait_step(OPENAI_CODE_MODE, "more", 1, max_tokens=40_000),
            Delta(content="Done."),
        ]
    )
    chat.send(llm, code_mode=True)

    assert len(rows) > 50_000
    for call_id in ("start", "more"):
        shown = last_tool_text(llm, call_id)
        assert rows.rstrip() in shown
        assert "persisted-output" not in shown
    assert _spills(node, chat.ref(db_session)) == {}


@pytest.mark.usefixtures("node")
def test_a_cell_that_closes_after_a_large_observation_spills_both_records(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    amended: list[ToolResult] = []
    apply_amendments = Run._apply_amendments

    def captured(run: Run, amendments: Sequence[Any]) -> None:
        amended.extend(amendment.result for amendment in amendments)
        apply_amendments(run, amendments)

    monkeypatch.setattr(Run, "_apply_amendments", captured)
    # The observation at yield_control is over its output limit. The cell
    # prints more than its closing record's limit and runs on until the
    # response ends and closes it.
    program = (
        _ROWS_PROGRAM
        + "yield_control()\n"
        + "for i in range(3000, 6000):\n    print(f'row {i}')\n"
        + "import asyncio\nawait asyncio.sleep(60)\n"
    )
    llm = ChatLLM(
        [
            code_step(OPENAI_CODE_MODE, "start", program, max_output_tokens=1_250),
            Delta(content="Started."),
        ]
    )
    chat.send(llm, code_mode=True)

    spills = _spills(node, chat.ref(db_session))
    [(path, data)] = [
        (path, data) for path, data in spills.items() if "_amended" not in path
    ]
    [(amended_path, amended_data)] = [
        (path, data) for path, data in spills.items() if "_amended" in path
    ]
    assert b"row 2700\n" in data
    assert b"row 5700\n" in amended_data
    [closing] = amended
    [saved] = _saved_results(db_session, chat.chat_session_id)
    # The closing record follows the observation as the model got it, and
    # ends with the note of its own file.
    observed = last_tool_text(llm, "start")
    assert f'<persisted-output path="{path}" ' in observed
    assert closing.content.startswith(f"{observed}\n\n")
    assert closing.content.endswith(
        _note(amended_path, len(amended_data), FULL_VALUE_NOTE, code_mode=True)
    )
    assert "row 5700\n" not in closing.content
    assert saved.content == closing.content
    assert isinstance(saved.details, CodeModeExecutionResult)
    assert saved.details.spilled is not None
    assert saved.details.closing is not None

    follow_up = ChatLLM([Delta(content="It ran.")])
    chat.send(follow_up, code_mode=True)
    assert last_tool_text(follow_up, "start") == closing.content


# The file copy status line


def _scripted_status(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Each read of the file copy status gives a new line; returns the lines
    given, in order."""
    given: list[str] = []

    def line(_status: CopyStatus) -> str:
        given.append(f"[files] Copying: attachments/{len(given)}.txt.")
        return given[-1]

    monkeypatch.setattr(CopyStatus, "line", line)
    return given


@pytest.mark.usefixtures("node")
def test_root_sandbox_results_end_with_the_file_status_and_errors_do_not(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, chat: SandboxChat
) -> None:
    given = _scripted_status(monkeypatch)
    llm = ChatLLM(
        [
            tool_step(EXEC_COMMAND_TOOL_NAME, "ok", {"cmd": "echo hi"}),
            tool_step(WRITE_STDIN_TOOL_NAME, "bad", {"session_id": "nope"}),
            tool_step(ApplyPatchTool.NAME, "patch", {"input": "not a patch"}),
            Delta(content="Done."),
        ]
    )
    chat.send(llm)

    ok, bad, patch = (last_tool_text(llm, call) for call in ("ok", "bad", "patch"))
    # Failed calls do not read the status; it waits for the next result.
    assert given == ["[files] Copying: attachments/0.txt."]
    assert ok.endswith(f"Output:\nhi\n\n\n{given[0]}")
    assert bad == str(ExecSessionNotFoundError("nope"))
    assert "[files]" not in patch
    # The history keeps what the model got.
    assert [
        saved.content for saved in _saved_results(db_session, chat.chat_session_id)
    ] == [ok, bad, patch]


@pytest.mark.usefixtures("node")
def test_the_file_status_follows_a_spilled_result(
    monkeypatch: pytest.MonkeyPatch, chat: SandboxChat
) -> None:
    given = _scripted_status(monkeypatch)
    llm = ChatLLM(
        [
            code_step(OPENAI_CODE_MODE, "big", _ROWS_PROGRAM, max_output_tokens=1_250),
            Delta(content="Done."),
        ]
    )
    chat.send(llm, code_mode=True)

    shown = last_tool_text(llm, "big")
    assert "<persisted-output path=" in shown
    assert shown.endswith(f"</persisted-output>\n\n{given[0]}")
    assert len(given) == 1


@pytest.mark.usefixtures("node")
def test_the_file_status_follows_a_spilled_exec_result(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, chat: SandboxChat
) -> None:
    given = _scripted_status(monkeypatch)
    llm = ChatLLM(
        [
            tool_step(EXEC_COMMAND_TOOL_NAME, "seq", {"cmd": "seq 20000"}),
            Delta(content="Done."),
        ]
    )
    parts = chat.send(llm)

    # The model gets the exec result with the spill note, then the status
    # line.
    shown = last_tool_text(llm, "seq")
    assert "<persisted-output path=" in shown
    assert given == ["[files] Copying: attachments/0.txt."]
    assert shown.endswith(f"</persisted-output>\n\n{given[0]}")
    [saved] = _saved_results(db_session, chat.chat_session_id)
    assert saved.content == shown
    # The card shows the spilled output, not the status.
    assert _exec_end(parts).output == _card(_seq(20_000))


@pytest.mark.usefixtures("node")
def test_a_code_cell_gets_the_file_status_and_its_calls_do_not_read_it(
    monkeypatch: pytest.MonkeyPatch, chat: SandboxChat
) -> None:
    given = _scripted_status(monkeypatch)
    program = (
        "for _ in range(2):\n"
        "    print((await tools.exec_command(cmd='echo hi'))['output'])\n"
        f"print(await tools.apply_patch(input={ADD_A!r}))\n"
    )
    llm = ChatLLM(
        [code_step(OPENAI_CODE_MODE, "code", program), Delta(content="Done.")]
    )
    chat.send(llm, code_mode=True)

    # One read, for the cell's result; the program's calls read none.
    assert given == ["[files] Copying: attachments/0.txt."]
    text = last_tool_text(llm, "code")
    assert text.endswith(f"\n\n{given[0]}")
    assert text.count("[files]") == 1


@pytest.mark.usefixtures("node")
def test_a_closed_cell_keeps_one_file_status_line(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, chat: SandboxChat
) -> None:
    given = _scripted_status(monkeypatch)
    amended: list[ToolResult] = []
    apply_amendments = Run._apply_amendments

    def captured(run: Run, amendments: Sequence[Any]) -> None:
        amended.extend(amendment.result for amendment in amendments)
        apply_amendments(run, amendments)

    monkeypatch.setattr(Run, "_apply_amendments", captured)
    # The cell's sandbox call starts the copy. The cell yields its
    # observation, runs on, and the end of the response closes it with an
    # amendment that starts from the recorded observation.
    program = (
        "await tools.exec_command(cmd='echo hi')\n"
        "print('started')\nyield_control()\nawait asyncio.sleep(60)\n"
    )
    llm = ChatLLM(
        [
            code_step(OPENAI_CODE_MODE, "start", "import asyncio\n" + program),
            Delta(content="Started."),
        ]
    )
    chat.send(llm, code_mode=True)

    observed = last_tool_text(llm, "start")
    assert observed.endswith(f"\n\n{given[0]}")
    [closing] = amended
    assert closing.content.startswith(observed)
    assert closing.content.count("[files]") == 1
    assert given == ["[files] Copying: attachments/0.txt."]
    [saved] = _saved_results(db_session, chat.chat_session_id)
    assert saved.content == closing.content


@pytest.mark.usefixtures("node")
def test_subagent_sandbox_results_do_not_read_the_file_status(
    monkeypatch: pytest.MonkeyPatch, chat: SandboxChat
) -> None:
    given = _scripted_status(monkeypatch)
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
                        id="child-exec",
                        name=EXEC_COMMAND_TOOL_NAME,
                        arguments={"cmd": "echo child"},
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
            tool_options=ToolOptions(allowed=[]),
            accepts_follow_ups=True,
        ),
        user=chat.user,
    ):
        pass
    assert chat_turn_work.wait_idle(timeout=30)

    [child_result] = helper_results
    assert "child" in child_result
    assert "[files]" not in child_result
    assert given == []


@pytest.mark.usefixtures("node")
def test_a_chat_without_a_sandbox_keeps_a_large_result_whole(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    monkeypatch.setattr(process_message, "HARNESS_SANDBOX_ENABLED", False)
    _offer_mcp_tool(monkeypatch, "fetch_report", _big)
    llm = ChatLLM([tool_step("fetch_report", "big", {}), Delta(content="Done.")])
    chat.send(llm)

    value = {"tool_result": _big("big")}
    assert EXEC_COMMAND_TOOL_NAME not in str(llm.requests[0].get("tools"))
    assert last_tool_text(llm, "big") == json.dumps(value)
    [saved] = _saved_results(db_session, chat.chat_session_id)
    assert isinstance(saved.details, CustomToolCallSummary)
    assert saved.details.tool_result == value
    assert not any(
        path.startswith(TOOL_RESULTS_ROOT) for (_, _, path) in node.agent.files
    )


@pytest.mark.usefixtures("node")
def test_parallel_cells_over_their_limit_spill_in_one_step_past_the_budget(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    # Each cell's cut is within its own limit; the two are over the step
    # budget, which does not apply to cells.
    monkeypatch.setattr(spill, "STEP_MAX_CHARS", 8_000)
    output = f"Output:\n{_ROWS.rstrip()}"
    call_ids = ("left", "right")
    step = Delta(
        tool_calls=[
            ChatCompletionDeltaToolCall(
                id=call_id,
                index=index,
                function=ResponseFunctionCall(
                    name="exec",
                    arguments=json.dumps(
                        {"code": _ROWS_PROGRAM, "max_output_tokens": 1_250}
                    ),
                ),
            )
            for index, call_id in enumerate(call_ids)
        ]
    )
    llm = ChatLLM([step, Delta(content="Done.")])
    chat.send(llm, code_mode=True)

    spills = _spills(node, chat.ref(db_session))
    assert sorted(path.rsplit("_", 1)[-1] for path in spills) == [
        "left.txt",
        "right.txt",
    ]
    assert set(spills.values()) == {output.encode()}
    shown = {call_id: last_tool_text(llm, call_id) for call_id in call_ids}
    assert sum(len(text) for text in shown.values()) > spill.STEP_MAX_CHARS
    for call_id, text in shown.items():
        preview, note = text.split("\n\n<persisted-output ")
        assert preview.startswith("Warning: truncated output")
        assert len(preview) < 5_200
        [path] = [path for path in spills if path.endswith(f"_{call_id}.txt")]
        assert f"<persisted-output {note}" == _note(
            path, len(output), FULL_VALUE_NOTE, code_mode=True
        )


@pytest.mark.parametrize(
    "steps",
    [
        pytest.param(
            [tool_step(EXEC_COMMAND_TOOL_NAME, "echo", {"cmd": "echo hi"})],
            id="after_a_command",
        ),
        # The spill alone sets up no session on the VM.
        pytest.param([], id="spill_only"),
    ],
)
@pytest.mark.usefixtures("node", "sandbox")
def test_a_chat_purge_deletes_only_its_own_spilled_results(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    user: User,
    steps: list[Delta],
) -> None:
    monkeypatch.setattr(purge, "HARNESS_SANDBOX_ENABLED", True)
    _offer_mcp_tool(monkeypatch, "fetch_report", _big)
    chats = [
        SandboxChat(
            user=user,
            chat_session_id=create_chat_session(
                db_session, name, user.id, persona_id=DEFAULT_PERSONA_ID
            ).id,
            monkeypatch=monkeypatch,
        )
        for name in ("deleted", "kept")
    ]
    for chat in chats:
        chat.send(
            ChatLLM(
                [*steps, tool_step("fetch_report", "big", {}), Delta(content="Done.")]
            )
        )
    ref = chats[0].ref(db_session)

    def spilled(chat: SandboxChat) -> list[str]:
        prefix = f"{TOOL_RESULTS_ROOT}/{chat.chat_session_id}/"
        return [path for path in _spills(node, ref) if path.startswith(prefix)]

    assert len(spilled(chats[0])) == len(spilled(chats[1])) == 1
    delete_chat_session_by_id(
        chats[0].chat_session_id, hard_delete=True, user=user, db_session=db_session
    )
    _wait_for_purges()

    assert spilled(chats[0]) == []
    assert len(spilled(chats[1])) == 1


@pytest.mark.usefixtures("node", "sandbox")
def test_the_oldest_spilled_results_of_any_chat_go_past_the_vm_limit(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    user: User,
) -> None:
    # Two results of about 60,000 bytes do not fit.
    monkeypatch.setattr(spill, "TOOL_RESULTS_MAX_BYTES", 100_000)
    _offer_mcp_tool(monkeypatch, "fetch_report", _big)
    chats = [
        SandboxChat(
            user=user,
            chat_session_id=create_chat_session(
                db_session, name, user.id, persona_id=DEFAULT_PERSONA_ID
            ).id,
            monkeypatch=monkeypatch,
        )
        for name in ("older", "newer")
    ]
    ref = chats[0].ref(db_session)

    def spilled(chat: SandboxChat) -> list[str]:
        prefix = f"{TOOL_RESULTS_ROOT}/{chat.chat_session_id}/"
        return [path for path in _spills(node, ref) if path.startswith(prefix)]

    for chat in chats:
        chat.send(
            ChatLLM([tool_step("fetch_report", "big", {}), Delta(content="Done.")])
        )
        # Eviction runs after the write returns.
        _wait_until(lambda: sum(map(len, _spills(node, ref).values())) <= 100_000)

    assert spilled(chats[0]) == []
    assert len(spilled(chats[1])) == 1


def _seq(count: int) -> str:
    """The output of `seq <count>` in the fake daemon."""
    return "".join(f"{n}\n" for n in range(1, count + 1))


def _cut(text: str, max_chars: int, omitted: int = 0) -> str:
    """`text` (ASCII) cut in the middle to `max_chars`, as exec cuts it."""
    if len(text) <= max_chars and not omitted:
        return text
    half = max_chars // 2
    return (
        text[:half]
        + f"\n... [output truncated, {len(text) - max_chars + omitted} characters "
        "omitted] ...\n" + text[len(text) - (max_chars - half) :]
    )


def _card(full: str) -> str:
    """What the terminal card shows of spilled output."""
    return f"{full[:2000]}\n\n[{SPILLED_OUTPUT_NOTE}]\n\n{full[-1000:]}"


def _exec_end(parts: Sequence[object]) -> packets.ExecEnd:
    [end] = [obj for obj in _sandbox_packets(parts) if isinstance(obj, packets.ExecEnd)]
    return end


@pytest.mark.parametrize(
    "count",
    [
        pytest.param(20_000, id="over_the_cut"),
        pytest.param(300_000, id="over_the_byte_cap"),
    ],
)
@pytest.mark.usefixtures("node")
def test_the_model_gets_its_cut_of_large_command_output_and_the_file_the_rest(
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
    count: int,
) -> None:
    llm = ChatLLM(
        [
            tool_step(EXEC_COMMAND_TOOL_NAME, "seq", {"cmd": f"seq {count}"}),
            Delta(content="Done."),
        ]
    )
    parts = chat.send(llm)

    output = _seq(count)
    # The call keeps the head and the tail of the output, and the file marks
    # the middle that the byte cap dropped.
    half = EXEC_CALL_OUTPUT_MAX_BYTES // 2
    dropped = max(len(output) - EXEC_CALL_OUTPUT_MAX_BYTES, 0)
    head, tail = (output[:half], output[-half:]) if dropped else (output, "")
    full = _cut(head + tail, len(head) + len(tail), dropped)
    [(path, data)] = _spills(node, chat.ref(db_session)).items()
    assert path.endswith("_seq.txt")
    assert data == full.encode()
    # The model gets exactly the default cut, whose one count includes the
    # dropped middle, then the file's note.
    cut = _cut(output, 40_000)
    shown = last_tool_text(llm, "seq")
    assert shown.startswith("Wall time: ")
    assert shown.endswith(
        f"Process exited with code 0\nOriginal character count: {len(output)}\n"
        f"Output:\n{cut}\n\n" + _note(path, len(data), FULL_VALUE_NOTE)
    )
    # The history keeps the model's cut, and the card shows the file's head
    # and tail with a plain note, the same live and on a reload.
    [saved] = _saved_results(db_session, chat.chat_session_id)
    assert saved.content == shown
    assert isinstance(saved.details, SandboxExecResult)
    assert saved.details.output == ""
    # The card's output is cut either way.
    assert saved.details.truncated
    assert saved.details.spilled == SpilledOutput(head=full[:2000], tail=full[-1000:])
    live = _exec_end(parts)
    assert live.output == _card(full) and live.truncated
    [replayed] = chat.replayed(db_session)
    assert _exec_end(replayed) == live


@pytest.mark.usefixtures("node")
def test_command_output_that_its_cut_barely_shortens_still_spills(
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    output = _seq(20_000)
    # The largest budget, in tokens of 4 characters, that cuts the output.
    max_tokens = (len(output) - 1) // 4
    max_chars = max_tokens * 4
    llm = ChatLLM(
        [
            tool_step(
                EXEC_COMMAND_TOOL_NAME,
                "seq",
                {"cmd": "seq 20000", "max_output_tokens": max_tokens},
            ),
            Delta(content="Done."),
        ]
    )
    chat.send(llm)

    [data] = _spills(node, chat.ref(db_session)).values()
    assert data == output.encode()
    assert f"Output:\n{_cut(output, max_chars)}\n\n<persisted-output " in (
        last_tool_text(llm, "seq")
    )


@pytest.mark.usefixtures("node")
def test_command_output_that_the_vm_cannot_take_keeps_its_cut(
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    node.agent.write_failures[ANY_PATH] = WriteFailure(
        SandboxDaemonErrorReason.INTERNAL
    )
    llm = ChatLLM(
        [
            tool_step(EXEC_COMMAND_TOOL_NAME, "seq", {"cmd": "seq 20000"}),
            Delta(content="Done."),
        ]
    )
    chat.send(llm)

    cut = _cut(_seq(20_000), 40_000)
    shown = last_tool_text(llm, "seq")
    assert shown.endswith(f"Output:\n{cut}\n\n{SPILL_FAILED_NOTE}")
    [saved] = _saved_results(db_session, chat.chat_session_id)
    assert isinstance(saved.details, SandboxExecResult)
    assert (saved.details.output, saved.details.spilled) == (cut, None)


@pytest.mark.usefixtures("node")
def test_exec_results_are_exempt_from_the_step_budget(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    monkeypatch.setattr(spill, "STEP_MAX_CHARS", 10_000)
    call_ids = ("first", "second")
    step = Delta(
        tool_calls=[
            ChatCompletionDeltaToolCall(
                id=call_id,
                index=index,
                function=ResponseFunctionCall(
                    name=EXEC_COMMAND_TOOL_NAME, arguments='{"cmd": "seq 5000"}'
                ),
            )
            for index, call_id in enumerate(call_ids)
        ]
    )
    llm = ChatLLM([step, Delta(content="Done.")])
    chat.send(llm)

    for call_id in call_ids:
        assert last_tool_text(llm, call_id).endswith(f"Output:\n{_seq(5_000)}")
    assert _spills(node, chat.ref(db_session)) == {}


@pytest.mark.usefixtures("node")
def test_a_program_gets_all_the_output_that_a_command_kept(
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    # Over the model's default cut, under the bytes that a call keeps.
    output = _seq(20_000)
    program = (
        "result = await tools.exec_command(cmd='seq 20000')\n"
        "print(len(result['output']), result['output'].endswith('19999\\n20000\\n'))\n"
    )
    llm = ChatLLM(
        [code_step(OPENAI_CODE_MODE, "count", program), Delta(content="Done.")]
    )
    chat.send(llm, code_mode=True)

    assert last_tool_text(llm, "count").endswith(f"Output:\n{len(output)} True")
    # Results of calls inside a program do not spill.
    assert _spills(node, chat.ref(db_session)) == {}


@pytest.mark.usefixtures("node")
def test_a_program_that_prints_a_mebibyte_of_command_output_spills_its_cell(
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    program = (
        "result = await tools.exec_command(cmd='seq 300000')\nprint(result['output'])\n"
    )
    llm = ChatLLM([code_step(OPENAI_CODE_MODE, "big", program), Delta(content="Done.")])
    chat.send(llm, code_mode=True)

    [(path, data)] = _spills(node, chat.ref(db_session)).items()
    assert path.endswith("_big.txt")
    kept = data.decode()
    # The cell keeps 640,000 characters of what the program printed.
    assert kept.startswith("Output:\n1\n2\n3\n")
    assert kept.rstrip().endswith("299999\n300000")
    assert len(kept) < 650_000
    shown = last_tool_text(llm, "big")
    assert shown.startswith("Warning: truncated output")
    assert len(shown) < 42_000


# Chat files in attachments/

# A 1x1 PNG.
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)

Attach = Callable[..., FileDescriptor]


def _user_file(
    db_session: Session,
    user: User,
    name: str,
    data: bytes,
    file_type: str = "text/plain",
) -> UserFile:
    """A processed user file, committed on its own so that each has its own
    upload time."""
    user_file = UserFile(
        id=uuid4(),
        user_id=user.id,
        file_id=get_default_file_store().save_file(
            content=io.BytesIO(data),
            display_name=name,
            file_origin=FileOrigin.USER_FILE,
            file_type=file_type,
        ),
        name=name,
        file_type=file_type,
        status=UserFileStatus.COMPLETED,
        token_count=len(data),
    )
    db_session.add(user_file)
    db_session.commit()
    return user_file


@pytest.fixture
def attach(db_session: Session, user: User) -> Attach:
    """Upload a file as the user; returns its chat attachment descriptor."""

    def upload(
        name: str, data: bytes, file_type: ChatFileType = ChatFileType.PLAIN_TEXT
    ) -> FileDescriptor:
        user_file = _user_file(
            db_session,
            user,
            name,
            data,
            "image/png" if file_type is ChatFileType.IMAGE else "text/plain",
        )
        return FileDescriptor(
            id=user_file.file_id,
            type=file_type,
            name=name,
            user_file_id=str(user_file.id),
        )

    return upload


def _exec_turn() -> ChatLLM:
    return ChatLLM(
        [
            tool_step(EXEC_COMMAND_TOOL_NAME, "exec", {"cmd": "echo hi"}),
            Delta(content="Done."),
        ]
    )


def _user_texts(llm: ScriptedLLM) -> list[str]:
    """The user message texts of the model's first request."""
    return [
        message.content
        if isinstance(message.content, str)
        else "".join(
            part.text for part in message.content if isinstance(part, TextContentPart)
        )
        for message in llm.requests[0]["prompt"]
        if isinstance(message, PromptUserMessage)
    ]


def _attachments(node: RunningFakeAgent, ref: HarnessSandboxRef) -> dict[str, bytes]:
    return {
        path: data
        for path, data in _files(node, ref).items()
        if path.startswith("attachments/")
    }


def _vm_name(file_id: str, name: str) -> str:
    """A chat file's name in the VM: its file store ID (a UUID) starts it."""
    return f"{file_id[:8]}-{name}"


@pytest.mark.usefixtures("initialize_file_store")
def test_a_late_upload_gets_its_path_in_its_message_and_reaches_the_vm(
    db_session: Session, node: RunningFakeAgent, chat: SandboxChat, attach: Attach
) -> None:
    first = attach("report.txt", b"first report")
    first_path = f"attachments/{_vm_name(first['id'], 'report.txt')}"
    chat.send(_exec_turn(), file_descriptors=[first])
    ref = chat.ref(db_session)
    _wait_until(lambda: _attachments(node, ref) == {first_path: b"first report"})

    # Later in the chat: a file with the same name, and an image.
    late = attach("report.txt", b"late report")
    late_path = f"attachments/{_vm_name(late['id'], 'report.txt')}"
    image = attach("chart.png", _PNG, ChatFileType.IMAGE)
    image_path = f"attachments/{_vm_name(image['id'], 'chart.png')}"
    llm = _exec_turn()
    chat.send(llm, file_descriptors=[late, image])
    _wait_until(
        lambda: (
            _attachments(node, ref)
            == {
                first_path: b"first report",
                late_path: b"late report",
                image_path: _PNG,
            }
        )
    )
    _wait_until(file_copies.file_copy_pool().idle)
    # The earlier file is in place, so it is not copied again.
    assert node.agent.write_paths.count(first_path) == 1

    # Each message names its files' paths.
    texts = _user_texts(llm)
    assert (
        f"File: report.txt\nIn the VM: {first_path}\nfirst report\nEnd of File"
    ) in texts
    assert (
        f"File: report.txt\nIn the VM: {late_path}\nlate report\nEnd of File"
    ) in texts
    assert f"Image: chart.png\nIn the VM: {image_path}" in texts


@pytest.mark.usefixtures("initialize_file_store")
def test_a_branch_switch_keeps_the_uploads_of_every_branch(
    db_session: Session, node: RunningFakeAgent, chat: SandboxChat, attach: Attach
) -> None:
    """The VM keeps the uploads of every branch; the prompt names the
    uploads of the branch that it answers."""
    a = attach("a.txt", b"a")
    chat.send(_exec_turn(), file_descriptors=[a])
    [first_answer] = db_session.scalars(
        select(ChatMessage.id).where(
            ChatMessage.chat_session_id == chat.chat_session_id,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
    )
    b = attach("b.txt", b"b")
    chat.send(_exec_turn(), file_descriptors=[b])
    ref = chat.ref(db_session)
    paths = {
        f"attachments/{_vm_name(a['id'], 'a.txt')}": b"a",
        f"attachments/{_vm_name(b['id'], 'b.txt')}": b"b",
    }
    _wait_until(lambda: _attachments(node, ref) == paths)

    # An edit of the second message: a new branch after the first answer,
    # with another file of the same name.
    new_b = attach("b.txt", b"new b")
    new_b_path = f"attachments/{_vm_name(new_b['id'], 'b.txt')}"
    llm = _exec_turn()
    chat.send(llm, file_descriptors=[new_b], parent_message_id=first_answer)
    _wait_until(lambda: _attachments(node, ref) == {**paths, new_b_path: b"new b"})
    texts = "\n".join(_user_texts(llm))
    assert f"File: b.txt\nIn the VM: {new_b_path}\nnew b\nEnd of File" in texts
    assert _vm_name(b["id"], "b.txt") not in texts


@pytest.mark.usefixtures("initialize_file_store", "sandbox")
def test_project_and_agent_files_are_copied_and_follow_their_changes(
    db_session: Session,
    node: RunningFakeAgent,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _user_file(db_session, user, "plan.md", b"old plan")
    newer_plan = _user_file(db_session, user, "plan.md", b"new plan")
    handbook = _user_file(db_session, user, "handbook.txt", b"handbook")
    faq = _user_file(db_session, user, "faq.txt", b"faq")
    shared = _user_file(db_session, user, "shared.txt", b"shared")
    project = UserProject(name=f"sandbox {uuid4().hex[:8]}", user_id=user.id)
    db_session.add(project)
    db_session.flush()
    db_session.add_all(
        [
            Project__UserFile(project_id=project.id, user_file_id=user_file.id)
            for user_file in (plan, newer_plan, shared)
        ]
    )
    persona = upsert_persona(
        user=user,
        name=f"files {uuid4().hex[:8]}",
        description="",
        starter_messages=None,
        system_prompt=None,
        task_prompt=None,
        datetime_aware=None,
        is_public=False,
        tool_ids=[],
        user_file_ids=[handbook.id, faq.id, shared.id],
        db_session=db_session,
    )
    chat = SandboxChat(
        user=user,
        chat_session_id=create_chat_session(
            db_session,
            "sandbox files",
            user.id,
            persona_id=persona.id,
            project_id=project.id,
        ).id,
        monkeypatch=monkeypatch,
    )
    try:
        chat.send(_exec_turn())
        ref = chat.ref(db_session)

        def path(directory: str, user_file: UserFile) -> str:
            return (
                f"attachments/{directory}/{_vm_name(user_file.file_id, user_file.name)}"
            )

        # Two files of one name keep both, and a file of both the project
        # and the agent is the agent's.
        _wait_until(
            lambda: (
                _attachments(node, ref)
                == {
                    path("project", plan): b"old plan",
                    path("project", newer_plan): b"new plan",
                    path("agent", handbook): b"handbook",
                    path("agent", faq): b"faq",
                    path("agent", shared): b"shared",
                }
            )
        )

        # Project and agent files are read at each turn; a file that left
        # goes.
        db_session.execute(
            delete(Project__UserFile).where(Project__UserFile.user_file_id == plan.id)
        )
        db_session.execute(
            delete(Persona__UserFile).where(Persona__UserFile.user_file_id == faq.id)
        )
        db_session.commit()
        chat.send(_exec_turn())
        _wait_until(
            lambda: (
                _attachments(node, ref)
                == {
                    path("project", newer_plan): b"new plan",
                    path("agent", handbook): b"handbook",
                    path("agent", shared): b"shared",
                }
            )
        )
    finally:
        db_session.rollback()
        db_session.execute(
            delete(Persona__UserFile).where(Persona__UserFile.persona_id == persona.id)
        )
        db_session.execute(
            delete(Project__UserFile).where(Project__UserFile.project_id == project.id)
        )
        db_session.commit()


@pytest.mark.usefixtures("node")
def test_a_turn_without_a_sandbox_call_copies_nothing(
    db_session: Session, node: RunningFakeAgent, chat: SandboxChat, attach: Attach
) -> None:
    chat.send(ChatLLM([Delta(content="Hi.")]), file_descriptors=[attach("a.txt", b"a")])
    assert chat_turn_work.wait_idle(timeout=30)
    assert str(chat.ref(db_session).sandbox_id) not in node.agent.vms
    # The turn holds its copy generation from its start.
    assert (
        get_cache_backend(tenant_id=TENANT_ID).get(
            copy_generation_key(chat.chat_session_id)
        )
        == b"1"
    )


@pytest.mark.usefixtures("initialize_file_store")
def test_a_hosted_agent_run_copies_the_chat_files(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
    attach: Attach,
) -> None:
    """An agent host runs a worker whose sandbox call copies the chat's
    files, so a worker on a VM that lost them gets them again. Its
    exec_command describes the chat's files as the root's does."""
    monkeypatch.setattr("onyx.chat.agent.CODE_MODE_ENABLED", False)
    exec_descriptions: dict[str, str] = {}

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        texts = [message.text for message in request.messages]
        [description] = [
            tool.description
            for tool in request.tools
            if tool.name == EXEC_COMMAND_TOOL_NAME
        ]
        if "Initial task" in texts:
            if "Follow up" in texts and not isinstance(
                request.messages[-1], ToolResultMessage
            ):
                exec_descriptions["hosted"] = description
                return AssistantMessage(
                    content=[
                        ToolCall(
                            id="hosted-exec",
                            name=EXEC_COMMAND_TOOL_NAME,
                            arguments={"cmd": "echo hosted"},
                        )
                    ]
                )
            return AssistantMessage(content=[TextContent(text="Worker done.")])
        if any(isinstance(message, ToolResultMessage) for message in request.messages):
            return AssistantMessage(content=[TextContent(text="Started.")])
        exec_descriptions["root"] = description
        return AssistantMessage(
            content=[
                ToolCall(
                    id="root-exec",
                    name=EXEC_COMMAND_TOOL_NAME,
                    arguments={"cmd": "echo root"},
                ),
                ToolCall(
                    id="spawn",
                    name=SPAWN_AGENT_TOOL_NAME,
                    arguments={"task_name": "worker", "message": "Initial task"},
                ),
            ]
        )

    model = WaitAgentLLM(generate)
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )
    a = attach("a.txt", b"a")
    for _part in handle_stream_message_objects(
        new_msg_req=SendMessageRequest(
            message="Start a worker.",
            chat_session_id=chat.chat_session_id,
            tool_options=ToolOptions(allowed=[]),
            accepts_follow_ups=True,
            file_descriptors=[a],
        ),
        user=chat.user,
    ):
        pass
    assert chat_turn_work.wait_idle(timeout=30)
    ref = chat.ref(db_session)
    copied = {f"attachments/{_vm_name(a['id'], 'a.txt')}": b"a"}
    _wait_until(lambda: _attachments(node, ref) == copied)
    cache = get_cache_backend(tenant_id=TENANT_ID)
    generation = cache.get(copy_generation_key(chat.chat_session_id))
    assert generation is not None
    # The VM loses the file, as a restored VM would.
    [path] = copied
    del node.agent.files[(str(ref.sandbox_id), str(ref.session_id), path)]

    # A message for the idle worker, which an agent host runs.
    spawn = db_session.scalars(
        select(ToolCallRecord).where(
            ToolCallRecord.chat_session_id == chat.chat_session_id,
            ToolCallRecord.tool_call_id == "spawn",
        )
    ).one()
    worker = db_session.scalars(
        select(ChatSession).where(
            ChatSession.spawned_by_message_id == spawn.parent_chat_message_id
        )
    ).one()
    finished = db_session.scalars(
        select(ChatMessage).where(
            ChatMessage.chat_session_id == worker.id,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
    ).one()
    db_session.add(
        ChatInput(
            recipient_session_id=worker.id,
            message_id=str(uuid4()),
            source=InputSource.AGENT,
            invoking_tool_call_id=spawn.id,
            source_response_id=spawn.parent_chat_message_id,
            target_response_id=finished.id,
            root_response_id=spawn.parent_chat_message_id,
            delivery=MessageDelivery.QUEUE,
            content="Follow up",
            max_steps=2,
        )
    )
    db_session.commit()
    dispatch_pending_chat_messages(chat.chat_session_id, chat.user.id)

    def hosted_exec_ran() -> bool:
        db_session.expire_all()
        return (
            db_session.scalars(
                select(ToolCallRecord).where(
                    ToolCallRecord.chat_session_id == worker.id,
                    ToolCallRecord.tool_call_id == "hosted-exec",
                )
            ).first()
            is not None
        )

    _wait_until(hosted_exec_ran)
    assert chat_turn_work.wait_idle(timeout=30)
    _wait_until(lambda: _attachments(node, ref) == copied)
    hosted_generation = cache.get(copy_generation_key(chat.chat_session_id))
    assert hosted_generation is not None
    assert int(hosted_generation) > int(generation)
    assert exec_descriptions["root"].endswith(CHAT_FILES_LAYOUT)
    assert exec_descriptions["hosted"] == exec_descriptions["root"]


@pytest.mark.usefixtures("sandbox", "node")
@pytest.mark.parametrize("tool", ["write", "edit", "apply_patch"])
def test_a_change_to_an_attachment_says_that_it_is_not_saved(
    make_tools: MakeTools, tool: str
) -> None:
    tools = make_tools()
    _run(tools.write, {"file_path": "attachments/a.txt", "content": "x\n"})
    _run(tools.write, {"file_path": "notes.txt", "content": "x\n"})
    run = {"write": tools.write, "edit": tools.edit, "apply_patch": tools.apply_patch}

    def changed(path: str) -> str:
        arguments: dict[str, JsonValue] = (
            {"file_path": path, "content": "y\n"}
            if tool == "write"
            else {"file_path": path, "old_string": "x", "new_string": "y"}
            if tool == "edit"
            else {
                "input": f"*** Begin Patch\n*** Update File: {path}\n@@\n-x\n+y\n"
                "*** End Patch"
            }
        )
        result, _ = _run(run[tool], arguments)
        assert not result.is_error, result.content
        return result.content

    assert changed("attachments/a.txt").endswith(f"\n\n{ATTACHMENTS_NOT_SAVED_NOTE}")
    assert ATTACHMENTS_NOT_SAVED_NOTE not in changed("notes.txt")


# open_url


def _web_page(index: int, chars: int) -> MockWebContent:
    """A page of about `chars` characters, with its search snippet in the
    middle."""
    half = "w" * (chars // 2)
    return MockWebContent(
        title=f"Page {index}",
        url=f"https://docs.example.com/{index}",
        content=f"START-{index}\n{half} {_snippet(index)} {half}\nEND-{index}",
    )


def _snippet(index: int) -> str:
    return f"The guide's section {index} explains the setup."


def _send_with_pages(
    chat: SandboxChat,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    pages: Sequence[MockWebContent],
    llm: ChatLLM,
    *,
    code_mode: bool = False,
) -> list[object]:
    """Send a message with web search and open_url, whose search finds
    `pages`. The pages come from the web, not the index."""
    monkeypatch.setattr(open_url_tool, "DISABLE_VECTOR_DB", True)
    tool_ids = [
        get_builtin_tool(db_session, tool).id for tool in (WebSearchTool, OpenURLTool)
    ]
    with (
        use_mock_web_provider(db_session) as web,
        use_mock_content_provider() as content,
    ):
        web.add_results(
            "guide",
            [
                MockWebSearchResult(
                    title=page.title, link=page.url, snippet=_snippet(index)
                )
                for index, page in enumerate(pages, start=1)
            ],
        )
        for page in pages:
            content.add_content(page)
        return chat.send(llm, tool_ids=tool_ids, code_mode=code_mode)


def _search_and_open(pages: Sequence[MockWebContent], answer: str) -> ChatLLM:
    """A model that finds `pages` with web search, opens them all with one
    open_url call, and answers `answer`."""
    return ChatLLM(
        [
            tool_step(WebSearchTool.NAME, "search", {"queries": ["guide"]}),
            tool_step(
                OPEN_URL_SHAPES[ToolFamily.OPENAI].name,
                "open",
                {"urls": [p.url for p in pages]},
            ),
            Delta(content=answer),
        ]
    )


def _excerpt(index: int, page: MockWebContent) -> str:
    """The text that the model gets of a page: 15,000 characters around its
    snippet."""
    return inference_section_from_internet_page_scrape(
        page.to_web_content(), _snippet(index)
    ).combined_content


def _file_pages(data: bytes) -> list[SearchResult]:
    return [SearchResult.model_validate_json(line) for line in data.splitlines()]


def _open_url_packets(parts: Sequence[object]) -> list[packets.PacketObj]:
    """The open_url card's packets and the citations of streamed parts or
    replayed packets. Replay sends saved documents, which add their row IDs;
    the comparison keeps the fields that both have. A live call sends each
    page as it opens, in no fixed order, and a replay sends them together, so
    the pages are one packet, in document ID order."""
    objects: list[packets.PacketObj] = []
    merged: packets.OpenUrlDocuments | None = None
    for part in parts:
        obj = part.obj if isinstance(part, packets.Packet) else part
        if isinstance(obj, packets.OpenUrlDocuments):
            if merged is None:
                merged = packets.OpenUrlDocuments(documents=[])
                objects.append(merged)
            merged.documents = sorted(
                [
                    *merged.documents,
                    *(
                        SearchDoc.model_validate(dict(document))
                        for document in obj.documents
                    ),
                ],
                key=lambda document: document.document_id,
            )
        elif isinstance(
            obj, (packets.OpenUrlStart, packets.OpenUrlUrls, packets.CitationInfo)
        ):
            objects.append(obj)
    return objects


@pytest.mark.parametrize("vm_fails", [False, True], ids=["spilled", "vm_fails"])
@pytest.mark.usefixtures("node")
def test_open_url_spills_whole_pages_and_the_model_keeps_excerpts_and_citations(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
    vm_fails: bool,
) -> None:
    if vm_fails:
        node.agent.write_failures[ANY_PATH] = WriteFailure(
            SandboxDaemonErrorReason.INTERNAL
        )
    # Each page is over its 15,000-character excerpt.
    pages = [_web_page(index, 40_000) for index in range(1, MAX_URLS_PER_CALL + 1)]
    whole = [page.content for page in pages]
    # The answer cites a page whose middle only the file holds.
    llm = _search_and_open(pages, "The seventh page explains it [7].")
    parts = _send_with_pages(chat, db_session, monkeypatch, pages, llm)

    if vm_fails:
        # The model keeps the excerpts, with a note that the save failed.
        shown, failed = last_tool_text(llm, "open").split("\n\n")
        assert failed == SPILL_FAILED_NOTE
        assert [
            page.content
            for page in SearchResults.model_validate_json(shown).results[:5]
        ] == [_excerpt(index, page) for index, page in enumerate(pages[:5], start=1)]
        return
    document_ids = [WEB_SEARCH_PREFIX + page.url for page in pages]
    [(path, data)] = _spills(node, chat.ref(db_session)).items()
    # The file holds each whole page, one for each line, with its citation
    # number.
    assert _file_pages(data) == [
        SearchResult(document=number, title=page.title, url=page.url, content=text)
        for number, (page, text) in enumerate(zip(pages, whole, strict=True), start=1)
    ]
    # The model gets the excerpts that a chat without a sandbox gets, then
    # the note with the list of pages.
    shown = last_tool_text(llm, "open")
    excerpts, note = shown.split("\n\n<persisted-output ")
    shown_pages = SearchResults.model_validate_json(excerpts).results
    assert [page.content for page in shown_pages[:5]] == [
        _excerpt(index, page) for index, page in enumerate(pages[:5], start=1)
    ]
    assert "END-7" not in shown
    listing = "\n".join(
        f'{number}. [{number}] "{page.title}" "{page.url}": {len(text):,} characters'
        for number, (page, text) in enumerate(zip(pages, whole, strict=True), start=1)
    )
    assert f"<persisted-output {note}" == _note(
        path,
        len(data),
        "The pages above are excerpts. The file holds each page whole, one JSON "
        f"object for each line; cite a page by its number:\n{listing}",
    )
    # The citation resolves, and the card's highlights are the excerpts.
    [saved] = [
        result
        for result in _saved_results(db_session, chat.chat_session_id)
        if isinstance(result.details, SearchDocsResponse)
        and result.details.queries == []
    ]
    assert saved.content == shown
    assert isinstance(saved.details, SearchDocsResponse)
    assert saved.details.citation_mapping == dict(enumerate(document_ids, start=1))
    live = _open_url_packets(parts)
    assert [packet for packet in live if isinstance(packet, packets.CitationInfo)] == [
        packets.CitationInfo(citation_number=7, document_id=document_ids[6])
    ]
    [documents] = [
        packet.documents
        for packet in live
        if isinstance(packet, packets.OpenUrlDocuments)
    ]
    excerpts = {
        WEB_SEARCH_PREFIX + page.url: [_excerpt(index, page)]
        for index, page in enumerate(pages, start=1)
    }
    assert {
        document.document_id: document.match_highlights for document in documents
    } == excerpts
    [replayed] = chat.replayed(db_session)
    assert _open_url_packets(replayed) == live


@pytest.mark.usefixtures("node")
def test_pages_within_their_excerpts_do_not_spill(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    pages = [_web_page(index, 10_000) for index in range(1, 3)]
    llm = _search_and_open(pages, "Done.")
    _send_with_pages(chat, db_session, monkeypatch, pages, llm)

    shown = SearchResults.model_validate_json(last_tool_text(llm, "open")).results
    assert [page.content for page in shown] == [page.content for page in pages]
    assert _spills(node, chat.ref(db_session)) == {}


@pytest.mark.usefixtures("node")
def test_a_page_a_little_longer_than_its_excerpt_spills(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    page = _web_page(1, 15_100)
    llm = _search_and_open([page], "Done.")
    _send_with_pages(chat, db_session, monkeypatch, [page], llm)

    assert len(page.content) - len(_excerpt(1, page)) < 200
    [data] = _spills(node, chat.ref(db_session)).values()
    assert [spilled.content for spilled in _file_pages(data)] == [page.content]


def _program_pages(urls: Sequence[str]) -> str:
    """A program that opens `urls` and prints each page's citation number,
    length and whether a limit cut it."""
    return (
        f"r = await tools.open_url(urls={list(urls)!r})\n"
        "for page in r['results']:\n"
        "    print(page['document'], len(page['content']), "
        "page['content'].endswith(' [...truncated]'))\n"
    )


def _printed_pages(llm: ChatLLM, call_id: str) -> list[tuple[int, int, bool]]:
    output = last_tool_text(llm, call_id).rsplit("Output:\n", 1)[1]
    return [
        (int(number), int(length), cut == "True")
        for number, length, cut in (line.split() for line in output.splitlines())
    ]


@pytest.mark.usefixtures("node")
@pytest.mark.parametrize("code_mode", [False, True], ids=["direct", "nested"])
def test_a_page_past_the_call_limit_keeps_the_excerpt_that_the_model_got(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
    code_mode: bool,
) -> None:
    monkeypatch.setattr(
        open_url_tool,
        "OPEN_URL_PROGRAM_MAX_CHARS" if code_mode else "OPEN_URL_MAX_CHARS",
        110_000,
    )
    pages = [_web_page(index, 40_000) for index in range(1, 5)]
    if code_mode:
        llm = ChatLLM(
            [
                code_step(
                    OPENAI_CODE_MODE,
                    "cell",
                    _program_pages([page.url for page in pages]),
                ),
                Delta(content="Done."),
            ]
        )
        _send_with_pages(chat, db_session, monkeypatch, pages, llm, code_mode=True)
        kept = _printed_pages(llm, "cell")
        # Results of calls inside a program do not spill.
        assert _spills(node, chat.ref(db_session)) == {}
    else:
        llm = _search_and_open(pages, "Done.")
        _send_with_pages(chat, db_session, monkeypatch, pages, llm)
        [(path, data)] = _spills(node, chat.ref(db_session)).items()
        saved = _file_pages(data)
        kept = [
            (
                page.document,
                len(page.content),
                page.content.endswith(TRUNCATED_CONTENT_SUFFIX),
            )
            for page in saved
        ]
        shown, note = last_tool_text(llm, "open").split("\n\n<persisted-output ")
        # The fourth page holds the excerpt that the model got, and the note
        # names every page.
        assert saved[3] == SearchResults.model_validate_json(shown).results[3]
        assert "\n4. [4] " in note
    # Two pages whole, the third cut at the limit after its snippet, so
    # longer than its excerpt, and the fourth an excerpt.
    lengths = [len(page.content) for page in pages]
    assert [(number, length) for number, length, _ in kept[:2]] == [
        (1, lengths[0]),
        (2, lengths[1]),
    ]
    assert kept[2][2] and len(_excerpt(3, pages[2])) < kept[2][1] < lengths[2]
    assert len(kept) == 4 and kept[3][0] == 4 and kept[3][1] < 20_000


@pytest.mark.usefixtures("node")
@pytest.mark.parametrize(
    ("code_mode", "kept_chars"),
    [
        pytest.param(False, 5_000, id="direct_cut_shorter_than_the_excerpt"),
        pytest.param(False, 40_000, id="direct_cut_before_the_snippet"),
        pytest.param(True, 5_000, id="nested_cut_shorter_than_the_excerpt"),
    ],
)
def test_a_page_that_the_limit_cuts_short_keeps_its_excerpt(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
    code_mode: bool,
    kept_chars: int,
) -> None:
    # The limit keeps about `kept_chars` of the second page, whose snippet
    # is 100,000 characters in.
    pages = [_web_page(1, 40_000), _web_page(2, 200_000)]
    monkeypatch.setattr(
        open_url_tool,
        "OPEN_URL_PROGRAM_MAX_CHARS" if code_mode else "OPEN_URL_MAX_CHARS",
        len(pages[0].content) + kept_chars,
    )
    if code_mode:
        llm = ChatLLM(
            [
                code_step(
                    OPENAI_CODE_MODE,
                    "cell",
                    _program_pages([page.url for page in pages]),
                ),
                Delta(content="Done."),
            ]
        )
        _send_with_pages(chat, db_session, monkeypatch, pages, llm, code_mode=True)
        # With no search before it, the call has no snippets, so its excerpt
        # is the page's head.
        head = inference_section_from_internet_page_scrape(
            pages[1].to_web_content(), ""
        ).combined_content
        assert _printed_pages(llm, "cell") == [
            (1, len(pages[0].content), False),
            (2, len(head), True),
        ]
        return
    llm = _search_and_open(pages, "Done.")
    _send_with_pages(chat, db_session, monkeypatch, pages, llm)
    [data] = _spills(node, chat.ref(db_session)).values()
    [first, second] = _file_pages(data)
    assert first.content == pages[0].content
    assert second.content == _excerpt(2, pages[1])


@pytest.mark.usefixtures("node")
def test_a_program_gets_less_of_one_call_than_a_direct_call(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    chat: SandboxChat,
) -> None:
    """A program holds its results in its memory, so each of its calls keeps
    OPEN_URL_PROGRAM_MAX_CHARS of whole pages."""
    pages = [_web_page(index, 150_000) for index in range(1, 3)]
    llm = ChatLLM(
        [
            code_step(
                OPENAI_CODE_MODE, "cell", _program_pages([page.url for page in pages])
            ),
            Delta(content="Done."),
        ]
    )
    _send_with_pages(chat, db_session, monkeypatch, pages, llm, code_mode=True)

    fields = [
        open_url_tool._estimate_result_chars(
            SearchResult(document=number, title=page.title, url=page.url, content="")
        )
        for number, page in enumerate(pages, start=1)
    ]
    # The second page keeps what the first page and both pages' other fields
    # leave of the limit, then the marker.
    assert _printed_pages(llm, "cell") == [
        (1, len(pages[0].content), False),
        (
            2,
            open_url_tool.OPEN_URL_PROGRAM_MAX_CHARS
            - len(pages[0].content)
            - sum(fields)
            + len(TRUNCATED_CONTENT_SUFFIX),
            True,
        ),
    ]


@pytest.mark.usefixtures("node")
def test_a_spilled_page_keeps_the_citation_number_of_an_earlier_turn(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    pages = [_web_page(index, 40_000) for index in range(1, 4)]
    first = ChatLLM(
        [
            tool_step(
                OPEN_URL_SHAPES[ToolFamily.OPENAI].name,
                "first",
                {"urls": [pages[1].url]},
            ),
            Delta(content="Read."),
        ]
    )
    _send_with_pages(chat, db_session, monkeypatch, pages, first)
    earlier = SearchResults.model_validate_json(
        last_tool_text(first, "first").split("\n\n<persisted-output ")[0]
    ).results[0]
    second = ChatLLM(
        [
            tool_step(
                OPEN_URL_SHAPES[ToolFamily.OPENAI].name,
                "again",
                {"urls": [p.url for p in pages]},
            ),
            Delta(content=f"As before [{earlier.document}]."),
        ]
    )
    parts = _send_with_pages(chat, db_session, monkeypatch, pages, second)

    [data] = [
        data
        for path, data in _spills(node, chat.ref(db_session)).items()
        if path.endswith("_again.txt")
    ]
    saved = _file_pages(data)
    assert [page.url for page in saved] == [page.url for page in pages]
    assert saved[1].document == earlier.document
    assert earlier.document not in {saved[0].document, saved[2].document}
    assert [
        packet
        for packet in _open_url_packets(parts)
        if isinstance(packet, packets.CitationInfo)
    ] == [
        packets.CitationInfo(
            citation_number=earlier.document,
            document_id=WEB_SEARCH_PREFIX + pages[1].url,
        )
    ]


def _section(document_id: str, title: str, url: str, content: str) -> InferenceSection:
    chunk = InferenceChunk(
        document_id=document_id,
        chunk_id=0,
        content=content,
        source_type=DocumentSource.WEB,
        semantic_identifier=title,
        title=title,
        boost=1,
        score=1.0,
        hidden=False,
        metadata={},
        match_highlights=[],
        doc_summary="",
        chunk_context="",
        updated_at=None,
        image_file_id=None,
        source_links={0: url},
        section_continuation=False,
        blurb=title,
    )
    return InferenceSection(
        center_chunk=chunk, chunks=[chunk], combined_content=content
    )


def _open_pages(
    chat: SandboxChat,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    opened: Sequence[OpenedPage],
) -> ChatLLM:
    """Send a message whose one open_url call opens `opened`; the model."""
    monkeypatch.setattr(
        OpenURLTool, "_merge_indexed_and_crawled_results", lambda *_args: list(opened)
    )
    llm = ChatLLM(
        [
            tool_step(
                OPEN_URL_SHAPES[ToolFamily.OPENAI].name,
                "open",
                {"urls": ["https://docs.example.com/page"]},
            ),
            Delta(content="Done."),
        ]
    )
    _send_with_pages(chat, db_session, monkeypatch, [], llm)
    return llm


@pytest.mark.usefixtures("node")
def test_a_page_whose_excerpt_the_call_budget_cuts_in_its_marker_spills_whole(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    url = "https://docs.example.com/long"
    overhead = open_url_tool._estimate_result_chars(
        SearchResult(document=1, title="Long", url=url, content="")
    )
    # The call's budget cuts the excerpt 7 characters before its end, in its
    # closing marker.
    excerpt_text = "m" * (MAX_CHARS_ACROSS_URLS - overhead + 7 - 30)
    excerpt = f"{TRUNCATED_CONTENT_PREFIX}{excerpt_text}{TRUNCATED_CONTENT_SUFFIX}"
    text = f"{'h' * 1_000}{excerpt_text}{'t' * 1_000}"
    section = _section(WEB_SEARCH_PREFIX + url, "Long", url, excerpt)
    llm = _open_pages(chat, db_session, monkeypatch, [OpenedPage(section, text)])

    shown, _ = last_tool_text(llm, "open").split("\n\n<persisted-output ")
    [shown_page] = SearchResults.model_validate_json(shown).results
    assert shown_page.content == excerpt[:-7] + TRUNCATED_CONTENT_SUFFIX
    [data] = _spills(node, chat.ref(db_session)).values()
    assert [page.content for page in _file_pages(data)] == [text]


@pytest.mark.usefixtures("node")
def test_pages_that_share_a_citation_number_each_spill_their_own_text(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    document_id = WEB_SEARCH_PREFIX + "https://docs.example.com/shared"
    opened = [
        OpenedPage(
            _section(
                document_id,
                f"Page {fill}",
                f"https://docs.example.com/{fill}",
                fill * 15_000 + TRUNCATED_CONTENT_SUFFIX,
            ),
            fill * 40_000,
        )
        for fill in ("x", "y")
    ]
    _open_pages(chat, db_session, monkeypatch, opened)

    [data] = _spills(node, chat.ref(db_session)).values()
    saved = _file_pages(data)
    assert [page.content for page in saved] == ["x" * 40_000, "y" * 40_000]
    assert saved[0].document == saved[1].document


def _index_document(monkeypatch: pytest.MonkeyPatch, url: str, text: str) -> None:
    """Make open_url find `url` in the index as one document with `text`."""
    monkeypatch.setattr(open_url_tool, "DISABLE_VECTOR_DB", False)
    monkeypatch.setattr(
        open_url_tool,
        "_resolve_urls_to_document_ids",
        lambda urls, _db_session: (
            [IndexedDocumentRequest(document_id="indexed-guide", original_url=urls[0])],
            [],
        ),
    )
    monkeypatch.setattr(
        OpenURLTool,
        "_retrieve_indexed_documents_with_filters",
        lambda _self, _requests, _filters: IndexedRetrievalResult(
            sections=[_section("indexed-guide", "Indexed guide", url, text)],
            missing_document_ids=[],
        ),
    )


@pytest.mark.usefixtures("node")
def test_an_indexed_document_spills_whole(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
) -> None:
    # Over the 150,000 characters that the model gets of one call.
    url = "https://wiki.example.com/guide"
    text = "i" * 200_000
    _index_document(monkeypatch, url, text)
    llm = ChatLLM(
        [
            tool_step(OPEN_URL_SHAPES[ToolFamily.OPENAI].name, "open", {"urls": [url]}),
            Delta(content="Done."),
        ]
    )
    with use_mock_content_provider():
        chat.send(llm, tool_ids=[get_builtin_tool(db_session, OpenURLTool).id])

    [data] = _spills(node, chat.ref(db_session)).values()
    [saved] = _file_pages(data)
    assert saved.content == text
    [shown] = SearchResults.model_validate_json(
        last_tool_text(llm, "open").split("\n\n<persisted-output ")[0]
    ).results
    assert len(shown.content) < MAX_CHARS_ACROSS_URLS


@pytest.mark.usefixtures("node")
@pytest.mark.parametrize("code_mode", [False, True], ids=["direct", "nested"])
def test_an_indexed_document_past_the_call_limit_keeps_more_than_its_excerpt(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    node: RunningFakeAgent,
    chat: SandboxChat,
    code_mode: bool,
) -> None:
    url = "https://wiki.example.com/guide"
    if code_mode:
        text = "i" * (open_url_tool.OPEN_URL_PROGRAM_MAX_CHARS + 50_000)
    else:
        monkeypatch.setattr(open_url_tool, "OPEN_URL_MAX_CHARS", 300_000)
        text = "i" * 400_000
    _index_document(monkeypatch, url, text)
    tool_ids = [get_builtin_tool(db_session, OpenURLTool).id]
    if code_mode:
        llm = ChatLLM(
            [
                code_step(OPENAI_CODE_MODE, "cell", _program_pages([url])),
                Delta(content="Done."),
            ]
        )
        with use_mock_content_provider():
            chat.send(llm, tool_ids=tool_ids, code_mode=True)
        [(_, length, cut)] = _printed_pages(llm, "cell")
        assert cut and MAX_CHARS_ACROSS_URLS < length < len(text)
        return
    llm = ChatLLM(
        [
            tool_step(OPEN_URL_SHAPES[ToolFamily.OPENAI].name, "open", {"urls": [url]}),
            Delta(content="Done."),
        ]
    )
    with use_mock_content_provider():
        chat.send(llm, tool_ids=tool_ids)

    [data] = _spills(node, chat.ref(db_session)).values()
    [saved] = _file_pages(data)
    head = saved.content.removesuffix(TRUNCATED_CONTENT_SUFFIX)
    assert MAX_CHARS_ACROSS_URLS < len(head) < len(text)
    assert text.startswith(head)


def test_open_url_without_a_sandbox_keeps_its_page_excerpts(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    chat: SandboxChat,
) -> None:
    monkeypatch.setattr(process_message, "HARNESS_SANDBOX_ENABLED", False)
    pages = [_web_page(index, 40_000) for index in range(1, 4)]
    llm = _search_and_open(pages, "Done.")
    _send_with_pages(chat, db_session, monkeypatch, pages, llm)

    shown = SearchResults.model_validate_json(last_tool_text(llm, "open")).results
    assert [page.content for page in shown] == [
        _excerpt(index, page) for index, page in enumerate(pages, start=1)
    ]


@pytest.mark.usefixtures("node")
def test_only_load_skill_puts_the_skill_files_in_the_vm(
    db_session: Session, chat: SandboxChat, node: RunningFakeAgent
) -> None:
    custom = f"tool-{chat.user.id.hex[:8]}"
    _, plugin, _ = make_chat_custom_skill(
        db_session,
        chat.user,
        {
            "SKILL.md": f"---\nname: {custom}\ndescription: C\n---\n\nRun it.\n",
            "scripts/run.py": "print(1)\n",
        },
    )
    llm = ChatLLM(
        [
            tool_step(SKILLS_READ_TOOL_NAME, "read", {"name": "pptx"}),
            tool_step(EXEC_COMMAND_TOOL_NAME, "exec", {"cmd": "echo hi"}),
            tool_step(LOAD_SKILL_TOOL_NAME, "load", {"name": "pptx"}),
            tool_step(LOAD_SKILL_TOOL_NAME, "again", {"name": "pptx"}),
            tool_step(LOAD_SKILL_TOOL_NAME, "custom", {"name": custom}),
            tool_step(LOAD_SKILL_TOOL_NAME, "missing", {"name": "nope"}),
            Delta(content="Done."),
        ]
    )
    try:
        chat.send(llm)
    finally:
        db_session.refresh(plugin)
        for bundle_id in delete_skill(plugin, db_session):
            delete_bundle_blob(get_default_file_store(), bundle_id)
        db_session.commit()
    assert [name for _, name in node.agent.skill_installs] == ["pptx", custom]
    files = {path for _, _, path in node.agent.files}
    assert f"{CHAT_SKILLS_PATH}/pptx/scripts/lint.py" in files
    assert f"{CHAT_SKILLS_PATH}/{custom}/scripts/run.py" in files
    assert f"{CHAT_SKILLS_PATH}/pptx/" in last_tool_text(llm, "again")
    assert "No skill is named 'nope'" in last_tool_text(llm, "missing")
