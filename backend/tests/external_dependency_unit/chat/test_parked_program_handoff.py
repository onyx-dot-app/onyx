"""A code mode program whose call waits for input parks; its run hands off,
and another process resumes the program after the answer. A cell that runs
while the request waits ends before the run hands off and keeps its result."""

import json
import subprocess
import sys
import threading
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.events import AgentEvent, InputRequiredEvent
from onyx.agents.models import (
    AgentState,
    ExecutionCheckpoint,
    RunStatus,
    ToolCallContext,
)
from onyx.agents.runtime import Agent
from onyx.agents.tools import (
    HumanToolAnswer,
    InputDecision,
    InputMode,
    NestedInputWait,
    PendingToolInput,
    ToolInvocation,
    ToolOutcome,
)
from onyx.chat.agent import ChatAgent
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.models import ChatResponseCheckpoint
from onyx.file_store.file_store import get_default_file_store
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.tools.models import ToolContext
from onyx.tools.tool_implementations.code_mode.code_mode_tool import (
    CodeModeTool,
    WaitCodeTool,
)
from onyx.utils.threadpool_concurrency import start_thread_future
from tests.external_dependency_unit.chat.test_run_store import (
    branch,
    chat_agent,
    store,
    user_message,
)
from tests.unit.onyx.agents.fakes import FakeModelClient
from tests.unit.onyx.tools.code_mode.fakes import FakeTool

__all__ = ["branch", "user_message"]

PROGRAM = 'print("before")\nr = await tools.send(value="x")\nprint("sent", r)'
REQUEST_ID = "send-approval"
# Runs in the background until its `wait` call returns.
BACKGROUND = 'yield_control()\nr = await tools.wait(value="b")\nprint("waited", r)'
# One call per step: a background cell, a program that waits for approval,
# then a read of the background cell.
BACKGROUND_STEPS = (
    ToolCall(id="background", name=CodeModeTool.NAME, arguments={"code": BACKGROUND}),
    ToolCall(id="program", name=CodeModeTool.NAME, arguments={"code": PROGRAM}),
    ToolCall(
        id="read",
        name=WaitCodeTool.NAME,
        arguments={"cell_id": 1, "yield_time_ms": 10_000},
    ),
)


def _ask_for_send(context: ToolCallContext) -> PendingToolInput | None:
    if context.call.name != "send":
        return None
    return PendingToolInput(
        request_id=REQUEST_ID, prompt="Send?", mode=InputMode.EXECUTE
    )


def _reply(request: GenerationRequest, _signal: CancellationSignal) -> AssistantMessage:
    results = [m for m in request.messages if isinstance(m, ToolResultMessage)]
    if results:
        return AssistantMessage(content=[TextContent(text=results[-1].text)])
    return AssistantMessage(
        content=[
            ToolCall(id="program", name=CodeModeTool.NAME, arguments={"code": PROGRAM})
        ]
    )


def _background_reply(
    request: GenerationRequest, _signal: CancellationSignal
) -> AssistantMessage:
    results = [m for m in request.messages if isinstance(m, ToolResultMessage)]
    if len(results) < len(BACKGROUND_STEPS):
        return AssistantMessage(content=[BACKGROUND_STEPS[len(results)]])
    return AssistantMessage(content=[TextContent(text=results[-1].text)])


