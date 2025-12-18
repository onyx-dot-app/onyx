from collections.abc import Callable

from pydantic import BaseModel

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.chat_utils import create_tool_call_failure_messages
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.emitter import Emitter
from onyx.chat.llm_loop import construct_message_history
from onyx.chat.llm_step import run_llm_step
from onyx.chat.models import ChatMessageSimple
from onyx.configs.constants import MessageType
from onyx.context.search.models import SearchDoc
from onyx.context.search.models import SearchDocsResponse
from onyx.deep_research.dr_mock_tools import (
    get_research_agent_additional_tool_definitions,
)
from onyx.deep_research.dr_mock_tools import RESEARCH_AGENT_TASK_KEY
from onyx.deep_research.dr_mock_tools import THINK_TOOL_RESPONSE_MESSAGE
from onyx.deep_research.dr_mock_tools import THINK_TOOL_RESPONSE_TOKEN_COUNT
from onyx.deep_research.utils import check_special_tool_calls
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import ToolChoiceOptions
from onyx.prompts.chat_prompts import OPEN_URL_REMINDER
from onyx.prompts.deep_research.dr_tool_prompts import OPEN_URLS_TOOL_DESCRIPTION
from onyx.prompts.deep_research.dr_tool_prompts import (
    OPEN_URLS_TOOL_DESCRIPTION_REASONING,
)
from onyx.prompts.deep_research.dr_tool_prompts import WEB_SEARCH_TOOL_DESCRIPTION
from onyx.prompts.deep_research.research_agent import RESEARCH_AGENT_PROMPT
from onyx.prompts.deep_research.research_agent import RESEARCH_AGENT_PROMPT_REASONING
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.prompts.tool_prompts import INTERNAL_SEARCH_GUIDANCE
from onyx.tools.models import ToolCallInfo
from onyx.tools.models import ToolCallKickoff
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.tool_runner import run_tool_calls
from onyx.tools.utils import generate_tools_description
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()

RESEARCH_CYCLE_CAP = 3


class ResearchAgentCallResult(BaseModel):
    report: str
    search_docs: list[SearchDoc]


