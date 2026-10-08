"""Context pressure preserves the task, tool effects, and recorded history."""

import threading
from collections.abc import Generator
from unittest.mock import patch

import pytest

from onyx.agents.compaction import (
    IMAGE_TOKEN_ESTIMATE,
    MESSAGE_OVERHEAD_TOKENS,
    CheckpointMismatchError,
    compact_history,
    context_budget,
    count_tokens,
    request_tokens,
    working_messages,
)
from onyx.agents.events import AgentEvent
from onyx.agents.execution_records import (
    CompactionCheckpoint,
    ExecutionStatus,
    RunStatus,
)
from onyx.agents.models import (
    AgentState,
    PreparedStep,
    RunState,
    StepInput,
)
from onyx.agents.runtime import Agent, Run, RunFailed, _compact_context
from onyx.agents.tools import (
    AgentTool,
    HumanToolAnswer,
    InputDecision,
    InputMode,
    PendingToolInput,
    ToolInvocation,
)
from onyx.chat.chat_utils import convert_chat_history
from onyx.chat.files import build_file_context
from onyx.chat.models import ChatHistoryMessage, CheckpointBinding
from onyx.chat.prompt_formatting import prompt_metadata
from onyx.chat.prompt_utils import prepare_prompt
from onyx.configs.constants import MessageType
from onyx.file_store.models import ChatFileType, ChatLoadedFile
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.exceptions import LLMContextLimitError
from onyx.llm.interfaces import LLM, GenerationContext, LLMConfig, LLMUserIdentity
from onyx.llm.models import (
    AssistantMessage,
    GenerationErrorEvent,
    GenerationEvent,
    GenerationOptions,
    GenerationRequest,
    ImageContentPart,
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
from tests.unit.onyx.agents.checkpoint_storage import CheckpointStorage, SavedCheckpoint
from tests.unit.onyx.agents.fakes import message_events

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
            yield ThinkingDeltaEvent(content_index=0, text="Discarded attempt")
            yield GenerationErrorEvent(error_message="Too much context")
            raise
        yield from message_events(message)


def test_compaction_replaces_attachment_body_with_file_reference() -> None:
    model = ContextModel()
    body = "Attachment-only detail. " * 2000
    file = build_file_context(
        tool_file_id="attachment-id",
        filename="report.txt",
        file_type=ChatFileType.PLAIN_TEXT,
        content_text=body,
    )
    findings = "The report supports option A; the user chose option B."

    def assemble(messages: list[Message]) -> list[Message]:
        return prepare_prompt(
            messages,
            system_prompt=None,
            custom_agent_prompt=None,
            reminder_message=None,
            context_files=None,
            token_counter=len,
            all_injected_file_metadata={"attachment-id": file.tool_metadata},
            available_tool_names=set(),
        )

    agent = Agent(
        model,
        state=AgentState(
            messages=[
                file.message,
                UserMessage(content="Compare the options in the attachment."),
                AssistantMessage(content=[TextContent(text=findings)]),
            ]
        ),
        prepare_step=lambda _: PreparedStep(assemble_messages=assemble),
    )
    run = agent.start(messages=[UserMessage(content="Continue. " * 160)], max_steps=1)
    run.result()
    assert run.wait_for_idle(2)

    assert len(model.summaries) == 1
    summary_input = model.summaries[0].messages[0].text
    assert "report.txt" in summary_input
    assert "attachment-id" in summary_input
    assert findings in summary_input
    assert "Attachment-only detail" not in summary_input
    generation_input = "\n".join(m.text for m in model.generations[0].messages)
    assert "report.txt" in generation_input
    assert "no tool here can read them" in generation_input
    assert "Attachment-only detail" not in generation_input
    assert body in file.message.text
    assert body in agent.state.messages[0].text


@pytest.mark.parametrize("long_question", [False, True])
def test_summary_cutoff_survives_request_context_removal(long_question: bool) -> None:
    model = ContextModel()
    old_answer = ChatHistoryMessage(
        id=1,
        message_type=MessageType.ASSISTANT,
        message="Old findings. " * 600,
        token_count=1800,
        files=[],
        is_clarification=False,
        response_messages=[
            AssistantMessage(
                id="old-answer", content=[TextContent(text="Old findings. " * 600)]
            )
        ],
    )
    question = ChatHistoryMessage(
        id=2,
        message_type=MessageType.USER,
        message="Current question. " * (160 if long_question else 1),
        token_count=0,
        files=[],
        is_clarification=False,
        response_messages=[],
    )
    source = convert_chat_history(
        [old_answer, question],
        files=[],
        context_image_files=[],
        additional_context="Temporary request detail. " * 160,
        token_counter=len,
    ).messages
    checkpoint = compact_history(model, source, None, GenerationContext())
    expected_cutoff = "chat:2" if long_question else "old-answer"
    assert checkpoint.covered_through_message_id == expected_cutoff
    summary_input = "\n".join(request.messages[0].text for request in model.summaries)
    assert ("Temporary request detail" in summary_input) == long_question

    next_question = question.model_copy(update={"id": 3, "message": "Next question"})
    reloaded = convert_chat_history(
        [old_answer, question, next_question],
        files=[],
        context_image_files=[],
        additional_context=None,
        token_counter=len,
    ).messages
    restored_checkpoint = CompactionCheckpoint.model_validate_json(
        checkpoint.model_dump_json()
    )
    remaining = working_messages(reloaded, restored_checkpoint)
    assert remaining[0].text == f"Conversation summary:\n{checkpoint.summary}"
    assert remaining[-1].text == "Next question"
    assert [message.id for message in remaining[1:]] == (
        ["chat:3"] if long_question else ["chat:2", "chat:3"]
    )


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

    def render(messages: list[Message]) -> list[Message]:
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
        state=AgentState(messages=[UserMessage(content=TASK)]),
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
            flow=LLMFlow.RESEARCH_AGENT,
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
        LLMFlow.RESEARCH_AGENT,
        LLMFlow.CHAT_HISTORY_SUMMARIZATION,
        LLMFlow.RESEARCH_AGENT,
    ]
    for context in model.contexts:
        assert context.cancellation is signal
        assert context.stall_timeout_s == (step_timeout or 23)
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
    assert agent.generation_context.flow == LLMFlow.RESEARCH_AGENT


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
        generation_context=GenerationContext(stall_timeout_s=23),
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
        model, state=AgentState(messages=[UserMessage(content="mandatory " * 2000)])
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
    source: list[Message] = [UserMessage(id="user", content="Updated file contents")]
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
        max_output_tokens=4096,
        context_tokens=4300,
        safety_tokens=120,
    )
    monkeypatch.setattr("onyx.agents.runtime.resolve_token_budget", lambda _: budget)
    model = ContextModel(reject_first=True)
    agent = Agent(
        model,
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


@pytest.mark.parametrize("supports_images", [False, True])
@pytest.mark.parametrize("stored_image_tokens", [0, 20000])
@pytest.mark.parametrize("configured_input_limit", [1200, 8000, 24000])
def test_image_replay_cost_controls_compaction_and_output_allowance(
    monkeypatch: pytest.MonkeyPatch,
    supports_images: bool,
    stored_image_tokens: int,
    configured_input_limit: int,
) -> None:
    class ImageBudgetModel(ContextModel):
        @property
        def config(self) -> LLMConfig:
            return super().config.model_copy(
                update={
                    "model_name": "image-budget-test",
                    "max_input_tokens": configured_input_limit,
                    "supports_images": supports_images,
                }
            )

    monkeypatch.setattr("onyx.agents.compaction.GEN_AI_INPUT_TOKEN_SAFETY_MARGIN", 0.05)
    monkeypatch.setattr("onyx.llm.token_budget.GEN_AI_INPUT_TOKEN_SAFETY_MARGIN", 0.05)
    monkeypatch.setattr(
        "onyx.llm.token_budget.get_model_map",
        lambda: {
            "openai/image-budget-test": {
                "max_input_tokens": 24000,
                "max_output_tokens": 16000,
            }
        },
    )
    older_text = "Look at this image."
    if configured_input_limit > 1200:
        older_text += " Earlier evidence" * 4000
    image = ChatLoadedFile(
        file_id="old-image",
        content=b"\x89PNG\r\n\x1a\n" + b"\x00" * 16,
        file_type=ChatFileType.IMAGE,
        filename="old-image.png",
        content_text=None,
        token_count=stored_image_tokens,
    )
    question = ChatHistoryMessage(
        id=1,
        message_type=MessageType.USER,
        message=older_text,
        token_count=count_tokens(older_text),
        files=[{"id": image.file_id, "type": ChatFileType.IMAGE}],
        is_clarification=False,
        response_messages=[],
    )
    history = convert_chat_history(
        [
            question,
            question.model_copy(
                update={
                    "id": 2,
                    "message_type": MessageType.ASSISTANT,
                    "files": [],
                    "response_messages": [
                        AssistantMessage(
                            id="old-answer", content=[TextContent(text="Old answer")]
                        )
                    ],
                }
            ),
            question.model_copy(
                update={"id": 3, "message": "Follow-up question", "files": []}
            ),
        ],
        files=[image],
        context_image_files=[],
        additional_context=None,
        token_counter=count_tokens,
    ).messages
    original = [message.model_copy(deep=True) for message in history]
    model = ImageBudgetModel()

    def prepare(_: StepInput) -> PreparedStep:
        return PreparedStep(
            assemble_messages=lambda messages: prepare_prompt(
                messages,
                system_prompt=None,
                custom_agent_prompt=None,
                reminder_message=None,
                context_files=None,
                token_counter=count_tokens,
                llm_config=model.config,
            )
        )

    agent = Agent(model, state=AgentState(messages=history), prepare_step=prepare)
    agent.start(background=False, max_steps=1).result()
    request = model.generations[0]
    compacted = configured_input_limit == 8000 or (
        configured_input_limit == 1200 and supports_images
    )
    assert bool(model.summaries) == compacted
    assert (agent.state.checkpoint is not None) == compacted
    assert any(message.text == "Follow-up question" for message in request.messages)
    image_count = sum(
        isinstance(part, ImageContentPart)
        for message in request.messages
        if isinstance(message, UserMessage) and isinstance(message.content, list)
        for part in message.content
    )
    assert image_count == int(supports_images and not compacted)
    if not compacted:
        assert older_text in request.messages[0].text
        if not supports_images:
            assert "old-image" in request.messages[0].text
            assert "does not support image input" in request.messages[0].text
    else:
        assert all(older_text not in message.text for message in request.messages)

    expected_input = (
        sum(
            count_tokens(message.text) + MESSAGE_OVERHEAD_TOKENS
            for message in request.messages
        )
        + image_count * IMAGE_TOKEN_ESTIMATE
    )
    assert request.options.max_tokens == min(
        16000, 24000 - int(configured_input_limit * 0.05) - expected_input
    )
    assert history == original
    assert prompt_metadata(history[0]).image_token_count == stored_image_tokens


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
    agent = Agent(model, state=AgentState(messages=history))
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
    reloaded = Agent(model, state=agent.state)
    reloaded.start(background=False, max_steps=1).result()
    assert model.generations[-1].messages[: len(request.messages)] == request.messages
    assert reloaded.state.messages[: len(history)] == history


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
    agent = Agent(model, state=AgentState(messages=history))
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
    with pytest.raises(CheckpointMismatchError, match="splits a tool call"):
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
    captured = run.capture()
    storage = CheckpointStorage({})
    stored = SavedCheckpoint.model_validate_json(
        storage.save(
            captured.run_state,
            captured.agent_state,
            CheckpointBinding(
                tenant_id="tenant", branch_id="branch", context_version="1"
            ),
        )
    )
    # SQL history can carry an older summary or omit a transient truncation cutoff.
    stored.response.checkpoint = (
        CompactionCheckpoint(
            summary="Outdated", covered_through_message_id="old-question"
        )
        if not summary
        else None
    )
    stored.context.checkpoint = None
    saved = storage.load(stored.model_dump_json())
    input_id = f"run:{run.id}:input:0" if parent_run_id else "supplied-id"
    assert saved.run_state.input_messages[0].id == input_id
    restored = Agent(model, tools=tools, state=saved.agent_state, agent_id=agent.id)
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
