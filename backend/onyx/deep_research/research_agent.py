from collections.abc import Callable

from onyx.agents.runtime import Agent, AgentContext, AgentHooks, AgentTurn, TurnResult
from onyx.chat.citation_processor import (
    CitationMapping,
    CitationMode,
    DynamicCitationProcessor,
)
from onyx.chat.citation_utils import (
    collapse_citations,
    extract_citation_order_from_text,
    update_citation_processor_from_tool_result,
)
from onyx.chat.emitter import Emitter, NullEmitter
from onyx.chat.presentation import TurnPresentation
from onyx.chat.prompt_utils import with_language_section
from onyx.chat.renderer import RenderConfig
from onyx.configs.chat_configs import DR_REPORT_LLM_TIMEOUT_S
from onyx.context.messages import PromptMetadata, prepare_model_messages
from onyx.context.prompt import prepare_prompt
from onyx.context.search.models import SearchDocsResponse
from onyx.deep_research.models import (
    CombinedResearchAgentCallResult,
    ResearchAgentCallResult,
)
from onyx.deep_research.tool_definitions import (
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TASK_KEY,
    THINK_TOOL_NAME,
    THINK_TOOL_RESPONSE_MESSAGE,
    get_research_agent_additional_tool_definitions,
)
from onyx.llm.cancellation import check_cancelled, current_cancellation
from onyx.llm.interfaces import LLM, GenerationContext, LLMUserIdentity
from onyx.llm.models import (
    Message,
    ReasoningEffort,
    SystemMessage,
    ToolCall,
    ToolChoiceOptions,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.prompts.deep_research.dr_tool_prompts import (
    OPEN_URLS_TOOL_DESCRIPTION,
    OPEN_URLS_TOOL_DESCRIPTION_REASONING,
    WEB_SEARCH_TOOL_DESCRIPTION,
)
from onyx.prompts.deep_research.research_agent import (
    MAX_RESEARCH_CYCLES,
    OPEN_URL_REMINDER_RESEARCH_AGENT,
    RESEARCH_AGENT_PROMPT,
    RESEARCH_AGENT_PROMPT_REASONING,
    RESEARCH_REPORT_PROMPT,
    USER_REPORT_QUERY,
)
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.prompts.tool_prompts import INTERNAL_SEARCH_GUIDANCE
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    Packet,
    PacketException,
    ResearchAgentStart,
    StreamingType,
)
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallKickoff
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.utils import extract_url_snippet_map
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.tool_runner import (
    LegacyToolContext,
    bind_tool,
    run_tool_call,
)
from onyx.tools.utils import (
    compute_all_tool_tokens,
    compute_tool_definition_tokens,
    generate_tools_description,
)
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import function_span
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()


# May be good to experiment with this, empirically reports of around 5,000 tokens are pretty good.
MAX_INTERMEDIATE_REPORT_LENGTH_TOKENS = 10000


