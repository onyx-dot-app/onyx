"""exec_command, write_stdin and apply_patch against FirecrackerHarnessSandbox
with a fake host agent: chat turns through the chat flow (streamed and
replayed packets, code mode values, approvals, Stop, turns that offer no
sandbox), the tools' model text and file effects, the turn lifecycle, the
Sandbox row and the chat delete purge."""

import threading
import time
from collections.abc import Callable, Generator, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from onyx.agents.models import RunStatus
from onyx.agents.runtime import Run
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
)
from onyx.chat.stop_signal_checker import request_stop
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.db import chat as db_chat
from onyx.db.chat import (
    count_turn_responses,
    create_chat_session,
    delete_all_chat_sessions_for_user,
    delete_chat_session,
    reserve_chat_response_ids,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IncognitoRecordMode, SandboxStatus
from onyx.db.mcp import create_mcp_server__no_commit
from onyx.db.models import (
    ApprovalRequest,
    ChatMessage,
    ChatSession,
    MCPServer,
    Sandbox,
    User,
)
from onyx.db.persona import upsert_persona
from onyx.deep_research.agent import DeepResearchAgent
from onyx.llm.cancellation import (
    AgentCancelled,
    CancellationSignal,
    cancellation_scope,
)
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
from onyx.server.features.build.db.sandbox import get_or_create_sandbox
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
    ExecCapReachedError,
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
from onyx.server.query_and_chat.chat_backend import decide_approval, get_chat_session
from onyx.server.query_and_chat.models import (
    ChatApprovalDecisionRequest,
    SendMessageRequest,
)
from onyx.server.query_and_chat.streaming_models import StreamingError
from onyx.tools.constants import SPAWN_AGENT_TOOL_NAME
from onyx.tools.interface import Tool
from onyx.tools.models import ToolContext
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
    ExecCommandTool,
    WriteStdinTool,
)
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
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
    """The three tools of one construction, their turn, and its sandbox
    reference."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    turn: SandboxTurn
    ref: HarnessSandboxRef
    exec_command: ExecCommandTool
    write_stdin: WriteStdinTool
    apply_patch: ApplyPatchTool

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
                allowed_tool_ids=[],
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
        packets.ApplyPatchStart(patch=ADD_A),
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
        "r = await exec_command(cmd='echo hi')\n"
        "print(sorted(r), r['output'], r['exit_code'], r['completion'])\n"
        "print(await apply_patch(input='*** Begin Patch\\n*** Add File: a.txt\\n+x\\n"
        "*** End Patch'))\n"
        "try:\n"
        "    await write_stdin(session_id='nope')\n"
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
                f"r = await exec_command(cmd='echo {'x' * 3_000}')\n"
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
def gated_server(db_session: Session, user: User) -> Generator[int, None, None]:
    server = create_mcp_server__no_commit(
        owner_email=user.email,
        name=f"sandbox_gate_{uuid4().hex[:8]}",
        description=None,
        server_url="https://example.com/mcp",
        auth_type=None,
        transport=None,
        auth_performer=None,
        db_session=db_session,
    )
    db_session.commit()
    server_id = server.id
    yield server_id
    assert chat_turn_work.wait_idle(timeout=30)
    db_session.rollback()
    # Cascades to the server's app identity and requests.
    db_session.execute(delete(MCPServer).where(MCPServer.id == server_id))
    db_session.commit()


@pytest.mark.usefixtures("node")
def test_a_turn_that_parks_for_approval_and_its_resumed_root_each_end_the_turn(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    chat: SandboxChat,
    gated_server: int,
) -> None:
    ended = _ended_turns(monkeypatch, sandbox)
    gated = _gated(gated_server, [])
    real_construct_tools = construct_tools

    def with_gated_tool(**kwargs: Any) -> dict[int, list[Tool]]:
        # Its own key, apart from the agent's tool rows.
        return {**real_construct_tools(**kwargs), -1: [gated]}

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
    assert _stops(parts) == [packets.AWAITING_APPROVAL]
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
    assert len(llm.requests) == 4
    assert ended == [ref, ref]


def _running_cats(node: RunningFakeAgent, ref: HarnessSandboxRef) -> list[str]:
    """The execution IDs of the sandbox's `cat` commands that still run."""
    return [
        execution_id
        for execution_id, execution in node.agent.executions.get(
            str(ref.sandbox_id), {}
        ).items()
        if execution.argv[-1:] == ["cat"] and execution.result is None
    ]


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
    join = _stop_when(chat, lambda: len(_running_cats(node, ref)) == 2)
    llm = ChatLLM(
        [
            # Its call returns while the command runs.
            tool_step(
                ExecCommandTool.NAME, "earlier", {"cmd": "cat", "yield_time_ms": 250}
            ),
            tool_step(
                ExecCommandTool.NAME, "exec", {"cmd": "cat", "yield_time_ms": 30_000}
            ),
        ]
    )
    try:
        parts = chat.send(llm)
    finally:
        pressed = join()

    # The 30 s wait ends with the Stop; the call renders as stopped (no end).
    assert time.monotonic() - pressed < 10
    assert _stops(parts) == ["user_cancelled"]
    ends = [obj for obj in _sandbox_packets(parts) if isinstance(obj, packets.ExecEnd)]
    assert len(ends) == 1 and ends[0].session_id is not None
    # Only the waited command dies (SIGKILL); the earlier one keeps running.
    _wait_until(lambda: len(_running_cats(node, ref)) == 1)
    executions = node.agent.executions[str(ref.sandbox_id)]
    [killed] = node.agent.cancel_calls
    result = executions[killed].result
    assert result is not None and result.completion == sandboxd_pb2.CANCELED
    assert killed not in _running_cats(node, ref)
    # The turn ends once the stopped call's thread has returned.
    _wait_until(lambda: ended == [ref])


