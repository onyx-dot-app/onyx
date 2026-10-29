"""Context pressure preserves the task, tool effects, and recorded history."""

import threading
from collections.abc import Generator, Sequence
from unittest.mock import Mock, patch

import pytest
import tiktoken

from onyx.agents.compaction import (
    SUMMARY_TIMEOUT_SECONDS,
    CheckpointMismatchError,
    ContextLimitError,
    compact_history,
    context_budget,
    history_boundaries,
    request_tokens,
    working_messages,
)
from onyx.agents.events import AgentEvent
from onyx.agents.models import (
    AgentState,
    CompactionCheckpoint,
    ExecutionCheckpoint,
    ExecutionStatus,
    PreparedStep,
    RunState,
    RunStatus,
    StepInput,
)
from onyx.agents.runtime import (
    Agent,
    Run,
    RunFailed,
    _compact_context,
    _truncate_context,
)
from onyx.agents.tools import (
    AgentTool,
    HumanToolAnswer,
    InputDecision,
    InputMode,
    PendingToolInput,
    ToolInvocation,
)
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.exceptions import LLMContextLimitError
from onyx.llm.interfaces import LLM, GenerationContext, LLMConfig, LLMUserIdentity
from onyx.llm.models import (
    AssistantMessage,
    GenerationErrorEvent,
    GenerationEvent,
    GenerationOptions,
    GenerationRequest,
    Message,
    SystemMessage,
    TextContent,
    ThinkingDeltaEvent,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.llm.token_budget import TokenBudget, resolve_token_budget
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.traces import TraceContentMode
from tests.unit.onyx.agents.fakes import FakeModelClient, message_events

TASK = "Compare the evidence and preserve citations."


class ContextModel(LLM):
    def __init__(self, *, tool_rounds: int = 0, reject_first: bool = False) -> None:
        self.tool_rounds = tool_rounds
        self.reject_first = reject_first
        self.generations: list[GenerationRequest] = []
        self.summaries: list[GenerationRequest] = []
        self.contexts: list[GenerationContext] = []
        self.threads: list[threading.Thread] = []

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="openai",
            model_name="test",
            max_input_tokens=1200,
            temperature=0,
        )

    def redact_error(self, text: str) -> str:
        return text

    def invoke(
        self, request: GenerationRequest, context: GenerationContext | None = None
    ) -> AssistantMessage:
        self.threads.append(threading.current_thread())
        if context:
            self.contexts.append(context.model_copy())
        if context and context.cancellation:
            context.cancellation.check()
        if context and context.flow == LLMFlow.CHAT_HISTORY_SUMMARIZATION:
            self.summaries.append(request.model_copy(deep=True))
            assert request_tokens(request) <= context_budget(self).input_limit
            return AssistantMessage(
                content=[
                    TextContent(
                        text=f"Summary revision {len(self.summaries)}: Evidence from completed searches supports [1]. Continue comparing sources."
                    )
                ]
            )
        self.generations.append(request.model_copy(deep=True))
        if self.reject_first and len(self.generations) == 1:
            raise LLMContextLimitError("Too much context")
        index = len(self.generations)
        if index <= self.tool_rounds:
            return AssistantMessage(
                content=[ToolCall(id=f"call-{index}", name="lookup", arguments={})]
            )
        return AssistantMessage(
            content=[TextContent(text="Evidence supports the conclusion [1].")]
        )

    def stream(
        self, request: GenerationRequest, context: GenerationContext | None = None
    ) -> Generator[GenerationEvent, None, None]:
        try:
            message = self.invoke(request, context)
        except LLMContextLimitError:
            yield GenerationErrorEvent(error_message="Too much context")
            raise
        yield from message_events(message)


def test_compaction_uses_configured_input_safety_margin() -> None:
    model = ContextModel()
    with (
        patch("onyx.agents.compaction.GEN_AI_INPUT_TOKEN_SAFETY_MARGIN", 0.25),
        patch("onyx.llm.token_budget.GEN_AI_INPUT_TOKEN_SAFETY_MARGIN", 0.25),
    ):
        budget = context_budget(model)
        output_budget = resolve_token_budget(model)
    assert budget.input_limit == 900
    assert (
        model.config.max_input_tokens - budget.input_limit
        == output_budget.safety_tokens
    )


