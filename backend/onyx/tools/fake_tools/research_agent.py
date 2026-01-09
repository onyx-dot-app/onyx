from collections.abc import Callable
from typing import cast

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.chat_utils import create_tool_call_failure_messages
from onyx.chat.citation_processor import CitationMapping
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.citation_utils import collapse_citations
from onyx.chat.citation_utils import update_citation_processor_from_tool_response
from onyx.chat.emitter import Emitter
from onyx.chat.llm_loop import construct_message_history
from onyx.chat.llm_step import run_llm_step
from onyx.chat.llm_step import run_llm_step_pkt_generator
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import LlmStepResult
from onyx.configs.constants import MessageType
from onyx.context.search.models import SearchDocsResponse
from onyx.deep_research.dr_mock_tools import (
    get_research_agent_additional_tool_definitions,
)
from onyx.deep_research.dr_mock_tools import RESEARCH_AGENT_TASK_KEY
from onyx.deep_research.dr_mock_tools import THINK_TOOL_RESPONSE_MESSAGE
from onyx.deep_research.dr_mock_tools import THINK_TOOL_RESPONSE_TOKEN_COUNT
from onyx.deep_research.models import CombinedResearchAgentCallResult
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.deep_research.utils import check_special_tool_calls
from onyx.deep_research.utils import create_think_tool_token_processor
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import ToolChoiceOptions
from onyx.prompts.deep_research.dr_tool_prompts import OPEN_URLS_TOOL_DESCRIPTION
from onyx.prompts.deep_research.dr_tool_prompts import (
    OPEN_URLS_TOOL_DESCRIPTION_REASONING,
)
from onyx.prompts.deep_research.dr_tool_prompts import WEB_SEARCH_TOOL_DESCRIPTION
from onyx.prompts.deep_research.research_agent import OPEN_URL_REMINDER_RESEARCH_AGENT
from onyx.prompts.deep_research.research_agent import RESEARCH_AGENT_PROMPT
from onyx.prompts.deep_research.research_agent import RESEARCH_AGENT_PROMPT_REASONING
from onyx.prompts.deep_research.research_agent import RESEARCH_REPORT_PROMPT
from onyx.prompts.deep_research.research_agent import USER_REPORT_QUERY
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.prompts.tool_prompts import INTERNAL_SEARCH_GUIDANCE
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import IntermediateReportCitedDocs
from onyx.server.query_and_chat.streaming_models import IntermediateReportDelta
from onyx.server.query_and_chat.streaming_models import IntermediateReportStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import PacketException
from onyx.server.query_and_chat.streaming_models import ResearchAgentStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.server.query_and_chat.streaming_models import StreamingType
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallInfo
from onyx.tools.models import ToolCallKickoff
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.tool_runner import run_tool_calls
from onyx.tools.utils import generate_tools_description
from onyx.tracing.framework.create import function_span
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()


RESEARCH_CYCLE_CAP = 3
# May be good to experiment with this, empirically reports of around 5,000 tokens are pretty good.
MAX_INTERMEDIATE_REPORT_LENGTH_TOKENS = 10000


