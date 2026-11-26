"""A code mode program whose call waits for input parks; its run hands off,
and another process resumes the program after the answer. A cell that runs
while the request waits ends before the run hands off and keeps its result.
A cell that waits for its own request in the background is saved with the
run, and continues in the other process after its answer."""

import json
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import JsonValue
from sqlalchemy.orm import Session

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.events import (
    AgentEvent,
    AgentSuspendedEvent,
    InputEndedEvent,
)
from onyx.agents.models import (
    AgentState,
    ExecutionCheckpoint,
    RunStatus,
    ToolCallContext,
)
from onyx.agents.runtime import Agent, RunHooks
from onyx.agents.tools import (
    HumanToolAnswer,
    InputDecision,
    InputMode,
    NestedInputWait,
    PendingToolInput,
    ToolInvocation,
    ToolOutcome,
)
from onyx.chat.agent import ChatFeature
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
from onyx.tools.constants import EXECUTE_CODE_TOOL_NAME, WAIT_TOOL_NAME
from onyx.tools.models import ToolContext
from onyx.utils.threadpool_concurrency import start_thread_future
from tests.external_dependency_unit.chat.test_run_store import (
    branch,
    chat_agent,
    store,
    user_message,
)
from tests.unit.onyx.agents.fakes import FakeModelClient
from tests.unit.onyx.tools.code_mode.fakes import FakeTool, until

__all__ = ["branch", "user_message"]

PROGRAM = 'print("before")\nr = await tools.send(value="x")\nprint("sent", r)'
REQUEST_ID = "send-approval"
# The model's first cell in each scenario: none, one that runs in the
# background until its `wait` call returns, or one that asks to send "bg"
# in the background.
FIRST_CELLS = {
    "program": None,
    "running": 'yield_control()\nr = await tools.wait(value="b")\nprint("waited", r)',
    "asking": 'yield_control()\nr = await tools.send(value="bg")\nprint("sent", r)',
}
BACKGROUND_REQUEST_ID = "send-bg"


def _ask_for_send(context: ToolCallContext) -> PendingToolInput | None:
    if context.call.name != "send":
        return None
    return PendingToolInput(
        request_id=BACKGROUND_REQUEST_ID
        if context.call.arguments.get("value") == "bg"
        else REQUEST_ID,
        prompt="Send?",
        mode=InputMode.EXECUTE,
    )


class _AskingFeature:
    """Chat whose `send` calls wait for approval (`_ask_for_send`)."""

    def __init__(self, chat: ChatFeature) -> None:
        self.chat = chat

    def bind(self) -> RunHooks:
        return self.chat.bind().model_copy(update={"before_tool_call": _ask_for_send})

    def restore_state(self, state: Mapping[str, JsonValue]) -> None:
        self.chat.restore_state(state)


def _steps(scenario: str) -> tuple[ToolCall, ...]:
    """One call per step: the scenario's first cell, if any, a program that
    waits for approval, then a read of the first cell."""
    first = FIRST_CELLS[scenario]
    program = ToolCall(
        id="program", name=EXECUTE_CODE_TOOL_NAME, arguments={"code": PROGRAM}
    )
    if first is None:
        return (program,)
    return (
        ToolCall(
            id="background", name=EXECUTE_CODE_TOOL_NAME, arguments={"code": first}
        ),
        program,
        ToolCall(
            id="read",
            name=WAIT_TOOL_NAME,
            arguments={"cell_id": 1, "yield_time_ms": 10_000},
        ),
    )


