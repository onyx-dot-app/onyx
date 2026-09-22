"""Pydantic AI orchestration for the existing chat packet protocol.

The model callback emits Onyx packets while Pydantic AI owns graph traversal,
tool dispatch, termination, and request limits. Each run owns its callbacks and
state; no tenant credentials or conversation data live on a shared agent.
"""

from __future__ import annotations

# Native execution keeps the provider messages as the agent's source of truth.
import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, replace
from functools import partial, wraps
from typing import Any, NamedTuple, ParamSpec

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from pydantic import TypeAdapter
from pydantic_ai import Agent, CancellationToken, ModelRetry, RunContext, Tool
from pydantic_ai import messages as pm
from pydantic_ai.capabilities import AbstractCapability, Hooks
from pydantic_ai.models import (
    ModelRequestContext,
    ModelRequestParameters,
    StreamedResponse,
)
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness import (
    ClearToolResults,
    SlidingWindowCompaction,
    SubAgent,
    SubAgents,
    TieredCompaction,
)
from pydantic_ai_harness.compaction import (
    estimate_context_tokens,
    estimate_token_count,
)
from pydantic_ai_harness.subagents import SubAgentToolset

from onyx.chat.agent_memory import OnyxMemoryProgress
from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.emitter import Emitter
from onyx.chat.token_budget import resolve_chat_token_budget
from onyx.context.search.models import SearchDoc
from onyx.llm.interfaces import LLM
from onyx.llm.request_context import get_llm_request_params, set_llm_request_params
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    AgentEventPhase,
    AnswerMetadata,
    Packet,
    PydanticAIEvent,
)
from onyx.tools.progress import (
    OnyxToolProgress,
    check_tool_run_active,
    route_tool_progress,
)
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.traces import TraceContentMode
from onyx.tracing.llm_utils import llm_generation_span


def count_tool_schema_tokens(
    tools: list[ToolDefinition], tokenizer: Callable[[str], int] | None
) -> int:
    text = TypeAdapter(list[ToolDefinition]).dump_json(tools).decode()
    return tokenizer(text) if tokenizer else (len(text) + 3) // 4


def request_instruction_tokens(
    parameters: ModelRequestParameters, tokenizer: Callable[[str], int] | None
) -> int:
    return estimate_token_count(
        [
            pm.ModelRequest(
                parts=[],
                instructions="\n\n".join(
                    part.content for part in parameters.instruction_parts or []
                ),
            )
        ],
        tokenizer,
    )


def estimate_request_tokens(
    messages: list[pm.ModelMessage],
    parameters: ModelRequestParameters,
    tokenizer: Callable[[str], int] | None,
) -> int:
    # Provider usage describes the previous request, before history compaction.
    counted = [
        replace(message, instructions=None)
        if isinstance(message, pm.ModelRequest)
        and parameters.instruction_parts is not None
        else message
        for message in messages
    ]
    return (
        estimate_token_count(counted, tokenizer)
        + count_tool_schema_tokens(parameters.function_tools, tokenizer)
        + request_instruction_tokens(parameters, tokenizer)
    )


