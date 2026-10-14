"""Safe response transfer uses canonical history and one conditional resume owner."""

import subprocess
import sys
import threading
from collections.abc import Generator
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.agents.agent_coordination import AgentCoordinator, RunStore
from onyx.agents.execution_records import CompactionCheckpoint, RunStatus
from onyx.agents.models import (
    AgentState,
    ExecutionCheckpoint,
    RunProgress,
    RunState,
)
from onyx.agents.runtime import Agent
from onyx.agents.tools import (
    AgentLifetime,
    AgentTool,
    HumanToolAnswer,
    InputDecision,
    InputMode,
    PendingToolInput,
    ToolInvocation,
)
from onyx.cache.factory import get_cache_backend
from onyx.chat.agent import ChatAgent
from onyx.chat.checkpoint import _checkpoint_model_types
from onyx.chat.history_store import get_chat_history_store
from onyx.chat.models import ChatFeatureState, CheckpointBinding
from onyx.chat.presentation import project_response
from onyx.chat.restoration import persist_checkpoint_files
from onyx.chat.run_store import ChatRunStore
from onyx.configs.constants import FileOrigin, MessageType
from onyx.db.chat import delete_messages_and_files_from_chat_session, root_response_id
from onyx.db.chat_checkpoint import (
    check_checkpoint_owner__no_commit,
    claim_checkpoint__no_commit,
    release_checkpoint_claim__no_commit,
)
from onyx.db.engine.sql_engine import SqlEngine, get_session_with_tenant
from onyx.db.models import ChatMessage, ChatResponseCheckpoint, ChatSession
from onyx.file_store.models import ExtractedContextFiles
from onyx.file_store.postgres_file_store import PostgresBackedFileStore
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolDefinition,
    ToolResult,
    UserMessage,
)
from onyx.tools.models import ChatFile, FileReadResult
from onyx.utils.threadpool_concurrency import start_thread_future
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.unit.onyx.agents.checkpoint_storage import CheckpointStorage
from tests.unit.onyx.agents.fakes import (
    FakeAgentDirectory,
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


def store(
    branch: tuple[UUID, int],
    *,
    root_response: RunStore | None = None,
    visible_response_ids: list[int] | None = None,
) -> ChatRunStore:
    return ChatRunStore(
        root_response=root_response,
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        chat_session_id=branch[0],
        response_id=branch[1],
        visible_response_ids=visible_response_ids or [],
        cache=get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE),
    )


