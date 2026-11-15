"""A background agent whose program call waits for approval parks; after the
decision, another process resumes it through the inbox and dispatch."""

import json
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.models import ExecutionCheckpoint, RunStatus
from onyx.agents.runtime import Agent
from onyx.agents.tools import ToolInvocation
from onyx.cache.factory import get_cache_backend
from onyx.chat.agent import ChatAgent
from onyx.chat.run_store import ChatRunStore
from onyx.db.engine.sql_engine import SqlEngine, get_session_with_tenant
from onyx.db.enums import GatedAppKind
from onyx.db.models import ChatMessage, ChatResponseCheckpoint, User
from onyx.file_store.file_store import get_default_file_store
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
)
from onyx.server.features.action_policies.models import ApprovalChoice
from onyx.tools.models import ToolApprovalScope, ToolContext
from onyx.tools.tool_implementations.code_mode.code_mode_tool import CodeModeTool
from onyx.tools.tool_implementations.subagents.subagent_tools import SpawnAgentTool
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.chat.test_chat_tool_approvals import (
    ACTION,
    ApprovalChat,
    OwnedRun,
    _replies,
    _start,
    chat,
    owned_runs,
)
from tests.external_dependency_unit.chat.test_run_store import chat_agent
from tests.unit.onyx.agents.fakes import FakeModelClient
from tests.unit.onyx.tools.code_mode.fakes import FakeMCPTool, until

__all__ = ["chat", "owned_runs"]

PROGRAM = f"r = await mcp__1__acme__{ACTION}(value='team')\nprint('sent', r)"


def _reply(request: GenerationRequest, _signal: CancellationSignal) -> AssistantMessage:
    results = [m for m in request.messages if isinstance(m, ToolResultMessage)]
    if results:
        return AssistantMessage(content=[TextContent(text=results[-1].text)])
    return AssistantMessage(
        content=[
            ToolCall(id="program", name=CodeModeTool.NAME, arguments={"code": PROGRAM})
        ]
    )


def _gated(server_id: int, sent: list[str]) -> FakeMCPTool:
    def send(invocation: ToolInvocation, _context: ToolContext) -> ToolResult:
        sent.append(str(invocation.arguments["value"]))
        return ToolResult(content=json.dumps({"tool_result": "sent"}))

    tool = FakeMCPTool(
        ACTION,
        send,
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    )
    tool.approval = ToolApprovalScope(
        app_kind=GatedAppKind.MCP_SERVER, target_id=server_id, action_id=ACTION
    )
    return tool


def _agent(tool: FakeMCPTool, checkpoint: ExecutionCheckpoint | None) -> ChatAgent:
    return chat_agent(
        FakeModelClient(_reply),
        agent_id=checkpoint.run_state.agent_id if checkpoint else None,
        state=checkpoint.agent_state if checkpoint else None,
        tools=[tool],
        code_mode=True,
    )


def _resume_agent_in_process(
    session_id: str,
    response_id: str,
    agent_response_id: str,
    user_id: str,
    server_id: str,
) -> None:
    """Resume the parked agent with fresh objects through dispatch, as another
    API pod's agent host does."""
    SqlEngine.init_engine(pool_size=5, max_overflow=5)
    tenant_id = POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        user = db_session.get(User, UUID(user_id))
        assert user is not None
        db_session.expunge(user)
    sent: list[str] = []
    tool = _gated(int(server_id), sent)
    depths: list[int] = []

    def rebuild(checkpoint: ExecutionCheckpoint, depth: int) -> Agent:
        depths.append(depth)
        return _agent(tool, checkpoint)

    host = ChatRunStore(
        tenant_id=tenant_id,
        chat_session_id=UUID(session_id),
        response_id=int(response_id),
        visible_response_ids=[],
        cache=get_cache_backend(tenant_id=tenant_id),
        follow_up_steps=3,
        user=user,
        tools=[tool],
    )
    coordinator = AgentCoordinator()
    host.bind(coordinator, build_agent=rebuild)

    def agent_status() -> RunStatus | None:
        with get_session_with_tenant(tenant_id=tenant_id) as db_session:
            response = db_session.get(ChatMessage, int(agent_response_id))
            return response.response_status if response is not None else None

    try:
        until(
            lambda: (
                host.poll_control() is None
                and agent_status() == RunStatus.COMPLETE
                and not host.has_owned_work
            ),
            timeout=60,
        )
        assert sent == ["team"]
        assert depths == [1]
    finally:
        try:
            assert coordinator.close(timeout=10)
        finally:
            SqlEngine.reset_engine()


def test_a_parked_agent_resumes_in_another_process(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    sent: list[str] = []
    tool = _gated(chat.server.id, sent)
    owned = _start(
        chat,
        owned_runs,
        reply=_replies(
            AssistantMessage(
                content=[
                    ToolCall(
                        id="spawn",
                        name=SpawnAgentTool.name,
                        arguments={"name": "mailer", "instruction": "Email the team"},
                    )
                ]
            )
        ),
        tools=[
            SpawnAgentTool(lambda: _agent(tool, None), max_steps=3).bind(ToolContext)
        ],
        gated=[tool],
    )
    file_store = get_default_file_store()
    prefix = f"agent-checkpoint/{chat.chat_session_id}/"

    def parked_agent() -> int | None:
        owned.owner.poll_control()
        rows = chat.rows(db_session)
        if len(rows) != 1:
            return None
        agent_id = rows[0].chat_message_id
        # Its own session: the agent's run reads the chat's user meanwhile.
        with get_session_with_tenant(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        ) as session:
            parked = session.get(ChatResponseCheckpoint, agent_id) is not None
        return agent_id if parked else None

    try:
        until(lambda: parked_agent() is not None, timeout=30)
        agent_response_id = parked_agent()
        assert agent_response_id is not None
        assert owned.run.result(timeout=10).output.text == "done"
        # The program's dump is saved under the root session, as a root's is.
        assert len(file_store.list_files_by_prefix(prefix)) == 1
        # Every object of this process lets go of the agent.
        owned.run.cancel()
        assert owned.coordinator.close(timeout=10)
        owned_runs.remove(owned)

        [row] = chat.rows(db_session)
        chat.decide(db_session, row.id, ApprovalChoice.APPROVE_ONCE)
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from tests.external_dependency_unit.chat."
                "test_parked_agent_handoff import _resume_agent_in_process; "
                "_resume_agent_in_process(*sys.argv[1:])",
                str(chat.chat_session_id),
                str(chat.response_id),
                str(agent_response_id),
                str(chat.user.id),
                str(chat.server.id),
            ],
            cwd=Path(__file__).resolve().parents[3],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr

        assert sent == []
        db_session.expire_all()
        response = db_session.get(ChatMessage, agent_response_id)
        assert response is not None and response.response_status == RunStatus.COMPLETE
        assert db_session.get(ChatResponseCheckpoint, agent_response_id) is None
        db_session.rollback()
        # The resumed program deleted its dump once it loaded it.
        assert file_store.list_files_by_prefix(prefix) == []
    finally:
        for record in file_store.list_files_by_prefix(prefix):
            file_store.delete_file(record.file_id, error_on_missing=False)
