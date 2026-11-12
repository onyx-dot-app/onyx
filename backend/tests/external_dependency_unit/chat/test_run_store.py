"""Safe response transfer uses canonical history and one conditional resume owner."""

import json
import subprocess
import sys
import threading
from collections.abc import Callable, Generator, Sequence
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from onyx.agents.agent_coordination import AgentCoordinator, RunStore
from onyx.agents.models import (
    AGENT_RESULT_MESSAGE_PREFIX,
    AgentInfo,
    AgentMessageRequest,
    AgentState,
    CompactionCheckpoint,
    ExecutionCheckpoint,
    InputMessageMetadata,
    InputSource,
    MessageDelivery,
    PreparedStep,
    RunProgress,
    RunState,
    RunStatus,
    StepInput,
    ToolCallContext,
    messages_from_steps,
)
from onyx.agents.runtime import Agent, Run, RunFailed
from onyx.agents.tools import (
    AgentLifetime,
    AgentTool,
    ChildRunWait,
    HumanToolAnswer,
    InputDecision,
    InputMode,
    PendingToolInput,
    SpawnResult,
    ToolInvocation,
)
from onyx.cache.factory import get_cache_backend
from onyx.chat import run_store
from onyx.chat.agent import ChatAgent
from onyx.chat.checkpoint import CHECKPOINT_PAYLOAD_TYPES
from onyx.chat.history_store import get_chat_history_store
from onyx.chat.models import (
    ChatBranch,
    ChatFeatureState,
    ChatMessageMetadata,
    CheckpointBinding,
    QueuedChatTurn,
    ResponseRecord,
    SavedAgentContext,
)
from onyx.chat.presentation import project_response
from onyx.chat.response import response_snapshot
from onyx.chat.restoration import persist_checkpoint_files, restore_chat_agent
from onyx.chat.run_store import ChatRunStore
from onyx.configs.constants import DocumentSource, FileOrigin, MessageType
from onyx.context.search.models import SearchDoc
from onyx.db.chat import (
    delete_messages_and_files_from_chat_session,
    get_selected_branch,
    root_response_id,
)
from onyx.db.chat_checkpoint import (
    check_checkpoint_owner__no_commit,
    claim_checkpoint__no_commit,
    release_checkpoint_claim__no_commit,
)
from onyx.db.chat_inputs import (
    agent_result_states,
    lock_agent,
    next_queued_turn,
    pending_inputs,
    submit_human_message__no_commit,
)
from onyx.db.chat_response import (
    read_chat_execution,
    read_response__no_commit,
    save_response_record__no_commit,
)
from onyx.db.chat_subagents import (
    latest_agent_response,
    load_agent_history,
    load_chat_branch,
    read_agent_completions,
)
from onyx.db.engine.sql_engine import SqlEngine, get_session_with_tenant
from onyx.db.models import (
    ChatInput,
    ChatMessage,
    ChatMessage__SearchDoc,
    ChatResponseCheckpoint,
    ChatResponseItem,
    ChatSession,
    User,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.models import ExtractedContextFiles
from onyx.file_store.postgres_file_store import PostgresBackedFileStore
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.interfaces import LLM, GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.server.query_and_chat.session_loading import (
    translate_assistant_message_to_packets,
)
from onyx.tools.interface import Tool
from onyx.tools.models import ChatFile, FileReadResult, ToolContext
from onyx.tools.tool_implementations.subagents.models import ChatConfiguration
from onyx.tools.tool_implementations.subagents.subagent_tools import (
    InterruptAgentTool,
    SendMessageTool,
    SpawnAgentTool,
)
from onyx.tracing.flows import LLMFlow
from onyx.utils.threadpool_concurrency import start_thread_future
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.unit.onyx.agents.checkpoint_storage import CheckpointStorage
from tests.unit.onyx.agents.fakes import (
    EchoTool,
    FakeModelClient,
    FakeRunStore,
)


@pytest.fixture
def branch(db_session: Session) -> Generator[tuple[UUID, int], None, None]:
    chat = ChatSession(id=uuid4(), description="checkpoint test")
    db_session.add(chat)
    db_session.flush()
    question = ChatMessage(
        chat_session_id=chat.id,
        message="task",
        token_count=1,
        message_type=MessageType.USER,
    )
    db_session.add(question)
    db_session.flush()
    response = ChatMessage(
        chat_session_id=chat.id,
        parent_message_id=question.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(response)
    db_session.flush()
    question.latest_child_message_id = response.id
    db_session.commit()
    try:
        yield chat.id, response.id
    finally:
        db_session.rollback()
        delete_messages_and_files_from_chat_session(chat.id, db_session)
        db_session.execute(delete(ChatSession).where(ChatSession.id == chat.id))
        db_session.commit()


@pytest.fixture
def user_message(branch: tuple[UUID, int], db_session: Session) -> UserMessage:
    response = db_session.get(ChatMessage, branch[1])
    assert response is not None
    question = response.parent_message
    assert question is not None
    return UserMessage(id=f"chat:{question.id}", content=question.message)


Reply = Callable[[GenerationRequest, CancellationSignal], AssistantMessage]


def unpolled_store(
    branch: tuple[UUID, int],
    *,
    root_response: RunStore | None = None,
    visible_response_ids: list[int] | None = None,
) -> ChatRunStore:
    """A store whose control thread the test drives with explicit polls."""
    return ChatRunStore(
        root_response=root_response,
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        chat_session_id=branch[0],
        response_id=branch[1],
        visible_response_ids=visible_response_ids or [],
        cache=get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE),
        follow_up_steps=4,
        user=User(),
    )


def store(
    branch: tuple[UUID, int],
    *,
    root_response: RunStore | None = None,
    visible_response_ids: list[int] | None = None,
) -> ChatRunStore:
    """A store polled in the background, like a turn's control thread."""
    return unpolled_store(
        branch, root_response=root_response, visible_response_ids=visible_response_ids
    )


def text(reply: str) -> AssistantMessage:
    return AssistantMessage(content=[TextContent(text=reply)])


def answering(reply: str) -> Reply:
    return lambda *_: text(reply)


def replies(*messages: AssistantMessage) -> Reply:
    remaining = iter(messages)
    return lambda *_: next(remaining)


def calls(*tool_calls: ToolCall) -> AssistantMessage:
    return AssistantMessage(content=list(tool_calls))


def call(call_id: str, name: str | None = None) -> ToolCall:
    return ToolCall(id=call_id, name=name or call_id, arguments={})


def spawn_call(call_id: str, name: str, instruction: str) -> ToolCall:
    return ToolCall(
        id=call_id,
        name="spawn_agent",
        arguments={"name": name, "instruction": instruction},
    )


def agent_tool(
    name: str,
    execute: Callable[[ToolInvocation], ToolResult | PendingToolInput | ChildRunWait],
    *,
    result_from_children: Callable[[ToolInvocation, list[RunState]], ToolResult]
    | None = None,
) -> AgentTool:
    return AgentTool(
        definition=ToolDefinition(name=name, description="", parameters={}),
        execute=execute,
        result_from_children=result_from_children,
    )


def first_child_answer(
    _invocation: ToolInvocation, children: list[RunState]
) -> ToolResult:
    return ToolResult(content=children[0].messages[-1].text)


def ask_tool(prompt: str = "Which file?") -> AgentTool:
    return agent_tool(
        "ask",
        lambda _: PendingToolInput(
            request_id="answer", prompt=prompt, mode=InputMode.RESULT
        ),
    )


def fake_agent(
    reply: Reply,
    *,
    agent_id: str | None = None,
    state: AgentState | None = None,
    tools: Sequence[AgentTool] = (),
    prepare_step: Callable[[StepInput], PreparedStep] | None = None,
    after_tool_call: Callable[[ToolCallContext, ToolResult], ToolResult] | None = None,
) -> Agent:
    return Agent(
        FakeModelClient(reply),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        agent_id=agent_id,
        state=state,
        tools=tools,
        prepare_step=prepare_step,
        after_tool_call=after_tool_call,
    )


def delegating_root(
    branch: tuple[UUID, int],
    tool: AgentTool,
    *,
    tool_calls: Sequence[ToolCall] = (),
    answer: str = "done",
) -> Agent:
    """A root that calls `tool` once, or with `tool_calls`, and then answers."""
    return fake_agent(
        replies(calls(*(tool_calls or [call(tool.name)])), text(answer)),
        agent_id=str(branch[0]),
        tools=[tool],
    )


def spawning_root(
    branch: tuple[UUID, int],
    create_child: Callable[[], Agent],
    *,
    name: str,
    instruction: str,
    answer: str,
    max_steps: int = 3,
) -> Agent:
    """A root that spawns one background child and then answers."""
    return fake_agent(
        replies(calls(spawn_call(name, name, instruction)), text(answer)),
        agent_id=str(branch[0]),
        tools=[SpawnAgentTool(create_child, max_steps=max_steps).bind(ToolContext)],
    )


def never_restore(reason: str) -> Callable[[ExecutionCheckpoint], Agent]:
    def restore(_: ExecutionCheckpoint) -> Agent:
        raise AssertionError(reason)

    return restore


def chat_agent(
    llm: LLM,
    *,
    state: AgentState | None = None,
    agent_id: str | None = None,
    previous_run_id: str | None = None,
    prompt: str = "",
    create_subagent: Callable[[], Agent] | None = None,
    chat_files: list[ChatFile] | None = None,
    tools: Sequence[Tool] = (),
    code_mode: bool = False,
) -> ChatAgent:
    state = state or AgentState()
    return ChatAgent(
        create_subagent=create_subagent,
        code_mode=code_mode,
        messages=state.messages,
        checkpoint=state.checkpoint,
        agent_id=agent_id,
        previous_run_id=previous_run_id,
        tools=list(tools),
        custom_agent_prompt=None,
        base_system_prompt=prompt,
        context_files=ExtractedContextFiles(
            file_texts=[],
            image_files=[],
            use_as_search_filter=False,
            total_token_count=0,
            file_metadata=[],
            uncapped_token_count=None,
        ),
        persona=None,
        user_memory_context=None,
        llm=llm,
        token_counter=len,
        chat_files=chat_files,
    )


def add_turn(
    db_session: Session, chat_id: UUID, parent_id: int, question: str
) -> tuple[ChatMessage, ChatMessage]:
    """Save a question under `parent_id` and an empty response to it, and select it."""
    asked = ChatMessage(
        chat_session_id=chat_id,
        parent_message_id=parent_id,
        message=question,
        token_count=len(question.split()),
        message_type=MessageType.USER,
    )
    db_session.add(asked)
    db_session.flush()
    response = ChatMessage(
        chat_session_id=chat_id,
        parent_message_id=asked.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(response)
    db_session.flush()
    asked.latest_child_message_id = response.id
    db_session.execute(
        update(ChatMessage)
        .where(ChatMessage.id == parent_id)
        .values(latest_child_message_id=asked.id)
    )
    db_session.commit()
    return asked, response


def child_info(owner: ChatRunStore, parent_id: str) -> AgentInfo:
    return next(info for info in owner.list_agents() if info.parent_id == parent_id)


def assistant_count(db_session: Session, chat_id: UUID) -> int | None:
    return db_session.scalar(
        select(func.count()).where(
            ChatMessage.chat_session_id == chat_id,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
    )


def queued_root_turn(db_session: Session, chat_id: UUID) -> QueuedChatTurn | None:
    selected, chat_branch = get_selected_branch(db_session, chat_id)
    return next_queued_turn(
        db_session,
        chat_id,
        selected,
        chat_branch,
        agent_result_states(db_session, chat_branch.message_ids),
    )


def pending_agent_messages(db_session: Session, agent_id: str) -> int | None:
    db_session.expire_all()
    return db_session.scalar(
        select(func.count()).where(
            ChatInput.recipient_session_id == UUID(agent_id),
            ChatInput.source == InputSource.AGENT,
        )
    )


@pytest.fixture(autouse=True)
def poll_run_owners(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    stores: list[ChatRunStore] = []
    lock = threading.Lock()
    finished = threading.Event()

    def registered_store(
        branch: tuple[UUID, int],
        *,
        root_response: RunStore | None = None,
        visible_response_ids: list[int] | None = None,
    ) -> ChatRunStore:
        created = unpolled_store(
            branch,
            root_response=root_response,
            visible_response_ids=visible_response_ids,
        )
        with lock:
            stores.append(created)
        return created

    def poll() -> None:
        while not finished.wait(0.01):
            with lock:
                current = list(stores)
            for owned in current:
                # A turn never closes its coordinator; a closed one ends the test's turn.
                coordinator = owned._coordinator
                if coordinator is not None:
                    try:
                        coordinator.check_open()
                    except RuntimeError:
                        continue
                owned.poll_control()

    monkeypatch.setattr(sys.modules[__name__], "store", registered_store)
    worker = start_thread_future(poll, name="test-chat-control")
    try:
        yield
    finally:
        finished.set()
        worker.result(timeout=10)


@pytest.mark.parametrize(
    "scenario",
    [
        None,
        "release",
        "claim",
        "slow_release",
        "slow_resume",
        "resume_thread",
        "ownership_lock",
        "root_save",
        "separate_process",
        "compaction",
        "input_group",
        "permissions",
    ],
)
def test_transfer_preserves_result_budget_and_callback_boundary(
    branch: tuple[UUID, int],
    db_session: Session,
    scenario: str | None,
    monkeypatch: pytest.MonkeyPatch,
    user_message: UserMessage,
) -> None:
    if scenario in {"slow_release", "slow_resume", "ownership_lock"}:
        monkeypatch.setattr("onyx.chat.run_store.OWNER_TTL_SECONDS", 1)
        monkeypatch.setattr("onyx.chat.run_store.OWNER_REFRESH_SECONDS", 0.1)
        monkeypatch.setattr("onyx.chat.run_store.OWNER_EXPIRY_MARGIN_SECONDS", 0.2)
    saved_roots: list[str] = []

    def save_root(snapshot: RunState) -> None:
        saved_roots.append(snapshot.run_id)
        get_chat_history_store(
            message_id=branch[1], chat_session_id=branch[0], persist_content=True
        ).save_response(project_response(snapshot, tool_ids={}))

    owner = store(branch)
    remote = store(
        branch,
        root_response=FakeRunStore(save=lambda run: save_root(run.snapshot()))
        if scenario == "root_save"
        else None,
    )
    if scenario == "root_save":
        monkeypatch.setattr(
            remote,
            "_save_output",
            Mock(
                side_effect=AssertionError(
                    "Root persistence must use the application save"
                )
            ),
        )

    first, second = AgentCoordinator(), AgentCoordinator()
    context = AgentState()
    if scenario == "compaction":
        context.messages = [
            UserMessage(id="earlier-question", content="earlier question"),
            AssistantMessage(
                id="earlier-answer", content=[TextContent(text="earlier answer")]
            ),
        ]
        context.checkpoint = CompactionCheckpoint(
            summary="earlier context",
            covered_through_message_id="earlier-question",
        )
    executed: list[str] = []
    finalized: list[str] = []

    def execute(invocation: ToolInvocation) -> ToolResult | PendingToolInput:
        executed.append(invocation.call_id)
        if invocation.call_id == "question":
            return PendingToolInput(
                request_id="answer", prompt="Which file?", mode=InputMode.RESULT
            )
        return ToolResult(
            content="recorded search result",
            details=FileReadResult(
                file_name="report.txt",
                file_id="file",
                start_char=0,
                end_char=8,
                total_chars=8,
            ),
        )

    tools = [agent_tool("search", execute), agent_tool("ask", execute)]
    if scenario == "permissions":
        tools.append(agent_tool("blocked", execute))

    def rebuild(checkpoint: ExecutionCheckpoint) -> Agent:
        if scenario == "permissions":
            progress = checkpoint.run_state.progress
            assert progress is not None
            assert [tool.name for tool in progress.tools] == [
                "search",
                "ask",
                "blocked",
            ]
            assert progress.allowed_tool_names == frozenset({"search", "ask"})
        if scenario == "slow_resume":
            threading.Event().wait(1.5)
            assert (
                remote.read_run_status(checkpoint.run_state.run_id, "")
                == RunStatus.RUNNING
            )
        result = checkpoint.run_state.messages[1]
        assert isinstance(result, ToolResult)
        assert isinstance(result.details, FileReadResult)
        assert result.details.file_name == "report.txt"
        return fake_agent(
            answering("done"),
            agent_id=checkpoint.run_state.agent_id,
            state=checkpoint.agent_state,
            tools=tools,
            after_tool_call=lambda call, result: (
                finalized.append(call.call.id) or result
            ),
        )

    coordinator = owner.bind(first, build_agent=rebuild)
    remote.bind(second, build_agent=rebuild)
    agent = fake_agent(
        lambda *_: calls(call("search"), call("question", "ask")),
        agent_id=str(branch[0]),
        state=context,
        tools=tools,
        prepare_step=(
            lambda _: PreparedStep(allowed_tool_names=frozenset({"search", "ask"}))
        )
        if scenario == "permissions"
        else None,
        after_tool_call=lambda call, result: finalized.append(call.call.id) or result,
    )
    input_messages = (
        [
            UserMessage(id="attachment", content="Attached report contents"),
            UserMessage(id="context", content="Use the attached report"),
            user_message,
        ]
        if scenario == "input_group"
        else [user_message]
    )
    run = agent.start(messages=input_messages, max_steps=2, coordinator=coordinator)
    try:
        assert run.wait_until_settled(timeout=10).status == RunStatus.SUSPENDED
        assert run.wait_for_idle(timeout=10)
        if scenario == "release":
            with patch.object(
                owner.cache, "delete", side_effect=RuntimeError("cache unavailable")
            ) as delete_owner:
                with pytest.raises(RuntimeError, match="cache unavailable"):
                    owner.handoff(run.id)
                assert delete_owner.call_count == 1
                with pytest.raises(RuntimeError, match="cache unavailable"):
                    run.result(0)
            assert remote.resume(run.id, context=context) is None
            owner.cache.delete(run_store._owner_key(int(run.id)))
        elif scenario == "ownership_lock":
            with run_store._ownership_lock(owner.cache, int(run.id)):
                threading.Event().wait(1.5)
                assert owner.cache.exists(run_store._owner_key(int(run.id)))
            owner.handoff(run.id)
        elif scenario == "slow_release":

            def slow_files(
                checkpoint: ExecutionCheckpoint, *, session_id: UUID
            ) -> None:
                persist_checkpoint_files(checkpoint, session_id=session_id)
                threading.Event().wait(1.5)
                assert remote.read_run_status(run.id, "") == RunStatus.RUNNING

            with patch(
                "onyx.chat.run_store.persist_checkpoint_files", side_effect=slow_files
            ):
                owner.handoff(run.id)
        else:
            with patch.object(owner, "release", wraps=owner.release) as release_owner:
                owner.handoff(run.id)
            assert release_owner.call_count == 1
        assert coordinator.newest_run(agent.id) is None
        db_session.expire_all()
        row = db_session.get(ChatResponseCheckpoint, branch[1])
        assert row is not None
        assert "recorded search result" not in str(row.state)
        assert (
            not {"execution", "operations", "status", "messages", "failure"}
            & row.state.keys()
        )
        assert run.id == str(branch[1])
        db_session.rollback()
        with pytest.raises(ValueError, match="history changed"):
            remote.resume(
                run.id,
                context=AgentState(messages=[UserMessage(content="another branch")]),
            )
        unauthorized = ChatRunStore(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            chat_session_id=uuid4(),
            response_id=branch[1],
            visible_response_ids=[],
            cache=get_cache_backend(),
            follow_up_steps=4,
            user=User(),
        )
        with pytest.raises(ValueError, match="unavailable on this branch"):
            unauthorized.read_run(run.id, "")
        with pytest.raises(ValueError, match="unavailable to this parent"):
            remote.read_run(run.id, str(uuid4()))
        if scenario == "claim":
            with patch.object(
                remote.cache, "set", side_effect=RuntimeError("cache unavailable")
            ):
                with pytest.raises(RuntimeError, match="cache unavailable"):
                    remote.resume(run.id, context=context)
        if scenario == "resume_thread":
            with patch(
                "onyx.agents.runtime.start_thread_with_context",
                side_effect=RuntimeError("execution thread failed"),
            ):
                with pytest.raises(RuntimeError, match="execution thread failed"):
                    remote.resume(run.id, context=context)
            assert remote.read_run_status(run.id, "") == RunStatus.SUSPENDED
            assert not remote.has_owned_work
        if scenario == "separate_process":
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import sys; from tests.external_dependency_unit.chat.test_run_store "
                    "import _resume_response_in_process; "
                    "_resume_response_in_process(*sys.argv[1:])",
                    str(branch[0]),
                    str(branch[1]),
                    run.id,
                ],
                cwd=Path(__file__).resolve().parents[3],
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert completed.returncode == 0, completed.stdout + completed.stderr
        else:
            resumed = remote.resume(run.id, context=context)
            assert resumed is not None
            assert resumed.snapshot().input_messages == input_messages
            resumed.submit(
                HumanToolAnswer(
                    request_id="answer",
                    decision=InputDecision.RESULT,
                    result=ToolResult(content="report.txt"),
                )
            )
            assert resumed.result(timeout=10).output.text == "done"
            assert resumed.wait_for_idle(timeout=10)
            assert resumed.snapshot().checkpoint == context.checkpoint
            progress = resumed.snapshot().progress
            assert progress is not None
            assert progress.step_limit == 2
        saved_result = remote.read_run(run.id, "")
        assert saved_result is not None and saved_result.status == RunStatus.COMPLETE
        assert sorted(executed) == ["question", "search"]
        assert finalized == (
            ["search"] if scenario == "separate_process" else ["search", "question"]
        )
        db_session.expire_all()
        assert db_session.get(ChatResponseCheckpoint, branch[1]) is None
        if scenario == "root_save":
            assert saved_roots == [run.id]
            saved_message = db_session.get(ChatMessage, branch[1])
            assert saved_message is not None
            assert saved_message.message == "done"
    finally:
        assert first.close(timeout=10)
        assert second.close(timeout=10)


def _resume_response_in_process(session_id: str, message_id: str, run_id: str) -> None:
    SqlEngine.init_engine(pool_size=5, max_overflow=5)
    remote = store((UUID(session_id), int(message_id)))
    coordinator = AgentCoordinator()

    def unexpected_tool(_: ToolInvocation) -> ToolResult:
        raise RuntimeError("Recorded tools must not execute again")

    def rebuild(checkpoint: ExecutionCheckpoint) -> Agent:
        return fake_agent(
            answering("done"),
            agent_id=checkpoint.run_state.agent_id,
            state=checkpoint.agent_state,
            tools=[agent_tool(name, unexpected_tool) for name in ("search", "ask")],
        )

    remote.bind(coordinator, build_agent=rebuild)
    finished = threading.Event()

    def poll() -> None:
        while not finished.wait(0.01):
            remote.poll_control()

    controller = start_thread_future(poll, name="test-chat-control")
    try:
        resumed = remote.resume(run_id, context=AgentState())
        assert resumed is not None
        resumed.submit(
            HumanToolAnswer(
                request_id="answer",
                decision=InputDecision.RESULT,
                result=ToolResult(content="report.txt"),
            )
        )
        assert resumed.result(timeout=10).output.text == "done"
        progress = resumed.snapshot().progress
        assert progress is not None
        assert progress.step_limit == 2
    finally:
        try:
            assert coordinator.close(timeout=10)
        finally:
            finished.set()
            controller.result(timeout=10)
            SqlEngine.reset_engine()


def test_transfer_rejects_input_missing_from_history_before_handoff(
    branch: tuple[UUID, int], db_session: Session, user_message: UserMessage
) -> None:
    owner = store(branch)
    coordinator = AgentCoordinator()
    view = owner.bind(
        coordinator,
        build_agent=never_restore("Transfer must fail before reconstruction"),
    )
    agent = fake_agent(
        lambda *_: calls(call("question", "ask")),
        agent_id=str(branch[0]),
        tools=[ask_tool()],
    )
    run = agent.start(
        messages=[
            user_message.model_copy(
                update={"content": "input absent from saved history"}
            )
        ],
        max_steps=2,
        coordinator=view,
    )
    try:
        assert run.wait_until_settled(timeout=10).status == RunStatus.SUSPENDED
        assert run.wait_for_idle(timeout=10)
        with pytest.raises(ValueError, match="Checkpoint response changed"):
            owner.handoff(run.id)
        assert view.run(run.id) is run
        assert db_session.get(ChatResponseCheckpoint, branch[1]) is None
    finally:
        assert coordinator.close(timeout=10)


@pytest.mark.parametrize("cancel_paused", [False, True])
def test_competing_resume_claims_and_stale_writer(
    branch: tuple[UUID, int], cancel_paused: bool, user_message: UserMessage
) -> None:
    owner = store(branch)
    coordinator = AgentCoordinator()
    view = owner.bind(
        coordinator,
        build_agent=never_restore(
            "This test claims the checkpoint without starting a run"
        ),
    )
    agent = fake_agent(
        lambda *_: calls(call("question", "ask")),
        agent_id=str(branch[0]),
        tools=[ask_tool()],
    )
    run = agent.start(messages=[user_message], max_steps=2, coordinator=view)
    try:
        assert run.wait_until_settled(timeout=10).status == RunStatus.SUSPENDED
        assert run.wait_for_idle(timeout=10)
        owner.handoff(run.id)
        if cancel_paused:
            remote = store(branch)
            remote.cancel_run(run.id, "")
            assert remote.read_run_status(run.id, "") == RunStatus.CANCELLED
            assert run.wait_for_idle(timeout=10)
            return
        barrier = threading.Barrier(2)

        def claim() -> int | None:
            barrier.wait(timeout=10)
            with get_session_with_tenant(
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
            ) as session:
                record = claim_checkpoint__no_commit(session, branch[1])
                session.commit()
                return record.ownership_version if record else None

        futures = [
            start_thread_future(lambda: claim(), name="checkpoint-claim")
            for _ in range(2)
        ]
        ownership_versions = [future.result(timeout=10) for future in futures]
        winners = [version for version in ownership_versions if version is not None]
        assert len(winners) == 1
        with get_session_with_tenant(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        ) as session:
            with pytest.raises(ValueError, match="ownership changed"):
                check_checkpoint_owner__no_commit(session, branch[1], winners[0] - 1)
            session.rollback()
            release_checkpoint_claim__no_commit(session, branch[1], winners[0])
            session.commit()
    finally:
        # The test leaves a published checkpoint, not a live remote worker.
        coordinator.close(timeout=1)


def test_checkpoint_files_use_durable_references_and_session_cleanup(
    branch: tuple[UUID, int], db_session: Session
) -> None:
    file_store = PostgresBackedFileStore()
    original_bytes = b"uploaded spreadsheet"
    generated_bytes = b"generated search data"
    original_id = file_store.save_file(
        BytesIO(original_bytes), "input.csv", FileOrigin.CHAT_UPLOAD, "text/csv"
    )
    try:
        with (
            patch(
                "onyx.chat.restoration.get_default_file_store", return_value=file_store
            ),
            patch(
                "onyx.file_store.file_store.get_default_file_store",
                return_value=file_store,
            ),
            patch("onyx.db.chat.get_default_file_store", return_value=file_store),
            patch.object(file_store, "read_file", wraps=file_store.read_file) as reads,
            patch.object(file_store, "save_file", wraps=file_store.save_file) as saves,
        ):
            feature = chat_agent(
                FakeModelClient(answering("done")),
                prompt="Help",
                chat_files=[
                    ChatFile.lazy_from_filename(
                        filename="input.csv",
                        file_id=original_id,
                        loader=lambda: file_store.read_file(
                            original_id, mode="b"
                        ).read(),
                    ),
                    ChatFile(filename="generated.csv", content=generated_bytes),
                ],
            )
            captured = ExecutionCheckpoint(
                agent_state=AgentState(),
                run_state=RunState(
                    run_id=str(branch[1]),
                    steps=[],
                    agent_id=str(branch[0]),
                    status=RunStatus.SUSPENDED,
                    progress=RunProgress(
                        tool_configuration_digest="test-tool-configuration",
                        step_limit=2,
                        feature_state=feature.capture_state().model_dump(mode="json"),
                    ),
                ),
            )
            persist_checkpoint_files(captured, session_id=branch[0])
            persist_checkpoint_files(captured, session_id=branch[0])
            reads.assert_not_called()
            assert saves.call_count == 1
            codec = CheckpointStorage(CHECKPOINT_PAYLOAD_TYPES)
            encoded = codec.save(
                captured.run_state,
                captured.agent_state,
                CheckpointBinding(
                    tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
                    response_id=str(branch[1]),
                ),
            )
            restored = codec.load(encoded)
            assert restored.run_state.progress is not None
            state = ChatFeatureState.model_validate(
                restored.run_state.progress.feature_state
            )
            rebuilt = restore_chat_agent(
                restored,
                llm=feature.llm,
                tools=feature.configured_tools,
                user_identity=None,
            )
            assert isinstance(rebuilt, ChatAgent)
            assert [tool.name for tool in rebuilt.tools] == [
                tool.name for tool in feature.tools
            ]
            assert all(file.content is None for file in state.chat_files)
            assert state.chat_files[0].file_id == original_id
            assert state.chat_files[0].restore().content == original_bytes
            assert state.chat_files[1].restore().content == generated_bytes
            generated_id = state.chat_files[1].file_id
            assert generated_id is not None
            delete_messages_and_files_from_chat_session(branch[0], db_session)
            db_session.commit()
            assert not file_store.has_file(
                generated_id, FileOrigin.OTHER, "application/octet-stream"
            )
            assert file_store.has_file(original_id, FileOrigin.CHAT_UPLOAD, "text/csv")
    finally:
        for record in file_store.list_files_by_prefix(f"agent-checkpoint/{branch[0]}/"):
            file_store.delete_file(record.file_id, error_on_missing=False)
        file_store.delete_file(original_id, error_on_missing=False)


@pytest.mark.parametrize("save_fails", [False, True])
def test_owner_cleanup_failure_releases_local_control(
    branch: tuple[UUID, int], save_fails: bool, user_message: UserMessage
) -> None:
    def save_root(snapshot: RunState) -> None:
        if save_fails:
            raise ValueError("response save failed")
        get_chat_history_store(
            message_id=branch[1], chat_session_id=branch[0], persist_content=True
        ).save_response(project_response(snapshot, tool_ids={}))

    owner = store(
        branch, root_response=FakeRunStore(save=lambda run: save_root(run.snapshot()))
    )
    coordinator = AgentCoordinator()
    view = owner.bind(
        coordinator, build_agent=never_restore("This response does not suspend")
    )
    agent = fake_agent(answering("done"), agent_id=str(branch[0]))
    try:
        with patch.object(
            owner.cache, "delete", side_effect=RuntimeError("cache cleanup failed")
        ):
            run = agent.start(messages=[user_message], max_steps=1, coordinator=view)
            assert run.result(timeout=10).output.text == "done"
            if save_fails:
                with pytest.raises(ValueError, match="response save failed"):
                    coordinator.completion(run.id).result(timeout=10)
            else:
                assert (
                    coordinator.completion(run.id).result(timeout=10).run_id == run.id
                )
            with pytest.raises(RuntimeError, match="cache cleanup failed"):
                run.wait_for_idle(timeout=10)
            assert not owner.has_owned_work
        owner.cache.delete(run_store._owner_key(int(run.id)))
    finally:
        assert coordinator.close(timeout=10)


def test_terminal_run_retains_control_until_cancelled_tool_drains(
    branch: tuple[UUID, int],
    user_message: UserMessage,
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def tool(_: ToolInvocation) -> ToolResult:
        entered.set()
        assert release.wait(timeout=10)
        return ToolResult(content="finished")

    owner = store(branch)
    coordinator = AgentCoordinator()
    view = owner.bind(
        coordinator, build_agent=never_restore("This response does not suspend")
    )
    agent = fake_agent(
        lambda *_: calls(call("slow")),
        agent_id=str(branch[0]),
        tools=[agent_tool("slow", tool)],
    )
    try:
        run = agent.start(messages=[user_message], max_steps=1, coordinator=view)
        assert entered.wait(timeout=10)
        run.cancel()
        with pytest.raises(AgentCancelled):
            run.result(timeout=10)
        coordinator.completion(run.id).result(timeout=10)
        assert owner.has_owned_work
        release.set()
        assert run.wait_for_idle(timeout=10)
        assert not owner.has_owned_work
    finally:
        release.set()
        assert coordinator.close(timeout=10)


def test_parallel_children_use_reserved_response_identity(
    branch: tuple[UUID, int], db_session: Session, user_message: UserMessage
) -> None:
    owner = store(branch)
    coordinator = AgentCoordinator()
    child_barrier = threading.Barrier(2)
    view = owner.bind(
        coordinator,
        build_agent=never_restore("Completed children do not require restoration"),
    )

    def delegate(invocation: ToolInvocation) -> ChildRunWait:
        def child_reply(*_: object) -> AssistantMessage:
            child_barrier.wait(timeout=10)
            return text(invocation.call_id)

        spawned = invocation.agents.spawn_agent(
            fake_agent(child_reply),
            name=invocation.call_id,
            description="Parallel research",
            messages=[UserMessage(content=invocation.call_id)],
            max_steps=1,
        )
        return ChildRunWait(run_ids=[spawned.run_id])

    agent = delegating_root(
        branch,
        agent_tool("delegate", delegate, result_from_children=first_child_answer),
        tool_calls=[call("first", "delegate"), call("second", "delegate")],
    )
    try:
        run = agent.start(messages=[user_message], max_steps=2, coordinator=view)
        assert run.result(timeout=20).output.text == "done"
        assert run.wait_for_idle(timeout=10)
        assert run.id == str(branch[1])
        snapshot = run.snapshot()
        assert len(snapshot.child_runs) == 2
        assert len({child.run_id for child in snapshot.child_runs}) == 2
        db_session.expire_all()
        for child in snapshot.child_runs:
            row = db_session.get(ChatMessage, int(child.run_id))
            assert row is not None
            assert row.chat_session_id == UUID(child.agent_id)
            assert row.parent_message is not None
            assert row.parent_message.invoking_tool_call is not None
            assert (
                row.parent_message.invoking_tool_call.parent_chat_message_id
                == branch[1]
            )
            assert child.parent_run_id == run.id
            assert child.messages[0].id == f"{child.run_id}:0"
            restored = owner.read_run(child.run_id, str(branch[0]))
            assert restored is not None
            assert restored.run_id == child.run_id
            assert restored.messages == child.messages
        with pytest.raises(ValueError, match="unavailable for a new run"):
            agent.start(messages=[user_message], max_steps=1, coordinator=view)
        restored_root = owner.read_run(run.id, "")
        assert restored_root is not None
        assert [message.model_dump() for message in restored_root.messages] == [
            message.model_dump() for message in snapshot.messages
        ]
    finally:
        assert coordinator.close(timeout=10)


@pytest.mark.parametrize("failure_point", ["bind", "worker", "owner_publication"])
def test_failed_child_start_can_retry_without_an_orphan_response(
    branch: tuple[UUID, int],
    db_session: Session,
    user_message: UserMessage,
    failure_point: str,
) -> None:
    owner = store(branch)
    coordinator = AgentCoordinator()
    view = owner.bind(
        coordinator,
        build_agent=never_restore("Child remains loaded during this test"),
    )
    child = fake_agent(answering("child answer"))

    def delegate(invocation: ToolInvocation) -> ChildRunWait:
        def start_child() -> str:
            return invocation.agents.spawn_agent(
                child,
                name="research",
                description="Research",
                messages=[UserMessage(content="first request")],
                max_steps=1,
            ).run_id

        target = (
            "onyx.agents.agent_coordination.AgentCoordinator.bind"
            if failure_point == "bind"
            else "onyx.agents.runtime.start_thread_with_context"
        )
        failed_start = (
            patch.object(owner.cache, "set", side_effect=RuntimeError("start failed"))
            if failure_point == "owner_publication"
            else patch(target, side_effect=RuntimeError("start failed"))
        )
        with failed_start:
            with pytest.raises(RuntimeError, match="start failed"):
                start_child()
        with get_session_with_tenant(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        ) as session:
            assert session.get(ChatSession, UUID(child.id)) is None
            parent_response = session.get(ChatMessage, branch[1])
            assert parent_response is not None
            assert parent_response.response_status == RunStatus.RUNNING
        retried_id = start_child()
        return ChildRunWait(run_ids=[retried_id])

    agent = delegating_root(
        branch,
        agent_tool("delegate", delegate, result_from_children=first_child_answer),
    )
    try:
        run = agent.start(messages=[user_message], max_steps=2, coordinator=view)
        assert run.result(timeout=20).output.text == "done"
        assert run.wait_for_idle(timeout=10)
        tool_result = run.snapshot().messages[1]
        assert isinstance(tool_result, ToolResult)
        assert not tool_result.is_error
        assert tool_result.content == "child answer"
        db_session.expire_all()
        rows = list(
            db_session.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_session_id == UUID(child.id))
                .order_by(ChatMessage.id)
            )
        )
        responses = [row for row in rows if row.message_type == MessageType.ASSISTANT]
        questions = [row for row in rows if row.message_type == MessageType.USER]
        assert len(responses) == len(questions) == 1
        assert all(row.response_status == RunStatus.COMPLETE for row in responses)
        assert questions[0].parent_message_id is None
        assert not owner.has_owned_work
    finally:
        assert coordinator.close(timeout=10)


@pytest.mark.parametrize("failure_point", ["worker", "owner_publication"])
def test_root_start_failure_releases_reserved_response_for_retry(
    branch: tuple[UUID, int],
    db_session: Session,
    user_message: UserMessage,
    failure_point: str,
) -> None:
    owner = store(branch)
    coordinator = AgentCoordinator()
    view = owner.bind(
        coordinator, build_agent=never_restore("Retry starts a fresh execution")
    )
    agent = fake_agent(answering("done"), agent_id=str(branch[0]))
    try:
        failed_start = (
            patch.object(owner.cache, "set", side_effect=RuntimeError("start failed"))
            if failure_point == "owner_publication"
            else patch(
                "onyx.agents.runtime.start_thread_with_context",
                side_effect=RuntimeError("start failed"),
            )
        )
        with failed_start:
            with pytest.raises(RuntimeError, match="start failed"):
                agent.start(messages=[user_message], max_steps=1, coordinator=view)
        assert not owner.has_owned_work
        response = db_session.get(ChatMessage, branch[1])
        assert response is not None
        assert response.response_status is None
        assert response.response_items == []
        run = agent.start(messages=[user_message], max_steps=1, coordinator=view)
        assert run.id == str(response.id)
        assert run.result(timeout=10).output.text == "done"
        assert run.wait_for_idle(timeout=10)
    finally:
        assert coordinator.close(timeout=10)


def test_resumed_child_keeps_its_original_response_tree(
    branch: tuple[UUID, int], db_session: Session, user_message: UserMessage
) -> None:
    owner = store(branch)
    first, second = AgentCoordinator(), AgentCoordinator()
    child_ids: list[str] = []
    grandchild_ids: list[str] = []

    def nested_delegate(invocation: ToolInvocation) -> ChildRunWait:
        spawned = invocation.agents.spawn_agent(
            fake_agent(answering("facts")),
            name="facts",
            description="Nested research",
            messages=[UserMessage(content="Find facts")],
            max_steps=1,
        )
        grandchild_ids.append(spawned.run_id)
        return ChildRunWait(run_ids=[spawned.run_id])

    child_tools = [
        ask_tool("Continue?"),
        agent_tool(
            "delegate", nested_delegate, result_from_children=first_child_answer
        ),
    ]

    def rebuild(checkpoint: ExecutionCheckpoint) -> Agent:
        return fake_agent(
            replies(calls(call("nested", "delegate")), text("child done")),
            agent_id=checkpoint.run_state.agent_id,
            state=checkpoint.agent_state,
            tools=child_tools,
        )

    view = owner.bind(first, build_agent=rebuild)

    def delegate(invocation: ToolInvocation) -> ToolResult:
        child = invocation.agents.spawn_agent(
            fake_agent(lambda *_: calls(call("ask")), tools=child_tools),
            name="research",
            description="Background research",
            messages=[UserMessage(content="Research")],
            max_steps=3,
            lifetime=AgentLifetime.BACKGROUND,
        )
        child_ids.append(child.run_id)
        running_child = view.run(child.run_id)
        assert running_child is not None
        assert (
            running_child.wait_until_settled(timeout=10).status == RunStatus.SUSPENDED
        )
        assert running_child.wait_for_idle(timeout=10)
        owner.handoff(child.run_id)
        return ToolResult(content="paused")

    agent = delegating_root(
        branch, agent_tool("delegate", delegate), answer="parent done"
    )
    try:
        root = agent.start(messages=[user_message], max_steps=2, coordinator=view)
        assert root.result(timeout=20).output.text == "parent done"
        assert root.wait_for_idle(timeout=10)
        original = db_session.get(ChatMessage, branch[1])
        assert original is not None
        _, next_response = add_turn(db_session, branch[0], original.id, "next")
        sibling = ChatMessage(
            chat_session_id=branch[0],
            parent_message_id=original.parent_message_id,
            message="",
            token_count=0,
            message_type=MessageType.ASSISTANT,
        )
        db_session.add(sibling)
        db_session.commit()
        remote = store(
            (branch[0], next_response.id), visible_response_ids=[original.id]
        )
        remote.bind(second, build_agent=rebuild)
        sibling_store = store((branch[0], sibling.id))
        with pytest.raises(ValueError, match="unavailable on this branch"):
            sibling_store.read_run(child_ids[0], str(branch[0]))
        resumed = remote.resume(child_ids[0], context=AgentState())
        assert resumed is not None
        resumed.submit(
            HumanToolAnswer(
                request_id="answer",
                decision=InputDecision.RESULT,
                result=ToolResult(content="approved"),
            )
        )
        assert resumed.result(timeout=20).output.text == "child done"
        assert resumed.wait_for_idle(timeout=10)
        assert len(grandchild_ids) == 1
        db_session.expire_all()
        grandchild = db_session.get(ChatMessage, int(grandchild_ids[0]))
        assert grandchild is not None
        assert root_response_id(db_session, grandchild) == original.id
        assert grandchild.parent_message is not None
        assert grandchild.parent_message.invoking_tool_call is not None
        assert (
            grandchild.parent_message.invoking_tool_call.parent_chat_message_id
            == int(child_ids[0])
        )
        assert next_response.response_status is None
        assert sibling.response_status is None
        restored = remote.read_run(grandchild_ids[0], resumed.agent_id)
        assert restored is not None and restored.status == RunStatus.COMPLETE
    finally:
        assert first.close(timeout=10)
        assert second.close(timeout=10)


@pytest.mark.parametrize("action", ["cancel", "running", "completed", "cancelled"])
def test_background_agent_tools_work_from_later_turn_and_preserve_branch_access(
    branch: tuple[UUID, int],
    db_session: Session,
    user_message: UserMessage,
    action: str,
) -> None:
    cancel_child = action in {"cancel", "cancelled"}
    child_started = threading.Event()
    release_child = threading.Event()
    first_owner = store(branch)
    first_coordinator = AgentCoordinator()
    later_coordinator = AgentCoordinator()
    no_restore = never_restore(
        "Reading results and cancelling must not restore an agent"
    )

    def child_reply(
        _request: GenerationRequest, cancellation: CancellationSignal
    ) -> AssistantMessage:
        child_started.set()
        for _ in range(1000):
            cancellation.check()
            if release_child.wait(0.01):
                cancellation.check()
                return text("Child answer [1]")
        raise TimeoutError("Test did not release the child")

    def create_leaf() -> Agent:
        return fake_agent(
            child_reply,
            prepare_step=lambda _: PreparedStep(
                output_metadata=ChatMessageMetadata(
                    sources={
                        1: SearchDoc(
                            document_id="child-source",
                            chunk_ind=0,
                            semantic_identifier="Child source",
                            blurb="Evidence",
                            source_type=DocumentSource.WEB,
                            boost=1,
                            hidden=False,
                            metadata={},
                            match_highlights=[],
                        )
                    }
                )
            ),
        )

    first_agent = fake_agent(
        replies(
            calls(spawn_call("spawn", "research", "Find the answer")),
            text("Agent started"),
        ),
        agent_id=str(branch[0]),
        tools=[SpawnAgentTool(create_leaf, max_steps=4).bind(ToolContext)],
    )
    first_view = first_owner.bind(first_coordinator, build_agent=no_restore)
    try:
        first = first_agent.start(
            messages=[user_message], max_steps=2, coordinator=first_view
        )
        assert first.result(timeout=10).output.text == "Agent started"
        assert first.wait_for_idle(timeout=10)
        spawned_result = first.snapshot().steps[0].tools["spawn"].result
        assert spawned_result is not None
        info = child_info(first_owner, str(branch[0]))
        assert info.latest_run_id is not None
        child = SpawnResult(
            agent_id=info.id, agent_path=info.path, run_id=info.latest_run_id
        )
        direct_child = child
        assert (
            first_owner.read_run_status(child.run_id, str(branch[0]))
            == RunStatus.RUNNING
        )
        assert first_owner.has_owned_work
        with pytest.raises(ValueError, match="unavailable to this parent"):
            first_owner.read_run(first.id, child.agent_id)
        assert first_owner.lookup_agent(str(branch[0]), child.agent_id) is None

        db_session.expire_all()
        initial_response = db_session.get(ChatMessage, branch[1])
        assert initial_response is not None
        alternate_response = ChatMessage(
            chat_session_id=branch[0],
            parent_message_id=initial_response.parent_message_id,
            message="",
            token_count=0,
            message_type=MessageType.ASSISTANT,
        )
        db_session.add(alternate_response)
        later_question, later_response = add_turn(
            db_session, branch[0], branch[1], "Check the agent"
        )
        alternate_owner = store((branch[0], alternate_response.id))
        assert not [info for info in alternate_owner.list_agents() if info.parent_id]
        with pytest.raises(ValueError, match="unavailable on this branch"):
            alternate_owner.read_run(child.run_id, str(branch[0]))
        with pytest.raises(ValueError, match="unavailable on this branch"):
            alternate_owner.cancel_run(child.run_id, str(branch[0]))

        later_owner = store(
            (branch[0], later_response.id), visible_response_ids=[branch[1]]
        )
        later_view = later_owner.bind(later_coordinator, build_agent=no_restore)
        for info in later_owner.list_agents():
            later_view.register(info)
        assert not later_owner.has_owned_work
        assert child_started.wait(timeout=10)
        if action in {"completed", "cancelled"}:
            if cancel_child:
                first_owner.cancel_run(child.run_id, str(branch[0]))
            else:
                release_child.set()
            first_coordinator.completion(direct_child.run_id).result(timeout=10)
        later_calls = [ToolCall(id="list", name="list_agents", arguments={})]
        if action == "cancel":
            later_calls.append(
                ToolCall(
                    id="queue",
                    name="send_message",
                    arguments={
                        "agent_id": child.agent_id,
                        "message": "Continue later",
                        "delivery": "queue",
                    },
                )
            )
            later_calls.append(
                ToolCall(
                    id="interrupt",
                    name="interrupt_agent",
                    arguments={"agent_id": child.agent_id},
                )
            )
            later_calls.append(ToolCall(id="refresh", name="list_agents", arguments={}))
        remaining_calls = iter(later_calls)

        def later_reply(
            _request: GenerationRequest, _cancellation: CancellationSignal
        ) -> AssistantMessage:
            next_call = next(remaining_calls, None)
            if next_call is None:
                return text("Checked")
            if next_call.id == "interrupt":
                observer = unpolled_store(
                    (branch[0], later_response.id), visible_response_ids=[branch[1]]
                )
                observer.bind(later_coordinator, build_agent=no_restore)
                observer.poll_control()
                assert observer.has_owned_work
            if action == "running":
                release_child.set()
            if action == "running" or next_call.id == "refresh":
                first_coordinator.completion(direct_child.run_id).result(timeout=10)
            return calls(next_call)

        later_agent = chat_agent(
            FakeModelClient(later_reply),
            agent_id=str(branch[0]),
            prompt="Help",
            create_subagent=lambda: pytest.fail("A later turn must not spawn"),
        )
        # The root comes first; the cap keeps each listed agent's parent.
        with patch("onyx.db.chat_subagents.MAX_DISCOVERED_AGENTS", 2):
            limited = later_owner.list_agents()
            assert {info.parent_id for info in limited} <= {
                None,
                *(info.id for info in limited),
            }
            assert child.agent_id in {info.id for info in limited}
            later = later_agent.start(
                messages=[
                    UserMessage(
                        id=f"chat:{later_question.id}", content=later_question.message
                    )
                ],
                max_steps=len(later_calls) + 1,
                coordinator=later_view,
            )
            assert later.result(timeout=15).output.text == "Checked"
            assert later.wait_for_idle(timeout=10)
        later_results = [
            tool.result
            for step in later.snapshot().steps
            for tool in step.tools.values()
        ]
        assert all(
            result is not None and not result.is_error for result in later_results
        )
        listed = later_results[0]
        assert listed is not None
        assert child.agent_id in listed.text
        assert child.agent_path in listed.text
        later_coordinator.completion(later.id).result(timeout=10)
        first_coordinator.completion(child.run_id).result(timeout=10)
        saved = later_owner.read_run(child.run_id, str(branch[0]))
        assert saved is not None
        assert saved.status == (
            RunStatus.CANCELLED if cancel_child else RunStatus.COMPLETE
        )
        if action == "cancel":
            assert child.agent_id in {info.id for info in later_view.discover_agents()}
            assert pending_agent_messages(db_session, child.agent_id) == 1
        received = [
            message
            for step in later.snapshot().steps
            for message in step.input_messages
        ]
        assert later_owner.delegated_runs(later_agent.id) == {}
        if action == "cancel":
            # An interrupted run reports no result.
            assert received == []
        else:
            assert len(received) == 1
            assert received[0].id == f"agent-result:{direct_child.run_id}"
            notification = json.loads(received[0].text.split("\n", 1)[1])
            assert notification["status"] == (
                "cancelled" if cancel_child else "complete"
            )
            assert notification["answer"] == (
                "" if cancel_child else "Child answer [1]"
            )
        saved_response = read_response__no_commit(db_session, int(later.id))
        assert saved_response is not None
        restored = response_snapshot(saved_response.response)
        assert [
            message for step in restored.steps for message in step.input_messages
        ] == received
        if not cancel_child:
            metadata = later.snapshot().steps[-1].message.metadata
            assert isinstance(metadata, ChatMessageMetadata)
            assert metadata.sources[1].document_id == "child-source"
            # A child's cited documents can be attached to its root response.
            db_session.execute(
                update(ChatMessage__SearchDoc)
                .where(ChatMessage__SearchDoc.chat_message_id == int(child.run_id))
                .values(chat_message_id=branch[1])
            )
            db_session.commit()
            completion = read_agent_completions(db_session, [int(child.run_id)])[0]
            assert completion.output is not None
            metadata = completion.output.metadata
            assert isinstance(metadata, ChatMessageMetadata)
            assert metadata.sources[1].document_id == "child-source"
        db_session.expire_all()
        parent_response = db_session.get(ChatMessage, branch[1])
        assert parent_response is not None
        packets = translate_assistant_message_to_packets(
            parent_response, {}, db_session
        )
        assert "Child answer" not in "".join(
            packet.model_dump_json() for packet in packets
        )
    finally:
        release_child.set()
        assert later_coordinator.close(timeout=10)
        assert first_coordinator.close(timeout=10)


@pytest.mark.parametrize(
    ("delivery", "child_is_running"),
    [("send", False), ("queue", False), ("send", True)],
)
def test_later_turn_sends_to_chat_child_through_another_coordinator(
    branch: tuple[UUID, int],
    db_session: Session,
    user_message: UserMessage,
    delivery: str,
    child_is_running: bool,
) -> None:
    first_coordinator = AgentCoordinator()
    later_coordinator = AgentCoordinator()
    first_owner = store(branch)
    release_child = threading.Event()
    child_started = threading.Event()
    child_answered = threading.Event()

    def make_agent(
        llm: LLM,
        *,
        prompt: str,
        state: AgentState | None = None,
        agent_id: str | None = None,
        previous_run_id: str | None = None,
    ) -> ChatAgent:
        return chat_agent(
            llm,
            state=state,
            agent_id=agent_id,
            previous_run_id=previous_run_id,
            prompt=prompt,
            create_subagent=lambda: make_agent(llm, prompt=prompt),
        )

    def first_reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if any(message.text == "child task" for message in request.messages):
            child_started.set()
            if child_is_running:
                assert release_child.wait(timeout=20)
            if any(message.text == "follow up" for message in request.messages):
                child_answered.set()
                return text("Second child answer")
            return text("First child answer")
        if any(isinstance(message, ToolResultMessage) for message in request.messages):
            return text("Started")
        return calls(spawn_call("spawn", "worker", "child task"))

    no_resume = never_restore("A fresh follow-up must not resume a suspended execution")

    try:
        first_agent = make_agent(
            FakeModelClient(first_reply),
            agent_id=str(branch[0]),
            prompt="Original settings",
        )
        first_view = first_owner.bind(first_coordinator, build_agent=no_resume)
        first = first_agent.start(
            messages=[user_message], max_steps=3, coordinator=first_view
        )
        assert first.result(timeout=15).output.text == "Started"
        assert first.wait_for_idle(timeout=10)
        spawned = first.snapshot().steps[0].tools["spawn"].result
        assert spawned is not None
        info = child_info(first_owner, str(branch[0]))
        assert info.latest_run_id is not None
        child = SpawnResult(
            agent_id=info.id, agent_path=info.path, run_id=info.latest_run_id
        )
        assert child_started.wait(timeout=10)
        if not child_is_running:
            first_coordinator.completion(child.run_id).result(timeout=15)
            assert first_coordinator.close(timeout=10)

        later_question, later_response = add_turn(
            db_session, branch[0], branch[1], "Continue the child"
        )
        later_owner = store(
            (branch[0], later_response.id), visible_response_ids=[branch[1]]
        )
        restored_ids: list[str] = []

        def later_reply(
            request: GenerationRequest, _signal: CancellationSignal
        ) -> AssistantMessage:
            if any(message.text == "child task" for message in request.messages):
                assert any(
                    message.text == "First child answer" for message in request.messages
                )
                assert any(message.text == "follow up" for message in request.messages)
                assert "Current settings" in request.messages[0].text
                child_answered.set()
                return text("Second child answer")
            result_names = {
                message.tool_name
                for message in request.messages
                if isinstance(message, ToolResultMessage)
            }
            if "send_message" not in result_names:
                return calls(
                    ToolCall(
                        id="send",
                        name="send_message",
                        arguments={
                            "agent_id": child.agent_id,
                            "message": "follow up",
                            "delivery": delivery,
                        },
                    )
                )
            release_child.set()
            if "list_agents" not in result_names:
                assert child_answered.wait(timeout=15)
                current_child = later_owner.lookup_agent(child.agent_id, str(branch[0]))
                assert (
                    current_child is not None
                    and current_child.latest_run_id is not None
                )
                child_owner = (
                    first_coordinator if child_is_running else later_coordinator
                )
                child_owner.completion(current_child.latest_run_id).result(timeout=15)
                return calls(call("list", "list_agents"))
            assert any(
                "Second child answer" in message.text for message in request.messages
            )
            return text("Continued")

        llm = FakeModelClient(later_reply)

        def restore_child(history: SavedAgentContext, _depth: int) -> ChatAgent:
            restored_ids.append(history.agent_id)
            assert history.previous_run_id == child.run_id
            return make_agent(
                llm,
                state=AgentState(
                    messages=history.messages, checkpoint=history.checkpoint
                ),
                agent_id=history.agent_id,
                previous_run_id=history.previous_run_id,
                prompt="Current settings",
            )

        later_owner._restore_subagent = restore_child
        later_view = later_owner.bind(later_coordinator, build_agent=no_resume)
        later_agent = make_agent(
            llm,
            agent_id=str(branch[0]),
            previous_run_id=first.id,
            prompt="Current settings",
        )
        later = later_agent.start(
            messages=[
                UserMessage(
                    id=f"chat:{later_question.id}", content=later_question.message
                )
            ],
            max_steps=4,
            coordinator=later_view,
        )
        assert later.result(timeout=20).output.text == "Continued"
        assert later.wait_for_idle(timeout=10)
        assert restored_ids == ([] if child_is_running else [child.agent_id])
        saved_child = later_owner.lookup_agent(child.agent_id, str(branch[0]))
        assert saved_child is not None
        assert saved_child.latest_run_id is not None
        saved = later_owner.read_run(saved_child.latest_run_id, str(branch[0]))
        assert saved is not None and saved.status == RunStatus.COMPLETE
        if child_is_running:
            assert saved_child.latest_run_id == child.run_id
            accepted = [
                message for step in saved.steps for message in step.input_messages
            ]
            assert [message.text for message in accepted] == ["follow up"]
        else:
            assert saved_child.latest_run_id != child.run_id
            assert saved.previous_run_id == child.run_id
            assert saved.input_messages[0].text == "follow up"
        assert pending_agent_messages(db_session, child.agent_id) == 0
    finally:
        release_child.set()
        assert later_coordinator.close(timeout=10)
        assert first_coordinator.close(timeout=10)


def test_message_from_an_earlier_turn_continues_the_recipients_latest_run(
    branch: tuple[UUID, int],
    db_session: Session,
    user_message: UserMessage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turn 1 starts X and C. In turn 2 the root messages C. Then X messages C.

    C's next run continues its turn-2 run under the turn-2 root, even when the
    turn-1 store dispatches it. The live turn keeps running.
    """
    monkeypatch.setattr("onyx.chat.run_store.INPUT_POLL_SECONDS", 0)
    root_id = str(branch[0])
    first_response = db_session.get(ChatMessage, branch[1])
    assert first_response is not None and first_response.parent_message is not None
    first_response.parent_message.latest_child_message_id = first_response.id
    db_session.commit()
    first_owner = unpolled_store(branch)
    first_coordinator = AgentCoordinator()
    later_coordinator = AgentCoordinator()
    send_from_x = threading.Event()
    finish_later_root = threading.Event()
    c_inputs: list[list[str]] = []
    c_ids: list[str] = []

    def child_reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        texts = [
            message.text
            for message in request.messages
            if isinstance(message, UserMessage)
        ]
        if texts[0] != "x task":
            c_inputs.append(texts)
            return text("C answer")
        if any(isinstance(message, ToolResultMessage) for message in request.messages):
            return text("X done")
        assert send_from_x.wait(20)
        return calls(
            ToolCall(
                id="tell",
                name="send_message",
                arguments={"agent_id": c_ids[0], "message": "from X"},
            )
        )

    def child(
        state: AgentState | None = None,
        agent_id: str | None = None,
        previous_run_id: str | None = None,
    ) -> Agent:
        return Agent(
            FakeModelClient(child_reply),
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
            state=state,
            agent_id=agent_id,
            previous_run_id=previous_run_id,
            tools=[SendMessageTool(max_steps=2).bind(ToolContext)],
        )

    def restore_child(history: SavedAgentContext, _depth: int) -> Agent:
        return child(
            AgentState(messages=history.messages, checkpoint=history.checkpoint),
            history.agent_id,
            history.previous_run_id,
        )

    def latest_c_run(owner: ChatRunStore) -> str:
        info = owner.lookup_agent(c_ids[0], root_id)
        assert info is not None and info.latest_run_id is not None
        return info.latest_run_id

    def dispatch_next_c_run(owner: ChatRunStore, previous: str) -> str:
        for _ in range(500):
            owner.poll_control()
            if (latest := latest_c_run(owner)) != previous:
                return latest
            threading.Event().wait(0.02)
        pytest.fail("C did not start its next run")

    first_owner._restore_subagent = restore_child
    first_view = first_owner.bind(first_coordinator, build_agent=never_restore("X"))
    first_root = fake_agent(
        replies(
            calls(
                spawn_call("x", "x", "x task"),
                spawn_call("c", "c", "c task"),
            ),
            text("Started"),
        ),
        agent_id=root_id,
        tools=[SpawnAgentTool(child, max_steps=3).bind(ToolContext)],
    )
    try:
        first = first_root.start(
            messages=[user_message], max_steps=2, coordinator=first_view
        )
        assert first.result(timeout=15).output.text == "Started"
        agents = {info.path: info for info in first_owner.list_agents()}
        x_run, c_first = (
            agents["/root/x"].latest_run_id,
            agents["/root/c"].latest_run_id,
        )
        assert x_run is not None and c_first is not None
        c_ids.append(agents["/root/c"].id)
        first_coordinator.completion(c_first).result(timeout=10)

        # Turn 2: the root messages C, which runs under the turn-2 root.
        later_question, later_response = add_turn(
            db_session, branch[0], branch[1], "Continue C"
        )
        first_response.latest_child_message_id = later_question.id
        later_question.latest_child_message_id = later_response.id
        db_session.commit()
        later_owner = unpolled_store(
            (branch[0], later_response.id), visible_response_ids=[branch[1]]
        )
        later_owner._restore_subagent = restore_child
        later_view = later_owner.bind(
            later_coordinator, build_agent=never_restore("Later root")
        )
        for info in later_owner.list_agents():
            later_view.register(info)

        def later_reply(
            request: GenerationRequest, _signal: CancellationSignal
        ) -> AssistantMessage:
            if not any(
                isinstance(message, ToolResultMessage) for message in request.messages
            ):
                return calls(
                    ToolCall(
                        id="ask",
                        name="send_message",
                        arguments={"agent_id": c_ids[0], "message": "from root"},
                    )
                )
            assert finish_later_root.wait(30)
            return text("Continued")

        later = fake_agent(
            later_reply,
            agent_id=root_id,
            tools=[SendMessageTool(max_steps=2).bind(ToolContext)],
        ).start(
            messages=[
                UserMessage(id=f"chat:{later_question.id}", content="Continue C")
            ],
            max_steps=2,
            coordinator=later_view,
        )
        c_second = dispatch_next_c_run(later_owner, c_first)
        later_coordinator.completion(c_second).result(timeout=10)

        # X, still running from turn 1, now messages C.
        send_from_x.set()
        first_coordinator.completion(x_run).result(timeout=10)
        c_third = dispatch_next_c_run(first_owner, c_second)
        assert first_coordinator.completion(c_third).result(timeout=10).status == (
            RunStatus.COMPLETE
        )

        saved = later_owner.read_run(c_third, root_id)
        assert saved is not None and saved.previous_run_id == c_second
        assert "from root" in c_inputs[-1]
        assert any(text.endswith("from X") for text in c_inputs[-1])
        db_session.expire_all()
        third = db_session.get(ChatMessage, int(c_third))
        assert third is not None and third.parent_message is not None
        assert third.parent_message.parent_message_id == int(c_second)
        assert db_session.scalar(
            select(ChatInput.root_response_id).where(
                ChatInput.source_response_id == int(c_third)
            )
        ) == (later_response.id)
        finish_later_root.set()
        assert later.result(timeout=10).output.text == "Continued"
    finally:
        send_from_x.set()
        finish_later_root.set()
        assert later_coordinator.close(timeout=10)
        assert first_coordinator.close(timeout=10)


@pytest.mark.parametrize(
    "failure", ["owner_publication", "interrupted_reservation", "bind", "worker"]
)
def test_queued_reservation_failure_is_durable_and_explicit_send_recovers(
    branch: tuple[UUID, int],
    db_session: Session,
    user_message: UserMessage,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    monkeypatch.setattr("onyx.chat.run_store.INPUT_POLL_SECONDS", 0)
    coordinator = AgentCoordinator()
    owner = unpolled_store(branch)
    observer = store(branch)
    model_inputs: list[list[str]] = []

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        model_inputs.append([message.text for message in request.messages])
        return text("Child answer")

    llm = FakeModelClient(reply)
    owner._restore_subagent = lambda history, _depth: chat_agent(
        llm,
        state=AgentState(messages=history.messages, checkpoint=history.checkpoint),
        agent_id=history.agent_id,
        previous_run_id=history.previous_run_id,
    )
    view = owner.bind(coordinator, build_agent=never_restore("No handoff"))
    child = chat_agent(llm, agent_id=str(uuid4()))
    dispatch = owner._dispatch_messages
    failed_response_ids: list[str] = []

    def interrupt_before_register(run: Run) -> None:
        with get_session_with_tenant(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        ) as session:
            saved = session.get(ChatMessage, int(run.id))
            assert saved is not None and saved.response_status == RunStatus.RUNNING
        assert owner.cache.exists(run_store._owner_key(int(run.id)))
        # Simulate an exited process after its durable reservation, before Run registration.
        owner._leases.pop(int(run.id)).released = True
        owner.cache.delete(run_store._owner_key(int(run.id)))
        assert observer.read_run_status(run.id, str(branch[0])) == RunStatus.ERROR
        failed_response_ids.append(run.id)
        raise RuntimeError("Process exited before registration")

    def delegate(invocation: ToolInvocation) -> ToolResult:
        started = invocation.agents.spawn_agent(
            child,
            name="worker",
            description="Worker",
            messages=[UserMessage(content="initial task")],
            max_steps=2,
            restoration_config=ChatConfiguration(kind="chat"),
        )
        assert (
            coordinator.completion(started.run_id).result(timeout=10).status
            == RunStatus.COMPLETE
        )
        assert coordinator.run(started.run_id).wait_for_idle(timeout=10)
        request = AgentMessageRequest(
            agent_id=child.id,
            parent_id=str(branch[0]),
            message=UserMessage(content="failed queued task"),
            delivery=MessageDelivery.SEND,
            max_steps=2,
            total_timeout_s=30,
            parent_run_id=str(branch[1]),
            parent_message_id=f"{branch[1]}:0",
            parent_tool_call_id="delegate",
        )
        owner.submit_message(request)
        if failure == "owner_publication":
            failure_patch = patch.object(
                owner.cache, "set", side_effect=RuntimeError("Owner publication failed")
            )
        elif failure == "interrupted_reservation":
            failure_patch = patch.object(
                owner, "register", side_effect=interrupt_before_register
            )
        else:
            failure_patch = patch(
                "onyx.agents.agent_coordination.AgentCoordinator.bind"
                if failure == "bind"
                else "onyx.agents.runtime.start_thread_with_context",
                side_effect=RuntimeError("Queued startup failed"),
            )
        with failure_patch:
            dispatch()
        info = owner.lookup_agent(child.id, str(branch[0]))
        assert info is not None and info.latest_run_id is not None
        failed_response_ids.append(info.latest_run_id)
        assert (
            observer.read_run_status(info.latest_run_id, str(branch[0]))
            == RunStatus.ERROR
        )
        saved = observer.read_run(info.latest_run_id, str(branch[0]))
        assert saved is not None
        assert saved.input_messages[0].text == "failed queued task"
        assert pending_agent_messages(db_session, child.id) == 0
        assert not owner.cache.exists(run_store._owner_key(int(info.latest_run_id)))
        assert all("failed queued task" not in messages for messages in model_inputs)
        # A fresh explicit send may restart after failure; it keeps the failed question in history.
        owner.submit_message(
            request.model_copy(update={"message": UserMessage(content="retry task")})
        )
        dispatch()
        retried = owner.lookup_agent(child.id, str(branch[0]))
        assert retried is not None and retried.latest_run_id is not None
        assert retried.latest_run_id != info.latest_run_id
        completed = coordinator.completion(retried.latest_run_id).result(timeout=10)
        assert completed.status == RunStatus.COMPLETE
        assert (
            observer.read_run_status(retried.latest_run_id, str(branch[0]))
            == RunStatus.COMPLETE
        )
        return ToolResult(content="Recovered")

    parent = delegating_root(branch, agent_tool("delegate", delegate), answer="Done")
    try:
        run = parent.start(messages=[user_message], max_steps=2, coordinator=view)
        assert run.result(timeout=20).output.text == "Done"
        assert run.wait_for_idle(timeout=10)
        result = run.snapshot().steps[0].tools["delegate"].result
        assert result is not None and not result.is_error
        assert result.text == "Recovered"
        assert len(set(failed_response_ids)) == 1
    finally:
        assert coordinator.close(timeout=10)


@pytest.mark.parametrize("commit_before_error", [False, True])
def test_input_acceptance_failure_preserves_committed_history(
    branch: tuple[UUID, int],
    db_session: Session,
    user_message: UserMessage,
    monkeypatch: pytest.MonkeyPatch,
    commit_before_error: bool,
) -> None:
    entered, release = threading.Event(), threading.Event()

    def generate(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        entered.set()
        assert release.wait(10)
        return text("First answer")

    def fail_acceptance(
        session: Session, root_message_id: int, record: ResponseRecord
    ) -> None:
        save_response_record__no_commit(session, root_message_id, record)
        if any(step.input_messages for step in record.steps):
            if commit_before_error:
                session.commit()
            raise RuntimeError("Input acceptance failed")

    monkeypatch.setattr(
        "onyx.chat.run_store.save_response_record__no_commit", fail_acceptance
    )
    owner = store(branch)
    coordinator = AgentCoordinator()
    view = owner.bind(coordinator, build_agent=never_restore("Unexpected restoration"))
    agent = fake_agent(generate, agent_id=str(branch[0]))
    try:
        run = agent.start(messages=[user_message], max_steps=2, coordinator=view)
        assert entered.wait(10)
        db_session.add(
            ChatInput(
                recipient_session_id=branch[0],
                message_id="incoming",
                source=InputSource.HUMAN,
                source_response_id=branch[1],
                target_response_id=branch[1],
                delivery=MessageDelivery.SEND,
                content="New instruction",
            )
        )
        db_session.commit()
        release.set()
        with pytest.raises(RunFailed):
            run.result(timeout=10)
        assert run.wait_for_idle(timeout=10)
        if commit_before_error:
            with pytest.raises(ValueError, match="cannot discard recorded items"):
                coordinator.completion(run.id).result(timeout=10)
        else:
            assert (
                coordinator.completion(run.id).result(timeout=10).status
                == RunStatus.ERROR
            )
        state = run.snapshot()
        assert len(state.steps) == 1
        assert all(
            message.id != "incoming"
            for step in state.steps
            for message in step.input_messages
        )
        saved = read_response__no_commit(db_session, branch[1])
        assert saved is not None
        assert len(saved.response.steps) == (2 if commit_before_error else 1)
        pending = list(
            db_session.scalars(
                select(ChatInput).where(
                    ChatInput.recipient_session_id == branch[0],
                    ChatInput.message_id == "incoming",
                )
            )
        )
        # Acceptance consumes the pending row in the transaction that saves the step.
        assert len(pending) == int(not commit_before_error)
        if commit_before_error:
            item = db_session.get(ChatResponseItem, f"{run.id}:1")
            assert item is not None
            assert [entry.id for entry in item.inputs] == ["incoming"]
            restored_input = saved.response.steps[1].input_messages[0]
            assert isinstance(restored_input.metadata, InputMessageMetadata)
            assert restored_input.metadata.source == InputSource.HUMAN
    finally:
        release.set()
        assert coordinator.close(timeout=10)


def test_follow_ups_answer_unread_results_under_a_hidden_question(
    make_test_user: MakeTestUser,
    branch: tuple[UUID, int],
    db_session: Session,
    user_message: UserMessage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = unpolled_store(branch)
    coordinator = AgentCoordinator()
    release_leaf = threading.Event()
    release_child = threading.Event()
    continued = threading.Event()
    response = db_session.get(ChatMessage, branch[1])
    assert response is not None and response.parent_message is not None
    response.parent_message.latest_child_message_id = response.id
    user = make_test_user("automatic-agent-response")
    response.chat_session.user_id = user.id
    db_session.commit()

    def leaf_reply(*_: object) -> AssistantMessage:
        assert release_leaf.wait(10)
        return text("The leaf found the evidence")

    def create_leaf() -> Agent:
        return fake_agent(leaf_reply)

    child_replies = replies(
        calls(spawn_call("leaf", "leaf", "Collect evidence")),
        text("Research delegated"),
    )

    def child_reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if any(
            isinstance(message, UserMessage)
            and "The leaf found the evidence" in message.text
            for message in request.messages
        ):
            continued.set()
            return text("The final research report")
        reply = child_replies(request, _signal)
        if not reply.tool_calls:
            assert release_child.wait(10)
        return reply

    def create_child() -> Agent:
        return fake_agent(
            child_reply,
            tools=[SpawnAgentTool(create_leaf, max_steps=3).bind(ToolContext)],
        )

    root = spawning_root(
        branch,
        create_child,
        name="research",
        instruction="Find the answer",
        answer="Research is running",
    )
    view = owner.bind(
        coordinator, build_agent=never_restore("No checkpoint restore expected")
    )
    try:
        run = root.start(messages=[user_message], max_steps=3, coordinator=view)
        assert run.result(timeout=10).output.text == "Research is running"
        assert run.wait_for_idle(timeout=10)
        info = child_info(owner, str(branch[0]))
        assert info.latest_run_id is not None
        release_child.set()
        child = view.child_run(info.latest_run_id, str(branch[0]))
        assert child is not None
        assert child.wait_until_settled(timeout=10).status == RunStatus.SUSPENDED
        leaf = child_info(owner, child.agent_id)
        assert leaf.latest_run_id is not None
        assert not any(
            status.is_terminal
            for status in owner.delegated_runs(str(branch[0])).values()
        )
        release_leaf.set()
        assert continued.wait(10)
        assert child.result(timeout=10).output.text == "The final research report"
        assert child.wait_for_idle(timeout=10)
        db_session.expire_all()
        stored = db_session.get(ChatMessage, int(child.id))
        assert stored is not None
        assert root_response_id(db_session, stored) == branch[1]
        accepted_results = [
            entry
            for item in stored.response_items
            for entry in item.inputs
            if entry.source == InputSource.AGENT_RESULT
        ]
        assert len(accepted_results) == 1
        assert accepted_results[0].source_run_id == leaf.latest_run_id
        assert owner.delegated_runs(child.agent_id) == {}
        history = load_agent_history(load_chat_branch(branch[1]), child.agent_id)
        assert history.previous_run_id == child.id
        assert history.messages[-1].text == "The final research report"
        execution = read_chat_execution(response)
        assert execution is not None
        assert child.id in {item.run_id for item in execution.response.child_runs}
        fresh_owner = store(branch)
        assert (
            fresh_owner.read_run_status(child.id, str(branch[0])) == RunStatus.COMPLETE
        )
        saved_child = fresh_owner.read_run(child.id, str(branch[0]))
        assert saved_child is not None
        assert saved_child.parent_run_id == str(branch[1])
        assert fresh_owner.delegated_runs(str(branch[0])) == {
            child.id: RunStatus.COMPLETE
        }
        assert (
            next(
                info for info in owner.list_agents() if info.id == child.agent_id
            ).latest_run_id
            == child.id
        )
        # An idle child with an unread result answers it in a follow-up run.
        result_id = f"{AGENT_RESULT_MESSAGE_PREFIX}{leaf.latest_run_id}"
        db_session.add(
            ChatInput(
                recipient_session_id=UUID(child.agent_id),
                message_id=result_id,
                source=InputSource.AGENT_RESULT,
                source_response_id=int(leaf.latest_run_id),
                root_response_id=branch[1],
                content="",
            )
        )
        db_session.commit()
        monkeypatch.setattr("onyx.chat.run_store.INPUT_POLL_SECONDS", 0)
        owner.poll_control()
        latest_child = next(
            info for info in view.discover_agents() if info.id == child.agent_id
        )
        assert latest_child.latest_run_id is not None
        assert latest_child.latest_run_id != child.id
        assert (
            coordinator.completion(latest_child.latest_run_id).result(timeout=10).status
            == RunStatus.COMPLETE
        )
        db_session.expire_all()
        child_follow_up = db_session.get(ChatMessage, int(latest_child.latest_run_id))
        assert child_follow_up is not None
        child_question = child_follow_up.parent_message
        assert child_question is not None
        assert child_question.message_type == MessageType.AGENT_RESULTS
        assert child_question.message == ""
        assert child_question.parent_message_id == int(child.id)
        first_question = stored.parent_message
        assert first_question is not None
        assert first_question.invoking_tool_call_id is not None
        assert (
            child_question.invoking_tool_call_id == first_question.invoking_tool_call_id
        )
        step_zero = min(
            child_follow_up.response_items, key=lambda item: item.step_index
        )
        assert [(entry.id, entry.source) for entry in step_zero.inputs] == [
            (result_id, InputSource.AGENT_RESULT)
        ]
        assert (
            db_session.scalar(
                select(ChatInput).where(
                    ChatInput.recipient_session_id == UUID(child.agent_id)
                )
            )
            is None
        )

    finally:
        release_child.set()
        release_leaf.set()
        assert coordinator.close(timeout=10)


def test_chat_parent_works_while_its_child_runs_and_reads_the_result(
    branch: tuple[UUID, int],
    db_session: Session,
    user_message: UserMessage,
    code_mode: bool,
) -> None:
    """In code mode the parent's work runs in a program; the child's result still
    arrives at the next step boundary, after the program's result."""
    owner = store(branch)
    coordinator = AgentCoordinator()
    child_entered, release_child = threading.Event(), threading.Event()
    child_requests: list[GenerationRequest] = []
    parent_requests: list[GenerationRequest] = []

    class WorkTool(EchoTool):
        def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
            # The parent keeps working while its child runs, then lets it finish.
            assert child_entered.wait(10)
            release_child.set()
            info = child_info(owner, str(branch[0]))
            assert info.latest_run_id is not None
            view.completion(info.latest_run_id).result(10)
            return ToolResult(content="work complete")

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if any(message.text == "Independent task" for message in request.messages):
            child_requests.append(request)
            child_entered.set()
            assert release_child.wait(10)
            return text("Child answer")
        parent_requests.append(request)
        if len(parent_requests) == 1:
            return calls(spawn_call("spawn", "investigate", "Independent task"))
        if len(parent_requests) == 2:
            if code_mode:
                return calls(
                    ToolCall(
                        id="work",
                        name="execute_code",
                        arguments={
                            "code": "print(await echo(value='x'))",
                            "yield_time_ms": 30000,
                        },
                    )
                )
            return calls(ToolCall(id="work", name="echo", arguments={"value": "x"}))
        return text("Parent answer")

    def make_agent(agent_id: str | None = None) -> ChatAgent:
        return chat_agent(
            FakeModelClient(reply),
            agent_id=agent_id,
            tools=[WorkTool()],
            create_subagent=make_agent,
            code_mode=code_mode,
        )

    view = owner.bind(coordinator, build_agent=never_restore("No resume expected"))
    try:
        run = make_agent(str(branch[0])).start(
            messages=[user_message], max_steps=4, coordinator=view
        )
        assert run.result(timeout=15).output.text == "Parent answer"
        assert run.wait_for_idle(timeout=10)
        # Agent tools stay direct tools; in code mode the work tool is a function.
        offered = {tool.name for tool in parent_requests[0].tools or []}
        assert {"spawn_agent", "send_message"} <= offered
        assert ("execute_code" in offered) is code_mode
        assert ("echo" in offered) is not code_mode
        # The child's answer reaches the parent after its work, as a new input
        # right after the work's result.
        last = parent_requests[-1].messages
        [answer_index] = [
            index
            for index, message in enumerate(last)
            if isinstance(message, UserMessage) and "Child answer" in message.text
        ]
        previous = last[answer_index - 1]
        assert isinstance(previous, ToolResultMessage)
        assert previous.tool_call_id == "work"
        assert not any(
            "Child answer" in message.text for message in parent_requests[1].messages
        )
        # The saved steps rebuild the same order.
        rebuilt = messages_from_steps(run.snapshot().steps)
        [rebuilt_index] = [
            index
            for index, message in enumerate(rebuilt)
            if isinstance(message, UserMessage) and "Child answer" in message.text
        ]
        rebuilt_previous = rebuilt[rebuilt_index - 1]
        assert isinstance(rebuilt_previous, ToolResultMessage)
        assert rebuilt_previous.tool_call_id == "work"
        # The child sees its instruction, not the parent's conversation.
        assert len(child_requests) == 1
        assert all(
            message.text != user_message.text for message in child_requests[0].messages
        )
        info = child_info(owner, str(branch[0]))
        assert info.latest_run_id is not None
        db_session.expire_all()
        saved = db_session.get(ChatMessage, int(info.latest_run_id))
        assert saved is not None
        assert saved.response_status == RunStatus.COMPLETE
        assert saved.message == "Child answer"
    finally:
        release_child.set()
        assert coordinator.close(timeout=10)


def test_interrupt_stops_one_run_without_a_result_or_follow_up(
    branch: tuple[UUID, int],
    db_session: Session,
    user_message: UserMessage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = unpolled_store(branch)
    coordinator = AgentCoordinator()
    leaf_started = threading.Event()
    release_leaf = threading.Event()

    def agent_id(path: str) -> str:
        return next(info.id for info in owner.list_agents() if info.path == path)

    def leaf_reply(*_: object) -> AssistantMessage:
        leaf_started.set()
        assert release_leaf.wait(10)
        return text("Leaf evidence")

    def interrupt(call_id: str, target: str) -> ToolCall:
        return ToolCall(
            id=call_id, name="interrupt_agent", arguments={"agent_id": target}
        )

    child_calls = 0

    def child_reply(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        nonlocal child_calls
        child_calls += 1
        if child_calls > 1:
            return text("Evidence delegated")
        return calls(
            interrupt("root", str(branch[0])),
            interrupt("self", agent_id("/root/research")),
            spawn_call("leaf", "leaf", "Collect evidence"),
        )

    def create_child() -> Agent:
        return fake_agent(
            child_reply,
            tools=[
                SpawnAgentTool(lambda: fake_agent(leaf_reply), max_steps=3).bind(
                    ToolContext
                ),
                InterruptAgentTool().bind(ToolContext),
            ],
        )

    root_calls = 0

    def root_reply(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        nonlocal root_calls
        root_calls += 1
        if root_calls == 1:
            return calls(spawn_call("research", "research", "Research"))
        if root_calls == 2:
            assert leaf_started.wait(10)
            child = coordinator.run(
                next(
                    info.latest_run_id or ""
                    for info in owner.list_agents()
                    if info.path == "/root/research"
                )
            )
            assert child.wait_until_settled(10).status == RunStatus.SUSPENDED
            return calls(interrupt("interrupt", agent_id("/root/research")))
        return text("Done")

    root = fake_agent(
        root_reply,
        agent_id=str(branch[0]),
        tools=[
            SpawnAgentTool(create_child, max_steps=3).bind(ToolContext),
            InterruptAgentTool().bind(ToolContext),
        ],
    )
    view = owner.bind(coordinator, build_agent=never_restore("No restore expected"))
    try:
        run = root.start(messages=[user_message], max_steps=3, coordinator=view)
        assert run.result(timeout=15).output.text == "Done"
        result = run.snapshot().steps[1].tools["interrupt"].result
        assert result is not None
        assert result.text == "Interruption requested for /root/research."
        agents = {info.path: info for info in owner.list_agents()}
        child_run_id = agents["/root/research"].latest_run_id
        leaf_run_id = agents["/root/research/leaf"].latest_run_id
        assert child_run_id is not None and leaf_run_id is not None
        child = coordinator.completion(child_run_id).result(timeout=10)
        assert child.status == RunStatus.CANCELLED
        # The caller and the root cannot be interrupted.
        for call_id in ("root", "self"):
            rejected = child.steps[0].tools[call_id].result
            assert rejected is not None and rejected.is_error
        # The interrupt does not reach the agents below the child.
        assert not coordinator.run(leaf_run_id).status.is_terminal
        release_leaf.set()
        assert (
            coordinator.completion(leaf_run_id).result(timeout=10).status
            == RunStatus.COMPLETE
        )
        monkeypatch.setattr("onyx.chat.run_store.INPUT_POLL_SECONDS", 0)
        # One inbox scan after the leaf finishes wakes neither the child nor the root.
        with patch("onyx.db.chat_inputs.pending_inputs", wraps=pending_inputs) as scan:
            owner.poll_control()
        scan.assert_called_once()
        db_session.expire_all()
        results = {
            row.source_response_id: row.recipient_session_id
            for row in db_session.scalars(
                select(ChatInput).where(
                    ChatInput.source == InputSource.AGENT_RESULT,
                    ChatInput.root_response_id == branch[1],
                )
            )
        }
        # The interrupted run reports nothing; the leaf's result waits for its paused spawner.
        assert results == {int(leaf_run_id): UUID(agents["/root/research"].id)}
        assert assistant_count(db_session, UUID(agents["/root/research"].id)) == 1
        assert assistant_count(db_session, branch[0]) == 1
        assert queued_root_turn(db_session, branch[0]) is None
    finally:
        release_leaf.set()
        assert coordinator.close(timeout=10)


def test_agent_message_to_the_root_waits_for_its_next_run(
    branch: tuple[UUID, int],
    db_session: Session,
    user_message: UserMessage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = unpolled_store(branch)
    coordinator = AgentCoordinator()
    later_coordinator = AgentCoordinator()
    sent = threading.Event()
    release_child = threading.Event()
    child_calls = 0

    def child_reply(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        nonlocal child_calls
        child_calls += 1
        if child_calls == 1:
            return calls(
                ToolCall(
                    id="status",
                    name="send_message",
                    arguments={"agent_id": str(branch[0]), "message": "Halfway there"},
                )
            )
        sent.set()
        assert release_child.wait(10)
        return text("Finished")

    root = spawning_root(
        branch,
        lambda: fake_agent(
            child_reply, tools=[SendMessageTool(max_steps=2).bind(ToolContext)]
        ),
        name="research",
        instruction="Research",
        answer="Started",
    )
    view = owner.bind(coordinator, build_agent=never_restore("No restore expected"))
    try:
        first = root.start(messages=[user_message], max_steps=2, coordinator=view)
        assert first.result(timeout=10).output.text == "Started"
        assert first.wait_for_idle(timeout=10)
        assert sent.wait(10)
        child_id = next(
            info.id for info in owner.list_agents() if info.path == "/root/research"
        )
        monkeypatch.setattr("onyx.chat.run_store.INPUT_POLL_SECONDS", 0)
        # One inbox scan leaves the message in the root's inbox and starts no root response.
        with patch("onyx.db.chat_inputs.pending_inputs", wraps=pending_inputs) as scan:
            owner.poll_control()
        scan.assert_called_once()
        db_session.expire_all()
        assert [
            row.content
            for row in db_session.scalars(
                select(ChatInput).where(
                    ChatInput.recipient_session_id == branch[0],
                    ChatInput.source == InputSource.AGENT,
                )
            )
        ] == [
            f"Message from agent /root/research (agent_id: {child_id}):\nHalfway there"
        ]
        assert assistant_count(db_session, branch[0]) == 1
        assert queued_root_turn(db_session, branch[0]) is None

        later_question, later_response = add_turn(
            db_session, branch[0], branch[1], "Any news?"
        )
        later_owner = store(
            (branch[0], later_response.id), visible_response_ids=[branch[1]]
        )
        later_view = later_owner.bind(
            later_coordinator, build_agent=never_restore("No restore")
        )
        seen: list[str] = []

        def later_reply(
            request: GenerationRequest, _signal: CancellationSignal
        ) -> AssistantMessage:
            seen.extend(message.text for message in request.messages)
            return text("Noted")

        later = fake_agent(later_reply, agent_id=str(branch[0])).start(
            messages=[UserMessage(id=f"chat:{later_question.id}", content="Any news?")],
            max_steps=1,
            coordinator=later_view,
        )
        assert later.result(timeout=10).output.text == "Noted"
        assert any("Halfway there" in text for text in seen)
        [accepted] = later.snapshot().steps[0].input_messages
        assert isinstance(accepted.metadata, InputMessageMetadata)
        assert accepted.metadata.source == InputSource.AGENT
        db_session.expire_all()
        assert (
            db_session.scalar(
                select(func.count()).where(
                    ChatInput.recipient_session_id == branch[0],
                    ChatInput.source == InputSource.AGENT,
                )
            )
            == 0
        )
    finally:
        release_child.set()
        assert later_coordinator.close(timeout=10)
        assert coordinator.close(timeout=10)


def test_message_poll_retries_after_database_failure(
    branch: tuple[UUID, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("onyx.chat.run_store.INPUT_POLL_SECONDS", 0)
    owner = unpolled_store(branch)
    coordinator = AgentCoordinator()
    owner.bind(coordinator, build_agent=never_restore("Unexpected restoration"))
    # A chat without inbox rows has no child input to poll.
    with patch("onyx.db.chat_inputs.pending_inputs") as read:
        owner.poll_control()
        read.assert_not_called()
    assert not owner.has_owned_work
    owner._pending_dispatch = True
    with (
        patch("onyx.db.chat_inputs.has_chat_inputs", return_value=True),
        patch(
            "onyx.db.chat_inputs.pending_inputs",
            side_effect=OperationalError(
                "SELECT", {}, RuntimeError("connection unavailable")
            ),
        ),
    ):
        owner.poll_control()
        assert owner.has_owned_work
    with (
        patch("onyx.db.chat_inputs.has_chat_inputs", return_value=True),
        patch("onyx.db.chat_inputs.pending_inputs", wraps=pending_inputs) as read,
    ):
        owner.poll_control()
        read.assert_called_once()
    assert not owner.has_owned_work
    assert coordinator.close(timeout=10)


def test_message_submitted_during_empty_poll_starts_after_parent_releases(
    branch: tuple[UUID, int],
    db_session: Session,
    user_message: UserMessage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.chat.run_store.INPUT_POLL_SECONDS", 0)
    owner = unpolled_store(branch)
    coordinator = AgentCoordinator()
    view = owner.bind(coordinator, build_agent=never_restore("Unexpected restoration"))
    child_finished = threading.Event()
    submit_message = threading.Event()
    scan_started = threading.Event()
    finish_scan = threading.Event()
    child_messages: list[list[str]] = []
    spawned: list[SpawnResult] = []

    def child_reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        child_messages.append([message.text for message in request.messages])
        return text("Child answer")

    def delegate(invocation: ToolInvocation) -> ToolResult:
        child = invocation.agents.spawn_agent(
            fake_agent(child_reply),
            name="worker",
            description="Collect evidence",
            messages=[UserMessage(content="Initial task")],
            max_steps=1,
            restoration_config=ChatConfiguration(kind="chat"),
            lifetime=AgentLifetime.BACKGROUND,
        )
        spawned.append(child)
        assert (
            coordinator.completion(child.run_id).result(timeout=10).status
            == RunStatus.COMPLETE
        )
        child_finished.set()
        assert submit_message.wait(10)
        invocation.agents.send_message(
            child.agent_id,
            message="Follow up during scan",
            delivery=MessageDelivery.QUEUE,
            max_steps=1,
        )
        return ToolResult(content="Queued")

    root = delegating_root(
        branch, agent_tool("delegate", delegate), answer="Root answer"
    )
    run = root.start(messages=[user_message], max_steps=2, coordinator=view)

    def read_then_wait(
        session: Session, selected_branch: ChatBranch, agent_id: str | None = None
    ) -> list[ChatInput]:
        rows = pending_inputs(session, selected_branch, agent_id)
        assert not rows
        scan_started.set()
        assert finish_scan.wait(10)
        return rows

    try:
        assert child_finished.wait(10)
        # The inbox is still empty, so the scan passes its inbox check only here.
        with (
            patch("onyx.db.chat_inputs.has_chat_inputs", return_value=True),
            patch("onyx.db.chat_inputs.pending_inputs", side_effect=read_then_wait),
        ):
            polling = start_thread_future(
                lambda: owner.poll_control(), name="test-message-poll"
            )
            try:
                assert scan_started.wait(10)
                submit_message.set()
                assert run.result(timeout=10).output.text == "Root answer"
                assert run.wait_for_idle(timeout=10)
                coordinator.completion(run.id).result(timeout=10)
            finally:
                finish_scan.set()
                polling.result(timeout=10)
        assert owner.has_owned_work
        owner.poll_control()
        child = next(
            info for info in view.discover_agents() if info.id == spawned[0].agent_id
        )
        assert child.latest_run_id is not None
        assert child.latest_run_id != spawned[0].run_id
        assert (
            coordinator.completion(child.latest_run_id).result(timeout=10).status
            == RunStatus.COMPLETE
        )
        assert len(child_messages) == 2
        assert "Follow up during scan" in child_messages[1]
        assert pending_agent_messages(db_session, child.id) == 0
        responses = list(
            db_session.scalars(
                select(ChatMessage.id).where(
                    ChatMessage.chat_session_id == UUID(child.id),
                    ChatMessage.message_type == MessageType.ASSISTANT,
                )
            )
        )
        assert set(responses) == {int(spawned[0].run_id), int(child.latest_run_id)}
    finally:
        submit_message.set()
        finish_scan.set()
        assert coordinator.close(timeout=10)


def test_results_follow_up_restores_through_the_spawner_after_another_sender(
    branch: tuple[UUID, int],
    db_session: Session,
    user_message: UserMessage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """root spawns A, A spawns B, B queues work for A, and A's queued run spawns C.

    A's latest run was started by B, not by its spawner root, so its follow-up
    must still restore A through the root.
    """
    owner = store(branch)
    coordinator = AgentCoordinator()

    def agent_info(path: str) -> AgentInfo:
        for _ in range(500):
            info = next(
                (info for info in owner.list_agents() if info.path == path), None
            )
            if info is not None and info.latest_run_id is not None:
                return info
            threading.Event().wait(0.02)
        pytest.fail(f"{path} did not start")

    def spawn(name: str) -> AssistantMessage:
        return calls(spawn_call(name, name, f"Work as {name}"))

    def received(request: GenerationRequest, content: str) -> bool:
        return any(
            isinstance(message, UserMessage) and content in message.text
            for message in request.messages
        )

    def worker_reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if received(request, "Work as evidence"):
            return text("C evidence")
        if any(isinstance(message, ToolResultMessage) for message in request.messages):
            return text("B done")
        return calls(
            ToolCall(
                id="queue-research",
                name="send_message",
                arguments={
                    "agent_id": agent_info("/root/research").id,
                    "message": "Use C",
                    "delivery": "queue",
                },
            )
        )

    def worker_agent() -> Agent:
        return fake_agent(
            worker_reply, tools=[SendMessageTool(max_steps=3).bind(ToolContext)]
        )

    def spawned(request: GenerationRequest, name: str) -> bool:
        return any(
            isinstance(message, ToolResultMessage) and message.tool_call_id == name
            for message in request.messages
        )

    def research_reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        # A waits for each child's result instead of starting another child.
        if received(request, "C evidence"):
            return text("A used evidence")
        if received(request, "Use C"):
            return (
                text("Waiting for C")
                if spawned(request, "evidence")
                else spawn("evidence")
            )
        if received(request, "B done"):
            return text("A done")
        return text("Waiting for B") if spawned(request, "leaf") else spawn("leaf")

    def research_agent() -> Agent:
        return fake_agent(
            research_reply,
            tools=[SpawnAgentTool(worker_agent, max_steps=3).bind(ToolContext)],
        )

    root = spawning_root(
        branch,
        research_agent,
        name="research",
        instruction="Work as research",
        answer="Root done",
    )
    view = owner.bind(coordinator, build_agent=never_restore("No restore"))
    monkeypatch.setattr("onyx.chat.run_store.INPUT_POLL_SECONDS", 0)
    try:
        run = root.start(messages=[user_message], max_steps=3, coordinator=view)
        assert run.result(timeout=15).output.text == "Root done"
        evidence = agent_info("/root/research/evidence")
        worker = agent_info("/root/research/leaf")
        assert evidence.latest_run_id is not None and worker.latest_run_id is not None
        message_run_id = evidence.latest_run_id
        for _ in range(500):
            research = agent_info("/root/research")
            assert research.latest_run_id is not None
            state = coordinator.completion(research.latest_run_id).result(10)
            if state.messages[-1].text == "A used evidence":
                message_run_id = research.latest_run_id
                break
            threading.Event().wait(0.02)
        assert coordinator.run(message_run_id).wait_for_idle(timeout=10)
        # The queued run answered under B's invocation, not its spawner's.
        sender_run_id = coordinator.completion(message_run_id).result(0).parent_run_id
        assert sender_run_id is not None
        assert coordinator.completion(sender_run_id).result(10).agent_id == worker.id
        # A late unread result for A wakes it while its sender B is idle.
        db_session.add(
            ChatInput(
                recipient_session_id=UUID(research.id),
                message_id=f"{AGENT_RESULT_MESSAGE_PREFIX}{evidence.latest_run_id}",
                source=InputSource.AGENT_RESULT,
                source_response_id=int(evidence.latest_run_id),
                root_response_id=branch[1],
                content="",
            )
        )
        db_session.commit()
        follow_up_id = message_run_id
        for _ in range(500):
            owner.poll_control()
            follow_up_id = agent_info("/root/research").latest_run_id
            if follow_up_id != message_run_id:
                break
            threading.Event().wait(0.02)
        assert follow_up_id is not None and follow_up_id != message_run_id
        follow_up = coordinator.completion(follow_up_id).result(timeout=10)
        assert follow_up.status == RunStatus.COMPLETE
        assert follow_up.failure is None
        [accepted] = follow_up.steps[0].input_messages
        assert accepted.id == f"{AGENT_RESULT_MESSAGE_PREFIX}{evidence.latest_run_id}"
    finally:
        assert coordinator.close(timeout=10)


def test_a_reserved_child_run_is_its_agents_latest_run(
    branch: tuple[UUID, int], user_message: UserMessage
) -> None:
    """From reservation on, a spawned run is the agent's running latest run.

    Another start for that agent sees it, so the agent never gets two runs.
    """
    owner = unpolled_store(branch)
    coordinator = AgentCoordinator()
    reserved: list[tuple[int, RunStatus | None] | None] = []
    register = owner.register

    def check_reservation(run: Run) -> None:
        if run.id != str(branch[1]):
            with get_session_with_tenant(
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
            ) as session:
                latest = latest_agent_response(
                    session,
                    ChatBranch(chat_session_id=branch[0], message_ids=[branch[1]]),
                    run.agent_id,
                )
                reserved.append(
                    (latest.id, latest.response_status) if latest is not None else None
                )
        register(run)

    root = spawning_root(
        branch,
        lambda: fake_agent(answering("Child answer")),
        name="worker",
        instruction="Task",
        answer="Started",
    )
    view = owner.bind(coordinator, build_agent=never_restore("No restore expected"))
    try:
        with patch.object(owner, "register", side_effect=check_reservation):
            run = root.start(messages=[user_message], max_steps=3, coordinator=view)
            assert run.result(timeout=10).output.text == "Started"
        child = child_info(owner, str(branch[0]))
        assert child.latest_run_id is not None
        assert reserved == [(int(child.latest_run_id), RunStatus.RUNNING)]
        coordinator.completion(child.latest_run_id).result(timeout=10)
    finally:
        assert coordinator.close(timeout=10)


def test_spawning_stops_at_the_running_agent_cap(
    branch: tuple[UUID, int], user_message: UserMessage
) -> None:
    """A chat runs at most the capped number of agents at a time."""
    owner = unpolled_store(branch)
    coordinator = AgentCoordinator()
    release = threading.Event()

    def blocked(*_: object) -> AssistantMessage:
        assert release.wait(30)
        return text("Done")

    spawns = [
        spawn_call(f"spawn-{index}", f"agent{index}", "Task")
        for index in range(run_store.MAX_RUNNING_AGENTS + 1)
    ]
    root = fake_agent(
        replies(calls(*spawns), text("Started")),
        agent_id=str(branch[0]),
        tools=[
            SpawnAgentTool(lambda: fake_agent(blocked), max_steps=2).bind(ToolContext)
        ],
    )
    view = owner.bind(coordinator, build_agent=never_restore("No restore expected"))
    try:
        run = root.start(messages=[user_message], max_steps=2, coordinator=view)
        assert run.result(timeout=30).output.text == "Started"
        results = [run.snapshot().steps[0].tools[spawn.id].result for spawn in spawns]
        refused = [
            result for result in results if result is not None and result.is_error
        ]
        assert len(refused) == 1
        assert (
            f"{run_store.MAX_RUNNING_AGENTS} agents are already running"
            in refused[0].text
        )
    finally:
        release.set()
        assert coordinator.close(timeout=30)


def test_spawn_takes_the_chat_lock_before_its_parent_response(
    branch: tuple[UUID, int], user_message: UserMessage
) -> None:
    """A spawn and a user's send to the spawning response lock in one order."""
    owner = unpolled_store(branch)
    coordinator = AgentCoordinator()
    release = threading.Event()
    spawn_locking = threading.Event()
    original_lock = run_store.lock_agent

    def signal_lock(session: Session, agent_id: str) -> ChatSession:
        spawn_locking.set()
        return original_lock(session, agent_id)

    def blocked(*_: object) -> AssistantMessage:
        assert release.wait(30)
        return text("Done")

    root = spawning_root(
        branch,
        lambda: fake_agent(blocked),
        name="worker",
        instruction="Task",
        answer="Started",
    )
    view = owner.bind(coordinator, build_agent=never_restore("No restore expected"))
    try:
        with (
            get_session_with_tenant(
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
            ) as sending,
            patch.object(run_store, "lock_agent", side_effect=signal_lock),
        ):
            # The user's send holds the chat lock while the spawn starts.
            lock_agent(sending, str(branch[0]))
            run = root.start(messages=[user_message], max_steps=3, coordinator=view)
            assert spawn_locking.wait(10)
            pending = submit_human_message__no_commit(
                sending,
                branch[0],
                message="Steer",
                delivery=MessageDelivery.SEND,
                target_response_id=branch[1],
                turn_preparing=False,
            )
            assert pending.target_response_id == branch[1]
            sending.commit()
            assert run.result(timeout=30).output.text == "Started"
        spawned = run.snapshot().steps[0].tools["worker"].result
        assert spawned is not None and not spawned.is_error
    finally:
        release.set()
        assert coordinator.close(timeout=30)


def test_a_stopped_parent_cannot_start_an_agent(
    branch: tuple[UUID, int], user_message: UserMessage
) -> None:
    """A spawn checks its parent's Stop under the parent's ownership lock."""
    owner = unpolled_store(branch)
    coordinator = AgentCoordinator()
    root = spawning_root(
        branch,
        lambda: fake_agent(lambda *_: text("Done")),
        name="worker",
        instruction="Task",
        answer="Started",
    )
    view = owner.bind(coordinator, build_agent=never_restore("No restore expected"))
    # The Stop arrives before the parent's control poll cancels it.
    run_store.request_response_stop(owner.cache, branch[1], "user")
    try:
        run = root.start(messages=[user_message], max_steps=3, coordinator=view)
        assert run.result(timeout=30).output.text == "Started"
        spawned = run.snapshot().steps[0].tools["worker"].result
        assert spawned is not None and spawned.is_error
        assert "stopped" in spawned.content
    finally:
        owner.cache.delete(f"chat_response_stop:{branch[1]}")
        assert coordinator.close(timeout=30)


def test_a_stopped_sender_cannot_queue_agent_work(
    branch: tuple[UUID, int], db_session: Session, user_message: UserMessage
) -> None:
    """A send checks its sender's Stop under the chat lock that Stop holds."""
    owner = unpolled_store(branch)
    coordinator = AgentCoordinator()
    view = owner.bind(coordinator, build_agent=never_restore("No restore expected"))
    spawned: list[SpawnResult] = []
    refused: list[str] = []

    def delegate(invocation: ToolInvocation) -> ToolResult:
        child = invocation.agents.spawn_agent(
            fake_agent(lambda *_: text("Child answer")),
            name="worker",
            description="Collect evidence",
            messages=[UserMessage(content="Initial task")],
            max_steps=1,
            restoration_config=ChatConfiguration(kind="chat"),
            lifetime=AgentLifetime.BACKGROUND,
        )
        spawned.append(child)
        coordinator.completion(child.run_id).result(timeout=10)
        # Stop subagents dropped pending work before this send reached the inbox.
        run_store.request_response_stop(owner.cache, branch[1], "user")
        try:
            invocation.agents.send_message(
                child.agent_id,
                message="Follow up",
                delivery=MessageDelivery.QUEUE,
                max_steps=1,
            )
        except ValueError as error:
            refused.append(str(error))
        return ToolResult(content="Done")

    root = delegating_root(
        branch, agent_tool("delegate", delegate), answer="Root answer"
    )
    try:
        run = root.start(messages=[user_message], max_steps=2, coordinator=view)
        run.result(timeout=30)
        assert refused and "stopped" in refused[0]
        assert pending_agent_messages(db_session, spawned[0].agent_id) == 0
    finally:
        owner.cache.delete(f"chat_response_stop:{branch[1]}")
        assert coordinator.close(timeout=30)


def test_inbox_work_waits_while_the_branch_runs_the_agent_cap(
    branch: tuple[UUID, int],
    db_session: Session,
    user_message: UserMessage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An idle agent's inbox run counts against the cap and starts once a slot frees."""
    monkeypatch.setattr("onyx.chat.run_store.INPUT_POLL_SECONDS", 0)
    owner = unpolled_store(branch)
    coordinator = AgentCoordinator()
    view = owner.bind(coordinator, build_agent=never_restore("Unexpected restoration"))
    child_messages: list[list[str]] = []
    spawned: list[SpawnResult] = []

    def child_reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        child_messages.append([message.text for message in request.messages])
        return text("Child answer")

    def delegate(invocation: ToolInvocation) -> ToolResult:
        child = invocation.agents.spawn_agent(
            fake_agent(child_reply),
            name="worker",
            description="Collect evidence",
            messages=[UserMessage(content="Initial task")],
            max_steps=1,
            restoration_config=ChatConfiguration(kind="chat"),
            lifetime=AgentLifetime.BACKGROUND,
        )
        spawned.append(child)
        coordinator.completion(child.run_id).result(timeout=10)
        invocation.agents.send_message(
            child.agent_id,
            message="Follow up",
            delivery=MessageDelivery.QUEUE,
            max_steps=1,
        )
        return ToolResult(content="Queued")

    root = delegating_root(
        branch, agent_tool("delegate", delegate), answer="Root answer"
    )
    try:
        run = root.start(messages=[user_message], max_steps=2, coordinator=view)
        assert run.result(timeout=10).output.text == "Root answer"
        assert run.wait_for_idle(timeout=10)
        coordinator.completion(run.id).result(timeout=10)
        with patch(
            "onyx.chat.run_store.active_agent_response_ids",
            return_value=list(range(run_store.MAX_RUNNING_AGENTS)),
        ):
            owner.poll_control()
        child = next(
            info for info in view.discover_agents() if info.id == spawned[0].agent_id
        )
        assert child.latest_run_id == spawned[0].run_id
        assert pending_agent_messages(db_session, child.id) == 1
        assert owner.has_owned_work
        owner.poll_control()
        child = next(
            info for info in view.discover_agents() if info.id == spawned[0].agent_id
        )
        assert child.latest_run_id is not None
        assert child.latest_run_id != spawned[0].run_id
        assert (
            coordinator.completion(child.latest_run_id).result(timeout=10).status
            == RunStatus.COMPLETE
        )
        assert "Follow up" in child_messages[1]
    finally:
        assert coordinator.close(timeout=10)


def test_runs_that_agents_start_check_the_token_rate_limit(
    branch: tuple[UUID, int], db_session: Session, user_message: UserMessage
) -> None:
    """A run an agent starts counts against the chat owner's limits."""
    owner = unpolled_store(branch)
    coordinator = AgentCoordinator()
    checks = 0

    def limit(_user: User) -> None:
        nonlocal checks
        checks += 1
        raise OnyxError(OnyxErrorCode.RATE_LIMITED, "Usage budget reached")

    root = spawning_root(
        branch,
        lambda: fake_agent(answering("Child answer")),
        name="worker",
        instruction="Task",
        answer="Started",
    )
    view = owner.bind(coordinator, build_agent=never_restore("No restore expected"))
    try:
        with patch("onyx.chat.run_store.check_token_rate_limits", side_effect=limit):
            run = root.start(messages=[user_message], max_steps=3, coordinator=view)
            assert run.result(timeout=10).output.text == "Started"
        spawned = run.snapshot().steps[0].tools["worker"].result
        assert spawned is not None and spawned.is_error
        assert "Usage budget reached" in spawned.text
        # The root turn checked its limits when it was sent.
        assert checks == 1
        db_session.expire_all()
        assert (
            db_session.scalar(
                select(func.count()).where(
                    ChatSession.spawned_by_message_id == branch[1]
                )
            )
            == 0
        )
    finally:
        assert coordinator.close(timeout=10)
