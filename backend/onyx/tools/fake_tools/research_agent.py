from collections.abc import Callable

from pydantic import BaseModel

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.emitter import Emitter
from onyx.chat.llm_step import run_llm_step
from onyx.chat.models import ChatMessageSimple
from onyx.configs.constants import MessageType
from onyx.context.search.models import SearchDoc
from onyx.deep_research.dr_mock_tools import (
    get_research_agent_additional_tool_definitions,
)
from onyx.deep_research.dr_mock_tools import RESEARCH_AGENT_TASK_KEY
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.models import ToolChoiceOptions
from onyx.prompts.deep_research.dr_tool_prompts import OPEN_URLS_TOOL_DESCRIPTION
from onyx.prompts.deep_research.dr_tool_prompts import (
    OPEN_URLS_TOOL_DESCRIPTION_REASONING,
)
from onyx.prompts.deep_research.dr_tool_prompts import WEB_SEARCH_TOOL_DESCRIPTION
from onyx.prompts.deep_research.research_agent import RESEARCH_AGENT_PROMPT
from onyx.prompts.deep_research.research_agent import RESEARCH_AGENT_PROMPT_REASONING
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.prompts.tool_prompts import INTERNAL_SEARCH_GUIDANCE
from onyx.tools.models import ToolCallKickoff
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
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
    user_identity: LLMUserIdentity,
) -> ResearchAgentCallResult:
    cycle_count = 0
    llm_cycle_count = 0
    current_tools = tools
    chat_history: list[ChatMessageSimple] = []
    reasoning_cycles = 0
    # If this fails to parse, we can't run the loop anyway, let this one fail in that case
    research_topic = research_agent_call.tool_args[RESEARCH_AGENT_TASK_KEY]
    while cycle_count <= RESEARCH_CYCLE_CAP:
        if cycle_count == RESEARCH_CYCLE_CAP:
            current_tools = [
                tool
                for tool in tools
                if tool.name not in {SearchTool.NAME, WebSearchTool.NAME}
            ]

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

        # Note, there is no truncation here, it's assumed that it will fit
        if not chat_history:
            chat_history.append(system_prompt)
            chat_history.append(
                ChatMessageSimple(
                    message=research_topic,
                    token_count=token_counter(research_topic),
                    message_type=MessageType.USER,
                )
            )
        else:
            chat_history.insert(0, system_prompt)

        required_tools = get_research_agent_additional_tool_definitions(
            include_think_tool=not is_reasoning_model
        )
        llm_step_result, has_reasoned = run_llm_step(
            emitter=emitter,
            history=chat_history,
            tool_definitions=[tool.tool_definition() for tool in current_tools]
            + required_tools,
            tool_choice=ToolChoiceOptions.REQUIRED,
            llm=llm,
            turn_index=llm_cycle_count + reasoning_cycles,
            citation_processor=DynamicCitationProcessor(),
            state_container=state_container,
            final_documents=None,
            user_identity=user_identity,
        )
        if has_reasoned:
            reasoning_cycles += 1

        llm_cycle_count += 1

    return ResearchAgentCallResult(report="final_report", search_docs=[])


def run_research_agent_calls(
    research_agent_calls: list[ToolCallKickoff],
    tools: list[Tool],
    emitter: Emitter,
    state_container: ChatStateContainer,
    llm: LLM,
    token_counter: Callable[[str], int],
) -> list[ResearchAgentCallResult]:
    # Run all research agent calls in parallel
    functions_with_args = [
        (
            run_research_agent_call,
            (research_agent_call, tools, emitter, state_container, llm, token_counter),
        )
        for research_agent_call in research_agent_calls
    ]

    return run_functions_tuples_in_parallel(
        functions_with_args,
        allow_failures=True,  # Continue even if some research agent calls fail
    )
