import asyncio
import time
from collections.abc import Callable
from threading import Lock

from pydantic_ai import RunContext

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.citation_processor import (
    CitationMode,
    DynamicCitationProcessor,
)
from onyx.chat.citation_utils import (
    update_citation_processor_from_tool_response,
)
from onyx.chat.emitter import Emitter
from onyx.chat.models import ChatMessageSimple
from onyx.chat.prompt_utils import with_language_section
from onyx.configs.chat_configs import DR_REPORT_LLM_TIMEOUT_S
from onyx.configs.constants import MessageType
from onyx.context.search.models import SearchDocsResponse
from onyx.deep_research.dr_mock_tools import (
    RESEARCH_AGENT_TASK_KEY,
    THINK_TOOL_RESPONSE_MESSAGE,
    get_research_agent_additional_tool_definitions,
)
from onyx.deep_research.models import (
    ResearchAgentCallResult,
)
from onyx.llm.interfaces import LLM, LLMUserIdentity
from onyx.llm.models import ReasoningEffort, ToolChoiceOptions
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
    IntermediateReportCitedDocs,
    IntermediateReportStart,
    PacketException,
    ResearchAgentStart,
    StreamingType,
)
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallInfo, ToolCallKickoff
from onyx.tools.progress import check_tool_run_active
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.utils import extract_url_snippet_map
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.tool_runner import run_tool_call_async
from onyx.tools.utils import (
    generate_tools_description,
)
from onyx.tracing.framework.create import function_span
from onyx.utils.logger import setup_logger

logger = setup_logger()


# 12 minute timeout before forcing intermediate report generation
RESEARCH_AGENT_FORCE_REPORT_SECONDS = 12 * 60
# May be good to experiment with this, empirically reports of around 5,000 tokens are pretty good.
MAX_INTERMEDIATE_REPORT_LENGTH_TOKENS = 10000