def test_a_stop_kills_the_command_that_a_program_call_waits_on(
    db_session: Session, node: RunningFakeAgent, chat: SandboxChat
) -> None:
    ref = chat.ref(db_session)
    join = _stop_when(chat, lambda: len(_running_cats(node, ref)) == 1)
    llm = ChatLLM(
        [code_step("code", "await exec_command(cmd='cat', yield_time_ms=30000)")]
    )
    try:
        parts = chat.send(llm, code_mode=True)
    finally:
        join()

    # The cell's stop signal ends the call: the command dies, and the call
    # renders as stopped, live and on replay.
    _wait_until(lambda: not _running_cats(node, ref))
    assert len(node.agent.cancel_calls) == 1
    assert _stops(parts) == ["user_cancelled"]
    started = packets.ExecCommandStart(cmd="cat")
    assert [
        obj
        for obj in _sandbox_packets(parts)
        if not isinstance(obj, packets.SectionEnd)
    ] == [started]
    [replayed] = chat.replayed(db_session)
    assert [
        obj
        for obj in _sandbox_packets(replayed)
        if not isinstance(obj, packets.SectionEnd)
    ] == [started]


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
            message="Work.", chat_session_id=chat.chat_session_id, allowed_tool_ids=[]
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
                    allowed_tool_ids=[],
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


