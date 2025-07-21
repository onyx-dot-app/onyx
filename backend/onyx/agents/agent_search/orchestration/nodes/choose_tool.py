from typing import cast
from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import ToolCall
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.basic.utils import process_llm_stream
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.orchestration.states import ToolChoice
from onyx.agents.agent_search.orchestration.states import ToolChoiceState
from onyx.agents.agent_search.orchestration.states import ToolChoiceUpdate
from onyx.agents.agent_search.shared_graph_utils.models import QueryExpansionType
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.chat.tool_handling.tool_response_handler import get_tool_by_name
from onyx.chat.tool_handling.tool_response_handler import (
    get_tool_call_for_non_tool_calling_llm_impl,
)
from onyx.configs.chat_configs import USE_SEMANTIC_KEYWORD_EXPANSIONS_BASIC_SEARCH
from onyx.context.search.preprocessing.preprocessing import query_analysis
from onyx.context.search.retrieval.search_runner import get_query_embedding
from onyx.llm.factory import get_default_llms
from onyx.prompts.chat_prompts import QUERY_KEYWORD_EXPANSION_WITH_HISTORY_PROMPT
from onyx.prompts.chat_prompts import QUERY_KEYWORD_EXPANSION_WITHOUT_HISTORY_PROMPT
from onyx.prompts.chat_prompts import QUERY_SEMANTIC_EXPANSION_WITH_HISTORY_PROMPT
from onyx.prompts.chat_prompts import QUERY_SEMANTIC_EXPANSION_WITHOUT_HISTORY_PROMPT
from onyx.tools.models import QueryExpansions
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_in_background
from onyx.utils.threadpool_concurrency import TimeoutThread
from onyx.utils.threadpool_concurrency import wait_on_background
from onyx.utils.timing import log_function_time
from shared_configs.model_server_models import Embedding

logger = setup_logger()


def _create_history_str(prompt_builder: AnswerPromptBuilder) -> str:
    # TODO: Add trimming logic
    history_segments = []
    for msg in prompt_builder.message_history:
        if isinstance(msg, HumanMessage):
            role = "User"
        elif isinstance(msg, AIMessage):
            role = "Assistant"
        else:
            continue
        history_segments.append(f"{role}:\n {msg.content}\n\n")
    return "\n".join(history_segments)


def _expand_query(
    query: str,
    expansion_type: QueryExpansionType,
    prompt_builder: AnswerPromptBuilder,
) -> str:

    history_str = _create_history_str(prompt_builder)

    if history_str:
        if expansion_type == QueryExpansionType.KEYWORD:
            base_prompt = QUERY_KEYWORD_EXPANSION_WITH_HISTORY_PROMPT
        else:
            base_prompt = QUERY_SEMANTIC_EXPANSION_WITH_HISTORY_PROMPT
        expansion_prompt = base_prompt.format(question=query, history=history_str)
    else:
        if expansion_type == QueryExpansionType.KEYWORD:
            base_prompt = QUERY_KEYWORD_EXPANSION_WITHOUT_HISTORY_PROMPT
        else:
            base_prompt = QUERY_SEMANTIC_EXPANSION_WITHOUT_HISTORY_PROMPT
        expansion_prompt = base_prompt.format(question=query)

    msg = HumanMessage(content=expansion_prompt)
    primary_llm, _ = get_default_llms()
    response = primary_llm.invoke([msg])
    rephrased_query: str = cast(str, response.content)

    return rephrased_query


def _expand_query_non_tool_calling_llm(
    expanded_keyword_thread: TimeoutThread[str],
    expanded_semantic_thread: TimeoutThread[str],
) -> QueryExpansions | None:
    keyword_expansion: str | None = wait_on_background(expanded_keyword_thread)
    semantic_expansion: str | None = wait_on_background(expanded_semantic_thread)

    if keyword_expansion is None or semantic_expansion is None:
        return None

    return QueryExpansions(
        keywords_expansions=[keyword_expansion],
        semantic_expansions=[semantic_expansion],
    )