def test_compaction_within_task_preserves_tool_effects_and_prepared_steps() -> None:
    model = ContextModel(tool_rounds=5)
    calls: list[str] = []
    prepared: list[int] = []
    execution_threads: list[threading.Thread] = []

    def execute(invocation: ToolInvocation) -> ToolResult:
        calls.append(invocation.call_id)
        return ToolResult(content="Evidence [1] 東京 " * 180)

    def prepare(decision: StepInput) -> PreparedStep:
        execution_threads.append(threading.current_thread())
        step = decision.step
        prepared.append(step.index)
        return PreparedStep(tools=tools, assemble_messages=render)

    def render(messages: Sequence[Message]) -> list[Message]:
        assert threading.current_thread() is execution_threads[0]
        return [*messages, SystemMessage(content="Use the required report format.")]

    tools = [
        AgentTool(
            definition=ToolDefinition(
                name="lookup", description="Search", parameters={}
            ),
            execute=execute,
        )
    ]
    agent = Agent(
        model,
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        state=AgentState(messages=[UserMessage(content=TASK)]),
        tools=tools,
        prepare_step=prepare,
    )
    run = agent.start(max_steps=6)
    run.result()
    assert run.wait_for_idle(2)
    assert len(model.summaries) >= 2
    assert all(thread is execution_threads[0] for thread in model.threads)
    assert all(thread is execution_threads[0] for thread in execution_threads)
    for index, summary_request in enumerate(model.summaries):
        summary_input = summary_request.messages[0].text
        assert "tool_result lookup (call-" in summary_input
        assert "\ufffd" not in summary_input
        previous = (
            f"Summary revision {index}: Evidence from completed searches supports [1]. Continue comparing sources."
            if index
            else ""
        )
        assert summary_input.startswith(f"Previous summary:\n{previous}\n\nHistory:\n")
    assert calls == [f"call-{i}" for i in range(1, 6)]
    assert prepared == list(range(6))
    assert (
        len([m for m in agent.state.messages if isinstance(m, ToolResultMessage)]) == 5
    )
    for request in model.generations:
        assert any(message.text == TASK for message in request.messages)
        assert request.messages[-1].text == "Use the required report format."
        assert request_tokens(request) <= context_budget(model).input_limit
        pending: set[str] = set()
        for message in request.messages:
            if isinstance(message, AssistantMessage):
                pending.update(call.id for call in message.tool_calls)
            elif isinstance(message, ToolResultMessage):
                assert message.tool_call_id in pending
                pending.remove(message.tool_call_id)
        assert not pending
    snapshot = run.snapshot()
    assert snapshot is not None and snapshot.checkpoint is not None
    reloaded = Agent(
        model,
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        state=AgentState(messages=agent.state.messages, checkpoint=snapshot.checkpoint),
    )
    reloaded_run = reloaded.start(
        max_steps=1, messages=[UserMessage(content="Summarize the conclusion.")]
    )
    reloaded_run.result()
    assert reloaded_run.wait_for_idle(2)
    assert any(
        "Conversation summary:" in message.text
        for message in model.generations[-1].messages
    )