@pytest.fixture(autouse=True)
def poll_run_owners(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    stores: list[ChatRunStore] = []
    lock = threading.Lock()
    finished = threading.Event()
    create_store = store

    def registered_store(
        branch: tuple[UUID, int],
        *,
        root_response: RunStore | None = None,
        visible_response_ids: list[int] | None = None,
    ) -> ChatRunStore:
        created = create_store(
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
            UserMessage(id="earlier-question", content="earlier question")
        ]
        context.checkpoint = CompactionCheckpoint(
            summary="earlier context",
            covered_through_message_id="earlier-question",
        )
    calls: list[str] = []
    finalized: list[str] = []

    def execute(invocation: ToolInvocation) -> ToolResult | PendingToolInput:
        calls.append(invocation.call_id)
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

    tools = [
        AgentTool(
            definition=ToolDefinition(name="search", description="", parameters={}),
            execute=execute,
        ),
        AgentTool(
            definition=ToolDefinition(name="ask", description="", parameters={}),
            execute=execute,
        ),
    ]

    def rebuild(checkpoint: ExecutionCheckpoint) -> Agent:
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
        return Agent(
            FakeModelClient(
                lambda *_: AssistantMessage(content=[TextContent(text="done")])
            ),
            agent_id=checkpoint.run_state.agent_id,
            state=checkpoint.agent_state,
            tools=tools,
            after_tool_call=lambda call, result: (
                finalized.append(call.call.id) or result
            ),
        )

    coordinator = owner.bind(
        first,
        directory=FakeAgentDirectory(
            lookup_agent=owner.lookup_agent,
            read_run=owner.read_run,
            read_run_status=owner.read_run_status,
            cancel_run=owner.cancel_run,
        ),
        build_agent=rebuild,
    )
    remote.bind(
        second,
        directory=FakeAgentDirectory(
            lookup_agent=remote.lookup_agent,
            read_run=remote.read_run,
            read_run_status=remote.read_run_status,
            cancel_run=remote.cancel_run,
        ),
        build_agent=rebuild,
    )
    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[
                    ToolCall(id="search", name="search", arguments={}),
                    ToolCall(id="question", name="ask", arguments={}),
                ]
            )
        ),
        agent_id=str(branch[0]),
        state=context,
        tools=tools,
        after_tool_call=lambda call, result: finalized.append(call.call.id) or result,
    )
    run = agent.start(messages=[user_message], max_steps=2, coordinator=coordinator)
    try:
        assert run.wait_until_settled(timeout=10).status == RunStatus.SUSPENDED
        assert run.wait_for_idle(timeout=10)
        if scenario == "release":
            with patch.object(
                owner.cache, "delete", side_effect=RuntimeError("cache unavailable")
            ):
                with pytest.raises(RuntimeError, match="cache unavailable"):
                    owner.handoff(run.id)
            assert remote.resume(run.id, context=context) is None
            owner.cache.delete(owner._owner_key(int(run.id)))
        elif scenario == "ownership_lock":
            with owner._ownership_lock(int(run.id)):
                threading.Event().wait(1.5)
                assert owner.cache.exists(owner._owner_key(int(run.id)))
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
            owner.handoff(run.id)
        assert coordinator.active_run(agent.id) is None
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
        assert sorted(calls) == ["question", "search"]
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
        return Agent(
            FakeModelClient(
                lambda *_: AssistantMessage(content=[TextContent(text="done")])
            ),
            agent_id=checkpoint.run_state.agent_id,
            state=checkpoint.agent_state,
            tools=[
                AgentTool(
                    definition=ToolDefinition(name=name, description="", parameters={}),
                    execute=unexpected_tool,
                )
                for name in ("search", "ask")
            ],
        )

    remote.bind(
        coordinator,
        directory=FakeAgentDirectory(
            lookup_agent=remote.lookup_agent,
            read_run=remote.read_run,
            read_run_status=remote.read_run_status,
            cancel_run=remote.cancel_run,
        ),
        build_agent=rebuild,
    )
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

    def unexpected_resume(_: ExecutionCheckpoint) -> Agent:
        raise RuntimeError("Transfer must fail before reconstruction")

    view = owner.bind(
        coordinator,
        directory=FakeAgentDirectory(
            lookup_agent=owner.lookup_agent,
            read_run=owner.read_run,
            read_run_status=owner.read_run_status,
            cancel_run=owner.cancel_run,
        ),
        build_agent=unexpected_resume,
    )
    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="question", name="ask", arguments={})]
            )
        ),
        agent_id=str(branch[0]),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="ask", description="", parameters={}),
                execute=lambda _: PendingToolInput(
                    request_id="answer", prompt="Which file?", mode=InputMode.RESULT
                ),
            )
        ],
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
    tool = AgentTool(
        definition=ToolDefinition(name="ask", description="", parameters={}),
        execute=lambda _: PendingToolInput(
            request_id="answer", prompt="Which file?", mode=InputMode.RESULT
        ),
    )

    def unexpected_resume(_: ExecutionCheckpoint) -> Agent:
        raise RuntimeError("This test claims the checkpoint without starting a run")

    view = owner.bind(
        coordinator,
        directory=FakeAgentDirectory(
            lookup_agent=owner.lookup_agent,
            read_run=owner.read_run,
            read_run_status=owner.read_run_status,
            cancel_run=owner.cancel_run,
        ),
        build_agent=unexpected_resume,
    )
    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="question", name="ask", arguments={})]
            )
        ),
        tools=[tool],
        agent_id=str(branch[0]),
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
                "onyx.tools.file_snapshot.get_default_file_store",
                return_value=file_store,
            ),
            patch("onyx.db.chat.get_default_file_store", return_value=file_store),
            patch.object(file_store, "read_file", wraps=file_store.read_file) as reads,
            patch.object(file_store, "save_file", wraps=file_store.save_file) as saves,
        ):
            feature = ChatAgent(
                messages=[],
                tools=[],
                custom_agent_prompt=None,
                base_system_prompt="Help",
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
                llm=FakeModelClient(
                    lambda *_: AssistantMessage(content=[TextContent(text="done")])
                ),
                token_counter=len,
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
                        step_limit=2, feature_state=feature.capture_state()
                    ),
                ),
            )
            persist_checkpoint_files(captured, session_id=branch[0])
            persist_checkpoint_files(captured, session_id=branch[0])
            reads.assert_not_called()
            assert saves.call_count == 1
            codec = CheckpointStorage(_checkpoint_model_types())
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
            state = restored.run_state.progress.feature_state
            assert isinstance(state, ChatFeatureState)
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

    def unexpected_restore(_: ExecutionCheckpoint) -> Agent:
        raise AssertionError("This response does not suspend")

    view = owner.bind(
        coordinator,
        directory=FakeAgentDirectory(
            lookup_agent=owner.lookup_agent,
            read_run=owner.read_run,
            read_run_status=owner.read_run_status,
            cancel_run=owner.cancel_run,
        ),
        build_agent=unexpected_restore,
    )
    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="done")])
        ),
        agent_id=str(branch[0]),
    )
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
        owner.cache.delete(owner._owner_key(int(run.id)))
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

    def unexpected_restore(_: ExecutionCheckpoint) -> Agent:
        raise AssertionError("This response does not suspend")

    owner = store(branch)
    coordinator = AgentCoordinator()
    view = owner.bind(
        coordinator,
        directory=FakeAgentDirectory(
            lookup_agent=owner.lookup_agent,
            read_run=owner.read_run,
            read_run_status=owner.read_run_status,
            cancel_run=owner.cancel_run,
        ),
        build_agent=unexpected_restore,
    )
    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="slow", name="slow", arguments={})]
            )
        ),
        agent_id=str(branch[0]),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="slow", description="", parameters={}),
                execute=tool,
            )
        ],
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

    def unexpected_restore(_: ExecutionCheckpoint) -> Agent:
        raise RuntimeError("Completed children do not require restoration")

    view = owner.bind(
        coordinator,
        directory=FakeAgentDirectory(
            lookup_agent=owner.lookup_agent,
            read_run=owner.read_run,
            read_run_status=owner.read_run_status,
            cancel_run=owner.cancel_run,
        ),
        build_agent=unexpected_restore,
    )

    def delegate(invocation: ToolInvocation) -> ToolResult:
        def child_reply(
            _request: GenerationRequest, _cancellation: CancellationSignal
        ) -> AssistantMessage:
            child_barrier.wait(timeout=10)
            return AssistantMessage(content=[TextContent(text=invocation.call_id)])

        spawned = invocation.agents.spawn_agent(
            Agent(FakeModelClient(child_reply)),
            name=invocation.call_id,
            description="Parallel research",
            messages=[UserMessage(content=invocation.call_id)],
            max_steps=1,
        )
        result = invocation.agents.wait_run(spawned.run_id, timeout=10)
        assert result is not None
        return ToolResult(content=result.output.text)

    replies = iter(
        [
            AssistantMessage(
                content=[
                    ToolCall(id="first", name="delegate", arguments={}),
                    ToolCall(id="second", name="delegate", arguments={}),
                ]
            ),
            AssistantMessage(content=[TextContent(text="done")]),
        ]
    )
    agent = Agent(
        FakeModelClient(lambda *_: next(replies)),
        agent_id=str(branch[0]),
        tools=[
            AgentTool(
                definition=ToolDefinition(
                    name="delegate", description="", parameters={}
                ),
                execute=delegate,
            )
        ],
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


@pytest.mark.parametrize("existing_child", [False, True])
@pytest.mark.parametrize("failure_point", ["bind", "worker", "owner_publication"])
def test_failed_child_start_can_retry_without_an_orphan_response(
    branch: tuple[UUID, int],
    db_session: Session,
    user_message: UserMessage,
    existing_child: bool,
    failure_point: str,
) -> None:
    owner = store(branch)
    coordinator = AgentCoordinator()

    def unexpected_restore(_: ExecutionCheckpoint) -> Agent:
        raise RuntimeError("Child remains loaded during this test")

    view = owner.bind(
        coordinator,
        directory=FakeAgentDirectory(
            lookup_agent=owner.lookup_agent,
            read_run=owner.read_run,
            read_run_status=owner.read_run_status,
            cancel_run=owner.cancel_run,
        ),
        build_agent=unexpected_restore,
    )
    child = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="child answer")])
        )
    )

    def delegate(invocation: ToolInvocation) -> ToolResult:
        def start_child() -> str:
            if existing_child:
                return invocation.agents.start_run(
                    child.id,
                    messages=[UserMessage(content="next request")],
                    max_steps=1,
                )
            return invocation.agents.spawn_agent(
                child,
                name="research",
                description="Research",
                messages=[UserMessage(content="first request")],
                max_steps=1,
            ).run_id

        if existing_child:
            first = invocation.agents.spawn_agent(
                child,
                name="research",
                description="Research",
                messages=[UserMessage(content="first request")],
                max_steps=1,
            )
            assert invocation.agents.wait_run(first.run_id, timeout=10) is not None

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
            assert (
                session.get(ChatSession, UUID(child.id)) is not None
            ) == existing_child
            parent_response = session.get(ChatMessage, branch[1])
            assert parent_response is not None
            assert parent_response.response_status == RunStatus.RUNNING
        retried_id = start_child()
        completed = invocation.agents.wait_run(retried_id, timeout=10)
        assert completed is not None
        return ToolResult(content=completed.output.text)

    replies = iter(
        [
            AssistantMessage(
                content=[ToolCall(id="delegate", name="delegate", arguments={})]
            ),
            AssistantMessage(content=[TextContent(text="done")]),
        ]
    )
    agent = Agent(
        FakeModelClient(lambda *_: next(replies)),
        agent_id=str(branch[0]),
        tools=[
            AgentTool(
                definition=ToolDefinition(
                    name="delegate", description="", parameters={}
                ),
                execute=delegate,
            )
        ],
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
        assert len(responses) == len(questions) == (2 if existing_child else 1)
        assert all(row.response_status == RunStatus.COMPLETE for row in responses)
        assert questions[0].parent_message_id is None
        if existing_child:
            assert questions[1].parent_message_id == responses[0].id
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

    def unexpected_restore(_: ExecutionCheckpoint) -> Agent:
        raise RuntimeError("Retry starts a fresh execution")

    view = owner.bind(
        coordinator,
        directory=FakeAgentDirectory(
            lookup_agent=owner.lookup_agent,
            read_run=owner.read_run,
            read_run_status=owner.read_run_status,
            cancel_run=owner.cancel_run,
        ),
        build_agent=unexpected_restore,
    )
    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="done")])
        ),
        agent_id=str(branch[0]),
    )
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
    ask = AgentTool(
        definition=ToolDefinition(name="ask", description="", parameters={}),
        execute=lambda _: PendingToolInput(
            request_id="answer", prompt="Continue?", mode=InputMode.RESULT
        ),
    )

    def nested_delegate(invocation: ToolInvocation) -> ToolResult:
        spawned = invocation.agents.spawn_agent(
            Agent(
                FakeModelClient(
                    lambda *_: AssistantMessage(content=[TextContent(text="facts")])
                )
            ),
            name="facts",
            description="Nested research",
            messages=[UserMessage(content="Find facts")],
            max_steps=1,
        )
        grandchild_ids.append(spawned.run_id)
        result = invocation.agents.wait_run(spawned.run_id, timeout=10)
        assert result is not None
        return ToolResult(content=result.output.text)

    def rebuild(checkpoint: ExecutionCheckpoint) -> Agent:
        replies = iter(
            [
                AssistantMessage(
                    content=[ToolCall(id="nested", name="delegate", arguments={})]
                ),
                AssistantMessage(content=[TextContent(text="child done")]),
            ]
        )
        return Agent(
            FakeModelClient(lambda *_: next(replies)),
            agent_id=checkpoint.run_state.agent_id,
            state=checkpoint.agent_state,
            tools=[
                ask,
                AgentTool(
                    definition=ToolDefinition(
                        name="delegate", description="", parameters={}
                    ),
                    execute=nested_delegate,
                ),
            ],
        )

    view = owner.bind(
        first,
        directory=FakeAgentDirectory(
            lookup_agent=owner.lookup_agent,
            read_run=owner.read_run,
            read_run_status=owner.read_run_status,
            cancel_run=owner.cancel_run,
        ),
        build_agent=rebuild,
    )

    def delegate(invocation: ToolInvocation) -> ToolResult:
        child = invocation.agents.spawn_agent(
            Agent(
                FakeModelClient(
                    lambda *_: AssistantMessage(
                        content=[ToolCall(id="ask", name="ask", arguments={})]
                    )
                ),
                tools=[ask],
            ),
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

    replies = iter(
        [
            AssistantMessage(
                content=[ToolCall(id="delegate", name="delegate", arguments={})]
            ),
            AssistantMessage(content=[TextContent(text="parent done")]),
        ]
    )
    agent = Agent(
        FakeModelClient(lambda *_: next(replies)),
        agent_id=str(branch[0]),
        tools=[
            AgentTool(
                definition=ToolDefinition(
                    name="delegate", description="", parameters={}
                ),
                execute=delegate,
            )
        ],
    )
    try:
        root = agent.start(messages=[user_message], max_steps=2, coordinator=view)
        assert root.result(timeout=20).output.text == "parent done"
        assert root.wait_for_idle(timeout=10)
        original = db_session.get(ChatMessage, branch[1])
        assert original is not None
        next_question = ChatMessage(
            chat_session_id=branch[0],
            parent_message_id=original.id,
            message="next",
            token_count=1,
            message_type=MessageType.USER,
        )
        db_session.add(next_question)
        db_session.flush()
        next_response = ChatMessage(
            chat_session_id=branch[0],
            parent_message_id=next_question.id,
            message="",
            token_count=0,
            message_type=MessageType.ASSISTANT,
        )
        sibling = ChatMessage(
            chat_session_id=branch[0],
            parent_message_id=original.parent_message_id,
            message="",
            token_count=0,
            message_type=MessageType.ASSISTANT,
        )
        db_session.add_all([next_response, sibling])
        db_session.commit()
        remote = store(
            (branch[0], next_response.id), visible_response_ids=[original.id]
        )
        remote.bind(
            second,
            directory=FakeAgentDirectory(
                lookup_agent=remote.lookup_agent,
                read_run=remote.read_run,
                read_run_status=remote.read_run_status,
                cancel_run=remote.cancel_run,
            ),
            build_agent=rebuild,
        )
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
