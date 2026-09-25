"""Persistence projects canonical output without waiting for stream observers."""

import threading
from collections.abc import Callable, Generator
from concurrent.futures import Future
from unittest.mock import patch
from uuid import uuid4

import pytest

from onyx.agents.events import AgentEvent, MessageEndEvent
from onyx.agents.execution_records import OperationSnapshot, RunStatus
from onyx.agents.models import AgentInfo, PreparedStep, RunState
from onyx.agents.runtime import Agent, Run
from onyx.chat.emitter import Emitter
from onyx.chat.history_store import get_chat_history_store
from onyx.chat.models import (
    AnswerStreamPart,
    ChatMessageMetadata,
    ChatResponseOutcome,
    ChatResponseSnapshot,
    PersistenceStatus,
)
from onyx.chat.persistence import ChatResponsePersistence
from onyx.chat.presentation import ResponsePresenter, project_response
from onyx.chat.process_message import gather_stream_full
from onyx.chat.stream_buffer import ChatDelivery
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc
from onyx.deep_research.models import ResearchMessageMetadata, ResearchPhase
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationDoneEvent,
    GenerationEvent,
    GenerationRequest,
    GenerationRequestParams,
    GenerationStartEvent,
    ReasoningEffort,
    TextContent,
    ToolCall,
    ToolResultMessage,
)
from onyx.server.query_and_chat.models import MessageResponseIDInfo
from onyx.utils.threadpool_concurrency import ContextThreadPoolExecutor
from tests.unit.onyx.agents.fakes import FakeModelClient


def _run_observed(
    agent: Agent,
    observe: Callable[[Run], None] | None = None,
    observer: Callable[[AgentEvent], None] | None = None,
) -> Run:
    run = agent.start(max_steps=1, on_event=observer)
    if observe:
        observe(run)
    run.result()
    assert run.wait_for_idle(timeout=5)
    return run


def test_snapshot_retains_partial_output_after_producer_continues() -> None:
    partial_ready = threading.Event()
    finish = threading.Event()
    params = GenerationRequestParams(
        model_name="test",
        model_provider="test",
        reasoning_effort=ReasoningEffort.AUTO,
        max_tokens=None,
        sent_kwargs={"temperature": 0.2},
    )

    class StreamingClient(FakeModelClient):
        def stream(
            self, request: GenerationRequest, context: GenerationContext | None = None
        ) -> Generator[GenerationEvent, None, None]:
            del request, context
            yield GenerationStartEvent(
                message=AssistantMessage(content=[TextContent(text="partial")]),
                request_params=params,
            )
            partial_ready.set()
            assert finish.wait(2)
            yield GenerationDoneEvent(
                message=AssistantMessage(content=[TextContent(text="complete")]),
                request_params=params,
            )

    started: Future[Run] = Future()
    agent = Agent(
        StreamingClient(lambda *_: AssistantMessage()),
        prepare_step=lambda _input: PreparedStep(
            output_metadata=ResearchMessageMetadata(
                phase=ResearchPhase.CLARIFICATION, is_reasoning_model=False
            )
        ),
    )

    with ContextThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(lambda: _run_observed(agent, started.set_result))
        try:
            assert partial_ready.wait(2)
            saved = project_response(
                started.result(timeout=2).snapshot(), response_id=42, tool_ids={}
            )
            params.sent_kwargs["temperature"] = 0.7
        finally:
            finish.set()
        future.result(timeout=2)

    assert not saved.cancelled
    assert not saved.is_clarification
    assert saved.answer == "partial"
    assert saved.request_params is not None
    assert saved.request_params.sent_kwargs == {"temperature": 0.2}
    assert saved.response is not None
    assert saved.response.status == RunStatus.RUNNING
    assert (
        project_response(
            started.result(timeout=2).snapshot(), response_id=42, tool_ids={}
        ).answer
        == "complete"
    )
    assert project_response(
        started.result(timeout=2).snapshot(), response_id=42, tool_ids={}
    ).is_clarification