@pytest.mark.parametrize("step_timeout", [None, 37])
def test_provider_context_rejection_preserves_execution_settings(
    step_timeout: int | None,
) -> None:
    model = ContextModel(reject_first=True)
    history: list[Message] = [
        UserMessage(content="Old question"),
        AssistantMessage(content=[TextContent(text="Old evidence " * 100)]),
        UserMessage(content=TASK),
    ]
    prepared: list[int] = []

    def prepare(state: StepInput) -> PreparedStep:
        prepared.append(state.step.index)
        return PreparedStep(stall_timeout_s=step_timeout)

    signal = CancellationSignal()
    default_signal = CancellationSignal()
    identity = LLMUserIdentity(user_id="user", session_id="session")
    agent = Agent(
        model,
        state=AgentState(messages=history),
        generation_context=GenerationContext(
            cancellation=default_signal,
            stall_timeout_s=23,
            total_timeout_s=71,
            user_identity=identity,
            flow=LLMFlow.CHAT_RESPONSE,
            content_mode=TraceContentMode.METADATA_ONLY,
        ),
        prepare_step=prepare,
    )
    events: list[AgentEvent] = []
    run = agent.start(
        background=False, max_steps=1, cancellation=signal, on_event=events.append
    )
    result = run.result()
    assert run.wait_for_idle(2)
    starts = [event for event in events if event.type == "message_start"]
    ends = [event for event in events if event.type == "message_end"]
    assert len(starts) == len(ends) == 1
    assert starts[0].message_id == ends[0].message_id == result.output.id
    assert ends[0].status == ExecutionStatus.COMPLETE
    assert ends[0].message.error_message is None
    assert ends[0].message.thinking == ""
    assert prepared == [0]
    assert [context.flow for context in model.contexts] == [
        LLMFlow.CHAT_RESPONSE,
        LLMFlow.CHAT_HISTORY_SUMMARIZATION,
        LLMFlow.CHAT_RESPONSE,
    ]
    for context in model.contexts:
        assert context.cancellation is run.cancellation_signal
        assert context.stall_timeout_s == (step_timeout or 23)
        if context.flow == LLMFlow.CHAT_HISTORY_SUMMARIZATION:
            assert context.total_timeout_s is not None
            assert 0 < context.total_timeout_s <= 71
        else:
            assert context.total_timeout_s == 71
        assert context.user_identity == identity
        assert context.content_mode == TraceContentMode.METADATA_ONLY
    assert len(model.generations) == 2
    assert len(model.summaries) == 1
    assert result.steps == 1
    assert len(agent.state.messages) == len(history) + 1
    assert result.output.text.endswith("[1].")

    assert agent.generation_context.cancellation is default_signal
    assert agent.generation_context.stall_timeout_s == 23
    assert agent.generation_context.flow == LLMFlow.CHAT_RESPONSE


def test_step_timeout_override_does_not_change_later_steps() -> None:
    model = ContextModel(tool_rounds=1)
    tool = AgentTool(
        definition=ToolDefinition(
            name="lookup", description="Lookup evidence", parameters={"type": "object"}
        ),
        execute=lambda _invocation: ToolResult(content="Evidence"),
    )

    def prepare(state: StepInput) -> PreparedStep:
        return PreparedStep(
            tools=[tool], stall_timeout_s=37 if state.step.index == 0 else None
        )

    agent = Agent(
        model,
        generation_context=GenerationContext(
            flow=LLMFlow.CHAT_RESPONSE, stall_timeout_s=23
        ),
        tools=[tool],
        prepare_step=prepare,
    )
    run = agent.start(background=False, max_steps=2)
    run.result()
    assert run.wait_for_idle(2)
    assert [context.stall_timeout_s for context in model.contexts] == [37, 23]
    assert agent.generation_context.stall_timeout_s == 23


def test_oversized_required_instruction_fails_without_losing_snapshot() -> None:
    model = ContextModel()
    agent = Agent(
        model,
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        state=AgentState(messages=[UserMessage(content="mandatory " * 2000)]),
    )
    run = agent.start(max_steps=1)
    with pytest.raises(RunFailed):
        run.result()
    assert run.wait_for_idle(2)
    assert not model.generations
    assert agent.state.messages[0].text == "mandatory " * 2000
    snapshot = run.snapshot()
    assert snapshot is not None and snapshot.status == "error"


