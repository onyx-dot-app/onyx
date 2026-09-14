# TODO: Notes for potential extensions and future improvements:
# 1. Allow tools that aren't search specific tools
# 2. Use user provided custom prompts
# 3. Save the plan for replay
import time
from collections.abc import Callable
from typing import Literal

from onyx.agents.runtime import (
    Agent,
    AgentContext,
    AgentHooks,
    AgentTurn,
    ToolCallContext,
    TurnResult,
)
from onyx.chat.artifacts import project_tool_artifacts
from onyx.chat.chat_state import ChatArtifactSnapshot, ChatStateContainer, SearchDocKey
from onyx.chat.citation_processor import CitationMapping, DynamicCitationProcessor
from onyx.chat.citation_utils import collapse_citations
from onyx.chat.emitter import Emitter, NullEmitter
from onyx.chat.presentation import TurnPresentation
from onyx.chat.prompt_utils import build_language_section, with_language_section
from onyx.chat.renderer import RenderConfig
from onyx.configs.chat_configs import (
    DR_REPORT_LLM_TIMEOUT_S,
    SKIP_DEEP_RESEARCH_CLARIFICATION,
)
from onyx.context.messages import PromptMetadata, prepare_model_messages
from onyx.context.prompt import prepare_prompt
from onyx.context.search.models import SearchDoc
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import SupportedLanguage
from onyx.db.tools import get_tool_by_name
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.deep_research.research_agent import run_research_agent_call
from onyx.deep_research.tool_definitions import (
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TOOL_NAME,
    THINK_TOOL_NAME,
    THINK_TOOL_RESPONSE_MESSAGE,
    get_clarification_tool_definitions,
    get_orchestrator_tools,
)
from onyx.file_store.models import FileToolMetadata
from onyx.llm.cancellation import (
    CancellationSignal,
    cancellation_scope,
    check_cancelled,
    current_cancellation,
)
from onyx.llm.interfaces import LLM, GenerationContext, LLMUserIdentity
from onyx.llm.model_capabilities import model_is_reasoning_model
from onyx.llm.models import (
    AssistantMessage,
    Message,
    ReasoningEffort,
    SystemMessage,
    ToolChoiceOptions,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.prompts.deep_research.orchestration_layer import (
    CLARIFICATION_PROMPT,
    FINAL_REPORT_PROMPT,
    FIRST_CYCLE_REMINDER,
    FIRST_CYCLE_REMINDER_TOKENS,
    INTERNAL_SEARCH_CLARIFICATION_GUIDANCE,
    INTERNAL_SEARCH_RESEARCH_TASK_GUIDANCE,
    ORCHESTRATOR_PROMPT,
    ORCHESTRATOR_PROMPT_REASONING,
    RESEARCH_PLAN_PROMPT,
    RESEARCH_PLAN_REMINDER,
    USER_FINAL_REPORT_QUERY,
)
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    OverallStop,
    Packet,
    SectionEnd,
    TopLevelBranching,
)
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallInfo, ToolCallKickoff
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.tool_runner import LegacyToolContext, bind_tool
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import ChatTraceMetadata, trace
from onyx.utils.logger import setup_logger
from onyx.utils.timing import log_function_time

logger = setup_logger()

MAX_USER_MESSAGES_FOR_CONTEXT = 5
MAX_FINAL_REPORT_TOKENS = 20000

MAX_ORCHESTRATOR_CYCLES = 8

# Reasoning models use internal thinking instead of separate thinking tool calls.
MAX_ORCHESTRATOR_CYCLES_REASONING = 4


def _get_research_agent_tool_id() -> int:
    with get_session_with_current_tenant() as db_session:
        return get_tool_by_name(
            tool_name=RESEARCH_AGENT_TOOL_NAME,
            db_session=db_session,
        ).id