def test_snapshot_does_not_wait_for_slow_stream_observer() -> None:
    updating = threading.Event()
    finish_update = threading.Event()
    started: Future[Run] = Future()
    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="answer")])
        ),
    )

    def display(event: AgentEvent) -> None:
        if isinstance(event, MessageEndEvent):
            updating.set()
            assert finish_update.wait(2)

    with ContextThreadPoolExecutor(max_workers=2) as executor:
        running = executor.submit(
            lambda: _run_observed(agent, started.set_result, display)
        )
        try:
            assert updating.wait(2)
            saving = executor.submit(
                lambda: project_response(
                    started.result(timeout=2).snapshot(), response_id=42, tool_ids={}
                )
            )
            result = saving.result(timeout=0.5)
            assert result.answer == "answer"
            assert result.response is not None
            assert result.response.messages[-1].text == "answer"
        finally:
            finish_update.set()
        running.result(timeout=2)


@pytest.mark.parametrize("delivery", ["complete", "detached", "overflow"])
@pytest.mark.parametrize("sources_known_at_generation", [True, False])
def test_full_response_content_survives_delivery_gaps(
    delivery: str, sources_known_at_generation: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    documents = [
        SearchDoc(
            document_id=f"doc-{number}",
            chunk_ind=0,
            semantic_identifier=f"Source {number}",
            link=f"https://example.com/{number}",
            blurb="Evidence",
            source_type=DocumentSource.WEB,
            boost=0,
            hidden=False,
            metadata={},
            match_highlights=[],
        )
        for number in (1, 2)
    ]
    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[TextContent(text="Second [2], then first [1].")]
            )
        ),
        prepare_step=lambda _input: PreparedStep(
            output_metadata=ChatMessageMetadata(
                sources={1: documents[0], 2: documents[1]}
                if sources_known_at_generation
                else {},
                documents=documents,
            )
        ),
    )
    response_future: Future[ChatResponseOutcome] = Future()
    if delivery == "overflow":
        monkeypatch.setattr("onyx.chat.stream_buffer._STREAM_QUEUE_CAPACITY", 2)
    output = ChatDelivery(None)

    def observe(run: Run) -> None:
        if delivery != "detached":
            run.subscribe(ResponsePresenter(Emitter(output.publish, 42)).consume)

    run = _run_observed(agent, observe)
    response_future.set_result(
        ChatResponseOutcome(
            response=project_response(
                run.snapshot(),
                response_id=42,
                tool_ids={},
                initial_citations={1: documents[0], 2: documents[1]},
            ),
            persistence_status=PersistenceStatus.SAVED,
        )
    )
    packets: list[AnswerStreamPart] = [
        MessageResponseIDInfo(user_message_id=41, reserved_assistant_message_id=42)
    ]
    output.finish()
    packets.extend(output.reader)
    response = gather_stream_full(iter(packets), response_future)
    assert response.answer_citationless == (
        "Second, then first."
        if sources_known_at_generation
        else "Second , then first ."
    )
    assert response.top_documents == documents
    assert [
        (citation.citation_number, citation.document_id)
        for citation in response.citation_info
    ] == ([(2, "doc-2"), (1, "doc-1")] if sources_known_at_generation else [])
    assert response.error_msg == (
        "The live stream is incomplete. Reload this conversation."
        if delivery == "overflow"
        else None
    )


def test_response_projection_uses_the_selected_run_after_agent_reuse() -> None:
    replies = iter(["First response", "Second response"])
    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text=next(replies))])
        )
    )
    first_run = _run_observed(agent)
    first = project_response(first_run.snapshot(), response_id=42, tool_ids={})
    latest = agent.start(background=False, max_steps=1).result()
    assert project_response(first_run.snapshot(), response_id=42, tool_ids={}) == first
    assert first.answer == "First response"
    assert latest.output.text == "Second response"