def run_research_agent_call(
    research_agent_call: ToolCallKickoff,
    tools: list[Tool],
    emitter: Emitter,
    state_container: ChatStateContainer,
    llm: LLM,
    is_reasoning_model: bool,
    token_counter: Callable[[str], int],
    user_identity: LLMUserIdentity | None,
) -> ResearchAgentCallResult:
    cycle_count = 0
    llm_cycle_count = 0
    current_tools = tools
    gathered_documents: list[SearchDoc] | None = None
    reasoning_cycles = 0
    just_ran_web_search = False

    # If this fails to parse, we can't run the loop anyway, let this one fail in that case
    research_topic = research_agent_call.tool_args[RESEARCH_AGENT_TASK_KEY]

    initial_user_message = ChatMessageSimple(
        message=research_topic,
        token_count=token_counter(research_topic),
        message_type=MessageType.USER,
    )
    msg_history: list[ChatMessageSimple] = [initial_user_message]

    citation_mapping: dict[int, str] = {}
    while cycle_count <= RESEARCH_CYCLE_CAP:
        if cycle_count == RESEARCH_CYCLE_CAP:
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
            current_cycle_count=cycle_count,
            optional_internal_search_tool_description=internal_search_tip,
            optional_web_search_tool_description=web_search_tip,
            optional_open_urls_tool_description=open_urls_tip,
        )

        system_prompt = ChatMessageSimple(
            message=system_prompt_str,
            token_count=token_counter(system_prompt_str),
            message_type=MessageType.SYSTEM,
        )

        if just_ran_web_search:
            reminder_message = ChatMessageSimple(
                message=OPEN_URL_REMINDER,
                token_count=token_counter(OPEN_URL_REMINDER),
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
        llm_step_result, has_reasoned = run_llm_step(
            emitter=emitter,
            history=constructed_history,
            tool_definitions=[tool.tool_definition() for tool in current_tools]
            + research_agent_tools,
            tool_choice=ToolChoiceOptions.REQUIRED,
            llm=llm,
            turn_index=llm_cycle_count + reasoning_cycles,
            citation_processor=DynamicCitationProcessor(),
            state_container=state_container,
            reasoning_effort=ReasoningEffort.LOW,
            final_documents=None,
            user_identity=user_identity,
        )
        if has_reasoned:
            reasoning_cycles += 1

        tool_responses: list[ToolResponse] = []
        tool_calls = llm_step_result.tool_calls or []

        just_ran_web_search = False

        special_tool_calls = check_special_tool_calls(tool_calls=tool_calls)
        if special_tool_calls.generate_report_tool_call:
            logger.info("Generate report tool called")
        elif special_tool_calls.think_tool_call:
            think_tool_call = special_tool_calls.think_tool_call
            tool_call_message = think_tool_call.to_msg_str()

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
            reasoning_cycles += 1
            continue
        else:
            tool_responses, citation_mapping = run_tool_calls(
                tool_calls=tool_calls,
                tools=current_tools,
                message_history=msg_history,
                memories=None,
                user_info=None,
                citation_mapping=citation_mapping,
                citation_processor=DynamicCitationProcessor(),
                # May be better to not do this step, hard to say, needs to be tested
                skip_search_query_expansion=False,
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
                    raise ValueError("Tool response missing tool_call reference")

                tool_call = tool_response.tool_call
                tab_index = tool_call.tab_index

                tool = tools_by_name.get(tool_call.tool_name)
                if not tool:
                    raise ValueError(
                        f"Tool '{tool_call.tool_name}' not found in tools list"
                    )

                # Extract search_docs if this is a search tool response
                search_docs = None
                if isinstance(tool_response.rich_response, SearchDocsResponse):
                    search_docs = tool_response.rich_response.search_docs
                    if gathered_documents:
                        gathered_documents.extend(search_docs)
                    else:
                        gathered_documents = search_docs

                    # This is used for the Open URL reminder in the next cycle
                    # only do this if the web search tool yielded results
                    if search_docs and tool_call.tool_name == WebSearchTool.NAME:
                        just_ran_web_search = True

                tool_call_info = ToolCallInfo(
                    parent_tool_call_id=None,  # TODO
                    turn_index=llm_cycle_count
                    + reasoning_cycles,  # TODO (subturn index also)
                    tab_index=tab_index,
                    tool_name=tool_call.tool_name,
                    tool_call_id=tool_call.tool_call_id,
                    tool_id=tool.id,
                    reasoning_tokens=llm_step_result.reasoning,
                    tool_call_arguments=tool_call.tool_args,
                    tool_call_response=tool_response.llm_facing_response,
                    search_docs=search_docs,
                    generated_images=None,
                )
                # Add to state container for partial save support
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

        llm_cycle_count += 1

    return ResearchAgentCallResult(report="final_report", search_docs=[])


def run_research_agent_calls(
    research_agent_calls: list[ToolCallKickoff],
    tools: list[Tool],
    emitter: Emitter,
    state_container: ChatStateContainer,
    llm: LLM,
    is_reasoning_model: bool,
    token_counter: Callable[[str], int],
    user_identity: LLMUserIdentity | None = None,
) -> list[ResearchAgentCallResult]:
    # Run all research agent calls in parallel
    functions_with_args = [
        (
            run_research_agent_call,
            (
                research_agent_call,
                tools,
                emitter,
                state_container,
                llm,
                is_reasoning_model,
                token_counter,
                user_identity,
            ),
        )
        for research_agent_call in research_agent_calls
    ]

    return run_functions_tuples_in_parallel(
        functions_with_args,
        allow_failures=True,  # Continue even if some research agent calls fail
    )
