"""Exercise feature policies through shared execution, child ownership, and rendering."""

import queue
from collections.abc import Generator
from threading import Event
from unittest.mock import MagicMock

import pytest

from onyx.agents.events import AgentEvent, ToolEndEvent
from onyx.agents.runtime import AgentContext, RunResult
from onyx.agents.tools import ToolInvocation
from onyx.chat.emitter import Emitter, ModelStreamStatus
from onyx.chat.presentation import ResponseBinding, ResponsePresenter, attach_response
from onyx.coding_agent.agent import CodingAgent
from onyx.coding_agent.tool_definitions import BASH_TOOL_NAME, GENERATE_ANSWER_TOOL_NAME
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc
from onyx.deep_research.agent import DeepResearchAgent
from onyx.deep_research.models import ResearchAgentCallResult, ResearchPhase
from onyx.deep_research.research_agent import ResearchAgent
from onyx.deep_research.tool_definitions import (
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TOOL_NAME,
    THINK_TOOL_NAME,
)
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.exceptions import LLMTimeoutError
from onyx.llm.interfaces import GenerationContext
from onyx.llm.litellm_models import ChatCompletionDeltaToolCall, Delta, FunctionCall
from onyx.llm.models import (
    AssistantMessage,
    GenerationEvent,
    GenerationRequest,
    ReasoningEffort,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.server.query_and_chat.streaming_models import OverallStop, Packet
from onyx.tools.interface import ToolContext
from onyx.tools.tool_implementations.bash.bash_tool import BashTool
from tests.unit.onyx.agents.fakes import EchoTool, FakeModelClient, ScriptedLLM


def tool_delta(name: str, arguments: str = "{}", count: int = 1) -> Delta:
    return Delta(
        tool_calls=[
            ChatCompletionDeltaToolCall(
                index=i,
                id=f"call-{i}",
                function=FunctionCall(name=name, arguments=arguments),
            )
            for i in range(count)
        ]
    )


def test_coding_bash_order_history_and_final_answer() -> None:
    llm = ScriptedLLM(
        [
            tool_delta(BASH_TOOL_NAME, '{"cmd":"pwd"}', 2),
            tool_delta(GENERATE_ANSWER_TOOL_NAME),
            Delta(content="Done"),
        ],
        128000,
    )
    bash = MagicMock(spec=BashTool)
    bash.run.side_effect = [
        ToolResult(details=None, content=value) for value in ["first", "second"]
    ]
    bash.name = "bash"
    harness = CodingAgent(
        query="Read repository",
        repo="org/repo",
        llm=llm,
        token_counter=len,
        user_identity=None,
        bash_tool=bash,
    )
    result = harness.agent.run(max_steps=3, messages=harness.input_messages)
    assert len(llm.requests) == 3
    assert result.output.text == "Done"
    assert bash.run.call_count == 2
    responses = [
        message
        for message in harness.agent.context.messages
        if message.role == "tool_result"
    ]
    assert [(message.tool_call_id, message.text) for message in responses] == [
        ("call-0", "first"),
        ("call-1", "second"),
        ("call-0", "Ready to produce the final answer."),
    ]
    assert llm.requests[-1]["tools"] == []


def test_cancel_after_coding_tools_prevents_final_model_call() -> None:
    llm = ScriptedLLM([tool_delta(BASH_TOOL_NAME, '{"cmd":"pwd"}')], 128000)
    bash = MagicMock(spec=BashTool)
    signal = CancellationSignal()

    def finish(_invocation: ToolInvocation, _context: ToolContext) -> ToolResult:
        signal.cancel()
        return ToolResult(content="done")

    bash.run.side_effect = finish
    bash.name = "bash"
    harness = CodingAgent(
        query="Read repository",
        repo="org/repo",
        llm=llm,
        token_counter=len,
        user_identity=None,
        bash_tool=bash,
    )
    agent = harness.agent
    with pytest.raises(AgentCancelled):
        agent.run(max_steps=3, cancellation=signal)
    assert len(llm.requests) == 1


@pytest.mark.parametrize("render", [True, False])
def test_research_think_steps_are_bounded_and_report_is_generated(render: bool) -> None:
    llm = ScriptedLLM(
        [
            tool_delta(THINK_TOOL_NAME, '{"reasoning":"inspect"}'),
            tool_delta(THINK_TOOL_NAME, '{"reasoning":"compare"}'),
            Delta(content="Report"),
        ],
        128000,
    )
    presentation = (
        ResponsePresenter(Emitter(merged_queue=queue.Queue(), response_id=42))
        if render
        else None
    )
    feature = ResearchAgent(
        "Find facts", [], llm, False, len, None, "", ReasoningEffort.LOW
    )
    if presentation:
        feature.agent.subscribe(presentation.consume)
    result = feature.agent.run(max_steps=3, messages=feature.input_messages)
    assert len(llm.requests) == 3
    assert feature.report(result).intermediate_report == "Report"
    assert (
        len(
            [
                message
                for message in feature.agent.context.messages
                if message.role == "tool_result"
            ]
        )
        == 2
    )


def test_research_executes_tools_and_records_results() -> None:
    llm = ScriptedLLM(
        [
            tool_delta("echo", '{"value":"found"}'),
            tool_delta(GENERATE_REPORT_TOOL_NAME),
            Delta(content="Report"),
        ],
        128000,
    )
    feature = ResearchAgent(
        "Find facts", [EchoTool()], llm, True, len, None, "", ReasoningEffort.LOW
    )
    result = feature.agent.run(max_steps=3, messages=feature.input_messages)
    assert result.output.text == "Report"
    snapshot = feature.agent.snapshot()
    assert snapshot is not None
    accepted = [
        message
        for message in snapshot.messages
        if message.role == "tool_result" and message.tool_name == "echo"
    ]
    assert accepted[0].text == "found"


def test_deep_research_composes_plan_child_and_report() -> None:
    llm = ScriptedLLM(
        [
            Delta(content="Plan"),
            tool_delta(RESEARCH_AGENT_TOOL_NAME, '{"task":"facts"}'),
            tool_delta(GENERATE_REPORT_TOOL_NAME),
            Delta(content="Child report"),
            tool_delta(GENERATE_REPORT_TOOL_NAME),
            Delta(content="Final report"),
        ],
        128000,
    )
    output: queue.Queue[tuple[int, Packet | ModelStreamStatus]] = queue.Queue()
    state = ResponseBinding()
    feature = DeepResearchAgent(
        messages=[UserMessage(content="Research")],
        allowed_tools=[],
        llm=llm,
        token_counter=len,
        user_identity=None,
        language_section="",
        reasoning_effort=ReasoningEffort.LOW,
        all_injected_file_metadata=None,
        skip_clarification=True,
    )
    attach_response(
        feature.agent,
        state,
        Emitter(merged_queue=output, response_id=42),
        response_id=42,
        tool_ids={RESEARCH_AGENT_TOOL_NAME: 7},
    )
    feature.agent.run(max_steps=8)
    assert state.snapshot().answer == "Final report"
    assert len(llm.requests) == 6
    snapshot = state.snapshot()
    assert snapshot.transcript is not None
    assert snapshot.transcript.messages[0].text == "Plan"
    assert snapshot.transcript.messages[-1].text == "Final report"
    assert len(snapshot.transcript.children) == 1
    assert snapshot.transcript.children[0].messages[-1].text == "Child report"
    assert any(
        isinstance(item[1], Packet) and isinstance(item[1].obj, OverallStop)
        for item in list(output.queue)
    )


@pytest.mark.parametrize("skip_clarification", [False, True])
def test_deep_research_prelude_cancellation_keeps_partial_output(
    skip_clarification: bool,
) -> None:
    state = ResponseBinding()
    signal = CancellationSignal()

    class InterruptedLLM(ScriptedLLM):
        def stream(
            self, request: GenerationRequest, context: GenerationContext | None = None
        ) -> Generator[GenerationEvent, None, None]:
            for event in super().stream(request, context):
                yield event
                if event.type == "text_delta":
                    signal.cancel()
                    signal.check()

    feature = DeepResearchAgent(
        [UserMessage(content="Research")],
        [],
        InterruptedLLM([Delta(content="Partial prelude")], 128000),
        len,
        None,
        "",
        ReasoningEffort.LOW,
        None,
        skip_clarification=skip_clarification,
    )

    attach_response(
        feature.agent,
        state,
        None,
        response_id=42,
        tool_ids={RESEARCH_AGENT_TOOL_NAME: 7},
    )
    with pytest.raises(AgentCancelled):
        feature.agent.run(max_steps=4, cancellation=signal)
    snapshot = state.snapshot(cancelled=True)
    assert snapshot.transcript is not None
    assert snapshot.transcript.status == "cancelled"
    assert snapshot.transcript.messages[-1].text == "Partial prelude"


def test_deep_research_advances_phases_without_user_queue_messages() -> None:
    llm = ScriptedLLM(
        [
            Delta(content="Plan"),
            Delta(content="Enough evidence"),
            Delta(content="Final report"),
        ],
        128000,
    )
    feature = DeepResearchAgent(
        [UserMessage(content="Research")],
        [],
        llm,
        len,
        None,
        "",
        ReasoningEffort.LOW,
        None,
        skip_clarification=True,
    )
    result = feature.agent.run(max_steps=3)
    assert result.output.text == "Final report"
    assert feature.phase == ResearchPhase.REPORT
    assert len(llm.requests) == 3
    assert [
        message.text
        for message in feature.agent.context.messages
        if isinstance(message, UserMessage)
    ] == ["Research"]


def test_child_timeout_is_a_failed_tool_result(monkeypatch: pytest.MonkeyPatch) -> None:
    original_prepare = ResearchAgent._build_request

    def fail_child(self: ResearchAgent, context: AgentContext) -> GenerationRequest:
        if self.research_topic == "unavailable":
            raise LLMTimeoutError("Provider timeout")
        return original_prepare(self, context)

    monkeypatch.setattr(ResearchAgent, "_build_request", fail_child)
    llm = ScriptedLLM(
        [
            Delta(content="Plan"),
            tool_delta(RESEARCH_AGENT_TOOL_NAME, '{"task":"unavailable"}'),
            tool_delta(GENERATE_REPORT_TOOL_NAME),
            Delta(content="Report with remaining evidence"),
        ],
        128000,
    )
    feature = DeepResearchAgent(
        [UserMessage(content="Research")],
        [],
        llm,
        len,
        None,
        "",
        ReasoningEffort.LOW,
        None,
        skip_clarification=True,
    )
    result = feature.agent.run(max_steps=4)
    assert result.output.text == "Report with remaining evidence"
    tool_results = [
        message
        for message in feature.agent.context.messages
        if message.role == "tool_result"
    ]
    assert tool_results[0].is_error
    snapshot = feature.agent.snapshot()
    assert snapshot is not None
    assert snapshot.children[0].status == "error"


def test_research_normalizes_citations_before_acceptance_in_call_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    second_finished = Event()
    completion_order: list[str] = []
    documents = {
        topic: SearchDoc(
            document_id=topic,
            chunk_ind=0,
            semantic_identifier=topic,
            blurb=topic,
            source_type=DocumentSource.WEB,
            boost=0,
            hidden=False,
            metadata={},
            match_highlights=[],
        )
        for topic in ("first", "second")
    }
    original_report = ResearchAgent.report

    def child_report(
        child: ResearchAgent, completed: RunResult
    ) -> ResearchAgentCallResult:
        report = original_report(child, completed)
        report.citation_mapping = {9: documents[child.research_topic]}
        completion_order.append(child.research_topic)
        if child.research_topic == "second":
            second_finished.set()
        return report

    monkeypatch.setattr(ResearchAgent, "report", child_report)

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        topic = next(
            (
                message.text
                for message in request.messages
                if isinstance(message, UserMessage) and message.text in documents
            ),
            None,
        )
        if topic is not None:
            if topic == "first":
                assert second_finished.wait(5)
            return AssistantMessage(content=[TextContent(text=f"{topic} [9]")])
        if any(tool.name == RESEARCH_AGENT_TOOL_NAME for tool in request.tools):
            if any(
                isinstance(message, ToolResultMessage)
                and message.tool_name == RESEARCH_AGENT_TOOL_NAME
                for message in request.messages
            ):
                return AssistantMessage(
                    content=[
                        ToolCall(
                            id="report", name=GENERATE_REPORT_TOOL_NAME, arguments={}
                        )
                    ]
                )
            return AssistantMessage(
                content=[
                    ToolCall(
                        id=topic,
                        name=RESEARCH_AGENT_TOOL_NAME,
                        arguments={"task": topic},
                    )
                    for topic in documents
                ]
            )
        return AssistantMessage(
            content=[
                TextContent(
                    text="Final [1] [2]"
                    if any(
                        isinstance(message, AssistantMessage)
                        for message in request.messages
                    )
                    else "Plan"
                )
            ]
        )

    state = ResponseBinding()
    feature = DeepResearchAgent(
        [UserMessage(content="Parent")],
        [],
        FakeModelClient(reply),
        len,
        None,
        "",
        ReasoningEffort.LOW,
        None,
        skip_clarification=True,
    )
    attach_response(
        feature.agent,
        state,
        None,
        response_id=42,
        tool_ids={RESEARCH_AGENT_TOOL_NAME: 7},
    )
    final_events: list[ToolEndEvent] = []

    def record(event: AgentEvent) -> None:
        if (
            isinstance(event, ToolEndEvent)
            and event.tool_call.name == RESEARCH_AGENT_TOOL_NAME
        ):
            final_events.append(event)

    feature.agent.subscribe(record)
    feature.agent.run(max_steps=4)
    accepted = [
        message
        for message in feature.agent.context.messages
        if isinstance(message, ToolResultMessage)
        and message.tool_name == RESEARCH_AGENT_TOOL_NAME
    ]
    assert completion_order == ["second", "first"]
    assert [message.text for message in accepted] == ["first [1]", "second [2]"]
    assert [event.result.text for event in final_events] == [
        message.text for message in accepted
    ]
    for index, message in enumerate(accepted, start=1):
        assert isinstance(message.details, ResearchAgentCallResult)
        assert message.details.intermediate_report == message.text
        assert list(message.details.citation_mapping) == [index]
    assert {
        number: doc.document_id
        for number, doc in state.snapshot().citation_to_doc.items()
    } == {1: "first", 2: "second"}