class ResearchAgent(Agent):
    """Search and report policy for one task, independent of turn scheduling."""

    def __init__(
        self,
        research_agent_call: ToolCall,
        parent_tool_call_id: str,
        tools: list[Tool],
        emitter: Emitter | None,
        llm: LLM,
        is_reasoning_model: bool,
        token_counter: Callable[[str], int],
        user_identity: LLMUserIdentity | None,
        language_section: str,
        reasoning_effort: ReasoningEffort,
        *,
        display_placement: Placement | None = None,
    ) -> None:
        self.parent_tool_call_id = parent_tool_call_id
        self.tools = tools
        self.emitter = emitter or NullEmitter()
        self.llm = llm
        self.is_reasoning_model = is_reasoning_model
        self.token_counter = token_counter
        self.user_identity = user_identity
        self.language_section = language_section
        self.reasoning_effort = reasoning_effort
        display_placement = display_placement or Placement(turn_index=0)
        self.turn_index = display_placement.turn_index
        self.tab_index = display_placement.tab_index
        self.citation_processor = DynamicCitationProcessor(
            citation_mode=CitationMode.KEEP_MARKERS
        )
        self.llm_cycle_count = 0
        self.current_tools = tools
        self.reasoning_cycles = 0
        self.just_ran_web_search = False
        self.research_topic = str(
            research_agent_call.arguments[RESEARCH_AGENT_TASK_KEY]
        )
        messages: list[Message] = [
            UserMessage(
                content=self.research_topic,
                metadata=PromptMetadata(token_count=token_counter(self.research_topic)),
            )
        ]
        self.citation_mapping: dict[int, str] = {}
        self.most_recent_reasoning: str | None = None

        self.turn = AgentTurn(index=0, limit=1)
        self.requested_final = False
        self.is_final_turn = False
        self.presentation = TurnPresentation(emitter) if emitter is not None else None
        super().__init__(
            self.llm,
            context=AgentContext(
                messages=messages,
                execution=GenerationContext(flow=LLMFlow.RESEARCH_AGENT),
            ),
            hooks=AgentHooks(
                transform_context=self._context, after_turn=self._after_turn
            ),
        )
        self.tool_context = LegacyToolContext(lambda: self.context.messages)
        if self.presentation is not None:
            self.subscribe(self.presentation.consume)

    def _context(self, context: AgentContext, turn: AgentTurn) -> AgentContext:
        self.turn = turn
        self.is_final_turn = self.requested_final or turn.is_last
        if self.is_final_turn:
            context.tools = []
            context.options.tool_choice = ToolChoiceOptions.NONE
        else:
            definitions = [
                tool.tool_definition() for tool in self.current_tools
            ] + get_research_agent_additional_tool_definitions(
                include_think_tool=not self.is_reasoning_model
            )
            context.tools = [
                bind_tool(
                    definition,
                    self._execute_tool,
                    self.tool_context,
                    sequential=True,
                )
                for definition in definitions
            ]
            context.options.tool_choice = ToolChoiceOptions.REQUIRED
        placement = Placement(
            turn_index=self.turn_index,
            tab_index=self.tab_index,
            sub_turn_index=None
            if self.is_final_turn
            else self.llm_cycle_count + self.reasoning_cycles,
        )
        prompt = with_language_section(RESEARCH_REPORT_PROMPT, self.language_section)
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
                    content=USER_REPORT_QUERY.format(
                        research_topic=self.research_topic
                    ),
                    metadata=PromptMetadata(token_count=100),
                ),
                context_files=None,
                available_tokens=self.llm.info.max_input_tokens,
            )
        )
        context.options.max_tokens = (
            MAX_INTERMEDIATE_REPORT_LENGTH_TOKENS if self.is_final_turn else 1000
        )
        context.execution.timeout = (
            DR_REPORT_LLM_TIMEOUT_S if self.is_final_turn else None
        )
        context.options.reasoning_effort = self.reasoning_effort
        config = RenderConfig(
            placement=placement,
            nested=True,
            mode="report" if self.is_final_turn else "answer",
            citations=self.citation_processor if self.is_final_turn else None,
            text_as_thinking=not self.is_final_turn,
            think_tool=THINK_TOOL_NAME if not self.is_reasoning_model else None,
        )
        if self.presentation is not None:
            self.presentation.configure(config)
        context.execution.user_identity = self.user_identity
        context.messages = history
        context.messages = prepare_model_messages(context.messages, self.llm.info)
        return context

    def prepare(self, turn: AgentTurn) -> list[Message]:
        tools_description = generate_tools_description(self.current_tools)

        internal_search_tip = (
            INTERNAL_SEARCH_GUIDANCE
            if any(isinstance(tool, SearchTool) for tool in self.current_tools)
            else ""
        )
        web_search_tip = (
            WEB_SEARCH_TOOL_DESCRIPTION
            if any(isinstance(tool, WebSearchTool) for tool in self.current_tools)
            else ""
        )
        has_open_url_tool: bool = any(
            isinstance(tool, OpenURLTool) for tool in self.current_tools
        )
        open_urls_tip = OPEN_URLS_TOOL_DESCRIPTION if has_open_url_tool else ""
        if self.is_reasoning_model and open_urls_tip:
            open_urls_tip = OPEN_URLS_TOOL_DESCRIPTION_REASONING

        system_prompt_template = (
            RESEARCH_AGENT_PROMPT_REASONING
            if self.is_reasoning_model
            else RESEARCH_AGENT_PROMPT
        )
        system_prompt_str = system_prompt_template.format(
            available_tools=tools_description,
            current_datetime=get_current_llm_day_time(full_sentence=False),
            current_cycle_count=turn.index,
            optional_internal_search_tool_description=internal_search_tip,
            optional_web_search_tool_description=web_search_tip,
            optional_open_url_tool_description=open_urls_tip,
        )

        system_prompt = SystemMessage(
            content=system_prompt_str,
            metadata=PromptMetadata(token_count=self.token_counter(system_prompt_str)),
        )

        # Gate the open_url nudge on the tool actually being available.
        if self.just_ran_web_search and has_open_url_tool:
            reminder_message = UserMessage(
                content=OPEN_URL_REMINDER_RESEARCH_AGENT,
                metadata=PromptMetadata(token_count=100),
            )
        else:
            reminder_message = None

        research_agent_tools = get_research_agent_additional_tool_definitions(
            include_think_tool=not self.is_reasoning_model
        )
        tool_token_budget = compute_all_tool_tokens(
            self.current_tools, self.token_counter
        ) + compute_tool_definition_tokens(research_agent_tools, self.token_counter)

        constructed_history = prepare_prompt(
            token_counter=self.token_counter,
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            messages=self.context.messages,
            reminder_message=reminder_message,
            context_files=None,
            available_tokens=max(0, self.llm.info.max_input_tokens - tool_token_budget),
        )

        return constructed_history

    def _execute_tool(self, call: ToolCallKickoff) -> ToolResult:
        if call.tool_name == GENERATE_REPORT_TOOL_NAME:
            self.requested_final = True
            return ToolResult(content="Ready to produce the research report.")
        if call.tool_name == THINK_TOOL_NAME:
            return ToolResult(content=THINK_TOOL_RESPONSE_MESSAGE)
        response = run_tool_call(
            tool_call=call,
            tool=next(
                tool for tool in self.current_tools if tool.name == call.tool_name
            ),
            message_history=self.context.messages,
            user_memory_context=None,
            user_info=None,
            citation_mapping=dict(self.citation_mapping),
            next_citation_num=self.citation_processor.get_next_citation_number()
            + 100 * self.tool_context.index(call.tool_call_id),
            skip_search_query_expansion=False,
            url_snippet_map=extract_url_snippet_map(
                [
                    doc
                    for message in self.context.messages
                    if isinstance(message, ToolResultMessage)
                    if isinstance(data := message.details, SearchDocsResponse)
                    for doc in data.search_docs
                ]
            ),
        )
        return response

    def _after_turn(self, result: TurnResult) -> None:
        self.reasoning_cycles += int(
            bool(result.message.thinking)
            or any(call.name == THINK_TOOL_NAME for call in result.message.tool_calls)
        )
        if self.is_final_turn:
            return
        self.just_ran_web_search = False
        for response in result.tool_results:
            if any(tool.name == response.tool_name for tool in self.current_tools):
                self._update_tool_context(response)
        if any(call.name == THINK_TOOL_NAME for call in result.message.tool_calls):
            self.most_recent_reasoning = "\n".join(
                str(call.arguments.get("reasoning", ""))
                for call in result.message.tool_calls
                if call.name == THINK_TOOL_NAME
            )
        else:
            self.most_recent_reasoning = None
            self.llm_cycle_count += 1
        if not result.message.tool_calls:
            self.requested_final = True
            self.follow_up(
                UserMessage(
                    content="Produce the research report from the available results."
                )
            )

    def _update_tool_context(self, tool_response: ToolResultMessage) -> None:
        data = tool_response.details
        if isinstance(data, SearchDocsResponse):
            if data.search_docs and tool_response.tool_name == WebSearchTool.NAME:
                self.just_ran_web_search = True

        if isinstance(data, SearchDocsResponse):
            self.citation_mapping.update(data.citation_mapping)

        # Makes sure the citation processor is updated with all the possible docs
        # and citation numbers so that it's populated when passed in to report generation.
        update_citation_processor_from_tool_result(
            tool_response=tool_response,
            citation_processor=self.citation_processor,
        )