def test_projection_retains_unfinished_descendant_for_inspection() -> None:
    snapshot = RunState(
        run_id="parent",
        status=RunStatus.ERROR,
        messages=[
            AssistantMessage(
                content=[TextContent(text="Partial answer")],
                metadata=ChatMessageMetadata(),
            )
        ],
        operations=[
            OperationSnapshot(step_index=0, message_index=0, status=RunStatus.ERROR)
        ],
        child_runs=[
            RunState(
                run_id="child",
                agent_id="child-agent",
                status=RunStatus.RUNNING,
                messages=[],
            )
        ],
    )
    response = project_response(
        snapshot,
        response_id=42,
        tool_ids={},
        registrations=[
            AgentInfo(
                id="child-agent",
                path="/root/child",
                parent_id="root",
                description="",
                restoration_config=None,
            )
        ],
    )
    assert response.answer == "Partial answer"
    assert response.response is not None
    assert response.response.child_runs[0].status == RunStatus.RUNNING
    assert snapshot.child_runs[0].status == RunStatus.RUNNING


def test_full_response_reads_canonical_tool_output() -> None:
    snapshot = RunState(
        run_id="root",
        status=RunStatus.COMPLETE,
        messages=[
            AssistantMessage(content=[ToolCall(id="tool", name="echo", arguments={})]),
            ToolResultMessage(
                tool_call_id="tool", tool_name="echo", content="tool output"
            ),
            AssistantMessage(content=[TextContent(text="Answer")]),
        ],
        operations=[
            OperationSnapshot(step_index=0, message_index=0, status=RunStatus.COMPLETE),
            OperationSnapshot(
                step_index=0,
                message_index=0,
                tool_call_id="tool",
                status=RunStatus.COMPLETE,
            ),
            OperationSnapshot(step_index=1, message_index=2, status=RunStatus.COMPLETE),
        ],
        answer_message_index=2,
    )
    projected = project_response(snapshot, response_id=42, tool_ids={"echo": 1})
    assert projected.tool_calls[0].tool_call_response == "tool output"
    assert projected.tool_calls[0].result_metadata is None
    future: Future[ChatResponseOutcome] = Future()
    future.set_result(
        ChatResponseOutcome(
            response=projected, persistence_status=PersistenceStatus.SAVED
        )
    )
    response = gather_stream_full(
        iter(
            [
                MessageResponseIDInfo(
                    user_message_id=41, reserved_assistant_message_id=42
                )
            ]
        ),
        future,
    )
    assert response.tool_calls[0].tool_result == "tool output"


def test_response_save_captures_run_once() -> None:
    run = Run.from_snapshot(
        RunState(
            run_id="run",
            agent_id="agent",
            status=RunStatus.COMPLETE,
            messages=[AssistantMessage(content=[TextContent(text="answer")])],
            operations=[
                OperationSnapshot(
                    step_index=0, message_index=0, status=RunStatus.COMPLETE
                )
            ],
            answer_message_index=0,
        )
    )
    outcome: Future[ChatResponseOutcome] = Future()
    delivery = ChatDelivery(None)
    persistence = ChatResponsePersistence(
        history_store=get_chat_history_store(
            message_id=42, chat_session_id=uuid4(), persist_content=True
        ),
        model_index=0,
        llm=FakeModelClient(lambda *_: AssistantMessage()),
        delivery=delivery,
        outcome=outcome,
    )
    saved: list[ChatResponseSnapshot] = []

    def save(
        *, message_id: int, response: ChatResponseSnapshot, **_kwargs: object
    ) -> None:
        assert message_id == 42
        saved.append(response)

    try:
        with (
            patch.object(run, "snapshot", wraps=run.snapshot) as snapshot,
            patch("onyx.chat.history_store.save_chat_response_to_db", side_effect=save),
        ):
            persistence.save(run)
        snapshot.assert_called_once_with()
        assert len(saved) == 1
        assert saved[0].answer == "answer"
        assert outcome.result(0).persistence_status == PersistenceStatus.SAVED
    finally:
        delivery.finish()