def _program_agent(
    sent: list[str],
    *,
    agent_id: str,
    state: AgentState | None = None,
    background_gate: threading.Event | None = None,
) -> ChatAgent:
    """With `background_gate`, the model runs BACKGROUND_STEPS, and the
    background cell's `wait` call returns once the gate opens."""

    def send(invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
        value = invocation.arguments["value"]
        assert isinstance(value, str)
        sent.append(value)
        return ToolResult(content=json.dumps({"sent": value}))

    def wait(invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
        assert background_gate is not None and background_gate.wait(30)
        return ToolResult(content=json.dumps({"waited": invocation.arguments["value"]}))

    agent = chat_agent(
        FakeModelClient(_reply if background_gate is None else _background_reply),
        agent_id=agent_id,
        state=state,
        tools=[FakeTool("send", send), FakeTool("wait", wait)],
        code_mode=True,
    )
    agent.before_tool_call = _ask_for_send
    return agent


def _resume_program_in_process(
    session_id: str, message_id: str, background: str = ""
) -> None:
    """Resume the handed-off run with fresh objects, as another API pod does.
    A nonempty `background` resumes the run of BACKGROUND_STEPS."""
    SqlEngine.init_engine(pool_size=5, max_overflow=5)
    remote = store((UUID(session_id), int(message_id)))
    coordinator = AgentCoordinator()
    sent: list[str] = []
    # The background cell ended before the handoff; its call does not run here.
    gate = threading.Event() if background else None

    def rebuild(checkpoint: ExecutionCheckpoint, _depth: int) -> Agent:
        agent_id = checkpoint.run_state.agent_id
        assert agent_id is not None
        return _program_agent(
            sent,
            agent_id=agent_id,
            state=checkpoint.agent_state,
            background_gate=gate,
        )

    remote.bind(coordinator, build_agent=rebuild)
    finished = threading.Event()

    def poll() -> None:
        while not finished.wait(0.01):
            remote.poll_control()

    controller = start_thread_future(poll, name="test-chat-control")
    try:
        resumed = remote.resume(message_id, context=AgentState())
        assert resumed is not None
        resumed.submit(
            HumanToolAnswer(request_id=REQUEST_ID, decision=InputDecision.APPROVE)
        )
        output = resumed.result(timeout=30).output.text
        assert resumed.wait_for_idle(timeout=30)
        assert sent == ["x"]
        if background:
            # wait_code returns the end of the cell that ended before the run
            # paused in the other process.
            assert output.startswith("Cell 1 completed before the run paused."), output
            assert "waited {'waited': 'b'}" in output, output
        else:
            assert "before" in output and "sent {'sent': 'x'}" in output, output
    finally:
        try:
            assert coordinator.close(timeout=10)
        finally:
            finished.set()
            controller.result(timeout=10)
            SqlEngine.reset_engine()


@pytest.mark.parametrize(
    "background",
    [False, True],
    ids=["program", "with_a_cell_that_ends_while_the_request_waits"],
)
def test_a_parked_program_resumes_in_another_process(
    background: bool,
    branch: tuple[UUID, int],
    db_session: Session,
    user_message: UserMessage,
) -> None:
    owner = store(branch)
    sent: list[str] = []
    gate = threading.Event() if background else None
    coordinator = owner.bind(
        AgentCoordinator(),
        build_agent=lambda _checkpoint, _depth: _program_agent(
            [], agent_id=str(branch[0]), background_gate=gate
        ),
    )
    agent = _program_agent(sent, agent_id=str(branch[0]), background_gate=gate)
    requested = threading.Event()

    def on_event(event: AgentEvent) -> None:
        if isinstance(event, InputRequiredEvent):
            requested.set()

    run = agent.start(
        messages=[user_message],
        max_steps=5,
        coordinator=coordinator,
        on_event=on_event,
    )
    file_store = get_default_file_store()
    prefix = f"agent-checkpoint/{branch[0]}/"
    try:
        if gate is not None:
            assert requested.wait(30)
            # The background cell still runs, so the run does not suspend.
            with pytest.raises(TimeoutError):
                run.wait_until_settled(timeout=1)
            gate.set()
        saved = run.wait_until_settled(timeout=30)
        assert saved.status == RunStatus.SUSPENDED, saved.failure
        assert saved.progress is not None
        assert isinstance(saved.progress.pending_tool_calls["program"], NestedInputWait)
        assert run.wait_for_idle(timeout=10)

        owner.handoff(run.id)

        db_session.expire_all()
        assert db_session.get(ChatResponseCheckpoint, branch[1]) is not None
        dumps = file_store.list_files_by_prefix(prefix)
        assert len(dumps) == 1
        db_session.rollback()

        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from tests.external_dependency_unit.chat."
                "test_parked_program_handoff import _resume_program_in_process; "
                "_resume_program_in_process(*sys.argv[1:])",
                str(branch[0]),
                str(branch[1]),
                "background" if background else "",
            ],
            cwd=Path(__file__).resolve().parents[3],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr

        assert sent == []
        saved_result = owner.read_run(run.id, "")
        assert saved_result is not None and saved_result.status == RunStatus.COMPLETE
        db_session.expire_all()
        assert db_session.get(ChatResponseCheckpoint, branch[1]) is None
        # The checkpoint owned the dump, which went when the response ended.
        assert file_store.list_files_by_prefix(prefix) == []
    finally:
        if gate is not None:
            gate.set()
        coordinator.close(timeout=1)
        for record in file_store.list_files_by_prefix(prefix):
            file_store.delete_file(record.file_id, error_on_missing=False)