def run_research_agent_call(
    research_agent_call: ToolCallKickoff,
    parent_tool_call_id: str,
    tools: list[Tool],
    emitter: Emitter | None,
    llm: LLM,
    is_reasoning_model: bool,
    token_counter: Callable[[str], int],
    user_identity: LLMUserIdentity | None,
    language_section: str,
    reasoning_effort: ReasoningEffort = ReasoningEffort.LOW,
) -> ResearchAgentCallResult | None:
    agent_emitter = emitter
    emitter = emitter or NullEmitter()
    turn_index = research_agent_call.placement.turn_index
    tab_index = research_agent_call.placement.tab_index
    with function_span("research_agent") as span:
        span.span_data.input = str(research_agent_call.tool_args)
        try:
            check_cancelled()
            agent = ResearchAgent(
                ToolCall(
                    id=research_agent_call.tool_call_id,
                    name=research_agent_call.tool_name,
                    arguments=research_agent_call.tool_args,
                ),
                parent_tool_call_id,
                tools,
                agent_emitter,
                llm,
                is_reasoning_model,
                token_counter,
                user_identity,
                language_section,
                reasoning_effort,
                display_placement=research_agent_call.placement,
            )
            emitter.emit(
                Packet(
                    placement=Placement(turn_index=turn_index, tab_index=tab_index),
                    obj=ResearchAgentStart(research_task=agent.research_topic),
                )
            )
            completed = agent.run(max_turns=MAX_RESEARCH_CYCLES + 1)
            check_cancelled()
            report = completed.output.text
            if not report:
                raise ValueError("Model failed to produce a research report")
            result = ResearchAgentCallResult(
                output_messages=agent.output_messages,
                call_placements=dict(agent.presentation.calls)
                if agent.presentation
                else {},
                intermediate_report=report,
                citation_mapping={
                    number: agent.citation_processor.citation_to_doc[number]
                    for number in extract_citation_order_from_text(report)
                    if number in agent.citation_processor.citation_to_doc
                },
            )
            span.span_data.output = result.intermediate_report
            return result

        except Exception as e:
            logger.error("Error running research agent call: %s", e)
            emitter.emit(
                Packet(
                    placement=Placement(turn_index=turn_index, tab_index=tab_index),
                    obj=PacketException(type=StreamingType.ERROR.value, exception=e),
                )
            )
            return None


