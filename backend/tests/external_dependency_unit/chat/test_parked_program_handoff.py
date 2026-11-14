"""A code mode program whose call waits for input parks; its run hands off,
and another process resumes the program after the answer."""

import json
import subprocess
import sys
import threading
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.agents.agent_coordination import AgentCoordinator
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
from onyx.tools.tool_implementations.code_mode.code_mode_tool import CodeModeTool
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

PROGRAM = 'print("before")\nr = await send(value="x")\nprint("sent", r)'
REQUEST_ID = "send-approval"


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


def _program_agent(
    sent: list[str], *, agent_id: str, state: AgentState | None = None
) -> ChatAgent:
    def send(invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
        value = invocation.arguments["value"]
        assert isinstance(value, str)
        sent.append(value)
        return ToolResult(content=json.dumps({"sent": value}))

    agent = chat_agent(
        FakeModelClient(_reply),
        agent_id=agent_id,
        state=state,
        tools=[FakeTool("send", send)],
        code_mode=True,
    )
    agent.before_tool_call = _ask_for_send
    return agent


def _resume_program_in_process(session_id: str, message_id: str) -> None:
    """Resume the handed-off run with fresh objects, as another API pod does."""
    SqlEngine.init_engine(pool_size=5, max_overflow=5)
    remote = store((UUID(session_id), int(message_id)))
    coordinator = AgentCoordinator()
    sent: list[str] = []

    def rebuild(checkpoint: ExecutionCheckpoint) -> Agent:
        agent_id = checkpoint.run_state.agent_id
        assert agent_id is not None
        return _program_agent(sent, agent_id=agent_id, state=checkpoint.agent_state)

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
        assert "before" in output and "sent {'sent': 'x'}" in output, output
        assert sent == ["x"]
    finally:
        try:
            assert coordinator.close(timeout=10)
        finally:
            finished.set()
            controller.result(timeout=10)
            SqlEngine.reset_engine()


def test_a_parked_program_resumes_in_another_process(
    branch: tuple[UUID, int], db_session: Session, user_message: UserMessage
) -> None:
    owner = store(branch)
    sent: list[str] = []
    coordinator = owner.bind(
        AgentCoordinator(),
        build_agent=lambda _checkpoint: _program_agent([], agent_id=str(branch[0])),
    )
    agent = _program_agent(sent, agent_id=str(branch[0]))
    run = agent.start(messages=[user_message], max_steps=3, coordinator=coordinator)
    file_store = get_default_file_store()
    prefix = f"agent-checkpoint/{branch[0]}/"
    try:
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
        # The resumed program deleted its dump once it loaded it.
        assert file_store.list_files_by_prefix(prefix) == []
    finally:
        coordinator.close(timeout=1)
        for record in file_store.list_files_by_prefix(prefix):
            file_store.delete_file(record.file_id, error_on_missing=False)
