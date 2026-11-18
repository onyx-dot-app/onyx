"""exec_command, write_stdin, apply_patch, edit and write against
FirecrackerHarnessSandbox with a fake host agent: chat turns through the chat flow (streamed and
replayed packets, code mode values, approvals, Stop, turns that offer no
sandbox), the tools' model text and file effects, the turn lifecycle, the
Sandbox row and the chat delete purge."""

import threading
import time
from collections.abc import Callable, Generator, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from onyx.agents.models import RunStatus
from onyx.agents.runtime import Agent, Run
from onyx.agents.tools import ToolInvocation, ToolProgress
from onyx.auth.users import get_anonymous_user
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.chat import execution, process_message
from onyx.chat.agent import ChatAgent
from onyx.chat.chat_processing_checker import get_processing_stream
from onyx.chat.execution import chat_turn_work
from onyx.chat.incognito_context import teardown_incognito_session
from onyx.chat.process_message import (
    handle_multi_model_stream,
    handle_stream_message_objects,
    run_chat_turn,
)
from onyx.chat.stop_signal_checker import request_stop
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.db import chat as db_chat
from onyx.db.chat import (
    create_chat_session,
    delete_all_chat_sessions_for_user,
    delete_chat_session,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    AccountType,
    ApprovalDecision,
    IncognitoRecordMode,
    PluginInstallationPolicy,
    SandboxStatus,
)
from onyx.db.models import (
    ApprovalRequest,
    ChatMessage,
    ChatSession,
    Sandbox,
    User,
)
from onyx.db.persona import upsert_persona
from onyx.db.sandbox import (
    create_sandbox__no_commit,
    get_or_create_sandbox,
    get_sandbox_by_user_id,
)
from onyx.db.users import fetch_user_by_id
from onyx.deep_research.agent import DeepResearchAgent
from onyx.feature_flags.interface import NoOpFeatureFlagProvider
from onyx.integrations.models import ApprovalMode
from onyx.llm.cancellation import (
    AgentCancelled,
    CancellationSignal,
    cancellation_scope,
)
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
from onyx.llm.override_models import LLMOverride
from onyx.microvm.daemon_client import SandboxDaemonErrorReason
from onyx.microvm.generated.sandboxd.v1 import sandboxd_pb2
from onyx.server.features.action_policies.models import ApprovalChoice
from onyx.server.features.build import utils as build_utils
from onyx.server.features.build.sandbox import harness_factory
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
    ExecSessionNotFoundError,
    session_workspace,
)
from onyx.server.features.build.sandbox.models import (
    ExecEvent,
    ExecOutputDelta,
    HarnessSandboxRef,
    SandboxPathInfo,
)
from onyx.server.query_and_chat import streaming_models as packets
from onyx.server.query_and_chat.chat_backend import (
    decide_approval,
    delete_all_chat_sessions,
    delete_chat_session_by_id,
    get_chat_session,
)
from onyx.server.query_and_chat.models import (
    ChatApprovalDecisionRequest,
    MessageOrigin,
    SendMessageRequest,
)
from onyx.server.query_and_chat.streaming_models import StreamingError
from onyx.server.settings.models import Tier
from onyx.tools.constants import SPAWN_AGENT_TOOL_NAME
from onyx.tools.interface import Tool
from onyx.tools.models import ToolContext, ToolOptions
from onyx.tools.tool_constructor import construct_tools
from onyx.tools.tool_implementations.code_mode import cells
from onyx.tools.tool_implementations.sandbox import sandbox_tools
from onyx.tools.tool_implementations.sandbox.models import (
    ApplyPatchFileChange,
    ApplyPatchResult,
    SandboxExecResult,
)
from onyx.tools.tool_implementations.sandbox.sandbox_tools import (
    ApplyPatchTool,
    EditTool,
    ExecCommandTool,
    WriteStdinTool,
    WriteTool,
)
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
from tests.external_dependency_unit.chat.test_chat_tool_approvals import ACTION
from tests.external_dependency_unit.chat.test_parked_agent_handoff import _gated
from tests.external_dependency_unit.chat.test_wait_agents import (
    ScriptedLLM as WaitAgentsLLM,
)
from tests.external_dependency_unit.code_mode_helpers import (
    ChatLLM,
    code_step,
    last_tool_text,
    saved_cells,
    send,
    tool_step,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.db.test_chat_tool_options import (
    ResearchCapableModel,
)
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    hold_in_plugin,
    make_mcp_integration,
)
from tests.external_dependency_unit.microvm.conftest import (
    TENANT_ID,
    AddNode,
    forget_sandbox_keys,
)
from tests.external_dependency_unit.microvm.fake_agent import (
    InsecureClientFactory,
    RunningFakeAgent,
)
from tests.unit.onyx.agents.fakes import ScriptedLLM

