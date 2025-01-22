from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from onyx.agents.agent_search.deep_search_a.main.operations import logger
from onyx.agents.agent_search.deep_search_a.main.states import MainState
from onyx.agents.agent_search.deep_search_a.main.states import RoutingDecision
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    build_history_prompt,
)
from onyx.agents.agent_search.shared_graph_utils.prompts import AGENT_DECISION_PROMPT
from onyx.agents.agent_search.shared_graph_utils.prompts import (
    AGENT_DECISION_PROMPT_AFTER_SEARCH,
)
from onyx.context.search.models import InferenceSection
from onyx.db.engine import get_session_context_manager
from onyx.llm.utils import check_number_of_tokens
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.search.search_tool import SearchResponseSummary


def agent_path_decision(state: MainState, config: RunnableConfig) -> RoutingDecision:
    now_start = datetime.now()

    agent_a_config = cast(AgentSearchConfig, config["metadata"]["config"])
    question = agent_a_config.search_request.query
    perform_initial_search_path_decision = (
        agent_a_config.perform_initial_search_path_decision
    )

    history = build_history_prompt(config["metadata"]["config"].message_history)

    logger.debug(f"--------{now_start}--------DECIDING TO SEARCH OR GO TO LLM---")

    if perform_initial_search_path_decision:
        search_tool = agent_a_config.search_tool
        retrieved_docs: list[InferenceSection] = []

        # new db session to avoid concurrency issues
        with get_session_context_manager() as db_session:
            for tool_response in search_tool.run(
                query=question,
                force_no_rerank=True,
                alternate_db_session=db_session,
            ):
                # get retrieved docs to send to the rest of the graph
                if tool_response.id == SEARCH_RESPONSE_SUMMARY_ID:
                    response = cast(SearchResponseSummary, tool_response.response)
                    retrieved_docs = response.top_sections
                    break

        sample_doc_str = "\n\n".join(
            [doc.combined_content for _, doc in enumerate(retrieved_docs[:3])]
        )

        agent_decision_prompt = AGENT_DECISION_PROMPT_AFTER_SEARCH.format(
            question=question, sample_doc_str=sample_doc_str, history=history
        )

    else:
        sample_doc_str = ""
        agent_decision_prompt = AGENT_DECISION_PROMPT.format(
            question=question, history=history
        )

    msg = [HumanMessage(content=agent_decision_prompt)]

    # Get the rewritten queries in a defined format
    model = agent_a_config.fast_llm

    # no need to stream this
    resp = model.invoke(msg)

    if isinstance(resp.content, str) and "research" in resp.content.lower():
        routing = "agent_search"
    else:
        routing = "LLM"

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------DECIDING TO SEARCH OR GO TO LLM END---"
    )

    check_number_of_tokens(agent_decision_prompt)

    return RoutingDecision(
        # Decide which route to take
        routing=routing,
        sample_doc_str=sample_doc_str,
        log_messages=[
            f"{now_start} -- Path decision: {routing},  Time taken: {now_end - now_start}"
        ],
    )