# TODO: break this out into an implementation function
# and a function that handles extracting the necessary fields
# from the state and config
# TODO: fan-out to multiple tool call nodes? Make this configurable?
@log_function_time(print_only=True)
def choose_tool(
    state: ToolChoiceState,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> ToolChoiceUpdate:
    """
    This node is responsible for calling the LLM to choose a tool. If no tool is chosen,
    The node MAY emit an answer, depending on whether state["should_stream_answer"] is set.
    """
    should_stream_answer = state.should_stream_answer

    agent_config = cast(GraphConfig, config["metadata"]["config"])

    force_use_tool = agent_config.tooling.force_use_tool

    embedding_thread: TimeoutThread[Embedding] | None = None
    keyword_thread: TimeoutThread[tuple[bool, list[str]]] | None = None
    expanded_keyword_thread: TimeoutThread[str] | None = None
    expanded_semantic_thread: TimeoutThread[str] | None = None
    # If we have override_kwargs, add them to the tool_args
    override_kwargs: SearchToolOverrideKwargs = (
        force_use_tool.override_kwargs or SearchToolOverrideKwargs()
    )
    override_kwargs.original_query = agent_config.inputs.prompt_builder.raw_user_query

    using_tool_calling_llm = agent_config.tooling.using_tool_calling_llm
    prompt_builder = state.prompt_snapshot or agent_config.inputs.prompt_builder

    llm = agent_config.tooling.primary_llm
    skip_gen_ai_answer_generation = agent_config.behavior.skip_gen_ai_answer_generation

    if (
        not agent_config.behavior.use_agentic_search
        and agent_config.tooling.search_tool is not None
        and (
            not force_use_tool.force_use or force_use_tool.tool_name == SearchTool._NAME
        )
    ):
        # Run in a background thread to avoid blocking the main thread
        embedding_thread = run_in_background(
            get_query_embedding,
            agent_config.inputs.prompt_builder.raw_user_query,
            agent_config.persistence.db_session,
        )
        keyword_thread = run_in_background(
            query_analysis,
            agent_config.inputs.prompt_builder.raw_user_query,
        )

        if USE_SEMANTIC_KEYWORD_EXPANSIONS_BASIC_SEARCH:

            expanded_keyword_thread = run_in_background(
                _expand_query,
                agent_config.inputs.prompt_builder.raw_user_query,
                QueryExpansionType.KEYWORD,
                prompt_builder,
            )
            expanded_semantic_thread = run_in_background(
                _expand_query,
                agent_config.inputs.prompt_builder.raw_user_query,
                QueryExpansionType.SEMANTIC,
                prompt_builder,
            )

    structured_response_format = agent_config.inputs.structured_response_format
    tools = [
        tool for tool in (agent_config.tooling.tools or []) if tool.name in state.tools
    ]

    tool, tool_args = None, None
    if force_use_tool.force_use and force_use_tool.args is not None:
        tool_name, tool_args = (
            force_use_tool.tool_name,
            force_use_tool.args,
        )
        tool = get_tool_by_name(tools, tool_name)

    # special pre-logic for non-tool calling LLM case
    elif not using_tool_calling_llm and tools:
        chosen_tool_and_args = get_tool_call_for_non_tool_calling_llm_impl(
            force_use_tool=force_use_tool,
            tools=tools,
            prompt_builder=prompt_builder,
            llm=llm,
        )
        if chosen_tool_and_args:
            tool, tool_args = chosen_tool_and_args

    # If we have a tool and tool args, we are ready to request a tool call.
    # This only happens if the tool call was forced or we are using a non-tool calling LLM.
    if tool and tool_args:
        if embedding_thread and tool.name == SearchTool._NAME:
            # Wait for the embedding thread to finish
            embedding = wait_on_background(embedding_thread)
            override_kwargs.precomputed_query_embedding = embedding
        if keyword_thread and tool.name == SearchTool._NAME:
            is_keyword, keywords = wait_on_background(keyword_thread)
            override_kwargs.precomputed_is_keyword = is_keyword
            override_kwargs.precomputed_keywords = keywords
        # dual keyword expansion needs to be added here for non-tool calling LLM case
        if (
            USE_SEMANTIC_KEYWORD_EXPANSIONS_BASIC_SEARCH
            and expanded_keyword_thread
            and expanded_semantic_thread
            and tool.name == SearchTool._NAME
        ):
            override_kwargs.expanded_queries = _expand_query_non_tool_calling_llm(
                expanded_keyword_thread=expanded_keyword_thread,
                expanded_semantic_thread=expanded_semantic_thread,
            )
        if (
            USE_SEMANTIC_KEYWORD_EXPANSIONS_BASIC_SEARCH
            and tool.name == SearchTool._NAME
            and override_kwargs.expanded_queries
        ):
            if (
                override_kwargs.expanded_queries.keywords_expansions is None
                or override_kwargs.expanded_queries.semantic_expansions is None
            ):
                raise ValueError("No expanded keyword or semantic threads found.")

        return ToolChoiceUpdate(
            tool_choice=ToolChoice(
                tool=tool,
                tool_args=tool_args,
                id=str(uuid4()),
                search_tool_override_kwargs=override_kwargs,
            ),
        )

    # if we're skipping gen ai answer generation, we should only
    # continue if we're forcing a tool call (which will be emitted by
    # the tool calling llm in the stream() below)
    if skip_gen_ai_answer_generation and not force_use_tool.force_use:
        return ToolChoiceUpdate(
            tool_choice=None,
        )

    built_prompt = (
        prompt_builder.build()
        if isinstance(prompt_builder, AnswerPromptBuilder)
        else prompt_builder.built_prompt
    )
    # At this point, we are either using a tool calling LLM or we are skipping the tool call.
    # DEBUG: good breakpoint
    stream = llm.stream(
        # For tool calling LLMs, we want to insert the task prompt as part of this flow, this is because the LLM
        # may choose to not call any tools and just generate the answer, in which case the task prompt is needed.
        prompt=built_prompt,
        tools=(
            [tool.tool_definition() for tool in tools] or None
            if using_tool_calling_llm
            else None
        ),
        tool_choice=(
            "required"
            if tools and force_use_tool.force_use and using_tool_calling_llm
            else None
        ),
        structured_response_format=structured_response_format,
    )

    tool_message = process_llm_stream(
        stream,
        should_stream_answer
        and not agent_config.behavior.skip_gen_ai_answer_generation,
        writer,
    )

    # If no tool calls are emitted by the LLM, we should not choose a tool
    if len(tool_message.tool_calls) == 0:
        logger.debug("No tool calls emitted by LLM")
        return ToolChoiceUpdate(
            tool_choice=None,
        )

    # TODO: here we could handle parallel tool calls. Right now
    # we just pick the first one that matches.
    selected_tool: Tool | None = None
    selected_tool_call_request: ToolCall | None = None
    for tool_call_request in tool_message.tool_calls:
        known_tools_by_name = [
            tool for tool in tools if tool.name == tool_call_request["name"]
        ]

        if known_tools_by_name:
            selected_tool = known_tools_by_name[0]
            selected_tool_call_request = tool_call_request
            break

        logger.error(
            "Tool call requested with unknown name field. \n"
            f"tools: {tools}"
            f"tool_call_request: {tool_call_request}"
        )

    if not selected_tool or not selected_tool_call_request:
        raise ValueError(
            f"Tool call attempted with tool {selected_tool}, request {selected_tool_call_request}"
        )

    logger.debug(f"Selected tool: {selected_tool.name}")
    logger.debug(f"Selected tool call request: {selected_tool_call_request}")

    if embedding_thread and selected_tool.name == SearchTool._NAME:
        # Wait for the embedding thread to finish
        embedding = wait_on_background(embedding_thread)
        override_kwargs.precomputed_query_embedding = embedding
    if keyword_thread and selected_tool.name == SearchTool._NAME:
        is_keyword, keywords = wait_on_background(keyword_thread)
        override_kwargs.precomputed_is_keyword = is_keyword
        override_kwargs.precomputed_keywords = keywords

    if (
        selected_tool.name == SearchTool._NAME
        and expanded_keyword_thread
        and expanded_semantic_thread
    ):

        override_kwargs.expanded_queries = _expand_query_non_tool_calling_llm(
            expanded_keyword_thread=expanded_keyword_thread,
            expanded_semantic_thread=expanded_semantic_thread,
        )
    if (
        USE_SEMANTIC_KEYWORD_EXPANSIONS_BASIC_SEARCH
        and selected_tool.name == SearchTool._NAME
        and override_kwargs.expanded_queries
    ):
        # TODO: this is a hack to handle the case where the expanded queries are not found.
        # We should refactor this to be more robust.
        if (
            override_kwargs.expanded_queries.keywords_expansions is None
            or override_kwargs.expanded_queries.semantic_expansions is None
        ):
            raise ValueError("No expanded keyword or semantic threads found.")

    return ToolChoiceUpdate(
        tool_choice=ToolChoice(
            tool=selected_tool,
            tool_args=selected_tool_call_request["args"],
            id=selected_tool_call_request["id"],
            search_tool_override_kwargs=override_kwargs,
        ),
    )
