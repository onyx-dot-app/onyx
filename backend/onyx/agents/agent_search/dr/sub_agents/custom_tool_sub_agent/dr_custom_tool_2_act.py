from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.models import DRPath
from onyx.agents.agent_search.dr.models import GenericToolAnswer
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.sub_agents.custom_tool_sub_agent.dr_custom_tool_states import (
    CustomToolBranchInput,
)
from onyx.agents.agent_search.dr.sub_agents.custom_tool_sub_agent.dr_custom_tool_states import (
    GenericToolBranchUpdate,
)
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_json
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.prompts.dr_prompts import TOOL_PROCESSING_PROMPT
from onyx.tools.tool_implementations.custom.custom_tool import CUSTOM_TOOL_RESPONSE_ID
from onyx.tools.tool_implementations.custom.custom_tool import CustomTool
from onyx.tools.tool_implementations.custom.custom_tool import CustomToolCallSummary
from onyx.utils.logger import setup_logger

logger = setup_logger()


def custom_tool_act(
    state: CustomToolBranchInput,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> GenericToolBranchUpdate:
    """
    LangGraph node to perform a generic tool call as part of the DR process.
    """

    node_start_time = datetime.now()
    iteration_nr = state.iteration_nr
    parallelization_nr = state.parallelization_nr
    tool_dict = state.tool_dict
    tool_name = tool_dict["name"]

    query = state.branch_question
    if not query:
        raise ValueError("query is not set")

    write_custom_event(
        "basic_response",
        AgentAnswerPiece(
            answer_piece=(
                f"SUB-QUERY {iteration_nr}.{parallelization_nr} "
                f"({tool_name.upper()}): {query}\n\n"
            ),
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    base_question = graph_config.inputs.prompt_builder.raw_user_query

    logger.debug(
        f"Search start for {tool_name.upper()} {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    if graph_config.inputs.persona is None:
        raise ValueError("persona is not set")

    custom_tool: CustomTool | None = None
    for tool in graph_config.tooling.tools:
        if tool.name == tool_name:
            custom_tool = cast(CustomTool, tool)
            break

    if custom_tool is None:
        raise ValueError("Tool is not set. This should not happen.")

    for tool_response in custom_tool.run(internet_search_query=query):
        # get retrieved docs to send to the rest of the graph
        if tool_response.id == CUSTOM_TOOL_RESPONSE_ID:
            tool_response.response.response_type
            cast(CustomToolCallSummary, tool_response.response)
            # TODO: properly handle responses for varying formats
            break

    document_texts = "<TODO: add document texts>"

    logger.debug(
        f"Search end/LLM start for {tool_name.upper()} {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    # Built prompt

    search_prompt = (
        TOOL_PROCESSING_PROMPT.replace("---search_query---", query)
        .replace("---base_question---", base_question)
        .replace("---document_text---", document_texts)
    )

    # Run LLM

    tool_answer_json = invoke_llm_json(
        llm=graph_config.tooling.primary_llm,
        prompt=search_prompt,
        schema=GenericToolAnswer,
        timeout_override=40,
        max_tokens=1500,
    )

    logger.debug(
        f"LLM/all done for {tool_name.upper()} {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    write_custom_event(
        "basic_response",
        AgentAnswerPiece(
            answer_piece=f"ANSWERED {iteration_nr}.{parallelization_nr}\n\n",
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )

    # get all citations and remove them from the answer to avoid
    # incorrect citations when the documents get reordered by the closer
    background_info_string = tool_answer_json.background_info
    answer_string = tool_answer_json.answer

    return GenericToolBranchUpdate(
        branch_iteration_responses=[
            IterationAnswer(
                tool=DRPath.GENERIC_TOOL,
                iteration_nr=iteration_nr,
                parallelization_nr=parallelization_nr,
                question=query,
                answer=answer_string,
                cited_documents={},
                background_info=background_info_string,
            )
        ],
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="search",
                node_start_time=node_start_time,
            )
        ],
    )