def generate_intermediate_report(
    research_topic: str,
    history: list[ChatMessageSimple],
    llm: LLM,
    token_counter: Callable[[str], int],
    citation_processor: DynamicCitationProcessor,
    user_identity: LLMUserIdentity | None,
    emitter: Emitter,
    placement: Placement,
) -> str:
    with function_span("generate_intermediate_report") as span:
        span.span_data.input = (
            f"research_topic={research_topic}, history_length={len(history)}"
        )
        # Having the state container here to handle the tokens and not passed through means there is no way to
        # get partial saves of the report. Arguably this is not useful anyway so not going to implement partial saves.
        state_container = ChatStateContainer()
        system_prompt = ChatMessageSimple(
            message=RESEARCH_REPORT_PROMPT,
            token_count=token_counter(RESEARCH_REPORT_PROMPT),
            message_type=MessageType.SYSTEM,
        )

        reminder_str = USER_REPORT_QUERY.format(research_topic=research_topic)
        reminder_message = ChatMessageSimple(
            message=reminder_str,
            token_count=token_counter(reminder_str),
            message_type=MessageType.USER,
        )

        research_history = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=history,
            reminder_message=reminder_message,
            project_files=None,
            available_tokens=llm.config.max_input_tokens,
        )

        intermediate_report_generator = run_llm_step_pkt_generator(
            history=research_history,
            tool_definitions=[],
            tool_choice=ToolChoiceOptions.NONE,
            llm=llm,
            placement=placement,
            citation_processor=citation_processor,
            state_container=state_container,
            reasoning_effort=ReasoningEffort.LOW,
            final_documents=None,
            user_identity=user_identity,
            max_tokens=MAX_INTERMEDIATE_REPORT_LENGTH_TOKENS,
            use_existing_tab_index=True,
            is_deep_research=True,
        )

        while True:
            try:
                packet = next(intermediate_report_generator)
                # Translate AgentResponseStart/Delta packets to IntermediateReportStart/Delta
                # Use original placement consistently for all packets
                if isinstance(packet.obj, AgentResponseStart):
                    emitter.emit(
                        Packet(
                            placement=placement,
                            obj=IntermediateReportStart(),
                        )
                    )
                elif isinstance(packet.obj, AgentResponseDelta):
                    emitter.emit(
                        Packet(
                            placement=placement,
                            obj=IntermediateReportDelta(content=packet.obj.content),
                        )
                    )
                else:
                    # Pass through other packet types (e.g., ReasoningStart, ReasoningDelta, etc.)
                    # Also use original placement to keep everything in the same group
                    emitter.emit(
                        Packet(
                            placement=placement,
                            obj=packet.obj,
                        )
                    )
            except StopIteration as e:
                llm_step_result, _ = e.value
                # Use original placement for completion packets
                emitter.emit(
                    Packet(
                        placement=placement,
                        obj=IntermediateReportCitedDocs(
                            cited_docs=list(
                                citation_processor.get_seen_citations().values()
                            )
                        ),
                    )
                )
                emitter.emit(
                    Packet(
                        placement=placement,
                        obj=SectionEnd(),
                    )
                )
                break

        llm_step_result = cast(LlmStepResult, llm_step_result)

        final_report = llm_step_result.answer
        span.span_data.output = final_report if final_report else None
        if final_report is None:
            raise ValueError(
                f"LLM failed to generate a report for research task: {research_topic}"
            )

        return final_report