def run_research_agent_calls(
    research_agent_calls: list[ToolCallKickoff],
    parent_tool_call_ids: list[str],
    tools: list[Tool],
    emitter: Emitter | None,
    llm: LLM,
    is_reasoning_model: bool,
    token_counter: Callable[[str], int],
    citation_mapping: CitationMapping,
    language_section: str,
    user_identity: LLMUserIdentity | None = None,
    reasoning_effort: ReasoningEffort = ReasoningEffort.LOW,
) -> CombinedResearchAgentCallResult:
    # Child runs inherit the parent cancellation scope.
    functions_with_args = [
        (
            run_research_agent_call,
            (
                research_agent_call,
                parent_tool_call_id,
                tools,
                emitter,
                llm,
                is_reasoning_model,
                token_counter,
                user_identity,
                language_section,
                reasoning_effort,
            ),
        )
        for research_agent_call, parent_tool_call_id in zip(
            research_agent_calls, parent_tool_call_ids, strict=False
        )
    ]

    research_agent_call_results = run_functions_tuples_in_parallel(
        functions_with_args,
        allow_failures=False,
        cancellation=current_cancellation(),
    )

    updated_citation_mapping = citation_mapping
    updated_answers: list[str | None] = []

    for result in research_agent_call_results:
        if result is None:
            updated_answers.append(None)
            continue

        # Use collapse_citations to renumber citations in the text and merge mappings.
        # Since we use KEEP_MARKERS mode, the intermediate reports have original citation
        # markers like [1], [2] which need to be renumbered for the combined report.
        updated_answer, updated_citation_mapping = collapse_citations(
            answer_text=result.intermediate_report,
            existing_citation_mapping=updated_citation_mapping,
            new_citation_mapping=result.citation_mapping,
        )
        updated_answers.append(updated_answer)

    return CombinedResearchAgentCallResult(
        intermediate_reports=updated_answers,
        citation_mapping=updated_citation_mapping,
    )
