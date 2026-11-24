"""A background agent whose program call waits for approval parks; after the
decision, another process resumes it through the inbox and dispatch."""

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.models import ExecutionCheckpoint, RunStatus
from onyx.agents.runtime import Agent
from onyx.agents.tools import ToolInvocation
from onyx.cache.factory import get_cache_backend
from onyx.chat import process_message
from onyx.chat.agent import ChatAgent
from onyx.chat.execution import chat_turn_work
from onyx.chat.process_message import dispatch_pending_chat_messages
from onyx.chat.run_store import INPUT_POLL_SECONDS, ChatRunStore
from onyx.db.engine.sql_engine import SqlEngine, get_session_with_tenant
from onyx.db.models import ChatMessage, ChatResponseCheckpoint, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
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
from onyx.llm.override_models import LLMOverride
from onyx.server.features.action_policies.models import ApprovalChoice
from onyx.server.query_and_chat.chat_backend import (
    get_chat_session_processing_status,
)
from onyx.tools.constants import EXEC_TOOL_NAME
from onyx.tools.models import ToolApprovalScope, ToolContext
from onyx.tools.tool_implementations.subagents.subagent_tools import SpawnAgentTool
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.chat.test_chat_tool_approvals import (
    ACTION,
    ApprovalChat,
    OwnedRun,
    _inbox,
    _replies,
    _start,
    chat,
    owned_runs,
)
from tests.external_dependency_unit.chat.test_run_store import chat_agent
from tests.external_dependency_unit.chat.test_wait_agents import ScriptedLLM
from tests.unit.onyx.agents.fakes import FakeModelClient
from tests.unit.onyx.tools.code_mode.fakes import FakeMCPTool, until

__all__ = ["chat", "owned_runs"]

PROGRAM = f"r = await tools.mcp__1__acme__{ACTION}(value='team')\nprint('sent', r)"


def _reply(request: GenerationRequest, _signal: CancellationSignal) -> AssistantMessage:
    results = [m for m in request.messages if isinstance(m, ToolResultMessage)]
    if results:
        return AssistantMessage(content=[TextContent(text=results[-1].text)])
    return AssistantMessage(
        content=[
            ToolCall(id="program", name=EXEC_TOOL_NAME, arguments={"code": PROGRAM})
        ]
    )


def _gated(integration_id: int, sent: list[str]) -> FakeMCPTool:
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
    tool.approval = ToolApprovalScope(integration_id=integration_id, action_id=ACTION)
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
    integration_id: str,
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
    tool = _gated(int(integration_id), sent)
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


def _park_agent(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun], sent: list[str]
) -> int:
    """Start a root whose background agent's program call waits for approval;
    returns the agent's response once it parked and this process let go."""
    tool = _gated(chat.integration_id, sent)
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

    until(lambda: parked_agent() is not None, timeout=30)
    agent_response_id = parked_agent()
    assert agent_response_id is not None
    assert owned.run.result(timeout=10).output.text == "done"
    # Every object of this process lets go of the agent.
    owned.run.cancel()
    assert owned.coordinator.close(timeout=10)
    owned_runs.remove(owned)
    return agent_response_id


def _has_active_subagents(chat: ApprovalChat) -> bool:
    return get_chat_session_processing_status(
        chat.chat_session_id,
        BackgroundTasks(),
        MagicMock(headers={}),
        user=chat.user,
    ).has_active_subagents