class DeepResearchAgent(Agent):
    """Compose research workers and produce a final report through the shared loop."""

    def __init__(
        self,
        emitter: Emitter | None,
        state_container: ChatStateContainer,
        messages: list[Message],
        allowed_tools: list[Tool],
        llm: LLM,
        token_counter: Callable[[str], int],
        user_identity: LLMUserIdentity | None,
        language_section: str,
        reasoning_effort: ReasoningEffort,
        all_injected_file_metadata: dict[str, FileToolMetadata] | None,
        processing_start_time: float,
        research_plan: str | None,
        orchestrator_start_turn_index: int,
        include_internal_search_tunings: bool,
        skip_clarification: bool = False,
    ) -> None:
        self.emitter = emitter or NullEmitter()
        self.state_container = state_container
        self.allowed_tools = allowed_tools
        self.llm = llm
        self.token_counter = token_counter
        self.user_identity = user_identity
        self.language_section = language_section
        self.reasoning_effort = reasoning_effort
        self.all_injected_file_metadata = all_injected_file_metadata
        self.processing_start_time = processing_start_time
        self.research_plan = research_plan or ""
        self.phase: Literal["clarification", "planning", "research"] = (
            "research"
            if research_plan
            else "planning"
            if skip_clarification
            else "clarification"
        )
        self.prelude_turns = 0 if research_plan else 1 if skip_clarification else 2
        self.research_turns = 0
        self.include_internal_search_tunings = include_internal_search_tunings
        self.orchestrator_start_turn_index = orchestrator_start_turn_index
        self.is_reasoning_model = model_is_reasoning_model(
            self.llm.info.model_name, self.llm.info.model_provider
        )

        self.max_orchestrator_cycles = (
            MAX_ORCHESTRATOR_CYCLES
            if not self.is_reasoning_model
            else MAX_ORCHESTRATOR_CYCLES_REASONING
        )

        self.orchestrator_prompt_template = (
            ORCHESTRATOR_PROMPT
            if not self.is_reasoning_model
            else ORCHESTRATOR_PROMPT_REASONING
        )

        self.internal_search_research_task_guidance = (
            INTERNAL_SEARCH_RESEARCH_TASK_GUIDANCE
            if include_internal_search_tunings
            else ""
        )
        token_count_prompt = self.orchestrator_prompt_template.format(
            current_datetime=get_current_llm_day_time(full_sentence=False),
            current_cycle_count=1,
            max_cycles=self.max_orchestrator_cycles,
            research_plan=self.research_plan,
            internal_search_research_task_guidance=self.internal_search_research_task_guidance,
        )
        self.orchestration_tokens = self.token_counter(token_count_prompt)

        self.reasoning_cycles = 0
        self.most_recent_reasoning: str | None = None
        self.citation_mapping: CitationMapping = {}
        self.report_citations = DynamicCitationProcessor()
        self.available_tokens = llm.info.max_input_tokens
        self.report_turn_index: int | None = None
        self.final_turn_index = orchestrator_start_turn_index
        self.save_report_reasoning = False
        self.research_tool_id: int | None = None

        self.turn = AgentTurn(index=0, limit=1)
        self.requested_final = False
        self.is_final_turn = False
        self.presentation = TurnPresentation(emitter) if emitter is not None else None
        super().__init__(
            self.llm,
            context=AgentContext(
                messages=messages,
                execution=GenerationContext(flow=LLMFlow.DEEP_RESEARCH),
            ),
            hooks=AgentHooks(
                transform_context=self._context,
                before_tool_call=self._before_tool,
                after_turn=self._after_turn,
            ),
        )
        self.state_container.bind_agent(self, self._project_artifacts)
        self.tool_context = LegacyToolContext(lambda: self.context.messages)
        if self.presentation is not None:
            self.subscribe(self.presentation.consume)

    def _context(self, context: AgentContext, turn: AgentTurn) -> AgentContext:
        if self.phase != "research":
            return self._prelude_context(context)
        turn = AgentTurn(
            index=self.research_turns,
            limit=self.research_turns + turn.limit - turn.index,
        )
        self.turn = turn
        self.is_final_turn = self.requested_final or turn.is_last
        context.tools = (
            []
            if self.is_final_turn
            else [
                bind_tool(definition, self._execute_tool, self.tool_context)
                for definition in get_orchestrator_tools(
                    include_think_tool=not self.is_reasoning_model
                )
            ]
        )
        context.options.tool_choice = (
            ToolChoiceOptions.NONE if self.is_final_turn else ToolChoiceOptions.REQUIRED
        )
        placement = Placement(
            turn_index=self.orchestrator_start_turn_index
            + turn.index
            + self.reasoning_cycles
        )
        prompt = with_language_section(
            FINAL_REPORT_PROMPT.format(
                current_datetime=get_current_llm_day_time(full_sentence=False)
            ),
            self.language_section,
        )
        history = (
            self.prepare(turn)
            if not self.is_final_turn
            else prepare_prompt(
                token_counter=self.token_counter,
                system_prompt=SystemMessage(
                    content=prompt,
                    metadata=PromptMetadata(token_count=self.token_counter(prompt)),
                ),
                custom_agent_prompt=None,
                messages=self.context.messages,
                reminder_message=UserMessage(
                    content=USER_FINAL_REPORT_QUERY.format(
                        research_plan=self.research_plan
                    ),
                    metadata=PromptMetadata(token_count=100, is_reminder=True),
                ),
                context_files=None,
                available_tokens=self.llm.info.max_input_tokens,
                all_injected_file_metadata=self.all_injected_file_metadata,
            )
        )
        processor = DynamicCitationProcessor()
        processor.update_citation_mapping(self.citation_mapping)
        self.report_citations = processor
        context.options.max_tokens = (
            MAX_FINAL_REPORT_TOKENS if self.is_final_turn else 1024
        )
        context.execution.timeout = (
            DR_REPORT_LLM_TIMEOUT_S if self.is_final_turn else None
        )
        context.options.reasoning_effort = self.reasoning_effort
        config = RenderConfig(
            placement=placement,
            citations=processor if self.is_final_turn else None,
            documents=list(processor.citation_to_doc.values())
            if self.is_final_turn
            else None,
            text_as_thinking=not self.is_final_turn,
            think_tool=THINK_TOOL_NAME if not self.is_reasoning_model else None,
            pre_answer_seconds=time.monotonic() - self.processing_start_time,
        )
        if self.presentation is not None:
            self.presentation.configure(config, self.state_container)
        context.execution.user_identity = self.user_identity
        context.messages = history
        context.messages = prepare_model_messages(context.messages, self.llm.info)
        return context

    def prepare(self, turn: AgentTurn) -> list[Message]:
        if turn.index == 1:
            first_cycle_reminder_message = UserMessage(
                content=FIRST_CYCLE_REMINDER,
                metadata=PromptMetadata(
                    token_count=FIRST_CYCLE_REMINDER_TOKENS, is_reminder=True
                ),
            )
        else:
            first_cycle_reminder_message = None

        orchestrator_prompt = self.orchestrator_prompt_template.format(
            current_datetime=get_current_llm_day_time(full_sentence=False),
            current_cycle_count=turn.index,
            max_cycles=self.max_orchestrator_cycles,
            research_plan=self.research_plan,
            internal_search_research_task_guidance=self.internal_search_research_task_guidance,
        )

        system_prompt = SystemMessage(
            content=orchestrator_prompt,
            metadata=PromptMetadata(token_count=self.orchestration_tokens),
        )

        truncated_message_history = prepare_prompt(
            token_counter=self.token_counter,
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            messages=self.context.messages,
            reminder_message=first_cycle_reminder_message,
            context_files=None,
            available_tokens=self.available_tokens,
            last_n_user_messages=MAX_USER_MESSAGES_FOR_CONTEXT,
            all_injected_file_metadata=self.all_injected_file_metadata,
        )

        return truncated_message_history

    def _prelude_context(self, context: AgentContext) -> AgentContext:
        clarification = self.phase == "clarification"
        prompt = (
            with_language_section(
                CLARIFICATION_PROMPT.format(
                    current_datetime=get_current_llm_day_time(full_sentence=False),
                    internal_search_clarification_guidance=INTERNAL_SEARCH_CLARIFICATION_GUIDANCE
                    if self.include_internal_search_tunings
                    else "",
                ),
                self.language_section,
            )
            if clarification
            else RESEARCH_PLAN_PROMPT.format(
                current_datetime=get_current_llm_day_time(full_sentence=False)
            )
        )
        context.messages = prepare_prompt(
            token_counter=self.token_counter,
            system_prompt=SystemMessage(
                content=prompt,
                metadata=PromptMetadata(token_count=self.token_counter(prompt)),
            ),
            custom_agent_prompt=None,
            messages=context.messages,
            reminder_message=None
            if clarification
            else UserMessage(
                content=RESEARCH_PLAN_REMINDER, metadata=PromptMetadata(token_count=100)
            ),
            context_files=None,
            available_tokens=self.available_tokens,
            last_n_user_messages=MAX_USER_MESSAGES_FOR_CONTEXT + int(not clarification),
            all_injected_file_metadata=self.all_injected_file_metadata,
        )
        context.tools = (
            [
                bind_tool(definition, self._execute_tool, self.tool_context)
                for definition in get_clarification_tool_definitions()
            ]
            if clarification
            else []
        )
        context.options.tool_choice = (
            ToolChoiceOptions.AUTO if clarification else ToolChoiceOptions.NONE
        )
        context.execution.user_identity = self.user_identity
        context.options.reasoning_effort = self.reasoning_effort
        if self.presentation is not None:
            self.presentation.configure(
                RenderConfig(
                    placement=Placement(turn_index=0),
                    mode="answer" if clarification else "plan",
                    pre_answer_seconds=time.monotonic() - self.processing_start_time,
                ),
                self.state_container,
            )
        context.messages = prepare_model_messages(context.messages, self.llm.info)
        return context

    def _before_tool(self, context: ToolCallContext) -> ToolResult | None:
        if self.phase != "research":
            return None
        research_calls = [
            call
            for call in self.tool_context.message().tool_calls
            if call.name == RESEARCH_AGENT_TOOL_NAME
        ]
        if (
            len(research_calls) > 1
            and context.call.id == research_calls[0].id
            and self.presentation is not None
        ):
            self.presentation.emit_tool_packet(
                context.call.id,
                Packet(
                    placement=self.tool_context.kickoff(
                        research_calls[0].id,
                        research_calls[0].name,
                        research_calls[0].arguments,
                    ).placement,
                    obj=TopLevelBranching(num_parallel_branches=len(research_calls)),
                ),
            )
        return None

    def _execute_tool(self, call: ToolCallKickoff) -> ToolResult:
        if self.phase == "clarification":
            return ToolResult(content="Proceed to planning.")
        if call.tool_name == GENERATE_REPORT_TOOL_NAME:
            return ToolResult(content="Ready to produce the final report.")
        if call.tool_name == THINK_TOOL_NAME:
            return ToolResult(content=THINK_TOOL_RESPONSE_MESSAGE)
        if self.research_tool_id is None:
            self.research_tool_id = _get_research_agent_tool_id()
        result = run_research_agent_call(
            research_agent_call=call,
            parent_tool_call_id=call.tool_call_id,
            tools=self.allowed_tools,
            emitter=self.emitter if self.presentation is not None else None,
            llm=self.llm,
            is_reasoning_model=self.is_reasoning_model,
            token_counter=self.token_counter,
            language_section=self.language_section,
            user_identity=self.user_identity,
            reasoning_effort=self.reasoning_effort
            if self.reasoning_effort is not ReasoningEffort.AUTO
            else ReasoningEffort.LOW,
        )
        if result is None:
            return ToolResult(
                content="Research agent call failed. Continue without this result.",
                is_error=True,
            )
        return ToolResult(content=result.intermediate_report, details=result)

    def _project_artifacts(self, messages: list[Message]) -> ChatArtifactSnapshot:
        records: list[ToolCallInfo] = []
        documents: dict[SearchDocKey, SearchDoc] = {}
        assistant: AssistantMessage | None = None
        for message in messages:
            if isinstance(message, AssistantMessage):
                assistant = message
            elif (
                isinstance(message, ToolResultMessage)
                and isinstance(message.details, ResearchAgentCallResult)
                and assistant is not None
            ):
                call = next(
                    call
                    for call in assistant.tool_calls
                    if call.id == message.tool_call_id
                )
                placement = (
                    self.presentation.placement_for(call.id)
                    if self.presentation is not None
                    else Placement(turn_index=0)
                )
                child = project_tool_artifacts(
                    message.details.output_messages,
                    self.allowed_tools,
                    lambda _call_id, placement=placement: placement,
                )
                call_turns = {
                    call.id: index
                    for index, output in enumerate(
                        item
                        for item in message.details.output_messages
                        if isinstance(item, AssistantMessage)
                    )
                    for call in output.tool_calls
                }
                for record in child.tool_calls:
                    relative = message.details.call_placements.get(record.tool_call_id)
                    records.append(
                        record.model_copy(
                            update={
                                "parent_tool_call_id": call.id,
                                "turn_index": (
                                    relative.sub_turn_index
                                    if relative is not None
                                    and relative.sub_turn_index is not None
                                    else relative.turn_index
                                    if relative is not None
                                    else call_turns[record.tool_call_id]
                                ),
                            }
                        )
                    )
                documents.update(child.all_search_docs)
                if self.research_tool_id is None:
                    raise RuntimeError(
                        "Research tool must be initialized before saving its results"
                    )
                records.append(
                    ToolCallInfo(
                        parent_tool_call_id=None,
                        turn_index=placement.turn_index,
                        tab_index=placement.tab_index,
                        tool_name=call.name,
                        tool_call_id=call.id,
                        tool_id=self.research_tool_id,
                        reasoning_tokens=assistant.thinking or None,
                        tool_call_arguments=call.arguments,
                        tool_call_response=message.text,
                    )
                )
        return ChatArtifactSnapshot(
            tool_calls=records,
            all_search_docs=documents,
            citation_to_doc=self.report_citations.citation_to_doc,
        )

    def _after_turn(self, result: TurnResult) -> None:
        if self.phase == "clarification":
            if result.message.tool_calls:
                self.phase = "planning"
            else:
                self.state_container.set_is_clarification(True)
                self.final_turn_index = 0
            return
        if self.phase == "planning":
            self.research_plan = result.message.text
            if not self.research_plan:
                raise RuntimeError("Deep Research failed to generate a research plan")
            self.orchestration_tokens = self.token_counter(
                self.orchestrator_prompt_template.format(
                    current_datetime=get_current_llm_day_time(full_sentence=False),
                    current_cycle_count=1,
                    max_cycles=self.max_orchestrator_cycles,
                    research_plan=self.research_plan,
                    internal_search_research_task_guidance=self.internal_search_research_task_guidance,
                )
            )
            self.orchestrator_start_turn_index = 1 + int(bool(result.message.thinking))
            self.phase = "research"
            self.emitter.emit(
                Packet(
                    placement=Placement(
                        turn_index=self.orchestrator_start_turn_index - 1
                    ),
                    obj=SectionEnd(),
                )
            )
            self.follow_up(
                UserMessage(
                    content="Carry out the research plan and produce the report."
                )
            )
            return
        self.research_turns += 1
        self.reasoning_cycles += int(
            bool(result.message.thinking)
            or any(call.name == THINK_TOOL_NAME for call in result.message.tool_calls)
        )
        if self.is_final_turn:
            if not result.message.text:
                raise ValueError("Model failed to produce the final report")
            self.final_turn_index = (
                self.orchestrator_start_turn_index
                + self.turn.index
                + self.reasoning_cycles
            )
            self.state_container.set_citation_mapping(
                self.report_citations.citation_to_doc
            )
            if self.save_report_reasoning and self.most_recent_reasoning:
                self.state_container.set_reasoning_tokens(self.most_recent_reasoning)
            return
        for response in result.tool_results:
            if response.tool_name == GENERATE_REPORT_TOOL_NAME:
                self.requested_final = True
                self.save_report_reasoning = True
            elif response.tool_name == THINK_TOOL_NAME:
                self.most_recent_reasoning = result.message.thinking or "\n".join(
                    str(call.arguments.get("reasoning", ""))
                    for call in result.message.tool_calls
                    if call.name == THINK_TOOL_NAME
                )
            elif isinstance(response.details, ResearchAgentCallResult):
                report, self.citation_mapping = collapse_citations(
                    answer_text=response.text,
                    existing_citation_mapping=self.citation_mapping,
                    new_citation_mapping=response.details.citation_mapping,
                )
                # Commit citation numbers in call order before the next model request.
                response.content = report
        if not result.message.tool_calls:
            self.requested_final = True
            self.follow_up(
                UserMessage(
                    content="Produce the final report from the available results."
                )
            )