async def run_research_agent_call(
    parent_context: RunContext[None],
    research_agent_call: ToolCallKickoff,
    parent_tool_call_id: str,
    tools: list[Tool],
    emitter: Emitter,
    state_container: ChatStateContainer,
    llm: LLM,
    is_reasoning_model: bool,
    token_counter: Callable[[str], int],
    user_identity: LLMUserIdentity | None,
    language_section: str,
    reasoning_effort: ReasoningEffort = ReasoningEffort.LOW,
) -> ResearchAgentCallResult | None:
    turn_index = research_agent_call.placement.turn_index
    tab_index = research_agent_call.placement.tab_index
    with function_span("research_agent") as span:
        span.span_data.input = str(research_agent_call.tool_args)
        try:
            # Track start time for timeout-based forced report generation
            start_time = time.monotonic()

            # Used to track citations while keeping original citation markers in intermediate reports.
            # KEEP_MARKERS preserves citation markers like [1], [2] in the text unchanged
            # while tracking which documents were cited via get_seen_citations().
            # This allows collapse_citations() to later renumber them in the final report.
            citation_processor = DynamicCitationProcessor(
                citation_mode=CitationMode.KEEP_MARKERS
            )

            from pydantic_ai.messages import (
                ModelMessage,
                ModelRequest,
                ModelResponse,
                SystemPromptPart,
                ThinkingPart,
                ToolCallPart,
                UserPromptPart,
            )
            from pydantic_ai.tools import ToolDefinition

            from onyx.chat.agent_runtime import NativeAgentRequest, build_native_agent
            from onyx.deep_research.dr_mock_tools import (
                GENERATE_REPORT_TOOL_NAME,
                THINK_TOOL_NAME,
            )
            from onyx.llm.pydantic_ai_llm import PydanticAILLM

            if not isinstance(llm, PydanticAILLM):
                raise TypeError("Research agents require a Pydantic AI model")
            research_topic = research_agent_call.tool_args[RESEARCH_AGENT_TASK_KEY]
            await asyncio.to_thread(
                emitter.report,
                placement=Placement(turn_index=turn_index, tab_index=tab_index),
                obj=ResearchAgentStart(research_task=research_topic),
            )
            initial_message = ChatMessageSimple(
                message=research_topic,
                token_count=token_counter(research_topic),
                message_type=MessageType.USER,
            )
            cycle_count = 0
            completed_research = False
            result_lock = Lock()
            citation_starts: dict[str, int] = {}
            report_requested = False
            report_started = False
            just_ran_web_search = False
            citation_mapping: dict[int, str] = {}
            calls: list[ToolCallKickoff] = []
            reasoning: str | None = None
            definitions = [
                tool.tool_definition() for tool in tools
            ] + get_research_agent_additional_tool_definitions(
                include_think_tool=not is_reasoning_model
            )
            native_tools = [
                ToolDefinition(
                    name=definition["function"]["name"],
                    description=definition["function"].get("description"),
                    parameters_json_schema=definition["function"]["parameters"],
                )
                for definition in definitions
            ]
            tools_by_name = {tool.name: tool for tool in tools}

            def placement() -> Placement:
                return Placement(
                    turn_index=turn_index,
                    tab_index=tab_index,
                    sub_turn_index=cycle_count,
                )

            def prepare_step(messages: list[ModelMessage]) -> NativeAgentRequest:
                nonlocal \
                    report_requested, \
                    report_started, \
                    cycle_count, \
                    completed_research
                if completed_research:
                    cycle_count += 1
                    completed_research = False
                report_requested = (
                    report_requested
                    or cycle_count >= MAX_RESEARCH_CYCLES
                    or time.monotonic() - start_time
                    >= RESEARCH_AGENT_FORCE_REPORT_SECONDS
                )
                if report_requested and not report_started:
                    emitter.report(
                        placement=Placement(turn_index=turn_index, tab_index=tab_index),
                        obj=IntermediateReportStart(),
                    )
                    report_started = True
                has_open_url = OpenURLTool.NAME in tools_by_name
                template = (
                    RESEARCH_AGENT_PROMPT_REASONING
                    if is_reasoning_model
                    else RESEARCH_AGENT_PROMPT
                )
                prompt = (
                    with_language_section(RESEARCH_REPORT_PROMPT, language_section)
                    if report_requested
                    else template.format(
                        available_tools=generate_tools_description(tools),
                        current_datetime=get_current_llm_day_time(full_sentence=False),
                        current_cycle_count=cycle_count,
                        optional_internal_search_tool_description=INTERNAL_SEARCH_GUIDANCE
                        if SearchTool.NAME in tools_by_name
                        else "",
                        optional_web_search_tool_description=WEB_SEARCH_TOOL_DESCRIPTION
                        if WebSearchTool.NAME in tools_by_name
                        else "",
                        optional_open_url_tool_description=(
                            OPEN_URLS_TOOL_DESCRIPTION_REASONING
                            if is_reasoning_model
                            else OPEN_URLS_TOOL_DESCRIPTION
                        )
                        if has_open_url
                        else "",
                    )
                )
                history = [
                    message
                    for message in messages
                    if not (
                        isinstance(message, ModelRequest)
                        and all(
                            isinstance(part, SystemPromptPart) for part in message.parts
                        )
                    )
                ]
                history.insert(0, ModelRequest(parts=[SystemPromptPart(prompt)]))
                if report_requested:
                    history.append(
                        ModelRequest(
                            parts=[
                                UserPromptPart(
                                    USER_REPORT_QUERY.format(
                                        research_topic=research_topic
                                    )
                                )
                            ]
                        )
                    )
                elif just_ran_web_search and has_open_url:
                    history.append(
                        ModelRequest(
                            parts=[UserPromptPart(OPEN_URL_REMINDER_RESEARCH_AGENT)]
                        )
                    )
                return NativeAgentRequest(
                    messages=history,
                    settings=llm.model_settings(
                        reasoning_effort=reasoning_effort,
                        max_tokens=MAX_INTERMEDIATE_REPORT_LENGTH_TOKENS
                        if report_requested
                        else 1000,
                        user_identity=user_identity,
                        timeout_override=DR_REPORT_LLM_TIMEOUT_S
                        if report_requested
                        else None,
                        tool_choice=ToolChoiceOptions.NONE
                        if report_requested
                        else ToolChoiceOptions.REQUIRED,
                    ),
                    tools=[] if report_requested else native_tools,
                )

            def finalize_step(response: ModelResponse) -> None:
                nonlocal calls, reasoning, completed_research, just_ran_web_search
                just_ran_web_search = False
                calls = [
                    ToolCallKickoff(
                        tool_call_id=part.tool_call_id,
                        tool_name=part.tool_name,
                        tool_args=part.args_as_dict(),
                        placement=placement(),
                    )
                    for part in response.parts
                    if isinstance(part, ToolCallPart)
                ]
                executable_calls = [
                    call
                    for call in calls
                    if call.tool_name
                    not in {GENERATE_REPORT_TOOL_NAME, THINK_TOOL_NAME}
                ]
                completed_research = bool(executable_calls)
                citation_start = citation_processor.get_next_citation_number()
                citation_starts.clear()
                citation_starts.update(
                    {
                        call.tool_call_id: citation_start + index * 100
                        for index, call in enumerate(executable_calls)
                    }
                )
                reasoning = (
                    "".join(
                        part.content
                        for part in response.parts
                        if isinstance(part, ThinkingPart)
                    )
                    or None
                )

            async def execute_tool(
                context: RunContext[None], native_call: ToolCallPart
            ) -> str:
                nonlocal report_requested, just_ran_web_search, citation_mapping
                results: dict[str, str] = {}
                executable: list[ToolCallKickoff] = []
                for call in [
                    ToolCallKickoff(
                        tool_call_id=native_call.tool_call_id,
                        tool_name=native_call.tool_name,
                        tool_args=native_call.args_as_dict(),
                        placement=next(
                            (
                                item.placement
                                for item in calls
                                if item.tool_call_id == native_call.tool_call_id
                            ),
                            placement(),
                        ),
                    )
                ]:
                    if call.tool_name == GENERATE_REPORT_TOOL_NAME:
                        report_requested = True
                        results[call.tool_call_id] = "Generate the research report."
                    elif call.tool_name == THINK_TOOL_NAME:
                        results[call.tool_call_id] = THINK_TOOL_RESPONSE_MESSAGE
                    else:
                        executable.append(call)
                if executable:
                    result = await run_tool_call_async(
                        context=context,
                        tool_call=executable[0],
                        tools=tools,
                        message_history=[initial_message],
                        user_memory_context=None,
                        user_info=None,
                        citation_mapping=dict(citation_mapping),
                        next_citation_num=citation_starts[native_call.tool_call_id],
                        skip_search_query_expansion=False,
                        url_snippet_map=extract_url_snippet_map(
                            [
                                document
                                for previous in state_container.get_tool_calls()
                                for document in previous.search_docs or []
                            ]
                        ),
                    )
                    with result_lock:
                        check_tool_run_active()
                        if isinstance(result.rich_response, SearchDocsResponse):
                            citation_mapping.update(
                                result.rich_response.citation_mapping
                            )
                        call = result.tool_call
                        if call is None:
                            raise ValueError("Tool response has no call provenance")
                        results[call.tool_call_id] = result.llm_facing_response
                        search_docs = None
                        displayed_docs = None
                        if isinstance(result.rich_response, SearchDocsResponse):
                            search_docs = result.rich_response.search_docs
                            displayed_docs = result.rich_response.displayed_docs
                            if search_docs:
                                state_container.add_search_docs(search_docs)
                                just_ran_web_search = (
                                    just_ran_web_search
                                    or call.tool_name == WebSearchTool.NAME
                                )
                        update_citation_processor_from_tool_response(
                            tool_response=result,
                            citation_processor=citation_processor,
                        )
                        state_container.add_tool_call(
                            ToolCallInfo(
                                parent_tool_call_id=parent_tool_call_id,
                                turn_index=cycle_count,
                                tab_index=call.placement.tab_index,
                                tool_name=call.tool_name,
                                tool_call_id=call.tool_call_id,
                                tool_id=tools_by_name[call.tool_name].id,
                                reasoning_tokens=reasoning,
                                tool_call_arguments=call.tool_args,
                                tool_call_response=result.llm_facing_response,
                                search_docs=displayed_docs or search_docs,
                                generated_images=None,
                            )
                        )
                    for call in executable:
                        results.setdefault(
                            call.tool_call_id,
                            "Tool execution failed. Try another approach.",
                        )
                return results.get(
                    native_call.tool_call_id, "Tool execution produced no result."
                )

            child = build_native_agent(
                agent_name="research_agent",
                llm=llm,
                prepare_step=prepare_step,
                finalize_step=finalize_step,
                execute_tool_async=execute_tool,
                tool_definitions=definitions,
                max_requests=MAX_RESEARCH_CYCLES * 3 + 2,
                total_timeout=30 * 60,
                event_phase=lambda: "report" if report_requested else "research",
                tokenizer=token_counter,
                citation_processor=citation_processor,
                emitter=emitter,
                state_container=None,
                placement=placement,
                message_history=[],
            )
            final_report = await child.delegate(parent_context, research_topic)
            # Track citations on the report without rewriting native event text.
            await asyncio.to_thread(
                emitter.report,
                placement=placement(),
                obj=IntermediateReportCitedDocs(
                    cited_docs=list(citation_processor.get_seen_citations().values())
                ),
            )
            span.span_data.output = final_report
            return ResearchAgentCallResult(
                intermediate_report=final_report,
                citation_mapping=citation_processor.get_seen_citations(),
            )

        except Exception as e:
            logger.error("Error running research agent call: %s", e)
            await asyncio.to_thread(
                emitter.report,
                placement=Placement(turn_index=turn_index, tab_index=tab_index),
                obj=PacketException(type=StreamingType.ERROR.value, exception=e),
            )
            return None