def test_a_parked_agent_resumes_in_another_process(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    sent: list[str] = []
    file_store = get_default_file_store()
    prefix = f"agent-checkpoint/{chat.chat_session_id}/"
    try:
        agent_response_id = _park_agent(db_session, chat, owned_runs, sent)
        # The program's dump is saved under the root session, as a root's is.
        assert len(file_store.list_files_by_prefix(prefix)) == 1

        # A parked agent that waits for the user is not active; once decided,
        # it is, from the decision's commit until it resumes and ends.
        assert not _has_active_subagents(chat)
        [row] = chat.rows(db_session)
        chat.decide(db_session, row.id, ApprovalChoice.APPROVE_ONCE)
        assert _has_active_subagents(chat)
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
                str(chat.integration_id),
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


def test_a_decided_agent_resumes_only_in_a_store_with_its_saved_model(
    db_session: Session, chat: ApprovalChat, owned_runs: list[OwnedRun]
) -> None:
    """A store of a turn that runs on another model or temperature leaves a
    decided agent parked, so an agent host continues it with its saved model
    settings and tools instead of the turn's. A store with the saved ones
    resumes it."""
    sent: list[str] = []
    agent_response_id = _park_agent(db_session, chat, owned_runs, sent)
    [row] = chat.rows(db_session)
    chat.decide(db_session, row.id, ApprovalChoice.APPROVE_ONCE)
    tool = _gated(chat.integration_id, sent)
    rebuilt: list[int] = []

    def rebuild(checkpoint: ExecutionCheckpoint, depth: int) -> Agent:
        rebuilt.append(depth)
        return _agent(tool, checkpoint)

    def agent_status() -> RunStatus | None:
        with get_session_with_tenant(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        ) as session:
            return session.get_one(ChatMessage, agent_response_id).response_status

    def bound_store(
        model_configuration_id: int | None, temperature: float | None
    ) -> ChatRunStore:
        store = ChatRunStore(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            chat_session_id=chat.chat_session_id,
            response_id=chat.response_id,
            visible_response_ids=[],
            cache=get_cache_backend(),
            follow_up_steps=3,
            user=chat.user,
            tools=[tool],
            model_configuration_id=model_configuration_id,
            temperature=temperature,
        )
        coordinator = AgentCoordinator()
        store.bind(coordinator, build_agent=rebuild)
        coordinators.append(coordinator)
        return store

    coordinators: list[AgentCoordinator] = []
    try:
        others = [bound_store(4242, None), bound_store(None, 0.9)]
        # Polls through several dispatch scans.
        deadline = time.monotonic() + 3 * INPUT_POLL_SECONDS

        def polled_past_scans() -> bool:
            for other in others:
                other.poll_control()
            return time.monotonic() > deadline

        until(polled_past_scans)
        assert rebuilt == []
        assert agent_status() == RunStatus.SUSPENDED

        same = bound_store(None, None)
        until(
            lambda: (
                same.poll_control() is None
                and agent_status() == RunStatus.COMPLETE
                and not same.has_owned_work
            ),
            timeout=60,
        )
        assert rebuilt == [1]
        assert sent == ["team"]
    finally:
        for coordinator in coordinators:
            assert coordinator.close(timeout=10)


@pytest.mark.parametrize("unavailable", ["raises", "falls_back"])
def test_a_decided_agent_whose_host_cannot_start_ends(
    db_session: Session,
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    monkeypatch: pytest.MonkeyPatch,
    unavailable: str,
) -> None:
    """The agent host asks for the model that the decided agent ran. When it
    fails to start for a reason that every attempt meets, such as that model
    being gone, it ends the agents that it would resume, as a root
    continuation that cannot start ends its response. Model selection that
    falls back to another model counts as the model being gone. The chat then
    has no active agents, so status reads stop dispatching."""
    sent: list[str] = []
    file_store = get_default_file_store()
    prefix = f"agent-checkpoint/{chat.chat_session_id}/"
    requested: list[LLMOverride | None] = []

    def model_gone(
        *, llm_override: LLMOverride | None, **_kwargs: object
    ) -> ScriptedLLM:
        requested.append(llm_override)
        if unavailable == "raises":
            raise ValueError("The model is no longer available")
        return ScriptedLLM(lambda *_args: pytest.fail("The agent ran on another model"))

    monkeypatch.setattr("onyx.chat.process_message.get_llm_for_persona", model_gone)
    prepare = process_message.prepare_chat_turn
    host_errors: list[Exception] = []

    def recorded_prepare(*args: Any, **kwargs: Any) -> Any:
        try:
            return prepare(*args, **kwargs)
        except Exception as error:
            if kwargs.get("agent_host"):
                host_errors.append(error)
            raise

    monkeypatch.setattr(process_message, "prepare_chat_turn", recorded_prepare)
    try:
        agent_response_id = _park_agent(db_session, chat, owned_runs, sent)
        # The agent ran on a model other than the chat's current one.
        with get_session_with_tenant(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        ) as session:
            checkpoint = session.get_one(ChatResponseCheckpoint, agent_response_id)
            checkpoint.state = {
                **checkpoint.state,
                "model_configuration_id": 4242,
                "temperature": 0.3,
            }
            session.commit()
        [row] = chat.rows(db_session)
        chat.decide(db_session, row.id, ApprovalChoice.APPROVE_ONCE)
        assert _has_active_subagents(chat)

        dispatch_pending_chat_messages(chat.chat_session_id, chat.user.id)

        def agent_status() -> RunStatus | None:
            with get_session_with_tenant(
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
            ) as session:
                return session.get_one(ChatMessage, agent_response_id).response_status

        until(lambda: agent_status() == RunStatus.ERROR, timeout=30)
        assert chat_turn_work.wait_idle(timeout=30)
        assert [
            override and (override.model_configuration_id, override.temperature)
            for override in requested
        ] == [(4242, 0.3)]
        [error] = host_errors
        if unavailable == "raises":
            assert isinstance(error, ValueError)
        else:
            assert isinstance(error, OnyxError)
            assert error.error_code == OnyxErrorCode.NOT_FOUND
        assert not _has_active_subagents(chat)
        assert sent == []
        # Its checkpoint and its program's dump go with it.
        assert file_store.list_files_by_prefix(prefix) == []
    finally:
        for record in file_store.list_files_by_prefix(prefix):
            file_store.delete_file(record.file_id, error_on_missing=False)


def test_a_host_that_cannot_start_ends_only_the_agents_of_its_model(
    db_session: Session,
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two decided agents parked on different models. A host that cannot
    start on the first agent's model ends that agent only; the other stays
    parked for a host on its own model."""
    sent: list[str] = []
    tool = _gated(chat.integration_id, sent)
    owned = _start(
        chat,
        owned_runs,
        reply=_replies(
            AssistantMessage(
                content=[
                    ToolCall(
                        id=f"spawn-{name}",
                        name=SpawnAgentTool.name,
                        arguments={"name": name, "instruction": "Email the team"},
                    )
                    for name in ("mailer", "notifier")
                ]
            )
        ),
        tools=[
            SpawnAgentTool(lambda: _agent(tool, None), max_steps=3).bind(ToolContext)
        ],
        gated=[tool],
    )

    def parked_agents() -> list[int]:
        owned.owner.poll_control()
        agent_ids = sorted(row.chat_message_id for row in chat.rows(db_session))
        with get_session_with_tenant(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        ) as session:
            return [
                agent_id
                for agent_id in agent_ids
                if session.get(ChatResponseCheckpoint, agent_id) is not None
            ]

    until(lambda: len(parked_agents()) == 2, timeout=30)
    first, second = parked_agents()
    assert owned.run.result(timeout=10).output.text == "done"
    owned.run.cancel()
    assert owned.coordinator.close(timeout=10)
    owned_runs.remove(owned)
    with get_session_with_tenant(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
    ) as session:
        for agent_id, model in ((first, 4242), (second, 5151)):
            checkpoint = session.get_one(ChatResponseCheckpoint, agent_id)
            checkpoint.state = {**checkpoint.state, "model_configuration_id": model}
        session.commit()
    for row in chat.rows(db_session):
        chat.decide(db_session, row.id, ApprovalChoice.APPROVE_ONCE)
    requested: list[int | None] = []

    def model_gone(*, llm_override: LLMOverride | None, **_kwargs: object) -> None:
        requested.append(llm_override.model_configuration_id if llm_override else None)
        raise ValueError("The model is no longer available")

    monkeypatch.setattr("onyx.chat.process_message.get_llm_for_persona", model_gone)

    def status(agent_id: int) -> RunStatus | None:
        with get_session_with_tenant(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        ) as session:
            return session.get_one(ChatMessage, agent_id).response_status

    dispatch_pending_chat_messages(chat.chat_session_id, chat.user.id)
    until(lambda: status(first) == RunStatus.ERROR, timeout=30)
    assert chat_turn_work.wait_idle(timeout=30)
    assert requested == [4242]
    # The other agent stays decided and parked, for a host on its own model.
    assert status(second) == RunStatus.SUSPENDED
    assert [run.response_id for run in _inbox(chat).resumable_runs] == [second]
    assert sent == []


def test_a_decided_agent_whose_host_is_rate_limited_stays_parked(
    db_session: Session,
    chat: ApprovalChat,
    owned_runs: list[OwnedRun],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rate limit is temporary: the agent host that it stops keeps the
    decided agent parked with its decision, and the agent resumes once the
    limit allows, here in another process's host."""
    sent: list[str] = []
    file_store = get_default_file_store()
    prefix = f"agent-checkpoint/{chat.chat_session_id}/"
    limited: list[bool] = []

    def rate_limited(**_kwargs: object) -> None:
        limited.append(True)
        raise OnyxError(OnyxErrorCode.RATE_LIMITED, "The agent limit is full")

    monkeypatch.setattr("onyx.chat.process_message.get_llm_for_persona", rate_limited)
    try:
        agent_response_id = _park_agent(db_session, chat, owned_runs, sent)
        [row] = chat.rows(db_session)
        chat.decide(db_session, row.id, ApprovalChoice.APPROVE_ONCE)

        dispatch_pending_chat_messages(chat.chat_session_id, chat.user.id)
        until(lambda: bool(limited), timeout=30)
        assert chat_turn_work.wait_idle(timeout=30)

        with get_session_with_tenant(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        ) as session:
            response = session.get_one(ChatMessage, agent_response_id)
            assert response.response_status == RunStatus.SUSPENDED
            assert session.get(ChatResponseCheckpoint, agent_response_id) is not None
        assert _has_active_subagents(chat)
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
                str(chat.integration_id),
            ],
            cwd=Path(__file__).resolve().parents[3],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert not _has_active_subagents(chat)
    finally:
        for record in file_store.list_files_by_prefix(prefix):
            file_store.delete_file(record.file_id, error_on_missing=False)