@log_function_time(print_only=True)
def run_deep_research(
    emitter: Emitter | None,
    state_container: ChatStateContainer,
    messages: list[Message],
    tools: list[Tool],
    custom_agent_prompt: str | None,  # noqa: ARG001
    llm: LLM,
    token_counter: Callable[[str], int],
    user_language: SupportedLanguage | None,
    reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
    skip_clarification: bool = False,
    user_identity: LLMUserIdentity | None = None,
    chat_session_id: str | None = None,
    all_injected_file_metadata: dict[str, FileToolMetadata] | None = None,
) -> None:
    agent_emitter = emitter
    emitter = emitter or NullEmitter()
    with (
        cancellation_scope(current_cancellation() or CancellationSignal()),
        trace(
            "run_deep_research",
            group_id=chat_session_id,
            metadata=ChatTraceMetadata(
                chat_session_id=chat_session_id,
                user_id=user_identity.user_id if user_identity else None,
            ).model_dump(),
        ),
    ):
        # Here for lazy load LiteLLM
        from onyx.llm.litellm_singleton.config import initialize_litellm

        # An approximate limit. In extreme cases it may still fail but this should allow deep research
        # to work in most cases.
        if llm.info.max_input_tokens < 50000:
            raise RuntimeError(
                "Cannot run Deep Research with an Model that has less than 50,000 max input tokens"
            )

        check_cancelled()
        initialize_litellm()

        # Track processing start time for tool duration calculation
        processing_start_time = time.monotonic()

        allowed_names = {SearchTool.NAME, WebSearchTool.NAME, OpenURLTool.NAME}
        allowed_tools = [tool for tool in tools if tool.name in allowed_names]
        agent = DeepResearchAgent(
            agent_emitter,
            state_container,
            messages,
            allowed_tools,
            llm,
            token_counter,
            user_identity,
            build_language_section(user_language),
            reasoning_effort,
            all_injected_file_metadata,
            processing_start_time,
            None,
            1,
            any(tool.name == SearchTool.NAME for tool in allowed_tools),
            skip_clarification=SKIP_DEEP_RESEARCH_CLARIFICATION or skip_clarification,
        )
        agent.run(max_turns=agent.max_orchestrator_cycles + agent.prelude_turns)
        check_cancelled()
        emitter.emit(
            Packet(
                placement=Placement(turn_index=agent.final_turn_index),
                obj=OverallStop(type="stop"),
            )
        )