def run_research_agent_call(
    research_agent_call: ToolCallKickoff,
    parent_tool_call_id: str,
    tools: list[Tool],
    emitter: Emitter,
    state_container: ChatStateContainer,
    llm: LLM,
    is_reasoning_model: bool,
    token_counter: Callable[[str], int],
    user_identity: LLMUserIdentity | None,
) -> ResearchAgentCallResult | None:
    turn_index = research_agent_call.placement.turn_index
    tab_index = research_agent_call.placement.tab_index
    with function_span("research_agent") as span:
        span.span_data.input = str(research_agent_call.tool_args)
        try:
            # Used to track the citations, but in this case they're not processed into links.
            # They are later stripped from the output since the user cannot use these and the numbers
            # change between the research and the final report.
            citation_processor = DynamicCitationProcessor(replace_citation_tokens=False)

            research_cycle_count = 0
            llm_cycle_count = 0
            current_tools = tools
            reasoning_cycles = 0
            just_ran_web_search = False

            # If this fails to parse, we can't run the loop anyway, let this one fail in that case
            research_topic = research_agent_call.tool_args[RESEARCH_AGENT_TASK_KEY]

            emitter.emit(
                Packet(
                    placement=Placement(turn_index=turn_index, tab_index=tab_index),
                    obj=ResearchAgentStart(research_task=research_topic),
                )
            )

            initial_user_message = ChatMessageSimple(
                message=research_topic,
                token_count=token_counter(research_topic),
                message_type=MessageType.USER,
            )
            msg_history: list[ChatMessageSimple] = [initial_user_message]

            citation_mapping: dict[int, str] = {}
            most_recent_reasoning: str | None = None
            while research_cycle_count <= RESEARCH_CYCLE_CAP:
                if research_cycle_count == RESEARCH_CYCLE_CAP:
                    # For the last cycle, do not use any more searches, only reason or generate a report
                    current_tools = [
                        tool
                        for tool in tools
                        if tool.name not in {SearchTool.NAME, WebSearchTool.NAME}
                    ]

                tools_by_name = {tool.name: tool for tool in current_tools}

                tools_description = generate_tools_description(current_tools)

                internal_search_tip = (
                    INTERNAL_SEARCH_GUIDANCE
                    if any(isinstance(tool, SearchTool) for tool in current_tools)
                    else ""
                )
                web_search_tip = (
                    WEB_SEARCH_TOOL_DESCRIPTION
                    if any(isinstance(tool, WebSearchTool) for tool in current_tools)
                    else ""
                )
                open_urls_tip = (
                    OPEN_URLS_TOOL_DESCRIPTION
                    if any(isinstance(tool, OpenURLTool) for tool in current_tools)
                    else ""
                )
                if is_reasoning_model and open_urls_tip:
                    open_urls_tip = OPEN_URLS_TOOL_DESCRIPTION_REASONING

                system_prompt_template = (
                    RESEARCH_AGENT_PROMPT_REASONING
                    if is_reasoning_model
                    else RESEARCH_AGENT_PROMPT
                )
                system_prompt_str = system_prompt_template.format(
                    available_tools=tools_description,
                    current_datetime=get_current_llm_day_time(full_sentence=False),
                    current_cycle_count=research_cycle_count,
                    optional_internal_search_tool_description=internal_search_tip,
                    optional_web_search_tool_description=web_search_tip,
                    optional_open_url_tool_description=open_urls_tip,
                )

                system_prompt = ChatMessageSimple(
                    message=system_prompt_str,
                    token_count=token_counter(system_prompt_str),
                    message_type=MessageType.SYSTEM,
                )

                if just_ran_web_search:
                    reminder_message = ChatMessageSimple(
                        message=OPEN_URL_REMINDER_RESEARCH_AGENT,
                        token_count=100,
                        message_type=MessageType.USER,
                    )
                else:
                    reminder_message = None

                constructed_history = construct_message_history(
                    system_prompt=system_prompt,
                    custom_agent_prompt=None,
                    simple_chat_history=msg_history,
                    reminder_message=reminder_message,
                    project_files=None,
                    available_tokens=llm.config.max_input_tokens,
                )

                research_agent_tools = get_research_agent_additional_tool_definitions(
                    include_think_tool=not is_reasoning_model
                )
                # Use think tool processor for non-reasoning models to convert
                # think_tool calls to reasoning content (same as dr_loop.py)
                custom_processor = (
                    create_think_tool_token_processor()
                    if not is_reasoning_model
                    else None
                )

                llm_step_result, has_reasoned = run_llm_step(
                    emitter=emitter,
                    history=constructed_history,
                    tool_definitions=[tool.tool_definition() for tool in current_tools]
                    + research_agent_tools,
                    tool_choice=ToolChoiceOptions.REQUIRED,
                    llm=llm,
                    placement=Placement(
                        turn_index=turn_index,
                        tab_index=tab_index,
                        sub_turn_index=llm_cycle_count + reasoning_cycles,
                    ),
                    citation_processor=None,
                    state_container=None,
                    reasoning_effort=ReasoningEffort.LOW,
                    final_documents=None,
                    user_identity=user_identity,
                    custom_token_processor=custom_processor,
                    use_existing_tab_index=True,
                    is_deep_research=True,
                )
                if has_reasoned:
                    reasoning_cycles += 1

                tool_responses: list[ToolResponse] = []
                tool_calls = llm_step_result.tool_calls or []

                # TODO handle the restriction of only 1 tool call type per turn
                # This is a problem right now because of the Placement system not allowing for
                # differentiating sub-tool calls.
                # Filter tool calls to only include the first tool type used
                # This prevents mixing different tool types in the same batch
                if tool_calls:
                    first_tool_type = tool_calls[0].tool_name
                    tool_calls = [
                        tc for tc in tool_calls if tc.tool_name == first_tool_type
                    ]

                just_ran_web_search = False

                if any(
                    tool_call.tool_name in {SearchTool.NAME, WebSearchTool.NAME}
                    for tool_call in tool_calls
                ):
                    # Only the search actions increment the cycle for the max cycle count
                    research_cycle_count += 1

                special_tool_calls = check_special_tool_calls(tool_calls=tool_calls)
                if special_tool_calls.generate_report_tool_call:
                    final_report = generate_intermediate_report(
                        research_topic=research_topic,
                        history=msg_history,
                        llm=llm,
                        token_counter=token_counter,
                        citation_processor=citation_processor,
                        user_identity=user_identity,
                        emitter=emitter,
                        placement=Placement(
                            turn_index=turn_index,
                            tab_index=tab_index,
                        ),
                    )
                    span.span_data.output = final_report if final_report else None
                    return ResearchAgentCallResult(
                        intermediate_report=final_report,
                        citation_mapping=citation_processor.get_seen_citations(),
                    )
                elif special_tool_calls.think_tool_call:
                    think_tool_call = special_tool_calls.think_tool_call
                    tool_call_message = think_tool_call.to_msg_str()

                    with function_span("think_tool") as think_span:
                        think_span.span_data.input = str(think_tool_call.tool_args)
                        think_tool_msg = ChatMessageSimple(
                            message=tool_call_message,
                            token_count=token_counter(tool_call_message),
                            message_type=MessageType.TOOL_CALL,
                            tool_call_id=think_tool_call.tool_call_id,
                            image_files=None,
                        )
                        msg_history.append(think_tool_msg)

                        think_tool_response_msg = ChatMessageSimple(
                            message=THINK_TOOL_RESPONSE_MESSAGE,
                            token_count=THINK_TOOL_RESPONSE_TOKEN_COUNT,
                            message_type=MessageType.TOOL_CALL_RESPONSE,
                            tool_call_id=think_tool_call.tool_call_id,
                            image_files=None,
                        )
                        msg_history.append(think_tool_response_msg)
                        think_span.span_data.output = THINK_TOOL_RESPONSE_MESSAGE
                    reasoning_cycles += 1
                    most_recent_reasoning = llm_step_result.reasoning
                    continue
                else:
                    parallel_tool_call_results = run_tool_calls(
                        tool_calls=tool_calls,
                        tools=current_tools,
                        message_history=msg_history,
                        memories=None,
                        user_info=None,
                        citation_mapping=citation_mapping,
                        next_citation_num=citation_processor.get_next_citation_number(),
                        # Packets currently cannot differentiate between parallel calls in a nested level
                        # so we just cannot show parallel calls in the UI. This should not happen for deep research anyhow.
                        max_concurrent_tools=1,
                        # May be better to not do this step, hard to say, needs to be tested
                        skip_search_query_expansion=False,
                    )
                    tool_responses = parallel_tool_call_results.tool_responses
                    citation_mapping = (
                        parallel_tool_call_results.updated_citation_mapping
                    )

                    if tool_calls and not tool_responses:
                        failure_messages = create_tool_call_failure_messages(
                            tool_calls[0], token_counter
                        )
                        msg_history.extend(failure_messages)
                        continue

                    for tool_response in tool_responses:
                        # Extract tool_call from the response (set by run_tool_calls)
                        if tool_response.tool_call is None:
                            raise ValueError(
                                "Tool response missing tool_call reference"
                            )

                        tool_call = tool_response.tool_call
                        tab_index = tool_call.placement.tab_index

                        tool = tools_by_name.get(tool_call.tool_name)
                        if not tool:
                            raise ValueError(
                                f"Tool '{tool_call.tool_name}' not found in tools list"
                            )

                        search_docs = None
                        if isinstance(tool_response.rich_response, SearchDocsResponse):
                            search_docs = tool_response.rich_response.search_docs

                            # This is used for the Open URL reminder in the next cycle
                            # only do this if the web search tool yielded results
                            if (
                                search_docs
                                and tool_call.tool_name == WebSearchTool.NAME
                            ):
                                just_ran_web_search = True

                        # Makes sure the citation processor is updated with all the possible docs
                        # and citation numbers so that it's populated when passed in to report generation.
                        update_citation_processor_from_tool_response(
                            tool_response=tool_response,
                            citation_processor=citation_processor,
                        )

                        # Research Agent is a top level tool call but the tools called by the research
                        # agent are sub-tool calls.
                        tool_call_info = ToolCallInfo(
                            parent_tool_call_id=parent_tool_call_id,
                            # At the DB save level, there is only a turn index, no sub-turn etc.
                            # This is implied by the parent tool call's turn index and the depth
                            # of the tree traversal.
                            turn_index=llm_cycle_count + reasoning_cycles,
                            tab_index=tab_index,
                            tool_name=tool_call.tool_name,
                            tool_call_id=tool_call.tool_call_id,
                            tool_id=tool.id,
                            reasoning_tokens=llm_step_result.reasoning
                            or most_recent_reasoning,
                            tool_call_arguments=tool_call.tool_args,
                            tool_call_response=tool_response.llm_facing_response,
                            search_docs=search_docs,
                            generated_images=None,
                        )
                        state_container.add_tool_call(tool_call_info)

                        # Store tool call with function name and arguments in separate layers
                        tool_call_message = tool_call.to_msg_str()
                        tool_call_token_count = token_counter(tool_call_message)

                        tool_call_msg = ChatMessageSimple(
                            message=tool_call_message,
                            token_count=tool_call_token_count,
                            message_type=MessageType.TOOL_CALL,
                            tool_call_id=tool_call.tool_call_id,
                            image_files=None,
                        )
                        msg_history.append(tool_call_msg)

                        tool_response_message = tool_response.llm_facing_response
                        tool_response_token_count = token_counter(tool_response_message)

                        tool_response_msg = ChatMessageSimple(
                            message=tool_response_message,
                            token_count=tool_response_token_count,
                            message_type=MessageType.TOOL_CALL_RESPONSE,
                            tool_call_id=tool_call.tool_call_id,
                            image_files=None,
                        )
                        msg_history.append(tool_response_msg)

                # If it reached this point, it did not call reasoning, so here we wipe it to not save it to multiple turns
                most_recent_reasoning = None
                llm_cycle_count += 1

            # If we've run out of cycles, just try to generate a report from everything so far
            final_report = generate_intermediate_report(
                research_topic=research_topic,
                history=msg_history,
                llm=llm,
                token_counter=token_counter,
                citation_processor=citation_processor,
                user_identity=user_identity,
                emitter=emitter,
                placement=Placement(
                    turn_index=turn_index,
                    tab_index=tab_index,
                ),
            )
            span.span_data.output = final_report if final_report else None
            return ResearchAgentCallResult(
                intermediate_report=final_report,
                citation_mapping=citation_processor.get_seen_citations(),
            )

        except Exception as e:
            logger.error(f"Error running research agent call: {e}")
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
    emitter: Emitter,
    state_container: ChatStateContainer,
    llm: LLM,
    is_reasoning_model: bool,
    token_counter: Callable[[str], int],
    citation_mapping: CitationMapping,
    user_identity: LLMUserIdentity | None = None,
) -> CombinedResearchAgentCallResult:
    # Run all research agent calls in parallel
    functions_with_args = [
        (
            run_research_agent_call,
            (
                research_agent_call,
                parent_tool_call_id,
                tools,
                emitter,
                state_container,
                llm,
                is_reasoning_model,
                token_counter,
                user_identity,
            ),
        )
        for research_agent_call, parent_tool_call_id in zip(
            research_agent_calls, parent_tool_call_ids
        )
    ]

    research_agent_call_results = run_functions_tuples_in_parallel(
        functions_with_args,
        allow_failures=False,
    )

    updated_citation_mapping = citation_mapping
    updated_answers: list[str | None] = []

    for result in research_agent_call_results:
        if result is None:
            updated_answers.append(None)
            continue

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