pytestmark = pytest.mark.usefixtures("tenant_context")

SANDBOX_NAMES = frozenset(
    {ExecCommandTool.NAME, WriteStdinTool.NAME, ApplyPatchTool.NAME}
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
    apply_patch: ApplyPatchTool
    edit: EditTool
    write: WriteTool

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
    # The sandbox tools follow Craft access: turn Craft on for the deployment.
    monkeypatch.setattr(build_utils, "ENABLE_CRAFT", True)
    monkeypatch.setattr(
        build_utils, "get_default_feature_flag_provider", NoOpFeatureFlagProvider
    )
    monkeypatch.setattr(build_utils, "get_current_tier", lambda: Tier.BUSINESS)
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
        turn = SandboxTurn(
            tenant_id=TENANT_ID, user_id=user.id, chat_session_id=session_id
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
            apply_patch=ApplyPatchTool(turn),
            edit=EditTool(turn),
            write=WriteTool(turn),
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
    ) -> list[object]:
        return list(
            send(
                self.chat_session_id,
                self.user,
                llm,
                "Work in the sandbox.",
                code_mode=code_mode,
                on_part=on_part,
                tool_options=ToolOptions(allowed=[]),
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
    db_session: Session,
    user: User,
    sandbox: FirecrackerHarnessSandbox,  # noqa: ARG001
) -> SandboxChat:
    chat_session = create_chat_session(
        db_session, "sandbox chat", user.id, persona_id=DEFAULT_PERSONA_ID
    )
    return SandboxChat(user=user, chat_session_id=chat_session.id)


def _sandbox_packets(parts: Sequence[object]) -> list[packets.PacketObj]:
    """The sandbox tools' packets of streamed parts or replayed packets, and
    their section ends."""
    sandbox_types = (
        packets.ExecCommandStart,
        packets.WriteStdinStart,
        packets.ExecOutputDelta,
        packets.ExecEnd,
        packets.ApplyPatchStart,
        packets.ApplyPatchEnd,
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
            tool_step(ExecCommandTool.NAME, "exec", {"cmd": "echo hi there"}),
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
        "Process exited with code 0\nOriginal token count: 3\nOutput:\nhi there\n"
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
    llm = ChatLLM([code_step("code", program), Delta(content="Done.")])
    chat.send(llm, code_mode=True)

    text = last_tool_text(llm, "code")
    assert (
        "['completion', 'exit_code', 'original_token_count', 'output', "
        "'wall_time_seconds'] hi\n 0 exited" in text
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
    hold_in_plugin(
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
            tool_step(ExecCommandTool.NAME, "exec", {"cmd": "echo hi"}),
            tool_step(gated.name, "send", {"value": "team"}),
            tool_step(ExecCommandTool.NAME, "again", {"cmd": "echo again"}),
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
                ExecCommandTool.NAME, "earlier", {"cmd": "cat", "yield_time_ms": 250}
            ),
            tool_step(
                ExecCommandTool.NAME,
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
    llm = ChatLLM([code_step("code", f"await tools.apply_patch(input={ADD_A!r})")])
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
    assert all(ExecCommandTool.NAME not in tools for tools in both)

    db_session.execute(
        update(ChatSession)
        .where(ChatSession.id == chat.chat_session_id)
        .values(incognito_record_mode=IncognitoRecordMode.USAGE_ONLY)
    )
    db_session.commit()
    try:
        [tools] = offered(ChatLLM([Delta(content="No sandbox.")]), multi_model=False)
        assert ExecCommandTool.NAME not in tools
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
    assert ExecCommandTool.NAME not in str(request.get("tools"))


def _set_user(
    db_session: Session,
    user: User,
    *,
    craft_enabled: bool | None = None,
    account_type: AccountType = AccountType.STANDARD,
) -> None:
    row = db_session.get(User, user.id)
    if row is None:
        raise RuntimeError("the test user exists")
    row.craft_enabled = craft_enabled
    row.account_type = account_type
    db_session.commit()
    user.craft_enabled = craft_enabled
    user.account_type = account_type


def _offers_sandbox(monkeypatch: pytest.MonkeyPatch, chat: SandboxChat) -> bool:
    """Send one message; returns whether its model request had the sandbox tools."""
    llm = ChatLLM([Delta(content="Maybe a sandbox.")])
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: llm
    )
    run_chat_turn(
        new_msg_req=SendMessageRequest(
            message="Work.",
            chat_session_id=chat.chat_session_id,
            tool_options=ToolOptions(allowed=[]),
        ),
        user=chat.user,
        approval_mode=ApprovalMode.NO_APPROVER,
    )
    [request] = llm.requests
    return ExecCommandTool.NAME in str(request.get("tools"))


@pytest.mark.usefixtures("node")
def test_a_user_without_craft_access_gets_no_sandbox(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, chat: SandboxChat
) -> None:
    assert _offers_sandbox(monkeypatch, chat)

    # An admin turned Craft off for this user.
    _set_user(db_session, chat.user, craft_enabled=False)
    assert not _offers_sandbox(monkeypatch, chat)

    # Craft is off for the deployment, and the user has no override.
    _set_user(db_session, chat.user, craft_enabled=None)
    monkeypatch.setattr(build_utils, "ENABLE_CRAFT", False)
    assert not _offers_sandbox(monkeypatch, chat)


@pytest.mark.usefixtures("node")
def test_a_service_account_turn_offers_no_sandbox(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, chat: SandboxChat
) -> None:
    # An API key acts as a service account.
    _set_user(db_session, chat.user, account_type=AccountType.SERVICE_ACCOUNT)
    assert not _offers_sandbox(monkeypatch, chat)


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
        assert ExecCommandTool.NAME not in str(request.get("tools"))
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
def test_the_live_output_of_a_call_stops_at_its_token_budget(
    make_tools: MakeTools,
) -> None:
    """The final output replaces the live preview, so the preview streams no
    more than max_output_tokens x 4 bytes."""
    tools = make_tools()
    text = "a" * 200 + "z" * 200
    result, progress = _run(
        tools.exec_command, {"cmd": f"echo {text}", "max_output_tokens": 20}
    )
    streamed = "".join(
        update.details.text
        for update in progress
        if isinstance(update.details, ExecOutputDelta)
    )
    assert streamed == "a" * 80
    details = result.details
    assert isinstance(details, SandboxExecResult)
    assert details.output.startswith("a" * 40) and "tokens omitted" in details.output


@pytest.mark.usefixtures("node")
def test_a_numeric_session_id_keeps_the_exec_card(chat: SandboxChat) -> None:
    # Models may send the session ID as a number.
    llm = ChatLLM(
        [
            tool_step(WriteStdinTool.NAME, "poll", {"session_id": 123}),
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
                "code", "await tools.write_stdin(session_id='nope', yield_time_ms=1000)"
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
            "'/etc/passwd' is outside the session directory",
        ),
        (
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Add File: ../other/x.txt\n+x\n*** End Patch",
            "'../other/x.txt' leaves the session directory",
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


def _claude(steps: Sequence[Delta]) -> NamedChatLLM:
    return NamedChatLLM(steps, model_name="claude-opus-4-5")


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
    # The system prompt's sandbox section names the turn's file tools.
    assert (
        "edit files with `edit` and create or overwrite files with `write`."
        if claude
        else "edit files with `apply_patch`."
    ) in str(request["prompt"])


@pytest.mark.usefixtures("node")
def test_edit_and_write_calls_render_patch_cards_live_and_on_replay(
    db_session: Session, node: RunningFakeAgent, chat: SandboxChat
) -> None:
    llm = _claude(
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
        ]
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
    assert _sandbox_packets(parts) == expected
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
    llm = _claude([code_step("code", program), Delta(content="Done.")])
    chat.send(llm, code_mode=True)

    assert (
        "edit files with `tools.edit` and create or overwrite files with "
        "`tools.write`." in str(llm.requests[0]["prompt"])
    )
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
    llm = _claude(
        [
            Delta(tool_calls=[write_call, edit_call.model_copy(update={"index": 1})]),
            Delta(content="Done."),
        ]
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
            "'../other/x.txt' leaves the session directory",
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


@pytest.mark.usefixtures("node")
def test_a_subagent_that_ends_during_a_root_call_leaves_the_turn_to_the_root(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    chat: SandboxChat,
) -> None:
    """Subagents share the root's sandbox tools. A subagent run whose work
    drains while the root's sandbox call runs ends no turn; the root's run
    ends it once."""
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
                    arguments={"name": "helper", "instruction": "Task helper"},
                ),
                ToolCall(
                    id="exec", name=ExecCommandTool.NAME, arguments={"cmd": "echo hi"}
                ),
            ]
        )

    model = WaitAgentsLLM(generate)
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
        assert setup.sandbox_tools
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

    # A session that never used the sandbox costs no VM or archive call.
    list_calls = node.agent.list_calls
    delete_chat_session_by_id(
        unused.id, hard_delete=True, user=user, db_session=db_session
    )
    _wait_for_purges()
    assert node.agent.list_calls == list_calls

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
    assert delete_all_chat_sessions_for_user(user, db_session, hard_delete=True) == [
        first
    ]
    db_session.expire_all()
    assert db_session.get(ChatSession, first) is None
    assert db_session.get(ChatSession, created[0]) is not None