@pytest.mark.usefixtures("node")
def test_a_resumed_response_of_a_multi_model_turn_offers_no_sandbox(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    chat: SandboxChat,
    gated_server: int,
) -> None:
    gated = _gated(gated_server, [])
    real_construct_tools = construct_tools

    def with_gated_tool(**kwargs: Any) -> dict[int, list[Tool]]:
        # Its own key, apart from the agent's tool rows.
        return {**real_construct_tools(**kwargs), -1: [gated]}

    monkeypatch.setattr("onyx.chat.execution.construct_tools", with_gated_tool)
    offered: list[list[str]] = []

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        offered.append([tool.name for tool in request.tools])
        if request.messages and isinstance(request.messages[-1], ToolResultMessage):
            return AssistantMessage(content=[TextContent(text="done")])
        return AssistantMessage(
            content=[ToolCall(id="send", name=gated.name, arguments={"value": "x"})]
        )

    model = WaitAgentsLLM(generate)
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )
    request = SendMessageRequest(
        message="Work.",
        chat_session_id=chat.chat_session_id,
        allowed_tool_ids=[],
    )
    stops = _stops(
        list(
            handle_multi_model_stream(
                new_msg_req=request,
                user=chat.user,
                llm_overrides=[
                    LLMOverride(model_version="a"),
                    LLMOverride(model_version="b"),
                ],
            )
        )
    )
    assert stops == [packets.AWAITING_APPROVAL] * 2
    first = db_session.scalars(
        select(ApprovalRequest)
        .where(ApprovalRequest.chat_session_id == chat.chat_session_id)
        .order_by(ApprovalRequest.chat_message_id)
    ).first()
    assert first is not None
    response_id = first.chat_message_id
    with get_session_with_current_tenant() as session:
        decide_approval(
            approval_id=first.id,
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
    # Two first steps, then the resumed response's answer step.
    assert len(offered) == 3
    assert all(ExecCommandTool.NAME not in names for names in offered)
    assert all(gated.name in names for names in offered)
    # A regeneration of the question is another turn, with one response.
    with get_session_with_current_tenant() as session:
        question_id = session.get_one(ChatMessage, response_id).parent_message_id
        assert question_id is not None
        [regenerated] = reserve_chat_response_ids(
            session, chat.chat_session_id, question_id, ["a"]
        )
        assert count_turn_responses(session, response_id) == 2
        assert count_turn_responses(session, regenerated) == 1


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


@pytest.mark.usefixtures("node")
def test_a_numeric_session_id_keeps_the_exec_card(chat: SandboxChat) -> None:
    # Models trained on Codex send the session ID as a number.
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


@pytest.mark.usefixtures("sandbox", "node")
def test_an_unknown_exec_session_is_a_tool_error(make_tools: MakeTools) -> None:
    # Models trained on Codex send the session ID as a number.
    result, _ = _run(make_tools().write_stdin, {"session_id": 123, "chars": ""})
    assert result.is_error
    assert result.content == str(ExecSessionNotFoundError("123"))


@pytest.mark.usefixtures("sandbox")
def test_a_patch_at_the_command_cap_is_a_tool_error(
    node: RunningFakeAgent, make_tools: MakeTools
) -> None:
    tools = make_tools()
    # The file check runs as a command, which the daemon refuses at its cap.
    node.agent.max_running_executions = 0
    result, _ = _run(tools.apply_patch, {"input": ADD_A})

    assert result.is_error
    assert result.content == str(ExecCapReachedError())
    assert _files(node, tools.ref) == {}


@pytest.mark.parametrize(
    ("kill_error", "kept"),
    [
        (SandboxDaemonErrorReason.INTERNAL, True),
        (SandboxDaemonErrorReason.EXECUTION_NOT_FOUND, False),
    ],
    ids=["kill_failed", "command_gone"],
)
@pytest.mark.usefixtures("sandbox")
def test_a_stopped_call_whose_kill_fails_keeps_the_command_reachable(
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

    def stop() -> None:
        _wait_until(lambda: len(_running_cats(node, ref)) == 1)
        signal.cancel()

    stopper = threading.Thread(target=stop)
    stopper.start()
    with cancellation_scope(signal), pytest.raises(AgentCancelled):
        _run(tools.exec_command, {"cmd": "cat", "yield_time_ms": 30_000})
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
    # Deletes read no content: binary and large files go too.
    agent.files[_key(ref, "image.bin")] = b"\xff\xfe\x00"
    agent.files[_key(ref, "big.log")] = b"x" * (
        sandbox_tools.APPLY_PATCH_MAX_FILE_BYTES + 1
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
        "*** Update File: link.txt\n"
        "@@\n"
        "-t\n"
        "+T\n"
        "*** Delete File: image.bin\n"
        "*** Delete File: big.log\n"
        "*** End Patch"
    )
    result, _ = _run(tools.apply_patch, {"input": patch_text})

    assert result.content == (
        "Success. Updated the following files:\n"
        "A new/dir/hello.txt\nA tool.sh\nM run.sh\nM moved/new.txt\nM link.txt\n"
        "D image.bin\nD big.log\n"
    )
    assert _files(node, ref) == {
        "new/dir/hello.txt": b"hi\n",
        "tool.sh": b"new\n",
        "run.sh": b"a\nB\nc\n",
        # Kept lines keep their endings; new lines use the file's first one.
        "moved/new.txt": b"z\r\ny\r\n",
        "real/target.txt": b"T\n",
    }
    # An add over a file and an update keep the file's mode; an update edits
    # a link's target in place.
    assert agent.file_modes[_key(ref, "new/dir/hello.txt")] == 0o644
    assert agent.file_modes[_key(ref, "tool.sh")] == 0o700
    assert agent.file_modes[_key(ref, "run.sh")] == 0o755
    assert agent.links[_key(ref, "link.txt")] == "real/target.txt"
    assert result.details == ApplyPatchResult(
        files=[
            ApplyPatchFileChange(path="new/dir/hello.txt", change="add"),
            ApplyPatchFileChange(path="tool.sh", change="add"),
            ApplyPatchFileChange(path="run.sh", change="update"),
            ApplyPatchFileChange(
                path="old.txt", change="update", move_path="moved/new.txt"
            ),
            ApplyPatchFileChange(path="link.txt", change="update"),
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
            # Two spellings of one file.
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Delete File: ./new.txt\n*** End Patch",
            "apply_patch verification failed: multiple operations target new.txt",
        ),
        (
            # A link and its target.
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Update File: link.txt\n@@\n-a\n+A\n"
            "*** Delete File: keep.py\n*** End Patch",
            "apply_patch verification failed: multiple operations target keep.py",
        ),
        (
            # A link into a read-only root.
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Add File: uploads/new.txt\n+u\n*** End Patch",
            "apply_patch verification failed: uploads/new.txt leads to "
            "/mnt/user-uploads/new.txt, outside the session directory",
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
            "*** Update File: out.txt\n@@\n-a\n+b\n*** End Patch",
            "apply_patch verification failed: out.txt leads to /etc/hosts, "
            "outside the session directory; edit that file with exec_command",
        ),
        (
            # A link to the session directory.
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Add File: here\n+h\n*** End Patch",
            "apply_patch verification failed: here leads to {root}, which is the "
            "session directory, not a file",
        ),
        (
            # A member of a link loop, which a write would replace.
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Add File: loop\n+l\n*** End Patch",
            "apply_patch verification failed: Cannot resolve 'loop': a symbolic link on its path loops",
        ),
        (
            # A link into a loop, and a path below a loop member.
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Add File: into_loop\n+l\n*** End Patch",
            "apply_patch verification failed: Cannot resolve 'into_loop': a symbolic link on its path loops",
        ),
        (
            "*** Begin Patch\n*** Add File: new.txt\n+n\n"
            "*** Update File: loop/x.txt\n@@\n-a\n+b\n*** End Patch",
            "apply_patch verification failed: Cannot resolve 'loop/x.txt': a symbolic link on its path loops",
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
    node.agent.links[_key(ref, "uploads")] = "/mnt/user-uploads"
    node.agent.links[_key(ref, "here")] = "."
    node.agent.links[_key(ref, "loop")] = "loop2"
    node.agent.links[_key(ref, "loop2")] = "loop"
    node.agent.links[_key(ref, "into_loop")] = "loop/z"
    links = dict(node.agent.links)

    result, _ = _run(tools.apply_patch, {"input": patch_text})

    assert result.is_error
    assert result.content.startswith(
        error.replace("{root}", session_workspace(ref.session_id))
    )
    assert _files(node, ref) == {key[2]: data for key, data in before.items()}
    assert node.agent.links == links


@pytest.mark.usefixtures("sandbox")
def test_a_patch_follows_chained_links_and_finds_files_in_large_directories(
    node: RunningFakeAgent, make_tools: MakeTools
) -> None:
    tools = make_tools()
    ref = tools.ref
    tools.turn.sandbox.ensure_running(ref)
    agent = node.agent
    agent.links[_key(ref, "sub")] = "deep/nested"
    agent.links[_key(ref, "deep/nested/f")] = "../g"
    agent.files[_key(ref, "deep/g")] = b"g\n"
    agent.file_modes[_key(ref, "deep/g")] = 0o600
    # More entries than one directory listing returns.
    agent.files.update(
        {_key(ref, f"big/{index:05}.txt"): b"x\n" for index in range(10_001)}
    )
    patch_text = (
        "*** Begin Patch\n"
        "*** Update File: sub/f\n@@\n-g\n+G\n"
        "*** Update File: big/10000.txt\n@@\n-x\n+y\n"
        "*** End Patch"
    )
    result, _ = _run(tools.apply_patch, {"input": patch_text})

    assert result.content == (
        "Success. Updated the following files:\nM sub/f\nM big/10000.txt\n"
    )
    # sub/f leads to deep/nested/f, which leads to deep/g.
    assert agent.files[_key(ref, "deep/g")] == b"G\n"
    assert agent.file_modes[_key(ref, "deep/g")] == 0o600
    assert agent.links[_key(ref, "deep/nested/f")] == "../g"
    assert agent.files[_key(ref, "big/10000.txt")] == b"y\n"


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


# The turn


@pytest.mark.usefixtures("node")
def test_a_subagent_that_ends_during_a_root_call_leaves_the_turn_to_the_root(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    sandbox: FirecrackerHarnessSandbox,
    chat: SandboxChat,
) -> None:
    """Subagents share the root's sandbox tools. A subagent run that releases
    while the root's sandbox call runs ends no turn; the root's release ends
    it once."""
    ended = _ended_turns(monkeypatch, sandbox)
    child_released = threading.Event()
    released_work = Run._released_work

    def recorded_released_work(run: Run) -> None:
        released_work(run)
        if run.parent_run_id is not None:
            child_released.set()

    monkeypatch.setattr(Run, "_released_work", recorded_released_work)
    exec_command = sandbox.exec_command
    ended_during_call: list[list[HarnessSandboxRef]] = []

    def exec_after_the_child(
        ref: HarnessSandboxRef, cmd: str, **kwargs: Any
    ) -> Iterator[ExecEvent]:
        # The call has started its turn; the child ends meanwhile.
        assert child_released.wait(30)
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
            allowed_tool_ids=[],
            accepts_follow_ups=True,
        ),
        user=chat.user,
    ):
        pass
    assert chat_turn_work.wait_idle(timeout=30)

    assert child_released.is_set()
    assert ended_during_call == [[]]
    assert ended == [chat.ref(db_session)]


@pytest.mark.usefixtures("node")
def test_each_end_of_a_used_turn_ends_it(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    make_tools: MakeTools,
) -> None:
    ended = _ended_turns(monkeypatch, sandbox)
    tools = make_tools()
    end_run = tools.exec_command.end_run
    assert end_run is not None
    # The three tools share one end, which the root chat agent calls once per
    # run.
    assert {tool.end_run for tool in tools.all} == {end_run}

    def busy() -> bool:
        return sandbox.is_busy(tenant_id=TENANT_ID, sandbox_id=tools.ref.sandbox_id)

    # A run without a call ends no turn.
    end_run()
    assert ended == []
    # A call renews the turn before it runs, so a failed call keeps the
    # sandbox busy until its run ends.
    assert _run(tools.write_stdin, {"session_id": "nope"})[0].is_error
    assert busy()
    end_run()
    assert not busy()

    # A later run's call renews the turn, and that run's end ends it again.
    assert not _run(tools.apply_patch, {"input": ADD_A})[0].is_error
    assert busy()
    end_run()
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
    built: list[list[Tool]] = []
    create_chat_agent = execution.create_chat_agent

    def recorded_create_chat_agent(
        *args: Any, **kwargs: Any
    ) -> ChatAgent | DeepResearchAgent:
        agent = create_chat_agent(*args, **kwargs)
        built.append(
            [tool for tool in agent.application_tools if tool.name in SANDBOX_NAMES]
        )
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
    for tools in built:
        if enabled:
            # One turn serves the three tools, which have no tool row.
            assert sorted(tool.name for tool in tools) == sorted(SANDBOX_NAMES)
            assert {tool.id for tool in tools} == {None}
            assert len({tool.end_run for tool in tools}) == 1
        else:
            assert tools == []


# The Sandbox row


def test_concurrent_first_calls_create_one_terminated_sandbox_row(
    db_session: Session, tenant_cache: CacheBackend, make_test_user: MakeTestUser
) -> None:
    user = make_test_user("sandbox_row_race")

    def get_or_create() -> UUID:
        with get_session_with_current_tenant() as session:
            return get_or_create_sandbox(session, user.id).id

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = set(pool.map(lambda _: get_or_create(), range(8)))
        [row] = db_session.scalars(select(Sandbox).where(Sandbox.user_id == user.id))
        assert ids == {row.id}
        assert row.status is SandboxStatus.TERMINATED
    finally:
        _forget_sandboxes(db_session, tenant_cache, user.id)


# Chat session delete


def test_a_chat_delete_purges_the_session_directory_hard_or_soft(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    make_tools: MakeTools,
) -> None:
    monkeypatch.setattr(purge, "HARNESS_SANDBOX_ENABLED", True)
    monkeypatch.setattr(db_chat, "HARNESS_SANDBOX_ENABLED", True)
    refs: dict[str, HarnessSandboxRef] = {}
    for name in ("hard", "soft", "bulk"):
        chat_session = create_chat_session(db_session, name, user.id, persona_id=0)
        tools = make_tools(chat_session.id)
        assert not _run(tools.apply_patch, {"input": ADD_A})[0].is_error
        refs[name] = tools.ref
        assert _files(node, refs[name]) == {"a.txt": b"x\n"}
    unused = create_chat_session(db_session, "unused", user.id, persona_id=0)

    # A session that never used the sandbox costs no VM or archive call.
    placed_calls: list[UUID] = []
    placed_if_running = sandbox._placed_if_running

    def counted(cache: CacheBackend, sandbox_id: UUID) -> object:
        placed_calls.append(sandbox_id)
        return placed_if_running(cache, sandbox_id)

    monkeypatch.setattr(sandbox, "_placed_if_running", counted)
    delete_chat_session(user.id, unused.id, db_session, hard_delete=True)
    assert placed_calls == []

    delete_chat_session(user.id, refs["hard"].session_id, db_session, hard_delete=True)
    assert _files(node, refs["hard"]) == {}
    # No one can restore a soft-deleted chat, so its files go too.
    delete_chat_session(user.id, refs["soft"].session_id, db_session, hard_delete=False)
    assert _files(node, refs["soft"]) == {}

    # A bulk delete, here a soft one, purges in the background.
    delete_all_chat_sessions_for_user(user, db_session, hard_delete=False)
    _wait_until(lambda: not _files(node, refs["bulk"]))
    # Teardown deletes the records that the purge thread still writes.
    _wait_until(
        lambda: (
            not any(
                thread.name == "fc-session-purge" for thread in threading.enumerate()
            )
        )
    )
