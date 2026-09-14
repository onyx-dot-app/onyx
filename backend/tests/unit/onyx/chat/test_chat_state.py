import threading
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor

from onyx.agents.events import AgentEvent, MessageEndEvent, MessageUpdateEvent
from onyx.agents.runtime import Agent
from onyx.chat.chat_state import ChatStateContainer
from onyx.context.search.models import SearchDoc
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
from tests.unit.onyx.agents.fakes import FakeModelClient


def test_snapshot_retains_partial_output_after_producer_continues() -> None:
    partial_ready = threading.Event()
    finish = threading.Event()

    class StreamingClient(FakeModelClient):
        def stream(
            self, request: GenerationRequest, context: GenerationContext | None = None
        ) -> Generator[GenerationEvent, None, None]:
            del request, context
            partial = AssistantMessage(content=[TextContent(text="partial")])
            yield GenerationStartEvent(message=partial)
            partial_ready.set()
            assert finish.wait(2)
            yield GenerationDoneEvent(
                message=AssistantMessage(content=[TextContent(text="complete")])
            )

    state = ChatStateContainer()
    agent = Agent(StreamingClient(lambda *_: AssistantMessage()))
    state.bind_agent(agent)
    params = GenerationRequestParams(
        model_name="test",
        model_provider="test",
        reasoning_effort=ReasoningEffort.AUTO,
        max_tokens=None,
        sent_kwargs={"temperature": 0.2},
    )

    def display(event: AgentEvent) -> None:
        if isinstance(event, (MessageUpdateEvent, MessageEndEvent)):
            state.update_display(
                answer=event.message.text,
                reasoning="",
                request_params=params,
                citations={1},
            )

    agent.subscribe(display)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(agent.run, max_turns=1)
        try:
            assert partial_ready.wait(2)
            saved = state.snapshot(cancelled=True)
            params.sent_kwargs["temperature"] = 0.7
        finally:
            finish.set()
        future.result(timeout=2)

    assert saved.cancelled
    assert saved.answer_tokens == "partial"
    assert saved.request_params is not None
    assert saved.request_params.sent_kwargs == {"temperature": 0.2}
    assert saved.emitted_citations == {1}
    assert saved.transcript is not None
    assert saved.transcript.status == "cancelled"
    assistant = saved.transcript.messages[-1]
    assert isinstance(assistant, AssistantMessage)
    assert assistant.text == "partial"
    assert assistant.stop_reason == "aborted"
    assert state.snapshot().answer_tokens == "complete"


def test_snapshot_waits_for_display_of_committed_runtime_message() -> None:
    updating = threading.Event()
    finish_update = threading.Event()
    snapshot_started = threading.Event()
    snapshot_done = threading.Event()
    state = ChatStateContainer()
    agent = Agent(
        FakeModelClient(
            lambda _context, _signal: AssistantMessage(
                content=[TextContent(text="answer")]
            )
        )
    )
    state.bind_agent(agent)

    def display(event: AgentEvent) -> None:
        if event.type == "message_end":
            updating.set()
            assert finish_update.wait(2)
            state.update_display(
                answer="answer",
                reasoning="reasoning",
                request_params=None,
                citations={2},
            )

    agent.subscribe(display)

    def snapshot() -> None:
        snapshot_started.set()
        result = state.snapshot()
        assert result.answer_tokens == "answer"
        assert result.reasoning_tokens == "reasoning"
        assert result.emitted_citations == {2}
        assert result.transcript is not None
        assert result.transcript.messages[-1].text == "answer"
        snapshot_done.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        running = executor.submit(agent.run, max_turns=1)
        try:
            assert updating.wait(2)
            saving = executor.submit(snapshot)
            assert snapshot_started.wait(2)
            assert not snapshot_done.wait(0.05)
        finally:
            finish_update.set()
        running.result(timeout=2)
        saving.result(timeout=2)


def test_state_owns_citation_mapping() -> None:
    state = ChatStateContainer()
    mapping: dict[int, SearchDoc] = {}
    state.set_citation_mapping(mapping)
    # Mutations through the producer or a getter cannot change stored state.
    mapping[1] = SearchDoc.model_construct(document_id="external")
    assert state.snapshot().citation_to_doc == {}
    returned = state.get_citation_to_doc()
    returned.update(mapping)
    assert state.snapshot().citation_to_doc == {}