@dataclass
class RequestCompaction(AbstractCapability[None]):
    input_budget: int
    tokenizer: Callable[[str], int] | None

    async def before_model_request(
        self, ctx: RunContext[None], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        original = request_context.messages
        systems: list[pm.ModelMessage] = []
        context: list[pm.ModelMessage] = []
        reminders: list[pm.ModelMessage] = []
        conversation: list[pm.ModelMessage] = []
        for message in original:
            metadata = message.metadata or {}
            if isinstance(message, pm.ModelRequest) and any(
                isinstance(part, pm.SystemPromptPart) for part in message.parts
            ):
                systems.append(message)
            elif metadata.get("onyx_reminder"):
                reminders.append(message)
            elif metadata.get("onyx_prompt"):
                context.append(message)
            else:
                conversation.append(message)
        schema_tokens = count_tool_schema_tokens(
            request_context.model_request_parameters.function_tools, self.tokenizer
        )
        required_tokens = estimate_token_count(
            [
                replace(message, instructions=None)
                if isinstance(message, pm.ModelRequest)
                else message
                for message in [*systems, *context, *reminders]
            ],
            self.tokenizer,
        )
        instruction_tokens = request_instruction_tokens(
            request_context.model_request_parameters, self.tokenizer
        )
        history_budget = (
            self.input_budget - schema_tokens - required_tokens - instruction_tokens
        )
        if history_budget <= 0:
            raise ValueError(
                "The tool definitions and required context exceed the model input token limit."
            )
        parameters = request_context.model_request_parameters
        if parameters.instruction_parts is not None:
            if not any(part.content for part in parameters.instruction_parts):
                conversation = [
                    replace(message, instructions=None)
                    if isinstance(message, pm.ModelRequest)
                    else message
                    for message in conversation
                ]
            if conversation and isinstance(conversation[-1], pm.ModelRequest):
                conversation[-1] = replace(
                    conversation[-1],
                    instructions="\n\n".join(
                        part.content for part in parameters.instruction_parts
                    ),
                )
        # Usage anchors include the protected prompt and schemas from the previous request.
        # Unanchored estimates include only schemas revealed through availability messages.
        target_tokens = (
            self.input_budget
            if any(
                isinstance(message, pm.ModelResponse) and message.usage.input_tokens
                for message in conversation
            )
            else (
                self.input_budget
                - required_tokens
                - schema_tokens
                + estimate_context_tokens(
                    conversation, self.tokenizer, model_request_parameters=parameters
                )
                - estimate_token_count(conversation, self.tokenizer)
            )
        )
        request_context.messages = conversation
        strategy = TieredCompaction[None](
            tiers=[
                ClearToolResults[None](
                    max_tokens=self.input_budget, keep_pairs=3, tokenizer=self.tokenizer
                ),
                SlidingWindowCompaction[None](
                    max_tokens=self.input_budget,
                    keep_tokens=max(1, int(history_budget * 0.8)),
                    preserve_first_user_message=False,
                    tokenizer=self.tokenizer,
                ),
            ],
            target_tokens=target_tokens,
            tokenizer=self.tokenizer,
        )
        compacted = await strategy.before_model_request(ctx, request_context)
        user_indices = [
            index
            for index, message in enumerate(compacted.messages)
            if isinstance(message, pm.ModelRequest)
            and any(isinstance(part, pm.UserPromptPart) for part in message.parts)
        ]
        insertion = user_indices[-1] if user_indices else len(compacted.messages)
        compacted.messages = [
            *systems,
            *compacted.messages[:insertion],
            *context,
            *compacted.messages[insertion:],
            *reminders,
        ]
        return compacted


def transform_citation_event(
    event: pm.AgentStreamEvent,
    answer: str,
    display_text: Callable[[str | None], str],
    emitter: Emitter,
    current_placement: Placement,
    phase: AgentEventPhase,
    part_answers: dict[int, str],
) -> tuple[pm.AgentStreamEvent, str]:
    event_adapter = TypeAdapter(pm.AgentStreamEvent)
    if isinstance(event, pm.PartStartEvent) and isinstance(event.part, pm.TextPart):
        text = display_text(event.part.content)
        answer += text
        part_answers[event.index] = text
        event = replace(event, part=replace(event.part, content=text))
    elif isinstance(event, pm.PartDeltaEvent) and isinstance(
        event.delta, pm.TextPartDelta
    ):
        text = display_text(event.delta.content_delta)
        answer += text
        part_answers[event.index] = part_answers.get(event.index, "") + text
        event = replace(event, delta=replace(event.delta, content_delta=text))
    elif isinstance(event, pm.PartEndEvent) and isinstance(event.part, pm.TextPart):
        tail = display_text(None)
        if tail:
            answer += tail
            part_answers[event.index] = part_answers.get(event.index, "") + tail
            emitter.emit(
                Packet(
                    placement=current_placement,
                    obj=PydanticAIEvent(
                        phase=phase,
                        event=event_adapter.dump_python(
                            pm.PartDeltaEvent(
                                index=event.index, delta=pm.TextPartDelta(tail)
                            ),
                            mode="json",
                        ),
                    ),
                )
            )
        event = replace(
            event, part=replace(event.part, content=part_answers.get(event.index, ""))
        )
    return event, answer


def update_stream_state(
    state: ChatStateContainer | None, answer: str, reasoning: str
) -> None:
    if state is not None:
        if answer:
            state.set_answer_tokens(answer)
        if reasoning:
            state.set_reasoning_tokens(reasoning)


async def emit_agent_events(
    events: AsyncIterable[pm.AgentStreamEvent],
    *,
    emitter: Emitter,
    state_container: ChatStateContainer | None,
    placement: Callable[[], Placement],
    citation_processor: DynamicCitationProcessor | None,
    final_documents: Callable[[], list[SearchDoc] | None] | None,
    elapsed_seconds: Callable[[], float] | None,
    event_phase: Callable[[], AgentEventPhase] | None,
) -> None:
    event_adapter = TypeAdapter(pm.AgentStreamEvent)
    answer = ""
    reasoning = ""
    section_offset = 0
    previous_section: str | None = None
    answer_started = False
    part_answers: dict[int, str] = {}
    base_placement = placement().model_copy()
    phase = event_phase() if event_phase else "chat"
    is_answer = (
        phase in {"chat", "clarification", "report"}
        and base_placement.sub_turn_index is None
    )

    def display_text(text: str | None, current: Placement) -> str:
        if citation_processor is None:
            return text or ""
        fragments: list[str] = []
        for fragment in citation_processor.process_token(text):
            if isinstance(fragment, str):
                fragments.append(fragment)
            else:
                emitter.emit(Packet(placement=current, obj=fragment))
                if state_container is not None:
                    state_container.add_emitted_citation(fragment.citation_number)
                    state_container.set_citation_mapping(
                        citation_processor.citation_to_doc
                    )
        return "".join(fragments)

    async for event in events:
        check_tool_run_active()
        if state_container is not None:
            state_container.set_request_params(get_llm_request_params())
        if isinstance(event, (OnyxToolProgress, OnyxMemoryProgress)):
            emitter.emit(Packet(placement=event.placement, obj=event.obj))
            continue
        section: str | None = None
        if isinstance(event, pm.PartStartEvent):
            if isinstance(event.part, pm.TextPart):
                section = "text"
            elif isinstance(event.part, pm.ThinkingPart):
                reasoning += event.part.content
                section = "thinking"
        elif isinstance(event, pm.PartDeltaEvent):
            if isinstance(event.delta, pm.TextPartDelta):
                section = "text"
            elif isinstance(event.delta, pm.ThinkingPartDelta):
                reasoning += event.delta.content_delta or ""
                section = "thinking"
        if section is not None:
            if previous_section is not None and section != previous_section:
                section_offset += 1
            previous_section = section
        current_placement = base_placement.model_copy()
        if current_placement.sub_turn_index is None:
            current_placement.turn_index += section_offset
        else:
            current_placement.sub_turn_index += section_offset
        if section == "text" and not answer_started and is_answer:
            answer_started = True
            elapsed = elapsed_seconds() if elapsed_seconds else None
            if state_container is not None and elapsed is not None:
                state_container.set_pre_answer_processing_time(elapsed)
            emitter.emit(
                Packet(
                    placement=current_placement,
                    obj=AnswerMetadata(
                        final_documents=final_documents() if final_documents else None,
                        pre_answer_processing_seconds=elapsed,
                    ),
                )
            )
        event, answer = transform_citation_event(
            event,
            answer,
            partial(display_text, current=current_placement),
            emitter,
            current_placement,
            phase,
            part_answers,
        )
        update_stream_state(
            state_container,
            answer if is_answer else "",
            reasoning if is_answer else reasoning + answer,
        )
        emitter.emit(
            Packet(
                placement=current_placement,
                obj=PydanticAIEvent(
                    phase=phase, event=event_adapter.dump_python(event, mode="json")
                ),
            )
        )


class NativeAgentRequest(NamedTuple):
    messages: list[pm.ModelMessage]
    settings: ModelSettings
    tools: list[ToolDefinition]
    allow_tools: bool = True


def build_native_agent(
    *,
    llm: LLM,
    prepare_step: Callable[[list[pm.ModelMessage]], NativeAgentRequest],
    finalize_step: Callable[[pm.ModelResponse], None],
    execute_tool: Callable[[pm.ToolCallPart], str] | None = None,
    execute_tool_async: Callable[[RunContext[None], pm.ToolCallPart], Awaitable[str]]
    | None = None,
    tool_definitions: list[dict[str, Any]],
    max_requests: int,
    emitter: Emitter,
    state_container: ChatStateContainer | None,
    placement: Callable[[], Placement],
    message_history: list[pm.ModelMessage],
    citation_processor: DynamicCitationProcessor | None = None,
    final_documents: Callable[[], list[SearchDoc] | None] | None = None,
    elapsed_seconds: Callable[[], float] | None = None,
    capabilities: list[AbstractCapability[None]] | None = None,
    tokenizer: Callable[[str], int] | None = None,
    flow: LLMFlow = LLMFlow.CHAT_RESPONSE,
    agent_name: str | None = None,
    event_phase: Callable[[], AgentEventPhase] | None = None,
    total_timeout: float | None = None,
    sequential_tool_names: frozenset[str] = frozenset(),
) -> NativeAgentRun:
    async def prepare_request(
        _context: RunContext[None], request: ModelRequestContext
    ) -> ModelRequestContext:
        prepared = await asyncio.to_thread(prepare_step, request.messages)
        configured_names = {
            definition["function"]["name"] for definition in tool_definitions
        }
        capability_tools = [
            tool
            for tool in request.model_request_parameters.function_tools
            if tool.name not in configured_names
        ]
        request.messages = prepared.messages
        request.model_settings = prepared.settings
        request.model_request_parameters = replace(
            request.model_request_parameters,
            function_tools=[*prepared.tools, *capability_tools]
            if prepared.allow_tools
            else [],
        )
        return request

    class MeteredModel(WrapperModel):
        @asynccontextmanager
        async def request_stream(
            self,
            messages: list[pm.ModelMessage],
            model_settings: ModelSettings | None,
            model_request_parameters: ModelRequestParameters,
            run_context: RunContext[Any] | None = None,
        ) -> AsyncIterator[StreamedResponse]:
            parameters = model_request_parameters
            if estimate_request_tokens(messages, parameters, tokenizer) > input_budget:
                raise ValueError(
                    "The current question, tool definitions, and required context exceed the model input limit."
                )
            with llm_generation_span(
                llm,
                flow,
                input_messages=pm.ModelMessagesTypeAdapter.dump_python(
                    messages, mode="json"
                ),
            ) as span:
                async with self.wrapped.request_stream(
                    messages, model_settings, parameters, run_context
                ) as stream:
                    try:
                        yield stream
                        check_tool_run_active()
                        finalize_step(stream.get())
                    finally:
                        usage = stream.usage
                        if span.content_mode == TraceContentMode.FULL:
                            span.span_data.output = (
                                pm.ModelMessagesTypeAdapter.dump_python(
                                    [stream.get()], mode="json"
                                )
                            )
                        span.span_data.usage = {
                            "input_tokens": usage.input_tokens,
                            "output_tokens": usage.output_tokens,
                            "cache_read_input_tokens": usage.cache_read_tokens,
                            "cache_creation_input_tokens": usage.cache_write_tokens,
                        }
                        await asyncio.to_thread(llm.record_usage, usage)

    async def dispatch_tool(context: RunContext[None], **arguments: Any) -> str:
        if context.tool_call_id is None or context.tool_name is None:
            raise ValueError("Tool execution requires a name and call identifier.")
        call = pm.ToolCallPart(
            tool_name=context.tool_name,
            args=arguments,
            tool_call_id=context.tool_call_id,
        )
        with route_tool_progress(context):
            if execute_tool_async is not None:
                return await execute_tool_async(context, call)
            if execute_tool is None:
                raise ValueError("No tool executor is configured")
            return await asyncio.to_thread(execute_tool, call)

    async def emit_events(
        context: RunContext[None], events: AsyncIterable[pm.AgentStreamEvent]
    ) -> None:
        del context
        await emit_agent_events(
            events,
            emitter=emitter,
            state_container=state_container,
            placement=placement,
            citation_processor=citation_processor,
            final_documents=final_documents,
            elapsed_seconds=elapsed_seconds,
            event_phase=event_phase,
        )

    def create_tool(definition: dict[str, Any]) -> Tool[None]:
        function = definition["function"]
        schema_validator = Draft202012Validator(function["parameters"])

        def validate_arguments(_context: RunContext[None], **arguments: Any) -> None:
            try:
                schema_validator.validate(arguments)
            except ValidationError as error:
                raise ModelRetry(error.message) from error

        return Tool.from_schema(
            function=dispatch_tool,
            name=function["name"],
            description=function.get("description"),
            json_schema=function["parameters"],
            takes_ctx=True,
            sequential=function["name"] in sequential_tool_names,
            args_validator=validate_arguments,
        )

    agent_tools = [create_tool(definition) for definition in tool_definitions]
    input_budget = max(1, resolve_chat_token_budget(llm).input_tokens)
    compaction = RequestCompaction(input_budget, tokenizer)
    agent = Agent[None, str](
        MeteredModel(llm.model),
        name=agent_name or flow.value,
        tools=agent_tools,
        capabilities=[
            Hooks(before_model_request=prepare_request),
            *(capabilities or []),
            compaction,
        ],
        retries=2,
    )
    return NativeAgentRun(
        agent=agent,
        event_handler=emit_events,
        message_history=message_history,
        max_requests=max_requests,
        total_timeout=total_timeout,
        emitter=emitter,
    )


@dataclass
class NativeAgentRun:
    agent: Agent[None, str]
    event_handler: Callable[
        [RunContext[None], AsyncIterable[pm.AgentStreamEvent]], Awaitable[None]
    ]
    message_history: list[pm.ModelMessage]
    max_requests: int
    total_timeout: float | None
    emitter: Emitter

    async def delegate(self, context: RunContext[None], task: str) -> str:
        """Keep typed domain tool arguments while native delegation owns the child run."""
        if self.message_history:
            raise ValueError(
                "Native delegates require a self-contained task, not seeded history"
            )
        name = self.agent.name or "delegate"
        # Child cycle limits are independent of coordinator limits. Provider billing remains per request.
        capability = SubAgents[None](
            agents=[
                SubAgent(
                    self.agent,
                    usage_limits=UsageLimits(request_limit=self.max_requests),
                    timeout_seconds=self.total_timeout,
                )
            ],
            agent_folders=None,
            inherit_tools=False,
            event_stream_handler=self.event_handler,
        )
        toolset = capability.get_toolset()
        if not isinstance(toolset, SubAgentToolset):
            raise TypeError("Native delegation requires a subagent toolset")
        async with self.agent:
            return await toolset.delegate_task(context, name, task)

    async def run(self, task: str | None = None) -> str:
        cancellation_token = CancellationToken()

        async def watch_disconnect() -> None:
            while not self.emitter.cancelled:
                try:
                    check_tool_run_active()
                except asyncio.CancelledError:
                    break
                await asyncio.sleep(0.1)
            cancellation_token.cancel()

        watcher = asyncio.create_task(watch_disconnect())
        try:
            async with self.agent, asyncio.timeout(self.total_timeout):
                result = await self.agent.run(
                    task,
                    message_history=self.message_history,
                    event_stream_handler=self.event_handler,
                    usage_limits=UsageLimits(request_limit=self.max_requests),
                    cancellation_token=cancellation_token,
                )
            return result.output
        finally:
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher


_RunParams = ParamSpec("_RunParams")


def _sync_entrypoint(
    factory: Callable[_RunParams, NativeAgentRun],
) -> Callable[_RunParams, str]:
    @wraps(factory)
    def run(*args: _RunParams.args, **kwargs: _RunParams.kwargs) -> str:
        set_llm_request_params({})
        configured = factory(*args, **kwargs)
        with asyncio.Runner() as runner:
            return runner.run(configured.run())

    return run


run_native_agent = _sync_entrypoint(build_native_agent)