def _program_agent(
    sent: list[str],
    *,
    agent_id: str,
    scenario: str,
    state: AgentState | None = None,
    gate: threading.Event | None = None,
) -> Agent:
    """The model runs the scenario's steps, then answers with the last result.
    A `wait` call returns once `gate` opens, or stops when its cell stops."""
    steps = _steps(scenario)

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        results = [m for m in request.messages if isinstance(m, ToolResultMessage)]
        if len(results) < len(steps):
            return AssistantMessage(content=[steps[len(results)]])
        return AssistantMessage(content=[TextContent(text=results[-1].text)])

    def send(invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
        value = invocation.arguments["value"]
        assert isinstance(value, str)
        sent.append(value)
        return ToolResult(content=json.dumps({"sent": value}))

    def wait(invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
        assert gate is not None
        deadline = time.monotonic() + 30
        while not gate.wait(0.05):
            invocation.cancellation.check()
            assert time.monotonic() < deadline
        return ToolResult(content=json.dumps({"waited": invocation.arguments["value"]}))

    agent = chat_agent(
        FakeModelClient(reply),
        agent_id=agent_id,
        state=state,
        tools=[FakeTool("send", send), FakeTool("wait", wait)],
        code_mode=True,
    )
    assert isinstance(agent.feature, ChatFeature)
    agent.feature = _AskingFeature(agent.feature)
    return agent


def _resume_program_in_process(session_id: str, message_id: str, scenario: str) -> None:
    """Resume the handed-off run with fresh objects, as another API pod does."""
    SqlEngine.init_engine(pool_size=5, max_overflow=5)
    remote = store((UUID(session_id), int(message_id)))
    coordinator = AgentCoordinator()
    sent: list[str] = []

    def rebuild(checkpoint: ExecutionCheckpoint, _depth: int) -> Agent:
        agent_id = checkpoint.run_state.agent_id
        assert agent_id is not None
        # A running first cell ended before the handoff; no call waits here.
        return _program_agent(
            sent, agent_id=agent_id, scenario=scenario, state=checkpoint.agent_state
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
        for request_id in (
            [REQUEST_ID, BACKGROUND_REQUEST_ID]
            if scenario == "asking"
            else [REQUEST_ID]
        ):
            resumed.submit(
                HumanToolAnswer(request_id=request_id, decision=InputDecision.APPROVE)
            )
        output = resumed.result(timeout=30).output.text
        assert resumed.wait_for_idle(timeout=30)
        if scenario == "program":
            assert sent == ["x"]
            assert "before" in output and "sent {'sent': 'x'}" in output, output
        elif scenario == "running":
            assert sent == ["x"]
            # wait points to the closing record that holds the end of
            # the cell that ended before the run paused in the other process.
            assert output == (
                "Cell 1 completed before the run paused; its output and result "
                "are in its earlier result."
            ), output
        else:
            # The background cell's approved call ran here.
            assert sorted(sent) == ["bg", "x"]
            assert "sent {'sent': 'bg'}" in output, output
    finally:
        try:
            assert coordinator.close(timeout=10)
        finally:
            finished.set()
            controller.result(timeout=10)
            SqlEngine.reset_engine()


@pytest.mark.parametrize("scenario", list(FIRST_CELLS))
def test_a_parked_program_resumes_in_another_process(
    scenario: str,
    branch: tuple[UUID, int],
    db_session: Session,
    user_message: UserMessage,
) -> None:
    owner = store(branch)
    sent: list[str] = []
    gate = threading.Event()
    coordinator = owner.bind(
        AgentCoordinator(),
        build_agent=lambda _checkpoint, _depth: _program_agent(
            [], agent_id=str(branch[0]), scenario=scenario, gate=gate
        ),
    )
    agent = _program_agent(sent, agent_id=str(branch[0]), scenario=scenario, gate=gate)
    suspended = threading.Event()
    events: list[AgentEvent] = []

    def on_event(event: AgentEvent) -> None:
        events.append(event)
        if isinstance(event, AgentSuspendedEvent):
            suspended.set()

    run = agent.start(
        messages=[user_message],
        max_steps=5,
        coordinator=coordinator,
        on_event=on_event,
    )
    file_store = get_default_file_store()
    prefix = f"agent-checkpoint/{branch[0]}/"
    try:
        if scenario == "running":
            until(
                lambda: (
                    "program"
                    in (
                        progress.pending_tool_calls
                        if (progress := run.snapshot().progress) is not None
                        else {}
                    )
                ),
                timeout=30,
            )
            # The background cell still runs, so the run does not suspend.
            assert not suspended.wait(1)
            assert run.status != RunStatus.SUSPENDED
            gate.set()
        saved = run.wait_until_settled(timeout=30)
        assert saved.status == RunStatus.SUSPENDED, saved.failure
        assert saved.progress is not None
        assert isinstance(saved.progress.pending_tool_calls["program"], NestedInputWait)
        # The background cell's request stays open with the run.
        assert list(saved.progress.open_inputs) == (
            [BACKGROUND_REQUEST_ID] if scenario == "asking" else []
        )
        assert not any(isinstance(event, InputEndedEvent) for event in events)
        assert run.wait_for_idle(timeout=10)

        owner.handoff(run.id)

        db_session.expire_all()
        assert db_session.get(ChatResponseCheckpoint, branch[1]) is not None
        dumps = file_store.list_files_by_prefix(prefix)
        # A dump for each parked program.
        assert len(dumps) == (2 if scenario == "asking" else 1)
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
                scenario,
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
        gate.set()
        coordinator.close(timeout=1)
        for record in file_store.list_files_by_prefix(prefix):
            file_store.delete_file(record.file_id, error_on_missing=False)
