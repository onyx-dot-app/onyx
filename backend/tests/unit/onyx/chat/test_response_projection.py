"""Persistence projects canonical output without waiting for stream observers."""

import threading
from collections.abc import Generator
from queue import Queue

import pytest

from onyx.agents.events import AgentEvent, MessageEndEvent
from onyx.agents.runtime import Agent, AgentContext
from onyx.chat.emitter import Emitter, ModelStreamStatus
from onyx.chat.models import (
    AnswerStreamPart,
    ChatResponseOutcome,
    ChatStepOutput,
    PersistenceStatus,
    StreamingError,
)
from onyx.chat.presentation import ResponseBinding, attach_response
from onyx.chat.process_message import gather_stream_full
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc
from onyx.deep_research.models import ResearchPhase, ResearchStepOutput
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
)
from onyx.server.query_and_chat.models import MessageResponseIDInfo
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.utils.threadpool_concurrency import ContextThreadPoolExecutor
from tests.unit.onyx.agents.fakes import FakeModelClient


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

    state = ResponseBinding()
    agent = Agent(
        StreamingClient(lambda *_: AssistantMessage()),
        context=AgentContext(
            output_metadata=ResearchStepOutput(
                phase=ResearchPhase.CLARIFICATION, is_reasoning_model=False
            )
        ),
    )
    attach_response(
        agent,
        state,
        Emitter(Queue(), response_id=42),
        response_id=42,
        tool_ids={},
    )
    with ContextThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(lambda: agent.run(max_steps=1))
        try:
            assert partial_ready.wait(2)
            saved = state.snapshot(cancelled=True)
            params.sent_kwargs["temperature"] = 0.7
        finally:
            finish.set()
        future.result(timeout=2)

    assert saved.cancelled
    assert not saved.is_clarification
    assert saved.answer == "partial"
    assert saved.request_params is not None
    assert saved.request_params.sent_kwargs == {"temperature": 0.2}
    assert saved.transcript is not None
    assert saved.transcript.status == "cancelled"
    assistant = saved.transcript.messages[-1]
    assert isinstance(assistant, AssistantMessage)
    assert assistant.text == "partial"
    assert assistant.stop_reason == "aborted"
    assert state.snapshot().answer == "complete"
    assert state.snapshot().is_clarification


def test_snapshot_does_not_wait_for_slow_stream_observer() -> None:
    updating = threading.Event()
    finish_update = threading.Event()
    state = ResponseBinding()
    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="answer")])
        ),
    )
    attach_response(
        agent,
        state,
        Emitter(Queue(), response_id=42),
        response_id=42,
        tool_ids={},
    )

    def display(event: AgentEvent) -> None:
        if isinstance(event, MessageEndEvent):
            updating.set()
            assert finish_update.wait(2)

    agent.subscribe(display)
    with ContextThreadPoolExecutor(max_workers=2) as executor:
        running = executor.submit(lambda: agent.run(max_steps=1))
        try:
            assert updating.wait(2)
            saving = executor.submit(state.snapshot)
            result = saving.result(timeout=0.5)
            assert result.answer == "answer"
            assert result.transcript is not None
            assert result.transcript.messages[-1].text == "answer"
        finally:
            finish_update.set()
        running.result(timeout=2)


@pytest.mark.parametrize("delivery", ["complete", "detached", "overflow"])
@pytest.mark.parametrize("sources_known_at_generation", [True, False])
def test_full_response_content_survives_delivery_gaps(
    delivery: str, sources_known_at_generation: bool
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
        context=AgentContext(
            output_metadata=ChatStepOutput(
                sources={1: documents[0], 2: documents[1]}
                if sources_known_at_generation
                else {},
                documents=documents,
            )
        ),
    )
    binding = ResponseBinding()
    output: Queue[tuple[int, Packet | ModelStreamStatus]] = Queue(
        maxsize=1 if delivery == "overflow" else 0
    )
    closed = threading.Event()
    attach_response(
        agent,
        binding,
        None if delivery == "detached" else Emitter(output, 42, drain_done=closed),
        response_id=42,
        tool_ids={},
        initial_citations={1: documents[0], 2: documents[1]},
    )
    agent.run(max_steps=1)
    binding.finish(
        ChatResponseOutcome(
            response=binding.snapshot(), persistence_status=PersistenceStatus.SAVED
        )
    )
    packets: list[AnswerStreamPart] = [
        MessageResponseIDInfo(user_message_id=41, reserved_assistant_message_id=42)
    ]
    packets.extend(
        packet for _, packet in list(output.queue) if isinstance(packet, Packet)
    )
    if delivery == "overflow":
        assert closed.is_set()
        packets.append(StreamingError(error="Delivery gap", error_code="STREAM_GAP"))
    response = gather_stream_full(iter(packets), binding)
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
    assert response.error_msg == ("Delivery gap" if delivery == "overflow" else None)