def test_context_fitting_reuses_checkpoint_after_content_changes() -> None:
    source: list[Message] = [
        UserMessage(id="user", content="Updated file contents"),
        AssistantMessage(id="answer", content=[TextContent(text="Saved answer")]),
        UserMessage(id="follow-up", content="Continue"),
    ]
    checkpoint = CompactionCheckpoint(
        summary="Summary", covered_through_message_id="user"
    )
    run = Run.from_snapshot(
        RunState(
            run_id="run",
            agent_id="agent",
            status=RunStatus.COMPLETE,
            checkpoint=checkpoint,
            steps=[],
        )
    )
    request = _compact_context(
        run,
        ContextModel(),
        source,
        PreparedStep(),
        GenerationContext(flow=LLMFlow.UNTAGGED_INVOKE),
    )
    assert any(
        message.text == "Conversation summary:\nSummary" for message in request.messages
    )
    assert run.snapshot().checkpoint == checkpoint


def test_checkpoint_from_another_branch_is_removed_from_context() -> None:
    agent = Agent(
        ContextModel(),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        state=AgentState(
            messages=[UserMessage(content="Current branch")],
            checkpoint=CompactionCheckpoint(
                summary="Other branch", covered_through_message_id="other-branch"
            ),
        ),
    )
    run = agent.start(max_steps=1)
    run.result()
    assert run.wait_for_idle(2)
    assert run.snapshot().checkpoint is None
    assert agent.state.checkpoint is None


@pytest.mark.parametrize("max_tokens", [None, 200])
def test_output_budget_is_recalculated_after_compaction(
    monkeypatch: pytest.MonkeyPatch, max_tokens: int | None
) -> None:
    budget = TokenBudget(
        input_tokens=1000,
        max_output_tokens=4096,
        context_tokens=4300,
        safety_tokens=120,
    )
    monkeypatch.setattr("onyx.agents.runtime.resolve_token_budget", lambda _: budget)
    model = ContextModel(reject_first=True)
    agent = Agent(
        model,
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        state=AgentState(
            messages=[
                UserMessage(content="Old question"),
                AssistantMessage(content=[TextContent(text="Old evidence " * 100)]),
                UserMessage(content=TASK),
            ]
        ),
        options=GenerationOptions(max_tokens=max_tokens),
    )
    agent.start(background=False, max_steps=1).result()
    assert len(model.generations) == 2
    assert model.summaries
    for request in model.generations:
        expected = budget.output_allowance(request_tokens(request))
        assert expected is not None
        assert request.options.max_tokens == (
            min(max_tokens, expected) if max_tokens else expected
        )
    if max_tokens is None:
        before = model.generations[0].options.max_tokens
        after = model.generations[1].options.max_tokens
        assert before is not None and after is not None
        assert after > before


@pytest.mark.parametrize("reject_first", [False, True])
@pytest.mark.parametrize("provider_error", [False, True])
def test_failed_summary_truncates_old_turns_without_changing_history(
    reject_first: bool, provider_error: bool
) -> None:
    class FailingSummaryModel(ContextModel):
        def invoke(
            self, request: GenerationRequest, context: GenerationContext | None = None
        ) -> AssistantMessage:
            if context and context.flow == LLMFlow.CHAT_HISTORY_SUMMARIZATION:
                self.summaries.append(request)
                if provider_error:
                    raise RuntimeError("Summary provider unavailable")
                return AssistantMessage()
            return super().invoke(request, context)

    model = FailingSummaryModel(reject_first=reject_first)
    history: list[Message] = [
        SystemMessage(content="Preserve these instructions."),
        UserMessage(content="Old question"),
        AssistantMessage(content=[ToolCall(id="old", name="lookup", arguments={})]),
        ToolResultMessage(
            tool_call_id="old",
            tool_name="lookup",
            content="Old evidence " * (100 if reject_first else 1500),
        ),
        AssistantMessage(content=[TextContent(text="Old answer")]),
        UserMessage(content=TASK),
        AssistantMessage(content=[ToolCall(id="current", name="lookup", arguments={})]),
        ToolResultMessage(
            tool_call_id="current", tool_name="lookup", content="Current evidence"
        ),
    ]
    agent = Agent(
        model,
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        state=AgentState(messages=history),
    )
    history = agent.state.messages
    run = agent.start(background=False, max_steps=1)
    run.result()
    assert model.summaries
    request = model.generations[-1]
    assert request.messages == [history[0], *history[5:]]
    assert request_tokens(request) <= context_budget(model).input_limit
    assert agent.state.messages[:-1] == history
    checkpoint = run.snapshot().checkpoint
    assert checkpoint is not None and checkpoint.summary == ""
    assert checkpoint.covered_through_message_id == history[4].id

    # The same cutoff survives a resumed agent without losing recorded history.
    reloaded = Agent(
        model,
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        state=agent.state,
    )
    reloaded.start(background=False, max_steps=1).result()
    assert model.generations[-1].messages[: len(request.messages)] == request.messages
    assert reloaded.state.messages[: len(history)] == history


@pytest.mark.parametrize("total_timeout", [None, 71, 500])
def test_summary_batches_share_deadline_and_fall_back_to_truncation(
    total_timeout: int | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    elapsed = 0.0
    time_limit = min(total_timeout or SUMMARY_TIMEOUT_SECONDS, SUMMARY_TIMEOUT_SECONDS)
    monkeypatch.setattr("onyx.agents.compaction.monotonic", lambda: elapsed)

    class SlowSummaryModel(ContextModel):
        def invoke(
            self, request: GenerationRequest, context: GenerationContext | None = None
        ) -> AssistantMessage:
            nonlocal elapsed
            response = super().invoke(request, context)
            if context and context.flow == LLMFlow.CHAT_HISTORY_SUMMARIZATION:
                elapsed += time_limit / 2
            return response

    model = SlowSummaryModel()
    agent = Agent(
        model,
        state=AgentState(
            messages=[
                UserMessage(content="Old question"),
                AssistantMessage(content=[TextContent(text="Old evidence " * 3000)]),
                UserMessage(content=TASK),
            ]
        ),
        generation_context=GenerationContext(
            flow=LLMFlow.CHAT_RESPONSE, total_timeout_s=total_timeout
        ),
    )
    history = agent.state.messages
    run = agent.start(background=False, max_steps=1)
    assert run.result().output.text == "Evidence supports the conclusion [1]."
    summary_contexts = [
        context
        for context in model.contexts
        if context.flow == LLMFlow.CHAT_HISTORY_SUMMARIZATION
    ]
    assert [context.total_timeout_s for context in summary_contexts] == [
        time_limit,
        time_limit / 2,
    ]
    assert len(model.generations) == 1
    assert model.generations[0].messages == [history[-1]]
    checkpoint = run.snapshot().checkpoint
    assert checkpoint is not None and checkpoint.summary == ""
    assert checkpoint.covered_through_message_id == history[-2].id
    assert agent.state.messages[:-1] == history


def test_truncation_does_not_drop_oversized_current_tool_result() -> None:
    model = ContextModel()
    history: list[Message] = [
        UserMessage(content="Old question"),
        AssistantMessage(content=[TextContent(text="Old answer")]),
        UserMessage(content=TASK),
        AssistantMessage(content=[ToolCall(id="current", name="lookup", arguments={})]),
        ToolResultMessage(
            tool_call_id="current", tool_name="lookup", content="Evidence " * 2000
        ),
    ]
    agent = Agent(
        model,
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        state=AgentState(messages=history),
    )
    history = agent.state.messages
    with patch(
        "onyx.agents.runtime.compact_history", side_effect=RuntimeError("Failed")
    ):
        run = agent.start(background=False, max_steps=1)
        with pytest.raises(RunFailed):
            run.result()
    assert not model.generations
    assert agent.state.messages == history


def test_failed_summary_does_not_swallow_cancellation() -> None:
    model = ContextModel()
    run = Run.from_snapshot(
        RunState(run_id="run", agent_id="agent", status=RunStatus.COMPLETE, steps=[])
    )
    with patch("onyx.agents.runtime.compact_history", side_effect=AgentCancelled()):
        with pytest.raises(AgentCancelled):
            _compact_context(
                run,
                model,
                [UserMessage(content="old"), UserMessage(content=TASK)],
                PreparedStep(),
                GenerationContext(),
                force=True,
            )


def test_checkpoint_cannot_split_completed_tool_calls() -> None:
    messages: list[Message] = [
        AssistantMessage(
            id="generation",
            content=[ToolCall(id="call", name="lookup", arguments={})],
        ),
        ToolResultMessage(
            id="result", tool_call_id="call", tool_name="lookup", content="evidence"
        ),
        UserMessage(id="next", content="Continue"),
    ]
    with pytest.raises(CheckpointMismatchError, match="splits a tool exchange"):
        working_messages(
            messages,
            CompactionCheckpoint(
                summary="Evidence", covered_through_message_id="generation"
            ),
        )
    compacted = working_messages(
        messages,
        CompactionCheckpoint(summary="Evidence", covered_through_message_id="result"),
    )
    assert compacted == [
        SystemMessage(content="Conversation summary:\nEvidence"),
        messages[-1],
    ]


@pytest.mark.parametrize("parent_run_id", [None, "parent"])
@pytest.mark.parametrize("summary", ["", "Prior evidence"])
def test_compaction_identity_survives_suspension_and_resume(
    parent_run_id: str | None,
    summary: str,
) -> None:
    model = ContextModel(tool_rounds=1)
    checkpoint = CompactionCheckpoint(
        summary=summary, covered_through_message_id="old-answer"
    )
    tools = [
        AgentTool(
            definition=ToolDefinition(
                name="lookup",
                description="Read evidence",
                parameters={"type": "object", "properties": {}},
            ),
            execute=lambda _: ToolResult(content="New evidence"),
        )
    ]
    agent = Agent(
        model,
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=tools,
        state=AgentState(
            messages=[
                UserMessage(id="old-question", content="Earlier question"),
                AssistantMessage(
                    id="old-answer", content=[TextContent(text="Evidence")]
                ),
            ],
            checkpoint=checkpoint,
        ),
        before_tool_call=lambda _: PendingToolInput(
            request_id="approval", prompt="Read evidence?", mode=InputMode.EXECUTE
        ),
    )
    run = agent.start(
        max_steps=2,
        background=False,
        messages=[UserMessage(id="supplied-id", content=TASK)],
        parent_run_id=parent_run_id,
    )
    assert run.status == RunStatus.SUSPENDED
    assert run.wait_for_idle(2)
    captured = run.handoff()
    saved = ExecutionCheckpoint.model_validate_json(captured.model_dump_json())
    input_id = f"run:{run.id}:input:0" if parent_run_id else "supplied-id"
    assert saved.run_state.input_messages[0].id == input_id
    restored = Agent(
        model,
        tools=tools,
        state=saved.agent_state,
        agent_id=agent.id,
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    )
    resumed = restored.resume(saved.run_state)
    resumed.submit(
        HumanToolAnswer(request_id="approval", decision=InputDecision.APPROVE)
    )
    resumed.result(timeout=3)
    assert resumed.wait_for_idle(2)
    state = resumed.snapshot()
    assert state.input_messages[0].id == input_id
    assert state.checkpoint == checkpoint
    result = state.steps[0].tools["call-1"].result
    assert result is not None
    assert result.id == f"{state.steps[0].message.id}:result:call-1"
    assert model.generations[-1].messages[0].text == (
        f"Conversation summary:\n{summary}" if summary else TASK
    )


def test_long_requests_reuse_counts_and_release_removed_history() -> None:
    class LargeContextModel(ContextModel):
        @property
        def config(self) -> LLMConfig:
            return super().config.model_copy(update={"max_input_tokens": 128000})

    source: list[Message] = [UserMessage(content="Compare these sources.")]
    for index in range(350):
        source.extend(
            [
                AssistantMessage(
                    content=[
                        TextContent(text=f"Checking source {index}."),
                        ToolCall(
                            id=f"call-{index}",
                            name="search",
                            arguments={"query": f"source {index}"},
                        ),
                    ]
                ),
                ToolResultMessage(
                    tool_call_id=f"call-{index}",
                    tool_name="search",
                    content=f"Source {index} contains useful evidence.",
                ),
            ]
        )
    source.append(UserMessage(content=TASK))
    run = Run(
        RunState(run_id="run", agent_id="agent", status=RunStatus.RUNNING),
        CancellationSignal(),
    )
    model = LargeContextModel()
    encoder = Mock(wraps=tiktoken.get_encoding("cl100k_base"))
    with patch("onyx.agents.compaction._encoder", return_value=encoder):
        for _ in range(2):
            request = _compact_context(
                run,
                model,
                [message.model_copy(deep=True) for message in source],
                PreparedStep(),
                GenerationContext(),
            )
            assert len(request.messages) == len(source)
            assert len(run._token_counts) > 1024
            assert encoder.encode.call_count == len(run._token_counts)

        encoded = encoder.encode.call_count
        _compact_context(run, model, source[-3:], PreparedStep(), GenerationContext())
        assert encoder.encode.call_count == encoded
        last_message = source[-3]
        assert isinstance(last_message, AssistantMessage)
        assert set(run._token_counts) == {
            "",
            last_message.text,
            last_message.tool_calls[0].model_dump_json(),
            source[-2].text,
            TASK,
        }


def test_rebuilt_prompts_reuse_counts_and_recount_changed_content() -> None:
    evidence = "Retrieved evidence from search. " * 20
    revised_evidence = evidence + "New information. " * 10
    system = "Use the evidence to answer."
    tokenizer = tiktoken.get_encoding("cl100k_base")
    sdk_encoder = Mock(wraps=tokenizer)
    with patch("onyx.agents.compaction._encoder", return_value=sdk_encoder):
        # Each run and model counter must own its cache independently.
        for _ in range(2):
            model = ContextModel(tool_rounds=2)

            tool = AgentTool(
                definition=ToolDefinition(
                    name="lookup", description="Search", parameters={}
                ),
                execute=lambda _: ToolResult(content=evidence),
            )

            def prepare(state: StepInput, tool: AgentTool = tool) -> PreparedStep:
                tool.definition = tool.definition.model_copy(
                    update={
                        "description": "Search updated sources"
                        if state.step.index == 2
                        else "Search"
                    }
                )

                def assemble(messages: Sequence[Message]) -> list[Message]:
                    updated_messages = [
                        message.model_copy(update={"content": revised_evidence})
                        if isinstance(message, ToolResultMessage)
                        and state.step.index == 2
                        else message
                        for message in messages
                    ]
                    return [SystemMessage(content=system), *updated_messages]

                return PreparedStep(tools=[tool], assemble_messages=assemble)

            agent = Agent(
                model,
                generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
                state=AgentState(messages=[UserMessage(content=TASK)]),
                tools=[tool],
                prepare_step=prepare,
            )
            run = agent.start(background=False, max_steps=3)
            assert run.result().output.text == "Evidence supports the conclusion [1]."
            assert run.wait_for_idle(timeout=5)
            assert len(model.generations) == 3
            assert not model.summaries
            assert not run._token_counts
            assert [
                message.content
                for message in model.generations[-1].messages
                if isinstance(message, ToolResultMessage)
            ] == [revised_evidence, revised_evidence]
            assert [
                message.content
                for message in agent.state.messages
                if isinstance(message, ToolResultMessage)
            ] == [evidence, evidence]

    sdk_inputs = [call.args[0] for call in sdk_encoder.encode.call_args_list]
    # Each text is encoded once per counter, even across copied prompt messages.
    for text in (TASK, system, evidence, revised_evidence):
        assert sdk_inputs.count(text) == 2
    for request in model.generations:
        assert sdk_inputs.count(request.tools[0].model_dump_json()) == 2


def test_truncation_validates_boundaries_once_across_candidates() -> None:
    history: list[Message] = [
        SystemMessage(id="system", content="Keep the system instructions."),
        UserMessage(id="old-user", content="Old question " * 300),
        AssistantMessage(
            id="old-answer", content=[TextContent(text="Old answer " * 300)]
        ),
        SystemMessage(id="later-system", content="Keep these instructions too."),
        UserMessage(id="middle-user", content="Middle question " * 300),
        AssistantMessage(
            id="middle-answer", content=[TextContent(text="Middle answer " * 300)]
        ),
        UserMessage(id="current-user", content=TASK),
        AssistantMessage(
            id="current-tool-call",
            content=[ToolCall(id="current", name="lookup", arguments={})],
        ),
        ToolResultMessage(
            id="current-tool-result",
            tool_call_id="current",
            tool_name="lookup",
            content="Current evidence",
        ),
    ]
    original = [message.model_copy(deep=True) for message in history]
    candidates: list[list[Message]] = []

    def assemble(messages: Sequence[Message]) -> list[Message]:
        candidates.append(list(messages))
        return list(messages)

    prepared = PreparedStep(assemble_messages=assemble)
    expected = [history[0], history[3], *history[6:]]
    input_limit = request_tokens(GenerationRequest(messages=expected))
    boundary_scan = Mock(wraps=history_boundaries)
    with (
        patch("onyx.agents.runtime.history_boundaries", boundary_scan),
        patch("onyx.agents.compaction.history_boundaries", boundary_scan),
    ):
        checkpoint, request, size = _truncate_context(
            CancellationSignal(),
            history,
            prepared,
            token_counts={},
            input_limit=input_limit,
            original_size=request_tokens(GenerationRequest(messages=history)),
        )
    assert boundary_scan.call_count == 1
    assert len(candidates) == 3
    assert checkpoint.summary == ""
    assert checkpoint.covered_through_message_id == "middle-answer"
    assert request.messages == expected
    assert request.messages == working_messages(history, checkpoint)
    assert size <= input_limit
    assert history == original


def test_context_rejection_after_thinking_does_not_restart_generation() -> None:
    calls = 0

    class ThinkingClient(FakeModelClient):
        def stream(
            self, request: GenerationRequest, context: GenerationContext | None = None
        ) -> Generator[GenerationEvent, None, None]:
            nonlocal calls
            del request, context
            calls += 1
            yield ThinkingDeltaEvent(content_index=0, text="Partial reasoning")
            raise LLMContextLimitError("Provider rejected context")

    agent = Agent(
        ThinkingClient(lambda *_: AssistantMessage()),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    )
    events: list[AgentEvent] = []
    run = agent.start(
        background=False,
        max_steps=1,
        messages=[UserMessage(content="Question")],
        on_event=events.append,
    )
    with pytest.raises(RunFailed):
        run.result(2)
    assert run.wait_for_idle(2)
    assert calls == 1
    state = run.snapshot()
    assert state.steps[0].message.thinking == "Partial reasoning"
    assert len([e for e in events if e.type == "message_start"]) == 1
    ends = [e for e in events if e.type == "message_end"]
    assert len(ends) == 1
    assert ends[0].message == state.steps[0].message


def test_compaction_rejects_missing_cutoff_identity_before_model_work() -> None:
    model = ContextModel()
    history: list[Message] = [
        AssistantMessage(content=[TextContent(text="Old evidence. " * 600)]),
        UserMessage(id="question", content="Continue"),
    ]
    with pytest.raises(ContextLimitError, match="source message has no identity"):
        compact_history(model, history, None, GenerationContext())
    assert model.summaries == []
    assert model.generations == []


def test_checkpoint_cannot_cover_unanswered_input_across_system_messages() -> None:
    messages: list[Message] = [
        UserMessage(id="file", content="New attachment contents"),
        SystemMessage(content="Use the supplied evidence."),
        UserMessage(id="question", content="Read the attachment."),
    ]
    checkpoint = CompactionCheckpoint(
        summary="File reference", covered_through_message_id="file"
    )
    with pytest.raises(CheckpointMismatchError, match="unanswered input"):
        working_messages(messages, checkpoint)

    messages.append(
        AssistantMessage(id="answer", content=[TextContent(text="Findings")])
    )
    assert working_messages(messages, checkpoint) == [
        SystemMessage(content="Conversation summary:\nFile reference"),
        *messages[1:],
    ]
